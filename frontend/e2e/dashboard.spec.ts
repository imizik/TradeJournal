import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";
import type { Trade } from "../lib/api";
import { closedInPeriod, recentCloses, weekStart } from "../lib/dashboardSummary";

const API = `http://127.0.0.1:${Number(process.env.E2E_BACKEND_PORT || 8099)}`;
const backend = path.resolve(__dirname, "../../backend");
const venvPython = path.join(backend, ".venv/bin/python");
const python = existsSync(venvPython) ? venvPython : "python3";

test("summary uses ET calendar dates, Monday weeks, complete P&L and close ordering", () => {
  const trade = (id: string, closed_at: string | null, realized_pnl: number | null, status: Trade["status"] = "closed") => ({ id, closed_at, realized_pnl, status } as Trade);
  expect(weekStart("2026-10-11")).toBe("2026-10-05"); // Sunday
  expect(weekStart("2026-10-12")).toBe("2026-10-12"); // Monday
  expect(weekStart("2026-01-01")).toBe("2025-12-29");
  const rows = [trade("sun", "2026-10-04T23:59:59", 900), trade("mon", "2026-10-05T00:00:00", 100),
    trade("close", "2026-10-11T23:59:59", -50), trade("future", "2026-10-12T00:00:00", 700),
    trade("trim", "2026-10-11T12:00:00", 1000, "open"), trade("expiry", "2026-10-09T16:00:00", -20, "expired")];
  expect(closedInPeriod(rows, weekStart("2026-10-11"), "2026-10-11")).toEqual({ count: 3, pnl: 30 });
  expect(closedInPeriod(rows, "2026-10-11", "2026-10-11")).toEqual({ count: 1, pnl: -50 });
  expect(closedInPeriod([], "2026-10-11", "2026-10-11")).toEqual({ count: 0, pnl: 0 });
  expect(closedInPeriod([trade("missing", "2026-10-11", null)], "2026-10-11", "2026-10-11").pnl).toBeNull();
  expect(closedInPeriod([trade("bad", "2026-10-11", NaN)], "2026-10-11", "2026-10-11").pnl).toBeNull();
  expect(recentCloses([...rows, trade("no-date", null, null)]).map((t) => t.id)).toEqual(["future", "close", "expiry", "mon", "sun"]);
  expect(rows[0].id).toBe("sun"); // Never reorder the shared source array.
});

test("owner foundation has compact hierarchy, reachable details and phone layout", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.setViewportSize({ width: 1440, height: 1100 });
  await page.goto("/");
  const owner = page.getByTestId("owner-dashboard");
  const summary = page.getByLabel("Journal summary", { exact: true });
  await expect(summary).toContainText("+$830.00"); // AAPL +$650, RNXT FIFO +$180
  await expect(summary).toContainText("2 options · 1 stock");
  await expect(page.getByRole("region", { name: "Active Options" })).toContainText("2 of 2 quoted");
  await expect(page.getByTestId("stock-holdings")).not.toHaveAttribute("open");
  const performance = page.getByRole("region", { name: "Trading Performance" });
  await expect(performance.getByText("+$1,019.00", { exact: true })).toBeVisible();
  await expect(performance.getByText("4.40", { exact: true })).toBeVisible();
  await expect(page.getByRole("region", { name: "Recent Closed Trades" }).locator("tbody tr")).toHaveCount(3);
  await expect(page.getByLabel("Import freshness", { exact: true })).toContainText("Position quote timestamps unavailable");
  await expect(owner).not.toContainText("Account Equity");
  const bounds = await Promise.all([summary.boundingBox(), page.getByRole("region", { name: "Today's Session" }).boundingBox(), performance.boundingBox()]);
  expect(bounds[0]!.y + bounds[0]!.height).toBeLessThan(bounds[1]!.y);
  expect(bounds[1]!.y).toBeLessThan(bounds[2]!.y);
  await page.screenshot({ path: test.info().outputPath("dashboard-foundation-desktop.png"), animations: "disabled" });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  await page.screenshot({ path: test.info().outputPath("dashboard-foundation-phone.png"), animations: "disabled" });
  await page.getByTestId("stock-holdings").locator("summary").click();
  await expect(page.getByTestId("stock-holdings").getByRole("link", { name: "RNXT" })).toBeVisible();
  await page.getByTestId("stock-holdings").screenshot({ path: test.info().outputPath("dashboard-holdings-phone.png"), animations: "disabled" });
  await page.getByText("Exposure & full position details", { exact: true }).click();
  await expect(page.getByText("Gross Marked Value", { exact: true })).toBeVisible();
  await performance.getByText("More performance metrics", { exact: true }).click();
  await expect(performance.getByText("Avg Hold", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: "Open practice workspace" }).click();
  await expect(page.getByRole("button", { name: "Prepare today", exact: true })).toBeInViewport();
  const trades = await (await page.request.get("/api/backend/trades")).json() as Trade[];
  const rnxt = trades.find((trade) => trade.ticker === "RNXT")!;
  await page.goto(`/daily/${rnxt.opened_at.slice(0, 10)}`);
  const rnxtRow = page.getByRole("row").filter({ has: page.getByRole("link", { name: "RNXT", exact: true }) });
  await expect(rnxtRow.getByText("+$180.00", { exact: true })).toBeVisible();
  expect(errors).toEqual([]);
});

