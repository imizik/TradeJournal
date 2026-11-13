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
