"""PRD 15.2: the metrics, as plain functions over result rows.

Each takes the rows the runner writes and returns a number. None of them knows
how a row was produced, which is what lets the tests check them against hand-made
rows whose right answer is obvious.

A row here is one scenario. Per-observation-count states live in `row["states"]`;
per-zone window checks in `row["windows"]`; samples-to-localise per strategy in
`row["samples"]`.
"""
from __future__ import annotations

import numpy as np


def _states(results, n_obs: int | None, key: str = "states"):
    for r in results:
        for s in r.get(key) or []:
            if n_obs is None or s["n_obs"] == n_obs:
                yield s


def top_k_accuracy(results, k: int, *, n_obs: int | None = None, key: str = "ranked") -> float:
    """Fraction of states whose true source is among the first k ranked."""
    hits = [s["truth"] in s[key][:k] for s in _states(results, n_obs)]
    return float(np.mean(hits)) if hits else float("nan")


def samples_to_localise(result, *, confidence: float = 0.8) -> int | None:
    """Samples until the top source reaches `confidence` AND is the true one.

    A curve of (top source, its probability) after each sample. Reaching the
    threshold on the wrong source is a failure, not a success: confidently wrong
    is worse than unsure.
    """
    for i, (top, p) in enumerate(zip(result["top_curve"], result["confidence_curve"],
                                     strict=True)):
        if p >= confidence:
            return i if top == result["truth"] else None
    return None


def window_coverage(results) -> float:
    """G2 / GC-11: of the true exposure time at truly exposed zones, the share the window held.

    Each truly exposed zone contributes the fraction of its true exposure interval
    that fell inside PULSE's 80% window; a zone PULSE gave no window at all
    contributes zero. For a calibrated 80% window this averages 0.80.
    """
    fractions = [w["covered"] for r in results for w in (r.get("windows") or [])]
    return float(np.mean(fractions)) if fractions else float("nan")


def calibration_error(results, bins: int = 10, *, key: str = "states") -> float:
    """Expected calibration error of the stated top-source probability.

    `key` names the states to score. They must have been chosen from observed data
    alone: states chosen because the hidden truth made them easy (a report known to be
    genuine) make any honest model look underconfident.
    """
    p = np.array([s["stated_probability"] for s in _states(results, None, key)], dtype=float)
    y = np.array([s["was_correct"] for s in _states(results, None, key)], dtype=float)
    if len(p) == 0:
        return float("nan")
    idx = np.clip((p * bins).astype(int), 0, bins - 1)
    ece = 0.0
    for b in range(bins):
        m = idx == b
        if m.any():
            ece += m.mean() * abs(y[m].mean() - p[m].mean())
    return float(ece)


def reliability_curve(results, bins: int = 10, *, key: str = "states"):
    """(mean stated, observed frequency, count) per bin, for the reliability diagram."""
    p = np.array([s["stated_probability"] for s in _states(results, None, key)], dtype=float)
    y = np.array([s["was_correct"] for s in _states(results, None, key)], dtype=float)
    idx = np.clip((p * bins).astype(int), 0, bins - 1)
    out = []
    for b in range(bins):
        m = idx == b
        if m.any():
            out.append((float(p[m].mean()), float(y[m].mean()), int(m.sum())))
    return out


def detection_delay(results, key: str = "delay_matched") -> float:
    """Mean days from exposure to detection; scenarios never detected count the horizon."""
    delays = [r[key] for r in results if r.get(key) is not None]
    return float(np.mean(delays)) if delays else float("nan")


def false_episode_rate(null_days, catchment_months: float | None = None, *,
                       key: str = "suspected") -> float:
    """Episodes opened per catchment-month when nothing was happening.

    `null_days` are rows for simulated event-free days, each saying whether that
    day's evidence pushed the posterior over the threshold named by `key`.
    """
    if not null_days:
        return float("nan")
    months = catchment_months if catchment_months is not None else len(null_days) / 30.0
    return float(sum(bool(d[key]) for d in null_days) / months)


def evidence_to_posterior_latency(results) -> dict:
    """NFR-1: p50 and p95 of the full recompute, in seconds."""
    lat = np.array([x for r in results for x in (r.get("latency_s") or [])], dtype=float)
    if len(lat) == 0:
        return {"p50": float("nan"), "p95": float("nan")}
    return {"p50": float(np.percentile(lat, 50)), "p95": float(np.percentile(lat, 95))}
