"""Write a scenario into the same event log the real system uses (GC-10).

Everything the simulator produces goes through the log as `stream='sim'`, in
the order the system would have learned it, so the kernel, the episode workflow
and the FHIR publisher treat it exactly as they would a real incident. The truth
goes somewhere else entirely: `sim_truth.injected_events`, a schema `kernel_role`
has no rights on, written with a credential the kernel does not hold.

    python -m upstream_sim.run --scenarios 3 --citizens 12 --sensors 2
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import uuid
from dataclasses import asdict

import numpy as np
import psycopg
from psycopg.types.json import Jsonb
from upstream_shared.events import EventEnvelope, EventType
from upstream_shared.evidence import EvidencePayload

from .citizens import generate_citizen_reports, to_evidence
from .clinical import zone_measure_reports
from .scenario import Scenario, sample_scenario
from .sensors import generate_lab_results, generate_sensor_readings
from .transport_truth import truth_plume

STREAM = "sim"
RAINFALL_STEP_S = 900


class SimStore:
    """Appends to the event log and the rainfall table, as the ingest routes would."""

    def __init__(self, dsn: str, catchment_id: str):
        self.conn = psycopg.connect(dsn, autocommit=True)
        self.catchment_id = catchment_id

    def append(self, env: EventEnvelope) -> int:
        with self.conn.cursor() as cur:
            cur.execute("SELECT append_event(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (env.event_id, env.stream, env.catchment_id, env.event_type.value,
                         env.schema_version, env.event_time, Jsonb(env.payload),
                         env.causation_id, env.correlation_id))
            return cur.fetchone()[0]

    def rainfall(self, ts: dt.datetime, mm_per_h: float, flow_condition: str) -> None:
        with self.conn.cursor() as cur:
            cur.execute("INSERT INTO rainfall (ts, catchment_id, stream, mm_per_h, "
                        "antecedent_dry_h, flow_condition) VALUES (%s,%s,%s,%s,%s,%s) "
                        "ON CONFLICT DO NOTHING",
                        (ts, self.catchment_id, STREAM, mm_per_h, 24.0, flow_condition))

    def close(self) -> None:
        self.conn.close()


class TruthWriter:
    """The only writer of ground truth. Its DSN is the owner's, never kernel_role's."""

    def __init__(self, dsn: str):
        self.conn = psycopg.connect(dsn, autocommit=True)

    def write(self, run_id: str, scenario: Scenario, zone_arrivals: dict) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO sim_truth.injected_events (run_id, scenario_id, true_entry_node, "
                "true_start, true_duration_s, true_mass, contaminant, flow_condition, "
                "true_zone_arrivals) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (run_id, scenario.scenario_id, scenario.entry_node, scenario.start,
                 scenario.duration_s, scenario.mass, scenario.contaminant,
                 scenario.flow_condition, Jsonb(zone_arrivals)))

    def close(self) -> None:
        self.conn.close()


def zone_arrivals(net, plume) -> dict:
    """When each zone was truly exposed: the thing PULSE's windows are scored against."""
    out = {}
    for zone_id, node in zip(net.zone_ids, net.zone_node_idx, strict=True):
        interval = plume.exposure_interval(int(node))
        if interval is not None:
            first, last, peak = interval
            out[zone_id] = {"first": first, "last": last, "peak": peak}
    return out


def build_run(net, scenario: Scenario, *, n_citizens: int, n_sensors: int = 0, n_labs: int = 0,
              now: dt.datetime | None = None, catchment_id: str = "sim") -> dict:
    """Everything a scenario produces, in memory, in the order the system would learn it."""
    now = now or dt.datetime.now(dt.UTC)
    rng = np.random.default_rng(scenario.seed)
    plume = truth_plume(net, scenario, rng)
    reports = generate_citizen_reports(net, plume, scenario, rng, n=n_citizens, now=now)
    readings = generate_sensor_readings(net, plume, rng, n_sensors=n_sensors,
                                        start=scenario.start - dt.timedelta(hours=2), end=now)
    labs = generate_lab_results(net, plume, rng, n=n_labs, sampled_between=(
        scenario.start, scenario.start + dt.timedelta(seconds=scenario.duration_s + 3600)))

    # A lab result is learned when it is reported; one not yet reported is not learned.
    learned = [(r["observed_at"], r) for r in reports + readings]
    learned += [(r["reported_at"], r) for r in labs if r["reported_at"] <= now]
    learned.sort(key=lambda x: x[0])

    events = []
    for _, r in learned:
        payload = EvidencePayload(**to_evidence(r)).model_dump(mode="json")
        events.append(EventEnvelope(stream=STREAM, catchment_id=catchment_id,
                                    event_type=EventType.EVIDENCE_RECORDED,
                                    event_time=r["observed_at"], payload=payload))
    return {"scenario": scenario, "plume": plume, "reports": reports, "readings": readings,
            "labs": labs, "events": events, "zone_arrivals": zone_arrivals(net, plume),
            "now": now}


