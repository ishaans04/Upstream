"""A HAPI client that validates before it writes (FR-26, GC-3).

GC-3 is "zero errors from the HL7 validator, in CI **and on write**". CI checks
the profiles and the examples; this checks every resource Upstream actually
publishes, against the server that will store it. A validation error is a hard
failure: an invalid resource is never written and the caller hears about it.
"""

from __future__ import annotations

import httpx

from ..config import settings

FAILING_SEVERITIES = ("error", "fatal")


class FhirValidationError(ValueError):
    """A resource failed validation, so it was not written (GC-3)."""

    def __init__(self, resource_type: str, resource_id: str, issues: list[dict]):
        self.resource_type = resource_type
        self.resource_id = resource_id
        self.issues = issues
        detail = "; ".join(_describe(i) for i in issues) or "no detail"
        super().__init__(
            f"GC-3: {resource_type}/{resource_id} has {len(issues)} validator "
            f"error(s) and was not written: {detail}"
        )


def _describe(issue: dict) -> str:
    where = ", ".join(issue.get("expression") or issue.get("location") or []) or "?"
    text = (issue.get("details") or {}).get("text") or issue.get("diagnostics") or ""
    return f"{where}: {text}"


class FhirClient:
    def __init__(self, base_url: str | None = None, *, timeout: float = 30.0):
        self.base = (base_url or settings.hapi_base_url).rstrip("/")
        self.timeout = timeout

    def validate(self, resource: dict) -> dict:
        """Ask the server whether it would accept this resource."""
        resource_type = resource["resourceType"]
        response = httpx.post(
            f"{self.base}/{resource_type}/$validate",
            json=resource,
            headers={"Content-Type": "application/fhir+json"},
            timeout=self.timeout,
        )
        # $validate answers with an OperationOutcome for both outcomes, so a 4xx
        # here is the report, not a transport failure. Anything without a JSON
        # body is a real failure and should surface as one.
        outcome = response.json()
        issues = [
            i
            for i in outcome.get("issue", [])
            if i.get("severity") in FAILING_SEVERITIES
        ]
        return {"issue_errors": len(issues), "issues": issues}

    def put(self, resource: dict) -> dict:
        """Validate, then write at a known id. Returns the id and version."""
        resource_type, resource_id = resource["resourceType"], resource["id"]
        report = self.validate(resource)
        if report["issue_errors"]:
            raise FhirValidationError(resource_type, resource_id, report["issues"])

        response = httpx.put(
            f"{self.base}/{resource_type}/{resource_id}",
            json=resource,
            headers={"Content-Type": "application/fhir+json"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return {
            "resourceType": resource_type,
            "id": resource_id,
            "version": _version_from(response),
        }

    def post(self, resource: dict) -> dict:
        """Validate, then create at a server-assigned id."""
        resource_type = resource["resourceType"]
        report = self.validate(resource)
        if report["issue_errors"]:
            raise FhirValidationError(resource_type, resource.get("id", ""), report["issues"])

        response = httpx.post(
            f"{self.base}/{resource_type}",
            json=resource,
            headers={"Content-Type": "application/fhir+json"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return {
            "resourceType": resource_type,
            "id": _id_from(response, resource_type),
            "version": _version_from(response),
        }


def _version_from(response: httpx.Response) -> str:
    """The version id out of an ETag like W/"3".

    Without it a Provenance target would name no version, and the whole point of
    publishing provenance is that it describes one exact version.
    """
    etag = response.headers.get("ETag", "")
    return etag.removeprefix("W/").strip('"') or "1"


def _id_from(response: httpx.Response, resource_type: str) -> str:
    location = response.headers.get("Location") or response.headers.get("Content-Location")
    if location and f"{resource_type}/" in location:
        return location.split(f"{resource_type}/", 1)[1].split("/")[0]
    return (response.json() or {}).get("id", "")
