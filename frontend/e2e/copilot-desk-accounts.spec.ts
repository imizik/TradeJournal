import { expect, test, type Page } from "@playwright/test";

// The desk's account line (docs/robinhood-read-feed.md § On the desk): per Robinhood account in the top bar, its total,
// today's change, options value, cash, buying power and open P&L; the live prices move it; tapping an account narrows the
// book to it and tapping again shows all; not live, no money. Every lab route is stubbed in the browser; nothing here
// reaches Robinhood, and every figure is invented.
const ON = {
  enabled: true, backend: "fake", evidence: "live", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
const NOW = new Date("2026-10-23T15:00:00Z");
const AS_OF = Date.parse("2026-10-23T14:59:00Z") / 1000;
const TRADE = "55555555-5555-4555-8555-555555555555";
const OTHER = "66666666-6666-4666-8666-666666666666";
const CALL = "NBIS261030C00100000";
const ROTH = { label: "Roth IRA", masked: "••8267" };
const MCP = { label: "MCP", masked: "••7884" };
const row = (fields: Record<string, unknown>) => ({
  symbol: null, instrument: null, value: null, meter: null, investigation_id: null, trade_id: null, radar_event_id: null, path: null,
  changed_at: null, ...fields,
});
const book = (fields: Record<string, unknown>) => ({ usd: null, pct: null, expiry: null, days_held: 1, track: null, state: "on_plan",
  planned: true, stop_pct: null, ...fields });
const LIVE_ROWS = [
  row({ key: `trade:${TRADE}`, group: "watch", symbol: "NBIS", title: "NBIS 10/30/26 100C", instrument: "10/30/26 100C", trade_id: TRADE,
    value: { text: "+$220.00", tone: "gain" }, status: { text: "Invalidation 92.30 (NBIS) · 1.8% away", tone: "muted" },
    book: book({ usd: 220, pct: 35.5, expiry: "2026-10-30", stop_pct: -1.8, track: { last: 40, entry: 80, tone: "muted" },
      quantity: 2, mark: 420, account: ROTH, live: "matched", tick: { quote: CALL, scale: 100, cost: 310, quantity: 2, sign: 1 } }) }),
  row({ key: `trade:${OTHER}`, group: "watch", symbol: "CRWV", title: "CRWV 11/20/26 120C", instrument: "11/20/26 120C", trade_id: OTHER,
    value: { text: "−$40.00", tone: "loss" }, status: { text: "No plan yet", tone: "muted" },
    book: book({ usd: -40, pct: -10, expiry: "2026-11-20", state: "no_plan", planned: false, live: "not_on_robinhood" }) }),
  row({ key: "robinhood:••7884:APLD 11/27/26 30P", group: "watch", symbol: "APLD", title: "APLD 11/27/26 30P", instrument: "11/27/26 30P",
    value: { text: "−$20.00", tone: "loss" }, status: { text: "New · not in the journal yet", tone: "info" }, path: "/copilot-lab?symbol=APLD",
    book: book({ usd: -20, pct: -16.7, expiry: "2026-11-27", days_held: null, state: "no_plan", planned: false, quantity: 1, mark: 100,
      account: MCP, live: "new" }) }),
  row({ key: "robinhood:••8267:RKLB stock", group: "watch", symbol: "RKLB", title: "RKLB stock", instrument: "stock",
    value: { text: "+$40.00", tone: "gain" }, status: { text: "New · not in the journal yet", tone: "info" }, path: "/copilot-lab?symbol=RKLB",
    book: book({ usd: 40, pct: 9.9, days_held: null, state: "no_plan", planned: false, quantity: 8, mark: 55.73, account: ROTH, live: "new" }) }),
];
// Invented figures: Roth holds NBIS (+$220) and RKLB (+$40); MCP holds APLD (-$20).
const LIVE = { state: "ok", joined: true, as_of: AS_OF, issue: null, accounts: [
  { ...ROTH, total_value: 9860.12, day_change: 140, day_change_pct: 1.44, options_value: 4200, cash: 1200.5, buying_power: 1150, open_pnl: 260 },
  { ...MCP, total_value: 480, day_change: null, day_change_pct: null, options_value: 100, cash: 380, buying_power: 380, open_pnl: -20 }] };
const desk = (robinhood: unknown, threads = LIVE_ROWS) => ({
  as_of: "2026-10-23T15:00:00Z", quotes_at: null, quote_issue: null, day: { phase: "regular", need_you: 0, streak: null },
  sections: { positions: "ok" }, plans: [], robinhood,
  threads: [row({ key: "briefing", group: "pinned", title: "Briefing", status: { text: "Nothing new.", tone: "muted" } }), ...threads],
});

const mark = { value: 4.2 };

async function open(page: Page, body: unknown) {
  const reads = { threads: 0, refresh: 0 };
  await page.clock.install({ time: NOW });
  await page.route("**/copilot/status", route => route.fulfill({ json: ON }));
  await page.route("**/copilot/desk/threads", route => { reads.threads += 1; return route.fulfill({ json: body }); });
  await page.route("**/copilot/desk/robinhood/refresh", route => {
    reads.refresh += 1;
    expect(route.request().method()).toBe("POST");
    expect(route.request().postData() ?? "").toBe(""); // parameterless: nothing from the page reaches Robinhood
    return route.fulfill({ json: LIVE });
  });
  await page.route("**/copilot/investigations?*", route => route.fulfill({ json: { investigations: [] } }));
  await page.route("**/copilot/desk/ticks?*", async route => {
    const at = Math.floor(await page.evaluate(() => Date.now() / 1000));
    return route.fulfill({ json: { state: "ok", as_of: "", poll_seconds: 5, closes_at: AS_OF + 6 * 3600, rows: { [CALL]: { last: mark.value, change_pct: null, prev_close: null, at } } } });
  });
  await page.goto("/copilot-lab");
  await expect(page.getByTestId("desk-book")).toBeVisible();
  return reads;
}

const account = (page: Page, name: string) => page.getByTestId("desk-account").filter({ hasText: name });
const heading = (page: Page) => page.getByTestId("desk-book").getByRole("heading", { level: 2 });

test("each account's figures, moved by the live prices", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  mark.value = 4.2;
  await open(page, desk(LIVE));
  const roth = account(page, "Roth IRA");
  await expect(roth.getByTestId("account-total")).toHaveText("$9,860");
  await expect(roth.getByTestId("account-today")).toHaveText("+$140 +1.4%");
  await expect(roth).toContainText("opt $4.2K cash $1.2K BP $1.2K");
  await expect(roth.getByTestId("account-open")).toHaveText("open +$260");
  const mcp = account(page, "MCP");
  await expect(mcp).toContainText("••7884");
  await expect(mcp.getByTestId("account-today")).toHaveCount(0); // unknown: no change shown, never $0
  await expect(mcp.getByTestId("account-open")).toHaveText("open −$20");
  await expect(page.locator("body")).not.toContainText("333338267");
  // NBIS to 4.70: +$100 on its two contracts moves Roth's total, today and open by $100; MCP stays.
  mark.value = 4.7;
  await page.clock.runFor(6_000);
  await expect(roth.getByTestId("account-total")).toHaveText("$9,960");
  await expect(roth.getByTestId("account-today")).toHaveText("+$240 +2.5%");
  await expect(roth.getByTestId("account-open")).toHaveText("open +$360");
  await expect(mcp.getByTestId("account-open")).toHaveText("open −$20");
  await page.screenshot({ path: test.info().outputPath("desk-accounts-1440.png") });
});

