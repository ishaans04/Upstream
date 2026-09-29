"""Task 9.2: the metrics, checked on rows whose right answer is obvious by hand.

A metric that is wrong makes every number in the README wrong at once, and the
benchmark itself cannot notice. So each one is tested here against a case small
enough to work out on paper.
"""
import datetime as dt
import os

import numpy as np
import pytest
from upstream_bench.baselines import (
    SAMPLERS,
    SamplerState,
    fixed_schedule_sampler,
    heuristic_weight_sampler,
    nearest_upstream_baseline,
    random_sampler,
)
from upstream_bench.metrics import (
    calibration_error,
    detection_delay,
    evidence_to_posterior_latency,
    false_episode_rate,
    reliability_curve,
    samples_to_localise,
    top_k_accuracy,
    window_coverage,
)
from upstream_bench.runner import TARGETS, _covered, check_targets


def r(truth="O14", ranked=("O9", "O14", "O3"), n_obs=5, p=0.5, correct=None):
    correct = ranked[0] == truth if correct is None else correct
    return {"states": [{"n_obs": n_obs, "truth": truth, "ranked": list(ranked),
                        "baseline": list(ranked), "stated_probability": p,
                        "was_correct": correct}]}


# --- G1 ----------------------------------------------------------------------


def test_top_k_accuracy_counts_a_hit_when_truth_is_in_the_top_k():
    assert top_k_accuracy([r(truth="O14", ranked=["O9", "O14", "O3"])], k=3) == 1.0
    assert top_k_accuracy([r(truth="O14", ranked=["O9", "O3", "O7"])], k=3) == 0.0


def test_top_1_is_stricter_than_top_3():
    rows = [r(truth="O14", ranked=["O9", "O14", "O3"])]
    assert top_k_accuracy(rows, k=1) == 0.0 and top_k_accuracy(rows, k=3) == 1.0


def test_accuracy_is_read_at_the_requested_number_of_observations():
    rows = [{"states": r(ranked=["O14", "O9", "O3"], n_obs=1)["states"]
             + r(ranked=["O9", "O3", "O7"], n_obs=5)["states"]}]
    assert top_k_accuracy(rows, 1, n_obs=1) == 1.0
    assert top_k_accuracy(rows, 1, n_obs=5) == 0.0


# --- G3 ----------------------------------------------------------------------


def test_samples_to_localise_returns_none_when_never_localised():
    assert samples_to_localise({"truth": "O14", "top_curve": ["O14"] * 3,
                                "confidence_curve": [0.2, 0.3, 0.4]}) is None


def test_samples_to_localise_counts_samples_not_states():
    """The first entry is the belief before any sample was taken."""
    curve = {"truth": "O14", "top_curve": ["O9", "O14", "O14"],
             "confidence_curve": [0.3, 0.6, 0.85]}
    assert samples_to_localise(curve) == 2


def test_confidently_wrong_is_a_failure_not_a_success():
    curve = {"truth": "O14", "top_curve": ["O9", "O9"], "confidence_curve": [0.3, 0.9]}
    assert samples_to_localise(curve) is None


# --- G2 ----------------------------------------------------------------------


def test_window_coverage_is_the_fraction_of_true_arrivals_inside_the_window():
    inside, outside = {"covered": 1.0}, {"covered": 0.0}
    assert window_coverage([{"windows": [inside, inside, outside, inside]}]) == \
        pytest.approx(0.75)


def test_covered_is_the_overlap_share_of_the_true_interval():
    truth = {"first": 100.0, "last": 200.0}
    assert _covered(truth, (100.0, 200.0)) == 1.0
    assert _covered(truth, (150.0, 400.0)) == pytest.approx(0.5)
    assert _covered(truth, (300.0, 400.0)) == 0.0
    assert _covered(truth, (None, None)) == 0.0          # no window at all


def test_an_instantaneous_exposure_is_covered_or_not():
    assert _covered({"first": 5.0, "last": 5.0}, (0.0, 10.0)) == 1.0
    assert _covered({"first": 50.0, "last": 50.0}, (0.0, 10.0)) == 0.0


# --- Calibration --------------------------------------------------------------


def test_calibration_error_is_zero_for_a_perfectly_calibrated_set():
    rng = np.random.default_rng(0)
    rows = []
    for p in np.linspace(0.05, 0.95, 10):
        for _ in range(4000):
            rows.append(r(p=float(p), correct=bool(rng.random() < p)))
    assert calibration_error(rows) < 0.01


def test_calibration_error_sees_overconfidence():
    rows = [r(p=0.9, correct=i % 2 == 0) for i in range(100)]       # says 90%, right 50%
    assert calibration_error(rows) == pytest.approx(0.4, abs=0.01)


def test_the_reliability_curve_reports_each_occupied_bin():
    rows = [r(p=0.15, correct=False), r(p=0.85, correct=True)]
    curve = reliability_curve(rows)
    assert [(round(x, 2), y, n) for x, y, n in curve] == [(0.15, 0.0, 1), (0.85, 1.0, 1)]


# --- G5, false episodes, latency -----------------------------------------------


def test_detection_delay_is_the_mean_over_scenarios_with_a_result():
    rows = [{"delay_matched": 3}, {"delay_matched": 5}, {"delay_matched": None}]
    assert detection_delay(rows) == 4.0


def test_false_episode_rate_is_per_catchment_month():
    days = [{"suspected": i < 2} for i in range(60)]              # 2 in 60 days
    assert false_episode_rate(days) == pytest.approx(1.0)


def test_latency_reports_p50_and_p95():
    lat = evidence_to_posterior_latency([{"latency_s": list(np.arange(1, 101) / 100)}])
    assert set(lat) == {"p50", "p95"}
    assert lat["p95"] == pytest.approx(0.95, abs=0.01)


