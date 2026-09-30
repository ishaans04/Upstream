import type { EpisodeDetail, EvidenceEvent, NetworkGeoJSON, Snapshot, TimelinePoint } from "@/lib/types";

// A toy catchment in South Delhi: two outfalls join at J1 and leave through OUT.
// ZONE_A sits on the junction; ZONE_B is a park about five kilometres away that no
// report has come near.
const P = {
  N1: [77.2, 28.56], N2: [77.21, 28.56], J1: [77.205, 28.565], OUT: [77.205, 28.57],
  Z2N: [77.25, 28.59],
} as const;
const pt = (id: keyof typeof P) => ({ type: "Point" as const, coordinates: [...P[id]] as [number, number] });
const sq = ([x, y]: readonly [number, number]) =>
  [[[x - 0.001, y - 0.001], [x + 0.001, y - 0.001], [x + 0.001, y + 0.001], [x - 0.001, y + 0.001], [x - 0.001, y - 0.001]]];

export const net: NetworkGeoJSON = {
  network_version: "16811181e3006ac9",
  catchment_id: "delhi-barapullah",
  nodes: { type: "FeatureCollection", features: (Object.keys(P) as (keyof typeof P)[]).map((id) => ({
    type: "Feature", geometry: pt(id), properties: { node_id: id, node_type: "junction" } })) },
  edges: { type: "FeatureCollection", features: [
    ["e1", "N1", "J1"], ["e2", "N2", "J1"], ["e3", "J1", "OUT"],
  ].map(([edge_id, a, b]) => ({ type: "Feature", properties: { edge_id, from_node: a, to_node: b, length_m: 800, mean_flow_m3s: 0.4 },
    geometry: { type: "LineString", coordinates: [[...P[a as keyof typeof P]], [...P[b as keyof typeof P]]] as [number, number][] } })) },
  outfalls: { type: "FeatureCollection", features: [
    { type: "Feature", geometry: pt("N1"), properties: { outfall_id: "O1", node_id: "N1", source_type: "storm_outfall", base_rate: 0.01, is_synthetic: false } },
    { type: "Feature", geometry: pt("N2"), properties: { outfall_id: "O2", node_id: "N2", source_type: "cso", base_rate: 0.02, is_synthetic: true } },
  ] },
  zones: { type: "FeatureCollection", features: [
    { type: "Feature", geometry: { type: "Polygon", coordinates: sq(P.J1) },
      properties: { zone_id: "ZONE_A", node_id: "J1", name: "park 32", pathways: ["recreation"], population_upper_bound: 120 } },
    { type: "Feature", geometry: { type: "Polygon", coordinates: sq(P.Z2N) },
      properties: { zone_id: "ZONE_B", node_id: "Z2N", name: "Lodhi Garden lawn", pathways: ["recreation", "animal_contact"], population_upper_bound: 400 } },
  ] },
};

const T0 = Date.parse("2026-09-30T05:00:00Z") / 1000;
const grid = Array.from({ length: 12 }, (_, k) => T0 + k * 1800);

export const snapshots: Snapshot[] = [
  {
    ts: "2026-09-30T05:00:00Z", fingerprint: "sha256:aaaa1111", as_of_seq: 10, p_event: 0.62,
    source_marginals: { N1: 0.372, N2: 0.248, __none__: 0.38, __diffuse__: 0 },
    zone_windows: {}, probe_candidates: [],
    explanation: { candidates: [{ rank: 1, entry_id: "N1", probability: 0.6, supported_by: [{ event_id: "ev-1", log_evidence: -2, relative_to_rival: 0.3 }], eliminated_rivals_by: [] }] },
    kernel_version: "upstream-kernel 0.1.0", network_version: "16811181e3006ac9", params_version: "668570ce0643d642",
  },
  {
    ts: "2026-09-30T05:20:00Z", fingerprint: "sha256:bbbb2222", as_of_seq: 14, p_event: 0.9,
    source_marginals: { N1: 0.36, N2: 0.54, __none__: 0.1, __diffuse__: 0 },
    zone_windows: { ZONE_A: { zone_id: "ZONE_A", p_peak: 0.7, window_lo: T0 + 1800, window_hi: T0 + 9000, pathways: ["recreation"],
      t_grid: grid, p_exposed: grid.map((_, k) => (k >= 1 && k <= 5 ? 0.7 : 0.02)) } },
    probe_candidates: [{ candidate_id: "J1@1", node_id: "J1", window_start: T0 + 1500, window_end: T0 + 5000, methods: ["test_strip"],
      mode: "protect", ec2_gain: 0.2, gain_per_cost: 0.0003, walk_cost_s: 600, expected_effect: "Expected to rule out 1 of the 2 remaining warning patterns." }],
    explanation: { candidates: [{ rank: 1, entry_id: "N2", probability: 0.6,
      supported_by: [{ event_id: "ev-1", log_evidence: -2, relative_to_rival: 0.3 }],
      eliminated_rivals_by: [{ event_id: "ev-2", log_evidence: -0.1, relative_to_rival: -0.05 }] }] },
    kernel_version: "upstream-kernel 0.1.0", network_version: "16811181e3006ac9", params_version: "668570ce0643d642",
  },
];

export const snapAt = (i: number) => snapshots[i];

export const timeline: TimelinePoint[] = snapshots.map((s) => ({
  ts: s.ts, p_event: s.p_event, fingerprint: s.fingerprint, as_of_seq: s.as_of_seq }));

const ev = (event_id: string, seq: number, node_id: string, result: "positive" | "negative",
            observer_type = "citizen", mission_id: string | null = null): EvidenceEvent => ({
  event_id, seq, event_type: "EvidenceRecorded",
  event_time: new Date((T0 - 600 + seq * 60) * 1000).toISOString(),
  recorded_at: new Date((T0 - 590 + seq * 60) * 1000).toISOString(),
  payload: { node_id, method: mission_id ? "test_strip" : "citizen_visual_olfactory", result,
             observer_id: `vol-${seq}`, observer_type, mission_id },
});

export const evidence: EvidenceEvent[] = [
  ev("ev-1", 10, "N1", "positive"),
  ev("ev-2", 11, "J1", "negative", "citizen", "M-1A2B"),
  { event_id: "ret-1", seq: 13, event_type: "EvidenceRetracted",
    event_time: new Date((T0 + 900) * 1000).toISOString(), recorded_at: new Date((T0 + 900) * 1000).toISOString(),
    payload: { retracts_event_id: "ev-1", reason: "reported the wrong drain", retracted_by: "off-1" } },
  ev("ev-3", 14, "N2", "positive"),
];

export const episode: EpisodeDetail = {
  episode_id: "EE-7C31", state: "PROBABLE", stream: "sim",
  opened_at: "2026-09-30T04:58:00Z", state_changed_at: "2026-09-30T05:20:00Z",
  est_start_lo: null, est_start_hi: null, clinical_window_end: "2026-10-16T04:58:00Z",
  p_event: 0.9, top_sources: [["N2", 0.54]], zone_windows: snapshots[1].zone_windows,
  fingerprint: "sha256:bbbb2222", version: 3, explanation: snapshots[1].explanation,
  source_marginals: snapshots[1].source_marginals, probe_candidates: snapshots[1].probe_candidates,
  belief_ts: snapshots[1].ts, evidence, notice: "Environmental context, not a diagnosis.",
};
