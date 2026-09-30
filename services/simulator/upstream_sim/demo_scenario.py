"""The PRD 10.5 walkthrough, replayed on the real Delhi network, and checked as it goes.

Every beat is a row of that table. The ones marked `expect` assert: if the system
does not do what the PRD promises, the rehearsal fails loudly rather than the video
quietly. It drives the real kernel worker (`kernel-sim`), the real episode workflow,
the mission API, the clinical statistics service and the recurring-source report.

Three departures from the PRD table, each forced by the system's own rules:

* **Daylight.** The PRD's incident is at 02:10, but no mission is sent in darkness
  (PRD 7.5). The script keeps the PRD's clock labels and runs in the present, so run
  it between 07:00 and 20:00 local time.
* **The storm passes.** 68 mm/h is a storm, and no one is sent out in a storm either;
  the burst eases to steady rain before PROBE plans, which is also what storms do.
* **The cast is chosen from the network.** O14 and J4 were Coimbra ids. Here the
  source is the Barapullah combined-sewer outfall with the most exposure zones below
  it, and the check goes wherever PROBE sends it.

What people observe is read from a hidden plume (`transport_truth`), so a "looks
normal" is genuinely negative and the day-3 cases come from real exposure, not from
the model's own prediction.

The early beats run in compressed real time (`--speed`). Day 3, day 16 and the
nightly report cannot wait for the calendar: the clinical job and the timer sweep are
run in this process with their clock set forward -- the same functions the services
run, so what is checked is the real path.

    python -m upstream_sim.demo_scenario --speed 60

Needs: `kernel-sim` up, the API with EPISODE_STREAMS=live,sim, the clinical service,
and JWT_SIGNING_KEY in the environment (to mint the officer's and agency's tokens).
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import time
import uuid
from dataclasses import dataclass, field

import httpx
import numpy as np
import psycopg
from psycopg.types.json import Jsonb

from .citizens import sample_at
from .clinical import zone_measure_reports
from .demo import do_mission, latest_belief, register_volunteers, reset_sim_stream
from .run import STREAM, SimStore, TruthWriter, zone_arrivals
from .scenario import Scenario
from .transport_truth import truth_plume

MIN = 60
CLINICAL_HISTORY_DAYS = 120          # a baseline needs at least 28 observed days
CLINICAL_ZONES = 8                   # the most-exposed areas; enough to show the loop
# Extra presentations per exposed area, stated rather than derived. The zones on this
# network carry placeholder populations, 200 for 81 of the 83 (docs/ASSUMPTIONS.md); at
# a 10% attack rate that is two or three cases an area, which no test could tell from a
# normal week - and saying so is the honest result. The demo shows the loop at a size
# where detection is possible, and says what size that is.
OUTBREAK_CASES_PER_AREA = 25


@dataclass
class Beat:
    clock: str                        # the PRD table's time
    what: str
    ok: bool | None = None            # None: not checked (skipped, with a reason)
    detail: str = ""


@dataclass
class Run:
    beats: list[Beat] = field(default_factory=list)

    def say(self, clock: str, what: str) -> None:
        print(f"  {clock:>8}  {what}")

    def expect(self, clock: str, what: str, ok: bool, detail: str = "") -> bool:
        self.beats.append(Beat(clock, what, bool(ok), detail))
        mark = "PASS" if ok else "FAIL"
        print(f"  {clock:>8}  [{mark}] {what}{f'  ({detail})' if detail else ''}")
        return bool(ok)

    def skip(self, clock: str, what: str, why: str) -> None:
        self.beats.append(Beat(clock, what, None, why))
        print(f"  {clock:>8}  [SKIP] {what}  ({why})")


# ------------------------------------------------------------------------- the cast


def downstream_nodes(net, node_idx: int) -> list[int]:
    """The nodes below one, in flow order. (`downstream_path` holds edge indices.)"""
    return [int(net.edges[e][1]) for e in net.downstream_path[int(node_idx)]]


def choose_cast(net) -> tuple[str, list[str]]:
    """A combined-sewer outfall with a rival outfall upstream of it, and the zones below.

    The rival is what makes PRD 10.5 a story rather than a formality: its water passes
    the outfall, so a smell or a sensor below cannot tell the two apart (TRACE splits
    71/19 in the PRD), and a check on the branch between them can. An outfall alone on
    its branch is certain from the first report, and PROBE rightly sends no one.
    Among such outfalls, the one with the most exposure zones below it.
    """
    best, best_zones = None, []
    for entry, k, stype in zip(net.entry_nodes, net.entry_idx, net.entry_source_type,
                               strict=True):
        if stype != "cso":
            continue
        rivals = [r for r in net.entry_idx if r != k and net.upstream_mask[int(r), int(k)]]
        if not rivals:
            continue
        below = [z for z, n in zip(net.zone_ids, net.zone_node_idx, strict=True)
                 if net.upstream_mask[int(k), int(n)]]
        if len(below) > len(best_zones):
            best, best_zones = entry, below
    if best is None:
        raise SystemExit("no combined-sewer outfall with a rival upstream to stage PRD 10.5 on")
    return best, best_zones


def seed_history(dsn: str, catchment: str, source: str, now: dt.datetime) -> list[str]:
    """Two earlier, closed episodes at the same outfall (simulated history).

    PRD 10.5's last row is "O14 flagged as a recurring source across episodes"; a
    single incident cannot be a pattern (upstream_kernel.pooling needs two).
    """
    made = []
    with psycopg.connect(dsn, autocommit=True) as c, c.cursor() as cur:
        for days_ago in (70, 35):
            eid, fp = f"EE-H{uuid.uuid4().hex[:4].upper()}", f"sha256:history-{uuid.uuid4().hex}"
            opened = now - dt.timedelta(days=days_ago)
            cur.execute("""INSERT INTO posterior_snapshots (ts,fingerprint,catchment_id,stream,
                           as_of_seq,network_version,kernel_version,params_version,p_event,
                           source_marginals,zone_windows,probe_candidates,explanation)
                           VALUES (%s,%s,%s,%s,0,'history','history','history',0.97,%s,
                                   '{}','[]','{}')""",
                        (opened, fp, catchment, STREAM,
                         Jsonb({"__none__": 0.03, source: 0.6})))
            cur.execute("""INSERT INTO episodes (episode_id,catchment_id,stream,state,opened_at,
                           state_changed_at,clinical_window_end,latest_fingerprint,summary)
                           VALUES (%s,%s,%s,'RESOLVED',%s,%s,%s,%s,%s)""",
                        (eid, catchment, STREAM, opened, opened + dt.timedelta(days=16),
                         opened + dt.timedelta(days=16), fp,
                         Jsonb({"note": "simulated history for the PRD 10.5 demo"})))
            made.append(eid)
    return made


def reset_clinical_sim(clinical_dsn: str) -> None:
    """The health zone's sim rows are scratch too (tests and the benchmark write them)."""
    with psycopg.connect(clinical_dsn, autocommit=True) as c, c.cursor() as cur:
        for table in ("test_results", "baselines", "syndromic_counts"):
            cur.execute(f"DELETE FROM {table} WHERE stream=%s", (STREAM,))


