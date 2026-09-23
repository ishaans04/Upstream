import datetime as dt
import os

import psycopg
import pytest


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
