# Security

How upstream-onehealth controls access, where its secrets live, and what the MVP does not
yet do. PRD §14.3 is the requirement; this page describes what is built.

## Roles and what each may do

Access is by role (PRD §14.3). In the MVP a role is a claim in a signed token
(`services/core-api/upstream_api/security.py`). `admin` may do anything any other role may.

| Role | May call | Why it is restricted |
|---|---|---|
| `officer` | `POST /episodes/{id}/signoff`, `POST /episodes/{id}/signoff/request`, `POST /ingest/retract`, `POST /ingest/lab`, `GET /reports/recurring-sources` | Sign-off confirms an episode and publishes it to FHIR; retraction and lab results change what the system believes |
| `agency` | `POST /ingest/sensor`, `POST /ingest/rainfall`, `POST /ingest/overflow`, `GET /reports/recurring-sources`, `GET /exports/{episodes,evidence}.parquet` | Machine feeds, the recurring-source report and research exports |
| `public_health` | `GET /clinical/episodes`, `POST /clinical/test-result`, `POST /clinical/upstream-search` | The only routes the health zone calls (GC-7); the clinical service holds a service token |
| `citizen`, `clinician` | Nothing restricted yet | Defined now so tokens and the future Keycloak realm share one role list |

**Public, with no token:**

- reads of beliefs, episodes, replay, the network, missions and the public-health view;
- a volunteer's own actions: proposing and confirming a report, and accepting, declining
  or completing a mission.

The MVP web app has no login. A volunteer is identified by an id they choose, not by an
account. Public reads therefore carry no personal detail (see [PRIVACY.md](PRIVACY.md)).
An officer or agency token sees who made each report, and any photo.

### Enforce mode is off (PRD open question 7)

PROBE can plan in two modes. *Protect* asks which zones need a warning; *enforce* asks
which outfall to inspect. **Only protect mode runs.** The kernel worker plans in protect
mode, and no route lets a caller pick a mode.

The reason: an enforce-mode recommendation names a specific outfall, and PRD §14.4 routes
enforcement through officer confirmation. If a route that takes a mode is ever added, it
must require the `agency` role. `test_no_route_lets_a_caller_choose_enforce_mode` fails
until someone makes that decision on purpose.

## Tokens

- HS256 JWTs signed with `JWT_SIGNING_KEY`, carrying `sub`, `roles`, `iat` and `exp`. An
  expiry is required.
- Roles outside the six above are dropped from a token. It cannot invent `superuser`.
- **Fails closed.** If `JWT_SIGNING_KEY` is empty, every token is refused with 503;
  routes that need a role then refuse everyone.

Mint a token (for the clinical service, a test officer, a script):

```bash
python -m upstream_api.security mint --sub clinical-stats --role public_health --days 365
python -m upstream_api.security mint --sub officer-anna --role officer --days 7
```

Send it as `Authorization: Bearer <token>`.

### The Keycloak swap (pilot)

PRD §17 defers Keycloak to the pilot. The swap needs three changes:

1. Replace the body of `current_principal` so it verifies the realm's RS256 tokens
   against its JWKS, instead of the static key.
2. Map the realm roles to the same six names.
3. Give the clinical service a client-credentials grant instead of a minted token.

The route rules, `require_roles` and `redact_evidence` do not change.

## Secrets (GC-17)

Every secret is an environment variable in `.env`, which is git-ignored. `.env.example`
lists every variable with an empty value.

| Variable | Used for |
|---|---|
| `JWT_SIGNING_KEY` | Signing and verifying MVP tokens (`openssl rand -hex 32`) |
| `EXPORT_PSEUDONYM_KEY` | Keying observer pseudonyms in research exports; exports refuse to run without it |
| `CLINICAL_CORE_API_TOKEN` | The clinical service's `public_health` token |
| `*_DB_PASSWORD`, `DATABASE_URL`, … | One credential per database role (below) |
| `VAPID_*`, `MEDIA_S3_*`, `ANTHROPIC_API_KEY` | Push notifications, photo storage, the report normaliser |

## Least privilege in the database

- **The event log is append-only.** `append_event` is the only way in. No role may
  `UPDATE` or `DELETE` events, and a correction or retraction is a new event (GC-5).
- **`kernel_role`** reads evidence and writes posterior snapshots. It cannot write
  episodes, and it cannot read the simulator's ground truth (`sim_truth`, GC-10). Both
  rules are tested from that role's own login.
- **The health zone is a separate database** with its own role and credential (GC-7).
  `REVOKE CONNECT ON DATABASE upstream FROM PUBLIC` keeps the clinical role out of the
  environmental database. A `CHECK (count >= 5)` makes a small count unstorable.

## Audit

Every CDS Hooks card is recorded as a FHIR `AuditEvent`.

**Not yet done:** PRD §14.3 also asks that every external read be audited. In the MVP,
API reads are not audited beyond the server log. This is a pilot task.

## Known limits of the MVP

- **Citizen actions are unauthenticated.** Anyone can post a report or act on a mission
  under a volunteer id they know. The kernel weights each observer by reliability, and
  sign-off needs an officer, so a false report can shift a belief but cannot confirm an
  episode. The pilot adds citizen login (Keycloak) and rate limiting.
- **No rate limiting.** `POST /ingest/report/propose` calls a paid model when
  `ANTHROPIC_API_KEY` is set; put it behind a rate limit before a public deployment.
- **Photos are not screened automatically.** They are withheld from every public read
  instead (see [PRIVACY.md](PRIVACY.md)).
- **TLS** is the deployment's job (a reverse proxy in front of `api` and `web`); the
  containers speak plain HTTP on the internal network.

## Reporting a vulnerability

Open a private security advisory on the GitHub repository rather than a public issue.
