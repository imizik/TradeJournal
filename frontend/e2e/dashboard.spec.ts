import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";
import type { RadarFeed } from "../lib/radar";
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
  const details = page.getByTestId("journal-details");
  await expect(details).not.toHaveAttribute("open");
  await expect(summary).not.toBeVisible();
  await expect(page.getByRole("region", { name: "Active Options" })).toBeVisible();
  await details.locator(":scope > summary").click();
  await expect(summary).toBeVisible();
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
  const market = await page.getByLabel("Market and discovery", { exact: true }).boundingBox();
  const attention = await page.getByRole("region", { name: "Attention", exact: true }).boundingBox();
  const options = await page.getByRole("region", { name: "Active Options", exact: true }).boundingBox();
  expect(market!.y).toBeLessThan(options!.y);
  expect(attention!.y).toBeLessThan(options!.y);
  expect(options!.y + options!.height).toBeLessThan(bounds[0]!.y);
  await details.screenshot({ path: test.info().outputPath("dashboard-journal-expanded-desktop.png") });
  await details.locator(":scope > summary").click();
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: test.info().outputPath("dashboard-foundation-desktop.png"), animations: "disabled" });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  await page.screenshot({ path: test.info().outputPath("dashboard-foundation-phone.png"), animations: "disabled" });
  await details.locator(":scope > summary").click();
  await expect(summary).toBeVisible();
  await page.getByTestId("stock-holdings").locator("summary").click();
  await expect(page.getByTestId("stock-holdings").getByRole("link", { name: "RNXT" })).toBeVisible();
  await page.getByTestId("stock-holdings").screenshot({ path: test.info().outputPath("dashboard-holdings-phone.png"), animations: "disabled" });
  await page.getByText("Exposure & full position details", { exact: true }).click();
  await expect(page.getByText("Gross Marked Value", { exact: true })).toBeVisible();
  await performance.getByText("More performance metrics", { exact: true }).click();
  await expect(performance.getByText("Avg Hold", { exact: true })).toBeVisible();
  await expect(page.getByTestId("practice-routine")).toHaveCount(0);
  await expect(page.getByTestId("practice-decisions")).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Daily Practice", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: /^Open menu/ }).click();
  await page.getByRole("link", { name: "Daily Practice", exact: true }).filter({ visible: true }).click();
  await expect(page).toHaveURL(/\/practice$/);
  await expect(page.getByTestId("practice-decisions")).toBeVisible();
  await expect(page.getByRole("button", { name: "Prepare today", exact: true })).toBeInViewport();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  await page.screenshot({ path: test.info().outputPath("practice-workspace-phone.png"), animations: "disabled" });
  await page.setViewportSize({ width: 1440, height: 1100 });
  await page.screenshot({ path: test.info().outputPath("practice-workspace-desktop.png"), animations: "disabled" });
  await expect(page.getByRole("button", { name: "Prepare today", exact: true })).toBeInViewport();
  const trades = await (await page.request.get("/api/backend/trades")).json() as Trade[];
  const rnxt = trades.find((trade) => trade.ticker === "RNXT")!;
  await page.goto(`/daily/${rnxt.opened_at.slice(0, 10)}`);
  const rnxtRow = page.getByRole("row").filter({ has: page.getByRole("link", { name: "RNXT", exact: true }) });
  await expect(rnxtRow.getByText("+$180.00", { exact: true })).toBeVisible();
  expect(errors).toEqual([]);
});

