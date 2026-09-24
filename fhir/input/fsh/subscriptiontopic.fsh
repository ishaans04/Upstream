// fhir/input/fsh/subscriptiontopic.fsh
//
// FR-29: a subscriber is told when an episode changes state, rather than
// polling for it.
//
// R4 has no SubscriptionTopic resource, and the R4 subscriptions backport does
// not add one -- it ships the Subscription profile and the extensions, and a
// topic is identified purely by canonical URL in Subscription.criteria. An
// R4 IG that defines a SubscriptionTopic instance therefore cannot even be
// parsed ("unknown or unrecognized resource name 'SubscriptionTopic'"). The
// topic is expressed here the way R4 expresses it: a profile that pins
// criteria to Upstream's topic canonical, and an example subscription.

Profile: UpstreamEpisodeStateChangeSubscription
Parent: http://hl7.org/fhir/uv/subscriptions-backport/StructureDefinition/backport-subscription
Id: UpstreamEpisodeStateChangeSubscription
Title: "Subscription to Exposure Episode state changes"
Description: "A subscription that fires when an exposure episode is created or moves
between states. The topic canonical is fixed: this is the only topic Upstream publishes."
* ^url = "https://upstream-onehealth.example/StructureDefinition/UpstreamEpisodeStateChangeSubscription"
* ^status = #draft
* ^experimental = false
// A pattern, not a fixed value: `(exactly)` means the element must match with
// nothing added, and the backport carries the filter as an extension *on*
// criteria -- so fixing the value forbids the very extension the profile needs.
* criteria = "https://upstream-onehealth.example/SubscriptionTopic/episode-state-change"
* criteria ^short = "The Upstream episode state change topic, by canonical URL"
* reason 1..1 MS
* channel.type 1..1 MS
* channel.endpoint 1..1 MS
* channel.endpoint ^short = "Where the notification is delivered. Notifications carry an id only; a subscriber reads the episode back over the API, where the read is audited (FR-30)."

Instance: upstream-episode-state-change-subscription
InstanceOf: UpstreamEpisodeStateChangeSubscription
Usage: #example
Title: "A public health system subscribing to episode state changes"
Description: "Registered by the API at startup. The payload is id-only, so nothing about
an episode travels over the channel itself."
* status = #requested
* reason = "Notify public health systems of Exposure Episode state changes"
* criteria = "https://upstream-onehealth.example/SubscriptionTopic/episode-state-change"
* criteria.extension[backport-filter-criteria].valueString = "RiskAssessment?_tag=https://upstream-onehealth.example/CodeSystem/episode-state|"
* channel.type = #rest-hook
* channel.endpoint = "https://public-health.example/upstream-notifications"
* channel.payload = #application/fhir+json
* channel.payload.extension[backport-payload-content].valueCode = #id-only
