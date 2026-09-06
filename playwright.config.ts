import { existsSync } from "node:fs";

import { defineConfig, devices } from "@playwright/test";

/**
 * This environment ships a Chromium that Playwright's own version pin does not match, so point at
 * it directly rather than downloading another copy. Where it is absent — a developer laptop — the
 * usual resolution applies.
 */
const CHROMIUM = "/opt/pw-browsers/chromium";
const launch = existsSync(CHROMIUM) ? { executablePath: CHROMIUM } : {};

/**
 * The smoke suite drives the real stack: the FastAPI service against the built DuckDB warehouse,
 * and the Next.js app against that API. Nothing is mocked, because what these tests are for is
 * catching the seams between the three — a contract that drifted, a route that moved, a figure
 * that stopped arriving with its query attached.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  timeout: 60_000,
  expect: { timeout: 15_000 },
  use: {
    baseURL: "http://127.0.0.1:3100",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], launchOptions: launch } },
    // A phone profile as well: the 3D city has to work on one, and the rail collapses there.
    { name: "phone", use: { ...devices["Pixel 7"], launchOptions: launch } },
  ],
  webServer: [
    {
      command:
        "uv run uvicorn api.main:app --host 127.0.0.1 --port 8100 --log-level warning",
      url: "http://127.0.0.1:8100/health",
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: { LLM_PROVIDER: "fake" },
    },
    {
      command: "npm --workspace @yieldmap/web run start -- --port 3100",
      url: "http://127.0.0.1:3100",
      reuseExistingServer: !process.env.CI,
      timeout: 180_000,
      // Read at runtime by the rewrite, so the build is not pinned to a URL.
      env: { API_ORIGIN: "http://127.0.0.1:8100" },
    },
  ],
});
