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

const DISAGREE = () => ({ count: 0, rules_priced: 0, rules_pnl: 0, shadow_priced: 0, shadow_pnl: 0, isaac_priced: 0, isaac_pnl_per_contract: 0, isaac_pnl_dollars: 0, evidence: "not enough" as const });
const ISAAC = () => ({
  setups: 0, traded: 0, assisted: 0, independent: 0, closed: 0, priced: 0, pnl_per_contract: 0, pnl_dollars: 0,
  evidence: "not enough" as const,
  group_evidence: { assisted: "not enough" as const, independent: "not enough" as const, closed: "not enough" as const },
  disagreements: { shadow_only: DISAGREE(), isaac_only: DISAGREE(), both_took: DISAGREE(), both_passed: DISAGREE() },
});
const SCORECARD = (setups = 1) => ({
  not_published: 0, shadow_setups: setups, isaac: ISAAC(), independent: ISAAC(),
  setups, decisions: setups, take: setups, skip: 0, late: 0, no_response: 0, unresolved: 0,
  rules_priced: setups, shadow_priced: setups, skipped_priced: 0, rules_pnl: 42, shadow_pnl: 42, skipped_rules_pnl: 0, clean_order: setups,
  evidence: "not enough" as const,
  group_evidence: { rules: "not enough" as const, takes: "not enough" as const, skipped: "not enough" as const },
});
const scannerDayBody = (day: string) => ({
  date: day, scanner_version: "v1", params_hash: "abcdef1234567890", enabled: true, session: "open",
  totals: { candidates: 1, trades: 1, resolved: 1, unresolved: 0, no_contract: 0, pnl: 42, pnl_2x_spread: 36, wins: 1 },
  scorecard: { day: SCORECARD(1), cumulative: SCORECARD(5) },
  candidates: [{
    id: `cand-${day}`, scanner_version: "v1", params_hash: "abcdef1234567890", symbol: "AMZN", setup: "fade", direction: "long",
    bar_end: `${day}T14:10:00Z`, detected_at: `${day}T14:10:05Z`, stop: 219.1, target: 222.4, flags: [],
    facts: { scanner_universe: ["AMZN", "MU"] }, contract: { symbol: "AMZN261120C00220000", expiration: "2026-11-20", option_type: "call", strike: 220, delta: 0.45, bid: 1.8, ask: 1.9 },
    status: "exit", paper_deadline: null,
    shadow: { decision: "take", status: "exit", timing: "on_time", clean_order: true, publication: "written", reason: "Clean fade.", labels: [], entry: {}, result: { pnl: 42 } },
    isaac: { traded: false, assisted: false, status: "none", pnl_per_contract: null, extra_trade_ids: [], trades: [] },
    events: { entry: { at: `${day}T14:11:00Z`, ask: 1.9 }, exit: { at: `${day}T14:55:00Z`, bid: 2.32, reason: "target", pnl: 42 } },
  }],
  monitoring: { state: "fresh", checked_at: `${day}T15:00:00Z`, last_judged_bar_end: `${day}T15:00:00Z`, symbols_judged: 12, symbols_selected: 12 },
});

const RADAR_EVENT_ID = "evt_mu_20261113";
const RADAR_DETAIL = (rating: string | null = null) => ({
  event: {
    event_id: RADAR_EVENT_ID, session_date: "2026-11-13", rule_version: "radar-rules-v1", universe_version: "radar-universe-v2",
    kind: "relative_to_sector", direction: "up", symbols: ["MU"], benchmark: "SPY", group: "SMH",
    first_seen_at: "2026-11-13T15:10:00Z", summary: "MU up 4.1% while SMH is up 0.6%",
    measures: { change_pct: 4.1, relative_pct: 3.5 },
    evidence: [{ symbol: "MU", pass_id: 1, retrieved_at: "2026-11-13T15:10:00Z", last: 112.5, change_pct: 4.1 }],
    coverage: { passes_expected: 10, passes_recorded: 10, symbols_missing: [] }, chart: { symbol: "MU" },
  },
  revisions: [{
    event_id: RADAR_EVENT_ID, revision: 1, recorded_at: "2026-11-13T15:25:00Z", status: "extended",
    measures: { change_pct: 4.8 }, evidence: [{ symbol: "MU", pass_id: 2, retrieved_at: "2026-11-13T15:25:00Z", last: 113.2, change_pct: 4.8 }],
    note: "Lead widened from 3.5 to 4.8 points",
  }],
  rating, news: { status: "none_found", checked_at: "2026-11-13T15:12:00Z", headlines: [] },
  news_checks: [{ status: "none_found", checked_at: "2026-11-13T15:12:00Z", headlines: [] }],
  plans: { planned: false, traded: false },
});