# ------------------------------------------------------------------------- helpers


def evidence(store: SimStore, when: dt.datetime, node: str, method: str, result: str,
             observer: str, observer_type: str) -> tuple[int, str]:
    from upstream_shared.events import EventEnvelope, EventType
    from upstream_shared.evidence import EvidencePayload

    payload = EvidencePayload(node_id=node, method=method, result=result, observer_id=observer,
                              observer_type=observer_type, snap_distance_m=4.0,
                              confirmed_by_observer=True).model_dump(mode="json")
    env = EventEnvelope(stream=STREAM, catchment_id=store.catchment_id,
                        event_type=EventType.EVIDENCE_RECORDED, event_time=when,
                        payload=payload)
    return store.append(env), str(env.event_id)


def the_episode(api: httpx.Client, timeout_s: float = 60.0) -> dict | None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        rows = api.get("/episodes", params={"stream": STREAM}).json()
        live = [r for r in rows if r["state"] not in ("RESOLVED", "REFUTED")]
        if live:
            return api.get(f"/episodes/{live[0]['episode_id']}",
                           params={"stream": STREAM}).json()
        time.sleep(2)
    return None


def wait_state(api: httpx.Client, episode_id: str, states: set[str],
               timeout_s: float = 60.0) -> str:
    deadline = time.time() + timeout_s
    state = ""
    while time.time() < deadline:
        state = api.get(f"/episodes/{episode_id}", params={"stream": STREAM}).json()["state"]
        if state in states:
            return state
        time.sleep(2)
    return state


