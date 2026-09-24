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


# A $validate against a server holding a full IG plus the HL7 extensions pack
# is not a quick call, and it gets slower while the server is busy. Publishing
# is off the critical path -- it happens after a state change is already
# durable -- so it can afford to wait. The 500 ms budget in GC-9 is CDS Hooks',
# and nothing here is on that path.
DEFAULT_TIMEOUT_S = 90.0


class FhirClient:
    def __init__(self, base_url: str | None = None, *, timeout: float | None = None):
        self.base = (base_url or settings.hapi_base_url).rstrip("/")
        self.timeout = timeout if timeout is not None else DEFAULT_TIMEOUT_S

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

    def put_unchanged_once(self, resource: dict, *, compare: tuple[str, ...]) -> dict:
        """Write only if the server does not already hold this resource unchanged.

        An episode's basis is every observation in the kernel's 24-hour horizon,
        and a busy catchment has hundreds. Observations are immutable apart from
        a retraction flipping the status, so re-validating and re-writing all of
        them on every state change is work with no result -- and each write costs
        a full $validate. The comparison is deliberately narrow: only the named
        fields are checked, and anything unexpected falls through to a real write.
        """
        resource_type, resource_id = resource["resourceType"], resource["id"]
        try:
            response = httpx.get(
                f"{self.base}/{resource_type}/{resource_id}", timeout=self.timeout
            )
        except httpx.HTTPError:
            return self.put(resource)

        if response.status_code == 200:
            existing = response.json()
            if all(existing.get(field) == resource.get(field) for field in compare):
                return {
                    "resourceType": resource_type,
                    "id": resource_id,
                    "version": _version_from(response),
                }
        return self.put(resource)

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
