import { expect, test, type Page } from "@playwright/test";

// The Ticket's Play check (docs/copilot-lab.md § Ticket, "Play check"): the plan's parts, his flagged habits judged
// before the entry, and what holding it overnight costs, beside the same-delta alternatives. Compact when clean; opens
// only for a missing part, a habit that fired or a hold past today's close. Every lab route is stubbed in the browser
// with invented numbers; nothing reaches a model, a broker or Robinhood.
const ON = {
  enabled: true, backend: "fake", evidence: "live", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
const NOW = new Date("2026-11-12T16:05:00Z"); // Thursday 11:05 New York
const epoch = (iso: string) => Date.parse(iso) / 1000;
const DESK = { as_of: "2026-11-12T16:05:00Z", quotes_at: null, quote_issue: null, day: { phase: "regular", need_you: 0, streak: null },
  sections: { positions: "ok", plans: "ok" }, plans: [], robinhood: null, threads: [] };
const SESSION = {
  as_of: "2026-11-12T16:05:00Z", now: epoch("2026-11-12T16:05:00Z"), day: "2026-11-12", phase: "regular",
  open: epoch("2026-11-12T14:30:00Z"), close: epoch("2026-11-12T21:00:00Z"), events: [], time_stops: [], pings: null, prep: null,
  indices: [], quote_issue: null, realized_today: 0, sections: {}, to_answer: { alerts: { count: 0, rows: [] }, radar: null },
};
const AS_OF = epoch("2026-11-12T16:04:00Z");
const PLAY_CLEAN = { lines: [{ part: "stop", ok: true, text: "out at 92.3" }, { part: "time", ok: true, text: "out by Friday 3:30 PM" },
  { part: "size", ok: true, text: "2 contracts" }], missing: [], fill: null };
const QUIET_HABITS = { state: "ok", fired: [], size: null, footer: "Your record, not advice." };
const ROWS = [
  { name: "as_traded", label: "NBIS $100 Call 11/21/26", unit: "contracts", state: "ok", units: 1, cost: 320, credit: false, max_loss: 320, max_loss_note: null,
    decay_day: 10, decay_pct: 3.1, hold_cost: 41.5, hold_cost_pct: 13, breakeven: 101.9, breakeven_move_pct: 7.26, vs_expected: 1.4 },
  { name: "deeper", label: "NBIS $92.5 Call 11/21/26", unit: "contracts", state: "ok", units: 0.57, cost: 400, credit: false, max_loss: 400, max_loss_note: null,
    decay_day: 4.57, decay_pct: 1.1, hold_cost: 18, hold_cost_pct: 4.5, breakeven: 97.2, breakeven_move_pct: 2.32, vs_expected: 0.5 },
  { name: "spread", label: "NBIS $100/$107.5 Call 11/21/26 spread", unit: "spreads", state: "stale", as_of: epoch("2026-11-12T15:30:00Z"),
    reason: "The latest bid and ask are too old to price an order from." },
  { name: "later", label: "NBIS $100 Call 12/18/26", unit: "contracts", state: "ok", units: 0.89, cost: 533.33, credit: false, max_loss: 533.33, max_loss_note: null,
    decay_day: 4.44, decay_pct: 0.8, hold_cost: 9, hold_cost_pct: 1.7, breakeven: 98.4, breakeven_move_pct: 3.58, vs_expected: 0.7 },
  { name: "shares", label: "NBIS shares", unit: "shares", state: "ok", units: 40, cost: 3800, credit: false, max_loss: 3800, max_loss_note: null,
    decay_day: 0, decay_pct: 0, hold_cost: 0, hold_cost_pct: 0, breakeven: 95, breakeven_move_pct: 0, vs_expected: 0 },
];
const NIGHT = { state: "ok", show: true, until: epoch("2026-11-13T20:30:00Z"), until_source: "time stop", expires_first: false, trading_days: 1,
  hold_days: 1.18, greeks_as_of: "2026-11-12 11:00:00", expected_move_pct: 5.1, basis: "per contract", rows: ROWS };
const TICKET = {
  state: "ok", investigation_id: "inv-nbis", symbol: "NBIS", direction: "long", thesis: "Reclaims VWAP with the group", option_type: "call", entry: 95.9,
  invalidation: 92.3, time_stop: "out by Friday 3:30 PM", plan_contract_words: null, size: { contracts: 2, risk_usd: null, text: "2 contracts" }, simulated: false,
  account: "roth", accounts: [{ id: "roth", label: "Roth IRA", last4: "8267", kind: "roth" }],
  contract: { strike: 100, expiry: "2026-11-21", type: "call", label: "NBIS $100 Call 11/21/26", source: "plan", multiplier: 100 },
  candidates: null, quote: { state: "ok", as_of: AS_OF, bid: 3.1, ask: 3.3, mid: 3.2, spread: 0.2, spread_pct: 6.3, multiplier: 100 },
  underlying: { state: "ok", last: 95, as_of: AS_OF }, expected_move_pct: 6, limit: 3.2, contracts: 2,
  check: { play: PLAY_CLEAN, habits: QUIET_HABITS, overnight: { ...NIGHT, show: false, until_source: "next close" } },
};

async function open(page: Page, ticket: object, { width = 1440, height = 900 } = {}) {
  const methods: string[] = [];
  page.on("request", request => { if (/\/copilot\/tickets/.test(request.url())) methods.push(request.method()); });
  await page.setViewportSize({ width, height });
  await page.clock.install({ time: NOW });
  await page.route("**/copilot/status", route => route.fulfill({ json: ON }));
  await page.route("**/copilot/desk/threads", route => route.fulfill({ json: DESK }));
  await page.route("**/copilot/desk/session", route => route.fulfill({ json: SESSION }));
  await page.route("**/copilot/desk/pings*", route => route.fulfill({ json: { day: "2026-11-12", since: "2026-11-11", alerts: { state: "ok", rows: [] }, radar: { state: "off", reason: null, rows: [] } } }));
  await page.route("**/copilot/desk/sparks?*", route => route.fulfill({ json: { as_of: "2026-11-12T16:05:00Z", spy_change_pct: 0.4, rows: {} } }));
  await page.route("**/copilot/desk/feed", route => route.fulfill({ json: { as_of: "2026-11-12T16:05:00Z", now: epoch("2026-11-12T16:05:00Z"), day: "2026-11-12", total: 0, sources: {}, unavailable: [], items: [] } }));
  await page.route("**/copilot/desk/*/{picture,chart}*", route => route.fulfill({ status: 503, json: { detail: "No chart in this test." } }));
  await page.route("**/copilot/investigations?*", route => route.fulfill({ json: { investigations: [] } }));
  await page.route("**/copilot/main-chat", route => route.fulfill({ status: 404, json: { detail: "none" } }));
  await page.route("**/copilot/main-chat/history*", route => route.fulfill({ json: { conversations: [] } }));
  await page.route("**/copilot/chat", route => route.abort());
  await page.route("**/copilot/tickets", route => route.fulfill({ json: { plans: [{ investigation_id: "inv-nbis", symbol: "NBIS", direction: "long",
    instrument: "calls", thesis: "Reclaims VWAP with the group", confirmed_at: epoch("2026-11-12T15:55:00Z"), entry: 95.9, invalidation: 92.3 }] } }));
  await page.route(/\/copilot\/tickets\/[^/]+$/, route => route.fulfill({ json: ticket }));
  await page.goto("/copilot-lab?ticket=inv-nbis");
  const check = page.getByTestId("play-check");
  await expect(check).toBeVisible();
  return { check, methods };
}

test("clean: the play and the habits are two quiet lines, and the overnight figures stay folded", async ({ page }) => {
  const { check, methods } = await open(page, TICKET);
  await expect(check.getByTestId("play-line")).toHaveText("Play✓ out at 92.3 · ✓ out by Friday 3:30 PM · ✓ 2 contracts");
  await expect(check.getByTestId("play-habits")).toHaveText("Your habitsnone of your flagged habits");
  await expect(check.getByTestId("play-overnight")).toHaveCount(0);
  await check.getByRole("button", { name: "If you held it to the next close" }).click();
  await expect(check.getByTestId("play-overnight")).toContainText("Time decay: $20.00 a day (3.1% of the premium)"); // $10 a contract x 2
  expect(methods.length > 0 && methods.every(m => m === "GET")).toBe(true); // the ticket and its check only read
});

test("missing parts are said plainly, with what to fill and a link to the plan", async ({ page }) => {
  const play = { lines: [{ part: "stop", ok: true, text: "out at 92.3" }, { part: "time", ok: false, text: "missing: no time stop" },
    { part: "size", ok: false, text: "missing: no size (contracts or dollars at risk)" }], missing: ["time", "size"], fill: "Add a time stop and a size to the plan." };
  const { check } = await open(page, { ...TICKET, check: { ...TICKET.check, play } });
  const lines = check.getByTestId("play-line");
  await expect(lines).toContainText("Time: missing: no time stop");
  await expect(lines).toContainText("Size: missing: no size (contracts or dollars at risk)");
  await expect(lines).toContainText("Add a time stop and a size to the plan.");
  await expect(lines.getByRole("link", { name: "Edit the plan" })).toHaveAttribute("href", "/copilot-lab?investigation=inv-nbis");
  // Nothing is blocked: the ticket still copies.
  await expect(page.getByRole("button", { name: "Copy all for Robinhood" })).toBeEnabled();
});

test("a habit that fired shows his record line; the size rule follows the count he types", async ({ page }) => {
  const habits = { state: "ok", footer: "Your record, not advice.",
    fired: [{ kind: "late_short_dated", line: "Late short-dated buy: 12 past buys after 2 PM with 0–2 days left, 58% expired worthless, −$3,100" }],
    size: { median: 300, multiple: 2, tail: "your 9 past entries above 2×: 33% won, −$1,450" } };
  const { check } = await open(page, { ...TICKET, check: { ...TICKET.check, habits } });
  const block = check.getByTestId("play-habits");
  await expect(block).toContainText("Late short-dated buy: 12 past buys after 2 PM with 0–2 days left, 58% expired worthless, −$3,100");
  // 2 contracts at 3.20 is $640: over twice his $300 median.
  await expect(block).toContainText("Size: $640 is 2.1× your median ($300); your 9 past entries above 2×: 33% won, −$1,450");
  await expect(block).toContainText("Your record, not advice.");
  await page.getByLabel("Quantity in contracts").fill("1"); // $320: under twice the median
  await expect(block).not.toContainText("Size:");
  await expect(block).toContainText("Late short-dated buy");
});

for (const width of [1440, 393]) {
  test(`at ${width} px: a hold past today's close shows the decay, the break-even and the same-delta alternatives`, async ({ page }) => {
    const { check } = await open(page, { ...TICKET, check: { ...TICKET.check, overnight: NIGHT } }, { width, height: width < 768 ? 852 : 900 });
    const night = check.getByTestId("play-overnight");
    await expect(night).toContainText("1 trading day");
    await expect(night).toContainText("For your 2 contracts");
    await expect(night).toContainText("Time decay: $20.00 a day (3.1% of the premium) · theta as of 2026-11-12 11:00:00");
    await expect(night).toContainText("If NBIS does not move: −$83.00 (13%) by then. Break-even then: NBIS 101.90 (+7.3%) vs ±5.1% expected over that time");
    const alts = night.getByTestId("play-alt");
    await expect(alts).toHaveCount(4);
    await expect(alts.nth(0)).toContainText("Deeper NBIS $92.5 Call 11/21/26");
    await expect(alts.nth(0)).toContainText("1.14 contracts · costs $800.00 · most you can lose $800.00 · $9.14 a day · break-even then 97.20 (+2.3%)");
    await expect(alts.nth(1)).toContainText("quote stale (last 10:30 AM ET)"); // grey, no number
    await expect(alts.nth(1)).not.toContainText("costs");
    await expect(alts.nth(3)).toContainText("80 shares · costs $7,600.00 · most you can lose $7,600.00 · no time decay");
    await expect(night).not.toContainText(/buy this|recommend|best/i);
    expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0);
  });
}

