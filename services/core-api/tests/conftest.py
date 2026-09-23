import datetime as dt
import os

import psycopg
import pytest
from psycopg.types.json import Jsonb
from upstream_shared.codes import ObservationMethod
from upstream_shared.events import EventEnvelope, EventType
from upstream_shared.evidence import EvidencePayload, ObservationResult


@pytest.fixture
def db_conn_factory():
    made = []

    def _make():
        c = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)
        made.append(c)
        return c

    yield _make
    for c in made:
        c.close()


@pytest.fixture
def db_conn(db_conn_factory):
    return db_conn_factory()


@pytest.fixture(scope="session")
def _pool():
    """The module-level connection pool, opened once for the test session.

    `upstream_api.db` builds the pool with open=False so importing the package never
    reaches for a database; the app's lifespan opens it in production and this
    fixture does the same for tests.
    """
    from upstream_api.db import close_pool, open_pool

    open_pool()
    yield
    close_pool()


@pytest.fixture
def store(_pool):
    from upstream_api.eventlog import PostgresEventStore

    return PostgresEventStore()


@pytest.fixture
def count_events(db_conn):
    """Total rows in the log. Used to assert that something did - or did not - append."""

    def _count() -> int:
        with db_conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM events")
            return cur.fetchone()[0]

    return _count


@pytest.fixture(scope="session")
def _network():
    from upstream_api.network import get_network

    return get_network()


@pytest.fixture
def a_node(_network) -> str:
    """A real node id from the compiled catchment.

    The plan's tests hardcode toy-network ids like "O14"/"J9". Those do not exist in
    the compiled Coselhas network, and a hardcoded lon/lat of (0.0001, 0.0001) is in
    the Gulf of Guinea, about 600 km from the catchment, so snapping rejects it.
    Deriving both from the loaded artefact keeps the tests honest about the real data.
    """
    return _network.entry_nodes[0]


@pytest.fixture
def on_network_point(_network) -> tuple[float, float]:
    """A lon/lat that is genuinely on the network, so snapping must succeed."""
    i = int(_network.entry_idx[0])
    lon, lat = _network.lonlat[i]
    return float(lon), float(lat)


