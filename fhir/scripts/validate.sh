#!/usr/bin/env bash
# fhir/scripts/validate.sh
#
# GC-3: zero errors from the HL7 validator against the OneAquaHealth IG, in CI
# and on write. Track 7 of the submission stands or falls on this, so the
# script exits non-zero on the first error and prints every one of them.
set -euo pipefail
cd "$(dirname "$0")/.."

winpath() {
  if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else printf '%s' "$1"; fi
}

# The IG is vendored, not published; sushi reads it from the package cache and
# the validator reads the tarball directly.
scripts/install-vendored-ig.sh
sushi . --log-level info

VALIDATOR=$(scripts/get-validator.sh)

REPORT=validation-report.json
rm -f "$REPORT"

# -ig vendor/... loads the OAH profiles our profiles derive from; -ig
# fsh-generated loads our own, so examples can be checked against them.
# The validator exits non-zero when it finds errors. That is the outcome this
# script exists to report on, so `set -e` must not swallow it before the report
# is read -- and CI still needs the report uploaded when the gate fails.
set +e
java -jar "$VALIDATOR" \
  fsh-generated/resources/*.json \
  -version 4.0.1 \
  -ig vendor/hl7.eu.fhir.oah.tgz \
  -ig fsh-generated \
  ${TX_SERVER_URL:+-tx "$TX_SERVER_URL"} \
  -output "$REPORT"
VALIDATOR_STATUS=$?
set -e

if [ ! -f "$REPORT" ]; then
  echo "the validator produced no report (exit $VALIDATOR_STATUS); it did not run" >&2
  exit 1
fi

python scripts/report_validation.py "$(winpath "$PWD")/$REPORT"
