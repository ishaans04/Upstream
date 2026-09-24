"""Map internal state to FHIR R4 on the OneAquaHealth IG (PRD 13.2, 13.3).

Every function here is pure: internal state in, a resource dict out. No I/O, no
database, no HAPI. That is what lets the publisher be a thin shell and the
mapper be tested exhaustively without a container.
"""

from __future__ import annotations

import base64
import datetime as dt
import json
import re

from upstream_shared.codes import LOCAL_CS, ObservationMethod
from upstream_shared.episode import EpisodeState

SD = "https://upstream-onehealth.example/StructureDefinition"
EPISODE_ID_SYSTEM = "https://upstream-onehealth.example/episode"
NODE_ID_SYSTEM = "https://upstream-onehealth.example/network/node"
ZONE_ID_SYSTEM = "https://upstream-onehealth.example/zone"

OAH_CS = "http://hl7.eu/fhir/ig/oah/CodeSystem/temporarySystem-oah-eu"
SNOMED = "http://snomed.info/sct"
UCUM = "http://unitsofmeasure.org"
INTERPRETATION_CS = "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation"
PARTICIPANT_TYPE_CS = "http://terminology.hl7.org/CodeSystem/provenance-participant-type"
LOCATION_PHYSICAL_TYPE_CS = "http://terminology.hl7.org/CodeSystem/location-physical-type"
OBS_CATEGORY_CS = "http://terminology.hl7.org/CodeSystem/observation-category"
BOUNDARY_EXT = "http://hl7.org/fhir/StructureDefinition/location-boundary-geojson"

DISCLAIMER = (
    "Environmental context, not a diagnosis. This is a probabilistic hypothesis about a "
    "place, computed from environmental observations. It is not an advisory and it names "
    "no polluter."
)

# GC-11: PULSE produces 80% credible windows, and the published window says so
# rather than leaving a reader to assume a level.
CREDIBLE_LEVEL = 0.80

# The kernel's no-event hypothesis. It is a column in the posterior, not a place
# on the network, and publishing it as a candidate source would invent a location.
NO_EVENT_KEY = "__none__"

MAX_RANKED_SOURCES = 3

_STATUS = {
    EpisodeState.SUSPECTED: "preliminary",
    EpisodeState.PROBABLE: "preliminary",
    EpisodeState.CONFIRMED: "final",
    EpisodeState.RESOLVED: "final",
    EpisodeState.REFUTED: "cancelled",
}

_OPEN_STATES = (EpisodeState.SUSPECTED, EpisodeState.PROBABLE)

# GC-2: *what* was observed is OneAquaHealth terminology. Upstream contributes
# instruments, not concepts, so each observation method resolves to the OAH
# indicator that instrument measures. Evidence that carries its own oah_codes
# (the normaliser can propose them) overrides this table.
INDICATOR_FOR_METHOD: dict[str, str] = {
    ObservationMethod.CITIZEN_VISUAL_OLFACTORY: "foam",
    ObservationMethod.CITIZEN_FREETEXT: "foam",
    ObservationMethod.CITIZEN_PHOTO: "foam",
    # Field strips read ammonium and nitrite; ammonium is the sewage marker.
    ObservationMethod.TEST_STRIP: "ammonium",
    ObservationMethod.FIELD_TEST: "ammonium",
    ObservationMethod.SENSOR_TURBIDITY: "tss",
    ObservationMethod.SENSOR_CONDUCTIVITY: "conductivity",
    # A sensor that stayed normal does not say which sensor it was. The physics
    # parameters give sensor_normal_window the same detection curve as
    # sensor_turbidity, so turbidity is what the kernel treats it as.
    ObservationMethod.SENSOR_NORMAL_WINDOW: "tss",
    ObservationMethod.LAB_ECOLI: "coliforms",
    ObservationMethod.LAB_ENTEROCOCCI: "coliforms",
    # An overflow activation is an event in the stream's hydrology, not a water
    # quality measurement. OAH has no discharge indicator; this is the nearest
    # concept it does have.
    ObservationMethod.OVERFLOW_TELEMETRY: "hydrology",
    ObservationMethod.BIOASSESSMENT: "macroinvertebreates",
}

_LAB_METHODS = {ObservationMethod.LAB_ECOLI, ObservationMethod.LAB_ENTEROCOCCI}

_ID_ILLEGAL = re.compile(r"[^A-Za-z0-9.-]")


