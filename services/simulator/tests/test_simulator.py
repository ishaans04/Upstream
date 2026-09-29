"""Task 9.1: the simulator, its hidden truth, and whether its world is realistic.

Two kinds of test. The ones marked integration write a scenario through the real
log and check GC-10 from the kernel's own credential. The rest run the generator
in memory and check that the world it produces has the properties PRD 15.1 asks
for -- because a benchmark against an unrealistic world measures nothing.
"""
import datetime as dt

import numpy as np
import psycopg
import pytest
from upstream_sim.citizens import DETECTION, distance_to_nearest_zone_m
from upstream_sim.clinical import excess_cases, measure_report
from upstream_sim.run import build_run
from upstream_sim.scenario import sample_scenario
from upstream_sim.transport_truth import truth_plume

ANCHOR = dt.datetime(2026, 9, 22, 14, 0, tzinfo=dt.UTC)


@pytest.fixture(scope="module")
def many_runs(net):
    rng = np.random.default_rng(3)
    return [build_run(net, sample_scenario(net, rng, now=ANCHOR), n_citizens=60, now=ANCHOR)
            for _ in range(40)]


# --- GC-10: the truth is written, and hidden --------------------------------


@pytest.mark.integration
def test_ground_truth_is_written_to_the_isolated_schema(written, owner_conn):
    row = owner_conn.execute(
        "SELECT true_entry_node, true_duration_s, true_zone_arrivals "
        "FROM sim_truth.injected_events WHERE run_id=%s", (written["run_id"],)).fetchone()
    assert row[0] == written["scenario"].entry_node
    assert row[1] == written["scenario"].duration_s
    assert set(row[2]) == set(written["zone_arrivals"])


@pytest.mark.integration
def test_kernel_cannot_read_ground_truth(kernel_conn):
    """GC-10, tested from the kernel's own credential."""
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        kernel_conn.execute("SELECT * FROM sim_truth.injected_events")


@pytest.mark.integration
def test_kernel_cannot_even_list_what_the_truth_schema_holds(kernel_conn):
    """No USAGE on the schema: the table is not merely unreadable, it is unreachable."""
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        kernel_conn.execute("SELECT count(*) FROM sim_truth.injected_events")
    usage = kernel_conn.execute(
        "SELECT has_schema_privilege('sim_truth', 'USAGE')").fetchone()[0]
    assert usage is False


@pytest.mark.integration
def test_sim_events_use_the_sim_stream_and_never_the_live_one(written, owner_conn):
    rows = owner_conn.execute("SELECT DISTINCT stream FROM events WHERE catchment_id=%s",
                              (written["catchment"],)).fetchall()
    assert rows == [("sim",)]


@pytest.mark.integration
def test_every_event_was_written_in_the_order_it_would_have_been_learned(written, owner_conn):
    times = [r[0] for r in owner_conn.execute(
        "SELECT event_time FROM events WHERE catchment_id=%s ORDER BY seq",
        (written["catchment"],)).fetchall()]
    assert len(times) == len(written["events"]) > 0
    assert times == sorted(times)


@pytest.mark.integration
def test_no_event_carries_the_truth(written, owner_conn):
    """The concentration a report was generated from must not ride along into the log."""
    payloads = [r[0] for r in owner_conn.execute(
        "SELECT payload FROM events WHERE catchment_id=%s", (written["catchment"],)).fetchall()]
    assert payloads and not any("true_concentration" in p for p in payloads)


@pytest.mark.integration
def test_the_weather_is_written_where_the_kernel_reads_it(written, owner_conn):
    conds = {r[0] for r in owner_conn.execute(
        "SELECT flow_condition FROM rainfall WHERE catchment_id=%s AND stream='sim'",
        (written["catchment"],)).fetchall()}
    assert conds == {written["scenario"].flow_condition}


@pytest.mark.integration
def test_clinical_counts_go_out_as_measure_reports(written):
    """Over the health zone's HTTP boundary, as a health system would send them."""
    assert written["posted"], "no MeasureReport was produced"
    assert all(r["resourceType"] == "MeasureReport" and r["type"] == "summary"
               for r in written["posted"])


# --- Is the world realistic? (PRD 15.1) ---------------------------------------


def test_citizen_reports_are_biased_towards_paths_and_parks(net, many_runs):
    near = distance_to_nearest_zone_m(net) <= 150
    reports = [r for run in many_runs for r in run["reports"]]
    near_share = np.mean([near[net.node_index[r["node_id"]]] for r in reports])
    assert near_share > 0.5
    assert near_share > 2 * near.mean()          # far above where nodes happen to be


def test_simulator_generates_negative_reports_too(many_runs):
    results = {r["result"] for run in many_runs for r in run["reports"]}
    assert results == {"positive", "negative"}


def test_detection_follows_the_configured_detection_curve(many_runs):
    """Reports in strong plume are positive far more often than reports in clean water,
    and clean water produces positives at about the false-positive rate."""
    reports = [r for run in many_runs for r in run["reports"]]
    strong = [r["result"] == "positive" for r in reports if r["true_concentration"] > 0.5]
    clean = [r["result"] == "positive" for r in reports if r["true_concentration"] < 1e-3]
    assert len(strong) >= 10 and len(clean) >= 500
    assert np.mean(strong) > 0.5
    fp = DETECTION["citizen_visual_olfactory"].false_positive
    assert np.mean(clean) == pytest.approx(fp, abs=0.02)


