"""The evaluation charts for the README and the demo video (scene 4:10-4:40).

Colour-blind-safe (Okabe-Ito), axes in plain language, and the target drawn on
the chart itself, so pass or fail is visible without reading the caption.
"""
from __future__ import annotations

import pathlib

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

PALETTE = ["#0072B2", "#E69F00", "#009E73", "#CC79A7", "#56B4E9", "#D55E00"]
STRATEGIES = [("upstream", "Upstream\n(EC²)"), ("nearest_site", "Nearest\nsite"),
              ("random", "Random\nupstream"), ("fixed_schedule", "Fixed\nschedule"),
              ("heuristic", "Heuristic\nweights")]


def _save(fig, out: pathlib.Path, name: str) -> None:
    fig.tight_layout()
    fig.savefig(out / name, dpi=160)
    plt.close(fig)


def chart_accuracy_vs_observations(summary: dict, out: pathlib.Path) -> None:
    """G1: top-1 and top-3 accuracy against the nearest-upstream baseline."""
    by_n = summary["accuracy_by_n_obs"]
    ns = [int(n) for n in by_n if not np.isnan(by_n[n]["top1"])]
    fig, ax = plt.subplots(figsize=(7, 4))
    series = [("Upstream top-3", "top3", "-"), ("Upstream top-1", "top1", "-"),
              ("Nearest-upstream top-3", "baseline_top3", "--"),
              ("Nearest-upstream top-1", "baseline_top1", "--")]
    for i, (label, key, ls) in enumerate(series):
        ax.plot(ns, [by_n[str(n)][key] for n in ns], marker="o", ls=ls, color=PALETTE[i],
                label=label)
    ax.axhline(0.80, ls=":", c="grey")
    ax.text(ns[0], 0.815, "G1 target: top-3 ≥ 80% after 5", color="grey", fontsize=8)
    ax.set_xlabel("Citizen reports available (from the first positive)")
    ax.set_ylabel("True source ranked")
    ax.set_ylim(0, 1)
    ax.legend(fontsize=8, loc="lower right")
    _save(fig, out, "accuracy.png")


def chart_samples_to_localise(rows: list[dict], summary: dict, out: pathlib.Path,
                              budget: int) -> None:
    """G3: samples needed, Upstream vs the four baselines. Failures sit at budget + 1."""
    g3 = [r for r in rows if r.get("g3_attempted")]
    data = [[budget + 1 if r["samples"][k] is None else r["samples"][k] for r in g3]
            for k, _ in STRATEGIES]
    fig, ax = plt.subplots(figsize=(7.5, 4))
    bp = ax.boxplot(data, patch_artist=True, showmeans=True,
                    meanprops={"marker": "D", "markerfacecolor": "white",
                               "markeredgecolor": "black"})
    ax.set_xticks(range(1, len(STRATEGIES) + 1), [label for _, label in STRATEGIES])
    for patch, colour in zip(bp["boxes"], PALETTE, strict=False):
        patch.set_facecolor(colour)
        patch.set_alpha(0.55)
    ax.axhline(budget + 1, ls=":", c="grey")
    ax.text(0.6, budget + 1.15, "not localised within the budget", color="grey", fontsize=8)
    red = summary.get("sample_reduction_vs_best_baseline")
    title = "Samples to localise the source (◆ mean)"
    if red is not None and not np.isnan(red):
        title += f" - {red:+.0%} vs best baseline (target -30%)".replace("+-", "-")
    ax.set_title(title, fontsize=10)
    ax.set_ylabel("Samples")
    _save(fig, out, "samples.png")


