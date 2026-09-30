"use client";
// The volunteer's list (FR-38). The volunteer id is remembered on this phone only; the
// PRD keeps volunteers to a coarse area and a name they chose (14.2), so there is no
// account to sign in to. Readings still waiting for signal are listed here too.
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { getMyMissions } from "@/lib/api";
import { hm } from "@/lib/format";
import { flushQueue, readFailed, readQueue, type Failed, type Queued } from "@/lib/offline";
import type { Mission } from "@/lib/types";

export const VOLUNTEER_KEY = "upstream.volunteer";

export function useVolunteer(): [string | null, (v: string | null) => void] {
  const [id, setId] = useState<string | null>(null);
  useEffect(() => { try { setId(localStorage.getItem(VOLUNTEER_KEY)); } catch { /* private mode */ } }, []);
  const set = (v: string | null) => {
    try { if (v) localStorage.setItem(VOLUNTEER_KEY, v); else localStorage.removeItem(VOLUNTEER_KEY); } catch { /* ignore */ }
    setId(v);
  };
  return [id, set];
}

const STATUS: Record<string, string> = {
  created: "New", accepted: "Accepted", completed: "Done", declined: "Declined", expired: "Closed",
};

export function MissionsHome() {
  const [volunteer, setVolunteer] = useVolunteer();
  const [draft, setDraft] = useState("");
  const [missions, setMissions] = useState<Mission[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [queue, setQueue] = useState<Queued[]>([]);
  const [failed, setFailed] = useState<Failed[]>([]);

  const refresh = useCallback(async () => {
    setQueue(await readQueue().catch(() => []));
    setFailed(await readFailed().catch(() => []));
    if (!volunteer) return;
    try { setMissions(await getMyMissions(volunteer, true)); setError(null); }
    catch (e) { setError(navigator.onLine ? (e as Error).message : "No signal. Showing nothing new until you are back online."); }
  }, [volunteer]);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 15_000);
    window.addEventListener("online", refresh);
    return () => { clearInterval(t); window.removeEventListener("online", refresh); };
  }, [refresh]);

  if (!volunteer) {
    return (
      <div className="mission-shell">
        <form className="screen" onSubmit={(e) => { e.preventDefault(); if (draft.trim()) setVolunteer(draft.trim()); }}>
          <div className="step">Volunteer</div>
          <h2>Who is checking?</h2>
          <div className="field">
            <label htmlFor="vid">Your volunteer id</label>
            <input id="vid" autoComplete="off" value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="vol-sim-03" />
          </div>
          <p className="note" style={{ margin: 0 }}>Kept on this phone only. Missions are offered by area and time, never by your location.</p>
          <button className="btn btn-primary big" type="submit" disabled={!draft.trim()}>Show my missions</button>
        </form>
      </div>
    );
  }

  const open = (missions ?? []).filter((m) => m.status === "created" || m.status === "accepted");
  const past = (missions ?? []).filter((m) => !(m.status === "created" || m.status === "accepted"));
  return (
    <div className="mission-shell">
      <div className="screen">
        <div className="step">Signed in on this phone as {volunteer}</div>
        <h2>{open.length ? `${open.length} mission${open.length > 1 ? "s" : ""} for you` : "No mission for you right now"}</h2>
        {error && <p className="note" role="status" style={{ margin: 0 }}>{error}</p>}
        {missions === null && !error && <p className="note" role="status" style={{ margin: 0 }}>Looking for missions…</p>}
        <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "grid", gap: 8 }} aria-label="Open missions">
          {open.map((m) => (
            <li key={m.mission_id}>
              <Link className="ep-btn" href={`/missions/${encodeURIComponent(m.mission_id)}`}>
                <span className="id">{m.mission_id} · {m.node_id}</span>
                <span className="mono" style={{ fontSize: 12 }}>{STATUS[m.status]}</span>
                <span className="meta">Go between {hm(m.window_start)} and {hm(m.window_end)}</span>
              </Link>
            </li>
          ))}
        </ul>
        {queue.length > 0 && (
          <div className="offline" role="status">
            {queue.length} reading{queue.length > 1 ? "s" : ""} saved on this phone, waiting for signal.
            <button className="btn btn-quiet btn-sm" type="button" onClick={() => flushQueue().then(refresh)}>Send now</button>
          </div>
        )}
        {failed.length > 0 && (
          <p className="error-note" role="alert">
            {failed.length} reading{failed.length > 1 ? "s were" : " was"} refused by the server ({failed[0].error}). They are kept on
            this phone; tell the coordinator.
          </p>
        )}
        {past.length > 0 && (
          <details>
            <summary style={{ cursor: "pointer" }} className="note">Earlier missions ({past.length})</summary>
            <ul style={{ margin: "8px 0 0", paddingLeft: 18 }}>
              {past.map((m) => (
                <li key={m.mission_id}><Link href={`/missions/${encodeURIComponent(m.mission_id)}`}>{m.mission_id}</Link> · {STATUS[m.status] ?? m.status}</li>
              ))}
            </ul>
          </details>
        )}
        <button className="btn btn-quiet btn-sm" type="button" style={{ justifySelf: "start" }} onClick={() => setVolunteer(null)}>Not {volunteer}?</button>
      </div>
    </div>
  );
}
