import { expect, test, type Page } from "@playwright/test";

// The desk's Chain tab (docs/copilot-lab.md § Chain): one expiry of the selected ticker's option chain around the price,
// with held and planned contracts marked; tapping a contract offers Check it (Check a call, pre-filled), Plan it (the
// plan flow) and Put on ticket (a saved plan's ticket, copy only). Every lab route is stubbed in the browser, so no model
// runs, no provider is read and nothing reaches the e2e backend; the tab only reads.
const ON = {
  enabled: true, backend: "fake", evidence: "fixture", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
const INV = "66666666-6666-4666-8666-666666666666";
const record = {
  id: INV, source: "copilot", title: "Which NBIS call?", symbol: "NBIS", status: "open", conclusion: null, revision: 1,
  message_count: 2, has_findings: false, created_at: "2026-11-12T14:00:00Z", updated_at: "2026-11-12T14:00:00Z",
  transcript: [{ role: "user", content: "Which NBIS call?" }, { role: "assistant", content: "The group is bid; size small." }],
  evidence: [], findings: null,
};
const now = Math.floor(Date.now() / 1000);

function cell(strike: number, side: "call" | "put", extra: Record<string, unknown> = {}) {
  const intrinsic = side === "call" ? Math.max(95 - strike, 0) : Math.max(strike - 95, 0);
  const mark = Math.round((intrinsic + 2.5) * 100) / 100;
  return {
    symbol: `NBIS261113${side === "call" ? "C" : "P"}${String(strike * 1000).padStart(8, "0")}`, bid: mark - 0.1, ask: mark + 0.1, mark,
    last: null, spread: 0.2, spread_pct: Math.round(0.2 / mark * 1000) / 10, wide: false, spread_note: null, volume: 120, open_interest: 900,
    delta: side === "call" ? 0.5 : -0.5, iv: 64, quoted_at: now - 20, state: "ok", multiplier: 100, held: null, planned: false, ...extra,
  };
}

function chain(expiration = "2026-11-13") {
  const rows = [90, 92.5, 95, 97.5, 100, 102.5, 105].map(strike => ({
    strike, atm: strike === 95, levels: strike === 95 ? ["entry"] : [],
    call: cell(strike, "call", strike === 100 ? { held: 2, planned: true } : strike === 105 ? { bid: 0.3, ask: 0.5, mark: 0.4, spread: 0.2, spread_pct: 50, wide: true,
      spread_note: "Wide spread: $20 a contract between bid and ask (50% of the mark)" } : {}),
    put: cell(strike, "put", strike === 90 ? { state: "missing", bid: null, ask: null, mark: null, spread: null, spread_pct: null } : {}),
  }));
  return {
    symbol: "NBIS", state: "ok", session: "open", poll_seconds: 15, simulated: false, root: "NBIS", centred_on: "price",
    expiries: [{ date: "2026-11-12", days: 0, kind: "0dte", held: false }, { date: "2026-11-13", days: 1, kind: "weekly", held: true },
      { date: "2026-11-20", days: 8, kind: "monthly", held: false, earnings: true }],
    earnings: { date: "2026-11-19", status: "confirmed" },
    expiration, spot: 95.4, spot_at: now - 5, spot_issue: null, atm_strike: 95, fetched_at: now - 3, age_s: 3, stale: false, message: null,
    rows, levels: [{ role: "entry", price: 95.2, strike: 95 }],
  };
}

const TICKET = {
  state: "ok", investigation_id: INV, symbol: "NBIS", direction: "long", thesis: "Reclaims VWAP with the group", option_type: "call",
  entry: 95.9, invalidation: 92.3, time_stop: "out by 15:30", plan_contract_words: "NBIS 11/13 100C",
  size: { contracts: 2, risk_usd: null, text: "2 contracts" }, simulated: false, account: "roth",
  accounts: [{ id: "roth", label: "Roth IRA", last4: "8267", kind: "roth" }],
  contract: { strike: 102.5, expiry: "2026-11-13", type: "call", label: "NBIS $102.5 Call 11/13/26", source: "picked", multiplier: 100 },
  candidates: null, quote: { state: "ok", as_of: now - 30, bid: 2.4, ask: 2.6, mid: 2.5, spread: 0.2, spread_pct: 8, multiplier: 100 },
  underlying: { state: "ok", last: 95, as_of: now - 10 }, expected_move_pct: 6, limit: 2.5, contracts: 2,
};

async function lab(page: Page, plans: object[] = [], ticket: object = TICKET) {
  const chainReads: string[] = [];
  const methods: string[] = [];
  const tickets: string[] = [];
  await page.route("**/copilot/status", route => route.fulfill({ json: ON }));
  await page.route("**/copilot/investigations?*", route => route.fulfill({ json: { investigations: [] } }));
  await page.route(`**/copilot/investigations/${INV}`, route => route.fulfill({ json: record }));
  await page.route("**/copilot/chat", route => route.abort());
  await page.route("**/copilot/checks", route => { methods.push(`${route.request().method()} checks`); return route.fulfill({ json: { day: "2026-11-12", checks: [] } }); });
  await page.route(/\/copilot\/chain\?/, route => {
    methods.push(route.request().method());
    const url = new URL(route.request().url());
    chainReads.push(url.search);
    return route.fulfill({ json: chain(url.searchParams.get("expiration") ?? "2026-11-13") });
  });
  await page.route("**/copilot/tickets", route => route.fulfill({ json: { plans } }));
  await page.route("**/copilot/unusual", route => route.fulfill({ json: UNUSUAL }));
  await page.route(/\/copilot\/tickets\/[^/?]+(\?.*)?$/, route => {
    methods.push(route.request().method());
    const url = new URL(route.request().url());
    tickets.push(`${url.pathname.split("/").pop()}${url.search}`);
    return route.fulfill({ json: ticket });
  });
  await page.goto(`/copilot-lab?investigation=${INV}`);
  await expect(page.getByText("The group is bid; size small.")).toBeVisible();
  const back = page.getByRole("region", { name: "Conversation" }).getByRole("button", { name: "Back to the desk" });
  if (await back.isVisible()) await back.click(); // a phone opens the link on the copilot sheet
  const ticker = page.getByTestId("desk-view-ticker");
  if (await ticker.isVisible()) await ticker.click(); // and the desk on its Book: the ticker's tools are its second view
  const pane = page.getByRole("region", { name: "Chart and tools" });
  await pane.getByRole("tab", { name: "Chain" }).click();
  return { pane, chainReads, methods, tickets };
}

// Invented: one unusual NBIS put on the Nov 20 expiry; the Feed's Unusual options filter lists it.
const UNUSUAL = {
  state: "ok", session: "open", label: "live", day: "2026-11-12", rule: "Unusual: a contract that has traded at least 3× its open interest today",
  rows: [{ symbol: "NBIS", held: true, contract: "NBIS261120P00097500", side: "put", strike: 97.5, expiration: "2026-11-20", volume: 4200,
    open_interest: 900, ratio: 4.7, last: 3.1, read_at: now - 60, stale: false }],
  tickers: [{ symbol: "NBIS", held: true, side: "put", today: 9100, usual: 3500, multiple: 2.6, sessions: 20, read_at: now - 60, stale: false }],
  unread: ["AMD"], no_history: [], stale: [], held: ["NBIS"], message: null, simulated: false,
};

const PLAN = { investigation_id: INV, symbol: "NBIS", direction: "long", instrument: "calls", option_type: "call", thesis: "Reclaims VWAP with the group",
  confirmed_at: now - 600, entry: 95.9, invalidation: 92.3 };
// A newer share-buying plan in the same ticker: long too, but it has no option ticket, so a call pick never goes on it.
const STOCK_PLAN = { ...PLAN, investigation_id: "77777777-7777-4777-8777-777777777777", instrument: "stock", option_type: null, confirmed_at: now - 60 };

test("the chain shows the expiries, the money line and his marks; a new expiry reads that expiry", async ({ page }) => {
  const { pane, chainReads } = await lab(page);
  const tab = pane.getByTestId("desk-chain");
  await expect(tab.getByRole("table")).toBeVisible();
  const expiries = tab.getByRole("radiogroup", { name: "Expiry" }).getByRole("radio");
  await expect(expiries).toHaveText([/0DTE/, /Nov 13/, /Nov 20/]);
  await expect(expiries.nth(1)).toHaveAttribute("aria-checked", "true");
  await expect(tab.getByTestId("chain-price-line")).toContainText("NBIS 95.40");
  await expect(tab.locator("tr[data-strike='95']")).toContainText("ATM");
  await expect(tab.getByTestId("chain-held")).toHaveCount(1);
  await expect(tab.getByTestId("chain-planned")).toHaveCount(1);
  await expect(tab.getByTestId("chain-level")).toHaveText(["entry"]);
  await expect(tab.getByTestId("chain-age")).toContainText("Quotes");
  expect(chainReads[0]).toBe("?symbol=NBIS");
  await expiries.nth(2).click();
  await expect.poll(() => chainReads.at(-1)).toBe("?symbol=NBIS&expiration=2026-11-20");
});

test("tap a contract: Check it fills Check a call, and nothing is checked until he taps", async ({ page }) => {
  const { pane, methods } = await lab(page);
  const tab = pane.getByTestId("desk-chain");
  await tab.getByRole("button", { name: "105 call" }).click();
  const actions = tab.getByTestId("chain-actions");
  await expect(actions).toContainText("NBIS $105 Call 11/13/26");
  await expect(actions).toContainText("Wide spread: $20 a contract between bid and ask (50% of the mark)");
  await expect(actions).toContainText("No armed NBIS call plan yet, so Put on ticket starts one for this contract, as Plan it does.");
  await expect(actions.getByRole("button", { name: "Put on ticket" })).toBeEnabled();
  // Real actions and Paper are two labelled groups: REAL with Check it…Make it a spread, PAPER with the Paper button alone.
  const real = actions.getByRole("group", { name: "Real: copy to Robinhood" });
  const paper = actions.getByRole("group", { name: "Paper, not real money" });
  await expect(real.getByTestId("mode-mark")).toHaveAttribute("data-mode", "real");
  await expect(real.getByRole("button", { name: "Make it a spread" })).toBeVisible();
  await expect(real.getByTestId("paper-button")).toHaveCount(0);
  await expect(paper.getByTestId("mode-mark")).toHaveText("Paper · not real money");
  await expect(paper.getByTestId("paper-button")).toHaveText("Paper");
  await actions.getByRole("button", { name: "Check it" }).click();
  await expect(pane.getByRole("tab", { name: "Check a call" })).toHaveAttribute("aria-selected", "true");
  await expect(pane.getByRole("textbox", { name: "The Discord message" })).toHaveValue("NBIS 11/13 105C");
  expect(methods.filter(m => m.startsWith("POST"))).toEqual([]);
});

test("tap a contract: Plan it opens the plan flow with the contract as text he edits", async ({ page }) => {
  const { pane } = await lab(page);
  const tab = pane.getByTestId("desk-chain");
  await tab.getByRole("button", { name: "100 call" }).click();
  await expect(tab.getByTestId("chain-actions")).toContainText("you hold 2");
  await tab.getByTestId("chain-actions").getByRole("button", { name: "Plan it" }).click();
  await expect.poll(() => new URL(page.url()).searchParams.get("context"))
    .toBe("Plan a trade: NBIS $100 Call 11/13/26 (mark 2.50, from the chain). My entry trigger, invalidation and time stop:");
  expect(new URL(page.url()).searchParams.get("symbol")).toBe("NBIS");
});

test("Put on ticket with no plan yet starts the plan flow for this exact contract, as Plan it does", async ({ page }) => {
  const { pane, tickets } = await lab(page);
  const tab = pane.getByTestId("desk-chain");
  await tab.getByRole("button", { name: "100 call" }).click();
  await tab.getByTestId("chain-actions").getByRole("button", { name: "Put on ticket" }).click();
  await expect.poll(() => new URL(page.url()).searchParams.get("context"))
    .toBe("Plan a trade: NBIS $100 Call 11/13/26 (mark 2.50, from the chain). My entry trigger, invalidation and time stop:");
  await expect(page.getByLabel("Message")).toHaveValue(/Plan a trade: NBIS \$100 Call 11\/13\/26/); // in the box, unsent
  expect(tickets).toEqual([]);
});

// --- From a chain contract to a copyable ticket: the plan's ticket opens on the contract he started from ----------------

const NEW = "88888888-8888-4888-8888-888888888888";
const ROTH = "00000000-0000-0000-0000-000000000001";
const draft = (contract: string) => ({ id: "p1", kind: "trade_plan", symbol: "NBIS", direction: "long", instrument: "calls", contract,
  thesis: "Reclaims VWAP with the group", entry_trigger: { condition: "closes_beyond", price: 95.9, interval: "5m" },
  invalidation: { condition: "crosses", price: 92.3, interval: null }, time_stop: "out by 15:30", size_note: "2 contracts", last: 95.4,
  as_of: "2026-11-12T14:00:00Z" });
const turn = (contract: string) => [
  { type: "tool", id: "p1", name: "propose_plan", status: "ok", summary: "proposed plan", ms: 1, provenance: { source: "proposal", kind: "proposal", as_of: null } },
  { type: "proposal", ...draft(contract) }, { type: "text", delta: "NBIS plan (draft)." },
  { type: "done", metrics: { backend: "fake", evidence: "fixture", model: "fake-scripted", first_text_ms: 1, total_ms: 2, rounds: 1, tool_calls: [],
    usage: { input_tokens: 0, output_tokens: 0, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 }, cost_usd: 0 } },
].map(e => `event: ${e.type}\ndata: ${JSON.stringify(e)}\n\n`).join("");

/** What a Send and a Confirm need, on top of ``lab``'s reads: the copilot's turn drafts a long-call plan naming
 *  ``contract`` (words that alone name no single contract), and the plan, its alerts and its horizon save in the browser. */
async function planning(page: Page, contract: string) {
  const sends: string[] = [];
  let saved = { ...record, id: NEW, transcript: [] as object[], message_count: 0 };
  await page.route("**/copilot/investigations", route => route.fulfill({ status: 201, json: saved }));
  await page.route(`**/copilot/investigations/${NEW}**`, route => {
    if (route.request().method() === "PUT") saved = { ...saved, ...route.request().postDataJSON(), revision: saved.revision + 1 };
    return route.fulfill({ json: saved });
  });
  await page.route("**/copilot/chat", route => { sends.push(route.request().method()); return route.fulfill({ status: 200, headers: { "content-type": "text/event-stream" }, body: turn(contract) }); });
  await page.route("**/copilot/quote?*", route => route.fulfill({ json: { symbol: "NBIS", last: 95.4, trade_time: 1, fetched_at: 1, age_s: 2, issue: null, fresh: true } }));
  await page.route("**/charts/captures/setup", route => route.fulfill({ json: { accounts: [{ id: ROTH, label: "Roth IRA ··8267", broker: "robinhood" }],
    default_account_id: ROTH, templates: [], max_templates: 3, transcriber: { configured: false, provider: "off", note: "" } } }));
  await page.route("**/charts/captures", route => route.fulfill({ status: 201, json: { id: "c1", ...route.request().postDataJSON() } }));
  await page.route("**/day-journal/*/entries", route => route.fulfill({ json: { id: "j1", day: "2026-11-12", not_traded: false, actor: "owner", created_at: "2026-11-12T14:01:00Z", ...route.request().postDataJSON() } }));
  await page.route("**/copilot/time-stops/preview?*", route => route.fulfill({ json: { due_at: null, reason: "Kept as a note.", enabled: true } }));
  await page.route("**/charts/alerts", route => route.fulfill({ json: { alerts: [], phone: true } }));
  return sends;
}

/** Send the plan line in the box, Confirm the copilot's card, then Open its ticket. */
async function sendConfirmOpen(page: Page) {
  await page.getByRole("button", { name: "Send" }).click();
  const card = page.getByRole("region", { name: "Proposed trade plan" });
  await card.getByRole("button", { name: "Confirm" }).click();
  await expect(card.getByRole("status")).toHaveText("Plan confirmed.");
  return card;
}

for (const kind of ["one contract", "a spread"] as const) {
  test(`a plan started from the chain on ${kind} opens its ticket on it after Confirm, Copy all in view at 1440×900`, async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const spread = kind === "a spread";
    const ticket = spread ? { ...SPREAD_TICKET, investigation_id: NEW } : { ...TICKET, investigation_id: NEW, contract: { ...TICKET.contract, strike: 100, label: "NBIS $100 Call 11/13/26" } };
    const { pane, methods, tickets } = await lab(page, [], ticket);
    const sends = await planning(page, spread ? "NBIS 100/105C debit spread" : "NBIS 100C");
    const tab = pane.getByTestId("desk-chain");
    await tab.getByRole("button", { name: "100 call" }).click();
    if (spread) {
      await tab.getByTestId("chain-actions").getByRole("button", { name: "Make it a spread" }).click();
      await tab.getByRole("button", { name: "105 call" }).click();
      await expect(tab.getByTestId("chain-spread")).toContainText("Confirm the plan and Open its ticket has both legs on it");
      await tab.getByTestId("chain-spread").getByRole("button", { name: "Put on ticket" }).click();
    } else {
      await tab.getByTestId("chain-actions").getByRole("button", { name: "Put on ticket" }).click();
    }
    await expect(page.getByLabel("Message")).toHaveValue(/Plan a trade: NBIS \$100/);
    const card = await sendConfirmOpen(page);
    expect(sends).toHaveLength(1);
    await expect(card.getByTestId("plan-ticket-pick")).toHaveText(spread ? "with NBIS $100/$105 Call Debit Spread 11/13/26, the contract you started from"
      : "with NBIS $100 Call 11/13/26, the contract you started from");
    await card.getByRole("button", { name: "Open its ticket" }).click();
    await expect(pane.getByRole("tab", { name: "Ticket" })).toHaveAttribute("aria-selected", "true");
    // The contract he picked on the chain, with no second pick: the ticket is read on it straight away.
    expect(tickets).toEqual([spread ? `${NEW}?expiration=2026-11-13&strike=100&short_strike=105&option_type=call` : `${NEW}?expiration=2026-11-13&strike=100`]);
    const open = pane.getByTestId("desk-ticket");
    await expect(open).toContainText(spread ? "NBIS $100/$110 Call Debit Spread 11/13/26" : "NBIS $100 Call 11/13/26");
    await expect(open.getByRole("button", { name: "Use this" })).toHaveCount(0);
    await expect(open.getByRole("button", { name: "Copy all for Robinhood" })).toBeInViewport({ ratio: 1 });
    await expect(open.getByText("Send to Robinhood")).toHaveCount(0);
    expect(methods.filter(m => m !== "GET" && !m.endsWith("checks"))).toEqual([]); // the chain and the ticket only read
  });
}

