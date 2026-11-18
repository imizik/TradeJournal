import { expect, test, type Page } from "@playwright/test";

// The old pages' pieces on the desk (docs/copilot-lab.md § Keys and the palette): the Dashboard's Data Sync Center opens
// from Data health's "Data sync" and from ⌘K, with Rebuild All and Resync All still asking first; ⌘K reaches the
// Scanner's history and the Radar log; and while the desk is home the menu no longer lists Radar or Scanner (their
// addresses open the desk's Feed). Every route is stubbed; every number is invented.
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

async function open(page: Page, width = 1440) {
  const posted: string[] = [];
  await page.setViewportSize({ width, height: width < 768 ? 812 : 900 });
  await page.clock.install({ time: NOW });
  page.on("request", request => { if (request.method() === "POST") posted.push(new URL(request.url()).pathname.replace(/^\/api\/backend/, "")); });
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
  await page.goto("/copilot-lab");
  await expect(page.getByTestId("desk-book")).toBeVisible();
  return posted;
}

test("Data health's Data sync opens the Sync Center; Resync All still asks first and a No sends nothing", async ({ page }) => {
  const posted = await open(page);
  await expect(page.getByRole("heading", { name: "Data Sync Center" })).toHaveCount(0); // no hidden drawer on the desk
  await page.getByTestId("desk-status-line").click();
  await page.getByTestId("desk-health-sync").click();
  const center = page.getByRole("complementary").filter({ has: page.getByRole("heading", { name: "Data Sync Center" }) });
  await expect(center).toBeVisible();
  await expect(center.getByText("Import/manual fills check")).toBeVisible();
  await expect(page.getByTestId("desk-health-list")).toHaveCount(0); // the list steps aside for the drawer

  // Resync All deletes fills: its confirmation is the Dashboard's own, and declining it posts nothing.
  await center.getByRole("button", { name: "Advanced" }).click();
  const asked: string[] = [];
  page.on("dialog", dialog => { asked.push(dialog.message()); void dialog.dismiss(); });
  await center.getByRole("button", { name: "Run Resync All" }).click();
  await expect.poll(() => asked).toEqual([expect.stringContaining("Resync All will delete imported fills")]);
  expect(posted.filter(path => path.startsWith("/sync"))).toEqual([]);

  await center.getByRole("button", { name: "Close Sync Center" }).click();
  await expect(page.getByRole("heading", { name: "Data Sync Center" })).toHaveCount(0);
});

test("⌘K: Data sync opens the Sync Center; Scanner history and Radar log are one command away", async ({ page }) => {
  await open(page);
  const palette = page.getByRole("dialog", { name: "Jump to" });
  await page.keyboard.press("ControlOrMeta+k");
  await palette.getByRole("combobox").fill("data sync");
  await expect(palette.getByRole("option").first()).toContainText("Data sync");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "Data Sync Center" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Close Sync Center" })).toBeFocused();
  // ⌘K over the drawer: Escape closes the palette first, then the drawer.
  await page.keyboard.press("ControlOrMeta+k");
  await expect(palette).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(palette).toBeHidden();
  await expect(page.getByRole("heading", { name: "Data Sync Center" })).toBeVisible();
  await page.keyboard.press("Escape"); // closes the drawer, not a desk panel under it
  await expect(page.getByRole("heading", { name: "Data Sync Center" })).toHaveCount(0);

  await page.keyboard.press("ControlOrMeta+k");
  await palette.getByRole("combobox").fill("scanner history");
  await expect(palette.getByRole("option").first()).toContainText("Scanner history");
  await page.keyboard.press("ControlOrMeta+k"); // closes it again
  await page.keyboard.press("ControlOrMeta+k");
  await palette.getByRole("combobox").fill("radar log");
  await expect(palette.getByRole("option").first()).toContainText("Radar log");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/radar\?log=1$/);
});

