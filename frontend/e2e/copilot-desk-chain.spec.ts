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
      { date: "2026-11-20", days: 8, kind: "monthly", held: false }],
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

async function lab(page: Page, plans: object[] = []) {
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
  await page.route(/\/copilot\/tickets\/[^/?]+(\?.*)?$/, route => {
    methods.push(route.request().method());
    const url = new URL(route.request().url());
    tickets.push(`${url.pathname.split("/").pop()}${url.search}`);
    return route.fulfill({ json: TICKET });
  });
  await page.goto(`/copilot-lab?investigation=${INV}`);
  await expect(page.getByText("The group is bid; size small.")).toBeVisible();
  const back = page.getByRole("region", { name: "Conversation" }).getByRole("button", { name: "Back to the desk" });
  if (await back.isVisible()) await back.click(); // a phone opens the link on the copilot sheet
  const pane = page.getByRole("region", { name: "Chart and feed" });
  await pane.getByRole("tab", { name: "Chain" }).click();
  return { pane, chainReads, methods, tickets };
}

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
  await expect(actions).toContainText("there is no armed NBIS call plan yet, so Plan it first");
  await expect(actions.getByRole("button", { name: "Put on ticket" })).toBeDisabled();
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