test("a plan the copilot moved to another expiry keeps its own words: its ticket is not opened on the chain's pick", async ({ page }) => {
  const { pane, tickets } = await lab(page, [], { ...TICKET, investigation_id: NEW });
  await planning(page, "NBIS 11/20 100C");
  await pane.getByTestId("desk-chain").getByRole("button", { name: "100 call" }).click();
  await pane.getByTestId("chain-actions").getByRole("button", { name: "Put on ticket" }).click();
  const card = await sendConfirmOpen(page);
  await expect(card.getByTestId("plan-ticket-pick")).toHaveCount(0);
  await card.getByRole("button", { name: "Open its ticket" }).click();
  await expect(pane.getByTestId("desk-ticket")).toBeVisible();
  expect(tickets).toEqual([NEW]); // the plan's own words decide
});

test("a checked call's Plan it carries its contract to the confirmed plan's ticket too", async ({ page }) => {
  await page.clock.setFixedTime(new Date("2026-11-12T16:00:00Z")); // the call's 11/13 is this year's
  const { pane, tickets } = await lab(page, [], { ...TICKET, investigation_id: NEW, contract: { ...TICKET.contract, strike: 105, label: "NBIS $105 Call 11/13/26" } });
  await planning(page, "NBIS 105C");
  const check = { id: "c0ffee00-0000-4000-8000-000000000001", checked_at: "2026-11-12T15:41:00Z", day: "2026-11-12", source: "desk", raw: "NBIS 11/13 105C",
    symbol: "NBIS", reading: { ticker: "NBIS", expiry: "2026-11-13", strike: 105, side: "call", entry: null, stop: null, target: null }, verdict: "Draft",
    underlying_price: 95.4, outcome: null, outcome_at: null, planned: false, plan_href: null,
    card: { headline: "NBIS needs +10% by Friday", tiles: [], against: null, changes_if: null, others: [], note: null } };
  await page.route("**/copilot/checks", route => route.fulfill({ json: route.request().method() === "POST" ? check : { day: "2026-11-12", checks: [] } }));
  const tab = pane.getByTestId("desk-chain");
  await tab.getByRole("button", { name: "105 call" }).click();
  await tab.getByTestId("chain-actions").getByRole("button", { name: "Check it" }).click();
  await pane.getByTestId("call-check-run").click();
  await pane.getByTestId("call-check-plan").click();
  await expect(page.getByRole("textbox", { name: "Message", exact: true })).toHaveValue(/Plan a trade: NBIS 105 call 11\/13, from a Discord call I checked/);
  const card = await sendConfirmOpen(page);
  await card.getByRole("button", { name: "Open its ticket" }).click();
  await expect(pane.getByTestId("desk-ticket")).toContainText("NBIS $105 Call 11/13/26");
  expect(tickets).toEqual([`${NEW}?expiration=2026-11-13&strike=105`]);
});