def fhir_id(value: str) -> str:
    """Make a FHIR id out of an internal identifier.

    FHIR ids allow only [A-Za-z0-9.-]{1,64}. Zone ids like ZONE_A and observer
    ids carry underscores, so a resource built from one verbatim is rejected on
    write with an error that points at the id rather than at its source.
    """
    return _ID_ILLEGAL.sub("-", value).lower()[:64].strip("-") or "unknown"


def zone_location_id(zone_id: str) -> str:
    """`ZONE_000` -> `zone-000`, `A` -> `zone-a`.

    The prefix keeps zone Locations apart from node Locations in a server that
    holds both; adding it to an id that already says "zone" would publish
    `zone-zone-000`, and a published id is not something to tidy up later.
    """
    slug = fhir_id(zone_id)
    return slug if slug.startswith("zone-") else f"zone-{slug}"


def zone_group_id(zone_id: str) -> str:
    return f"{zone_location_id(zone_id)}-population"


def node_location_id(node_id: str) -> str:
    return f"node-{fhir_id(node_id)}"


def observation_id(event_id) -> str:
    return f"ev-{fhir_id(str(event_id))}"


def episode_resource_id(episode_id: str, version: int) -> str:
    return f"{fhir_id(episode_id)}-v{version}"


# --- Episodes ---------------------------------------------------------------


def episode_to_riskassessment(ep: dict, snapshot: dict, net) -> dict:
    """One version of an exposure episode, as a computable RiskAssessment."""
    state = EpisodeState(ep["state"])
    status = (
        "amended" if ep["version"] > 1 and state in _OPEN_STATES else _STATUS[state]
    )

    predictions, windows = [], []
    for zone_id, zone in (snapshot.get("zone_windows") or {}).items():
        if zone.get("window_lo") is None:
            continue  # the plume never credibly reaches this zone
        predictions.append(
            {
                "outcome": {"text": "Acute gastrointestinal illness"},
                "probabilityDecimal": round(float(zone["p_peak"]), 4),
                "whenPeriod": {
                    "start": _iso(zone["window_lo"]),
                    "end": _iso(ep["clinical_window_end"]),
                },
            }
        )
        windows.append(
            {
                "url": f"{SD}/upstream-exposure-window",
                "extension": [
                    {
                        "url": "zone",
                        "valueReference": {
                            "reference": f"Location/{zone_location_id(zone_id)}"
                        },
                    },
                    {
                        "url": "window",
                        "valuePeriod": {
                            "start": _iso(zone["window_lo"]),
                            "end": _iso(zone["window_hi"]),
                        },
                    },
                    *[
                        {
                            "url": "pathway",
                            "valueCoding": {
                                "system": f"{LOCAL_CS}/exposure-pathway",
                                "code": pathway,
                            },
                        }
                        for pathway in zone.get("pathways") or []
                    ],
                    {"url": "credibleLevel", "valueDecimal": CREDIBLE_LEVEL},
                ],
            }
        )

    ranked = [
        {
            "url": f"{SD}/upstream-source-ranking",
            "extension": [
                {
                    "url": "sourceLocation",
                    "valueReference": {"reference": f"Location/{node_location_id(node)}"},
                },
                {"url": "probability", "valueDecimal": round(float(p), 4)},
                *_source_type_coding(net, node),
            ],
        }
        for node, p in sorted(
            (snapshot.get("source_marginals") or {}).items(), key=lambda kv: -kv[1]
        )[: MAX_RANKED_SOURCES + 1]
        if node != NO_EVENT_KEY
    ][:MAX_RANKED_SOURCES]

    return {
        "resourceType": "RiskAssessment",
        "id": episode_resource_id(ep["episode_id"], ep["version"]),
        "meta": {
            "profile": [f"{SD}/UpstreamExposureEpisode"],
            "tag": [{"system": f"{LOCAL_CS}/episode-state", "code": state.value}],
        },
        "identifier": [{"system": EPISODE_ID_SYSTEM, "value": ep["episode_id"]}],
        "status": status,
        "subject": {"reference": f"Group/{zone_group_id(_primary_zone(snapshot))}"},
        "occurrenceDateTime": _iso(snapshot["ts"]),
        "method": {"text": snapshot["kernel_version"]},
        "basis": [
            {"reference": f"Observation/{e}"} for e in snapshot.get("evidence_ids", [])
        ],
        "prediction": predictions,
        "note": [{"text": f"Fingerprint {snapshot['fingerprint']}. {DISCLAIMER}"}],
        "extension": [
            {"url": f"{SD}/upstream-fingerprint", "valueString": snapshot["fingerprint"]},
            *ranked,
            *windows,
        ],
    }


