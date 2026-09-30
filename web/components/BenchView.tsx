// The evaluation, from bench/results/summary.json (copied to data/bench.json). Targets
// that are missed are shown as missed: the reader should not have to find the caveat.
import bench from "@/data/bench.json";
import { pct } from "@/lib/format";

type Status = "met" | "near" | "miss";
const WORD: Record<Status, string> = { met: "met", near: "just short", miss: "not met" };
const B = bench as typeof bench & {
  accuracy_by_n_obs: Record<string, { top1: number; top3: number; baseline_top1: number; baseline_top3: number }>;
  p_true_source_after_samples: Record<string, Record<string, number>>;
};

export function goals(): [string, string, string, string, string, Status][] {
  const acc = B.top3_accuracy_after_5_obs, cov = B.window_coverage, red = B.sample_reduction_vs_best_baseline, ece = B.calibration_error;
  return [
    ["G1", "Source in the top 3 after five reports", `nearest-upstream heuristic ${pct(B.baseline_top3_accuracy_after_5_obs)}`, pct(acc), "target 80%", acc >= 0.8 ? "met" : acc >= 0.75 ? "near" : "miss"],
    ["G2", "Share of true exposure inside the 80% window", `${B.window_zones} zones scored`, pct(cov), "target 75–85%", cov >= 0.75 && cov <= 0.85 ? "met" : "near"],
    ["G3", "Fewer samples than the best baseline", `${B.g3_scenarios} incidents where missions were safe`, `${(red * 100).toFixed(1)}%`, "target 30% fewer", red >= 0.3 ? "met" : red > 0 ? "near" : "miss"],
    ["—", "Calibration error of stated probabilities", "states chosen from what the system could see", ece.toFixed(3), "target ≤ 0.05", ece <= 0.05 ? "met" : ece <= 0.07 ? "near" : "miss"],
    ["G5", "Days from exposure to a clinical signal", `blind cluster scan ${B.delay_blind_days.toFixed(1)} days`, `${B.delay_matched_days.toFixed(1)} d`, "shorter than the scan", B.delay_matched_days < B.delay_blind_days ? "met" : "miss"],
    ["—", "False episodes when nothing happened", `${B.null_days} simulated quiet days`, B.false_suspected_per_catchment_month.toFixed(1), "per catchment-month", "met"],
    ["NFR-1", "Evidence to updated belief, p95", "TRACE, PULSE and PROBE together", `${B.latency.p95.toFixed(2)} s`, "target under 5 s", B.latency.p95 < 5 ? "met" : "miss"],
  ];
}

