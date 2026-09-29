"""PRD 15.2 baselines: what someone would do without Upstream.

G1 is compared with the nearest-upstream heuristic -- "the source is the outfall
just above the first bad report" -- which is what an officer does by eye.

G3 is compared with four ways of choosing where to take the next sample. Each
gets exactly what EC2 gets: the network, the trigger report, the samples taken
so far, the same safety gates and the same kernel to judge the result. Only the
choice of where to sample differs, so the comparison measures the choice.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from upstream_kernel.model.priors import _RAIN_FACTOR


def _entries_reaching(net, tables, node_idx: int, flow_idx: int) -> list[int]:
    reach = np.asarray(tables.reachable[flow_idx, :, node_idx], dtype=bool)
    return [int(k) for k in np.flatnonzero(reach)]


def nearest_upstream_baseline(evidence, net, tables, *, flow_idx: int = 1) -> list[str]:
    """Entries ranked by travel time above the first positive report, nearest first.

    Entries that cannot reach the report follow, nearest by straight line, so the
    ranking is complete and top-k is always defined. With no positive report at
    all there is nothing to be upstream of, and the ranking is by base rate --
    the officer's fallback of "the usual suspect".
    """
    positives = [e for e in evidence if e["result"] in ("positive", "quantitative")]
    if not positives:
        order = np.argsort(-np.asarray(net.entry_base_rate))
        return [net.entry_nodes[int(k)] for k in order]
    node = net.node_index[positives[0]["node_id"]]
    upstream = _entries_reaching(net, tables, node, flow_idx)
    tau = tables.tau[flow_idx, :, node]
    ranked = sorted(upstream, key=lambda k: float(tau[k]))
    rest = [k for k in range(len(net.entry_nodes)) if k not in upstream]
    lonlat = np.asarray(net.lonlat)
    rest.sort(key=lambda k: float(np.hypot(*(lonlat[int(net.entry_idx[k])] - lonlat[node]))))
    return [net.entry_nodes[k] for k in ranked + rest]


@dataclass
class SamplerState:
    """What a sampler may know when it chooses: the same for every strategy."""

    net: object
    tables: object
    flow_idx: int
    trigger_node: int
    flow_condition: str
    sampled: list[int] = field(default_factory=list)
    rng: np.random.Generator = field(default_factory=lambda: np.random.default_rng(0))


def _unsampled(state: SamplerState, candidates) -> list[int]:
    seen = set(state.sampled)
    return [int(c) for c in candidates if int(c) not in seen]


def _upstream_nodes(state: SamplerState) -> np.ndarray:
    """Nodes upstream of (or at) the trigger: where the water in the report came from."""
    mask = np.asarray(state.net.upstream_mask)[:, state.trigger_node].copy()
    mask[state.trigger_node] = True
    return np.flatnonzero(mask)


def nearest_site_sampler(state: SamplerState) -> int | None:
    """The nearest unsampled point to the report, walking outwards."""
    lonlat = np.asarray(state.net.lonlat)
    d = np.hypot(*(lonlat - lonlat[state.trigger_node]).T)
    order = _unsampled(state, np.argsort(d))
    return order[0] if order else None


def random_sampler(state: SamplerState) -> int | None:
    """A random unsampled point upstream of the report.

    Upstream, not anywhere: sampling below a report cannot find its source, and a
    baseline that did would be a strawman.
    """
    options = _unsampled(state, _upstream_nodes(state))
    return int(state.rng.choice(options)) if options else None


def fixed_schedule_sampler(state: SamplerState) -> int | None:
    """A routine inspection round: every outfall, in a fixed order, regardless of the report."""
    options = _unsampled(state, sorted(int(i) for i in state.net.entry_idx))
    return options[0] if options else None


def heuristic_weight_sampler(state: SamplerState) -> int | None:
    """An experienced officer: outfalls above the report, likeliest type for the weather first."""
    net = state.net
    upstream = set(_entries_reaching(net, state.tables, state.trigger_node, state.flow_idx))
    weight = {k: float(net.entry_base_rate[k])
              * _RAIN_FACTOR.get(net.entry_source_type[k], _RAIN_FACTOR["unknown"])
              [state.flow_condition] for k in upstream}
    ranked = sorted(upstream, key=lambda k: -weight[k])
    options = _unsampled(state, [int(net.entry_idx[k]) for k in ranked])
    return options[0] if options else None


SAMPLERS = {
    "nearest_site": nearest_site_sampler,
    "random": random_sampler,
    "fixed_schedule": fixed_schedule_sampler,
    "heuristic": heuristic_weight_sampler,
}