def _source_type_coding(net, node_id: str) -> list[dict]:
    """The kind of entry point this node is, when the network knows.

    A ranking is never an accusation (GC-12): this says a storm outfall, not who
    operates it.
    """
    try:
        index = net.node_index[node_id]
        source_type = net.entry_source_type[list(net.entry_idx).index(index)]
    except (KeyError, ValueError, AttributeError, IndexError):
        return []
    return [
        {
            "url": "sourceType",
            "valueCoding": {"system": f"{LOCAL_CS}/source-type", "code": str(source_type)},
        }
    ]


def _primary_zone(snapshot: dict) -> str:
    zones = snapshot.get("zone_windows") or {}
    if not zones:
        return "unknown"
    return max(zones.items(), key=lambda kv: kv[1].get("p_peak") or 0.0)[0]


# --- Evidence ---------------------------------------------------------------


def evidence_to_observation(ev, *, retracted: bool) -> dict:
    """One piece of evidence, positive or negative, as it is published."""
    p = ev.payload
    method = p["method"]
    obs = {
        "resourceType": "Observation",
        # FR-10, GC-5: a retraction changes the status. Nothing is deleted.
        #
        # It also changes the profile. The OneAquaHealth indicator observation
        # pattern-fixes Observation.status to #final, so a withdrawn reading
        # cannot conform to it -- and should not: it is no longer an indicator,
        # it is the record of one being withdrawn.
        "id": observation_id(ev.event_id),
        "meta": {
            "profile": [
                f"{SD}/UpstreamRetractedObservation"
                if retracted
                else f"{SD}/UpstreamEvidenceObservation"
            ]
        },
        "status": "entered-in-error" if retracted else "final",
        "category": [{"coding": [{"system": OBS_CATEGORY_CS, "code": _category(method)}]}],
        "code": {"coding": [{"system": OAH_CS, "code": _indicator_code(p)}]},
        "subject": {"reference": f"Location/{node_location_id(p['node_id'])}"},
        "effectiveDateTime": _iso(ev.event_time),  # GC-4 event time
        "issued": _iso(ev.recorded_at),  # GC-4 record time
        "method": {
            "coding": [{"system": f"{LOCAL_CS}/observation-method", "code": method}]
        },
        # GC-7: an observer is a programme, a laboratory or a device, never a
        # patient. The identifier is pseudonymous and is published as a display
        # so that no reference to a person resource is ever created.
        "performer": [{"display": p["observer_id"]}],
    }

    if p["result"] == "quantitative":
        obs["valueQuantity"] = {
            "value": p["value"],
            "unit": p["unit"],
            "system": UCUM,  # GC-13
            "code": p["unit"],
        }
    elif p["result"] == "negative":
        # A check that happened and found nothing is evidence, not a missing
        # value. dataAbsentReason would say the opposite.
        obs["valueCodeableConcept"] = {
            "coding": [{"system": SNOMED, "code": "260385009", "display": "Negative"}]
        }
        obs["interpretation"] = [
            {"coding": [{"system": INTERPRETATION_CS, "code": "NEG", "display": "Negative"}]}
        ]
    else:
        obs["valueCodeableConcept"] = {
            "coding": [{"system": SNOMED, "code": "260373001", "display": "Detected"}]
        }
        obs["interpretation"] = [
            {"coding": [{"system": INTERPRETATION_CS, "code": "POS", "display": "Positive"}]}
        ]

    extensions = []
    if p.get("ai_assisted"):
        # GC-8: the model proposed, the citizen confirmed, and the published
        # record says which model and that the confirmation happened.
        extensions.append(
            {
                "url": f"{SD}/upstream-ai-assisted",
                "extension": [
                    {"url": "modelId", "valueString": p.get("ai_model", "claude-opus-5")},
                    {
                        "url": "confirmedByObserver",
                        "valueBoolean": bool(p.get("confirmed_by_observer")),
                    },
                ],
            }
        )
    if p.get("observer_reliability") is not None:
        extensions.append(
            {
                "url": f"{SD}/upstream-observer-reliability",
                "valueDecimal": float(p["observer_reliability"]),
            }
        )
    if extensions:
        obs["extension"] = extensions
    return obs


def _indicator_code(payload: dict) -> str:
    codes = payload.get("oah_codes") or []
    if codes:
        return codes[0]
    return INDICATOR_FOR_METHOD.get(payload["method"], "foam")


def _category(method: str) -> str:
    if method in _LAB_METHODS:
        return "laboratory"
    return "survey"


# --- Zones ------------------------------------------------------------------