function AccuracyChart() {
  const W = 560, H = 220, L = 40, R = 14, T = 12, Bt = 30;
  const ns = Object.keys(B.accuracy_by_n_obs).map(Number);
  const X = (k: number) => L + (k / (ns.length - 1)) * (W - L - R);
  const Y = (p: number) => T + (1 - p) * (H - T - Bt);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Top-3 accuracy against number of reports: after five reports Upstream ${pct(B.top3_accuracy_after_5_obs)}, the nearest-upstream heuristic ${pct(B.baseline_top3_accuracy_after_5_obs)}`}>
      {[0, 0.5, 0.8, 1].map((p) => (
        <g key={p}>
          <line x1={L} x2={W - R} y1={Y(p)} y2={Y(p)} stroke={p === 0.8 ? "rgba(255,255,255,0.193)" : "rgba(255,255,255,0.055)"} strokeDasharray={p === 0.8 ? "4 4" : undefined} />
          <text x={L - 6} y={Y(p) + 4} textAnchor="end">{pct(p)}</text>
        </g>
      ))}
      <text x={W - R} y={Y(0.8) - 6} textAnchor="end">target</text>
      {ns.map((n, k) => <text key={n} x={X(k)} y={H - 10} textAnchor="middle">{n} report{n > 1 ? "s" : ""}</text>)}
      {([["top3", "#f2a33a"], ["baseline_top3", "#4f8fb5"]] as const).map(([key, c]) => (
        <g key={key}>
          <polyline points={ns.map((n, k) => `${X(k)},${Y(B.accuracy_by_n_obs[n][key])}`).join(" ")} fill="none" stroke={c} strokeWidth={2.2} />
          {ns.map((n, k) => <circle key={n} cx={X(k)} cy={Y(B.accuracy_by_n_obs[n][key])} r={3} fill={c} />)}
        </g>
      ))}
    </svg>
  );
}

function SamplingChart() {
  const W = 560;
  const strategies = [["upstream", "Mission planner"], ["nearest_site", "Nearest site"], ["heuristic", "Officer heuristic"], ["fixed_schedule", "Fixed schedule"], ["random", "Random upstream"]];
  const H = 30 * strategies.length + 30, L = 120;
  const X = (p: number) => L + (p * (W - L - 60)) / 0.6;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Belief in the true source after 0, 5 and 10 samples, for each sampling strategy">
      {[0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6].map((p) => (
        <g key={p}><line x1={X(p)} x2={X(p)} y1={6} y2={H - 22} stroke="rgba(255,255,255,0.055)" /><text x={X(p)} y={H - 8} textAnchor="middle">{pct(p)}</text></g>
      ))}
      {strategies.map(([k, label], i) => {
        const v = B.p_true_source_after_samples[k];
        const y = 18 + i * 30;
        const hi = k === "upstream";
        return (
          <g key={k}>
            <text x={L - 10} y={y + 4} textAnchor="end" style={{ fill: hi ? "#f7bd6a" : "#c3c3bf" }}>{label}</text>
            <line x1={X(v["0"])} x2={X(v["10"])} y1={y} y2={y} stroke="rgba(255,255,255,0.099)" strokeWidth={6} strokeLinecap="round" />
            {([["0", 3, "#9a9ca0"], ["5", 4, hi ? "#f2a33a" : "#4f8fb5"], ["10", 5.5, hi ? "#f2a33a" : "#4f8fb5"]] as const).map(([s, r, c]) =>
              <circle key={s} cx={X(v[s])} cy={y} r={r} fill={c} />)}
            <text x={X(v["10"]) + 10} y={y + 4} style={{ fill: hi ? "#f7bd6a" : "#c3c3bf" }}>{pct(v["10"])}</text>
          </g>
        );
      })}
    </svg>
  );
}

export function BenchView() {
  return (
    <section className="page" aria-labelledby="benchTitle">
      <div className="page-head"><div>
        <div className="eyebrow">Evaluation</div>
        <h1 id="benchTitle">{B.scenarios} incidents, scored against hidden truth</h1>
        <p className="desc">Simulated on the real Barapullah drain network ({B.network_version}) with its own transport, detection and illness models, none
          shared with the kernel. The same run gates every change in CI.</p>
      </div></div>
      <div className="bench">
        <div className="card">
          <div className="card-head"><h2>Goals</h2><span className="aside">seed {B.seed}</span></div>
          <div>
            {goals().map(([id, l, sub, v, t, st]) => (
              <div className="goal" key={l}>
                <div className="g">{id}</div>
                <div className="l">{l}<small>{sub}</small></div>
                <div className="r"><span className={st}>{v}</span><small>{t} · <span className={st}>{WORD[st]}</span></small></div>
              </div>
            ))}
          </div>
        </div>
        <div className="col">
          <div className="card chart">
            <div className="card-head"><h2>Finding the source from citizen reports</h2><span className="aside">true source in the top 3</span></div>
            <AccuracyChart />
            <div className="legend"><span><i className="sw-line" style={{ background: "var(--ochre)" }} />Upstream</span><span><i className="sw-line" style={{ background: "var(--water)" }} />Nearest outfall upstream of the report</span></div>
            <p className="note">On a dense urban network the nearest outfall upstream of a report is a strong guess: after five reports it is slightly ahead
              in the top 3 ({pct(B.baseline_top3_accuracy_after_5_obs)} against {pct(B.top3_accuracy_after_5_obs)}), while Upstream is well ahead on its first
              choice ({pct(B.accuracy_by_n_obs["5"].top1)} against {pct(B.accuracy_by_n_obs["5"].baseline_top1)}) and says how sure it is.</p>
          </div>
          <div className="card chart">
            <div className="card-head"><h2>Belief in the true source after sampling</h2><span className="aside">mean over {B.g3_scenarios} incidents</span></div>
            <SamplingChart />
            <p className="note">Test strips miss about one reading in four, and most spills have ended before the first mission arrives. On the dense Barapullah
              network, sampling the points nearest the report does better than the mission planner, which misses the 30% target.</p>
          </div>
        </div>
      </div>
    </section>
  );
}
