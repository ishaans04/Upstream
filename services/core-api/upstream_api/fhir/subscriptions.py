"""Topic-based Subscription registration (FR-29).

R4 has no SubscriptionTopic resource and the R4 subscriptions backport does not
add one: a topic is a canonical URL carried in `Subscription.criteria`. So the
topic below is a URL Upstream owns and publishes in its IG, and the Subscription
is a real resource registered against HAPI.

The payload is `id-only` on purpose. A notification that carried the episode
would push health-relevant content down a channel nobody audited; making the
subscriber read the episode back over the API keeps every read on the record
(FR-30).
"""

from __future__ import annotations

import logging

from ..config import settings
from .client import FhirClient

log = logging.getLogger(__name__)

TOPIC = "https://upstream-onehealth.example/SubscriptionTopic/episode-state-change"
BACKPORT = "http://hl7.org/fhir/uv/subscriptions-backport/StructureDefinition"
SUBSCRIPTION_ID = "upstream-episode-state-change"

EPISODE_STATE_TAG = "https://upstream-onehealth.example/CodeSystem/episode-state"


def subscription_for(endpoint: str) -> dict:
    return {
        "resourceType": "Subscription",
        "id": SUBSCRIPTION_ID,
        "meta": {"profile": [f"{BACKPORT}/backport-subscription"]},
        "status": "requested",
        "reason": "Notify public health systems of Exposure Episode state changes",
        "criteria": TOPIC,
        "_criteria": {
            "extension": [
                {
                    "url": f"{BACKPORT}/backport-filter-criteria",
                    "valueString": f"RiskAssessment?_tag={EPISODE_STATE_TAG}|",
                }
            ]
        },
        "channel": {
            "type": "rest-hook",
            "endpoint": endpoint,
            "payload": "application/fhir+json",
            "_payload": {
                "extension": [
                    {"url": f"{BACKPORT}/backport-payload-content", "valueCode": "id-only"}
                ]
            },
        },
    }


def register(endpoint: str | None = None) -> dict | None:
    """Register the episode-state-change subscription, if one is configured.

    No endpoint configured means nobody is subscribing, which is the normal
    state in development and at a demo. That is not an error and must not stop
    the API from starting.
    """
    endpoint = endpoint or getattr(settings, "subscription_endpoint", "") or ""
    if not endpoint:
        log.info("no subscription endpoint configured; FR-29 registration skipped")
        return None
    try:
        return FhirClient().put(subscription_for(endpoint))
    except Exception:
        log.exception("registering the episode state change subscription failed")
        return None
