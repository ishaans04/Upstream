"""Drive one simulated incident through the running system, in real time (the demo).

`run.py` writes a whole scenario at once, which is what a benchmark wants. A person
watching the console wants to see the system *learn*: reports arriving one by one,
the belief sharpening, a mission going out, a volunteer's test strip changing the
picture. This does that, on the real network, against the real kernel worker,
episode workflow and mission API:

* the citizen reports leading up to the first credible one are appended to the log
  on `stream='sim'` a few seconds apart, each with the time it was really made;
* the truth goes to `sim_truth`, which the kernel cannot read (GC-10);
* simulated volunteers take the missions the kernel's PROBE step sends them, walk
  (briefly), read a test strip against the hidden plume, and submit through the same
  HTTP endpoints the mission PWA uses.

One volunteer can be left to a human with `--human`, so the demo can be finished from
the PWA on a phone.

    python -m upstream_sim.demo --api http://localhost:8000 --human vol-sim-03

Needs the `sim` kernel worker (`docker compose --profile demo up kernel-sim`) and the
API with `EPISODE_STREAMS=live,sim`.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import time
import uuid

import httpx
import numpy as np
import psycopg

from .citizens import generate_citizen_reports, sample_at, to_evidence
from .run import RAINFALL_STEP_S, STREAM, SimStore, TruthWriter, zone_arrivals
from .scenario import sample_scenario
from .transport_truth import truth_plume

EXPOSURE_THRESHOLD_C = 0.05          # the same "credible first report" rule as the bench
REPORTS_BEFORE_TRIGGER = 3
# One credible positive among negatives leaves the belief near its prior (about 5%):
# no episode opens and no mission goes out. Replay until this many have come in.
MIN_CREDIBLE_POSITIVES = 2
MAX_REPLAY = 12                      # reports; each gets its own belief, a pace apart
# Residents reporting over the incident's hours. Only the last few are replayed, but
# with fewer a third credible report almost never comes in time.
DEMO_CITIZENS = 150
VOLUNTEER_AREA_DEG = 0.006           # about 650 m: a neighbourhood, never a GPS fix


def pick_scenario(net, seed: int, now: dt.datetime, *, n_citizens: int = DEMO_CITIZENS,
                  tries: int = 400):
    """The first seed from `seed` whose incident is worth watching, deterministically.

    Worth watching: a resident has credibly reported it, and it is still under way, so
    a check at the source now can find it. A storm is skipped because no mission may go
    out in one (PRD 7.5). The replay runs from a few reports before the first credible
    one to the report that brings the count of credible ones to MIN_CREDIBLE_POSITIVES,
    and is at most MAX_REPLAY long.
    """
    for k in range(tries):
        rng = np.random.default_rng(seed + k)
        sc = sample_scenario(net, rng, now=now, earliest_h=1.5, latest_h=0.4)
        if sc.flow_condition == "storm":
            continue
        world = np.random.default_rng(sc.seed)
        plume = truth_plume(net, sc, world)
        source = net.node_index[sc.entry_node]
        if plume.concentration(source, now.timestamp() + 600) <= EXPOSURE_THRESHOLD_C:
            continue                                     # over before anyone could look
        reports = generate_citizen_reports(net, plume, sc, world, n=n_citizens, now=now)
        credible = [j for j, r in enumerate(reports) if r["result"] == "positive"
                    and r["true_concentration"] > EXPOSURE_THRESHOLD_C]
        if len(credible) < MIN_CREDIBLE_POSITIVES:
            continue
        first, enough = credible[0], credible[MIN_CREDIBLE_POSITIVES - 1]
        start = max(0, first - REPORTS_BEFORE_TRIGGER, enough + 1 - MAX_REPLAY)
        if enough + 1 - start > MAX_REPLAY or start > first:
            continue                                     # too drawn out to watch
        return sc, plume, reports[start: enough + 1]
    raise SystemExit(f"no visible, ongoing, mission-safe incident in seeds {seed}..{seed + tries - 1}")


def latest_belief(api: httpx.Client, after_seq: int, *, timeout_s: float = 90.0) -> dict:
    """The kernel's first belief that includes the log up to `after_seq`."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        tl = api.get("/replay/timeline", params={"stream": STREAM, "limit": 5000}).json()
        done = [p for p in tl if p["as_of_seq"] >= after_seq]
        if done:
            return api.get("/replay", params={"stream": STREAM, "at": done[-1]["ts"]}).json()
        time.sleep(2)
    raise SystemExit("the sim kernel worker wrote no belief; is kernel-sim running?")