# --- The gate (FR-45) -----------------------------------------------------------


def _summary(**over):
    s = {"calibration_error": 0.03, "latency": {"p95": 2.0},
         "top3_accuracy_after_5_obs": 0.9, "sample_reduction_vs_best_baseline": 0.3,
         "window_coverage": 0.8}
    s.update(over)
    return s


def test_the_gate_passes_a_calibrated_run():
    assert check_targets(_summary(), TARGETS, _summary()) == []


def test_the_gate_blocks_a_calibration_regression():
    fails = check_targets(_summary(calibration_error=0.12), TARGETS, _summary())
    assert any("calibration" in f for f in fails)


def test_the_gate_blocks_a_window_that_drifts_from_eighty_percent():
    fails = check_targets(_summary(window_coverage=0.62), TARGETS, _summary())
    assert any("window coverage" in f for f in fails)


def test_the_gate_blocks_an_accuracy_regression_but_not_noise():
    assert check_targets(_summary(top3_accuracy_after_5_obs=0.85), TARGETS, _summary()) == []
    fails = check_targets(_summary(top3_accuracy_after_5_obs=0.6), TARGETS, _summary())
    assert any("top3" in f for f in fails)


def test_with_nothing_to_compare_calibration_is_held_to_the_absolute_target():
    assert check_targets(_summary(calibration_error=0.06), TARGETS, None)
    assert check_targets(_summary(calibration_error=0.04), TARGETS, None) == []


def test_a_small_calibration_wobble_against_the_committed_run_is_not_a_regression():
    committed = _summary(calibration_error=0.07)
    assert check_targets(_summary(calibration_error=0.08), TARGETS, committed) == []


def test_the_gate_blocks_a_latency_regression():
    assert check_targets(_summary(latency={"p95": 7.5}), TARGETS, _summary())


# --- Baselines, on the real network ---------------------------------------------


# The committed catchment network, not whatever data/artifacts holds: CI compiles a
# synthetic line there, and these tests are about the real catchment.
REAL_NETWORK = os.environ.get("SIM_TEST_NETWORK", "bench/fixtures/network.npz")


@pytest.fixture(scope="module")
def kernel_parts():
    from upstream_kernel.compile.loader import load_network
    from upstream_kernel.physics.params import default_params
    from upstream_kernel.physics.tables import build_tables

    net = load_network(REAL_NETWORK)
    return net, build_tables(net, default_params())


def _report_below(net, tables, k: int) -> dict:
    """A positive report at a node the entry k drains to, some way downstream."""
    reach = np.flatnonzero(tables.reachable[1, k] & (tables.tau[1, k] > 300))
    node = int(reach[len(reach) // 2])
    return {"node_id": net.node_ids[node], "result": "positive",
            "observed_at": dt.datetime(2026, 9, 22, 12, tzinfo=dt.UTC)}


def test_nearest_upstream_baseline_picks_the_nearest_entry_above_the_report(kernel_parts):
    net, tables = kernel_parts
    for k in range(len(net.entry_nodes)):
        report = _report_below(net, tables, k)
        ranked = nearest_upstream_baseline([report], net, tables)
        node = net.node_index[report["node_id"]]
        above = [e for j, e in enumerate(net.entry_nodes) if tables.reachable[1, j, node]]
        nearest = min(above, key=lambda e: tables.tau[1, net.entry_nodes.index(e), node])
        assert ranked[0] == nearest
        assert sorted(ranked) == sorted(net.entry_nodes)     # a complete ranking


def test_with_no_positive_the_baseline_falls_back_to_the_usual_suspect(kernel_parts):
    net, tables = kernel_parts
    ranked = nearest_upstream_baseline([{"node_id": net.node_ids[0], "result": "negative"}],
                                       net, tables)
    assert ranked[0] == net.entry_nodes[int(np.argmax(net.entry_base_rate))]


def _state(net, tables, node: int, **kw) -> SamplerState:
    return SamplerState(net=net, tables=tables, flow_idx=1, trigger_node=node,
                        flow_condition="wet", **kw)


def test_no_sampler_repeats_a_site(kernel_parts):
    net, tables = kernel_parts
    node = net.node_index[_report_below(net, tables, 0)["node_id"]]
    for name, sampler in SAMPLERS.items():
        state = _state(net, tables, node, rng=np.random.default_rng(1))
        for _ in range(4):
            pick = sampler(state)
            if pick is None:
                break
            assert pick not in state.sampled, name
            state.sampled.append(pick)


def test_the_random_baseline_only_samples_upstream_of_the_report(kernel_parts):
    net, tables = kernel_parts
    node = net.node_index[_report_below(net, tables, 0)["node_id"]]
    state = _state(net, tables, node, rng=np.random.default_rng(2))
    upstream = np.asarray(net.upstream_mask)[:, node]
    for _ in range(5):
        pick = random_sampler(state)
        state.sampled.append(pick)
        assert pick == node or upstream[pick]


def test_the_fixed_schedule_ignores_the_report(kernel_parts):
    net, tables = kernel_parts
    a = fixed_schedule_sampler(_state(net, tables, 0))
    b = fixed_schedule_sampler(_state(net, tables, len(net.node_ids) - 1))
    assert a == b and a in set(int(i) for i in net.entry_idx)


def test_the_heuristic_goes_to_an_outfall_above_the_report(kernel_parts):
    net, tables = kernel_parts
    node = net.node_index[_report_below(net, tables, 0)["node_id"]]
    pick = heuristic_weight_sampler(_state(net, tables, node))
    k = [int(i) for i in net.entry_idx].index(pick)
    assert tables.reachable[1, k, node]
