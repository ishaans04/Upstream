import datetime as dt

import numpy as np
import pytest
from fixtures_network import toy_gdfs
from upstream_kernel.compile.compiler import compile_network
from upstream_kernel.model.hypotheses import build_grid
from upstream_kernel.model.likelihood import Observation
from upstream_kernel.model.posterior import compute_posterior
from upstream_kernel.model.priors import PriorInputs
from upstream_kernel.physics.params import FLOW_CONDITIONS, default_params
from upstream_kernel.physics.tables import build_tables
from upstream_kernel.pulse import pulse

END = dt.datetime(2026, 9, 22, 3, tzinfo=dt.UTC)


def _ctx(cond="wet"):
    net = compile_network(*toy_gdfs(), catchment_id="toy")
    params = default_params()
    tables = build_tables(net, params)
    grid = build_grid(net, horizon_start=END - dt.timedelta(hours=3), horizon_end=END)
    B = int((grid.horizon_end - grid.horizon_start) // grid.bin_s)
    pi = PriorInputs(np.full(B, FLOW_CONDITIONS.index(cond), np.int8), np.full(B, 40.0),
                     np.zeros(len(net.entry_idx), np.int32), np.zeros(len(net.entry_idx)))
    return net, params, tables, grid, pi, FLOW_CONDITIONS.index(cond)


def _post(obs, cond="wet"):
    net, params, tables, grid, pi, f = _ctx(cond)
    post = compute_posterior(obs, net, grid, tables, pi, params, flow_idx=f,
                             kernel_version="test", stream="sim")
    return post, net, params, tables, grid


def _o(net, node, t, result, eid, method="citizen_visual_olfactory"):
    return Observation(eid, net.node_index[node], t, method, result, None, 0.95, None, None)


def _strong_o14(cond="wet"):
    """Several consistent positives downstream of O14, so belief concentrates there."""
    net, params, tables, grid, pi, f = _ctx(cond)
    tau = float(tables.tau[f, net.entry_nodes.index("O14"), net.node_index["J9"]])
    t = grid.horizon_end - 1800
    obs = [_o(net, "J9", t, "positive", f"p{i}") for i in range(6)]
    obs += [_o(net, "O9", t - tau, "negative", "n1")]
    return _post(obs, cond)


@pytest.fixture
def strong():
    return _strong_o14()


def test_downstream_zone_window_starts_later_than_the_nearer_one(strong):
    post, net, params, tables, _ = strong
    z = pulse(post, net, tables, params)
    assert z["ZONE_A"]["window_lo"] is not None and z["ZONE_B"]["window_lo"] is not None
    assert z["ZONE_A"]["window_lo"] < z["ZONE_B"]["window_lo"]


def test_window_is_an_80_percent_credible_interval(strong):
    """GC-11: the window holds 80% of the mass, and is the narrowest one that does.

    Asserted as a property rather than a tolerance band. The interval's ends fall on
    grid steps, so the mass it holds cannot land exactly on 0.80 and the achievable
    minimum moves with the shape of the arrival curve - a fixed band like 0.78-0.82 was
    tighter than the grid can honestly deliver on a steep edge, and failed on one
    platform while passing on another. "At least 80%, and removing either end would
    drop it below 80%" pins the same thing exactly, at any resolution.
    """
    post, net, params, tables, _ = strong
    z = pulse(post, net, tables, params)["ZONE_A"]
    t, p = np.array(z["t_grid"]), np.array(z["p_exposed"])
    inside = (t >= z["window_lo"]) & (t <= z["window_hi"])
    held = p[inside].sum() / p.sum()
    assert held >= 0.80
    assert held <= 0.85, "GC-11 coverage ceiling"

    idx = np.flatnonzero(inside)
    for shrunk in (idx[1:], idx[:-1]):
        assert p[shrunk].sum() / p.sum() < 0.80, "the window is wider than it needs to be"


def test_uncertain_posterior_gives_a_wider_window_than_a_sharp_one():
    sharp_post, net, params, tables, _ = _strong_o14()
    # One weak report: the arrival-time distribution stays spread across start bins.
    flat_post, *_ = _post([_o(net, "J9", END.timestamp() - 1800, "positive", "a")])

    def width(p):
        z = pulse(p, net, tables, params)["ZONE_A"]
        return z["window_hi"] - z["window_lo"]

    assert width(flat_post) > width(sharp_post)


def test_zone_with_no_credible_exposure_returns_no_window():
    post, net, params, tables, _ = _post([])
    assert pulse(post, net, tables, params)["ZONE_A"]["window_lo"] is None


def test_pathways_come_from_zone_attributes(strong):
    post, net, params, tables, _ = strong
    assert pulse(post, net, tables, params)["ZONE_B"]["pathways"] == \
        ["animal_contact", "floodwater"]


def test_storm_flow_adds_floodwater_pathway():
    """PRD 7.9 role 4."""
    post, net, params, tables, _ = _strong_o14("storm")
    assert "floodwater" in pulse(post, net, tables, params)["ZONE_A"]["pathways"]


def test_floodwater_is_not_added_twice(strong):
    post, net, params, tables, _ = _strong_o14("storm")
    pw = pulse(post, net, tables, params)["ZONE_B"]["pathways"]
    assert pw.count("floodwater") == 1


def test_exposure_probability_never_exceeds_p_event(strong):
    """A zone cannot be more likely to be exposed than an event is to have happened."""
    post, net, params, tables, _ = strong
    for z in pulse(post, net, tables, params).values():
        assert z["p_peak"] <= post.p_event + 1e-9


def test_the_per_node_shortcut_gives_the_same_curves_as_every_hypothesis_everywhere():
    """PULSE computes each stream node once, over only the hypotheses that can reach it.

    That is an optimisation, so it must change nothing: the curve for every zone equals
    evaluating every hypothesis at that zone, the way PULSE did before (NFR-1 on a
    network with dozens of zones is what forced the shortcut).
    """
    import jax.numpy as jnp
    from upstream_kernel.model.hypotheses import KIND_DIFFUSE, KIND_NONE
    from upstream_kernel.physics.transport import concentration
    from upstream_kernel.pulse import DIFFUSE_ZONE_C, EXPOSURE_THRESHOLD_C

    post, net, params, tables, grid = _strong_o14()
    zones = pulse(post, net, tables, params)
    p = np.exp(post.log_p)
    k = np.clip(grid.entry_k, 0, None)
    f = post.flow_idx
    for z, zone_id in enumerate(net.zone_ids):
        node = int(net.zone_node_idx[z])
        t = np.asarray(zones[zone_id]["t_grid"])
        c = np.asarray(concentration(
            jnp.asarray(tables.tau[f, k, node]), jnp.asarray(tables.sigma[f, k, node]),
            jnp.asarray(tables.dilution[f, k, node]), jnp.asarray(tables.reachable[f, k, node]),
            t0=jnp.asarray(np.nan_to_num(grid.t0)), duration_s=jnp.asarray(grid.duration_s),
            mass=jnp.asarray(grid.mass), t_obs=jnp.asarray(t).reshape(-1, 1),
            decay_per_s=params.decay_per_hour["fecal_indicator"] / 3600.0))
        c = np.where(grid.kind == KIND_DIFFUSE, DIFFUSE_ZONE_C, c)
        c = np.where(grid.kind == KIND_NONE, 0.0, c)
        brute = (c > EXPOSURE_THRESHOLD_C) @ p
        assert np.allclose(zones[zone_id]["p_exposed"], brute, atol=1e-12)
