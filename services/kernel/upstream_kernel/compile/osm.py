"""Fetch the stream network and footpaths for one catchment from OpenStreetMap.

No API key: OSMnx uses the public Overpass API. Results are cached under
data/artifacts/osm-cache so a rebuild is offline and reproducible (GC-6).
"""
from __future__ import annotations

import json
import os

import geopandas as gpd
import osmnx as ox
import rustworkx as rx
from shapely.geometry import LineString, Point

ox.settings.use_cache = True
ox.settings.cache_folder = "data/artifacts/osm-cache"

WATERWAY_TAGS = {"waterway": ["river", "stream", "ditch", "drain", "canal"]}
FOOTPATH_FILTER = '["highway"~"footway|path|pedestrian|residential|living_street|cycleway"]'

ORIENTATION_OVERRIDES = "data/catchment/edge_orientation_overrides.json"


def fetch_waterways(boundary_path: str) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    boundary = gpd.read_file(boundary_path).union_all()
    ways = ox.features_from_polygon(boundary, WATERWAY_TAGS)
    ways = ways[ways.geometry.geom_type == "LineString"].reset_index(drop=True)
    if ways.empty:
        raise ValueError(f"no OSM waterways inside {boundary_path}")

    metric = ways.estimate_utm_crs()
    nodes: dict[tuple[float, float], str] = {}
    rows = []
    for geom in ways.geometry:
        coords = list(geom.coords)
        for a, b in zip(coords[:-1], coords[1:], strict=True):
            fa, fb = _node_id(nodes, a), _node_id(nodes, b)
            if fa == fb:
                continue
            seg = LineString([a, b])
            length = gpd.GeoSeries([seg], crs=4326).to_crs(metric).length.iloc[0]
            if length < 1.0:
                continue
            rows.append({"edge_id": f"e{len(rows)}", "from_node": fa, "to_node": fb,
                         "length_m": float(length), "mean_flow_m3s": 0.05, "geometry": seg})
    edges = gpd.GeoDataFrame(rows, crs="EPSG:4326")
    nodes_gdf = gpd.GeoDataFrame(
        {"node_id": list(nodes.values()),
         "node_type": ["reach_point"] * len(nodes),
         "geometry": [Point(c) for c in nodes]}, crs="EPSG:4326")
    edges = _orient_downhill(nodes_gdf, edges)
    edges = _break_cycles(nodes_gdf, edges)
    edges = _keep_single_outflow(edges)
    return nodes_gdf, edges


def _node_id(nodes: dict, c: tuple[float, float]) -> str:
    key = (round(c[0], 7), round(c[1], 7))
    if key not in nodes:
        nodes[key] = f"N{len(nodes):05d}"
    return nodes[key]


def _orient_downhill(nodes_gdf, edges):
    """OSM waterway ways are digitised downstream by convention, and the MVP relies on
    that (documented assumption, PRD R4).

    No elevation pipeline: if the console map shows obviously reversed reaches, list
    their edge ids in data/catchment/edge_orientation_overrides.json and they are
    flipped here.
    """
    if not os.path.exists(ORIENTATION_OVERRIDES):
        return edges
    with open(ORIENTATION_OVERRIDES, encoding="utf-8") as fh:
        flip = set(json.load(fh).get("flip_edge_ids", []))
    if not flip:
        return edges
    mask = edges["edge_id"].isin(flip)
    edges.loc[mask, ["from_node", "to_node"]] = edges.loc[mask, ["to_node", "from_node"]].values
    edges.loc[mask, "geometry"] = edges.loc[mask, "geometry"].apply(
        lambda g: LineString(list(g.coords)[::-1]))
    return edges


def _break_cycles(nodes_gdf, edges):
    """Braided channels and mapping errors create cycles. Drop the longest edge in each
    cycle and record it, so the compiler's DAG assumption holds.
    """
    idx = {n: i for i, n in enumerate(nodes_gdf["node_id"])}
    while True:
        edges = edges.reset_index(drop=True)
        g = rx.PyDiGraph()
        g.add_nodes_from(range(len(idx)))
        g.add_edges_from([(idx[f], idx[t], i) for i, (f, t)
                          in enumerate(zip(edges["from_node"], edges["to_node"], strict=True))])
        cyc = next(iter(rx.simple_cycles(g)), None)
        if cyc is None:
            return edges
        cyc = set(cyc)
        members = [i for i, (f, t)
                   in enumerate(zip(edges["from_node"], edges["to_node"], strict=True))
                   if idx[f] in cyc and idx[t] in cyc]
        # reset_index above makes positional and label indices identical, so idxmax
        # on the label index selects the right row.
        edges = edges.drop(index=edges.loc[members, "length_m"].idxmax())


def _keep_single_outflow(edges):
    """The compiler assumes a tree: at most one outgoing edge per node
    (`downstream_path` walks a single successor). OSM distributaries and
    digitisation artefacts break that, so keep the highest-flow outgoing edge and
    drop the rest.
    """
    edges = edges.reset_index(drop=True)
    keep = (edges.sort_values(["mean_flow_m3s", "length_m"], ascending=[False, False])
                 .groupby("from_node", sort=False)
                 .head(1).index)
    return edges.loc[sorted(keep)].reset_index(drop=True)


FOOTPATH_BUFFER_DEG = 0.006          # roughly 500 m


def fetch_footpaths(boundary_path: str, nodes_gdf=None) -> gpd.GeoDataFrame:
    """Footpaths covering everywhere a mission could be sent.

    The catchment boundary is a corridor, but OSM waterways are returned whole: a reach
    that crosses the boundary is kept entire, so stream nodes end up outside it. Fetching
    footpaths over the bare boundary therefore leaves parts of the network with no path
    within kilometres - measured at 3.1 km for the eastern headwater outfall, which made
    PROBE's walking times meaningless and silently excluded those candidates from every
    assignment.

    So the fetch covers the boundary *and* the extent of the compiled stream nodes,
    buffered.
    """
    area = gpd.read_file(boundary_path).union_all()
    if nodes_gdf is not None and len(nodes_gdf):
        area = area.union(nodes_gdf.union_all().convex_hull)
    area = area.buffer(FOOTPATH_BUFFER_DEG)
    g = ox.graph_from_polygon(area, custom_filter=FOOTPATH_FILTER, simplify=True)
    _, e = ox.graph_to_gdfs(g)
    return e.reset_index()[["u", "v", "length", "geometry"]]
