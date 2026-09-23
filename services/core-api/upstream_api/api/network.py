"""The catchment as GeoJSON, for the console map (FR-36, PRD R2).

Every outfall carries `is_synthetic`. All nine in this catchment are synthetic, and PRD
R2 requires that to be visible rather than buried in a caveat: a map that draws an
invented outfall exactly like a surveyed one is making a claim it cannot support.

Geometry comes from the database rather than the compiled artefact, because the artefact
keeps node coordinates but not the zone polygons or reach lines the map needs.
"""
from __future__ import annotations

from fastapi import APIRouter

from ..config import settings
from ..db import pool
from ..network import get_network

router = APIRouter(tags=["network"])


@router.get("/network/geojson")
def network_geojson(network_version: str | None = None):
    version = network_version or get_network().version
    with pool.connection() as c, c.cursor() as cur:
        return {
            "network_version": version,
            "catchment_id": settings.catchment_id,
            "nodes": _fc(cur, """
                SELECT ST_AsGeoJSON(geom), node_id, node_type, attrs
                FROM network_nodes WHERE network_version=%s AND catchment_id=%s""",
                         (version, settings.catchment_id),
                         lambda r: {"node_id": r[1], "node_type": r[2], **(r[3] or {})}),
            "edges": _fc(cur, """
                SELECT ST_AsGeoJSON(geom), edge_id, from_node, to_node, length_m,
                       mean_flow_m3s FROM network_edges WHERE network_version=%s""",
                         (version,),
                         lambda r: {"edge_id": r[1], "from_node": r[2], "to_node": r[3],
                                    "length_m": r[4], "mean_flow_m3s": r[5]}),
            "outfalls": _fc(cur, """
                SELECT ST_AsGeoJSON(n.geom), o.outfall_id, o.node_id, o.source_type,
                       o.base_rate, o.is_synthetic
                FROM outfalls o JOIN network_nodes n
                  ON n.network_version=o.network_version AND n.node_id=o.node_id
                WHERE o.network_version=%s""",
                            (version,),
                            lambda r: {"outfall_id": r[1], "node_id": r[2],
                                       "source_type": r[3], "base_rate": r[4],
                                       "is_synthetic": r[5]}),
            "zones": _fc(cur, """
                SELECT ST_AsGeoJSON(geom), zone_id, node_id, name, pathways,
                       population_upper_bound FROM receptor_zones WHERE network_version=%s""",
                         (version,),
                         lambda r: {"zone_id": r[1], "node_id": r[2], "name": r[3],
                                    "pathways": list(r[4] or []),
                                    "population_upper_bound": r[5]}),
        }


def _fc(cur, sql: str, args: tuple, props) -> dict:
    import json

    cur.execute(sql, args)
    return {"type": "FeatureCollection",
            "features": [{"type": "Feature", "geometry": json.loads(r[0]),
                          "properties": props(r)} for r in cur.fetchall()]}
