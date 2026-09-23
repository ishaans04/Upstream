"""Travel time, dispersion and dilution, precomputed per (flow condition, entry, node).

These tables are the whole reason the posterior can be exact: with tau/sigma/dilution
already known for every entry-node pair, evaluating ~11.5k hypotheses is an array
multiply rather than a simulation.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

import numpy as np

from .params import FLOW_CONDITIONS, ParameterSet
from .velocity import edge_flow, edge_velocity


@dataclass(frozen=True)
class TravelTimeTables:
    params_version: str
    network_version: str
    flow_conditions: tuple[str, ...]
    tau: np.ndarray        # (F, K, N) seconds
    sigma: np.ndarray      # (F, K, N) seconds
    dilution: np.ndarray   # (F, K, N)
    reachable: np.ndarray  # (F, K, N) bool


def build_tables(net, params: ParameterSet) -> TravelTimeTables:
    F, K, N = len(FLOW_CONDITIONS), len(net.entry_idx), len(net.node_ids)
    tau = np.full((F, K, N), np.inf)
    dil = np.zeros((F, K, N))
    reach = np.zeros((F, K, N), dtype=bool)

    for f, cond in enumerate(FLOW_CONDITIONS):
        v = edge_velocity(net, params, cond)                  # (E,)
        q = edge_flow(net, params, cond)                      # (E,)
        edge_time = net.edge_length_m / v                     # (E,) seconds

        # Total inflow per node, accumulated once rather than rescanned inside the
        # per-entry walk. np.add.at handles the repeated indices at a confluence.
        inflow = np.zeros(N)
        np.add.at(inflow, net.edges[:, 1], q)

        for k, entry in enumerate(net.entry_idx):
            # Walk the single downstream path from the entry node to the outlet.
            t_acc, d_acc, cur = 0.0, 1.0, int(entry)
            tau[f, k, cur] = 0.0
            dil[f, k, cur] = 1.0
            reach[f, k, cur] = True
            for e in net.downstream_path[int(entry)]:
                t_acc += edge_time[e]
                nxt = int(net.edges[e][1])
                # Dilution at a confluence: this branch's flow over the total inflow.
                d_acc *= float(q[e] / inflow[nxt]) if inflow[nxt] > 0 else 1.0
                tau[f, k, nxt] = t_acc
                dil[f, k, nxt] = d_acc
                reach[f, k, nxt] = True

    # Fickian dispersion: the plume's standard deviation grows as the square root of
    # elapsed travel time. Exactly proportional - no additive term and no floor,
    # because either one would break that relationship, and transport.py already
    # guards the sigma = 0 case at the entry node itself.
    sigma = params.dispersion_coeff * np.sqrt(np.where(np.isfinite(tau), tau, 0.0))
    return TravelTimeTables(params.version, net.version, FLOW_CONDITIONS,
                            tau, sigma, dil, reach)


def save_tables(t: TravelTimeTables, path: str) -> None:
    np.savez_compressed(path, tau=t.tau, sigma=t.sigma, dilution=t.dilution,
                        reachable=t.reachable)
    with open(path + ".json", "w", encoding="utf-8") as fh:
        json.dump({"params_version": t.params_version, "network_version": t.network_version,
                   "flow_conditions": list(t.flow_conditions)}, fh)


def load_tables(path: str) -> TravelTimeTables:
    z = np.load(path, allow_pickle=False)
    with open(path + ".json", encoding="utf-8") as fh:
        m = json.load(fh)
    return TravelTimeTables(m["params_version"], m["network_version"],
                            tuple(m["flow_conditions"]),
                            z["tau"], z["sigma"], z["dilution"], z["reachable"])
