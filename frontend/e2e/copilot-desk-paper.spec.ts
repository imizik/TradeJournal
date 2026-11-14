import { expect, test, type Page, type Request } from "@playwright/test";

// His own paper book on the desk (docs/copilot-lab.md § Paper): the Paper section under the book shows the paper account
// and each paper position's P&L from the desk's live ticks; Close reads a live quote first and fills on paper only on
// "Fill on paper"; Progress shows the scorecard beside his real trades; a refused order says why. Every lab route is
// stubbed in the browser (the e2e backend runs with the lab off). Invented numbers.
const ON = {
  enabled: true, backend: "fake", evidence: "live", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
const NOW = new Date("2026-11-13T16:00:00Z"); // 11:00 New York
const at = (iso: string) => Date.parse(iso) / 1000;
const OCC = "NBIS261120C00100000";
const DESK = {
  as_of: "2026-11-13T16:00:00Z", quotes_at: null, quote_issue: null, day: { phase: "regular", need_you: 0, streak: null },
  sections: { positions: "ok" }, plans: [], threads: [{ key: "briefing", group: "pinned", title: "Briefing", symbol: null, instrument: null, value: null,
    meter: null, investigation_id: null, trade_id: null, radar_event_id: null, path: null, changed_at: null, status: { text: "Nothing new.", tone: "muted" } }],
};
const OPEN = {
  id: "11111111-1111-4111-8111-111111111111", symbol: "NBIS", instrument: "option", option_type: "call", expiry: "2026-11-20",
  label: "NBIS $100 Call 11/20/26", bias: "long", credit: false, width: null, multiplier: 100, quantity: 2, remaining: 2, per_share: -3.4,
  cash: -680, basis: -680, stock: 98.05, note: "Reclaim of 98 on volume", stop: 95, target: 105, opened_at: at("2026-11-13T15:10:00Z"),
  status: "open", closed_at: null, realized: 0, legs: [{ quote: OCC, action: "buy", strike: 100 }], awaiting_close: false,
  mark: { per_share: 3.6, value: 720, pnl: 40, pct: 5.9, at: at("2026-11-13T15:50:00Z") },
};
const CLOSED = {
  ...OPEN, id: "22222222-2222-4222-8222-222222222222", symbol: "AAPL", instrument: "stock", option_type: null, expiry: null, label: "AAPL shares",
  multiplier: 1, quantity: 10, remaining: 0, basis: 0, status: "closed", closed_at: at("2026-11-12T19:00:00Z"), realized: 40.5, note: "Breakout over 100",
  legs: [{ quote: "AAPL", action: "buy", strike: null }], verdict: { kind: "target", text: "Took the target: stock 104.12 vs target 104" }, mark: undefined,
};
const stats = (pnl: number, trades: number, win: number | null) => ({ trades, pnl, win_rate: win, avg_win: pnl > 0 ? pnl : null, avg_loss: pnl < 0 ? pnl : null,
  largest_loss: pnl < 0 ? pnl : null, curve: [{ day: "2026-11-12", pnl }] });
const BOOK = {
  run: { id: "r1", number: 1, starting_cash: 10000, started_at: at("2026-11-10T15:00:00Z") },
  account: { cash: 9360.5, collateral: 0, buying_power: 9360.5, equity: 10080.5, pnl: 80.5, unpriced: 0 },
  positions: [OPEN], closed: [CLOSED], score: { paper: { ...stats(40.5, 1, 100), open_pnl: 40 }, real: stats(-312, 3, 33.3) },
  earlier: [], market_open: true,
};

// A real position on NBIS, so the desk's selected ticker is NBIS and the section offers paper shares of it.
const HELD = { key: "trade:33333333-3333-4333-8333-333333333333", group: "watch", symbol: "NBIS", title: "NBIS 11/20/26 100C", instrument: "11/20/26 100C",
  value: { text: "+$220.00", tone: "gain" }, status: { text: "On plan", tone: "muted" }, meter: null, investigation_id: null, trade_id: "33333333-3333-4333-8333-333333333333",
  radar_event_id: null, path: null, changed_at: null,
  book: { usd: 220, pct: 35.5, expiry: "2026-11-20", days_held: 1, track: null, state: "on_plan", planned: true, quantity: 2, mark: 420, live: "matched" } };

async function open(page: Page, width: number, held = false) {
  const posts: Request[] = [];
  let reads = 0;
  await page.setViewportSize({ width, height: 900 });
  await page.clock.install({ time: NOW });
  await page.route("**/copilot/status", route => route.fulfill({ json: ON }));
  await page.route("**/copilot/desk/threads", route => route.fulfill({ json: held ? { ...DESK, threads: [...DESK.threads, HELD] } : DESK }));
  await page.route("**/copilot/investigations?*", route => route.fulfill({ json: { investigations: [] } }));
  await page.route("**/copilot/desk/ticks?*", route => route.fulfill({ json: { state: "ok", as_of: NOW.toISOString(),
    rows: { [OCC]: { last: 4.0, change_pct: null, prev_close: null, at: NOW.getTime() / 1000 } }, poll_seconds: 5 } }));
  await page.route(url => url.pathname.endsWith("/copilot/paper"), route => { reads += 1; return route.fulfill({ json: BOOK }); });
  await page.route("**/copilot/paper/orders", route => {
    const body = route.request().postDataJSON();
    if (body.action === "open") return route.fulfill({ status: 409, json: { detail: "The market is closed: paper orders fill only in the regular session, on a live quote." } });
    if (!body.preview) posts.push(route.request());
    const fill = { label: OPEN.label, quantity: body.quantity, per_share: 3.9, cash: 3.9 * 100 * body.quantity, quoted_at: at("2026-11-13T15:59:58Z"), stock: 101.2,
      legs: { [OCC]: { action: "sell", bid: 3.9, ask: 4.1, price: 3.9 } }, pnl: 3.9 * 100 * body.quantity - 340 * body.quantity, all: body.quantity === 2 };
    return route.fulfill({ json: body.preview ? { preview: fill } : { filled: fill } });
  });
  await page.goto("/copilot-lab");
  if (width < 768) await page.getByTestId("desk-view-book").click();
  const paper = page.getByTestId("desk-paper");
  await expect(paper).toBeVisible();
  return { paper, posts, reads: () => reads };
}

for (const width of [1440, 375]) {
  test(`paper positions tick live and Close fills on paper only after the live quote at ${width}px`, async ({ page }) => {
    const { paper, posts, reads } = await open(page, width);
    await expect(paper).toContainText("not real money");
    await expect(paper.getByTestId("paper-account")).toContainText("Buying power $9,360.50");
    // The live tick (4.00) moves the P&L: 4.00 × 100 × 2 − 680 = +$120.00, +17.6%.
    await expect(paper.getByTestId("paper-pnl")).toHaveText("+$120.00+17.6%");
    // The account's value at the same live prices: $9,360.50 cash + 4.00 × 100 × 2 = $10,160.50, +$160.50 on $10,000.
    await expect(paper.getByTestId("paper-value")).toHaveText("Value $10,160.50");
    await paper.getByTestId("paper-close-button").click();
    await expect(paper.getByTestId("paper-close")).toContainText("Sell 2 × NBIS $100 Call 11/20/26 at 3.90 (the bid");
    await expect(paper.getByTestId("paper-close")).toContainText("takes in $780.00");
    expect(posts).toHaveLength(0); // the quote alone fills nothing
    const before = reads();
    await paper.getByTestId("paper-close-fill").click();
    await expect(paper.getByRole("status")).toContainText("made $100.00");
    expect(posts).toHaveLength(1);
    const sent = posts[0].postDataJSON();
    expect(sent).toMatchObject({ action: "close", position_id: OPEN.id, quantity: 2 });
    expect(sent.order_key).toMatch(/^[A-Za-z0-9_-]{8,}$/);
    await expect.poll(reads).toBeGreaterThan(before); // the book reads again after a fill
  });
}

test("progress shows paper beside real over the same dates, with each trade's note and how it ended", async ({ page }) => {
  const { paper } = await open(page, 1440);
  await expect(paper.getByTestId("paper-score-line")).toContainText("Paper +$40.50 · 100% of 1");
  await expect(paper.getByTestId("paper-score-line")).toContainText("Real −$312.00 · 33.3% of 3");
  await paper.getByTestId("paper-progress-toggle").click();
  const score = paper.getByTestId("paper-score");
  await expect(score).toContainText("Since Nov 10");
  await expect(score.locator("tr", { hasText: "Largest loss" })).toContainText("−$312.00");
  const closed = paper.getByTestId("paper-closed");
  await expect(closed).toContainText("AAPL shares");
  await expect(closed).toContainText("+$40.50");
  await expect(closed).toContainText("Took the target: stock 104.12 vs target 104 · “Breakout over 100”");
});

test("a refused paper order says why and fills nothing", async ({ page }) => {
  const { paper } = await open(page, 1440, true);
  const buy = paper.getByTestId("paper-button");
  await expect(buy).toHaveText("Paper buy NBIS shares");
  await buy.click();
  await expect(paper.getByTestId("paper-refused")).toHaveText("The market is closed: paper orders fill only in the regular session, on a live quote.");
  await expect(paper.getByTestId("paper-fill")).toHaveCount(0);
});
