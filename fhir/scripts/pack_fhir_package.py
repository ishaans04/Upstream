#!/usr/bin/env python3
"""Assemble a FHIR NPM package tarball from a directory of resource JSON files.

The OneAquaHealth IG is not published to packages.fhir.org and has no GitHub
release, so Upstream vendors a package built from the IG's own source. This is
the packaging half of `vendor-oah-ig.sh`; it is deliberately a separate file so
that the shell script contains no embedded program text.
"""

from __future__ import annotations

import json
import shutil
import sys
import tarfile
import tempfile
from pathlib import Path

# The IG declares these in its own sushi-config.yaml; they are repeated here
# because a package manifest must carry them and sushi does not emit one.
MANIFEST = {
    "name": "hl7.eu.fhir.oah",
    "version": "0.1.0-ci-build",
    "canonical": "http://hl7.eu/fhir/ig/oah",
    "url": "http://hl7.eu/fhir/ig/oah",
    "title": "OneAquaHealth Project",
    "description": (
        "The OneAquaHealth project FHIR implementation guide. Vendored by "
        "Upstream from https://github.com/hl7-eu/oah because the package is "
        "not published to a registry."
    ),
    "fhirVersions": ["4.0.1"],
    "type": "IG",
    "author": "OneAquaHealth Project",
    "dependencies": {
        "hl7.fhir.r4.core": "4.0.1",
        "hl7.fhir.uv.xver-r5.r4": "0.1.0",
    },
}


def index_entry(path: Path, resource: dict) -> dict:
    entry = {
        "filename": path.name,
        "resourceType": resource.get("resourceType"),
        "id": resource.get("id"),
    }
    for field in ("url", "version", "kind", "type", "supplements"):
        if field in resource:
            entry[field] = resource[field]
    return entry


def main(source_dir: str, out_tgz: str) -> int:
    source = Path(source_dir)
    resources = sorted(source.glob("*.json"))
    if not resources:
        print(f"no resource JSON found in {source}", file=sys.stderr)
        return 1

    staging = Path(tempfile.mkdtemp()) / "package"
    staging.mkdir(parents=True)
    try:
        files = []
        for path in resources:
            resource = json.loads(path.read_text(encoding="utf-8"))
            if "resourceType" not in resource:
                continue
            shutil.copy2(path, staging / path.name)
            files.append(index_entry(path, resource))

        (staging / "package.json").write_text(
            json.dumps(MANIFEST, indent=2) + "\n", encoding="utf-8"
        )
        (staging / ".index.json").write_text(
            json.dumps({"index-version": 1, "files": files}, indent=2) + "\n",
            encoding="utf-8",
        )

        out = Path(out_tgz)
        out.parent.mkdir(parents=True, exist_ok=True)
        # Deterministic member order so the tarball is stable across rebuilds
        # (GC-6): the same IG source must always produce the same artefact.
        with tarfile.open(out, "w:gz") as tar:
            for name in sorted(p.name for p in staging.iterdir()):
                tar.add(staging / name, arcname=f"package/{name}")

        print(f"{out} <- {len(files)} resources from {source}")
        return 0
    finally:
        shutil.rmtree(staging.parent, ignore_errors=True)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: pack_fhir_package.py <resource-dir> <out.tgz>", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
