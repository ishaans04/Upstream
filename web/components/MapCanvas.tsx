"use client";
// The deck.gl half of NetworkMap, loaded only in a browser with WebGL. Layers follow the
// approved mockup: neutral buildings under neutral light, steel-blue drains, the likely
// route in amber, and a tracker per exposed zone (ring = chance, dot = how soon).
import { AmbientLight, DirectionalLight, LightingEffect, type PickingInfo } from "@deck.gl/core";
import { PathLayer, PolygonLayer, ScatterplotLayer, SolidPolygonLayer, TextLayer } from "@deck.gl/layers";
import DeckGL from "@deck.gl/react";
import { useEffect, useMemo, useState } from "react";
import { givenEvent, type EvidenceRow } from "@/lib/belief";
import { loadBasemap, type Basemap } from "@/lib/basemap";
import { epoch, hm, pct, SOURCE_TYPE } from "@/lib/format";
import { MAP_PLACES } from "@/lib/places";
import type { NetworkGeoJSON, Snapshot } from "@/lib/types";
import type { Reach, ViewState, ZoneView } from "./NetworkMap";

type RGB = [number, number, number];
const C: Record<string, RGB> = {
  ochre: [242, 163, 58], sand: [247, 189, 106], rust: [229, 83, 61], sage: [127, 163, 122],
  drain: [79, 143, 181], road: [40, 41, 45], bldg: [34, 35, 39], water: [16, 26, 34], green: [22, 34, 25], faint: [120, 122, 128],
};
const mix = (a: RGB, b: RGB, t: number): RGB => [0, 1, 2].map((i) => Math.round(a[i] + (b[i] - a[i]) * t)) as RGB;

const lighting = new LightingEffect({
  ambient: new AmbientLight({ color: [238, 241, 246], intensity: 1.0 }),
  sun: new DirectionalLight({ color: [236, 240, 248], intensity: 1.35, direction: [-3, -8, -4] }),
});
const MATERIAL = { ambient: 0.45, diffuse: 0.6, shininess: 16, specularColor: [52, 56, 62] as RGB };
const esc = (s: string) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]!));
const tipStyle = {
  background: "rgba(16,17,19,.96)", color: "#f3f2ee", border: "1px solid rgba(255,255,255,.12)", borderRadius: "8px",
  padding: "8px 10px", font: "12px/1.45 var(--sans)", maxWidth: "280px",
};

type Outfall = { outfall_id: string; node_id: string; source_type: string; is_synthetic: boolean; ll: [number, number] };

type Props = {
  network: NetworkGeoJSON;
  snapshot: Snapshot | null;
  evidence: EvidenceRow[];
  reaches: Reach[];
  zones: ZoneView[];
  coords: Map<string, [number, number]>;
  view: ViewState;
  onView: (v: ViewState) => void;
  interactive: boolean;
  reduced: boolean;
};