test("tap a contract: Put on ticket opens the saved plan's ticket with that contract, and only reads", async ({ page }) => {
  const { pane, methods, tickets } = await lab(page, [STOCK_PLAN, PLAN]);
  const tab = pane.getByTestId("desk-chain");
  await tab.getByRole("button", { name: "102.5 call" }).click();
  const actions = tab.getByTestId("chain-actions");
  await expect(actions).toContainText("opens your saved NBIS plan's ticket with this contract");
  await actions.getByRole("button", { name: "Put on ticket" }).click();
  await expect(pane.getByRole("tab", { name: "Ticket" })).toHaveAttribute("aria-selected", "true");
  const ticket = pane.getByTestId("desk-ticket");
  await expect(ticket).toContainText("NBIS $102.5 Call 11/13/26");
  await expect(ticket).toContainText("Your pick from the chain (your plan says: NBIS 11/13 100C)");
  expect(tickets).toEqual([`${INV}?expiration=2026-11-13&strike=102.5`]); // the call plan's ticket, not the newer stock plan's
  expect([...new Set(methods)]).toEqual(["GET"]);
});

test("a put tapped on the phone layout uses the calls and puts toggle", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const { pane } = await lab(page);
  const tab = pane.getByTestId("desk-chain");
  const toggle = tab.getByRole("radiogroup", { name: "Calls or puts" });
  await expect(toggle).toBeVisible();
  await toggle.getByRole("radio", { name: "Puts" }).click();
  await tab.getByRole("button", { name: "97.5 put" }).click();
  await expect(tab.getByTestId("chain-actions")).toContainText("NBIS $97.5 Put 11/13/26");
});

