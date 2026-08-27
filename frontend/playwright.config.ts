import { defineConfig, devices } from "@playwright/test";
import { existsSync } from "node:fs";
import path from "node:path";

/**
 * Browser smoke tests against a seeded backend.
 *
 * These exist because typecheck, lint and build all pass on a component that
 * is broken at runtime. Nothing else in this repo proves a page renders.
 *
 * Dedicated ports (8099 / 3099) so a running dev session on 8080 / 3000 is
 * left alone, and a dedicated database (backend/data/e2e_seed.db) so real
 * trading history is never involved.
 */

const ROOT = path.resolve(__dirname, "..");
const BACKEND = path.join(ROOT, "backend");
const E2E_DB = path.join(BACKEND, "data", "e2e_seed.db");

const BACKEND_PORT = 8099;
const FRONTEND_PORT = 3099;
const API_URL = `http://127.0.0.1:${BACKEND_PORT}`;

// Prefer the project venv so the servers match what scripts/setup.sh built.
const VENV_PYTHON = path.join(BACKEND, ".venv", "bin", "python");
const PYTHON = existsSync(VENV_PYTHON) ? VENV_PYTHON : "python3";

// Seeding runs as part of the backend command rather than in globalSetup, so
// the database is guaranteed to exist before uvicorn's lifespan touches it
// regardless of how Playwright orders setup against webServer startup.
const backendCommand = [
  `"${PYTHON}" scripts/seed_dev_data.py --database-url "sqlite:///${E2E_DB}"`,
  `"${PYTHON}" -m uvicorn app.main:app --host 127.0.0.1 --port ${BACKEND_PORT}`,
].join(" && ");

export default defineConfig({
  testDir: "./e2e",
  // Pages read from one shared backend, so parallel workers would race on
  // any test that mutates. Serial keeps failures interpretable.
  workers: 1,
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: process.env.CI ? [["github"], ["list"]] : [["list"]],
  timeout: 30_000,
  expect: { timeout: 10_000 },

  use: {
    baseURL: `http://127.0.0.1:${FRONTEND_PORT}`,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },

  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        // Escape hatch for sandboxes that ship a preinstalled browser whose
        // build does not match this Playwright version (agent containers
        // typically do). Normally unset: CI and local machines resolve the
        // browser Playwright installed for itself.
        //   PLAYWRIGHT_CHROMIUM_PATH=/opt/pw-browsers/chromium npm run e2e
        ...(process.env.PLAYWRIGHT_CHROMIUM_PATH
          ? { launchOptions: { executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH } }
          : {}),
      },
    },
  ],

  webServer: [
    {
      command: backendCommand,
      cwd: BACKEND,
      url: `${API_URL}/health`,
      // Never reuse. NEXT_PUBLIC_* is baked at build time and the backend's
      // seed + CORS origin come from this config's env, so an already-running
      // server can be serving a stale build against a stale database -- which
      // shows up as tests passing on code that is actually broken. Rebuilding
      // each run costs ~15s and is worth it for a check whose whole job is to
      // be trustworthy.
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        DATABASE_URL: `sqlite:///${E2E_DB}`,
        // Client components fetch the API straight from the browser, so this
        // origin has to be in the backend's CORS allowlist or every
        // client-side request fails and those pages render a stuck loading
        // state.
        FRONTEND_PUBLIC_URL: `http://127.0.0.1:${FRONTEND_PORT}`,
        // Background workers would make runs nondeterministic and reach for
        // credentials that are deliberately absent here.
        GMAIL_WATCH_AUTOSTART: "false",
        WEBULL_LISTENER_AUTOSTART: "false",
        TRADINGVIEW_ANALYSIS_AUTOSTART: "false",
      },
    },
    {
      // NEXT_PUBLIC_* is inlined at build time, so the build has to happen
      // here with the e2e API URL set; a previously built bundle would point
      // at the wrong backend.
      command: `npm run build && npx next start -p ${FRONTEND_PORT}`,
      cwd: __dirname,
      url: `http://127.0.0.1:${FRONTEND_PORT}`,
      // Never reuse. NEXT_PUBLIC_* is baked at build time and the backend's
      // seed + CORS origin come from this config's env, so an already-running
      // server can be serving a stale build against a stale database -- which
      // shows up as tests passing on code that is actually broken. Rebuilding
      // each run costs ~15s and is worth it for a check whose whole job is to
      // be trustworthy.
      reuseExistingServer: false,
      timeout: 180_000,
      env: { NEXT_PUBLIC_API_URL: API_URL },
    },
  ],
});
