"use client";
// The drain network in 3D (FR-36). deck.gl draws probability along the real reaches
// over a self-hosted OSM basemap, so no tile-server key is needed (lib/basemap.ts).
//
// The canvas is not the only way to read the map. The same belief is listed as text
// below it (outfalls with their probabilities, zones with their status), which is what
// a screen reader gets and what a browser without WebGL shows (GC-14).
import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import {
  corridor, downstreamPaths, exposureColour, givenEvent, isExposed, nodeCoords, outerRing,
  rankedSources, ringCentroid, zoneStatus, type EvidenceRow, type ZoneStatus,
} from "@/lib/belief";
import { hm, pct, SOURCE_TYPE } from "@/lib/format";
import { zoneLabel } from "@/lib/places";
import type { NetworkGeoJSON, Snapshot, ZoneExposure } from "@/lib/types";
import { SyntheticBadge } from "./SyntheticBadge";

const MapCanvas = lazy(() => import("./MapCanvas"));

export type ViewState = { longitude: number; latitude: number; zoom: number; pitch: number; bearing: number; transitionDuration?: number };
export const HOME: ViewState = { longitude: 77.2345, latitude: 28.5805, zoom: 14.15, pitch: 52, bearing: -22 };

export type Reach = { edge_id: string; path: [number, number][]; p: number; colour: [number, number, number, number] };
export type ZoneView = {
  zone_id: string; name: string; ring: [number, number][]; centre: [number, number];
  status: ZoneStatus; window: ZoneExposure | null; population: number; pathways: string[];
};

/** Every reach with the chance the contamination passed along it, and its colour. */
export function reachData(net: NetworkGeoJSON, s: Pick<Snapshot, "source_marginals" | "p_event">,
                          paths = downstreamPaths(net)): Reach[] {
  const w = corridor(s, net, paths);
  return net.edges.features.map((e) => {
    const p = Math.min(1, w.get(e.properties.edge_id) ?? 0);
    return { edge_id: e.properties.edge_id, path: e.geometry.coordinates, p, colour: exposureColour(p) };
  });
}

export function zoneData(net: NetworkGeoJSON, s: Pick<Snapshot, "zone_windows">, evidence: EvidenceRow[],
                         coords = nodeCoords(net)): ZoneView[] {
  const seen = evidence.filter((e) => !e.retracted).map((e) => e.payload);
  return net.zones.features.map((f) => {
    const z = f.properties;
    const centre = ringCentroid(f.geometry.coordinates);
    return {
      zone_id: z.zone_id, name: zoneLabel(z.name, centre), ring: outerRing(f.geometry.coordinates), centre,
      status: zoneStatus(z, s, seen, net, coords),
      window: isExposed(s, z.zone_id) ? s.zone_windows[z.zone_id] : null,
      population: z.population_upper_bound, pathways: z.pathways,
    };
  });
}

function webglAvailable(): boolean {
  try {
    const c = document.createElement("canvas");
    return !!(c.getContext("webgl2") || c.getContext("webgl"));
  } catch {
    return false;
  }
}

type Props = {
  network: NetworkGeoJSON;
  snapshot: Snapshot | null;
  evidence: EvidenceRow[];
  mode?: "console" | "hero";
};

