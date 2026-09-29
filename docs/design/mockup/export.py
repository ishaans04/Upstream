"""Freeze one real kernel episode on the real network into JSON for the UI mockup."""
import datetime as dt
import json
import sys

import numpy as np
from clinical_stats.baselines import fit_baseline
from clinical_stats.matched_filter import expected_curve, matched_filter_test
from upstream_bench import runner as R
from upstream_kernel.compile.loader import load_network
from upstream_kernel.model.posterior import source_marginals, start_time_credible_interval
from upstream_kernel.physics.params import FLOW_CONDITIONS, default_params
from upstream_kernel.physics.tables import load_tables
from upstream_kernel.probe import probe
from upstream_kernel.pulse import pulse
from upstream_kernel.trace import explain
from upstream_shared.codes import SEWAGE_PATHOGEN_MIX
from upstream_sim.citizens import generate_citizen_reports, sample_at
from upstream_sim.clinical import area_counts, excess_cases
from upstream_sim.run import zone_arrivals
from upstream_sim.scenario import sample_scenario
from upstream_sim.transport_truth import truth_plume

OUT = sys.argv[1]
I = int(sys.argv[2]) if len(sys.argv) > 2 else 0
net = load_network("data/artifacts/network.npz")
tables = load_tables("data/artifacts/tables.npz")
params = default_params()
K = R.Kernel(net, tables, params)
rng = np.random.default_rng(20260922 + I)
sc = sample_scenario(net, rng, now=R.ANCHOR, earliest_h=8.0, latest_h=1.0)
world = np.random.default_rng(sc.seed)
plume = truth_plume(net, sc, world)
reports = generate_citizen_reports(net, plume, sc, world, n=R.N_CITIZENS, now=R.ANCHOR)
trig = next(j for j, x in enumerate(reports) if x["result"] == "positive"
            and x["true_concentration"] > 0.05)
ctx = {"flow_condition": sc.flow_condition, "weather_from": sc.start - dt.timedelta(hours=2)}

# Evidence the operator sees: the last few organic reports up to the trigger, then
# EC2's missions, one every 20 minutes.
known = reports[max(0, trig - 4): trig + 1]
evidence = []
for r in known:
    evidence.append({**r, "kind": "citizen"})
snaps = []
node_of_outfall = {}


def snapshot(t, label):
    post, obs, grid = K.posterior([R._event(x) for x in evidence], now=t, **ctx)
    m = source_marginals(post, net)
    zones = pulse(post, net, tables, params)
    cands = probe(post, net, tables, params, zones, now=t, mode=R.ProbeMode.ENFORCE,
                  max_candidates=3, flow_condition=sc.flow_condition, method="test_strip")
    ex = explain(post, obs, net, grid, tables, params)
    lo, hi = start_time_credible_interval(post, net)
    zw = {}
    for z, w in zones.items():
        tg = w["t_grid"][::3]
        pe = w["p_exposed"][::3]
        zw[z] = {"lo": w["window_lo"], "hi": w["window_hi"], "p_peak": w["p_peak"],
                 "t": [round(x) for x in tg], "p": [round(x, 4) for x in pe],
                 "pathways": w["pathways"]}
    ids = {str(o.event_id): i for i, o in enumerate(obs)}
    for c in ex["candidates"]:
        for key in ("supported_by", "eliminated_rivals_by"):
            for e in c[key]:
                e["evidence_index"] = ids.get(e["event_id"])
    snaps.append({"ts": t.isoformat(), "label": label, "fingerprint": post.fingerprint,
                  "p_event": post.p_event, "evidence_count": len(evidence),
                  "marginals": {k: v for k, v in m.items()},
                  "est_start": [lo, hi], "zones": zw, "probe": cands[:3],
                  "explanation": ex["candidates"]})
    return post


t = known[-1]["observed_at"]
post = snapshot(t, "First report of the incident")
for n in range(6):
    t = t + dt.timedelta(seconds=R.SAMPLE_STEP_S)
    picks = probe(post, net, tables, params, {}, now=t, mode=R.ProbeMode.ENFORCE,
                  max_candidates=1, flow_condition=sc.flow_condition, method="test_strip")
    if not picks:
        break
    node = net.node_index[picks[0]["node_id"]]
    s = sample_at(net, plume, node, t.timestamp(), np.random.default_rng(sc.seed + 7 + n),
                  method="test_strip", observer_id=f"vol-{17 + n * 5:03d}")
    evidence.append({**s, "kind": "mission", "mission_effect": picks[0]["expected_effect"],
                     "expected_gain": picks[0]["ec2_gain"]})
    post = snapshot(t, f"Mission {n + 1}: test strip at {picks[0]['node_id']}")

