// fhir/input/fsh/valuesets.fsh
//
// One value set per Upstream code system, plus the indicator set Upstream
// actually observes. The indicator set is drawn from the OneAquaHealth IG's
// own code system rather than a new one (GC-2): Upstream measures the same
// things OneAquaHealth measures, through different instruments.

ValueSet: UpstreamEpisodeStateVS
Id: episode-state-vs
Title: "Upstream Exposure Episode State"
Description: "Every lifecycle state an exposure episode can be tagged with."
* ^url = "https://upstream-onehealth.example/ValueSet/episode-state-vs"
* ^status = #draft
* ^experimental = false
* include codes from system UpstreamEpisodeState

ValueSet: UpstreamExposurePathwayVS
Id: exposure-pathway-vs
Title: "Upstream Exposure Pathway"
Description: "Routes by which a person can contact contaminated water in a zone."
* ^url = "https://upstream-onehealth.example/ValueSet/exposure-pathway-vs"
* ^status = #draft
* ^experimental = false
* include codes from system UpstreamExposurePathway

ValueSet: UpstreamObservationMethodVS
Id: observation-method-vs
Title: "Upstream Observation Method"
Description: "How an Upstream evidence observation was made."
* ^url = "https://upstream-onehealth.example/ValueSet/observation-method-vs"
* ^status = #draft
* ^experimental = false
* include codes from system UpstreamObservationMethod

ValueSet: UpstreamSourceTypeVS
Id: source-type-vs
Title: "Upstream Source Type"
Description: "Kinds of candidate contamination entry point."
* ^url = "https://upstream-onehealth.example/ValueSet/source-type-vs"
* ^status = #draft
* ^experimental = false
* include codes from system UpstreamSourceType

ValueSet: UpstreamCohortCharacteristicVS
Id: cohort-characteristic-vs
Title: "Upstream Cohort Characteristic"
Description: "Characteristics that define an Upstream zone population."
* ^url = "https://upstream-onehealth.example/ValueSet/cohort-characteristic-vs"
* ^status = #draft
* ^experimental = false
* include codes from system UpstreamCohortCharacteristic

ValueSet: UpstreamIndicatorVS
Id: indicator-vs
Title: "Upstream Observed Indicator"
Description: "What an Upstream evidence observation measures. Every code is a
OneAquaHealth indicator (GC-2); Upstream adds instruments, not concepts."
* ^url = "https://upstream-onehealth.example/ValueSet/indicator-vs"
* ^status = #draft
* ^experimental = false
* $oah-temporary#foam "Foam/colour/smell"
* $oah-temporary#coliforms "Coliforms"
* $oah-temporary#conductivity "Conductivity"
* $oah-temporary#tss "Total suspended solids (TSS)"
* $oah-temporary#waterTemperature "Water temperature"
* $oah-temporary#dissolvedO2 "Dissolved O2"
* $oah-temporary#macroinvertebreates "Benthic Macro invertebrates count"
* $oah-temporary#ammonium "Ammonium"
* $oah-temporary#nitrite "Nitrite"
* $oah-temporary#nitrate "Nitrate"
* $oah-temporary#hydrology "Hydrology of the stream"
