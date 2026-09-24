// fhir/input/fsh/profiles-observation.fsh
//
// Evidence, as published. One Observation per event in Upstream's log: a
// citizen report, a sensor reading, a field test, a laboratory result. The
// parent is the OneAquaHealth indicator observation (GC-2) -- Upstream
// observes the same river indicators OneAquaHealth does, and adds the
// instrument and the bitemporal discipline the kernel needs.

Profile: UpstreamEvidenceObservation
Parent: $oah-observation-indicators
Id: UpstreamEvidenceObservation
Title: "Upstream Evidence Observation"
Description: "One piece of evidence about the state of the catchment, positive or
negative, with both the time it happened and the time the system learned it (GC-4).
Retraction is a status change, never a delete (GC-5, FR-10)."
* ^url = "https://upstream-onehealth.example/StructureDefinition/UpstreamEvidenceObservation"
* ^status = #draft
* ^experimental = false

* status 1..1 MS
* status ^short = "final; entered-in-error when the observation is retracted (FR-10)"

* code 1..1 MS
* code from UpstreamIndicatorVS (extensible)
* code ^short = "What was observed, as a OneAquaHealth indicator"

* subject 1..1 MS
* subject only Reference(UpstreamExposureZone or $oah-location)
* subject ^short = "The zone the observation is about, or the reach or node it was taken at."
* subject ^comment = "The OneAquaHealth parent already restricts this to its own Location profile, so a reach or node Location conforms to location-oah even when it is not an exposure zone."

* effectiveDateTime 1..1 MS
* effectiveDateTime ^short = "Event time: when the observation happened"
* issued 1..1 MS
* issued ^short = "Record time: when the system learned it (bitemporal, GC-4)"

* method 1..1 MS
* method from UpstreamObservationMethodVS (required)
* method ^short = "The instrument or procedure behind the value"

* value[x] 0..1
* valueQuantity.system = "http://unitsofmeasure.org" (exactly)   // UCUM, GC-13

* dataAbsentReason 0..1 MS
* dataAbsentReason ^short = "Used for explicit negative observations ('checked, looks normal')"

* performer 1..* MS
* performer ^short = "Citizen, officer, laboratory or device owner. The OneAquaHealth parent requires at least one."
* device 0..1 MS

* extension contains
    UpstreamAiAssisted named aiAssisted 0..1 MS and
    UpstreamObserverReliability named observerReliability 0..1 MS

Extension: UpstreamAiAssisted
Id: upstream-ai-assisted
Title: "AI-assisted observation"
Description: "GC-8: an AI proposed these fields and the observer confirmed them. Absent
means no model was involved. Present with confirmedByObserver false must never happen --
Upstream does not accept an unconfirmed proposal as evidence."
* ^url = "https://upstream-onehealth.example/StructureDefinition/upstream-ai-assisted"
* ^status = #draft
* ^context[0].type = #element
* ^context[0].expression = "Observation"
* extension contains modelId 1..1 and confirmedByObserver 1..1
* extension[modelId].value[x] only string
* extension[modelId] ^short = "The exact model identifier, for example claude-opus-5"
* extension[confirmedByObserver].value[x] only boolean
* extension[confirmedByObserver] ^short = "The citizen confirmed every field the model proposed"

Extension: UpstreamObserverReliability
Id: upstream-observer-reliability
Title: "Observer reliability"
Description: "The weight the kernel gave this observer when it computed the posterior.
Published so that a reader can see why two reports of the same thing did not count
equally; it is an input to the model, not a judgement about a person."
* ^url = "https://upstream-onehealth.example/StructureDefinition/upstream-observer-reliability"
* ^status = #draft
* ^context[0].type = #element
* ^context[0].expression = "Observation"
* value[x] only decimal
* valueDecimal ^short = "Reliability in [0, 1] as used by the kernel for this observation"
