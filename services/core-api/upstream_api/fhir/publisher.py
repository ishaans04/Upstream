"""Publish an episode and everything it rests on to HAPI (FR-25, FR-26, FR-27).

Publishing is a *projection*. It reads the event log and the snapshot table,
writes resources, and appends one FhirPublished event so the publication itself
is on the record. Nothing downstream of here feeds back into the engine: if HAPI
is empty, Upstream still works, and republishing is always safe.
"""

from __future__ import annotations

import datetime as dt
import json
import logging

from upstream_kernel.worker import HORIZON_HOURS
from upstream_shared.events import EventEnvelope, EventType

from ..config import settings
from ..db import pool
from ..eventlog import store
from ..network import get_network
from .client import FhirClient
from .mapper import (
    LOCATION_PHYSICAL_TYPE_CS,
    NODE_ID_SYSTEM,
    PARTICIPANT_TYPE_CS,
    episode_to_riskassessment,
    evidence_to_observation,
    node_location_id,
    provenance_for,
    zone_to_group,
    zone_to_location,
)

log = logging.getLogger(__name__)


def publish_episode(episode_id: str) -> dict:
    """Write one episode, its evidence, its zones and its provenance.

    Returns the RiskAssessment's id and version.
    """
    episode = _episode(episode_id)
    snapshot = _latest_snapshot(episode_id, stream=episode["stream"])
    if snapshot is None:
        raise LookupError(f"{episode_id} has no posterior snapshot to publish")

    net = get_network()
    client = FhirClient()

    evidence = _evidence_for(episode, snapshot)

    # Places first, and not only for tidiness. HAPI rejects a reference to a
    # resource it does not hold (HAPI-1094) rather than creating a placeholder,
    # so an Observation written before the Location it is about is refused
    # outright -- and every node an Observation or a source ranking points at
    # must exist anyway, or the published episode has dangling references the
    # moment a reader follows one.
    for node_id in _referenced_nodes(evidence, snapshot):
        client.put(_node_location(net, node_id))

    zone_geometry = _zone_geometry()
    for zone_id in snapshot.get("zone_windows") or {}:
        geometry = zone_geometry.get(zone_id, {})
        client.put(
            zone_to_location(
                net, zone_id, boundary=geometry.get("boundary"), name=geometry.get("name")
            )
        )
        client.put(zone_to_group(net, zone_id, name=geometry.get("population_name")))

    # Everything is published, including what was withdrawn; only what the
    # kernel actually used goes in the basis. The posterior was computed with
    # retracted evidence excluded, so listing it as the basis would claim the
    # episode rests on something it does not (GC-6) -- while dropping it from
    # the server altogether would break the references in every earlier version
    # of the episode (GC-5).
    observation_refs = []
    retracted_refs = []
    for event, retracted in evidence:
        written = client.put_unchanged_once(
            evidence_to_observation(event, retracted=retracted),
            compare=("status", "meta"),
        )
        (retracted_refs if retracted else observation_refs).append(
            f"Observation/{written['id']}"
        )

    snapshot = snapshot | {
        "evidence_ids": [ref.split("/", 1)[1] for ref in observation_refs]
    }
    written = client.put(episode_to_riskassessment(episode, snapshot, net))
    client.post(
        provenance_for(
            f"RiskAssessment/{written['id']}",
            written["version"],
            snapshot,
            observation_refs,
            agents=_human_agents(evidence),
        )
    )

    _record_publication(
        episode, written, len(observation_refs), len(retracted_refs)
    )
    return written


def publish_episode_quietly(episode_id: str) -> dict | None:
    """Publish, but never let a publishing failure take down a state change.

    FHIR is a view. An episode that moved from PROBABLE to CONFIRMED has moved
    whether or not HAPI was reachable, and losing the transition because a
    projection failed would be the worse outcome by far. The failure is logged
    and the next transition republishes from scratch.
    """
    try:
        return publish_episode(episode_id)
    except Exception:
        log.exception("publishing %s to FHIR failed; the episode is unaffected", episode_id)
        return None


# --- Reads ------------------------------------------------------------------

_EPISODE_COLS = (
    "episode_id",
    "catchment_id",
    "stream",
    "state",
    "opened_at",
    "state_changed_at",
    "clinical_window_end",
    "latest_fingerprint",
    "version",
    "summary",
)


def _episode(episode_id: str) -> dict:
    with pool.connection() as c, c.cursor() as cur:
        cur.execute(
            f"SELECT {','.join(_EPISODE_COLS)} FROM episodes WHERE episode_id=%s",
            (episode_id,),
        )
        row = cur.fetchone()
    if row is None:
        raise KeyError(f"no such episode: {episode_id}")
    return dict(zip(_EPISODE_COLS, row, strict=True))


_SNAPSHOT_COLS = (
    "ts",
    "fingerprint",
    "as_of_seq",
    "network_version",
    "kernel_version",
    "params_version",
    "p_event",
    "source_marginals",
    "zone_windows",
)


