import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";

const API = `http://127.0.0.1:${Number(process.env.E2E_BACKEND_PORT || 8099)}`;
const BACKEND_DIR = path.resolve(__dirname, "..", "..", "backend");
const E2E_DB = path.join(BACKEND_DIR, "data", "e2e_seed.db");
const python = existsSync(path.join(BACKEND_DIR, ".venv", "bin", "python"))
  ? path.join(BACKEND_DIR, ".venv", "bin", "python")
  : "python3";

function seedNoProviderRun(day: string) {
  const runId = crypto.randomUUID();
  const oppId = crypto.randomUUID();
  const contextId = crypto.randomUUID();
  const jobId = crypto.randomUUID();
  const script = `
import json, sqlite3, sys
from datetime import datetime, timedelta, timezone
run_id, opp_id, context_id, job_id, day = sys.argv[2:]
now = datetime.now(timezone.utc).replace(tzinfo=None)
stamp = now.isoformat(sep=" ")
captured = now.replace(tzinfo=timezone.utc).isoformat()
db = sqlite3.connect(sys.argv[1])
db.execute("PRAGMA foreign_keys=ON")
db.execute("insert into job_run (id, job_type, status, params_json, total, done, enriched, created_at, updated_at) values (?,?,?,?,?,?,?,?,?)", (job_id, "practice_prepare", "failed", "{}", 1, 0, 0, stamp, stamp))
db.execute("insert into practice_run (id, session_key, day, revision, parent_id, job_id, mode, comparison, status, result, late, deadline, created_at, finished_at, policy_version, policy_hash, calendar_json, brief_json, timings_json, error) values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (run_id, "e2e-a3-" + run_id, day, 0, None, job_id, "manual", "independent", "failed", "failed", 0, (now + timedelta(hours=2)).isoformat(sep=" "), stamp, (now + timedelta(seconds=1)).isoformat(sep=" "), "practice-long-15m-v1", "fixture-policy-hash", json.dumps({"status":"unavailable"}), json.dumps([{ "title":"MARKET TAPE", "text":"Unavailable: provider credentials are disabled in this fixture.", "sources":[] }, { "title":"IMPORTANT NEWS", "text":"Unavailable.", "sources":[] }, { "title":"SETUP BOARD", "text":"Provider unavailable; frozen context retained for a reasoned SKIP.", "sources":[] }]), "{}", "Provider unavailable; no agent call was attempted"))
packet = {"symbol":"SPY", "data_source":"unavailable", "missing":["Provider unavailable"], "recent_minute_bars":[]}
evidence = {"context_version":1,"context_state":"unavailable","symbol":"SPY","provider":"unavailable","captured_at":captured,"packet":packet,"price_facts":[]}
db.execute("insert into decision_context (id, operation_id, symbol, captured_at, provider, data_json, context_sha256) values (?,?,?,?,?,?,?)", (context_id, "e2e-a3-context-" + run_id, "SPY", stamp, "unavailable", json.dumps(evidence, separators=(",",":")), "fixture-context-hash"))
benchmark = {"version":"underlying-open-close-v1", "status":"unavailable", "reason":"Provider unavailable in fixture"}
db.execute("insert into practice_opportunity (id, run_id, symbol, context_id, revealed_at, benchmark_json, feedback_json) values (?,?,?,?,?,?,?)", (opp_id, run_id, "SPY", context_id, None, json.dumps(benchmark), json.dumps({"rating":"unrated","phone_received":None})))
db.commit()
db.close()
`;
  execFileSync(python, ["-c", script, E2E_DB, runId.replace(/-/g, ""), oppId.replace(/-/g, ""), contextId.replace(/-/g, ""), jobId.replace(/-/g, ""), day], { cwd: BACKEND_DIR });
  return { runId, oppId };
}

