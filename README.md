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

## Safety

The system never issues advisories, never contacts patients and never names a polluter. Every
health-facing output carries **"Environmental context, not a diagnosis."**

## Spec

See [`PRD.md`](PRD.md) and the implementation plan in
[`docs/superpowers/plans/`](docs/superpowers/plans/).

## Licence

Source code is public. Data formats are open (Parquet, FHIR JSON). Hosted in the EU.
