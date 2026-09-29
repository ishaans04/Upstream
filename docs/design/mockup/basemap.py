"""OSM basemap extract for the mockup: buildings (with heights), roads, water, green.

Rounded to 5 decimals (about a metre) and packed as flat arrays so a few tens of
thousands of buildings fit comfortably inside one page.
"""
import json
import pathlib
import sys
import time

import requests

S, W, N, E = 28.545, 77.195, 28.600, 77.262
OUT = pathlib.Path(sys.argv[1])
URLS = ["https://overpass.kumi.systems/api/interpreter", "https://overpass-api.de/api/interpreter"]
Q = f"""[out:json][timeout:240];
(
  way["building"]({S},{W},{N},{E});
  way["highway"~"^(motorway|trunk|primary|secondary|tertiary|residential|unclassified|living_street)$"]({S},{W},{N},{E});
  way["natural"="water"]({S},{W},{N},{E});
  way["water"]({S},{W},{N},{E});
  way["leisure"~"^(park|garden|playground|pitch|golf_course)$"]({S},{W},{N},{E});
  way["landuse"~"^(grass|recreation_ground|forest|cemetery)$"]({S},{W},{N},{E});
);
out geom;"""


def fetch():
    for u in URLS:
        for attempt in range(3):
            try:
                r = requests.post(u, data={"data": Q}, timeout=300, headers={"User-Agent": "upstream-onehealth/0.1 (catchment mockup basemap; github.com/ishaans04/Upstream)"})
                if r.ok:
                    return r.json()
                print(u, r.status_code, r.text[:200])
            except Exception as exc:
                print(u, exc)
            time.sleep(10)
    raise SystemExit("no Overpass endpoint answered")


cache = OUT / "osm_raw.json"
data = json.loads(cache.read_text()) if cache.exists() else fetch()
cache.write_text(json.dumps(data))


def ring(el):
    pts, last = [], None
    for g in el.get("geometry", []):
        p = (round(g["lon"], 5), round(g["lat"], 5))
        if p != last:
            pts.append(p)
            last = p
    return pts


def height(t):
    for k in ("height", "building:height"):
        v = t.get(k)
        if v:
            try:
                return float(str(v).split()[0].replace("m", "")), True
            except ValueError:
                pass
    lv = t.get("building:levels")
    if lv:
        try:
            return float(lv) * 3.2 + 1.5, True
        except ValueError:
            pass
    return 10.0, False                      # a typical three-storey Delhi colony house


buildings, roads, water, green = [], [], [], []
ROAD_W = {"motorway": 5, "trunk": 5, "primary": 4, "secondary": 3, "tertiary": 2}
for el in data["elements"]:
    t = el.get("tags", {})
    pts = ring(el)
    if len(pts) < 2:
        continue
    flat = [c for p in pts for c in p]
    if "building" in t and len(pts) >= 4:
        h, known = height(t)
        buildings.append([round(h, 1), 1 if known else 0, flat])
    elif "highway" in t:
        roads.append([ROAD_W.get(t["highway"], 1), t.get("name", ""), flat])
    elif t.get("natural") == "water" or "water" in t:
        if len(pts) >= 4:
            water.append(flat)
    elif len(pts) >= 4:
        green.append([t.get("name", ""), flat])

out = {"bbox": [W, S, E, N], "buildings": buildings, "roads": roads, "water": water, "green": green}
(OUT / "basemap.json").write_text(json.dumps(out, separators=(",", ":")))
print({k: len(v) for k, v in out.items() if k != "bbox"},
      round((OUT / "basemap.json").stat().st_size / 1e6, 2), "MB",
      "heights known", sum(b[1] for b in buildings))