async function stubLogs(page: Page) {
  const rated: Array<{ id: string; rating: string }> = [];
  let savedRating: string | null = null;
  await page.route(url => url.pathname.endsWith("/scanner/day"), route => {
    const day = new URL(route.request().url()).searchParams.get("day") ?? "2026-11-13";
    return route.fulfill({ json: scannerDayBody(day) });
  });
  await page.route(url => url.pathname.endsWith("/scanner/settings"), route =>
    route.fulfill({ json: { symbols: ["AMZN", "MU"], revision: 1, max_symbols: 12 } }));
  await page.route(url => url.pathname.endsWith("/radar/feed"), route => {
    const reqSession = new URL(route.request().url()).searchParams.get("session") ?? "2026-11-13";
    return route.fulfill({
      json: {
        state: "recording", reason: null, session: reqSession, sessions: ["2026-11-13", "2026-11-12"],
        events: [{ ...RADAR_DETAIL(savedRating).event, on_movers: false, latest_status: "extended", revision_count: 1, rating: savedRating, news: RADAR_DETAIL().news }],
        since_last_visit: [RADAR_EVENT_ID], last_visit_at: null,
        coverage: { passes_recorded: 10, passes_expected: 10, passes_failed: 0, last_ok_pass_at: "2026-11-13T15:30:00Z", symbols_tracked: 169, symbols_missing: [], universe_version: "radar-universe-v2", live: true },
        generated_at: "2026-11-13T15:30:00Z",
        outside_list: [{ as_of: "2026-11-13T15:30:00Z", status: "ok", covered: 50, requested: 50, rows: [{ kind: "outside_list", symbol: "PLTR", price: 61.2, move_vs_spy_pp: 5.4, dollar_volume: 120_000_000, sector: "Software" }] }],
      },
    });
  });
  await page.route(url => url.pathname.endsWith(`/radar/events/${RADAR_EVENT_ID}`), route => route.fulfill({ json: RADAR_DETAIL(savedRating) }));
  await page.route(url => url.pathname.endsWith(`/radar/events/${RADAR_EVENT_ID}/feedback`), async route => {
    const body = route.request().postDataJSON() as { rating: string };
    savedRating = body.rating;
    rated.push({ id: RADAR_EVENT_ID, rating: body.rating });
    return route.fulfill({ json: { rating: body.rating } });
  });
  await page.route(url => url.pathname.endsWith("/radar/visits"), route => route.fulfill({ json: { visited_at: "2026-11-13T15:30:00Z", previous_visit_at: null } }));
  await page.route(url => url.pathname.endsWith("/radar/setups"), route => route.fulfill({ json: { session: "2026-11-13", setups: [], scorecard: [] } }));
  await page.route(url => url.pathname.endsWith("/radar/movers"), route => route.fulfill({ json: { session: "2026-11-13", state: "off", reason: "No movers in fixture.", header: null, leaders: [], laggards: [], groups: [], missing: [] } }));
  await page.route(url => url.pathname.endsWith("/radar/shadow-book"), route => route.fulfill({
    json: {
      enabled: true, max_turns: 4, week: { start: "2026-11-09", end: "2026-11-13" },
      summary: { shadow: { decisions: 1, turns: 1, filtered: 0, plans: 1, closed: 0, pnl_usd: 0 }, owner: { state: "ok", trades: 1, pnl_usd: 50 }, note: "Shadow week fixture." },
      decisions: [{ id: "sd1", radar_event_id: RADAR_EVENT_ID, session_date: "2026-11-13", event: { kind: "relative_to_sector", direction: "up", symbols: ["MU"], first_seen_at: "2026-11-13T15:10:00Z", summary: "MU up 4.1% while SMH is up 0.6%" }, decision: "skip", status: "skip", reason: "Shadow fixture skip", plan: null, model: "fake", decided_at: "2026-11-13T15:11:00Z", entry: null, exit: null, result: null, unresolved: null }],
    },
  }));
  return { rated };
}

