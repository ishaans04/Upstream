"""clinical counts and results carry a stream

The simulator feeds the health zone the same way a health system would, and its
counts are for the same areas as the live ones -- every zone publishes one area.
Without a stream they would land in the same rows: a simulated outbreak would
become part of a live baseline, and a live test would find a simulated excess.
GC-10 keeps the sim apart in the event log; this keeps it apart here.

Existing rows are live: nothing before this revision could write anything else.
"""
from alembic import op

revision, down_revision = "c0002", "c0001"


def upgrade():
    op.execute("""
    ALTER TABLE syndromic_counts ADD COLUMN stream TEXT NOT NULL DEFAULT 'live'
      CHECK (stream IN ('live', 'sim'));
    ALTER TABLE syndromic_counts DROP CONSTRAINT syndromic_counts_pkey;
    ALTER TABLE syndromic_counts ADD PRIMARY KEY (stream, day, area_code, syndrome);

    ALTER TABLE baselines ADD COLUMN stream TEXT NOT NULL DEFAULT 'live'
      CHECK (stream IN ('live', 'sim'));
    ALTER TABLE baselines DROP CONSTRAINT baselines_pkey;
    ALTER TABLE baselines ADD PRIMARY KEY (stream, area_code, syndrome);

    ALTER TABLE test_results ADD COLUMN stream TEXT NOT NULL DEFAULT 'live'
      CHECK (stream IN ('live', 'sim'));
    """)


def downgrade():
    op.execute("""
    DELETE FROM syndromic_counts WHERE stream <> 'live';
    ALTER TABLE syndromic_counts DROP CONSTRAINT syndromic_counts_pkey;
    ALTER TABLE syndromic_counts ADD PRIMARY KEY (day, area_code, syndrome);
    ALTER TABLE syndromic_counts DROP COLUMN stream;
    DELETE FROM baselines WHERE stream <> 'live';
    ALTER TABLE baselines DROP CONSTRAINT baselines_pkey;
    ALTER TABLE baselines ADD PRIMARY KEY (area_code, syndrome);
    ALTER TABLE baselines DROP COLUMN stream;
    DELETE FROM test_results WHERE stream <> 'live';
    ALTER TABLE test_results DROP COLUMN stream;
    """)
