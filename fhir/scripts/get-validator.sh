#!/usr/bin/env bash
# fhir/scripts/get-validator.sh
#
# Print the path to the HL7 validator jar, downloading it first if needed.
# Both validate.sh and vendor-oah-ig.sh need it: one to check resources, the
# other to generate the snapshots a derived IG cannot be built without.
set -euo pipefail
cd "$(dirname "$0")/.."

VALIDATOR=${VALIDATOR:-.validator/validator_cli.jar}
if [ ! -f "$VALIDATOR" ]; then
  echo "downloading the HL7 validator" >&2
  mkdir -p "$(dirname "$VALIDATOR")"
  curl -fL --retry 3 -o "$VALIDATOR" \
    https://github.com/hapifhir/org.hl7.fhir.core/releases/latest/download/validator_cli.jar >&2
fi
printf '%s' "$VALIDATOR"
