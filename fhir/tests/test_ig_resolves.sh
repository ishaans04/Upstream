#!/usr/bin/env bash
# fhir/tests/test_ig_resolves.sh
#
# Task 7.1's gate: the OneAquaHealth IG must be resolvable to every tool that
# needs it (sushi, the HL7 validator, HAPI). It is not published to
# packages.fhir.org, so we vendor a package built from the IG's own source and
# this test is what proves that package is usable (GC-2).
set -euo pipefail
cd "$(dirname "$0")/.."

fail() { echo "FAIL: $*" >&2; exit 1; }
ok()   { echo "ok: $*"; }

TGZ=vendor/hl7.eu.fhir.oah.tgz
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

# Git Bash hands out POSIX paths that the Windows python interpreter cannot
# open. Translate before crossing that boundary; a no-op everywhere else.
winpath() {
  if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else printf '%s' "$1"; fi
}

# 1. The vendored package exists.
[ -f "$TGZ" ] || fail "$TGZ is missing; run scripts/vendor-oah-ig.sh"
ok "vendored package present"

tar -xzf "$TGZ" -C "$WORK"
[ -f "$WORK/package/package.json" ] || fail "no package/package.json inside $TGZ"

# 2. It identifies itself as the OAH IG at the version the build pins.
read -r NAME VERSION CANONICAL FHIRVER <<EOF
$(python -c "
import json
m = json.load(open(r'$(winpath "$WORK")/package/package.json'))
print(m['name'], m['version'], m['canonical'], (m.get('fhirVersions') or ['?'])[0])
")
EOF
[ "$NAME" = "hl7.eu.fhir.oah" ] || fail "package name is $NAME, not hl7.eu.fhir.oah"
[ "$CANONICAL" = "http://hl7.eu/fhir/ig/oah" ] || fail "canonical is $CANONICAL"
[ "$FHIRVER" = "4.0.1" ] || fail "fhirVersion is $FHIRVER, not 4.0.1 (GC-2)"
ok "package identifies as $NAME#$VERSION on FHIR $FHIRVER"

# 3. OAH_IG_VERSION in the environment agrees with the package. Known correction
#    4: an empty or wrong version aborts HAPI startup.
[ -n "${OAH_IG_VERSION:-}" ] || fail "OAH_IG_VERSION is unset"
[ "$OAH_IG_VERSION" = "$VERSION" ] || fail "OAH_IG_VERSION=$OAH_IG_VERSION but the package is $VERSION"
ok "OAH_IG_VERSION matches the vendored package"

# 4. The profiles Phase 7.2 derives from are present (GC-2: derive, never invent).
for sd in observation-indicators-oah observation-with-component-oah \
          location-oah group-oah specimen-oah; do
  [ -f "$WORK/package/StructureDefinition-$sd.json" ] \
    || fail "OAH profile $sd is not in the package"
done
ok "the five OAH parent profiles are present"

# 5. sushi finds the IG and builds our project with zero errors (GC-3). A
#    missing dependency does not fail the build -- sushi carries on without the
#    parent profiles -- so the log is checked for the load itself, not just the
#    exit status.
scripts/install-vendored-ig.sh >/dev/null
sushi . --log-level info > "$WORK/sushi.log" 2>&1 \
  || { cat "$WORK/sushi.log"; fail "sushi build failed"; }
grep -q "Loaded hl7.eu.fhir.oah#$VERSION" "$WORK/sushi.log" \
  || { cat "$WORK/sushi.log"; fail "sushi did not load hl7.eu.fhir.oah#$VERSION"; }
grep -qE "0 Errors" "$WORK/sushi.log" \
  || { cat "$WORK/sushi.log"; fail "sushi reported errors"; }
ok "sushi loads the vendored IG and builds fhir/ with zero errors"

echo "PASS: the OneAquaHealth IG resolves"
