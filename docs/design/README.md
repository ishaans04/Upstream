# Upstream UI design

The approved look for the web app (Phase 10). The clickable mockup lives in
`mockup/`; every colour and component the real `web/` build uses comes from it.

## Palette

| Token | Value | Use |
|---|---|---|
| `--bg` | `#0F1012` | Page ground (flat near-black) |
| `--bg-2` | `#0C0D0F` | Map ground, deepest panels |
| `--surface` | `#151619` | Cards |
| `--surface-2` | `#1B1C20` | Hover, inner panels |
| `--surface-3` | `#26272B` | Bar and meter tracks |
| `--line` | `rgba(255,255,255,.08)` | Card borders |
| `--line-soft` | `rgba(255,255,255,.06)` | Dividers inside cards |
| `--text` | `#F3F2EE` | Titles, big numbers |
| `--muted` | `#C3C3BF` | Supporting text |
| `--faint` | `#9A9CA0` | Mono caps labels, small notes |
| `--ochre` (amber) | `#F2A33A` | Accent: bars, active states, likely route, badges |
| `--rust` (red) | `#E5533D` | Contamination seen; most likely source stripe |
| `--sage` (green) | `#7FA37A` | Checked, looked normal; evidence stripe |
| `--slate` | `#7D8A93` | Zones stripe |
| `--water` (steel blue) | `#4F8FB5` | Drains on the map |
| `--live` | `#6FBF73` | Header status dot |

Every text colour is at least 4.5:1 on `--bg`, `--surface` and `--surface-2`
(text 15:1, muted 9.6:1, faint 6.2:1, amber 8.2:1, red 4.6:1 on the lightest).

## Components

- **Stat cards**: filled `--surface`, 1px `--line` border, 3px left stripe in the
  card's semantic colour (amber event, red source, slate zones, green evidence), a
  small line icon beside the mono caps label.
- **Map**: dark ground, neutral grey buildings under neutral light, steel-blue drains,
  amber route (brighter with probability), zone trackers as concentric amber rings
  around a dot that runs red (exposure now) to amber (later). Controls on
  `rgba(12,13,15,.9)`; the active control has an amber border.
- **Badges**: PROBABLE is solid amber with dark text. **Chips**: SYNTHETIC is a solid
  hairline outline, uppercase mono.
- **Sidebar**: same ground as the page; the active item has an amber left border and
  amber label.

## Rebuilding the mockup

```bash
uv run --python 3.12 python docs/design/mockup/basemap.py <out-dir>      # OSM extract
uv run --python 3.12 python docs/design/mockup/export.py <out-dir> 183   # kernel episode
uv run --python 3.12 python docs/design/mockup/build.py bench/results/summary.json
```

The scripts were written for a scratch directory and read their inputs from the
working directory; `export.py` needs the Overpass settings noted in its header to
hit the OSM cache.
