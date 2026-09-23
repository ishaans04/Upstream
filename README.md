# Upstream (`upstream-onehealth`)

An event-driven **One Health** system that turns sparse citizen and sensor observations of an urban
stream into a computable, FHIR-published **Exposure Episode**.

| Capability | What it does |
|---|---|
| **TRACE** | Exact Bayesian posterior over ~11.5k source/time/mass hypotheses |
| **PULSE** | Per-zone exposure probability curves and 80% credible exposure windows |
| **PROBE** | Next-best-sample missions chosen by Equivalence Class Edge Cutting (EC²) |
| **BRIDGE** | FHIR R4 publication (OneAquaHealth IG) + CDS Hooks + clinical matched filter |

## Design in one paragraph

An append-only PostgreSQL event log is the single source of truth. A JAX kernel worker recomputes an
exact posterior from the *full* evidence set on every change and writes fingerprinted snapshots.
DBOS durable workflows drive the episode lifecycle from minutes to weeks. FHIR is a *published
view*, served by HAPI and validated against the OneAquaHealth IG with zero errors. A hard
database-level boundary isolates the clinical statistics service — only aggregate counts go in, only
test results come out. The map, the exports and the FHIR store are all rebuildable from the log.

## Stack

PostgreSQL 17 + TimescaleDB + PostGIS + pgRouting · Python 3.12 / FastAPI / DBOS Transact / JAX /
rustworkx / NumPyro / statsmodels / OR-Tools · HAPI FHIR JPA R4 + `hl7.eu.fhir.oah` ·
FSH / SUSHI / IG-Publisher / HL7 validator · Next.js 15 + MapLibre GL + deck.gl + PMTiles ·
Docker Compose · GitHub Actions.

## Quick start

```bash
cp .env.example .env     # fill in the values (see "Credentials" in the plan)
make up                  # bring up db, api, kernel, clinical, hapi, minio, web
make migrate             # run Alembic migrations
make test                # run the test suite
```

## Layout

```
packages/upstream-shared/   Pydantic models + code constants. No I/O. Depends on nothing.
services/core-api/          FastAPI: ingestion, episodes, missions, FHIR publishing, CDS Hooks
services/kernel/            JAX worker: network compiler, physics, TRACE/PULSE/PROBE
services/clinical-stats/    Isolated health zone: aggregates in, test results out
services/simulator/         Scenario generator writing to the same log (stream='sim')
services/bench/             Benchmark runner and metrics
db/                         Alembic migrations
fhir/                       FSH project, profiles, validation scripts
web/                        Next.js console + mission PWA
```

`packages/upstream-shared` holds *only* schemas and constants — that is what stops event payloads
drifting between producer and consumer.

## Stated assumptions

The PRD requires assumptions to be stated rather than buried (R4). These are the load-bearing
ones:

**Hydraulics are analytic, not simulated.** Velocities come from Manning's equation with a
uniform hydraulic radius and a single default channel slope, scaled by flow condition
(dry / wet / storm). A calibrated EPA SWMM model for an arbitrary OSM catchment cannot be
built inside the project window, and the posterior needs only *relative* travel times with
honest uncertainty. `services/kernel/upstream_kernel/physics/swmm.py` is the seam: a pilot
city with a real `.inp` file drops it in and the kernel does not change.

**Flow direction comes from OSM convention.** OpenStreetMap waterways are digitised
downstream, and the compiler trusts that. There is no elevation pipeline. Reversed reaches
are corrected by hand in `data/catchment/edge_orientation_overrides.json`.

**The stream graph is reduced to a tree.** Braided channels and distributaries are pruned to
a single outflow per node, because the travel-time model walks one downstream path.

**Travel-time uncertainty is Fickian.** The plume's standard deviation grows as the square
root of elapsed travel time, exactly: `sigma = dispersion_coeff * sqrt(tau)`. Phase 9
recalibrates `dispersion_coeff` against the 80%-window coverage target.

**Every outfall in the pilot catchment is synthetic.** The water utility has not published
CSO or storm-outfall locations for the Ribeira de Coselhas, so they are invented at
plausible positions and carry `is_synthetic: true`. The console labels them (PRD R2).

## Safety

The system never issues advisories, never contacts patients and never names a polluter. Every
health-facing output carries **"Environmental context, not a diagnosis."**

## Spec

See [`PRD.md`](PRD.md) and the implementation plan in
[`docs/superpowers/plans/`](docs/superpowers/plans/).

## Licence

Source code is public. Data formats are open (Parquet, FHIR JSON). Hosted in the EU.