def open_missions(api: httpx.Client, volunteers: list[str]) -> list[tuple[str, dict]]:
    out = []
    for v in volunteers:
        for m in api.get("/missions/mine", params={"volunteer_id": v}).json():
            if m["status"] == "created":
                out.append((v, m))
    return out


def pace(seconds_of_script: float, speed: float) -> None:
    time.sleep(max(seconds_of_script / speed, 0.0))


# ------------------------------------------------------------------------- the run


def main() -> None:  # noqa: C901 - one beat after another is the clearest shape here
    from upstream_kernel.compile.loader import load_network

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--api", default=os.environ.get("CORE_API_URL", "http://localhost:8000"))
    ap.add_argument("--clinical", default=os.environ.get("CLINICAL_URL", "http://localhost:8100"))
    ap.add_argument("--speed", type=float, default=60.0,
                    help="script seconds per wall-clock second for the first 30 minutes")
    ap.add_argument("--seed", type=int, default=20261005)
    a = ap.parse_args()

    from upstream_api.security import mint

    net = load_network(os.environ.get("NETWORK_ARTIFACT", "data/artifacts/network.npz"))
    dsn = os.environ["DATABASE_URL"]
    clinical_dsn = os.environ["CLINICAL_DATABASE_URL"]
    catchment = os.environ.get("CATCHMENT_ID", net.catchment_id)
    officer = {"Authorization": "Bearer " + mint("off-demo", ["officer"])}
    agency = {"Authorization": "Bearer " + mint("agency-demo", ["agency"])}
    api = httpx.Client(base_url=a.api, timeout=60.0)
    run = Run()
    rng = np.random.default_rng(a.seed)

    now = dt.datetime.now(dt.UTC)
    t0 = now - dt.timedelta(minutes=31)              # "02:10": all script times are past
    at = {label: t0 + dt.timedelta(minutes=m) for label, m in
          (("02:10", 0), ("02:14", 4), ("02:16", 6), ("02:17", 7), ("02:20", 10),
           ("02:31", 21), ("02:40", 30))}

    source, zones_below = choose_cast(net)
    k_source = net.node_index[source]
    below = downstream_nodes(net, k_source)
    sensor_node = net.node_ids[below[min(5, len(below) - 1)]]
    rivals = [e for e, r in zip(net.entry_nodes, net.entry_idx, strict=True)
              if net.upstream_mask[int(r), k_source]]
    print(f"PRD 10.5 on {catchment}: source {source} (combined-sewer outfall) with "
          f"{', '.join(rivals)} upstream of it; {len(zones_below)} exposure zones below; "
          f"sensor at {sensor_node}")

    reset_sim_stream(dsn, catchment)
    reset_clinical_sim(clinical_dsn)
    history = seed_history(dsn, catchment, source, now)
    print(f"reset the sim stream; simulated history: {', '.join(history)} at {source}")

    scenario = Scenario(scenario_id="PRD-10.5", entry_node=source, start=at["02:16"],
                        duration_s=3 * 3600, mass=2.0, contaminant="sewage",
                        flow_condition="storm", rainfall_mm_h=68.0, seed=a.seed)
    plume = truth_plume(net, scenario, np.random.default_rng(a.seed))
    arrivals = zone_arrivals(net, plume)
    store, truth = SimStore(dsn, catchment), TruthWriter(dsn)
    truth.write(f"demo-{uuid.uuid4().hex[:8]}", scenario, arrivals)
    volunteers = register_volunteers(dsn, net, now, 10)

    try:
        # ---- 02:10 - 02:17: the storm, the sensor, the overflow, the smell ----------
        t = t0 - dt.timedelta(hours=2)
        while t < at["02:10"]:
            store.rainfall(t, 0.0, "dry")
            t += dt.timedelta(minutes=15)
        store.rainfall(at["02:10"], 68.0, "storm")
        run.say("02:10", "rainfall reaches 68 mm/h (storm)")
        pace(4 * MIN, a.speed)
        evidence(store, at["02:14"], sensor_node, "sensor_turbidity", "positive",
                 "sensor-demo", "sensor")
        run.say("02:14", f"sensor {sensor_node}: turbidity up")
        pace(2 * MIN, a.speed)
        evidence(store, at["02:16"], source, "overflow_telemetry", "positive",
                 f"telemetry-{source}", "sensor")
        run.say("02:16", f"overflow at {source} reports activation")
        pace(1 * MIN, a.speed)
        last, _ = evidence(store, at["02:17"], net.node_ids[below[0]],
                           "citizen_visual_olfactory", "positive", "vol-sim-05", "citizen")
        run.say("02:17", f'citizen: "strong sewage smell near the outfall at {source}"')

        belief = latest_belief(api, last)
        ep = the_episode(api)
        # A new episode: the history's episodes closed weeks ago and must stay closed.
        run.expect("02:17", "posterior recomputed; a new episode opens",
                   ep is not None and ep["state"] in ("SUSPECTED", "PROBABLE")
                   and ep["episode_id"] not in history,
                   f"{ep['episode_id']} {ep['state']}, p_event {belief['p_event']:.0%}"
                   if ep else "no episode")
        if ep is None:
            raise SystemExit(1)
        episode_id = ep["episode_id"]

        top = sorted(belief["source_marginals"].items(), key=lambda kv: -kv[1])
        top = [(k, v) for k, v in top if not k.startswith("__")]
        p_event = belief["p_event"] or 1.0
        share = {k: v / p_event for k, v in top}
        run.expect("02:19", "TRACE: the overflowing outfall leads, given an event",
                   top[0][0] == source and share[source] >= 0.5,
                   ", ".join(f"{k} {share[k]:.0%}" for k, _ in top[:3]))

        # ---- 02:20: the burst eases, so PULSE and PROBE can work ----------------------
        t = at["02:20"]
        while t <= now + dt.timedelta(hours=4):
            store.rainfall(t, 4.0, "wet")
            t += dt.timedelta(minutes=15)
        pace(3 * MIN, a.speed)
        ep = api.get(f"/episodes/{episode_id}", params={"stream": STREAM}).json()
        windows = {z: w for z, w in (ep["zone_windows"] or {}).items()
                   if isinstance(w, dict) and w.get("window_lo")}
        run.expect("02:21", "PULSE: exposure windows downstream of the source",
                   bool(set(windows) & set(zones_below)),
                   f"{len(windows)} zones with an 80% window")

        deadline = time.time() + 90
        missions = open_missions(api, volunteers)
        while not missions and time.time() < deadline:
            time.sleep(3)
            missions = open_missions(api, volunteers)
        run.expect("02:22", "PROBE: a check is planned and a mission is sent",
                   bool(missions),
                   f"{missions[0][1]['mission_id']} to {missions[0][0]} at "
                   f"{missions[0][1]['node_id']}" if missions else "no mission within 90 s")

        # ---- 02:31: the volunteer checks where PROBE said -----------------------------
        if missions:
            pace(9 * MIN, a.speed)
            vol, m = missions[0]
            out = do_mission(api, net, plume, m, vol, walk_s=2.0, rng=rng)
            run.say("02:31", f"volunteer {vol} at {m['node_id']}: {out['result']}")
            fb = {}
            for _ in range(30):
                fb = api.get(f"/missions/{m['mission_id']}/feedback").json()
                if fb.get("realised_gain") is not None:
                    break
                time.sleep(2)
            run.expect("02:31", "the volunteer is told what their check changed (G7)",
                       fb.get("realised_gain") is not None, fb.get("effect", ""))
        else:
            run.skip("02:31", "volunteer check", "no mission was sent")

        # ---- 02:40: the officer's field test at the outfall, and sign-off ------------
        pace(9 * MIN, a.speed)
        # A field kit misses about one time in five. An officer who gets a negative at
        # an outfall the evidence points to tests again, as demo.py's officer does;
        # every reading, negatives included, goes on the record.
        # The seed fixes the kit's draws. With +41 the first reading is positive, which
        # is the usual case (sensitivity ~0.8 at this concentration); +40 draws two
        # false negatives in a row, a 1-in-25 run that the kernel rightly counts against
        # the outfall - worth knowing, but not the story PRD 10.5 tells.
        frng = np.random.default_rng(a.seed + 41)
        for attempt in range(1, 4):
            when = at["02:40"] + dt.timedelta(minutes=2 * (attempt - 1))
            reading = sample_at(net, plume, k_source, when.timestamp(), frng,
                                method="field_test", observer_id="off-demo")
            last, field_event = evidence(store, when, source, "field_test",
                                         reading["result"], "off-demo", "officer")
            run.say("02:40", f"officer's field test at {source} (#{attempt}): "
                             f"{reading['result']}")
            if reading["result"] == "positive":
                break
        latest_belief(api, last)
        state = wait_state(api, episode_id, {"PROBABLE", "CONFIRMED"})
        run.expect("02:40", "the episode is PROBABLE before an officer is asked",
                   state == "PROBABLE", state)
        r = api.post(f"/episodes/{episode_id}/signoff", headers=officer,
                     json={"officer_id": "off-demo", "field_result_event_id": field_event})
        state = wait_state(api, episode_id, {"CONFIRMED"}, timeout_s=15)
        run.expect("02:40", "officer sign-off: CONFIRMED (FR-21)",
                   r.status_code == 200 and state == "CONFIRMED",
                   f"HTTP {r.status_code}, {state}"
                   + ("" if r.status_code == 200 else f": {r.json().get('detail')}"))

        hapi = os.environ.get("HAPI_BASE_URL", "http://localhost:8080/fhir")
        try:
            hapi_up = httpx.get(f"{hapi}/metadata", timeout=3).status_code == 200
        except httpx.HTTPError:
            hapi_up = False
        if hapi_up:
            with psycopg.connect(dsn) as c, c.cursor() as cur:
                cur.execute("SELECT fhir_risk_assessment_id FROM episodes WHERE episode_id=%s",
                            (episode_id,))
                fhir_id = cur.fetchone()[0]
            run.expect("02:40", "FHIR resources published to HAPI", bool(fhir_id), str(fhir_id))
        else:
            run.skip("02:31", "FHIR resources published", f"HAPI is not running at {hapi}")
    finally:
        store.close()
        truth.close()

    # ---- day 3: the health zone's matched filter sees the excess --------------------
    os.environ.setdefault("EPISODE_API_BASE_URL", a.api)
    os.environ["CORE_API_TOKEN"] = mint("clinical-demo", ["public_health"])
    from clinical_stats import db as clinical_db
    from clinical_stats import jobs

    today = now.date()
    exposed = sorted((z for z in arrivals if z in zones_below),
                     key=lambda z: -net.zone_population[net.zone_ids.index(z)])[:CLINICAL_ZONES]
    crng = np.random.default_rng(a.seed + 3)
    clinical = httpx.Client(base_url=a.clinical, timeout=30.0)
    posted = 0
    for zone in exposed:
        arrival = arrivals[zone]
        reports, _ = zone_measure_reports(
            zone, int(net.zone_population[net.zone_ids.index(zone)]),
            (arrival["first"], arrival["last"]),
            today - dt.timedelta(days=CLINICAL_HISTORY_DAYS), today + dt.timedelta(days=3), crng,
            n_cases=OUTBREAK_CASES_PER_AREA)
        for report in reports:
            clinical.post("/counts", params={"stream": STREAM}, json=report).raise_for_status()
            posted += 1
    run.say("day 3", f"{posted} daily counts from {len(exposed)} health areas "
                     f"({CLINICAL_HISTORY_DAYS} days of history; a simulated outbreak of "
                     f"{OUTBREAK_CASES_PER_AREA} extra presentations per exposed area)")
    clinical_db.open_pool()
    try:
        outcome = jobs.run_daily(stream=STREAM, today=today + dt.timedelta(days=3))
    finally:
        clinical_db.close_pool()
    ph = api.get("/public-health/episodes", params={"stream": STREAM}).json()
    results = next((e["clinical_results"] for e in ph["episodes"]
                    if e["episode_id"] == episode_id), [])
    best = min((r["p_value"] for r in results), default=None)
    run.expect("day 3", "the matched filter finds the excess; only the result crosses (FR-34)",
               best is not None and best < 0.05,
               f"{outcome['published']} results, smallest p = {best:.3g}" if best is not None
               else f"{outcome}")

    # ---- day 16 and week 4: the durable timers --------------------------------------
    from upstream_api.db import close_pool, open_pool
    from upstream_api.workflows.episode import resolve_due_episodes

    ep = api.get(f"/episodes/{episode_id}", params={"stream": STREAM}).json()
    window_end = dt.datetime.fromisoformat(ep["clinical_window_end"])
    # The sweep's own resolution step, with its clock at the window's end. (Not the whole
    # sweep: expiring this morning's missions "at day 16" would stamp an event in the
    # future, which the log rightly refuses.)
    open_pool()
    try:
        swept = resolve_due_episodes(window_end + dt.timedelta(minutes=1), stream=STREAM)
    finally:
        close_pool()
    state = api.get(f"/episodes/{episode_id}", params={"stream": STREAM}).json()["state"]
    run.expect("day 16", "clinical window ends: RESOLVED (FR-22)", state == "RESOLVED",
               f"resolved {swept}")
    with psycopg.connect(dsn) as c, c.cursor() as cur:
        cur.execute("SELECT mission_id, window_start FROM missions WHERE episode_id=%s "
                    "AND 'bioassessment' = ANY(methods)", (episode_id,))
        bio = cur.fetchone()
    run.expect("week 4", "post-episode bioassessment mission (FR-24)", bio is not None,
               f"{bio[0]}, opens {bio[1]:%d %b}" if bio else "none")

    # ---- nightly: the recurring-source report ----------------------------------------
    report = api.get("/reports/recurring-sources", params={"stream": STREAM},
                     headers=agency).json()
    first = (report.get("sources") or [{}])[0]
    run.expect("nightly", "the outfall is flagged as a recurring source, to inspect",
               first.get("node_id") == source
               and episode_id in first.get("evidence_episode_ids", []),
               f"{first.get('outfall_id')} {first.get('pooled_probability', 0):.0%} over "
               f"{first.get('episode_count')} episodes" if first else "no recurring source")

    failed = [b for b in run.beats if b.ok is False]
    skipped = [b for b in run.beats if b.ok is None]
    print(f"\n{len(run.beats) - len(failed) - len(skipped)} passed, {len(failed)} failed, "
          f"{len(skipped)} skipped")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