test("the expiries that live through the next earnings report are marked ER, with one line saying so", async ({ page }) => {
  const { pane } = await lab(page);
  const tab = pane.getByTestId("desk-chain");
  const expiries = tab.getByRole("radiogroup", { name: "Expiry" }).getByRole("radio");
  await expect(expiries.nth(2).getByTestId("chain-expiry-earnings")).toHaveText("ER");
  await expect(expiries.nth(2)).toHaveAttribute("title", /includes the 11\/19\/26 earnings report \(time of day not published\)/);
  await expect(tab.getByTestId("chain-expiry-earnings")).toHaveCount(1);
  await expect(tab.getByTestId("chain-earnings-note")).toHaveText("ER: these expiries include the 11/19/26 earnings report; time of day not published.");
});

test("an Unusual options row in the Feed selects its contract in the Chain tab, on its expiry, marked", async ({ page }) => {
  const { pane, chainReads, methods } = await lab(page);
  await page.getByRole("tab", { name: "Feed" }).click();
  const feed = page.getByTestId("desk-feed");
  await feed.getByRole("button", { name: "Ideas", exact: true }).click();
  await feed.getByRole("button", { name: "Unusual options" }).click();
  const list = feed.getByTestId("feed-unusual");
  await expect(list.getByTestId("unusual-rule")).toHaveAttribute("title", /3× its open interest/);
  await expect(list).toContainText("NBIS puts 2.6× usual");
  await expect(list).toContainText("Not read yet: AMD.");
  const row = list.getByTestId("unusual-row");
  await expect(row).toContainText("NBIS $97.5 Put 11/20/26");
  await expect(row).toContainText("Vol 4,200 · OI 900 · Last 3.10");
  await expect(row).toContainText("4.7× OI");
  const before = chainReads.length; // the setup opened the Chain once already
  await row.click();
  await expect(pane.getByRole("tab", { name: "Chain" })).toHaveAttribute("aria-selected", "true");
  const tab = pane.getByTestId("desk-chain");
  await expect(tab.getByRole("radiogroup", { name: "Expiry" }).getByRole("radio", { checked: true })).toContainText("Nov 20");
  await expect.poll(() => chainReads.at(-1)).toBe("?symbol=NBIS&expiration=2026-11-20&strike=97.5");
  await expect(tab.getByTestId("chain-actions")).toContainText("NBIS $97.5 Put 11/20/26");
  await expect(tab.locator("tr[data-strike='97.5']").getByTestId("chain-unusual")).toHaveText("unusual");
  expect(chainReads.slice(before).filter(q => !q.includes("expiration"))).toEqual([]); // the pick's expiry is the first read
  // Leaving the Chain and coming back is a fresh look: the nearest expiry, nothing selected.
  await pane.getByRole("tab", { name: "Position" }).click();
  await pane.getByRole("tab", { name: "Chain" }).click();
  await expect(tab.getByRole("radiogroup", { name: "Expiry" }).getByRole("radio", { checked: true })).toContainText("Nov 13");
  await expect(tab.getByTestId("chain-actions")).toHaveCount(0);
  expect(methods.filter(m => m.startsWith("POST"))).toEqual([]);
});