test.afterEach(() => {
  const cleanup = `
import sqlite3,sys,uuid
db=sqlite3.connect(sys.argv[1])
db.execute("PRAGMA foreign_keys=OFF")
ids=[r[0] for r in db.execute("select id from practice_run where session_key like 'e2e-a3-%'")]
for run_id in ids:
  opps=[r[0] for r in db.execute("select id from practice_opportunity where run_id=?", (run_id,))]
  for opp_id in opps:
    db.execute("delete from decision_record where opportunity_id=?", ("a3:" + str(uuid.UUID(hex=opp_id)),))
  db.execute("delete from decision_context where operation_id=?", ("e2e-a3-context-" + run_id,))
  db.execute("delete from practice_opportunity where run_id=?", (run_id,))
  job_id=db.execute("select job_id from practice_run where id=?", (run_id,)).fetchone()[0]
  db.execute("delete from practice_run where id=?", (run_id,))
  db.execute("delete from job_run where id=?", (job_id,))
db.commit()
`;
  execFileSync(python, ["-c", cleanup, E2E_DB], { cwd: BACKEND_DIR });
});

test("manual no-provider choice persists, reveal refuses without agent output, and routine fits phone width", async ({ page, request }) => {
  const day = new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
  const fixture = seedNoProviderRun(day);

  const response = await request.get(`${API}/practice/runs/${fixture.runId}`);
  expect(response.ok()).toBeTruthy();
  expect(await response.json()).toMatchObject({ id: fixture.runId, agent: { status: "disabled" }, comparison: "independent" });

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  const routine = page.getByTestId("practice-routine");
  await expect(routine).toBeVisible();
  await expect(routine).toContainText("Provider unavailable");
  await expect(routine).toContainText("Agent disabled");
  const opportunity = routine.getByTestId("practice-opportunity");
  await expect(opportunity).toContainText("SPY");
  await opportunity.getByLabel("Rationale").fill("No verified market facts are available; preserve the decision as SKIP.");
  await opportunity.getByRole("button", { name: "Save frozen choice" }).click();
  await expect(opportunity).toContainText("Human: SKIP");
  await expect(opportunity).toContainText("No verified market facts are available");

  const denied = await request.post(`${API}/practice/opportunities/${fixture.oppId}/reveal`, { data: {} });
  expect(denied.status()).toBe(409);
  expect((await denied.json()).detail).toContain("both durably committed choices");

  await page.reload();
  const reopened = page.getByTestId("practice-routine").getByTestId("practice-opportunity");
  await expect(reopened).toContainText("Human: SKIP");
  await expect(reopened).toContainText("No verified market facts are available");
  await expect(reopened).toContainText("unavailable");
  await expect(reopened.getByText("Agent choice: Unavailable")).toHaveCount(0);

  const widths = await page.evaluate(() => ({
    viewport: window.innerWidth,
    scrollWidth: document.documentElement.scrollWidth,
    routine: document.querySelector('[data-testid="practice-routine"]')?.getBoundingClientRect().right ?? Infinity,
  }));
  expect(widths.routine).toBeLessThanOrEqual(widths.viewport + 1);
  expect(widths.scrollWidth).toBeLessThanOrEqual(widths.viewport + 1);
});

