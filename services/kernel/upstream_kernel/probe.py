"""PROBE: where should the next observation be, and who can take it? (PRD 7.5)"""
from __future__ import annotations

import datetime as dt

import jax.numpy as jnp
import numpy as np
from pyproj import Geod
from upstream_shared.mission import ProbeMode

from .ec2 import ec2_gain, greedy_select
from .model.hypotheses import KIND_DIFFUSE, KIND_NONE, KIND_POINT
from .model.likelihood import Observation, _detect_prob, _predicted_concentration
from .pulse import EXPOSURE_THRESHOLD_C
from .safety import mission_allowed

WARN_THRESHOLD = 0.20              # zone warning threshold used to define Protect classes
CANDIDATE_METHODS = ["citizen_visual_olfactory", "test_strip"]
WALK_SPEED_MPS = 1.3
MAX_PROTECT_ZONE_BITS = 16
MIN_CREDIBLE_MASS = 1e-4

_GEOD = Geod(ellps="WGS84")


def decision_classes(post, net, tables, zones, mode: ProbeMode) -> np.ndarray:
    """Group hypotheses by the decision they imply (PRD 7.5 'two modes').

    This grouping is the whole lever. EC2 scores a test by the edges it cuts *between*
    classes, so changing what a class means changes what the system considers worth
    going to look at - the same posterior yields different missions under Protect and
    Enforce without any reweighting.
    """
    g = post.grid
    if mode is ProbeMode.ENFORCE:
        # "Which outfall should be inspected": one class per entry point, plus diffuse,
        # plus none.
        cls = np.where(g.kind == KIND_POINT, g.entry_k, -1).astype(np.int64)
        cls = np.where(g.kind == KIND_DIFFUSE, len(net.entry_nodes), cls)
        cls = np.where(g.kind == KIND_NONE, len(net.entry_nodes) + 1, cls)
        return cls
    # PROTECT: "which zones need a warning" - the signature of exposed zones per
    # hypothesis. Only the top-ranked zones get a bit; beyond that a warning decision
    # would not differ, and an unbounded signature would blow up the class count.
    ranked = sorted(range(len(net.zone_ids)),
                    key=lambda z: -zones[net.zone_ids[z]]["p_peak"])[:MAX_PROTECT_ZONE_BITS]
    sig = np.zeros(g.H, dtype=np.int64)
    for bit, z in enumerate(ranked):
        sig |= _hypothesis_exposes_zone(post, net, tables, z).astype(np.int64) << bit
    return _densify(sig)


def _densify(labels: np.ndarray) -> np.ndarray:
    """Relabel to a contiguous 0..n-1 range.

    The Protect signature is a sparse bitfield, and `edge_weight` groups with
    `np.bincount`, which allocates up to max(label)+1 entries. Sixteen zone bits would
    ask for a 65k array on every scored candidate.
    """
    _, dense = np.unique(labels, return_inverse=True)
    return dense.astype(np.int64)


def _hypothesis_exposes_zone(post, net, tables, z: int) -> np.ndarray:
    """True per hypothesis if its plume would exceed the exposure threshold at that zone.

    Reachability plus enough dilution-adjusted mass to cross EXPOSURE_THRESHOLD_C - the
    same threshold PULSE uses, so PROBE and PULSE cannot disagree about what "exposed"
    means.
    """
    g = post.grid
    k = np.clip(g.entry_k, 0, None)
    node = int(net.zone_node_idx[z])
    reach = np.asarray(tables.reachable[post.flow_idx, k, node], dtype=bool)
    dil = np.asarray(tables.dilution[post.flow_idx, k, node])
    return reach & (g.kind == KIND_POINT) & (g.mass * dil > EXPOSURE_THRESHOLD_C)


