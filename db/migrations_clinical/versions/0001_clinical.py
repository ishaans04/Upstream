"""clinical schema: aggregate counts, baselines, test results

The health zone (GC-7, PRD 14.1). Three tables, and what is *absent* from them
matters more than what is present: there is no column anywhere here that could
hold a patient, an address finer than an area, or a date of birth. That is not
a convention to be remembered -- it is the schema, and a future writer who tries
to store a patient has nowhere to put one.

Small-count suppression is a CHECK constraint for the same reason. Suppression
in application code is a branch someone can forget; a constraint is not.
"""
from alembic import op

revision, down_revision = "c0001", None


def upgrade():
    op.execute("""
    CREATE EXTENSION IF NOT EXISTS timescaledb;

    -- The aggregate feed. One row per area, day and syndrome; never per person.
    CREATE TABLE syndromic_counts (
      day         DATE        NOT NULL,
      area_code   TEXT        NOT NULL,
      syndrome    TEXT        NOT NULL,
      count       INT         NOT NULL CHECK (count >= 5),
      source      TEXT        NOT NULL,
      received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      PRIMARY KEY (day, area_code, syndrome));
    SELECT create_hypertable('syndromic_counts','day', migrate_data => true);

    COMMENT ON CONSTRAINT syndromic_counts_count_check ON syndromic_counts IS
      'GC-7 small-count suppression. A count below the threshold is not stored at all, '
      'because a stored small count is re-identifiable from an area and a day.';

    -- FR-33: one fitted seasonal/day-of-week baseline per area and syndrome.
    CREATE TABLE baselines (
      area_code    TEXT        NOT NULL,
      syndrome     TEXT        NOT NULL,
      fitted_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
      alpha        DOUBLE PRECISION NOT NULL,
      coefficients JSONB       NOT NULL,
      n_obs        INT         NOT NULL,
      PRIMARY KEY (area_code, syndrome));

    -- FR-34: the only thing that ever leaves this zone.
    CREATE TABLE test_results (
      result_id   BIGSERIAL PRIMARY KEY,
      episode_id  TEXT,
      area_code   TEXT        NOT NULL,
      syndrome    TEXT        NOT NULL,
      method      TEXT        NOT NULL,
      p_value     DOUBLE PRECISION NOT NULL,
      effect_size DOUBLE PRECISION,
      n_days      INT         NOT NULL,
      computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      published_at TIMESTAMPTZ);
    CREATE INDEX test_results_episode_idx ON test_results (episode_id, computed_at DESC);
    """)


def downgrade():
    op.execute("""
    DROP TABLE IF EXISTS test_results;
    DROP TABLE IF EXISTS baselines;
    DROP TABLE IF EXISTS syndromic_counts;
    """)
