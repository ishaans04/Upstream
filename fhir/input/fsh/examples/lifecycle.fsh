// fhir/input/fsh/examples/lifecycle.fsh
//
// One episode, end to end, as the validator sees it: the places, the
// population, three pieces of evidence (a positive citizen report, an explicit
// negative, and a laboratory result that arrived after the fact), two versions
// of the published episode, its provenance, the audit record of a CDS card,
// and the aggregate syndromic count that crossed the health boundary.
//
// Every identifier here is synthetic. The catchment is coimbra-ribeira and its
// outfalls are synthetic by construction (PRD R2).

Instance: upstream-programme
InstanceOf: Organization
Usage: #example
Title: "Upstream catchment programme"
Description: "The programme that operates the sensors and receives citizen reports."
* name = "Upstream - Ribeira de Coselhas catchment programme"
* active = true

Instance: upstream-lab-coimbra
InstanceOf: Organization
Usage: #example
Title: "Municipal water laboratory"
Description: "The laboratory that returned the E. coli count."
* name = "Coimbra municipal water laboratory"
* active = true

Instance: upstream-outfall-O14
InstanceOf: UpstreamExposureZone
Usage: #example
Title: "Outfall O14"
Description: "A synthetic storm outfall on the Ribeira de Coselhas (PRD R2)."
* identifier.system = "https://upstream-onehealth.example/network/node"
* identifier.value = "O14"
* name = "Outfall O14"
* mode = #instance
* status = #active
* type = $location-physical-type#si "Site"
* position.longitude = -8.4265
* position.latitude = 40.2215

Instance: upstream-junction-J9
InstanceOf: UpstreamExposureZone
Usage: #example
Title: "Junction J9"
Description: "The confluence immediately downstream of outfall O14."
* identifier.system = "https://upstream-onehealth.example/network/node"
* identifier.value = "J9"
* name = "Junction J9"
* mode = #instance
* status = #active
* type = $location-physical-type#si "Site"
* position.longitude = -8.4241
* position.latitude = 40.2198

Instance: upstream-zone-A
InstanceOf: UpstreamExposureZone
Usage: #example
Title: "Exposure zone A"
Description: "The reach between junction J9 and the municipal park footbridge."
* identifier.system = "https://upstream-onehealth.example/zone"
* identifier.value = "ZONE_A"
* name = "Exposure zone A - Coselhas park reach"
* description = "Ribeira de Coselhas between junction J9 and the park footbridge."
* mode = #instance
* status = #active
* type = $location-physical-type#area "Area"
* position.longitude = -8.4216
* position.latitude = 40.2173
* extension[boundary].valueAttachment.contentType = #application/geo+json
* extension[boundary].valueAttachment.title = "Exposure zone A boundary"

Instance: upstream-zone-A-population
InstanceOf: UpstreamZonePopulation
Usage: #example
Title: "Population of exposure zone A"
Description: "Everyone present in exposure zone A during the episode window. Descriptive
only: the group is never enumerated (GC-7)."
* type = #person
* actual = false
* name = "Population of exposure zone A"
* characteristic[0].code = $upstream-cohort-characteristic#zone-presence "Present in an exposure zone"
* characteristic[0].valueReference = Reference(upstream-zone-A)
* characteristic[0].exclude = false

// --- Evidence --------------------------------------------------------------

Instance: upstream-evidence-foam
InstanceOf: UpstreamEvidenceObservation
Usage: #example
Title: "Citizen report of foam and smell at zone A"
Description: "A positive citizen observation, proposed by the normaliser and confirmed
field by field by the citizen before it was accepted (GC-8)."
* status = #final
* category = $obs-category#survey "Survey"
* code = $oah-temporary#foam "Foam/colour/smell"
* subject = Reference(upstream-zone-A)
* effectiveDateTime = "2026-09-20T07:42:00+01:00"
* issued = "2026-09-20T07:44:31+01:00"
* method = $observation-method#citizen_visual_olfactory "Citizen visual and olfactory check"
* performer = Reference(upstream-programme)
* valueCodeableConcept = $sct#260373001 "Detected"
* extension[aiAssisted].extension[modelId].valueString = "claude-opus-5"
* extension[aiAssisted].extension[confirmedByObserver].valueBoolean = true
* extension[observerReliability].valueDecimal = 0.72