test("tapping an account narrows the book to it, tapping again shows every row", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, desk(LIVE));
  await expect(heading(page)).toHaveText("Your book · 4 followed");
  await account(page, "MCP").click();
  await expect(account(page, "MCP")).toHaveAttribute("aria-pressed", "true");
  await expect(heading(page)).toHaveText("Your book · 1 followed");
  const shelf = page.getByTestId("desk-book");
  await expect(shelf.getByRole("button", { name: /^APLD/ })).toBeVisible();
  await expect(shelf.getByRole("button", { name: /^NBIS/ })).toHaveCount(0);
  await account(page, "Roth IRA").click(); // another account: switches
  await expect(heading(page)).toHaveText("Your book · 2 followed");
  await expect(shelf.getByRole("button", { name: /^NBIS/ })).toBeVisible();
  await account(page, "Roth IRA").click(); // the same one again: every row
  await expect(account(page, "Roth IRA")).toHaveAttribute("aria-pressed", "false");
  await expect(heading(page)).toHaveText("Your book · 4 followed");
});

test("on a phone the accounts are one row that swipes", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await open(page, desk(LIVE));
  const line = page.getByTestId("desk-accounts");
  await expect(account(page, "MCP")).toBeVisible(); // evaluateAll does not wait: measure once the line has rendered
  const tops = await line.getByTestId("desk-account").evaluateAll(els => els.map(el => Math.round(el.getBoundingClientRect().top)));
  expect(new Set(tops).size).toBe(1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
  await page.screenshot({ path: test.info().outputPath("desk-accounts-375.png") });
  await account(page, "MCP").click();
  await expect(heading(page)).toHaveText("Your book · 1 followed");
});

