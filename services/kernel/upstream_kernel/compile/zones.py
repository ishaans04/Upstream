"""Receptor zones: the places where people and animals actually meet the water.

A zone only counts if it is stream-adjacent. A park 800 m from the water is not an
exposure pathway, and including it would put probability mass on arrivals that
cannot happen.
"""
from __future__ import annotations

import geopandas as gpd
import numpy as np
import osmnx as ox
import pandas as pd

ZONE_TAGS = {"leisure": ["park", "playground", "dog_park", "nature_reserve"],
             "landuse": ["allotments", "recreation_ground"]}
PATHWAY_BY_TAG = {"playground": ["recreation"], "park": ["recreation", "animal_contact"],
                  "dog_park": ["animal_contact"], "allotments": ["irrigation"],
                  "nature_reserve": ["recreation"], "recreation_ground": ["recreation"]}
BUFFER_M = 150      # a zone is "exposed" via the stream node within this distance


def build_zones(boundary_path: str, overrides_path: str, nodes_gdf) -> gpd.GeoDataFrame:
    boundary = gpd.read_file(boundary_path).union_all()
    feats = ox.features_from_polygon(boundary, ZONE_TAGS)
    feats = feats[feats.geometry.geom_type.isin(["Polygon", "MultiPolygon"])]
    metric = nodes_gdf.estimate_utm_crs()
    nodes_m = nodes_gdf.to_crs(metric)
    rows = []
    for i, (_, f) in enumerate(feats.iterrows()):
        poly = f.geometry if f.geometry.geom_type == "Polygon" else f.geometry.convex_hull
        centroid = gpd.GeoSeries([poly.centroid], crs=4326).to_crs(metric).iloc[0]
        d = nodes_m.distance(centroid)
        if d.min() > BUFFER_M:
            continue                       # not stream-adjacent: not a receptor zone
        tag = _first_str(f.get("leisure"), f.get("landuse")) or "zone"
        # pandas returns NaN, not None, for a missing tag - and NaN is truthy, so a
        # plain `f.get("name") or fallback` would carry the NaN straight into a
        # NOT NULL column.
        rows.append({"zone_id": f"ZONE_{i:03d}",
                     "node_id": nodes_gdf.loc[d.idxmin(), "node_id"],
                     "name": _first_str(f.get("name")) or f"{tag} {i}",
                     "pathways": PATHWAY_BY_TAG.get(tag, ["recreation"]),
                     "population_upper_bound": 200, "geometry": poly})
    zones = gpd.GeoDataFrame(rows, columns=["zone_id", "node_id", "name", "pathways",
                                            "population_upper_bound", "geometry"],
                             crs="EPSG:4326")
    overrides = _read_overrides(overrides_path, nodes_gdf, metric)
    if overrides is not None and not overrides.empty:
        zones = gpd.GeoDataFrame(pd.concat([zones, overrides], ignore_index=True),
                                 crs="EPSG:4326")
    return zones.reset_index(drop=True)


def _first_str(*values) -> str | None:
    """First value that is a non-empty, non-NaN string."""
    for v in values:
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _read_overrides(path: str, nodes_gdf, metric):
    """Hand-added zones. Unlike the OSM pass these are kept even if far from the
    stream, but they still need a node_id, so snap any that omit one.
    """
    try:
        ov = gpd.read_file(path)
    except Exception:
        return None
    if ov.empty:
        return None
    if "node_id" not in ov.columns:
        ov["node_id"] = None
    nodes_m = nodes_gdf.to_crs(metric)
    missing = ov["node_id"].isna() | (ov["node_id"] == "")
    if missing.any():
        # Reproject before taking centroids: a centroid computed in degrees is wrong.
        cents = ov.loc[missing, "geometry"].to_crs(metric).centroid
        ov.loc[missing, "node_id"] = [
            nodes_gdf.loc[nodes_m.distance(c).idxmin(), "node_id"] for c in cents]
    if "pathways" in ov.columns:
        ov["pathways"] = ov["pathways"].apply(_as_pathway_list)
    return ov


def _as_pathway_list(p) -> list[str]:
    """Normalise the `pathways` property to a list of strings.

    A GeoJSON array property comes back as a numpy array from pyogrio, not a list,
    so an `isinstance(p, list)` check alone silently falls through to the string
    branch and yields one bogus pathway like "['recreation' 'animal_contact']".
    """
    if p is None:
        return []
    if isinstance(p, str):
        return [s.strip() for s in p.split(",") if s.strip()]
    if isinstance(p, list | tuple | np.ndarray | pd.Series):
        return [str(s).strip() for s in p if str(s).strip()]
    return [str(p).strip()]