def run_scenario(net, scenario: Scenario, *, n_citizens: int, n_sensors: int = 0,
                 n_labs: int = 0, store: SimStore, truth_writer: TruthWriter,
                 clinical_poster=None, clinical_days: int = 0, run_id: str | None = None,
                 now: dt.datetime | None = None) -> dict:
    """Write one scenario: rainfall and evidence to the log, truth to sim_truth.

    `clinical_poster(report: dict)` sends a MeasureReport to the health zone -- over
    its HTTP boundary, as a health system would, never into its database.
    """
    run = build_run(net, scenario, n_citizens=n_citizens, n_sensors=n_sensors, n_labs=n_labs,
                    now=now, catchment_id=store.catchment_id)
    run_id = run_id or uuid.uuid4().hex[:12]
    t = scenario.start - dt.timedelta(hours=2)
    while t <= run["now"]:
        store.rainfall(t, scenario.rainfall_mm_h, scenario.flow_condition)
        t += dt.timedelta(seconds=RAINFALL_STEP_S)
    seqs = [store.append(env) for env in run["events"]]
    truth_writer.write(run_id, scenario, run["zone_arrivals"])

    clinical_truth = []
    if clinical_poster is not None and clinical_days > 0:
        rng = np.random.default_rng(scenario.seed + 1)
        first = (scenario.start - dt.timedelta(days=clinical_days)).date()
        last = run["now"].date()
        for zone_id, pop in zip(net.zone_ids, net.zone_population, strict=True):
            arrival = run["zone_arrivals"].get(zone_id)
            exposure = (arrival["first"], arrival["last"]) if arrival else None
            reports, truth = zone_measure_reports(zone_id, int(pop), exposure, first, last, rng)
            for report in reports:
                clinical_poster(report)
            clinical_truth.append(truth)
    return {**run, "run_id": run_id, "seqs": seqs, "clinical_truth": clinical_truth}


def main() -> None:
    from upstream_kernel.compile.loader import load_network

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--scenarios", type=int, default=1)
    ap.add_argument("--citizens", type=int, default=12)
    ap.add_argument("--sensors", type=int, default=0)
    ap.add_argument("--labs", type=int, default=0)
    ap.add_argument("--seed", type=int, default=20260922)
    ap.add_argument("--clinical-url", default=None,
                    help="post synthetic MeasureReports to this clinical service")
    ap.add_argument("--clinical-days", type=int, default=400)
    a = ap.parse_args()

    net = load_network(os.environ.get("NETWORK_ARTIFACT", "data/artifacts/network.npz"))
    dsn = os.environ["DATABASE_URL"]
    store = SimStore(dsn, os.environ.get("CATCHMENT_ID", net.catchment_id))
    truth = TruthWriter(dsn)
    poster = None
    if a.clinical_url:
        import httpx

        client = httpx.Client(base_url=a.clinical_url, timeout=15.0)

        def poster(report: dict) -> None:
            client.post("/counts", params={"stream": STREAM}, json=report).raise_for_status()

    rng = np.random.default_rng(a.seed)
    run_id = uuid.uuid4().hex[:12]
    try:
        for _ in range(a.scenarios):
            scenario = sample_scenario(net, rng)
            out = run_scenario(net, scenario, n_citizens=a.citizens, n_sensors=a.sensors,
                               n_labs=a.labs, store=store, truth_writer=truth,
                               clinical_poster=poster,
                               clinical_days=a.clinical_days if poster else 0, run_id=run_id)
            positives = sum(r["result"] == "positive" for r in out["reports"])
            print(f"{run_id} {scenario.scenario_id}: {len(out['events'])} events "
                  f"({positives} positive citizen reports), weather {scenario.flow_condition}")
    finally:
        store.close()
        truth.close()


def scenario_dict(s: Scenario) -> dict:
    d = asdict(s)
    d["start"] = s.start.isoformat()
    return d


if __name__ == "__main__":
    main()
