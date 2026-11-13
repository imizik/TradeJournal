import { expect, test, type Page } from "@playwright/test";

// Robinhood's orders on the desk's book (docs/robinhood-order-fills.md § On the desk): a working order and a fresh fill
// on their contract's row, the rest in a small "Orders" group, the fill marked provisional until its email matches, and
// nothing at all when Robinhood is not live. Every lab route is stubbed in the browser (the e2e backend runs with the lab
// off); nothing here reaches Robinhood, and the book has no control that places, changes or cancels an order.
const ON = {
  enabled: true, backend: "fake", evidence: "live", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
const NOW = new Date("2026-10-23T15:00:00Z"); // 11:00 New York
const at = (iso: string) => Date.parse(iso) / 1000;
const AS_OF = at("2026-10-23T14:59:00Z");
const TRADE = "55555555-5555-4555-8555-555555555555";
const ROTH = { label: "Roth IRA", masked: "••8267" };
const MCP = { label: "MCP", masked: "••7884" };
const row = (fields: Record<string, unknown>) => ({
  symbol: null, instrument: null, value: null, meter: null, investigation_id: null, trade_id: null, radar_event_id: null, path: null,
  changed_at: null, ...fields,
});
const order = (fields: Record<string, unknown>) => ({
  contract: "NBIS 10/30/26 100C", symbol: "NBIS", instrument: "option", action: "Sell to close", working: true, quantity: 2, filled: 0,
  price_kind: "limit", limit: 4.5, avg: null, placed_at: at("2026-10-23T14:51:00Z"), filled_at: null, account: ROTH, pairing: null, ...fields,
});
const WORKING = order({ filled: 1, avg: 4.4, pairing: "provisional" });
const FILLED = order({ action: "Buy to open", working: false, quantity: 1, filled: 1, limit: 3.1, avg: 3.08,
  placed_at: at("2026-10-23T14:40:00Z"), filled_at: at("2026-10-23T14:42:00Z"), pairing: "provisional" });
const NBIS_ROW = (orders?: unknown[]) => row({
  key: `trade:${TRADE}`, group: "watch", symbol: "NBIS", title: "NBIS 10/30/26 100C", instrument: "10/30/26 100C", trade_id: TRADE,
  value: { text: "+$220.00", tone: "gain" }, status: { text: "Invalidation 92.30 (NBIS) · 1.8% away", tone: "muted" },
  book: { usd: 220, pct: 35.5, expiry: "2026-10-30", days_held: 1, track: { last: 40, entry: 80, tone: "muted" }, state: "on_plan",
    planned: true, stop_pct: -1.8, quantity: 2, mark: 420, account: ROTH, live: "matched", ...(orders ? { orders } : {}) },
});
const GROUP = [
  order({ contract: "APLD 11/27/26 30P", symbol: "APLD", action: "Buy to open", quantity: 3, limit: 1.05, placed_at: at("2026-10-23T14:58:00Z"), account: MCP }),
  order({ contract: "MU 11/13/26 835C", symbol: "MU", action: "Sell to close", working: false, quantity: 2, filled: 2, limit: 1.95, avg: 1.93,
    placed_at: at("2026-10-23T14:35:00Z"), filled_at: at("2026-10-23T14:36:00Z"), pairing: "matched" }),
];
const LIVE = { state: "ok", joined: true, as_of: AS_OF, issue: null, accounts: [
  { ...ROTH, total_value: 9860.12, cash: 1200.5, buying_power: 1150 }, { ...MCP, total_value: 0, cash: 0, buying_power: 0 }] };
const desk = (robinhood: unknown, threads: unknown[]) => ({
  as_of: "2026-10-23T15:00:00Z", quotes_at: null, quote_issue: null, day: { phase: "regular", need_you: 0, streak: null },
  sections: { positions: "ok" }, plans: [], robinhood,
  threads: [row({ key: "briefing", group: "pinned", title: "Briefing", status: { text: "Nothing new.", tone: "muted" } }), ...threads],
});

async function open(page: Page, body: unknown) {
  await page.clock.install({ time: NOW });
  await page.route("**/copilot/status", route => route.fulfill({ json: ON }));
  await page.route("**/copilot/desk/threads", route => route.fulfill({ json: body }));
  await page.route("**/copilot/investigations?*", route => route.fulfill({ json: { investigations: [] } }));
  await page.goto("/copilot-lab");
  await expect(page.getByTestId("desk-book")).toBeVisible();
}

for (const width of [1440, 375]) {
  test(`orders on the book at ${width}px: working and filled on the row, the rest grouped, no order controls`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await open(page, desk({ ...LIVE, orders: GROUP }, [NBIS_ROW([WORKING, FILLED])]));
    const shelf = page.getByTestId("desk-book");
    const nbis = shelf.getByRole("button", { name: /^NBIS/ });
    const lines = nbis.getByTestId("book-order");
    await expect(lines).toHaveCount(2);
    await expect(lines.nth(0)).toHaveAttribute("data-working", "true");
    await expect(lines.nth(0)).toContainText("Working · Sell 2 @ 4.50 limit · 1/2 filled · Roth IRA · 9m");
    await expect(lines.nth(0).getByTestId("book-order-mark")).toHaveText("provisional");
    await expect(lines.nth(1)).toContainText("Filled · Buy 1 @ 3.08, 10:42 AM");
    await expect(lines.nth(1).getByTestId("book-order-mark")).toHaveText("provisional");
    const group = shelf.getByTestId("book-orders");
    await expect(group.getByRole("heading")).toHaveText("Orders");
    await expect(group.getByTestId("book-order")).toHaveCount(2);
    await expect(group.getByTestId("book-order").nth(0)).toContainText("APLD 11/27/26 30P");
    await expect(group.getByTestId("book-order").nth(0)).toContainText("Working · Buy to open 3 @ 1.05 limit · MCP · 2m");
    await expect(group.getByTestId("book-order").nth(1)).toContainText("Filled · Sell to close 2 @ 1.93, 10:36 AM");
    await expect(group.getByTestId("book-order-mark")).toHaveCount(0); // matched: the email is in, no mark
    // Read only: nothing on the book offers to place, change or cancel an order.
    await expect(shelf.getByRole("button", { name: /cancel|replace|modify|change order|place|submit/i })).toHaveCount(0);
    await expect(shelf.getByRole("link", { name: /cancel|replace|modify/i })).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    await shelf.screenshot({ path: test.info().outputPath(`desk-orders-${width}.png`) });
  });
}

test("when the email matches the mark goes; Robinhood not live shows no orders and no empty group", async ({ page }) => {
  await open(page, desk({ ...LIVE }, [NBIS_ROW([{ ...FILLED, pairing: "matched" }])]));
  const shelf = page.getByTestId("desk-book");
  await expect(shelf.getByTestId("book-order")).toContainText("Filled · Buy 1 @ 3.08, 10:42 AM");
  await expect(shelf.getByTestId("book-order-mark")).toHaveCount(0);
  await expect(shelf.getByTestId("book-orders")).toHaveCount(0); // no leftovers: no heading at all
  for (const robinhood of [{ state: "stale", as_of: AS_OF, orders: GROUP }, { state: "signed_out" }, { state: "off" }]) {
    await page.unrouteAll();
    await open(page, desk(robinhood, [NBIS_ROW([WORKING])]));
    await expect(page.getByTestId("book-order")).toHaveCount(0);
    await expect(page.getByTestId("book-orders")).toHaveCount(0);
  }
});
