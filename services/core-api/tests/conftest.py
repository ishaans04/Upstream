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
