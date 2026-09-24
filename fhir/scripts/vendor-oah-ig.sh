#!/usr/bin/env bash
# fhir/scripts/vendor-oah-ig.sh
#
# Rebuild fhir/vendor/hl7.eu.fhir.oah.tgz from the OneAquaHealth IG's source.
#
# Why this exists (Task 7.1, Step 1): `hl7.eu.fhir.oah` is not on
# packages.fhir.org, is absent from build.fhir.org's IG index, and the GitHub
# repository has no release. There is therefore nothing for sushi, the HL7
# validator or HAPI to download, and GC-2 forbids inventing a parallel model.
# So we build the IG's FSH ourselves and vendor the resulting package. The
# tarball is committed: GC-6 reproducibility beats repository tidiness.
#
# Only the IG's data files are copied into the build directory -- its
# sushi-config.yaml and input/fsh. None of its shell scripts, templates or
# build tooling is executed.
set -euo pipefail
cd "$(dirname "$0")/.."

# Git Bash hands out POSIX paths that the Windows java and python binaries
# cannot open. Translate before crossing that boundary; a no-op elsewhere.
winpath() {
  if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else printf '%s' "$1"; fi
}

IG_REPO=${IG_REPO:-https://github.com/hl7-eu/oah.git}
IG_REF=${IG_REF:-master}
OUT=vendor/hl7.eu.fhir.oah.tgz

command -v sushi >/dev/null || { echo "sushi is not installed: npm install -g fsh-sushi@3" >&2; exit 1; }

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

echo "cloning $IG_REPO@$IG_REF"
git clone --depth 1 --branch "$IG_REF" "$IG_REPO" "$WORK/src" >/dev/null 2>&1

# Data files only.
mkdir -p "$WORK/build/input"
cp "$WORK/src/sushi-config.yaml" "$WORK/build/sushi-config.yaml"
cp -r "$WORK/src/input/fsh" "$WORK/build/input/fsh"
find "$WORK/build" -type f ! -name '*.fsh' ! -name '*.yaml' -delete
rm -rf "$WORK/src"

echo "compiling the IG's FSH"
(cd "$WORK/build" && sushi . --log-level warn)

RESOURCES=$WORK/build/fsh-generated/resources

# sushi emits differentials only; the IG Publisher is what normally adds
# snapshots. Without them sushi refuses to derive from these profiles at all
# ("missing a snapshot. Snapshot is required for import"), so GC-2 would be
# unreachable. Generate them with the validator instead of running the whole
# publisher, which needs Jekyll and a template we do not otherwise use.
VALIDATOR=$(scripts/get-validator.sh)
echo "generating snapshots"
java -jar "$VALIDATOR" snapshot "$(winpath "$RESOURCES")"/StructureDefinition-*.json \
  -version 4.0.1 -ig "$(winpath "$RESOURCES")" -outputSuffix snap.json
for f in "$RESOURCES"/*.json.snap.json; do
  mv -f "$f" "${f%.json.snap.json}.json"
done

python scripts/pack_fhir_package.py "$RESOURCES" "$OUT"

echo "wrote $OUT"
