# Track 7 alignment: Digital Health Standards

**Upstream creates the object that environmental monitoring and health systems have
never shared: an Exposure Episode.** It is a time-bounded, evidence-backed hypothesis
about one contamination event, published as FHIR R4 resources derived from the
OneAquaHealth Implementation Guide (`hl7.eu.fhir.oah`), not a parallel model.

## The track, and the answer

| Track 7 | Official text | How Upstream answers it |
|---|---|---|
| Challenge | Enable interoperability across systems | The Exposure Episode is the shared object between the OAH Environmental Surveillance System and clinical and public-health systems |
| Problem | Fragmented data and lack of standards | Citizen reports, sensors, rainfall, lab results and clinical counts become one evidence model, published as FHIR resources that extend the OAH IG |
| Build | FHIR models, AI agents, integration frameworks | FHIR profiles in FSH, a validating HAPI FHIR server, a CDS Hooks service, topic-based Subscriptions, Provenance and AuditEvent, and a bounded AI normaliser |

## The evidence, claim by claim

| Claim | Where it is | How it is checked |
|---|---|---|
| **Zero HL7 validator errors against the OAH IG** (GC-3) | [`fhir/scripts/validate.sh`](../fhir/scripts/validate.sh) runs the official HL7 validator on every generated resource and example | The `fhir` job in [CI](../.github/workflows/ci.yml) fails the build on any error, and uploads `validation-report.json` on every run |
| **Profiles derive from the OAH IG** (GC-2) | [`fhir/input/fsh/`](../fhir/input/fsh/): exposure zone ← OAH `Location`; zone population ← OAH `Group`; evidence ← OAH indicator `Observation` | [`sushi-config.yaml`](../fhir/sushi-config.yaml) depends on `hl7.eu.fhir.oah` |
| **The episode is a `RiskAssessment`** carrying its source ranking, per-zone 80% exposure windows and a reproducibility fingerprint | [`profiles-risk.fsh`](../fhir/input/fsh/profiles-risk.fsh) | [Example lifecycle](../fhir/input/fsh/examples/lifecycle.fsh): versions v1 → v3 of one episode |
| **Negative evidence is a finding, not missing data** | "I checked and it looks normal" is an `Observation` with a result | `test_the_negative_observation_records_a_finding_not_absent_data` |
| **Retractions are `entered-in-error`, never deletes** (GC-5) | [`profiles-observation.fsh`](../fhir/input/fsh/profiles-observation.fsh) `UpstreamRetractedObservation` | `test_retracted_evidence_is_published_as_entered_in_error_not_deleted` |
| **Provenance on every episode version and every AI-assisted observation** (FR-27) | [`profiles-provenance.fsh`](../fhir/input/fsh/profiles-provenance.fsh) records the kernel version, parameters, network and the evidence used; the `UpstreamAiAssisted` extension marks model-proposed fields | `test_provenance_records_the_kernel_and_the_evidence` |
| **Publishing validates on write** | [`upstream_api/fhir/publisher.py`](../services/core-api/upstream_api/fhir/publisher.py) calls `$validate` on HAPI before it writes | `test_an_invalid_resource_is_never_written` |
| **CDS Hooks** (FR-28): a card only when the patient's area, the timing and the syndrome all match | [`upstream_api/fhir/cds_hooks.py`](../services/core-api/upstream_api/fhir/cds_hooks.py): `patient-view` and `encounter-start`; discovery at `GET /cds-services` | Card rule and p95 < 500 ms (GC-9) in `test_cds_hooks.py` |
| **Every CDS card is audited** (FR-30) | [`upstream_api/fhir/audit.py`](../services/core-api/upstream_api/fhir/audit.py) writes an `AuditEvent` per card | Example `upstream-audit-cds-card` |
| **Topic-based Subscriptions** (FR-29) | [`subscriptiontopic.fsh`](../fhir/input/fsh/subscriptiontopic.fsh), on the R4 subscriptions backport; subscribers hear when an episode changes state | Example subscription validates with zero errors |
| **Aggregate health data only, as `MeasureReport`** (FR-32) | [`profiles-measure.fsh`](../fhir/input/fsh/profiles-measure.fsh): a summary about a `Group`, never a patient; counts below five cannot be stored | The clinical boundary tests run from the clinical service's own credential |
| **Only a test result crosses back** (FR-34) | The clinical service sends area, syndrome, method, p-value, effect size and number of days; the Core API refuses anything else | `extra="forbid"` models in [`api/clinical.py`](../services/core-api/upstream_api/api/clinical.py) |
| **A bounded AI normaliser** (GC-8, GC-16) | [`ingest/normaliser.py`](../services/core-api/upstream_api/ingest/normaliser.py): the model proposes fields to a fixed schema; the citizen confirms each one (`/ingest/report/propose` → `/ingest/report/confirm`) | The evidence schema refuses AI-assisted evidence that the observer has not confirmed |

## Honest notes for a standards reviewer

- **`hl7.eu.fhir.oah` has no published release.** It is not on packages.fhir.org and
  its repository has no tag. It is built from its public FSH source and vendored
  (`fhir/vendor/hl7.eu.fhir.oah.tgz`, `0.1.0-ci-build`). When OAH publishes a release,
  only the dependency version changes.
- **Topic-based Subscriptions in R4** use the subscriptions backport. R4 has no
  `SubscriptionTopic` resource, so the topic is a canonical URL pinned by a
  `Subscription` profile, as the backport specifies.
- **SNOMED CT** is not used: no affiliate licence is assumed. Syndromes, exposure
  pathways, episode states and observation methods are local code systems
  ([`codesystems.fsh`](../fhir/input/fsh/codesystems.fsh)), with LOINC and UCUM where
  they apply (GC-13).
- **Deferred** (PRD §17):
  - missions as FHIR `Task` (FR-31);
  - the SMART on FHIR app (FR-40): the CDS card's link is informational.

- **The data is simulated** on a real network (the drains, not the incidents); see
  [ASSUMPTIONS.md](ASSUMPTIONS.md).
