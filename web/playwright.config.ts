import { defineConfig, devices } from "@playwright/test";

// End-to-end against the production build and a running Core API
// (`docker compose up api` or the whole stack). BASE_URL overrides the target.
export default defineConfig({
  testDir: "./e2e",
  timeout: 180_000,             // the map loads a whole catchment; slow under parallel load
  retries: 0,
  // One browser at a time: each console page renders a whole catchment in WebGL, and
  // parallel instances starve a small machine into timeouts that are not the app's.
  workers: 1,
  use: {
    baseURL: process.env.BASE_URL || "http://localhost:3000", trace: "off",
    // E2E_CHANNEL=chrome (or msedge) drives an installed browser instead of Playwright's own.
    ...(process.env.E2E_CHANNEL ? { channel: process.env.E2E_CHANNEL } : {}),
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] }, testIgnore: /mission-offline/ },
    { name: "phone", use: { ...devices["Pixel 7"] }, testMatch: /mission-offline/ },
  ],
  webServer: process.env.BASE_URL ? undefined : {
    command: "npm run start",
    url: "http://localhost:3000",
    reuseExistingServer: true,
    timeout: 120_000,
  },
});
