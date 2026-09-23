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
