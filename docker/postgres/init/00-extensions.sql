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

-- The boundary is symmetric, and it was not. Postgres grants CONNECT on every
-- database to PUBLIC, so clinical_role could open a session on the
-- environmental database. Table privileges denied every read, so nothing leaked
-- -- but one later `GRANT ... TO PUBLIC`, or one table created by a superuser
-- with default grants, would have opened it silently and nothing would have
-- said so. 01-rotate-passwords.sh grants kernel_role back in; the owner does
-- not need a grant.
REVOKE CONNECT ON DATABASE upstream FROM PUBLIC;
