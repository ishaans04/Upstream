// fhir/input/fsh/codesystems.fsh
//
// Upstream's own code systems (GC-13). These describe things the OneAquaHealth
// IG has no concept for -- the lifecycle of an exposure episode, how an
// observation was made, what kind of thing a source is. What an observation
// measures is *not* here: that comes from the OAH indicator codes, because
// GC-2 forbids a parallel model of the same thing.

CodeSystem: UpstreamEpisodeState
Id: episode-state
Title: "Upstream Exposure Episode State"
Description: "Lifecycle state of an Exposure Episode (PRD section 6.3)."
* ^url = "https://upstream-onehealth.example/CodeSystem/episode-state"
* ^status = #draft
* ^experimental = false
* ^caseSensitive = true
* ^content = #complete
* #SUSPECTED "Suspected" "Probability of an event is above the suspected threshold."
* #PROBABLE  "Probable"  "Probability of an event is above the probable threshold."
* #CONFIRMED "Confirmed" "A positive field or lab result plus officer sign-off."
* #REFUTED   "Refuted"   "Probability fell below the refuted threshold, or an officer rejected it."
* #RESOLVED  "Resolved"  "Plume passed and the clinical relevance window elapsed."

CodeSystem: UpstreamExposurePathway
Id: exposure-pathway
Title: "Upstream Exposure Pathway"
Description: "How a person could come into contact with contaminated water in a zone."
* ^url = "https://upstream-onehealth.example/CodeSystem/exposure-pathway"
* ^status = #draft
* ^experimental = false
* ^caseSensitive = true
* ^content = #complete
* #recreation     "Recreation"     "Paddling, wading, water play."
* #animal_contact "Animal contact" "Dogs and other animals entering the water."
* #floodwater     "Floodwater"     "Contact with flooded streets or paths."
* #irrigation     "Irrigation"     "Allotments or gardens irrigated from the stream."

CodeSystem: UpstreamObservationMethod
Id: observation-method
Title: "Upstream Observation Method"
Description: "How an observation was made. This is the provenance of the measurement, not
what was measured -- the measured indicator is coded from the OneAquaHealth IG (GC-2)."
* ^url = "https://upstream-onehealth.example/CodeSystem/observation-method"
* ^status = #draft
* ^experimental = false
* ^caseSensitive = true
* ^content = #complete
* #citizen_visual_olfactory "Citizen visual and olfactory check"
* #citizen_freetext         "Citizen free-text report"
* #citizen_photo            "Citizen photograph"
* #test_strip               "Field test strip"
* #sensor_turbidity         "Turbidity sensor"
* #sensor_conductivity      "Conductivity sensor"
* #sensor_normal_window     "Sensor normal for a time window"
* #field_test               "Officer field test"
* #lab_ecoli                "Laboratory E. coli count"
* #lab_enterococci          "Laboratory intestinal enterococci count"
* #overflow_telemetry       "Overflow activation telemetry"
* #bioassessment            "Post-episode bioassessment"

CodeSystem: UpstreamSourceType
Id: source-type
Title: "Upstream Source Type"
Description: "The kind of entry point a candidate source is."
* ^url = "https://upstream-onehealth.example/CodeSystem/source-type"
* ^status = #draft
* ^experimental = false
* ^caseSensitive = true
* ^content = #complete
* #cso            "Combined sewer overflow"
* #storm_outfall  "Storm water outfall"
* #industrial     "Industrial discharge point"
* #misconnection  "Misconnected drain"
* #diffuse_runoff "Diffuse urban runoff"
* #unknown        "Unknown entry point"

CodeSystem: UpstreamCohortCharacteristic
Id: cohort-characteristic
Title: "Upstream Cohort Characteristic"
Description: "Characteristics that define an Upstream zone population. The OneAquaHealth
cohort-characteristic value set carries only age and sex; its binding is extensible, and
an exposure zone population is defined by where people are, not by who they are."
* ^url = "https://upstream-onehealth.example/CodeSystem/cohort-characteristic"
* ^status = #draft
* ^experimental = false
* ^caseSensitive = true
* ^content = #complete
* #zone-presence "Present in an exposure zone" "Resident in, or otherwise present in, the referenced exposure zone during the episode window."
