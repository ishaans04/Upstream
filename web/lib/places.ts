// OSM leaves many small parks unnamed and the zone compiler labels them "park 32".
// A resident says where they are by the neighbourhood, so the console does too.
const PLACES: [string, number, number][] = [
  ["Lodhi Garden", 77.2197, 28.5933], ["Lodhi Colony", 77.2235, 28.5815], ["Jangpura", 77.241, 28.5827],
  ["Nizamuddin", 77.2476, 28.5893], ["Humayun's Tomb", 77.2507, 28.5933], ["Sarai Kale Khan", 77.2585, 28.587],
  ["Defence Colony", 77.232, 28.573], ["Lajpat Nagar", 77.2433, 28.5677], ["Green Park", 77.207, 28.559],
  ["Safdarjung Enclave", 77.1985, 28.565], ["Andrews Ganj", 77.224, 28.5665], ["Chirag Delhi", 77.227, 28.5465],
];
export const MAP_PLACES = PLACES;

const M_PER_DEG: [number, number] = [111320 * Math.cos((28.58 * Math.PI) / 180), 110540];
export const metres = (a: [number, number], b: [number, number]) =>
  Math.hypot((a[0] - b[0]) * M_PER_DEG[0], (a[1] - b[1]) * M_PER_DEG[1]);

export function nearestPlace(p: [number, number]): string {
  let best = "", d = Infinity;
  for (const [name, x, y] of PLACES) {
    const m = metres(p, [x, y]);
    if (m < d) { d = m; best = name; }
  }
  return best;
}

const UNNAMED = /^(park|playground|garden|dog_park|nature_reserve|allotments|recreation_ground|zone)[ _]?\d+$/i;

export function zoneLabel(name: string | null | undefined, centre: [number, number]): string {
  const m = UNNAMED.exec(name || "");
  if (!m) return name || "Unnamed zone";
  const kind = m[1].replace(/_/g, " ");
  return `${kind[0].toUpperCase()}${kind.slice(1)} near ${nearestPlace(centre)}`;
}

/** upstream_shared/ids.py `zone_group_id`, the health zone's area code for a zone. Keep in step. */
export function zoneGroupId(zoneId: string): string {
  const slug = zoneId.replace(/[^A-Za-z0-9.-]/g, "-").toLowerCase().slice(0, 64).replace(/^-+|-+$/g, "") || "unknown";
  return `${slug.startsWith("zone-") ? slug : `zone-${slug}`}-population`;
}