def chart_belief_in_true_source(rows: list[dict], out: pathlib.Path, budget: int) -> None:
    """G3, finer: how much belief each strategy's samples put on the true source."""
    g3 = [r for r in rows if r.get("g3_attempted")]
    fig, ax = plt.subplots(figsize=(7, 4))
    for i, (key, label) in enumerate(STRATEGIES):
        curves = [r["curves"][key]["truth_curve"] for r in g3]
        if not curves:
            continue
        means = [np.mean([c[min(k, len(c) - 1)] for c in curves]) for k in range(budget + 1)]
        ax.plot(range(budget + 1), means, marker="o", ms=3, color=PALETTE[i],
                label=label.replace("\n", " "), lw=2.5 if key == "upstream" else 1.5)
    ax.set_xlabel("Samples taken after the first report")
    ax.set_ylabel("P(true source | an event), mean")
    ax.set_ylim(0, 1)
    ax.legend(fontsize=8, loc="upper left")
    _save(fig, out, "belief_in_true_source.png")


def chart_window_calibration(summary: dict, out: pathlib.Path) -> None:
    """G2 / GC-11: does an 80% window hold about 80% of the true exposure?"""
    cov = summary["window_coverage"]
    fig, ax = plt.subplots(figsize=(5, 4))
    ax.axhspan(0.75, 0.85, color=PALETTE[2], alpha=0.2, label="target band 75–85%")
    ax.bar(["80% exposure window"], [cov], color=PALETTE[0], width=0.5)
    ax.text(0, cov + 0.02, f"{cov:.0%}", ha="center")
    ax.set_ylim(0, 1)
    ax.set_ylabel("Share of true exposure inside the window")
    ax.legend(loc="lower right", fontsize=8)
    _save(fig, out, "window_calibration.png")


def chart_reliability_diagram(summary: dict, out: pathlib.Path) -> None:
    """Probability calibration, with the expected calibration error on the chart."""
    pts = summary["reliability"]
    fig, ax = plt.subplots(figsize=(5, 5))
    ax.plot([0, 1], [0, 1], ls="--", c="grey", label="perfect calibration")
    if pts:
        x, y, n = (np.array(v) for v in zip(*pts, strict=True))
        ax.scatter(x, y, s=20 + 200 * n / n.max(), color=PALETTE[0], zorder=3,
                   label="Upstream (size = number of statements)")
        ax.plot(x, y, color=PALETTE[0])
    ece = summary["calibration_error"]
    ax.set_title(f"Calibration error {ece:.3f} (target ≤ 0.05)", fontsize=10)
    ax.set_xlabel("Stated probability of the top source")
    ax.set_ylabel("How often it was the true source")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.legend(fontsize=8, loc="upper left")
    _save(fig, out, "reliability.png")


def chart_detection_delay(rows: list[dict], summary: dict, out: pathlib.Path,
                          horizon: int) -> None:
    """G5: matched filter vs a blind cluster scan, same counts, same 1% level."""
    m = [r["delay_matched"] for r in rows if r.get("delay_matched") is not None]
    b = [r["delay_blind"] for r in rows if r.get("delay_blind") is not None]
    fig, ax = plt.subplots(figsize=(6.5, 4))
    bins = np.arange(0, horizon + 2) - 0.5
    ax.hist([m, b], bins=bins, color=PALETTE[:2],
            label=[f"Matched filter (mean {np.mean(m):.1f} d)" if m else "Matched filter",
                   f"Blind cluster scan (mean {np.mean(b):.1f} d)" if b else "Blind scan"])
    ax.set_xlabel(f"Days from exposure to detection ({horizon} = not detected)")
    ax.set_ylabel("Scenarios")
    ax.legend(fontsize=8)
    _save(fig, out, "detection_delay.png")


def render_all(rows: list[dict], summary: dict, out) -> None:
    from .runner import CLINICAL_WINDOW_DAYS, MAX_SAMPLES

    out = pathlib.Path(out)
    detected = [r for r in rows if r.get("detected")]
    chart_accuracy_vs_observations(summary, out)
    chart_samples_to_localise(detected, summary, out, MAX_SAMPLES)
    chart_belief_in_true_source(detected, out, MAX_SAMPLES)
    chart_window_calibration(summary, out)
    chart_reliability_diagram(summary, out)
    chart_detection_delay(detected, summary, out, CLINICAL_WINDOW_DAYS)
