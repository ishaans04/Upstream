// fhir/input/fsh/aliases.fsh
//
// Every alias Upstream's profiles use. The OAH aliases are the parents GC-2
// requires us to derive from; they resolve out of the vendored
// hl7.eu.fhir.oah package, so a broken vendor step shows up here first.

// --- OneAquaHealth IG (GC-2) -----------------------------------------------
Alias: $oah-observation-indicators = http://hl7.eu/fhir/ig/oah/StructureDefinition/observation-indicators-oah
Alias: $oah-observation-components = http://hl7.eu/fhir/ig/oah/StructureDefinition/observation-with-component-oah
Alias: $oah-observation-health-measure = http://hl7.eu/fhir/ig/oah/StructureDefinition/observation-health-measure-oah
Alias: $oah-location = http://hl7.eu/fhir/ig/oah/StructureDefinition/location-oah
Alias: $oah-group = http://hl7.eu/fhir/ig/oah/StructureDefinition/group-oah
Alias: $oah-specimen = http://hl7.eu/fhir/ig/oah/StructureDefinition/specimen-oah

// --- Terminology (GC-13) ---------------------------------------------------
Alias: $loinc = http://loinc.org
Alias: $sct = http://snomed.info/sct
Alias: $ucum = http://unitsofmeasure.org
Alias: $obs-category = http://terminology.hl7.org/CodeSystem/observation-category
Alias: $v3-ActReason = http://terminology.hl7.org/CodeSystem/v3-ActReason
Alias: $audit-event-type = http://terminology.hl7.org/CodeSystem/audit-event-type
Alias: $provenance-participant-type = http://terminology.hl7.org/CodeSystem/provenance-participant-type
Alias: $location-physical-type = http://terminology.hl7.org/CodeSystem/location-physical-type
Alias: $measure-scoring = http://terminology.hl7.org/CodeSystem/measure-scoring
Alias: $location-boundary-geojson = http://hl7.org/fhir/StructureDefinition/location-boundary-geojson

// --- Upstream's own code systems (Task 7.2) --------------------------------
Alias: $episode-state = https://upstream-onehealth.example/CodeSystem/episode-state
Alias: $exposure-pathway = https://upstream-onehealth.example/CodeSystem/exposure-pathway
Alias: $observation-method = https://upstream-onehealth.example/CodeSystem/observation-method
Alias: $source-type = https://upstream-onehealth.example/CodeSystem/source-type

// --- OAH terminology -------------------------------------------------------
Alias: $oah-temporary = http://hl7.eu/fhir/ig/oah/CodeSystem/temporarySystem-oah-eu
Alias: $upstream-cohort-characteristic = https://upstream-onehealth.example/CodeSystem/cohort-characteristic
