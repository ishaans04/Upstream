"""Graph in, arrays out.

This module is pure: geodataframes in, a frozen `CompiledNetwork` out, no I/O and no
database. That is what makes it unit-testable against a six-node toy network, and it
is also what lets `version` be content-addressed (GC-6) - identical inputs always
produce an identical hash, so a posterior fingerprint can name the exact network it
was computed against.

The index order of `node_ids` is *the* node order everywhere downstream. Every array
in this dataclass, and every array the physics and model layers build on top of it,
is indexed the same way.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

import numpy as np
import rustworkx as rx


@dataclass(frozen=True)
class CompiledNetwork:
    version: str
    catchment_id: str
    node_ids: tuple[str, ...]
    node_index: dict[str, int]
    node_type: np.ndarray
    lonlat: np.ndarray
    edges: np.ndarray
    edge_length_m: np.ndarray
    edge_mean_flow: np.ndarray
    topo_order: np.ndarray
    downstream_path: dict[int, np.ndarray]
    upstream_mask: np.ndarray
    entry_nodes: tuple[str, ...]
    entry_idx: np.ndarray
    entry_source_type: tuple[str, ...]
    entry_base_rate: np.ndarray
    zone_ids: tuple[str, ...]
    zone_node_idx: np.ndarray
    zone_pathways: tuple[tuple[str, ...], ...]
    zone_population: np.ndarray


_TYPE_CODE = {"junction": 0, "outfall": 1, "reach_point": 2, "gauge": 3}


def compile_network(nodes_gdf, edges_gdf, outfalls_gdf, zones_gdf, catchment_id: str
                    ) -> CompiledNetwork:
    node_ids = tuple(nodes_gdf["node_id"].tolist())
    node_index = {n: i for i, n in enumerate(node_ids)}
    N = len(node_ids)

    edges = np.array([[node_index[f], node_index[t]]
                      for f, t in zip(edges_gdf["from_node"], edges_gdf["to_node"])],
                     dtype=np.int32)
    length = np.asarray(edges_gdf["length_m"], dtype=np.float64)
    flow = np.asarray(edges_gdf["mean_flow_m3s"], dtype=np.float64)

    g = rx.PyDiGraph()
    g.add_nodes_from(range(N))
    g.add_edges_from([(int(a), int(b), i) for i, (a, b) in enumerate(edges)])
    try:
        topo = np.array(rx.topological_sort(g), dtype=np.int32)
    except rx.DAGHasCycle as exc:
        raise ValueError("network contains a cycle; loops are out of scope (PRD R4)") from exc

    # upstream_mask[a, b] is True iff a is strictly upstream of b. Walking in
    # topological order means every predecessor's column is already complete when
    # we reach a node, so one pass suffices.
    upstream = np.zeros((N, N), dtype=bool)
    for n in topo:
        for pred in g.predecessor_indices(int(n)):
            upstream[pred, n] = True
            upstream[:, n] |= upstream[:, pred]

    # Single-outlet assumption: each node has at most one outgoing edge (tree).
    out_edge = {int(a): i for i, (a, _) in enumerate(edges)}
    downstream_path: dict[int, np.ndarray] = {}
    for n in range(N):
        path, cur = [], n
        while cur in out_edge:
            e = out_edge[cur]
            path.append(e)
            cur = int(edges[e][1])
        downstream_path[n] = np.array(path, dtype=np.int32)

    entry_nodes = tuple(outfalls_gdf["node_id"].tolist())
    entry_idx = np.array([node_index[n] for n in entry_nodes], dtype=np.int32)
    zone_node_idx = np.array([node_index[n] for n in zones_gdf["node_id"]], dtype=np.int32)

    net_kwargs = dict(
        catchment_id=catchment_id,
        node_ids=node_ids, node_index=node_index,
        node_type=np.array([_TYPE_CODE[t] for t in nodes_gdf["node_type"]], dtype=np.int8),
        lonlat=np.array([[g_.x, g_.y] for g_ in nodes_gdf.geometry], dtype=np.float64),
        edges=edges, edge_length_m=length, edge_mean_flow=flow,
        topo_order=topo, downstream_path=downstream_path, upstream_mask=upstream,
        entry_nodes=entry_nodes, entry_idx=entry_idx,
        entry_source_type=tuple(outfalls_gdf["source_type"].tolist()),
        entry_base_rate=np.asarray(outfalls_gdf["base_rate"], dtype=np.float64),
        zone_ids=tuple(zones_gdf["zone_id"].tolist()), zone_node_idx=zone_node_idx,
        zone_pathways=tuple(tuple(p) for p in zones_gdf["pathways"]),
        zone_population=np.asarray(zones_gdf["population_upper_bound"], dtype=np.int32),
    )
    return CompiledNetwork(version=_version(net_kwargs), **net_kwargs)


def _version(k: dict) -> str:
    """Content-addressed version (GC-6): identical inputs -> identical hash.

    Floats are rounded before hashing so that a round-trip through GeoJSON or .npz
    cannot silently change the version in the last bit.
    """
    canon = json.dumps({
        "catchment": k["catchment_id"],
        "nodes": list(k["node_ids"]),
        "edges": k["edges"].tolist(),
        "length_m": [round(x, 6) for x in k["edge_length_m"].tolist()],
        "flow": [round(x, 6) for x in k["edge_mean_flow"].tolist()],
        "entries": list(k["entry_nodes"]),
        "base_rate": [round(x, 9) for x in k["entry_base_rate"].tolist()],
        "zones": list(k["zone_ids"]),
    }, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode()).hexdigest()[:16]
