import { expect, test, type Page } from "@playwright/test";

// Paper it on the desk's ideas (docs/copilot-lab.md § Paper): a Radar setup card in the Feed and a scanner pick each open
// the existing paper confirm prefilled from the idea (its contract, the stop and target as the idea gives them, its
// reasoning as the note), show the fill price before anything is placed, and send one order through the paper order
// route tagged with whose idea it was; an idea with no contract shows the button disabled with the reason. The Paper
// section tags each position by source and splits the closed score by source in one row. Every route is stubbed with
// invented numbers, so nothing reaches the e2e backend.
const ON = {
  enabled: true, backend: "fake", evidence: "live", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
const NOW = new Date("2026-11-13T16:00:00Z"); // Friday 11:00 New York
const epoch = (iso: string) => Date.parse(iso) / 1000;
const iso = (at: number) => new Date(at * 1000).toISOString().replace(/\.\d+Z$/, "Z");
const item = (over: Record<string, unknown>) => ({
  has_time: true, symbol: null, detail: null, publisher: null, url: null, href: null, investigation_id: null, radar_event_id: null,
  setup: null, plan: null, mine: false, upcoming: false, ...over,
});
const setup = (id: string, contract: object | null) => ({
  id, event_id: `rd-${id}`, words: "dip turning up", levels_line: "In near 94.00 · out below 92.50 (−1.6%)",
  contract_line: contract ? "Candidate: MU Nov 20 95C · ask 2.10" : null, record: null, paper_record: null, plan_state: "none", investigation_id: null,
  direction: "up", invalidation: 92.5, contract,
});
const FEED = {
  as_of: "2026-11-13T16:00:00Z", now: epoch("2026-11-13T16:00:00Z"), day: "2026-11-13", total: 2, sources: {}, unavailable: [],
  items: [
    item({ id: "setup:mu", source: "Radar setup", at: epoch("2026-11-13T15:40:00Z"), symbol: "MU", text: "MU dip turning up", radar_event_id: "rd-setup-mu",
      setup: setup("setup-mu", { option_type: "call", expiry: "2026-11-20", strike: 95 }), plan: "setup" }),
    item({ id: "setup:amd", source: "Radar setup", at: epoch("2026-11-13T15:30:00Z"), symbol: "AMD", text: "AMD dip turning up", radar_event_id: "rd-setup-amd",
      setup: setup("setup-amd", null), plan: "setup" }),
  ],
};
const SCANNER = { state: "ok", day: "2026-11-13", simulated: false, message: null,
  monitoring: { state: "fresh", checked_at: "2026-11-13T16:00:00Z", last_judged_bar_end: "2026-11-13T15:58:00Z", symbols_judged: 12, symbols_selected: 12 },
  rows: [{ id: "c-crwv", symbol: "CRWV", setup: "fade", direction: "short", words: "VWAP fade (short)", bar_end: iso(epoch("2026-11-13T15:30:00Z")),
    trigger: 118.4, stop: 120.15, target: 115.9, vwap: 116.8, range_high: 119.2, range_low: 116.3, flags: [], contract_line: "11-20 115P · Δ0.41",
    contract: { option_type: "put", expiry: "2026-11-20", strike: 115 }, status: "open", pnl: null, exit_reason: null, new: true, radar: null }] };
const stats = (pnl: number, trades: number, win: number | null) => ({ trades, pnl, win_rate: win, avg_win: null, avg_loss: null, largest_loss: null, curve: [] });
const OPEN = {
  id: "11111111-1111-4111-8111-111111111111", symbol: "MU", instrument: "option", option_type: "call", expiry: "2026-11-20", label: "MU $95 Call 11/20/26",
  bias: "long", credit: false, width: null, multiplier: 100, quantity: 1, remaining: 1, per_share: -2.1, cash: -210, basis: -210, stock: 94.2,
  note: "Radar: MU dip turning up", stop: 92.5, target: null, opened_at: epoch("2026-11-13T15:45:00Z"), status: "open", closed_at: null, realized: 0,
  legs: [{ quote: "MU261120C00095000", action: "buy", strike: 95 }], awaiting_close: false, mark: null, auto: false, touched: {}, exiting: false, held: 0,
  source: "radar", idea_id: "setup-mu",
};
const BOOK = {
  run: { id: "r1", number: 1, starting_cash: 10000, started_at: epoch("2026-11-10T15:00:00Z") },
  account: { cash: 9790, collateral: 0, reserved: 0, buying_power: 9790, equity: null, pnl: null, unpriced: 1, prices_at: null },
  positions: [OPEN], closed: [], orders: [],
  score: { paper: { ...stats(-14.5, 3, 66.7), open_pnl: null, by_source: [
    { source: "mine", trades: 2, pnl: 80.5, win_rate: 100 }, { source: "copilot", trades: 0, pnl: 0, win_rate: null },
    { source: "radar", trades: 1, pnl: -95, win_rate: 0 }, { source: "scanner", trades: 0, pnl: 0, win_rate: null }] }, real: stats(-312, 3, 33.3) },
  earlier: [], market_open: true,
};
const THREADS = {
  as_of: "2026-11-13T16:00:00Z", quotes_at: null, quote_issue: null, day: { phase: "regular", need_you: 0, streak: null },
  sections: { positions: "ok" }, plans: [], robinhood: { state: "off" }, threads: [],
};
const READS: Record<string, unknown> = {
  "/copilot/desk/threads": THREADS,
  "/copilot/desk/watching": { state: "ok", symbols: [], count: 0, max: 30, imported_at: null, robinhood: "off", levels: {}, setups: {} },
  "/copilot/desk/sparks": { as_of: "2026-11-13T16:00:00Z", spy_change_pct: 0.4, rows: {} },
  "/copilot/desk/moving": { state: "ok", mode: "live", session: "2026-11-13", as_of: "2026-11-13T16:00:00Z", reason: null, groups: [], movers: [] },
  "/copilot/desk/feed": FEED,
  "/copilot/investigations": { investigations: [] },
  "/copilot/tickets": { plans: [] },
  "/copilot/unusual": { state: "ok", rows: [], tickers: [], unread: [], no_history: [], stale: [], rule: "" },
  "/copilot/scanner": SCANNER,
  "/copilot/exposure": { line: null },
  "/copilot/paper": BOOK,
};
const PREVIEW = {
  MU: { label: "MU $95 Call 11/20/26", per_share: -2.1, stock: 94.2, legs: { MU261120C00095000: { action: "buy", bid: 2.0, ask: 2.1, price: 2.1 } } },
  CRWV: { label: "CRWV $115 Put 11/20/26", per_share: -1.85, stock: 117.9, legs: { CRWV261120P00115000: { action: "buy", bid: 1.75, ask: 1.85, price: 1.85 } } },
};

async function open(page: Page, width: number) {
  const orders: Record<string, unknown>[] = [];
  await page.setViewportSize({ width, height: 900 });
  await page.clock.install({ time: NOW });
  await page.route("**/api/backend/**", route => route.fulfill({ status: 404, json: { detail: "Not in this test." } }));
  await page.route("**/copilot/status", route => route.fulfill({ json: ON }));
  await page.route("**/copilot/chat", route => route.abort());
  for (const [path, body] of Object.entries(READS)) await page.route(url => url.pathname.endsWith(path), route => route.fulfill({ json: body }));
  await page.route("**/copilot/desk/minute?*", route => {
    const reads = new URL(route.request().url()).searchParams.getAll("read").map(target => {
      const body = READS[target.split("?")[0]];
      return body ? { status: 200, body } : { status: 404, body: { detail: "Not in this test." } };
    });
    return route.fulfill({ json: { reads } });
  });
  await page.route("**/copilot/paper/orders", route => {
    const body = route.request().postDataJSON();
    orders.push(body);
    const one = PREVIEW[body.symbol as keyof typeof PREVIEW];
    const fill = { ...one, quantity: body.quantity, cash: one.per_share * 100 * body.quantity, quoted_at: NOW.getTime() / 1000 - 2,
      buying_power: 9790, need_each: -one.per_share * 100 };
    return route.fulfill({ json: body.preview ? { preview: fill } : { filled: { ...fill, position_id: "p-new" } } });
  });
  await page.goto("/copilot-lab");
  if (width < 768) await page.getByTestId("desk-view-feed").click();
  else await page.getByRole("tab", { name: "Feed" }).click();
  const feed = page.getByTestId("desk-feed");
  await feed.getByRole("button", { name: "Ideas", exact: true }).click();
  return { page, feed, orders };
}

for (const width of [1440, 375]) {
  test(`Paper it on a Radar setup opens the paper confirm prefilled and sends one tagged order at ${width}px`, async ({ page }) => {
    const { feed, orders } = await open(page, width);
    const mu = feed.getByTestId("feed-item").filter({ hasText: "MU dip turning up" });
    await mu.getByTestId("paper-button").click();
    const confirm = mu.getByTestId("paper-confirm");
    await expect(confirm.getByTestId("paper-idea")).toHaveText("· Radar's idea: MU $95 Call 11/20/26");
    await expect(confirm.getByTestId("paper-preview")).toContainText("Buy 1 × MU $95 Call 11/20/26 at 2.10 (the ask), quote 10:59:58 AM ET: costs $210.00");
    expect(orders).toHaveLength(1); // the preview only: nothing placed yet
    await expect(confirm.getByLabel("Paper stop (stock price)")).toHaveValue("92.5");
    await expect(confirm.getByLabel("Paper target (stock price)")).toHaveValue("");
    await expect(confirm.getByLabel("Paper note")).toHaveValue("Radar: MU dip turning up. In near 94.00 · out below 92.50 (−1.6%)");
    await confirm.getByTestId("paper-fill").click();
    await expect(confirm.getByTestId("paper-done")).toContainText("Paper: Buy 1 × MU $95 Call 11/20/26 at 2.10");
    expect(orders).toHaveLength(2);
    expect(orders[1]).toMatchObject({ action: "open", instrument: "option", symbol: "MU", option_type: "call", expiry: "2026-11-20", strike: 95,
      quantity: 1, stop: 92.5, target: null, source: "radar", idea_id: "setup-mu" });
    expect(String(orders[1].order_key)).toMatch(/^[A-Za-z0-9_-]{8,}$/);
    // A setup with no liquid contract cannot be papered, and says why.
    const amd = feed.getByTestId("feed-item").filter({ hasText: "AMD dip turning up" });
    await expect(amd.getByTestId("paper-button")).toBeDisabled();
    await expect(amd.getByTestId("paper-why")).toHaveText("No liquid contract on this card to paper.");
  });
}

test("Paper it on a scanner pick carries the scanner's stop and target", async ({ page }) => {
  const { feed, orders } = await open(page, 1440);
  await feed.getByRole("button", { name: "Scanner", exact: true }).click();
  const row = feed.getByTestId("scanner-row").filter({ hasText: "CRWV" });
  await row.getByTestId("paper-button").click();
  const confirm = row.getByTestId("paper-confirm");
  await expect(confirm.getByTestId("paper-idea")).toHaveText("· Scanner's idea: CRWV $115 Put 11/20/26");
  await expect(confirm.getByTestId("paper-preview")).toContainText("Buy 1 × CRWV $115 Put 11/20/26 at 1.85 (the ask");
  await expect(confirm.getByLabel("Paper stop (stock price)")).toHaveValue("120.15");
  await expect(confirm.getByLabel("Paper target (stock price)")).toHaveValue("115.9");
  await confirm.getByTestId("paper-fill").click();
  await expect(confirm.getByTestId("paper-done")).toBeVisible();
  expect(orders[1]).toMatchObject({ symbol: "CRWV", option_type: "put", strike: 115, expiry: "2026-11-20", stop: 120.15, target: 115.9,
    source: "scanner", idea_id: "c-crwv" });
  expect(String(orders[1].note)).toBe("Scanner: CRWV VWAP fade (short). Trigger 118.40. Stop 120.15 · Target 115.90");
});

for (const width of [1440, 375]) {
  test(`the Paper section tags a position by source and splits the closed score by source at ${width}px`, async ({ page }) => {
    await open(page, width);
    if (width < 768) await page.getByTestId("desk-view-book").click();
    const paper = page.getByTestId("desk-paper");
    await expect(paper.getByTestId("paper-position").getByTestId("paper-source")).toHaveText("Radar");
    const split = paper.getByTestId("paper-by-source");
    await expect(split.locator('[data-source="mine"]')).toHaveText("Mine +$80.50 100%/2");
    await expect(split.locator('[data-source="radar"]')).toHaveText("Radar −$95.00 0%/1");
    await expect(split.locator('[data-source="copilot"]')).toHaveText("Copilot —");
    await expect(split.locator('[data-source="scanner"]')).toHaveText("Scanner —");
  });
}
