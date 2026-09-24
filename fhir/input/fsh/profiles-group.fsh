// fhir/input/fsh/profiles-group.fsh
//
// The population of an exposure zone. This is the subject of every published
// episode: Upstream reasons about places and the people in them, never about
// an identified patient (GC-7, GC-12).

Profile: UpstreamZonePopulation
Parent: $oah-group
Id: UpstreamZonePopulation
Title: "Upstream Zone Population"
Description: "Everyone present in one exposure zone during an episode window, as a
descriptive group. The group is never enumerated -- the OneAquaHealth parent forbids
members, and Upstream has no membership to publish."
* ^url = "https://upstream-onehealth.example/StructureDefinition/UpstreamZonePopulation"
* ^status = #draft
* ^experimental = false

* type = #person (exactly)
* actual = false (exactly)
* actual ^short = "Descriptive: a definition of who would be affected, not a roster (GC-7)"
* name 1..1 MS
* name ^short = "For example: Population of exposure zone ZONE_A"

* characteristic 1..* MS
* characteristic.code from UpstreamCohortCharacteristicVS (extensible)
* characteristic ^short = "At least the zone this population is defined by"
