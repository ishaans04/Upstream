#!/usr/bin/env python3
"""Turn the HL7 validator's OperationOutcome into a pass/fail verdict.

GC-3 allows zero errors, so this exits 1 if any issue is error or fatal and
prints each one with the file and element it came from. The plan reached for
`jq`; this host has no jq and the repository already depends on Python, so the
gate is written once, here, and behaves identically on Windows and in CI.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

FAILING = {"error", "fatal"}


def issues(report: dict):
    """Yield (source, issue) for every issue in the report.

    The validator emits a single OperationOutcome when given one file and a
    Bundle of them when given several, so both shapes have to be walked.
    """
    if report.get("resourceType") == "Bundle":
        for entry in report.get("entry", []):
            outcome = entry.get("resource", {})
            source = _source_of(outcome) or entry.get("fullUrl", "?")
            for issue in outcome.get("issue", []):
                yield source, issue
    else:
        source = _source_of(report) or "?"
        for issue in report.get("issue", []):
            yield source, issue


def _source_of(outcome: dict) -> str | None:
    for extension in outcome.get("extension", []):
        if extension.get("url", "").endswith("/OperationOutcome.file"):
            return extension.get("valueString")
    return None


def describe(source: str, issue: dict) -> str:
    location = ", ".join(issue.get("expression") or issue.get("location") or [])
    text = (issue.get("details") or {}).get("text") or issue.get("diagnostics") or ""
    where = f"{Path(source).name}:{location}" if location else Path(source).name
    return f"  [{issue.get('severity')}] {where}\n    {text}"


def main(report_path: str) -> int:
    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    found = list(issues(report))

    errors = [(s, i) for s, i in found if i.get("severity") in FAILING]
    warnings = [(s, i) for s, i in found if i.get("severity") == "warning"]

    print(f"validator errors: {len(errors)}  warnings: {len(warnings)}")
    if warnings:
        for source, issue in warnings:
            print(describe(source, issue))
    if errors:
        print("\nGC-3 requires zero errors against the OneAquaHealth IG:")
        for source, issue in errors:
            print(describe(source, issue))
        return 1
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: report_validation.py <validation-report.json>", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
