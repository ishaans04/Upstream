// fhir/input/fsh/profiles-risk.fsh
//
// The core artefact (PRD section 13.3). An exposure episode published as a
// computable RiskAssessment, carrying enough to recompute it bit for bit.

Profile: UpstreamExposureEpisode
Parent: RiskAssessment
Id: UpstreamExposureEpisode
Title: "Upstream Exposure Episode"
Description: "A time-bounded, evidence-backed hypothesis about one contamination event,
published as a computable RiskAssessment. Environmental exposure context, not a diagnosis."
* ^url = "https://upstream-onehealth.example/StructureDefinition/UpstreamExposureEpisode"
* ^status = #draft
* ^experimental = false

* identifier 1..* MS
* identifier ^short = "Episode identifier, for example EE-2841"
* status 1..1 MS
* status ^short = "preliminary for SUSPECTED/PROBABLE; final for CONFIRMED/RESOLVED; amended after new evidence; cancelled for REFUTED"
* meta.tag 1..* MS
* meta.tag from UpstreamEpisodeStateVS (required)
* meta.tag ^short = "The exact episode state from the Upstream code system"
* subject 1..1 MS
* subject only Reference(UpstreamZonePopulation)
* occurrenceDateTime 1..1 MS
* occurrenceDateTime ^short = "When THIS version of the episode was computed"
* method 1..1 MS
* method ^short = "Kernel version that computed this episode"
* basis 1..* MS
* basis only Reference(UpstreamEvidenceObservation)
* basis ^short = "Every observation used, positive and negative"
* prediction 1..* MS
* prediction.outcome 1..1 MS
* prediction.probability[x] only decimal
* prediction.probabilityDecimal 1..1 MS
* prediction.whenPeriod 1..1 MS
* prediction.whenPeriod ^short = "Clinical relevance window for this zone"
* note 1..* MS
* note ^short = "At least the GC-12 disclaimer: environmental context, not a diagnosis"

* extension contains
    UpstreamFingerprint named fingerprint 1..1 MS and
    UpstreamSourceRanking named sourceRanking 0..* MS and
    UpstreamExposureWindow named exposureWindow 0..* MS

Extension: UpstreamFingerprint
Id: upstream-fingerprint
Title: "Reproducibility fingerprint"
Description: "SHA-256 over the evidence set, network version, kernel version and parameter
version, so the published episode can be recomputed bit-for-bit."
* ^url = "https://upstream-onehealth.example/StructureDefinition/upstream-fingerprint"
* ^status = #draft
* ^context[0].type = #element
* ^context[0].expression = "RiskAssessment"
* value[x] only string

Extension: UpstreamSourceRanking
Id: upstream-source-ranking
Title: "Ranked candidate source"
Description: "One candidate entry point and the posterior probability the kernel gave it.
A ranking is never an accusation: GC-12 forbids naming a polluter, and a Location here is
an outfall on the network, not an operator."
* ^url = "https://upstream-onehealth.example/StructureDefinition/upstream-source-ranking"
* ^status = #draft
* ^context[0].type = #element
* ^context[0].expression = "RiskAssessment"
* extension contains sourceLocation 1..1 and probability 1..1 and sourceType 0..1
* extension[sourceLocation].value[x] only Reference(Location)
* extension[probability].value[x] only decimal
* extension[sourceType].value[x] only Coding
* extension[sourceType].valueCoding from UpstreamSourceTypeVS (required)

Extension: UpstreamExposureWindow
Id: upstream-exposure-window
Title: "Exposure window for one zone"
Description: "When contaminated water is credibly present in one zone, and by what routes
a person could contact it."
* ^url = "https://upstream-onehealth.example/StructureDefinition/upstream-exposure-window"
* ^status = #draft
* ^context[0].type = #element
* ^context[0].expression = "RiskAssessment"
* extension contains zone 1..1 and window 1..1 and pathway 0..* and credibleLevel 1..1
* extension[zone].value[x] only Reference(UpstreamExposureZone)
* extension[window].value[x] only Period
* extension[pathway].value[x] only Coding
* extension[pathway].valueCoding from UpstreamExposurePathwayVS (required)
* extension[credibleLevel].value[x] only decimal
* extension[credibleLevel] ^short = "Credible level of the window, 0.80 for an 80% window"
