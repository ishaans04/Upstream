# Assumptions and limits

What Upstream simplifies, what it invents, and what its evaluation does and does not
show. The PRD asks for these to be stated, not buried (R4, R12).

## What is real and what is simulated

| Real | Simulated or invented |
|---|---|
| The drain network: the Kushak Nallah and Barapulla Nala in South Delhi, from the colony drains of R K Puram, Green Park and Chirag Delhi to the Yamuna at Sarai Kale Khan, compiled from OpenStreetMap (network `16811181e3006ac9`: 559 nodes, 495 reaches, 83 exposure zones) | **Every outfall.** No public register of sewer overflows, misconnections or storm outfalls exists for these drains. The 10 outfalls are placed at plausible positions and carry `is_synthetic: true`; the console badges each one (PRD R2) |
| The kernel, the episode lifecycle, the mission planner, the FHIR layer, the clinical statistics: all run as they would in production | **Every incident, report, sensor reading and clinical count** in the demo and the benchmarks, from the simulator (`stream = 'sim'`) |
| The OneAquaHealth FHIR IG, built from its public source | Zone populations (below) |

## Physics

- **Travel times are analytic, not a calibrated hydraulic model.** Velocities come from
  Manning's equation, with a uniform hydraulic radius and one default channel slope,
  scaled by flow condition (dry, wet, storm). A calibrated EPA SWMM model of an arbitrary
  OSM catchment cannot be built in a hackathon. The posterior needs relative travel times
  with honest uncertainty, and the 80% windows are checked for calibration (below).
  `services/kernel/upstream_kernel/physics/swmm.py` is the seam where a real model plugs
  in.
- **Flow direction follows OpenStreetMap's digitisation convention** (waterways are drawn
  downstream). There is no elevation pipeline. A reach drawn the wrong way can be
  reversed by listing it in `data/catchment/edge_orientation_overrides.json`; no
  overrides are in use for the Delhi network, so a mis-drawn reach there would go
  undetected.
- **The network is a tree.** Each node has one downstream path. Braids and distributaries
  are pruned; loops and backwater are out of scope, and the compiler refuses a cycle.
- **Spreading is Fickian**: a plume's spread grows as the square root of travel time. The
  coefficient was swept against the coverage target in Phase 9 and left unchanged.
- **One source at a time.** Two simultaneous discharges are outside the hypothesis space;
  multi-source inference is in the scale path.

## Data the network does not have

- **Zone populations are placeholders**: 200 people for 81 of the 83 exposure zones on
  the Delhi network, 250 and 400 for the other two. At realistic attack rates that is two or three extra clinic visits per area
  after an incident, which no statistical test could tell from an ordinary week. That is
  the honest result, and it is what the system reports.

  The benchmark's clinical goal (G5) and the demo's day-3 beat therefore state the
  outbreak size instead of deriving it: 40 cases on average in the benchmark, 25 extra
  presentations per exposed area in the demo. A pilot needs real catchment populations
  from census or ward data.
- **Rainfall** in the demo and benchmarks is simulated. The live stream polls Open-Meteo
  every 15 minutes.

## The evaluation is on synthetic data

All numbers below come from the simulator, on the real Delhi network, with ground truth
the kernel cannot read (`sim_truth`, enforced by database grants). The simulator uses its
own physics and its own detection tables, not the kernel's, so agreement is not
circular. It still validates the **method under its assumptions, not field
performance.** Field validation needs a pilot with real outfalls, volunteers and lab
confirmation.

200 scenarios, seed 20260922 (`bench/results/summary.json`):

| Goal | Target | Result | Met? |
|---|---|---|---|
| G1 Top-3 source accuracy after 5 reports | ≥ 80% | 86.5% | Yes. The nearest-upstream heuristic scores 88.5% on this network; see below |
| G2 80% exposure-window coverage | 75–85% | 77.6% | Yes |
| Calibration error (reliability) | ≤ 0.05 | 0.050 | Yes, at the limit |
| G3 Samples needed to localise | ≥ 30% fewer than the best baseline | 21% **more** | **No** |
| G5 Clinical detection delay | Shorter than a blind cluster scan | 6.5 d vs 9.2 d | Yes |
| False episodes | Low | 0 per catchment-month (100 null days) | Yes |
| Evidence-to-posterior latency, p95 | < 5 s | 2.8 s | Yes |

**Where it falls short, plainly:**

- **G3 is not met.** On this network PROBE's decision-aware sampling does not beat
  simply checking the nearest site or a random one. Two reasons were diagnosed:
  - Test strips miss about a quarter of real contamination, so a single "looks normal"
    is weak evidence.
  - Many simulated spills finish before anyone could sample them, so no strategy can
    localise them.

  The benchmark also reports the probability of the true source after 0, 3, 5 and 10
  samples, which is a finer measure than a count to a threshold.
- **The nearest-upstream heuristic edges out TRACE on top-3 accuracy here.** The Delhi
  tree is narrow: most reports have only a few outfalls upstream, so "the nearest ones"
  is often right. What TRACE adds that the heuristic cannot:
  - calibrated probabilities;
  - exposure windows downstream;
  - the use of negative evidence;
  - it doesn't need to be told which reports are real.

## Thresholds and parameters

- Episode thresholds are 0.50 (SUSPECTED), 0.90 (PROBABLE) and 0.10 (REFUTED), as PRD
  §6.3 proposes. They held in Phase 9 (no false episodes in 100 null days), but they are
  provisional until a pilot.
- An episode reopens on new evidence only within the kernel's 24-hour evidence horizon;
  after that, a new belief is a new episode.
- The clinical window is 16 days (FR-22); the bioassessment survey opens 14 days after
  a confirmed episode resolves (FR-24).

## Software limits of this version

- **The AI normaliser has had only a smoke test.** `GroqNormaliser` uses Groq's official
  SDK with a fixed output schema (model `openai/gpt-oss-120b`, text only) and switches on
  when `GROQ_API_KEY` is set; without it the deterministic `StubNormaliser` handles every
  report, which is also what CI uses. Live calls have been checked on a handful of
  reports, not evaluated at scale.
- **Access control is MVP-grade:** static signed tokens rather than Keycloak, and citizen
  actions are unauthenticated. See [SECURITY.md](SECURITY.md).
- **Photos are not screened** for faces or number plates. They are withheld from every
  public view instead. See [PRIVACY.md](PRIVACY.md).
- **The OneAquaHealth IG is a vendored build.** `hl7.eu.fhir.oah` has no published
  release, so it is built from its public source (`fhir/scripts/vendor-oah-ig.sh`) and
  committed as `fhir/vendor/hl7.eu.fhir.oah.tgz` (version `0.1.0-ci-build`).
- **Deferred, per PRD §17:**
  - missions as FHIR `Task` (FR-31);
  - the SMART on FHIR app (FR-40); the CDS card's link is informational;
  - Keycloak.
- **The scripted demo departs from the PRD §10.5 timetable** in three places, each forced
  by the system's own rules or data:
  - it runs in daylight, because no mission is sent in darkness;
  - the 68 mm/h storm eases before PROBE plans, because no mission is sent in a storm;
  - the source and its rival are chosen from the Delhi topology.

  `services/simulator/upstream_sim/demo_scenario.py` states each one.
