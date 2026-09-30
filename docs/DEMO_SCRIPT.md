# Demo script (3–5 minutes)

For whoever records the video. Each scene below says what to put on screen, what to
say, and which check in `make demo` proves it.

## Before recording

1. Run in **daylight** (07:00–20:00 Delhi time); no mission is sent after dark.
2. Start the stack: `make up`.
3. Load FHIR: `docker compose up -d hapi`, wait about two minutes, then `make fhir-load`.
4. Rehearse: `make demo`. Expect `12 passed, 0 failed, 0 skipped`, in about four
   minutes.
   - It brings up the API, the web app and the sim worker with the demo's settings.
     A plain `docker compose up` afterwards puts the API back on the live stream only,
     so run `make demo` again rather than restarting services by hand.
   - Each run resets the simulated stream, so the last run is what the console shows.
5. Record at 1920×1080, 30 fps. Open <http://localhost:3000/console>.

## Scenes (PRD §16)

| Time | Scene | On screen | Say | Proved by |
|---|---|---|---|---|
| 0:00–0:30 | The three clocks | Landing page, then the console with no episode | "A sewage spill runs on the river's clock. Clinics see it days later, on their own clock. The two never meet." | — |
| 0:30–1:00 | Rain, one report | Console at the first belief: storm, one smell report; probability spread over several outfalls | "One report. The system does not pick a culprit: it spreads belief over every outfall that could explain it." | `02:17 a new episode opens` |
| 1:00–1:40 | A volunteer's check | The mission on a phone (`/missions/<id>`), then back to the console: the volunteer's "looked normal" and what it changed | "PROBE picked the check that best separates the suspects. 'Looks normal' is evidence too: it rules places out." | `02:22 PROBE`, `02:31 G7 feedback` |
| 1:40–2:10 | The source corridor | TRACE ranking (the overflowing outfall first), PULSE windows with credible bands on the timeline | "Now it knows where, and it tells each park downstream when it is exposed, with an 80% window." | `02:19 TRACE`, `02:21 PULSE` |
| 2:10–2:50 | Belief replay | `/replay`, then drag the console slider back to the first belief and forward again; point at the fingerprint changing | "Every belief is stored and fingerprinted. Recomputing from this fingerprint gives this exact belief, bit for bit." | e2e `console.spec.ts` |
| 2:50–3:30 | **Standards** | Terminal: `./fhir/scripts/validate.sh`, ending **`validator errors: 0`** (hold **≥ 6 s**). Then the episode in HAPI (`/fhir/RiskAssessment/<id>`) and a CDS card in the CDS Hooks sandbox (hold **≥ 6 s**) | "Published as FHIR, derived from the OneAquaHealth IG, zero validator errors. A clinician in the exposed area sees one line." | `02:40 FHIR published`; CI `fhir` job |
| 3:30–4:10 | The One Health loop | `/public-health`: the episode's clinical results; only a p-value crosses | "Days later the health service tests its own counts against the predicted curve. Only the answer comes back, never a count." | `day 3 matched filter` |
| 4:10–4:40 | It is evaluated | `/benchmarks`: accuracy against the heuristic, calibration, samples to localise | "Two hundred simulated incidents with hidden ground truth. Calibrated windows. And where it does not yet beat the baselines, we say so." | `bench` CI gate |
| 4:40–5:00 | Recurring source, ecosystem | The recurring-source report and the week-4 bioassessment mission | "Across episodes one outfall keeps coming back: a place to inspect, not a party to blame. Four weeks on, a survey measures recovery." | `nightly`, `week 4` |

## Getting the pieces on screen

- **The mission on a phone.** `make demo` completes its missions with simulated
  volunteers. For a live phone shot, run `make demo-free` with `--human vol-sim-03`,
  open `/missions` on the phone, and enter `vol-sim-03`.
- **The recurring-source report** needs an agency token:
  ```bash
  TOKEN=$(uv run python -m upstream_api.security mint --sub demo --role agency --days 1)
  curl -H "Authorization: Bearer $TOKEN" "localhost:8000/reports/recurring-sources?stream=sim"
  ```
- **The CDS Hooks sandbox** needs the API reachable from the internet (for example
  `cloudflared tunnel --url http://localhost:8000`). Register
  `https://<tunnel>/cds-services` in the sandbox.

## Things not to say

- Don't say the outfalls are real: they are synthetic, and badged.
- Don't say the results are field-validated: they are simulated on a real network.
- Don't say Upstream issues advisories or names a polluter. It gives environmental
  context, not a diagnosis, and places to inspect.
