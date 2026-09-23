"""P(observation | hypothesis).

Each observation method has a detection curve: the chance of a positive result given the
concentration the forward model predicts at that place and time, plus a false-positive rate.
A negative observation gets 1 - that. Observer reliability shrinks the curve towards the
false-positive rate, so an unreliable observer moves the posterior less.

The negative case is where most of the work happens. "Checked the bridge, looks normal"
is not an absence of data: it is a direct statement that the plume from any hypothesis
whose predicted concentration was high there and then almost certainly did not occur
(PRD 7.2).
"""
from __future__ import annotations

from dataclasses import dataclass

import jax
import jax.numpy as jnp
import numpy as np

from ..physics.transport import concentration
from .hypotheses import KIND_DIFFUSE, KIND_NONE


@dataclass(frozen=True)
class Observation:
    event_id: str
    node_idx: int
    t_obs: float
    method: str
    result: str
    value: float | None
    observer_reliability: float
    window_start: float | None
    window_end: float | None


DIFFUSE_BACKGROUND_C = 0.12        # what a diffuse-runoff hypothesis predicts everywhere
LAB_LOG_SD = 0.8                   # lognormal spread of a lab count given concentration
LAB_SCALE = 5.0e4                  # CFU/100mL at relative concentration 1.0


def _detect_prob(c, curve, reliability: float):
    """Logistic detection on log10 concentration, shrunk towards fp by unreliability."""
    z = (jnp.log10(jnp.maximum(c, 1e-12)) - jnp.log10(curve.c50)) / curve.slope
    p = curve.false_positive + (1.0 - curve.false_positive) * jax.nn.sigmoid(z)
    return curve.false_positive + reliability * (p - curve.false_positive)


def _predicted_concentration(obs, grid, tables, flow_idx, params):
    node = obs.node_idx
    k = np.clip(grid.entry_k, 0, None)
    tau = jnp.asarray(tables.tau[flow_idx, k, node])
    sigma = jnp.asarray(tables.sigma[flow_idx, k, node])
    dil = jnp.asarray(tables.dilution[flow_idx, k, node])
    reach = jnp.asarray(tables.reachable[flow_idx, k, node])
    decay = params.decay_per_hour["fecal_indicator"] / 3600.0
    c = concentration(tau, sigma, dil, reach,
                      t0=jnp.asarray(np.nan_to_num(grid.t0)),
                      duration_s=jnp.asarray(grid.duration_s),
                      mass=jnp.asarray(grid.mass),
                      t_obs=float(obs.t_obs), decay_per_s=decay)
    c = jnp.where(jnp.asarray(grid.kind == KIND_DIFFUSE), DIFFUSE_BACKGROUND_C, c)
    return jnp.where(jnp.asarray(grid.kind == KIND_NONE), 0.0, c)


def log_likelihood(obs: Observation, grid, tables, flow_idx: int, params) -> jnp.ndarray:
    c = _predicted_concentration(obs, grid, tables, flow_idx, params)
    curve = params.detection[obs.method]
    if obs.result == "quantitative":
        mu = jnp.log(jnp.maximum(c * LAB_SCALE, 1.0))
        x = jnp.log(max(float(obs.value or 0.0), 1.0))
        return -0.5 * ((x - mu) / LAB_LOG_SD) ** 2 - jnp.log(LAB_LOG_SD)
    p = _detect_prob(c, curve, obs.observer_reliability)
    p = jnp.clip(p, 1e-6, 1 - 1e-6)
    return jnp.log(p) if obs.result == "positive" else jnp.log1p(-p)


def total_log_likelihood(observations, grid, tables, flow_idx: int, params) -> jnp.ndarray:
    acc = jnp.zeros(grid.H)
    for o in observations:
        acc = acc + log_likelihood(o, grid, tables, flow_idx, params)
    return acc
