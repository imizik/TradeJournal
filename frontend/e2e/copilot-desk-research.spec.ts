import { expect, test, type Page } from "@playwright/test";

const ON = {
  enabled: true, backend: "fake", evidence: "live", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
const NOW = new Date("2026-11-13T16:00:00Z");
const epoch = (iso: string) => Date.parse(iso) / 1000;
const JOB = {
  job_type: "fill_import_check", label: "Import/manual fills check", description: "Checks imported fills against manual ones.", advanced: false,
  status: "succeeded", running: false, done: 0, total: 0, items_processed: 12, errors_count: 0, message: null, error_summary: null, phase: null,
  wait_provider: null, wait_reason: null, wait_until: null, progress_unit: "fill", job_id: null, created_at: null, started_at: null,
  finished_at: "2026-11-13T15:40:00Z", updated_at: null, last_run_at: "2026-11-13T15:40:00Z",
};
const READS: Record<string, unknown> = {
  "/copilot/desk/threads": { as_of: "2026-11-13T16:00:00Z", quotes_at: null, quote_issue: null, day: { phase: "regular", need_you: 0, streak: null },
    sections: { positions: "ok" }, plans: [], robinhood: { state: "off" }, threads: [] },
  "/copilot/desk/session": { as_of: "2026-11-13T16:00:00Z", now: epoch("2026-11-13T16:00:00Z"), day: "2026-11-13", phase: "regular",
    open: epoch("2026-11-13T14:30:00Z"), close: epoch("2026-11-13T21:00:00Z"), events: [], time_stops: [], pings: null, prep: null,
    indices: [], quote_issue: null, realized_today: 0, sections: {} },
  "/copilot/desk/watching": { state: "ok", symbols: [], count: 0, max: 30, imported_at: null, robinhood: "off", levels: {}, setups: {} },
  "/copilot/desk/sparks": { as_of: "2026-11-13T16:00:00Z", spy_change_pct: 0.4, rows: {} },
  "/copilot/desk/feed": { as_of: "2026-11-13T16:00:00Z", now: epoch("2026-11-13T16:00:00Z"), day: "2026-11-13", total: 0, sources: {}, unavailable: [], items: [] },
  "/copilot/investigations": { investigations: [] },
  "/copilot/tickets": { plans: [] },
  "/copilot/exposure": { line: null },
  "/copilot/desk/health": { as_of: "2026-11-13T16:00:00Z", now: epoch("2026-11-13T16:00:00Z"), phase: "regular", overall: "ok",
    sources: [{ id: "gmail", name: "Fill emails", state: "live", line: "Live · last email 10:19", last_at: epoch("2026-11-13T15:19:00Z"), affects: "Fills.", fix: null }] },
  "/sync/summary": { running: false, active_job: null, last_success_at: "2026-11-13T15:40:00Z", errors_count: 0 },
  "/sync/jobs": [JOB],
  "/sync/runs": [],
};

async function open(page: Page, width = 1440, query = "?symbol=NBIS") {
  const symbolReads: string[] = [];
  await page.setViewportSize({ width, height: width < 768 ? 812 : 900 });
  await page.clock.install({ time: NOW });
  page.on("request", request => { const path = new URL(request.url()).pathname; if (path.includes("/charts/symbol/")) symbolReads.push(path.replace(/^\/api\/backend/, "")); });
  await page.route("**/api/backend/**", route => route.fulfill({ status: 404, json: { detail: "Not in this test." } }));
  await page.route("**/copilot/status", route => route.fulfill({ json: ON }));
  for (const [path, body] of Object.entries(READS)) await page.route(url => url.pathname.endsWith(path), route => route.fulfill({ json: body }));
  await page.route("**/copilot/desk/minute?*", route => {
    const reads = new URL(route.request().url()).searchParams.getAll("read").map(target => {
      const body = READS[target.split("?")[0]];
      return body ? { status: 200, body } : { status: 404, body: { detail: "Not in this test." } };
    });
    return route.fulfill({ json: { reads } });
  });
  await page.goto(`/copilot-lab${query}`);
  await expect(page.getByTestId(width < 768 ? "desk-view-ticker" : "desk-book")).toBeVisible();
  return symbolReads;
}


// The desk's Research drawer (docs/copilot-lab.md § The desk): the chart ticker's symbol research from Charts (the same
// SymbolInfo tabs and reads), closed by default with no research read, opened from the chart's More or ⌘K's "Research
// NBIS", closed by Escape, a full-width sheet on a phone. The research routes are stubbed to fail, so what is checked is
// the drawer and its honest error line, never a number.
const tabs = ["Overview", "News", "Events", "Forecast", "Financials", "Short", "You"];

test("Research is closed with no reads, opens from More with the tabs in order, loads only when opened, and Escape closes it", async ({ page }) => {
  const reads = await open(page);
  await page.route("**/api/backend/charts/symbol/**", route => route.fulfill({ status: 503, json: { detail: "No research in this test." } }));
  await expect(page.getByTestId("desk-research")).toHaveCount(0);
  expect(reads).toEqual([]);

  await page.getByTestId("desk-chart-more").click();
  await page.getByTestId("desk-research-open").click();
  const drawer = page.getByRole("dialog", { name: "NBIS research" });
  await expect(drawer).toBeVisible();
  await expect(drawer.getByRole("tab")).toHaveText(tabs);
  await drawer.getByRole("tab", { name: "Events" }).click();
  await expect(drawer.getByRole("alert")).toContainText("Events unavailable"); // an error says so; it never shows a zero
  expect(reads.every(path => path.includes("/charts/symbol/NBIS/"))).toBe(true);
  expect(reads.length).toBeGreaterThan(0);

  await page.keyboard.press("Escape");
  await expect(page.getByTestId("desk-research")).toHaveCount(0);
});

test("⌘K lists Research for the chart's ticker and opens its drawer", async ({ page }) => {
  await open(page);
  await page.route("**/api/backend/charts/symbol/**", route => route.fulfill({ status: 503, json: { detail: "No research in this test." } }));
  await page.keyboard.press("Control+k");
  await page.getByRole("combobox").fill("research");
  await page.getByRole("option", { name: /Research NBIS/ }).click();
  await expect(page.getByRole("dialog", { name: "NBIS research" })).toBeVisible();
});

test("On a phone Research is a full-width, full-height sheet", async ({ page }) => {
  await open(page, 390, ""); // no ticker in the address: the desk opens on its own chart
  await page.getByTestId("desk-view-ticker").click();
  await page.route("**/api/backend/charts/symbol/**", route => route.fulfill({ status: 503, json: { detail: "No research in this test." } }));
  await page.getByTestId("desk-chart-more").click();
  await page.getByTestId("desk-research-open").click();
  const box = await page.getByRole("dialog", { name: "QQQ research" }).boundingBox();
  const view = page.viewportSize()!;
  expect(box!.width).toBeGreaterThanOrEqual(view.width - 1);
  expect(box!.height).toBeGreaterThanOrEqual(view.height - 1);
});
