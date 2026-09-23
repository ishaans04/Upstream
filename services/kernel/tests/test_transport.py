import jax.numpy as jnp
import numpy as np
import pytest
from upstream_kernel.physics.transport import concentration

BASE = dict(tau=jnp.array([600.0]), sigma=jnp.array([120.0]),
            dilution=jnp.array([0.5]), reachable=jnp.array([True]),
            duration_s=jnp.array([900.0]), mass=jnp.array([1.0]), decay_per_s=0.0)


def test_peak_concentration_is_near_arrival_time():
    t0 = jnp.array([0.0])
    grid = np.arange(0, 3000, 30.0)
    vals = [float(concentration(**BASE, t0=t0, t_obs=t)[0]) for t in grid]
    peak_t = grid[int(np.argmax(vals))]
    assert 600 <= peak_t <= 600 + 900     # between arrival and arrival+duration


def test_concentration_is_near_zero_long_before_arrival():
    assert float(concentration(**BASE, t0=jnp.array([0.0]), t_obs=0.0)[0]) < 1e-3


def test_unreachable_node_gives_zero():
    kw = dict(BASE)
    kw["reachable"] = jnp.array([False])
    assert float(concentration(**kw, t0=jnp.array([0.0]), t_obs=700.0)[0]) == 0.0


def test_dilution_scales_concentration_linearly():
    a = float(concentration(**BASE, t0=jnp.array([0.0]), t_obs=900.0)[0])
    kw = dict(BASE)
    kw["dilution"] = jnp.array([0.25])
    b = float(concentration(**kw, t0=jnp.array([0.0]), t_obs=900.0)[0])
    assert b == pytest.approx(a / 2, rel=1e-6)


def test_decay_reduces_concentration_with_travel_time():
    a = float(concentration(**BASE, t0=jnp.array([0.0]), t_obs=900.0)[0])
    kw = dict(BASE)
    kw["decay_per_s"] = 0.12 / 3600
    b = float(concentration(**kw, t0=jnp.array([0.0]), t_obs=900.0)[0])
    assert b < a


def test_longer_release_gives_a_wider_plume_at_a_bounded_peak():
    """A longer release is wider in time, not weaker.

    Concentration is an intensive quantity: a CSO discharging for an hour at the
    same rate as one discharging for five minutes produces the same concentration,
    just for longer. The plateau is bounded above by mass * dilution, which is the
    scale the DetectionCurve c50 values in params.py are calibrated against.
    """
    short = dict(BASE)
    short["duration_s"] = jnp.array([300.0])
    long_ = dict(BASE)
    long_["duration_s"] = jnp.array([3600.0])
    t0 = jnp.array([0.0])
    grid = np.arange(0, 6000, 30.0)

    c_s = np.array([float(concentration(**short, t0=t0, t_obs=t)[0]) for t in grid])
    c_l = np.array([float(concentration(**long_, t0=t0, t_obs=t)[0]) for t in grid])
    ceiling = float(BASE["mass"][0] * BASE["dilution"][0])

    # Wider: more of the time series sits above half the ceiling.
    assert (c_l > ceiling / 2).sum() > (c_s > ceiling / 2).sum()
    # Bounded: neither exceeds mass * dilution.
    assert c_s.max() <= ceiling + 1e-9
    assert c_l.max() <= ceiling + 1e-9


def test_total_delivered_mass_grows_with_release_duration():
    """Integrating concentration over time recovers the mass that went past."""
    t0 = jnp.array([0.0])
    grid = np.arange(0, 12000, 10.0)
    totals = []
    for dur in (300.0, 3600.0):
        kw = dict(BASE)
        kw["duration_s"] = jnp.array([dur])
        c = np.array([float(concentration(**kw, t0=t0, t_obs=t)[0]) for t in grid])
        totals.append(np.trapezoid(c, grid))
    assert totals[1] > totals[0]
