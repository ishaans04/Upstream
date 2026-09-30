// Copy the fields the web app shows from bench/results/summary.json into data/bench.json.
// Run after `make bench`; __tests__/bench-data.test.ts fails while the two disagree.
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

export const KEEP = [
  "scenarios", "top3_accuracy_after_5_obs", "baseline_top3_accuracy_after_5_obs", "window_coverage", "window_zones",
  "sample_reduction_vs_best_baseline", "g3_scenarios", "calibration_error", "delay_matched_days", "delay_blind_days",
  "false_suspected_per_catchment_month", "null_days", "latency", "accuracy_by_n_obs", "p_true_source_after_samples",
  "network_version", "params_version", "seed", "targets",
];

const here = dirname(fileURLToPath(import.meta.url));
const src = JSON.parse(readFileSync(resolve(here, "../../bench/results/summary.json"), "utf8"));
const out = Object.fromEntries(KEEP.map((k) => [k, src[k]]));
writeFileSync(resolve(here, "../data/bench.json"), JSON.stringify(out, null, 2) + "\n");
console.log("data/bench.json <- bench/results/summary.json", out.network_version);
