import { defineConfig } from "@playwright/test";
import { existsSync } from "node:fs";
import path from "node:path";
const root = path.resolve(__dirname, "..");
const python = existsSync(`${root}/backend/.venv/bin/python`) ? `${root}/backend/.venv/bin/python` : "python3";
const backend = Number(process.env.SAMPLE_BACKEND_PORT ?? 8141);
const owner = Number(process.env.SAMPLE_OWNER_PORT ?? 3141);
const assistant = Number(process.env.SAMPLE_ASSISTANT_PORT ?? 3142);
if (new Set([backend, owner, assistant]).size !== 3 || ![backend, owner, assistant].every(p => Number.isInteger(p) && p > 0 && p < 65536)) throw new Error("Sample fixtures need three distinct ports");
const api = `http://127.0.0.1:${backend}`;
const ownerOrigin = `http://127.0.0.1:${owner}`;
const assistantOrigin = `http://127.0.0.1:${assistant}`;
const state = `${root}/backend/data/sample_browser_trial`;
const db = `sqlite:///${state}/data/trial.db`;
const common = { TJ_ACCESS_ALLOW_LOCAL_HTTP: "true", TJ_OWNER_GATEWAY_KEY: "o".repeat(43), TJ_ASSISTANT_GATEWAY_KEY: "p".repeat(43), TJ_OWNER_ORIGIN: ownerOrigin, TJ_ASSISTANT_ORIGIN: assistantOrigin };
export default defineConfig({
  outputDir: "./sample-test-results", testDir: "./e2e", testMatch: "sample-decision.auth.ts", workers: 1, retries: 0,
  timeout: 60_000, expect: { timeout: 10_000 },
  use: { baseURL: assistantOrigin, trace: "retain-on-failure", screenshot: "only-on-failure" },
  webServer: [
    { command: `mkdir -p "${state}/data" && touch "${state}/.sample-installation" && "${python}" scripts/seed_dev_data.py --database-url "${db}" && "${python}" -m uvicorn scripts.sample_trial_browser:build_app --factory --host 127.0.0.1 --port ${backend}`, cwd: `${root}/backend`, url: `${api}/health`, reuseExistingServer: false, timeout: 120000,
      env: { ...common, DATABASE_URL: db, MIGRATION_DATABASE_URL: db, TJ_ACCESS_ENABLED: "true", TJ_ACCESS_SAMPLE_DATA: "true", TJ_DOT_TRIAL_ENABLED: "true", TJ_SAMPLE_DECISION_WRITES: "true", TJ_SAMPLE_REPLAY_ENABLED: "true", TJ_MARKET_DECISION_WRITES: "true", JOB_EXECUTION_MODE: "external", JOB_LOCK_DIR: `${state}/job_locks`, GMAIL_WATCH_AUTOSTART: "false", GMAIL_LISTENER_ENABLED: "false", WEBULL_LISTENER_AUTOSTART: "false", LEVEL_ALERTS_AUTOSTART: "false", PRACTICE_AGENT_ENABLED: "false", PRACTICE_SCHEDULE_ENABLED: "false", TRADIER_API_KEY: "", ALPACA_API_KEY: "", ALPACA_API_SECRET: "", POLYGON_API_KEY: "", OPENAI_API_KEY: "", ANTHROPIC_API_KEY: "", WEBULL_USERNAME: "", WEBULL_PASSWORD: "", NTFY_URL: "", CAPTURE_TRANSCRIBER: "off" } },
    { command: "npm run start", cwd: __dirname, url: `${ownerOrigin}/api/backend/health`, reuseExistingServer: false, timeout: 180000,
      env: { API_INTERNAL_URL: api, API_PROXY_TARGET: api, NEXT_PUBLIC_API_URL: "/api/backend", PORT: String(owner), TJ_ACCESS_PROFILE: "owner", TJ_GATEWAY_KEY: common.TJ_OWNER_GATEWAY_KEY, TJ_WEB_ORIGIN: ownerOrigin, TJ_ACCESS_ALLOW_LOCAL_HTTP: "true" } },
    { command: "npm run start", cwd: __dirname, url: `${assistantOrigin}/login`, reuseExistingServer: false, timeout: 180000,
      env: { API_INTERNAL_URL: api, API_PROXY_TARGET: api, NEXT_PUBLIC_API_URL: "/api/backend", PORT: String(assistant), TJ_ACCESS_PROFILE: "assistant", TJ_ASSISTANT_ENABLED: "true", TJ_GATEWAY_KEY: common.TJ_ASSISTANT_GATEWAY_KEY, TJ_WEB_ORIGIN: assistantOrigin, TJ_ACCESS_ALLOW_LOCAL_HTTP: "true" } },
  ],
});
