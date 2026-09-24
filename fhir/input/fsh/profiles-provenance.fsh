// fhir/input/fsh/profiles-provenance.fsh
//
// How a published episode came to exist. The plan names this profile but
// leaves its shape open; it is written here to carry exactly what FR-27 and
// GC-6 need to answer "who and what produced this version, from what".

Profile: UpstreamEpisodeProvenance
Parent: Provenance
Id: UpstreamEpisodeProvenance
Title: "Upstream Episode Provenance"
Description: "The derivation of one version of a published exposure episode: the evidence
it was computed from, the software that computed it, and the people whose confirmations
the evidence rests on. Nothing here is deleted or rewritten (GC-5)."
* ^url = "https://upstream-onehealth.example/StructureDefinition/UpstreamEpisodeProvenance"
* ^status = #draft
* ^experimental = false

* target 1..1 MS
* target only Reference(UpstreamExposureEpisode)
* target ^short = "The exact version of the episode this describes, as a versioned reference"

* recorded 1..1 MS
* occurredDateTime 0..1 MS
* occurredDateTime ^short = "When the kernel computed this version"

* agent 1..* MS
* agent.type 1..1 MS
* agent.type ^short = "assembler for the kernel; author for a person whose report is in the basis"
* agent.who 1..1 MS

* entity 0..* MS
* entity.role 1..1 MS
* entity.what 1..1 MS
* entity.what ^short = "An evidence Observation the episode was derived from"

* signature 0..* MS
* signature ^short = "Officer sign-off, where a state change required one (FR-21)"
