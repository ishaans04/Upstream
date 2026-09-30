import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { CORE } from "./helpers";

const VOLUNTEER = process.env.E2E_VOLUNTEER || "vol-sim-03";

// GC-14 / NFR-10: axe reports zero WCAG 2.1 AA violations on every route.
const ROUTES = ["/", "/console", "/replay", "/missions", "/public-health", "/benchmarks"];

async function audit(page: import("@playwright/test").Page) {
  const r = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    // The WebGL map canvas is not DOM content; its controls and legend are audited.
    .exclude("canvas")
    .analyze();
  return r.violations.map((v) => `${v.id} (${v.impact}): ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`);
}

for (const route of ROUTES) {
  test(`no WCAG 2.1 AA violations on ${route}`, async ({ page }) => {
    await page.goto(route);
    await page.waitForLoadState("networkidle");
    expect(await audit(page)).toEqual([]);
  });
}

test("no WCAG 2.1 AA violations on a mission", async ({ page, request }) => {
  const r = await request.get(`${CORE}/missions/mine`, { params: { volunteer_id: VOLUNTEER, include_closed: true } });
  const rows = r.ok() ? await r.json() : [];
  test.skip(rows.length === 0, "no mission on record to render");
  await page.addInitScript((v) => localStorage.setItem("upstream.volunteer", v), VOLUNTEER);
  await page.goto(`/missions/${rows[0].mission_id}`);
  await page.waitForLoadState("networkidle");
  expect(await audit(page)).toEqual([]);
});
