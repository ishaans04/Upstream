import Link from "next/link";
import { Mark, StreamChip } from "@/components/Chrome";
import { HeroMap } from "@/components/HeroMap";
import bench from "@/data/bench.json";
import { CATCHMENT } from "@/lib/config";
import { pct } from "@/lib/format";

export default function Landing() {
  const B = bench;
  return (
    <div className="landing">
      <header className="topbar">
        <div className="brand"><Mark size={22} />UPSTREAM<span className="sub">Catchment console</span></div>
        <div className="spacer" />
        <StreamChip />
        <Link className="btn btn-quiet btn-sm" href="/console">Open console</Link>
      </header>

      <main id="main" tabIndex={-1}>
        <section className="hero">
          <div>
            <div className="eyebrow place">{CATCHMENT.reaches}</div>
            <h1>Where did it come from, and <em>who is downstream?</em></h1>
            <p className="lede">A resident smells sewage at a nallah-side park. Upstream turns that report, and every report around it, into a
              calibrated picture of the event: the likely outfall, when each park and bank downstream is exposed, and the next place worth checking.</p>
            <div className="actions">
              <Link className="btn btn-primary" href="/console">Enter the console
                <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path d="M3 8h10M9 4l4 4-4 4" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>
              </Link>
              <Link className="btn btn-quiet" href="/benchmarks">How it is evaluated</Link>
            </div>
          </div>
          <HeroMap />
        </section>

        <section className="modules" aria-label="What Upstream does">
          <div className="module">
            <div className="eyebrow">Trace</div>
            <h2 className="h3">Which outfall is it?</h2>
            <p>Every report, including &quot;checked, looks normal&quot;, updates an exact posterior over every outfall, start time and duration on the real drain network.</p>
            <div className="fact">{pct(B.top3_accuracy_after_5_obs)} top-3 after five reports; {pct(B.calibration_error, 1)} calibration error</div>
          </div>
          <div className="module">
            <div className="eyebrow">Pulse</div>
            <h2 className="h3">Who is exposed, and when?</h2>
            <p>The belief is pushed downstream to every park, footpath and playground beside the drains as an 80% exposure window, calibrated against simulation.</p>
            <div className="fact">{pct(B.window_coverage)} of true exposure inside the window</div>
          </div>
          <div className="module">
            <div className="eyebrow">Probe</div>
            <h2 className="h3">Where should someone look next?</h2>
            <p>Missions go to the sample that would change the decision most, within walking distance, in daylight, and never beside a drain in monsoon spate.</p>
            <div className="fact">evidence to updated mission list in {B.latency.p95.toFixed(1)} s (p95)</div>
          </div>
        </section>

        <section className="evaluated" aria-label="Evaluation">
          <div className="evaluated-inner">
            <div className="intro">
              <h2>Evaluated, not only demonstrated</h2>
              <p>{B.scenarios} simulated incidents on the real network, scored against hidden ground truth. Targets we miss are reported as missed.</p>
              <Link className="btn btn-quiet btn-sm" href="/benchmarks" style={{ marginTop: 12 }}>All results</Link>
            </div>
            <div className="stat"><div className="v num">{pct(B.window_coverage)}</div><div className="k">of true exposure falls inside the 80% window</div><div className="t">target 75–85%</div></div>
            <div className="stat"><div className="v num">{B.delay_matched_days.toFixed(1)}<small> vs {B.delay_blind_days.toFixed(1)} days</small></div><div className="k">clinical signal found earlier than a blind cluster scan</div><div className="t">matched filter vs scan</div></div>
            <div className="stat"><div className="v num">{B.latency.p95.toFixed(1)}<small> s</small></div><div className="k">from new evidence to an updated belief, p95</div><div className="t">target under 5 s</div></div>
            <div className="stat"><div className="v num">0</div><div className="k">HL7 validator errors on the OneAquaHealth IG</div><div className="t">checked on every change</div></div>
          </div>
        </section>
      </main>

      <footer className="footer">
        <span>No patient data enters the environmental system. Only aggregate counts reach the health zone, and only test results leave it.</span>
        <span className="mono">network {B.network_version} · params {B.params_version} · map © OpenStreetMap contributors (ODbL)</span>
      </footer>
    </div>
  );
}
