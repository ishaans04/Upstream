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
    "cso":            {"dry": 0.05, "wet": 1.0, "storm": 12.0},
    "storm_outfall":  {"dry": 0.30, "wet": 1.5, "storm": 4.0},
    "misconnection":  {"dry": 1.00, "wet": 1.0, "storm": 1.0},   # constant, rain-independent
    "industrial":     {"dry": 1.00, "wet": 1.0, "storm": 1.2},
    "diffuse_runoff": {"dry": 0.20, "wet": 1.0, "storm": 3.0},
    "unknown":        {"dry": 0.50, "wet": 1.0, "storm": 2.0},
}

# Probability that nothing is happening, in *dry* weather. Conditions move it: see
# the odds calculation in log_prior.
P_NO_EVENT_DRY = 0.97
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

    # The no-event prior is not a constant. Renormalising event mass to a fixed budget
    # would let the model argue only about *which* source, never that an event is more
    # likely at all - and PRD 7.9 role 1 is precisely that storms make spills likelier.
    #
    # Instead the odds of "something happened" scale with how much the conditions raise
    # the total event weight above the same grid evaluated in dry weather. Measuring
    # against the grid's own dry reference keeps this independent of how many entries,
    # bins or duration classes the grid happens to have.
    dry = np.full_like(inputs.flow_condition_by_bin, FLOW_CONDITIONS.index("dry"))
    w_dry = _event_weights(net, grid, inputs, dry)

    odds_dry = (1.0 - P_NO_EVENT_DRY) / P_NO_EVENT_DRY
    ref = float(w_dry.sum())
    odds_event = odds_dry * (float(w.sum()) / ref) if ref > 0 else odds_dry
    p_event = odds_event / (1.0 + odds_event)

    total = float(w.sum())
    if total > 0:
        w *= p_event / total
    w[grid.kind == KIND_NONE] = 1.0 - p_event

    logw = np.log(np.maximum(w, 1e-300))
    return logw - logsumexp(logw)
