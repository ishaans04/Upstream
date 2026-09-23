import datetime as dt

import numpy as np
import pytest
from fixtures_network import toy_gdfs
from upstream_kernel.compile.compiler import compile_network
from upstream_kernel.ec2 import edge_weight
from upstream_kernel.model.hypotheses import build_grid
from upstream_kernel.model.likelihood import Observation
from upstream_kernel.model.posterior import compute_posterior
from upstream_kernel.model.priors import PriorInputs
from upstream_kernel.physics.params import FLOW_CONDITIONS, default_params
from upstream_kernel.physics.tables import build_tables
from upstream_kernel.probe import decision_classes, probe
from upstream_kernel.pulse import pulse
from upstream_kernel.safety import mission_allowed
from upstream_shared.mission import ProbeMode

# Mid-morning, so the daylight gate is open and the interesting assertions are reachable.
NOW = dt.datetime(2026, 9, 22, 10, 0, tzinfo=dt.UTC)


def _build(cond="wet", obs_spec=None):
    net = compile_network(*toy_gdfs(), catchment_id="toy")
    params = default_params()
    tables = build_tables(net, params)
    grid = build_grid(net, horizon_start=NOW - dt.timedelta(hours=3), horizon_end=NOW)
    B = int((grid.horizon_end - grid.horizon_start) // grid.bin_s)
    f = FLOW_CONDITIONS.index(cond)
    pi = PriorInputs(np.full(B, f, np.int8), np.full(B, 40.0),
                     np.zeros(len(net.entry_idx), np.int32), np.zeros(len(net.entry_idx)))
    obs = obs_spec(net, grid) if obs_spec else []
    post = compute_posterior(obs, net, grid, tables, pi, params, flow_idx=f,
                             kernel_version="test", stream="sim")
    zones = pulse(post, net, tables, params)
    return dict(post=post, net=net, params=params, tables=tables, grid=grid, zones=zones,
                pi=pi, flow_idx=f, obs=obs)


def _positives(net, grid):
    t = grid.horizon_end - 1800
    return [Observation(f"p{i}", net.node_index["J9"], t, "citizen_visual_olfactory",
                        "positive", None, 0.95, None, None) for i in range(4)]


@pytest.fixture
def ctx():
    return _build("wet", _positives)


def _probe(c, **kw):
    return probe(c["post"], c["net"], c["tables"], c["params"], c["zones"], now=NOW, **kw)


def test_protect_and_enforce_group_hypotheses_differently(ctx):
    """The two modes must actually disagree about what counts as the same decision."""
    a = decision_classes(ctx["post"], ctx["net"], ctx["tables"], ctx["zones"],
                         ProbeMode.PROTECT)
    b = decision_classes(ctx["post"], ctx["net"], ctx["tables"], ctx["zones"],
                         ProbeMode.ENFORCE)
    assert not np.array_equal(a, b)


def test_candidate_windows_lie_inside_the_plausible_passage_window(ctx):
    """FR-16: only recommend observations reachable while the plume could still be passing."""
    cands = _probe(ctx)
    assert cands
    for c in cands:
        assert c["window_end"] > c["window_start"] >= NOW.timestamp()


def test_unreachable_candidates_are_dropped(ctx):
    near = {c["node_id"] for c in _probe(ctx, reachable_within_s=1800,
                                         origin_node="O14")}
    far = {c["node_id"] for c in _probe(ctx, reachable_within_s=60, origin_node="O14")}
    assert far <= near
    assert "ZB" not in far


def test_safety_blocks_missions_during_a_flood_warning(ctx):
    assert _probe(ctx, flood_warning=True) == []


def test_safety_blocks_missions_in_high_flow(ctx):
    assert _probe(ctx, flow_condition="storm") == []


def test_safety_blocks_missions_after_dark(ctx):
    night = dt.datetime(2026, 9, 22, 23, 30, tzinfo=dt.UTC)
    assert probe(ctx["post"], ctx["net"], ctx["tables"], ctx["params"], ctx["zones"],
                 now=night) == []


def test_safety_blocks_a_node_without_public_access():
    ok, why = mission_allowed(now=NOW, flow_condition="wet", flood_warning=False,
                              node_attrs={"public_access": False})
    assert not ok and "public access" in why


def test_the_first_candidate_is_the_best_single_choice(ctx):
    """Greedy returns *execution* order, which is not the same as sorted by gain.

    After each pick the distribution is conditioned on that candidate's expected
    outcome, so a later candidate's gain is measured against a different posterior and
    can exceed an earlier one's. Only the first pick is a maximum over the original
    posterior - and resorting the list would discard the adaptive-submodular
    near-optimality guarantee that makes the sequence worth following in order.
    """
    from upstream_kernel.ec2 import ec2_gain

    picks = _probe(ctx)
    assert len(picks) > 1
    post, net, tables = ctx["post"], ctx["net"], ctx["tables"]
    p = np.exp(post.log_p)
    classes = decision_classes(post, net, tables, ctx["zones"], ProbeMode.PROTECT)
    first = picks[0]
    for other in picks[1:]:
        a = ec2_gain(p, classes, _outcomes(ctx, first)) / max(first["walk_cost_s"], 1.0)
        b = ec2_gain(p, classes, _outcomes(ctx, other)) / max(other["walk_cost_s"], 1.0)
        assert a >= b - 1e-15


def _outcomes(ctx, cand):
    """Rebuild a candidate's outcome matrix the way probe() does."""
    import jax.numpy as jnp
    from upstream_kernel.model.likelihood import _detect_prob, _predicted_concentration

    params = ctx["params"]
    o = Observation("cand", ctx["net"].node_index[cand["node_id"]],
                    0.5 * (cand["window_start"] + cand["window_end"]),
                    "citizen_visual_olfactory", "positive", None,
                    params.observer_reliability_default, None, None)
    c = _predicted_concentration(o, ctx["post"].grid, ctx["tables"], ctx["post"].flow_idx,
                                 params)
    p_pos = np.asarray(_detect_prob(jnp.asarray(c),
                                    params.detection["citizen_visual_olfactory"],
                                    params.observer_reliability_default))
    return np.stack([p_pos, 1.0 - p_pos])


def test_expected_effect_is_plain_language_and_quantified(ctx):
    c = _probe(ctx)[0]
    assert "%" in c["expected_effect"]
    assert "outfalls" in c["expected_effect"] or "warning patterns" in c["expected_effect"]


def test_a_negative_outcome_at_the_top_candidate_really_would_shrink_the_posterior(ctx):
    """The promised effect must be real: simulate the negative outcome and re-run."""
    top = _probe(ctx, mode=ProbeMode.ENFORCE)[0]
    post, net, tables, params = ctx["post"], ctx["net"], ctx["tables"], ctx["params"]

    cls_before = decision_classes(post, net, tables, ctx["zones"], ProbeMode.ENFORCE)
    before = edge_weight(np.exp(post.log_p), cls_before)

    extra = Observation("probe-result", net.node_index[top["node_id"]],
                        0.5 * (top["window_start"] + top["window_end"]),
                        "citizen_visual_olfactory", "negative", None,
                        params.observer_reliability_default, None, None)
    post2 = compute_posterior(ctx["obs"] + [extra], net, ctx["grid"], tables, ctx["pi"],
                              params, flow_idx=ctx["flow_idx"], kernel_version="test",
                              stream="sim")
    cls_after = decision_classes(post2, net, tables, ctx["zones"], ProbeMode.ENFORCE)
    after = edge_weight(np.exp(post2.log_p), cls_after)
    assert after < before


def test_evidence_shrinks_the_uncertainty_probe_has_left_to_cut():
    """EC2 gain measures edge weight available to cut, so it *falls* as belief sharpens.

    This is the right way round, and worth pinning because the naive expectation is the
    opposite. An uninformed posterior is spread across many decision classes, so there
    are many edges and a test can cut a lot; once evidence has collapsed belief onto one
    class there is little left to resolve and every candidate scores low. A rising gain
    after evidence would mean the decision grouping had stopped tracking the posterior.
    """
    quiet = _build("wet")
    informed = _build("wet", _positives)

    def remaining(c):
        cls = decision_classes(c["post"], c["net"], c["tables"], c["zones"],
                               ProbeMode.PROTECT)
        return edge_weight(np.exp(c["post"].log_p), cls)

    assert remaining(informed) < remaining(quiet)
    assert max(c["ec2_gain"] for c in _probe(informed)) <         max(c["ec2_gain"] for c in _probe(quiet))


def test_gain_never_exceeds_the_uncertainty_actually_present():
    """A candidate cannot promise to cut more than the total edge weight."""
    c = _build("wet", _positives)
    cls = decision_classes(c["post"], c["net"], c["tables"], c["zones"], ProbeMode.PROTECT)
    total = edge_weight(np.exp(c["post"].log_p), cls)
    for cand in _probe(c):
        assert cand["ec2_gain"] <= total + 1e-12


def test_expected_effect_never_claims_a_zero_reduction_for_a_positive_gain(ctx):
    """Rounding a real but small gain to "0%" tells a volunteer their trip is pointless."""
    for c in _probe(ctx):
        assert c["ec2_gain"] > 0
        assert "0%" not in c["expected_effect"]
        assert "(no measurable reduction" not in c["expected_effect"]
