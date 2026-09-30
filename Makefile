up:        ; docker compose up -d
down:      ; docker compose down
migrate:   ; docker compose run --rm api alembic -c db/alembic.ini upgrade head
test:      ; docker compose run --rm api pytest -q
compile:   ; docker compose run --rm kernel python -m upstream_kernel.compile.cli
tables:    ; docker compose run --rm kernel python -m upstream_kernel.physics.cli
# The simulator and the benchmark run on the host: neither needs a service container,
# and the api image does not install them. `sim` writes to the database in .env.host.
sim:       ; set -a && . ./.env.host && set +a && uv run --python 3.12 python -m upstream_sim.run --scenarios 50
bench:     ; JAX_ENABLE_X64=1 JAX_PLATFORMS=cpu uv run --python 3.12 python -m upstream_bench.runner --scenarios 200 --out bench/results --charts
# bench-ci re-records the baseline the CI gate compares against; run it when a change
# is meant to move the numbers, and commit bench/results/summary-ci.json with it.
bench-ci:  ; $(BENCH_CI) --out bench/ci-results && cp bench/ci-results/summary.json bench/results/summary-ci.json
bench-gate: ; $(BENCH_CI) --out bench/ci-results --gate --baseline-summary bench/results/summary-ci.json
validate:  ; ./fhir/scripts/validate.sh
fhir-load: ; ./fhir/scripts/load-into-hapi.sh
# The demo: a simulated incident on the sim stream, driven through the real kernel,
# episode workflow and mission API. Needs `EPISODE_STREAMS=live,sim` for the api and
# the web app built with WEB_STREAM=sim.
demo:      ; docker compose --profile demo up -d kernel-sim && set -a && . ./.env.host && set +a && uv run --python 3.12 python -m upstream_sim.demo --reset
# Before running the test suite after a demo: frees the network, clears the sim stream and
# stops the sim worker. The api should then run with EPISODE_STREAMS=live.
demo-end:  ; set -a && . ./.env.host && set +a && uv run --python 3.12 python -m upstream_sim.demo --end && docker compose stop kernel-sim
web-test:  ; cd web && npm test
web-e2e:   ; cd web && npx playwright test
# Regenerate the typed client after an API change (a Python test fails until you do).
web-types: ; set -a && . ./.env.host && set +a && uv run --python 3.12 python scripts/export_openapi.py && cd web && npm run types
web-bench: ; cd web && node scripts/sync-bench.mjs

BENCH_CI = JAX_ENABLE_X64=1 JAX_PLATFORMS=cpu uv run --python 3.12 python -m upstream_bench.runner --scenarios 40 --null-days 30 --network bench/fixtures/network.npz --tables none

.PHONY: up down migrate test compile tables sim bench bench-ci bench-gate validate fhir-load demo demo-end web-test web-e2e web-types web-bench
