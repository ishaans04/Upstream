"use client";
// FR-37 as a record: every stored belief for the episode, with its fingerprint, and
// how the leading candidates moved as evidence arrived. Selecting a row opens the
// console at that moment.
import Link from "next/link";
import { useRouter } from "next/navigation";
import { getEpisode, getEpisodes, getNetwork, getReplay, getTimeline } from "@/lib/api";
import { givenEvent, rankedSources } from "@/lib/belief";
import { full, hm, pct, shortFingerprint, SOURCE_TYPE } from "@/lib/format";
import type { NetworkGeoJSON, Snapshot } from "@/lib/types";
import { LEAD_IN_MS } from "./ConsoleLoader";
import { outfallName } from "./SourceRanking";
import { LoadError, Loading, NoEpisodes } from "./States";
import { useLoad } from "./useLoad";

const MAX_POINTS = 30;
const COLOURS = ["#f2a33a", "#4f8fb5", "#c3c3bf", "#7fa37a"];

async function loadReplay() {
  const [network, episodes] = await Promise.all([getNetwork(), getEpisodes()]);
  if (!episodes.length) return { network, episode: null, snaps: [] as Snapshot[] };
  const episode = await getEpisode(episodes[0].episode_id);
  const tl = await getTimeline(new Date(Date.parse(episode.opened_at) - LEAD_IN_MS));
  const step = Math.max(1, Math.ceil(tl.length / MAX_POINTS));
  const picked = tl.filter((_, i) => i % step === 0 || i === tl.length - 1);
  const snaps = await Promise.all(picked.map((p) => getReplay(p.ts)));
  return { network, episode, snaps };
}

function Chart({ snaps, network }: { snaps: Snapshot[]; network: NetworkGeoJSON }) {
  const W = 640, H = 300, L = 44, R = 16, T = 14, B = 34;
  const X = (k: number) => L + (snaps.length > 1 ? k / (snaps.length - 1) : 0.5) * (W - L - R);
  const Y = (p: number) => T + (1 - p) * (H - T - B);
  const shown = [...new Set(snaps.flatMap((s) => rankedSources(s, network).slice(0, 2)))].slice(0, 4);
  const labelEvery = Math.max(1, Math.ceil(snaps.length / 6));
  return (
    <>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Line chart of source probabilities across the episode">
        {[0, 0.25, 0.5, 0.75, 1].map((p) => (
          <g key={p}><line x1={L} x2={W - R} y1={Y(p)} y2={Y(p)} stroke="rgba(255,255,255,0.055)" />
            <text x={L - 8} y={Y(p) + 4} textAnchor="end">{pct(p)}</text></g>
        ))}
        {snaps.map((s, k) => (k % labelEvery === 0 || k === snaps.length - 1) &&
          <text key={s.fingerprint} x={X(k)} y={H - 12} textAnchor="middle">{hm(s.ts)}</text>)}
        {shown.map((node, c) => (
          <g key={node}>
            <polyline points={snaps.map((s, i) => `${X(i)},${Y(givenEvent(s, node))}`).join(" ")} fill="none" stroke={COLOURS[c]} strokeWidth={c === 0 ? 2.6 : 1.8} />
            {snaps.map((s, i) => <circle key={i} cx={X(i)} cy={Y(givenEvent(s, node))} r={i === snaps.length - 1 ? 4 : 2.6} fill={COLOURS[c]} />)}
          </g>
        ))}
        <polyline points={snaps.map((s, i) => `${X(i)},${Y(s.p_event)}`).join(" ")} fill="none" stroke="#f3f2ee" strokeWidth={1.4} strokeDasharray="4 4" />
      </svg>
      <div className="legend">
        {shown.map((node, c) => {
          const o = outfallName(network, node);
          return <span key={node}><i className="sw-line" style={{ background: COLOURS[c] }} />{o?.outfall_id ?? node} ({SOURCE_TYPE[o?.source_type ?? ""] ?? o?.source_type})</span>;
        })}
        <span><i className="sw-line" style={{ background: "repeating-linear-gradient(90deg,#f4f1e8 0 4px,transparent 4px 8px)" }} />Something is happening</span>
      </div>
    </>
  );
}

export function ReplayView() {
  const router = useRouter();
  const r = useLoad(loadReplay, []);
  if (r.error) return <LoadError what="the stored beliefs" error={r.error} />;
  if (!r.data) return <Loading what="the stored beliefs" />;
  const { network, episode, snaps } = r.data;

  return (
    <section className="page" aria-labelledby="replayTitle">
      <div className="page-head"><div>
        <div className="eyebrow">Belief replay</div>
        <h1 id="replayTitle">What did the system believe, and when?</h1>
        <p className="desc">Every belief is stored with a fingerprint of the exact evidence and model versions behind it. Pick any moment to
          see the console as it was then.</p>
      </div></div>
      {!episode || snaps.length === 0 ? <NoEpisodes /> : (
        <div className="replay">
          <div className="card chart">
            <div className="card-head"><h2>Belief as evidence arrived</h2><span className="aside">{episode.episode_id} · probability of each outfall, given an event</span></div>
            <Chart snaps={snaps} network={network} />
          </div>
          <div className="card">
            <div className="card-head"><h2>Stored beliefs</h2><span className="aside">select a row to open it</span></div>
            <div className="table-wrap">
              <table>
                <caption className="sr-only">Stored beliefs for {episode.episode_id}; each row opens the console at that moment</caption>
                <thead><tr><th scope="col">Time</th><th scope="col">Event</th><th scope="col">Top source</th><th scope="col">Fingerprint</th></tr></thead>
                <tbody>
                  {snaps.map((s) => {
                    const top = rankedSources(s, network)[0];
                    const href = `/console?episode=${encodeURIComponent(episode.episode_id)}&at=${encodeURIComponent(s.ts)}`;
                    return (
                      <tr key={s.fingerprint} onClick={() => router.push(href)}>
                        <td className="mono"><Link href={href} aria-label={`Open the belief of ${full(s.ts)} in the console`}>{hm(s.ts)}</Link></td>
                        <td className="num">{pct(s.p_event)}</td>
                        <td>{outfallName(network, top)?.outfall_id ?? top} <span className="num" style={{ color: "var(--faint)" }}>{pct(givenEvent(s, top))}</span></td>
                        <td className="mono" style={{ color: "var(--faint)", fontSize: 11 }} title={s.fingerprint}>{shortFingerprint(s.fingerprint)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
