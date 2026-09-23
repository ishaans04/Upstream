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

.PHONY: up down migrate test compile tables sim bench validate demo
