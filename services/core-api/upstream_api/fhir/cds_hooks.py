"""CDS Hooks service (PRD 13.4, FR-28).

Three conditions, all of which must hold, or no card is returned:

  1. the patient's coarse area overlaps an active episode's exposure zone,
  2. the encounter falls inside the clinical relevance window,
  3. the reason for the visit matches the episode's syndrome set.

Any one of them alone would produce noise, and a decision-support card that
cries wolf is worse than no card: the clinician learns to dismiss it.

The service stores nothing about the patient. It reads the request, matches
against episode state already in memory, returns a card, and forgets. The only
thing written is an AuditEvent saying a card was or was not served (FR-30), and
that is written off the request path.
"""

from __future__ import annotations

import datetime as dt
import time

from fastapi import APIRouter, Request
from upstream_shared.codes import SYNDROME_SET

from ..db import pool
from .audit import write_audit

router = APIRouter(tags=["cds-hooks"])

SERVICE_ID = "upstream-exposure-context"
DISCLAIMER = "Environmental context, not a diagnosis."

# GC-9 gives this service 500 ms. A database round trip per hook call would
# spend most of that budget on work whose answer changes every few minutes at
# most, so active episodes are cached and refreshed on a short interval.
_CACHE_TTL_S = 30.0
_CACHE: dict = {"at": 0.0, "episodes": []}


@router.get("/cds-services")
def discovery() -> dict:
    common = {
        "title": "Upstream exposure context",
        "description": (
            "Shows recent stream contamination episodes affecting this patient's "
            "area, inside the clinical relevance window."
        ),
        "prefetch": {"patient": "Patient/{{context.patientId}}"},
    }
    return {
        "services": [
            dict(common, id=SERVICE_ID, hook="patient-view"),
            dict(common, id=f"{SERVICE_ID}-encounter", hook="encounter-start"),
        ]
    }


@router.post("/cds-services/{service_id}")
async def hook(service_id: str, request: Request) -> dict:
    body = await request.json()
    episode = match(
        coarse_area(body), encounter_time(body), reason_codes(body), active_episodes()
    )
    write_audit(
        "cds-card-served",
        outcome="0",
        detail={
            "service": service_id,
            "matched": bool(episode),
            "episode_id": episode["episode_id"] if episode else None,
        },
    )
    return {"cards": [card_for(episode)] if episode else []}


# --- The rule ---------------------------------------------------------------


def match(
    area: str | None,
    when: dt.datetime,
    reasons: list[str],
    episodes: list[dict],
) -> dict | None:
    """The three-condition rule. Pure, so every branch of it can be tested."""
    if not area or not reasons:
        return None
    if not set(reasons) & set(SYNDROME_SET):  # condition 3
        return None
    normalised = _normalise(area)
    for episode in episodes:
        if normalised not in episode["zone_areas"]:  # condition 1
            continue
        start = episode["exposure_start"] or episode["opened_at"]
        if not (start <= when <= episode["clinical_window_end"]):  # condition 2
            continue
        return episode
    return None


def card_for(episode: dict) -> dict:
    start = episode["exposure_start"] or episode["opened_at"]
    end = episode["exposure_end"] or episode["clinical_window_end"]
    window = f"{start.strftime('%d %b, %H:%M')}-{end.strftime('%H:%M')}"
    return {
        "summary": (
            "Recent stream contamination episode in this patient's area "
            f"({episode['episode_id']})"
        ),
        "indicator": "info",
        "detail": (
            f"Probable sewage-related contamination of a local stream on {window}. "
            "This visit is within the clinical relevance window. If symptoms fit, "
            "consider pathogen-specific stool testing (for example Cryptosporidium), "
            "which routine panels may not include. "
            f"{DISCLAIMER}"
        ),
        "source": {"label": "Upstream", "url": "https://upstream-onehealth.example"},
        "links": [
            {
                "label": "Episode details",
                "url": (
                    "https://upstream-onehealth.example/smart/launch"
                    f"?episode={episode['episode_id']}"
                ),
                "type": "smart",
            }
        ],
    }


