#!/usr/bin/env bash
# fhir/scripts/load-into-hapi.sh
#
# Put the OneAquaHealth IG and Upstream's own profiles into a running HAPI, so
# that $validate has something to validate against (FR-26, GC-3 on write).
# Safe to re-run: every resource is written at a known id.
set -euo pipefail
cd "$(dirname "$0")/.."

BASE=${HAPI_BASE_URL:-http://localhost:8080/fhir}

echo "waiting for $BASE"
for _ in $(seq 1 60); do
  if curl -fsS -o /dev/null "$BASE/metadata"; then break; fi
  sleep 5
done
curl -fsS -o /dev/null "$BASE/metadata" || { echo "HAPI is not answering at $BASE" >&2; exit 1; }

[ -d fsh-generated/resources ] || sushi . --log-level warn

python scripts/load_into_hapi.py --base "$BASE" \
  vendor/hl7.eu.fhir.oah.tgz fsh-generated/resources
