"""PRD 15.3: evaluation as CI. Run N scenarios, compare with baselines, gate on targets.

    python -m upstream_bench.runner --scenarios 200 --out bench/results --charts
    python -m upstream_bench.runner --scenarios 40 --gate          # what CI runs

Each scenario is sampled on the real network, its truth computed by the
simulator's own transport, and its evidence fed to the kernel through the same
functions the worker calls -- `build_observations`, `compute_posterior`, `pulse`,
`probe` -- in-process. Nothing goes through the database: the benchmark measures
the method, and the simulator's own tests cover the path through the log.

The protocol, per scenario:

- **Trigger.** The first report of the real incident: the first positive report
  made where the true concentration was above the exposure threshold. Scenarios
  nobody noticed have no episode and are counted, not scored. False positives
  made before the trigger stay in the evidence, as the system would hold them.
- **G1.** After the trigger and the next n-1 reports, is the true source in the
  kernel's top 1 / top 3? The nearest-upstream heuristic gets the same reports.
- **G3.** From the evidence at the trigger, each strategy chooses where the next
  test strip is read, every 20 minutes, under the same safety gates. Samples until
  the kernel's top source is the true one at >= 80% given an event; confidently
  wrong, or never within the budget, is charged the budget + 1.
- **G2.** Windows are published for episodes, so they are scored where the kernel
  has one (P(event) >= the SUSPECTED threshold): at the latest such state, from the
  organic reports or after EC2's missions. For each truly exposed zone, the share
  of its true exposure interval inside PULSE's 80% window; no window = 0.
- **Calibration.** Every scored state's top source and its probability given an event.
- **G5.** An outbreak of a stated size among the most exposed zone's visitors, with
  its timing from the true exposure. Days until the matched filter (shaped by
  PULSE's curve) and a blind scan each first reject at 1%, on the same counts.
- **False episodes.** Event-free days of citizen reports: how often the posterior
  crosses the SUSPECTED and PROBABLE thresholds anyway.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import pathlib
import time

import numpy as np
from clinical_stats.baselines import fit_baseline
from clinical_stats.cluster import blind_scan
from clinical_stats.matched_filter import expected_curve, matched_filter_test
from upstream_kernel.compile.loader import load_network
from upstream_kernel.evidence_view import build_observations
from upstream_kernel.model.hypotheses import build_grid
from upstream_kernel.model.posterior import compute_posterior, source_marginals
from upstream_kernel.model.priors import PriorInputs
from upstream_kernel.physics.params import FLOW_CONDITIONS, default_params
from upstream_kernel.physics.tables import build_tables, load_tables
from upstream_kernel.probe import ProbeMode, probe
from upstream_kernel.pulse import pulse
from upstream_kernel.safety import mission_allowed
from upstream_kernel.trace import explain
from upstream_shared.codes import SEWAGE_PATHOGEN_MIX
from upstream_shared.episode import THRESHOLD_PROBABLE, THRESHOLD_SUSPECTED
from upstream_shared.events import EventEnvelope, EventType
from upstream_shared.evidence import EvidencePayload
from upstream_sim.citizens import (
    DETECTION,
    generate_citizen_reports,
    report_weights,
    sample_at,
    to_evidence,
)
from upstream_sim.clinical import area_counts, excess_cases
from upstream_sim.run import zone_arrivals
from upstream_sim.scenario import sample_scenario
from upstream_sim.transport_truth import EXPOSURE_THRESHOLD_C, truth_plume

from . import metrics
from .baselines import SAMPLERS, SamplerState, nearest_upstream_baseline

KERNEL_VERSION = "bench"
BIN_S = 900
HORIZON_H = 24
N_CITIZENS = 40
N_OBS = (1, 2, 3, 5, 8, 12)
G1_STATE = 5
SAMPLE_STEP_S = 1200
SAMPLE_METHOD = "test_strip"
MAX_SAMPLES = 10
CONFIDENCE = 0.8
CLINICAL_HISTORY_DAYS = 400
CLINICAL_WINDOW_DAYS = 21
CLINICAL_ALPHA = 0.01
G5_OUTBREAK_CASES = 40          # mean size of the outbreak G5 is scored on
NULL_REPORTS_PER_DAY = 6.0
# A fixed past moment, so a benchmark run means the same thing whenever it is run.
ANCHOR = dt.datetime(2026, 9, 22, 14, 0, tzinfo=dt.UTC)
STRATEGIES = ("upstream", *SAMPLERS)

TARGETS = {                                                  # PRD 15.2
    "top3_accuracy_after_5_obs": 0.80,                       # G1
    "window_coverage_lo": 0.75, "window_coverage_hi": 0.85,  # G2, GC-11
    "sample_reduction_vs_best_baseline": 0.30,               # G3
    "calibration_error_max": 0.05,
    "latency_p95_s": 5.0,                                    # NFR-1
}
# FR-45 blocks changes that degrade calibration. See check_targets for what is
# absolute and what is judged against the committed summary. A target not yet met
# cannot keep CI red for ever that way, while a change that makes it worse still
# cannot land.
CALIBRATION_TOLERANCE = 0.02
REGRESSION_TOLERANCE = {"top3_accuracy_after_5_obs": 0.10,
                        "sample_reduction_vs_best_baseline": 0.15,
                        "window_coverage": 0.08}


class Kernel:
    """The kernel's functions, called the way the worker calls them."""

    def __init__(self, net, tables, params):
        self.net, self.tables, self.params = net, tables, params

    def posterior(self, events, *, now: dt.datetime, flow_condition: str,
                  weather_from: dt.datetime):
        end = dt.datetime.fromtimestamp((now.timestamp() // BIN_S) * BIN_S, dt.UTC)
        start = end - dt.timedelta(hours=HORIZON_H)
        grid = build_grid(self.net, horizon_start=start, horizon_end=end, bin_s=BIN_S)
        bins = start.timestamp() + BIN_S * np.arange(HORIZON_H * 3600 // BIN_S)
        cond = np.where(bins >= weather_from.timestamp(), FLOW_CONDITIONS.index(flow_condition),
                        FLOW_CONDITIONS.index("dry")).astype(np.int8)
        K = len(self.net.entry_idx)
        inputs = PriorInputs(cond, np.full(len(bins), 24.0), np.zeros(K, np.int32), np.zeros(K))
        obs = build_observations(events, self.net, self.params)
        post = compute_posterior(obs, self.net, grid, self.tables, inputs, self.params,
                                 flow_idx=int(cond[-1]), kernel_version=KERNEL_VERSION,
                                 stream="sim")
        return post, obs, grid

    def ranked(self, post) -> tuple[list[str], float]:
        """Entries by probability, and the top one's probability given an event."""
        m = source_marginals(post, self.net)
        entries = sorted(self.net.entry_nodes, key=lambda e: -m[e])
        return entries, m[entries[0]] / max(post.p_event, 1e-12)

    def p_source(self, post, entry: str) -> float:
        """P(this entry is the source | an event), the finer-grained G3 measure."""
        return float(source_marginals(post, self.net)[entry] / max(post.p_event, 1e-12))


def _event(report: dict) -> EventEnvelope:
    return EventEnvelope(stream="sim", catchment_id="bench",
                         event_type=EventType.EVIDENCE_RECORDED,
                         event_time=report["observed_at"],
                         payload=EvidencePayload(**to_evidence(report)).model_dump(mode="json"))


def _covered(truth: dict, window) -> float:
    lo, hi = window
    if lo is None or hi is None:
        return 0.0
    first, last = truth["first"], truth["last"]
    if last <= first:
        return float(lo <= first <= hi)
    return max(0.0, min(hi, last) - max(lo, first)) / (last - first)


def run_one(i: int, *, seed: int, kernel: Kernel, with_latency: bool = True) -> dict:
    net = kernel.net
    rng = np.random.default_rng(seed)
    scenario = sample_scenario(net, rng, now=ANCHOR, earliest_h=8.0, latest_h=1.0)
    world = np.random.default_rng(scenario.seed)
    plume = truth_plume(net, scenario, world)
    reports = generate_citizen_reports(net, plume, scenario, world, n=N_CITIZENS, now=ANCHOR)
    arrivals = zone_arrivals(net, plume)
    ctx = {"flow_condition": scenario.flow_condition,
           "weather_from": scenario.start - dt.timedelta(hours=2)}
    row = {"i": i, "scenario_id": scenario.scenario_id, "truth": scenario.entry_node,
           "weather": scenario.flow_condition, "duration_s": scenario.duration_s,
           "exposed_zones": len(arrivals), "states": [], "windows": [], "samples": {},
           "latency_s": [], "detected": False,
           "false_positives": sum(r["result"] == "positive"
                                  and r["true_concentration"] <= EXPOSURE_THRESHOLD_C
                                  for r in reports)}

    trigger = next((j for j, r in enumerate(reports) if r["result"] == "positive"
                    and r["true_concentration"] > EXPOSURE_THRESHOLD_C), None)
    if trigger is None:
        return row                    # nobody noticed: there is no episode to evaluate
    row["detected"] = True
    t_trigger = reports[trigger]["observed_at"]

    episode_states = []               # (post, n) where the kernel has an episode
    for n in N_OBS:
        if trigger + n > len(reports):
            break
        known = reports[: trigger + n]
        now = max(known[-1]["observed_at"], t_trigger)
        post, obs, grid = kernel.posterior([_event(r) for r in known], now=now, **ctx)
        ranked, stated = kernel.ranked(post)
        baseline = nearest_upstream_baseline(known[trigger:], net, kernel.tables,
                                             flow_idx=post.flow_idx)
        row["states"].append({"n_obs": n, "truth": scenario.entry_node, "ranked": ranked[:3],
                              "baseline": baseline[:3], "stated_probability": float(stated),
                              "was_correct": ranked[0] == scenario.entry_node,
                              "p_event": float(post.p_event)})
        if post.p_event >= THRESHOLD_SUSPECTED:
            episode_states.append((post, f"organic-{n}"))
        if with_latency and n == G1_STATE:
            row["latency_s"].append(_time_recompute(kernel, known, now, ctx))

    row.update(_localise_all(kernel, scenario, plume, reports[: trigger + 1], ctx,
                             episode_states))

    if episode_states:
        post, label = episode_states[-1]
        zones = pulse(post, net, kernel.tables, kernel.params)
        row["g2_state"] = label
        for zone_id, truth in arrivals.items():
            w = zones[zone_id]
            row["windows"].append({"zone_id": zone_id,
                                   "covered": _covered(truth, (w["window_lo"], w["window_hi"]))})
        row["false_windows"] = sum(1 for z, w in zones.items()
                                   if w["window_lo"] is not None and z not in arrivals)
        row.update(_clinical(kernel, arrivals, zones, seed))
    return row


def _time_recompute(kernel: Kernel, known: list[dict], now: dt.datetime, ctx: dict) -> float:
    """NFR-1: evidence to posterior, as the worker does it -- TRACE, PULSE, PROBE, explain."""
    t0 = time.perf_counter()
    post, obs, grid = kernel.posterior([_event(r) for r in known], now=now, **ctx)
    zones = pulse(post, kernel.net, kernel.tables, kernel.params)
    probe(post, kernel.net, kernel.tables, kernel.params, zones, now=now,
          flow_condition=ctx["flow_condition"])
    explain(post, obs, kernel.net, grid, kernel.tables, kernel.params)
    return time.perf_counter() - t0


def _localise_all(kernel: Kernel, scenario, plume, known: list[dict], ctx: dict,
                  episode_states: list) -> dict:
    """G3: samples to localise, EC2 against every baseline, under the same rules."""
    first_sample = known[-1]["observed_at"] + dt.timedelta(seconds=SAMPLE_STEP_S)
    allowed, why = mission_allowed(now=first_sample, flow_condition=scenario.flow_condition,
                                   flood_warning=False, node_attrs={})
    if not allowed:
        return {"g3_attempted": False, "g3_skip_reason": why}
    # Sampling can only find a source that is still discharging when someone gets
    # there; a finished spill has to be localised from the record. Both are
    # reported, and the headline is all of them.
    active = scenario.start + dt.timedelta(seconds=scenario.duration_s) > first_sample
    out = {"g3_attempted": True, "g3_active": bool(active), "samples": {}, "curves": {}}
    for name in STRATEGIES:
        curve, final = _localise(kernel, scenario, plume, known, ctx, name)
        out["curves"][name] = curve
        out["samples"][name] = metrics.samples_to_localise(
            {**curve, "truth": scenario.entry_node}, confidence=CONFIDENCE)
        if name == "upstream" and final.p_event >= THRESHOLD_SUSPECTED:
            episode_states.append((final, "after-missions"))
    return out


def _localise(kernel: Kernel, scenario, plume, known: list[dict], ctx: dict, strategy: str):
    net = kernel.net
    rng = np.random.default_rng(scenario.seed + 7)        # same draws for every strategy
    trigger = known[-1]
    state = SamplerState(net=net, tables=kernel.tables,
                         flow_idx=FLOW_CONDITIONS.index(scenario.flow_condition),
                         trigger_node=net.node_index[trigger["node_id"]],
                         flow_condition=scenario.flow_condition, rng=rng)
    reports, t = list(known), trigger["observed_at"]
    post, _, _ = kernel.posterior([_event(r) for r in reports], now=t, **ctx)
    ranked, stated = kernel.ranked(post)
    tops, confs = [ranked[0]], [float(stated)]
    truth = [kernel.p_source(post, scenario.entry_node)]
    for _ in range(MAX_SAMPLES):
        t = t + dt.timedelta(seconds=SAMPLE_STEP_S)
        if not mission_allowed(now=t, flow_condition=scenario.flow_condition,
                               flood_warning=False, node_attrs={})[0]:
            break
        if strategy == "upstream":
            picks = probe(post, net, kernel.tables, kernel.params, {}, now=t,
                          mode=ProbeMode.ENFORCE, max_candidates=1,
                          flow_condition=scenario.flow_condition, method=SAMPLE_METHOD)
            node = net.node_index[picks[0]["node_id"]] if picks else None
        else:
            node = SAMPLERS[strategy](state)
        if node is None:
            break                     # the strategy has nowhere left worth sampling
        state.sampled.append(int(node))
        reports.append(sample_at(net, plume, int(node), t.timestamp(), rng,
                                 method=SAMPLE_METHOD))
        post, _, _ = kernel.posterior([_event(r) for r in reports], now=t, **ctx)
        ranked, stated = kernel.ranked(post)
        tops.append(ranked[0])
        confs.append(float(stated))
        truth.append(kernel.p_source(post, scenario.entry_node))
    return {"top_curve": tops, "confidence_curve": confs, "truth_curve": truth}, post


def _clinical(kernel: Kernel, arrivals: dict, zones: dict, seed: int) -> dict:
    """G5 on the most exposed zone: matched filter against a blind scan, same counts."""
    if not arrivals:
        return {"delay_matched": None, "delay_blind": None}
    net = kernel.net
    zone_id = max(arrivals, key=lambda z: arrivals[z]["last"] - arrivals[z]["first"])
    population = int(net.zone_population[list(net.zone_ids).index(zone_id)])
    rng = np.random.default_rng(seed + 11)
    truth = arrivals[zone_id]
    excess = excess_cases((truth["first"], truth["last"]), population, rng,
                          n_cases=int(rng.poisson(G5_OUTBREAK_CASES)))
    exposure_day = dt.datetime.fromtimestamp(truth["first"], dt.UTC).date()
    first = exposure_day - dt.timedelta(days=CLINICAL_HISTORY_DAYS)
    last = exposure_day + dt.timedelta(days=CLINICAL_WINDOW_DAYS - 1)
    days, base, extra = area_counts(first, last, rng, excess=excess)
    counts = (base + extra).astype(float)
    counts[counts < 5] = np.nan                     # what suppression leaves the health zone
    h = CLINICAL_HISTORY_DAYS
    baseline = fit_baseline(days[:h], counts[:h], area_code=zone_id, syndrome="ag")

    z = zones[zone_id]
    t_grid = np.asarray(z["t_grid"])
    exposure = {"t_grid": t_grid, "p_exposed": z["p_exposed"], "population": population}
    day0 = dt.datetime.fromtimestamp(t_grid.min(), dt.UTC).date()
    offset = max((exposure_day - day0).days, 0)     # the curve starts at the horizon
    shape = expected_curve(exposure, SEWAGE_PATHOGEN_MIX,
                           days=np.arange(offset + CLINICAL_WINDOW_DAYS))[offset:]
    wc, wd = counts[h:], days[h:]

    def first_rejection(test) -> int:
        for d in range(1, CLINICAL_WINDOW_DAYS):
            if test(wc[: d + 1], wd[: d + 1]) < CLINICAL_ALPHA:
                return d
        return CLINICAL_WINDOW_DAYS                 # never: charged the whole window

    matched = first_rejection(lambda c, d: matched_filter_test(
        c, baseline, shape, days=d, episode_id="bench", area_code=zone_id, syndrome="ag",
        n_sim=499).p_value)
    blind = first_rejection(lambda c, d: blind_scan(c, baseline, days=d, n_sim=499).p_value)
    return {"delay_matched": matched, "delay_blind": blind, "excess_cases": int(extra.sum())}


def null_day(i: int, *, seed: int, kernel: Kernel) -> dict:
    """One day with nothing happening: do ordinary false positives open an episode?"""
    net = kernel.net
    rng = np.random.default_rng(seed)
    n = int(rng.poisson(NULL_REPORTS_PER_DAY))
    weights = report_weights(net)
    times = np.sort(rng.uniform(ANCHOR.timestamp() - 86400, ANCHOR.timestamp(), n))
    reports, peak = [], 0.0
    for t in times:
        node = int(rng.choice(len(net.node_ids), p=weights))
        # No plume anywhere: every positive is a false one.
        positive = bool(rng.random() < DETECTION["citizen_visual_olfactory"].false_positive)
        reports.append({"node_id": net.node_ids[node],
                        "observed_at": dt.datetime.fromtimestamp(float(t), dt.UTC),
                        "method": "citizen_visual_olfactory",
                        "result": "positive" if positive else "negative",
                        "observer_id": f"null-{i}", "observer_type": "citizen",
                        "snap_distance_m": 5.0, "confirmed_by_observer": True})
        post, _, _ = kernel.posterior([_event(r) for r in reports],
                                      now=dt.datetime.fromtimestamp(float(t), dt.UTC),
                                      flow_condition="dry", weather_from=ANCHOR)
        peak = max(peak, post.p_event)
    return {"reports": n, "peak_p_event": peak, "suspected": peak >= THRESHOLD_SUSPECTED,
            "probable": peak >= THRESHOLD_PROBABLE}


def summarise(rows: list[dict], nulls: list[dict]) -> dict:
    detected = [r for r in rows if r["detected"]]
    by_n = {str(n): {"top1": metrics.top_k_accuracy(detected, 1, n_obs=n),
                     "top3": metrics.top_k_accuracy(detected, 3, n_obs=n),
                     "baseline_top1": metrics.top_k_accuracy(detected, 1, n_obs=n,
                                                             key="baseline"),
                     "baseline_top3": metrics.top_k_accuracy(detected, 3, n_obs=n,
                                                             key="baseline"),
                     "states": sum(1 for _ in metrics._states(detected, n))}
            for n in N_OBS}
    g3 = [r for r in detected if r.get("g3_attempted")]
    charged, success, reduction = _g3(g3)
    active_charged, active_success, active_reduction = _g3([r for r in g3 if r["g3_active"]])
    months = len(nulls) / 30.0
    g5 = [r for r in detected if r.get("delay_matched") is not None]
    return {
        "scenarios": len(rows),
        "detected": len(detected),
        "false_positive_reports_per_scenario": float(np.mean([r["false_positives"]
                                                              for r in rows])),
        "accuracy_by_n_obs": by_n,
        "top3_accuracy_after_5_obs": by_n[str(G1_STATE)]["top3"],
        "baseline_top3_accuracy_after_5_obs": by_n[str(G1_STATE)]["baseline_top3"],
        "episode_reached": sum(1 for r in detected if r.get("g2_state")),
        "window_coverage": metrics.window_coverage(detected),
        "window_zones": sum(len(r["windows"]) for r in detected),
        "window_zones_missed": sum(1 for r in detected for w in r["windows"]
                                   if w["covered"] == 0.0),
        "false_windows_per_episode": float(np.mean([r["false_windows"] for r in detected
                                                    if "false_windows" in r]))
        if any("false_windows" in r for r in detected) else float("nan"),
        "g3_scenarios": len(g3),
        "mean_samples_charged": charged,
        "localised_rate": success,
        "sample_reduction_vs_best_baseline": reduction,
        "p_true_source_after_samples": _p_true(g3),
        "active_p_true_source_after_samples": _p_true([r for r in g3 if r["g3_active"]]),
        "g3_active_scenarios": sum(1 for r in g3 if r["g3_active"]),
        "active_mean_samples_charged": active_charged,
        "active_localised_rate": active_success,
        "active_sample_reduction_vs_best_baseline": active_reduction,
        "calibration_error": metrics.calibration_error(detected),
        "reliability": metrics.reliability_curve(detected),
        "g5_scenarios": len(g5),
        "g5_outbreak_cases_mean": G5_OUTBREAK_CASES,
        "delay_matched_days": metrics.detection_delay(g5, "delay_matched"),
        "delay_blind_days": metrics.detection_delay(g5, "delay_blind"),
        "false_suspected_per_catchment_month": metrics.false_episode_rate(nulls, months),
        "false_probable_per_catchment_month": metrics.false_episode_rate(nulls, months,
                                                                         key="probable"),
        "null_days": len(nulls),
        "latency": metrics.evidence_to_posterior_latency(detected),
    }


def _g3(rows: list[dict]):
    charged, success = {}, {}
    for name in STRATEGIES:
        s = [r["samples"][name] for r in rows]
        charged[name] = float(np.mean([MAX_SAMPLES + 1 if x is None else x for x in s])) \
            if s else float("nan")
        success[name] = float(np.mean([x is not None for x in s])) if s else float("nan")
    best = min(charged[n] for n in SAMPLERS) if rows else float("nan")
    reduction = 1 - charged["upstream"] / best if rows and best > 0 else float("nan")
    return charged, success, reduction


def _p_true(rows: list[dict], ks=(0, 3, 5, 10)) -> dict:
    """Mean P(true source | event) after k samples, per strategy.

    Finer-grained than samples-to-localise, which counts only crossings of 80%: with
    test strips that miss one reading in four, few runs cross it inside the budget,
    and the count stops seeing any difference between strategies. This sees how much
    each sample taught the kernel. A strategy that stopped early keeps its last value.
    """
    out = {}
    for name in STRATEGIES:
        curves = [r["curves"][name]["truth_curve"] for r in rows]
        out[name] = {str(k): float(np.mean([c[min(k, len(c) - 1)] for c in curves]))
                     if curves else float("nan") for k in ks}
    return out


def check_targets(summary: dict, targets: dict, committed: dict | None = None) -> list[str]:
    """FR-45: what blocks a change.

    Latency is absolute. Calibration is absolute when there is nothing to compare
    with; with a committed summary from the same protocol it may not get worse by
    more than its tolerance. A small CI run has a few hundred calibration statements,
    so its error carries sampling noise of several points either way -- a fixed 0.05
    would pass or fail on the seed, not on the change. The seed is fixed, so the same
    code reproduces the committed number, and a change is judged by what it moved.
    """
    fails = []
    lat = summary["latency"]["p95"]
    if not _nan(lat) and lat > targets["latency_p95_s"]:
        fails.append(f"latency p95 {lat:.2f}s > {targets['latency_p95_s']}s")
    ece = summary["calibration_error"]
    was_ece = (committed or {}).get("calibration_error")
    if not _nan(ece):
        if was_ece is None or _nan(was_ece):
            if ece > targets["calibration_error_max"]:
                fails.append(f"calibration error {ece:.3f} > {targets['calibration_error_max']}")
        elif ece > was_ece + CALIBRATION_TOLERANCE:
            fails.append(f"calibration error {ece:.3f} degraded from {was_ece:.3f} "
                         f"(tolerance {CALIBRATION_TOLERANCE})")
    for key, tol in REGRESSION_TOLERANCE.items():
        now, was = summary.get(key), (committed or {}).get(key)
        if now is None or was is None or _nan(now) or _nan(was):
            continue
        if key == "window_coverage":
            if abs(now - 0.80) > abs(was - 0.80) + tol:
                fails.append(f"window coverage {now:.3f} moved away from 0.80 (was {was:.3f})")
        elif now < was - tol:
            fails.append(f"{key} {now:.3f} regressed from {was:.3f} (tolerance {tol})")
    return fails


def _nan(x) -> bool:
    return isinstance(x, float) and math.isnan(x)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenarios", type=int, default=200)
    ap.add_argument("--null-days", type=int, default=None)
    ap.add_argument("--seed", type=int, default=20260922)
    ap.add_argument("--out", default="bench/results")
    ap.add_argument("--network", default=os.environ.get("NETWORK_ARTIFACT",
                                                        "data/artifacts/network.npz"))
    ap.add_argument("--tables", default=os.environ.get("TABLES_ARTIFACT",
                                                       "data/artifacts/tables.npz"))
    ap.add_argument("--baseline-summary", default="bench/results/summary.json",
                    help="committed summary the regression gate compares against")
    ap.add_argument("--gate", action="store_true", help="exit 1 if a target regresses")
    ap.add_argument("--charts", action="store_true", help="render the evaluation charts")
    ap.add_argument("--param", action="append", default=[], metavar="NAME=VALUE",
                    help="override a numeric kernel parameter and rebuild the tables in "
                         "memory; for calibration sweeps, never for the gate")
    a = ap.parse_args()

    committed = None
    if a.gate and pathlib.Path(a.baseline_summary).exists():
        committed = json.loads(pathlib.Path(a.baseline_summary).read_text(encoding="utf-8"))
        if committed.get("network_version") and committed["network_version"] != \
                load_network(a.network).version:
            committed = None          # a different catchment: nothing to regress against

    net = load_network(a.network)
    overrides = {k: float(v) for k, v in (p.split("=", 1) for p in a.param)}
    params = default_params(**overrides)
    # With overrides, or with no table file (`--tables none`, as CI runs it), the
    # tables are built from the parameters in memory: what is benchmarked is then
    # always the current physics, never a table left over from an older one.
    rebuild = bool(overrides) or not pathlib.Path(a.tables).is_file()
    tables = build_tables(net, params) if rebuild else load_tables(a.tables)
    if tables.params_version != params.version:
        raise SystemExit(f"tables were built with params {tables.params_version}, "
                         f"the kernel is at {params.version}: rebuild the tables first")
    kernel = Kernel(net, tables, params)
    started = time.perf_counter()
    rows = []
    for i in range(a.scenarios):
        rows.append(run_one(i, seed=a.seed + i, kernel=kernel))
        if (i + 1) % 10 == 0:
            print(f"  {i + 1}/{a.scenarios} scenarios, {time.perf_counter() - started:.0f}s",
                  flush=True)
    n_null = a.null_days if a.null_days is not None else max(30, a.scenarios // 2)
    nulls = [null_day(i, seed=a.seed + 100_000 + i, kernel=kernel) for i in range(n_null)]

    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    summary = summarise(rows, nulls)
    summary.update(network_version=net.version, params_version=params.version, seed=a.seed,
                   runtime_s=round(time.perf_counter() - started, 1), targets=TARGETS)
    (out / "results.json").write_text(json.dumps(rows, default=str), encoding="utf-8")
    _write_parquet(rows, out / "results.parquet")
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str) + "\n",
                                      encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "reliability"}, indent=2,
                     default=str))
    if a.charts:
        from .charts import render_all

        render_all(rows, summary, out)

    if a.gate:
        fails = check_targets(summary, TARGETS, committed)
        if fails:
            print("BENCHMARK GATE FAILED:")
            for f in fails:
                print(" -", f)
            raise SystemExit(1)
        print("benchmark gate passed")


def _write_parquet(rows: list[dict], path: pathlib.Path) -> None:
    """One row per scenario; nested fields as JSON so the schema never depends on the data."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    flat = [{k: (json.dumps(v, default=str) if isinstance(v, dict | list) else v)
             for k, v in r.items()} for r in rows]
    pq.write_table(pa.Table.from_pylist(flat), path)


if __name__ == "__main__":
    main()