test("independent comparison hides a committed agent choice until human commit and explicit reveal", async ({ page, request }) => {
  const day = new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
  const fixture = seedNoProviderRun(day);
  const script = `
import sys,uuid
from sqlmodel import Session
from app.database import engine
from app.engine import practice
from app.models import PracticeOpportunity
with Session(engine) as db:
    opp=db.get(PracticeOpportunity,uuid.UUID(sys.argv[1]))
    practice.choose(db,opp,{"decision":"wait","rationale":"Agent WAIT verdict withheld until reveal","wait_condition":"Price facts remain unavailable","wait_expiry":"2030-01-01T21:00:00Z"},actor="agent:a3")
`;
  execFileSync(python, ["-c", script, fixture.oppId], { cwd: BACKEND_DIR, env: { ...process.env, DATABASE_URL: `sqlite:///${E2E_DB}`, MIGRATION_DATABASE_URL: `sqlite:///${E2E_DB}`, PRACTICE_AGENT_ENABLED: "false" } });
  await page.goto(`/?practice_run=${fixture.runId}`);
  const routine = page.getByTestId("practice-routine");
  const opp = routine.getByTestId("practice-opportunity");
  await expect(routine).not.toContainText("Agent WAIT verdict");
  const before = await request.get(`${API}/practice/runs/${fixture.runId}`);
  expect((await before.json()).opportunities[0].agent).toBeNull();
  await routine.getByLabel("Review records").selectOption("wait");
  await expect(routine.getByTestId("practice-opportunity")).toHaveCount(0);
  await routine.getByLabel("Review records").selectOption("all");
  await opp.getByLabel("Rationale").fill("Human fixture committed without agent result");
  await opp.getByRole("button", { name: "Save frozen choice" }).click();
  await expect(opp).toContainText("Human: SKIP");
  await expect(routine).not.toContainText("Agent WAIT verdict");
  await opp.getByRole("button", { name: "Reveal agent choice after both commit" }).click();
  await expect(opp).toContainText("Agent choice: WAIT");
  await expect(opp).toContainText("Agent WAIT verdict withheld until reveal");
  await routine.getByLabel("Review records").selectOption("wait");
  await expect(routine.getByTestId("practice-opportunity")).toContainText("Human: SKIP");
  await expect(routine.getByTestId("practice-opportunity")).toContainText("Agent choice: WAIT");
  await page.reload();
  const reopened = page.getByTestId("practice-routine");
  await expect(reopened).toContainText("Agent choice: WAIT");
  await expect(reopened).toContainText("Human: SKIP");
  await reopened.getByLabel("Review records").selectOption("wait");
  await expect(reopened.getByTestId("practice-opportunity")).toContainText("Agent choice: WAIT");
  await expect(reopened.getByTestId("practice-opportunity")).toContainText("Human: SKIP");
  await expect(reopened.getByRole("button", { name: "Save frozen choice" })).toHaveCount(0);
});

test("attention timing stays with its original run and a failed save preserves the timer", async ({ page, request }) => {
  const day = new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
  const original = seedNoProviderRun(day);
  const other = seedNoProviderRun(day);
  await page.goto(`/?practice_run=${original.runId}`);
  const routine = page.getByTestId("practice-routine");
  await expect(routine.getByTestId("practice-run")).toBeVisible();
  await routine.getByRole("button", { name: "Start morning timing" }).click();
  await routine.getByLabel("Saved run").selectOption(other.runId);
  await expect(routine.getByTestId("practice-opportunity")).toContainText(other.oppId);
  await routine.getByRole("button", { name: "Save morning time" }).click();
  await expect(routine).toContainText("Select the run where this timer began");
  const untouched = await request.get(`${API}/practice/runs/${other.runId}`);
  expect((await untouched.json()).timings).toEqual({});
  await routine.getByLabel("Saved run").selectOption(original.runId);
  await expect(routine.getByTestId("practice-opportunity")).toContainText(original.oppId);
  let attempts = 0;
  await page.route(`**/api/backend/practice/runs/${original.runId}/timing`, async (route) => {
    attempts++;
    if (attempts === 1) await route.fulfill({ status: 503, json: { detail: "Temporary timing write failure" } });
    else await route.continue();
  });
  await routine.getByRole("button", { name: "Save morning time" }).click();
  await expect(routine).toContainText("Temporary timing write failure");
  await expect(routine.getByRole("button", { name: "Save morning time" })).toBeVisible();
  await routine.getByRole("button", { name: "Save morning time" }).click();
  await expect(routine.getByRole("button", { name: "Save morning time" })).toHaveCount(0);
  const recorded = await request.get(`${API}/practice/runs/${original.runId}`);
  expect((await recorded.json()).timings.morning.seconds).toBeGreaterThan(0);
});

test("historical runs do not offer current-facts assisted revisions", async ({ page }) => {
  const today = new Date();
  today.setDate(today.getDate() - 1);
  const day = new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit" }).format(today);
  const old = seedNoProviderRun(day);
  await page.goto(`/daily/${day}?practice_run=${old.runId}`);
  const routine = page.getByTestId("practice-routine");
  await expect(routine.getByTestId("practice-run")).toBeVisible();
  await expect(routine.getByRole("button", { name: "Prepare assisted revision" })).toHaveCount(0);
});
