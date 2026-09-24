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

# The OneAquaHealth Location profile slices Location.extension against
# artifact-relatedArtifact, an extension HAPI does not ship. Without it HAPI
# cannot evaluate the slicing and refuses every zone Location with "Slicing
# cannot be evaluated". sushi has already resolved the package into the FHIR
# package cache, so take it from there rather than pinning a version here.
CACHE=${FHIR_PACKAGE_CACHE:-$HOME/.fhir/packages}
EXTENSIONS=$(ls -d "$CACHE"/hl7.fhir.uv.extensions.r4#*/package 2>/dev/null | sort -V | tail -1 || true)
[ -n "$EXTENSIONS" ] ||
  echo "warning: no hl7.fhir.uv.extensions.r4 in $CACHE; zone Locations will not validate" >&2

python scripts/load_into_hapi.py --base "$BASE" \
  ${EXTENSIONS:+--optional "$EXTENSIONS"} \
  vendor/hl7.eu.fhir.oah.tgz fsh-generated/resources
