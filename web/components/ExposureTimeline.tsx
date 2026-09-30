"use client";
// PULSE (FR-14): when each zone downstream may be exposed, as an 80% credible window
// with the probability curve inside it. A zone nobody has looked near reads "Not
// enough evidence here" -- never the "no exposure" of a zone the model believes is
// clean (PRD 14.4).
import { useState } from "react";
import { epoch, hm } from "@/lib/format";
import type { ZoneView } from "./NetworkMap";

type Props = { zones: ZoneView[]; at: string; origin: string };

export function ExposureTimeline({ zones, at, origin }: Props) {
  const [showAll, setShowAll] = useState(false);
  const t0 = epoch(origin) - 2 * 3600, t1 = t0 + 14 * 3600;
  const X = (t: number) => ((t - t0) / (t1 - t0)) * 100;
  const now = epoch(at);
  const exposed = zones.filter((z) => z.status === "exposed" && z.window)
    .sort((a, b) => (a.window!.window_lo ?? 0) - (b.window!.window_lo ?? 0));
  const rest = zones.filter((z) => z.status !== "exposed");
  const listed = showAll ? [...exposed, ...rest] : exposed;

  return (
    <div className="windows">
      {listed.length === 0 && <p className="note" style={{ margin: 0 }}>No zone expects exposure in this belief.</p>}
      {listed.map((z) => {
        const w = z.window;
        let body: React.ReactNode;
        if (z.status === "exposed" && w && w.window_lo != null && w.window_hi != null) {
          const pts = (w.t_grid ?? []).map((t, k) => [X(t), 24 - 20 * (w.p_exposed?.[k] ?? 0)] as const)
            .filter(([x]) => x >= 0 && x <= 100).map(([x, y]) => `${x.toFixed(2)},${y.toFixed(2)}`);
          body = (
            <svg viewBox="0 0 100 26" preserveAspectRatio="none" role="img"
                 aria-label={`Exposure expected ${hm(w.window_lo)} to ${hm(w.window_hi)}`}>
              <rect x="0" y="23.5" width="100" height="1" fill="rgba(255,255,255,0.099)" />
              <rect x={X(w.window_lo)} y="3" width={Math.max(0.6, X(w.window_hi) - X(w.window_lo))} height="21" fill="rgba(242,163,58,.16)" />
              {pts.length > 1 && <polyline points={pts.join(" ")} fill="none" stroke="#f2a33a" strokeWidth="1.4" vectorEffect="non-scaling-stroke" />}
              <line x1={X(now)} x2={X(now)} y1="0" y2="26" stroke="#f3f2ee" strokeWidth="1" vectorEffect="non-scaling-stroke" strokeDasharray="2 2" />
            </svg>
          );
        } else if (z.status === "clear") {
          body = <span style={{ color: "var(--sage-text)", fontSize: 12 }}>No exposure expected</span>;
        } else {
          body = <span className="zone-row-nodata">Not enough evidence here</span>;
        }
        const when = z.status === "exposed" && w?.window_lo != null ? `${hm(w.window_lo)}–${hm(w.window_hi!)}` : "";
        return (
          <div className="wrow" key={z.zone_id}>
            <div className="zn">{z.name}<small>{when && <><span className="mono">{when}</span> · </>}up to {z.population} people</small></div>
            <div>{body}</div>
          </div>
        );
      })}
      {listed.length > 0 && (
        <div className="waxis" aria-hidden="true"><div />
          <div>{[0, 3.5, 7, 10.5, 14].map((h) => <span key={h}>{hm(t0 + h * 3600)}</span>)}</div>
        </div>
      )}
      <button type="button" className="btn btn-quiet btn-sm" style={{ justifySelf: "start", marginTop: 6 }}
              onClick={() => setShowAll((v) => !v)}>
        {showAll ? `Show only the ${exposed.length} zones expecting exposure` : `Show all ${zones.length} zones`}
      </button>
    </div>
  );
}