test("import freshness discloses initial failure, retained history and recovery on one shared poll", async ({ page }) => {
  let unavailable = true;
  let requests = 0;
  await page.route("**/api/backend/gmail/health", async (route) => {
    requests++;
    if (unavailable) await route.fulfill({ status: 503, json: { detail: "Fixture health unavailable" } });
    else await route.fulfill({ json: { status: "live", message: "Fixture listener healthy", action: null, listener_enabled: true,
      last_import_at: "2026-10-09T14:32:00Z", last_notification_at: null, watch_expires_at: null, data_version: "fixture" } });
  });
  await page.goto("/");
  const panel = page.getByLabel("Import freshness", { exact: true });
  await expect(panel).toContainText("Import status could not load.");
  await expect(panel).toContainText("Gmail: status unavailable");
  expect(requests).toBe(1); // Nav, banner and Dashboard subscribe to one poll.
  await panel.screenshot({ path: test.info().outputPath("dashboard-import-unavailable-desktop.png") });
  unavailable = false;
  await page.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));
  await expect(panel).toContainText("Gmail: live");
  await expect(panel.getByRole("time")).toHaveAttribute("datetime", "2026-10-09T14:32:00Z");
  unavailable = true;
  await page.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));
  await expect(panel).toContainText("Showing historical import data; last status check");
  await expect(panel).toContainText("Gmail: status unavailable");
  await page.setViewportSize({ width: 390, height: 844 });
  await panel.screenshot({ path: test.info().outputPath("dashboard-import-historical-phone.png") });
  unavailable = false;
  await page.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));
  await expect(panel).toContainText("Gmail: live");
  await expect(panel).not.toContainText("Showing historical");
  expect(requests).toBe(4);
});

test("filters retain scope, drill-down links work and history shows five latest closes", async ({ page, request }) => {
  const ids = execFileSync(python, ["-c", `
import json,uuid
from datetime import datetime,timedelta
from sqlmodel import Session,select
from app.database import engine
from app.models import Trade
assert engine.url.database.endswith('/data/e2e_seed.db')
ids=[]
with Session(engine) as db:
    source=db.exec(select(Trade).where(Trade.status=='closed')).first()
    for ticker,opened,closed in [('EARLY',70,0),('LATER',4,1),('NEWER',3,2)]:
        data=source.model_dump()
        data.update(id=uuid.uuid4(),ticker=ticker,opened_at=datetime.now()-timedelta(days=opened),closed_at=datetime.now()-timedelta(days=closed),realized_pnl=10,ai_review=None)
        row=Trade(**data);db.add(row);ids.append(str(row.id))
    db.commit()
print(json.dumps(ids))
`], { cwd: backend, env: { ...process.env, DATABASE_URL: `sqlite:///${backend}/data/e2e_seed.db` }, encoding: "utf8" }).trim();
  try {
    await page.goto("/");
    const recent = page.getByRole("region", { name: "Recent Closed Trades" });
    await expect(recent.locator("tbody tr")).toHaveCount(5);
    await expect(recent.locator("tbody tr").first()).toContainText("EARLY");
    await recent.getByRole("link", { name: "EARLY", exact: true }).click();
    await expect(page).toHaveURL(/\/trades\/[0-9a-f-]+$/);
    await expect(page.getByText("Trade Summary", { exact: true })).toBeVisible();
    const decision = "00000000-0000-0000-0000-000000000001";
    const run = "00000000-0000-0000-0000-000000000002";
    await page.goto(`/?account=roth_ira&decision=${decision}&practice_run=${run}`);
    const filters = page.getByLabel("Dashboard filters", { exact: true });
    await expect(filters.getByRole("link", { name: "Options", exact: true })).toHaveAttribute("href", `/?account=roth_ira&type=option&decision=${decision}&practice_run=${run}`);
    await filters.getByRole("link", { name: "Options", exact: true }).click();
    await expect(page.getByRole("region", { name: "Active Options" })).toContainText("1 positions");
    await expect(recent.getByRole("link", { name: "All trades" })).toHaveAttribute("href", "/trades?account=roth_ira&type=option");
    await recent.getByRole("link", { name: "All trades" }).click();
    await expect(page).toHaveURL(/\/trades\?account=roth_ira&type=option$/);
    await page.goBack();
    await expect(filters.getByRole("link", { name: "Options", exact: true })).toHaveAttribute("aria-current", "true");
    const analytics = page.getByRole("link", { name: "Explore detailed Analytics" });
    const accounts = await (await request.get(`${API}/accounts`)).json();
    await expect(analytics).toHaveAttribute("href", `/analytics?account_id=${accounts.find((a: { type: string }) => a.type === "roth_ira").id}&instrument_type=option`);
    await analytics.click();
    await expect(page.getByRole("heading", { name: "Analytics", exact: true })).toBeVisible();
    await expect(page.getByRole("combobox", { name: "Instrument", exact: true })).toHaveValue("option");
  } finally {
    execFileSync(python, ["-c", `
import json,sys,uuid
from sqlmodel import Session
from app.database import engine
from app.models import Trade
with Session(engine) as db:
    for id in json.loads(sys.argv[1]):
        row=db.get(Trade,uuid.UUID(id))
        if row: db.delete(row)
    db.commit()
`, ids], { cwd: backend, env: { ...process.env, DATABASE_URL: `sqlite:///${backend}/data/e2e_seed.db` } });
  }
});

