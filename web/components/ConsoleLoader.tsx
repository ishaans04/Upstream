"use client";
// Fetches what the console shows and hands it over. `?episode=` picks an episode and
// `?at=` opens it at a past moment, so a replay row or a shared link reproduces a view.
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useCallback, useMemo } from "react";
import { getEpisode, getEpisodes, getNetwork, getReplay, getTimeline } from "@/lib/api";
import { STATE_LABEL } from "@/lib/belief";
import { full, pct } from "@/lib/format";
import type { TimelinePoint } from "@/lib/types";
import { Console } from "./Console";
import { LoadError, Loading, NoEpisodes } from "./States";
import { useLoad } from "./useLoad";

/** Snapshots from a little before the episode opened: the belief building up to it. */
export const LEAD_IN_MS = 2 * 3600 * 1000;

export function ConsoleLoader() {
  const params = useSearchParams();
  const wanted = params.get("episode");
  const at = params.get("at");

  const net = useLoad(getNetwork, []);
  const list = useLoad(getEpisodes, []);
  const chosen = wanted ?? list.data?.[0]?.episode_id ?? null;
  const ep = useLoad(() => (chosen ? getEpisode(chosen) : Promise.resolve(null)), [chosen]);
  const tl = useLoad(() => (ep.data ? getTimeline(new Date(Date.parse(ep.data.opened_at) - LEAD_IN_MS)) : Promise.resolve([])),
    [ep.data?.episode_id]);
  const load = useCallback((p: TimelinePoint) => getReplay(p.ts), []);
  const initialIndex = useMemo(() => {
    if (!at || !tl.data?.length) return undefined;
    const t = Date.parse(at);
    let k = -1;
    tl.data.forEach((p, i) => { if (Date.parse(p.ts) <= t) k = i; });
    return k >= 0 ? k : 0;
  }, [at, tl.data]);

  if (net.error) return <LoadError what="the drain network" error={net.error} />;
  if (list.error) return <LoadError what="the episodes" error={list.error} />;
  if (list.data && list.data.length === 0) return <div className="page"><NoEpisodes /></div>;
  if (ep.error) return <LoadError what={`episode ${chosen}`} error={ep.error} />;
  if (!net.data || !ep.data || !tl.data || tl.loading) return <Loading what="the belief" />;
  if (tl.data.length === 0) return <div className="page"><NoEpisodes /></div>;

  const others = (list.data ?? []).slice(0, 8);
  const picker = others.length > 1 && (
    <div className="card">
      <div className="card-head"><h2>Episodes</h2><span className="aside">newest first</span></div>
      <nav className="ep-list" aria-label="Episodes">
        {others.map((e) => (
          <Link key={e.episode_id} className="ep-btn" href={`/console?episode=${encodeURIComponent(e.episode_id)}`}
                aria-current={e.episode_id === ep.data!.episode_id ? "true" : undefined}>
            <span className="id">{e.episode_id}</span>
            <span className="mono" style={{ fontSize: 12 }}>{e.p_event != null ? pct(e.p_event) : ""}</span>
            <span className="meta">{STATE_LABEL[e.state] ?? e.state} · opened {full(e.opened_at)}</span>
          </Link>
        ))}
      </nav>
    </div>
  );

  return <Console network={net.data} episode={ep.data} timeline={tl.data} loadSnapshot={load} initialIndex={initialIndex} aside={picker} />;
}
