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
