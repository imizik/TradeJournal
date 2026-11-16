import { expect, test, type Page } from "@playwright/test";

// The copilot's paper order card (docs/copilot-lab.md § Paper): "paper 2 NBIS 100c Friday, stop 96" comes back as one card
// with the contract, the live price it would fill at and its time, the cost and the paper buying power left, and his
// stop. Nothing is filled until Fill on paper, which goes through the paper book's own route with one key; a price older
// than the book's freshness window is greyed with its time and the button is off until Refresh price reads a new one;
// Edit opens the full confirm prefilled; a close card fills at the bid. Every lab route is stubbed in the browser (the
// e2e backend runs with the lab off): no model, no Robinhood. Invented numbers.
const ON = {
  enabled: true, backend: "fake", evidence: "live", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
const NOW = new Date("2026-11-13T16:00:00Z"); // Friday 11:00 New York
const epoch = (iso: string) => Date.parse(iso) / 1000;
const QUOTED = epoch("2026-11-13T15:59:56Z");
const MAIN = "77777777-7777-4777-8777-777777777777";
const POSITION = "11111111-1111-4111-8111-111111111111";
const THREADS = { as_of: "2026-11-13T16:00:00Z", quotes_at: null, quote_issue: null, day: { phase: "regular", need_you: 0, streak: null },
  sections: { positions: "ok" }, plans: [], robinhood: { state: "off" },
  threads: [{ key: "briefing", group: "pinned", title: "Briefing", status: { text: "Nothing new.", tone: "muted" }, symbol: null, instrument: null,
    value: null, meter: null, investigation_id: null, trade_id: null, radar_event_id: null, path: null, changed_at: null }] };
const SESSION = { as_of: "2026-11-13T16:00:00Z", now: epoch("2026-11-13T16:00:00Z"), day: "2026-11-13", phase: "regular",
  open: epoch("2026-11-13T14:30:00Z"), close: epoch("2026-11-13T21:00:00Z"), events: [], time_stops: [], pings: null, prep: null,
  indices: [{ symbol: "SPY", last: 580.1, change_pct: 0.42 }], quote_issue: null, realized_today: 0, sections: {} };
const main = () => ({ id: MAIN, source: "copilot", title: "Main chat", symbol: null, status: "open", conclusion: null,
  revision: 1, message_count: 0, has_findings: false, created_at: "2026-11-13T14:00:00Z", updated_at: "2026-11-13T15:00:00Z", evidence: [],
  findings: null, transcript: [] as unknown[], main_day: "2026-11-13" });

const OPEN_CARD = { type: "proposal", id: "p_open", kind: "paper_order", action: "open", symbol: "NBIS", instrument: "option", quantity: 2,
  option_type: "call", expiry: "2026-11-20", strike: 100, stop: 96, idea: "mine", label: "NBIS $100 Call 11/20/26", multiplier: 100,
  picked: ["$101 is not a listed strike; the nearest is $100."], issue: null, made_at: QUOTED,
  preview: { per_share: -3.4, cash: -680, quoted_at: QUOTED, stock: 98.05, price: 3.4, side: "ask", buying_power: 9309.5, buying_power_after: 8629.5 } };
const CLOSE_CARD = { type: "proposal", id: "p_close", kind: "paper_order", action: "close", symbol: "NBIS", position_id: POSITION,
  instrument: "option", credit: false, held: 2, quantity: 2, remains: 0, label: "NBIS $100 Call 11/20/26", multiplier: 100, picked: [],
  issue: null, made_at: QUOTED, preview: { per_share: 4.1, cash: 820, quoted_at: QUOTED, stock: 99.1, price: 4.1, side: "bid", pnl: 140 } };

const sse = (cards: unknown[]) => [
  ...cards.map((c) => ({ type: "tool", id: (c as { id: string }).id, name: "draft_paper_order", status: "ok", summary: "paper order",
    provenance: { source: "A paper order card for the owner to tap; nothing filled", kind: "proposal", as_of: null } })),
  ...cards, { type: "text", delta: "Here it is on paper: tap Fill on paper." },
  { type: "done", metrics: { backend: "fake", evidence: "live", model: "fake-scripted", first_text_ms: 1, total_ms: 2, rounds: 2, tool_calls: [],
    usage: { input_tokens: 0, output_tokens: 0, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 }, cost_usd: 0 } },
].map((e) => `data: ${JSON.stringify(e)}\n\n`).join("");

async function desk(page: Page, cards: unknown[], width = 1440) {
  const orders: Record<string, unknown>[] = [];
  const outcomes: { id: string; body: { state: string; note?: string } }[] = [];
  let current = main();
  await page.setViewportSize({ width, height: 900 });
  await page.clock.install({ time: NOW });
  await page.route("**/copilot/status", (r) => r.fulfill({ json: ON }));
  await page.route("**/copilot/desk/threads", (r) => r.fulfill({ json: THREADS }));
  await page.route("**/copilot/desk/session", (r) => r.fulfill({ json: SESSION }));
  await page.route("**/copilot/desk/pings*", (r) => r.fulfill({ json: { day: "2026-11-13", since: "2026-11-12", alerts: { state: "ok", rows: [] }, radar: { state: "off", reason: null, rows: [] } } }));
  await page.route("**/copilot/desk/feed", (r) => r.fulfill({ json: { as_of: "2026-11-13T16:00:00Z", now: epoch("2026-11-13T16:00:00Z"), day: "2026-11-13", total: 0, sources: {}, unavailable: [], items: [] } }));
  await page.route("**/copilot/desk/sparks?*", (r) => r.fulfill({ json: { as_of: "2026-11-13T16:00:00Z", spy_change_pct: 0.4, rows: {} } }));
  await page.route("**/copilot/investigations?*", (r) => r.fulfill({ json: { investigations: [] } }));
  await page.route("**/copilot/main-chat", (r) => r.fulfill({ json: current }));
  await page.route("**/copilot/main-chat/history*", (r) => r.fulfill({ json: { conversations: [] } }));
  await page.route(`**/copilot/investigations/${MAIN}`, (r) => r.fulfill({ json: current }));
  await page.route(`**/copilot/main-chat/${MAIN}/exchange`, async (r) => {
    const transcript = [...current.transcript, ...r.request().postDataJSON().transcript];
    current = { ...current, transcript, message_count: transcript.length, revision: current.revision + 1 };
    await r.fulfill({ json: current });
  });
  await page.route(`**/copilot/investigations/${MAIN}/proposals/*/outcome`, async (r) => {
    outcomes.push({ id: decodeURIComponent(new URL(r.request().url()).pathname.split("/").at(-2)!), body: r.request().postDataJSON() });
    await r.fulfill({ json: current });
  });
  await page.route("**/copilot/rules/check", (r) => r.fulfill({ json: { results: [] } }));
  await page.route("**/copilot/chat", (r) => r.fulfill({ status: 200, headers: { "content-type": "text/event-stream" }, body: sse(cards) }));
  await page.route("**/copilot/paper/orders", (r) => {
    const body = r.request().postDataJSON();
    orders.push(body);
    const quoted = Date.now() / 1000 - 2;
    if (body.action === "close") {
      const fill = { label: "NBIS $100 Call 11/20/26", quantity: body.quantity, per_share: 4.1, cash: 410 * body.quantity, quoted_at: quoted, stock: 99.1,
        legs: { NBIS261120C00100000: { action: "sell", bid: 4.1, ask: 4.2, price: 4.1 } }, pnl: 70 * body.quantity, all: true };
      return r.fulfill({ json: body.preview ? { preview: fill } : { filled: fill } });
    }
    const fill = { label: "NBIS $100 Call 11/20/26", quantity: body.quantity, per_share: -3.5, cash: -350 * body.quantity, quoted_at: quoted, stock: 98.2,
      legs: { NBIS261120C00100000: { action: "buy", bid: 3.4, ask: 3.5, price: 3.5 } }, buying_power: 9309.5,
      buying_power_after: 9309.5 - 350 * body.quantity, need_each: 350 };
    return r.fulfill({ json: body.preview ? { preview: fill } : { filled: { ...fill, position_id: POSITION } } });
  });
  await page.route("**/copilot/desk/*/{picture,chart}*", (r) => r.fulfill({ status: 503, json: { detail: "No chart in this test." } }));
  await page.goto(`/copilot-lab?thread=${MAIN}`);
  await expect(page.getByTestId("desk-book")).toBeVisible();
  await page.getByLabel("Message").fill("paper 2 NBIS 101c Friday, stop 96");
  await page.getByLabel("Message").press("Enter");
  return { orders, outcomes };
}

const cardOf = (page: Page, action: string) => page.getByTestId("paper-order-card").and(page.locator(`[data-action="${action}"]`));

for (const width of [1440, 375]) {
  test(`one tap fills the drafted paper order through the paper route, and nothing before it, at ${width}px`, async ({ page }) => {
    const { orders, outcomes } = await desk(page, [OPEN_CARD], width);
    const card = cardOf(page, "open");
    await expect(card.getByTestId("paper-order-line")).toHaveText("Buy 2 × NBIS $100 Call 11/20/26");
    await expect(card.getByTestId("mode-mark")).toHaveAttribute("data-mode", "paper");
    await expect(card.getByTestId("paper-order-picked")).toHaveText("$101 is not a listed strike; the nearest is $100.");
    await expect(card.getByTestId("paper-order-price")).toContainText("Fills at the ask 3.40 · quote 10:59:56 AM ET");
    await expect(card.getByTestId("paper-order-price")).toContainText("Costs $680.00 · buying power left $8,629.50");
    await expect(card.getByTestId("paper-order-levels")).toHaveText("Stop 96 (stock prices)");
    if (width < 768) expect((await card.boundingBox())!.width).toBeLessThanOrEqual(375);
    expect(orders).toEqual([]); // the card alone fills nothing
    await expect(card.getByTestId("paper-order-fill")).toBeEnabled(); // once his rules are on the card
    await card.screenshot({ path: test.info().outputPath(`paper-order-card-${width}.png`) });
    await card.getByTestId("paper-order-fill").click();
    await expect(card.getByTestId("paper-order-done")).toContainText("Paper: bought 2 × NBIS $100 Call 11/20/26 at 3.50 (the ask)");
    expect(orders).toHaveLength(1);
    expect(orders[0]).toMatchObject({ action: "open", instrument: "option", symbol: "NBIS", option_type: "call", expiry: "2026-11-20", strike: 100,
      quantity: 2, stop: 96, target: null });
    expect(orders[0]).not.toHaveProperty("preview");
    expect(orders[0]).not.toHaveProperty("source"); // he dictated it: his own ("mine", the default)
    expect(String(orders[0].order_key)).toMatch(/^paper-card-[A-Za-z0-9_-]+$/);
    await expect.poll(() => outcomes.find((o) => o.id === "p_open")?.body.state).toBe("confirmed");
    await expect(card.getByTestId("paper-order-fill")).toHaveCount(0);
  });
}

test("a price older than the freshness window is greyed with its time and refreshed before Fill", async ({ page }) => {
  const old = { ...OPEN_CARD, preview: { ...OPEN_CARD.preview, quoted_at: epoch("2026-11-13T15:50:00Z") } };
  const { orders } = await desk(page, [old]);
  const card = cardOf(page, "open");
  await expect(card.getByTestId("paper-order-price")).toHaveAttribute("data-fresh", "false");
  await expect(card.getByTestId("paper-order-price")).toContainText("quote 10:50:00 AM ET, not live");
  await expect(card.getByTestId("paper-order-fill")).toBeDisabled();
  await card.getByTestId("paper-order-refresh").click();
  await expect(card.getByTestId("paper-order-price")).toHaveAttribute("data-fresh", "true");
  await expect(card.getByTestId("paper-order-price")).toContainText("Fills at the ask 3.50");
  expect(orders).toEqual([expect.objectContaining({ preview: true, action: "open", quantity: 2 })]);
  await expect(card.getByTestId("paper-order-fill")).toBeEnabled();
});

test("no live price at the draft says why and keeps the button off; Edit opens the full confirm prefilled", async ({ page }) => {
  const none = { ...OPEN_CARD, preview: null, picked: [], issue: "The market is closed: paper orders fill only in the regular session, on a live quote." };
  await desk(page, [none]);
  const card = cardOf(page, "open");
  await expect(card.getByTestId("paper-order-price")).toContainText("No live price: The market is closed");
  await expect(card.getByTestId("paper-order-fill")).toBeDisabled();
  await card.getByTestId("paper-order-edit").click();
  const confirm = card.getByTestId("paper-confirm");
  await expect(confirm.getByTestId("paper-preview")).toContainText("Buy 2 × NBIS $100 Call 11/20/26 at 3.50 (the ask");
  await expect(confirm.getByLabel("Paper stop (stock price)")).toHaveValue("96"); // prefilled, so More is open
});

test("a close card fills all of his paper position at the bid", async ({ page }) => {
  const { orders } = await desk(page, [CLOSE_CARD]);
  const card = cardOf(page, "close");
  await expect(card.getByTestId("paper-order-line")).toHaveText("Close NBIS $100 Call 11/20/26 · all 2");
  await expect(card.getByTestId("paper-order-price")).toContainText("Fills at the bid 4.10");
  await expect(card.getByTestId("paper-order-price")).toContainText("Brings in $820.00 · P&L +$140.00");
  await card.getByTestId("paper-order-fill").click();
  await expect(card.getByTestId("paper-order-done")).toContainText("made $140.00");
  expect(orders).toEqual([expect.objectContaining({ action: "close", position_id: POSITION, quantity: 2 })]);
});
