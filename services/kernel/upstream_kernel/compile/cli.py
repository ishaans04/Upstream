"""Build the compiled network + PostGIS tables, then append NetworkVersionPublished.

Usage:
    python -m upstream_kernel.compile.cli --catchment <id> --out data/artifacts/network.npz
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import uuid

import geopandas as gpd
import psycopg
import sqlalchemy as sa
from psycopg.types.json import Jsonb
from pyproj import Geod

from .compiler import compile_network
from .loader import save_network
from .osm import fetch_footpaths, fetch_waterways
from .zones import build_zones

_GEOD = Geod(ellps="WGS84")
OUTFALL_SNAP_MAX_M = 250.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--catchment", default=os.environ.get("CATCHMENT_ID"))
    ap.add_argument("--boundary", default="data/catchment/catchment.geojson")
    ap.add_argument("--outfalls", default="data/catchment/outfalls.geojson")
    ap.add_argument("--overrides", default="data/catchment/zones_overrides.geojson")
    ap.add_argument("--out", default="data/artifacts/network.npz")
    ap.add_argument("--skip-db", action="store_true",
                    help="compile and save the .npz only; do not touch PostGIS or the log")
    a = ap.parse_args()
    if not a.catchment:
        ap.error("--catchment is required (or set CATCHMENT_ID)")

    nodes, edges = fetch_waterways(a.boundary)
    outfalls = _snap_outfalls(gpd.read_file(a.outfalls), nodes)
    # Outfall points are snapped onto the stream graph and become entry nodes.
    nodes.loc[nodes["node_id"].isin(outfalls["node_id"]), "node_type"] = "outfall"
    zones = build_zones(a.boundary, a.overrides, nodes)
    net = compile_network(nodes, edges, outfalls, zones, catchment_id=a.catchment)

    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    save_network(net, a.out)

    if not a.skip_db:
        dsn = os.environ["DATABASE_URL"]
        _write_postgis(dsn, net.version, nodes, edges, outfalls, zones,
                       fetch_footpaths(a.boundary), a.catchment)
        with psycopg.connect(dsn, autocommit=True) as c, c.cursor() as cur:
            cur.execute(
                "SELECT append_event(%s,'live',%s,'NetworkVersionPublished',1,%s,%s,NULL,NULL)",
                (uuid.uuid4(), a.catchment, dt.datetime.now(dt.UTC),
                 Jsonb({"network_version": net.version, "nodes": len(net.node_ids),
                        "edges": int(net.edges.shape[0]), "entries": len(net.entry_nodes),
                        "zones": len(net.zone_ids)})))

    print(f"network_version={net.version} nodes={len(net.node_ids)} "
          f"edges={net.edges.shape[0]} entries={len(net.entry_nodes)} "
          f"zones={len(net.zone_ids)}")


def _snap_outfalls(outfalls: gpd.GeoDataFrame, nodes: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Fill each outfall's `node_id` by snapping its point onto the stream graph.

    The curated GeoJSON leaves `node_id` empty because the node ids do not exist
    until the waterways are fetched and segmented.
    """
    lons = nodes.geometry.x.to_numpy()
    lats = nodes.geometry.y.to_numpy()
    node_ids = nodes["node_id"].to_numpy()

    snapped, dists = [], []
    for pt in outfalls.geometry:
        _, _, d = _GEOD.inv([pt.x] * len(lons), [pt.y] * len(lats), lons, lats)
        i = int(d.argmin())
        if d[i] > OUTFALL_SNAP_MAX_M:
            raise ValueError(
                f"outfall at ({pt.x:.5f}, {pt.y:.5f}) is {d[i]:.0f} m from the nearest "
                f"stream node (limit {OUTFALL_SNAP_MAX_M:.0f} m) - check the coordinates")
        snapped.append(node_ids[i])
        dists.append(float(d[i]))

    outfalls = outfalls.copy()
    outfalls["node_id"] = snapped
    outfalls["snap_distance_m"] = dists
    # Two outfalls can snap to the same node; the compiler indexes entries by node,
    # so keep the first and warn rather than producing duplicate hypotheses.
    dupes = outfalls["node_id"].duplicated()
    if dupes.any():
        print(f"warning: {int(dupes.sum())} outfall(s) snapped onto an already-used node; "
              f"dropping {list(outfalls.loc[dupes, 'outfall_id'])}")
        outfalls = outfalls.loc[~dupes]
    return outfalls.reset_index(drop=True)


def _pg_array(values) -> str:
    """Render a Python sequence as a Postgres array literal.

    `to_postgis` loads via COPY, which bypasses SQLAlchemy type handling entirely,
    so a `dtype={"pathways": ARRAY(Text)}` hint is silently ignored and the list
    arrives as its Python repr. The literal has to be built here.
    """
    out = []
    for v in values:
        s = str(v).replace("\\", "\\\\").replace('"', '\\"')
        out.append(f'"{s}"')
    return "{" + ",".join(out) + "}"


def _write_postgis(dsn, version, nodes, edges, outfalls, zones, footpaths, catchment):
    """Write the four spatial tables plus footpaths.

    Column names must match migration 0002 exactly: the geometry column there is
    `geom`, not geopandas' default `geometry`.

    Re-running the compiler for the same network_version replaces that version's
    rows rather than duplicating them, so the CLI is safe to run repeatedly.
    """
    eng = sa.create_engine(dsn.replace("postgresql://", "postgresql+psycopg://"))
    with eng.begin() as conn:
        for tbl in ("network_nodes", "network_edges", "outfalls", "receptor_zones"):
            conn.execute(sa.text(f"DELETE FROM {tbl} WHERE network_version = :v"), {"v": version})
        conn.execute(sa.text("TRUNCATE footpath_edges"))

    n = (nodes[["node_id", "node_type", "geometry"]]
         .assign(network_version=version, catchment_id=catchment)
         .rename_geometry("geom"))
    n.to_postgis("network_nodes", eng, if_exists="append", index=False)

    e = (edges[["edge_id", "from_node", "to_node", "length_m", "mean_flow_m3s", "geometry"]]
         .assign(network_version=version)
         .rename_geometry("geom"))
    e.to_postgis("network_edges", eng, if_exists="append", index=False)

    o = (outfalls[["outfall_id", "node_id", "source_type", "base_rate", "is_synthetic"]]
         .assign(network_version=version))
    o.to_sql("outfalls", eng, if_exists="append", index=False)

    z = (zones[["zone_id", "node_id", "name", "pathways", "population_upper_bound", "geometry"]]
         .assign(network_version=version,
                 pathways=lambda d: d["pathways"].apply(_pg_array))
         .rename_geometry("geom"))
    z.to_postgis("receptor_zones", eng, if_exists="append", index=False)

    f = (footpaths.rename(columns={"u": "source", "v": "target", "length": "cost"})
                  .assign(reverse_cost=lambda d: d["cost"])
                  .rename_geometry("geom"))
    f[["source", "target", "cost", "reverse_cost", "geom"]].to_postgis(
        "footpath_edges", eng, if_exists="append", index=False)


if __name__ == "__main__":
    main()