def test_positive_rate_near_the_source_exceeds_far_downstream(net, many_runs):
    near, far = [], []
    for run in many_runs:
        plume = run["plume"]
        for r in run["reports"]:
            tau = plume.arrival_s[net.node_index[r["node_id"]]]
            if not np.isfinite(tau):
                continue
            (near if tau < 1800 else far).append(r["result"] == "positive")
    assert np.mean(near) > np.mean(far)


def test_some_lab_results_arrive_days_late(net):
    scenario = sample_scenario(net, np.random.default_rng(5), now=ANCHOR, earliest_h=80,
                               latest_h=76)
    run = build_run(net, scenario, n_citizens=0, n_labs=6, now=ANCHOR)
    delays = [(lab["reported_at"] - lab["observed_at"]) for lab in run["labs"]]
    assert any(d >= dt.timedelta(days=1) for d in delays)
    learned = [e for e in run["events"] if e.payload["method"] == "lab_ecoli"]
    assert learned and all(e.payload["unit"] == "{CFU}/(100.mL)" for e in learned)


def test_a_lab_result_not_yet_reported_is_not_yet_known(net):
    """GC-4: the system cannot hold evidence before it was reported."""
    scenario = sample_scenario(net, np.random.default_rng(5), now=ANCHOR, earliest_h=3,
                               latest_h=2)
    run = build_run(net, scenario, n_citizens=0, n_labs=6, now=ANCHOR)
    assert run["labs"] and not any(e.payload["method"] == "lab_ecoli" for e in run["events"])


def test_sensors_drop_out_sometimes(net):
    scenario = sample_scenario(net, np.random.default_rng(8), now=ANCHOR)
    run = build_run(net, scenario, n_citizens=0, n_sensors=3, now=ANCHOR)
    span = ANCHOR - (scenario.start - dt.timedelta(hours=2))
    expected = 3 * span.total_seconds() / 900
    assert 0.8 * expected < len(run["readings"]) < expected


def test_clinical_counts_carry_an_excess_shaped_by_incubation():
    exposure_start = ANCHOR.timestamp()
    days = excess_cases((exposure_start, exposure_start + 3 * 3600), 0,
                        np.random.default_rng(2), n_cases=400)
    offsets = np.array([(d - ANCHOR.date()).days for d in days])
    counts = np.bincount(offsets)
    assert int(np.argmax(counts)) >= 2         # nobody presents the day they swam
    assert np.percentile(offsets, 90) > 7      # the parasites' long tail is there


def test_a_small_count_is_reported_without_a_score():
    assert "measureScore" not in measure_report("ZONE_000", ANCHOR.date(), 3)["group"][0]
    assert measure_report("ZONE_000", ANCHOR.date(), 8)["group"][0]["measureScore"]["value"] == 8


def test_scenarios_follow_the_weather(net):
    """CSOs spill in storms: a storm scenario comes from a CSO far more often than a dry one."""
    if "cso" not in net.entry_source_type:
        pytest.skip("this network has no CSO")
    rng = np.random.default_rng(0)
    by_weather: dict[str, list[bool]] = {"dry": [], "storm": []}
    for _ in range(3000):
        s = sample_scenario(net, rng, now=ANCHOR)
        if s.flow_condition in by_weather:
            k = net.entry_nodes.index(s.entry_node)
            by_weather[s.flow_condition].append(net.entry_source_type[k] == "cso")
    assert np.mean(by_weather["storm"]) > 3 * np.mean(by_weather["dry"])


def test_the_truth_is_not_the_kernels_own_physics(net):
    """If the simulator's arrival times were the kernel's, the benchmark would be circular."""
    from upstream_kernel.physics.params import FLOW_CONDITIONS, default_params
    from upstream_kernel.physics.tables import build_tables

    tables = build_tables(net, default_params())
    rng = np.random.default_rng(4)
    ratios = []
    for _ in range(20):
        s = sample_scenario(net, rng, now=ANCHOR)
        plume = truth_plume(net, s, np.random.default_rng(s.seed))
        k = net.entry_nodes.index(s.entry_node)
        tau = tables.tau[FLOW_CONDITIONS.index(s.flow_condition), k]
        both = np.isfinite(tau) & np.isfinite(plume.arrival_s) & (tau > 600)
        ratios += list(plume.arrival_s[both] / tau[both])
    ratios = np.array(ratios)
    assert not np.allclose(ratios, 1.0, atol=0.02)       # not the same numbers
    assert 0.7 < np.median(ratios) < 1.4                  # but the same world


def test_same_seed_reproduces_the_same_event_sequence(net):
    a = build_run(net, sample_scenario(net, np.random.default_rng(7), now=ANCHOR),
                  n_citizens=30, n_sensors=1, now=ANCHOR)
    b = build_run(net, sample_scenario(net, np.random.default_rng(7), now=ANCHOR),
                  n_citizens=30, n_sensors=1, now=ANCHOR)
    assert [e.payload for e in a["events"]] == [e.payload for e in b["events"]]
    assert [e.event_time for e in a["events"]] == [e.event_time for e in b["events"]]