test("⌘K: Data sync opens the Sync Center; Scanner history and Radar log open their desk drawers", async ({ page }) => {
  await open(page);
  await stubLogs(page);
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
  await page.keyboard.press("Enter");
  const scannerDrawer = page.getByTestId("desk-scanner-history");
  await expect(scannerDrawer).toBeVisible();
  await expect(scannerDrawer.getByRole("region", { name: "Setups" }).getByText("AMZN", { exact: true })).toBeVisible();
  await expect(scannerDrawer.getByRole("region", { name: "Day scorecard scorecard" })).toBeVisible();
  await expect(scannerDrawer.getByRole("region", { name: "Cumulative scorecard scorecard" })).toBeVisible();
  await scannerDrawer.getByRole("button", { name: "← Previous day" }).click();
  await expect(scannerDrawer).toContainText("2026-11-12");
  await expect(page).toHaveURL(/\/copilot-lab/);
  await page.keyboard.press("Escape");
  await expect(scannerDrawer).toHaveCount(0);

  await page.keyboard.press("ControlOrMeta+k");
  await palette.getByRole("combobox").fill("radar log");
  await expect(palette.getByRole("option").first()).toContainText("Radar log");
  await page.keyboard.press("Enter");
  const radarDrawer = page.getByTestId("desk-radar-log");
  await expect(radarDrawer).toBeVisible();
  await expect(radarDrawer.getByText("Developments", { exact: true })).toBeVisible();
  await expect(radarDrawer.getByRole("region", { name: "Outside your list" })).toContainText("PLTR");
  await expect(radarDrawer.getByTestId("shadow-book")).toContainText("Shadow fixture skip");
  await radarDrawer.getByTestId("radar-event").getByRole("button").first().click();
  await expect(radarDrawer.getByRole("region", { name: "Revisions" })).toContainText("Lead widened from 3.5 to 4.8 points");
  await expect(radarDrawer.getByRole("group", { name: "Was this useful?" })).toBeVisible();
  await expect(page).toHaveURL(/\/copilot-lab/);
  await page.keyboard.press("Escape");
  await expect(radarDrawer).toHaveCount(0);
});

test("old /scanner and /radar URLs open their desk drawers and phone rating links save the rating", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.clock.install({ time: NOW });
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
  const { rated } = await stubLogs(page);

  await page.goto("/scanner?day=2026-11-12");
  await expect(page).toHaveURL(/\/copilot-lab/);
  await expect(page.getByTestId("desk-scanner-history")).toContainText("2026-11-12");
  await page.keyboard.press("Escape");

  await page.goto("/scanner?history=1");
  await expect(page).toHaveURL(/\/copilot-lab/);
  await expect(page.getByTestId("desk-scanner-history")).toContainText("2026-11-13");
  await page.keyboard.press("Escape");

  await page.goto(`/radar?event=${RADAR_EVENT_ID}&rate=useful`);
  await expect(page).toHaveURL(/\/copilot-lab/);
  await expect(page).not.toHaveURL(/rate=/);
  expect(new URL(page.url()).searchParams.get("rate")).toBeNull();
  const radarDrawer = page.getByTestId("desk-radar-log");
  await expect(radarDrawer).toBeVisible();
  await expect(radarDrawer.getByRole("button", { name: "Useful", exact: true })).toHaveAttribute("aria-pressed", "true");
  expect(rated).toEqual([{ id: RADAR_EVENT_ID, rating: "useful" }]);
  await page.keyboard.press("Escape");

  await page.goto("/radar?session=2026-11-12");
  await expect(page).toHaveURL(/\/copilot-lab/);
  await expect(page.getByTestId("desk-radar-log").getByLabel("Session")).toHaveValue("2026-11-12");
  await page.keyboard.press("Escape");

  await page.goto("/radar?log=1");
  await expect(page).toHaveURL(/\/copilot-lab/);
  await expect(page.getByTestId("desk-radar-log").getByTestId("shadow-book")).toBeVisible();
});

test("while the desk is home the menu drops Radar and Scanner; Signals stays", async ({ page }) => {
  await open(page);
  await page.getByRole("button", { name: /open menu|menu/i }).first().click();
  const market = page.getByRole("button", { name: "Market", exact: true });
  if ((await market.getAttribute("aria-expanded")) !== "true") await market.click();
  await expect(page.getByRole("link", { name: "Signals", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Radar", exact: true })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Scanner", exact: true })).toHaveCount(0);
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