// The day's account value line (docs/robinhood-read-feed.md § The value line): invented readings each minute from 9:31,
// none from 10:02 to 10:31 (a break, never a straight line), the day's two fills as dots.
const ET_OPEN = Date.parse("2026-10-23T13:30:00Z") / 1000;
const minute = (m: number) => ET_OPEN + m * 60;
const seg = (from: number, to: number, value: (m: number) => number) =>
  Array.from({ length: to - from + 1 }, (_, i) => [minute(from + i), Math.round(value(from + i) * 100) / 100] as [number, number]);
const series = (label: string, base: number, slope: number, quiet: number | null = null) => {
  const segments = [seg(1, 32, m => base + slope * m), seg(61, 89, m => base + slope * m)];
  const points = segments.flat();
  const first = points[0], last = points[points.length - 1];
  const change = Math.round((last[1] - first[1]) * 100) / 100;
  const [low, high] = slope >= 0 ? [first, last] : [last, first];
  return { label, segments, breaks: [{ from: minute(32), to: minute(61) }], first: { at: first[0], value: first[1] }, last: { at: last[0], value: last[1] },
    high: { at: high[0], value: high[1] }, low: { at: low[0], value: low[1] }, change, change_pct: Math.round(10000 * change / first[1]) / 100, quiet_since: quiet };
};
const DAY_LINE = {
  day: "2026-10-23", open: ET_OPEN, close: ET_OPEN + 390 * 60,
  series: { all: series("All accounts", 10_000, 4), [ROTH.masked]: series("Roth IRA", 9_500, 5), [MCP.masked]: series("MCP", 500, -1) },
  fills: [{ at: minute(10), masked: ROTH.masked, symbol: "NBIS", text: "Buy to open 2 NBIS 10/30/26 100C" },
    { at: minute(70), masked: MCP.masked, symbol: "APLD", text: "Buy to open 1 APLD 11/27/26 30P" }],
};

test("the day's value line: change, fills as dots, a break with its times, and the account tap", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, desk({ ...LIVE, day_line: DAY_LINE }));
  const line = page.getByTestId("desk-value-line");
  // All accounts: 10,004 at 9:31 to 10,356 at 10:29 → +$352 +3.5%.
  await expect(line.getByTestId("value-change")).toHaveText("+$352 +3.5%");
  await expect(line).toContainText("since 9:31 AM");
  await expect(line.locator("[data-testid=value-segment]")).toHaveCount(2); // the break is a gap, not a line
  await expect(line.locator("[data-testid=value-fill]")).toHaveCount(2);
  await expect(page.getByTestId("value-detail")).toBeHidden();
  await line.hover();
  const detail = page.getByTestId("value-detail");
  await expect(detail.getByTestId("value-high-low")).toHaveText("High $10,356 at 10:59 AMLow $10,004 at 9:31 AM");
  await expect(detail.getByTestId("value-break")).toHaveText("No readings 10:02 AM–10:31 AM");
  await page.screenshot({ path: test.info().outputPath("desk-value-line-1440.png") });
  // MCP alone: its own line, its own fill, a loss in red.
  await account(page, "MCP").click();
  await expect(line.getByTestId("value-change")).toHaveText("−$88 −17.6%");
  await expect(line.getByTestId("value-change")).toHaveClass(/text-rose/);
  await expect(line.locator("[data-testid=value-fill]")).toHaveCount(1);
  await account(page, "MCP").click();
  await expect(line.getByTestId("value-change")).toHaveText("+$352 +3.5%");
});

test("the value line stays when the feed goes stale and says since when", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  const quiet = { ...DAY_LINE, series: { all: series("All accounts", 10_000, 4, minute(89)) } };
  await open(page, desk({ state: "stale", as_of: minute(89), issue: null, day_line: quiet }));
  const line = page.getByTestId("desk-value-line");
  await expect(line.getByTestId("value-quiet")).toHaveText("· last 10:59 AM");
  await expect(page.getByTestId("desk-accounts")).toHaveText("Accounts as of 10:59 AM");
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
  await line.click(); // a phone's tap opens the detail
  await expect(page.getByTestId("value-detail")).toContainText("No reading since 10:59 AM");
  await page.screenshot({ path: test.info().outputPath("desk-value-line-375.png") });
});

test("before the day's first reading there is no value line", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, desk({ ...LIVE, day_line: { ...DAY_LINE, series: {}, fills: [] } }));
  await expect(page.getByTestId("desk-accounts")).toBeVisible();
  await expect(page.getByTestId("desk-value-line")).toHaveCount(0);
});
