from psycopg_pool import ConnectionPool

from .config import settings

# open=False so that importing the package never reaches for a database. The app's
# lifespan opens it; tests open it through a fixture.
pool = ConnectionPool(settings.database_url, min_size=2, max_size=10, open=False)


def open_pool() -> None:
    pool.open()
    pool.wait()


def close_pool() -> None:
    pool.close()
