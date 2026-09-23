-- docker/postgres/init/00-extensions.sql
CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pgrouting;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- GC-7 health-data boundary: a physically separate database with its own owner.
CREATE ROLE clinical_role LOGIN PASSWORD 'set-from-env';
CREATE DATABASE clinical OWNER clinical_role;
REVOKE CONNECT ON DATABASE clinical FROM PUBLIC;

-- HAPI gets its own database; the FHIR store is a rebuildable view (GC-2).
CREATE ROLE hapi_role LOGIN PASSWORD 'set-from-env';
CREATE DATABASE hapi OWNER hapi_role;
