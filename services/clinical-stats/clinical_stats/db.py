"""The only database this service can reach (GC-7).

`CLINICAL_DATABASE_URL` is the one connection string read anywhere in this
package, and the role it names has rights in the `clinical` database and nowhere
else. The environmental database's URL is never read here, so no code in this
process can connect to it -- not by mistake, and not by a later change that did
not know the rule.
"""

from __future__ import annotations

import os
from contextlib import contextmanager

from psycopg_pool import ConnectionPool

DSN = os.environ.get("CLINICAL_DATABASE_URL", "")

# open=False so importing this package never reaches for a database; the app's
# lifespan opens it, and tests open it themselves.
pool = ConnectionPool(DSN, min_size=1, max_size=5, open=False, kwargs={"autocommit": True})


def open_pool() -> None:
    if not DSN:
        raise RuntimeError("CLINICAL_DATABASE_URL is not set")
    pool.open()
    pool.wait(timeout=30.0)


def close_pool() -> None:
    pool.close()


@contextmanager
def conn():
    with pool.connection() as connection:
        yield connection
