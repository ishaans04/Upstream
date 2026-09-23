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
    post, net, params, tables, _ = strong
    z = pulse(post, net, tables, params)["ZONE_A"]
    t, p = np.array(z["t_grid"]), np.array(z["p_exposed"])
    inside = p[(t >= z["window_lo"]) & (t <= z["window_hi"])].sum()
    assert 0.78 <= inside / p.sum() <= 0.82


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
