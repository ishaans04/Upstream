// fhir/input/fsh/profiles-location.fsh
//
// An exposure zone: the stretch of catchment a plume is expected to reach
// inside one clinical relevance window. Derived from the OneAquaHealth
// location profile (GC-2), which already requires an identifier, a name and a
// mode.

Profile: UpstreamExposureZone
Parent: $oah-location
Id: UpstreamExposureZone
Title: "Upstream Exposure Zone"
Description: "A named stretch of the catchment that a contamination plume is predicted to
reach. Zones are the only geography Upstream publishes; no patient location ever appears
here (GC-7)."
* ^url = "https://upstream-onehealth.example/StructureDefinition/UpstreamExposureZone"
* ^status = #draft
* ^experimental = false

* identifier 1..* MS
* identifier ^short = "Stable zone identifier, for example ZONE_A"
* name 1..1 MS
* mode ^short = "#instance, fixed by the OneAquaHealth parent: a zone is a specific stretch of one catchment"

* position 0..1 MS
* position ^short = "Representative point for the zone, for map display"
* type 1..* MS
* type ^short = "Physical type of the place the zone covers"

* extension contains
    $location-boundary-geojson named boundary 0..1 MS
* extension[boundary] ^short = "Zone polygon as GeoJSON (PRD 13.2)"
