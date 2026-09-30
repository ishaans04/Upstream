import type { APIRequestContext } from "@playwright/test";

// The e2e suite runs against a real Core API through the web app's own same-origin
// rewrite, on whichever stream the app was built for. `make demo` fills the sim
// stream with an incident; build with NEXT_PUBLIC_STREAM=sim to test against it.
export const STREAM = process.env.E2E_STREAM || "sim";
export const CORE = "/api/core";

export type TimelinePoint = { ts: string; p_event: number; fingerprint: string };
export type MissionRow = { mission_id: string; episode_id: string; status: string; window_end: string };

export async function timeline(request: APIRequestContext, since?: string): Promise<TimelinePoint[]> {
  const params: Record<string, string | number> = { stream: STREAM, limit: 2000 };
  if (since) params.since = since;
  const r = await request.get(`${CORE}/replay/timeline`, { params });
  return r.ok() ? r.json() : [];
}

/** The track the console's slider shows: from a lead-in before the newest episode opened. */
export async function consoleTrack(request: APIRequestContext): Promise<TimelinePoint[]> {
  const r = await request.get(`${CORE}/episodes`, { params: { stream: STREAM } });
  const episodes: { opened_at: string }[] = r.ok() ? await r.json() : [];
  if (!episodes.length) return [];
  const LEAD_IN_MS = 2 * 3600 * 1000;                     // components/ConsoleLoader.tsx
  return timeline(request, new Date(Date.parse(episodes[0].opened_at) - LEAD_IN_MS).toISOString());
}

/** An open mission offered to (or already accepted by) this volunteer, or null. */
export async function openMission(request: APIRequestContext, volunteer: string): Promise<MissionRow | null> {
  const r = await request.get(`${CORE}/missions/mine`, { params: { volunteer_id: volunteer } });
  if (!r.ok()) return null;
  const rows: MissionRow[] = await r.json();
  return rows.find((m) => (m.status === "created" || m.status === "accepted") && Date.parse(m.window_end) > Date.now()) ?? null;
}
