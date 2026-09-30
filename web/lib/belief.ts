// Reading a belief: pure functions, no React, so the rules that carry ethical weight
// (PRD 14.4: a zone nobody has looked at is not a clean zone) are tested on their own.
import { metres } from "./places";
import type { EvidenceEvent, EvidencePayload, NetworkGeoJSON, Snapshot } from "./types";

/** A zone counts as exposed from this chance upward (the console and the CDS rule agree). */
export const EXPOSED_P = 0.05;
/** Evidence within this distance of a zone's node says something about the zone. */
export const NEAR_EVIDENCE_M = 700;

type Marginals = Pick<Snapshot, "source_marginals" | "p_event">;

/** P(this outfall | something is happening). The bars and labels all use this. */
export function givenEvent(s: Marginals, nodeId: string): number {
  return (s.source_marginals[nodeId] ?? 0) / Math.max(s.p_event, 1e-12);
}

export function outfallNodes(net: NetworkGeoJSON): string[] {
  return net.outfalls.features.map((f) => f.properties.node_id);
}

/** Outfalls, most probable first. `__none__` and `__diffuse__` are not places. */
export function rankedSources(s: Marginals, net: NetworkGeoJSON): string[] {
  return [...outfallNodes(net)].sort((a, b) => givenEvent(s, b) - givenEvent(s, a));
}

export function nodeCoords(net: NetworkGeoJSON): Map<string, [number, number]> {
  return new Map(net.nodes.features.map((f) => [f.properties.node_id, f.geometry.coordinates]));
}

/** The reaches downstream of each outfall, in order: the network has one outflow per node. */
export function downstreamPaths(net: NetworkGeoJSON): Map<string, string[]> {
  const out = new Map<string, { id: string; to: string }>();
  for (const e of net.edges.features) {
    if (!out.has(e.properties.from_node)) out.set(e.properties.from_node, { id: e.properties.edge_id, to: e.properties.to_node });
  }
  const paths = new Map<string, string[]>();
  for (const start of outfallNodes(net)) {
    const path: string[] = [];
    const seen = new Set<string>();
    let cur = start;
    while (out.has(cur) && !seen.has(cur)) {
      seen.add(cur);
      const e = out.get(cur)!;
      path.push(e.id);
      cur = e.to;
    }
    paths.set(start, path);
  }
  return paths;
}

/** Chance the contamination passed along each reach: every outfall's share, carried down. */
export function corridor(s: Marginals, net: NetworkGeoJSON, paths = downstreamPaths(net)): Map<string, number> {
  const w = new Map<string, number>();
  for (const [node, path] of paths) {
    const p = givenEvent(s, node);
    for (const edge of path) w.set(edge, (w.get(edge) ?? 0) + p);
  }
  return w;
}

/** Amber, deeper and more opaque as the reach becomes more likely. RGBA 0-255. */
export function exposureColour(p: number): [number, number, number, number] {
  const t = Math.max(0, Math.min(1, p));
  const lo = [160, 98, 30], hi = [242, 163, 58];
  return [
    Math.round(lo[0] + (hi[0] - lo[0]) * t),
    Math.round(lo[1] + (hi[1] - lo[1]) * t),
    Math.round(lo[2] + (hi[2] - lo[2]) * t),
    110 + Math.round(145 * t),
  ];
}

export type ZoneStatus = "exposed" | "clear" | "no-data";
type ZoneProps = { zone_id: string; node_id: string };
type Seen = Pick<EvidencePayload, "node_id" | "result">;

export function isExposed(s: Pick<Snapshot, "zone_windows">, zoneId: string): boolean {
  const w = s.zone_windows[zoneId];
  return !!w && w.window_lo !== null && w.p_peak >= EXPOSED_P;
}

/**
 * PRD 14.4. "Clear" needs someone to have looked nearby; without that the honest
 * answer is that we do not know, and the console must say so rather than draw the
 * zone like one the model believes is clean.
 */
export function zoneStatus(zone: ZoneProps, s: Pick<Snapshot, "zone_windows">, seen: Seen[],
                           net: NetworkGeoJSON, coords = nodeCoords(net)): ZoneStatus {
  if (isExposed(s, zone.zone_id)) return "exposed";
  const at = coords.get(zone.node_id);
  if (at && seen.some((e) => { const c = coords.get(e.node_id); return !!c && metres(c, at) < NEAR_EVIDENCE_M; })) {
    return "clear";
  }
  return "no-data";
}

export type EvidenceRow = {
  event_id: string;
  seq: number;
  event_time: string;
  recorded_at: string;
  payload: EvidencePayload;
  retracted: boolean;
  retraction_reason?: string;
};

/**
 * The evidence a belief at `asOfSeq` was built from, oldest first. A retraction later
 * than that belief does not reach back into it; one before it marks the report, which
 * stays listed (GC-5: nothing is deleted, and nothing is hidden).
 */
export function evidenceAsOf(events: EvidenceEvent[], asOfSeq: number): EvidenceRow[] {
  const retractions = new Map<string, string>();
  for (const e of events) {
    if (e.event_type === "EvidenceRetracted" && e.seq <= asOfSeq && "retracts_event_id" in e.payload) {
      retractions.set(e.payload.retracts_event_id, e.payload.reason);
    }
  }
  return events
    .filter((e) => e.event_type === "EvidenceRecorded" && e.seq <= asOfSeq)
    .map((e) => ({
      event_id: e.event_id, seq: e.seq, event_time: e.event_time, recorded_at: e.recorded_at,
      payload: e.payload as EvidencePayload,
      retracted: retractions.has(e.event_id),
      retraction_reason: retractions.get(e.event_id),
    }));
}

/** Episode state as the badge shows it, from the recorded state, never re-derived. */
export const STATE_LABEL: Record<string, string> = {
  SUSPECTED: "Suspected", PROBABLE: "Probable", CONFIRMED: "Confirmed", RESOLVED: "Resolved",
  RETRACTED: "Retracted", EXPIRED: "Expired",
};

/** The outer ring of a Polygon, or of a MultiPolygon's first part. */
export function outerRing(coords: unknown): [number, number][] {
  let r = coords as unknown[];
  while (Array.isArray(r[0]) && Array.isArray((r[0] as unknown[])[0])) r = r[0] as unknown[];
  return r as [number, number][];
}

export function ringCentroid(coords: unknown): [number, number] {
  const pts = outerRing(coords);
  let x = 0, y = 0;
  for (const [a, b] of pts) { x += a; y += b; }
  return [x / pts.length, y / pts.length];
}
