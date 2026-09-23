"""Forward transport model: what concentration does hypothesis h predict at (node, t)?

A rectangular release of `duration_s` starting at `t0` arrives after `tau` and is smeared
by Gaussian dispersion of width `sigma`. The concentration profile is therefore the
difference of two normal CDFs, scaled by dilution, decay and released mass.

The result is a *concentration*, which is intensive. A release lasting an hour at the
same rate as one lasting five minutes reaches the same plateau, it just holds it for
longer; it is the time integral, not the height, that grows with duration. The plateau
is bounded above by `mass * dilution`, and that is the scale the DetectionCurve `c50`
values in params.py are calibrated against - which is why the duration normalisation
inside `_profile` is undone again here.
"""
from __future__ import annotations

import jax
import jax.numpy as jnp
from jax.scipy.stats import norm


@jax.jit
def _profile(t_rel, duration_s, sigma):
    lo = norm.cdf(t_rel / sigma)
    hi = norm.cdf((t_rel - duration_s) / sigma)
    return (lo - hi) / jnp.maximum(duration_s, 1.0)


def concentration(tau, sigma, dilution, reachable, *, t0, duration_s, mass,
                  t_obs: float, decay_per_s: float):
    """Relative concentration (H,) at one node and one observation time."""
    t_rel = t_obs - t0 - tau                       # time since the leading edge arrived
    safe_tau = jnp.where(jnp.isfinite(tau), tau, 0.0)
    shape = _profile(t_rel, duration_s, jnp.maximum(sigma, 1.0))
    decay = jnp.exp(-decay_per_s * safe_tau)
    c = mass * dilution * decay * shape * duration_s   # renormalise: peak ~ mass*dilution
    return jnp.where(reachable & jnp.isfinite(tau), c, 0.0)