# --- Reading the request ----------------------------------------------------


def coarse_area(body: dict) -> str | None:
    """The patient's area, and never anything finer (PRD 14.2, GC-7).

    A postcode district or a city district is as much geography as this service
    will look at. A full address or a coordinate is ignored even when the EHR
    sends one.
    """
    patient = ((body.get("prefetch") or {}).get("patient")) or {}
    for address in patient.get("address") or []:
        for field in ("district", "postalCode", "city"):
            value = address.get(field)
            if value:
                return str(value)
    return None


def encounter_time(body: dt.datetime | dict) -> dt.datetime:
    context = (body or {}).get("context") or {}
    for value in (context.get("encounterTime"), context.get("start")):
        parsed = _parse(value)
        if parsed is not None:
            return parsed
    encounter = (body.get("prefetch") or {}).get("encounter") or {}
    parsed = _parse((encounter.get("period") or {}).get("start"))
    return parsed if parsed is not None else dt.datetime.now(dt.UTC)


def reason_codes(body: dict) -> list[str]:
    context = (body or {}).get("context") or {}
    codes = list(context.get("reasonCodes") or context.get("reason") or [])
    encounter = (body.get("prefetch") or {}).get("encounter") or {}
    for reason in encounter.get("reasonCode") or []:
        codes.extend(c.get("code") for c in reason.get("coding") or [] if c.get("code"))
    return [str(c) for c in codes if c]


def _parse(value) -> dt.datetime | None:
    if isinstance(value, dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=dt.UTC)
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)


# --- Episode state ----------------------------------------------------------


def _normalise(area: str) -> str:
    return "".join(ch for ch in area.lower() if ch.isalnum())


def active_episodes(*, force: bool = False) -> list[dict]:
    if not force and time.time() - _CACHE["at"] < _CACHE_TTL_S:
        return _CACHE["episodes"]
    episodes = _read_active_episodes()
    _CACHE.update(at=time.time(), episodes=episodes)
    return episodes


def invalidate_cache() -> None:
    _CACHE.update(at=0.0, episodes=[])


def _read_active_episodes() -> list[dict]:
    """Episodes a clinician could still act on.

    SUSPECTED is deliberately excluded. A single unconfirmed citizen report is
    not grounds for prompting a clinician to order a test.
    """
    with pool.connection() as c, c.cursor() as cur:
        cur.execute(
            """SELECT e.episode_id, e.opened_at, e.est_start_lo, e.est_start_hi,
                      e.clinical_window_end, e.summary
                 FROM episodes e
                WHERE e.state IN ('PROBABLE','CONFIRMED')
                  AND e.clinical_window_end > now()"""
        )
        rows = cur.fetchall()
        zone_names = _zone_areas(cur)

    episodes = []
    for episode_id, opened_at, start_lo, start_hi, window_end, summary in rows:
        zones = list((summary or {}).get("zone_windows") or {})
        areas = set()
        for zone_id in zones:
            areas.add(_normalise(zone_id))
            areas.update(zone_names.get(zone_id, set()))
        episodes.append(
            {
                "episode_id": episode_id,
                "opened_at": opened_at,
                "exposure_start": start_lo,
                "exposure_end": start_hi,
                "clinical_window_end": window_end,
                "zone_areas": areas,
            }
        )
    return episodes


def _zone_areas(cur) -> dict[str, set[str]]:
    """The names a zone can be matched by.

    A production deployment maps postcode districts to zones from a gazetteer.
    The compiled catchment has no postcode layer, so a zone is matched by its
    identifier and its name -- which is what the CDS Hooks sandbox sends when a
    test patient's address is set to a zone.
    """
    cur.execute(
        "SELECT zone_id, name FROM receptor_zones "
        "WHERE network_version=(SELECT network_version FROM receptor_zones "
        "ORDER BY network_version DESC LIMIT 1)"
    )
    out: dict[str, set[str]] = {}
    for zone_id, name in cur.fetchall():
        out.setdefault(zone_id, set()).add(_normalise(zone_id))
        if name:
            out[zone_id].add(_normalise(name))
    return out