test("empty, missing quote, quote error and journal retry states are explicit", async ({ page, request }) => {
  async function state(value: string) {
    expect((await request.post(`${API}/__test/dashboard-state?value=${value}`)).ok()).toBe(true);
  }
  try {
    await page.goto("/?account=no-such-account");
    await expect(page.getByRole("region", { name: "Active Options" })).toContainText("No open options");
    await expect(page.getByText("No closed trades in this period.", { exact: true })).toBeVisible();
    await page.screenshot({ path: test.info().outputPath("dashboard-empty-desktop.png"), animations: "disabled" });
    await state("quotes_unavailable");
    await page.goto("/");
    await expect(page.getByLabel("Journal summary", { exact: true })).toContainText("0 of 3 positions quoted");
    await expect(page.getByRole("region", { name: "Active Options" }).getByRole("cell", { name: "—", exact: true })).toHaveCount(4);
    await page.screenshot({ path: test.info().outputPath("dashboard-missing-quotes-desktop.png"), animations: "disabled" });
    await state("quotes_error");
    await page.reload();
    await expect(page.getByRole("alert").filter({ hasText: "Some position quotes could not load" })).toBeVisible();
    await expect(page.getByLabel("Journal summary", { exact: true })).toContainText("0 of 3 positions quoted");
    await state("journal_error");
    await page.reload();
    await expect(page.getByRole("heading", { name: "Workspace could not load" })).toBeVisible();
    await page.screenshot({ path: test.info().outputPath("dashboard-error-desktop.png"), animations: "disabled" });
    await state("ready");
    await page.getByRole("button", { name: "Try again" }).click();
    await expect(page.getByTestId("owner-dashboard")).toBeVisible();
    await state("slow");
    await page.goto("/?type=option", { waitUntil: "commit" });
    await expect(page.getByRole("status", { name: "Loading workspace" })).toBeVisible();
    await page.screenshot({ path: test.info().outputPath("dashboard-loading-desktop.png"), animations: "disabled" });
    await expect(page.getByTestId("owner-dashboard")).toBeVisible();
  } finally { await state("ready"); }
});

test("journal retry makes a fresh page GET and preserves scoped deep links", async ({ page, request }) => {
  await page.setViewportSize({ width: 1440, height: 1100 });
  const params = new URLSearchParams({ account: "all", type: "option", decision: "00000000-0000-0000-0000-000000000001", practice_run: "00000000-0000-0000-0000-000000000002" });
  try {
    expect((await request.post(`${API}/__test/dashboard-state?value=journal_error`)).ok()).toBe(true);
    await page.goto(`/?${params}`);
    await expect(page.getByRole("heading", { name: "Workspace could not load" })).toBeVisible();
    await page.screenshot({ path: test.info().outputPath("dashboard-native-retry-error-desktop.png") });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({ path: test.info().outputPath("dashboard-native-retry-error-phone.png") });
    expect((await request.post(`${API}/__test/dashboard-state?value=ready`)).ok()).toBe(true);
    const navigation = page.waitForResponse((response) => response.request().isNavigationRequest() && new URL(response.url()).pathname === "/", { timeout: 10_000 });
    await page.getByRole("button", { name: "Try again" }).click();
    expect((await navigation).request().method()).toBe("GET");
    await expect(page.getByTestId("owner-dashboard")).toBeVisible();
    expect(Object.fromEntries(new URL(page.url()).searchParams)).toEqual(Object.fromEntries(params));
    await expect(page.getByLabel("Journal summary", { exact: true })).toContainText("2 options · 0 stocks");
    await page.screenshot({ path: test.info().outputPath("dashboard-native-retry-recovered-phone.png") });
  } finally {
    await request.post(`${API}/__test/dashboard-state?value=ready`);
  }
});
