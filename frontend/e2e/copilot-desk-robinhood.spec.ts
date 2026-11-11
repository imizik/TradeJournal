import { expect, test, type Page } from "@playwright/test";

// The desk's live book from Robinhood (docs/robinhood-read-feed.md): account chips in the top bar, an account tag on each
// book row, Robinhood's P&L and quantity on matched rows, new and not-on-Robinhood rows named, stocks folded, and the
// journal's book as before whenever the feed is not live. Every lab route is stubbed in the browser (the e2e backend
// runs with the lab off); nothing here reaches Robinhood.
const ON = {
  enabled: true, backend: "fake", evidence: "live", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
const NOW = new Date("2026-10-23T15:00:00Z");
const AS_OF = Date.parse("2026-10-23T14:59:00Z") / 1000;
const TRADE = "55555555-5555-4555-8555-555555555555";
const OTHER = "66666666-6666-4666-8666-666666666666";
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
      quantity: 2, mark: 420, account: ROTH, live: "matched" }) }),
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
const LIVE = { state: "ok", joined: true, as_of: AS_OF, issue: null, accounts: [
  { ...ROTH, total_value: 9860.12, cash: 1200.5, buying_power: 1150 }, { ...MCP, total_value: 0, cash: 0, buying_power: 0 }] };
const desk = (robinhood: unknown, threads = LIVE_ROWS) => ({
  as_of: "2026-10-23T15:00:00Z", quotes_at: null, quote_issue: null, day: { phase: "regular", need_you: 0, streak: null },
  sections: { positions: "ok" }, plans: [], robinhood,
  threads: [row({ key: "briefing", group: "pinned", title: "Briefing", status: { text: "Nothing new.", tone: "muted" } }), ...threads],
});

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
  await page.goto("/copilot-lab");
  await expect(page.getByTestId("desk-book")).toBeVisible();
  return reads;
}

for (const width of [1440, 375]) {
  test(`live from Robinhood at ${width}px: chips, account tags, new and missing rows, stocks folded, refresh`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const reads = await open(page, desk(LIVE));
    const chips = page.getByTestId("desk-accounts");
    await expect(chips).toContainText("Roth IRA ••8267 $9,860");
    await expect(chips).toContainText("MCP ••7884 $0");
    const shelf = page.getByTestId("desk-book");
    await expect(shelf.getByRole("heading", { level: 2 })).toHaveText("Your book · 4 followed");
    await expect(shelf.getByTestId("book-live")).toHaveText(/^live from Robinhood · as of \d/);
    // Options first; the stock with no plan waits behind one line.
    await expect(shelf.getByRole("button", { name: /^(NBIS|CRWV|APLD) / })).toHaveCount(3);
    await expect(shelf.getByRole("button", { name: /^RKLB/ })).toHaveCount(0);
    await expect(shelf.getByTestId("book-stocks")).toHaveText("1 stock position ▾");
    const nbis = shelf.getByRole("button", { name: /^NBIS/ });
    await expect(nbis).toContainText("Roth IRA");
    await expect(nbis).toContainText("10/30/26 100C ×2");
    await expect(nbis).toContainText("+$220");
    await expect(nbis).toContainText("On plan");
    await expect(shelf.getByRole("button", { name: /^APLD/ })).toContainText("New · not in the journal yet");
    await expect(shelf.getByRole("button", { name: /^APLD/ })).toContainText("MCP");
    await expect(shelf.getByRole("button", { name: /^CRWV/ })).toContainText("Not on Robinhood");
    await shelf.getByTestId("book-stocks").click();
    await expect(shelf.getByRole("button", { name: /^RKLB/ })).toContainText("stock ×8");
    await expect(page.locator("body")).not.toContainText("333338267");
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    await page.screenshot({ path: test.info().outputPath(`desk-robinhood-${width}.png`), fullPage: false });
    const before = reads.threads;
    await shelf.getByTestId("book-live").click();
    await expect.poll(() => reads.refresh).toBe(1);
    await expect.poll(() => reads.threads).toBeGreaterThan(before);
  });
}

test("not live: no chips, no tags, the journal's book as before, one quiet line", async ({ page }) => {
  const journal = LIVE_ROWS.slice(0, 2).map(r => {
    const { account: _a, live: _l, quantity: _q, mark: _m, ...rest } = (r as unknown as { book: Record<string, unknown> }).book; // eslint-disable-line @typescript-eslint/no-unused-vars
    return { ...r, book: rest };
  });
  for (const [robinhood, words] of [[{ state: "stale", as_of: AS_OF }, /^Robinhood stale · from the journal · as of/],
    [{ state: "expired" }, /^Robinhood sign-in expired · from the journal$/], [{ state: "signed_out" }, /^Robinhood signed out/]] as const) {
    await page.unrouteAll();
    await open(page, desk(robinhood, journal));
    await expect(page.getByTestId("desk-accounts")).toHaveCount(0);
    await expect(page.getByTestId("book-account")).toHaveCount(0);
    await expect(page.getByTestId("book-live")).toHaveText(words);
  }
  await page.unrouteAll();
  await open(page, desk({ state: "off" }, journal));
  await expect(page.getByTestId("book-live")).toHaveCount(0); // off: exactly today's book
  await expect(page.getByTestId("desk-book").getByRole("heading", { level: 2 })).toHaveText("Your book · 2 followed");
});