test("a put's short-share alternative is said as not in a Roth IRA", async ({ page }) => {
  const shortRow = { name: "shares", label: "Short NBIS shares", unit: "shares", state: "ok", units: 30, cost: 2850, credit: true, max_loss: null,
    max_loss_note: "no limit", decay_day: 0, decay_pct: 0, hold_cost: 0, hold_cost_pct: 0, breakeven: 95, breakeven_move_pct: 0, vs_expected: 0, note: "not in a Roth IRA" };
  const { check } = await open(page, { ...TICKET, contracts: 1, check: { ...TICKET.check, overnight: { ...NIGHT, rows: [ROWS[0], shortRow] } } });
  await expect(check.getByTestId("play-alt")).toContainText("Short NBIS shares · 30 shares · takes in $2,850.00 · most you can lose no limit · no time decay");
  await expect(check.getByTestId("play-alt")).toContainText("not in a Roth IRA");
});

test("a stale quote gives no overnight figures, only its time", async ({ page }) => {
  const stale = { state: "stale", show: false, as_of: epoch("2026-11-12T15:30:00Z"), reason: "The latest bid and ask are too old to price an order from." };
  const { check } = await open(page, { ...TICKET, check: { ...TICKET.check, overnight: stale } });
  await expect(check.getByTestId("play-overnight")).toHaveText("Holding overnight: quote stale (last 10:30 AM ET), no figures");
});
