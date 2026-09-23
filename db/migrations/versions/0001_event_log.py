"""event log, consumer positions, append_event

The single most load-bearing piece of infrastructure in the project (PRD 12.2).
The advisory lock is *not* optional: without it a transaction that takes a `seq`
early but commits late is invisible to a consumer that has already read past it,
and the consumer silently skips that event forever.
"""
from alembic import op

revision, down_revision = "0001", None


def upgrade():
    op.execute("""
    CREATE TABLE events (
      seq            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      event_id       UUID        NOT NULL UNIQUE,
      stream         TEXT        NOT NULL CHECK (stream IN ('live','sim')),
      catchment_id   TEXT        NOT NULL,
      event_type     TEXT        NOT NULL,
      schema_version INT         NOT NULL,
      event_time     TIMESTAMPTZ NOT NULL,
      recorded_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
      payload        JSONB       NOT NULL,
      causation_id   UUID,
      correlation_id UUID
    );
    CREATE INDEX events_catchment_seq_idx ON events (catchment_id, stream, seq);
    CREATE INDEX events_type_time_idx     ON events (event_type, event_time DESC);
    CREATE INDEX events_recorded_idx      ON events (recorded_at DESC);

    CREATE TABLE consumer_positions (
      consumer   TEXT PRIMARY KEY,
      last_seq   BIGINT NOT NULL DEFAULT 0,
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );

    CREATE FUNCTION append_event(p_event_id UUID, p_stream TEXT, p_catchment TEXT,
                                 p_type TEXT, p_version INT, p_event_time TIMESTAMPTZ,
                                 p_payload JSONB, p_causation UUID, p_correlation UUID)
    RETURNS BIGINT LANGUAGE plpgsql AS $$
    DECLARE new_seq BIGINT;
    BEGIN
      PERFORM pg_advisory_xact_lock(424242);
      INSERT INTO events (event_id, stream, catchment_id, event_type, schema_version,
                          event_time, payload, causation_id, correlation_id)
      VALUES (p_event_id, p_stream, p_catchment, p_type, p_version,
              p_event_time, p_payload, p_causation, p_correlation)
      RETURNING seq INTO new_seq;
      PERFORM pg_notify('events', p_catchment);
      RETURN new_seq;
    END $$;

    DO $$ BEGIN CREATE ROLE app_role;    EXCEPTION WHEN duplicate_object THEN NULL; END $$;
    DO $$ BEGIN CREATE ROLE kernel_role; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
    GRANT SELECT, INSERT ON events TO app_role, kernel_role;
    REVOKE UPDATE, DELETE ON events FROM app_role, kernel_role;
    GRANT USAGE, SELECT ON SEQUENCE events_seq_seq TO app_role, kernel_role;
    GRANT EXECUTE ON FUNCTION append_event TO app_role, kernel_role;
    GRANT SELECT, INSERT, UPDATE ON consumer_positions TO app_role, kernel_role;
    """)


def downgrade():
    op.execute("DROP FUNCTION append_event; DROP TABLE consumer_positions; DROP TABLE events;")
