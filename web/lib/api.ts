// The typed client. Every function is one Core API call; the web app computes nothing
// the API does not already know, it only reads.
import { API_BASE, STREAM } from "./config";
import type {
  EpisodeDetail, EpisodeSummary, Mission, MissionFeedback, NetworkGeoJSON,
  PublicHealthEpisode, Snapshot, Stream, TimelinePoint,
} from "./types";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { Accept: "application/json", ...(init?.body ? { "Content-Type": "application/json" } : {}), ...init?.headers },
  });
  if (!r.ok) {
    let detail = r.statusText;
    try { detail = JSON.stringify((await r.json()).detail ?? detail); } catch { /* not JSON */ }
    throw new ApiError(r.status, detail);
  }
  return r.json() as Promise<T>;
}

const q = (params: Record<string, string | number | undefined>) =>
  "?" + new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined)
    .map(([k, v]) => [k, String(v)])).toString();

/** FR-37: the belief as it stood at `at` -- the latest snapshot no later than it. */
// A snapshot's own `ts` goes back exactly as the API wrote it. The API keeps
// microseconds and a Date keeps milliseconds, so rounding it through a Date asks for
// the instant before the snapshot and replays the previous belief.
export const getReplay = (at: Date | string, stream: Stream = STREAM) =>
  call<Snapshot>(`/replay${q({ at: typeof at === "string" ? at : at.toISOString(), stream })}`);

export const getTimeline = (since?: Date | string, stream: Stream = STREAM) =>
  call<TimelinePoint[]>(`/replay/timeline${q({ stream, since: since ? new Date(since).toISOString() : undefined, limit: 2000 })}`);

export const getEpisodes = (stream: Stream = STREAM) =>
  call<EpisodeSummary[]>(`/episodes${q({ stream })}`);

export const getEpisode = (id: string, stream: Stream = STREAM) =>
  call<EpisodeDetail>(`/episodes/${encodeURIComponent(id)}${q({ stream })}`);

export const getNetwork = () => call<NetworkGeoJSON>("/network/geojson");

export const getPublicHealth = (stream: Stream = STREAM) =>
  call<{ notice: string; episodes: PublicHealthEpisode[] }>(`/public-health/episodes${q({ stream })}`);

export type ClinicalZone = { area_code: string; population: number | null; t_grid: number[]; p_exposed: number[];
  window_lo: number | null; window_hi: number | null; pathways: string[] };
/** Exposure curves as the health zone receives them: no source, no evidence (FR-34). */
export const getClinicalEpisodes = (stream: Stream = STREAM) =>
  call<{ episodes: { episode_id: string; zones: Record<string, ClinicalZone> }[] }>(`/clinical/episodes${q({ stream })}`);

export const getMyMissions =(volunteerId: string, includeClosed = false) =>
  call<Mission[]>(`/missions/mine${q({ volunteer_id: volunteerId, include_closed: String(includeClosed) })}`);

export const getMission = (id: string) => call<Mission>(`/missions/${encodeURIComponent(id)}`);

export const getMissionFeedback = (id: string) =>
  call<MissionFeedback>(`/missions/${encodeURIComponent(id)}/feedback`);

export const acceptMission = (id: string, volunteerId: string) =>
  call<{ mission_id: string; status: string }>(`/missions/${encodeURIComponent(id)}/accept`,
    { method: "POST", body: JSON.stringify({ volunteer_id: volunteerId }) });

export const declineMission = (id: string, volunteerId: string) =>
  call<{ mission_id: string; status: string }>(`/missions/${encodeURIComponent(id)}/decline`,
    { method: "POST", body: JSON.stringify({ volunteer_id: volunteerId }) });

export const API = { base: API_BASE };