export default function MapCanvas({ network, snapshot, evidence, reaches, zones, coords, view, onView, interactive, reduced }: Props) {
  const [base, setBase] = useState<Basemap | null>(null);
  useEffect(() => { loadBasemap().then(setBase).catch(() => setBase(null)); }, []);

  const outfalls: Outfall[] = useMemo(() => network.outfalls.features.map((f) => ({
    ...f.properties, ll: f.geometry.coordinates })), [network]);
  const drains = useMemo(() => network.edges.features.map((f) => f.geometry.coordinates), [network]);
  const s = snapshot ?? { source_marginals: {}, p_event: 1 };
  const key = snapshot?.fingerprint ?? "none";
  const now = snapshot ? epoch(snapshot.ts) : Date.now() / 1000;
  const exposed = zones.filter((z) => z.status === "exposed" && z.window);
  const transitions = reduced ? {} : { getRadius: 350 };

  const layers = [
    base && new SolidPolygonLayer({ id: "water", data: base.water, getPolygon: (d: [number, number][]) => d, getFillColor: C.water }),
    base && new SolidPolygonLayer({ id: "green", data: base.green, getPolygon: (d: [number, number][]) => d, getFillColor: C.green }),
    base && new PathLayer({
      id: "roads", data: base.roads, getPath: (d: Basemap["roads"][number]) => d.path,
      getColor: (d: Basemap["roads"][number]) => (d.w >= 3 ? [56, 57, 62] : C.road),
      getWidth: (d: Basemap["roads"][number]) => ({ 5: 18, 4: 14, 3: 10, 2: 7 } as Record<number, number>)[d.w] || 4,
      widthUnits: "meters", widthMinPixels: 0.6, capRounded: true, jointRounded: true,
    }),
    new PathLayer({ id: "drains", data: drains, getPath: (d: [number, number][]) => d, getColor: C.drain, getWidth: 7,
      widthUnits: "meters", widthMinPixels: 1.6, capRounded: true, jointRounded: true }),
    base && new PolygonLayer({
      id: "buildings", data: base.buildings, getPolygon: (d: Basemap["buildings"][number]) => d.polygon, extruded: true,
      getElevation: (d: Basemap["buildings"][number]) => d.h, getFillColor: C.bldg, stroked: false, material: MATERIAL,
    }),
    new PathLayer({
      id: "route", data: reaches.filter((r) => r.p >= 0.03), getPath: (d: Reach) => d.path, widthUnits: "meters", widthMinPixels: 2,
      getWidth: (d: Reach) => 8 + 30 * d.p, getColor: (d: Reach) => d.colour, capRounded: true, jointRounded: true,
      pickable: interactive, updateTriggers: { getWidth: key, getColor: key },
    }),
    new PolygonLayer({
      id: "zones", data: zones, getPolygon: (d: ZoneView) => d.ring, stroked: true, filled: true, lineWidthMinPixels: 1.5,
      getFillColor: (d: ZoneView) => d.status === "exposed" ? [...C.ochre, 70] : d.status === "clear" ? [...C.sage, 40] : [0, 0, 0, 0],
      getLineColor: (d: ZoneView) => d.status === "exposed" ? C.ochre : d.status === "clear" ? C.sage : C.faint,
      pickable: interactive, updateTriggers: { getFillColor: key, getLineColor: key },
    }),
    new ScatterplotLayer({
      id: "tracker-halo", data: exposed, getPosition: (d: ZoneView) => [d.centre[0], d.centre[1], 18], radiusUnits: "pixels",
      getRadius: (d: ZoneView) => 12 + 14 * d.window!.p_peak, filled: true, stroked: true, lineWidthUnits: "pixels", getLineWidth: 1,
      getFillColor: [...C.ochre, 26], getLineColor: [...C.ochre, 90], billboard: true, updateTriggers: { getRadius: key }, transitions,
    }),
    new ScatterplotLayer({
      id: "trackers", data: exposed, getPosition: (d: ZoneView) => [d.centre[0], d.centre[1], 18], radiusUnits: "pixels",
      getRadius: (d: ZoneView) => 6 + 7 * d.window!.p_peak, filled: false, stroked: true, lineWidthUnits: "pixels", getLineWidth: 1.6,
      getLineColor: [...C.ochre, 230], billboard: true, pickable: interactive, updateTriggers: { getRadius: key }, transitions,
    }),
    new ScatterplotLayer({
      id: "tracker-dot", data: exposed, getPosition: (d: ZoneView) => [d.centre[0], d.centre[1], 18], radiusUnits: "pixels",
      getRadius: 3.8, stroked: true, lineWidthUnits: "pixels", getLineWidth: 1.2, getLineColor: [17, 18, 13, 255], billboard: true,
      pickable: interactive,
      getFillColor: (d: ZoneView) => { const soon = Math.max(0, Math.min(1, (d.window!.window_lo! - now) / (6 * 3600))); return [...mix(C.rust, C.ochre, soon), 255]; },
      updateTriggers: { getFillColor: key },
    }),
    new ScatterplotLayer({
      id: "outfalls", data: outfalls, getPosition: (d: Outfall) => d.ll, radiusUnits: "meters",
      getRadius: (d: Outfall) => 18 + 70 * givenEvent(s, d.node_id), radiusMinPixels: 4, stroked: true, lineWidthMinPixels: 1.6,
      getFillColor: (d: Outfall) => (givenEvent(s, d.node_id) > 0.4 ? C.ochre : [16, 17, 19]), getLineColor: C.sand,
      pickable: interactive, updateTriggers: { getRadius: key, getFillColor: key }, transitions,
    }),
    new ScatterplotLayer({
      id: "evidence", data: evidence.filter((e) => !e.retracted && coords.has(e.payload.node_id)),
      getPosition: (d: EvidenceRow) => coords.get(d.payload.node_id)!, radiusUnits: "meters",
      getRadius: (d: EvidenceRow) => (d.payload.mission_id ? 22 : 16), radiusMinPixels: 4, stroked: true, lineWidthMinPixels: 2,
      getFillColor: (d: EvidenceRow) => (d.payload.result === "positive" ? C.rust : [12, 13, 15]),
      getLineColor: (d: EvidenceRow) => (d.payload.result === "positive" ? [245, 154, 136] : C.sage),
      pickable: interactive, updateTriggers: { getFillColor: key },
    }),
    interactive && new TextLayer({
      id: "outfall-labels", data: outfalls, getPosition: (d: Outfall) => d.ll,
      getText: (d: Outfall) => `${d.outfall_id} ${pct(givenEvent(s, d.node_id))}`, getSize: 12, getColor: [236, 236, 232],
      getPixelOffset: [0, -16], fontFamily: "IBM Plex Mono, monospace", fontWeight: 500, outlineWidth: 3,
      outlineColor: [12, 13, 15, 255], fontSettings: { sdf: true }, billboard: true, updateTriggers: { getText: key },
    }),
    interactive && new TextLayer({
      id: "places", data: MAP_PLACES, getPosition: (d: (typeof MAP_PLACES)[number]) => [d[1], d[2], 60],
      getText: (d: (typeof MAP_PLACES)[number]) => d[0], getSize: 12, getColor: [200, 200, 196, 235],
      fontFamily: "Schibsted Grotesk, Arial, sans-serif", outlineWidth: 3, outlineColor: [12, 13, 15, 255],
      fontSettings: { sdf: true }, billboard: true, characterSet: "auto",
    }),
  ].filter(Boolean);

  const tooltip = ({ object, layer }: PickingInfo) => {
    if (!object || !layer) return null;
    let html: string | null = null;
    if (layer.id === "outfalls") {
      const o = object as Outfall;
      html = `<b>${esc(o.outfall_id)} · ${esc(SOURCE_TYPE[o.source_type] ?? o.source_type)}</b><br>${pct(givenEvent(s, o.node_id), 1)} likely to be the source, given an event${o.is_synthetic ? "<br><span style=\"color:#c3c3bf\">synthetic location</span>" : ""}`;
    } else if (layer.id === "route") {
      html = `${pct((object as Reach).p)} chance the contamination passed along this reach`;
    } else if (layer.id === "zones" || layer.id === "trackers" || layer.id === "tracker-dot") {
      const z = object as ZoneView;
      html = `<b>${esc(z.name)}</b><br>` + (z.status === "exposed" && z.window
        ? `Exposure expected ${hm(z.window.window_lo!)}–${hm(z.window.window_hi!)} (80% window)<br>Chance of exposure ${pct(z.window.p_peak)}`
        : z.status === "clear" ? "No exposure expected" : "Not enough evidence here") + `<br><span style="color:#c3c3bf">up to ${z.population} people</span>`;
    } else if (layer.id === "evidence") {
      const e = object as EvidenceRow;
      html = `<b>${e.payload.result === "positive" ? "Contamination seen" : "Checked, looked normal"}</b><br>${e.payload.mission_id ? "Test strip, mission" : "Citizen report"} at ${hm(e.event_time)}`;
    }
    return html ? { html, style: tipStyle } : null;
  };

  return (
    <DeckGL
      layers={layers}
      viewState={view}
      onViewStateChange={({ viewState }) => onView(viewState as ViewState)}
      controller={interactive ? { dragRotate: true, touchRotate: true, keyboard: true, scrollZoom: { smooth: true } } : false}
      effects={[lighting]}
      getTooltip={interactive ? tooltip : undefined}
      parameters={{ clearColor: [11 / 255, 12 / 255, 14 / 255, 1] } as never}
    />
  );
}