def probe(post, net, tables, params, zones, *, now: dt.datetime,
          mode: ProbeMode = ProbeMode.PROTECT, max_candidates: int = 5,
          reachable_within_s: float = 1800, flood_warning: bool = False,
          flow_condition: str = "wet", origin_node: str | None = None) -> list[dict]:
    ok, _reason = mission_allowed(now=now, flow_condition=flow_condition,
                                  flood_warning=flood_warning, node_attrs={})
    if not ok:
        return []

    p = np.exp(post.log_p)
    classes = decision_classes(post, net, tables, zones, mode)
    t_now = now.timestamp()
    k = np.clip(post.grid.entry_k, 0, None)

    candidate_outcomes: dict[str, np.ndarray] = {}
    costs: dict[str, float] = {}
    meta: dict[str, dict] = {}
    origin = net.node_index[origin_node] if origin_node else None
    curve = params.detection["citizen_visual_olfactory"]

    for node_idx in range(len(net.node_ids)):
        tau = tables.tau[post.flow_idx, k, node_idx]
        arrival = post.grid.t0 + tau
        passing = (np.isfinite(arrival) & (arrival + post.grid.duration_s > t_now)
                   & (arrival < t_now + reachable_within_s))
        if not passing.any() or p[passing].sum() < MIN_CREDIBLE_MASS:
            continue                       # nothing credible could still be passing here
        cost = _walk_cost_s(net, origin, node_idx)
        if cost > reachable_within_s:
            continue
        w_lo = max(t_now, float(np.nanmin(arrival[passing])))
        w_hi = float(np.nanmax((arrival + post.grid.duration_s)[passing]))
        if w_hi <= t_now or w_hi <= w_lo:
            continue
        t_mid = 0.5 * (w_lo + w_hi)
        obs = Observation(event_id="cand", node_idx=node_idx, t_obs=t_mid,
                          method="citizen_visual_olfactory", result="positive", value=None,
                          observer_reliability=params.observer_reliability_default,
                          window_start=None, window_end=None)
        c = _predicted_concentration(obs, post.grid, tables, post.flow_idx, params)
        p_pos = np.asarray(_detect_prob(jnp.asarray(c), curve,
                                        params.observer_reliability_default))
        cid = f"{net.node_ids[node_idx]}@{int(t_mid)}"
        candidate_outcomes[cid] = np.stack([p_pos, 1.0 - p_pos])
        costs[cid] = cost
        meta[cid] = {"node_id": net.node_ids[node_idx], "window_start": w_lo,
                     "window_end": w_hi}

    picks = greedy_select(p, classes, candidate_outcomes, costs, k=max_candidates)
    out = []
    for cid, score in picks:
        gain = ec2_gain(p, classes, candidate_outcomes[cid])
        out.append({"candidate_id": cid, **meta[cid], "methods": CANDIDATE_METHODS,
                    "mode": mode.value, "ec2_gain": float(gain),
                    "gain_per_cost": float(score), "walk_cost_s": costs[cid],
                    "expected_effect": _expected_effect(p, classes,
                                                        candidate_outcomes[cid], net, mode)})
    return out


def _walk_cost_s(net, origin: int | None, node_idx: int) -> float:
    """Straight-line fallback; the Core API replaces this with pgRouting walking time."""
    if origin is None:
        return 300.0
    lon1, lat1 = net.lonlat[origin]
    lon2, lat2 = net.lonlat[node_idx]
    _, _, d = _GEOD.inv(lon1, lat1, lon2, lat2)
    return float(d) / WALK_SPEED_MPS * 1.35        # 1.35 detour factor for real paths


def _expected_effect(p, classes, outcomes, net, mode: ProbeMode) -> str:
    """The sentence the volunteer sees. Every number here is computed, never guessed.

    It has to stay honest when the effect is small. A single visual check against a
    catchment-wide posterior often cuts well under one percent of the uncertainty, and
    rounding that to "0%" tells the volunteer their trip is pointless when it is not -
    so the percentage carries enough precision to stay non-zero, and a genuinely
    marginal check says so in words instead.
    """
    before = len(np.unique(classes[p > 0.001]))
    residual = []
    for o in range(outcomes.shape[0]):
        pq = p * outcomes[o]
        residual.append(len(np.unique(classes[pq / max(pq.sum(), 1e-300) > 0.001])))
    after = int(np.mean(residual))
    total = 0.5 * (p.sum() ** 2 - float((np.bincount(classes, weights=p) ** 2).sum()))
    cut = ec2_gain(p, classes, outcomes) / max(total, 1e-12)
    noun = "suspect outfalls" if mode is ProbeMode.ENFORCE else "warning patterns"

    ruled_out = max(before - after, 0)
    if ruled_out:
        head = f"Expected to rule out about {ruled_out} of {before} {noun}"
    else:
        head = f"Narrows the {before} remaining {noun} without ruling any out yet"
    return f"{head} ({_percent(cut)} of the remaining uncertainty)."


def _percent(x: float) -> str:
    """Never render a positive quantity as 0%."""
    if x <= 0:
        return "no measurable reduction"
    for places in (0, 1, 2, 3):
        s = f"{x:.{places}%}"
        if float(s.rstrip("%")) > 0:
            return s
    return "under 0.001%"
