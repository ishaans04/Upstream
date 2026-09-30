// The self-hosted basemap: an OpenStreetMap extract of the catchment packed as flat
// coordinate arrays (docs/design/mockup/basemap.py). No tile server and no key, and it
// is cached with the app shell, so the map still draws on a phone without signal.
// © OpenStreetMap contributors, ODbL.
export type Basemap = {
  bbox: [number, number, number, number];
  buildings: { h: number; polygon: [number, number][] }[];
  roads: { w: number; path: [number, number][] }[];
  water: [number, number][][];
  green: [number, number][][];
};

type Raw = {
  bbox: [number, number, number, number];
  buildings: [number, boolean, number[]][];
  roads: [number, string, number[]][];
  water: number[][];
  green: [string, number[]][];
};

const pairs = (flat: number[]) => {
  const out: [number, number][] = [];
  for (let i = 0; i < flat.length; i += 2) out.push([flat[i], flat[i + 1]]);
  return out;
};

let cached: Promise<Basemap> | null = null;

export function loadBasemap(url = "/basemap.json"): Promise<Basemap> {
  cached ??= fetch(url)
    .then((r) => { if (!r.ok) throw new Error(`basemap ${r.status}`); return r.json() as Promise<Raw>; })
    .then((raw) => ({
      bbox: raw.bbox,
      buildings: raw.buildings.map(([h, , flat]) => ({ h, polygon: pairs(flat) })),
      roads: raw.roads.map(([w, , flat]) => ({ w, path: pairs(flat) })),
      water: raw.water.map(pairs),
      green: raw.green.map(([, flat]) => pairs(flat)),
    }))
    .catch((e) => { cached = null; throw e; });
  return cached;
}
