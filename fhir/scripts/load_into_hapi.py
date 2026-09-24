#!/usr/bin/env python3
"""Load the OneAquaHealth IG and Upstream's own profiles into HAPI.

`$validate` can only check a resource against a profile the server holds, so
without this step validation-on-write (FR-26, the "on write" half of GC-3)
silently checks nothing but base R4.

This is a separate step rather than HAPI's boot-time package installer on
purpose. That installer makes the server's startup depend on resolving a
package; the OAH IG is on no registry, and when it cannot be resolved HAPI does
not start at all. It also only ever loads dependencies, never the IG being
developed -- so Upstream's own profiles would still be missing.

Only conformance resources are loaded. The OAH package also carries 469
examples, which HAPI does not need in order to validate and which would take far
longer to write than they are worth.
"""

from __future__ import annotations

import argparse
import json
import sys
import tarfile
import urllib.error
import urllib.request
from pathlib import Path

# What $validate needs in order to check a resource against a profile.
#
# ConceptMap is deliberately not here. The OneAquaHealth IG ships seven of them,
# mapping its logical models to FHIR, and all seven fail ele-1 ("All FHIR
# elements must have a @value or children") -- HAPI rejects every one with a
# 422. They are model documentation: nothing validates against a ConceptMap, so
# loading them would buy nothing and cost a red exit on every run.
CONFORMANCE = (
    "CodeSystem",
    "ValueSet",
    "StructureDefinition",
    "SearchParameter",
    "NamingSystem",
)


def put(base: str, resource: dict, *, timeout: float) -> tuple[bool, str]:
    url = f"{base}/{resource['resourceType']}/{resource['id']}"
    request = urllib.request.Request(
        url,
        data=json.dumps(resource).encode(),
        headers={"Content-Type": "application/fhir+json"},
        method="PUT",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return True, str(response.status)
    except urllib.error.HTTPError as exc:
        return False, f"{exc.code} {exc.read()[:300].decode(errors='replace')}"
    except OSError as exc:
        return False, str(exc)


def resources_from_tarball(path: Path):
    with tarfile.open(path) as tar:
        for member in tar.getmembers():
            if not member.name.endswith(".json") or member.name.endswith("package.json"):
                continue
            handle = tar.extractfile(member)
            if handle is None:
                continue
            try:
                yield json.loads(handle.read().decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue


def resources_from_directory(path: Path):
    for file in sorted(path.glob("*.json")):
        try:
            yield json.loads(file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue


def load(base: str, sources: list[Path], *, timeout: float) -> int:
    written = failed = skipped = 0
    failures: list[str] = []
    for source in sources:
        if not source.exists():
            print(f"missing source: {source}", file=sys.stderr)
            return 1
        stream = (
            resources_from_tarball(source)
            if source.is_file()
            else resources_from_directory(source)
        )
        for resource in stream:
            if resource.get("resourceType") not in CONFORMANCE or not resource.get("id"):
                skipped += 1
                continue
            ok, detail = put(base, resource, timeout=timeout)
            if ok:
                written += 1
            else:
                failed += 1
                failures.append(f"{resource['resourceType']}/{resource['id']}: {detail}")

    print(f"loaded {written} conformance resources into {base} "
          f"({skipped} non-conformance skipped, {failed} failed)")
    for failure in failures[:20]:
        print(f"  {failure}", file=sys.stderr)
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://localhost:8080/fhir")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument(
        "sources",
        nargs="*",
        default=["vendor/hl7.eu.fhir.oah.tgz", "fsh-generated/resources"],
        help="package tarballs or directories of resource JSON",
    )
    args = parser.parse_args()
    return load(
        args.base.rstrip("/"), [Path(s) for s in args.sources], timeout=args.timeout
    )


if __name__ == "__main__":
    raise SystemExit(main())