def officer_checks(store: SimStore, api: httpx.Client, net, plume, last_seq: int, *, n: int,
                   pace: float, rng: np.random.Generator) -> None:
    """What a duty officer does with a suspicion: field-test the likeliest outfall.

    Each check goes to the outfall the kernel ranks highest among those not yet
    cleared, read against the hidden plume with the field-test detection curve, and
    the next waits for the belief that includes it. A negative clears an outfall; a
    positive does not, so the officer confirms it before moving on, as one would.
    """
    checked: set[str] = set()                            # cleared by a negative
    for k in range(n):
        belief = latest_belief(api, last_seq)
        print(f"  belief: something is happening {belief['p_event']:.0%}")
        if belief["p_event"] >= 0.9:
            return
        m = belief["source_marginals"]
        ranked = sorted((e for e in net.entry_nodes if e not in checked), key=lambda e: -m.get(e, 0))
        if not ranked:
            return
        node = ranked[0]
        reading = sample_at(net, plume, net.node_index[node], time.time(), rng,
                            method="field_test", observer_id=f"officer-{k + 1}")
        reading["observer_type"] = "officer"
        if reading["result"] == "negative":
            checked.add(node)
        last_seq = _post_report(store, reading)
        print(f"  officer field test at {node}: {reading['result']}")
        time.sleep(pace)
    print(f"  belief: something is happening {latest_belief(api, last_seq)['p_event']:.0%}")


def register_volunteers(dsn: str, net, now: dt.datetime, n: int) -> list[str]:
    """One volunteer living near each outfall, available for the next few hours."""
    ids = []
    with psycopg.connect(dsn, autocommit=True) as c, c.cursor() as cur:
        for k in range(n):
            lon, lat = net.lonlat[int(net.entry_idx[k % len(net.entry_idx)])]
            p = VOLUNTEER_AREA_DEG
            box = (f"POLYGON(({lon - p} {lat - p},{lon + p} {lat - p},{lon + p} {lat + p},"
                   f"{lon - p} {lat + p},{lon - p} {lat - p}))")
            vid = f"vol-sim-{k + 1:02d}"
            cur.execute("""INSERT INTO volunteers (volunteer_id,display_name,coarse_area,
                           available_from,available_to,reliability)
                           VALUES (%s,%s,ST_GeomFromText(%s,4326),%s,%s,0.8)
                           ON CONFLICT (volunteer_id) DO UPDATE SET
                             coarse_area=EXCLUDED.coarse_area,
                             available_from=EXCLUDED.available_from,
                             available_to=EXCLUDED.available_to""",
                        (vid, f"Simulated volunteer {k + 1}", box,
                         now - dt.timedelta(hours=1), now + dt.timedelta(hours=8)))
            ids.append(vid)
    return ids


def end_demo(dsn: str) -> int:
    """Take the demo's volunteers off duty; returns how many.

    They live beside every outfall for eight hours, so until then they win the
    assignment of any mission on the network, the test suite's included. Their rows
    stay (a person may still be finishing a mission on the PWA); only availability ends.
    """
    with psycopg.connect(dsn, autocommit=True) as c, c.cursor() as cur:
        cur.execute("""UPDATE volunteers SET available_to=now()
                       WHERE volunteer_id LIKE 'vol-sim-%%' AND available_to > now()""")
        return cur.rowcount


def reset_sim_stream(dsn: str, catchment_id: str) -> None:
    """Clear this catchment's simulator stream so the demo starts from nothing.

    `stream='sim'` is scratch space: the benchmark and the test suite write to it
    too, and a test's leftover evidence inside the kernel's 24-hour horizon would
    quietly shape the demo's belief. The live stream is never touched -- the stream
    is a literal here, not a parameter. The consumer cursors are moved past what was
    cleared, so neither worker replays history into the new session.
    """
    with psycopg.connect(dsn, autocommit=False) as c, c.cursor() as cur:
        sim = "sim"
        cur.execute("""DELETE FROM missions WHERE episode_id IN
                       (SELECT episode_id FROM episodes WHERE stream=%s AND catchment_id=%s)""",
                    (sim, catchment_id))
        for table in ("episodes", "posterior_snapshots", "events", "rainfall"):
            cur.execute(f"DELETE FROM {table} WHERE stream=%s AND catchment_id=%s", (sim, catchment_id))
        cur.execute("SELECT coalesce(max(seq), 0) FROM events")
        top = cur.fetchone()[0]
        for consumer in ("episodes:sim", f"kernel:{catchment_id}:sim"):
            cur.execute("""INSERT INTO consumer_positions (consumer, last_seq, updated_at)
                           VALUES (%s, %s, now()) ON CONFLICT (consumer)
                           DO UPDATE SET last_seq=EXCLUDED.last_seq, updated_at=now()""",
                        (consumer, top))
        c.commit()


def _post_report(store: SimStore, report: dict) -> int:
    from upstream_shared.events import EventEnvelope, EventType
    from upstream_shared.evidence import EvidencePayload

    payload = EvidencePayload(**to_evidence(report)).model_dump(mode="json")
    return store.append(EventEnvelope(stream=STREAM, catchment_id=store.catchment_id,
                                      event_type=EventType.EVIDENCE_RECORDED,
                                      event_time=report["observed_at"], payload=payload))