// --- Make it a spread ------------------------------------------------------------------------------------------------

// Invented: the 100/110 call debit spread as the server prices it (desk_ticket's spread ticket), 2 spreads at the 2.20 mid.
const leg = (strike: number, bid: number, ask: number) => ({
  role: strike === 100 ? "long" : "short", action: strike === 100 ? "buy" : "sell", strike, label: `NBIS $${strike} Call 11/13/26`,
  quote: { state: "ok", as_of: now - 30, bid, ask, mid: Math.round((bid + ask) * 50) / 100, spread: ask - bid, spread_pct: 6, multiplier: 100 }, wide: false,
});
const SPREAD_TICKET = {
  ...TICKET, contract: null, quote: null, limit: 2.2, contracts: 2, target: 101,
  spread: { kind: "call", expiry: "2026-11-13", type: "debit", width: 10, long: 100, short: 110, label: "NBIS $100/$110 Call Debit Spread 11/13/26",
    source: "picked", multiplier: 100, legs: [leg(100, 3.1, 3.3), leg(110, 0.97, 1.03)], net_mid: 2.2, net_natural: 2.33, rough: [] as string[],
    bullish: true, against_plan: null },
  check: { play: { lines: [{ part: "stop", ok: true, text: "out at 92.3" }, { part: "size", ok: true, text: "2 contracts" }], missing: [], fill: null },
    habits: { state: "spread", fired: [], size: null, footer: "", reason: "Your habit checks read single options; a spread is not checked against them." },
    overnight: { state: "missing", show: false, reason: "No theta in the chain." } },
};

