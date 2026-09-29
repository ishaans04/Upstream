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
demo:      ; docker compose run --rm api python -m upstream_sim.demo_scenario

BENCH_CI = JAX_ENABLE_X64=1 JAX_PLATFORMS=cpu uv run --python 3.12 python -m upstream_bench.runner --scenarios 40 --null-days 30 --network bench/fixtures/network.npz --tables none

.PHONY: up down migrate test compile tables sim bench bench-ci bench-gate validate fhir-load demo
