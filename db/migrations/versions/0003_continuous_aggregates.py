"""15-minute continuous aggregate over sensor_readings

The aggregate is what makes "this sensor was normal for these 15 minutes" cheap
enough to compute every quarter hour. That negative evidence does most of the work
in the posterior (PRD 7.2), so it cannot be an expensive query.
"""
from alembic import op

revision, down_revision = "0003", "0002"


def upgrade():
    op.execute("""
    CREATE MATERIALIZED VIEW sensor_15min
    WITH (timescaledb.continuous) AS
    SELECT time_bucket('15 minutes', ts) AS bucket,
           sensor_id, node_id, catchment_id, stream, parameter,
           avg(value) AS mean_value, stddev_samp(value) AS sd_value,
           max(value) AS max_value, count(*) AS n
    FROM sensor_readings
    GROUP BY bucket, sensor_id, node_id, catchment_id, stream, parameter
    WITH NO DATA;

    SELECT add_continuous_aggregate_policy('sensor_15min',
      start_offset => INTERVAL '3 days', end_offset => INTERVAL '1 minute',
      schedule_interval => INTERVAL '5 minutes');
    GRANT SELECT ON sensor_15min TO app_role, kernel_role;
    """)


def downgrade():
    op.execute("DROP MATERIALIZED VIEW IF EXISTS sensor_15min;")