def _seed_sensor(db_conn, sensor_id: str, node_id: str, window_values: list[float]) -> dict:
    """Seed a baseline plus one 15-minute window, then refresh the aggregate.

    The baseline carries deliberate noise. With a constant baseline `stddev_samp`
    is 0, the anomaly z-score divides by the 1e-6 floor, and *every* reading looks
    like a spike - so a zero-variance fixture would pass the spike test while
    silently breaking the quiet-sensor one.
    """
    import math
    import random

    from upstream_api.config import settings

    rng = random.Random(f"seed::{sensor_id}")
    now = dt.datetime.now(dt.UTC).replace(second=0, microsecond=0)
    start = now.replace(minute=(now.minute // 15) * 15) - dt.timedelta(minutes=15)
    end = start + dt.timedelta(minutes=15)

    rows = []
    # 10 days of hourly baseline, mean 20, sd ~3.
    for h in range(1, 10 * 24):
        ts = start - dt.timedelta(hours=h)
        rows.append((ts, sensor_id, node_id, settings.catchment_id, "live",
                     "turbidity", 20.0 + rng.gauss(0, 3.0), "[NTU]"))
    # The window under test.
    for i, v in enumerate(window_values):
        rows.append((start + dt.timedelta(minutes=i * 3), sensor_id, node_id,
                     settings.catchment_id, "live", "turbidity", v, "[NTU]"))

    with db_conn.cursor() as cur:
        cur.execute("DELETE FROM sensor_readings WHERE sensor_id = %s", (sensor_id,))
        cur.executemany(
            "INSERT INTO sensor_readings (ts,sensor_id,node_id,catchment_id,stream,"
            "parameter,value,unit) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)", rows)
        # refresh_continuous_aggregate cannot run inside a transaction block; the
        # fixture connection is autocommit, so this is safe here.
        cur.execute("CALL refresh_continuous_aggregate('sensor_15min', %s, %s)",
                    (start - dt.timedelta(days=11), end + dt.timedelta(minutes=15)))
    assert math.isfinite(window_values[0])
    return {"sensor_id": sensor_id, "node_id": node_id, "start": start, "end": end}


@pytest.fixture
def seeded_normal_sensor(_pool, db_conn, a_node):
    return _seed_sensor(db_conn, "s-normal-1", a_node, [20.5, 21.0, 20.8, 21.4, 20.2])


@pytest.fixture
def seeded_spiking_sensor(_pool, db_conn, a_node):
    return _seed_sensor(db_conn, "s-spike-1", a_node, [21.0, 60.0, 180.0, 150.0, 40.0])

# ------------------------------------------------- Phase 6: episodes and missions

STREAM = "sim"


@pytest.fixture
def episodes(_pool, db_conn):
    """Isolate the sim stream, and give the test a handle on its own episodes."""
    from upstream_api.config import settings

    def _purge():
        with db_conn.cursor() as cur:
            cur.execute("DELETE FROM missions WHERE episode_id IN "
                        "(SELECT episode_id FROM episodes WHERE stream=%s AND catchment_id=%s)",
                        (STREAM, settings.catchment_id))
            cur.execute("DELETE FROM episodes WHERE stream=%s AND catchment_id=%s",
                        (STREAM, settings.catchment_id))

    _purge()
    yield
    _purge()


@pytest.fixture
def seq0(db_conn):
    """The log's high-water mark before the test, so event counts are scoped to it."""
    with db_conn.cursor() as cur:
        cur.execute("SELECT coalesce(max(seq), 0) FROM events")
        return cur.fetchone()[0]


@pytest.fixture
def emit_posterior(store, episodes):
    """Append a PosteriorComputed event exactly as the kernel writes it, then consume it."""
    from upstream_api.config import settings
    from upstream_api.workflows.episode import on_posterior_computed

    def _emit(p_event: float, zone_windows: dict | None = None, *, fingerprint: str = "fp-test"):
        env = EventEnvelope(
            stream=STREAM, catchment_id=settings.catchment_id,
            event_type=EventType.POSTERIOR_COMPUTED,
            event_time=dt.datetime.now(dt.UTC),
            payload={"fingerprint": fingerprint, "p_event": p_event, "as_of_seq": 0,
                     "top_sources": [], "est_start": [None, None],
                     "zone_windows": zone_windows or {}, "probe_candidates": []})
        seq = store.append(env)
        stored = store.read_from(seq - 1, catchment_id=settings.catchment_id,
                                 stream=STREAM, limit=1)[0]
        on_posterior_computed(stored)
        return stored

    return _emit


@pytest.fixture
def episode_row(db_conn):
    from upstream_api.config import settings

    cols = ("episode_id", "state", "opened_at", "state_changed_at", "clinical_window_end")

    def _get(episode_id: str | None = None):
        with db_conn.cursor() as cur:
            if episode_id:
                cur.execute(f"SELECT {','.join(cols)} FROM episodes WHERE episode_id=%s",
                            (episode_id,))
            else:
                cur.execute(f"SELECT {','.join(cols)} FROM episodes WHERE stream=%s "
                            "AND catchment_id=%s ORDER BY opened_at DESC LIMIT 1",
                            (STREAM, settings.catchment_id))
            row = cur.fetchone()
        return dict(zip(cols, row, strict=True)) if row else None

    return _get


@pytest.fixture
def post_evidence(store, a_node):
    """Append one piece of evidence and return its event id."""
    from upstream_api.config import settings

    def _post(result: str, *, method=ObservationMethod.FIELD_TEST, value=None, unit=None,
              days_ago: float = 0.0, node_id: str | None = None) -> str:
        payload = EvidencePayload(
            node_id=node_id or a_node, method=method, result=ObservationResult(result),
            value=value, unit=unit, observer_id="off-1", observer_type="officer",
            snap_distance_m=0.0)
        env = EventEnvelope(
            stream=STREAM, catchment_id=settings.catchment_id,
            event_type=EventType.EVIDENCE_RECORDED,
            event_time=dt.datetime.now(dt.UTC) - dt.timedelta(days=days_ago),
            payload=payload.model_dump(mode="json"))
        store.append(env)
        return str(env.event_id)

    return _post


@pytest.fixture
def events_since(db_conn, seq0):
    def _q(event_type: str, episode_id: str | None = None) -> list[dict]:
        sql = "SELECT payload FROM events WHERE seq > %s AND event_type=%s"
        args: list = [seq0, event_type]
        if episode_id:
            sql += " AND payload->>'episode_id' = %s"
            args.append(episode_id)
        with db_conn.cursor() as cur:
            cur.execute(sql + " ORDER BY seq", args)
            return [r[0] for r in cur.fetchall()]

    return _q


@pytest.fixture
def fast_clock(db_conn):
    """Make time appear to pass by moving the deadlines back, not the clock forward.

    The durable timer sleeps for 16 days (FR-22) and no test can wait for it. Patching
    the clock forward was the obvious alternative and it is wrong: every event the
    transition writes would then be stamped in the future, which FR-5 rejects outright
    - correctly, because a real system's clock never jumps. Ageing the episode instead
    puts the sweep in exactly the state it would be in on the day, and every event it
    writes still carries a truthful `event_time`.
    """
    from upstream_api.config import settings
    from upstream_api.workflows import timers

    class _Clock:
        def advance(self, **kw):
            delta = dt.timedelta(**kw)
            with db_conn.cursor() as cur:
                cur.execute("UPDATE episodes SET opened_at=opened_at-%s, "
                            "state_changed_at=state_changed_at-%s, "
                            "clinical_window_end=clinical_window_end-%s "
                            "WHERE stream=%s AND catchment_id=%s",
                            (delta, delta, delta, STREAM, settings.catchment_id))
                cur.execute("UPDATE missions SET created_at=created_at-%s, "
                            "window_start=window_start-%s, window_end=window_end-%s "
                            "WHERE episode_id IN (SELECT episode_id FROM episodes "
                            "WHERE stream=%s AND catchment_id=%s)",
                            (delta, delta, delta, STREAM, settings.catchment_id))
            timers.sweep_due()

    return _Clock()


# ------------------------------------------------------------- Phase 6: missions


@pytest.fixture
def an_episode(emit_posterior, episode_row):
    emit_posterior(p_event=0.94)
    return episode_row()["episode_id"]


@pytest.fixture
def a_volunteer(_pool, db_conn, _network):
    """A volunteer who lives near one entry node (PRD 14.2: a coarse area, never GPS).

    Neighbourhood-sized on purpose. We only ever know an area, so routing has to place
    the person at its centre; a coarse area the size of the whole catchment would put
    that centre kilometres from anywhere real and no one would ever be assigned.
    """
    made: list[str] = []

    def _make(volunteer_id="vol-1", *, push=None, available=True, near=0):
        lon, lat = _network.lonlat[int(_network.entry_idx[near % len(_network.entry_idx)])]
        pad = 0.01                      # about 1.1 km: a neighbourhood
        box = (f"POLYGON(({lon - pad} {lat - pad},{lon + pad} {lat - pad},"
               f"{lon + pad} {lat + pad},{lon - pad} {lat + pad},{lon - pad} {lat - pad}))")
        now = dt.datetime.now(dt.UTC)
        window = ((now - dt.timedelta(hours=1), now + dt.timedelta(hours=6)) if available
                  else (now + dt.timedelta(days=2), now + dt.timedelta(days=3)))
        with db_conn.cursor() as cur:
            cur.execute("""INSERT INTO volunteers (volunteer_id,display_name,coarse_area,
                           available_from,available_to,reliability,push_subscription)
                           VALUES (%s,%s,ST_GeomFromText(%s,4326),%s,%s,0.8,%s)
                           ON CONFLICT (volunteer_id) DO UPDATE SET
                             coarse_area=EXCLUDED.coarse_area,
                             available_from=EXCLUDED.available_from,
                             available_to=EXCLUDED.available_to,
                             push_subscription=EXCLUDED.push_subscription""",
                        (volunteer_id, volunteer_id, box, window[0], window[1],
                         Jsonb(push) if push else None))
        made.append(volunteer_id)
        return volunteer_id

    yield _make
    with db_conn.cursor() as cur:
        for vid in made:
            cur.execute("DELETE FROM volunteers WHERE volunteer_id=%s", (vid,))


@pytest.fixture
def candidates(_network):
    """PROBE-shaped candidates over real network nodes.

    Deliberately *not* carrying `lonlat`: PROBE does not produce one (probe.py), and the
    mission layer is what has to resolve a node id to a place on the map.
    """
    now = dt.datetime.now(dt.UTC).timestamp()

    def _make(n=2, *, window_s=3600):
        out = []
        for i in range(n):
            node = _network.node_ids[int(_network.entry_idx[i % len(_network.entry_idx)])]
            out.append({"candidate_id": f"{node}@{int(now)}-{i}", "node_id": node,
                        "window_start": now, "window_end": now + window_s,
                        "methods": ["field_test"], "mode": "protect",
                        "ec2_gain": 0.5 - 0.1 * i, "gain_per_cost": 1e-4,
                        "walk_cost_s": 600.0,
                        "expected_effect": "expected to rule out about 2 warning patterns"})
        return out

    return _make


@pytest.fixture
def mission_row(db_conn):
    cols = ("mission_id", "episode_id", "node_id", "status", "assignee_id", "methods",
            "expected_gain", "realised_gain", "window_start", "window_end")

    def _get(mission_id):
        with db_conn.cursor() as cur:
            cur.execute(f"SELECT {','.join(cols)} FROM missions WHERE mission_id=%s",
                        (mission_id,))
            row = cur.fetchone()
        return dict(zip(cols, row, strict=True)) if row else None

    return _get


@pytest.fixture
def count_missions(db_conn):
    def _count(episode_id):
        with db_conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM missions WHERE episode_id=%s", (episode_id,))
            return cur.fetchone()[0]

    return _count


@pytest.fixture
def seed_snapshot(db_conn, _network):
    """Write a posterior snapshot with chosen source marginals."""
    from upstream_api.config import settings

    def _seed(marginals: dict, *, probe: list | None = None, as_of_seq: int = 0,
              ts: dt.datetime | None = None, explanation: dict | None = None):
        with db_conn.cursor() as cur:
            cur.execute("""INSERT INTO posterior_snapshots (ts,fingerprint,episode_id,
                catchment_id,stream,as_of_seq,network_version,kernel_version,params_version,
                p_event,source_marginals,zone_windows,probe_candidates,explanation)
                VALUES (%s,%s,NULL,%s,%s,%s,'net','test','params',%s,%s,%s,%s,%s)""",
                        (ts or dt.datetime.now(dt.UTC), f"sha256:seed-{as_of_seq}",
                         settings.catchment_id, STREAM, as_of_seq,
                         1.0 - marginals.get("__none__", 0.0), Jsonb(marginals), Jsonb({}),
                         Jsonb(probe or []), Jsonb(explanation or {})))

    yield _seed
    with db_conn.cursor() as cur:
        cur.execute("DELETE FROM posterior_snapshots WHERE stream=%s AND kernel_version='test'",
                    (STREAM,))
