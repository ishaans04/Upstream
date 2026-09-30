// Domain types for what the Core API returns.
//
// The endpoint shapes are generated from the API's OpenAPI schema into
// lib/api-schema.ts (`npm run types`), and a Python test fails when that schema drifts
// from the running code. The belief blobs inside a snapshot (marginals, zone windows,
// PROBE candidates, the explanation) are JSON columns the schema only knows as
// objects, so their shape is written out here, from the kernel that produces them.

export type Stream = "live" | "sim";

export type EpisodeState =
  | "SUSPECTED" | "PROBABLE" | "CONFIRMED" | "RESOLVED" | "RETRACTED" | "EXPIRED";

/** PULSE: one zone's exposure (services/kernel/upstream_kernel/pulse.py). Epoch seconds. */
export type ZoneExposure = {
  zone_id: string;
  p_peak: number;
  window_lo: number | null;
  window_hi: number | null;
  pathways: string[];
  t_grid?: number[];
  p_exposed?: number[];
};

/** PROBE: a place worth sampling next (services/kernel/upstream_kernel/probe.py). */
export type ProbeCandidate = {
  candidate_id: string;
  node_id: string;
  window_start: number;
  window_end: number;
  methods: string[];
  mode: "protect" | "enforce";
  ec2_gain: number;
  gain_per_cost: number;
  walk_cost_s: number;
  expected_effect: string;
};

export type EvidenceLink = { event_id: string; log_evidence: number; relative_to_rival: number };

/** The computed explanation (trace.explain): which evidence moved each candidate. */
export type Explanation = {
  p_event?: number;
  fingerprint?: string;
  kernel_version?: string;
  candidates?: {
    rank: number;
    entry_id: string;
    probability: number;
    node_path?: string[];
    supported_by: EvidenceLink[];
    eliminated_rivals_by: EvidenceLink[];
  }[];
};

export type Snapshot = {
  ts: string;
  fingerprint: string;
  as_of_seq: number;
  p_event: number;
  source_marginals: Record<string, number>;
  zone_windows: Record<string, ZoneExposure>;
  probe_candidates: ProbeCandidate[];
  explanation: Explanation;
  kernel_version: string;
  network_version: string;
  params_version: string;
};

export type TimelinePoint = { ts: string; p_event: number; fingerprint: string; as_of_seq: number };

export type EpisodeSummary = {
  episode_id: string;
  state: EpisodeState;
  opened_at: string;
  state_changed_at: string;
  clinical_window_end: string | null;
  p_event: number | null;
  top_sources: [string, number][];
  zone_windows: Record<string, ZoneExposure>;
  fingerprint: string | null;
};

export type EvidencePayload = {
  node_id: string;
  method: string;
  result: "positive" | "negative" | "quantitative";
  value?: number | null;
  unit?: string | null;
  observer_id?: string;            // withheld from public reads (PRD 14.2)
  observer_type: string;
  mission_id?: string | null;
};

export type EvidenceEvent = {
  event_id: string;
  event_type: "EvidenceRecorded" | "EvidenceRetracted";
  event_time: string;
  recorded_at: string;
  seq: number;
  payload: EvidencePayload | { retracts_event_id: string; reason: string; retracted_by: string };
};

export type EpisodeDetail = Omit<EpisodeSummary, "zone_windows"> & {
  stream: Stream;
  est_start_lo: string | null;
  est_start_hi: string | null;
  zone_windows: Record<string, ZoneExposure>;
  version: number;
  explanation: Explanation;
  source_marginals: Record<string, number>;
  probe_candidates: ProbeCandidate[];
  belief_ts: string | null;
  evidence: EvidenceEvent[];
  notice: string;
};

type Feature<P, G = { type: string; coordinates: unknown }> = { type: "Feature"; geometry: G; properties: P };
type FC<P, G = { type: string; coordinates: unknown }> = { type: "FeatureCollection"; features: Feature<P, G>[] };
type Point = { type: "Point"; coordinates: [number, number] };

export type NetworkGeoJSON = {
  network_version: string;
  catchment_id: string;
  nodes: FC<{ node_id: string; node_type: string }, Point>;
  edges: FC<{ edge_id: string; from_node: string; to_node: string; length_m: number; mean_flow_m3s: number },
    { type: "LineString"; coordinates: [number, number][] }>;
  outfalls: FC<{ outfall_id: string; node_id: string; source_type: string; base_rate: number; is_synthetic: boolean }, Point>;
  zones: FC<{ zone_id: string; node_id: string; name: string; pathways: string[]; population_upper_bound: number },
    { type: "Polygon" | "MultiPolygon"; coordinates: unknown }>;
};

export type Mission = {
  mission_id: string;
  episode_id: string;
  node_id: string;
  window_start: string;
  window_end: string;
  methods: string[];
  mode: string;
  status: "created" | "accepted" | "completed" | "declined" | "expired";
  assignee_id: string | null;
  realised_gain: number | null;
  stream?: Stream;
  expected_effect?: string;
  walk_cost_s?: number | null;
  summary?: string;
  lon?: number | null;
  lat?: number | null;
};

export type MissionFeedback = {
  mission_id: string;
  status: string;
  realised_gain: number | null;
  sources_before: number | null;
  sources_after: number | null;
  effect: string;
};

export type ClinicalResult = {
  area_code: string;
  syndrome: string;
  method: string;
  p_value: number;
  effect_size: number | null;
  n_days: number;
  computed_at: string;
};

export type PublicHealthEpisode = {
  episode_id: string;
  state: EpisodeState;
  opened_at: string;
  clinical_window_end: string | null;
  zone_windows: Record<string, ZoneExposure>;
  pathways: string[];
  clinical_results: ClinicalResult[];
  notice: string;
};

/** Exactly what the mission PWA submits (POST /ingest/report/confirm). */
export type MissionSubmission = {
  mission_id: string;
  node_id: string;
  method: string;
  result: "positive" | "negative";
  observer_id: string;
  observed_at: string;          // stamped on the device when the strip was read (GC-4)
  idempotency_key: string;      // the event id; a retry cannot double-count (NFR-9)
};
