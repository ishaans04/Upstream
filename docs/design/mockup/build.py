import json, sys
bench = sys.argv[1]
d = json.load(open("data.json"))
bm = json.load(open("basemap.json"))
b = json.load(open(bench))
keep = ['top3_accuracy_after_5_obs','baseline_top3_accuracy_after_5_obs','window_coverage','window_zones','sample_reduction_vs_best_baseline','g3_scenarios','calibration_error','delay_matched_days','delay_blind_days','false_suspected_per_catchment_month','null_days','latency','accuracy_by_n_obs','p_true_source_after_samples']
b = {k: b[k] for k in keep}
j = lambda o: json.dumps(o, separators=(",", ":")).replace("</", "<\/")
s = open("template.html", encoding="utf-8").read()
s = s.replace("__DATA__", j(d)).replace("__BASEMAP__", j(bm)).replace("__BENCH__", j(b))
open("upstream-console.html", "w", encoding="utf-8").write(s)
print(round(len(s) / 1e6, 2), "MB")
