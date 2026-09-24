#!/usr/bin/env bash
# fhir/scripts/install-vendored-ig.sh
#
# Put the vendored OneAquaHealth IG where sushi and the IG Publisher look for
# packages. They resolve dependencies from the FHIR package cache
# (~/.fhir/packages) and fall back to packages.fhir.org, where this IG does not
# exist -- so without this step a sushi build silently loses every OAH parent
# profile and GC-2 cannot be met. The HL7 validator is passed the tarball
# directly and does not need this.
set -euo pipefail
cd "$(dirname "$0")/.."

TGZ=vendor/hl7.eu.fhir.oah.tgz
[ -f "$TGZ" ] || { echo "$TGZ is missing; run scripts/vendor-oah-ig.sh" >&2; exit 1; }

VERSION=$(python -c "
import json, tarfile
with tarfile.open('$TGZ') as t:
    print(json.load(t.extractfile('package/package.json'))['version'])
")

CACHE=${FHIR_PACKAGE_CACHE:-$HOME/.fhir/packages}
DEST="$CACHE/hl7.eu.fhir.oah#$VERSION"

rm -rf "$DEST"
mkdir -p "$DEST"
tar -xzf "$TGZ" -C "$DEST"
echo "installed hl7.eu.fhir.oah#$VERSION into $CACHE"