def zone_to_location(
    net, zone_id: str, *, boundary: dict | None = None, name: str | None = None
) -> dict:
    """An exposure zone as a Location.

    The compiled network artefact keeps one anchor node per zone, not the zone
    polygon -- that lives in PostGIS. So the boundary is passed in by whoever
    has already read it; the mapper does no I/O.
    """
    loc = {
        "resourceType": "Location",
        "id": zone_location_id(zone_id),
        "meta": {"profile": [f"{SD}/UpstreamExposureZone"]},
        "identifier": [{"system": ZONE_ID_SYSTEM, "value": zone_id}],
        "status": "active",
        "name": name or f"Exposure zone {zone_id}",
        "mode": "instance",
        "type": [
            {"coding": [{"system": LOCATION_PHYSICAL_TYPE_CS, "code": "area", "display": "Area"}]}
        ],
    }
    position = _zone_position(net, zone_id)
    if position:
        loc["position"] = position
    if boundary is not None:
        loc["extension"] = [
            {
                "url": BOUNDARY_EXT,
                "valueAttachment": {
                    "contentType": "application/geo+json",
                    "title": f"Exposure zone {zone_id} boundary",
                    "data": base64.b64encode(
                        json.dumps(boundary, separators=(",", ":")).encode()
                    ).decode(),
                },
            }
        ]
    return loc


def zone_to_group(net, zone_id: str, *, name: str | None = None) -> dict:
    """The population of a zone: a definition of who is affected, not a roster.

    GC-7. The OneAquaHealth parent forbids members, and Upstream has none to
    publish -- the population figure is an upper bound from the census grid.
    """
    group = {
        "resourceType": "Group",
        "id": zone_group_id(zone_id),
        "meta": {"profile": [f"{SD}/UpstreamZonePopulation"]},
        "type": "person",
        "actual": False,
        "name": name or f"Population of exposure zone {zone_id}",
        "characteristic": [
            {
                "code": {
                    "coding": [
                        {
                            "system": f"{LOCAL_CS}/cohort-characteristic",
                            "code": "zone-presence",
                            "display": "Present in an exposure zone",
                        }
                    ]
                },
                "valueReference": {"reference": f"Location/{zone_location_id(zone_id)}"},
                "exclude": False,
            }
        ],
    }
    population = _zone_population(net, zone_id)
    if population is not None:
        group["quantity"] = population
    return group


def _zone_index(net, zone_id: str) -> int | None:
    try:
        return list(net.zone_ids).index(zone_id)
    except (ValueError, AttributeError):
        return None


def _zone_position(net, zone_id: str) -> dict | None:
    index = _zone_index(net, zone_id)
    if index is None:
        return None
    try:
        lon, lat = net.lonlat[int(net.zone_node_idx[index])]
    except (IndexError, AttributeError, TypeError):
        return None
    return {"longitude": float(lon), "latitude": float(lat)}


def _zone_population(net, zone_id: str) -> int | None:
    index = _zone_index(net, zone_id)
    if index is None:
        return None
    try:
        return int(net.zone_population[index])
    except (IndexError, AttributeError, TypeError):
        return None


# --- Provenance -------------------------------------------------------------


def provenance_for(
    ra_ref: str,
    ra_version: str,
    snapshot: dict,
    evidence_refs: list[str],
    agents: list[dict],
) -> dict:
    """How one version of a published episode came to exist (FR-27, GC-6).

    The target is a *versioned* reference: provenance that pointed at the
    episode in general would claim to describe every later version too.
    """
    return {
        "resourceType": "Provenance",
        "meta": {"profile": [f"{SD}/UpstreamEpisodeProvenance"]},
        "target": [{"reference": f"{ra_ref}/_history/{ra_version}"}],
        "recorded": _iso(dt.datetime.now(dt.UTC)),
        "occurredDateTime": _iso(snapshot["ts"]) if snapshot.get("ts") else None,
        "agent": [
            {
                "type": {"coding": [{"system": PARTICIPANT_TYPE_CS, "code": "assembler"}]},
                "who": {"display": snapshot["kernel_version"]},
            },
            *agents,
        ],
        "entity": [
            {"role": "source", "what": {"reference": ref}} for ref in evidence_refs
        ],
    }


# --- Time -------------------------------------------------------------------


def _iso(value) -> str:
    """Epoch seconds or a datetime, as a FHIR instant.

    PULSE hands out epoch floats and the database hands out datetimes, and both
    reach this module.
    """
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return dt.datetime.fromtimestamp(float(value), dt.UTC).isoformat()
