"""network, timeseries, read models, isolated sim_truth schema

Column names here are referenced verbatim by Phases 1-11. Changing one means
changing every consumer, so treat this file as the schema contract.
"""
from alembic import op

revision, down_revision = "0002", "0001"


def upgrade():
    op.execute("""
    CREATE TABLE network_nodes (
      network_version TEXT NOT NULL, node_id TEXT NOT NULL,
      node_type TEXT NOT NULL,                      -- junction|outfall|reach_point|gauge
      geom GEOMETRY(Point,4326) NOT NULL, catchment_id TEXT NOT NULL,
      attrs JSONB NOT NULL DEFAULT '{}'::jsonb,
      PRIMARY KEY (network_version, node_id));
    CREATE INDEX network_nodes_geom_idx ON network_nodes USING GIST (geom);

    CREATE TABLE network_edges (
      network_version TEXT NOT NULL, edge_id TEXT NOT NULL,
      from_node TEXT NOT NULL, to_node TEXT NOT NULL,
      length_m DOUBLE PRECISION NOT NULL, slope DOUBLE PRECISION,
      mean_flow_m3s DOUBLE PRECISION NOT NULL DEFAULT 0.05,
      geom GEOMETRY(LineString,4326) NOT NULL,
      PRIMARY KEY (network_version, edge_id));
    CREATE INDEX network_edges_geom_idx ON network_edges USING GIST (geom);

    CREATE TABLE outfalls (
      network_version TEXT NOT NULL, outfall_id TEXT NOT NULL, node_id TEXT NOT NULL,
      source_type TEXT NOT NULL,                    -- cso|storm_outfall|industrial|misconnection|unknown
      base_rate DOUBLE PRECISION NOT NULL DEFAULT 0.001,
      is_synthetic BOOLEAN NOT NULL DEFAULT FALSE,  -- PRD R2: label synthetic elements
      attrs JSONB NOT NULL DEFAULT '{}'::jsonb,
      PRIMARY KEY (network_version, outfall_id));

    CREATE TABLE receptor_zones (
      network_version TEXT NOT NULL, zone_id TEXT NOT NULL, node_id TEXT NOT NULL,
      name TEXT NOT NULL,
      pathways TEXT[] NOT NULL DEFAULT '{}',        -- recreation|animal_contact|floodwater|irrigation
      population_upper_bound INT,
      geom GEOMETRY(Polygon,4326) NOT NULL,
      PRIMARY KEY (network_version, zone_id));
    CREATE INDEX receptor_zones_geom_idx ON receptor_zones USING GIST (geom);

    CREATE TABLE footpath_edges (
      id BIGSERIAL PRIMARY KEY, source BIGINT, target BIGINT,
      cost DOUBLE PRECISION, reverse_cost DOUBLE PRECISION,
      geom GEOMETRY(LineString,4326));
    CREATE INDEX footpath_edges_geom_idx ON footpath_edges USING GIST (geom);
    CREATE INDEX footpath_edges_source_idx ON footpath_edges (source);
    CREATE INDEX footpath_edges_target_idx ON footpath_edges (target);

    CREATE TABLE sensor_readings (
      ts TIMESTAMPTZ NOT NULL, sensor_id TEXT NOT NULL, node_id TEXT NOT NULL,
      catchment_id TEXT NOT NULL, stream TEXT NOT NULL DEFAULT 'live',
      parameter TEXT NOT NULL, value DOUBLE PRECISION NOT NULL, unit TEXT NOT NULL);
    SELECT create_hypertable('sensor_readings','ts');
    ALTER TABLE sensor_readings SET (timescaledb.compress,
      timescaledb.compress_segmentby='sensor_id,parameter');
    SELECT add_compression_policy('sensor_readings', INTERVAL '7 days');

    CREATE TABLE rainfall (
      ts TIMESTAMPTZ NOT NULL, catchment_id TEXT NOT NULL, stream TEXT NOT NULL DEFAULT 'live',
      mm_per_h DOUBLE PRECISION NOT NULL, antecedent_dry_h DOUBLE PRECISION,
      flow_condition TEXT NOT NULL);                -- dry|wet|storm
    SELECT create_hypertable('rainfall','ts');

    CREATE TABLE posterior_snapshots (
      ts TIMESTAMPTZ NOT NULL, fingerprint TEXT NOT NULL,
      episode_id TEXT, catchment_id TEXT NOT NULL, stream TEXT NOT NULL,
      as_of_seq BIGINT NOT NULL,
      network_version TEXT NOT NULL, kernel_version TEXT NOT NULL, params_version TEXT NOT NULL,
      p_event DOUBLE PRECISION NOT NULL,
      source_marginals JSONB NOT NULL, zone_windows JSONB NOT NULL,
      probe_candidates JSONB NOT NULL, explanation JSONB NOT NULL DEFAULT '{}'::jsonb);
    SELECT create_hypertable('posterior_snapshots','ts');
    CREATE INDEX posterior_snapshots_replay_idx ON posterior_snapshots (catchment_id, ts DESC);
    CREATE INDEX posterior_snapshots_fp_idx ON posterior_snapshots (fingerprint);

    CREATE TABLE episodes (
      episode_id TEXT PRIMARY KEY, catchment_id TEXT NOT NULL, stream TEXT NOT NULL,
      state TEXT NOT NULL, opened_at TIMESTAMPTZ NOT NULL,
      state_changed_at TIMESTAMPTZ NOT NULL,
      est_start_lo TIMESTAMPTZ, est_start_hi TIMESTAMPTZ,
      clinical_window_end TIMESTAMPTZ,
      latest_fingerprint TEXT, version INT NOT NULL DEFAULT 1,
      fhir_risk_assessment_id TEXT,
      summary JSONB NOT NULL DEFAULT '{}'::jsonb);

    CREATE TABLE volunteers (
      volunteer_id TEXT PRIMARY KEY, display_name TEXT,
      coarse_area GEOMETRY(Polygon,4326),           -- PRD 14.2: area, never live location
      available_from TIMESTAMPTZ, available_to TIMESTAMPTZ,
      reliability DOUBLE PRECISION NOT NULL DEFAULT 0.7,
      push_subscription JSONB);

    CREATE TABLE missions (
      mission_id TEXT PRIMARY KEY,
      episode_id TEXT NOT NULL REFERENCES episodes(episode_id),
      node_id TEXT NOT NULL, window_start TIMESTAMPTZ NOT NULL, window_end TIMESTAMPTZ NOT NULL,
      methods TEXT[] NOT NULL, mode TEXT NOT NULL,
      assignee_id TEXT, assignee_type TEXT, status TEXT NOT NULL,
      expected_gain DOUBLE PRECISION NOT NULL, realised_gain DOUBLE PRECISION,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now());

    CREATE SCHEMA sim_truth;
    CREATE TABLE sim_truth.injected_events (
      run_id TEXT NOT NULL, scenario_id TEXT NOT NULL,
      true_entry_node TEXT NOT NULL, true_start TIMESTAMPTZ NOT NULL,
      true_duration_s INT NOT NULL, true_mass DOUBLE PRECISION NOT NULL,
      contaminant TEXT NOT NULL, flow_condition TEXT NOT NULL,
      true_zone_arrivals JSONB NOT NULL,
      PRIMARY KEY (run_id, scenario_id));
    REVOKE ALL ON SCHEMA sim_truth FROM PUBLIC;
    REVOKE ALL ON ALL TABLES IN SCHEMA sim_truth FROM PUBLIC;
    REVOKE ALL ON SCHEMA sim_truth FROM kernel_role;

    GRANT SELECT, INSERT, UPDATE ON episodes, missions, volunteers TO app_role;
    GRANT SELECT, INSERT ON sensor_readings, rainfall TO app_role;
    GRANT SELECT, INSERT, UPDATE, DELETE ON network_nodes, network_edges, outfalls,
          receptor_zones, footpath_edges TO app_role;
    GRANT SELECT ON network_nodes, network_edges, outfalls, receptor_zones,
          sensor_readings, rainfall, episodes, missions TO kernel_role;
    GRANT SELECT, INSERT ON posterior_snapshots TO kernel_role;
    """)


def downgrade():
    op.execute("DROP SCHEMA sim_truth CASCADE;")
    for t in ["missions", "volunteers", "episodes", "posterior_snapshots", "rainfall",
              "sensor_readings", "footpath_edges", "receptor_zones", "outfalls",
              "network_edges", "network_nodes"]:
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE;")