# Clinical: the most exposed zone, 40 extra cases, the matched filter result day by day.
arr = zone_arrivals(net, plume)
zid = max(arr, key=lambda z: arr[z]["last"] - arr[z]["first"])
crng = np.random.default_rng(99)
truth = arr[zid]
pop = int(net.zone_population[list(net.zone_ids).index(zid)])
exc = excess_cases((truth["first"], truth["last"]), pop, crng, n_cases=40)
eday = dt.datetime.fromtimestamp(truth["first"], dt.UTC).date()
first = eday - dt.timedelta(days=400)
last = eday + dt.timedelta(days=20)
days, base, extra = area_counts(first, last, crng, excess=exc)
counts = (base + extra).astype(float)
counts[counts < 5] = np.nan
b = fit_baseline(days[:400], counts[:400], area_code=zid, syndrome="ag")
z = pulse(post, net, tables, params)[zid]
tg = np.asarray(z["t_grid"])
day0 = dt.datetime.fromtimestamp(tg.min(), dt.UTC).date()
off = (eday - day0).days
shape = expected_curve({"t_grid": tg, "p_exposed": z["p_exposed"], "population": pop},
                       SEWAGE_PATHOGEN_MIX, days=np.arange(off + 21))[off:]
daily = []
for d in range(21):
    r = matched_filter_test(counts[400:400 + d + 1], b, shape, days=days[400:400 + d + 1],
                            episode_id="EE-7C31", area_code=zid, syndrome="ag", n_sim=999)
    daily.append(r.p_value)
clinical = {"zone_id": zid, "exposure_day": eday.isoformat(),
            "days": [dt.date.fromordinal(int(d)).isoformat() for d in days[386:]],
            "counts": [None if np.isnan(c) else int(c) for c in counts[386:]],
            "expected": [round(float(x), 2) for x in b.predict(days[386:])],
            "shape": [0.0] * 14 + [round(float(x), 2) for x in shape],
            "p_by_day": [round(p, 4) for p in daily], "suppressed_below": 5}

# Geometry in lon/lat, straight from the compiled network and the catchment files.
import geopandas as gpd
import osmnx as ox
import upstream_kernel.compile.osm  # noqa: F401 - sets the cache folder
from upstream_kernel.compile.osm import fetch_waterways

# The same settings the compile ran with, so every query is answered from the cache.
ox.settings.overpass_rate_limit = False
ox.settings.requests_timeout = 900
ox.settings.overpass_settings = '[out:json][timeout:600]{maxsize}'
ox.settings.overpass_url = 'https://overpass.kumi.systems/api'
ox.settings.http_user_agent = 'upstream-onehealth/0.1 (github.com/ishaans04/Upstream)'
from upstream_kernel.compile.zones import build_zones

ll = [[round(float(a), 6), round(float(b), 6)] for a, b in net.lonlat]
nodes = {n: ll[i] for i, n in enumerate(net.node_ids)}
edges = [{"id": f"e{k}", "from": net.node_ids[int(a)], "to": net.node_ids[int(b)],
          "ll": [ll[int(a)], ll[int(b)]]} for k, (a, b) in enumerate(net.edges)]
from upstream_kernel.compile.cli import _snap_outfalls

wn, _ = fetch_waterways("data/catchment/catchment.geojson")
of = _snap_outfalls(gpd.read_file("data/catchment/outfalls.geojson"), wn)
by_node = {r.node_id: r for r in of.itertuples()}
outfalls = []
for k, entry in enumerate(net.entry_nodes):
    r = by_node[entry]
    outfalls.append({"outfall_id": r.outfall_id, "node_id": entry, "source_type": net.entry_source_type[k],
                     "is_synthetic": True, "name": r.name, "ll": ll[net.node_index[entry]]})
zg = build_zones("data/catchment/catchment.geojson", "data/catchment/zones_overrides.geojson", wn)
zones = []
for r in zg.itertuples():
    geom = r.geometry if r.geometry.geom_type == "Polygon" else r.geometry.convex_hull
    zones.append({"zone_id": r.zone_id, "node_id": r.node_id, "name": r.name,
                  "pathways": list(r.pathways), "population_upper_bound": int(r.population_upper_bound),
                  "ring": [[round(x, 6), round(y, 6)] for x, y in geom.exterior.coords]})

ev_out = [{"node_id": e["node_id"], "t": e["observed_at"].isoformat(), "method": e["method"],
           "result": e["result"], "kind": e["kind"],
           "observer": e["observer_id"].replace("sim-vol-", "vol-"),
           "effect": e.get("mission_effect")} for e in evidence]
json.dump({"scenario": {"weather": sc.flow_condition, "rain_mm_h": sc.rainfall_mm_h,
                        "truth_hidden": sc.entry_node},
           "network_version": net.version, "params_version": params.version,
           "snapshots": snaps, "evidence": ev_out, "clinical": clinical,
           "edges": edges, "nodes": nodes, "outfalls": outfalls, "zones": zones,
           "entry_types": dict(zip(net.entry_nodes, net.entry_source_type))},
          open(OUT + "/data.json", "w"), default=float)
print(len(snaps), [round(s["p_event"], 3) for s in snaps],
      [max((k for k in s["marginals"] if not k.startswith("__")), key=s["marginals"].get)
       for s in snaps], [e["result"] for e in ev_out], "clinical p", daily[-1], zid)