Instance: upstream-evidence-normal
InstanceOf: UpstreamEvidenceObservation
Usage: #example
Title: "Citizen check upstream of the outfall found nothing"
Description: "An explicit negative. The check happened and the finding was negative; that
is evidence, and the kernel weighs it exactly as it weighs a positive."
* status = #final
* category = $obs-category#survey "Survey"
* code = $oah-temporary#foam "Foam/colour/smell"
* subject = Reference(upstream-outfall-O14)
* effectiveDateTime = "2026-09-20T07:55:00+01:00"
* issued = "2026-09-20T07:56:02+01:00"
* method = $observation-method#citizen_visual_olfactory "Citizen visual and olfactory check"
* performer = Reference(upstream-programme)
* valueCodeableConcept = $sct#260385009 "Negative"
* extension[observerReliability].valueDecimal = 0.72

Instance: upstream-evidence-lab-ecoli
InstanceOf: UpstreamEvidenceObservation
Usage: #example
Title: "Laboratory E. coli count, reported two days later"
Description: "The sample was taken during the episode and the result arrived after it. The
event time and the record time differ by two days, which is why both are mandatory (GC-4)."
* status = #final
* category = $obs-category#laboratory "Laboratory"
* code = $oah-temporary#coliforms "Coliforms"
* subject = Reference(upstream-zone-A)
* effectiveDateTime = "2026-09-20T09:10:00+01:00"
* issued = "2026-09-22T14:05:00+01:00"
* method = $observation-method#lab_ecoli "Laboratory E. coli count"
* performer = Reference(upstream-lab-coimbra)
* valueQuantity.value = 1840
* valueQuantity.unit = "colony forming units per 100 millilitre"
* valueQuantity.system = "http://unitsofmeasure.org"
* valueQuantity.code = #"{CFU}/(100.mL)"

// --- The episode -----------------------------------------------------------

Instance: upstream-episode-2841-v1
InstanceOf: UpstreamExposureEpisode
Usage: #example
Title: "Exposure episode EE-2841, first version (SUSPECTED)"
Description: "The episode as it stood on the first citizen report alone."
* meta.tag = $episode-state#SUSPECTED "Suspected"
* identifier.system = "https://upstream-onehealth.example/episode"
* identifier.value = "EE-2841"
* status = #preliminary
* subject = Reference(upstream-zone-A-population)
* occurrenceDateTime = "2026-09-20T07:45:10+01:00"
* method.text = "upstream-kernel 0.1.0 / network 132f62627eef3d97 / params 668570ce0643d642"
* basis = Reference(upstream-evidence-foam)
* prediction.outcome.text = "Contact with water contaminated by a sewage-derived source"
* prediction.probabilityDecimal = 0.41
* prediction.whenPeriod.start = "2026-09-20T07:20:00+01:00"
* prediction.whenPeriod.end = "2026-09-20T13:20:00+01:00"
* note.text = "Environmental context, not a diagnosis. This is a probabilistic hypothesis about a place, computed from environmental observations. It is not an advisory and it names no polluter."
* extension[fingerprint].valueString = "8f14e45fceea167a5a36dedd4bea2543a14b6f2c3bb7ddc8b1a1d5ea1d6e0b91"

Instance: upstream-episode-2841-v3
InstanceOf: UpstreamExposureEpisode
Usage: #example
Title: "Exposure episode EE-2841, third version (PROBABLE)"
Description: "The same episode after the explicit negative upstream and the laboratory
result. The negative moved probability mass onto the outfall between the two points."
* meta.tag = $episode-state#PROBABLE "Probable"
* meta.versionId = "3"
* identifier.system = "https://upstream-onehealth.example/episode"
* identifier.value = "EE-2841"
* status = #amended
* subject = Reference(upstream-zone-A-population)
* occurrenceDateTime = "2026-09-22T14:06:02+01:00"
* method.text = "upstream-kernel 0.1.0 / network 132f62627eef3d97 / params 668570ce0643d642"
* basis[0] = Reference(upstream-evidence-foam)
* basis[1] = Reference(upstream-evidence-normal)
* basis[2] = Reference(upstream-evidence-lab-ecoli)
* prediction.outcome.text = "Contact with water contaminated by a sewage-derived source"
* prediction.probabilityDecimal = 0.78
* prediction.whenPeriod.start = "2026-09-20T07:20:00+01:00"
* prediction.whenPeriod.end = "2026-09-20T13:20:00+01:00"
* note.text = "Environmental context, not a diagnosis. This is a probabilistic hypothesis about a place, computed from environmental observations. It is not an advisory and it names no polluter."
* extension[fingerprint].valueString = "c7b4dd6e5c9a1f0b2e8d3a7c4f19b5e0d2a6c8f3b1e7d9a4c0f6b2e8d4a1c7f3"
* extension[sourceRanking][0].extension[sourceLocation].valueReference = Reference(upstream-outfall-O14)
* extension[sourceRanking][0].extension[probability].valueDecimal = 0.63
* extension[sourceRanking][0].extension[sourceType].valueCoding = $source-type#storm_outfall "Storm water outfall"
* extension[sourceRanking][1].extension[sourceLocation].valueReference = Reference(upstream-junction-J9)
* extension[sourceRanking][1].extension[probability].valueDecimal = 0.15
* extension[sourceRanking][1].extension[sourceType].valueCoding = $source-type#unknown "Unknown entry point"
* extension[exposureWindow][0].extension[zone].valueReference = Reference(upstream-zone-A)
* extension[exposureWindow][0].extension[window].valuePeriod.start = "2026-09-20T07:20:00+01:00"
* extension[exposureWindow][0].extension[window].valuePeriod.end = "2026-09-20T13:20:00+01:00"
* extension[exposureWindow][0].extension[pathway][0].valueCoding = $exposure-pathway#recreation "Recreation"
* extension[exposureWindow][0].extension[pathway][1].valueCoding = $exposure-pathway#animal_contact "Animal contact"
* extension[exposureWindow][0].extension[credibleLevel].valueDecimal = 0.80

