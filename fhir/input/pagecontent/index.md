# Upstream — Exposure Episodes for One Health

Upstream turns citizen, sensor and laboratory observations of a river catchment
into probabilistic **exposure episodes**, and publishes each episode as FHIR so
that a clinician sees environmental context alongside a patient.

Every profile in this guide derives from the
[OneAquaHealth IG](http://hl7.eu/fhir/ig/oah). Upstream contributes instruments
and a lifecycle, not a parallel model of a river.

## What is published

| Artefact | What it carries |
|---|---|
| `UpstreamExposureEpisode` | One version of one episode: its state, the evidence behind it, a per-zone exposure window, ranked candidate entry points, and the fingerprint that lets it be recomputed bit for bit. |
| `UpstreamEvidenceObservation` | One observation, positive or negative, with both the time it happened and the time the system learned it. |
| `UpstreamExposureZone` | A stretch of catchment a plume is predicted to reach. |
| `UpstreamZonePopulation` | The people in that zone, described and never enumerated. |
| `UpstreamEpisodeProvenance` | Which evidence and which software produced one exact version. |
| `UpstreamSyndromicCount` | An aggregate count for an area and a day. Small counts are suppressed before the resource exists. |

## What is never published

No patient-level data crosses this boundary, in either direction. An episode is
about a place and the people who may have been in it. Nothing here is an
advisory, nothing names a polluter, and every health-facing output says the same
thing: **environmental context, not a diagnosis.**

## Retraction

Nothing is deleted. A retracted observation becomes `entered-in-error` and stays
in the record, because an episode that was computed from it has to remain
explicable afterwards.