test("exit habits card shows each alert's follow-up and the four habits against baseline", async ({ page, request }) => {
  expect((await request.post(`${API}/__test/exit-habits-seed`)).ok()).toBe(true);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.setViewportSize({ width: 1440, height: 1100 });
  await page.goto("/");
  const card = page.getByTestId("exit-habits");
  // Every seeded trade closed long before the alerts went live: nothing to compare yet, and no trend language.
  await expect(card).toContainText("0 since phone alerts went live on Oct 21, against 2 before");
  await expect(card).toContainText("Too few trades yet to read a change");
  await expect(card).not.toContainText(/improv|grade|score/i);
  const expired = card.getByTestId("habit-expired_worthless");
  await expect(expired).toContainText("Since Oct 21 (0 of 30 so far)");
  await expect(expired).toContainText("no trades");
  await expect(expired).toContainText("1 of 2 · 50% · -$300");
  await expect(card.getByTestId("habit-green_to_red")).toContainText("2 trades, no data"); // no path metrics in the seed
  const alerts = card.getByTestId("exit-habits-alert");
  await expect(alerts).toHaveCount(3);
  const nvda = alerts.filter({ hasText: "NVDA" });
  await expect(nvda).toContainText("Gave back its gain");
  await expect(nvda).toContainText("Closed within 15 min");
  await expect(nvda).toContainText("You came out $250 better than closing at the alert."); // 5 sold at $700 vs a $650 mark
  const tsla = alerts.filter({ hasText: "TSLA" });
  await expect(tsla).toContainText("Held an hour");
  await expect(tsla).toContainText("Let it expire");
  await expect(tsla).toContainText("Closing at the alert would have been $240 better.");
  const aapl = alerts.filter({ hasText: "AAPL" });
  await expect(aapl).toContainText("Trimmed within 15 min");
  await expect(aapl).toContainText("Still open, so there is no result yet.");
  const link = nvda.getByRole("link");
  await expect(link).toHaveAttribute("href", /^\/trades\/[0-9a-f-]{36}\?alert=[0-9a-f-]{36}$/); // the alert itself, not just its trade
  await card.screenshot({ path: test.info().outputPath("dashboard-exit-habits-desktop.png") });
  await page.screenshot({ path: test.info().outputPath("dashboard-exit-habits-page-desktop.png"), fullPage: true });
  await page.setViewportSize({ width: 375, height: 812 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  await card.scrollIntoViewIfNeeded();
  await card.screenshot({ path: test.info().outputPath("dashboard-exit-habits-phone.png") });
  await link.click();
  await expect(page).toHaveURL(/\/trades\/[0-9a-f-]{36}\?alert=[0-9a-f-]{36}$/);
  await expect(page.getByTestId("selected-position-alert")).toContainText("Give-back triggered");
  expect(errors).toEqual([]);
});

test("dashboard Radar preview reads a bounded dated feed without changing visits or feedback", async ({ page, request }) => {
  expect((await request.post(`${API}/__test/radar-seed`)).ok()).toBe(true);
  const base = await (await request.get(`${API}/radar/feed`)).json();
  expect(base.events.length).toBeGreaterThan(0);
  let view: RadarFeed = { ...base, state: "recording", events: Array.from({ length: 4 }, (_, i) => ({ ...base.events[0], event_id: `preview-${i}`, summary: `Saved discovery ${i}`, news: i === 0 ? {
    status: "found", checked_at: "2026-10-20T15:15:00Z", headlines: [
      { headline: "Invented memory demand headline", source: "Fixture Wire", published_at: "2026-10-20T15:00:00Z", url: "https://example.com/before", symbols: ["MU"], timing: "before" },
      { headline: "Invented later follow-up", source: "Fixture Wire", published_at: "2026-10-20T15:14:00Z", url: "https://example.com/after", symbols: ["MU"], timing: "after" },
    ],
  } : i === 1 ? { status: "none_found", checked_at: "2026-10-20T15:15:00Z", headlines: [] } : null })) };
  let fail = false;
  const writes: string[] = [];
  page.on("request", (req) => { if (req.url().includes("/radar/") && req.method() !== "GET") writes.push(req.url()); });
  await page.route("**/api/backend/radar/feed*", (route) => route.fulfill(fail ? { status: 503, json: {} } : { json: view }));
  await page.setViewportSize({ width: 1440, height: 1100 });
  await page.goto("/?account=roth_ira&type=option");
  const preview = page.getByTestId("radar-preview");
  await expect(preview).toContainText(`${base.session} ET`);
  await expect(preview.locator("li")).toHaveCount(3);
  await expect(preview.getByRole("link").first()).toHaveAttribute("href", `/charts?symbol=${base.events[0].chart.symbol}`);
  await expect(preview).toContainText("News nearby: Invented memory demand headline");
  await expect(preview).toContainText("No news found — cause unknown");
  await expect(preview).toContainText("News not checked yet");
  const context = preview.getByTestId("radar-preview-context").first();
  await context.locator("summary").click();
  await expect(context).toContainText("not a confirmed cause");
  await expect(context).toContainText("Invented later follow-up");
  await expect(context).toContainText("before the move");
  await expect(context).toContainText("after the move");
  await expect(context.locator("time")).toHaveAttribute("datetime", "2026-10-20T15:15:00Z");
  await expect(context.getByRole("link", { name: "Inspect saved evidence in Radar" })).toHaveAttribute("href", "/radar");
  await preview.screenshot({ path: test.info().outputPath("dashboard-radar-recorded-desktop.png") });
  view = { ...view, state: "stale" };
  await preview.getByRole("button", { name: "Refresh Radar" }).click();
  await expect(preview).toContainText("Stale since");
  await page.setViewportSize({ width: 390, height: 844 });
  await preview.screenshot({ path: test.info().outputPath("dashboard-radar-stale-phone.png") });
  fail = true;
  await preview.getByRole("button", { name: "Refresh Radar" }).click();
  await expect(preview).toContainText("Showing the previous snapshot; current status is unknown");
  fail = false;
  view = { ...view, events: view.events.map((event) => ({ ...event, news: { status: "unavailable", checked_at: "2026-10-20T15:20:00Z", headlines: [] } })) };
  await preview.getByRole("button", { name: "Refresh Radar" }).click();
  await expect(preview).toContainText("News unavailable — cause unknown");
  await expect(preview).not.toContainText("Invented memory demand headline");
  expect(await preview.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);
  view = { ...view, state: "no_data", events: [], coverage: null };
  await preview.getByRole("button", { name: "Refresh Radar" }).click();
  await expect(preview).toContainText("No recorded session yet");
  await expect(preview).toContainText("This does not mean nothing moved");
  view = { ...view, state: "off", reason: "Recording is not enabled." };
  await preview.getByRole("button", { name: "Refresh Radar" }).click();
  await expect(preview).toContainText("Radar is off. Recording is not enabled.");
  await expect(preview.locator("li")).toHaveCount(0);
  await expect(page.getByLabel("Dashboard filters", { exact: true }).getByRole("link", { name: "Options", exact: true })).toHaveAttribute("aria-current", "true");
  expect(writes).toEqual([]);
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
    await page.getByTestId("journal-details").locator(":scope > summary").click();
    const recent = page.getByRole("region", { name: "Recent Closed Trades" });
    await expect(recent.locator("tbody tr")).toHaveCount(5);
    await expect(recent.locator("tbody tr").first()).toContainText("EARLY");
    await recent.getByRole("link", { name: "EARLY", exact: true }).click();
    await expect(page).toHaveURL(/\/trades\/[0-9a-f-]+$/);
    await expect(page.getByText("Trade Summary", { exact: true })).toBeVisible();
    await page.goto("/?account=roth_ira");
    const filters = page.getByLabel("Dashboard filters", { exact: true });
    await expect(filters.getByRole("link", { name: "Options", exact: true })).toHaveAttribute("href", "/?account=roth_ira&type=option");
    await filters.getByRole("link", { name: "Options", exact: true }).click();
    await expect(page.getByRole("region", { name: "Active Options" })).toContainText("1 positions");
    await page.getByTestId("journal-details").locator(":scope > summary").click();
    await expect(recent.getByRole("link", { name: "All trades" })).toHaveAttribute("href", "/trades?account=roth_ira&type=option");
    await recent.getByRole("link", { name: "All trades" }).click();
    await expect(page).toHaveURL(/\/trades\?account=roth_ira&type=option$/);
    await page.goBack();
    await expect(filters.getByRole("link", { name: "Options", exact: true })).toHaveAttribute("aria-current", "true");
    const restoredDetails = page.getByTestId("journal-details");
    if (!(await restoredDetails.evaluate((el) => (el as HTMLDetailsElement).open))) await restoredDetails.locator(":scope > summary").click();
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
    await page.getByTestId("journal-details").locator(":scope > summary").click();
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
    await expect(page.locator('[aria-label="Market and discovery"]')).toBeVisible();
    await expect(page.getByTestId("radar-preview")).toBeVisible();
    await page.screenshot({ path: test.info().outputPath("dashboard-loading-desktop.png"), animations: "disabled" });
    await expect(page.getByTestId("owner-dashboard")).toBeVisible();
  } finally { await state("ready"); }
});

test("attention does not wait for journal statistics, and a slow page answers the click at once", async ({ page, request }) => {
  const state = async (value: string) => expect((await request.post(`${API}/__test/dashboard-state?value=${value}`)).ok()).toBe(true);
  try {
    await state("slow_stats");
    await page.goto("/", { waitUntil: "commit" });
    await expect(page.getByRole("complementary", { name: "Attention and data status" }).getByLabel(/^\d+ items?$/)).toBeVisible();
    await expect(page.getByRole("status", { name: "Loading workspace" })).toBeVisible(); // the journal still waits for statistics
    await expect(page.getByRole("status", { name: "Loading workspace" })).toHaveCount(0);
    await state("slow");
    await page.getByRole("link", { name: "Trades", exact: true }).click();
    await expect(page.getByTestId("nav-pending")).toBeVisible(); // before the slow journal answers
    await page.screenshot({ path: test.info().outputPath("nav-pending-desktop.png"), clip: { x: 0, y: 0, width: 300, height: 420 } });
    await expect(page.getByRole("heading", { name: "Trades", exact: true })).toBeVisible();
    await expect(page.getByTestId("nav-pending")).toHaveCount(0);
  } finally { await state("ready"); }
});

test("journal retry makes a fresh page GET and preserves scope", async ({ page, request }) => {
  await page.setViewportSize({ width: 1440, height: 1100 });
  const params = new URLSearchParams({ account: "all", type: "option" });
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

test("legacy dashboard record links forward both saved references to Practice", async ({ page }) => {
  const params = new URLSearchParams({ decision: "00000000-0000-0000-0000-000000000001", practice_run: "00000000-0000-0000-0000-000000000002" });
  await page.goto(`/?${params}#saved-decisions`);
  await expect(page).toHaveURL(`/practice?${params}#saved-decisions`);
  await expect(page.getByTestId("practice-decisions")).toBeVisible();
});
