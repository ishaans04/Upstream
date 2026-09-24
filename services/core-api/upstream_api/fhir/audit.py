"""AuditEvent for every card served and every external read (FR-30, PRD 14.3).

Two rules shape this module.

An audit record says that a decision was made and which episode it was about. It
never carries clinical content -- not the reason for the visit, not the patient,
not the area. Recording what a clinician was looking at would turn the audit
trail into exactly the patient-level store GC-7 forbids.

And an audit write never blocks a clinician. The resource is built here and
handed to a sink; the default sink writes to HAPI on a worker thread, so a slow
or unreachable HAPI costs the request nothing (NFR-2, GC-9).
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from .client import FhirClient

log = logging.getLogger(__name__)

AUDIT_EVENT_TYPE_CS = "http://terminology.hl7.org/CodeSystem/audit-event-type"
SECURITY_ROLE_CS = "http://terminology.hl7.org/CodeSystem/extra-security-role-type"

# Only these keys ever reach an audit record. Anything else a caller passes is
# dropped rather than trusted, because the caller is holding a request that
# contains a patient.
PERMITTED_DETAIL = ("service", "matched", "episode_id")

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="audit")


def audit_event(action: str, *, outcome: str, detail: dict) -> dict:
    """Build the AuditEvent. Pure, so what gets recorded can be asserted on."""
    safe = {k: detail.get(k) for k in PERMITTED_DETAIL if k in detail}
    return {
        "resourceType": "AuditEvent",
        "id": f"audit-{uuid.uuid4().hex[:24]}",
        "type": {
            "system": AUDIT_EVENT_TYPE_CS,
            "code": "rest",
            "display": "RESTful Operation",
        },
        "action": "R",
        "recorded": dt.datetime.now(dt.UTC).isoformat(),
        "outcome": outcome,
        "agent": [
            {
                "type": {"coding": [{"system": SECURITY_ROLE_CS, "code": "dataprocessor"}]},
                "who": {"display": "upstream-cds-hooks"},
                "requestor": False,
            }
        ],
        "source": {"observer": {"display": "Upstream Core API"}},
        "entity": [
            {
                "what": {"display": safe.get("episode_id") or "no-match"},
                "detail": [
                    {"type": "action", "valueString": action},
                    *[
                        {"type": key, "valueString": str(value)}
                        for key, value in safe.items()
                        if key != "episode_id"
                    ],
                ],
            }
        ],
    }


def _write_to_hapi(resource: dict) -> None:
    try:
        FhirClient().put(resource)
    except Exception:
        log.exception("writing an AuditEvent failed; the request it describes was served")


#: Where audit records go. Tests replace this to observe what was recorded.
sink: Callable[[dict], None] = _write_to_hapi


def write_audit(action: str, *, outcome: str, detail: dict) -> dict:
    """Record one audited action. Returns the resource, for callers that test it."""
    resource = audit_event(action, outcome=outcome, detail=detail)
    _executor.submit(sink, resource)
    return resource
