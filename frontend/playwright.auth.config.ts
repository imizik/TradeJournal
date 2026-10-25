import { defineConfig } from "@playwright/test";
import { existsSync, mkdtempSync, realpathSync } from "node:fs";
import os from "node:os";
import path from "node:path";
const root = path.resolve(__dirname, "..");
const python = existsSync(`${root}/backend/.venv/bin/python`) ? `${root}/backend/.venv/bin/python` : "python3";
const backend = Number(process.env.AUTH_BACKEND_PORT ?? 8129);
const owner = Number(process.env.AUTH_OWNER_PORT ?? 3129);
const assistant = Number(process.env.AUTH_ASSISTANT_PORT ?? 3130);
if (new Set([backend, owner, assistant]).size !== 3 || ![backend, owner, assistant].every(p => Number.isInteger(p) && p > 0 && p < 65536)) throw new Error("Auth fixtures need three distinct ports");
const api = `http://127.0.0.1:${backend}`;
const ownerOrigin = `http://127.0.0.1:${owner}`;
const assistantOrigin = `http://127.0.0.1:${assistant}`;
const db = `sqlite:///${root}/backend/data/auth_e2e.db`;
const manualFillsBackup = `${mkdtempSync(path.join(os.tmpdir(), "tj-auth-manual-fills-"))}/manual_fills.json`;
process.env.ADVISOR_OWNER_TEST_DIR ??= mkdtempSync(path.join(realpathSync(os.tmpdir()), "tj-owner-"));
const common = { TJ_ACCESS_ALLOW_LOCAL_HTTP: "true", TJ_OWNER_GATEWAY_KEY: "o".repeat(43), TJ_ASSISTANT_GATEWAY_KEY: "p".repeat(43), TJ_OWNER_ORIGIN: ownerOrigin, TJ_ASSISTANT_ORIGIN: assistantOrigin };
export default defineConfig({
  outputDir: "./auth-test-results",
  testDir: "./e2e", testMatch: ["browser-access.auth.ts", "advisor-owner.auth.ts", "advisor-assignments.auth.ts"], workers: 1, retries: 0,
  timeout: 30_000, expect: { timeout: 10_000 },
  // Same browser escape hatch as playwright.config.ts (verify.sh sets it in a cloud sandbox).
  use: { baseURL: assistantOrigin, trace: "retain-on-failure", screenshot: "only-on-failure", ...(process.env.PLAYWRIGHT_CHROMIUM_PATH ? { launchOptions: { executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH } } : {}) },
  webServer: [
    { command: `"${python}" scripts/seed_dev_data.py --database-url "${db}" && "${python}" -m uvicorn app.main:app --host 127.0.0.1 --port ${backend}`, cwd: `${root}/backend`, url: `${api}/health`, reuseExistingServer: false, timeout: 120000,
      env: { ...common, DATABASE_URL: db, TJ_MANUAL_FILLS_BACKUP: manualFillsBackup, TJ_ACCESS_ENABLED: "true", TJ_ACCESS_SAMPLE_DATA: "true", JO_MORNING_CONFIG: "", JOB_EXECUTION_MODE: "external", JOB_LOCK_DIR: `${root}/backend/data/auth_job_locks`, GMAIL_WATCH_AUTOSTART: "false", GMAIL_LISTENER_ENABLED: "false", WEBULL_LISTENER_AUTOSTART: "false", LEVEL_ALERTS_AUTOSTART: "false", PRACTICE_AGENT_ENABLED: "false", PRACTICE_SCHEDULE_ENABLED: "false", TRADIER_API_KEY: "", ALPACA_API_KEY: "", ALPACA_API_SECRET: "", CAPTURE_TRANSCRIBER: "off" } },
    { command: "npm run start", cwd: __dirname, url: `${ownerOrigin}/api/backend/health`, reuseExistingServer: false, timeout: 180000,
      env: { API_INTERNAL_URL: api, API_PROXY_TARGET: api, NEXT_PUBLIC_API_URL: "/api/backend", PORT: String(owner), TJ_ACCESS_PROFILE: "owner", TJ_GATEWAY_KEY: common.TJ_OWNER_GATEWAY_KEY, TJ_WEB_ORIGIN: ownerOrigin, TJ_ACCESS_ALLOW_LOCAL_HTTP: "true", TJ_ADVISOR_MANAGEMENT_ENABLED: "true", TJ_ADVISOR_MANAGER_SOCKET: `${process.env.ADVISOR_OWNER_TEST_DIR}/managed/backend.sock`, TJ_ADVISOR_MANAGER_SOCKET_UID: String(process.getuid!()), TJ_ADVISOR_OWNER_ENABLED: "true", TJ_ADVISOR_OWNER_SOCKET: `${process.env.ADVISOR_OWNER_TEST_DIR}/owner.sock`, TJ_ADVISOR_OWNER_SOCKET_UID: String(process.getuid!()) } },
    { command: "npm run start", cwd: __dirname, url: `${assistantOrigin}/login`, reuseExistingServer: false, timeout: 180000,
      env: { API_INTERNAL_URL: api, API_PROXY_TARGET: api, NEXT_PUBLIC_API_URL: "/api/backend", PORT: String(assistant), TJ_ACCESS_PROFILE: "assistant", TJ_ASSISTANT_ENABLED: "true", TJ_GATEWAY_KEY: common.TJ_ASSISTANT_GATEWAY_KEY, TJ_WEB_ORIGIN: assistantOrigin, TJ_ACCESS_ALLOW_LOCAL_HTTP: "true" } },
  ],
});