export function NetworkMap({ network, snapshot, evidence, mode = "console" }: Props) {
  const [gl, setGl] = useState<boolean | null>(null);
  const [view, setView] = useState<ViewState>(mode === "hero" ? { ...HOME, zoom: 13.55, pitch: 56, bearing: -28 } : HOME);
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    setGl(webglAvailable());
    setReduced(window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  }, []);

  const paths = useMemo(() => downstreamPaths(network), [network]);
  const coords = useMemo(() => nodeCoords(network), [network]);
  const empty = { source_marginals: {}, p_event: 1, zone_windows: {} };
  const s = snapshot ?? empty;
  const reaches = useMemo(() => reachData(network, s, paths), [network, s, paths]);
  const zones = useMemo(() => zoneData(network, s, evidence, coords), [network, s, evidence, coords]);
  const ranked = useMemo(() => rankedSources(s, network), [s, network]);

  const move = (patch: Partial<ViewState>) =>
    setView((v) => ({ ...v, ...patch, transitionDuration: reduced ? 0 : 450 }));
  const focusRoute = () => {
    let x = 0, y = 0, n = 0;
    for (const r of reaches) if (r.p > 0.4) for (const [a, b] of r.path) { x += a; y += b; n += 1; }
    if (n) move({ longitude: x / n, latitude: y / n, zoom: 15, pitch: 55 });
  };

  const canvas = gl === null ? null : gl ? (
    <Suspense fallback={null}>
      <MapCanvas network={network} snapshot={snapshot} evidence={evidence} reaches={reaches} zones={zones}
                 coords={coords} view={view} onView={setView} interactive={mode === "console"} reduced={reduced} />
    </Suspense>
  ) : <div className="map-fallback">The 3D map needs WebGL, which this browser does not provide. The table below lists everything it would show.</div>;

  if (mode === "hero") {
    return <div className="deck-box deck-hero" role="img"
                aria-label="3D view of South Delhi with the Barapullah drain system and the most likely contamination route highlighted">{canvas}</div>;
  }

  return (
    <>
      <div className="deck-box deck-console" role="application"
           aria-label="3D map of the Barapullah drain system. Use the buttons to zoom, tilt and reset the view.">
        {canvas}
        <div className="map-place"><b>Kushak Nallah → Barapulla Nala</b><span>South Delhi to the Yamuna at Sarai Kale Khan</span></div>
        <div className="map-tools" role="toolbar" aria-label="Map view">
          <button type="button" aria-label="Zoom in" title="Zoom in" onClick={() => move({ zoom: Math.min(18, view.zoom + 0.8) })}>+</button>
          <button type="button" aria-label="Zoom out" title="Zoom out" onClick={() => move({ zoom: Math.max(11.5, view.zoom - 0.8) })}>−</button>
          <div className="sep" />
          <button type="button" aria-label="Switch between 3D and flat view" aria-pressed={view.pitch > 5} title="3D / flat"
                  onClick={() => move({ pitch: view.pitch > 5 ? 0 : 52 })}>3D</button>
          <button type="button" aria-label="Rotate left" title="Rotate left" onClick={() => move({ bearing: view.bearing - 30 })}>↺</button>
          <button type="button" aria-label="Rotate right" title="Rotate right" onClick={() => move({ bearing: view.bearing + 30 })}>↻</button>
          <div className="sep" />
          <button type="button" aria-label="Fly to the likely contamination route" title="Fly to the likely route" onClick={focusRoute}>◎</button>
          <button type="button" aria-label="Reset the view" title="Reset view" onClick={() => move({ ...HOME })}>⌂</button>
        </div>
        <div className="map-hint">Trackers mark zones expecting exposure · buildings from OpenStreetMap</div>
      </div>
      <div className="legend" aria-label="Map legend">
        <span><i className="sw-line" style={{ background: "#4f8fb5" }} />Drain</span>
        <span><i className="sw-line" style={{ background: "var(--ochre)" }} />Likely contamination route</span>
        <span><i className="sw" style={{ border: "2px solid var(--ochre-2)", background: "transparent" }} />Outfall, sized by probability</span>
        <span><i className="sw" style={{ background: "var(--rust)" }} />Contamination seen</span>
        <span><i className="sw" style={{ border: "2px solid var(--sage)" }} />Checked, looked normal</span>
        <span><i className="sw" style={{ background: "var(--rust)", boxShadow: "0 0 0 3px var(--bg-2),0 0 0 4.5px var(--ochre-2)" }} />Zone tracker: ring size is the chance of exposure, colour how soon</span>
        <span><i className="sw-sq" style={{ border: "1.5px dashed var(--faint)" }} />Not enough evidence here</span>
        <span><span className="synthetic" aria-hidden="true">SYNTHETIC</span> outfall locations are illustrative</span>
      </div>
      <ul className="outfall-chips" aria-label="Outfalls, most likely first">
        {ranked.map((node) => {
          const o = network.outfalls.features.find((f) => f.properties.node_id === node)!.properties;
          return (
            <li key={node} title={SOURCE_TYPE[o.source_type] ?? o.source_type}>
              <span>{o.outfall_id} {pct(givenEvent(s, node))}</span>
              {o.is_synthetic && <SyntheticBadge />}
            </li>
          );
        })}
      </ul>
      <details className="note" style={{ marginTop: 10 }}>
        <summary style={{ cursor: "pointer" }}>Every zone, as text</summary>
        <div style={{ marginTop: 10 }}>
          <ul aria-label="Zones and what the belief says about them" style={{ margin: 0, paddingLeft: 18, columns: "260px" }}>
            {[...zones].sort((a, b) => rankStatus(a.status) - rankStatus(b.status)).slice(0, 40).map((z) => (
              <li key={z.zone_id}>
                {z.name}:{" "}
                {z.status === "exposed" && z.window
                  ? <span>exposure expected {hm(z.window.window_lo!)}–{hm(z.window.window_hi!)} ({pct(z.window.p_peak)})</span>
                  : z.status === "clear" ? <span style={{ color: "var(--sage-text)" }}>no exposure expected</span>
                    : <span className="zone-row-nodata" data-testid="zone-no-data">Not enough evidence here</span>}
              </li>
            ))}
          </ul>
        </div>
      </details>
    </>
  );
}

const rankStatus = (s: ZoneStatus) => (s === "exposed" ? 0 : s === "clear" ? 1 : 2);
