import pytest

pytestmark = pytest.mark.integration

EXPECTED = {"events", "consumer_positions", "network_nodes", "network_edges", "outfalls",
            "receptor_zones", "sensor_readings", "rainfall", "posterior_snapshots",
            "episodes", "missions", "volunteers", "footpath_edges"}


def test_all_domain_tables_exist(db_conn):
    with db_conn.cursor() as cur:
        cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")
        assert EXPECTED <= {r[0] for r in cur.fetchall()}


def test_hypertables_registered(db_conn):
    with db_conn.cursor() as cur:
        cur.execute("SELECT hypertable_name FROM timescaledb_information.hypertables")
        assert {"sensor_readings", "rainfall", "posterior_snapshots"} <= {r[0] for r in cur.fetchall()}


def test_kernel_role_cannot_read_ground_truth(db_conn):
    """GC-10: the kernel must not be able to see simulator ground truth."""
    with db_conn.cursor() as cur:
        cur.execute("SELECT has_schema_privilege('kernel_role','sim_truth','USAGE')")
        assert cur.fetchone()[0] is False


def test_kernel_role_cannot_write_episodes(db_conn):
    """PRD 10.3: the kernel never changes episode state."""
    with db_conn.cursor() as cur:
        cur.execute("SELECT has_table_privilege('kernel_role','episodes','INSERT')")
        assert cur.fetchone()[0] is False
