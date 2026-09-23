"""Exact posterior over all hypotheses. Recomputed from scratch every time (GC-6).

There is no incremental update path and that is deliberate. Recomputing from the full
evidence set means a lab result that arrives three days late, or a retraction, or an
observation that turns up out of order, needs no special handling at all - it just
changes the set the next recompute reads.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.special import logsumexp

from ..fingerprint import fingerprint as make_fingerprint
from .hypotheses import KIND_DIFFUSE, KIND_NONE, KIND_POINT
from .likelihood import total_log_likelihood
from .priors import log_prior


@dataclass(frozen=True)
class Posterior:
    log_p: np.ndarray
    p_event: float
    grid: object
    flow_idx: int
    network_version: str
    params_version: str
    kernel_version: str
    fingerprint: str


def compute_posterior(observations, net, grid, tables, prior_inputs, params, *,
                      flow_idx: int, kernel_version: str, stream: str) -> Posterior:
    lp = log_prior(net, grid, prior_inputs, params)
    if observations:
        lp = lp + np.asarray(total_log_likelihood(observations, grid, tables, flow_idx, params),
                             dtype=np.float64)
    lp = lp - logsumexp(lp)
    p_none = float(np.exp(lp[grid.kind == KIND_NONE][0]))
    return Posterior(log_p=lp, p_event=1.0 - p_none, grid=grid, flow_idx=flow_idx,
                     network_version=net.version, params_version=params.version,
                     kernel_version=kernel_version,
                     fingerprint=make_fingerprint(
                         [o.event_id for o in observations],
                         network_version=net.version, params_version=params.version,
                         kernel_version=kernel_version, stream=stream,
                         horizon_start=grid.horizon_start, horizon_end=grid.horizon_end))


def source_marginals(post: Posterior, net) -> dict[str, float]:
    """P(entry point), summed over start times and durations (PRD 7.3)."""
    p = np.exp(post.log_p)
    g = post.grid
    out = {"__diffuse__": float(p[g.kind == KIND_DIFFUSE].sum()),
           "__none__": float(p[g.kind == KIND_NONE][0])}
    pts = g.kind == KIND_POINT
    for k, entry_id in enumerate(net.entry_nodes):
        out[entry_id] = float(p[pts & (g.entry_k == k)].sum())
    return out


def start_time_credible_interval(post: Posterior, net, entry_id: str | None = None,
                                 q: float = 0.80) -> tuple[float, float]:
    """Credible interval on the event start time, for the episode's est_start_lo/hi."""
    p = np.exp(post.log_p)
    g = post.grid
    mask = g.kind == KIND_POINT
    if entry_id is not None:
        mask = mask & (g.entry_k == net.entry_nodes.index(entry_id))
    w = p[mask]
    t = g.t0[mask]
    if w.sum() <= 0:
        return (g.horizon_start, g.horizon_end)
    order = np.argsort(t)
    t, w = t[order], w[order] / w.sum()
    c = np.cumsum(w)
    lo_q, hi_q = (1 - q) / 2, 1 - (1 - q) / 2
    return (float(t[min(np.searchsorted(c, lo_q), len(t) - 1)]),
            float(t[min(np.searchsorted(c, hi_q), len(t) - 1)]))
