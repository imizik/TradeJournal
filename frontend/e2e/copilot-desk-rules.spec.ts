import { expect, test, type Page } from "@playwright/test";

// His own trading rules on the desk (docs/copilot-lab.md § My rules): Paper › Rules edits the list; the paper confirm and
// the Ticket's Copy show the checklist with the automatic checks already marked and his tick-boxes; a broken rule says so
// in one line and never disables the order; the paper order carries his answers and Copy all keeps the real checklist
// with the plan; the score line splits closed trades followed versus broken, a tap opens it per rule. Every route is
// stubbed with invented numbers, so nothing reaches the e2e backend.
const ON = {
  enabled: true, backend: "fake", evidence: "live", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
const NOW = new Date("2026-11-13T16:00:00Z"); // Friday 11:00 New York
const epoch = (iso: string) => Date.parse(iso) / 1000;
const RULES = [
  { id: "r_size000001", text: "Never more than 5% on one trade", check: { kind: "max_size_pct", n: 5 } },
  { id: "r_stop000001", text: "Stop before I enter", check: { kind: "stop_set" } },
  { id: "r_wait000001", text: "Wait out the first 15 minutes", check: { kind: "no_open_minutes", n: 15 } },
  { id: "r_aplus00001", text: "Only A+ setups", check: null },
];
const result = (rule: (typeof RULES)[number], status: string, reason: string) => ({ id: rule.id, text: rule.text, kind: rule.check?.kind ?? "tick", n: null, status, reason });
const stats = (pnl: number, trades: number, win: number | null) => ({ trades, pnl, win_rate: win, avg_win: null, avg_loss: null, largest_loss: null, curve: [] });
const g = (pnl: number, trades: number, win: number | null) => ({ trades, pnl, win_rate: win });
const SPLIT = {
  followed: g(184.5, 3, 66.7), broken: g(-260, 2, 0), unclear: g(0, 0, null), unrecorded: 1,
  by_rule: [
    { id: "r_size000001", text: "Never more than 5% on one trade", current: true, followed: g(64.5, 4, 50), broken: g(-140, 1, 0), unchecked: 0 },
    { id: "r_stop000001", text: "Stop before I enter", current: true, followed: g(184.5, 3, 66.7), broken: g(-260, 2, 0), unchecked: 0 },
  ],
};
const BOOK = {
  run: { id: "r1", number: 1, starting_cash: 10000, started_at: epoch("2026-11-10T15:00:00Z") },
  account: { cash: 9924.5, collateral: 0, reserved: 0, buying_power: 9924.5, equity: 9924.5, pnl: -75.5, unpriced: 0, prices_at: null },
  positions: [], closed: [], orders: [],
  score: { paper: { ...stats(-75.5, 6, 33.3), open_pnl: null, by_source: [], rules: SPLIT }, real: stats(-312, 3, 33.3),
    real_rules: { ...SPLIT, followed: g(150, 1, 100), broken: g(0, 0, null), by_rule: [], checklists: 3, matched: 1, open: 1, unmatched: 1 } },
  my_rules: RULES, earlier: [], market_open: true,
};
const TICKET = {
  state: "ok", investigation_id: "inv-nbis", symbol: "NBIS", direction: "long", thesis: "Reclaim of 98", option_type: "call", entry: 98,
  invalidation: 95, time_stop: null, target: 108, plan_contract_words: null, size: { contracts: 2, risk_usd: null, text: "2 contracts" },
  accounts: [{ id: "a1", label: "Roth", last4: "8267", kind: "roth" }], account: "a1", simulated: false,
  contract: { strike: 100, expiry: "2026-11-20", type: "call", label: "NBIS $100 Call 11/20/26", source: "plan", multiplier: 100 },
  candidates: null, quote: { state: "ok", as_of: NOW.getTime() / 1000 - 30, bid: 3.3, ask: 3.4, mid: 3.35, spread: 0.1, spread_pct: 3, multiplier: 100 },
  underlying: { state: "ok", last: 98.05, as_of: NOW.getTime() / 1000 - 30 }, expected_move_pct: null, limit: 3.35, contracts: 2, spread: null, check: null,
};
const THREADS = {
  as_of: "2026-11-13T16:00:00Z", quotes_at: null, quote_issue: null, day: { phase: "regular", need_you: 0, streak: null },
  sections: { positions: "ok" }, plans: [], robinhood: { state: "off" }, threads: [
    // A real position on NBIS, so the desk's selected ticker is NBIS and the Paper section offers paper shares of it.
    { key: "trade:33333333-3333-4333-8333-333333333333", group: "watch", symbol: "NBIS", title: "NBIS 11/20/26 100C", instrument: "11/20/26 100C",
      value: { text: "+$220.00", tone: "gain" }, status: { text: "On plan", tone: "muted" }, meter: null, investigation_id: null,
      trade_id: "33333333-3333-4333-8333-333333333333", radar_event_id: null, path: null, changed_at: null,
      book: { usd: 220, pct: 35.5, expiry: "2026-11-20", days_held: 1, track: null, state: "on_plan", planned: true, quantity: 2, mark: 420, live: "matched" } },
  ],
};
const READS: Record<string, unknown> = {
  "/copilot/desk/threads": THREADS,
  "/copilot/desk/watching": { state: "ok", symbols: [], count: 0, max: 30, imported_at: null, robinhood: "off", levels: {}, setups: {} },
  "/copilot/desk/sparks": { as_of: "2026-11-13T16:00:00Z", spy_change_pct: 0.4, rows: {} },
  "/copilot/investigations": { investigations: [] },
  "/copilot/tickets": { plans: [] },
  "/copilot/tickets/inv-nbis": TICKET,
  "/copilot/exposure": { line: null },
  "/copilot/paper": BOOK,
};

async function open(page: Page, width: number, path = "/copilot-lab") {
  const seen = { orders: [] as Record<string, unknown>[], checks: [] as Record<string, unknown>[], saves: [] as unknown[], tickets: [] as Record<string, unknown>[] };
  await page.setViewportSize({ width, height: 900 });
  await page.clock.install({ time: NOW });
  await page.route("**/api/backend/**", route => route.fulfill({ status: 404, json: { detail: "Not in this test." } }));
  await page.route("**/copilot/status", route => route.fulfill({ json: ON }));
  await page.route("**/copilot/chat", route => route.abort());
  for (const [p, body] of Object.entries(READS)) await page.route(url => url.pathname.endsWith(p), route => route.fulfill({ json: body }));
  await page.route("**/copilot/desk/minute?*", route => {
    const reads = new URL(route.request().url()).searchParams.getAll("read").map(target => {
      const body = READS[target.split("?")[0]];
      return body ? { status: 200, body } : { status: 404, body: { detail: "Not in this test." } };
    });
    return route.fulfill({ json: { reads } });
  });
  await page.route("**/copilot/rules", route => {
    seen.saves.push(route.request().postDataJSON());
    return route.fulfill({ json: { rules: RULES } });
  });
  await page.route("**/copilot/rules/check", route => {
    const body = route.request().postDataJSON();
    seen.checks.push(body);
    const real = body.side === "real";
    return route.fulfill({ json: { rules: RULES, results: [
      result(RULES[0], body.size > (real ? 1000 : 500) ? "fail" : "pass", `$${Number(body.size).toFixed(2)} is ${(body.size / (real ? 200 : 99.245)).toFixed(1)}% of ${real ? "Roth ••8267 at $20,000.00 (10:58 AM ET)" : "paper cash $9,924.50"}.`),
      body.stop ? result(RULES[1], "pass", `Stop at ${body.stop}.`) : result(RULES[1], "fail", "No stop set."),
      result(RULES[2], "unknown", "The market calendar could not be read."),
      result(RULES[3], "ask", "Tick it if this trade follows it."),
    ] } });
  });
  await page.route("**/copilot/rules/ticket", route => {
    seen.tickets.push(route.request().postDataJSON());
    return route.fulfill({ json: { recorded: true, outcome: "followed", results: [] } });
  });
  await page.route("**/copilot/paper/orders", route => {
    const body = route.request().postDataJSON();
    seen.orders.push(body);
    const fill = { label: "NBIS shares", per_share: -98.1, stock: 98.05, legs: { NBIS: { action: "buy", bid: 98, ask: 98.1, price: 98.1 } },
      quantity: body.quantity, cash: -98.1 * body.quantity, quoted_at: NOW.getTime() / 1000 - 2, buying_power: 9924.5, need_each: 98.1 };
    return route.fulfill({ json: body.preview ? { preview: fill } : { filled: { ...fill, position_id: "p-new" } } });
  });
  await page.goto(path);
  return seen;
}

async function paperSection(page: Page, width: number) {
  if (width < 768) await page.getByTestId("desk-view-book").click();
  return page.getByTestId("desk-paper");
}

for (const width of [1440, 375]) {
  test(`the paper confirm shows his rules, says a broken one in one line and still fills, with his answers, at ${width}px`, async ({ page }) => {
    const seen = await open(page, width);
    const paper = await paperSection(page, width);
    const button = paper.getByTestId("paper-button");
    await expect(button).toHaveText("Paper buy NBIS shares");
    await button.click();
    const confirm = paper.getByTestId("paper-confirm");
    const list = confirm.getByTestId("rules-checklist");
    await expect(list.getByTestId("rules-row")).toHaveCount(4);
    // 10 shares at 98.10 = $981 > 5% of paper cash: broken; no stop: broken; the calendar: can't check, never a pass.
    await expect(list.getByTestId("rules-broken")).toHaveText("· breaks 3 of 4. You can still go ahead.");
    await expect(list.locator('[data-status="unknown"]')).toContainText("Can't check: The market calendar could not be read.");
    await confirm.getByLabel("Paper stop (stock price)").fill("95");
    await list.getByLabel("Only A+ setups").check();
    await expect(list.getByTestId("rules-broken")).toHaveText("· breaks 1 of 4. You can still go ahead.");
    expect(seen.checks.at(-1)).toMatchObject({ side: "paper", instrument: "stock", size: 981, stop: 95 });
    await expect(confirm.getByTestId("paper-fill")).toBeEnabled();
    await confirm.getByTestId("paper-fill").click();
    await expect(confirm.getByTestId("paper-done")).toBeVisible();
    expect(seen.orders.at(-1)).toMatchObject({ action: "open", stop: 95, rule_answers: { r_aplus00001: true } });
  });
}

test("the Ticket's Copy all keeps the real checklist with the plan and the account", async ({ page }) => {
  const seen = await open(page, 1440, "/copilot-lab?ticket=inv-nbis");
  const ticket = page.getByTestId("desk-ticket");
  const list = ticket.getByTestId("rules-checklist").first();
  await expect(list.getByTestId("rules-row")).toHaveCount(4);
  await expect(list.locator('[data-status="pass"]').first()).toContainText("$670.00 is 3.4% of Roth ••8267 at $20,000.00");
  expect(seen.checks.find(c => c.side === "real")).toMatchObject({ instrument: "option", expiry: "2026-11-20", size: 670, stop: 95, last4: "8267" });
  await list.getByLabel("Only A+ setups").check();
  await page.context().grantPermissions(["clipboard-read", "clipboard-write"]);
  await ticket.getByRole("button", { name: "Copy all for Robinhood" }).click();
  await expect(ticket.getByTestId("rules-kept")).toContainText("Checklist kept with this copy");
  expect(seen.tickets).toHaveLength(1);
  expect(seen.tickets[0]).toMatchObject({ investigation_id: "inv-nbis", symbol: "NBIS", side: "real", last4: "8267", answers: { r_aplus00001: true } });
});

for (const width of [1440, 375]) {
  test(`Paper › Rules edits the list and the score line splits followed versus broken, per rule on a tap, at ${width}px`, async ({ page }) => {
    const seen = await open(page, width);
    const paper = await paperSection(page, width);
    const split = paper.getByTestId("rules-split");
    await expect(split).toContainText("Paper followed +$184.50 66.7%/3 · broken −$260.00 0%/2");
    await expect(split).toContainText("Real followed +$150.00 100%/1 · broken — · 1 copied, not matched to a fill, 1 still open");
    await split.getByRole("button").click();
    const table = split.getByTestId("rules-by-rule");
    await expect(table.getByTestId("rules-by-rule-row").filter({ hasText: "Stop before I enter" })).toContainText("followed +$184.50 66.7%/3broken −$260.00 0%/2");
    await paper.getByTestId("rules-toggle").click();
    const editor = paper.getByTestId("rules-editor");
    await expect(editor.getByTestId("rules-editor-row")).toHaveCount(4);
    await editor.getByRole("button", { name: "Add a rule" }).click();
    await editor.getByLabel("Rule 5", { exact: true }).fill("No new trades after two losers");
    await editor.getByLabel("Rule 1 N").fill("4");
    await editor.getByTestId("rules-save").click();
    await expect(editor).toBeHidden();
    expect(seen.saves.at(-1)).toMatchObject({ rules: [
      { id: "r_size000001", text: "Never more than 5% on one trade", check: { kind: "max_size_pct", n: 4 } },
      { id: "r_stop000001", check: { kind: "stop_set" } }, { id: "r_wait000001", check: { kind: "no_open_minutes", n: 15 } },
      { id: "r_aplus00001", check: null }, { text: "No new trades after two losers", check: null }] });
  });
}
