// fhir/input/fsh/profiles-measure.fsh
//
// The only clinical thing Upstream publishes: a count, for an area and a day,
// of presentations matching a syndrome. Counts cross the health boundary;
// people never do (GC-7).

Profile: UpstreamSyndromicCount
Parent: MeasureReport
Id: UpstreamSyndromicCount
Title: "Aggregate syndromic count for one area and day"
Description: "Aggregate counts only. Small counts are suppressed before this resource is
created. No patient-level data ever crosses this boundary (GC-7)."
* ^url = "https://upstream-onehealth.example/StructureDefinition/UpstreamSyndromicCount"
* ^status = #draft
* ^experimental = false

* type = #summary (exactly)
* type ^short = "Never #individual: an individual report would carry a patient (GC-7)"
* subject 1..1 MS
* subject only Reference(Group)
* subject ^short = "The population of an area, never a Patient"
* period 1..1 MS
* group.measureScore.value 0..1 MS
* group.measureScore ^short = "Count for the area/day/syndrome; absent when suppressed"
