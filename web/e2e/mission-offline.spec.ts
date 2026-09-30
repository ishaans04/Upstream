import { expect, test } from "@playwright/test";
import { CORE, STREAM, openMission } from "./helpers";

// Phase 10 exit criterion (NFR-9, GC-4): a mission submitted in airplane mode arrives
// after reconnect with the original observed_at, and exactly once.
//
// Needs a mission left for a person: `python -m upstream_sim.demo --human vol-sim-03`.
const VOLUNTEER = process.env.E2E_VOLUNTEER || "vol-sim-03";

// Chromium does not apply Playwright's offline emulation to service-worker traffic, so
// Background Sync would send the reading while the page believes it has no signal.
// Blocking the worker tests the path every browser has: the page's own outbox, flushed
// on `online`. The worker's drain sends the same idempotency key, so it cannot add a
// second event (checked by hand: one event per mission, device time kept).
test.use({ serviceWorkers: "block" });

test("a reading saved offline arrives once, with the time it was taken", async ({ page, context, request }) => {
  const mission = await openMission(request, VOLUNTEER);
  test.skip(!mission, `no open mission for ${VOLUNTEER} on the ${STREAM} stream (run the demo with --human ${VOLUNTEER})`);
  const id = mission!.mission_id;

  await page.addInitScript((v) => localStorage.setItem("upstream.volunteer", v), VOLUNTEER);
  await page.goto(`/missions/${id}`);
  if (mission!.status === "created") {
    await expect(page.getByText(/why it matters/i)).toBeVisible({ timeout: 30_000 });
    await page.getByRole("button", { name: "Accept mission" }).click();
  }
  await expect(page.getByRole("heading", { name: /what did the strip show/i })).toBeVisible();

  // Airplane mode, then take the reading.
  await context.setOffline(true);
  await page.getByRole("radio", { name: "Looked normal" }).click();
  const before = Date.now();
  await page.getByRole("button", { name: "Save reading" }).click();
  await expect(page.getByRole("heading", { name: /waiting for signal/i })).toBeVisible();

  const queued = await page.evaluate(() => new Promise<{ observed_at: string; idempotency_key: string }[]>((resolve, reject) => {
    const req = indexedDB.open("upstream-outbox", 1);
    req.onsuccess = () => {
      const all = req.result.transaction("outbox", "readonly").objectStore("outbox").getAll();
      all.onsuccess = () => resolve(all.result);
      all.onerror = () => reject(all.error);
    };
    req.onerror = () => reject(req.error);
  }));
  expect(queued).toHaveLength(1);
  const { observed_at, idempotency_key } = queued[0];
  expect(Date.parse(observed_at)).toBeGreaterThanOrEqual(before - 1000);

  // Stay offline long enough that "now" on reconnect is clearly not the reading's time.
  await page.waitForTimeout(3_000);
  await context.setOffline(false);
  await page.evaluate(() => window.dispatchEvent(new Event("online")));
  await expect(page.getByRole("heading", { name: /your check changed the picture/i })).toBeVisible({ timeout: 30_000 });

  // The server holds one event for this mission, keyed by the phone's idempotency key,
  // stamped with the phone's time.
  const m = await (await request.get(`${CORE}/missions/${id}`)).json();
  expect(m.status).toBe("completed");
  const ep = await (await request.get(`${CORE}/episodes/${m.episode_id}`, { params: { stream: STREAM } })).json();
  const mine = ep.evidence.filter((e: { payload: { mission_id?: string } }) => e.payload.mission_id === id);
  expect(mine).toHaveLength(1);
  expect(mine[0].event_id).toBe(idempotency_key);
  expect(Date.parse(mine[0].event_time)).toBe(Date.parse(observed_at));
  expect(Date.parse(mine[0].recorded_at)).toBeGreaterThan(Date.parse(observed_at) + 2_000);
});
