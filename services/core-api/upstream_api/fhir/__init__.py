"""The FHIR view of Upstream (PRD 13, GC-2, GC-3).

FHIR is a published *view*. Nothing in this package reads back into the engine:
HAPI can be dropped and rebuilt from the event log at any time, and no decision
anywhere in Upstream depends on a resource having been written.
"""