Instance: upstream-episode-2841-v3-provenance
InstanceOf: UpstreamEpisodeProvenance
Usage: #example
Title: "How version 3 of EE-2841 was produced"
Description: "The kernel assembled this version from three observations. No officer had
signed anything at this point, so there is no signature (FR-21)."
* target = Reference(upstream-episode-2841-v3)
* recorded = "2026-09-22T14:06:02+01:00"
* occurredDateTime = "2026-09-22T14:06:02+01:00"
* agent[0].type = $provenance-participant-type#assembler "Assembler"
* agent[0].who.display = "upstream-kernel 0.1.0"
* agent[1].type = $provenance-participant-type#author "Author"
* agent[1].who = Reference(upstream-programme)
* entity[0].role = #source
* entity[0].what = Reference(upstream-evidence-foam)
* entity[1].role = #source
* entity[1].what = Reference(upstream-evidence-normal)
* entity[2].role = #source
* entity[2].what = Reference(upstream-evidence-lab-ecoli)

// --- The health-facing side ------------------------------------------------

Instance: upstream-audit-cds-card
InstanceOf: AuditEvent
Usage: #example
Title: "A CDS Hooks card was returned to a clinician"
Description: "FR-30: every card and every external read is audited. The audit records that
a card was shown, not who the patient was."
* type = $audit-event-type#rest "RESTful Operation"
* subtype = http://hl7.org/fhir/restful-interaction#read "read"
* action = #R
* recorded = "2026-09-22T16:30:11+01:00"
* outcome = #0
* agent.type.text = "CDS Hooks client"
* agent.who.display = "Coimbra primary care EHR"
* agent.requestor = true
* source.observer.display = "upstream-onehealth cds-hooks service"
* entity.what = Reference(upstream-episode-2841-v3)
* entity.detail.type = "card-summary"
* entity.detail.valueString = "Environmental context, not a diagnosis."

Instance: upstream-syndromic-measure
InstanceOf: Measure
Usage: #definition
Title: "Daily count of gastrointestinal presentations by area"
Description: "The aggregate the clinical statistics service publishes. Defined here so the
MeasureReport has something to point at; the counts themselves never carry a patient."
* url = "https://upstream-onehealth.example/Measure/gi-presentations-by-area-day"
* version = "0.1.0"
* name = "UpstreamGiPresentationsByAreaDay"
* title = "Daily count of gastrointestinal presentations by area"
* status = #active
* experimental = false
* publisher = "Upstream (IEEE OneAquaHealth Hackathon 2026)"
* description = "Number of primary care presentations matching the gastrointestinal syndrome definition, by area and day."
* scoring = $measure-scoring#continuous-variable "Continuous Variable"

Instance: upstream-syndromic-zoneA-2026-09-22
InstanceOf: UpstreamSyndromicCount
Usage: #example
Title: "Gastrointestinal presentations in zone A, 22 September 2026"
Description: "An aggregate count. Counts below the suppression threshold are never
published at all; this one is above it (GC-7)."
* status = #complete
* type = #summary
* measure = "https://upstream-onehealth.example/Measure/gi-presentations-by-area-day"
* subject = Reference(upstream-zone-A-population)
* date = "2026-09-23T02:00:00+01:00"
* period.start = "2026-09-22"
* period.end = "2026-09-22"
* group.measureScore.value = 7
* group.measureScore.unit = "presentations"
* group.measureScore.system = "http://unitsofmeasure.org"
* group.measureScore.code = #1