def _latest_snapshot(episode_id: str, *, stream: str) -> dict | None:
    with pool.connection() as c, c.cursor() as cur:
        cur.execute(
            f"SELECT {','.join(_SNAPSHOT_COLS)} FROM posterior_snapshots "
            "WHERE episode_id=%s AND catchment_id=%s AND stream=%s "
            "ORDER BY ts DESC LIMIT 1",
            (episode_id, settings.catchment_id, stream),
        )
        row = cur.fetchone()
    return dict(zip(_SNAPSHOT_COLS, row, strict=True)) if row else None


def _evidence_for(episode: dict, snapshot: dict) -> list[tuple[object, bool]]:
    """Exactly the evidence this snapshot was computed from, retracted included.

    The window is the kernel's own: HORIZON_HOURS back from the moment the
    snapshot was computed, cut at the snapshot's `as_of_seq`. Both halves
    matter. The posterior is computed over the whole catchment for that horizon,
    not over one episode's evidence, so anything narrower would publish a basis
    the episode does not actually rest on; and `as_of_seq` is the same prefix of
    the log the kernel read, so a later event changes nothing until a later
    snapshot exists to publish (GC-6).

    GC-5: a retraction is published as `entered-in-error`, not as an absence.
    An episode computed before the retraction has to stay explicable afterwards,
    and that is only possible if the observation is still there to read.
    """
    events = store.read_as_of(
        catchment_id=episode["catchment_id"],
        stream=episode["stream"],
        as_of_seq=snapshot["as_of_seq"],
        since=snapshot["ts"] - dt.timedelta(hours=HORIZON_HOURS),
    )
    retracted = {
        str(e.payload["retracts_event_id"])
        for e in events
        if e.event_type == EventType.EVIDENCE_RETRACTED
    }
    return [
        (e, str(e.event_id) in retracted)
        for e in events
        if e.event_type == EventType.EVIDENCE_RECORDED
    ]




def _referenced_nodes(evidence, snapshot: dict) -> list[str]:
    nodes = {e.payload["node_id"] for e, _ in evidence}
    nodes |= {
        node
        for node in (snapshot.get("source_marginals") or {})
        if not node.startswith("__")
    }
    return sorted(nodes)


def _node_location(net, node_id: str) -> dict:
    """A network node as a plain OneAquaHealth Location.

    Not an UpstreamExposureZone: an outfall or a junction is a point on the
    network, not a stretch of river people are exposed in, and profiling it as
    a zone would claim a population that does not exist.
    """
    location = {
        "resourceType": "Location",
        "id": node_location_id(node_id),
        "meta": {
            "profile": ["http://hl7.eu/fhir/ig/oah/StructureDefinition/location-oah"]
        },
        "identifier": [{"system": NODE_ID_SYSTEM, "value": node_id}],
        "status": "active",
        "name": node_id,
        "mode": "instance",
        "type": [
            {
                "coding": [
                    {"system": LOCATION_PHYSICAL_TYPE_CS, "code": "si", "display": "Site"}
                ]
            }
        ],
    }
    index = net.node_index.get(node_id)
    if index is not None:
        lon, lat = net.lonlat[int(index)]
        location["position"] = {"longitude": float(lon), "latitude": float(lat)}
    return location


def _zone_geometry() -> dict[str, dict]:
    """Zone polygons and names out of PostGIS.

    The compiled artefact keeps one anchor node per zone; the polygon the map
    and the published Location need is in `receptor_zones`.
    """
    with pool.connection() as c, c.cursor() as cur:
        cur.execute(
            "SELECT zone_id, name, ST_AsGeoJSON(geom) FROM receptor_zones "
            "WHERE network_version=(SELECT network_version FROM receptor_zones "
            "ORDER BY network_version DESC LIMIT 1)"
        )
        rows = cur.fetchall()

    out = {}
    for zone_id, name, geojson in rows:
        out[zone_id] = {
            "name": name or f"Exposure zone {zone_id}",
            "population_name": f"Population of {name or zone_id}",
            "boundary": json.loads(geojson) if geojson else None,
        }
    return out


def _human_agents(evidence) -> list[dict]:
    """The people whose confirmations the evidence rests on.

    Pseudonymous observer ids only. A `display` never becomes a reference to a
    person resource, because there is no person resource to point at (GC-7).
    """
    seen, agents = set(), []
    for event, _ in evidence:
        observer = event.payload.get("observer_id")
        if not observer or observer in seen:
            continue
        seen.add(observer)
        agents.append(
            {
                "type": {"coding": [{"system": PARTICIPANT_TYPE_CS, "code": "author"}]},
                "who": {"display": observer},
            }
        )
    return agents


def _record_publication(
    episode: dict, written: dict, observation_count: int, retracted_count: int
) -> None:
    with pool.connection() as c, c.cursor() as cur:
        cur.execute(
            "UPDATE episodes SET fhir_risk_assessment_id=%s WHERE episode_id=%s",
            (written["id"], episode["episode_id"]),
        )
    store.append(
        EventEnvelope(
            stream=episode["stream"],
            catchment_id=settings.catchment_id,
            event_type=EventType.FHIR_PUBLISHED,
            event_time=dt.datetime.now(dt.UTC),
            payload={
                "episode_id": episode["episode_id"],
                "risk_assessment_id": written["id"],
                "fhir_version_id": written["version"],
                "observation_count": observation_count,
                "retracted_observation_count": retracted_count,
            },
        )
    )
