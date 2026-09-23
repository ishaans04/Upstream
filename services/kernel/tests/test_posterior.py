import datetime as dt
import time

import numpy as np
import pytest
from fixtures_network import toy_gdfs
from upstream_kernel.compile.compiler import compile_network
from upstream_kernel.fingerprint import fingerprint
from upstream_kernel.model.hypotheses import build_grid
from upstream_kernel.model.likelihood import Observation
from upstream_kernel.model.posterior import compute_posterior, source_marginals
from upstream_kernel.model.priors import PriorInputs
from upstream_kernel.physics.params import FLOW_CONDITIONS, default_params
from upstream_kernel.physics.tables import build_tables
from upstream_kernel.trace import explain


@pytest.fixture
def ctx():
    net = compile_network(*toy_gdfs(), catchment_id="toy")
    params = default_params(); tables = build_tables(net, params)
    end = dt.datetime(2026, 9, 22, 3, tzinfo=dt.UTC)
    grid = build_grid(net, horizon_start=end - dt.timedelta(hours=3), horizon_end=end)
    B = int((grid.horizon_end - grid.horizon_start) // grid.bin_s)
    pi = PriorInputs(np.full(B, FLOW_CONDITIONS.index("storm"), np.int8), np.full(B, 40.0),
                     np.zeros(len(net.entry_idx), np.int32), np.zeros(len(net.entry_idx)))
    return net, params, tables, grid, pi

def _obs(net, node, t, result, eid="e", method="citizen_visual_olfactory"):
    return Observation(eid, net.node_index[node], t, method, result, None, 0.9, None, None)

def _run(ctx, obs):
    net, params, tables, grid, pi = ctx
    return compute_posterior(obs, net, grid, tables, pi, params,
                             flow_idx=FLOW_CONDITIONS.index("storm"),
                             kernel_version="test-1", stream="sim")

def test_posterior_is_normalised(ctx):
    post = _run(ctx, [])
    assert float(np.exp(post.log_p).sum()) == pytest.approx(1.0, rel=1e-9)

def test_no_evidence_means_p_event_stays_at_the_prior(ctx):
    assert _run(ctx, []).p_event < 0.1

def test_one_positive_report_raises_p_event(ctx):
    net, *_ , grid, _ = ctx
    post = _run(ctx, [_obs(net, "J9", grid.horizon_end - 900, "positive")])
    assert post.p_event > _run(ctx, []).p_event

def test_negative_evidence_upstream_eliminates_that_branch(ctx):
    """PRD 10.5: volunteer at J4 reports 'looks normal' -> the O9 branch goes dark."""
    net, _, _, grid, _ = ctx
    t = grid.horizon_end - 900
    positive_only = _run(ctx, [_obs(net, "ZA", t, "positive", "a")])
    with_negative = _run(ctx, [_obs(net, "ZA", t, "positive", "a"),
                               _obs(net, "J9", t - 600, "negative", "b")])
    m0 = source_marginals(positive_only, net); m1 = source_marginals(with_negative, net)
    assert m1["O9"] < m0["O9"]

def test_marginals_sum_to_one_including_special_hypotheses(ctx):
    m = source_marginals(_run(ctx, []), net=ctx[0])
    assert sum(m.values()) == pytest.approx(1.0, rel=1e-9)
    assert "__diffuse__" in m and "__none__" in m

def test_recompute_is_order_independent(ctx):
    """GC-6: recompute from the full set; late and out-of-order data is not special."""
    net, _, _, grid, _ = ctx
    a = _obs(net, "ZA", grid.horizon_end - 900, "positive", "a")
    b = _obs(net, "J9", grid.horizon_end - 1500, "negative", "b")
    assert np.allclose(_run(ctx, [a, b]).log_p, _run(ctx, [b, a]).log_p, atol=1e-12)

def test_fingerprint_is_reproducible_and_input_sensitive():
    kw = dict(network_version="n1", params_version="p1", kernel_version="k1",
              stream="sim", horizon_start=0.0, horizon_end=3600.0)
    assert fingerprint(["a", "b"], **kw) == fingerprint(["b", "a"], **kw)   # order-insensitive
    assert fingerprint(["a"], **kw) != fingerprint(["a", "b"], **kw)
    assert fingerprint(["a"], **kw) != fingerprint(["a"], **{**kw, "kernel_version": "k2"})

def test_bitwise_reproducibility_of_the_posterior(ctx):
    net, _, _, grid, _ = ctx
    obs = [_obs(net, "ZA", grid.horizon_end - 900, "positive", "a")]
    a, b = _run(ctx, obs), _run(ctx, obs)
    assert a.fingerprint == b.fingerprint
    assert np.array_equal(a.log_p, b.log_p), "GC-6 requires bit-for-bit equality"

def test_explanation_cites_real_observations_and_computed_numbers(ctx):
    net, params, tables, grid, _ = ctx
    obs = [_obs(net, "ZA", grid.horizon_end - 900, "positive", "a"),
           _obs(net, "J9", grid.horizon_end - 1500, "negative", "b")]
    post = _run(ctx, obs)
    ex = explain(post, obs, net, grid, tables, params)
    top = ex["candidates"][0]
    assert {"entry_id", "probability", "supported_by", "eliminated_rivals_by"} <= set(top)
    assert all(s["event_id"] in {"a", "b"} for s in top["supported_by"])

@pytest.mark.slow
def test_full_scale_recompute_is_under_the_latency_budget():
    """NFR-1: evidence -> posterior p95 < 5 s, measured at PRD scale
    (40 entries x 96 bins x 3 durations ~ 11.5k hypotheses, 300 observations)."""
    from fixtures_network import line_network_gdfs
    net = compile_network(*line_network_gdfs(n_nodes=400, n_entries=40), catchment_id="big")
    params = default_params(); tables = build_tables(net, params)
    end = dt.datetime(2026, 9, 22, 6, tzinfo=dt.UTC)
    grid = build_grid(net, horizon_start=end - dt.timedelta(hours=24), horizon_end=end)
    assert 11_000 <= grid.H <= 12_000
    B = int((grid.horizon_end - grid.horizon_start) // grid.bin_s)
    pi = PriorInputs(np.zeros(B, np.int8), np.full(B, 24.0),
                     np.zeros(40, np.int32), np.zeros(40))
    rng = np.random.default_rng(1)
    obs = [_obs(net, net.node_ids[int(rng.integers(0, 400))],
                grid.horizon_end - float(rng.uniform(0, 7200)),
                "positive" if rng.random() < 0.3 else "negative", eid=f"e{i}")
           for i in range(300)]

    compute_posterior(obs, net, grid, tables, pi, params, flow_idx=0,
                      kernel_version="t", stream="sim")          # warm the JIT cache
    times = []
    for _ in range(10):
        t0 = time.perf_counter()
        compute_posterior(obs, net, grid, tables, pi, params, flow_idx=0,
                          kernel_version="t", stream="sim")
        times.append(time.perf_counter() - t0)
    assert float(np.percentile(times, 95)) < 5.0, f"p95 was {np.percentile(times,95):.2f}s"
