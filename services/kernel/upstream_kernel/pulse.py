"""PULSE: push the posterior forward to every receptor zone (PRD 7.4).

For each zone and each future time step we ask: summing over hypotheses weighted by their
posterior probability, what is the chance the concentration there exceeds the exposure
threshold? The 80% credible window is the narrowest central interval of the resulting
arrival-time distribution (GC-11).

The concentration is evaluated for the whole time grid in one broadcast rather than a
step at a time. On the real catchment that is nine zones times ~156 steps; done as
separate calls it adds well over a second to every recompute, which is budget NFR-1
cannot spare.
"""
from __future__ import annotations

import jax.numpy as jnp
import numpy as np
from upstream_shared.codes import ExposurePathway

from .model.hypotheses import KIND_DIFFUSE, KIND_NONE
from .physics.params import FLOW_CONDITIONS
from .physics.transport import concentration

EXPOSURE_THRESHOLD_C = 0.05
DIFFUSE_ZONE_C = 0.10


def pulse(post, net, tables, params, *, forward_hours: int = 12, step_s: int = 300) -> dict:
    p = np.exp(post.log_p)
    g = post.grid
    f = post.flow_idx
    decay = params.decay_per_hour["fecal_indicator"] / 3600.0
    k = np.clip(g.entry_k, 0, None)
    t_grid = np.arange(g.horizon_end - 3600, g.horizon_end + forward_hours * 3600, step_s,
                       dtype=np.float64)
    storm = FLOW_CONDITIONS[f] == "storm"

    t0 = jnp.asarray(np.nan_to_num(g.t0))
    duration = jnp.asarray(g.duration_s)
    mass = jnp.asarray(g.mass)
    t_obs = jnp.asarray(t_grid).reshape(-1, 1)          # (T, 1) broadcasts against (H,)
    is_diffuse = g.kind == KIND_DIFFUSE
    is_none = g.kind == KIND_NONE

    out: dict[str, dict] = {}
    for z, zone_id in enumerate(net.zone_ids):
        node = int(net.zone_node_idx[z])
        c = np.asarray(concentration(
            jnp.asarray(tables.tau[f, k, node]),
            jnp.asarray(tables.sigma[f, k, node]),
            jnp.asarray(tables.dilution[f, k, node]),
            jnp.asarray(tables.reachable[f, k, node]),
            t0=t0, duration_s=duration, mass=mass,
            t_obs=t_obs, decay_per_s=decay))            # (T, H)
        c = np.where(is_diffuse, DIFFUSE_ZONE_C, c)
        c = np.where(is_none, 0.0, c)
        p_exposed = (c > EXPOSURE_THRESHOLD_C) @ p      # (T,)

        lo, hi = _credible_window(t_grid, p_exposed, q=0.80)
        pathways = list(net.zone_pathways[z])
        if storm and ExposurePathway.FLOODWATER.value not in pathways:
            pathways.append(ExposurePathway.FLOODWATER.value)     # PRD 7.9 role 4
        out[zone_id] = {"zone_id": zone_id, "t_grid": t_grid.tolist(),
                        "p_exposed": p_exposed.tolist(),
                        "window_lo": lo, "window_hi": hi,
                        "p_peak": float(p_exposed.max()), "pathways": pathways}
    return out


def _credible_window(t, w, q: float = 0.80):
    """Narrowest central interval holding q of the exposure-probability mass."""
    if w.max() < EXPOSURE_THRESHOLD_C or w.sum() <= 0:
        return None, None
    c = np.cumsum(w) / w.sum()
    lo_i = int(np.searchsorted(c, (1 - q) / 2))
    hi_i = int(min(np.searchsorted(c, 1 - (1 - q) / 2), len(t) - 1))
    return float(t[lo_i]), float(t[hi_i])
