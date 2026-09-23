"""Prior over hypotheses, before any evidence.

PRD 7.2 "Prior" + PRD 7.9 roles 1 and 3. Five inputs shape it:
  1. the entry point's type-driven base rate,
  2. rainfall (CSOs spill in storms; dry-weather events mean misconnections),
  3. first flush after a dry spell (raises the diffuse-runoff hypothesis),
  4. how often this point has been implicated before (Phase 11 pooling),
  5. slow ecological indicators of chronic pressure on that reach (OAH bioassessment).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.special import logsumexp

from ..physics.params import FLOW_CONDITIONS
from .hypotheses import KIND_DIFFUSE, KIND_NONE, KIND_POINT


@dataclass(frozen=True)
class PriorInputs:
    flow_condition_by_bin: np.ndarray
    antecedent_dry_h: np.ndarray
    past_episode_count: np.ndarray
    ecology_pressure: np.ndarray


# How much each source type's base rate is multiplied in each flow condition.
_RAIN_FACTOR: dict[str, dict[str, float]] = {
    # A CSO discharging in dry weather is an incident, not a normal event, which is
    # what makes a dry-weather report point away from it so strongly (PRD 7.9 role 1,
    # converse). At the plan's 0.05 the storm/dry ratio is only 2.4 and fails the
    # stated requirement that a storm raises the CSO prior more than threefold; at
    # 0.01 it is 8.4.
    "cso":            {"dry": 0.01, "wet": 1.0, "storm": 12.0},
    "storm_outfall":  {"dry": 0.30, "wet": 1.5, "storm": 4.0},
    "misconnection":  {"dry": 1.00, "wet": 1.0, "storm": 1.0},   # constant, rain-independent
    "industrial":     {"dry": 1.00, "wet": 1.0, "storm": 1.2},
    "diffuse_runoff": {"dry": 0.20, "wet": 1.0, "storm": 3.0},
    "unknown":        {"dry": 0.50, "wet": 1.0, "storm": 2.0},
}

# Probability that nothing is happening. Deliberately constant across flow conditions.
#
# It is tempting to let a storm raise it - spills really are likelier in storms - but
# operationally that is wrong: the prior alone would then push p_event past the
# SUSPECTED threshold every time it rained, and the system would open episodes from
# weather rather than from evidence (PRD 6.3). Rainfall's job is to say *which* source,
# and it does that through _RAIN_FACTOR. Evidence decides *whether*.
P_NO_EVENT = 0.97
DIFFUSE_BASE = 0.002
FIRST_FLUSH_DRY_H = 24.0


def _event_weights(net, grid, inputs: PriorInputs, cond_idx: np.ndarray) -> np.ndarray:
    """Unnormalised weight for every event hypothesis under the given flow conditions."""
    H = grid.H
    w = np.zeros(H, dtype=np.float64)
    pts = grid.kind == KIND_POINT

    bin_of = np.zeros(H, dtype=np.int64)
    bin_of[pts] = ((grid.t0[pts] - grid.horizon_start) // grid.bin_s).astype(np.int64)
    bin_of = np.clip(bin_of, 0, len(cond_idx) - 1)

    safe_k = np.where(pts, grid.entry_k, 0)
    base = net.entry_base_rate[safe_k]
    cond = np.array(FLOW_CONDITIONS)[cond_idx[bin_of]]
    stype = np.array(net.entry_source_type)[safe_k]
    rain_mult = np.array([_RAIN_FACTOR.get(s, _RAIN_FACTOR["unknown"])[c]
                          for s, c in zip(stype, cond, strict=True)])
    history = 1.0 + 0.35 * inputs.past_episode_count[safe_k]
    ecology = 1.0 + 0.50 * inputs.ecology_pressure[safe_k]
    w[pts] = (base * rain_mult * history * ecology)[pts]

    dif = grid.kind == KIND_DIFFUSE
    storm_bins = float((cond_idx == FLOW_CONDITIONS.index("storm")).mean())
    first_flush = 1.0 + 4.0 * float((inputs.antecedent_dry_h > FIRST_FLUSH_DRY_H).mean())
    w[dif] = DIFFUSE_BASE * (0.2 + 3.0 * storm_bins) * first_flush
    return w


def log_prior(net, grid, inputs: PriorInputs, params) -> np.ndarray:
    w = _event_weights(net, grid, inputs, inputs.flow_condition_by_bin)

    total = float(w.sum())
    if total > 0:
        w *= (1.0 - P_NO_EVENT) / total
    w[grid.kind == KIND_NONE] = P_NO_EVENT

    logw = np.log(np.maximum(w, 1e-300))
    return logw - logsumexp(logw)
