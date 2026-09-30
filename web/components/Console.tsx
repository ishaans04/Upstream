"use client";
// The operator console (FR-36) with belief replay built in (FR-37).
//
// Everything on screen is one stored belief: the snapshot the slider points at, and
// the evidence whose sequence number that snapshot was computed from. Moving the
// slider does not recompute anything; it fetches the belief that was recorded then
// (`/replay?at=`), so the console can only ever show what the system actually believed.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { evidenceAsOf, givenEvent, nodeCoords, rankedSources } from "@/lib/belief";
import { full, hm, pct, SOURCE_TYPE } from "@/lib/format";
import type { EpisodeDetail, NetworkGeoJSON, Snapshot, TimelinePoint } from "@/lib/types";
import { BeliefSlider } from "./BeliefSlider";
import { EpisodeStateBadge } from "./EpisodeStateBadge";
import { Drawer, EvidenceList } from "./EvidenceList";
import { ExposureTimeline } from "./ExposureTimeline";
import { NetworkMap, zoneData } from "./NetworkMap";
import { ProbeCard } from "./ProbeCard";
import { outfallName, SourceRanking } from "./SourceRanking";
import { SyntheticBadge } from "./SyntheticBadge";

export const REPLAY_DEBOUNCE_MS = 120;

type Props = {
  network: NetworkGeoJSON;
  episode: EpisodeDetail;
  timeline: TimelinePoint[];
  loadSnapshot: (p: TimelinePoint) => Promise<Snapshot>;
  initialIndex?: number;
  aside?: React.ReactNode;
};