test("while the desk is home the menu drops Radar, Scanner and Daily Practice; Signals and Advisor review stay", async ({ page }) => {
  await open(page);
  await page.getByRole("button", { name: /open menu|menu/i }).first().click();
  const market = page.getByRole("button", { name: "Market", exact: true });
  if ((await market.getAttribute("aria-expanded")) !== "true") await market.click();
  await expect(page.getByRole("link", { name: "Signals", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Radar", exact: true })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Scanner", exact: true })).toHaveCount(0);
  const practice = page.getByRole("button", { name: "Practice", exact: true });
  if ((await practice.getAttribute("aria-expanded")) !== "true") await practice.click();
  await expect(page.getByRole("link", { name: "Advisor review", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Daily Practice", exact: true })).toHaveCount(0);
});

// The Dashboard's closed P&L, performance and latest closes: a desk drawer from More → Journal and ⌘K, invented numbers.
const TRADE = (id: string, closed_at: string, pnl: number) => ({ id, account_id: "a1", ticker: "XYZ", instrument_type: "stock", option_type: null, strike: null,
  expiration: null, contracts: 10, avg_entry_premium: 10, avg_exit_premium: 11, total_premium_paid: 100, realized_pnl: pnl, pnl_pct: pnl, hold_duration_mins: 30,
  entry_time_bucket: null, expired_worthless: false, opened_at: closed_at, closed_at, status: "closed", ai_review: null });

async function stubJournal(page: Page) {
  await page.route(url => url.pathname.endsWith("/trades"), route => route.fulfill({ json: [TRADE("t1", "2026-11-13T10:00:00", 120), TRADE("t2", "2026-11-12T10:00:00", -45)] }));
  await page.route(url => url.pathname.endsWith("/accounts"), route => route.fulfill({ json: [{ id: "a1", name: "Invented", type: "roth" }] }));
  await page.route(url => url.pathname.endsWith("/stats"), route => route.fulfill({ json: { total_pnl: 75, closed_trades: 2 } }));
}

test("⌘K: Journal summary opens closed P&L and the latest closes on the desk; Escape closes it", async ({ page }) => {
  await open(page);
  await stubJournal(page);
  await expect(page.getByTestId("desk-journal")).toHaveCount(0); // nothing on the first screen
  await page.keyboard.press("ControlOrMeta+k");
  await page.getByRole("dialog", { name: "Jump to" }).getByRole("combobox").fill("journal summary");
  await page.keyboard.press("Enter");
  const journal = page.getByTestId("desk-journal");
  await expect(journal.getByLabel("Journal summary figures").getByText("All-Time Closed P&L")).toBeVisible();
  await expect(journal.getByLabel("Journal summary figures").getByText("+$75.00").first()).toBeVisible();
  await expect(journal.getByRole("region", { name: "Recent closed trades" }).getByText("XYZ").first()).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(journal).toHaveCount(0);
});

test("More → Journal summary opens the same drawer and drops the word from the address", async ({ page }) => {
  await stubJournal(page);
  await open(page);
  await page.getByRole("button", { name: /open menu|menu/i }).first().click();
  const journal = page.getByRole("button", { name: "Journal", exact: true });
  if ((await journal.getAttribute("aria-expanded")) !== "true") await journal.click();
  await expect(page.getByRole("link", { name: "Dashboard", exact: true })).toHaveCount(0);
  await page.getByRole("link", { name: "Journal summary", exact: true }).click();
  await expect(page.getByTestId("desk-journal")).toBeVisible();
  await expect(page).not.toHaveURL(/desk=journal/);
});

test("Journal summary over the Sync Center: Escape closes the top one first and focus goes back", async ({ page }) => {
  await open(page);
  await stubJournal(page);
  await page.keyboard.press("ControlOrMeta+k");
  await page.getByRole("dialog", { name: "Jump to" }).getByRole("combobox").fill("data sync");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "Data Sync Center" })).toBeVisible();
  await page.keyboard.press("ControlOrMeta+k");
  await page.getByRole("dialog", { name: "Jump to" }).getByRole("combobox").fill("journal summary");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("desk-journal")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("desk-journal")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Data Sync Center" })).toBeVisible(); // the one underneath stays
});

