"""Published identifiers, derived from internal ones in exactly one place.

A zone's population Group id is also the area code the health zone files counts
under (GC-7). The FHIR mapper, the clinical feed and the simulator all need the
same answer, and a second copy of the rule would drift the first time either
was edited -- after which counts would be filed under an area no episode names.
"""
import re

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
    """The zone's population Group -- and the health zone's area code for it."""
    return f"{zone_location_id(zone_id)}-population"


def node_location_id(node_id: str) -> str:
    return f"node-{fhir_id(node_id)}"