export function Console({ network, episode, timeline, loadSnapshot, initialIndex, aside }: Props) {
  const last = timeline.length - 1;
  const [index, setIndex] = useState(initialIndex ?? last);
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [drawer, setDrawer] = useState(false);
  const opener = useRef<HTMLButtonElement>(null);
  const cache = useRef(new Map<string, Snapshot>());

  useEffect(() => { setIndex(initialIndex ?? timeline.length - 1); }, [timeline, initialIndex]);

  // Debounced so dragging the slider asks for the belief where it stops, and guarded
  // so a slow answer for an earlier position never overwrites a later one.
  useEffect(() => {
    const point = timeline[index];
    if (!point) return;
    const hit = cache.current.get(point.fingerprint);
    if (hit) { setSnap(hit); return; }
    let live = true;
    const t = setTimeout(() => {
      loadSnapshot(point)
        .then((s) => { cache.current.set(point.fingerprint, s); if (live) { setSnap(s); setError(null); } })
        .catch((e) => { if (live) setError(String(e.message ?? e)); });
    }, REPLAY_DEBOUNCE_MS);
    return () => { live = false; clearTimeout(t); };
  }, [index, timeline, loadSnapshot]);

  const coords = useMemo(() => nodeCoords(network), [network]);
  const rows = useMemo(() => (snap ? evidenceAsOf(episode.evidence, snap.as_of_seq) : []), [snap, episode.evidence]);
  const zones = useMemo(() => (snap ? zoneData(network, snap, rows, coords) : []), [network, snap, rows, coords]);
  const closeDrawer = useCallback(() => { setDrawer(false); opener.current?.focus(); }, []);

  const top = snap ? rankedSources(snap, network)[0] : undefined;
  const topO = top ? outfallName(network, top) : undefined;
  const nExposed = zones.filter((z) => z.status === "exposed").length;
  const nUnknown = zones.filter((z) => z.status === "no-data").length;
  const live = rows.filter((r) => !r.retracted);
  const nPos = live.filter((r) => r.payload.result !== "negative").length;

  return (
    <section className="page" aria-labelledby="consoleTitle">
      <div className="page-head">
        <div>
          <div className="eyebrow">Episode</div>
          <h1 id="consoleTitle">{episode.episode_id} <EpisodeStateBadge state={episode.state} /></h1>
          <p className="desc">
            Opened {full(episode.opened_at)}.{" "}
            {snap ? `Showing the belief recorded at ${hm(snap.ts)}, built from ${rows.length} pieces of evidence.` : "Loading the belief…"}
          </p>
        </div>
      </div>
      {error && <p className="error-note" role="alert">Could not load that belief: {error}</p>}

      <div className="kpis">
        <div className="kpi s-event">
          <div className="kpi-head"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M10 3L18 17H2z" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" /><path d="M10 8v4M10 14.5v.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" /></svg><div className="eyebrow">Something is happening</div></div>
          <div className="v num">{snap ? pct(snap.p_event) : "—"}</div>
          <div className="s">probability of any event, not only this source</div>
        </div>
        <div className="kpi s-source">
          <div className="kpi-head"><svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="5" cy="10" r="2.2" fill="none" stroke="currentColor" strokeWidth="1.5" /><circle cx="15" cy="5" r="2.2" fill="none" stroke="currentColor" strokeWidth="1.5" /><circle cx="15" cy="15" r="2.2" fill="none" stroke="currentColor" strokeWidth="1.5" /><path d="M7 9l6-3M7 11l6 3" stroke="currentColor" strokeWidth="1.5" /></svg><div className="eyebrow">Most likely source</div></div>
          <div className="v">{topO ? <>{topO.outfall_id} {topO.is_synthetic && <SyntheticBadge />}</> : "—"}</div>
          <div className="s">{snap && top ? `${SOURCE_TYPE[topO?.source_type ?? ""] ?? ""} · ${pct(givenEvent(snap, top))} given an event` : ""}</div>
        </div>
        <div className="kpi s-zones">
          <div className="kpi-head"><svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="10" r="6.5" fill="none" stroke="currentColor" strokeWidth="1.5" /><circle cx="10" cy="10" r="2.2" fill="none" stroke="currentColor" strokeWidth="1.5" /><path d="M10 1.5v3M10 15.5v3M1.5 10h3M15.5 10h3" stroke="currentColor" strokeWidth="1.5" /></svg><div className="eyebrow">Zones expecting exposure</div></div>
          <div className="v num">{snap ? `${nExposed} of ${zones.length}` : "—"}</div>
          <div className="s">{snap ? `${nUnknown} with not enough evidence to say` : ""}</div>
        </div>
        <button ref={opener} type="button" className="kpi kpi-btn s-evidence" aria-haspopup="dialog" aria-expanded={drawer}
                onClick={() => setDrawer(true)}>
          <div className="kpi-head"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M5 2.5h7l3.5 3.5v11.5H5z" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" /><path d="M12 2.5V6h3.5M8 10h5M8 13h5" stroke="currentColor" strokeWidth="1.5" /></svg><div className="eyebrow">Evidence</div>
            <span className="kpi-open" aria-hidden="true">Open log <svg viewBox="0 0 12 12"><path d="M4 2.5L7.5 6 4 9.5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" /></svg></span></div>
          <div className="v num">{rows.length}</div>
          <div className="s">{nPos} contamination seen · {live.length - nPos} looked normal</div>
        </button>
      </div>

      <div className="console">
        <div className="col">
          <div className="card">
            <div className="card-head"><svg className="ic" viewBox="0 0 20 20" aria-hidden="true"><path d="M10 2l7 4v8l-7 4-7-4V6z M3 6l7 4 7-4 M10 10v8" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" /></svg><h2>Drain network, 3D</h2><span className="aside">drag to pan · scroll to zoom · right-drag to tilt</span></div>
            <NetworkMap network={network} snapshot={snap} evidence={rows} />
            <BeliefSlider timeline={timeline} index={index} fingerprint={snap?.fingerprint ?? timeline[index]?.fingerprint ?? null} onChange={setIndex} />
          </div>
          <div className="card">
            <div className="card-head"><h2>Exposure windows</h2><span className="aside">80% credible window per zone, local time</span></div>
            {snap && <ExposureTimeline zones={zones} at={snap.ts} origin={episode.opened_at} />}
          </div>
        </div>
        <div className="col">
          {aside}
          <div className="card">
            <div className="card-head"><h2>Likely source</h2><span className="aside">given that something is happening</span></div>
            {snap && <SourceRanking network={network} snapshot={snap} evidence={rows} />}
          </div>
          <div className="card">
            <div className="card-head"><h2>Next best sample</h2><span className="aside">chosen to separate the suspects</span></div>
            {snap && <ProbeCard candidates={snap.probe_candidates} network={network} isPast={index !== last} />}
          </div>
        </div>
      </div>

      <Drawer open={drawer} onClose={closeDrawer} title="Evidence log" eyebrow={`Episode ${episode.episode_id}`}
              sub={snap ? `${rows.length} pieces of evidence at ${hm(snap.ts)} · ${nPos} contamination seen` : ""}>
        {snap && <EvidenceList rows={rows} explanation={snap.explanation} topName={topO?.outfall_id ?? ""} />}
      </Drawer>
    </section>
  );
}