const DECISION_ID = "11111111-1111-4111-8111-111111111111";
const DECISION = {
  id: DECISION_ID, operation_id: "op-1", opportunity_id: "SPY:2026-11-13", actor: "human", decision: "wait", symbol: "SPY",
  received_at: "2026-11-13T14:35:00Z", input_cutoff: "2026-11-13T14:35:00Z", policy_version: "p0-v1", policy_hash: "h1",
  evidence: { packet: {} }, evidence_sha256: "e1", plan: {}, rationale: "Wait for opening drive confirmation.",
  wait_condition: "Break above opening high", wait_expiry: "2026-11-13T18:00:00Z", record_sha256: "r1", status: "practice_draft_unarmed",
};
const SCALP = {
  day: "2026-11-13", today: "2026-11-13", now: "2026-11-13T09:45:00-05:00", sessions: ["2026-11-13"],
  live: { day: "2026-11-13", captured_at: "2026-11-13T09:40:05-05:00", feed: "sip", eligible: 120,
    picks: [{ symbol: "ANET", direction: "up", relative_volume: 2.5, sector_lead_pct: 1.2 }], movers: [] },
  recap: null, decisions: [],
};
const SCENARIO = {
  id: "replay-1", title: "Trim or hold a fast winner", symbol: "XYZ", instrument: "call option",
  description: "Two frozen moments from a synthetic call.", checkpoint_count: 2, repeat_status: "new", latest_attempt_id: null,
  option_contract: { right: "call", strike: 100, expiry: "2026-11-20", dte_at_entry: 5 },
};

test("Practice fold & ⌘K reach Daily practice, Saved decisions, 9:40 scalp shortlist and Decision replay lab", async ({ page }) => {
  await open(page);
  await page.route(url => url.pathname.endsWith("/practice/runs"), route => route.fulfill({ json: { runs: [] } }));
  await page.route(url => url.pathname.endsWith("/decisions"), route => route.fulfill({ json: { decisions: [DECISION] } }));
  await page.route(url => url.pathname.endsWith("/scalp-shortlist"), route => route.fulfill({ json: SCALP }));
  await page.route(url => url.pathname.endsWith("/practice/replay/scenarios"), route => route.fulfill({ json: { scenarios: [SCENARIO] } }));

  // Nothing from /practice mounts on the desk's first screen while lines wait closed.
  for (const id of ["practice-routine", "practice-decisions", "scalp-shortlist", "personal-replay"]) {
    await expect(page.getByTestId(id)).toHaveCount(0);
  }

  const jump = async (name: string) => {
    await page.keyboard.press("ControlOrMeta+k");
    const box = page.getByRole("dialog", { name: "Jump to" });
    await box.getByRole("combobox").fill(name);
    await box.getByRole("option", { name: new RegExp(`^${name}`) }).click();
  };

  await jump("Daily practice");
  await expect(page.getByTestId("practice-routine")).toBeVisible();
  await jump("Saved decisions");
  await expect(page.getByTestId("practice-decisions")).toContainText("SPY · WAIT");
  await jump("9:40 scalp shortlist");
  await expect(page.getByTestId("scalp-shortlist")).toContainText("ANET");
  await jump("Decision replay lab");
  await expect(page.getByTestId("personal-replay")).toContainText("Trim or hold a fast winner");

  // Closing one collapses it cleanly inside the fold.
  await page.getByTestId("practice-line-decision-replay").click();
  await expect(page.getByTestId("personal-replay")).toHaveCount(0);
});

test("desk ?decision= deep-link opens Saved decisions and focuses that card; 9:40 scalp nudge opens its fold", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.clock.install({ time: new Date("2026-11-13T14:45:00Z") }); // 9:45 ET during 9:40 scalp window
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
  await page.route(url => url.pathname.endsWith("/decisions"), route => route.fulfill({ json: { decisions: [DECISION] } }));
  await page.route(url => url.pathname.endsWith("/scalp-shortlist"), route => route.fulfill({ json: SCALP }));

  await page.goto(`/copilot-lab?decision=${DECISION_ID}`);
  await expect(page.getByTestId("desk-book")).toBeVisible();
  const card = page.locator(`details[data-decision-id="${DECISION_ID}"]`);
  await expect(card).toHaveAttribute("open", "");
  await expect(card).toContainText("Break above opening high");

  const nudge = page.getByRole("link", { name: "9:40 scalp picks" });
  await expect(nudge).toBeVisible();
  await expect(nudge).toHaveAttribute("href", "#scalp-shortlist");
  await nudge.click();
  await expect(page.getByTestId("practice-line-scalp")).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByTestId("scalp-shortlist")).toContainText("ANET");
});