test("Make it a spread: the next call tapped is the leg sold, with the net, and Put on ticket carries both legs", async ({ page }) => {
  const { pane, methods, tickets } = await lab(page, [STOCK_PLAN, PLAN], SPREAD_TICKET);
  const tab = pane.getByTestId("desk-chain");
  await tab.getByRole("button", { name: "92.5 call" }).click();
  await tab.getByTestId("chain-actions").getByRole("button", { name: "Make it a spread" }).click();
  await expect(tab.getByTestId("chain-spread-building")).toContainText("Now tap the call to sell");
  await tab.getByRole("button", { name: "97.5 call" }).click();
  const spread = tab.getByTestId("chain-spread");
  await expect(spread).toContainText("NBIS $92.5/$97.5 Call Debit Spread 11/13/26");
  await expect(spread).toContainText("Buy NBIS $92.5 Call 11/13/26");
  await expect(spread).toContainText("Sell NBIS $97.5 Call 11/13/26");
  // 5.00 − 2.50 = 2.50 at the mid; 5.10 − 2.40 = 2.70 at the natural price. Per spread: risk $250 to make $250.
  await expect(tab.getByTestId("chain-spread-net")).toContainText("Net debit 2.50 at the mid · 2.70 at the natural price · width 5");
  await expect(tab.getByTestId("chain-spread-net")).toContainText("risk $250 to make $250, break-even 95.00");
  await spread.getByRole("button", { name: "Put on ticket" }).click();
  expect(tickets).toEqual([`${INV}?expiration=2026-11-13&strike=92.5&short_strike=97.5&option_type=call`]);
  const ticket = pane.getByTestId("desk-ticket");
  await expect(ticket).toHaveAttribute("data-spread", "debit");
  await expect(ticket).toContainText("NBIS $100/$110 Call Debit Spread 11/13/26");
  await expect(ticket.getByTestId("spread-leg-quote")).toHaveText([/Bid 3\.10 · Ask 3\.30 · Mid 3\.20/, /Bid 0\.97 · Ask 1\.03 · Mid 1\.00/]);
  await expect(ticket.getByTestId("spread-net")).toContainText("2.20 debit at the mid · 2.33 debit at the natural price");
  // 2 spreads at 2.20: $440 at risk, the 7.80 left of the 10 width x 200 = $1,560 to make, break-even 102.20.
  await expect(ticket.getByTestId("spread-max-loss")).toContainText("$440.00");
  await expect(ticket.getByTestId("spread-max-gain")).toContainText("$1,560.00");
  await expect(ticket.getByTestId("spread-sentence")).toHaveText("Pay $2.20 a share for the 100/110 call spread (2 of them), risk $440.00 to make $1,560.00, breakeven 102.20.");
  await expect(ticket.getByTestId("spread-levels")).toContainText("At your target 101: worth 1.00 at expiry, −$240.00");
  await expect(ticket.getByTestId("play-habits")).toContainText("a spread is not checked against them");
  // He edits: 3 spreads at 2.50 is $750 at risk and $2,250 to make; everything follows.
  await ticket.getByRole("textbox", { name: "Quantity in spreads" }).fill("3");
  await ticket.getByRole("textbox", { name: "Net limit price per share, debit" }).fill("2.50");
  await expect(ticket.getByTestId("spread-max-loss")).toContainText("$750.00");
  await expect(ticket.getByTestId("spread-max-gain")).toContainText("$2,250.00");
  await expect(ticket.getByTestId("spread-sentence")).toContainText("breakeven 102.50");
  // At or over the width: no figures, and why.
  await ticket.getByRole("textbox", { name: "Net limit price per share, debit" }).fill("10");
  await expect(ticket.getByTestId("spread-warning")).toContainText("can never be worth more than you pay");
  await expect(ticket.getByText("Send to Robinhood")).toHaveCount(0);
  expect([...new Set(methods)]).toEqual(["GET"]);
});

