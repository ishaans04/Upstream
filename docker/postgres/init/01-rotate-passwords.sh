#!/bin/bash
# Automates the password rotation the plan describes after 00-extensions.sql:
# that file runs before .env interpolation, so the roles are created with a
# placeholder and given their real passwords here, from the container env.
set -euo pipefail

: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD must be set}"
CLINICAL_PW="${CLINICAL_DB_PASSWORD:-$POSTGRES_PASSWORD}"
HAPI_PW="${HAPI_DB_PASSWORD:-$POSTGRES_PASSWORD}"
KERNEL_PW="${KERNEL_DB_PASSWORD:-$POSTGRES_PASSWORD}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<SQL
ALTER ROLE clinical_role WITH PASSWORD '${CLINICAL_PW}';
ALTER ROLE hapi_role     WITH PASSWORD '${HAPI_PW}';

-- kernel_role is created by migration 0001 (NOLOGIN there); give it a login now
-- so KERNEL_DATABASE_URL works. Migration 0001 is idempotent about the role.
DO \$\$ BEGIN CREATE ROLE kernel_role LOGIN PASSWORD '${KERNEL_PW}';
EXCEPTION WHEN duplicate_object THEN
  ALTER ROLE kernel_role WITH LOGIN PASSWORD '${KERNEL_PW}';
END \$\$;
GRANT CONNECT ON DATABASE ${POSTGRES_DB} TO kernel_role;
SQL
