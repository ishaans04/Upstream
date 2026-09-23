# Upstream (upstream-onehealth) — Phase-wise Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the Phase-0 Hackathon MVP of Upstream — an event-driven One Health system that turns sparse citizen/sensor observations of an urban stream into a computable, FHIR-published **Exposure Episode** (TRACE source inference, PULSE exposure windows, PROBE next-best-sample, BRIDGE clinical relevance) — in 6 working days, with every P0 requirement of `PRD.md` covered.

**Architecture:** Append-only Postgres event log is the single source of truth. A JAX kernel worker recomputes an exact posterior over ~11.5k hypotheses on every evidence change and writes fingerprinted snapshots. DBOS durable workflows inside the Core API drive the episode lifecycle (minutes → weeks). FHIR is a *published view* served by HAPI and validated against the OneAquaHealth IG. A hard database-level boundary isolates the clinical statistics service. Everything (map, exports, FHIR store) is rebuildable from the log.

**Tech Stack:** PostgreSQL 17 + TimescaleDB + PostGIS + pgRouting · Python 3.12 / FastAPI / DBOS Transact / JAX / rustworkx / NumPyro / statsmodels / OR-Tools · HAPI FHIR JPA R4 + `hl7.eu.fhir.oah` · FSH/SUSHI/IG-Publisher/HL7 validator · Next.js 15 + MapLibre GL + deck.gl + PMTiles · Docker Compose · GitHub Actions.

**Spec:** [`PRD.md`](../../../PRD.md) — the plan argues from the PRD; executors read both.

---

## Global Constraints

Copied verbatim from the PRD. **Every task's requirements implicitly include this section.**

| # | Constraint | Source |
|---|---|---|
| GC-1 | Repository name is `upstream-onehealth` (never bare `upstream`). | PRD header, R10 |
| GC-2 | FHIR **R4**, built on the OneAquaHealth IG package `hl7.eu.fhir.oah`. Where the OAH IG has a profile, derive from it; do not invent parallel models. | §13.1 |
| GC-3 | **Zero errors** from the HL7 validator against the OAH IG, in CI and on write. This is the gating condition for the Track 7 submission. | §3.2, G4, FR-26 |
| GC-4 | Every observation stores **two times**: `event_time` (when it happened) and `recorded_at` (when the system learned it). | FR-4, NFR-4 |
| GC-5 | Nothing is ever deleted. Retractions and corrections are **new events**. `REVOKE UPDATE, DELETE ON events FROM app_role`. | FR-10, NFR-4 |
| GC-6 | Posteriors are **recomputed from the full evidence set**, never incrementally updated. Deterministic CPU execution, pinned versions, bit-for-bit reproducible from a fingerprint. | §7.2, G6, NFR-3 |
| GC-7 | No patient-level data outside the health zone. Only **aggregate counts** enter; only **test results** leave. Separate container, database and credentials. | NFR-5, §14.1 |
| GC-8 | AI (language model) **proposes fields only**. The citizen confirms every field. Provenance records model + version. AI never makes a decision. | §7.8, FR-3, FR-27 |
| GC-9 | Latency: new evidence → updated posterior **p95 < 5 s**. CDS Hooks responses **< 500 ms**. | NFR-1, NFR-2 |
| GC-10 | The simulator writes to the **same event log** (`stream = 'sim'`); ground truth lives in a separate schema the kernel role cannot read. | FR-42, FR-43, §15.1 |
| GC-11 | Exposure windows are **80% credible windows**. Calibration target: coverage 75–85%, calibration error ≤ 0.05. | G2, §15.2 |
| GC-12 | The system never issues advisories, never contacts patients, never names a polluter. Every health-facing output carries "Environmental context, not a diagnosis." | §5.2, §14.4 |
| GC-13 | Units: **UCUM**. Codes: OAH code systems for indicators, LOINC for lab tests, SNOMED CT for syndromes *where licensed*; local CodeSystems for episode state / exposure pathway / observation method / source type. | NFR-7, §13.1 |
| GC-14 | Accessibility: WCAG 2.1 AA for console and mission app; plain-language labels. | NFR-10 |
| GC-15 | Hosted in the EU. Source code public. Open formats (Parquet, FHIR JSON). | NFR-11, NFR-12 |
| GC-16 | LLM calls use the official `anthropic` Python SDK, model `claude-opus-5`, schema-constrained via `client.messages.parse(output_format=<PydanticModel>)`. Never raw HTTP, never another provider. | §7.8 + claude-api skill |
| GC-17 | Secrets live in `.env` (git-ignored). `.env.example` lists every variable with an empty value. No credential ever enters the repository. | §14.3 |

### Never cut (PRD §17)

The kernel · the simulator benchmarks · FHIR validation · belief replay. If time runs out, cut in this order instead: Subscriptions → recurring-source pooling → bioassessment missions → Keycloak → SMART app → FHIR `Task`.

---

## Day map (6 days, 22–28 Sep, with 29–30 Sep as buffer before the 30 Sep 21:00 PDT deadline)

| Day | Phases | Headline deliverable |
|---|---|---|
| **D1** | 0, 1, 2 | Stack boots; real catchment compiled to arrays; travel-time tables exist |
| **D2** | 3, 4 | Evidence flows into the log; TRACE posterior computes and is fingerprinted |
| **D3** | 5, 6 | PULSE windows + PROBE/EC² missions; episode lifecycle runs end-to-end |
| **D4** | 7, 8 | FHIR profiles validate with zero errors; CDS card returns; clinical matched filter works |
| **D5** | 9, 10 | Simulator + benchmark charts; console with belief replay + mission PWA |
| **D6** | 11, 12 | Pooling, exports, hardening; demo video, docs, submission |

Each phase below is independently reviewable and ends with a green test run and a commit.

---

# Phase 0 — Foundation: repo, containers, database, CI

**Day 1, morning (≈3 h).** Everything after this depends on the stack booting and migrations running.

**PRD coverage:** §11.1 (6 containers), §12.1 (schema overview), §12.2 (event log), NFR-3, NFR-12, GC-1, GC-5, GC-17.

## File structure

```
upstream-onehealth/
├── PRD.md
├── README.md
├── .env.example                      # every secret, empty values
├── .gitignore
├── docker-compose.yml
├── Makefile                          # up / down / migrate / test / bench / validate
├── docker/
│   ├── Dockerfile.python             # shared base for api, kernel, clinical, sim
│   ├── Dockerfile.web
│   └── postgres/init/00-extensions.sql
├── db/
│   ├── alembic.ini
│   └── migrations/versions/
├── services/
│   ├── core-api/      (upstream_api/, tests/, pyproject.toml)
│   ├── kernel/        (upstream_kernel/, tests/, pyproject.toml)
│   ├── clinical-stats/(clinical_stats/, tests/, pyproject.toml)
│   ├── simulator/     (upstream_sim/, tests/, pyproject.toml)
│   └── bench/         (benchmarks/, tests/, pyproject.toml)
├── packages/
│   └── upstream-shared/upstream_shared/  (events.py, evidence.py, episode.py, mission.py, codes.py)
├── fhir/                             # FSH project (Phase 7)
├── web/                              # Next.js (Phase 10)
├── data/
│   ├── catchment/                    # curated GeoJSON inputs (committed)
│   └── artifacts/                    # compiled network + tables (git-ignored, built)
├── docs/superpowers/plans/
└── .github/workflows/ci.yml
```

**Responsibility split:** `packages/upstream-shared` holds *only* Pydantic models and code constants — no I/O, no DB. Every service depends on it; it depends on nothing. This is what stops event payloads drifting between producer and consumer.

---

### Task 0.1: Repository skeleton and pinned Python workspace

**Files:**
- Create: `.gitignore`, `README.md`, `Makefile`, `pyproject.toml` (workspace root), `.env.example`

**Interfaces:**
- Produces: a `uv` workspace where `import upstream_shared` resolves from every service.

- [ ] **Step 1: Initialise the repository**

```bash
cd upstream-onehealth && git init -b main
```

- [ ] **Step 2: Write `.gitignore`**

```gitignore
__pycache__/
*.py[cod]
.venv/
.env
.env.local
data/artifacts/
node_modules/
web/.next/
fhir/fsh-generated/
fhir/output/
fhir/input-cache/
.pytest_cache/
.ruff_cache/
bench/results/
*.parquet
```

- [ ] **Step 3: Write the root `pyproject.toml`**

```toml
[project]
name = "upstream-onehealth"
version = "0.1.0"
requires-python = "==3.12.*"

[tool.uv.workspace]
members = ["packages/*", "services/*"]

[tool.uv.sources]
upstream-shared = { workspace = true }

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.pytest.ini_options]
testpaths = ["services", "packages"]
addopts = "-q --strict-markers"
markers = ["integration: needs docker-compose services", "slow: benchmark-scale"]
```

Pin exact versions in each service `pyproject.toml` — GC-6 requires bit-for-bit reproducibility:
`fastapi==0.115.*`, `uvicorn[standard]==0.32.*`, `pydantic==2.9.*`, `dbos==0.26.*`,
`psycopg[binary,pool]==3.2.*`, `sqlalchemy==2.0.*`, `alembic==1.14.*`, `jax[cpu]==0.4.35`,
`rustworkx==0.15.*`, `numpy==2.1.*`, `scipy==1.14.*`, `numpyro==0.15.*`, `statsmodels==0.14.*`,
`ortools==9.11.*`, `shapely==2.0.*`, `pyproj==3.7.*`, `geopandas==1.0.*`, `osmnx==2.0.*`,
`duckdb==1.1.*`, `pyarrow==17.*`, `anthropic>=1.0,<2`, `pywebpush==2.0.*`,
`pytest==8.3.*`, `pytest-asyncio==0.24.*`, `ruff==0.7.*`.

- [ ] **Step 4: Write `.env.example` — every variable, all values empty**

```dotenv
# ---- Phase 0 ----
POSTGRES_USER=upstream
POSTGRES_PASSWORD=
POSTGRES_DB=upstream
DATABASE_URL=
KERNEL_DATABASE_URL=
CLINICAL_DATABASE_URL=
CATCHMENT_ID=
# ---- Phase 3 ----
ANTHROPIC_API_KEY=
MEDIA_S3_ENDPOINT=
MEDIA_S3_BUCKET=
MEDIA_S3_ACCESS_KEY=
MEDIA_S3_SECRET_KEY=
OPEN_METEO_BASE_URL=https://api.open-meteo.com/v1
# ---- Phase 6 ----
VAPID_PUBLIC_KEY=
VAPID_PRIVATE_KEY=
VAPID_SUBJECT=
# ---- Phase 7 ----
HAPI_BASE_URL=http://hapi:8080/fhir
OAH_IG_VERSION=
TX_SERVER_URL=
SNOMED_LICENCE_ACCEPTED=
# ---- Phase 10 ----
NEXT_PUBLIC_API_BASE_URL=
NEXT_PUBLIC_MAPTILER_KEY=
NEXT_PUBLIC_VAPID_PUBLIC_KEY=
# ---- Phase 12 ----
DEPLOY_HOST=
DEPLOY_SSH_KEY_PATH=
PUBLIC_BASE_URL=
```

- [ ] **Step 5: Write the `Makefile`**

```makefile
up:        ; docker compose up -d
down:      ; docker compose down
migrate:   ; docker compose run --rm api alembic -c db/alembic.ini upgrade head
test:      ; docker compose run --rm api pytest -q
compile:   ; docker compose run --rm kernel python -m upstream_kernel.compile.cli
tables:    ; docker compose run --rm kernel python -m upstream_kernel.physics.cli
sim:       ; docker compose run --rm api python -m upstream_sim.run --scenarios 50
bench:     ; docker compose run --rm api python -m benchmarks.runner --out bench/results
validate:  ; ./fhir/scripts/validate.sh
demo:      ; docker compose run --rm api python -m upstream_sim.demo_scenario
```

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "chore: repository skeleton, pinned workspace, env template"
```

---

### Task 0.2: Docker Compose — the six containers

**Files:**
- Create: `docker-compose.yml`, `docker/Dockerfile.python`, `docker/postgres/init/00-extensions.sql`

**Interfaces:**
- Produces: service names `db`, `api`, `kernel`, `clinical`, `hapi`, `web`, `minio`. Every later phase's `docker compose exec <svc>` command assumes these names.

- [ ] **Step 1: Write the Postgres init script**

```sql
-- docker/postgres/init/00-extensions.sql
CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pgrouting;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- GC-7 health-data boundary: a physically separate database with its own owner.
CREATE ROLE clinical_role LOGIN PASSWORD 'set-from-env';
CREATE DATABASE clinical OWNER clinical_role;
REVOKE CONNECT ON DATABASE clinical FROM PUBLIC;

-- HAPI gets its own database; the FHIR store is a rebuildable view (GC-2).
CREATE ROLE hapi_role LOGIN PASSWORD 'set-from-env';
CREATE DATABASE hapi OWNER hapi_role;
```

> After first boot, rotate both placeholder passwords to the values in `.env` with
> `ALTER ROLE clinical_role PASSWORD '...'` — the init script runs before `.env` interpolation.

- [ ] **Step 2: Write `docker/Dockerfile.python`**

```dockerfile
FROM python:3.12-slim
ARG SERVICE
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential libpq-dev gdal-bin libgdal-dev curl && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.5.0 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY packages ./packages
COPY services ./services
COPY db ./db
RUN uv sync --frozen --package "$SERVICE"
ENV PATH="/app/.venv/bin:$PATH" PYTHONPATH=/app
```

- [ ] **Step 3: Write `docker-compose.yml`**

```yaml
name: upstream
services:
  db:
    image: timescale/timescaledb-ha:pg17
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./docker/postgres/init:/docker-entrypoint-initdb.d:ro
    ports: ["5432:5432"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
      interval: 5s
      retries: 20

  api:
    build: { context: ., dockerfile: docker/Dockerfile.python, args: { SERVICE: core-api } }
    command: uvicorn upstream_api.main:app --host 0.0.0.0 --port 8000
    environment:
      DATABASE_URL: ${DATABASE_URL}
      CATCHMENT_ID: ${CATCHMENT_ID}
      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY}
      HAPI_BASE_URL: ${HAPI_BASE_URL}
      MEDIA_S3_ENDPOINT: ${MEDIA_S3_ENDPOINT}
      MEDIA_S3_BUCKET: ${MEDIA_S3_BUCKET}
      MEDIA_S3_ACCESS_KEY: ${MEDIA_S3_ACCESS_KEY}
      MEDIA_S3_SECRET_KEY: ${MEDIA_S3_SECRET_KEY}
      VAPID_PUBLIC_KEY: ${VAPID_PUBLIC_KEY}
      VAPID_PRIVATE_KEY: ${VAPID_PRIVATE_KEY}
      VAPID_SUBJECT: ${VAPID_SUBJECT}
      OPEN_METEO_BASE_URL: ${OPEN_METEO_BASE_URL}
    depends_on: { db: { condition: service_healthy } }
    volumes: ["./data:/app/data"]
    ports: ["8000:8000"]

  kernel:
    build: { context: ., dockerfile: docker/Dockerfile.python, args: { SERVICE: kernel } }
    command: python -m upstream_kernel.worker
    environment:
      KERNEL_DATABASE_URL: ${KERNEL_DATABASE_URL}
      JAX_PLATFORMS: cpu
      JAX_ENABLE_X64: "1"                          # GC-6 determinism + numeric headroom
      XLA_FLAGS: "--xla_cpu_enable_fast_math=false"
    depends_on: { db: { condition: service_healthy } }
    volumes: ["./data:/app/data"]

  clinical:
    build: { context: ., dockerfile: docker/Dockerfile.python, args: { SERVICE: clinical-stats } }
    command: uvicorn clinical_stats.main:app --host 0.0.0.0 --port 8100
    environment:
      CLINICAL_DATABASE_URL: ${CLINICAL_DATABASE_URL}
      EPISODE_API_BASE_URL: http://api:8000
    depends_on: { db: { condition: service_healthy } }
    ports: ["8100:8100"]

  hapi:
    image: hapiproject/hapi:v7.4.0
    environment:
      SPRING_DATASOURCE_URL: jdbc:postgresql://db:5432/hapi
      SPRING_DATASOURCE_USERNAME: hapi_role
      SPRING_DATASOURCE_PASSWORD: ${POSTGRES_PASSWORD}
      SPRING_DATASOURCE_DRIVERCLASSNAME: org.postgresql.Driver
      SPRING_JPA_PROPERTIES_HIBERNATE_DIALECT: ca.uhn.fhir.jpa.model.dialect.HapiFhirPostgres94Dialect
      HAPI_FHIR_FHIR_VERSION: R4
      HAPI_FHIR_VALIDATION_REQUESTS_ENABLED: "true"
      HAPI_FHIR_SUBSCRIPTION_RESTHOOK_ENABLED: "true"
      HAPI_FHIR_IMPLEMENTATIONGUIDES_OAH_NAME: hl7.eu.fhir.oah
      HAPI_FHIR_IMPLEMENTATIONGUIDES_OAH_VERSION: ${OAH_IG_VERSION}
    depends_on: { db: { condition: service_healthy } }
    ports: ["8080:8080"]

  minio:
    image: minio/minio:RELEASE.2024-10-13T13-34-11Z
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: ${MEDIA_S3_ACCESS_KEY}
      MINIO_ROOT_PASSWORD: ${MEDIA_S3_SECRET_KEY}
    volumes: ["miniodata:/data"]
    ports: ["9000:9000", "9001:9001"]

  web:
    build: { context: ./web, dockerfile: ../docker/Dockerfile.web }
    environment:
      NEXT_PUBLIC_API_BASE_URL: ${NEXT_PUBLIC_API_BASE_URL}
      NEXT_PUBLIC_MAPTILER_KEY: ${NEXT_PUBLIC_MAPTILER_KEY}
      NEXT_PUBLIC_VAPID_PUBLIC_KEY: ${VAPID_PUBLIC_KEY}
    depends_on: [api]
    ports: ["3000:3000"]

volumes: { pgdata: {}, miniodata: {} }
```

- [ ] **Step 4: Bring the stack up and verify extensions**

```bash
cp .env.example .env    # fill POSTGRES_PASSWORD and the two MinIO values
docker compose up -d db hapi minio
docker compose exec db psql -U upstream -d upstream -c "SELECT extname FROM pg_extension ORDER BY 1;"
```

Expected: rows include `postgis`, `pgrouting`, `timescaledb`.

- [ ] **Step 5: Commit**

```bash
git add docker-compose.yml docker/ && git commit -m "feat: six-container stack (timescale/postgis/pgrouting, hapi, minio)"
```

---

### Task 0.3: Event log migration and the ordering-safe append function

The single most load-bearing piece of infrastructure in the project (PRD §12.2). The advisory lock is **not** optional — without it a consumer silently skips events forever.

**Files:**
- Create: `db/alembic.ini`, `db/migrations/env.py`, `db/migrations/versions/0001_event_log.py`
- Create: `services/core-api/tests/conftest.py`
- Test: `services/core-api/tests/test_event_log.py`

**Interfaces:**
- Produces: SQL function `append_event(uuid, text, text, text, int, timestamptz, jsonb, uuid, uuid) RETURNS bigint`; tables `events`, `consumer_positions`; roles `app_role`, `kernel_role`.

- [ ] **Step 1: Write the test fixtures**

```python
# services/core-api/tests/conftest.py
import os, pytest, psycopg

@pytest.fixture
def db_conn_factory():
    made = []
    def _make():
        c = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)
        made.append(c)
        return c
    yield _make
    for c in made:
        c.close()

@pytest.fixture
def db_conn(db_conn_factory):
    return db_conn_factory()
```

- [ ] **Step 2: Write the failing test**

```python
# services/core-api/tests/test_event_log.py
import uuid, datetime as dt, threading
import pytest, psycopg
from psycopg.types.json import Json

pytestmark = pytest.mark.integration

def _append(conn, *, payload, commit=True):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT append_event(%s,'live','catch-1','EvidenceRecorded',1,%s,%s,NULL,NULL)",
            (uuid.uuid4(), dt.datetime.now(dt.UTC), Json(payload)),
        )
        seq = cur.fetchone()[0]
    if commit and not conn.autocommit:
        conn.commit()
    return seq

def test_append_event_returns_monotonic_seq(db_conn):
    seqs = [_append(db_conn, payload={"i": i}) for i in range(3)]
    assert seqs == sorted(seqs) and len(set(seqs)) == 3

def test_events_are_append_only(db_conn):
    seq = _append(db_conn, payload={"x": 1})
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with db_conn.cursor() as cur:
            cur.execute("SET ROLE app_role")
            cur.execute("UPDATE events SET payload='{}'::jsonb WHERE seq=%s", (seq,))

def test_commit_order_matches_seq_order(db_conn_factory):
    """PRD 12.2 ordering rule: a slow txn must not commit after a later one."""
    a, b = db_conn_factory(), db_conn_factory()
    a.autocommit = False
    result = {}
    seq_a = _append(a, payload={"who": "a"}, commit=False)
    t = threading.Thread(target=lambda: result.update(seq_b=_append(b, payload={"who": "b"})))
    t.start()
    t.join(timeout=2)
    assert "seq_b" not in result, "b should be blocked on the advisory lock"
    a.commit()
    t.join(timeout=10)
    assert result["seq_b"] > seq_a
```

- [ ] **Step 3: Run it and confirm it fails**

```bash
docker compose run --rm api pytest services/core-api/tests/test_event_log.py -v
```

Expected: FAIL — `UndefinedFunction: function append_event(...) does not exist`.

- [ ] **Step 4: Write migration 0001**

```python
# db/migrations/versions/0001_event_log.py
"""event log, consumer positions, append_event"""
from alembic import op

revision, down_revision = "0001", None

def upgrade():
    op.execute("""
    CREATE TABLE events (
      seq            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      event_id       UUID        NOT NULL UNIQUE,
      stream         TEXT        NOT NULL CHECK (stream IN ('live','sim')),
      catchment_id   TEXT        NOT NULL,
      event_type     TEXT        NOT NULL,
      schema_version INT         NOT NULL,
      event_time     TIMESTAMPTZ NOT NULL,
      recorded_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
      payload        JSONB       NOT NULL,
      causation_id   UUID,
      correlation_id UUID
    );
    CREATE INDEX events_catchment_seq_idx ON events (catchment_id, stream, seq);
    CREATE INDEX events_type_time_idx     ON events (event_type, event_time DESC);
    CREATE INDEX events_recorded_idx      ON events (recorded_at DESC);

    CREATE TABLE consumer_positions (
      consumer   TEXT PRIMARY KEY,
      last_seq   BIGINT NOT NULL DEFAULT 0,
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );

    CREATE FUNCTION append_event(p_event_id UUID, p_stream TEXT, p_catchment TEXT,
                                 p_type TEXT, p_version INT, p_event_time TIMESTAMPTZ,
                                 p_payload JSONB, p_causation UUID, p_correlation UUID)
    RETURNS BIGINT LANGUAGE plpgsql AS $$
    DECLARE new_seq BIGINT;
    BEGIN
      PERFORM pg_advisory_xact_lock(424242);
      INSERT INTO events (event_id, stream, catchment_id, event_type, schema_version,
                          event_time, payload, causation_id, correlation_id)
      VALUES (p_event_id, p_stream, p_catchment, p_type, p_version,
              p_event_time, p_payload, p_causation, p_correlation)
      RETURNING seq INTO new_seq;
      PERFORM pg_notify('events', p_catchment);
      RETURN new_seq;
    END $$;

    DO $$ BEGIN CREATE ROLE app_role;    EXCEPTION WHEN duplicate_object THEN NULL; END $$;
    DO $$ BEGIN CREATE ROLE kernel_role; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
    GRANT SELECT, INSERT ON events TO app_role, kernel_role;
    REVOKE UPDATE, DELETE ON events FROM app_role, kernel_role;
    GRANT USAGE, SELECT ON SEQUENCE events_seq_seq TO app_role, kernel_role;
    GRANT EXECUTE ON FUNCTION append_event TO app_role, kernel_role;
    GRANT SELECT, INSERT, UPDATE ON consumer_positions TO app_role, kernel_role;
    """)

def downgrade():
    op.execute("DROP FUNCTION append_event; DROP TABLE consumer_positions; DROP TABLE events;")
```

- [ ] **Step 5: Migrate and re-run the tests**

```bash
docker compose run --rm api alembic -c db/alembic.ini upgrade head
docker compose run --rm api pytest services/core-api/tests/test_event_log.py -v
```

Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add db/ services/core-api/tests/
git commit -m "feat(db): append-only event log with commit-order-safe append_event"
```

---

### Task 0.4: Domain tables — network, time series, read models, ground-truth isolation

**Files:**
- Create: `db/migrations/versions/0002_domain_tables.py`
- Test: `services/core-api/tests/test_schema.py`

**Interfaces:**
- Produces: tables `network_nodes`, `network_edges`, `outfalls`, `receptor_zones`, `footpath_edges`, `sensor_readings`, `rainfall`, `posterior_snapshots`, `episodes`, `missions`, `volunteers`, schema `sim_truth`. Column names here are referenced verbatim by Phases 1–11.

- [ ] **Step 1: Write the failing test**

```python
# services/core-api/tests/test_schema.py
import pytest
pytestmark = pytest.mark.integration

EXPECTED = {"events","consumer_positions","network_nodes","network_edges","outfalls",
            "receptor_zones","sensor_readings","rainfall","posterior_snapshots",
            "episodes","missions","volunteers","footpath_edges"}

def test_all_domain_tables_exist(db_conn):
    with db_conn.cursor() as cur:
        cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")
        assert EXPECTED <= {r[0] for r in cur.fetchall()}

def test_hypertables_registered(db_conn):
    with db_conn.cursor() as cur:
        cur.execute("SELECT hypertable_name FROM timescaledb_information.hypertables")
        assert {"sensor_readings","rainfall","posterior_snapshots"} <= {r[0] for r in cur.fetchall()}

def test_kernel_role_cannot_read_ground_truth(db_conn):
    """GC-10: the kernel must not be able to see simulator ground truth."""
    with db_conn.cursor() as cur:
        cur.execute("SELECT has_schema_privilege('kernel_role','sim_truth','USAGE')")
        assert cur.fetchone()[0] is False

def test_kernel_role_cannot_write_episodes(db_conn):
    """PRD 10.3: the kernel never changes episode state."""
    with db_conn.cursor() as cur:
        cur.execute("SELECT has_table_privilege('kernel_role','episodes','INSERT')")
        assert cur.fetchone()[0] is False
```

- [ ] **Step 2: Run to verify failure**

```bash
docker compose run --rm api pytest services/core-api/tests/test_schema.py -v
```

Expected: FAIL — tables missing.

- [ ] **Step 3: Write migration 0002**

```python
# db/migrations/versions/0002_domain_tables.py
from alembic import op
revision, down_revision = "0002", "0001"

def upgrade():
    op.execute("""
    CREATE TABLE network_nodes (
      network_version TEXT NOT NULL, node_id TEXT NOT NULL,
      node_type TEXT NOT NULL,                      -- junction|outfall|reach_point|gauge
      geom GEOMETRY(Point,4326) NOT NULL, catchment_id TEXT NOT NULL,
      attrs JSONB NOT NULL DEFAULT '{}'::jsonb,
      PRIMARY KEY (network_version, node_id));
    CREATE INDEX network_nodes_geom_idx ON network_nodes USING GIST (geom);

    CREATE TABLE network_edges (
      network_version TEXT NOT NULL, edge_id TEXT NOT NULL,
      from_node TEXT NOT NULL, to_node TEXT NOT NULL,
      length_m DOUBLE PRECISION NOT NULL, slope DOUBLE PRECISION,
      mean_flow_m3s DOUBLE PRECISION NOT NULL DEFAULT 0.05,
      geom GEOMETRY(LineString,4326) NOT NULL,
      PRIMARY KEY (network_version, edge_id));
    CREATE INDEX network_edges_geom_idx ON network_edges USING GIST (geom);

    CREATE TABLE outfalls (
      network_version TEXT NOT NULL, outfall_id TEXT NOT NULL, node_id TEXT NOT NULL,
      source_type TEXT NOT NULL,                    -- cso|storm_outfall|industrial|misconnection|unknown
      base_rate DOUBLE PRECISION NOT NULL DEFAULT 0.001,
      is_synthetic BOOLEAN NOT NULL DEFAULT FALSE,  -- PRD R2: label synthetic elements
      attrs JSONB NOT NULL DEFAULT '{}'::jsonb,
      PRIMARY KEY (network_version, outfall_id));

    CREATE TABLE receptor_zones (
      network_version TEXT NOT NULL, zone_id TEXT NOT NULL, node_id TEXT NOT NULL,
      name TEXT NOT NULL,
      pathways TEXT[] NOT NULL DEFAULT '{}',        -- recreation|animal_contact|floodwater|irrigation
      population_upper_bound INT,
      geom GEOMETRY(Polygon,4326) NOT NULL,
      PRIMARY KEY (network_version, zone_id));
    CREATE INDEX receptor_zones_geom_idx ON receptor_zones USING GIST (geom);

    CREATE TABLE footpath_edges (
      id BIGSERIAL PRIMARY KEY, source BIGINT, target BIGINT,
      cost DOUBLE PRECISION, reverse_cost DOUBLE PRECISION,
      geom GEOMETRY(LineString,4326));
    CREATE INDEX footpath_edges_geom_idx ON footpath_edges USING GIST (geom);
    CREATE INDEX footpath_edges_source_idx ON footpath_edges (source);
    CREATE INDEX footpath_edges_target_idx ON footpath_edges (target);

    CREATE TABLE sensor_readings (
      ts TIMESTAMPTZ NOT NULL, sensor_id TEXT NOT NULL, node_id TEXT NOT NULL,
      catchment_id TEXT NOT NULL, stream TEXT NOT NULL DEFAULT 'live',
      parameter TEXT NOT NULL, value DOUBLE PRECISION NOT NULL, unit TEXT NOT NULL);
    SELECT create_hypertable('sensor_readings','ts');
    ALTER TABLE sensor_readings SET (timescaledb.compress,
      timescaledb.compress_segmentby='sensor_id,parameter');
    SELECT add_compression_policy('sensor_readings', INTERVAL '7 days');

    CREATE TABLE rainfall (
      ts TIMESTAMPTZ NOT NULL, catchment_id TEXT NOT NULL, stream TEXT NOT NULL DEFAULT 'live',
      mm_per_h DOUBLE PRECISION NOT NULL, antecedent_dry_h DOUBLE PRECISION,
      flow_condition TEXT NOT NULL);                -- dry|wet|storm
    SELECT create_hypertable('rainfall','ts');

    CREATE TABLE posterior_snapshots (
      ts TIMESTAMPTZ NOT NULL, fingerprint TEXT NOT NULL,
      episode_id TEXT, catchment_id TEXT NOT NULL, stream TEXT NOT NULL,
      as_of_seq BIGINT NOT NULL,
      network_version TEXT NOT NULL, kernel_version TEXT NOT NULL, params_version TEXT NOT NULL,
      p_event DOUBLE PRECISION NOT NULL,
      source_marginals JSONB NOT NULL, zone_windows JSONB NOT NULL,
      probe_candidates JSONB NOT NULL, explanation JSONB NOT NULL DEFAULT '{}'::jsonb);
    SELECT create_hypertable('posterior_snapshots','ts');
    CREATE INDEX posterior_snapshots_replay_idx ON posterior_snapshots (catchment_id, ts DESC);
    CREATE INDEX posterior_snapshots_fp_idx ON posterior_snapshots (fingerprint);

    CREATE TABLE episodes (
      episode_id TEXT PRIMARY KEY, catchment_id TEXT NOT NULL, stream TEXT NOT NULL,
      state TEXT NOT NULL, opened_at TIMESTAMPTZ NOT NULL,
      state_changed_at TIMESTAMPTZ NOT NULL,
      est_start_lo TIMESTAMPTZ, est_start_hi TIMESTAMPTZ,
      clinical_window_end TIMESTAMPTZ,
      latest_fingerprint TEXT, version INT NOT NULL DEFAULT 1,
      fhir_risk_assessment_id TEXT,
      summary JSONB NOT NULL DEFAULT '{}'::jsonb);

    CREATE TABLE volunteers (
      volunteer_id TEXT PRIMARY KEY, display_name TEXT,
      coarse_area GEOMETRY(Polygon,4326),           -- PRD 14.2: area, never live location
      available_from TIMESTAMPTZ, available_to TIMESTAMPTZ,
      reliability DOUBLE PRECISION NOT NULL DEFAULT 0.7,
      push_subscription JSONB);

    CREATE TABLE missions (
      mission_id TEXT PRIMARY KEY,
      episode_id TEXT NOT NULL REFERENCES episodes(episode_id),
      node_id TEXT NOT NULL, window_start TIMESTAMPTZ NOT NULL, window_end TIMESTAMPTZ NOT NULL,
      methods TEXT[] NOT NULL, mode TEXT NOT NULL,
      assignee_id TEXT, assignee_type TEXT, status TEXT NOT NULL,
      expected_gain DOUBLE PRECISION NOT NULL, realised_gain DOUBLE PRECISION,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now());

    CREATE SCHEMA sim_truth;
    CREATE TABLE sim_truth.injected_events (
      run_id TEXT NOT NULL, scenario_id TEXT NOT NULL,
      true_entry_node TEXT NOT NULL, true_start TIMESTAMPTZ NOT NULL,
      true_duration_s INT NOT NULL, true_mass DOUBLE PRECISION NOT NULL,
      contaminant TEXT NOT NULL, flow_condition TEXT NOT NULL,
      true_zone_arrivals JSONB NOT NULL,
      PRIMARY KEY (run_id, scenario_id));
    REVOKE ALL ON SCHEMA sim_truth FROM PUBLIC;
    REVOKE ALL ON ALL TABLES IN SCHEMA sim_truth FROM PUBLIC;
    REVOKE ALL ON SCHEMA sim_truth FROM kernel_role;

    GRANT SELECT, INSERT, UPDATE ON episodes, missions, volunteers TO app_role;
    GRANT SELECT, INSERT ON sensor_readings, rainfall TO app_role;
    GRANT SELECT, INSERT, UPDATE, DELETE ON network_nodes, network_edges, outfalls,
          receptor_zones, footpath_edges TO app_role;
    GRANT SELECT ON network_nodes, network_edges, outfalls, receptor_zones,
          sensor_readings, rainfall, episodes, missions TO kernel_role;
    GRANT SELECT, INSERT ON posterior_snapshots TO kernel_role;
    """)

def downgrade():
    op.execute("DROP SCHEMA sim_truth CASCADE;")
    for t in ["missions","volunteers","episodes","posterior_snapshots","rainfall",
              "sensor_readings","footpath_edges","receptor_zones","outfalls",
              "network_edges","network_nodes"]:
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE;")
```

- [ ] **Step 4: Migrate and run tests**

```bash
docker compose run --rm api alembic -c db/alembic.ini upgrade head
docker compose run --rm api pytest services/core-api/tests/test_schema.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add db/ services/core-api/tests/test_schema.py
git commit -m "feat(db): network, timeseries, read models, isolated sim_truth schema"
```

---

### Task 0.5: Shared Pydantic schemas and CI

**Files:**
- Create: `packages/upstream-shared/upstream_shared/{codes.py,evidence.py,events.py,episode.py,mission.py}`
- Create: `.github/workflows/ci.yml`
- Test: `packages/upstream-shared/tests/test_schemas.py`

**Interfaces:**
- Produces: `EventEnvelope`, `EventType`, `EvidencePayload`, `ObservationResult`, `RetractionPayload`, `EpisodeState`, `THRESHOLD_SUSPECTED/PROBABLE/REFUTED`, `ObservationMethod`, `ExposurePathway`, `SourceType`, `PathogenClass`, `INCUBATION_DAYS`, `SEWAGE_PATHOGEN_MIX`, `CLINICAL_RELEVANCE_DAYS`, `MissionSpec`, `MissionStatus`, `ProbeMode`. Phases 3–11 import these names verbatim.

- [ ] **Step 1: Write the failing test**

```python
# packages/upstream-shared/tests/test_schemas.py
import datetime as dt, pytest
from pydantic import ValidationError
from upstream_shared.evidence import EvidencePayload, ObservationResult
from upstream_shared.events import EventEnvelope, EventType
from upstream_shared.episode import EpisodeState

def test_evidence_payload_roundtrip():
    p = EvidencePayload(node_id="J4", method="citizen_visual_olfactory",
                        result=ObservationResult.NEGATIVE, observer_id="vol-1182",
                        observer_type="citizen", snap_distance_m=12.5,
                        oah_codes=["OAH-IND-001"], ai_assisted=True, confirmed_by_observer=True)
    assert EvidencePayload.model_validate(p.model_dump()) == p

def test_ai_assisted_requires_confirmation():
    """GC-8: AI-assisted evidence is unusable until the observer confirms."""
    with pytest.raises(ValidationError):
        EvidencePayload(node_id="J4", method="citizen_freetext",
                        result=ObservationResult.POSITIVE, observer_id="v1",
                        observer_type="citizen", snap_distance_m=1.0,
                        ai_assisted=True, confirmed_by_observer=False)

def test_quantitative_result_requires_value_and_unit():
    with pytest.raises(ValidationError):
        EvidencePayload(node_id="J4", method="lab_ecoli",
                        result=ObservationResult.QUANTITATIVE, observer_id="lab-1",
                        observer_type="lab", snap_distance_m=0.0)

def test_envelope_rejects_future_event_time():
    with pytest.raises(ValidationError):
        EventEnvelope(stream="live", catchment_id="c1",
                      event_type=EventType.EVIDENCE_RECORDED, schema_version=1,
                      event_time=dt.datetime.now(dt.UTC) + dt.timedelta(hours=2), payload={})

def test_episode_state_transitions_match_prd():
    assert EpisodeState.SUSPECTED.can_transition_to(EpisodeState.PROBABLE)
    assert EpisodeState.SUSPECTED.can_transition_to(EpisodeState.REFUTED)
    assert not EpisodeState.SUSPECTED.can_transition_to(EpisodeState.CONFIRMED)
    assert not EpisodeState.RESOLVED.can_transition_to(EpisodeState.PROBABLE)
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest packages/upstream-shared/tests/test_schemas.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'upstream_shared'`.

- [ ] **Step 3: Implement `codes.py`**

```python
# packages/upstream-shared/upstream_shared/codes.py
from enum import StrEnum

LOCAL_CS = "https://upstream-onehealth.example/CodeSystem"

class SourceType(StrEnum):
    CSO = "cso"; STORM_OUTFALL = "storm_outfall"; INDUSTRIAL = "industrial"
    MISCONNECTION = "misconnection"; DIFFUSE_RUNOFF = "diffuse_runoff"; UNKNOWN = "unknown"

class ExposurePathway(StrEnum):
    RECREATION = "recreation"; ANIMAL_CONTACT = "animal_contact"
    FLOODWATER = "floodwater"; IRRIGATION = "irrigation"

class ObservationMethod(StrEnum):
    CITIZEN_VISUAL_OLFACTORY = "citizen_visual_olfactory"
    CITIZEN_FREETEXT = "citizen_freetext"
    CITIZEN_PHOTO = "citizen_photo"
    TEST_STRIP = "test_strip"
    SENSOR_TURBIDITY = "sensor_turbidity"
    SENSOR_CONDUCTIVITY = "sensor_conductivity"
    SENSOR_NORMAL_WINDOW = "sensor_normal_window"
    FIELD_TEST = "field_test"
    LAB_ECOLI = "lab_ecoli"
    LAB_ENTEROCOCCI = "lab_enterococci"
    OVERFLOW_TELEMETRY = "overflow_telemetry"
    BIOASSESSMENT = "bioassessment"

class PathogenClass(StrEnum):
    NOROVIRUS = "norovirus"; CAMPYLOBACTER = "campylobacter"; STEC = "stec"
    CRYPTOSPORIDIUM = "cryptosporidium"; GIARDIA = "giardia"; LEPTOSPIRA = "leptospira"

# PRD 7.6 incubation table -> (mean_days, sd_days) for a gamma fit.
INCUBATION_DAYS: dict[PathogenClass, tuple[float, float]] = {
    PathogenClass.NOROVIRUS: (1.25, 0.5),
    PathogenClass.CAMPYLOBACTER: (3.0, 1.0),
    PathogenClass.STEC: (3.5, 1.5),
    PathogenClass.CRYPTOSPORIDIUM: (7.0, 2.0),
    PathogenClass.GIARDIA: (10.5, 3.0),
    PathogenClass.LEPTOSPIRA: (9.5, 4.0),
}
SEWAGE_PATHOGEN_MIX: dict[PathogenClass, float] = {
    PathogenClass.NOROVIRUS: 0.35, PathogenClass.CAMPYLOBACTER: 0.25,
    PathogenClass.STEC: 0.10, PathogenClass.CRYPTOSPORIDIUM: 0.15,
    PathogenClass.GIARDIA: 0.15,
}
FLOODWATER_PATHOGEN_MIX: dict[PathogenClass, float] = {
    PathogenClass.LEPTOSPIRA: 0.4, PathogenClass.NOROVIRUS: 0.3,
    PathogenClass.CAMPYLOBACTER: 0.3,
}
CLINICAL_RELEVANCE_DAYS = 16          # PRD 6.1 "until about 16 days after exposure"
SYNDROME_SET = ["acute_gastroenteritis", "fever_after_floodwater_contact"]
```

- [ ] **Step 4: Implement `evidence.py`**

```python
# packages/upstream-shared/upstream_shared/evidence.py
from enum import StrEnum
from pydantic import BaseModel, Field, model_validator
from .codes import ObservationMethod

class ObservationResult(StrEnum):
    POSITIVE = "positive"; NEGATIVE = "negative"; QUANTITATIVE = "quantitative"

class EvidencePayload(BaseModel):
    node_id: str
    method: ObservationMethod
    result: ObservationResult
    value: float | None = None
    unit: str | None = None                       # UCUM (GC-13)
    observer_id: str
    observer_type: str                            # citizen|officer|sensor|lab
    snap_distance_m: float = Field(ge=0)
    oah_codes: list[str] = Field(default_factory=list)
    ai_assisted: bool = False
    confirmed_by_observer: bool = False
    photo_uri: str | None = None
    mission_id: str | None = None
    window_start: str | None = None               # sensor "normal for this window" evidence
    window_end: str | None = None

    @model_validator(mode="after")
    def _rules(self):
        if self.ai_assisted and not self.confirmed_by_observer:
            raise ValueError("GC-8: AI-assisted evidence requires observer confirmation")
        if self.result is ObservationResult.QUANTITATIVE and (self.value is None or not self.unit):
            raise ValueError("quantitative results need value and a UCUM unit")
        return self

class RetractionPayload(BaseModel):
    retracts_event_id: str
    reason: str
    retracted_by: str
```

- [ ] **Step 5: Implement `events.py`, `episode.py`, `mission.py`**

```python
# packages/upstream-shared/upstream_shared/events.py
import datetime as dt, uuid
from enum import StrEnum
from pydantic import BaseModel, Field, field_validator

class EventType(StrEnum):
    EVIDENCE_RECORDED = "EvidenceRecorded"
    EVIDENCE_RETRACTED = "EvidenceRetracted"
    RAINFALL_OBSERVED = "RainfallObserved"
    OVERFLOW_ACTIVATED = "OverflowActivated"
    POSTERIOR_COMPUTED = "PosteriorComputed"
    EPISODE_OPENED = "EpisodeOpened"
    EPISODE_STATE_CHANGED = "EpisodeStateChanged"
    SIGN_OFF_REQUESTED = "SignOffRequested"
    SIGN_OFF_GIVEN = "SignOffGiven"
    MISSION_CREATED = "MissionCreated"
    MISSION_ACCEPTED = "MissionAccepted"
    MISSION_COMPLETED = "MissionCompleted"
    MISSION_EXPIRED = "MissionExpired"
    FHIR_PUBLISHED = "FhirPublished"
    CLINICAL_TEST_RESULT = "ClinicalTestResult"
    UPSTREAM_SEARCH_REQUESTED = "UpstreamSearchRequested"
    NETWORK_VERSION_PUBLISHED = "NetworkVersionPublished"
    PARAMETERS_VERSION_PUBLISHED = "ParametersVersionPublished"

MAX_CLOCK_SKEW = dt.timedelta(minutes=5)

class EventEnvelope(BaseModel):
    event_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    stream: str
    catchment_id: str
    event_type: EventType
    schema_version: int = 1
    event_time: dt.datetime                       # GC-4
    payload: dict
    causation_id: uuid.UUID | None = None
    correlation_id: uuid.UUID | None = None

    @field_validator("event_time")
    @classmethod
    def _not_future(cls, v: dt.datetime) -> dt.datetime:
        if v.tzinfo is None:
            raise ValueError("event_time must be timezone-aware")
        if v > dt.datetime.now(dt.UTC) + MAX_CLOCK_SKEW:
            raise ValueError("event_time is in the future (FR-5 plausibility check)")
        return v

    @field_validator("stream")
    @classmethod
    def _known_stream(cls, v: str) -> str:
        if v not in ("live", "sim"):
            raise ValueError("stream must be 'live' or 'sim'")
        return v
```

```python
# packages/upstream-shared/upstream_shared/episode.py
from enum import StrEnum

class EpisodeState(StrEnum):
    SUSPECTED = "SUSPECTED"; PROBABLE = "PROBABLE"; CONFIRMED = "CONFIRMED"
    REFUTED = "REFUTED"; RESOLVED = "RESOLVED"
    def can_transition_to(self, other: "EpisodeState") -> bool:
        return other in _ALLOWED[self]

# PRD 6.3 state diagram, exactly.
_ALLOWED: dict[EpisodeState, set[EpisodeState]] = {
    EpisodeState.SUSPECTED: {EpisodeState.PROBABLE, EpisodeState.REFUTED},
    EpisodeState.PROBABLE:  {EpisodeState.CONFIRMED, EpisodeState.REFUTED, EpisodeState.RESOLVED},
    EpisodeState.CONFIRMED: {EpisodeState.RESOLVED},
    EpisodeState.RESOLVED:  set(),
    EpisodeState.REFUTED:   set(),
}

THRESHOLD_SUSPECTED = 0.50   # PRD 6.3, configurable; tuned in Phase 9
THRESHOLD_PROBABLE  = 0.90
THRESHOLD_REFUTED   = 0.10
```

```python
# packages/upstream-shared/upstream_shared/mission.py
import datetime as dt
from enum import StrEnum
from pydantic import BaseModel
from .codes import ObservationMethod

class MissionStatus(StrEnum):
    CREATED = "created"; ACCEPTED = "accepted"; COMPLETED = "completed"
    EXPIRED = "expired"; DECLINED = "declined"

class ProbeMode(StrEnum):
    PROTECT = "protect"; ENFORCE = "enforce"

class MissionSpec(BaseModel):
    mission_id: str
    episode_id: str
    node_id: str
    window_start: dt.datetime
    window_end: dt.datetime
    methods: list[ObservationMethod]
    mode: ProbeMode
    expected_gain: float
    human_summary: str            # "Check Junction J4 between 02:22 and 02:39"
```

- [ ] **Step 6: Run the tests**

```bash
pytest packages/upstream-shared/tests/test_schemas.py -v
```

Expected: 5 passed.

- [ ] **Step 7: Write the CI workflow**

```yaml
# .github/workflows/ci.yml
name: ci
on: [push, pull_request]
jobs:
  python:
    runs-on: ubuntu-latest
    services:
      db:
        image: timescale/timescaledb-ha:pg17
        env: { POSTGRES_USER: upstream, POSTGRES_PASSWORD: upstream, POSTGRES_DB: upstream }
        ports: ["5432:5432"]
        options: >-
          --health-cmd "pg_isready -U upstream" --health-interval 5s --health-retries 20
    env:
      DATABASE_URL: postgresql://upstream:upstream@localhost:5432/upstream
      JAX_PLATFORMS: cpu
      JAX_ENABLE_X64: "1"
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync --all-packages
      - run: uv run ruff check .
      - run: uv run alembic -c db/alembic.ini upgrade head
      - run: uv run pytest -q
  # `fhir` job added in Phase 7; `bench` job added in Phase 9.
```

- [ ] **Step 8: Commit**

```bash
git add packages/ .github/
git commit -m "feat(shared): event/evidence/episode/mission schemas; CI pipeline"
```

## Phase 0 exit criteria

- `make up && make migrate` succeeds from a clean checkout.
- `pytest -q` green: event-log ordering under concurrency, append-only enforcement, all domain tables + hypertables present, `sim_truth` unreadable by `kernel_role`, `episodes` unwritable by `kernel_role`, all shared-schema validation rules.
- CI green on first push.

## 🔑 Credentials needed at the end of Phase 0

| Variable | What it is | Where it comes from |
|---|---|---|
| `POSTGRES_PASSWORD` | Password for the `upstream` Postgres role | **You choose it** — any strong random string |
| `DATABASE_URL` | `postgresql://upstream:<pw>@db:5432/upstream` | Derived from the above |
| `KERNEL_DATABASE_URL` | `postgresql://kernel_role:<pw>@db:5432/upstream` | **You choose the `kernel_role` password** |
| `CLINICAL_DATABASE_URL` | `postgresql://clinical_role:<pw>@db:5432/clinical` | **You choose the `clinical_role` password** |
| `CATCHMENT_ID` | Short slug for the pilot catchment, e.g. `coimbra-ribeira` | **You choose it** (resolves PRD open question 1) |

*No third-party API keys are required for Phase 0.*

---

# Phase 1 — Catchment network compiler

**Day 1, midday (≈3 h).** Turns a real OAH pilot catchment into versioned arrays the kernel can multiply. Nothing downstream can be tested without this.

**PRD coverage:** §7.2 "Stream network", §10.4 L9 (network compiler), §12.1 (PostGIS tables), FR-5 (snapping), R2 (label synthetic elements), NetworkVersionPublished event.

## File structure

```
services/kernel/upstream_kernel/compile/
├── __init__.py
├── osm.py          # fetch + clean OSM waterways and footpaths
├── zones.py        # receptor zones from OSM leisure/landuse + curated overrides
├── compiler.py     # graph -> CompiledNetwork arrays + version hash
├── loader.py       # load/save CompiledNetwork to .npz and to PostGIS
└── cli.py          # `python -m upstream_kernel.compile.cli`
data/catchment/
├── catchment.geojson      # catchment boundary polygon (you draw/export this once)
├── outfalls.geojson       # curated outfalls/CSOs; `is_synthetic` per feature
└── zones_overrides.geojson# hand-added receptor zones
```

**Responsibility split:** `osm.py` only talks to the network; `compiler.py` is pure (geodataframes in, arrays out) so it is unit-testable without any I/O; `loader.py` owns persistence.

---

### Task 1.1: `CompiledNetwork` data structure and pure compiler

**Files:**
- Create: `services/kernel/upstream_kernel/compile/compiler.py`
- Test: `services/kernel/tests/test_compiler.py`

**Interfaces:**
- Produces:
  ```python
  @dataclass(frozen=True)
  class CompiledNetwork:
      version: str                     # sha256[:16] of the canonical description
      catchment_id: str
      node_ids: tuple[str, ...]        # index order is THE node order everywhere
      node_index: dict[str, int]
      node_type: np.ndarray            # (N,) int8: 0 junction 1 outfall 2 reach 3 gauge
      lonlat: np.ndarray               # (N,2) float64
      edges: np.ndarray                # (E,2) int32 [from_idx, to_idx]
      edge_length_m: np.ndarray        # (E,) float64
      edge_mean_flow: np.ndarray       # (E,) float64 m3/s at 'dry'
      topo_order: np.ndarray           # (N,) int32, sources first
      downstream_path: dict[int, np.ndarray]   # node -> ordered edge indices to the outlet
      upstream_mask: np.ndarray        # (N,N) bool: upstream_mask[a,b] = a is upstream of b
      entry_nodes: tuple[str, ...]     # candidate contamination entry points
      entry_idx: np.ndarray            # (K,) int32 into node_ids
      entry_source_type: tuple[str,...]
      entry_base_rate: np.ndarray      # (K,) float64 prior base rates
      zone_ids: tuple[str, ...]
      zone_node_idx: np.ndarray        # (Z,) int32
      zone_pathways: tuple[tuple[str,...], ...]
      zone_population: np.ndarray      # (Z,) int32 upper bound
  def compile_network(nodes_gdf, edges_gdf, outfalls_gdf, zones_gdf, catchment_id) -> CompiledNetwork
  ```

- [ ] **Step 1: Write the failing test using a hand-built 6-node toy network**

```python
# services/kernel/tests/test_compiler.py
import numpy as np, pytest
from upstream_kernel.compile.compiler import compile_network
from .fixtures_network import toy_gdfs     # see Step 3

def test_topological_order_puts_sources_first():
    net = compile_network(*toy_gdfs(), catchment_id="toy")
    pos = {n: i for i, n in enumerate(net.topo_order)}
    for e_from, e_to in net.edges:
        assert pos[e_from] < pos[e_to]

def test_upstream_mask_is_transitive():
    net = compile_network(*toy_gdfs(), catchment_id="toy")
    i = net.node_index
    #   O14 -> J9 -> R3 -> ZoneA_node
    assert net.upstream_mask[i["O14"], i["J9"]]
    assert net.upstream_mask[i["O14"], i["R3"]]       # transitive
    assert not net.upstream_mask[i["R3"], i["O14"]]   # not symmetric
    assert not net.upstream_mask[i["O9"], i["O14"]]   # sibling branches

def test_downstream_path_edges_are_contiguous():
    net = compile_network(*toy_gdfs(), catchment_id="toy")
    path = net.downstream_path[net.node_index["O14"]]
    for a, b in zip(path[:-1], path[1:]):
        assert net.edges[a][1] == net.edges[b][0]

def test_version_is_stable_and_content_addressed():
    a = compile_network(*toy_gdfs(), catchment_id="toy")
    b = compile_network(*toy_gdfs(), catchment_id="toy")
    assert a.version == b.version and len(a.version) == 16

def test_version_changes_when_an_edge_length_changes():
    nodes, edges, outfalls, zones = toy_gdfs()
    a = compile_network(nodes, edges, outfalls, zones, catchment_id="toy")
    edges.loc[0, "length_m"] = edges.loc[0, "length_m"] + 1.0
    b = compile_network(nodes, edges, outfalls, zones, catchment_id="toy")
    assert a.version != b.version

def test_cycles_are_rejected():
    nodes, edges, outfalls, zones = toy_gdfs()
    edges.loc[len(edges)] = {"edge_id": "back", "from_node": "R3", "to_node": "O14",
                             "length_m": 10.0, "mean_flow_m3s": 0.01, "geometry": None}
    with pytest.raises(ValueError, match="cycle"):
        compile_network(nodes, edges, outfalls, zones, catchment_id="toy")
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest services/kernel/tests/test_compiler.py -v
```

Expected: FAIL — `ModuleNotFoundError: upstream_kernel.compile.compiler`.

- [ ] **Step 3: Write the toy-network fixture**

```python
# services/kernel/tests/fixtures_network.py
import geopandas as gpd, pandas as pd
from shapely.geometry import Point, LineString, Polygon

def toy_gdfs():
    """O14 and O9 are two outfalls feeding J9; J9 -> R3 -> ZA (Zone A node)."""
    pts = {"O14": (0.0, 0.0), "O9": (0.01, 0.0), "J9": (0.005, -0.01),
           "R3": (0.005, -0.02), "ZA": (0.005, -0.03), "ZB": (0.005, -0.04)}
    nodes = gpd.GeoDataFrame(
        {"node_id": list(pts), "node_type": ["outfall","outfall","junction","reach_point","reach_point","reach_point"],
         "geometry": [Point(*v) for v in pts.values()]}, crs="EPSG:4326")
    links = [("e1","O14","J9",300.0,0.02), ("e2","O9","J9",250.0,0.02),
             ("e3","J9","R3",400.0,0.05), ("e4","R3","ZA",350.0,0.06),
             ("e5","ZA","ZB",500.0,0.06)]
    edges = gpd.GeoDataFrame(
        {"edge_id":[l[0] for l in links], "from_node":[l[1] for l in links],
         "to_node":[l[2] for l in links], "length_m":[l[3] for l in links],
         "mean_flow_m3s":[l[4] for l in links],
         "geometry":[LineString([pts[l[1]], pts[l[2]]]) for l in links]}, crs="EPSG:4326")
    outfalls = gpd.GeoDataFrame(
        {"outfall_id":["O14","O9"], "node_id":["O14","O9"],
         "source_type":["cso","storm_outfall"], "base_rate":[0.004,0.001],
         "is_synthetic":[False,False],
         "geometry":[Point(*pts["O14"]), Point(*pts["O9"])]}, crs="EPSG:4326")
    def box(c, d=0.002):
        x, y = c
        return Polygon([(x-d,y-d),(x+d,y-d),(x+d,y+d),(x-d,y+d)])
    zones = gpd.GeoDataFrame(
        {"zone_id":["ZONE_A","ZONE_B"], "node_id":["ZA","ZB"],
         "name":["Park play area","Dog walking path"],
         "pathways":[["recreation"],["animal_contact","floodwater"]],
         "population_upper_bound":[400, 250],
         "geometry":[box(pts["ZA"]), box(pts["ZB"])]}, crs="EPSG:4326")
    return nodes, edges, outfalls, zones

def line_network_gdfs(n_nodes: int = 400, n_entries: int = 40):
    """A straight chain of n_nodes with n_entries evenly spaced outfalls.

    Used by the Phase 4 latency test to reach PRD scale (40 entries) without needing the
    real catchment. Geometry is a synthetic meridian line; only topology and lengths matter.
    """
    ids = [f"N{i:04d}" for i in range(n_nodes)]
    coords = {n: (0.0, -0.0005 * i) for i, n in enumerate(ids)}
    entry_ids = [ids[i] for i in range(0, n_nodes, max(n_nodes // n_entries, 1))][:n_entries]
    nodes = gpd.GeoDataFrame(
        {"node_id": ids,
         "node_type": ["outfall" if n in entry_ids else "reach_point" for n in ids],
         "geometry": [Point(*coords[n]) for n in ids]}, crs="EPSG:4326")
    edges = gpd.GeoDataFrame(
        {"edge_id": [f"e{i}" for i in range(n_nodes - 1)],
         "from_node": ids[:-1], "to_node": ids[1:],
         "length_m": [250.0] * (n_nodes - 1),
         "mean_flow_m3s": [0.05] * (n_nodes - 1),
         "geometry": [LineString([coords[a], coords[b]])
                      for a, b in zip(ids[:-1], ids[1:])]}, crs="EPSG:4326")
    outfalls = gpd.GeoDataFrame(
        {"outfall_id": entry_ids, "node_id": entry_ids,
         "source_type": ["cso"] * n_entries, "base_rate": [0.002] * n_entries,
         "is_synthetic": [True] * n_entries,
         "geometry": [Point(*coords[n]) for n in entry_ids]}, crs="EPSG:4326")
    def box(c, d=0.0002):
        x, y = c
        return Polygon([(x-d,y-d),(x+d,y-d),(x+d,y+d),(x-d,y+d)])
    zone_nodes = ids[-3:]
    zones = gpd.GeoDataFrame(
        {"zone_id": [f"ZONE_{i}" for i in range(3)], "node_id": zone_nodes,
         "name": [f"Zone {i}" for i in range(3)],
         "pathways": [["recreation"]] * 3, "population_upper_bound": [300] * 3,
         "geometry": [box(coords[n]) for n in zone_nodes]}, crs="EPSG:4326")
    return nodes, edges, outfalls, zones
```

- [ ] **Step 4: Implement `compiler.py`**

```python
# services/kernel/upstream_kernel/compile/compiler.py
from __future__ import annotations
import hashlib, json
from dataclasses import dataclass
import numpy as np
import rustworkx as rx

@dataclass(frozen=True)
class CompiledNetwork:
    version: str
    catchment_id: str
    node_ids: tuple[str, ...]
    node_index: dict[str, int]
    node_type: np.ndarray
    lonlat: np.ndarray
    edges: np.ndarray
    edge_length_m: np.ndarray
    edge_mean_flow: np.ndarray
    topo_order: np.ndarray
    downstream_path: dict[int, np.ndarray]
    upstream_mask: np.ndarray
    entry_nodes: tuple[str, ...]
    entry_idx: np.ndarray
    entry_source_type: tuple[str, ...]
    entry_base_rate: np.ndarray
    zone_ids: tuple[str, ...]
    zone_node_idx: np.ndarray
    zone_pathways: tuple[tuple[str, ...], ...]
    zone_population: np.ndarray

_TYPE_CODE = {"junction": 0, "outfall": 1, "reach_point": 2, "gauge": 3}

def compile_network(nodes_gdf, edges_gdf, outfalls_gdf, zones_gdf, catchment_id: str
                    ) -> CompiledNetwork:
    node_ids = tuple(nodes_gdf["node_id"].tolist())
    node_index = {n: i for i, n in enumerate(node_ids)}
    N = len(node_ids)

    edges = np.array([[node_index[f], node_index[t]]
                      for f, t in zip(edges_gdf["from_node"], edges_gdf["to_node"])],
                     dtype=np.int32)
    length = np.asarray(edges_gdf["length_m"], dtype=np.float64)
    flow = np.asarray(edges_gdf["mean_flow_m3s"], dtype=np.float64)

    g = rx.PyDiGraph()
    g.add_nodes_from(range(N))
    g.add_edges_from([(int(a), int(b), i) for i, (a, b) in enumerate(edges)])
    try:
        topo = np.array(rx.topological_sort(g), dtype=np.int32)
    except rx.DAGHasCycle as exc:                       # noqa: F841
        raise ValueError("network contains a cycle; loops are out of scope (PRD R4)") from exc

    # upstream_mask[a, b] is True iff a is strictly upstream of b.
    upstream = np.zeros((N, N), dtype=bool)
    for n in topo:
        for pred in g.predecessor_indices(int(n)):
            upstream[pred, n] = True
            upstream[:, n] |= upstream[:, pred]

    # Single-outlet assumption: each node has at most one outgoing edge (tree).
    out_edge = {int(a): i for i, (a, _) in enumerate(edges)}
    downstream_path: dict[int, np.ndarray] = {}
    for n in range(N):
        path, cur = [], n
        while cur in out_edge:
            e = out_edge[cur]
            path.append(e)
            cur = int(edges[e][1])
        downstream_path[n] = np.array(path, dtype=np.int32)

    entry_nodes = tuple(outfalls_gdf["node_id"].tolist())
    entry_idx = np.array([node_index[n] for n in entry_nodes], dtype=np.int32)
    zone_node_idx = np.array([node_index[n] for n in zones_gdf["node_id"]], dtype=np.int32)

    net_kwargs = dict(
        catchment_id=catchment_id,
        node_ids=node_ids, node_index=node_index,
        node_type=np.array([_TYPE_CODE[t] for t in nodes_gdf["node_type"]], dtype=np.int8),
        lonlat=np.array([[g_.x, g_.y] for g_ in nodes_gdf.geometry], dtype=np.float64),
        edges=edges, edge_length_m=length, edge_mean_flow=flow,
        topo_order=topo, downstream_path=downstream_path, upstream_mask=upstream,
        entry_nodes=entry_nodes, entry_idx=entry_idx,
        entry_source_type=tuple(outfalls_gdf["source_type"].tolist()),
        entry_base_rate=np.asarray(outfalls_gdf["base_rate"], dtype=np.float64),
        zone_ids=tuple(zones_gdf["zone_id"].tolist()), zone_node_idx=zone_node_idx,
        zone_pathways=tuple(tuple(p) for p in zones_gdf["pathways"]),
        zone_population=np.asarray(zones_gdf["population_upper_bound"], dtype=np.int32),
    )
    return CompiledNetwork(version=_version(net_kwargs), **net_kwargs)

def _version(k: dict) -> str:
    """Content-addressed version (GC-6): identical inputs -> identical hash."""
    canon = json.dumps({
        "catchment": k["catchment_id"],
        "nodes": list(k["node_ids"]),
        "edges": k["edges"].tolist(),
        "length_m": [round(x, 6) for x in k["edge_length_m"].tolist()],
        "flow": [round(x, 6) for x in k["edge_mean_flow"].tolist()],
        "entries": list(k["entry_nodes"]),
        "base_rate": [round(x, 9) for x in k["entry_base_rate"].tolist()],
        "zones": list(k["zone_ids"]),
    }, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode()).hexdigest()[:16]
```

- [ ] **Step 5: Run the tests**

```bash
pytest services/kernel/tests/test_compiler.py -v
```

Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add services/kernel/
git commit -m "feat(kernel): content-addressed network compiler with upstream masks"
```

---

### Task 1.2: OSM ingestion, receptor zones and the compile CLI

**Files:**
- Create: `services/kernel/upstream_kernel/compile/{osm.py,zones.py,loader.py,cli.py}`
- Create: `data/catchment/catchment.geojson`, `data/catchment/outfalls.geojson`, `data/catchment/zones_overrides.geojson`
- Test: `services/kernel/tests/test_osm_snap.py`

**Interfaces:**
- Consumes: `compile_network` from Task 1.1.
- Produces:
  - `fetch_waterways(boundary_geojson_path) -> (nodes_gdf, edges_gdf)`
  - `fetch_footpaths(boundary_geojson_path) -> gpd.GeoDataFrame` (for pgRouting, Phase 5)
  - `build_zones(boundary, overrides_path, nodes_gdf) -> zones_gdf`
  - `save_network(net, path)` / `load_network(path) -> CompiledNetwork` (`.npz` + sidecar JSON)
  - `write_network_to_postgis(net, nodes_gdf, edges_gdf, outfalls_gdf, zones_gdf, dsn)`
  - CLI: `python -m upstream_kernel.compile.cli --catchment <id> --out data/artifacts/network.npz`

- [ ] **Step 1: Write the failing snapping test (FR-5)**

```python
# services/kernel/tests/test_osm_snap.py
import pytest
from upstream_kernel.compile.loader import snap_point_to_node
from .fixtures_network import toy_gdfs
from upstream_kernel.compile.compiler import compile_network

def test_snaps_to_nearest_node_within_tolerance():
    net = compile_network(*toy_gdfs(), catchment_id="toy")
    node_id, dist_m = snap_point_to_node(net, lon=0.0001, lat=0.0001, max_m=100)
    assert node_id == "O14" and dist_m < 100

def test_rejects_points_outside_tolerance():
    net = compile_network(*toy_gdfs(), catchment_id="toy")
    with pytest.raises(ValueError, match="too far"):
        snap_point_to_node(net, lon=5.0, lat=45.0, max_m=150)
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest services/kernel/tests/test_osm_snap.py -v
```

Expected: FAIL — module missing.

- [ ] **Step 3: Implement `osm.py`**

```python
# services/kernel/upstream_kernel/compile/osm.py
"""Fetch the stream network and footpaths for one catchment from OpenStreetMap.

No API key: OSMnx uses the public Overpass API. Results are cached under
data/artifacts/osm-cache so a rebuild is offline and reproducible (GC-6).
"""
from __future__ import annotations
import geopandas as gpd, osmnx as ox
from shapely.geometry import LineString, Point

ox.settings.use_cache = True
ox.settings.cache_folder = "data/artifacts/osm-cache"

WATERWAY_TAGS = {"waterway": ["river", "stream", "ditch", "drain", "canal"]}
FOOTPATH_FILTER = '["highway"~"footway|path|pedestrian|residential|living_street|cycleway"]'

def fetch_waterways(boundary_path: str) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    boundary = gpd.read_file(boundary_path).union_all()
    ways = ox.features_from_polygon(boundary, WATERWAY_TAGS)
    ways = ways[ways.geometry.geom_type == "LineString"].reset_index(drop=True)

    metric = ways.estimate_utm_crs()
    nodes: dict[tuple[float, float], str] = {}
    rows = []
    for i, geom in enumerate(ways.geometry):
        coords = list(geom.coords)
        for a, b in zip(coords[:-1], coords[1:]):
            fa, fb = _node_id(nodes, a), _node_id(nodes, b)
            seg = LineString([a, b])
            length = gpd.GeoSeries([seg], crs=4326).to_crs(metric).length.iloc[0]
            if length < 1.0:
                continue
            rows.append({"edge_id": f"e{len(rows)}", "from_node": fa, "to_node": fb,
                         "length_m": float(length), "mean_flow_m3s": 0.05, "geometry": seg})
    edges = gpd.GeoDataFrame(rows, crs="EPSG:4326")
    nodes_gdf = gpd.GeoDataFrame(
        {"node_id": list(nodes.values()),
         "node_type": ["reach_point"] * len(nodes),
         "geometry": [Point(c) for c in nodes]}, crs="EPSG:4326")
    edges = _orient_downhill(nodes_gdf, edges)
    edges = _break_cycles(nodes_gdf, edges)
    return nodes_gdf, edges

def _node_id(nodes: dict, c: tuple[float, float]) -> str:
    key = (round(c[0], 7), round(c[1], 7))
    if key not in nodes:
        nodes[key] = f"N{len(nodes):05d}"
    return nodes[key]

def _orient_downhill(nodes_gdf, edges):
    """OSM waterway ways are drawn downstream by convention; keep that orientation but
    verify with SRTM elevation where available, flipping edges that point uphill."""
    try:
        g = ox.graph_from_gdfs_placeholder  # noqa: F841  (see note below)
    except AttributeError:
        pass
    return edges   # convention-only in the MVP; documented assumption (PRD R4)

def _break_cycles(nodes_gdf, edges):
    """Braided channels and mapping errors create cycles. Drop the longest edge in each
    cycle and record it, so the compiler's DAG assumption holds."""
    import rustworkx as rx
    idx = {n: i for i, n in enumerate(nodes_gdf["node_id"])}
    while True:
        g = rx.PyDiGraph(); g.add_nodes_from(range(len(idx)))
        g.add_edges_from([(idx[f], idx[t], i)
                          for i, (f, t) in enumerate(zip(edges["from_node"], edges["to_node"]))])
        cycles = rx.simple_cycles(g)
        cyc = next(iter(cycles), None)
        if cyc is None:
            return edges.reset_index(drop=True)
        members = [i for i, (f, t) in enumerate(zip(edges["from_node"], edges["to_node"]))
                   if idx[f] in cyc and idx[t] in cyc]
        drop = edges.loc[members, "length_m"].idxmax()
        edges = edges.drop(index=drop)

def fetch_footpaths(boundary_path: str) -> gpd.GeoDataFrame:
    boundary = gpd.read_file(boundary_path).union_all()
    g = ox.graph_from_polygon(boundary, custom_filter=FOOTPATH_FILTER, simplify=True)
    _, e = ox.graph_to_gdfs(g)
    return e.reset_index()[["u", "v", "length", "geometry"]]
```

> **Note on `_orient_downhill`:** the MVP relies on the OSM convention that waterways are
> digitised downstream, and states that as an assumption (PRD R4). If the pilot catchment
> shows obviously-reversed reaches on the console map, fix them by hand in
> `data/catchment/edge_orientation_overrides.json` rather than adding an elevation pipeline.

- [ ] **Step 4: Implement `zones.py`, `loader.py`, `cli.py`**

```python
# services/kernel/upstream_kernel/compile/zones.py
import geopandas as gpd, osmnx as ox
from shapely.geometry import Point

ZONE_TAGS = {"leisure": ["park", "playground", "dog_park", "nature_reserve"],
             "landuse": ["allotments", "recreation_ground"]}
PATHWAY_BY_TAG = {"playground": ["recreation"], "park": ["recreation", "animal_contact"],
                  "dog_park": ["animal_contact"], "allotments": ["irrigation"],
                  "nature_reserve": ["recreation"], "recreation_ground": ["recreation"]}
BUFFER_M = 150      # a zone is "exposed" via the stream node within this distance

def build_zones(boundary_path: str, overrides_path: str, nodes_gdf) -> gpd.GeoDataFrame:
    boundary = gpd.read_file(boundary_path).union_all()
    feats = ox.features_from_polygon(boundary, ZONE_TAGS)
    feats = feats[feats.geometry.geom_type.isin(["Polygon", "MultiPolygon"])]
    metric = nodes_gdf.estimate_utm_crs()
    nodes_m = nodes_gdf.to_crs(metric)
    rows = []
    for i, (_, f) in enumerate(feats.iterrows()):
        poly = f.geometry if f.geometry.geom_type == "Polygon" else f.geometry.convex_hull
        centroid = gpd.GeoSeries([poly.centroid], crs=4326).to_crs(metric).iloc[0]
        d = nodes_m.distance(centroid)
        if d.min() > BUFFER_M:
            continue                       # not stream-adjacent: not a receptor zone
        tag = f.get("leisure") or f.get("landuse")
        rows.append({"zone_id": f"ZONE_{i:03d}", "node_id": nodes_gdf.iloc[d.idxmin()]["node_id"],
                     "name": f.get("name") or f"{tag} {i}",
                     "pathways": PATHWAY_BY_TAG.get(tag, ["recreation"]),
                     "population_upper_bound": 200, "geometry": poly})
    zones = gpd.GeoDataFrame(rows, crs="EPSG:4326")
    try:
        overrides = gpd.read_file(overrides_path)
        zones = gpd.GeoDataFrame(
            __import__("pandas").concat([zones, overrides], ignore_index=True), crs="EPSG:4326")
    except Exception:
        pass
    return zones.reset_index(drop=True)
```

```python
# services/kernel/upstream_kernel/compile/loader.py
from __future__ import annotations
import json, math
import numpy as np
from pyproj import Geod
from .compiler import CompiledNetwork

_GEOD = Geod(ellps="WGS84")

def save_network(net: CompiledNetwork, path: str) -> None:
    np.savez_compressed(
        path, node_type=net.node_type, lonlat=net.lonlat, edges=net.edges,
        edge_length_m=net.edge_length_m, edge_mean_flow=net.edge_mean_flow,
        topo_order=net.topo_order, upstream_mask=net.upstream_mask,
        entry_idx=net.entry_idx, entry_base_rate=net.entry_base_rate,
        zone_node_idx=net.zone_node_idx, zone_population=net.zone_population,
        **{f"dpath_{k}": v for k, v in net.downstream_path.items()})
    with open(path + ".json", "w") as fh:
        json.dump({"version": net.version, "catchment_id": net.catchment_id,
                   "node_ids": net.node_ids, "entry_nodes": net.entry_nodes,
                   "entry_source_type": net.entry_source_type,
                   "zone_ids": net.zone_ids, "zone_pathways": net.zone_pathways}, fh)

def load_network(path: str) -> CompiledNetwork:
    z = np.load(path, allow_pickle=False)
    meta = json.load(open(path + ".json"))
    node_ids = tuple(meta["node_ids"])
    return CompiledNetwork(
        version=meta["version"], catchment_id=meta["catchment_id"], node_ids=node_ids,
        node_index={n: i for i, n in enumerate(node_ids)},
        node_type=z["node_type"], lonlat=z["lonlat"], edges=z["edges"],
        edge_length_m=z["edge_length_m"], edge_mean_flow=z["edge_mean_flow"],
        topo_order=z["topo_order"],
        downstream_path={int(k.split("_")[1]): z[k] for k in z.files if k.startswith("dpath_")},
        upstream_mask=z["upstream_mask"], entry_nodes=tuple(meta["entry_nodes"]),
        entry_idx=z["entry_idx"], entry_source_type=tuple(meta["entry_source_type"]),
        entry_base_rate=z["entry_base_rate"], zone_ids=tuple(meta["zone_ids"]),
        zone_node_idx=z["zone_node_idx"],
        zone_pathways=tuple(tuple(p) for p in meta["zone_pathways"]),
        zone_population=z["zone_population"])

def snap_point_to_node(net: CompiledNetwork, lon: float, lat: float, max_m: float
                       ) -> tuple[str, float]:
    """FR-5: snap an observation to the nearest network node, or reject it."""
    lons = net.lonlat[:, 0]; lats = net.lonlat[:, 1]
    _, _, dist = _GEOD.inv(np.full_like(lons, lon), np.full_like(lats, lat), lons, lats)
    i = int(np.argmin(dist))
    if dist[i] > max_m:
        raise ValueError(f"observation is too far from the network ({dist[i]:.0f} m > {max_m} m)")
    return net.node_ids[i], float(dist[i])
```

```python
# services/kernel/upstream_kernel/compile/cli.py
"""Build the compiled network + PostGIS tables, then append NetworkVersionPublished."""
import argparse, os, uuid, datetime as dt
import geopandas as gpd, psycopg
from psycopg.types.json import Json
from .osm import fetch_waterways, fetch_footpaths
from .zones import build_zones
from .compiler import compile_network
from .loader import save_network

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--catchment", default=os.environ["CATCHMENT_ID"])
    ap.add_argument("--boundary", default="data/catchment/catchment.geojson")
    ap.add_argument("--outfalls", default="data/catchment/outfalls.geojson")
    ap.add_argument("--overrides", default="data/catchment/zones_overrides.geojson")
    ap.add_argument("--out", default="data/artifacts/network.npz")
    a = ap.parse_args()

    nodes, edges = fetch_waterways(a.boundary)
    outfalls = gpd.read_file(a.outfalls)
    # Outfall points are snapped onto the stream graph and become entry nodes.
    nodes.loc[nodes["node_id"].isin(outfalls["node_id"]), "node_type"] = "outfall"
    zones = build_zones(a.boundary, a.overrides, nodes)
    net = compile_network(nodes, edges, outfalls, zones, catchment_id=a.catchment)
    save_network(net, a.out)

    dsn = os.environ["DATABASE_URL"]
    _write_postgis(dsn, net.version, nodes, edges, outfalls, zones,
                   fetch_footpaths(a.boundary), a.catchment)
    with psycopg.connect(dsn, autocommit=True) as c, c.cursor() as cur:
        cur.execute("SELECT append_event(%s,'live',%s,'NetworkVersionPublished',1,%s,%s,NULL,NULL)",
                    (uuid.uuid4(), a.catchment, dt.datetime.now(dt.UTC),
                     Json({"network_version": net.version, "nodes": len(net.node_ids),
                           "edges": int(net.edges.shape[0]), "entries": len(net.entry_nodes),
                           "zones": len(net.zone_ids)})))
    print(f"network_version={net.version} nodes={len(net.node_ids)} "
          f"entries={len(net.entry_nodes)} zones={len(net.zone_ids)}")

def _write_postgis(dsn, version, nodes, edges, outfalls, zones, footpaths, catchment):
    import sqlalchemy as sa
    eng = sa.create_engine(dsn.replace("postgresql://", "postgresql+psycopg://"))
    nodes.assign(network_version=version, catchment_id=catchment, attrs="{}") \
         .to_postgis("network_nodes", eng, if_exists="append")
    edges.assign(network_version=version).to_postgis("network_edges", eng, if_exists="append")
    outfalls.drop(columns="geometry").assign(network_version=version) \
            .to_sql("outfalls", eng, if_exists="append", index=False)
    zones.assign(network_version=version).to_postgis("receptor_zones", eng, if_exists="append")
    footpaths.rename(columns={"u": "source", "v": "target", "length": "cost"}) \
             .assign(reverse_cost=lambda d: d["cost"]) \
             .to_postgis("footpath_edges", eng, if_exists="append")

if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Create the three curated GeoJSON inputs**

Draw the catchment boundary and mark outfalls in [geojson.io](https://geojson.io) over the chosen
OAH pilot catchment, then save them. Minimum viable content:

```json
// data/catchment/outfalls.geojson — every feature needs these properties
{"type":"FeatureCollection","features":[
 {"type":"Feature","geometry":{"type":"Point","coordinates":[-8.4200,40.2080]},
  "properties":{"outfall_id":"O14","node_id":"","source_type":"cso",
                "base_rate":0.004,"is_synthetic":true}}
]}
```

`node_id` is filled by the CLI after snapping. **`is_synthetic: true` on every outfall you
invent** — PRD R2 requires synthetic elements to be visibly labelled in the UI.

- [ ] **Step 6: Run the compiler against the real catchment**

```bash
docker compose run --rm kernel python -m upstream_kernel.compile.cli
docker compose exec db psql -U upstream -d upstream \
  -c "SELECT count(*) FROM network_nodes; SELECT count(*) FROM receptor_zones;"
pytest services/kernel/tests/ -v
```

Expected: node count in the hundreds–low thousands; snapping tests pass.

- [ ] **Step 7: Commit**

```bash
git add services/kernel/ data/catchment/
git commit -m "feat(kernel): OSM catchment ingestion, receptor zones, compile CLI"
```

## Phase 1 exit criteria

- `data/artifacts/network.npz` exists; `load_network(...).version` is stable across two builds.
- `network_nodes`, `network_edges`, `outfalls`, `receptor_zones`, `footpath_edges` populated in PostGIS.
- A `NetworkVersionPublished` event is in the log.
- Snapping accepts a near point and rejects a far one.

## 🔑 Credentials needed at the end of Phase 1

**None.** OSM data comes from the public Overpass API through OSMnx, which needs no key.

Two *content* decisions are needed from you (not credentials):
1. **Which OAH pilot catchment** (PRD open question 1) → the boundary polygon in `data/catchment/catchment.geojson`.
2. **Outfall and CSO locations** for that catchment (PRD open question 3). If the water utility has not published them, invent plausible ones and set `is_synthetic: true`.

---

# Phase 2 — Forward physics: travel time, dispersion, dilution, die-off

**Day 1, afternoon (≈3 h).** The likelihood function is meaningless without a forward model. This phase produces the versioned lookup tables the kernel multiplies against.

**PRD coverage:** §7.2 "Forward model (physics)", §7.9 (rainfall sets the flow condition), §11.2 (SWMM offline into lookup tables), ParametersVersionPublished, R4 (state assumptions).

## File structure

```
services/kernel/upstream_kernel/physics/
├── __init__.py
├── params.py       # ParameterSet dataclass + version hash
├── velocity.py     # Manning velocity per edge per flow condition (SWMM fallback)
├── swmm.py         # optional PySWMM ensemble -> per-edge velocity (P1)
├── tables.py       # tau / sigma / dilution / decay tables from a CompiledNetwork
├── transport.py    # concentration profile C(node, t | hypothesis)
└── cli.py          # `python -m upstream_kernel.physics.cli`
```

**Decision recorded here:** the MVP computes velocities analytically (Manning) per flow
condition and treats a PySWMM ensemble as an optional refinement. Reason: a calibrated SWMM
model for an arbitrary OSM catchment cannot be built inside the hackathon window, and the
posterior only needs *relative* travel times with honest uncertainty. `swmm.py` exists so a
pilot city with a real SWMM model can drop it in without touching the kernel. **State this
assumption in the README and the demo** (PRD R4).

---

### Task 2.1: Parameter set, velocity model and travel-time tables

**Files:**
- Create: `services/kernel/upstream_kernel/physics/{params.py,velocity.py,tables.py}`
- Test: `services/kernel/tests/test_physics_tables.py`

**Interfaces:**
- Produces:
  ```python
  FLOW_CONDITIONS = ("dry", "wet", "storm")     # index order used everywhere

  @dataclass(frozen=True)
  class ParameterSet:
      version: str
      manning_n: float; hydraulic_radius_m: float
      slope_default: float
      velocity_multiplier: dict[str, float]     # per flow condition
      velocity_cv: float                        # coefficient of variation -> sigma_tau
      dispersion_coeff: float                   # sigma grows as c*sqrt(tau)
      decay_per_hour: dict[str, float]          # first-order die-off by contaminant
      flow_multiplier: dict[str, float]         # dilution scaling per flow condition
      detection: dict[str, DetectionCurve]      # keyed by ObservationMethod
      observer_reliability_default: float

  @dataclass(frozen=True)
  class DetectionCurve:
      c50: float          # concentration at 50% detection, in "relative mass units"
      slope: float        # logistic slope on log10 concentration
      false_positive: float

  @dataclass(frozen=True)
  class TravelTimeTables:
      params_version: str; network_version: str
      flow_conditions: tuple[str, ...]
      tau: np.ndarray        # (F, K_entry, N) seconds; inf where unreachable
      sigma: np.ndarray      # (F, K_entry, N) seconds
      dilution: np.ndarray   # (F, K_entry, N) in (0,1]
      reachable: np.ndarray  # (F, K_entry, N) bool

  def build_tables(net, params) -> TravelTimeTables
  def save_tables(t, path) / load_tables(path) -> TravelTimeTables
  ```

- [ ] **Step 1: Write the failing test**

```python
# services/kernel/tests/test_physics_tables.py
import numpy as np, pytest
from upstream_kernel.compile.compiler import compile_network
from upstream_kernel.physics.params import ParameterSet, default_params, FLOW_CONDITIONS
from upstream_kernel.physics.tables import build_tables
from .fixtures_network import toy_gdfs

@pytest.fixture
def net():
    return compile_network(*toy_gdfs(), catchment_id="toy")

def test_travel_time_increases_downstream(net, ):
    t = build_tables(net, default_params())
    f = FLOW_CONDITIONS.index("dry"); k = net.entry_nodes.index("O14")
    i = net.node_index
    assert t.tau[f, k, i["J9"]] < t.tau[f, k, i["R3"]] < t.tau[f, k, i["ZA"]]

def test_unreachable_nodes_are_infinite(net):
    t = build_tables(net, default_params())
    f = 0; k = net.entry_nodes.index("O14")
    assert np.isinf(t.tau[f, k, net.node_index["O9"]])   # sibling branch, not downstream
    assert not t.reachable[f, k, net.node_index["O9"]]

def test_storm_flow_is_faster_than_dry(net):
    t = build_tables(net, default_params())
    k = net.entry_nodes.index("O14"); j = net.node_index["ZA"]
    assert t.tau[FLOW_CONDITIONS.index("storm"), k, j] < t.tau[FLOW_CONDITIONS.index("dry"), k, j]

def test_dispersion_grows_with_sqrt_of_travel_time(net):
    t = build_tables(net, default_params())
    f = 0; k = net.entry_nodes.index("O14"); i = net.node_index
    r = t.sigma[f, k, i["ZA"]] / t.sigma[f, k, i["J9"]]
    r_expected = np.sqrt(t.tau[f, k, i["ZA"]] / t.tau[f, k, i["J9"]])
    assert r == pytest.approx(r_expected, rel=1e-9)

def test_dilution_decreases_downstream_and_is_bounded(net):
    t = build_tables(net, default_params())
    f = 0; k = net.entry_nodes.index("O14"); i = net.node_index
    d = t.dilution[f, k]
    assert 0 < d[i["ZA"]] <= d[i["J9"]] <= 1.0

def test_params_version_is_content_addressed():
    a, b = default_params(), default_params()
    assert a.version == b.version
    c = default_params(velocity_cv=0.5)
    assert c.version != a.version
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest services/kernel/tests/test_physics_tables.py -v
```

Expected: FAIL — `upstream_kernel.physics` missing.

- [ ] **Step 3: Implement `params.py`**

```python
# services/kernel/upstream_kernel/physics/params.py
from __future__ import annotations
import hashlib, json
from dataclasses import dataclass, asdict, field

FLOW_CONDITIONS: tuple[str, ...] = ("dry", "wet", "storm")

@dataclass(frozen=True)
class DetectionCurve:
    """P(positive | concentration c) = fp + (1-fp) * logistic((log10 c - log10 c50)/slope)."""
    c50: float
    slope: float
    false_positive: float

@dataclass(frozen=True)
class ParameterSet:
    manning_n: float = 0.035
    hydraulic_radius_m: float = 0.35
    slope_default: float = 0.004
    velocity_multiplier: dict = field(default_factory=lambda: {"dry": 0.6, "wet": 1.0, "storm": 1.8})
    velocity_cv: float = 0.30
    dispersion_coeff: float = 0.18          # sigma = coeff * sqrt(tau)
    decay_per_hour: dict = field(default_factory=lambda: {"fecal_indicator": 0.12})
    flow_multiplier: dict = field(default_factory=lambda: {"dry": 0.5, "wet": 1.0, "storm": 3.0})
    detection: dict = field(default_factory=lambda: {
        "citizen_visual_olfactory": DetectionCurve(c50=0.30, slope=0.55, false_positive=0.04),
        "citizen_freetext":         DetectionCurve(c50=0.30, slope=0.55, false_positive=0.06),
        "citizen_photo":            DetectionCurve(c50=0.35, slope=0.60, false_positive=0.05),
        "test_strip":               DetectionCurve(c50=0.12, slope=0.40, false_positive=0.03),
        "sensor_turbidity":         DetectionCurve(c50=0.08, slope=0.35, false_positive=0.02),
        "sensor_conductivity":      DetectionCurve(c50=0.10, slope=0.40, false_positive=0.02),
        "sensor_normal_window":     DetectionCurve(c50=0.08, slope=0.35, false_positive=0.02),
        "field_test":               DetectionCurve(c50=0.05, slope=0.30, false_positive=0.01),
        "lab_ecoli":                DetectionCurve(c50=0.02, slope=0.25, false_positive=0.005),
        "lab_enterococci":          DetectionCurve(c50=0.02, slope=0.25, false_positive=0.005),
        "overflow_telemetry":       DetectionCurve(c50=0.01, slope=0.20, false_positive=0.001),
        "bioassessment":            DetectionCurve(c50=0.50, slope=0.80, false_positive=0.10),
    })
    observer_reliability_default: float = 0.7
    version: str = ""

    def __post_init__(self):
        object.__setattr__(self, "version", _hash(self))

def _hash(p: "ParameterSet") -> str:
    d = asdict(p); d.pop("version", None)
    return hashlib.sha256(
        json.dumps(d, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()[:16]

def default_params(**overrides) -> ParameterSet:
    return ParameterSet(**overrides)
```

- [ ] **Step 4: Implement `velocity.py` and `tables.py`**

```python
# services/kernel/upstream_kernel/physics/velocity.py
import numpy as np
from .params import ParameterSet

def edge_velocity(net, params: ParameterSet, flow_condition: str) -> np.ndarray:
    """Manning's equation: v = (1/n) * R^(2/3) * S^(1/2), scaled by the flow condition.

    ASSUMPTION (PRD R4): uniform hydraulic radius and a default slope where OSM has none.
    A pilot city with a calibrated SWMM model replaces this via physics/swmm.py.
    """
    slope = np.full(net.edge_length_m.shape, params.slope_default)
    v = (1.0 / params.manning_n) * params.hydraulic_radius_m ** (2 / 3) * np.sqrt(slope)
    return v * params.velocity_multiplier[flow_condition]

def edge_flow(net, params: ParameterSet, flow_condition: str) -> np.ndarray:
    return net.edge_mean_flow * params.flow_multiplier[flow_condition]
```

```python
# services/kernel/upstream_kernel/physics/tables.py
from __future__ import annotations
from dataclasses import dataclass
import json
import numpy as np
from .params import ParameterSet, FLOW_CONDITIONS
from .velocity import edge_velocity, edge_flow

@dataclass(frozen=True)
class TravelTimeTables:
    params_version: str
    network_version: str
    flow_conditions: tuple[str, ...]
    tau: np.ndarray        # (F, K, N) seconds
    sigma: np.ndarray      # (F, K, N) seconds
    dilution: np.ndarray   # (F, K, N)
    reachable: np.ndarray  # (F, K, N) bool

def build_tables(net, params: ParameterSet) -> TravelTimeTables:
    F, K, N = len(FLOW_CONDITIONS), len(net.entry_idx), len(net.node_ids)
    tau = np.full((F, K, N), np.inf)
    dil = np.zeros((F, K, N))
    reach = np.zeros((F, K, N), dtype=bool)

    for f, cond in enumerate(FLOW_CONDITIONS):
        v = edge_velocity(net, params, cond)                  # (E,)
        q = edge_flow(net, params, cond)                      # (E,)
        edge_time = net.edge_length_m / v                     # (E,) seconds
        for k, entry in enumerate(net.entry_idx):
            # Walk the single downstream path from the entry node to the outlet.
            t_acc, d_acc, cur = 0.0, 1.0, int(entry)
            tau[f, k, cur] = 0.0; dil[f, k, cur] = 1.0; reach[f, k, cur] = True
            for e in net.downstream_path[int(entry)]:
                t_acc += edge_time[e]
                nxt = int(net.edges[e][1])
                # Dilution at a confluence: this branch's flow over the total inflow.
                inflow = q[[i for i, (_, b) in enumerate(net.edges) if b == nxt]].sum()
                d_acc *= float(q[e] / inflow) if inflow > 0 else 1.0
                tau[f, k, nxt] = t_acc; dil[f, k, nxt] = d_acc; reach[f, k, nxt] = True
    sigma = params.dispersion_coeff * np.sqrt(np.where(np.isfinite(tau), tau, 0.0))
    sigma = np.maximum(sigma, 60.0)                           # floor: 1 minute of timing slop
    sigma += params.velocity_cv * np.where(np.isfinite(tau), tau, 0.0)
    return TravelTimeTables(params.version, net.version, FLOW_CONDITIONS,
                            tau, sigma, dil, reach)

def save_tables(t: TravelTimeTables, path: str) -> None:
    np.savez_compressed(path, tau=t.tau, sigma=t.sigma, dilution=t.dilution,
                        reachable=t.reachable)
    json.dump({"params_version": t.params_version, "network_version": t.network_version,
               "flow_conditions": list(t.flow_conditions)}, open(path + ".json", "w"))

def load_tables(path: str) -> TravelTimeTables:
    z = np.load(path); m = json.load(open(path + ".json"))
    return TravelTimeTables(m["params_version"], m["network_version"],
                            tuple(m["flow_conditions"]),
                            z["tau"], z["sigma"], z["dilution"], z["reachable"])
```

- [ ] **Step 5: Run the tests**

```bash
pytest services/kernel/tests/test_physics_tables.py -v
```

Expected: 6 passed.

- [ ] **Step 6: Commit**

```bash
git add services/kernel/upstream_kernel/physics/ services/kernel/tests/test_physics_tables.py
git commit -m "feat(kernel): manning velocity, travel-time/dispersion/dilution tables"
```

---

### Task 2.2: Concentration profile (the forward model proper)

**Files:**
- Create: `services/kernel/upstream_kernel/physics/transport.py`
- Test: `services/kernel/tests/test_transport.py`

**Interfaces:**
- Produces:
  ```python
  def concentration(tau, sigma, dilution, reachable, *,
                    t0: jnp.ndarray, duration_s: jnp.ndarray, mass: jnp.ndarray,
                    t_obs: float, decay_per_s: float) -> jnp.ndarray
  ```
  All hypothesis-shaped arrays are `(H,)`; `tau/sigma/dilution/reachable` are `(H,)` slices
  already selected for the observed node. Returns `(H,)` relative concentration.

- [ ] **Step 1: Write the failing test**

```python
# services/kernel/tests/test_transport.py
import jax.numpy as jnp, numpy as np, pytest
from upstream_kernel.physics.transport import concentration

BASE = dict(tau=jnp.array([600.0]), sigma=jnp.array([120.0]),
            dilution=jnp.array([0.5]), reachable=jnp.array([True]),
            duration_s=jnp.array([900.0]), mass=jnp.array([1.0]), decay_per_s=0.0)

def test_peak_concentration_is_near_arrival_time():
    t0 = jnp.array([0.0])
    grid = np.arange(0, 3000, 30.0)
    vals = [float(concentration(**BASE, t0=t0, t_obs=t)[0]) for t in grid]
    peak_t = grid[int(np.argmax(vals))]
    assert 600 <= peak_t <= 600 + 900     # between arrival and arrival+duration

def test_concentration_is_near_zero_long_before_arrival():
    assert float(concentration(**BASE, t0=jnp.array([0.0]), t_obs=0.0)[0]) < 1e-3

def test_unreachable_node_gives_zero():
    kw = dict(BASE); kw["reachable"] = jnp.array([False])
    assert float(concentration(**kw, t0=jnp.array([0.0]), t_obs=700.0)[0]) == 0.0

def test_dilution_scales_concentration_linearly():
    a = float(concentration(**BASE, t0=jnp.array([0.0]), t_obs=900.0)[0])
    kw = dict(BASE); kw["dilution"] = jnp.array([0.25])
    b = float(concentration(**kw, t0=jnp.array([0.0]), t_obs=900.0)[0])
    assert b == pytest.approx(a / 2, rel=1e-6)

def test_decay_reduces_concentration_with_travel_time():
    a = float(concentration(**BASE, t0=jnp.array([0.0]), t_obs=900.0)[0])
    kw = dict(BASE); kw["decay_per_s"] = 0.12 / 3600
    b = float(concentration(**kw, t0=jnp.array([0.0]), t_obs=900.0)[0])
    assert b < a

def test_longer_release_gives_wider_but_lower_plume():
    short = dict(BASE); short["duration_s"] = jnp.array([300.0])
    long_ = dict(BASE); long_["duration_s"] = jnp.array([3600.0])
    t0 = jnp.array([0.0])
    peak_s = max(float(concentration(**short, t0=t0, t_obs=t)[0]) for t in np.arange(0, 6000, 30.))
    peak_l = max(float(concentration(**long_, t0=t0, t_obs=t)[0]) for t in np.arange(0, 6000, 30.))
    assert peak_l < peak_s
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest services/kernel/tests/test_transport.py -v
```

Expected: FAIL — module missing.

- [ ] **Step 3: Implement `transport.py`**

```python
# services/kernel/upstream_kernel/physics/transport.py
"""Forward transport model: what concentration does hypothesis h predict at (node, t)?

A rectangular release of `duration_s` starting at `t0` arrives after `tau` and is smeared
by Gaussian dispersion of width `sigma`. The concentration profile is therefore the
difference of two normal CDFs, scaled by dilution, decay and released mass, and normalised
by the release duration so total mass is conserved.
"""
from __future__ import annotations
import jax, jax.numpy as jnp
from jax.scipy.stats import norm

@jax.jit
def _profile(t_rel, duration_s, sigma):
    lo = norm.cdf(t_rel / sigma)
    hi = norm.cdf((t_rel - duration_s) / sigma)
    return (lo - hi) / jnp.maximum(duration_s, 1.0)

def concentration(tau, sigma, dilution, reachable, *, t0, duration_s, mass,
                  t_obs: float, decay_per_s: float):
    """Relative concentration (H,) at one node and one observation time."""
    t_rel = t_obs - t0 - tau                       # time since the leading edge arrived
    safe_tau = jnp.where(jnp.isfinite(tau), tau, 0.0)
    shape = _profile(t_rel, duration_s, jnp.maximum(sigma, 1.0))
    decay = jnp.exp(-decay_per_s * safe_tau)
    c = mass * dilution * decay * shape * duration_s   # renormalise: peak ~ mass*dilution
    return jnp.where(reachable & jnp.isfinite(tau), c, 0.0)
```

- [ ] **Step 4: Run the tests**

```bash
pytest services/kernel/tests/test_transport.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Build the real tables and publish the version**

```python
# services/kernel/upstream_kernel/physics/cli.py
import argparse, os, uuid, datetime as dt
import psycopg
from psycopg.types.json import Json
from ..compile.loader import load_network
from .params import default_params
from .tables import build_tables, save_tables

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--network", default="data/artifacts/network.npz")
    ap.add_argument("--out", default="data/artifacts/tables.npz")
    a = ap.parse_args()
    net = load_network(a.network); params = default_params()
    tables = build_tables(net, params)
    save_tables(tables, a.out)
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as c, c.cursor() as cur:
        cur.execute("SELECT append_event(%s,'live',%s,'ParametersVersionPublished',1,%s,%s,NULL,NULL)",
                    (uuid.uuid4(), net.catchment_id, dt.datetime.now(dt.UTC),
                     Json({"params_version": params.version,
                           "network_version": net.version})))
    print(f"params_version={params.version} tau_shape={tables.tau.shape}")

if __name__ == "__main__":
    main()
```

```bash
docker compose run --rm kernel python -m upstream_kernel.physics.cli
```

Expected: prints a 16-char params version and a `(3, K, N)` tau shape.

- [ ] **Step 6: Commit**

```bash
git add services/kernel/
git commit -m "feat(kernel): JAX forward transport model and versioned physics tables"
```

## Phase 2 exit criteria

- `data/artifacts/tables.npz` built from the real network; `tau`/`sigma`/`dilution`/`reachable` all `(3, K, N)`.
- 12 physics tests pass: monotone travel time, unreachable = ∞, storm faster than dry, σ ∝ √τ, bounded decreasing dilution, mass-conserving plume shape, decay, dilution linearity.
- A `ParametersVersionPublished` event is in the log.
- README records the Manning/SWMM assumption verbatim (PRD R4).

## 🔑 Credentials needed at the end of Phase 2

**None.** The MVP physics is analytic. If you later drop in a real EPA SWMM model you will
need the `.inp` file from the water utility — a data file, not a credential.

---

# Phase 3 — Ingestion: evidence, retraction, rainfall, sensors, AI normaliser

**Day 2, morning (≈4 h).** Everything that turns the outside world into `EvidenceRecorded` events.

**PRD coverage:** FR-1…FR-10, §10.4 Layer 1 and Layer 3, §7.9 (rainfall's five roles), §7.8 (AI at the edges only), §12.4 (evidence payload), NFR-8 (ingestion accepts reports even if the kernel is down), GC-4, GC-8.

## File structure

```
services/core-api/upstream_api/
├── main.py            # FastAPI app, routers, lifespan
├── config.py          # Settings (pydantic-settings), reads .env
├── db.py              # psycopg connection pool
├── eventlog.py        # append() wrapper + read_from(seq) — the EventStore interface
├── network.py         # in-process CompiledNetwork cache + snapping
├── media.py           # S3/MinIO upload, face/plate blur check
├── ingest/
│   ├── routes.py      # POST /ingest/* endpoints
│   ├── normaliser.py  # Claude adapter (proposals only)
│   ├── rainfall_job.py# Open-Meteo poller -> RainfallObserved
│   └── sensor_job.py  # Timescale continuous aggregate -> anomaly / normal-window evidence
└── api/               # read endpoints (Phase 5+)
```

---

### Task 3.1: `EventStore` interface and the config/db plumbing

**Files:**
- Create: `services/core-api/upstream_api/{config.py,db.py,eventlog.py,main.py}`
- Test: `services/core-api/tests/test_eventstore.py`

**Interfaces:**
- Produces (PRD §11.4 — the kernel depends *only* on this interface, so Kafka can replace it later):
  ```python
  class EventStore(Protocol):
      def append(self, env: EventEnvelope, *, causation_id=None, correlation_id=None) -> int
      def read_from(self, seq: int, *, catchment_id: str, stream: str, limit: int = 10_000) -> list[StoredEvent]
      def read_as_of(self, *, catchment_id: str, stream: str, as_of_seq: int,
                     since: datetime | None = None) -> list[StoredEvent]

  @dataclass(frozen=True)
  class StoredEvent:
      seq: int; event_id: UUID; stream: str; catchment_id: str
      event_type: EventType; schema_version: int
      event_time: datetime; recorded_at: datetime; payload: dict
      causation_id: UUID | None; correlation_id: UUID | None
  ```

- [ ] **Step 1: Write the failing test**

```python
# services/core-api/tests/test_eventstore.py
import datetime as dt, pytest
from upstream_shared.events import EventEnvelope, EventType
from upstream_api.eventlog import PostgresEventStore

pytestmark = pytest.mark.integration

def _env(**kw):
    base = dict(stream="sim", catchment_id="t1", event_type=EventType.EVIDENCE_RECORDED,
                event_time=dt.datetime.now(dt.UTC), payload={"node_id": "J4"})
    return EventEnvelope(**(base | kw))

def test_append_then_read_from(store: PostgresEventStore):
    s1 = store.append(_env()); s2 = store.append(_env())
    got = store.read_from(s1 - 1, catchment_id="t1", stream="sim")
    assert [e.seq for e in got][-2:] == [s1, s2]

def test_read_from_filters_by_stream(store):
    store.append(_env(stream="sim")); store.append(_env(stream="live"))
    got = store.read_from(0, catchment_id="t1", stream="sim")
    assert all(e.stream == "sim" for e in got)

def test_read_as_of_is_the_belief_replay_primitive(store):
    s1 = store.append(_env(payload={"n": 1}))
    store.append(_env(payload={"n": 2}))
    got = store.read_as_of(catchment_id="t1", stream="sim", as_of_seq=s1)
    assert all(e.seq <= s1 for e in got)

def test_late_arriving_event_keeps_its_event_time(store):
    """GC-4: a lab result from three days ago gets seq=now but event_time=then."""
    then = dt.datetime.now(dt.UTC) - dt.timedelta(days=3)
    seq = store.append(_env(event_time=then))
    e = [x for x in store.read_from(seq - 1, catchment_id="t1", stream="sim") if x.seq == seq][0]
    assert e.event_time == then and e.recorded_at > then
```

- [ ] **Step 2: Run to verify failure**

```bash
docker compose run --rm api pytest services/core-api/tests/test_eventstore.py -v
```

Expected: FAIL — `upstream_api.eventlog` missing.

- [ ] **Step 3: Implement config, db and the event store**

```python
# services/core-api/upstream_api/config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str
    catchment_id: str = "catch-1"
    anthropic_api_key: str = ""
    hapi_base_url: str = "http://hapi:8080/fhir"
    media_s3_endpoint: str = ""
    media_s3_bucket: str = "upstream-media"
    media_s3_access_key: str = ""
    media_s3_secret_key: str = ""
    open_meteo_base_url: str = "https://api.open-meteo.com/v1"
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_subject: str = ""
    snap_max_distance_m: float = 150.0
    network_artifact: str = "data/artifacts/network.npz"
    tables_artifact: str = "data/artifacts/tables.npz"
    class Config:
        env_file = ".env"

settings = Settings()
```

```python
# services/core-api/upstream_api/db.py
from psycopg_pool import ConnectionPool
from .config import settings

pool = ConnectionPool(settings.database_url, min_size=2, max_size=10, open=False)

def open_pool() -> None: pool.open(); pool.wait()
def close_pool() -> None: pool.close()
```

```python
# services/core-api/upstream_api/eventlog.py
from __future__ import annotations
import datetime as dt
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID
from psycopg.types.json import Json
from upstream_shared.events import EventEnvelope, EventType
from .db import pool

@dataclass(frozen=True)
class StoredEvent:
    seq: int; event_id: UUID; stream: str; catchment_id: str
    event_type: EventType; schema_version: int
    event_time: dt.datetime; recorded_at: dt.datetime; payload: dict
    causation_id: UUID | None; correlation_id: UUID | None

_COLS = ("seq,event_id,stream,catchment_id,event_type,schema_version,"
         "event_time,recorded_at,payload,causation_id,correlation_id")

class EventStore(Protocol):
    def append(self, env: EventEnvelope) -> int: ...
    def read_from(self, seq: int, *, catchment_id: str, stream: str,
                  limit: int = 10_000) -> list[StoredEvent]: ...
    def read_as_of(self, *, catchment_id: str, stream: str, as_of_seq: int,
                   since: dt.datetime | None = None) -> list[StoredEvent]: ...

class PostgresEventStore:
    def append(self, env: EventEnvelope) -> int:
        with pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT append_event(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (env.event_id, env.stream, env.catchment_id, env.event_type.value,
                 env.schema_version, env.event_time, Json(env.payload),
                 env.causation_id, env.correlation_id))
            return cur.fetchone()[0]

    def read_from(self, seq, *, catchment_id, stream, limit=10_000):
        return self._query(
            f"SELECT {_COLS} FROM events WHERE catchment_id=%s AND stream=%s AND seq>%s "
            f"ORDER BY seq LIMIT %s", (catchment_id, stream, seq, limit))

    def read_as_of(self, *, catchment_id, stream, as_of_seq, since=None):
        sql = (f"SELECT {_COLS} FROM events WHERE catchment_id=%s AND stream=%s AND seq<=%s")
        args: list = [catchment_id, stream, as_of_seq]
        if since is not None:
            sql += " AND event_time >= %s"; args.append(since)
        return self._query(sql + " ORDER BY seq", tuple(args))

    @staticmethod
    def _query(sql, args) -> list[StoredEvent]:
        with pool.connection() as conn, conn.cursor() as cur:
            cur.execute(sql, args)
            return [StoredEvent(r[0], r[1], r[2], r[3], EventType(r[4]), r[5],
                                r[6], r[7], r[8], r[9], r[10]) for r in cur.fetchall()]

store = PostgresEventStore()
```

- [ ] **Step 4: Run the tests**

```bash
docker compose run --rm api pytest services/core-api/tests/test_eventstore.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add services/core-api/
git commit -m "feat(api): EventStore interface over the append-only log"
```

---

### Task 3.2: The AI normaliser (proposals only)

Model: **`claude-opus-5`**, via `client.messages.parse(output_format=<Pydantic model>)` so the
output is schema-constrained. The endpoint returns a **proposal**; a separate confirm call
records the evidence. Nothing the model says can enter the log unconfirmed (GC-8).

**Files:**
- Create: `services/core-api/upstream_api/ingest/normaliser.py`
- Test: `services/core-api/tests/test_normaliser.py`

**Interfaces:**
- Produces:
  ```python
  class NormalisedReport(BaseModel):      # the schema Claude is constrained to
      method: ObservationMethod
      result: ObservationResult
      value: float | None
      unit: str | None
      oah_codes: list[str]
      observed_signs: list[str]           # e.g. ["sewage_smell", "grey_foam"]
      confidence: float                   # model's own confidence, shown to the citizen
      rationale: str                      # one short sentence, shown for confirmation

  class Normaliser(Protocol):
      def propose(self, free_text: str, photo_bytes: bytes | None,
                  photo_media_type: str | None) -> NormalisedReport

  class ClaudeNormaliser:  MODEL = "claude-opus-5"
  class StubNormaliser:    # keyword rules; used in tests and when no API key is set
  def get_normaliser() -> Normaliser
  ```

- [ ] **Step 1: Write the failing test (no network calls — the stub and the contract)**

```python
# services/core-api/tests/test_normaliser.py
import pytest
from upstream_api.ingest.normaliser import (NormalisedReport, StubNormaliser,
                                            ClaudeNormaliser, get_normaliser)
from upstream_shared.evidence import ObservationResult

def test_stub_detects_a_negative_report():
    r = StubNormaliser().propose("Had a look at the bridge, water looks completely normal", None, None)
    assert r.result is ObservationResult.NEGATIVE

def test_stub_detects_a_positive_sewage_report():
    r = StubNormaliser().propose("strong sewage smell and grey foam near outfall 14", None, None)
    assert r.result is ObservationResult.POSITIVE
    assert "sewage_smell" in r.observed_signs

def test_normalised_report_rejects_confidence_outside_unit_interval():
    with pytest.raises(Exception):
        NormalisedReport(method="citizen_freetext", result="positive", value=None, unit=None,
                         oah_codes=[], observed_signs=[], confidence=1.4, rationale="x")

def test_get_normaliser_falls_back_to_stub_without_an_api_key(monkeypatch):
    monkeypatch.setattr("upstream_api.config.settings.anthropic_api_key", "")
    assert isinstance(get_normaliser(), StubNormaliser)

def test_claude_normaliser_pins_the_model_id():
    assert ClaudeNormaliser.MODEL == "claude-opus-5"
```

- [ ] **Step 2: Run to verify failure**

```bash
docker compose run --rm api pytest services/core-api/tests/test_normaliser.py -v
```

Expected: FAIL — module missing.

- [ ] **Step 3: Implement the normaliser**

```python
# services/core-api/upstream_api/ingest/normaliser.py
"""AI normaliser — GC-8: proposes structured fields, never decides anything.

The model output is schema-constrained with the Anthropic SDK's `messages.parse`, so the
result is a validated Pydantic object or an exception, never free-form prose we have to
guess at. The citizen confirms every field before an EvidenceRecorded event is appended.
"""
from __future__ import annotations
import base64
from typing import Protocol
from pydantic import BaseModel, Field
from upstream_shared.codes import ObservationMethod
from upstream_shared.evidence import ObservationResult
from ..config import settings

class NormalisedReport(BaseModel):
    method: ObservationMethod
    result: ObservationResult
    value: float | None = None
    unit: str | None = None
    oah_codes: list[str] = Field(default_factory=list)
    observed_signs: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str

SYSTEM = """You structure citizen reports about an urban stream for a One Health system.

You do NOT decide whether pollution happened. You only turn what the person wrote or
photographed into fields, and you say plainly when you are unsure.

Rules:
- "looks normal", "nothing unusual", "all clear", "checked, fine" -> result = "negative".
  Negative reports are valuable; never discard them.
- A described smell, colour, foam, sewage debris, fish distress -> result = "positive".
- A numeric test-strip or meter reading -> result = "quantitative", with value and a UCUM unit.
- observed_signs uses these tokens only: sewage_smell, chemical_smell, grey_foam, white_foam,
  discolouration, oil_sheen, sewage_debris, dead_fish, turbid, clear_water, normal_smell.
- confidence is your own confidence in the extraction, not in whether pollution exists.
- rationale is ONE short sentence, written for the person who filed the report to confirm.
"""

class Normaliser(Protocol):
    def propose(self, free_text: str, photo_bytes: bytes | None,
                photo_media_type: str | None) -> NormalisedReport: ...

class ClaudeNormaliser:
    MODEL = "claude-opus-5"

    def __init__(self) -> None:
        import anthropic
        self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    def propose(self, free_text, photo_bytes=None, photo_media_type=None) -> NormalisedReport:
        content: list[dict] = []
        if photo_bytes:
            content.append({"type": "image", "source": {
                "type": "base64", "media_type": photo_media_type or "image/jpeg",
                "data": base64.b64encode(photo_bytes).decode()}})
        content.append({"type": "text", "text": free_text or "(photo only, no text)"})
        resp = self._client.messages.parse(
            model=self.MODEL,
            max_tokens=2000,
            system=SYSTEM,
            messages=[{"role": "user", "content": content}],
            output_format=NormalisedReport,
        )
        return resp.parsed_output

_POSITIVE = {"sewage": "sewage_smell", "smell": "sewage_smell", "foam": "grey_foam",
             "grey": "discolouration", "brown": "discolouration", "oil": "oil_sheen",
             "dead fish": "dead_fish", "cloudy": "turbid", "murky": "turbid",
             "debris": "sewage_debris"}
_NEGATIVE = ("looks normal", "nothing unusual", "all clear", "looks fine",
             "no smell", "water is clear", "seems normal")

class StubNormaliser:
    """Deterministic keyword fallback. Used in tests and when no API key is configured,
    so the whole pipeline is demonstrable offline."""
    def propose(self, free_text, photo_bytes=None, photo_media_type=None) -> NormalisedReport:
        text = (free_text or "").lower()
        if any(p in text for p in _NEGATIVE):
            return NormalisedReport(method=ObservationMethod.CITIZEN_VISUAL_OLFACTORY,
                                    result=ObservationResult.NEGATIVE, observed_signs=["clear_water"],
                                    confidence=0.6, rationale="Report says the water looks normal.")
        signs = sorted({v for k, v in _POSITIVE.items() if k in text})
        if signs:
            return NormalisedReport(method=ObservationMethod.CITIZEN_VISUAL_OLFACTORY,
                                    result=ObservationResult.POSITIVE, observed_signs=signs,
                                    confidence=0.55,
                                    rationale=f"Report mentions {', '.join(signs).replace('_',' ')}.")
        return NormalisedReport(method=ObservationMethod.CITIZEN_FREETEXT,
                                result=ObservationResult.NEGATIVE, observed_signs=[],
                                confidence=0.2,
                                rationale="No recognisable pollution sign; please confirm or correct.")

def get_normaliser() -> Normaliser:
    return ClaudeNormaliser() if settings.anthropic_api_key else StubNormaliser()
```

- [ ] **Step 4: Run the tests**

```bash
docker compose run --rm api pytest services/core-api/tests/test_normaliser.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Smoke-test the real model once (needs `ANTHROPIC_API_KEY`)**

```bash
docker compose run --rm api python -c "
from upstream_api.ingest.normaliser import ClaudeNormaliser
r = ClaudeNormaliser().propose('had a look under the bridge at 7am, water totally normal, no smell', None, None)
print(r.model_dump_json(indent=2))"
```

Expected: `result: "negative"`, a one-sentence rationale.

- [ ] **Step 6: Commit**

```bash
git add services/core-api/upstream_api/ingest/normaliser.py services/core-api/tests/test_normaliser.py
git commit -m "feat(api): schema-constrained AI normaliser with deterministic offline fallback"
```

---

### Task 3.3: Ingestion endpoints

**Files:**
- Create: `services/core-api/upstream_api/ingest/routes.py`, `services/core-api/upstream_api/{network.py,media.py}`
- Test: `services/core-api/tests/test_ingest_routes.py`

**Interfaces:**
- Produces these routes (FR-1…FR-10):

| Method | Path | FR | Body → effect |
|---|---|---|---|
| POST | `/ingest/report/propose` | FR-3 | free text + optional photo → `NormalisedReport` + snapped node. **Appends nothing.** |
| POST | `/ingest/report/confirm` | FR-1,2,3 | confirmed fields → `EvidenceRecorded` |
| POST | `/ingest/sensor` | FR-6 | reading → `sensor_readings` row |
| POST | `/ingest/rainfall` | FR-7 | reading → `rainfall` row + `RainfallObserved` |
| POST | `/ingest/overflow` | FR-8 | activation → `OverflowActivated` + `EvidenceRecorded` |
| POST | `/ingest/lab` | FR-9 | lab result with its own `event_time` → `EvidenceRecorded` |
| POST | `/ingest/retract` | FR-10 | `{event_id, reason}` → `EvidenceRetracted` |

- [ ] **Step 1: Write the failing tests**

```python
# services/core-api/tests/test_ingest_routes.py
import datetime as dt, pytest
from fastapi.testclient import TestClient
from upstream_api.main import app

pytestmark = pytest.mark.integration
client = TestClient(app)

def test_propose_does_not_append_anything(count_events):
    before = count_events()
    r = client.post("/ingest/report/propose", json={
        "lon": 0.0001, "lat": 0.0001, "observed_at": dt.datetime.now(dt.UTC).isoformat(),
        "free_text": "strong sewage smell"})
    assert r.status_code == 200
    assert r.json()["proposal"]["result"] == "positive"
    assert r.json()["snapped_node_id"]
    assert count_events() == before, "GC-8: a proposal must not enter the log"

def test_confirm_appends_evidence_with_both_times(store):
    observed = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=20)
    r = client.post("/ingest/report/confirm", json={
        "node_id": "O14", "observed_at": observed.isoformat(),
        "method": "citizen_visual_olfactory", "result": "positive",
        "observer_id": "vol-1", "observer_type": "citizen", "snap_distance_m": 12.0,
        "ai_assisted": True, "confirmed_by_observer": True, "oah_codes": []})
    assert r.status_code == 201
    ev = _fetch(store, r.json()["seq"])
    assert ev.event_time == observed and ev.recorded_at > observed

def test_negative_report_is_recorded_not_discarded(store):
    r = client.post("/ingest/report/confirm", json={
        "node_id": "J9", "observed_at": dt.datetime.now(dt.UTC).isoformat(),
        "method": "citizen_visual_olfactory", "result": "negative",
        "observer_id": "vol-2", "observer_type": "citizen", "snap_distance_m": 4.0,
        "confirmed_by_observer": True})
    assert r.status_code == 201
    assert _fetch(store, r.json()["seq"]).payload["result"] == "negative"

def test_unconfirmed_ai_evidence_is_rejected():
    r = client.post("/ingest/report/confirm", json={
        "node_id": "J9", "observed_at": dt.datetime.now(dt.UTC).isoformat(),
        "method": "citizen_freetext", "result": "positive", "observer_id": "v",
        "observer_type": "citizen", "snap_distance_m": 1.0,
        "ai_assisted": True, "confirmed_by_observer": False})
    assert r.status_code == 422

def test_observation_too_far_from_network_is_rejected():
    r = client.post("/ingest/report/propose", json={
        "lon": 5.0, "lat": 45.0, "observed_at": dt.datetime.now(dt.UTC).isoformat(),
        "free_text": "foam"})
    assert r.status_code == 422 and "too far" in r.text

def test_future_event_time_is_rejected():
    r = client.post("/ingest/report/confirm", json={
        "node_id": "J9", "observed_at": (dt.datetime.now(dt.UTC)+dt.timedelta(days=1)).isoformat(),
        "method": "citizen_visual_olfactory", "result": "negative",
        "observer_id": "v", "observer_type": "citizen", "snap_distance_m": 1.0})
    assert r.status_code == 422

def test_retraction_is_a_new_event_not_a_delete(store, count_events):
    seq = client.post("/ingest/report/confirm", json={
        "node_id": "J9", "observed_at": dt.datetime.now(dt.UTC).isoformat(),
        "method": "citizen_visual_olfactory", "result": "positive",
        "observer_id": "v", "observer_type": "citizen", "snap_distance_m": 1.0}).json()["seq"]
    before = count_events()
    ev = _fetch(store, seq)
    r = client.post("/ingest/retract", json={"event_id": str(ev.event_id),
                                            "reason": "wrong location", "retracted_by": "officer-1"})
    assert r.status_code == 201
    assert count_events() == before + 1
    assert _fetch(store, seq) is not None, "the original event must still exist"

def test_late_lab_result_keeps_its_original_event_time(store):
    three_days_ago = dt.datetime.now(dt.UTC) - dt.timedelta(days=3)
    r = client.post("/ingest/lab", json={
        "node_id": "R3", "observed_at": three_days_ago.isoformat(),
        "method": "lab_ecoli", "value": 2400.0, "unit": "{CFU}/100mL",
        "observer_id": "lab-a", "observer_type": "lab"})
    assert r.status_code == 201
    assert _fetch(store, r.json()["seq"]).event_time == three_days_ago

def _fetch(store, seq):
    from upstream_api.config import settings
    evs = store.read_from(seq - 1, catchment_id=settings.catchment_id, stream="live", limit=5)
    return next((e for e in evs if e.seq == seq), None)
```

- [ ] **Step 2: Run to verify failure**

```bash
docker compose run --rm api pytest services/core-api/tests/test_ingest_routes.py -v
```

Expected: FAIL — routes missing.

- [ ] **Step 3: Implement `network.py` (cached compiled network + snapping)**

```python
# services/core-api/upstream_api/network.py
from functools import lru_cache
from upstream_kernel.compile.loader import load_network, snap_point_to_node
from .config import settings

@lru_cache(maxsize=1)
def get_network():
    return load_network(settings.network_artifact)

def snap(lon: float, lat: float) -> tuple[str, float]:
    return snap_point_to_node(get_network(), lon, lat, settings.snap_max_distance_m)
```

- [ ] **Step 4: Implement `ingest/routes.py`**

```python
# services/core-api/upstream_api/ingest/routes.py
from __future__ import annotations
import datetime as dt, uuid
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel, ValidationError
from psycopg.types.json import Json
from upstream_shared.events import EventEnvelope, EventType
from upstream_shared.evidence import EvidencePayload, ObservationResult, RetractionPayload
from upstream_shared.codes import ObservationMethod
from ..config import settings
from ..db import pool
from ..eventlog import store
from ..network import snap
from .normaliser import get_normaliser

router = APIRouter(prefix="/ingest", tags=["ingest"])

class ProposeIn(BaseModel):
    lon: float; lat: float; observed_at: dt.datetime
    free_text: str = ""; photo_uri: str | None = None

class ConfirmIn(BaseModel):
    node_id: str; observed_at: dt.datetime
    method: ObservationMethod; result: ObservationResult
    value: float | None = None; unit: str | None = None
    observer_id: str; observer_type: str; snap_distance_m: float
    oah_codes: list[str] = []
    ai_assisted: bool = False; confirmed_by_observer: bool = False
    photo_uri: str | None = None; mission_id: str | None = None

@router.post("/report/propose")
def propose(body: ProposeIn):
    """FR-3: AI proposes fields. Appends nothing to the log (GC-8)."""
    try:
        node_id, dist = snap(body.lon, body.lat)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    proposal = get_normaliser().propose(body.free_text, None, None)
    return {"snapped_node_id": node_id, "snap_distance_m": dist,
            "proposal": proposal.model_dump(),
            "confirm_prompt": proposal.rationale,
            "notice": "These fields are a suggestion. Please confirm or correct them."}

@router.post("/report/confirm", status_code=201)
def confirm(body: ConfirmIn):
    """FR-1, FR-2, FR-3: record confirmed evidence, positive or negative."""
    return {"seq": _append_evidence(body)}

@router.post("/lab", status_code=201)
def lab_result(body: ConfirmIn):
    """FR-9: lab results, including ones that arrive days later (GC-4)."""
    body = body.model_copy(update={"result": ObservationResult.QUANTITATIVE})
    return {"seq": _append_evidence(body)}

@router.post("/retract", status_code=201)
def retract(body: RetractionPayload):
    """FR-10: retraction is a new event, never a delete (GC-5)."""
    env = EventEnvelope(stream="live", catchment_id=settings.catchment_id,
                        event_type=EventType.EVIDENCE_RETRACTED,
                        event_time=dt.datetime.now(dt.UTC),
                        payload=body.model_dump(),
                        causation_id=uuid.UUID(body.retracts_event_id))
    return {"seq": store.append(env)}

class SensorIn(BaseModel):
    sensor_id: str; node_id: str; ts: dt.datetime
    parameter: str; value: float; unit: str; stream: str = "live"

@router.post("/sensor", status_code=201)
def sensor(body: SensorIn):
    """FR-6: raw readings land in the hypertable; derived evidence comes from sensor_job."""
    with pool.connection() as c, c.cursor() as cur:
        cur.execute("INSERT INTO sensor_readings (ts,sensor_id,node_id,catchment_id,stream,"
                    "parameter,value,unit) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                    (body.ts, body.sensor_id, body.node_id, settings.catchment_id,
                     body.stream, body.parameter, body.value, body.unit))
    return {"ok": True}

class RainfallIn(BaseModel):
    ts: dt.datetime; mm_per_h: float
    antecedent_dry_h: float | None = None; stream: str = "live"

@router.post("/rainfall", status_code=201)
def rainfall(body: RainfallIn):
    """FR-7: rainfall every 15 minutes, with the derived flow condition (PRD 7.9)."""
    cond = flow_condition(body.mm_per_h)
    with pool.connection() as c, c.cursor() as cur:
        cur.execute("INSERT INTO rainfall (ts,catchment_id,stream,mm_per_h,antecedent_dry_h,"
                    "flow_condition) VALUES (%s,%s,%s,%s,%s,%s)",
                    (body.ts, settings.catchment_id, body.stream, body.mm_per_h,
                     body.antecedent_dry_h, cond))
    env = EventEnvelope(stream=body.stream, catchment_id=settings.catchment_id,
                        event_type=EventType.RAINFALL_OBSERVED, event_time=body.ts,
                        payload={"mm_per_h": body.mm_per_h, "flow_condition": cond,
                                 "antecedent_dry_h": body.antecedent_dry_h})
    return {"seq": store.append(env), "flow_condition": cond}

class OverflowIn(BaseModel):
    outfall_id: str; node_id: str; ts: dt.datetime; active: bool

@router.post("/overflow", status_code=201)
def overflow(body: OverflowIn):
    """FR-8: an overflow activation is both a signal and a piece of evidence."""
    env = EventEnvelope(stream="live", catchment_id=settings.catchment_id,
                        event_type=EventType.OVERFLOW_ACTIVATED, event_time=body.ts,
                        payload=body.model_dump())
    seq = store.append(env)
    ev = EvidencePayload(node_id=body.node_id, method=ObservationMethod.OVERFLOW_TELEMETRY,
                         result=ObservationResult.POSITIVE if body.active
                                else ObservationResult.NEGATIVE,
                         observer_id=body.outfall_id, observer_type="sensor",
                         snap_distance_m=0.0, confirmed_by_observer=True)
    store.append(EventEnvelope(stream="live", catchment_id=settings.catchment_id,
                               event_type=EventType.EVIDENCE_RECORDED, event_time=body.ts,
                               payload=ev.model_dump(mode="json"), causation_id=env.event_id))
    return {"seq": seq}

def flow_condition(mm_per_h: float) -> str:
    """PRD 7.9 role 2: rainfall selects the precomputed table."""
    if mm_per_h >= 10.0: return "storm"
    if mm_per_h >= 1.0:  return "wet"
    return "dry"

def _append_evidence(body: ConfirmIn) -> int:
    try:
        payload = EvidencePayload(**body.model_dump(exclude={"observed_at"}))
    except ValidationError as e:
        raise HTTPException(422, e.errors()) from e
    try:
        env = EventEnvelope(stream="live", catchment_id=settings.catchment_id,
                            event_type=EventType.EVIDENCE_RECORDED,
                            event_time=body.observed_at,
                            payload=payload.model_dump(mode="json"))
    except ValidationError as e:
        raise HTTPException(422, e.errors()) from e
    return store.append(env)
```

- [ ] **Step 5: Wire `main.py`**

```python
# services/core-api/upstream_api/main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from .db import open_pool, close_pool
from .ingest.routes import router as ingest_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    open_pool(); yield; close_pool()

app = FastAPI(title="Upstream Core API", version="0.1.0", lifespan=lifespan)
app.include_router(ingest_router)

@app.get("/healthz")
def healthz(): return {"ok": True}
```

- [ ] **Step 6: Run the tests**

```bash
docker compose run --rm api pytest services/core-api/tests/test_ingest_routes.py -v
```

Expected: 8 passed.

- [ ] **Step 7: Commit**

```bash
git add services/core-api/
git commit -m "feat(api): ingestion for reports, negatives, sensors, rainfall, overflow, lab, retraction"
```

---

### Task 3.4: Rainfall poller and derived sensor evidence

**Files:**
- Create: `services/core-api/upstream_api/ingest/{rainfall_job.py,sensor_job.py}`
- Create: `db/migrations/versions/0003_continuous_aggregates.py`
- Test: `services/core-api/tests/test_derived_evidence.py`

**Interfaces:**
- Consumes: `flow_condition()` from Task 3.3.
- Produces:
  - `poll_rainfall(catchment_lonlat, now) -> list[RainfallIn]` (Open-Meteo, **no API key**)
  - `derive_sensor_evidence(window_start, window_end) -> list[EvidencePayload]`
  - Continuous aggregate `sensor_15min`

- [ ] **Step 1: Write the failing test**

```python
# services/core-api/tests/test_derived_evidence.py
import datetime as dt, pytest
from upstream_api.ingest.sensor_job import derive_sensor_evidence, _is_anomalous
from upstream_shared.evidence import ObservationResult

def test_anomaly_detected_on_turbidity_spike():
    assert _is_anomalous(parameter="turbidity", value=180.0, baseline_mean=20.0, baseline_sd=5.0)

def test_normal_reading_is_not_an_anomaly():
    assert not _is_anomalous(parameter="turbidity", value=22.0, baseline_mean=20.0, baseline_sd=5.0)

@pytest.mark.integration
def test_quiet_sensor_emits_negative_window_evidence(seeded_normal_sensor):
    """FR-6 + PRD 7.2: 'sensor normal for these 15 minutes' is evidence, not silence."""
    evs = derive_sensor_evidence(window_start=seeded_normal_sensor["start"],
                                 window_end=seeded_normal_sensor["end"])
    assert evs and all(e.result is ObservationResult.NEGATIVE for e in evs)
    assert all(e.method == "sensor_normal_window" for e in evs)

@pytest.mark.integration
def test_spiking_sensor_emits_positive_evidence(seeded_spiking_sensor):
    evs = derive_sensor_evidence(window_start=seeded_spiking_sensor["start"],
                                 window_end=seeded_spiking_sensor["end"])
    assert any(e.result is ObservationResult.POSITIVE for e in evs)
```

- [ ] **Step 2: Run to verify failure**

```bash
docker compose run --rm api pytest services/core-api/tests/test_derived_evidence.py -v
```

Expected: FAIL — module missing.

- [ ] **Step 3: Add the continuous aggregate migration**

```python
# db/migrations/versions/0003_continuous_aggregates.py
from alembic import op
revision, down_revision = "0003", "0002"

def upgrade():
    op.execute("""
    CREATE MATERIALIZED VIEW sensor_15min
    WITH (timescaledb.continuous) AS
    SELECT time_bucket('15 minutes', ts) AS bucket,
           sensor_id, node_id, catchment_id, stream, parameter,
           avg(value) AS mean_value, stddev_samp(value) AS sd_value,
           max(value) AS max_value, count(*) AS n
    FROM sensor_readings
    GROUP BY bucket, sensor_id, node_id, catchment_id, stream, parameter
    WITH NO DATA;

    SELECT add_continuous_aggregate_policy('sensor_15min',
      start_offset => INTERVAL '3 days', end_offset => INTERVAL '1 minute',
      schedule_interval => INTERVAL '5 minutes');
    GRANT SELECT ON sensor_15min TO app_role, kernel_role;
    """)

def downgrade():
    op.execute("DROP MATERIALIZED VIEW IF EXISTS sensor_15min;")
```

- [ ] **Step 4: Implement the two jobs**

```python
# services/core-api/upstream_api/ingest/sensor_job.py
"""FR-6: turn raw sensor readings into evidence every 15 minutes.

Two kinds of evidence come out of this job, and the second one matters more:
  * an anomaly ("turbidity spiked at N14"), and
  * a *normal window* ("N14 was normal 02:15-02:30") — negative evidence that rules out
    whole upstream branches for that time slice (PRD 7.2).
"""
from __future__ import annotations
import datetime as dt
from upstream_shared.codes import ObservationMethod
from upstream_shared.evidence import EvidencePayload, ObservationResult
from ..config import settings
from ..db import pool

ANOMALY_SIGMA = 4.0
BASELINE_DAYS = 14

def _is_anomalous(*, parameter: str, value: float, baseline_mean: float,
                  baseline_sd: float) -> bool:
    sd = max(baseline_sd, 1e-6)
    z = (value - baseline_mean) / sd
    # Conductivity *drops* when storm water dilutes sewage; turbidity rises.
    return abs(z) >= ANOMALY_SIGMA if parameter == "conductivity" else z >= ANOMALY_SIGMA

def derive_sensor_evidence(window_start: dt.datetime, window_end: dt.datetime
                           ) -> list[EvidencePayload]:
    out: list[EvidencePayload] = []
    with pool.connection() as c, c.cursor() as cur:
        cur.execute("""
            SELECT a.sensor_id, a.node_id, a.parameter, a.mean_value, a.max_value,
                   b.mean_value, b.sd_value
            FROM sensor_15min a
            JOIN LATERAL (
              SELECT avg(mean_value) AS mean_value, coalesce(stddev_samp(mean_value),0) AS sd_value
              FROM sensor_15min h
              WHERE h.sensor_id=a.sensor_id AND h.parameter=a.parameter
                AND h.bucket < %s AND h.bucket > %s - (%s || ' days')::interval
            ) b ON TRUE
            WHERE a.bucket >= %s AND a.bucket < %s AND a.catchment_id = %s
        """, (window_start, window_start, BASELINE_DAYS, window_start, window_end,
              settings.catchment_id))
        for sensor_id, node_id, parameter, mean_v, max_v, base_mean, base_sd in cur.fetchall():
            if base_mean is None:
                continue
            hit = _is_anomalous(parameter=parameter, value=max_v,
                                baseline_mean=base_mean, baseline_sd=base_sd)
            method = (ObservationMethod.SENSOR_TURBIDITY if parameter == "turbidity"
                      else ObservationMethod.SENSOR_CONDUCTIVITY if parameter == "conductivity"
                      else ObservationMethod.SENSOR_NORMAL_WINDOW)
            out.append(EvidencePayload(
                node_id=node_id,
                method=method if hit else ObservationMethod.SENSOR_NORMAL_WINDOW,
                result=ObservationResult.POSITIVE if hit else ObservationResult.NEGATIVE,
                value=float(max_v), unit="[arb'U]",
                observer_id=sensor_id, observer_type="sensor", snap_distance_m=0.0,
                confirmed_by_observer=True,
                window_start=window_start.isoformat(), window_end=window_end.isoformat()))
    return out
```

```python
# services/core-api/upstream_api/ingest/rainfall_job.py
"""FR-7: poll Open-Meteo for catchment rainfall every 15 minutes.

Open-Meteo's free non-commercial endpoint needs NO API KEY. If you later switch to a
national radar or gauge feed, only this file changes.
"""
from __future__ import annotations
import datetime as dt
import httpx
from ..config import settings
from .routes import RainfallIn, flow_condition   # noqa: F401  (flow_condition re-exported)

async def poll_rainfall(lon: float, lat: float, now: dt.datetime | None = None
                        ) -> list[RainfallIn]:
    now = now or dt.datetime.now(dt.UTC)
    url = (f"{settings.open_meteo_base_url}/forecast?latitude={lat}&longitude={lon}"
           f"&minutely_15=precipitation&past_days=1&forecast_days=1&timezone=UTC")
    async with httpx.AsyncClient(timeout=20.0) as client:
        data = (await client.get(url)).json()
    times = data["minutely_15"]["time"]
    precip_mm = data["minutely_15"]["precipitation"]     # mm per 15 min
    out, dry_run = [], 0.0
    for t, mm in zip(times, precip_mm):
        ts = dt.datetime.fromisoformat(t).replace(tzinfo=dt.UTC)
        if ts > now:
            break
        mm_per_h = (mm or 0.0) * 4.0
        dry_run = 0.0 if mm_per_h > 0.2 else dry_run + 0.25
        out.append(RainfallIn(ts=ts, mm_per_h=mm_per_h, antecedent_dry_h=dry_run))
    return out
```

- [ ] **Step 5: Register both jobs on a 15-minute schedule in `main.py`**

```python
# append to services/core-api/upstream_api/main.py
import asyncio, datetime as dt
from .config import settings
from .eventlog import store
from .ingest.rainfall_job import poll_rainfall
from .ingest.sensor_job import derive_sensor_evidence
from .ingest.routes import rainfall as ingest_rainfall
from .network import get_network
from upstream_shared.events import EventEnvelope, EventType

async def _derived_evidence_loop():
    """Layer 3 (PRD 10.4): scheduled jobs that turn raw feeds into evidence."""
    while True:
        try:
            net = get_network()
            lon, lat = net.lonlat.mean(axis=0)
            for r in await poll_rainfall(float(lon), float(lat)):
                ingest_rainfall(r)
            end = dt.datetime.now(dt.UTC).replace(second=0, microsecond=0)
            start = end - dt.timedelta(minutes=15)
            for ev in derive_sensor_evidence(start, end):
                store.append(EventEnvelope(
                    stream="live", catchment_id=settings.catchment_id,
                    event_type=EventType.EVIDENCE_RECORDED, event_time=end,
                    payload=ev.model_dump(mode="json")))
        except Exception as exc:                       # NFR-8: never take ingestion down
            print(f"[derived-evidence] {type(exc).__name__}: {exc}")
        await asyncio.sleep(900)

# inside lifespan(), before `yield`:
#     task = asyncio.create_task(_derived_evidence_loop())
# after `yield`:
#     task.cancel()
```

- [ ] **Step 6: Run the tests and the migration**

```bash
docker compose run --rm api alembic -c db/alembic.ini upgrade head
docker compose run --rm api pytest services/core-api/tests/ -v
```

Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add services/core-api/ db/
git commit -m "feat(api): rainfall poller and 15-minute derived sensor evidence (incl. normal windows)"
```

## Phase 3 exit criteria

- All seven ingestion routes work; `/healthz` returns OK.
- Proposal → confirm flow appends exactly one event, only after confirmation.
- Negative reports, late lab results and retractions all recorded correctly (bitemporal).
- Rainfall rows appear with a derived `flow_condition`; a quiet sensor produces `sensor_normal_window` negative evidence.
- Ingestion still returns 201 with the kernel container stopped (NFR-8) — verify with `docker compose stop kernel`.

## 🔑 Credentials needed at the end of Phase 3

| Variable | What it is | Where to get it |
|---|---|---|
| `ANTHROPIC_API_KEY` | Claude API key for the AI normaliser (model `claude-opus-5`) | console.anthropic.com → API Keys. **Without it the system still runs**, falling back to `StubNormaliser`. |
| `MEDIA_S3_ACCESS_KEY` | MinIO root user for photo storage | **You choose it** (it configures the local MinIO container) |
| `MEDIA_S3_SECRET_KEY` | MinIO root password | **You choose it** |
| `MEDIA_S3_ENDPOINT` | `http://minio:9000` locally | Fixed |
| `MEDIA_S3_BUCKET` | `upstream-media` | Fixed |
| `OPEN_METEO_BASE_URL` | `https://api.open-meteo.com/v1` | **No key needed** — free non-commercial tier |

---

# Phase 4 — TRACE: the exact posterior

**Day 2, afternoon (≈5 h).** The heart of the project. Never cut this.

**PRD coverage:** §7.2 (hypotheses, likelihood, negative evidence, prior, posterior, recompute-don't-update), §7.3 (TRACE output + computed explanation), FR-11, FR-13, FR-18, §12.5 (snapshot + fingerprint), G1, G6, NFR-1, NFR-3, GC-6.

## File structure

```
services/kernel/upstream_kernel/
├── model/
│   ├── hypotheses.py   # the hypothesis grid
│   ├── priors.py       # base rates x rainfall x history x ecology
│   ├── likelihood.py   # detection curves, negative evidence, quantitative readings
│   └── posterior.py    # exact log-posterior over all hypotheses
├── trace.py            # source marginals, corridors, computed explanation
├── fingerprint.py      # sha256 over evidence ids + versions
├── evidence_view.py    # StoredEvent[] -> ObservationSet (applies retractions)
└── worker.py           # LISTEN/NOTIFY loop; writes snapshots + PosteriorComputed
```

---

### Task 4.1: Hypothesis grid

**Files:**
- Create: `services/kernel/upstream_kernel/model/hypotheses.py`
- Test: `services/kernel/tests/test_hypotheses.py`

**Interfaces:**
- Produces:
  ```python
  KIND_POINT, KIND_DIFFUSE, KIND_NONE = 0, 1, 2
  DURATION_CLASSES_S = (900, 3600, 10800)      # 15 min, 1 h, 3 h

  @dataclass(frozen=True)
  class HypothesisGrid:
      H: int
      entry_k: np.ndarray      # (H,) int32 index into net.entry_idx; -1 for diffuse/none
      t0: np.ndarray           # (H,) float64 epoch seconds; nan for 'none'
      duration_s: np.ndarray   # (H,) float64
      kind: np.ndarray         # (H,) int8
      mass: np.ndarray         # (H,) float64 relative released mass
      bin_s: int
      horizon_start: float; horizon_end: float

  def build_grid(net, *, horizon_start: datetime, horizon_end: datetime,
                 bin_s: int = 900,
                 durations: tuple[int, ...] = DURATION_CLASSES_S) -> HypothesisGrid
  ```

- [ ] **Step 1: Write the failing test**

```python
# services/kernel/tests/test_hypotheses.py
import datetime as dt, numpy as np
from upstream_kernel.compile.compiler import compile_network
from upstream_kernel.model.hypotheses import build_grid, KIND_POINT, KIND_DIFFUSE, KIND_NONE
from .fixtures_network import toy_gdfs

def _grid(hours=24):
    net = compile_network(*toy_gdfs(), catchment_id="toy")
    end = dt.datetime(2026, 9, 22, 6, tzinfo=dt.UTC)
    return net, build_grid(net, horizon_start=end - dt.timedelta(hours=hours), horizon_end=end)

def test_grid_size_is_entries_times_bins_times_durations_plus_two():
    net, g = _grid()
    expected = len(net.entry_nodes) * 96 * 3 + 2      # 24 h / 15 min = 96 bins
    assert g.H == expected

def test_exactly_one_none_and_one_diffuse_hypothesis():
    _, g = _grid()
    assert int((g.kind == KIND_NONE).sum()) == 1
    assert int((g.kind == KIND_DIFFUSE).sum()) == 1
    assert int((g.kind == KIND_POINT).sum()) == g.H - 2

def test_start_times_lie_inside_the_horizon():
    _, g = _grid()
    pts = g.kind == KIND_POINT
    assert g.t0[pts].min() >= g.horizon_start
    assert g.t0[pts].max() < g.horizon_end

def test_longer_durations_release_more_mass():
    _, g = _grid()
    pts = g.kind == KIND_POINT
    by_dur = {float(d): g.mass[pts][g.duration_s[pts] == d][0] for d in np.unique(g.duration_s[pts])}
    ks = sorted(by_dur)
    assert by_dur[ks[0]] < by_dur[ks[1]] < by_dur[ks[2]]

def test_prd_scale_is_about_eleven_thousand_hypotheses():
    """PRD 7.2: 40 entries x 96 bins x 3 durations ~ 11,500."""
    class FakeNet:
        entry_nodes = tuple(f"O{i}" for i in range(40))
        entry_idx = np.arange(40, dtype=np.int32)
    end = dt.datetime(2026, 9, 22, 6, tzinfo=dt.UTC)
    g = build_grid(FakeNet(), horizon_start=end - dt.timedelta(hours=24), horizon_end=end)
    assert 11_000 <= g.H <= 12_000
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest services/kernel/tests/test_hypotheses.py -v
```

Expected: FAIL — module missing.

- [ ] **Step 3: Implement `hypotheses.py`**

```python
# services/kernel/upstream_kernel/model/hypotheses.py
from __future__ import annotations
import datetime as dt
from dataclasses import dataclass
import numpy as np

KIND_POINT, KIND_DIFFUSE, KIND_NONE = 0, 1, 2
DURATION_CLASSES_S: tuple[int, ...] = (900, 3600, 10800)

@dataclass(frozen=True)
class HypothesisGrid:
    H: int
    entry_k: np.ndarray
    t0: np.ndarray
    duration_s: np.ndarray
    kind: np.ndarray
    mass: np.ndarray
    bin_s: int
    horizon_start: float
    horizon_end: float

def build_grid(net, *, horizon_start: dt.datetime, horizon_end: dt.datetime,
               bin_s: int = 900, durations: tuple[int, ...] = DURATION_CLASSES_S
               ) -> HypothesisGrid:
    """A hypothesis is (entry node, start bin, duration class), plus 'diffuse' and 'none'."""
    t_start, t_end = horizon_start.timestamp(), horizon_end.timestamp()
    bins = np.arange(t_start, t_end, bin_s, dtype=np.float64)
    K, B, D = len(net.entry_idx), len(bins), len(durations)

    entry_k = np.repeat(np.arange(K, dtype=np.int32), B * D)
    t0 = np.tile(np.repeat(bins, D), K)
    duration_s = np.tile(np.asarray(durations, dtype=np.float64), K * B)
    kind = np.full(K * B * D, KIND_POINT, dtype=np.int8)
    # Mass grows sub-linearly with duration: a longer spill releases more, but the rate falls.
    mass = np.sqrt(duration_s / durations[0])

    # Two special hypotheses (PRD 7.2).
    entry_k = np.concatenate([entry_k, [-1, -1]]).astype(np.int32)
    t0 = np.concatenate([t0, [t_start, np.nan]])
    duration_s = np.concatenate([duration_s, [float(t_end - t_start), 0.0]])
    kind = np.concatenate([kind, [KIND_DIFFUSE, KIND_NONE]]).astype(np.int8)
    mass = np.concatenate([mass, [0.25, 0.0]])          # diffuse runoff is weak but everywhere

    return HypothesisGrid(H=len(kind), entry_k=entry_k, t0=t0, duration_s=duration_s,
                          kind=kind, mass=mass, bin_s=bin_s,
                          horizon_start=t_start, horizon_end=t_end)
```

- [ ] **Step 4: Run the tests**

```bash
pytest services/kernel/tests/test_hypotheses.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add services/kernel/upstream_kernel/model/hypotheses.py services/kernel/tests/test_hypotheses.py
git commit -m "feat(kernel): hypothesis grid with diffuse-runoff and no-event hypotheses"
```

---

### Task 4.2: Priors — the five ways rainfall and history change the odds

**Files:**
- Create: `services/kernel/upstream_kernel/model/priors.py`
- Test: `services/kernel/tests/test_priors.py`

**Interfaces:**
- Produces:
  ```python
  @dataclass(frozen=True)
  class PriorInputs:
      flow_condition_by_bin: np.ndarray   # (B,) int8 index into FLOW_CONDITIONS
      antecedent_dry_h: np.ndarray        # (B,) float64
      past_episode_count: np.ndarray      # (K,) int32 from pooling (Phase 11); zeros at first
      ecology_pressure: np.ndarray        # (K,) float64 in [0,1] from OAH bioassessment

  def log_prior(net, grid, inputs: PriorInputs, params) -> np.ndarray   # (H,)
  ```

- [ ] **Step 1: Write the failing test**

```python
# services/kernel/tests/test_priors.py
import datetime as dt, numpy as np, pytest
from upstream_kernel.compile.compiler import compile_network
from upstream_kernel.model.hypotheses import build_grid, KIND_DIFFUSE, KIND_NONE, KIND_POINT
from upstream_kernel.model.priors import PriorInputs, log_prior
from upstream_kernel.physics.params import default_params, FLOW_CONDITIONS
from .fixtures_network import toy_gdfs

def setup(cond="dry", dry_h=48.0):
    net = compile_network(*toy_gdfs(), catchment_id="toy")
    end = dt.datetime(2026, 9, 22, 6, tzinfo=dt.UTC)
    g = build_grid(net, horizon_start=end - dt.timedelta(hours=6), horizon_end=end)
    B = int(((g.horizon_end - g.horizon_start) // g.bin_s))
    inputs = PriorInputs(
        flow_condition_by_bin=np.full(B, FLOW_CONDITIONS.index(cond), dtype=np.int8),
        antecedent_dry_h=np.full(B, dry_h),
        past_episode_count=np.zeros(len(net.entry_idx), dtype=np.int32),
        ecology_pressure=np.zeros(len(net.entry_idx)))
    return net, g, inputs

def test_prior_is_normalised():
    net, g, inp = setup()
    lp = log_prior(net, g, inp, default_params())
    assert float(np.exp(lp).sum()) == pytest.approx(1.0, rel=1e-9)

def test_storm_raises_cso_prior_relative_to_dry():
    """PRD 7.9 role 1: overflows mostly activate during heavy rain."""
    net, g, dry = setup("dry")
    _, _, storm = setup("storm")
    k_cso = net.entry_nodes.index("O14")     # source_type == 'cso'
    def cso_mass(inp):
        lp = log_prior(net, g, inp, default_params())
        return float(np.exp(lp)[(g.kind == KIND_POINT) & (g.entry_k == k_cso)].sum())
    assert cso_mass(storm) > 3 * cso_mass(dry)

def test_dry_weather_event_points_away_from_cso():
    """PRD 7.9 role 1, converse: a dry-weather event suggests a misconnection."""
    net, g, dry = setup("dry")
    lp = np.exp(log_prior(net, g, dry, default_params()))
    k_cso = net.entry_nodes.index("O14"); k_storm = net.entry_nodes.index("O9")
    assert lp[(g.entry_k == k_cso)].sum() < lp[(g.entry_k == k_storm)].sum() * 3

def test_first_flush_raises_the_diffuse_hypothesis():
    """PRD 7.9 role 3: first rain after a dry spell washes streets."""
    net, g, wet_after_dry = setup("storm", dry_h=72.0)
    _, _, wet_after_wet = setup("storm", dry_h=1.0)
    def diffuse(inp):
        return float(np.exp(log_prior(net, g, inp, default_params()))[g.kind == KIND_DIFFUSE].sum())
    assert diffuse(wet_after_dry) > diffuse(wet_after_wet)

def test_no_event_holds_most_of_the_prior_mass():
    net, g, inp = setup()
    p = np.exp(log_prior(net, g, inp, default_params()))
    assert p[g.kind == KIND_NONE][0] > 0.9

def test_recurring_source_history_raises_that_entry_prior():
    net, g, inp = setup()
    k = net.entry_nodes.index("O9")
    boosted = PriorInputs(inp.flow_condition_by_bin, inp.antecedent_dry_h,
                          np.array([0, 6], dtype=np.int32), inp.ecology_pressure)
    base = np.exp(log_prior(net, g, inp, default_params()))
    more = np.exp(log_prior(net, g, boosted, default_params()))
    assert more[g.entry_k == k].sum() > base[g.entry_k == k].sum()
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest services/kernel/tests/test_priors.py -v
```

Expected: FAIL — module missing.

- [ ] **Step 3: Implement `priors.py`**

```python
# services/kernel/upstream_kernel/model/priors.py
"""Prior over hypotheses, before any evidence.

PRD 7.2 "Prior" + PRD 7.9 roles 1 and 3. Five inputs shape it:
  1. the entry point's type-driven base rate,
  2. rainfall (CSOs spill in storms; dry-weather events mean misconnections),
  3. first flush after a dry spell (raises the diffuse-runoff hypothesis),
  4. how often this point has been implicated before (Phase 11 pooling),
  5. slow ecological indicators of chronic pressure on that reach (OAH bioassessment).
"""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
from scipy.special import logsumexp
from .hypotheses import KIND_POINT, KIND_DIFFUSE, KIND_NONE
from ..physics.params import FLOW_CONDITIONS

@dataclass(frozen=True)
class PriorInputs:
    flow_condition_by_bin: np.ndarray
    antecedent_dry_h: np.ndarray
    past_episode_count: np.ndarray
    ecology_pressure: np.ndarray

# How much each source type's base rate is multiplied in each flow condition.
_RAIN_FACTOR: dict[str, dict[str, float]] = {
    "cso":            {"dry": 0.05, "wet": 1.0, "storm": 12.0},
    "storm_outfall":  {"dry": 0.30, "wet": 1.5, "storm": 4.0},
    "misconnection":  {"dry": 1.00, "wet": 1.0, "storm": 1.0},   # constant, rain-independent
    "industrial":     {"dry": 1.00, "wet": 1.0, "storm": 1.2},
    "unknown":        {"dry": 0.50, "wet": 1.0, "storm": 2.0},
}
P_NO_EVENT = 0.97                 # base rate of "nothing is happening right now"
DIFFUSE_BASE = 0.002
FIRST_FLUSH_DRY_H = 24.0

def log_prior(net, grid, inputs: PriorInputs, params) -> np.ndarray:
    H = grid.H
    w = np.zeros(H, dtype=np.float64)
    pts = grid.kind == KIND_POINT
    bin_of = np.zeros(H, dtype=np.int64)
    bin_of[pts] = ((grid.t0[pts] - grid.horizon_start) // grid.bin_s).astype(np.int64)
    bin_of = np.clip(bin_of, 0, len(inputs.flow_condition_by_bin) - 1)

    base = net.entry_base_rate[np.where(pts, grid.entry_k, 0)]
    cond = np.array(FLOW_CONDITIONS)[inputs.flow_condition_by_bin[bin_of]]
    stype = np.array(net.entry_source_type)[np.where(pts, grid.entry_k, 0)]
    rain_mult = np.array([_RAIN_FACTOR.get(s, _RAIN_FACTOR["unknown"])[c]
                          for s, c in zip(stype, cond)])
    history = 1.0 + 0.35 * inputs.past_episode_count[np.where(pts, grid.entry_k, 0)]
    ecology = 1.0 + 0.50 * inputs.ecology_pressure[np.where(pts, grid.entry_k, 0)]
    w[pts] = (base * rain_mult * history * ecology)[pts]

    dif = grid.kind == KIND_DIFFUSE
    storm_bins = (inputs.flow_condition_by_bin == FLOW_CONDITIONS.index("storm")).mean()
    first_flush = 1.0 + 4.0 * float((inputs.antecedent_dry_h > FIRST_FLUSH_DRY_H).mean())
    w[dif] = DIFFUSE_BASE * (0.2 + 3.0 * storm_bins) * first_flush

    total_event = w.sum()
    if total_event > 0:
        w *= (1.0 - P_NO_EVENT) / total_event
    w[grid.kind == KIND_NONE] = P_NO_EVENT
    return np.log(np.maximum(w, 1e-300)) - logsumexp(np.log(np.maximum(w, 1e-300)))
```

- [ ] **Step 4: Run the tests**

```bash
pytest services/kernel/tests/test_priors.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add services/kernel/upstream_kernel/model/priors.py services/kernel/tests/test_priors.py
git commit -m "feat(kernel): rainfall-, history- and ecology-aware prior"
```

---

### Task 4.3: Likelihood — including the negative evidence that does the real work

**Files:**
- Create: `services/kernel/upstream_kernel/model/likelihood.py`, `services/kernel/upstream_kernel/evidence_view.py`
- Test: `services/kernel/tests/test_likelihood.py`

**Interfaces:**
- Produces:
  ```python
  @dataclass(frozen=True)
  class Observation:
      event_id: str; node_idx: int; t_obs: float
      method: str; result: str              # positive|negative|quantitative
      value: float | None; observer_reliability: float
      window_start: float | None; window_end: float | None

  def build_observations(events: list[StoredEvent], net, params) -> list[Observation]
      # applies EvidenceRetracted (GC-5): retracted observations are excluded, not deleted

  def log_likelihood(obs: Observation, grid, tables, flow_idx: int, params) -> jnp.ndarray  # (H,)
  def total_log_likelihood(observations, grid, tables, flow_idx, params) -> jnp.ndarray     # (H,)
  ```

- [ ] **Step 1: Write the failing test**

```python
# services/kernel/tests/test_likelihood.py
import datetime as dt, numpy as np, pytest
import jax.numpy as jnp
from upstream_kernel.compile.compiler import compile_network
from upstream_kernel.physics.params import default_params, FLOW_CONDITIONS
from upstream_kernel.physics.tables import build_tables
from upstream_kernel.model.hypotheses import build_grid, KIND_NONE, KIND_POINT
from upstream_kernel.model.likelihood import Observation, log_likelihood
from .fixtures_network import toy_gdfs

@pytest.fixture
def ctx():
    net = compile_network(*toy_gdfs(), catchment_id="toy")
    params = default_params()
    tables = build_tables(net, params)
    end = dt.datetime(2026, 9, 22, 3, tzinfo=dt.UTC)
    grid = build_grid(net, horizon_start=end - dt.timedelta(hours=3), horizon_end=end)
    return net, params, tables, grid, FLOW_CONDITIONS.index("wet")

def _obs(net, node, t, result, method="citizen_visual_olfactory"):
    return Observation(event_id="e", node_idx=net.node_index[node], t_obs=t,
                       method=method, result=result, value=None,
                       observer_reliability=0.9, window_start=None, window_end=None)

def test_positive_report_favours_upstream_sources_at_the_right_time(ctx):
    net, params, tables, grid, f = ctx
    # An observation at ZA that should be explained by an O14 release ~1 travel time earlier.
    k = net.entry_nodes.index("O14"); j = net.node_index["ZA"]
    tau = float(tables.tau[f, k, j])
    t_obs = grid.horizon_end - 600
    ll = np.asarray(log_likelihood(_obs(net, "ZA", t_obs, "positive"), grid, tables, f, params))
    fits = (grid.kind == KIND_POINT) & (grid.entry_k == k) & \
           (np.abs(grid.t0 - (t_obs - tau)) < 2 * grid.bin_s)
    assert ll[fits].mean() > ll[grid.kind == KIND_NONE][0]

def test_negative_report_eliminates_hypotheses_whose_plume_should_be_passing(ctx):
    """PRD 7.2: 'checked, looks normal' rules out whole upstream branches."""
    net, params, tables, grid, f = ctx
    k = net.entry_nodes.index("O14"); j = net.node_index["J9"]
    tau = float(tables.tau[f, k, j])
    t_obs = grid.horizon_end - 1200
    ll = np.asarray(log_likelihood(_obs(net, "J9", t_obs, "negative"), grid, tables, f, params))
    should_be_passing = (grid.entry_k == k) & (np.abs(grid.t0 - (t_obs - tau)) < grid.bin_s)
    assert ll[should_be_passing].mean() < ll[grid.kind == KIND_NONE][0] - 1.0

def test_negative_report_does_not_penalise_unrelated_branches(ctx):
    net, params, tables, grid, f = ctx
    t_obs = grid.horizon_end - 1200
    ll = np.asarray(log_likelihood(_obs(net, "J9", t_obs, "negative"), grid, tables, f, params))
    k_other = net.entry_nodes.index("O9")
    far_in_time = (grid.entry_k == k_other) & (grid.t0 < grid.horizon_start + 900)
    assert ll[far_in_time].mean() == pytest.approx(ll[grid.kind == KIND_NONE][0], abs=0.15)

def test_far_downstream_positive_counts_for_less_than_a_near_one(ctx):
    """Dilution and decay mean a distant report is weaker evidence, automatically."""
    net, params, tables, grid, f = ctx
    k = net.entry_nodes.index("O14")
    t = grid.horizon_end - 600
    near = np.asarray(log_likelihood(_obs(net, "J9", t, "positive"), grid, tables, f, params))
    far  = np.asarray(log_likelihood(_obs(net, "ZB", t, "positive"), grid, tables, f, params))
    spread = lambda a: a[grid.entry_k == k].max() - a[grid.kind == KIND_NONE][0]
    assert spread(near) > spread(far)

def test_false_positive_rate_keeps_likelihood_finite_everywhere(ctx):
    net, params, tables, grid, f = ctx
    ll = np.asarray(log_likelihood(_obs(net, "ZB", grid.horizon_start + 60, "positive"),
                                   grid, tables, f, params))
    assert np.all(np.isfinite(ll))

def test_low_reliability_observer_moves_the_posterior_less(ctx):
    net, params, tables, grid, f = ctx
    t = grid.horizon_end - 600
    good = _obs(net, "J9", t, "positive")
    weak = Observation(**{**good.__dict__, "observer_reliability": 0.3})
    a = np.asarray(log_likelihood(good, grid, tables, f, params))
    b = np.asarray(log_likelihood(weak, grid, tables, f, params))
    assert (a.max() - a.min()) > (b.max() - b.min())

def test_quantitative_lab_value_uses_a_lognormal_likelihood(ctx):
    net, params, tables, grid, f = ctx
    o = Observation(event_id="e", node_idx=net.node_index["R3"], t_obs=grid.horizon_end - 600,
                    method="lab_ecoli", result="quantitative", value=2400.0,
                    observer_reliability=1.0, window_start=None, window_end=None)
    ll = np.asarray(log_likelihood(o, grid, tables, f, params))
    assert np.all(np.isfinite(ll)) and ll.std() > 0
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest services/kernel/tests/test_likelihood.py -v
```

Expected: FAIL — module missing.

- [ ] **Step 3: Implement `likelihood.py`**

```python
# services/kernel/upstream_kernel/model/likelihood.py
"""P(observation | hypothesis).

Each observation method has a detection curve: the chance of a positive result given the
concentration the forward model predicts at that place and time, plus a false-positive rate.
A negative observation gets 1 - that. Observer reliability shrinks the curve towards the
false-positive rate, so an unreliable observer moves the posterior less.
"""
from __future__ import annotations
from dataclasses import dataclass
import jax, jax.numpy as jnp
import numpy as np
from ..physics.transport import concentration
from .hypotheses import KIND_NONE, KIND_DIFFUSE

@dataclass(frozen=True)
class Observation:
    event_id: str
    node_idx: int
    t_obs: float
    method: str
    result: str
    value: float | None
    observer_reliability: float
    window_start: float | None
    window_end: float | None

DIFFUSE_BACKGROUND_C = 0.12        # what a diffuse-runoff hypothesis predicts everywhere
LAB_LOG_SD = 0.8                   # lognormal spread of a lab count given concentration
LAB_SCALE = 5.0e4                  # CFU/100mL at relative concentration 1.0

def _detect_prob(c, curve, reliability: float):
    """Logistic detection on log10 concentration, shrunk towards fp by unreliability."""
    z = (jnp.log10(jnp.maximum(c, 1e-12)) - jnp.log10(curve.c50)) / curve.slope
    p = curve.false_positive + (1.0 - curve.false_positive) * jax.nn.sigmoid(z)
    return curve.false_positive + reliability * (p - curve.false_positive)

def _predicted_concentration(obs, grid, tables, flow_idx, params):
    node = obs.node_idx
    k = np.clip(grid.entry_k, 0, None)
    tau = jnp.asarray(tables.tau[flow_idx, k, node])
    sigma = jnp.asarray(tables.sigma[flow_idx, k, node])
    dil = jnp.asarray(tables.dilution[flow_idx, k, node])
    reach = jnp.asarray(tables.reachable[flow_idx, k, node])
    decay = params.decay_per_hour["fecal_indicator"] / 3600.0
    c = concentration(tau, sigma, dil, reach,
                      t0=jnp.asarray(np.nan_to_num(grid.t0)),
                      duration_s=jnp.asarray(grid.duration_s),
                      mass=jnp.asarray(grid.mass),
                      t_obs=float(obs.t_obs), decay_per_s=decay)
    c = jnp.where(jnp.asarray(grid.kind == KIND_DIFFUSE), DIFFUSE_BACKGROUND_C, c)
    return jnp.where(jnp.asarray(grid.kind == KIND_NONE), 0.0, c)

def log_likelihood(obs: Observation, grid, tables, flow_idx: int, params) -> jnp.ndarray:
    c = _predicted_concentration(obs, grid, tables, flow_idx, params)
    curve = params.detection[obs.method]
    if obs.result == "quantitative":
        mu = jnp.log(jnp.maximum(c * LAB_SCALE, 1.0))
        x = jnp.log(max(float(obs.value or 0.0), 1.0))
        return -0.5 * ((x - mu) / LAB_LOG_SD) ** 2 - jnp.log(LAB_LOG_SD)
    p = _detect_prob(c, curve, obs.observer_reliability)
    p = jnp.clip(p, 1e-6, 1 - 1e-6)
    return jnp.log(p) if obs.result == "positive" else jnp.log1p(-p)

def total_log_likelihood(observations, grid, tables, flow_idx: int, params) -> jnp.ndarray:
    acc = jnp.zeros(grid.H)
    for o in observations:
        acc = acc + log_likelihood(o, grid, tables, flow_idx, params)
    return acc
```

- [ ] **Step 4: Implement `evidence_view.py` (retractions applied here, not in SQL)**

```python
# services/kernel/upstream_kernel/evidence_view.py
"""Turn the raw event list into the observation set the model consumes.

GC-5: retracted evidence is excluded here. The events themselves are never deleted, so a
belief replay to a moment before the retraction still sees the original observation.
"""
from __future__ import annotations
import numpy as np
from .model.likelihood import Observation

def build_observations(events, net, params, observer_reliability: dict[str, float] | None = None
                       ) -> list[Observation]:
    reliability = observer_reliability or {}
    retracted: set[str] = {str(e.payload["retracts_event_id"])
                           for e in events if e.event_type == "EvidenceRetracted"}
    out: list[Observation] = []
    for e in events:
        if e.event_type != "EvidenceRecorded" or str(e.event_id) in retracted:
            continue
        p = e.payload
        node = p["node_id"]
        if node not in net.node_index:
            continue                                  # network changed under us; skip cleanly
        out.append(Observation(
            event_id=str(e.event_id), node_idx=net.node_index[node],
            t_obs=e.event_time.timestamp(), method=p["method"], result=p["result"],
            value=p.get("value"),
            observer_reliability=reliability.get(p["observer_id"],
                                                 params.observer_reliability_default),
            window_start=None, window_end=None))
    return out
```

- [ ] **Step 5: Run the tests**

```bash
pytest services/kernel/tests/test_likelihood.py -v
```

Expected: 7 passed.

- [ ] **Step 6: Commit**

```bash
git add services/kernel/upstream_kernel/model/likelihood.py services/kernel/upstream_kernel/evidence_view.py services/kernel/tests/test_likelihood.py
git commit -m "feat(kernel): detection-curve likelihood with negative and quantitative evidence"
```

---

### Task 4.4: Posterior, fingerprint and the computed explanation

**Files:**
- Create: `services/kernel/upstream_kernel/model/posterior.py`, `services/kernel/upstream_kernel/{trace.py,fingerprint.py}`
- Test: `services/kernel/tests/test_posterior.py`

**Interfaces:**
- Produces:
  ```python
  @dataclass(frozen=True)
  class Posterior:
      log_p: np.ndarray            # (H,) normalised
      p_event: float
      grid: HypothesisGrid
      flow_idx: int
      network_version: str; params_version: str; kernel_version: str
      fingerprint: str

  def compute_posterior(observations, net, grid, tables, prior_inputs, params, *,
                        flow_idx: int, kernel_version: str, stream: str) -> Posterior

  def source_marginals(post, net) -> dict[str, float]     # entry_id -> p, plus
                                                          # "__diffuse__" and "__none__"
  def source_corridors(post, net, top_k: int = 3) -> list[Corridor]
  def explain(post, observations, net, grid, tables, params, top_k: int = 3) -> dict
  def fingerprint(evidence_ids, *, network_version, params_version,
                  kernel_version, stream, horizon_start, horizon_end) -> str
  ```

- [ ] **Step 1: Write the failing test**

```python
# services/kernel/tests/test_posterior.py
import datetime as dt, time, numpy as np, pytest
from upstream_kernel.compile.compiler import compile_network
from upstream_kernel.physics.params import default_params, FLOW_CONDITIONS
from upstream_kernel.physics.tables import build_tables
from upstream_kernel.model.hypotheses import build_grid, KIND_NONE
from upstream_kernel.model.priors import PriorInputs
from upstream_kernel.model.likelihood import Observation
from upstream_kernel.model.posterior import compute_posterior, source_marginals
from upstream_kernel.trace import explain, source_corridors
from upstream_kernel.fingerprint import fingerprint
from .fixtures_network import toy_gdfs

@pytest.fixture
def ctx():
    net = compile_network(*toy_gdfs(), catchment_id="toy")
    params = default_params(); tables = build_tables(net, params)
    end = dt.datetime(2026, 9, 22, 3, tzinfo=dt.UTC)
    grid = build_grid(net, horizon_start=end - dt.timedelta(hours=3), horizon_end=end)
    B = int((grid.horizon_end - grid.horizon_start) // grid.bin_s)
    pi = PriorInputs(np.full(B, FLOW_CONDITIONS.index("storm"), np.int8), np.full(B, 40.0),
                     np.zeros(len(net.entry_idx), np.int32), np.zeros(len(net.entry_idx)))
    return net, params, tables, grid, pi

def _obs(net, node, t, result, eid="e", method="citizen_visual_olfactory"):
    return Observation(eid, net.node_index[node], t, method, result, None, 0.9, None, None)

def _run(ctx, obs):
    net, params, tables, grid, pi = ctx
    return compute_posterior(obs, net, grid, tables, pi, params,
                             flow_idx=FLOW_CONDITIONS.index("storm"),
                             kernel_version="test-1", stream="sim")

def test_posterior_is_normalised(ctx):
    post = _run(ctx, [])
    assert float(np.exp(post.log_p).sum()) == pytest.approx(1.0, rel=1e-9)

def test_no_evidence_means_p_event_stays_at_the_prior(ctx):
    assert _run(ctx, []).p_event < 0.1

def test_one_positive_report_raises_p_event(ctx):
    net, *_ , grid, _ = ctx
    post = _run(ctx, [_obs(net, "J9", grid.horizon_end - 900, "positive")])
    assert post.p_event > _run(ctx, []).p_event

def test_negative_evidence_upstream_eliminates_that_branch(ctx):
    """PRD 10.5: volunteer at J4 reports 'looks normal' -> the O9 branch goes dark."""
    net, _, _, grid, _ = ctx
    t = grid.horizon_end - 900
    positive_only = _run(ctx, [_obs(net, "ZA", t, "positive", "a")])
    with_negative = _run(ctx, [_obs(net, "ZA", t, "positive", "a"),
                               _obs(net, "J9", t - 600, "negative", "b")])
    m0 = source_marginals(positive_only, net); m1 = source_marginals(with_negative, net)
    assert m1["O9"] < m0["O9"]

def test_marginals_sum_to_one_including_special_hypotheses(ctx):
    m = source_marginals(_run(ctx, []), net=ctx[0])
    assert sum(m.values()) == pytest.approx(1.0, rel=1e-9)
    assert "__diffuse__" in m and "__none__" in m

def test_recompute_is_order_independent(ctx):
    """GC-6: recompute from the full set; late and out-of-order data is not special."""
    net, _, _, grid, _ = ctx
    a = _obs(net, "ZA", grid.horizon_end - 900, "positive", "a")
    b = _obs(net, "J9", grid.horizon_end - 1500, "negative", "b")
    assert np.allclose(_run(ctx, [a, b]).log_p, _run(ctx, [b, a]).log_p, atol=1e-12)

def test_fingerprint_is_reproducible_and_input_sensitive():
    kw = dict(network_version="n1", params_version="p1", kernel_version="k1",
              stream="sim", horizon_start=0.0, horizon_end=3600.0)
    assert fingerprint(["a", "b"], **kw) == fingerprint(["b", "a"], **kw)   # order-insensitive
    assert fingerprint(["a"], **kw) != fingerprint(["a", "b"], **kw)
    assert fingerprint(["a"], **kw) != fingerprint(["a"], **{**kw, "kernel_version": "k2"})

def test_bitwise_reproducibility_of_the_posterior(ctx):
    net, _, _, grid, _ = ctx
    obs = [_obs(net, "ZA", grid.horizon_end - 900, "positive", "a")]
    a, b = _run(ctx, obs), _run(ctx, obs)
    assert a.fingerprint == b.fingerprint
    assert np.array_equal(a.log_p, b.log_p), "GC-6 requires bit-for-bit equality"

def test_explanation_cites_real_observations_and_computed_numbers(ctx):
    net, params, tables, grid, _ = ctx
    obs = [_obs(net, "ZA", grid.horizon_end - 900, "positive", "a"),
           _obs(net, "J9", grid.horizon_end - 1500, "negative", "b")]
    post = _run(ctx, obs)
    ex = explain(post, obs, net, grid, tables, params)
    top = ex["candidates"][0]
    assert {"entry_id", "probability", "supported_by", "eliminated_rivals_by"} <= set(top)
    assert all(s["event_id"] in {"a", "b"} for s in top["supported_by"])

@pytest.mark.slow
def test_full_scale_recompute_is_under_the_latency_budget():
    """NFR-1: evidence -> posterior p95 < 5 s, measured at PRD scale
    (40 entries x 96 bins x 3 durations ~ 11.5k hypotheses, 300 observations)."""
    from .fixtures_network import line_network_gdfs
    net = compile_network(*line_network_gdfs(n_nodes=400, n_entries=40), catchment_id="big")
    params = default_params(); tables = build_tables(net, params)
    end = dt.datetime(2026, 9, 22, 6, tzinfo=dt.UTC)
    grid = build_grid(net, horizon_start=end - dt.timedelta(hours=24), horizon_end=end)
    assert 11_000 <= grid.H <= 12_000
    B = int((grid.horizon_end - grid.horizon_start) // grid.bin_s)
    pi = PriorInputs(np.zeros(B, np.int8), np.full(B, 24.0),
                     np.zeros(40, np.int32), np.zeros(40))
    rng = np.random.default_rng(1)
    obs = [_obs(net, net.node_ids[int(rng.integers(0, 400))],
                grid.horizon_end - float(rng.uniform(0, 7200)),
                "positive" if rng.random() < 0.3 else "negative", eid=f"e{i}")
           for i in range(300)]

    compute_posterior(obs, net, grid, tables, pi, params, flow_idx=0,
                      kernel_version="t", stream="sim")          # warm the JIT cache
    times = []
    for _ in range(10):
        t0 = time.perf_counter()
        compute_posterior(obs, net, grid, tables, pi, params, flow_idx=0,
                          kernel_version="t", stream="sim")
        times.append(time.perf_counter() - t0)
    assert float(np.percentile(times, 95)) < 5.0, f"p95 was {np.percentile(times,95):.2f}s"
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest services/kernel/tests/test_posterior.py -v
```

Expected: FAIL — modules missing.

- [ ] **Step 3: Implement `fingerprint.py`**

```python
# services/kernel/upstream_kernel/fingerprint.py
"""GC-6: a posterior is reproducible from its fingerprint alone."""
import hashlib, json

def fingerprint(evidence_ids, *, network_version: str, params_version: str,
                kernel_version: str, stream: str,
                horizon_start: float, horizon_end: float) -> str:
    canon = json.dumps({
        "evidence": sorted(str(e) for e in evidence_ids),
        "network_version": network_version,
        "params_version": params_version,
        "kernel_version": kernel_version,
        "stream": stream,
        "horizon": [round(horizon_start, 3), round(horizon_end, 3)],
    }, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canon.encode()).hexdigest()
```

- [ ] **Step 4: Implement `posterior.py`**

```python
# services/kernel/upstream_kernel/model/posterior.py
"""Exact posterior over all hypotheses. Recomputed from scratch every time (GC-6)."""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
from scipy.special import logsumexp
from .hypotheses import KIND_NONE, KIND_DIFFUSE, KIND_POINT
from .priors import log_prior
from .likelihood import total_log_likelihood
from ..fingerprint import fingerprint as make_fingerprint

@dataclass(frozen=True)
class Posterior:
    log_p: np.ndarray
    p_event: float
    grid: object
    flow_idx: int
    network_version: str
    params_version: str
    kernel_version: str
    fingerprint: str

def compute_posterior(observations, net, grid, tables, prior_inputs, params, *,
                      flow_idx: int, kernel_version: str, stream: str) -> Posterior:
    lp = log_prior(net, grid, prior_inputs, params)
    if observations:
        lp = lp + np.asarray(total_log_likelihood(observations, grid, tables, flow_idx, params),
                             dtype=np.float64)
    lp = lp - logsumexp(lp)
    p_none = float(np.exp(lp[grid.kind == KIND_NONE][0]))
    return Posterior(log_p=lp, p_event=1.0 - p_none, grid=grid, flow_idx=flow_idx,
                     network_version=net.version, params_version=params.version,
                     kernel_version=kernel_version,
                     fingerprint=make_fingerprint(
                         [o.event_id for o in observations],
                         network_version=net.version, params_version=params.version,
                         kernel_version=kernel_version, stream=stream,
                         horizon_start=grid.horizon_start, horizon_end=grid.horizon_end))

def source_marginals(post: Posterior, net) -> dict[str, float]:
    """P(entry point), summed over start times and durations (PRD 7.3)."""
    p = np.exp(post.log_p); g = post.grid
    out = {"__diffuse__": float(p[g.kind == KIND_DIFFUSE].sum()),
           "__none__": float(p[g.kind == KIND_NONE][0])}
    pts = g.kind == KIND_POINT
    for k, entry_id in enumerate(net.entry_nodes):
        out[entry_id] = float(p[pts & (g.entry_k == k)].sum())
    return out

def start_time_credible_interval(post: Posterior, net, entry_id: str | None = None,
                                 q: float = 0.80) -> tuple[float, float]:
    """Credible interval on the event start time, for the episode's est_start_lo/hi."""
    p = np.exp(post.log_p); g = post.grid
    mask = g.kind == KIND_POINT
    if entry_id is not None:
        mask = mask & (g.entry_k == net.entry_nodes.index(entry_id))
    w = p[mask]; t = g.t0[mask]
    if w.sum() <= 0:
        return (g.horizon_start, g.horizon_end)
    order = np.argsort(t)
    t, w = t[order], w[order] / w.sum()
    c = np.cumsum(w); lo_q, hi_q = (1 - q) / 2, 1 - (1 - q) / 2
    return float(t[np.searchsorted(c, lo_q)]), float(t[min(np.searchsorted(c, hi_q), len(t)-1)])
```

- [ ] **Step 5: Implement `trace.py` (corridors + the computed explanation)**

```python
# services/kernel/upstream_kernel/trace.py
"""TRACE: rank source corridors and explain the ranking from the model, not from an LLM.

PRD 7.3: "for each top candidate, the observations that most supported it and the
observations that eliminated its rivals. This explanation is computed from the model."
"""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
from scipy.special import logsumexp
from .model.hypotheses import KIND_POINT
from .model.likelihood import log_likelihood
from .model.posterior import source_marginals

@dataclass(frozen=True)
class Corridor:
    entry_id: str
    probability: float
    node_path: tuple[str, ...]

def source_corridors(post, net, top_k: int = 3) -> list[Corridor]:
    m = source_marginals(post, net)
    ranked = sorted(((k, v) for k, v in m.items() if not k.startswith("__")),
                    key=lambda kv: -kv[1])[:top_k]
    out = []
    for entry_id, p in ranked:
        i = net.node_index[entry_id]
        path = [entry_id] + [net.node_ids[int(net.edges[e][1])]
                             for e in net.downstream_path[i]]
        out.append(Corridor(entry_id=entry_id, probability=float(p),
                            node_path=tuple(path)))
    return out

def explain(post, observations, net, grid, tables, params, top_k: int = 3) -> dict:
    """For each top candidate, the log-evidence each observation contributed to it,
    and the log-evidence it removed from that candidate's closest rival."""
    corridors = source_corridors(post, net, top_k)
    per_obs = {o.event_id: np.asarray(log_likelihood(o, grid, tables, post.flow_idx, params))
               for o in observations}
    lp_prior_only = post.log_p - sum(per_obs.values()) if per_obs else post.log_p

    def group_ll(arr, k):
        mask = (grid.kind == KIND_POINT) & (grid.entry_k == k)
        w = np.exp(lp_prior_only[mask] - logsumexp(lp_prior_only[mask]))
        return float(np.sum(w * arr[mask]))

    candidates = []
    for rank, c in enumerate(corridors):
        k = net.entry_nodes.index(c.entry_id)
        rivals = [x for x in corridors if x.entry_id != c.entry_id]
        rival_k = net.entry_nodes.index(rivals[0].entry_id) if rivals else k
        supported, eliminated = [], []
        for eid, arr in per_obs.items():
            mine = group_ll(arr, k)
            theirs = group_ll(arr, rival_k)
            entry = {"event_id": eid, "log_evidence": round(mine, 4),
                     "relative_to_rival": round(mine - theirs, 4)}
            (supported if mine - theirs > 0 else eliminated).append(entry)
        supported.sort(key=lambda e: -e["relative_to_rival"])
        eliminated.sort(key=lambda e: e["relative_to_rival"])
        candidates.append({
            "rank": rank + 1, "entry_id": c.entry_id, "probability": round(c.probability, 4),
            "node_path": list(c.node_path),
            "supported_by": supported[:5],
            "eliminated_rivals_by": eliminated[:5],
        })
    return {"candidates": candidates,
            "p_event": round(post.p_event, 4),
            "kernel_version": post.kernel_version,
            "fingerprint": post.fingerprint}
```

- [ ] **Step 6: Run the tests**

```bash
pytest services/kernel/tests/test_posterior.py -v -m "not slow"
pytest services/kernel/tests/test_posterior.py -v -m slow
```

Expected: 9 passed, then the latency test passes under 5 s.

- [ ] **Step 7: Commit**

```bash
git add services/kernel/
git commit -m "feat(kernel): exact posterior, source marginals, fingerprint, computed explanation"
```

---

### Task 4.5: Kernel worker — LISTEN/NOTIFY, snapshots, `PosteriorComputed`

**Files:**
- Create: `services/kernel/upstream_kernel/worker.py`
- Test: `services/kernel/tests/test_worker.py`

**Interfaces:**
- Consumes: everything above.
- Produces: rows in `posterior_snapshots`; `PosteriorComputed` events carrying `{fingerprint, p_event, as_of_seq, top_sources}`.
- The worker is the **only** writer of `posterior_snapshots` and never touches `episodes` (enforced by `kernel_role` grants from Phase 0).

- [ ] **Step 1: Write the failing test**

```python
# services/kernel/tests/test_worker.py
import datetime as dt, pytest
from upstream_kernel.worker import KernelWorker

pytestmark = pytest.mark.integration

def test_worker_writes_a_snapshot_after_new_evidence(kernel_worker, post_evidence, db_conn):
    post_evidence(node_id="O14", result="positive")
    kernel_worker.process_once()
    with db_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM posterior_snapshots")
        assert cur.fetchone()[0] == 1

def test_worker_emits_posterior_computed_with_a_fingerprint(kernel_worker, post_evidence, db_conn):
    post_evidence(node_id="O14", result="positive")
    kernel_worker.process_once()
    with db_conn.cursor() as cur:
        cur.execute("SELECT payload FROM events WHERE event_type='PosteriorComputed'")
        p = cur.fetchone()[0]
    assert p["fingerprint"].startswith("sha256:") and 0 <= p["p_event"] <= 1

def test_worker_advances_its_consumer_position(kernel_worker, post_evidence, db_conn):
    post_evidence(node_id="O14", result="positive")
    kernel_worker.process_once()
    with db_conn.cursor() as cur:
        cur.execute("SELECT last_seq FROM consumer_positions WHERE consumer='kernel'")
        assert cur.fetchone()[0] > 0

def test_reprocessing_the_same_evidence_yields_the_same_fingerprint(kernel_worker,
                                                                    post_evidence, db_conn):
    post_evidence(node_id="O14", result="positive")
    kernel_worker.process_once()
    kernel_worker.reset_position()
    kernel_worker.process_once()
    with db_conn.cursor() as cur:
        cur.execute("SELECT DISTINCT fingerprint FROM posterior_snapshots")
        assert len(cur.fetchall()) == 1

def test_belief_replay_returns_the_state_at_a_past_moment(kernel_worker, post_evidence, db_conn):
    post_evidence(node_id="O14", result="positive"); kernel_worker.process_once()
    t_mid = dt.datetime.now(dt.UTC)
    post_evidence(node_id="J9", result="negative");  kernel_worker.process_once()
    with db_conn.cursor() as cur:
        cur.execute("SELECT p_event FROM posterior_snapshots WHERE ts <= %s "
                    "ORDER BY ts DESC LIMIT 1", (t_mid,))
        early = cur.fetchone()[0]
        cur.execute("SELECT p_event FROM posterior_snapshots ORDER BY ts DESC LIMIT 1")
        latest = cur.fetchone()[0]
    assert early != latest
```

- [ ] **Step 2: Run to verify failure**

```bash
docker compose run --rm kernel pytest services/kernel/tests/test_worker.py -v
```

Expected: FAIL — module missing.

- [ ] **Step 3: Implement `worker.py`**

```python
# services/kernel/upstream_kernel/worker.py
"""Layer 4 (PRD 10.4): wake on new events, recompute everything, write a snapshot.

Deliberately dumb: no incremental state, no caches keyed on evidence. Every wake-up reloads
the full evidence set for the horizon and recomputes (GC-6). At ~11.5k hypotheses this is a
few million multiplications — milliseconds.
"""
from __future__ import annotations
import datetime as dt, json, os, select, uuid
import numpy as np
import psycopg
from psycopg.types.json import Json
from .compile.loader import load_network
from .physics.params import default_params, FLOW_CONDITIONS
from .physics.tables import load_tables
from .model.hypotheses import build_grid
from .model.priors import PriorInputs
from .model.posterior import compute_posterior, source_marginals, start_time_credible_interval
from .evidence_view import build_observations
from .trace import explain
from .pulse import pulse                 # Phase 5
from .probe import probe                 # Phase 5

KERNEL_VERSION = "upstream-kernel 0.1.0"
HORIZON_HOURS = 24
CONSUMER = "kernel"

class KernelWorker:
    def __init__(self, dsn: str, catchment_id: str, stream: str = "live"):
        self.dsn, self.catchment_id, self.stream = dsn, catchment_id, stream
        self.net = load_network(os.environ.get("NETWORK_ARTIFACT", "data/artifacts/network.npz"))
        self.tables = load_tables(os.environ.get("TABLES_ARTIFACT", "data/artifacts/tables.npz"))
        self.params = default_params()
        self.conn = psycopg.connect(dsn, autocommit=True)

    # --- main loop -------------------------------------------------------
    def run(self) -> None:
        with self.conn.cursor() as cur:
            cur.execute("LISTEN events")
        self.process_once()
        while True:
            if select.select([self.conn], [], [], 5.0)[0]:
                self.conn.execute("SELECT 1")          # drain notifies
                list(self.conn.notifies(timeout=0.1))
            self.process_once()

    def process_once(self) -> None:
        last = self._position()
        events = self._read_events()
        if not events or events[-1].seq <= last:
            return
        post, extras = self._recompute(events)
        self._write_snapshot(post, extras, as_of_seq=events[-1].seq)
        self._set_position(events[-1].seq)

    # --- computation -----------------------------------------------------
    def _recompute(self, events):
        now = dt.datetime.now(dt.UTC)
        horizon_start = now - dt.timedelta(hours=HORIZON_HOURS)
        grid = build_grid(self.net, horizon_start=horizon_start, horizon_end=now)
        flow_idx, prior_inputs = self._flow_and_priors(grid)
        obs = build_observations(events, self.net, self.params)
        post = compute_posterior(obs, self.net, grid, self.tables, prior_inputs, self.params,
                                 flow_idx=flow_idx, kernel_version=KERNEL_VERSION,
                                 stream=self.stream)
        zones = pulse(post, self.net, self.tables, self.params)
        candidates = probe(post, self.net, self.tables, self.params, zones, now=now)
        ex = explain(post, obs, self.net, grid, self.tables, self.params)
        lo, hi = start_time_credible_interval(post, self.net)
        return post, {"zones": zones, "probe": candidates, "explanation": ex,
                      "est_start": (lo, hi),
                      "marginals": source_marginals(post, self.net)}

    def _flow_and_priors(self, grid):
        B = int((grid.horizon_end - grid.horizon_start) // grid.bin_s)
        cond = np.full(B, FLOW_CONDITIONS.index("dry"), dtype=np.int8)
        dry = np.full(B, 24.0)
        with self.conn.cursor() as cur:
            cur.execute("""SELECT ts, flow_condition, coalesce(antecedent_dry_h,24)
                           FROM rainfall WHERE catchment_id=%s AND stream=%s
                             AND ts >= to_timestamp(%s) AND ts < to_timestamp(%s)""",
                        (self.catchment_id, self.stream, grid.horizon_start, grid.horizon_end))
            for ts, fc, adh in cur.fetchall():
                b = int((ts.timestamp() - grid.horizon_start) // grid.bin_s)
                if 0 <= b < B:
                    cond[b] = FLOW_CONDITIONS.index(fc); dry[b] = adh
        K = len(self.net.entry_idx)
        inputs = PriorInputs(cond, dry, self._past_episode_counts(K), np.zeros(K))
        return int(cond[-1]), inputs

    def _past_episode_counts(self, K: int) -> np.ndarray:
        """Filled by Phase 11 pooling; zeros until then."""
        counts = np.zeros(K, dtype=np.int32)
        with self.conn.cursor() as cur:
            cur.execute("SELECT summary->>'top_source', count(*) FROM episodes "
                        "WHERE state IN ('CONFIRMED','RESOLVED') GROUP BY 1")
            for entry_id, n in cur.fetchall():
                if entry_id in self.net.entry_nodes:
                    counts[self.net.entry_nodes.index(entry_id)] = n
        return counts

    # --- persistence -----------------------------------------------------
    def _write_snapshot(self, post, extras, *, as_of_seq: int) -> None:
        now = dt.datetime.now(dt.UTC)
        with self.conn.cursor() as cur:
            cur.execute("""INSERT INTO posterior_snapshots
                (ts,fingerprint,episode_id,catchment_id,stream,as_of_seq,network_version,
                 kernel_version,params_version,p_event,source_marginals,zone_windows,
                 probe_candidates,explanation)
                VALUES (%s,%s,NULL,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (now, post.fingerprint, self.catchment_id, self.stream, as_of_seq,
                 post.network_version, post.kernel_version, post.params_version,
                 post.p_event, Json(extras["marginals"]), Json(extras["zones"]),
                 Json(extras["probe"]), Json(extras["explanation"])))
            top = sorted(((k, v) for k, v in extras["marginals"].items()
                          if not k.startswith("__")), key=lambda kv: -kv[1])[:3]
            cur.execute("SELECT append_event(%s,%s,%s,'PosteriorComputed',1,%s,%s,NULL,NULL)",
                        (uuid.uuid4(), self.stream, self.catchment_id, now,
                         Json({"fingerprint": post.fingerprint, "p_event": post.p_event,
                               "as_of_seq": as_of_seq, "top_sources": top,
                               "est_start": [extras["est_start"][0], extras["est_start"][1]],
                               "zone_windows": extras["zones"],
                               "probe_candidates": extras["probe"][:5]})))

    def _read_events(self):
        from collections import namedtuple
        E = namedtuple("E", "seq event_id event_type event_time payload")
        horizon = dt.datetime.now(dt.UTC) - dt.timedelta(hours=HORIZON_HOURS)
        with self.conn.cursor() as cur:
            cur.execute("""SELECT seq,event_id,event_type,event_time,payload FROM events
                           WHERE catchment_id=%s AND stream=%s
                             AND event_type IN ('EvidenceRecorded','EvidenceRetracted')
                             AND event_time >= %s ORDER BY seq""",
                        (self.catchment_id, self.stream, horizon))
            return [E(*r) for r in cur.fetchall()]

    def _position(self) -> int:
        with self.conn.cursor() as cur:
            cur.execute("SELECT last_seq FROM consumer_positions WHERE consumer=%s", (CONSUMER,))
            row = cur.fetchone()
            return row[0] if row else 0

    def _set_position(self, seq: int) -> None:
        with self.conn.cursor() as cur:
            cur.execute("""INSERT INTO consumer_positions (consumer,last_seq,updated_at)
                           VALUES (%s,%s,now()) ON CONFLICT (consumer)
                           DO UPDATE SET last_seq=EXCLUDED.last_seq, updated_at=now()""",
                        (CONSUMER, seq))

    def reset_position(self) -> None:
        self._set_position(0)

def main() -> None:
    KernelWorker(os.environ["KERNEL_DATABASE_URL"], os.environ["CATCHMENT_ID"]).run()

if __name__ == "__main__":
    main()
```

> `pulse` and `probe` are implemented in Phase 5. Until then, stub them as
> `def pulse(*a, **k): return {}` / `def probe(*a, **k): return []` so Phase 4's tests run.

- [ ] **Step 4: Run the tests**

```bash
docker compose run --rm kernel pytest services/kernel/tests/test_worker.py -v
```

Expected: 5 passed.

- [ ] **Step 5: End-to-end smoke test**

```bash
docker compose up -d
curl -X POST localhost:8000/ingest/report/confirm -H 'content-type: application/json' -d '{
  "node_id":"O14","observed_at":"'$(date -u +%Y-%m-%dT%H:%M:%SZ)'",
  "method":"citizen_visual_olfactory","result":"positive","observer_id":"vol-1",
  "observer_type":"citizen","snap_distance_m":3.0,"confirmed_by_observer":true}'
sleep 3
docker compose exec db psql -U upstream -d upstream -c \
  "SELECT p_event, left(fingerprint,20), source_marginals FROM posterior_snapshots ORDER BY ts DESC LIMIT 1;"
```

Expected: one row, `p_event` above the no-evidence baseline, a `sha256:` fingerprint.

- [ ] **Step 6: Commit**

```bash
git add services/kernel/
git commit -m "feat(kernel): LISTEN/NOTIFY worker writing fingerprinted posterior snapshots"
```

## Phase 4 exit criteria

- 27 kernel tests pass, including the two that matter most: **negative evidence eliminates a branch**, and **the same evidence produces a bit-identical posterior and fingerprint**.
- `posterior_snapshots` gains a row within ~3 s of an ingested report; a `PosteriorComputed` event accompanies it.
- Recompute is order-independent (late data is not a special case).
- The slow test shows p95 recompute < 5 s at PRD scale (NFR-1).
- The explanation cites real `event_id`s and model-computed log-evidence — no prose generation anywhere (PRD §7.3, §7.8).

## 🔑 Credentials needed at the end of Phase 4

**None.** The kernel is pure computation over the event log.

---

# Phase 5 — PULSE and PROBE (EC²) + routing

**Day 3, morning (≈5 h).** Where the posterior becomes an action.

**PRD coverage:** §7.4 (PULSE), §7.5 (PROBE, EC², Protect/Enforce, safety constraints, routing), FR-14, FR-15, FR-16, FR-17, G2, G3, GC-11.

## File structure

```
services/kernel/upstream_kernel/
├── pulse.py        # zone exposure curves + 80% credible windows + pathways
├── ec2.py          # Equivalence Class Edge Cutting (pure, no I/O)
├── probe.py        # candidate generation, safety filter, EC² scoring
└── safety.py       # PRD 7.5 mission safety constraints
services/core-api/upstream_api/
└── routing.py      # OR-Tools assignment over pgRouting walking times
```

---

### Task 5.1: PULSE — exposure probability curves and 80% credible windows

**Files:**
- Create: `services/kernel/upstream_kernel/pulse.py`
- Test: `services/kernel/tests/test_pulse.py`

**Interfaces:**
- Produces:
  ```python
  EXPOSURE_THRESHOLD_C = 0.05    # relative concentration counted as "exposed"

  @dataclass(frozen=True)
  class ZoneExposure:
      zone_id: str
      t_grid: list[float]          # epoch seconds, 5-minute steps over the forward horizon
      p_exposed: list[float]       # P(concentration > threshold at t)
      window_lo: float | None      # 80% credible window on arrival, None if p_peak < 0.05
      window_hi: float | None
      p_peak: float
      pathways: list[str]

  def pulse(post, net, tables, params, *, forward_hours: int = 12,
            step_s: int = 300) -> dict[str, dict]   # zone_id -> ZoneExposure as a dict
  ```

- [ ] **Step 1: Write the failing test**

```python
# services/kernel/tests/test_pulse.py — key assertions
def test_downstream_zone_window_starts_later_than_the_nearer_one(ctx_with_strong_o14_belief):
    z = pulse(post, net, tables, params)
    assert z["ZONE_A"]["window_lo"] < z["ZONE_B"]["window_lo"]

def test_window_is_an_80_percent_credible_interval(ctx_with_strong_o14_belief):
    z = pulse(post, net, tables, params)["ZONE_A"]
    t, p = np.array(z["t_grid"]), np.array(z["p_exposed"])
    inside = p[(t >= z["window_lo"]) & (t <= z["window_hi"])].sum()
    assert 0.78 <= inside / p.sum() <= 0.82

def test_uncertain_posterior_gives_a_wider_window_than_a_sharp_one(flat_post, sharp_post):
    w = lambda p: pulse(p, net, tables, params)["ZONE_A"]
    assert (w(flat_post)["window_hi"] - w(flat_post)["window_lo"]) > \
           (w(sharp_post)["window_hi"] - w(sharp_post)["window_lo"])

def test_zone_with_no_credible_exposure_returns_no_window(ctx_no_evidence):
    assert pulse(post, net, tables, params)["ZONE_A"]["window_lo"] is None

def test_pathways_come_from_zone_attributes(ctx_with_strong_o14_belief):
    assert pulse(post, net, tables, params)["ZONE_B"]["pathways"] == ["animal_contact", "floodwater"]

def test_storm_flow_adds_floodwater_pathway(ctx_storm):
    """PRD 7.9 role 4."""
    assert "floodwater" in pulse(post, net, tables, params)["ZONE_A"]["pathways"]
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest services/kernel/tests/test_pulse.py -v
```

Expected: FAIL — module missing.

- [ ] **Step 3: Implement `pulse.py`**

```python
# services/kernel/upstream_kernel/pulse.py
"""PULSE: push the posterior forward to every receptor zone (PRD 7.4).

For each zone and each future time step we ask: summing over hypotheses weighted by their
posterior probability, what is the chance the concentration there exceeds the exposure
threshold? The 80% credible window is the narrowest central interval of the resulting
arrival-time distribution (GC-11).
"""
from __future__ import annotations
import numpy as np
import jax.numpy as jnp
from .physics.transport import concentration
from .model.hypotheses import KIND_NONE, KIND_DIFFUSE
from upstream_shared.codes import ExposurePathway
from .physics.params import FLOW_CONDITIONS

EXPOSURE_THRESHOLD_C = 0.05

def pulse(post, net, tables, params, *, forward_hours: int = 12, step_s: int = 300) -> dict:
    p = np.exp(post.log_p)
    g = post.grid
    f = post.flow_idx
    decay = params.decay_per_hour["fecal_indicator"] / 3600.0
    k = np.clip(g.entry_k, 0, None)
    t_grid = np.arange(g.horizon_end - 3600, g.horizon_end + forward_hours * 3600, step_s,
                       dtype=np.float64)
    storm = FLOW_CONDITIONS[f] == "storm"

    out: dict[str, dict] = {}
    for z, zone_id in enumerate(net.zone_ids):
        node = int(net.zone_node_idx[z])
        tau = jnp.asarray(tables.tau[f, k, node])
        sigma = jnp.asarray(tables.sigma[f, k, node])
        dil = jnp.asarray(tables.dilution[f, k, node])
        reach = jnp.asarray(tables.reachable[f, k, node])
        p_exposed = []
        for t in t_grid:
            c = np.asarray(concentration(tau, sigma, dil, reach,
                                         t0=jnp.asarray(np.nan_to_num(g.t0)),
                                         duration_s=jnp.asarray(g.duration_s),
                                         mass=jnp.asarray(g.mass),
                                         t_obs=float(t), decay_per_s=decay))
            c = np.where(g.kind == KIND_DIFFUSE, 0.10, c)
            c = np.where(g.kind == KIND_NONE, 0.0, c)
            p_exposed.append(float(p[c > EXPOSURE_THRESHOLD_C].sum()))
        p_exposed = np.asarray(p_exposed)
        lo, hi = _credible_window(t_grid, p_exposed, q=0.80)
        pathways = list(net.zone_pathways[z])
        if storm and ExposurePathway.FLOODWATER.value not in pathways:
            pathways.append(ExposurePathway.FLOODWATER.value)     # PRD 7.9 role 4
        out[zone_id] = {"zone_id": zone_id, "t_grid": t_grid.tolist(),
                        "p_exposed": p_exposed.tolist(),
                        "window_lo": lo, "window_hi": hi,
                        "p_peak": float(p_exposed.max()), "pathways": pathways}
    return out

def _credible_window(t, w, q: float = 0.80):
    """Narrowest central interval holding q of the exposure-probability mass."""
    if w.max() < 0.05 or w.sum() <= 0:
        return None, None
    c = np.cumsum(w) / w.sum()
    lo_i = int(np.searchsorted(c, (1 - q) / 2))
    hi_i = int(min(np.searchsorted(c, 1 - (1 - q) / 2), len(t) - 1))
    return float(t[lo_i]), float(t[hi_i])
```

- [ ] **Step 4: Run tests, then commit**

```bash
pytest services/kernel/tests/test_pulse.py -v
git add services/kernel/upstream_kernel/pulse.py services/kernel/tests/test_pulse.py
git commit -m "feat(kernel): PULSE zone exposure curves with 80% credible windows"
```

---

### Task 5.2: EC² — Equivalence Class Edge Cutting

The differentiator against every heuristic-weights competitor (PRD §3.4). Keep it pure and
separately testable.

**Files:**
- Create: `services/kernel/upstream_kernel/ec2.py`
- Test: `services/kernel/tests/test_ec2.py`

**Interfaces:**
- Produces:
  ```python
  def edge_weight(p: np.ndarray, classes: np.ndarray) -> float
      # unnormalised cut weight: 0.5 * ((sum p)^2 - sum_c (sum_{h in c} p_h)^2)

  def expected_residual_weight(p, classes, outcome_probs: np.ndarray) -> float
      # outcome_probs: (O, H) = P(outcome o | h); returns sum_o W(p * outcome_probs[o])

  def ec2_gain(p, classes, outcome_probs) -> float
      # edge_weight(p, classes) - expected_residual_weight(...)

  def greedy_select(p, classes, candidate_outcome_probs: dict[str, np.ndarray],
                    costs: dict[str, float], k: int = 5) -> list[tuple[str, float]]
      # returns [(candidate_id, gain_per_unit_cost)], best first
  ```

- [ ] **Step 1: Write the failing test**

```python
# services/kernel/tests/test_ec2.py
import numpy as np, pytest
from upstream_kernel.ec2 import edge_weight, ec2_gain, greedy_select

def test_edge_weight_is_zero_when_all_mass_is_in_one_class():
    p = np.array([0.5, 0.5]); classes = np.array([0, 0])
    assert edge_weight(p, classes) == pytest.approx(0.0)

def test_edge_weight_is_maximal_for_an_even_split_across_classes():
    even = edge_weight(np.array([0.5, 0.5]), np.array([0, 1]))
    skewed = edge_weight(np.array([0.9, 0.1]), np.array([0, 1]))
    assert even > skewed

def test_a_test_that_perfectly_separates_two_classes_cuts_all_edges():
    p = np.array([0.5, 0.5]); classes = np.array([0, 1])
    # outcome 0 happens only under h0, outcome 1 only under h1
    outcomes = np.array([[1.0, 0.0], [0.0, 1.0]])
    assert ec2_gain(p, classes, outcomes) == pytest.approx(edge_weight(p, classes))

def test_an_uninformative_test_has_zero_gain():
    p = np.array([0.5, 0.5]); classes = np.array([0, 1])
    outcomes = np.array([[0.5, 0.5], [0.5, 0.5]])
    assert ec2_gain(p, classes, outcomes) == pytest.approx(0.0, abs=1e-12)

def test_ec2_ignores_a_test_that_only_separates_within_one_class():
    """This is the whole point of EC2 over information gain: distinguishing hypotheses
    that lead to the SAME decision is worth nothing."""
    p = np.array([0.25, 0.25, 0.5]); classes = np.array([0, 0, 1])
    within = np.array([[1.0, 0.0, 0.5], [0.0, 1.0, 0.5]])   # splits h0 from h1, same class
    across = np.array([[1.0, 1.0, 0.0], [0.0, 0.0, 1.0]])   # splits class 0 from class 1
    assert ec2_gain(p, classes, across) > ec2_gain(p, classes, within)

def test_gain_is_never_negative():
    rng = np.random.default_rng(0)
    for _ in range(50):
        p = rng.dirichlet(np.ones(8)); classes = rng.integers(0, 3, 8)
        o = rng.uniform(0.01, 0.99, 8); outcomes = np.stack([o, 1 - o])
        assert ec2_gain(p, classes, outcomes) >= -1e-12

def test_greedy_select_prefers_high_gain_per_cost():
    p = np.array([0.5, 0.5]); classes = np.array([0, 1])
    perfect = np.array([[1.0, 0.0], [0.0, 1.0]])
    cands = {"cheap_perfect": perfect, "expensive_perfect": perfect}
    picks = greedy_select(p, classes, cands, {"cheap_perfect": 60.0,
                                              "expensive_perfect": 600.0}, k=2)
    assert picks[0][0] == "cheap_perfect"
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest services/kernel/tests/test_ec2.py -v
```

Expected: FAIL — module missing.

- [ ] **Step 3: Implement `ec2.py`**

```python
# services/kernel/upstream_kernel/ec2.py
"""EC2 — Equivalence Class Edge Cutting (Golovin, Krause & Ray, NeurIPS 2010).

Hypotheses are grouped by the DECISION they imply. Imagine an edge between every pair of
hypotheses that sit in different groups, weighted by the product of their probabilities.
A test is worth exactly the edge weight it is expected to cut. Distinguishing two
hypotheses that lead to the same decision cuts no edges and therefore scores zero — which
is why EC2 beats plain information gain for this problem, and why it carries a
near-optimality guarantee under greedy selection.
"""
from __future__ import annotations
import numpy as np

def edge_weight(p: np.ndarray, classes: np.ndarray) -> float:
    total = float(p.sum())
    per_class = np.bincount(classes, weights=p)
    return 0.5 * (total ** 2 - float((per_class ** 2).sum()))

def expected_residual_weight(p: np.ndarray, classes: np.ndarray,
                             outcome_probs: np.ndarray) -> float:
    """Sum over outcomes of the (unnormalised) residual weight after seeing that outcome."""
    return float(sum(edge_weight(p * outcome_probs[o], classes)
                     for o in range(outcome_probs.shape[0])))

def ec2_gain(p: np.ndarray, classes: np.ndarray, outcome_probs: np.ndarray) -> float:
    return edge_weight(p, classes) - expected_residual_weight(p, classes, outcome_probs)

def greedy_select(p: np.ndarray, classes: np.ndarray,
                  candidate_outcome_probs: dict[str, np.ndarray],
                  costs: dict[str, float], k: int = 5) -> list[tuple[str, float]]:
    """Greedy adaptive-submodular selection, normalised by cost (walking seconds).

    After picking a candidate we condition p on its *expected* outcome so the next pick is
    not redundant. This is the standard greedy policy whose near-optimality EC2 guarantees.
    """
    remaining = dict(candidate_outcome_probs)
    p_work = p.copy()
    picks: list[tuple[str, float]] = []
    for _ in range(min(k, len(remaining))):
        scored = [(cid, ec2_gain(p_work, classes, op) / max(costs.get(cid, 1.0), 1.0))
                  for cid, op in remaining.items()]
        scored.sort(key=lambda x: -x[1])
        best_id, best_score = scored[0]
        if best_score <= 0:
            break
        picks.append((best_id, float(best_score)))
        op = remaining.pop(best_id)
        # Condition on the expected outcome: mixture weighted by each outcome's probability.
        po = np.array([float((p_work * op[o]).sum()) for o in range(op.shape[0])])
        po = po / max(po.sum(), 1e-300)
        p_work = p_work * np.einsum("o,oh->h", po, op)
        p_work = p_work / max(p_work.sum(), 1e-300)
    return picks
```

- [ ] **Step 4: Run tests, then commit**

```bash
pytest services/kernel/tests/test_ec2.py -v
git add services/kernel/upstream_kernel/ec2.py services/kernel/tests/test_ec2.py
git commit -m "feat(kernel): EC2 equivalence-class edge cutting with cost-normalised greedy"
```

---

### Task 5.3: PROBE — candidates, safety filter, Protect/Enforce modes

**Files:**
- Create: `services/kernel/upstream_kernel/{probe.py,safety.py}`
- Test: `services/kernel/tests/test_probe.py`

**Interfaces:**
- Produces:
  ```python
  @dataclass(frozen=True)
  class ProbeCandidate:
      candidate_id: str; node_id: str
      window_start: float; window_end: float
      methods: list[str]; mode: str
      ec2_gain: float; expected_effect: str      # plain-language line for the volunteer

  def decision_classes(post, net, tables, zones, mode: ProbeMode) -> np.ndarray  # (H,) int
  def probe(post, net, tables, params, zones, *, now, mode=ProbeMode.PROTECT,
            max_candidates: int = 5, reachable_within_s: float = 1800) -> list[dict]
  ```
  - **Protect** classes: the tuple of zones whose `p_exposed` peak crosses the warning
    threshold under that hypothesis → "which zones need a warning".
  - **Enforce** classes: the entry node → "which outfall should be inspected".

- [ ] **Step 1: Write the failing tests**

```python
# services/kernel/tests/test_probe.py — key assertions
def test_protect_and_enforce_produce_different_top_candidates(ctx):
    a = probe(post, net, tables, params, zones, now=now, mode=ProbeMode.PROTECT)
    b = probe(post, net, tables, params, zones, now=now, mode=ProbeMode.ENFORCE)
    assert a[0]["node_id"] != b[0]["node_id"]

def test_candidate_windows_lie_inside_the_plausible_passage_window(ctx):
    """FR-16: only recommend observations reachable while the plume could still be passing."""
    for c in probe(post, net, tables, params, zones, now=now):
        assert c["window_end"] > c["window_start"] >= now.timestamp()

def test_unreachable_candidates_are_dropped(ctx_far_node):
    ids = {c["node_id"] for c in probe(post, net, tables, params, zones, now=now,
                                       reachable_within_s=60)}
    assert "ZB" not in ids

def test_safety_blocks_missions_during_a_flood_warning(ctx_storm):
    assert probe(post, net, tables, params, zones, now=now, flood_warning=True) == []

def test_safety_blocks_missions_after_dark(ctx):
    night = dt.datetime(2026, 9, 22, 23, 30, tzinfo=dt.UTC)
    assert probe(post, net, tables, params, zones, now=night) == []

def test_candidates_are_ordered_by_ec2_gain(ctx):
    gains = [c["ec2_gain"] for c in probe(post, net, tables, params, zones, now=now)]
    assert gains == sorted(gains, reverse=True)

def test_expected_effect_is_plain_language_and_quantified(ctx):
    c = probe(post, net, tables, params, zones, now=now)[0]
    assert "%" in c["expected_effect"] or "suspect" in c["expected_effect"]

def test_a_negative_outcome_at_the_top_candidate_really_would_shrink_the_posterior(ctx):
    """The promised effect must be real: simulate the negative outcome and re-run."""
    c = probe(post, net, tables, params, zones, now=now)[0]
    before = edge_weight(np.exp(post.log_p), decision_classes(post, net, tables, zones, ProbeMode.ENFORCE))
    post2 = recompute_with_extra_negative(c["node_id"], c["window_start"])
    after = edge_weight(np.exp(post2.log_p), decision_classes(post2, net, tables, zones, ProbeMode.ENFORCE))
    assert after < before
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest services/kernel/tests/test_probe.py -v
```

Expected: FAIL — module missing.

- [ ] **Step 3: Implement `safety.py`**

```python
# services/kernel/upstream_kernel/safety.py
"""PRD 7.5 + 14.4: no missions in high flow, flood warnings, darkness, or private land."""
from __future__ import annotations
import datetime as dt

DAYLIGHT_START_H, DAYLIGHT_END_H = 7, 20      # conservative; replace with sunrise/sunset in Phase 1 pilot

def mission_allowed(*, now: dt.datetime, flow_condition: str, flood_warning: bool,
                    node_attrs: dict) -> tuple[bool, str]:
    if flood_warning:
        return False, "flood warning in force"
    if flow_condition == "storm":
        return False, "high flow: unsafe to approach the bank"
    local_hour = now.astimezone(dt.UTC).hour
    if not (DAYLIGHT_START_H <= local_hour < DAYLIGHT_END_H):
        return False, "outside daylight hours"
    if not node_attrs.get("public_access", True):
        return False, "not a public access point"
    return True, ""
```

- [ ] **Step 4: Implement `probe.py`**

```python
# services/kernel/upstream_kernel/probe.py
"""PROBE: where should the next observation be, and who can take it? (PRD 7.5)"""
from __future__ import annotations
import datetime as dt
import numpy as np
import jax.numpy as jnp
from upstream_shared.mission import ProbeMode
from .ec2 import greedy_select, ec2_gain
from .model.hypotheses import KIND_NONE, KIND_DIFFUSE, KIND_POINT
from .model.likelihood import _detect_prob, _predicted_concentration, Observation
from .pulse import EXPOSURE_THRESHOLD_C
from .safety import mission_allowed

WARN_THRESHOLD = 0.20              # zone warning threshold used to define Protect classes
CANDIDATE_METHODS = ["citizen_visual_olfactory", "test_strip"]
WALK_SPEED_MPS = 1.3

def decision_classes(post, net, tables, zones, mode: ProbeMode) -> np.ndarray:
    """Group hypotheses by the decision they imply (PRD 7.5 'two modes')."""
    g = post.grid
    if mode is ProbeMode.ENFORCE:
        # "Which outfall should be inspected": one class per entry point, plus diffuse, plus none.
        cls = np.where(g.kind == KIND_POINT, g.entry_k, -1).astype(np.int64)
        cls = np.where(g.kind == KIND_DIFFUSE, len(net.entry_nodes), cls)
        cls = np.where(g.kind == KIND_NONE, len(net.entry_nodes) + 1, cls)
        return cls
    # PROTECT: "which zones need a warning" — the signature of exposed zones per hypothesis.
    # At most 62 zones fit in the int64 signature; beyond that, bucket by the top-16 zones
    # ranked by p_peak, which are the only ones a warning decision would differ on.
    ranked = sorted(range(len(net.zone_ids)),
                    key=lambda z: -zones[net.zone_ids[z]]["p_peak"])[:16]
    sig = np.zeros(g.H, dtype=np.int64)
    for bit, z in enumerate(ranked):
        sig |= _hypothesis_exposes_zone(post, net, tables, z).astype(np.int64) << bit
    return sig

def _hypothesis_exposes_zone(post, net, tables, z: int) -> np.ndarray:
    """True per hypothesis if its plume would exceed the exposure threshold at that zone.

    Reachability plus enough dilution-adjusted mass to cross EXPOSURE_THRESHOLD_C — the same
    threshold PULSE uses, so PROBE and PULSE cannot disagree about what "exposed" means.
    """
    g = post.grid
    k = np.clip(g.entry_k, 0, None)
    node = int(net.zone_node_idx[z])
    reach = np.asarray(tables.reachable[post.flow_idx, k, node], dtype=bool)
    dil = np.asarray(tables.dilution[post.flow_idx, k, node])
    return reach & (g.kind == KIND_POINT) & (g.mass * dil > EXPOSURE_THRESHOLD_C)

def probe(post, net, tables, params, zones, *, now: dt.datetime,
          mode: ProbeMode = ProbeMode.PROTECT, max_candidates: int = 5,
          reachable_within_s: float = 1800, flood_warning: bool = False,
          flow_condition: str = "wet", origin_node: str | None = None) -> list[dict]:
    ok, reason = mission_allowed(now=now, flow_condition=flow_condition,
                                 flood_warning=flood_warning, node_attrs={})
    if not ok:
        return []

    p = np.exp(post.log_p)
    classes = decision_classes(post, net, tables, zones, mode)
    t_now = now.timestamp()
    k = np.clip(post.grid.entry_k, 0, None)

    candidate_outcomes: dict[str, np.ndarray] = {}
    costs: dict[str, float] = {}
    meta: dict[str, dict] = {}
    origin = net.node_index[origin_node] if origin_node else None

    for node_idx in range(len(net.node_ids)):
        tau = tables.tau[post.flow_idx, k, node_idx]
        arrival = post.grid.t0 + tau
        passing = np.isfinite(arrival) & (arrival + post.grid.duration_s > t_now) & \
                  (arrival < t_now + reachable_within_s)
        if p[passing].sum() < 1e-4:
            continue                       # nothing credible could still be passing here
        w_lo = max(t_now, float(np.nanmin(arrival[passing])))
        w_hi = float(np.nanmax((arrival + post.grid.duration_s)[passing]))
        cost = _walk_cost_s(net, origin, node_idx)
        if cost > reachable_within_s or w_hi <= t_now:
            continue
        t_mid = 0.5 * (w_lo + w_hi)
        obs = Observation(event_id="cand", node_idx=node_idx, t_obs=t_mid,
                          method="citizen_visual_olfactory", result="positive", value=None,
                          observer_reliability=params.observer_reliability_default,
                          window_start=None, window_end=None)
        c = np.asarray(_predicted_concentration(obs, post.grid, tables, post.flow_idx, params))
        p_pos = np.asarray(_detect_prob(jnp.asarray(c),
                                        params.detection["citizen_visual_olfactory"],
                                        params.observer_reliability_default))
        cid = f"{net.node_ids[node_idx]}@{int(t_mid)}"
        candidate_outcomes[cid] = np.stack([p_pos, 1.0 - p_pos])
        costs[cid] = cost
        meta[cid] = {"node_id": net.node_ids[node_idx], "window_start": w_lo,
                     "window_end": w_hi}

    picks = greedy_select(p, classes, candidate_outcomes, costs, k=max_candidates)
    out = []
    for cid, score in picks:
        gain = ec2_gain(p, classes, candidate_outcomes[cid])
        out.append({"candidate_id": cid, **meta[cid], "methods": CANDIDATE_METHODS,
                    "mode": mode.value, "ec2_gain": float(gain),
                    "gain_per_cost": float(score), "walk_cost_s": costs[cid],
                    "expected_effect": _expected_effect(p, classes,
                                                        candidate_outcomes[cid], net, mode)})
    return out

def _walk_cost_s(net, origin: int | None, node_idx: int) -> float:
    """Straight-line fallback; the Core API replaces this with pgRouting walking time."""
    if origin is None:
        return 300.0
    from pyproj import Geod
    g = Geod(ellps="WGS84")
    lon1, lat1 = net.lonlat[origin]; lon2, lat2 = net.lonlat[node_idx]
    _, _, d = g.inv(lon1, lat1, lon2, lat2)
    return float(d) / WALK_SPEED_MPS * 1.35        # 1.35 detour factor for real paths

def _expected_effect(p, classes, outcomes, net, mode: ProbeMode) -> str:
    """The sentence the volunteer sees. Every number here is computed, never guessed."""
    before = len(np.unique(classes[p > 0.001]))
    residual = []
    for o in range(outcomes.shape[0]):
        pq = p * outcomes[o]
        residual.append(len(np.unique(classes[pq / max(pq.sum(), 1e-300) > 0.001])))
    after = int(np.mean(residual))
    cut = ec2_gain(p, classes, outcomes) / max(1e-12,
        0.5 * (p.sum() ** 2 - float((np.bincount(classes, weights=p) ** 2).sum())))
    noun = "suspect outfalls" if mode is ProbeMode.ENFORCE else "warning patterns"
    return (f"Expected to rule out about {max(before - after, 0)} of {before} {noun} "
            f"(cuts {cut:.0%} of the remaining uncertainty).")
```

- [ ] **Step 5: Run tests, then commit**

```bash
pytest services/kernel/tests/test_probe.py -v
git add services/kernel/upstream_kernel/{probe.py,safety.py} services/kernel/tests/test_probe.py
git commit -m "feat(kernel): PROBE candidate selection with EC2, protect/enforce modes, safety gates"
```

---

### Task 5.4: Routing and assignment (OR-Tools + pgRouting)

**Files:**
- Create: `services/core-api/upstream_api/routing.py`
- Test: `services/core-api/tests/test_routing.py`

**Interfaces:**
- Produces:
  ```python
  def walking_time_s(from_lonlat, to_lonlat) -> float            # pgRouting over footpath_edges
  def assign_missions(candidates: list[dict], volunteers: list[dict], *, now
                      ) -> list[tuple[str, str]]                 # (candidate_id, volunteer_id)
  ```
  Uses OR-Tools CP-SAT with time windows; respects each candidate's `[window_start, window_end]`
  and each volunteer's availability and coarse area (FR-17).

- [ ] **Step 1: Write the failing tests**

```python
# services/core-api/tests/test_routing.py — key assertions
def test_volunteer_is_not_assigned_a_window_they_cannot_reach_in_time():
    assigned = assign_missions([far_candidate_closing_in_5_min], [one_volunteer], now=now)
    assert assigned == []

def test_higher_gain_candidate_wins_when_a_volunteer_can_only_do_one():
    assigned = assign_missions([low_gain, high_gain], [one_volunteer], now=now)
    assert assigned[0][0] == high_gain["candidate_id"]

def test_each_volunteer_gets_at_most_one_concurrent_mission():
    assigned = assign_missions([c1, c2], [one_volunteer], now=now)
    assert len({v for _, v in assigned}) == len(assigned)

def test_volunteer_outside_their_coarse_area_is_not_offered_the_mission():
    assert assign_missions([candidate_in_north], [volunteer_in_south], now=now) == []

@pytest.mark.integration
def test_pgrouting_walking_time_exceeds_straight_line_distance():
    assert walking_time_s(a, b) > geodesic_seconds(a, b)
```

- [ ] **Step 2: Run to verify failure, then implement**

```python
# services/core-api/upstream_api/routing.py
"""FR-17: assign PROBE candidates to available people and route them.

Walking times come from pgRouting over the OSM footpath graph loaded in Phase 1; the
assignment is a CP-SAT model that maximises total EC2 gain subject to time windows.
"""
from __future__ import annotations
import datetime as dt
from ortools.sat.python import cp_model
from .db import pool

def walking_time_s(from_lonlat: tuple[float, float], to_lonlat: tuple[float, float]) -> float:
    with pool.connection() as c, c.cursor() as cur:
        cur.execute("""
        WITH s AS (SELECT id FROM footpath_edges
                   ORDER BY geom <-> ST_SetSRID(ST_Point(%s,%s),4326) LIMIT 1),
             t AS (SELECT id FROM footpath_edges
                   ORDER BY geom <-> ST_SetSRID(ST_Point(%s,%s),4326) LIMIT 1)
        SELECT coalesce(sum(cost),0) FROM pgr_dijkstra(
          'SELECT id, source, target, cost, reverse_cost FROM footpath_edges',
          (SELECT source FROM footpath_edges WHERE id=(SELECT id FROM s)),
          (SELECT target FROM footpath_edges WHERE id=(SELECT id FROM t)), directed := false)
        """, (from_lonlat[0], from_lonlat[1], to_lonlat[0], to_lonlat[1]))
        metres = float(cur.fetchone()[0])
    return metres / 1.3 if metres > 0 else float("inf")

def assign_missions(candidates: list[dict], volunteers: list[dict], *, now: dt.datetime
                    ) -> list[tuple[str, str]]:
    model = cp_model.CpModel()
    x: dict[tuple[int, int], cp_model.IntVar] = {}
    t_now = now.timestamp()
    for i, c in enumerate(candidates):
        for j, v in enumerate(volunteers):
            if not _in_area(v, c):
                continue
            travel = walking_time_s(v["lonlat"], c["lonlat"])
            if t_now + travel > c["window_end"]:
                continue                                    # FR-16: cannot arrive in time
            if not (v["available_from"] <= now <= v["available_to"]):
                continue
            x[i, j] = model.NewBoolVar(f"x_{i}_{j}")
    for i in range(len(candidates)):
        model.AddAtMostOne(x[i, j] for j in range(len(volunteers)) if (i, j) in x)
    for j in range(len(volunteers)):
        model.AddAtMostOne(x[i, j] for i in range(len(candidates)) if (i, j) in x)
    model.Maximize(sum(int(candidates[i]["ec2_gain"] * 1e6) * var
                       for (i, j), var in x.items()))
    solver = cp_model.CpSolver(); solver.parameters.max_time_in_seconds = 5.0
    if solver.Solve(model) not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return []
    return [(candidates[i]["candidate_id"], volunteers[j]["volunteer_id"])
            for (i, j), var in x.items() if solver.Value(var)]

def _in_area(volunteer: dict, candidate: dict) -> bool:
    """PRD 14.2: volunteers share a coarse area, never a live location."""
    with pool.connection() as c, c.cursor() as cur:
        cur.execute("""SELECT ST_Contains(coarse_area, ST_SetSRID(ST_Point(%s,%s),4326))
                       FROM volunteers WHERE volunteer_id=%s""",
                    (candidate["lonlat"][0], candidate["lonlat"][1],
                     volunteer["volunteer_id"]))
        row = cur.fetchone()
    return bool(row and row[0])
```

- [ ] **Step 3: Run tests and commit**

```bash
docker compose run --rm api pytest services/core-api/tests/test_routing.py -v
git add services/core-api/upstream_api/routing.py services/core-api/tests/test_routing.py
git commit -m "feat(api): pgRouting walking times and CP-SAT mission assignment"
```

## Phase 5 exit criteria

- 24 tests green across pulse, ec2, probe, routing.
- The EC² test that proves it **ignores within-class discrimination** passes — that is the claim in PRD §3.4 and it must be demonstrable.
- PROBE returns an empty list under flood warning, storm flow and after dark.
- `_expected_effect` produces a quantified sentence whose promise is verified by `test_a_negative_outcome_at_the_top_candidate_really_would_shrink_the_posterior`.
- Kernel worker now writes real `zone_windows` and `probe_candidates` into each snapshot.

## 🔑 Credentials needed at the end of Phase 5

**None.**

---

# Phase 6 — Episode lifecycle, missions and durable timers

**Day 3, afternoon (≈4 h).** DBOS workflows that survive restarts and run from minutes to weeks.

**PRD coverage:** §6.3 (lifecycle), §10.4 Layer 5, FR-12, FR-20…FR-24, FR-37 (belief replay API), NFR-8, GC-12.

## File structure

```
services/core-api/upstream_api/
├── workflows/
│   ├── episode.py     # DBOS workflow: open, advance, refute, resolve
│   ├── missions.py    # create, assign, notify, expire, re-plan
│   └── timers.py      # sample deadline, clinical window, bioassessment
├── api/
│   ├── episodes.py    # GET /episodes, /episodes/{id}, POST /episodes/{id}/signoff
│   ├── replay.py      # GET /replay?at=... (belief replay, FR-37)
│   ├── missions.py    # GET/POST mission endpoints for the PWA
│   └── network.py     # GET /network/geojson for the map
└── push.py            # Web Push via VAPID
```

---

### Task 6.1: Episode state machine workflow

**Files:**
- Create: `services/core-api/upstream_api/workflows/episode.py`
- Test: `services/core-api/tests/test_episode_workflow.py`

**Interfaces:**
- Consumes: `PosteriorComputed` events; `EpisodeState`, `THRESHOLD_*` from `upstream_shared`.
- Produces:
  ```python
  @DBOS.workflow()
  def episode_workflow(catchment_id: str, episode_id: str) -> None
  def on_posterior_computed(event: StoredEvent) -> None      # consumer entry point
  def request_signoff(episode_id: str, reason: str) -> None
  def give_signoff(episode_id: str, officer_id: str, field_result_event_id: str) -> None
  ```

- [ ] **Step 1: Write the failing tests**

```python
# services/core-api/tests/test_episode_workflow.py — key assertions
def test_episode_opens_as_suspected_above_threshold(store):
    emit_posterior(p_event=0.62)
    assert latest_episode().state == "SUSPECTED"

def test_episode_does_not_open_below_threshold(store):
    emit_posterior(p_event=0.30)
    assert latest_episode() is None

def test_suspected_advances_to_probable(store):
    emit_posterior(p_event=0.62); emit_posterior(p_event=0.94)
    assert latest_episode().state == "PROBABLE"

def test_probable_cannot_jump_straight_to_confirmed_without_signoff(store):
    emit_posterior(p_event=0.94)
    with pytest.raises(PermissionError):
        force_state(latest_episode().episode_id, "CONFIRMED")

def test_confirmed_requires_both_a_positive_field_result_and_an_officer(store):
    """FR-21."""
    emit_posterior(p_event=0.94)
    ep = latest_episode().episode_id
    with pytest.raises(ValueError, match="positive field or lab result"):
        give_signoff(ep, officer_id="off-1", field_result_event_id=None)
    eid = post_field_test(node_id="O14", result="positive")
    give_signoff(ep, officer_id="off-1", field_result_event_id=eid)
    assert episode(ep).state == "CONFIRMED"

def test_falling_probability_refutes_the_episode(store):
    emit_posterior(p_event=0.62); emit_posterior(p_event=0.05)
    assert latest_episode().state == "REFUTED"

def test_state_change_emits_an_event_with_old_and_new_state(store):
    emit_posterior(p_event=0.62); emit_posterior(p_event=0.94)
    e = last_event("EpisodeStateChanged")
    assert e.payload["from"] == "SUSPECTED" and e.payload["to"] == "PROBABLE"

def test_clinical_window_is_set_from_the_exposure_window_plus_incubation(store):
    """FR-22 + PRD 7.6: relevance lasts ~16 days after exposure."""
    emit_posterior(p_event=0.94, zone_windows=WINDOWS)
    ep = latest_episode()
    assert (ep.clinical_window_end - ep.opened_at).days >= 14

def test_resolved_after_the_clinical_window_elapses(store, fast_clock):
    emit_posterior(p_event=0.94); fast_clock.advance(days=17)
    assert latest_episode().state == "RESOLVED"

def test_late_evidence_can_reopen_a_resolved_episode_history_preserved(store, fast_clock):
    """PRD 6.3: any later evidence can reopen an episode; the history is preserved."""
    emit_posterior(p_event=0.94); fast_clock.advance(days=17)
    ep = latest_episode().episode_id
    post_lab_result(node_id="O14", result="quantitative", value=9000.0, days_ago=16)
    emit_posterior(p_event=0.97)
    assert count_events("EpisodeStateChanged", episode_id=ep) >= 3
```

- [ ] **Step 2: Run to verify failure, then implement**

```python
# services/core-api/upstream_api/workflows/episode.py
"""Layer 5 (PRD 10.4): episode lifecycle as durable DBOS workflows.

Timers here run for weeks (clinical relevance) and months (bioassessment), so they live in
Postgres via DBOS rather than in memory — a container restart must not lose them.
"""
from __future__ import annotations
import datetime as dt, uuid
from dbos import DBOS
from psycopg.types.json import Json
from upstream_shared.codes import CLINICAL_RELEVANCE_DAYS
from upstream_shared.episode import (EpisodeState, THRESHOLD_SUSPECTED,
                                     THRESHOLD_PROBABLE, THRESHOLD_REFUTED)
from upstream_shared.events import EventEnvelope, EventType
from ..config import settings
from ..db import pool
from ..eventlog import store

def on_posterior_computed(event) -> None:
    """Consumer of PosteriorComputed. The kernel never does this itself (PRD 10.3)."""
    p = event.payload
    ep = _open_episode(event) if p["p_event"] >= THRESHOLD_SUSPECTED else _current_episode()
    if ep is None:
        return
    target = _target_state(EpisodeState(ep["state"]), p["p_event"])
    if target and EpisodeState(ep["state"]).can_transition_to(target):
        _transition(ep, target, reason=f"p_event={p['p_event']:.3f}", event=event)
    _update_summary(ep["episode_id"], p)

def _target_state(current: EpisodeState, p_event: float) -> EpisodeState | None:
    if p_event < THRESHOLD_REFUTED:
        return EpisodeState.REFUTED
    if current is EpisodeState.SUSPECTED and p_event >= THRESHOLD_PROBABLE:
        return EpisodeState.PROBABLE
    return None     # CONFIRMED needs a human (FR-21); RESOLVED comes from a timer (FR-22)

def _open_episode(event) -> dict:
    existing = _current_episode()
    if existing:
        return existing
    now = dt.datetime.now(dt.UTC)
    episode_id = f"EE-{uuid.uuid4().hex[:4].upper()}"
    lo, hi = event.payload.get("est_start", [None, None])
    clinical_end = now + dt.timedelta(days=CLINICAL_RELEVANCE_DAYS)
    with pool.connection() as c, c.cursor() as cur:
        cur.execute("""INSERT INTO episodes (episode_id,catchment_id,stream,state,opened_at,
                       state_changed_at,est_start_lo,est_start_hi,clinical_window_end,
                       latest_fingerprint,summary)
                       VALUES (%s,%s,%s,'SUSPECTED',%s,%s,
                               to_timestamp(%s),to_timestamp(%s),%s,%s,%s)""",
                    (episode_id, settings.catchment_id, event.stream, now, now, lo, hi,
                     clinical_end, event.payload["fingerprint"], Json({})))
    store.append(EventEnvelope(stream=event.stream, catchment_id=settings.catchment_id,
                               event_type=EventType.EPISODE_OPENED, event_time=now,
                               payload={"episode_id": episode_id,
                                        "fingerprint": event.payload["fingerprint"]},
                               causation_id=event.event_id))
    DBOS.start_workflow(episode_workflow, settings.catchment_id, episode_id)
    return _episode(episode_id)

def _transition(ep: dict, target: EpisodeState, *, reason: str, event=None) -> None:
    now = dt.datetime.now(dt.UTC)
    with pool.connection() as c, c.cursor() as cur:
        cur.execute("UPDATE episodes SET state=%s, state_changed_at=%s, version=version+1 "
                    "WHERE episode_id=%s", (target.value, now, ep["episode_id"]))
    store.append(EventEnvelope(
        stream=ep["stream"], catchment_id=settings.catchment_id,
        event_type=EventType.EPISODE_STATE_CHANGED, event_time=now,
        payload={"episode_id": ep["episode_id"], "from": ep["state"],
                 "to": target.value, "reason": reason},
        causation_id=getattr(event, "event_id", None)))

def give_signoff(episode_id: str, officer_id: str, field_result_event_id: str | None) -> None:
    """FR-21: CONFIRMED needs a positive field/lab result AND an officer."""
    if not field_result_event_id or not _is_positive_result(field_result_event_id):
        raise ValueError("CONFIRMED requires a positive field or lab result")
    ep = _episode(episode_id)
    if not EpisodeState(ep["state"]).can_transition_to(EpisodeState.CONFIRMED):
        raise PermissionError(f"cannot confirm from {ep['state']}")
    store.append(EventEnvelope(stream=ep["stream"], catchment_id=settings.catchment_id,
                               event_type=EventType.SIGN_OFF_GIVEN,
                               event_time=dt.datetime.now(dt.UTC),
                               payload={"episode_id": episode_id, "officer_id": officer_id,
                                        "field_result_event_id": field_result_event_id}))
    _transition(ep, EpisodeState.CONFIRMED, reason=f"officer {officer_id} signed off")

@DBOS.workflow()
def episode_workflow(catchment_id: str, episode_id: str) -> None:
    """Durable timers: FR-22 (clinical window) and FR-24 (post-episode bioassessment)."""
    DBOS.sleep(CLINICAL_RELEVANCE_DAYS * 24 * 3600)
    ep = _episode(episode_id)
    if EpisodeState(ep["state"]).can_transition_to(EpisodeState.RESOLVED):
        _transition(ep, EpisodeState.RESOLVED, reason="clinical relevance window elapsed")
    if ep["state"] == EpisodeState.CONFIRMED.value:
        DBOS.sleep(14 * 24 * 3600)                    # FR-24: 2-4 weeks later
        from .missions import create_bioassessment_mission
        create_bioassessment_mission(episode_id)
```

> Helper functions `_current_episode`, `_episode`, `_update_summary`, `_is_positive_result`
> are thin SQL reads over `episodes` / `events`; implement them in the same file.

- [ ] **Step 3: Run tests and commit**

```bash
docker compose run --rm api pytest services/core-api/tests/test_episode_workflow.py -v
git add services/core-api/upstream_api/workflows/episode.py
git commit -m "feat(api): episode lifecycle workflow with officer sign-off and durable timers"
```

---

### Task 6.2: Mission lifecycle, push notifications and re-planning

**Files:**
- Create: `services/core-api/upstream_api/workflows/missions.py`, `services/core-api/upstream_api/push.py`
- Test: `services/core-api/tests/test_missions.py`

**Interfaces:**
- Produces:
  ```python
  def create_missions_from_probe(episode_id: str, candidates: list[dict]) -> list[MissionSpec]
  def accept_mission(mission_id: str, volunteer_id: str) -> None
  def complete_mission(mission_id: str, evidence_event_id: str) -> None
  @DBOS.workflow() def mission_deadline_workflow(mission_id: str) -> None   # FR-23
  def create_bioassessment_mission(episode_id: str) -> str                  # FR-24
  def send_push(volunteer_id: str, title: str, body: str, url: str) -> None
  ```

- [ ] **Step 1: Write the failing tests**

```python
# services/core-api/tests/test_missions.py — key assertions
def test_mission_created_from_top_probe_candidate():
    specs = create_missions_from_probe(ep, candidates)
    assert specs[0].node_id == candidates[0]["node_id"]
    assert "Check" in specs[0].human_summary

def test_mission_expires_and_triggers_a_replan(fast_clock):
    """FR-23: re-plan PROBE if a requested sample is not returned within its window."""
    m = create_missions_from_probe(ep, candidates)[0]
    fast_clock.advance(minutes=30)
    assert mission(m.mission_id).status == "expired"
    assert count_events("MissionExpired") == 1
    assert count_missions(episode_id=ep) > 1          # a replacement was planned

def test_completing_a_mission_records_its_realised_gain():
    m = create_missions_from_probe(ep, candidates)[0]
    accept_mission(m.mission_id, "vol-1")
    eid = post_evidence(node_id=m.node_id, result="negative", mission_id=m.mission_id)
    complete_mission(m.mission_id, eid)
    assert mission(m.mission_id).realised_gain is not None

def test_volunteer_sees_the_measured_effect_of_their_contribution():
    """G7 + PRD 16: 'your sample eliminated two of three suspects'."""
    m = create_missions_from_probe(ep, candidates)[0]
    accept_mission(m.mission_id, "vol-1")
    eid = post_evidence(node_id=m.node_id, result="negative", mission_id=m.mission_id)
    kernel_worker.process_once()           # a new snapshot is what makes the effect measurable
    complete_mission(m.mission_id, eid)
    fb = get_mission_feedback(m.mission_id)
    assert "ruled out" in fb["effect"]
    assert fb["realised_gain"] > 0, "a negative check upstream must shrink the hypothesis set"

def test_bioassessment_mission_scheduled_after_a_confirmed_episode():
    mid = create_bioassessment_mission(ep)
    assert mission(mid).methods == ["bioassessment"]

def test_push_is_not_sent_when_the_volunteer_has_no_subscription():
    send_push("vol-no-sub", "t", "b", "/")     # must not raise
```

- [ ] **Step 2: Implement `push.py` and `missions.py`**

```python
# services/core-api/upstream_api/push.py
"""Web Push to the mission PWA. VAPID keys are generated locally — see the Phase 6 key table."""
import json
from pywebpush import webpush, WebPushException
from .config import settings
from .db import pool

def send_push(volunteer_id: str, title: str, body: str, url: str) -> None:
    with pool.connection() as c, c.cursor() as cur:
        cur.execute("SELECT push_subscription FROM volunteers WHERE volunteer_id=%s",
                    (volunteer_id,))
        row = cur.fetchone()
    if not row or not row[0]:
        return
    try:
        webpush(subscription_info=row[0],
                data=json.dumps({"title": title, "body": body, "url": url}),
                vapid_private_key=settings.vapid_private_key,
                vapid_claims={"sub": settings.vapid_subject})
    except WebPushException as exc:
        print(f"[push] {volunteer_id}: {exc}")        # never fail a workflow on a push error
```

```python
# services/core-api/upstream_api/workflows/missions.py (core of it)
def create_missions_from_probe(episode_id: str, candidates: list[dict]) -> list[MissionSpec]:
    """FR-15/FR-17: turn PROBE candidates into assigned, time-boxed missions."""
    volunteers = _available_volunteers()
    pairs = assign_missions(candidates, volunteers, now=dt.datetime.now(dt.UTC))
    specs = []
    for cand_id, vol_id in pairs:
        c = next(x for x in candidates if x["candidate_id"] == cand_id)
        mission_id = f"M-{uuid.uuid4().hex[:4].upper()}"
        summary = (f"Check {c['node_id']} between "
                   f"{_hhmm(c['window_start'])} and {_hhmm(c['window_end'])}: "
                   f"{', '.join(c['methods'])}. {c['expected_effect']}")
        _insert_mission(mission_id, episode_id, c, vol_id, summary)
        store.append(EventEnvelope(stream="live", catchment_id=settings.catchment_id,
                                   event_type=EventType.MISSION_CREATED,
                                   event_time=dt.datetime.now(dt.UTC),
                                   payload={"mission_id": mission_id, "episode_id": episode_id,
                                            "node_id": c["node_id"], "assignee": vol_id,
                                            "expected_gain": c["ec2_gain"]}))
        send_push(vol_id, "Upstream mission nearby", summary, f"/missions/{mission_id}")
        DBOS.start_workflow(mission_deadline_workflow, mission_id)
        specs.append(MissionSpec(mission_id=mission_id, episode_id=episode_id,
                                 node_id=c["node_id"],
                                 window_start=_dt(c["window_start"]),
                                 window_end=_dt(c["window_end"]),
                                 methods=c["methods"], mode=ProbeMode(c["mode"]),
                                 expected_gain=c["ec2_gain"], human_summary=summary))
    return specs

@DBOS.workflow()
def mission_deadline_workflow(mission_id: str) -> None:
    """FR-23: if the sample does not come back inside its window, expire and re-plan."""
    m = _mission(mission_id)
    DBOS.sleep(max((m["window_end"] - dt.datetime.now(dt.UTC)).total_seconds(), 0))
    if _mission(mission_id)["status"] in ("created", "accepted"):
        _set_status(mission_id, MissionStatus.EXPIRED)
        store.append(EventEnvelope(stream="live", catchment_id=settings.catchment_id,
                                   event_type=EventType.MISSION_EXPIRED,
                                   event_time=dt.datetime.now(dt.UTC),
                                   payload={"mission_id": mission_id}))
        _replan(m["episode_id"])          # reads the newest snapshot's probe_candidates

def complete_mission(mission_id: str, evidence_event_id: str) -> None:
    """G7: record what the contribution actually changed, measured from two snapshots."""
    before = _snapshot_before(evidence_event_id)
    after = _latest_snapshot()
    realised = _decision_uncertainty(before) - _decision_uncertainty(after)
    _set_status(mission_id, MissionStatus.COMPLETED, realised_gain=realised)
    store.append(EventEnvelope(stream="live", catchment_id=settings.catchment_id,
                               event_type=EventType.MISSION_COMPLETED,
                               event_time=dt.datetime.now(dt.UTC),
                               payload={"mission_id": mission_id,
                                        "evidence_event_id": evidence_event_id,
                                        "realised_gain": realised}))
```

- [ ] **Step 3: Run tests and commit**

```bash
docker compose run --rm api pytest services/core-api/tests/test_missions.py -v
git add services/core-api/upstream_api/
git commit -m "feat(api): mission lifecycle, web push, deadline re-planning, bioassessment"
```

---

### Task 6.3: Read APIs — episodes, belief replay, network GeoJSON

**Files:**
- Create: `services/core-api/upstream_api/api/{episodes.py,replay.py,missions.py,network.py}`
- Test: `services/core-api/tests/test_read_apis.py`

**Interfaces:**

| Method | Path | FR | Returns |
|---|---|---|---|
| GET | `/episodes` | FR-36 | list of episodes with state, top sources, zone windows |
| GET | `/episodes/{id}` | FR-36 | full episode incl. evidence list and explanation |
| POST | `/episodes/{id}/signoff` | FR-21 | officer sign-off |
| GET | `/replay?at=<iso8601>` | **FR-37** | the snapshot the system believed at that moment |
| GET | `/replay/timeline` | FR-37 | all snapshot timestamps + p_event, for the slider |
| GET | `/missions/mine?volunteer_id=` | FR-38 | open missions for one volunteer |
| POST | `/missions/{id}/accept` / `/decline` / `/complete` | FR-38 | mission actions |
| GET | `/network/geojson` | FR-36 | nodes, edges, outfalls (with `is_synthetic`), zones |
| GET | `/public-health/episodes` | FR-39 | episodes + windows + clinical test results |

- [ ] **Step 1: Write the failing tests**

```python
# services/core-api/tests/test_read_apis.py — key assertions
def test_belief_replay_returns_the_snapshot_as_of_a_past_moment():
    r = client.get(f"/replay?at={t_mid.isoformat()}")
    assert r.json()["p_event"] == early_p_event

def test_belief_replay_never_leaks_a_later_snapshot():
    r = client.get(f"/replay?at={t_mid.isoformat()}")
    assert dt.datetime.fromisoformat(r.json()["ts"]) <= t_mid

def test_replay_timeline_is_ordered_and_matches_snapshot_count():
    tl = client.get("/replay/timeline").json()
    assert [x["ts"] for x in tl] == sorted(x["ts"] for x in tl)

def test_episode_detail_includes_the_computed_explanation():
    d = client.get(f"/episodes/{ep}").json()
    assert d["explanation"]["candidates"][0]["supported_by"]

def test_network_geojson_marks_synthetic_outfalls():
    """PRD R2: synthetic elements must be visibly labelled."""
    g = client.get("/network/geojson").json()
    assert any(f["properties"]["is_synthetic"] for f in g["outfalls"]["features"])

def test_public_health_view_carries_the_not_a_diagnosis_notice():
    """GC-12."""
    assert "not a diagnosis" in client.get("/public-health/episodes").text.lower()
```

- [ ] **Step 2: Implement the routers**

```python
# services/core-api/upstream_api/api/replay.py
"""FR-37 Belief replay: what did the system believe at any past moment?

PRD 12.5: 'select the latest snapshot with recorded_at <= the chosen moment'.
"""
import datetime as dt
from fastapi import APIRouter, HTTPException, Query
from ..config import settings
from ..db import pool

router = APIRouter(tags=["replay"])

@router.get("/replay")
def replay(at: dt.datetime = Query(...), stream: str = "live"):
    with pool.connection() as c, c.cursor() as cur:
        cur.execute("""SELECT ts,fingerprint,as_of_seq,p_event,source_marginals,zone_windows,
                              probe_candidates,explanation,kernel_version,network_version,
                              params_version
                       FROM posterior_snapshots
                       WHERE catchment_id=%s AND stream=%s AND ts <= %s
                       ORDER BY ts DESC LIMIT 1""", (settings.catchment_id, stream, at))
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "no belief recorded before that moment")
    keys = ["ts","fingerprint","as_of_seq","p_event","source_marginals","zone_windows",
            "probe_candidates","explanation","kernel_version","network_version","params_version"]
    return dict(zip(keys, row))

@router.get("/replay/timeline")
def timeline(stream: str = "live", limit: int = 500):
    with pool.connection() as c, c.cursor() as cur:
        cur.execute("""SELECT ts, p_event, fingerprint FROM posterior_snapshots
                       WHERE catchment_id=%s AND stream=%s ORDER BY ts LIMIT %s""",
                    (settings.catchment_id, stream, limit))
        return [{"ts": r[0], "p_event": r[1], "fingerprint": r[2]} for r in cur.fetchall()]
```

- [ ] **Step 3: Run tests and commit**

```bash
docker compose run --rm api pytest services/core-api/tests/test_read_apis.py -v
git add services/core-api/upstream_api/api/
git commit -m "feat(api): episode, belief-replay, mission and network read endpoints"
```

## Phase 6 exit criteria

- Full lifecycle demonstrable from the API: evidence → SUSPECTED → PROBABLE → (field test + sign-off) → CONFIRMED → RESOLVED after the clinical window.
- `CONFIRMED` is unreachable without both a positive result and an officer (FR-21).
- A mission that is not completed inside its window expires and triggers a re-plan (FR-23).
- `GET /replay?at=` returns strictly-past beliefs; the timeline drives the Phase 10 slider.
- Restarting the `api` container does not lose the clinical-window timer (DBOS durability) — verify with `docker compose restart api`.

## 🔑 Credentials needed at the end of Phase 6

| Variable | What it is | Where to get it |
|---|---|---|
| `VAPID_PUBLIC_KEY` | Web Push public key | **Generate yourself:** `docker compose run --rm api python -c "from py_vapid import Vapid01; v=Vapid01(); v.generate_keys(); print(v.public_key_urlsafe_base64, v.private_key_urlsafe_base64)"` |
| `VAPID_PRIVATE_KEY` | Web Push private key | Same command as above |
| `VAPID_SUBJECT` | Contact URI for push services | **You provide:** `mailto:<your email>` |

*No third-party account is needed — Web Push uses the browser's own push service.*

---

# Phase 7 — BRIDGE part 1: FHIR profiles, publishing, CDS Hooks

**Day 4, morning (≈6 h). This is the submission track.** GC-3 (zero validator errors) is the
single condition on which Track 7 stands or falls (PRD §3.2). Do this before anything cosmetic.

**PRD coverage:** §13 in full, FR-25…FR-31, G4, NFR-7, GC-2, GC-3, GC-12, GC-13.

## File structure

```
fhir/
├── sushi-config.yaml
├── input/fsh/
│   ├── aliases.fsh
│   ├── codesystems.fsh          # episode state, exposure pathway, observation method, source type
│   ├── valuesets.fsh
│   ├── profiles-observation.fsh # UpstreamEvidenceObservation
│   ├── profiles-location.fsh    # UpstreamExposureZone
│   ├── profiles-group.fsh       # UpstreamZonePopulation
│   ├── profiles-risk.fsh        # UpstreamExposureEpisode  <- the core artefact
│   ├── profiles-provenance.fsh  # UpstreamEpisodeProvenance
│   ├── profiles-measure.fsh     # UpstreamSyndromicCount
│   ├── subscriptiontopic.fsh    # episode state change
│   └── examples/                # one full episode lifecycle
├── scripts/
│   ├── build.sh                 # sushi + IG Publisher
│   ├── validate.sh              # HL7 validator, exit 1 on any error
│   └── load-into-hapi.sh
services/core-api/upstream_api/fhir/
├── mapper.py      # episode/evidence -> FHIR resources
├── client.py      # HAPI REST client with validate-on-write
├── publisher.py   # workflow hook: publish on state change; FhirPublished event
├── subscriptions.py # topic-based Subscription registration (FR-29)
├── cds_hooks.py   # discovery + patient-view + encounter-start (FR-28)
└── audit.py       # AuditEvent for every card and external read (FR-30)
```

---

### Task 7.1: Resolve the OAH IG and stand up the FSH project

**Do this first — it is the highest-risk unknown in the whole build (PRD R3).**

**Files:**
- Create: `fhir/sushi-config.yaml`, `fhir/input/fsh/aliases.fsh`, `fhir/scripts/*.sh`
- Test: `fhir/tests/test_ig_resolves.sh`

- [ ] **Step 1: Determine whether `hl7.eu.fhir.oah` is installable**

```bash
mkdir -p fhir && cd fhir
npm install -g fsh-sushi@3.x
curl -sI https://packages.fhir.org/hl7.eu.fhir.oah | head -1
curl -s https://packages.fhir.org/hl7.eu.fhir.oah | jq -r '.versions | keys[]'
```

**Decision point:**
- **If the package resolves** → record the version in `.env` as `OAH_IG_VERSION` and derive profiles from it.
- **If it does not** (the IG is still at `build.fhir.org/ig/hl7-eu/oah/`, i.e. a CI build) → build it from source once and vendor the tarball:
  ```bash
  git clone --depth 1 https://github.com/hl7-eu/oah fhir/vendor/oah
  (cd fhir/vendor/oah && ./_genonce.sh)     # produces output/package.tgz
  cp fhir/vendor/oah/output/package.tgz fhir/vendor/hl7.eu.fhir.oah.tgz
  ```
  Then set `OAH_IG_VERSION=current` and add the tarball path to `dependencies` in `sushi-config.yaml`
  and to HAPI's IG loader. **Commit the tarball** — GC-6 reproducibility beats repo tidiness here.

- [ ] **Step 2: Write `sushi-config.yaml`**

```yaml
# fhir/sushi-config.yaml
id: upstream.onehealth
canonical: https://upstream-onehealth.example
name: UpstreamOneHealth
title: "Upstream — Exposure Episodes for One Health"
status: draft
version: 0.1.0
fhirVersion: 4.0.1
copyrightYear: 2026+
releaseLabel: ci-build
publisher:
  name: Upstream (IEEE OneAquaHealth Hackathon 2026)
dependencies:
  hl7.eu.fhir.oah: current          # or the resolved version from Step 1
  hl7.fhir.uv.subscriptions-backport: 1.1.0
parameters:
  show-inherited-invariants: false
```

- [ ] **Step 3: Write `fhir/scripts/validate.sh` — the CI gate for GC-3**

```bash
#!/usr/bin/env bash
# fhir/scripts/validate.sh — zero validator errors, or the build fails (GC-3, FR-26).
set -euo pipefail
cd "$(dirname "$0")/.."

sushi .                                        # FSH -> fsh-generated/resources
VALIDATOR=${VALIDATOR:-validator_cli.jar}
[ -f "$VALIDATOR" ] || curl -L -o "$VALIDATOR" \
  https://github.com/hapifhir/org.hl7.fhir.core/releases/latest/download/validator_cli.jar

IG_ARGS=(-ig hl7.eu.fhir.oah#${OAH_IG_VERSION:-current})
[ -f vendor/hl7.eu.fhir.oah.tgz ] && IG_ARGS=(-ig vendor/hl7.eu.fhir.oah.tgz)

java -jar "$VALIDATOR" \
  fsh-generated/resources/*.json input/fsh/examples/*.json \
  -version 4.0.1 "${IG_ARGS[@]}" -ig fsh-generated \
  ${TX_SERVER_URL:+-tx "$TX_SERVER_URL"} \
  -output validation-report.json

ERRORS=$(jq '[.issue[]? | select(.severity=="error" or .severity=="fatal")] | length' \
            validation-report.json)
echo "validator errors: $ERRORS"
[ "$ERRORS" -eq 0 ] || { jq '.issue[] | select(.severity=="error")' validation-report.json; exit 1; }
```

- [ ] **Step 4: Add the `fhir` job to CI**

```yaml
# append to .github/workflows/ci.yml
  fhir:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: "20" }
      - uses: actions/setup-java@v4
        with: { distribution: temurin, java-version: "17" }
      - run: npm install -g fsh-sushi@3
      - run: ./fhir/scripts/validate.sh       # fails the build on ANY validator error (GC-3)
      - uses: actions/upload-artifact@v4
        with: { name: validation-report, path: fhir/validation-report.json }
```

- [ ] **Step 5: Commit**

```bash
git add fhir/ .github/workflows/ci.yml
git commit -m "feat(fhir): FSH project on the OAH IG with a zero-error validator CI gate"
```

---

### Task 7.2: Author the profiles, code systems and value sets

**Files:**
- Create: the eight `.fsh` files listed in the file structure.

**Interfaces:**
- Produces profile URLs used verbatim by `mapper.py`:
  `https://upstream-onehealth.example/StructureDefinition/UpstreamEvidenceObservation`,
  `…/UpstreamExposureZone`, `…/UpstreamZonePopulation`, `…/UpstreamExposureEpisode`,
  `…/UpstreamEpisodeProvenance`, `…/UpstreamSyndromicCount`;
  code systems `…/CodeSystem/episode-state`, `…/exposure-pathway`, `…/observation-method`,
  `…/source-type`.

- [ ] **Step 1: Write the code systems and value sets**

```
// fhir/input/fsh/codesystems.fsh
CodeSystem: UpstreamEpisodeState
Id: episode-state
Title: "Upstream Exposure Episode State"
Description: "Lifecycle state of an Exposure Episode (PRD section 6.3)."
* ^url = "https://upstream-onehealth.example/CodeSystem/episode-state"
* ^caseSensitive = true
* ^content = #complete
* #SUSPECTED "Suspected" "Probability of an event is above the suspected threshold."
* #PROBABLE  "Probable"  "Probability of an event is above the probable threshold."
* #CONFIRMED "Confirmed" "A positive field or lab result plus officer sign-off."
* #REFUTED   "Refuted"   "Probability fell below the refuted threshold, or an officer rejected it."
* #RESOLVED  "Resolved"  "Plume passed and the clinical relevance window elapsed."

CodeSystem: UpstreamExposurePathway
Id: exposure-pathway
* ^url = "https://upstream-onehealth.example/CodeSystem/exposure-pathway"
* ^content = #complete
* #recreation     "Recreation"     "Paddling, wading, water play."
* #animal_contact "Animal contact" "Dogs and other animals entering the water."
* #floodwater     "Floodwater"     "Contact with flooded streets or paths."
* #irrigation     "Irrigation"     "Allotments or gardens irrigated from the stream."

CodeSystem: UpstreamObservationMethod
Id: observation-method
* ^url = "https://upstream-onehealth.example/CodeSystem/observation-method"
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
* ^url = "https://upstream-onehealth.example/CodeSystem/source-type"
* ^content = #complete
* #cso            "Combined sewer overflow"
* #storm_outfall  "Storm water outfall"
* #industrial     "Industrial discharge point"
* #misconnection  "Misconnected drain"
* #diffuse_runoff "Diffuse urban runoff"
* #unknown        "Unknown entry point"
```

- [ ] **Step 2: Write `UpstreamExposureEpisode` (PRD §13.3, element for element)**

```
// fhir/input/fsh/profiles-risk.fsh
Profile: UpstreamExposureEpisode
Parent: RiskAssessment
Id: UpstreamExposureEpisode
Title: "Upstream Exposure Episode"
Description: "A time-bounded, evidence-backed hypothesis about one contamination event,
published as a computable RiskAssessment. Environmental exposure context, not a diagnosis."
* ^url = "https://upstream-onehealth.example/StructureDefinition/UpstreamExposureEpisode"

* identifier 1..* MS
* identifier ^short = "Episode identifier, for example EE-2841"
* status 1..1 MS
* status ^short = "preliminary for SUSPECTED/PROBABLE; final for CONFIRMED/RESOLVED; amended after new evidence; cancelled for REFUTED"
* meta.tag 1..* MS
* meta.tag from UpstreamEpisodeStateVS (required)
* meta.tag ^short = "The exact episode state from the Upstream code system"
* subject 1..1 MS
* subject only Reference(UpstreamZonePopulation)
* occurrenceDateTime 1..1 MS
* occurrenceDateTime ^short = "When THIS version of the episode was computed"
* method 1..1 MS
* method ^short = "Kernel version that computed this episode"
* basis 1..* MS
* basis only Reference(UpstreamEvidenceObservation)
* basis ^short = "Every observation used, positive and negative"
* prediction 1..* MS
* prediction.outcome 1..1 MS
* prediction.probability[x] only decimal
* prediction.probabilityDecimal 1..1 MS
* prediction.whenPeriod 1..1 MS
* prediction.whenPeriod ^short = "Clinical relevance window for this zone"
* note 1..* MS

* extension contains
    UpstreamFingerprint named fingerprint 1..1 MS and
    UpstreamSourceRanking named sourceRanking 0..* MS and
    UpstreamExposureWindow named exposureWindow 0..* MS

Extension: UpstreamFingerprint
Id: upstream-fingerprint
Title: "Reproducibility fingerprint"
Description: "SHA-256 over the evidence set, network version, kernel version and parameter
version, so the published episode can be recomputed bit-for-bit."
* value[x] only string

Extension: UpstreamSourceRanking
Id: upstream-source-ranking
* extension contains sourceLocation 1..1 and probability 1..1 and sourceType 0..1
* extension[sourceLocation].value[x] only Reference(Location)
* extension[probability].value[x] only decimal
* extension[sourceType].value[x] only Coding
* extension[sourceType].valueCoding from UpstreamSourceTypeVS (required)

Extension: UpstreamExposureWindow
Id: upstream-exposure-window
* extension contains zone 1..1 and window 1..1 and pathway 0..* and credibleLevel 1..1
* extension[zone].value[x] only Reference(UpstreamExposureZone)
* extension[window].value[x] only Period
* extension[pathway].value[x] only Coding
* extension[pathway].valueCoding from UpstreamExposurePathwayVS (required)
* extension[credibleLevel].value[x] only decimal
* extension[credibleLevel] ^short = "Credible level of the window, 0.80 for an 80% window"
```

- [ ] **Step 3: Write the remaining profiles**

```
// fhir/input/fsh/profiles-observation.fsh
Profile: UpstreamEvidenceObservation
Parent: Observation          // change to the OAH observation profile once resolved (GC-2)
Id: UpstreamEvidenceObservation
Title: "Upstream Evidence Observation"
* ^url = "https://upstream-onehealth.example/StructureDefinition/UpstreamEvidenceObservation"
* status 1..1 MS
* status ^short = "final; entered-in-error when the observation is retracted (FR-10)"
* subject 1..1 MS
* subject only Reference(Location)
* effectiveDateTime 1..1 MS
* effectiveDateTime ^short = "Event time: when the observation happened"
* issued 1..1 MS
* issued ^short = "Record time: when the system learned it (bitemporal, GC-4)"
* method 1..1 MS
* method from UpstreamObservationMethodVS (required)
* value[x] 0..1
* valueQuantity.system = "http://unitsofmeasure.org" (exactly)   // UCUM, GC-13
* dataAbsentReason 0..1 MS
* dataAbsentReason ^short = "Used for explicit negative observations ('checked, looks normal')"
* performer 0..* MS
* device 0..1 MS
* extension contains UpstreamAiAssisted named aiAssisted 0..1 MS
* extension contains UpstreamObserverReliability named observerReliability 0..1 MS

Extension: UpstreamAiAssisted
Id: upstream-ai-assisted
* extension contains modelId 1..1 and confirmedByObserver 1..1
* extension[modelId].value[x] only string
* extension[confirmedByObserver].value[x] only boolean
* ^short = "GC-8: an AI proposed these fields and the observer confirmed them."
```

```
// fhir/input/fsh/profiles-location.fsh
Profile: UpstreamExposureZone
Parent: Location
Id: UpstreamExposureZone
* position 0..1 MS
* type 1..* MS
* extension contains
    http://hl7.org/fhir/StructureDefinition/location-boundary-geojson named boundary 0..1 MS
* extension[boundary] ^short = "Zone polygon as GeoJSON (PRD 13.2)"
```

```
// fhir/input/fsh/profiles-measure.fsh
Profile: UpstreamSyndromicCount
Parent: MeasureReport
Id: UpstreamSyndromicCount
Title: "Aggregate syndromic count for one area and day"
Description: "Aggregate counts only. Small counts are suppressed before this resource is
created. No patient-level data ever crosses this boundary (GC-7)."
* type = #summary (exactly)
* subject 1..1 MS
* subject only Reference(Group)
* period 1..1 MS
* group.measureScore.value 0..1 MS
* group.measureScore ^short = "Count for the area/day/syndrome; absent when suppressed"
```

```
// fhir/input/fsh/subscriptiontopic.fsh
Instance: UpstreamEpisodeStateChangeTopic
InstanceOf: SubscriptionTopic
Usage: #definition
* url = "https://upstream-onehealth.example/SubscriptionTopic/episode-state-change"
* status = #active
* title = "Exposure Episode state change"
* resourceTrigger.resource = "RiskAssessment"
* resourceTrigger.supportedInteraction[0] = #create
* resourceTrigger.supportedInteraction[1] = #update
* resourceTrigger.queryCriteria.current = "RiskAssessment?_tag=https://upstream-onehealth.example/CodeSystem/episode-state|"
```

- [ ] **Step 4: Write one full-lifecycle example set**

`fhir/input/fsh/examples/` must contain a coherent set the validator can resolve end to end:
`Location` (outfall O14, junction J9, Zone A polygon), `Group` (Zone A population),
three `UpstreamEvidenceObservation` instances (one positive, one **negative via
`dataAbsentReason`**, one late lab result), `UpstreamExposureEpisode` v1 (SUSPECTED) and v3
(PROBABLE), `UpstreamEpisodeProvenance`, `AuditEvent`, `UpstreamSyndromicCount`.

- [ ] **Step 5: Run the validator until it reports zero errors**

```bash
./fhir/scripts/validate.sh
```

Expected: `validator errors: 0`. **Do not proceed past this line until it is zero** — GC-3.

- [ ] **Step 6: Commit**

```bash
git add fhir/
git commit -m "feat(fhir): Upstream profiles, code systems, subscription topic, lifecycle examples"
```

---

### Task 7.3: The FHIR mapper and publisher

**Files:**
- Create: `services/core-api/upstream_api/fhir/{mapper.py,client.py,publisher.py,subscriptions.py}`
- Test: `services/core-api/tests/test_fhir_mapper.py`

**Interfaces:**
- Produces:
  ```python
  def evidence_to_observation(ev: StoredEvent, *, retracted: bool) -> dict
  def zone_to_location(net, zone_id: str) -> dict
  def zone_to_group(net, zone_id: str) -> dict
  def episode_to_riskassessment(ep: dict, snapshot: dict, net) -> dict
  def provenance_for(ra_id: str, ra_version: str, snapshot: dict,
                     evidence_refs: list[str], agents: list[dict]) -> dict
  def publish_episode(episode_id: str) -> dict          # writes to HAPI, emits FhirPublished
  ```

- [ ] **Step 1: Write the failing tests**

```python
# services/core-api/tests/test_fhir_mapper.py — key assertions
def test_riskassessment_status_maps_from_episode_state():
    assert episode_to_riskassessment(ep(state="SUSPECTED"), snap, net)["status"] == "preliminary"
    assert episode_to_riskassessment(ep(state="CONFIRMED"), snap, net)["status"] == "final"
    assert episode_to_riskassessment(ep(state="REFUTED"),   snap, net)["status"] == "cancelled"

def test_meta_tag_carries_the_exact_episode_state():
    ra = episode_to_riskassessment(ep(state="PROBABLE"), snap, net)
    assert ra["meta"]["tag"][0]["code"] == "PROBABLE"

def test_one_prediction_per_zone_with_a_period_and_a_decimal_probability():
    ra = episode_to_riskassessment(ep(), snap_with_two_zones, net)
    assert len(ra["prediction"]) == 2
    assert all("whenPeriod" in p and isinstance(p["probabilityDecimal"], float)
               for p in ra["prediction"])

def test_fingerprint_extension_matches_the_snapshot():
    ra = episode_to_riskassessment(ep(), snap, net)
    fp = next(e for e in ra["extension"] if e["url"].endswith("upstream-fingerprint"))
    assert fp["valueString"] == snap["fingerprint"]

def test_note_carries_the_not_a_diagnosis_disclaimer():
    """GC-12."""
    ra = episode_to_riskassessment(ep(), snap, net)
    assert any("not a diagnosis" in n["text"].lower() for n in ra["note"])

def test_negative_observation_uses_data_absent_reason_not_a_value():
    o = evidence_to_observation(negative_evidence_event, retracted=False)
    assert "valueQuantity" not in o and o["dataAbsentReason"]["coding"][0]["code"] == "not-performed"

def test_retracted_observation_becomes_entered_in_error():
    """FR-10 + FR-26: a retraction changes status; it never deletes."""
    assert evidence_to_observation(ev, retracted=True)["status"] == "entered-in-error"

def test_observation_carries_both_times():
    o = evidence_to_observation(late_lab_event, retracted=False)
    assert o["effectiveDateTime"] < o["issued"]

def test_lab_value_uses_ucum():
    o = evidence_to_observation(lab_event, retracted=False)
    assert o["valueQuantity"]["system"] == "http://unitsofmeasure.org"

def test_provenance_lists_kernel_and_ai_agents_and_the_confirming_citizen():
    p = provenance_for("RiskAssessment/x", "3", snap, ["Observation/a"], agents)
    roles = {a["type"]["coding"][0]["code"] for a in p["agent"]}
    assert {"assembler", "author"} <= roles

@pytest.mark.integration
def test_every_generated_resource_passes_the_hl7_validator():
    """GC-3 / FR-26: validation on write, not just in CI."""
    for r in [episode_to_riskassessment(ep(), snap, net),
              evidence_to_observation(ev, retracted=False),
              zone_to_location(net, "ZONE_A"), zone_to_group(net, "ZONE_A")]:
        assert validate_against_hapi(r)["issue_errors"] == 0
```

- [ ] **Step 2: Implement `mapper.py`**

```python
# services/core-api/upstream_api/fhir/mapper.py
"""Map internal state to FHIR R4 on the OAH IG (PRD 13.2, 13.3).

FHIR is a published VIEW (GC-2). Nothing here reads back into the engine; HAPI can be
dropped and rebuilt from the event log at any time.
"""
from __future__ import annotations
import datetime as dt
from upstream_shared.codes import LOCAL_CS
from upstream_shared.episode import EpisodeState

SD = "https://upstream-onehealth.example/StructureDefinition"
DISCLAIMER = "Environmental exposure context, not a diagnosis."

_STATUS = {EpisodeState.SUSPECTED: "preliminary", EpisodeState.PROBABLE: "preliminary",
           EpisodeState.CONFIRMED: "final", EpisodeState.RESOLVED: "final",
           EpisodeState.REFUTED: "cancelled"}

def episode_to_riskassessment(ep: dict, snapshot: dict, net) -> dict:
    state = EpisodeState(ep["state"])
    status = "amended" if ep["version"] > 1 and state in (
        EpisodeState.SUSPECTED, EpisodeState.PROBABLE) else _STATUS[state]
    predictions, windows = [], []
    for zone_id, z in (snapshot["zone_windows"] or {}).items():
        if z["window_lo"] is None:
            continue
        predictions.append({
            "outcome": {"text": "Acute gastrointestinal illness"},
            "probabilityDecimal": round(float(z["p_peak"]), 4),
            "whenPeriod": {"start": _iso(z["window_lo"]),
                           "end": ep["clinical_window_end"].isoformat()}})
        windows.append({"url": f"{SD}/upstream-exposure-window", "extension": [
            {"url": "zone", "valueReference": {"reference": f"Location/zone-{zone_id.lower()}"}},
            {"url": "window", "valuePeriod": {"start": _iso(z["window_lo"]),
                                              "end": _iso(z["window_hi"])}},
            {"url": "credibleLevel", "valueDecimal": 0.80},
            *[{"url": "pathway", "valueCoding":
               {"system": f"{LOCAL_CS}/exposure-pathway", "code": pw}} for pw in z["pathways"]]]})

    ranking = [{"url": f"{SD}/upstream-source-ranking", "extension": [
        {"url": "sourceLocation", "valueReference": {"reference": f"Location/{k.lower()}"}},
        {"url": "probability", "valueDecimal": round(float(v), 4)}]}
        for k, v in sorted((snapshot["source_marginals"] or {}).items(),
                           key=lambda kv: -kv[1])[:3] if not k.startswith("__")]

    return {
        "resourceType": "RiskAssessment",
        "id": f"{ep['episode_id'].lower()}-v{ep['version']}",
        "meta": {"profile": [f"{SD}/UpstreamExposureEpisode"],
                 "tag": [{"system": f"{LOCAL_CS}/episode-state", "code": state.value}]},
        "identifier": [{"system": "https://upstream-onehealth.example/episode",
                        "value": ep["episode_id"]}],
        "status": status,
        "subject": {"reference": f"Group/{_primary_zone(snapshot)}-population"},
        "occurrenceDateTime": _iso(snapshot["ts"]),
        "method": {"text": snapshot["kernel_version"]},
        "basis": [{"reference": f"Observation/{e}"} for e in snapshot.get("evidence_ids", [])],
        "prediction": predictions,
        "note": [{"text": f"Fingerprint {snapshot['fingerprint']}. {DISCLAIMER}"}],
        "extension": [{"url": f"{SD}/upstream-fingerprint",
                       "valueString": snapshot["fingerprint"]}, *ranking, *windows],
    }

def evidence_to_observation(ev, *, retracted: bool) -> dict:
    p = ev.payload
    obs = {
        "resourceType": "Observation",
        "id": f"ev-{str(ev.event_id)[:8]}",
        "meta": {"profile": [f"{SD}/UpstreamEvidenceObservation"]},
        "status": "entered-in-error" if retracted else "final",      # FR-10
        "code": {"coding": [{"system": f"{LOCAL_CS}/observation-method", "code": p["method"]}]},
        "subject": {"reference": f"Location/{p['node_id'].lower()}"},
        "effectiveDateTime": ev.event_time.isoformat(),              # GC-4 event time
        "issued": ev.recorded_at.isoformat(),                        # GC-4 record time
        "method": {"coding": [{"system": f"{LOCAL_CS}/observation-method",
                               "code": p["method"]}]},
        "performer": [{"display": p["observer_id"]}],
    }
    if p["result"] == "quantitative":
        obs["valueQuantity"] = {"value": p["value"], "unit": p["unit"],
                                "system": "http://unitsofmeasure.org", "code": p["unit"]}
    elif p["result"] == "negative":
        # An explicit negative check is not a missing value; it is a recorded non-detection.
        obs["dataAbsentReason"] = {"coding": [{
            "system": "http://terminology.hl7.org/CodeSystem/data-absent-reason",
            "code": "not-performed", "display": "Checked; nothing detected"}]}
        obs["interpretation"] = [{"coding": [{
            "system": "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation",
            "code": "NEG", "display": "Negative"}]}]
    else:
        obs["interpretation"] = [{"coding": [{
            "system": "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation",
            "code": "POS", "display": "Positive"}]}]
    if p.get("ai_assisted"):
        obs["extension"] = [{"url": f"{SD}/upstream-ai-assisted", "extension": [
            {"url": "modelId", "valueString": p.get("ai_model", "claude-opus-5")},
            {"url": "confirmedByObserver",
             "valueBoolean": bool(p.get("confirmed_by_observer"))}]}]
    return obs

def provenance_for(ra_ref: str, ra_version: str, snapshot: dict,
                   evidence_refs: list[str], agents: list[dict]) -> dict:
    return {
        "resourceType": "Provenance",
        "meta": {"profile": [f"{SD}/UpstreamEpisodeProvenance"]},
        "target": [{"reference": ra_ref, "display": f"version {ra_version}"}],
        "recorded": dt.datetime.now(dt.UTC).isoformat(),
        "agent": [
            {"type": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/provenance-participant-type",
                                  "code": "assembler"}]},
             "who": {"display": snapshot["kernel_version"]}},
            *agents],
        "entity": [{"role": "source", "what": {"reference": r}} for r in evidence_refs],
        "signature": [],
    }

def _iso(v) -> str:
    return v.isoformat() if hasattr(v, "isoformat") else \
        dt.datetime.fromtimestamp(float(v), dt.UTC).isoformat()

def _primary_zone(snapshot: dict) -> str:
    zones = snapshot["zone_windows"] or {}
    if not zones:
        return "unknown"
    return max(zones.items(), key=lambda kv: kv[1]["p_peak"])[0].lower()
```

- [ ] **Step 3: Implement `client.py` and `publisher.py`**

```python
# services/core-api/upstream_api/fhir/client.py
"""HAPI client that validates on write (FR-26). A validation error is a hard failure."""
import httpx
from ..config import settings

class FhirClient:
    def __init__(self, base_url: str | None = None):
        self.base = (base_url or settings.hapi_base_url).rstrip("/")

    def validate(self, resource: dict) -> dict:
        rt = resource["resourceType"]
        r = httpx.post(f"{self.base}/{rt}/$validate", json=resource, timeout=30.0)
        oo = r.json()
        errors = [i for i in oo.get("issue", [])
                  if i.get("severity") in ("error", "fatal")]
        return {"issue_errors": len(errors), "issues": errors}

    def put(self, resource: dict) -> dict:
        v = self.validate(resource)
        if v["issue_errors"]:
            raise ValueError(f"GC-3 violation: {v['issues']}")
        rt, rid = resource["resourceType"], resource["id"]
        r = httpx.put(f"{self.base}/{rt}/{rid}", json=resource, timeout=30.0)
        r.raise_for_status()
        return {"id": rid, "version": r.headers.get("ETag", "").strip('W/"')}
```

```python
# services/core-api/upstream_api/fhir/publisher.py
"""Publish an episode and its evidence to HAPI, then record FhirPublished."""
def publish_episode(episode_id: str) -> dict:
    ep = _episode(episode_id); snap = _latest_snapshot(episode_id)
    client = FhirClient()
    refs = []
    for ev, retracted in _evidence_for(episode_id):
        refs.append("Observation/" + client.put(
            evidence_to_observation(ev, retracted=retracted))["id"])
    for zone_id in (snap["zone_windows"] or {}):
        client.put(zone_to_location(get_network(), zone_id))
        client.put(zone_to_group(get_network(), zone_id))
    ra = episode_to_riskassessment(ep, snap | {"evidence_ids": [r.split("/")[1] for r in refs]},
                                   get_network())
    res = client.put(ra)
    client.put(provenance_for(f"RiskAssessment/{res['id']}", res["version"], snap, refs,
                              agents=_human_agents(episode_id)))
    store.append(EventEnvelope(stream=ep["stream"], catchment_id=settings.catchment_id,
                               event_type=EventType.FHIR_PUBLISHED,
                               event_time=dt.datetime.now(dt.UTC),
                               payload={"episode_id": episode_id,
                                        "risk_assessment_id": res["id"],
                                        "fhir_version_id": res["version"],
                                        "observation_count": len(refs)}))
    return res
```

- [ ] **Step 4: Hook publishing to state changes, register the Subscription (FR-29)**

Call `publish_episode(...)` from `_transition(...)` in `workflows/episode.py`, and register the
topic-based `Subscription` at startup:

```python
# services/core-api/upstream_api/fhir/subscriptions.py
SUBSCRIPTION = {
  "resourceType": "Subscription", "id": "upstream-episode-state-change", "status": "requested",
  "meta": {"profile": ["http://hl7.org/fhir/uv/subscriptions-backport/StructureDefinition/backport-subscription"]},
  "criteria": "https://upstream-onehealth.example/SubscriptionTopic/episode-state-change",
  "channel": {"type": "rest-hook", "endpoint": "", "payload": "application/fhir+json",
              "_payload": {"extension": [{
                "url": "http://hl7.org/fhir/uv/subscriptions-backport/StructureDefinition/backport-payload-content",
                "valueCode": "id-only"}]}},
  "reason": "Notify public health systems of Exposure Episode state changes",
}
```

- [ ] **Step 5: Run tests and commit**

```bash
docker compose run --rm api pytest services/core-api/tests/test_fhir_mapper.py -v
./fhir/scripts/validate.sh
git add services/core-api/upstream_api/fhir/
git commit -m "feat(fhir): mapper, validating HAPI client, publisher, subscription topic"
```

---

### Task 7.4: CDS Hooks service and AuditEvent

**Files:**
- Create: `services/core-api/upstream_api/fhir/{cds_hooks.py,audit.py}`
- Test: `services/core-api/tests/test_cds_hooks.py`

**Interfaces:**
- Produces:
  - `GET /cds-services` — discovery document
  - `POST /cds-services/upstream-exposure-context` — the card service (both hooks)
  - `def card_for(patient_area: str, encounter_time: datetime, reason_codes: list[str]) -> dict | None`
  - `def write_audit(event_type: str, *, outcome: str, detail: dict) -> None`

- [ ] **Step 1: Write the failing tests — the three-condition rule is the whole service**

```python
# services/core-api/tests/test_cds_hooks.py
def test_discovery_lists_both_hooks():
    s = client.get("/cds-services").json()["services"]
    assert {x["hook"] for x in s} == {"patient-view", "encounter-start"}

def test_card_returned_when_area_window_and_syndrome_all_match():
    r = _hook(area="ZONE_B", when=inside_window, reason=["acute_gastroenteritis"])
    assert len(r["cards"]) == 1
    assert "EE-" in r["cards"][0]["summary"]

def test_no_card_when_the_area_does_not_overlap():
    assert _hook(area="ZONE_FAR", when=inside_window,
                 reason=["acute_gastroenteritis"])["cards"] == []

def test_no_card_outside_the_clinical_relevance_window():
    assert _hook(area="ZONE_B", when=twenty_days_later,
                 reason=["acute_gastroenteritis"])["cards"] == []

def test_no_card_for_an_unrelated_reason_for_visit():
    assert _hook(area="ZONE_B", when=inside_window, reason=["ankle_sprain"])["cards"] == []

def test_card_suggests_pathogen_specific_testing():
    """PRD 7.6: the card's value is prompting a test routine panels may not include."""
    c = _hook(area="ZONE_B", when=inside_window, reason=["acute_gastroenteritis"])["cards"][0]
    assert "cryptosporidium" in c["detail"].lower()

def test_card_says_it_is_not_a_diagnosis():
    c = _hook(area="ZONE_B", when=inside_window, reason=["acute_gastroenteritis"])["cards"][0]
    assert "not a diagnosis" in c["detail"].lower()

def test_service_stores_nothing_about_the_patient():
    before = count_rows_everywhere()
    _hook(area="ZONE_B", when=inside_window, reason=["acute_gastroenteritis"])
    assert count_patient_rows() == 0 and count_rows_everywhere() == before + 1  # only the AuditEvent

def test_every_call_writes_an_auditevent_without_clinical_content():
    _hook(area="ZONE_B", when=inside_window, reason=["acute_gastroenteritis"])
    a = last_audit_event()
    assert a["type"]["code"] == "rest" and "acute_gastroenteritis" not in json.dumps(a)

def test_response_is_under_the_latency_budget():
    """NFR-2: clinicians are waiting."""
    t = timeit(lambda: _hook(area="ZONE_B", when=inside_window,
                             reason=["acute_gastroenteritis"]), number=20) / 20
    assert t < 0.5
```

- [ ] **Step 2: Implement `cds_hooks.py`**

```python
# services/core-api/upstream_api/fhir/cds_hooks.py
"""CDS Hooks service (PRD 13.4, FR-28).

Three conditions, all of which must hold, or no card is returned:
  1. the patient's coarse area overlaps an active episode's exposure zone,
  2. the encounter falls inside the clinical relevance window,
  3. the reason for the visit matches the episode's syndrome set.

Stores nothing. Active episode zones are held in memory and refreshed on a short interval,
so the p99 stays well under the 500 ms budget (NFR-2).
"""
from __future__ import annotations
import datetime as dt, time
from fastapi import APIRouter, Request
from upstream_shared.codes import SYNDROME_SET
from .audit import write_audit

router = APIRouter(tags=["cds-hooks"])
SERVICE_ID = "upstream-exposure-context"
_CACHE: dict = {"at": 0.0, "episodes": []}
_CACHE_TTL_S = 30

@router.get("/cds-services")
def discovery():
    common = {"id": SERVICE_ID, "title": "Upstream exposure context",
              "description": ("Shows recent stream contamination episodes affecting this "
                              "patient's area, inside the clinical relevance window."),
              "prefetch": {"patient": "Patient/{{context.patientId}}"}}
    return {"services": [dict(common, hook="patient-view"),
                         dict(common, hook="encounter-start",
                              id=f"{SERVICE_ID}-encounter")]}

@router.post("/cds-services/{service_id}")
async def hook(service_id: str, request: Request):
    body = await request.json()
    area = _coarse_area(body)                       # postcode / district only
    when = _encounter_time(body)
    reasons = _reason_codes(body)
    cards = []
    ep = _match(area, when, reasons)
    if ep:
        cards.append(_card(ep))
    write_audit("cds-card-served", outcome="0",
                detail={"service": service_id, "matched": bool(ep),
                        "episode_id": ep["episode_id"] if ep else None})
    return {"cards": cards}

def _match(area: str | None, when: dt.datetime, reasons: list[str]) -> dict | None:
    if not area or not reasons:
        return None
    if not set(reasons) & set(SYNDROME_SET):                       # condition 3
        return None
    for ep in _active_episodes():
        if area not in ep["zone_areas"]:                            # condition 1
            continue
        if not (ep["exposure_start"] <= when <= ep["clinical_window_end"]):   # condition 2
            continue
        return ep
    return None

def _card(ep: dict) -> dict:
    start = ep["exposure_start"].strftime("%d %b, %H:%M")
    end = ep["exposure_end"].strftime("%H:%M")
    return {
        "summary": f"Recent stream contamination episode in this patient's area ({ep['episode_id']})",
        "indicator": "info",
        "detail": (f"Probable sewage-related contamination of a local stream on {start}-{end}. "
                   "This visit is within the clinical relevance window. If symptoms fit, "
                   "consider pathogen-specific stool testing (for example Cryptosporidium), "
                   "which routine panels may not include. "
                   "Environmental context, not a diagnosis."),
        "source": {"label": "Upstream",
                   "url": "https://upstream-onehealth.example"},
        "links": [{"label": "Episode details",
                   "url": f"https://upstream-onehealth.example/smart/launch?episode={ep['episode_id']}",
                   "type": "smart"}],
    }

def _active_episodes() -> list[dict]:
    if time.time() - _CACHE["at"] < _CACHE_TTL_S:
        return _CACHE["episodes"]
    from ..db import pool
    with pool.connection() as c, c.cursor() as cur:
        cur.execute("""SELECT episode_id, est_start_lo, est_start_hi, clinical_window_end,
                              summary FROM episodes
                       WHERE state IN ('PROBABLE','CONFIRMED')
                         AND clinical_window_end > now()""")
        eps = [{"episode_id": r[0], "exposure_start": r[1], "exposure_end": r[2],
                "clinical_window_end": r[3],
                "zone_areas": set((r[4] or {}).get("zone_areas", []))} for r in cur.fetchall()]
    _CACHE.update(at=time.time(), episodes=eps)
    return eps
```

- [ ] **Step 3: Implement `audit.py` (FR-30)**

```python
# services/core-api/upstream_api/fhir/audit.py
"""AuditEvent for every CDS card served and every external read (FR-30, PRD 14.3).

Never records clinical content — only that a decision was made and for which episode.
"""
import datetime as dt
from .client import FhirClient

def write_audit(action: str, *, outcome: str, detail: dict) -> None:
    ae = {
        "resourceType": "AuditEvent",
        "type": {"system": "http://terminology.hl7.org/CodeSystem/audit-event-type",
                 "code": "rest", "display": "RESTful Operation"},
        "action": "R",
        "recorded": dt.datetime.now(dt.UTC).isoformat(),
        "outcome": outcome,
        "agent": [{"type": {"coding": [{
            "system": "http://terminology.hl7.org/CodeSystem/extra-security-role-type",
            "code": "dataprocessor"}]}, "who": {"display": "upstream-cds-hooks"},
            "requestor": False}],
        "source": {"observer": {"display": "Upstream Core API"}},
        "entity": [{"what": {"display": detail.get("episode_id") or "no-match"},
                    "detail": [{"type": "action", "valueString": action},
                               {"type": "matched",
                                "valueString": str(detail.get("matched"))}]}],
    }
    try:
        FhirClient().put(ae | {"id": f"audit-{int(dt.datetime.now().timestamp()*1000)}"})
    except Exception as exc:
        print(f"[audit] failed: {exc}")     # never fail a clinician's request on an audit write
```

- [ ] **Step 4: Verify against the public CDS Hooks sandbox**

```bash
docker compose up -d api
# Expose the service (ngrok or a tunnel), then in https://sandbox.cds-hooks.org:
#   add discovery endpoint  https://<tunnel>/cds-services
#   choose patient-view, set the patient's address postcode to a zone area
```

Expected: the info card renders with the "not a diagnosis" line and the SMART link.

- [ ] **Step 5: Run tests and commit**

```bash
docker compose run --rm api pytest services/core-api/tests/test_cds_hooks.py -v
git add services/core-api/upstream_api/fhir/
git commit -m "feat(fhir): CDS Hooks service with three-condition card rule and AuditEvent"
```

## Phase 7 exit criteria

- **`./fhir/scripts/validate.sh` reports `validator errors: 0`** and the CI `fhir` job is green. (GC-3 — without this, fall back to Track 6 per PRD §3.2.)
- Every episode state change publishes a `RiskAssessment` + `Provenance` + `Observation`s to HAPI, validated on write, and emits `FhirPublished`.
- Retracted evidence appears as `entered-in-error`, never deleted.
- The CDS card appears in the public sandbox only when area **and** window **and** syndrome match; p95 under 500 ms; an `AuditEvent` is written for every call with no clinical content.
- A screen recording of the sandbox card exists for the demo video (scene 2:50–3:30).

## 🔑 Credentials needed at the end of Phase 7

| Variable | What it is | Where to get it |
|---|---|---|
| `OAH_IG_VERSION` | Version of `hl7.eu.fhir.oah` to load | From `curl -s https://packages.fhir.org/hl7.eu.fhir.oah`. If unpublished, use `current` with the vendored tarball. **No key.** |
| `TX_SERVER_URL` | Terminology server for the validator | Optional. Default `http://tx.fhir.org`. **No key.** Set to `n/a` to disable terminology checks if tx.fhir.org is slow. |
| `SNOMED_LICENCE_ACCEPTED` | Whether SNOMED CT codes may be used | **Your decision** (PRD open question 5). If you have no SNOMED affiliate licence for the pilot country, set `false` and the syndrome value set uses the local code system only — the PRD already allows "where licensed" (GC-13). |
| — | Public tunnel for the CDS Hooks sandbox | `ngrok`, `cloudflared` or similar. A free ngrok account gives a stable URL; **optional** if you demo from `localhost` with the sandbox's local mode. |

---

# Phase 8 — BRIDGE part 2: the clinical statistics service and the health boundary

**Day 4, afternoon (≈3 h).** The One Health loop closes here — and so does the privacy boundary.

**PRD coverage:** §7.6 (matched filter), §10.4 Layer 7, FR-32…FR-35, §14.1, G5, NFR-5, GC-7, GC-12.

## File structure

```
services/clinical-stats/clinical_stats/
├── main.py            # FastAPI app on port 8100, separate container and DB
├── db.py              # connects ONLY to CLINICAL_DATABASE_URL
├── ingest.py          # POST /counts — MeasureReport in, small counts suppressed
├── baselines.py       # negative-binomial GLM with seasonality and day-of-week
├── matched_filter.py  # expected case-curve shape + one-sided test
├── cluster.py         # space-time scan for unexplained clusters (FR-35)
└── episode_client.py  # read-only calls to the Core API for episode windows
db/migrations_clinical/  # separate alembic chain for the clinical database
```

**The boundary, restated:** this service has its own container, its own database, its own
role, and no credential for the environmental database. The only things that cross are
**aggregate counts in** and **test results out** (GC-7).

---

### Task 8.1: Clinical schema, aggregate ingestion and small-count suppression

**Files:**
- Create: `db/migrations_clinical/versions/0001_clinical.py`, `services/clinical-stats/clinical_stats/{db.py,ingest.py,main.py}`
- Test: `services/clinical-stats/tests/test_boundary.py`

**Interfaces:**
- Produces: tables `syndromic_counts` (hypertable), `baselines`, `test_results`; route
  `POST /counts` accepting a `UpstreamSyndromicCount` MeasureReport.
  ```python
  SUPPRESSION_THRESHOLD = 5
  def ingest_measure_report(mr: dict) -> dict     # {"accepted": n, "suppressed": m}
  ```

- [ ] **Step 1: Write the failing boundary tests — these are the ones judges will look for**

```python
# services/clinical-stats/tests/test_boundary.py
def test_clinical_service_has_no_environmental_credential():
    """GC-7: the separation is enforced by configuration, not by convention."""
    import clinical_stats.db as d
    assert "clinical" in d.DSN
    assert os.environ.get("DATABASE_URL") not in (d.DSN,)

@pytest.mark.integration
def test_clinical_role_cannot_read_the_environmental_database(clinical_conn):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        clinical_conn.execute("SELECT * FROM dblink('dbname=upstream','SELECT 1') AS t(x int)")

def test_small_counts_are_suppressed_on_ingest():
    r = ingest_measure_report(measure_report(count=3))
    assert r["suppressed"] == 1 and r["accepted"] == 0

def test_counts_at_or_above_the_threshold_are_accepted():
    assert ingest_measure_report(measure_report(count=5))["accepted"] == 1

def test_no_patient_identifier_can_be_stored(clinical_conn):
    cols = all_column_names(clinical_conn)
    assert not any(c in cols for c in ("patient_id", "nhs_number", "mrn", "name", "dob"))

def test_only_test_results_leave_the_service(http_log):
    run_daily_tests()
    outbound = [c for c in http_log if c.method == "POST"]
    assert all(set(json.loads(c.body)) <= {"episode_id", "p_value", "effect_size",
                                           "n_days", "method", "computed_at"}
               for c in outbound)
```

- [ ] **Step 2: Implement the migration and ingestion**

```python
# db/migrations_clinical/versions/0001_clinical.py
from alembic import op
revision, down_revision = "c0001", None

def upgrade():
    op.execute("""
    CREATE EXTENSION IF NOT EXISTS timescaledb;
    CREATE TABLE syndromic_counts (
      day DATE NOT NULL, area_code TEXT NOT NULL, syndrome TEXT NOT NULL,
      count INT NOT NULL CHECK (count >= 5),        -- suppression enforced by the schema
      source TEXT NOT NULL, received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      PRIMARY KEY (day, area_code, syndrome));
    SELECT create_hypertable('syndromic_counts','day', migrate_data => true);

    CREATE TABLE baselines (
      area_code TEXT NOT NULL, syndrome TEXT NOT NULL,
      fitted_at TIMESTAMPTZ NOT NULL, alpha DOUBLE PRECISION NOT NULL,
      coefficients JSONB NOT NULL, n_obs INT NOT NULL,
      PRIMARY KEY (area_code, syndrome));

    CREATE TABLE test_results (
      result_id BIGSERIAL PRIMARY KEY, episode_id TEXT, area_code TEXT NOT NULL,
      syndrome TEXT NOT NULL, method TEXT NOT NULL,
      p_value DOUBLE PRECISION NOT NULL, effect_size DOUBLE PRECISION,
      n_days INT NOT NULL, computed_at TIMESTAMPTZ NOT NULL DEFAULT now());
    """)

def downgrade():
    op.execute("DROP TABLE test_results; DROP TABLE baselines; DROP TABLE syndromic_counts;")
```

```python
# services/clinical-stats/clinical_stats/ingest.py
"""FR-32: accept aggregate syndrome counts as MeasureReport. Suppress small counts.

Nothing here can accept a patient-level resource: the only route takes a MeasureReport, and
the schema's CHECK (count >= 5) makes a suppressed value unstorable even by mistake.
"""
from __future__ import annotations
import datetime as dt
from fastapi import APIRouter, HTTPException
from .db import conn

router = APIRouter(tags=["clinical"])
SUPPRESSION_THRESHOLD = 5

@router.post("/counts")
def post_counts(mr: dict) -> dict:
    return ingest_measure_report(mr)

def ingest_measure_report(mr: dict) -> dict:
    if mr.get("resourceType") != "MeasureReport":
        raise HTTPException(400, "only MeasureReport is accepted at this boundary")
    if mr.get("type") != "summary":
        raise HTTPException(400, "only aggregate (summary) reports are accepted (GC-7)")
    area = mr["subject"]["reference"].split("/")[-1]
    period_start = dt.date.fromisoformat(mr["period"]["start"][:10])
    accepted = suppressed = 0
    for g in mr.get("group", []):
        syndrome = g["code"]["coding"][0]["code"]
        value = (g.get("measureScore") or {}).get("value")
        if value is None or value < SUPPRESSION_THRESHOLD:
            suppressed += 1
            continue
        with conn() as c, c.cursor() as cur:
            cur.execute("""INSERT INTO syndromic_counts (day,area_code,syndrome,count,source)
                           VALUES (%s,%s,%s,%s,%s)
                           ON CONFLICT (day,area_code,syndrome)
                           DO UPDATE SET count=EXCLUDED.count, received_at=now()""",
                        (period_start, area, syndrome, int(value), "measure-report"))
        accepted += 1
    return {"accepted": accepted, "suppressed": suppressed}
```

- [ ] **Step 3: Run tests and commit**

```bash
docker compose run --rm clinical pytest services/clinical-stats/tests/test_boundary.py -v
git add db/migrations_clinical services/clinical-stats/
git commit -m "feat(clinical): isolated clinical database, aggregate-only ingestion with suppression"
```

---

### Task 8.2: Baselines and the matched filter

**Files:**
- Create: `services/clinical-stats/clinical_stats/{baselines.py,matched_filter.py,episode_client.py}`
- Test: `services/clinical-stats/tests/test_matched_filter.py`

**Interfaces:**
- Produces:
  ```python
  @dataclass(frozen=True)
  class Baseline:
      area_code: str; syndrome: str; alpha: float
      predict: Callable[[np.ndarray], np.ndarray]     # dates -> expected counts

  def fit_baseline(days: np.ndarray, counts: np.ndarray, *, area_code, syndrome) -> Baseline

  def expected_curve(zone_exposure: dict, pathogen_mix: dict[PathogenClass, float],
                     days: np.ndarray, *, attack_rate: float = 0.02) -> np.ndarray
      # exposure(t) convolved with each pathogen's incubation distribution, mixed by weight

  @dataclass(frozen=True)
  class TestResult:
      episode_id: str; area_code: str; syndrome: str; method: str
      p_value: float; effect_size: float; n_days: int

  def matched_filter_test(counts, baseline, shape, *, episode_id, area_code,
                          syndrome) -> TestResult
  ```

- [ ] **Step 1: Write the failing tests**

```python
# services/clinical-stats/tests/test_matched_filter.py
def test_expected_curve_peaks_after_the_exposure_window():
    c = expected_curve(zone_exposure_at_day0, SEWAGE_PATHOGEN_MIX, days=np.arange(0, 21))
    assert 2 <= int(np.argmax(c)) <= 8          # sewage mix peaks a few days out

def test_norovirus_heavy_mix_peaks_earlier_than_a_crypto_heavy_mix():
    early = expected_curve(z, {PathogenClass.NOROVIRUS: 1.0}, days=np.arange(0, 21))
    late  = expected_curve(z, {PathogenClass.CRYPTOSPORIDIUM: 1.0}, days=np.arange(0, 21))
    assert np.argmax(early) < np.argmax(late)

def test_curve_integrates_to_the_attack_rate_times_population():
    c = expected_curve(z, SEWAGE_PATHOGEN_MIX, days=np.arange(0, 40), attack_rate=0.02)
    assert c.sum() == pytest.approx(0.02 * z["population"], rel=0.05)

def test_baseline_captures_day_of_week_effect():
    b = fit_baseline(days, counts_with_monday_spike, area_code="A", syndrome="ag")
    assert b.predict(mondays).mean() > b.predict(sundays).mean()

def test_matched_filter_detects_an_injected_excess_matching_the_shape():
    r = matched_filter_test(counts_baseline_plus_matching_excess, baseline, shape,
                            episode_id="EE-1", area_code="A", syndrome="ag")
    assert r.p_value < 0.01 and r.effect_size > 0

def test_matched_filter_ignores_an_excess_with_the_wrong_shape():
    """The whole point: looking for a known shape, not for any bump."""
    r = matched_filter_test(counts_with_excess_two_weeks_early, baseline, shape,
                            episode_id="EE-1", area_code="A", syndrome="ag")
    assert r.p_value > 0.10

def test_no_excess_gives_a_uniform_p_value_distribution():
    """Calibration: under the null, p-values should be roughly uniform."""
    ps = [matched_filter_test(simulate_null(seed=s), baseline, shape,
                              episode_id="x", area_code="A", syndrome="ag").p_value
          for s in range(200)]
    assert 0.02 <= np.mean(np.array(ps) < 0.05) <= 0.10

def test_matched_filter_beats_a_blind_cluster_scan_on_detection_delay():
    """G5 — the claim the PRD makes, tested directly."""
    assert mean_delay_matched < mean_delay_blind_scan
```

- [ ] **Step 2: Implement `matched_filter.py`**

```python
# services/clinical-stats/clinical_stats/matched_filter.py
"""PRD 7.6: look for the SHAPE the case curve should have, not for any cluster.

The expected shape is the zone's exposure probability curve convolved with the incubation
distribution of each plausible pathogen class, mixed by the source type's weights. Testing
for that specific shape above a negative-binomial baseline is far more sensitive than a
blind scan — like listening for a known voice in a noisy room.
"""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import statsmodels.api as sm
from scipy.stats import gamma
from upstream_shared.codes import INCUBATION_DAYS, PathogenClass

@dataclass(frozen=True)
class TestResult:
    episode_id: str; area_code: str; syndrome: str; method: str
    p_value: float; effect_size: float; n_days: int

def _incubation_pdf(pc: PathogenClass, days: np.ndarray) -> np.ndarray:
    mean, sd = INCUBATION_DAYS[pc]
    shape = (mean / sd) ** 2
    scale = sd ** 2 / mean
    return gamma.pdf(days, a=shape, scale=scale)

def expected_curve(zone_exposure: dict, pathogen_mix: dict[PathogenClass, float],
                   days: np.ndarray, *, attack_rate: float = 0.02) -> np.ndarray:
    """Exposure(day) convolved with the mixed incubation distribution."""
    t = np.asarray(zone_exposure["t_grid"], dtype=float)
    p = np.asarray(zone_exposure["p_exposed"], dtype=float)
    day0 = t.min() / 86400.0
    exposure_by_day = np.zeros(len(days))
    for ti, pi in zip(t, p):
        d = int(ti / 86400.0 - day0)
        if 0 <= d < len(days):
            exposure_by_day[d] += pi
    if exposure_by_day.sum() > 0:
        exposure_by_day /= exposure_by_day.sum()
    lag = np.arange(0, len(days))
    kernel = sum(w * _incubation_pdf(pc, lag) for pc, w in pathogen_mix.items())
    kernel = kernel / max(kernel.sum(), 1e-12)
    shape = np.convolve(exposure_by_day, kernel)[:len(days)]
    return shape * attack_rate * float(zone_exposure.get("population", 1000))

def matched_filter_test(counts: np.ndarray, baseline, shape: np.ndarray, *,
                        episode_id: str, area_code: str, syndrome: str) -> TestResult:
    """Negative-binomial GLM: counts ~ offset(log baseline) + beta * shape, one-sided on beta.

    beta > 0 means "an excess with the predicted shape". The p-value answers exactly the
    question a public health officer asks, and nothing more (GC-12).
    """
    n = len(counts)
    mu0 = np.maximum(baseline.predict(np.arange(n)), 1e-6)
    X = sm.add_constant(shape[:n] / max(shape[:n].max(), 1e-12))
    model = sm.GLM(counts, X, family=sm.families.NegativeBinomial(alpha=baseline.alpha),
                   offset=np.log(mu0))
    fit = model.fit()
    beta = float(fit.params[1])
    p_two_sided = float(fit.pvalues[1])
    p_one_sided = p_two_sided / 2 if beta > 0 else 1.0 - p_two_sided / 2
    return TestResult(episode_id=episode_id, area_code=area_code, syndrome=syndrome,
                      method="matched-filter-nb", p_value=p_one_sided,
                      effect_size=beta, n_days=n)
```

- [ ] **Step 3: Implement `baselines.py`**

```python
# services/clinical-stats/clinical_stats/baselines.py
"""FR-33: seasonal and day-of-week baselines per area and syndrome (Noufaily-style)."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable
import numpy as np
import statsmodels.api as sm

@dataclass(frozen=True)
class Baseline:
    area_code: str; syndrome: str; alpha: float
    predict: Callable[[np.ndarray], np.ndarray]

def _design(day_index: np.ndarray) -> np.ndarray:
    t = day_index / 365.25
    dow = np.eye(7)[(day_index % 7).astype(int)][:, 1:]        # drop one level
    return np.column_stack([np.ones_like(t), t,
                            np.sin(2*np.pi*t), np.cos(2*np.pi*t),
                            np.sin(4*np.pi*t), np.cos(4*np.pi*t), dow])

def fit_baseline(days: np.ndarray, counts: np.ndarray, *, area_code: str,
                 syndrome: str) -> Baseline:
    X = _design(days)
    poisson = sm.GLM(counts, X, family=sm.families.Poisson()).fit()
    resid = (counts - poisson.mu) ** 2 - poisson.mu
    alpha = float(max(np.sum(resid) / np.sum(poisson.mu ** 2), 1e-3))
    nb = sm.GLM(counts, X, family=sm.families.NegativeBinomial(alpha=alpha)).fit()
    return Baseline(area_code=area_code, syndrome=syndrome, alpha=alpha,
                    predict=lambda d: np.asarray(nb.predict(_design(np.asarray(d)))))
```

- [ ] **Step 4: Daily job + result publication (FR-34) and reverse direction (FR-35)**

```python
# services/clinical-stats/clinical_stats/main.py (the daily job)
@app.post("/run-daily")
def run_daily():
    """FR-34: run the matched-filter test for every active episode and publish ONLY the result."""
    published = []
    for ep in episode_client.active_episodes():          # read-only, windows and zones only
        for zone_id, z in ep["zone_windows"].items():
            area = episode_client.zone_area_code(zone_id)
            for syndrome in SYNDROME_SET:
                counts, days = _counts(area, syndrome, ep["window_days"])
                if counts is None:
                    continue
                baseline = _baseline(area, syndrome, days, counts)
                shape = expected_curve(z, _mix_for(ep), days=np.arange(len(counts)))
                r = matched_filter_test(counts, baseline, shape, episode_id=ep["episode_id"],
                                        area_code=area, syndrome=syndrome)
                _store(r)
                episode_client.post_test_result(r)       # ONLY these fields cross (GC-7)
                published.append(r)
    return {"published": len(published)}

@app.post("/scan-clusters")
def scan_clusters():
    """FR-35: an unexplained cluster asks the kernel to search upstream of the affected areas."""
    for c in detect_unexplained_clusters():
        episode_client.request_upstream_search(area_code=c.area_code, day=c.day,
                                               p_value=c.p_value)
    return {"ok": True}
```

The Core API receives `post_test_result` at `POST /clinical/test-result`, appends a
`ClinicalTestResult` event, and `request_upstream_search` at `POST /clinical/upstream-search`,
appending `UpstreamSearchRequested`. Neither endpoint accepts counts.

- [ ] **Step 5: Run tests and commit**

```bash
docker compose run --rm clinical pytest services/clinical-stats/tests/ -v
git add services/clinical-stats/ services/core-api/upstream_api/api/
git commit -m "feat(clinical): NB baselines, matched-filter test, cluster scan, result-only boundary"
```

## Phase 8 exit criteria

- Boundary tests pass: no environmental credential, no patient columns, only six fields leave.
- Small counts are rejected by the schema, not just by code.
- The matched filter detects a shape-matching excess (p < 0.01) and ignores a mis-timed one (p > 0.10); p-values are uniform under the null.
- The G5 test shows shorter detection delay than a blind cluster scan.
- `ClinicalTestResult` events appear in the environmental log with no counts in them.

## 🔑 Credentials needed at the end of Phase 8

**None.** In a pilot you would need a data-sharing agreement with a public-health authority
for the aggregate feed (PRD open question 4), but the MVP uses simulator-generated counts.

---

# Phase 9 — Simulator, ground truth, benchmarks and CI gates

**Day 5, morning (≈5 h).** Never cut this: "evaluated, not just demonstrated" is the
difference between this project and the competition (PRD §3.4, §15).

**PRD coverage:** §15 in full, FR-42…FR-45, G1, G2, G3, G5, GC-10, GC-11.

## File structure

```
services/simulator/upstream_sim/
├── scenario.py      # sample a scenario: source, start, duration, contaminant, weather
├── transport_truth.py # ground-truth plume, independent of the kernel's tables
├── citizens.py      # citizen observation generator (biased to paths and parks)
├── sensors.py       # sensor noise, dropouts
├── clinical.py      # synthetic syndrome counts with injected shaped excess
├── run.py           # write sim events to the log + truth to sim_truth
└── demo_scenario.py # the exact scripted incident for the demo video
services/bench/benchmarks/
├── metrics.py       # top-k accuracy, samples-to-localise, coverage, ECE, delay
├── baselines.py     # nearest-upstream, nearest-site, random, fixed-schedule, heuristic
├── runner.py        # run N scenarios, write results.parquet
└── charts.py        # the four charts used in the demo and the README
```

---

### Task 9.1: Simulator with hidden ground truth

**Files:**
- Create: the six `upstream_sim` modules.
- Test: `services/simulator/tests/test_simulator.py`

**Interfaces:**
- Produces:
  ```python
  @dataclass(frozen=True)
  class Scenario:
      scenario_id: str; entry_node: str; start: datetime; duration_s: int
      mass: float; contaminant: str; flow_condition: str; rainfall_mm_h: float
      seed: int

  def sample_scenario(net, rng) -> Scenario
  def run_scenario(net, tables, scenario, *, n_citizens: int, n_sensors: int,
                   store, truth_writer) -> dict
  ```
  `truth_writer` writes to `sim_truth.injected_events` using a DSN that the kernel role
  cannot use (GC-10).

- [ ] **Step 1: Write the failing tests**

```python
# services/simulator/tests/test_simulator.py — key assertions
def test_ground_truth_is_written_to_the_isolated_schema(run):
    assert truth_row(run["run_id"])["true_entry_node"] == run["scenario"].entry_node

def test_kernel_cannot_read_ground_truth(kernel_conn):
    """GC-10, tested from the kernel's own credential."""
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        kernel_conn.execute("SELECT * FROM sim_truth.injected_events")

def test_sim_events_use_the_sim_stream_and_never_the_live_one(run):
    assert all(e.stream == "sim" for e in events_for(run["run_id"]))

def test_citizen_reports_are_biased_towards_paths_and_parks(run):
    near_zone = fraction_of_reports_within_150m_of_a_zone(run)
    assert near_zone > 0.5

def test_simulator_generates_negative_reports_too(run):
    assert any(e.payload["result"] == "negative" for e in evidence_events(run))

def test_detection_follows_the_configured_detection_curve(many_runs):
    """A report far downstream should be positive less often than one near the source."""
    assert positive_rate_near_source(many_runs) > positive_rate_far_downstream(many_runs)

def test_some_lab_results_arrive_days_late(run_with_labs):
    assert any((e.recorded_at - e.event_time).days >= 1 for e in lab_events(run_with_labs))

def test_clinical_counts_carry_an_excess_shaped_by_incubation(run):
    counts = clinical_counts(run)
    assert np.argmax(counts - baseline_counts) >= 2

def test_same_seed_reproduces_the_same_event_sequence():
    a = run_scenario(..., scenario=sample_scenario(net, np.random.default_rng(7)))
    b = run_scenario(..., scenario=sample_scenario(net, np.random.default_rng(7)))
    assert [e.payload for e in a["events"]] == [e.payload for e in b["events"]]
```

- [ ] **Step 2: Implement the simulator**

```python
# services/simulator/upstream_sim/scenario.py
"""PRD 15.1: inject events on the REAL network with realistic noise.

The simulator's transport model is deliberately written separately from the kernel's
(`transport_truth.py`), with its own velocity draw per scenario. If both used the same code
the evaluation would only prove the kernel agrees with itself.
"""
from __future__ import annotations
import datetime as dt, uuid
from dataclasses import dataclass
import numpy as np

CONTAMINANTS = ("sewage", "industrial", "runoff")
WEATHER = (("dry", 0.0), ("wet", 3.0), ("storm", 25.0))

@dataclass(frozen=True)
class Scenario:
    scenario_id: str; entry_node: str; start: dt.datetime; duration_s: int
    mass: float; contaminant: str; flow_condition: str; rainfall_mm_h: float; seed: int

def sample_scenario(net, rng: np.random.Generator) -> Scenario:
    cond, mm = WEATHER[rng.choice(len(WEATHER), p=[0.5, 0.3, 0.2])]
    # Weight entry points by their base rate under this weather, as reality would.
    w = net.entry_base_rate * np.array(
        [12.0 if (t == "cso" and cond == "storm") else
         0.05 if (t == "cso" and cond == "dry") else 1.0
         for t in net.entry_source_type])
    k = int(rng.choice(len(net.entry_nodes), p=w / w.sum()))
    start = dt.datetime.now(dt.UTC) - dt.timedelta(hours=float(rng.uniform(1, 12)))
    return Scenario(scenario_id=uuid.uuid4().hex[:8], entry_node=net.entry_nodes[k],
                    start=start.replace(second=0, microsecond=0),
                    duration_s=int(rng.choice([900, 3600, 10800])),
                    mass=float(rng.lognormal(0.0, 0.5)),
                    contaminant=str(rng.choice(CONTAMINANTS)),
                    flow_condition=cond, rainfall_mm_h=mm,
                    seed=int(rng.integers(0, 2**31)))
```

```python
# services/simulator/upstream_sim/citizens.py
"""Citizen observations: sparse, irregular, noisy, and biased to where people walk."""
def generate_citizen_reports(net, truth_conc, scenario, rng, *, n: int):
    weights = _proximity_to_paths_and_parks(net)        # PRD 15.1 bias
    reports = []
    for _ in range(n):
        node = int(rng.choice(len(net.node_ids), p=weights))
        t = scenario.start + dt.timedelta(seconds=float(rng.uniform(0, 6 * 3600)))
        c = truth_conc(node, t.timestamp())
        curve = DETECTION["citizen_visual_olfactory"]
        p_pos = curve.false_positive + (1 - curve.false_positive) * _logistic(c, curve)
        positive = bool(rng.random() < p_pos)
        reports.append({"node_id": net.node_ids[node], "observed_at": t,
                        "result": "positive" if positive else "negative",
                        "method": "citizen_visual_olfactory",
                        "observer_id": f"sim-vol-{rng.integers(1, 200)}",
                        "observer_type": "citizen", "snap_distance_m": float(rng.uniform(0, 30)),
                        "confirmed_by_observer": True})
    return reports
```

- [ ] **Step 3: Run tests and commit**

```bash
docker compose run --rm api pytest services/simulator/tests/ -v
git add services/simulator/
git commit -m "feat(sim): scenario sampler, independent truth transport, biased citizen and sensor generators"
```

---

### Task 9.2: Metrics, baselines and the benchmark runner

**Files:**
- Create: `services/bench/benchmarks/{metrics.py,baselines.py,runner.py,charts.py}`
- Test: `services/bench/tests/test_metrics.py`

**Interfaces:**
- Produces:
  ```python
  def top_k_accuracy(results, k: int) -> float
  def samples_to_localise(result, *, confidence: float = 0.8) -> int | None
  def window_coverage(results) -> float                 # G2: should land in 0.75-0.85
  def calibration_error(results, bins: int = 10) -> float
  def detection_delay(results) -> float
  def false_episode_rate(results, catchment_months: float) -> float
  def evidence_to_posterior_latency(results) -> dict     # p50 / p95

  # Baselines (PRD 15.2)
  def nearest_upstream_baseline(evidence, net) -> str
  def nearest_site_sampler(...) / random_sampler(...) /
      fixed_schedule_sampler(...) / heuristic_weight_sampler(...)
  ```

- [ ] **Step 1: Write the failing metric tests**

```python
# services/bench/tests/test_metrics.py — key assertions
def test_top_k_accuracy_counts_a_hit_when_truth_is_in_the_top_k():
    assert top_k_accuracy([r(truth="O14", ranked=["O9","O14","O3"])], k=3) == 1.0
    assert top_k_accuracy([r(truth="O14", ranked=["O9","O3","O7"])], k=3) == 0.0

def test_samples_to_localise_returns_none_when_never_localised():
    assert samples_to_localise(r(confidence_curve=[0.2,0.3,0.4])) is None

def test_window_coverage_is_the_fraction_of_true_arrivals_inside_the_window():
    assert window_coverage([inside, inside, outside, inside]) == pytest.approx(0.75)

def test_calibration_error_is_zero_for_a_perfectly_calibrated_set():
    assert calibration_error(perfectly_calibrated_results) < 0.01

def test_nearest_upstream_baseline_picks_the_nearest_entry_above_the_report():
    assert nearest_upstream_baseline([report_at("R3")], net) in ("O14", "O9")

def test_latency_reports_p50_and_p95():
    assert set(evidence_to_posterior_latency(results)) == {"p50", "p95"}
```

- [ ] **Step 2: Implement the runner and the gates**

```python
# services/bench/benchmarks/runner.py
"""PRD 15.3: evaluation as CI. Run N scenarios, compare against baselines, gate on targets."""
import argparse, json
import numpy as np, pyarrow as pa, pyarrow.parquet as pq

TARGETS = {                                   # PRD 15.2, tuned after the first runs
    "top3_accuracy_after_5_obs": 0.80,        # G1
    "window_coverage_lo": 0.75, "window_coverage_hi": 0.85,   # G2, GC-11
    "sample_reduction_vs_best_baseline": 0.30,                # G3
    "calibration_error_max": 0.05,
    "latency_p95_s": 5.0,                                     # NFR-1
}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenarios", type=int, default=200)
    ap.add_argument("--seed", type=int, default=20260922)
    ap.add_argument("--out", default="bench/results")
    ap.add_argument("--gate", action="store_true", help="exit 1 if a target regresses")
    a = ap.parse_args()

    rows = [run_one(i, seed=a.seed + i) for i in range(a.scenarios)]
    pq.write_table(pa.Table.from_pylist(rows), f"{a.out}/results.parquet")
    summary = summarise(rows)
    json.dump(summary, open(f"{a.out}/summary.json", "w"), indent=2)
    print(json.dumps(summary, indent=2))

    if a.gate:
        fails = check_targets(summary, TARGETS)
        if fails:
            print("BENCHMARK GATE FAILED:"); [print(" -", f) for f in fails]
            raise SystemExit(1)
```

```yaml
# append to .github/workflows/ci.yml
  bench:
    runs-on: ubuntu-latest
    needs: python
    services: { db: { image: timescale/timescaledb-ha:pg17, ... } }
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync --all-packages
      - run: uv run alembic -c db/alembic.ini upgrade head
      - run: uv run python -m upstream_kernel.compile.cli --boundary tests/fixtures/small.geojson
      - run: uv run python -m upstream_kernel.physics.cli
      - run: uv run python -m benchmarks.runner --scenarios 40 --gate   # FR-45
      - uses: actions/upload-artifact@v4
        with: { name: bench, path: bench/results }
```

- [ ] **Step 3: Produce the four charts**

```python
# services/bench/benchmarks/charts.py
"""The four charts for the README and the demo video (scene 4:10-4:40)."""
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt, numpy as np

PALETTE = ["#0072B2", "#E69F00", "#009E73", "#CC79A7", "#56B4E9"]   # colour-blind safe

def chart_accuracy_vs_observations(results, out):
    """G1: top-1 and top-3 accuracy against the nearest-upstream baseline."""
    ns = sorted({r["n_obs"] for r in results})
    fig, ax = plt.subplots(figsize=(7, 4))
    for i, (label, key) in enumerate([("Upstream top-1", "top1"), ("Upstream top-3", "top3"),
                                      ("Nearest-upstream baseline", "baseline_top1")]):
        ax.plot(ns, [np.mean([r[key] for r in results if r["n_obs"] == n]) for n in ns],
                marker="o", color=PALETTE[i], label=label)
    ax.axhline(0.80, ls="--", c="grey"); ax.text(ns[0], 0.81, "target 80%", color="grey")
    ax.set_xlabel("Observations available"); ax.set_ylabel("Source correctly ranked")
    ax.set_ylim(0, 1); ax.legend(); fig.tight_layout(); fig.savefig(f"{out}/accuracy.png", dpi=160)

def chart_samples_to_localise(results, out):
    """G3: samples needed, Upstream vs the four baselines (box plot)."""
    groups = ["upstream", "nearest_site", "random", "fixed_schedule", "heuristic"]
    data = [[r[f"samples_{g}"] for r in results if r.get(f"samples_{g}")] for g in groups]
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.boxplot(data, labels=["Upstream\n(EC²)", "Nearest\nsite", "Random",
                             "Fixed\nschedule", "Heuristic\nweights"])
    ax.set_ylabel("Samples to localise the source"); fig.tight_layout()
    fig.savefig(f"{out}/samples.png", dpi=160)

def chart_window_calibration(results, out):
    """G2/GC-11: does an 80% window contain the truth about 80% of the time?"""
    cov = np.mean([r["true_arrival_in_window"] for r in results])
    fig, ax = plt.subplots(figsize=(5, 4))
    ax.axhspan(0.75, 0.85, color=PALETTE[2], alpha=0.2, label="target band 75–85%")
    ax.bar(["80% exposure window"], [cov], color=PALETTE[0])
    ax.set_ylim(0, 1); ax.set_ylabel("Fraction containing the true arrival")
    ax.legend(); fig.tight_layout(); fig.savefig(f"{out}/window_calibration.png", dpi=160)

def chart_reliability_diagram(results, out):
    """Probability calibration with the expected calibration error printed on the chart."""
    p = np.array([r["stated_probability"] for r in results])
    y = np.array([r["was_correct"] for r in results], dtype=float)
    bins = np.linspace(0, 1, 11); idx = np.clip(np.digitize(p, bins) - 1, 0, 9)
    obs = [y[idx == b].mean() if (idx == b).any() else np.nan for b in range(10)]
    ece = np.nansum([abs(obs[b] - (bins[b] + 0.05)) * (idx == b).mean() for b in range(10)])
    fig, ax = plt.subplots(figsize=(5, 5))
    ax.plot([0, 1], [0, 1], ls="--", c="grey")
    ax.plot(bins[:-1] + 0.05, obs, marker="o", color=PALETTE[0])
    ax.set_xlabel("Stated probability"); ax.set_ylabel("Observed frequency")
    ax.set_title(f"Calibration error {ece:.3f} (target ≤ 0.05)")
    fig.tight_layout(); fig.savefig(f"{out}/reliability.png", dpi=160)

def chart_detection_delay(results, out):
    """G5: matched filter vs a blind space-time cluster scan, at equal false-alarm rate."""
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.hist([[r["delay_matched"] for r in results], [r["delay_blind"] for r in results]],
            bins=12, color=PALETTE[:2], label=["Matched filter", "Blind cluster scan"])
    ax.set_xlabel("Days from exposure to detection"); ax.set_ylabel("Scenarios")
    ax.legend(); fig.tight_layout(); fig.savefig(f"{out}/detection_delay.png", dpi=160)
```

Use a colour-blind-safe categorical palette, label axes in plain language, and put the
target band directly on the calibration chart so a judge sees pass/fail without reading text.

- [ ] **Step 4: Run the full benchmark and record the numbers**

```bash
make bench
cat bench/results/summary.json
```

Then **update PRD §15.2's "initial target" column** with the measured values — the PRD says
targets "will be adjusted after the first simulation runs", and honest numbers beat
aspirational ones in front of judges.

- [ ] **Step 5: Commit**

```bash
git add services/bench/ bench/results/summary.json .github/workflows/ci.yml
git commit -m "feat(bench): metrics, five baselines, CI gate, evaluation charts"
```

## Phase 9 exit criteria

- 200-scenario run completes; `summary.json` reports every metric in PRD §15.2.
- **G1** top-3 accuracy after 5 observations, **G2** window coverage in 75–85%, **G3** ≥30% fewer samples than the best baseline, **G5** shorter detection delay, calibration error ≤ 0.05, latency p95 < 5 s — each either met or *honestly reported as not met* with a note.
- `--gate` fails CI on a calibration regression (FR-45).
- Five charts rendered into `bench/results/`.
- The kernel provably cannot read `sim_truth` (tested with the kernel's own credential).

## 🔑 Credentials needed at the end of Phase 9

**None.**

---

# Phase 10 — Console, belief replay and the mission PWA

**Day 5, afternoon (≈6 h).** The judging criterion "UX" lives here, and so do two of the
three headline demo scenes.

**PRD coverage:** FR-36…FR-41, §16 (demo scenes), NFR-9 (offline), NFR-10 (WCAG 2.1 AA), G7.

> **Before writing any component, invoke the `ui-ux-pro-max` skill** for the Next.js +
> Tailwind guidance, colour palette and accessibility checks. This plan specifies *what* each
> screen must show and prove; the skill specifies *how* it should look.

## File structure

```
web/
├── app/
│   ├── layout.tsx
│   ├── page.tsx                  # operator console (FR-36)
│   ├── replay/page.tsx           # belief replay (FR-37) — can also be a console drawer
│   ├── missions/
│   │   ├── page.tsx              # volunteer mission list (FR-38)
│   │   └── [id]/page.tsx         # single mission: accept, submit, see effect
│   ├── public-health/page.tsx    # FR-39
│   └── api/                      # nothing: the Next app holds no business logic
├── components/
│   ├── NetworkMap.tsx            # MapLibre + deck.gl; PMTiles basemap
│   ├── SourceRanking.tsx         # TRACE bars with probabilities
│   ├── ExposureTimeline.tsx      # PULSE windows with credible bands
│   ├── EvidenceList.tsx          # positive/negative/retracted, with the computed explanation
│   ├── BeliefSlider.tsx          # the time slider (FR-37)
│   ├── EpisodeStateBadge.tsx
│   ├── MissionCard.tsx
│   └── SyntheticBadge.tsx        # PRD R2: label synthetic outfalls
├── lib/
│   ├── api.ts                    # typed client generated from the FastAPI OpenAPI schema
│   ├── types.ts                  # generated from Pydantic JSON Schema
│   └── offline.ts                # IndexedDB queue + background sync (NFR-9)
├── public/
│   ├── manifest.webmanifest
│   ├── sw.js                     # service worker: cache shell, queue submissions
│   └── basemap.pmtiles           # self-hosted; no tile-server key needed
```

---

### Task 10.1: Typed API client and the network map

**Files:**
- Create: `web/lib/{api.ts,types.ts}`, `web/components/{NetworkMap.tsx,SyntheticBadge.tsx}`
- Test: `web/__tests__/network-map.test.tsx` (Vitest + Testing Library)

**Interfaces:**
- Produces:
  ```ts
  export type Snapshot = { ts: string; fingerprint: string; p_event: number;
    source_marginals: Record<string, number>;
    zone_windows: Record<string, ZoneExposure>;
    probe_candidates: ProbeCandidate[]; explanation: Explanation; };
  export async function getReplay(at: Date): Promise<Snapshot>
  export async function getTimeline(): Promise<TimelinePoint[]>
  export async function getEpisodes(): Promise<Episode[]>
  export async function getNetwork(): Promise<NetworkGeoJSON>
  ```

- [ ] **Step 1: Generate types from the backend, so drift is impossible**

```bash
cd web
npx openapi-typescript http://localhost:8000/openapi.json -o lib/types.ts
```

Add this to `make test` so a backend schema change breaks the frontend build, not production.

- [ ] **Step 2: Write the failing component tests**

```tsx
// web/__tests__/network-map.test.tsx — key assertions
it("renders every outfall with a probability label", () => { ... })
it("marks synthetic outfalls with a visible badge", () => {
  render(<NetworkMap network={netWithSynthetic} snapshot={snap} />)
  expect(screen.getByLabelText(/synthetic \(illustrative\) outfall/i)).toBeInTheDocument()
})
it("shows sparse areas as uncertain, not clean", () => {
  // PRD 14.4 equity safeguard
  expect(screen.getByTestId("zone-no-data")).toHaveTextContent(/not enough evidence/i)
})
it("colours edges by exposure probability at the selected time", () => { ... })
it("has an accessible name for every interactive map control", () => { ... })
```

- [ ] **Step 3: Implement `NetworkMap.tsx`**

```tsx
// web/components/NetworkMap.tsx
// deck.gl animates probability along network edges over time (PRD 11.1).
// The basemap is a self-hosted PMTiles file, so no tile-server API key is required.
"use client";
import { useMemo } from "react";
import DeckGL from "@deck.gl/react";
import { GeoJsonLayer, ScatterplotLayer } from "@deck.gl/layers";
import Map from "react-map-gl/maplibre";
import { Protocol } from "pmtiles";

export function NetworkMap({ network, snapshot, atTime }: Props) {
  const edgeLayer = useMemo(() => new GeoJsonLayer({
    id: "edges", data: network.edges,
    getLineColor: (f) => exposureColour(snapshot, f.properties.to_node, atTime),
    getLineWidth: 3, lineWidthMinPixels: 2, pickable: true,
  }), [network, snapshot, atTime]);

  const outfallLayer = useMemo(() => new ScatterplotLayer({
    id: "outfalls", data: network.outfalls.features,
    getPosition: (f) => f.geometry.coordinates,
    getRadius: (f) => 6 + 24 * (snapshot.source_marginals[f.properties.outfall_id] ?? 0),
    getFillColor: (f) => f.properties.is_synthetic ? SYNTHETIC_COLOUR : SOURCE_COLOUR,
    pickable: true,
  }), [network, snapshot]);

  return (
    <DeckGL layers={[edgeLayer, outfallLayer]} initialViewState={viewState} controller
            getTooltip={({ object }) => object && sourceTooltip(object, snapshot)}>
      <Map mapStyle="/basemap-style.json" />
    </DeckGL>
  );
}
```

> **Equity safeguard (PRD §14.4):** a zone with no nearby evidence must render in the
> "insufficient evidence" style with the label *"Not enough evidence here"* — **never** in the
> same style as a zone the model believes is clean. This is a one-line rule with a real
> ethical weight; the test above enforces it.

- [ ] **Step 4: Run tests and commit**

```bash
cd web && npm test
git add web/ && git commit -m "feat(web): typed API client, deck.gl network map with synthetic labelling"
```

---

### Task 10.2: The operator console (FR-36) and belief replay (FR-37)

Belief replay is the demo's best 40 seconds (PRD §16, 2:10–2:50). It must be fluid.

**Files:**
- Create: `web/app/page.tsx`, `web/components/{SourceRanking.tsx,ExposureTimeline.tsx,EvidenceList.tsx,BeliefSlider.tsx,EpisodeStateBadge.tsx}`
- Test: `web/__tests__/belief-replay.test.tsx`

- [ ] **Step 1: Write the failing tests**

```tsx
// web/__tests__/belief-replay.test.tsx — key assertions
it("shows the belief as of the slider position, not the latest", async () => {
  render(<Console timeline={twoSnapshots} />)
  fireEvent.change(screen.getByRole("slider"), { target: { value: "0" } })
  expect(await screen.findByText(/62%/)).toBeInTheDocument()   // the earlier p_event
})
it("labels the slider for screen readers with the timestamp it is showing", () => {
  expect(screen.getByRole("slider")).toHaveAccessibleName(/showing belief at/i)
})
it("explains each top candidate with the observations that supported it", () => {
  expect(screen.getByText(/supported by/i)).toBeInTheDocument()
  expect(screen.getByText(/eliminated rivals/i)).toBeInTheDocument()
})
it("shows negative evidence distinctly from positive evidence", () => {
  expect(screen.getByTestId("evidence-negative")).toHaveAccessibleDescription(/checked.*normal/i)
})
it("shows retracted evidence struck through, never hidden", () => {
  expect(screen.getByTestId("evidence-retracted")).toHaveClass("line-through")
})
it("displays the fingerprint so a judge can verify reproducibility", () => {
  expect(screen.getByText(/sha256:/)).toBeInTheDocument()
})
it("meets contrast requirements in both themes", async () => {
  expect(await axe(container)).toHaveNoViolations()   // NFR-10 / GC-14
})
```

- [ ] **Step 2: Implement the console layout**

The console is one screen, three regions:

| Region | Contents | Requirement |
|---|---|---|
| Left rail | Episode list with `EpisodeStateBadge`, p_event, opened-at | FR-36 |
| Centre | `NetworkMap` with animated exposure + `BeliefSlider` underneath | FR-36, FR-37 |
| Right rail | `SourceRanking` (TRACE) → `ExposureTimeline` (PULSE) → next-best-sample (PROBE) → `EvidenceList` with the computed explanation | FR-13, FR-14, FR-15 |

`BeliefSlider` fetches `/replay/timeline` once and `/replay?at=` on change (debounced 120 ms),
and shows the fingerprint of whatever snapshot it is displaying.

- [ ] **Step 3: Run tests and commit**

```bash
cd web && npm test && npx playwright test e2e/console.spec.ts
git add web/ && git commit -m "feat(web): operator console with belief replay slider and computed explanations"
```

---

### Task 10.3: Mission PWA with offline submission (FR-38, NFR-9)

**Files:**
- Create: `web/app/missions/**`, `web/public/{manifest.webmanifest,sw.js}`, `web/lib/offline.ts`
- Test: `web/__tests__/offline-queue.test.ts`, `web/e2e/mission-offline.spec.ts`

- [ ] **Step 1: Write the failing tests**

```ts
// web/__tests__/offline-queue.test.ts — key assertions
it("queues a submission when offline and keeps the original observed_at", async () => {
  setOffline(true)
  const observedAt = new Date()
  await submitMission("M-1", { result: "negative", observedAt })
  expect((await readQueue())[0].observed_at).toBe(observedAt.toISOString())  // GC-4
})
it("flushes the queue in order when connectivity returns", async () => { ... })
it("does not double-submit after a retry", async () => { ... })
it("shows the mission's expected effect before the volunteer accepts", () => {
  expect(screen.getByText(/expected to rule out/i)).toBeInTheDocument()
})
it("shows the measured effect after completion", () => {
  // G7: "your sample eliminated two of three suspects"
  expect(screen.getByText(/your check ruled out/i)).toBeInTheDocument()
})
it("refuses to show a mission whose safety window has closed", () => { ... })
```

- [ ] **Step 2: Implement the offline queue**

```ts
// web/lib/offline.ts
// NFR-9: the mission app works without signal and syncs later with correct event times.
// The observation's `observed_at` is stamped on the DEVICE at observation time and never
// rewritten on sync — the server supplies `recorded_at` (GC-4).
const DB = "upstream-outbox";

export async function submitMission(missionId: string, body: MissionSubmission) {
  const record = { ...body, mission_id: missionId, observed_at: body.observedAt.toISOString(),
                   idempotency_key: crypto.randomUUID() };
  if (!navigator.onLine) { await enqueue(record); await registerSync(); return { queued: true }; }
  try { return await postSubmission(record); }
  catch { await enqueue(record); await registerSync(); return { queued: true }; }
}
```

The service worker registers a `sync` event that drains the outbox in insertion order and
sends the `idempotency_key` so a retry cannot double-submit.

- [ ] **Step 3: Verify offline end to end**

```bash
npx playwright test e2e/mission-offline.spec.ts   # uses context.setOffline(true)
```

- [ ] **Step 4: Public-health view (FR-39)**

One page listing active episodes, their per-zone 80% windows, exposure pathways, and any
`ClinicalTestResult`. Every page carries the standing line *"Environmental context, not a
diagnosis. Advisory decisions are made by public health officers."* (GC-12).

- [ ] **Step 5: Accessibility pass and commit**

```bash
npx playwright test e2e/a11y.spec.ts   # axe-core on every route, WCAG 2.1 AA
git add web/ && git commit -m "feat(web): offline mission PWA, public-health view, a11y pass"
```

## Phase 10 exit criteria

- Console renders the real catchment with animated exposure; the belief slider reproduces past beliefs and shows their fingerprints.
- Negative and retracted evidence are visually distinct and never hidden.
- Synthetic outfalls carry a visible badge (PRD R2); zones with no evidence read "not enough evidence", never "clean" (PRD §14.4).
- Mission submitted in airplane mode arrives after reconnect with the original `observed_at` and no duplicate.
- axe reports zero violations on all routes (GC-14).

## 🔑 Credentials needed at the end of Phase 10

| Variable | What it is | Where to get it |
|---|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | Where the browser reaches the Core API | **You choose** (`http://localhost:8000` locally, your domain in production) |
| `NEXT_PUBLIC_VAPID_PUBLIC_KEY` | Same value as `VAPID_PUBLIC_KEY` from Phase 6 | Already generated |
| `NEXT_PUBLIC_MAPTILER_KEY` | **Optional.** Only if you use MapTiler tiles instead of the self-hosted PMTiles basemap. | maptiler.com free tier. **Recommended: leave empty** and build `basemap.pmtiles` from OSM with `pmtiles extract` — no key, no rate limit, works offline (which the mission PWA needs anyway). |

---

# Phase 11 — Pooling, exports, security hardening

**Day 6, morning (≈3 h).** The ecosystem leg of One Health, plus the things a judge checks.

**PRD coverage:** §7.7 (multi-episode pooling, recurring sources, bioassessment), FR-19, FR-24, FR-41, §14.2, §14.3, NFR-4, NFR-12.

---

### Task 11.1: Multi-episode pooling and the recurring-source report

**Files:**
- Create: `services/kernel/upstream_kernel/pooling.py`, `services/core-api/upstream_api/api/reports.py`
- Test: `services/kernel/tests/test_pooling.py`

**Interfaces:**
- Produces:
  ```python
  @dataclass(frozen=True)
  class RecurringSource:
      entry_id: str; source_type: str
      episode_count: int; pooled_probability: float
      first_seen: datetime; last_seen: datetime
      evidence_episode_ids: list[str]
      suggested_action: str        # "inspect outfall O14 for a misconnection"

  def pool_closed_episodes(dsn, net, *, since_days: int = 365) -> list[RecurringSource]
  def updated_priors(recurring: list[RecurringSource], net) -> np.ndarray   # (K,)
  ```
  Runs nightly (DBOS scheduled workflow), writes a report, and feeds `past_episode_count`
  back into `PriorInputs` (Phase 4 already reads it).

- [ ] **Step 1: Write the failing tests**

```python
# services/kernel/tests/test_pooling.py — key assertions
def test_repeated_episodes_at_one_point_raise_its_pooled_probability():
    rs = pool_closed_episodes(dsn, net)
    assert next(r for r in rs if r.entry_id == "O14").pooled_probability > 0.5

def test_pooling_sharpens_localisation_beyond_any_single_episode():
    """PRD 7.7: a single citizen-driven episode may leave the source unclear."""
    single = max(episode_marginals("EE-1").values())
    pooled = next(r for r in pool_closed_episodes(dsn, net)
                  if r.entry_id == "O14").pooled_probability
    assert pooled > single

def test_only_closed_episodes_are_pooled():
    assert "EE-OPEN" not in {e for r in pool_closed_episodes(dsn, net)
                             for e in r.evidence_episode_ids}

def test_updated_priors_feed_back_into_the_next_posterior():
    before = posterior_without_pooling(); after = posterior_with_pooling()
    assert after.source_marginals["O14"] > before.source_marginals["O14"]

def test_report_suggests_an_inspection_not_an_accusation():
    """GC-12 / PRD 14.4: recommendations, never accusations."""
    r = pool_closed_episodes(dsn, net)[0]
    assert "inspect" in r.suggested_action.lower()
    assert not any(w in r.suggested_action.lower() for w in ("responsible", "polluter", "blame"))
```

- [ ] **Step 2: Implement and schedule nightly**

```python
# services/kernel/upstream_kernel/pooling.py
"""PRD 7.7: misconnections and overflows recur at the same place.

Pool the posterior source marginals of closed episodes. Under the assumption that episodes
are conditionally independent given the true source, the pooled log-odds is the sum of the
per-episode log-odds; a point that keeps appearing in the top of the ranking rises sharply
even when no single episode was conclusive.
"""
def pool_closed_episodes(dsn, net, *, since_days: int = 365) -> list[RecurringSource]:
    marginals = _closed_episode_marginals(dsn, since_days)      # list[dict[entry_id, p]]
    if not marginals:
        return []
    log_odds = np.zeros(len(net.entry_nodes))
    for m in marginals:
        p = np.array([max(m.get(e, 1e-6), 1e-6) for e in net.entry_nodes])
        log_odds += np.log(p / (1 - np.clip(p, 0, 1 - 1e-6)))
    pooled = 1 / (1 + np.exp(-log_odds))
    pooled = pooled / max(pooled.sum(), 1e-12)
    out = []
    for k, entry_id in enumerate(net.entry_nodes):
        if pooled[k] < 0.15:
            continue
        stype = net.entry_source_type[k]
        implicating = [m["episode_id"] for m in marginals if m.get(entry_id, 0) > 0.2]
        opened = [m["opened_at"] for m in marginals if m["episode_id"] in implicating]
        out.append(RecurringSource(
            entry_id=entry_id, source_type=stype,
            episode_count=len(implicating),
            pooled_probability=float(pooled[k]),
            first_seen=min(opened), last_seen=max(opened),
            evidence_episode_ids=implicating,
            suggested_action=(f"Inspect {entry_id} ({stype.replace('_',' ')}) for a recurring "
                              f"source; consider it as a restoration measure.")))
    return sorted(out, key=lambda r: -r.pooled_probability)
```

`_closed_episode_marginals` returns one dict per closed episode, carrying `episode_id`,
`opened_at` and each entry point's marginal probability:

```python
def _closed_episode_marginals(dsn, since_days: int) -> list[dict]:
    with psycopg.connect(dsn) as c, c.cursor() as cur:
        cur.execute("""
            SELECT e.episode_id, e.opened_at, s.source_marginals
            FROM episodes e
            JOIN LATERAL (SELECT source_marginals FROM posterior_snapshots p
                          WHERE p.fingerprint = e.latest_fingerprint LIMIT 1) s ON TRUE
            WHERE e.state IN ('CONFIRMED','RESOLVED','REFUTED')
              AND e.opened_at > now() - (%s || ' days')::interval""", (since_days,))
        return [{"episode_id": r[0], "opened_at": r[1], **r[2]} for r in cur.fetchall()]
```

Expose it at `GET /reports/recurring-sources` for the environmental agency view and the OAH
Decision Support System, and schedule it with DBOS at 02:00 daily.

- [ ] **Step 3: Run tests and commit**

```bash
docker compose run --rm kernel pytest services/kernel/tests/test_pooling.py -v
git add services/kernel/upstream_kernel/pooling.py services/core-api/upstream_api/api/reports.py
git commit -m "feat(kernel): nightly multi-episode pooling and recurring-source report"
```

---

### Task 11.2: Research exports and security hardening

**Files:**
- Create: `services/core-api/upstream_api/api/exports.py`, `services/core-api/upstream_api/security.py`
- Create: `docs/SECURITY.md`, `docs/PRIVACY.md`
- Test: `services/core-api/tests/test_exports.py`, `services/core-api/tests/test_security.py`

- [ ] **Step 1: Write the failing tests**

```python
# services/core-api/tests/test_exports.py
def test_export_writes_parquet_readable_by_duckdb(tmp_path):
    """FR-41."""
    p = export_episodes(tmp_path); import duckdb
    assert duckdb.sql(f"SELECT count(*) FROM '{p}'").fetchone()[0] > 0

def test_export_contains_no_observer_identifiers():
    """PRD 14.2: research exports are pseudonymised."""
    assert "observer_id" not in duckdb_columns(export_evidence(tmp_path))
    assert "observer_hash" in duckdb_columns(export_evidence(tmp_path))

def test_export_includes_the_fingerprint_for_reproducibility():
    assert "fingerprint" in duckdb_columns(export_episodes(tmp_path))

# services/core-api/tests/test_security.py
def test_officer_endpoints_reject_an_unauthenticated_caller():
    assert client.post("/episodes/EE-1/signoff", json={...}).status_code == 401

def test_citizen_role_cannot_sign_off_an_episode():
    assert client.post("/episodes/EE-1/signoff", headers=citizen_token,
                       json={...}).status_code == 403

def test_enforce_mode_probe_requires_an_agency_role():
    """PRD open question 7 — decided here: enforce mode is agency-only by default."""
    assert client.get("/episodes/EE-1/probe?mode=enforce",
                      headers=citizen_token).status_code == 403

def test_photos_are_screened_before_public_display():
    """PRD 14.2."""
    assert upload_photo(with_face).response["public_display"] is False

def test_no_endpoint_returns_patient_level_data():
    for route in all_routes():
        assert "patient" not in json.dumps(openapi_schema(route)).lower() or \
               route.startswith("/cds-services")
```

- [ ] **Step 2: Implement**

Roles (PRD §14.3): `citizen`, `officer`, `agency`, `public_health`, `clinician`, `admin`.
For the MVP use signed JWTs with a static key set (`security.py`), and document the Keycloak
swap in `docs/SECURITY.md` — the PRD explicitly defers Keycloak to Phase 1 (§17 cut list).

**Decision recorded (PRD open question 7):** *enforce* mode is **not** enabled by default;
it requires the `agency` role. Rationale: an enforce-mode recommendation names a specific
outfall to inspect, and PRD §14.4 requires enforcement to run through officer confirmation.

- [ ] **Step 3: Write the privacy and security docs**

`docs/PRIVACY.md` must state, in plain language: what a volunteer shares (coarse area, not
live location), what a photo is checked for before public display, what crosses the health
boundary in each direction, the GDPR Article 9 basis for the separation, and how to request
deletion of a volunteer profile (the *profile*, not the append-only events — explain that
distinction honestly).

- [ ] **Step 4: Run tests and commit**

```bash
docker compose run --rm api pytest services/core-api/tests/test_exports.py services/core-api/tests/test_security.py -v
git add services/core-api/ docs/
git commit -m "feat(api): parquet exports, role-based access, privacy and security documentation"
```

## Phase 11 exit criteria

- Nightly pooling produces a recurring-source report whose language recommends inspection and never attributes blame.
- Pooled priors measurably sharpen the next episode's posterior.
- Parquet export readable by DuckDB, with observers pseudonymised and fingerprints retained.
- Officer/agency endpoints reject citizens; enforce mode is agency-only.
- `docs/PRIVACY.md` and `docs/SECURITY.md` exist and are accurate.

## 🔑 Credentials needed at the end of Phase 11

| Variable | What it is | Where to get it |
|---|---|---|
| `JWT_SIGNING_KEY` | Symmetric key for MVP auth tokens | **You choose it** (`openssl rand -hex 32`) |
| `MEDIA_S3_*` | Already set in Phase 3 | — |

*Keycloak/OIDC credentials are **not** needed for the MVP — PRD §17 defers them to Phase 1.*

---

# Phase 12 — Demo, documentation and submission

**Day 6, afternoon (≈4 h) + buffer days.** The hackathon is judged on what is *seen*.

**PRD coverage:** §16 (demo plan scene by scene), §3.1 (submission requirements), §3.3 (judging criteria), R9, R10.

---

### Task 12.1: The scripted demo scenario

**Files:**
- Create: `services/simulator/upstream_sim/demo_scenario.py`
- Create: `docs/DEMO_SCRIPT.md`

**Interfaces:**
- Produces: `python -m upstream_sim.demo_scenario --speed 60` — replays the PRD §10.5
  walkthrough (02:10 rainfall → 02:40 sign-off → day 3 clinical signal → week 4 bioassessment)
  at 60× so the whole loop plays in under four minutes of wall-clock.

- [ ] **Step 1: Encode the PRD §10.5 walkthrough exactly**

```python
# services/simulator/upstream_sim/demo_scenario.py
"""The scripted incident from PRD 10.5, replayed at a chosen speed for the demo video.

Every beat below maps to a row of that table, so what the judges see is what the PRD promised.
"""
BEATS = [
  (0,    "rainfall",  {"mm_per_h": 68.0}),                       # 02:10
  (240,  "sensor",    {"sensor_id": "N14", "parameter": "turbidity", "value": 180.0}),  # 02:14
  (360,  "overflow",  {"outfall_id": "O14", "active": True}),    # 02:16
  (420,  "citizen",   {"node": "O14", "text": "strong sewage smell near outfall 14"}),  # 02:17
  (660,  "expect",    {"episode_state": "SUSPECTED"}),           # 02:17 + kernel
  (720,  "expect",    {"trace_top": "O14", "min_probability": 0.5}),                    # 02:19
  (780,  "expect",    {"pulse_zones": ["ZONE_A", "ZONE_B"]}),    # 02:21
  (840,  "expect",    {"probe_node_within_minutes": 17}),        # 02:22
  (1260, "citizen",   {"node": "J9", "text": "had a look, water looks completely normal"}),  # 02:31
  (1270, "expect",    {"episode_state": "PROBABLE", "fhir_published": True}),
  (1800, "field",     {"node": "O14", "result": "positive"}),    # 02:40
  (1810, "signoff",   {"officer_id": "off-1"}),                  # -> CONFIRMED
  (3*86400, "clinical", {"zone": "ZONE_B", "excess": True}),     # day 3
  (16*86400, "expect", {"episode_state": "RESOLVED"}),           # day 16
  (28*86400, "expect", {"bioassessment_mission": True}),         # week 4
]
```

Each `expect` beat **asserts** rather than narrates: if the system does not do what the PRD
says, the demo script fails loudly in rehearsal rather than quietly on camera.

- [ ] **Step 2: Rehearse**

```bash
make demo   # docker compose up + reset + demo_scenario --speed 60
```

Expected: every `expect` beat passes; total runtime under four minutes.

- [ ] **Step 3: Write `docs/DEMO_SCRIPT.md`** mapping each PRD §16 scene to exactly what to
show, what to say, and which assertion proves it:

| Time | Scene | On screen | Proves |
|---|---|---|---|
| 0:00–0:30 | The three clocks; Milwaukee | PRD §2.1 diagram animated | Why this matters |
| 0:30–1:00 | Rain, one smell report | Map shows a diffuse haze of probability | Honest uncertainty |
| 1:00–1:40 | PROBE mission → "looks normal" | Half the network goes dark | Negative evidence + EC² |
| 1:40–2:10 | Second observation localises | Source corridor + credible bands | TRACE + PULSE |
| 2:10–2:50 | Belief replay slider | Fingerprints change with the slider | Reproducibility + audit |
| 2:50–3:30 | Validator output + CDS sandbox card | `validator errors: 0`; the card | **Track 7 core** |
| 3:30–4:10 | Clinical matched-filter result | Only `p = 0.003` crosses the boundary | One Health loop + privacy |
| 4:10–4:40 | Benchmark charts | Samples-to-localise vs baselines; calibration | Evaluated, not demonstrated |
| 4:40–5:00 | Recurring-source report + bioassessment | The ecosystem leg | Scale + One Health triangle |

- [ ] **Step 4: Record and edit to 3–5 minutes**

Record at 1920×1080, 30 fps. Put the **validator "0 errors" frame and the CDS card on screen
for at least six seconds** — an HL7 Fellow is on the judging panel and that is the frame they
are looking for.

---

### Task 12.2: Repository, README and submission materials

**Files:**
- Create: `README.md`, `docs/ARCHITECTURE.md`, `docs/ASSUMPTIONS.md`, `docs/TRACK7_ALIGNMENT.md`, `LICENSE`, `CITATION.cff`

- [ ] **Step 1: Write the README so a judge can run it in five minutes**

Required sections, in this order:
1. One-sentence pitch (PRD §1, verbatim).
2. A single animated GIF of the belief replay slider.
3. **Quickstart**: `cp .env.example .env` → fill four values → `make up && make migrate && make compile && make tables && make demo`.
4. What is real and what is simulated — link `docs/ASSUMPTIONS.md`.
5. **Standards conformance**: validator output badge, profile list, CDS Hooks discovery URL.
6. Benchmark results table + the five charts.
7. Architecture diagram (PRD §10.2 mermaid, rendered).
8. Where AI is and is not used (PRD §7.8 table, verbatim).
9. Privacy boundary diagram.
10. Licence, citation, team.

- [ ] **Step 2: Write `docs/ASSUMPTIONS.md` — the honesty document**

State plainly, because judges reward it and R4/R12 demand it:
- Velocities are Manning-based, not a calibrated SWMM model (Phase 2 decision).
- The network is a DAG; loops and backwater are out of scope; cycles from OSM were broken by dropping the longest edge.
- Single-source model; simultaneous multiple sources are in the scale path.
- Waterway orientation follows the OSM digitisation convention.
- Outfalls marked `is_synthetic` are invented for the demo catchment.
- All evaluation is on synthetic data; this validates the *method*, not field performance.
- Thresholds (0.5 / 0.9 / 0.1) are initial values, tuned in Phase 9 and still provisional.

- [ ] **Step 3: Write `docs/TRACK7_ALIGNMENT.md`**

Reproduce PRD §3.2's table and add, for each row, a **link to the artefact that proves it**:
the FSH profiles, the CI validator run, the CDS Hooks discovery endpoint, the
SubscriptionTopic, the Provenance examples, the AuditEvent examples, and the bounded
AI normaliser with its confirmation step.

- [ ] **Step 4: Final submission checklist**

```
[ ] Repository public, named upstream-onehealth (R10)
[ ] Searched the hackathon gallery for name collisions (R10)
[ ] LICENSE present (Apache-2.0 or MIT)
[ ] CI green: python, fhir (0 validator errors), bench (gates pass)
[ ] Demo video 3-5 min, uploaded, unlisted link works in an incognito window
[ ] Track alignment statement submitted (Track 7)
[ ] Project description written for a non-specialist
[ ] Working prototype reachable: either a hosted URL or a one-command local run
[ ] Screenshots: console, belief replay, CDS card, validator output, benchmark charts
[ ] .env.example committed; .env absent from the repository (GC-17)
[ ] No API key, token or password anywhere in git history (`git log -p | grep -iE 'sk-|api[_-]?key'`)
```

- [ ] **Step 5: Deploy to an EU host (NFR-11)**

```bash
# one EU-hosted VM, Docker Compose, Caddy for TLS
ssh $DEPLOY_HOST 'git clone https://github.com/<you>/upstream-onehealth && cd upstream-onehealth'
scp .env.production $DEPLOY_HOST:upstream-onehealth/.env
ssh $DEPLOY_HOST 'cd upstream-onehealth && make up && make migrate && make compile && make tables'
```

- [ ] **Step 6: Final commit and tag**

```bash
git add -A
git commit -m "docs: README, architecture, assumptions, Track 7 alignment, demo script"
git tag -a v0.1.0-hackathon -m "IEEE OneAquaHealth Hackathon 2026 submission"
git push origin main --tags
```

## Phase 12 exit criteria

- `make demo` passes every `expect` beat from PRD §10.5.
- Demo video 3–5 minutes covering all nine scenes of PRD §16.
- README lets a judge go from clone to running demo in five minutes.
- `docs/ASSUMPTIONS.md` states every simplification honestly.
- All three CI jobs green on the tagged commit.
- Repository public, licensed, named `upstream-onehealth`, no secrets in history.

## 🔑 Credentials needed at the end of Phase 12

| Variable | What it is | Where to get it |
|---|---|---|
| `DEPLOY_HOST` | `user@host` of an EU-hosted VM (NFR-11) | Hetzner (Falkenstein/Nuremberg), Scaleway (Paris/Amsterdam) or OVH. **You create the server and choose the region.** |
| `DEPLOY_SSH_KEY_PATH` | Path to the private key for that host | **You generate it** (`ssh-keygen -t ed25519`) |
| `PUBLIC_BASE_URL` | Public HTTPS URL of the deployment | Your domain, or the host's default; Caddy issues the certificate automatically |
| — | Devpost account | **You create it** — required to submit |
| — | Video host (YouTube/Vimeo, unlisted) | **You create it** — required for the 3–5 min demo |
| — | GitHub account + public repository | **You create it** — required for the code submission |

---

# Appendix A — Consolidated credentials checklist

Fill these into `.env`. **Nothing here blocks Phase 0–2**, so you can start building today and
fill keys as each phase arrives.

## A.1 — Things only you can decide (no third party involved)

| Variable | Phase | What to put |
|---|---|---|
| `POSTGRES_PASSWORD` | 0 | Any strong random string |
| `DATABASE_URL` | 0 | `postgresql://upstream:<pw>@db:5432/upstream` |
| `KERNEL_DATABASE_URL` | 0 | `postgresql://kernel_role:<pw>@db:5432/upstream` |
| `CLINICAL_DATABASE_URL` | 0 | `postgresql://clinical_role:<pw>@db:5432/clinical` |
| `CATCHMENT_ID` | 0 | Slug for the pilot catchment, e.g. `coimbra-ribeira` |
| `MEDIA_S3_ACCESS_KEY` / `MEDIA_S3_SECRET_KEY` | 3 | MinIO root credentials — you choose both |
| `VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY` | 6 | Generate locally: `python -c "from py_vapid import Vapid01; v=Vapid01(); v.generate_keys(); print(v.public_key_urlsafe_base64, v.private_key_urlsafe_base64)"` |
| `VAPID_SUBJECT` | 6 | `mailto:<your email>` |
| `JWT_SIGNING_KEY` | 11 | `openssl rand -hex 32` |
| `NEXT_PUBLIC_API_BASE_URL` | 10 | `http://localhost:8000`, then your domain |
| `PUBLIC_BASE_URL` | 12 | Your deployment URL |

## A.2 — Third-party keys you need to obtain

| Variable | Phase | Provider | Required? | Notes |
|---|---|---|---|---|
| `ANTHROPIC_API_KEY` | 3 | console.anthropic.com | **Recommended, not required** | Powers the AI normaliser on `claude-opus-5`. Without it the system falls back to `StubNormaliser` and everything else still works and demos. |
| `DEPLOY_HOST` + `DEPLOY_SSH_KEY_PATH` | 12 | Hetzner / Scaleway / OVH (EU region, NFR-11) | **Required for a hosted prototype** | Not needed if you demo from a local one-command run. |
| — | 12 | GitHub, Devpost, YouTube/Vimeo | **Required to submit** | Accounts, not keys. |
| `NEXT_PUBLIC_MAPTILER_KEY` | 10 | maptiler.com | **Optional — recommend leaving empty** | Only if you skip the self-hosted PMTiles basemap. PMTiles is better anyway: no rate limit and it works offline, which the mission PWA needs. |
| `TX_SERVER_URL` | 7 | tx.fhir.org | **Optional, no key** | Default public terminology server. Set to `n/a` to skip terminology checks if it is slow during a CI run. |

## A.3 — Things that are *not* keys but are often mistaken for them

| Item | Phase | Reality |
|---|---|---|
| OpenStreetMap / Overpass | 1 | **No key.** Public API via OSMnx, cached locally. |
| Open-Meteo rainfall | 3 | **No key** on the free non-commercial tier. |
| `hl7.eu.fhir.oah` IG package | 7 | **No key.** Either resolves from `packages.fhir.org` or is built once from `github.com/hl7-eu/oah` and vendored. |
| HL7 FHIR validator | 7 | **No key.** A JAR downloaded in CI. |
| CDS Hooks sandbox | 7 | **No key.** A public tunnel (ngrok/cloudflared) is optional for the demo. |
| SNOMED CT | 7 | **Not a key — a licence.** If you have no affiliate licence for the pilot country, set `SNOMED_LICENCE_ACCEPTED=false`; the local code system covers the MVP (GC-13 says "where licensed"). |
| Web Push | 6 | **No account.** VAPID keys are self-generated; browsers' own push services are used. |

---

# Appendix B — Requirement traceability

Every PRD functional requirement, and the task that implements it. This is the self-review
pass: no P0 requirement is unassigned.

| FR | Requirement (abbreviated) | Phase.Task |
|---|---|---|
| FR-1 | Accept citizen reports | 3.3 |
| FR-2 | Accept explicit negative reports | 3.3 |
| FR-3 | AI-proposed fields, citizen confirms | 3.2, 3.3 |
| FR-4 | Two times per observation | 0.3, 3.1, 3.3 |
| FR-5 | Snap to nearest node, reject far ones | 1.2, 3.3 |
| FR-6 | Sensor anomaly + normal-window evidence | 3.4 |
| FR-7 | Rainfall every 15 minutes | 3.3, 3.4 |
| FR-8 | Overflow activation signals | 3.3 |
| FR-9 | Field and lab results, including late | 3.3 |
| FR-10 | Retraction as a new event | 3.3, 4.3, 7.3 |
| FR-11 | Exact posterior on every change | 4.4 |
| FR-12 | Open SUSPECTED automatically | 6.1 |
| FR-13 | Rank source corridors + explanation | 4.4 |
| FR-14 | Per-zone exposure + 80% windows | 5.1 |
| FR-15 | EC², Protect and Enforce | 5.2, 5.3 |
| FR-16 | Reachable + safety-allowed only | 5.3 |
| FR-17 | Assign and route | 5.4, 6.2 |
| FR-18 | Fingerprinted snapshot | 4.4, 4.5 |
| FR-19 | Pool across closed episodes | 11.1 |
| FR-20 | Episode states and transitions | 6.1 |
| FR-21 | Officer sign-off + positive result for CONFIRMED | 6.1 |
| FR-22 | Clinically relevant until window ends | 6.1 |
| FR-23 | Re-plan PROBE on missed sample | 6.2 |
| FR-24 | Post-episode bioassessment | 6.1, 6.2 |
| FR-25 | Map to FHIR R4 on the OAH IG | 7.2, 7.3 |
| FR-26 | Zero validator errors in CI | 7.1, 7.3 |
| FR-27 | Provenance on episodes and AI observations | 7.3 |
| FR-28 | CDS Hooks with the three-condition rule | 7.4 |
| FR-29 | Topic-based Subscriptions | 7.3 |
| FR-30 | AuditEvent for cards and reads | 7.4 |
| FR-31 | Missions as FHIR `Task` | **Deferred (P2)** — PRD §17 cut list |
| FR-32 | Aggregate counts as MeasureReport, suppressed | 8.1 |
| FR-33 | Seasonal + day-of-week baselines | 8.2 |
| FR-34 | Daily matched-filter test, result only | 8.2 |
| FR-35 | Cluster detection → upstream search | 8.2 |
| FR-36 | Operator console | 10.1, 10.2 |
| FR-37 | Belief replay | 6.3, 10.2 |
| FR-38 | Mission PWA, offline | 10.3 |
| FR-39 | Public-health view | 10.3 |
| FR-40 | SMART on FHIR app | **Deferred (P2)** — the CDS card's SMART link is a stub |
| FR-41 | Parquet exports | 11.2 |
| FR-42 | Simulator on the real network | 9.1 |
| FR-43 | Ground truth hidden from the kernel | 0.4, 9.1 |
| FR-44 | Benchmark suite with baselines | 9.2 |
| FR-45 | Block calibration regressions | 9.2 |

| NFR | Where it is enforced |
|---|---|
| NFR-1 latency | 4.4 slow test; 9.2 metric; gate in CI |
| NFR-2 CDS < 500 ms | 7.4 test; in-memory zone cache |
| NFR-3 reproducibility | 0.1 pinned versions; 4.4 bitwise test; `XLA_FLAGS` fast-math off |
| NFR-4 auditability | 0.3 append-only grants; 7.3 `entered-in-error` |
| NFR-5 privacy | 0.4 separate DB; 8.1 boundary tests |
| NFR-6 calibration | 9.2 coverage + ECE with CI gate |
| NFR-7 standards | Phase 7 in full |
| NFR-8 ingestion survives kernel outage | 3.4 loop catches all exceptions; Phase 3 exit test |
| NFR-9 offline | 10.3 offline queue + Playwright offline test |
| NFR-10 accessibility | 10.2, 10.3 axe on every route |
| NFR-11 EU hosting | 12.2 deployment step |
| NFR-12 openness | 12.2 licence, Parquet, FHIR JSON |

---

# Appendix C — Contingency: what to cut, in what order

If you are behind at the end of any day, cut from the top of this list. **Never cut the
kernel, the simulator benchmarks, the FHIR validation, or belief replay** (PRD §17).

| Order | Cut | Cost of cutting | Where it is in this plan |
|---|---|---|---|
| 1 | FHIR `Task` for missions | None for Track 7 | Already deferred (FR-31) |
| 2 | SMART on FHIR app | The CDS card's link becomes informational | Already deferred (FR-40) |
| 3 | Keycloak / OIDC | Static JWTs instead; documented | Phase 11.2 |
| 4 | Post-episode bioassessment missions | Loses a 20-second demo scene | Phase 6.1, 6.2 |
| 5 | Multi-episode pooling | Loses the ecosystem leg of the demo | Phase 11.1 |
| 6 | FHIR Subscriptions | Publish still works; no push to subscribers | Phase 7.3 |
| 7 | OR-Tools routing | Assign to the nearest available volunteer by straight-line time | Phase 5.4 |
| 8 | Public-health view | Fold the content into the console | Phase 10.3 |
| 9 | Cluster detection (reverse direction) | Loses FR-35 only | Phase 8.2 |
| 10 | Real AI normaliser | `StubNormaliser` keeps the flow intact | Phase 3.2 |

**The one irreversible decision point:** if by the end of Day 4 `./fhir/scripts/validate.sh`
still reports errors, PRD §3.2 says to **fall back to Track 6 (Resilience Informatics) and
demote BRIDGE**. Make that call on Day 4 evening, not on Day 6 — Track 6 needs TRACE, PULSE,
PROBE and the benchmarks, all of which are done by then.

---

# Appendix D — Risks from PRD §19, and where each is handled

| Risk | Handled in |
|---|---|
| R1 sparse citizen data → flat posteriors | 10.1 "not enough evidence" rendering; 5.3 PROBE targets the highest-value check; 11.1 pooling |
| R2 no real outfall data | 1.2 `is_synthetic` flag; 10.1 `SyntheticBadge`; 12.2 `ASSUMPTIONS.md` |
| R3 FHIR modelling errors | 7.1 validator gate **first**, before any profile is written; 7.2 derives from the OAH IG |
| R4 physics simplifications | 2.1 Manning decision recorded; 1.1 cycle rejection; 12.2 `ASSUMPTIONS.md` |
| R5 false alarms | 9.2 calibration gate; 6.1 human gates; PRD thresholds configurable |
| R6 misuse to blame parties | 11.1 language test on the recurring-source report; 11.2 enforce mode is agency-only |
| R7 health-data breach | 0.4 separate database; 8.1 boundary tests from the clinical credential |
| R8 volunteer harm | 5.3 `safety.py` with tests for flood, storm and darkness |
| R9 seen as over-engineered | 0.2 six containers; 12.2 README leads with outcomes, not infrastructure |
| R10 name collision | 0.1 repo named `upstream-onehealth`; 12.2 gallery check in the checklist |
| R11 LLM normalisation mistakes | 3.2 schema-constrained output + mandatory confirmation (enforced in the Pydantic validator, Phase 0.5) |
| R12 synthetic-only evaluation | 9.2 honest reporting; 12.2 `ASSUMPTIONS.md` states it plainly |

---

# Appendix E — PRD open questions, decided here

The PRD leaves seven open questions. Six of them block implementation, so this plan takes a
position on each. Change any of them and only the named task is affected.

| # | Question | Decision taken in this plan | Task |
|---|---|---|---|
| 1 | Which OAH pilot catchment? | **You choose** and supply `data/catchment/catchment.geojson`. Everything downstream is catchment-agnostic. | 1.2 |
| 2 | Can the OAH Citizen Science App export observations? | **Assume not.** The MVP ingests through its own endpoints; OAH codes are carried in `oah_codes[]` so an import adapter is a later, additive change. | 3.3 |
| 3 | Are outfall locations available? | **Assume not.** Invent them, flag `is_synthetic`, badge them in the UI. | 1.2, 10.1 |
| 4 | Public-health partner for aggregate counts? | **Not for the MVP.** The simulator generates counts; the ingestion contract is real so a partner can plug in. | 8.1, 9.1 |
| 5 | SNOMED CT licensing? | **Assume no licence.** Local code systems for syndromes; `SNOMED_LICENCE_ACCEPTED=false`. | 7.2 |
| 6 | Which episode thresholds are acceptable? | **0.50 / 0.90 / 0.10** as PRD §6.3 proposes, configurable, re-tuned from the Phase 9 runs. | 0.5, 9.2 |
| 7 | Is enforce mode on by default? | **No.** Enforce mode requires the `agency` role, because it names an outfall to inspect. | 11.2 |

---

# Appendix F — Daily checkpoints

Run these at the end of each day. If a checkpoint fails, consult Appendix C before adding hours.

| End of | Must be true |
|---|---|
| **D1** | `make up && make migrate && make compile && make tables` succeeds on the real catchment; event-log ordering tests green |
| **D2** | An ingested report produces a fingerprinted posterior snapshot within 3 s; negative evidence demonstrably eliminates a branch |
| **D3** | Full lifecycle SUSPECTED → PROBABLE → CONFIRMED → RESOLVED runs; a mission is created, expires and re-plans |
| **D4** | **`validator errors: 0`**; CDS card renders in the sandbox; matched filter detects a shaped excess. *(Track decision point.)* |
| **D5** | 200-scenario benchmark with charts; console belief replay working; offline mission submission syncs |
| **D6** | `make demo` passes every `expect` beat; video recorded; README complete; repo public and tagged |

---

# Appendix G — Execution notes for whoever builds this

- **Test-first is not optional here.** The claims this project makes — calibrated windows, near-optimal sampling, bit-for-bit reproducibility, a hard privacy boundary — are only credible because tests demonstrate them. Several tests in this plan *are* the deliverable (the EC² within-class test, the bitwise-reproducibility test, the clinical boundary tests).
- **Commit after every task.** Each task in this plan ends with a working, tested increment.
- **Two tasks are on the critical path and should start earliest in their day:** Task 7.1 (resolving the OAH IG) and Task 1.2 (the real catchment). Both depend on external data whose availability you cannot control.
- **Do not build the frontend before Phase 9.** A console over a kernel that has not been benchmarked shows pictures, not evidence.
- **Invoke `superpowers:test-driven-development` per task and `superpowers:systematic-debugging` on any failure** rather than guessing; `ui-ux-pro-max` before writing any component in Phase 10.