test("a wide leg makes the chain's spread rough; Plan it carries the spread's words", async ({ page }) => {
  const { pane } = await lab(page);
  const tab = pane.getByTestId("desk-chain");
  await tab.getByRole("button", { name: "95 call" }).click();
  await tab.getByTestId("chain-actions").getByRole("button", { name: "Make it a spread" }).click();
  await tab.getByRole("button", { name: "105 call" }).click(); // the wide 105 (50% of its mark)
  await expect(tab.getByTestId("chain-spread")).toContainText("Rough: the $105 leg's market is wide.");
  await expect(tab.getByTestId("chain-spread-net")).toContainText("Net debit 2.10 at the mid");
  await expect(tab.getByTestId("chain-spread")).toContainText("No armed NBIS long (call) plan for this bullish spread yet, so Put on ticket starts one for this spread");
  await tab.getByTestId("chain-spread").getByRole("button", { name: "Plan it" }).click();
  await expect.poll(() => new URL(page.url()).searchParams.get("context"))
    .toBe("Plan a trade: NBIS $95/$105 Call Debit Spread 11/13/26. Contract: NBIS 11/13/26 95/105C debit spread. My entry trigger, invalidation and time stop:");
});

test("a spread ticket with a stale leg shows it grey with its time, no net price, and says rough", async ({ page }) => {
  const stale = { ...SPREAD_TICKET, limit: null, contracts: null, spread: { ...SPREAD_TICKET.spread, net_mid: null, net_natural: null,
    rough: ["the $110 leg has a stale quote"],
    legs: [leg(100, 3.1, 3.3), { ...leg(110, 0, 0), quote: { state: "stale", as_of: now - 3600, reason: "The latest bid and ask are too old to price an order from.", multiplier: 100 } }] } };
  const { pane } = await lab(page, [PLAN], stale);
  const tab = pane.getByTestId("desk-chain");
  await tab.getByRole("button", { name: "100 call" }).click();
  await tab.getByTestId("chain-actions").getByRole("button", { name: "Make it a spread" }).click();
  await tab.getByRole("button", { name: "102.5 call" }).click();
  await tab.getByTestId("chain-spread").getByRole("button", { name: "Put on ticket" }).click();
  const ticket = pane.getByTestId("desk-ticket");
  await expect(ticket.getByTestId("spread-leg-quote").nth(1)).toContainText("Quote stale (last");
  await expect(ticket.getByTestId("spread-net")).toContainText("No net price: the $110 leg has a stale quote.");
  await expect(ticket.getByTestId("spread-rough")).toContainText("Rough: the $110 leg has a stale quote.");
  await expect(ticket.getByRole("textbox", { name: "Net limit price per share, debit" })).toHaveValue("");
  await expect(ticket.getByRole("button", { name: "Read the quotes again" })).toBeVisible();
});
