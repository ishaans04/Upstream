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
import urllib.parse
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


def load(base: str, sources: list[Path], optional: set[Path], *, timeout: float) -> int:
    written = failed = skipped = 0
    failures: list[str] = []
    tolerated: list[str] = []
    for source in sources:
        if not source.exists():
            print(f"missing source: {source}", file=sys.stderr)
            return 1
        best_effort = source in optional
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
            elif best_effort:
                tolerated.append(f"{resource['resourceType']}/{resource['id']}: {detail}")
            else:
                failed += 1
                failures.append(f"{resource['resourceType']}/{resource['id']}: {detail}")

    print(f"loaded {written} conformance resources into {base} "
          f"({skipped} non-conformance skipped, {failed} failed, "
          f"{len(tolerated)} tolerated from optional packages)")
    # Tolerated is not the same as unseen. A dependency package that suddenly
    # stops loading is worth noticing even when it cannot fail the run.
    for entry in tolerated[:5]:
        print(f"  tolerated: {entry}", file=sys.stderr)
    if len(tolerated) > 5:
        print(f"  ... and {len(tolerated) - 5} more tolerated", file=sys.stderr)
    for failure in failures[:20]:
        print(f"  {failure}", file=sys.stderr)
    return 1 if failed else 0


def verify_terminology(base: str, sources: list[Path], *, timeout: float) -> int:
    """Check that the *last* concept of each loaded CodeSystem resolves.

    HAPI defers indexing for a CodeSystem with more concepts than
    `hapi.fhir.defer_indexing_for_codesystems_of_size` (100 by default), and
    until that background job runs it answers $validate with "Code is not found
    in CodeSystem" while still reporting the CodeSystem as supported. The
    OneAquaHealth system has 185 concepts. Nothing about that failure points at
    its cause, so it is checked here instead of being discovered later as an
    unexplainable rejected write.

    HAPI also skips a no-op update, so a CodeSystem already stored under a lower
    threshold is not re-imported by loading it again -- it has to be deleted
    first. That is what the remedy below says.
    """
    missing = []
    for source in sources:
        stream = (
            resources_from_tarball(source)
            if source.is_file()
            else resources_from_directory(source)
        )
        for resource in stream:
            concepts = resource.get("concept") or []
            if resource.get("resourceType") != "CodeSystem" or len(concepts) < 2:
                continue
            code = concepts[-1]["code"]
            url = (
                f"{base}/CodeSystem/$lookup"
                f"?system={urllib.parse.quote(resource['url'], safe='')}"
                f"&code={urllib.parse.quote(code, safe='')}"
            )
            try:
                with urllib.request.urlopen(url, timeout=timeout):
                    pass
            except (urllib.error.HTTPError, OSError):
                missing.append(f"{resource['url']}#{code} ({len(concepts)} concepts)")

    if missing:
        print(
            "\nterminology is incompletely indexed; $validate will reject valid codes:",
            file=sys.stderr,
        )
        for entry in missing:
            print(f"  {entry}", file=sys.stderr)
        print(
            "  remedy: raise hapi.fhir.defer_indexing_for_codesystems_of_size above the\n"
            "  concept count (docker-compose.yml, via SPRING_APPLICATION_JSON), recreate\n"
            "  the container with `docker compose up -d --force-recreate hapi` -- a plain\n"
            "  `up -d` restarts it without applying the new environment -- then DELETE the\n"
            "  CodeSystem and re-run this script. HAPI skips a no-op update, so loading it\n"
            "  again on its own will not re-import the concepts.",
            file=sys.stderr,
        )
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://localhost:8080/fhir")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument(
        "--optional",
        action="append",
        default=[],
        metavar="SOURCE",
        help=(
            "a source whose individual failures do not fail the run. Used for "
            "upstream dependency packages: HAPI rejects a handful of R5-flavoured "
            "artefacts in the HL7 extensions pack, and none of them is anything "
            "Upstream validates against."
        ),
    )
    parser.add_argument(
        "sources",
        nargs="*",
        default=["vendor/hl7.eu.fhir.oah.tgz", "fsh-generated/resources"],
        help="package tarballs or directories of resource JSON",
    )
    args = parser.parse_args()
    optional = {Path(s) for s in args.optional}
    sources = [Path(s) for s in args.sources]
    base = args.base.rstrip("/")
    status = load(base, [*optional, *sources], optional, timeout=args.timeout)
    return status or verify_terminology(base, sources, timeout=args.timeout)


if __name__ == "__main__":
    raise SystemExit(main())
