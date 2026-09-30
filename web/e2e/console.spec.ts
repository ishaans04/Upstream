import { expect, test } from "@playwright/test";
import { STREAM, consoleTrack, timeline } from "./helpers";

// Phase 10 exit criteria, against the real catchment and a real stored history:
// the console renders the network, and the belief slider reproduces past beliefs and
// shows their fingerprints.

test("the console renders the real catchment with its synthetic outfalls labelled", async ({ page }) => {
  await page.goto("/console");
  await expect(page.getByLabel("The drain network is loading")).toHaveCount(0, { timeout: 90_000 });
  // PRD R2: every outfall on the Delhi network is synthetic, and each says so.
  await expect(page.locator('[aria-label="Synthetic (illustrative) outfall location"]:visible').first()).toBeVisible();
});

test("the slider shows the belief recorded at its position, with that belief's fingerprint", async ({ page, request }) => {
  const track = await consoleTrack(request);
  test.skip(track.length < 2, `needs an episode with two stored beliefs on the ${STREAM} stream (run make demo)`);

  await page.goto("/console");
  const slider = page.getByRole("slider");
  await expect(slider).toHaveAccessibleName(/showing belief at/i, { timeout: 90_000 });

  // Drag to the first stored belief: the fingerprint must be that snapshot's, not the latest.
  await slider.focus();
  await page.keyboard.press("Home");
  const first = track[0].fingerprint;
  await expect(page.getByText(first, { exact: true })).toBeVisible({ timeout: 30_000 });

  await page.keyboard.press("End");
  const last = track[track.length - 1].fingerprint;
  await expect(page.getByText(last, { exact: true })).toBeVisible({ timeout: 30_000 });
  expect(first).toMatch(/^sha256:/);
});

test("the replay page reproduces a past belief from the API, bit for bit", async ({ page, request }) => {
  const track = await timeline(request);
  test.skip(track.length === 0, `no stored beliefs on the ${STREAM} stream`);
  // Every stored moment returns its own belief, not the one before it.
  for (const point of track.slice(0, 20)) {
    const r = await request.get("/api/core/replay", { params: { at: point.ts, stream: STREAM } });
    expect(r.ok()).toBeTruthy();
    expect((await r.json()).fingerprint).toBe(point.fingerprint);
  }
  await page.goto("/replay");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible({ timeout: 90_000 });
});
