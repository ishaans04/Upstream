"""Persistence for CompiledNetwork, plus the snapping rule (FR-5).

Arrays go to a compressed .npz; everything that is a string (node ids, zone
pathways) goes to a sidecar JSON, because .npz with `allow_pickle=False` cannot
hold ragged object arrays. Loading uses `allow_pickle=False` deliberately - a
network artefact is data, and must never be able to execute code.
"""
from __future__ import annotations

import json

import numpy as np
from pyproj import Geod

from .compiler import CompiledNetwork

_GEOD = Geod(ellps="WGS84")


def save_network(net: CompiledNetwork, path: str) -> None:
    np.savez_compressed(
        path, node_type=net.node_type, lonlat=net.lonlat, edges=net.edges,
        edge_length_m=net.edge_length_m, edge_mean_flow=net.edge_mean_flow,
        topo_order=net.topo_order, upstream_mask=net.upstream_mask,
        entry_idx=net.entry_idx, entry_base_rate=net.entry_base_rate,
        zone_node_idx=net.zone_node_idx, zone_population=net.zone_population,
        **{f"dpath_{k}": v for k, v in net.downstream_path.items()})
    with open(path + ".json", "w", encoding="utf-8") as fh:
        json.dump({"version": net.version, "catchment_id": net.catchment_id,
                   "node_ids": net.node_ids, "entry_nodes": net.entry_nodes,
                   "entry_source_type": net.entry_source_type,
                   "zone_ids": net.zone_ids, "zone_pathways": net.zone_pathways}, fh)


def load_network(path: str) -> CompiledNetwork:
    z = np.load(path, allow_pickle=False)
    with open(path + ".json", encoding="utf-8") as fh:
        meta = json.load(fh)
    node_ids = tuple(meta["node_ids"])
    return CompiledNetwork(
        version=meta["version"], catchment_id=meta["catchment_id"], node_ids=node_ids,
        node_index={n: i for i, n in enumerate(node_ids)},
        node_type=z["node_type"], lonlat=z["lonlat"], edges=z["edges"],
        edge_length_m=z["edge_length_m"], edge_mean_flow=z["edge_mean_flow"],
        topo_order=z["topo_order"],
        downstream_path={int(k.split("_")[1]): z[k] for k in z.files if k.startswith("dpath_")},
        upstream_mask=z["upstream_mask"], entry_nodes=tuple(meta["entry_nodes"]),
        entry_idx=z["entry_idx"], entry_source_type=tuple(meta["entry_source_type"]),
        entry_base_rate=z["entry_base_rate"], zone_ids=tuple(meta["zone_ids"]),
        zone_node_idx=z["zone_node_idx"],
        zone_pathways=tuple(tuple(p) for p in meta["zone_pathways"]),
        zone_population=z["zone_population"])


def snap_point_to_node(net: CompiledNetwork, lon: float, lat: float, max_m: float
                       ) -> tuple[str, float]:
    """FR-5: snap an observation to the nearest network node, or reject it.

    Rejecting is the point. An observation the system cannot place on the network
    is not weak evidence, it is evidence about somewhere else, and letting it in
    would put mass on the wrong hypotheses.
    """
    lons = net.lonlat[:, 0]
    lats = net.lonlat[:, 1]
    _, _, dist = _GEOD.inv(np.full_like(lons, lon), np.full_like(lats, lat), lons, lats)
    i = int(np.argmin(dist))
    if dist[i] > max_m:
        raise ValueError(f"observation is too far from the network ({dist[i]:.0f} m > {max_m} m)")
    return net.node_ids[i], float(dist[i])
