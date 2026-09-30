// PROBE (FR-15): the single most useful next observation. The effect sentence is the
// kernel's, computed from EC2 -- it says "narrows" rather than "rules out" when that
// is all a sample can do. Missions are dispatched by the episode workflow, not from
// here: the console shows what was offered, it does not send people anywhere.
import { hm } from "@/lib/format";
import type { NetworkGeoJSON, ProbeCandidate } from "@/lib/types";
import { outfallName } from "./SourceRanking";

export function ProbeCard({ candidates, network, isPast }: { candidates: ProbeCandidate[]; network: NetworkGeoJSON; isPast: boolean }) {
  const pr = candidates[0];
  if (!pr) {
    return (
      <p className="note" style={{ margin: 0 }}>
        No sample is worth sending anyone for right now: nothing credible is still passing a reachable point,
        or it is dark, in spate, or under a flood warning (PRD 7.5).
      </p>
    );
  }
  const o = outfallName(network, pr.node_id);
  const alts = candidates.slice(1).map((c) => c.node_id).join(", ");
  return (
    <div className="probe">
      <div className="where">Test strip at {pr.node_id}{o ? ` (outfall ${o.outfall_id})` : ""}</div>
      <div className="meta">
        <span>Go between {hm(pr.window_start)} and {hm(pr.window_end)}</span>
        <span>about {Math.round(pr.walk_cost_s / 60)} min walk</span>
      </div>
      <div className="effect">{pr.expected_effect}</div>
      <div className="safe">
        <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><path d="M2 6.5l2.5 2.5L10 3" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" /></svg>
        Daylight, normal flow, public access
      </div>
      <div className="note" style={{ margin: 0 }}>
        {isPast ? "This was the recommendation at the time shown." : "Offered to available volunteers nearby by the mission planner."}
        {alts && <> Then {alts}.</>}
      </div>
    </div>
  );
}