def do_mission(api: httpx.Client, net, plume, mission: dict, volunteer: str, *,
               walk_s: float, rng: np.random.Generator) -> dict:
    """Accept, walk, read a strip against the hidden plume, submit, complete."""
    mid = mission["mission_id"]
    api.post(f"/missions/{mid}/accept", json={"volunteer_id": volunteer}).raise_for_status()
    time.sleep(walk_s)
    t = time.time()
    method = (mission.get("methods") or ["test_strip"])[0]
    reading = sample_at(net, plume, net.node_index[mission["node_id"]], t, rng,
                        method=method, observer_id=volunteer)
    body = {**to_evidence(reading), "observed_at": reading["observed_at"].isoformat(),
            "mission_id": mid, "idempotency_key": str(uuid.uuid4())}
    r = api.post("/ingest/report/confirm", json=body)
    r.raise_for_status()
    done = api.post(f"/missions/{mid}/complete",
                    json={"evidence_event_id": r.json()["event_id"]})
    done.raise_for_status()
    return {"result": reading["result"], **done.json()}


def main() -> None:
    from upstream_kernel.compile.loader import load_network

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--api", default=os.environ.get("CORE_API_URL", "http://localhost:8000"))
    ap.add_argument("--seed", type=int, default=20260930)
    ap.add_argument("--pace", type=float, default=12.0,
                    help="seconds between citizen reports, so each gets its own belief")
    ap.add_argument("--walk", type=float, default=25.0,
                    help="seconds a simulated volunteer takes to reach a site")
    ap.add_argument("--missions", type=int, default=4, help="stop after this many")
    ap.add_argument("--minutes", type=float, default=20.0, help="give up after this long")
    ap.add_argument("--volunteers", type=int, default=10)
    ap.add_argument("--human", action="append", default=[],
                    help="a volunteer id left for a person on the PWA (repeatable)")
    ap.add_argument("--officer-checks", type=int, default=3,
                    help="field tests by the duty officer at the likeliest outfalls")
    ap.add_argument("--reset", action="store_true",
                    help="clear this catchment's sim stream first (never the live one)")
    ap.add_argument("--end", action="store_true",
                    help="take the demo's volunteers off duty, clear the sim stream and exit "
                         "(before running the test suite)")
    a = ap.parse_args()
    if a.end:
        # Its beliefs would also sit between a test's seeded snapshots and be measured
        # against instead of them.
        print(f"{end_demo(os.environ['DATABASE_URL'])} demo volunteers taken off duty")
        reset_sim_stream(os.environ["DATABASE_URL"],
                         os.environ.get("CATCHMENT_ID", "delhi-barapullah"))
        print("cleared the sim stream")
        return

    net = load_network(os.environ.get("NETWORK_ARTIFACT", "data/artifacts/network.npz"))
    dsn = os.environ["DATABASE_URL"]
    catchment = os.environ.get("CATCHMENT_ID", net.catchment_id)
    if a.reset:
        reset_sim_stream(dsn, catchment)
        print(f"cleared the sim stream for {catchment}")
    now = dt.datetime.now(dt.UTC)
    sc, plume, reports = pick_scenario(net, a.seed, now)
    print(f"incident {sc.scenario_id}: weather {sc.flow_condition}, "
          f"{len(reports)} reports to replay (truth hidden in sim_truth)")

    store = SimStore(dsn, catchment)
    truth = TruthWriter(dsn)
    api = httpx.Client(base_url=a.api, timeout=30.0)
    try:
        t = sc.start - dt.timedelta(hours=2)
        while t <= now + dt.timedelta(hours=4):
            store.rainfall(t, sc.rainfall_mm_h, sc.flow_condition)
            t += dt.timedelta(seconds=RAINFALL_STEP_S)
        truth.write(f"demo-{uuid.uuid4().hex[:8]}", sc, zone_arrivals(net, plume))
        volunteers = register_volunteers(dsn, net, now, a.volunteers)
        auto = [v for v in volunteers if v not in a.human]
        print(f"volunteers: {', '.join(volunteers)}; left for a person: "
              f"{', '.join(a.human) or 'none'}")

        last = 0
        for r in reports:
            last = _post_report(store, r)
            print(f"  report at {r['node_id']}: {r['result']} "
                  f"(made {r['observed_at']:%H:%M} UTC)")
            time.sleep(a.pace)
        officer_checks(store, api, net, plume, last, n=a.officer_checks, pace=a.pace,
                       rng=np.random.default_rng(sc.seed + 5))
    finally:
        store.close()
        truth.close()

    rng = np.random.default_rng(sc.seed + 7)
    done, deadline = 0, time.time() + 60 * a.minutes
    while done < a.missions and time.time() < deadline:
        progressed = False
        for v in auto:
            try:
                mine = api.get("/missions/mine", params={"volunteer_id": v}).json()
            except httpx.TransportError as e:            # a dropped connection is not the end
                print(f"  (api unreachable: {e}; retrying)")
                break
            for m in mine:
                if m["status"] != "created":
                    continue
                out = do_mission(api, net, plume, m, v, walk_s=a.walk, rng=rng)
                done += 1
                progressed = True
                print(f"  {v} checked {m['node_id']}: {out['result']}. {out['effect']}")
                if done >= a.missions:
                    break
            if done >= a.missions:
                break
        if not progressed:
            time.sleep(5)
    print(f"done: {done} missions completed")


if __name__ == "__main__":
    main()
