import { expect, test, type Page, type Request, type Route } from "@playwright/test";
import { closeNowTicket, trimCount, type HeldLeg } from "../lib/closingTicket";
import { legWorth } from "../lib/deskAction";
import type { DeskBook } from "../lib/desk";
import type { OptionTerms } from "../lib/optionStanding";

// The copilot acting on a position he holds (docs/copilot-lab.md § Desk actions): a close or trim card opens the Ticket
// tab's copy-only closing view at the mark now, from the desk's own book row; a note card saves his note through the book
// row's pen route and shows it under the row; a plan card opens today's Radar setup card, whose own Plan it waits for him.
// Nothing is placed, staged or sent. Every lab route is stubbed in the browser; every number is invented.
const ON = {
  enabled: true, backend: "fake", evidence: "live", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
// Friday November 13, 2026, 11:00 in New York: in the session.
const NOW = new Date("2026-11-13T16:00:00Z");
const MADE = Date.parse("2026-11-13T15:59:00Z") / 1000;
const epoch = (iso: string) => Date.parse(iso) / 1000;
const MAIN = "77777777-7777-4777-8777-777777777777";
const NBIS = "11111111-1111-4111-8111-111111111111";
const IREN_LONG = "22222222-2222-4222-8222-222222222222";
const IREN_SHORT = "33333333-3333-4333-8333-333333333333";
const NBIS_CALL = "NBIS261120C00100000";
const EVENT = "rd0-2026-11-13-dip-iren-up-1";

const position = (id: string, symbol: string, contract: string, book: object) => ({
  key: `trade:${id}`, group: "watch", symbol, title: `${symbol} ${contract}`, instrument: contract, trade_id: id,
  value: null, status: { text: "No plan yet", tone: "muted" }, path: null, hidden: false,
  meter: null, investigation_id: null, radar_event_id: null, changed_at: null, book,
});
const base = { days_held: 1, track: null, state: "no_plan", planned: false, stop_pct: null, plan_levels: { stop: null, target: null } };
const option = (side: string, strike: number, direction: string, quantity: number, cost: number) =>
  ({ side, strike, expiry: "2026-11-20", direction, quantity, multiplier: 100, cost, greeks: null });
const THREADS = {
  as_of: "2026-11-13T16:00:00Z", quotes_at: null, quote_issue: null, day: { phase: "regular", need_you: 0, streak: null },
  sections: { positions: "ok" }, plans: [], robinhood: { state: "off" },
  threads: [
    // Three NBIS 100 calls Robinhood matched: its account, mark 4.10 a share, +$420.
    position(NBIS, "NBIS", "11/20/26 100C", { ...base, usd: 420, pct: 51.9, expiry: "2026-11-20", live: "matched", quantity: 3, mark: 410,
      account: { label: "Roth IRA", masked: "••8267" }, tick: { quote: NBIS_CALL, scale: 100, cost: 270, quantity: 3, sign: 1 },
      option: option("call", 100, "long", 3, 270) }),
    // An IREN 40/45 call spread, two of each, in the journal only: marks 3.00 and 1.20 a share.
    position(IREN_LONG, "IREN", "11/20/26 40C", { ...base, usd: 100, pct: 20, expiry: "2026-11-20", mark: 300, quantity: 2, tick: null,
      option: option("call", 40, "long", 2, 250) }),
    position(IREN_SHORT, "IREN", "11/20/26 45C", { ...base, usd: -40, pct: -50, expiry: "2026-11-20", mark: 120, quantity: 2, tick: null,
      option: option("call", 45, "short", 2, 100) }),
  ],
};
const SESSION = { as_of: "2026-11-13T16:00:00Z", now: epoch("2026-11-13T16:00:00Z"), day: "2026-11-13", phase: "regular",
  open: epoch("2026-11-13T14:30:00Z"), close: epoch("2026-11-13T21:00:00Z"), events: [], time_stops: [], pings: null, prep: null,
  indices: [{ symbol: "SPY", last: 580.1, change_pct: 0.42 }], quote_issue: null, realized_today: 0, sections: {} };
const main = (fields: Record<string, unknown> = {}) => ({ id: MAIN, source: "copilot", title: "Main chat", symbol: null, status: "open", conclusion: null,
  revision: 1, message_count: 0, has_findings: false, created_at: "2026-11-13T14:00:00Z", updated_at: "2026-11-13T15:00:00Z", evidence: [],
  findings: null, transcript: [] as unknown[], main_day: "2026-11-13", ...fields });

const card = (id: string, fields: Record<string, unknown>) => ({ type: "proposal", id, kind: "desk_action", made_at: MADE, ...fields });
const leg = (trade_id: string, strike: number, direction = "long") => ({ trade_id, instrument: "option", direction, side: "call", strike, expiry: "2026-11-20" });
const CLOSE = card("a_close", { action: "close", symbol: "NBIS", option_type: "call", legs: [leg(NBIS, 100)], contract: "100 call Nov 20",
  held: 3, contracts: 3, remains: 0, mark: 410, proceeds: 1230, usd: 420 });
const TRIM = card("a_trim", { action: "trim", symbol: "NBIS", half: true, legs: [leg(NBIS, 100)], contract: "100 call Nov 20",
  held: 3, contracts: 1, remains: 2, mark: 410, proceeds: 410, usd: 420 });
const SPREAD = card("a_spread", { action: "trim", symbol: "IREN", quantity: 1, legs: [leg(IREN_LONG, 40), leg(IREN_SHORT, 45, "short")],
  contract: "40/45 call spread Nov 20", held: 2, contracts: 1, remains: 1, mark: null, proceeds: null, usd: null });
const NOTE = card("a_note", { action: "note", symbol: "NBIS", text: "took profit into the wall", legs: [leg(NBIS, 100)], contract: "100 call Nov 20" });
const PLAN = card("a_plan", { action: "plan_idea", symbol: "IREN", direction: "long", event_id: EVENT, words: "dip turning up",
  levels_line: "In near 41.20 · out below 39.80 (−3.4%)" });
const sse = (cards: unknown[], text = "Tap the card to do it; nothing happens until you do.") => [
  ...cards.map((c) => ({ type: "tool", id: (c as { id: string }).id, name: "desk_action", status: "ok", summary: "desk action",
    provenance: { source: "A desk action for the owner to tap; nothing done", kind: "proposal", as_of: null } })),
  ...cards, { type: "text", delta: text },
  { type: "done", metrics: { backend: "fake", evidence: "live", model: "fake-scripted", first_text_ms: 1, total_ms: 2, rounds: 2, tool_calls: [],
    usage: { input_tokens: 0, output_tokens: 0, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 }, cost_usd: 0 } },
].map((e) => `data: ${JSON.stringify(e)}\n\n`).join("");

type Seen = { notes: unknown[]; outcomes: { id: string; body: { state: string; note?: string } }[]; writes: Request[] };

async function desk(page: Page, cards: unknown[], { width = 1440, threads = THREADS, optionTick = true } = {}) {
  const seen: Seen = { notes: [], outcomes: [], writes: [] };
  let current = main();
  await page.setViewportSize({ width, height: 900 });
  await page.clock.install({ time: NOW });
  await page.route("**/copilot/status", (r) => r.fulfill({ json: ON }));
  await page.route("**/copilot/desk/threads", (r) => r.fulfill({ json: threads }));
  await page.route("**/copilot/desk/session", (r) => r.fulfill({ json: SESSION }));
  await page.route("**/copilot/desk/pings*", (r) => r.fulfill({ json: { day: "2026-11-13", since: "2026-11-12", alerts: { state: "ok", rows: [] }, radar: { state: "off", reason: null, rows: [] } } }));
  await page.route("**/copilot/desk/feed", (r) => r.fulfill({ json: { as_of: "2026-11-13T16:00:00Z", now: epoch("2026-11-13T16:00:00Z"), day: "2026-11-13", total: 0, sources: {}, unavailable: [], items: [] } }));
  await page.route("**/copilot/desk/sparks?*", (r) => r.fulfill({ json: { as_of: "2026-11-13T16:00:00Z", spy_change_pct: 0.4, rows: {} } }));
  await page.route("**/copilot/desk/watching", (r) => r.fulfill({ json: { state: "ok", symbols: [], count: 0, max: 30, imported_at: null, robinhood: "off", levels: {}, setups: {} } }));
  // The NBIS call's live mark is 4.20 now (the book read 4.10): the ticket takes the newer price. Without ``optionTick``
  // the feed has no row for the contract, so the ticket uses the book's last mark.
  await page.route("**/copilot/desk/ticks?*", async (r) => {
    const at = Math.floor(await page.evaluate(() => Date.now() / 1000));
    return r.fulfill({ json: { state: "ok", as_of: "", poll_seconds: 5, closes_at: epoch("2026-11-13T21:00:00Z"), rows: {
      ...(optionTick ? { [NBIS_CALL]: { last: 4.2, change_pct: null, prev_close: null, at } } : {}), NBIS: { last: 101.2, change_pct: 1, prev_close: 100.2, at },
      IREN: { last: 41.5, change_pct: 1, prev_close: 41, at } } } });
  });
  await page.route("**/copilot/desk/notes?*", (r) => r.fulfill({ json: { trades: {}, fills: {} } }));
  await page.route("**/copilot/desk/notes", (r: Route) => {
    const body = r.request().postDataJSON();
    seen.notes.push(body);
    return r.fulfill({ json: { trade_id: body.trade_id, note: { id: "n1", text: body.text, at: epoch("2026-11-13T16:00:00Z") } } });
  });
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
    seen.outcomes.push({ id: decodeURIComponent(new URL(r.request().url()).pathname.split("/").at(-2)!), body: r.request().postDataJSON() });
    await r.fulfill({ json: current });
  });
  await page.route("**/copilot/chat", (r) => r.fulfill({ status: 200, headers: { "content-type": "text/event-stream" }, body: sse(cards) }));
  await page.route("**/copilot/tickets", (r) => r.fulfill({ json: { plans: [] } }));
  await page.route("**/copilot/desk/*/{picture,chart}*", (r) => r.fulfill({ status: 503, json: { detail: "No chart in this test." } }));
  await page.route(`**/radar/events/${EVENT}`, (r) => r.fulfill({ json: { event: { event_id: EVENT, rule_version: "rd0", kind: "dip_turn",
    symbols: ["IREN"], summary: "IREN turned up from its session low 39.80.", at: "2026-11-13T15:40:00Z", session_date: "2026-11-13", group: null,
    details: {} }, revisions: [], rating: null, news: null, news_checks: [], plans: { planned: false, traded: false } } }));
  await page.route(`**/copilot/desk/radar-setup?event=${EVENT}`, (r) => r.fulfill({ json: { setup: { id: "6f0c2f8e-1d1a-4c3e-9a51-2d5c6f7a8b90",
    event_id: EVENT, session_date: "2026-11-13", kind: "dip_turn", direction: "up", symbol: "IREN", words: "dip turning up", entry: 41.2,
    invalidation: 39.8, side: "below", levels_line: "In near 41.20 · out below 39.80 (−3.4%)", contract_line: null, record: null, paper_record: null,
    plan_state: "none", plan_note: null, investigation_id: null, last: null, distance_pct: null, paper: { state: "pending" } } } }));
  await page.route("**/day-journal/2026-11-13", (r) => r.fulfill({ json: { day: "2026-11-13", entries: [], trade_plans: {} } }));
  page.on("request", (request) => { if (request.method() !== "GET" && !request.url().includes("/outcome") && !request.url().includes("/exchange")
    && !request.url().includes("/copilot/chat")) seen.writes.push(request); });
  await page.goto(`/copilot-lab?thread=${MAIN}`);
  await expect(page.getByTestId("desk-book")).toBeVisible();
  await page.getByLabel("Message").fill("Do it on the desk");
  await page.getByLabel("Message").press("Enter");
  return seen;
}

const byAction = (page: Page, action: string) => page.getByTestId("desk-action").and(page.locator(`[data-action="${action}"]`));
const ticket = (page: Page) => page.getByTestId("desk-ticket");

test("a close card opens the closing ticket for the whole position at the mark now; nothing is sent", async ({ page }) => {
  const seen = await desk(page, [CLOSE], { optionTick: false });
  const close = byAction(page, "close");
  await expect(close).toContainText("Close NBIS 100 call Nov 20 · all 3");
  await expect(close.getByTestId("desk-action-facts")).toHaveText("P&L +$420 · about $1,230 to close at the mark. The ticket reads the mark again when you tap.");
  await close.getByRole("button", { name: "Open ticket" }).click();
  // No live tick for the contract yet (nothing on the desk asked for it): the book's last mark, said so.
  await expect(close).toContainText("Ticket open on the desk: close all 3 at about 4.10 (the book's last mark). Copy it into Robinhood; nothing is sent from here.");
  await expect(page.getByRole("tab", { name: "Ticket" })).toHaveAttribute("aria-selected", "true");
  await expect(ticket(page)).toHaveAttribute("data-closing", "now");
  await expect(ticket(page)).toContainText("Roth IRA ••8267");
  await expect(ticket(page)).toContainText("Sell to close");
  await expect(ticket(page).getByLabel("Quantity in contracts")).toHaveValue("3");
  await expect(ticket(page).getByLabel("Limit price per share")).toHaveValue("4.10");
  await expect(ticket(page).getByTestId("close-now-mark")).toHaveText("Mark now 4.10 (last read)");
  await expect(ticket(page).getByTestId("close-now-left")).toHaveText("You hold 3; none left after this.");
  await expect(ticket(page).getByTestId("close-now-proceeds")).toHaveText("about $1,230.00 at this limit"); // 4.10 x 100 x 3
  await expect(ticket(page).getByRole("button", { name: /send|place order|submit/i })).toHaveCount(0);
  await expect.poll(() => seen.outcomes.find((o) => o.id === "a_close")?.body.state).toBe("confirmed");
  expect(seen.writes.map((r) => r.url())).toEqual([]);
});

test("a trim card sells half rounded down and shows what is left; editing the quantity re-adds it", async ({ page }) => {
  const seen = await desk(page, [TRIM]);
  const trim = byAction(page, "trim");
  await expect(trim).toContainText("Trim NBIS 100 call Nov 20 · sell 1 of 3, 2 left");
  await expect(trim.getByTestId("desk-action-facts")).toContainText("about $410 to sell 1 at the mark");
  // The book's contract ticks live: once the tick is in, the ticket takes the newer 4.20, not the card's 4.10.
  await expect(page.getByTestId("desk-book")).toContainText("450"); // (4.20 − 2.70) x 100 x 3
  await trim.getByRole("button", { name: "Open ticket" }).click();
  await expect(trim).toContainText("close 1 of 3 (2 left) at about 4.20. Copy it");
  await expect(ticket(page)).toContainText("Trim at the mark now");
  await expect(ticket(page).getByLabel("Quantity in contracts")).toHaveValue("1");
  await expect(ticket(page).getByTestId("close-now-mark")).toHaveText("Mark now 4.20");
  await expect(ticket(page).getByTestId("close-now-left")).toHaveText("You hold 3; 2 left after this.");
  await expect(ticket(page).getByTestId("close-now-proceeds")).toHaveText("about $420.00 at this limit");
  await ticket(page).getByLabel("Quantity in contracts").fill("2");
  await expect(ticket(page).getByTestId("close-now-left")).toHaveText("You hold 3; 1 left after this.");
  await expect(ticket(page).getByTestId("close-now-proceeds")).toHaveText("about $840.00 at this limit");
  await ticket(page).getByLabel("Quantity in contracts").fill("4"); // more than he holds: no quantity, no proceeds
  await expect(ticket(page).getByTestId("close-now-left")).toHaveText("You hold 3: set 1 to 3.");
  await expect(ticket(page).getByTestId("close-now-proceeds")).toHaveText("—");
  expect(seen.writes).toEqual([]);
});

test("a held vertical trims as its closing spread at the net mark", async ({ page }) => {
  await desk(page, [SPREAD]);
  const spread = byAction(page, "trim");
  await expect(spread).toContainText("Trim IREN 40/45 call spread Nov 20 · sell 1 of 2, 1 left");
  await expect(spread.getByTestId("desk-action-facts")).toHaveText("The ticket reads the mark when you tap."); // journal-only: no mark on the card
  await spread.getByRole("button", { name: "Open ticket" }).click();
  await expect(spread).toContainText("close 1 of 2 (1 left) at about 1.80 (the book's last mark)");
  await expect(ticket(page)).toContainText("Close spread: sell the $40 call, buy back the $45 call");
  await expect(ticket(page)).not.toContainText("Account");
  await expect(ticket(page).getByLabel("Limit price, net credit per spread")).toHaveValue("1.80");
  await expect(ticket(page).getByTestId("close-now-mark")).toHaveText("Mark now 3.00 − 1.20 = 1.80 (last read)");
  await expect(ticket(page).getByTestId("close-now-proceeds")).toHaveText("about $180.00 at this limit");
});

test("a card made for a size he no longer holds says so and opens nothing", async ({ page }) => {
  await desk(page, [{ ...CLOSE, held: 4, contracts: 4 }]);
  const close = byAction(page, "close");
  await close.getByRole("button", { name: "Open ticket" }).click();
  await expect(close).toContainText("You hold 3 NBIS 100 call Nov 20 now, not 4. Ask again.");
  await expect(ticket(page)).toHaveCount(0);
});

test("a note card saves through the book row's own route and the note shows under the position", async ({ page }) => {
  const seen = await desk(page, [NOTE]);
  const note = byAction(page, "note");
  await expect(note).toContainText("Note on NBIS 100 call Nov 20: took profit into the wall");
  expect(seen.notes).toEqual([]);
  await note.getByRole("button", { name: "Save note" }).click();
  await expect(note).toContainText("Saved on your NBIS 100 call Nov 20: “took profit into the wall”. It shows under the position on the desk.");
  expect(seen.notes).toEqual([{ trade_id: NBIS, text: "took profit into the wall" }]);
  await expect(page.getByTestId("desk-book")).toContainText("took profit into the wall");
});

test("a plan card opens today's setup card, whose own Plan it waits for him", async ({ page }) => {
  const seen = await desk(page, [PLAN]);
  const plan = byAction(page, "plan_idea");
  await expect(plan).toContainText("Plan it: IREN dip turning up");
  await expect(plan.getByTestId("desk-action-facts")).toHaveText("In near 41.20 · out below 39.80 (−3.4%)");
  await plan.getByRole("button", { name: "Plan it" }).click();
  await expect(page).toHaveURL(new RegExp(`radar=${EVENT}`));
  const hit = page.getByRole("region", { name: "Radar hit" });
  await expect(hit.getByTestId("radar-setup-levels")).toHaveText("In near 41.20 · out below 39.80 (−3.4%)");
  await expect(hit.getByRole("button", { name: "Plan it" })).toBeVisible();
  expect(seen.writes.map((r) => r.url()).filter((u) => u.includes("/plan"))).toEqual([]);
});

test("on a phone a trim card fits and its ticket comes into view", async ({ page }) => {
  await desk(page, [TRIM], { width: 393 });
  const trim = byAction(page, "trim");
  const box = await trim.boundingBox();
  expect(box!.width).toBeLessThanOrEqual(393);
  await trim.getByRole("button", { name: "Open ticket" }).click();
  await expect(ticket(page)).toBeInViewport();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(393);
});

// --------------------------------------------------------------------------- the arithmetic, no page

const terms = (o: Partial<OptionTerms>): OptionTerms => ({ side: "call", strike: 100, expiry: "2026-11-20", direction: "long", quantity: 3,
  multiplier: 100, cost: 270, greeks: null, ...o });
const heldLeg = (o: Partial<OptionTerms>, worth: number, markLive = true): HeldLeg => ({ terms: terms(o), worth, markLive });

test("trim counts: half rounds down and is at least one; a count is 1 to what he holds", () => {
  expect([1, 2, 3, 4, 5, 11].map((held) => trimCount(held, { half: true }))).toEqual([1, 1, 1, 2, 2, 5]);
  expect(trimCount(3, { quantity: 3 })).toBe(3);
  expect(trimCount(3, { quantity: 4 })).toBeNull();
  expect(trimCount(3, { quantity: 0 })).toBeNull();
  expect(trimCount(3, { quantity: 1.5 })).toBeNull();
  expect(trimCount(0, { half: true })).toBeNull();
});

test("close now: a single call at its mark, part of it, and what is left", () => {
  // Three calls worth $1,260 now: 4.20 a share. Selling 1 brings $420 and leaves 2.
  const one = closeNowTicket({ symbol: "NBIS", legs: [heldLeg({}, 1260)], account: "Roth IRA ••8267", contracts: 1 })!;
  expect(one).toMatchObject({ at: "now", strike: 100, shortStrike: null, held: 3, contracts: 1, remains: 2, mark: 4.2, net: 4.2, limit: 4.2,
    credit: true, proceeds: 420, markLive: true });
  expect(closeNowTicket({ symbol: "NBIS", legs: [heldLeg({}, 1260)], account: null, contracts: 4 })).toBeNull(); // more than held
  expect(closeNowTicket({ symbol: "NBIS", legs: [heldLeg({ direction: "short" }, 1260)], account: null, contracts: 1 })).toBeNull();
  // A cheap option never prices at zero: a $1 position of 3 is 0.0033 a share, limit 0.01.
  expect(closeNowTicket({ symbol: "NBIS", legs: [heldLeg({}, 1)], account: null, contracts: 3 })!.limit).toBe(0.01);
});

test("close now: a debit spread closes for a credit, a credit spread for a debit", () => {
  // Bought 40C worth 3.00, sold 45C worth 1.20, two each: net 1.80 credit, $360 for both.
  const debit = closeNowTicket({ symbol: "IREN", legs: [heldLeg({ strike: 40, quantity: 2 }, 600, false), heldLeg({ strike: 45, direction: "short", quantity: 2 }, 240)],
    account: null, contracts: 2 })!;
  expect(debit).toMatchObject({ shortStrike: 45, mark: 3, shortMark: 1.2, net: 1.8, limit: 1.8, credit: true, proceeds: 360, markLive: false });
  // Bought 90P worth 0.60, sold 95P worth 1.95: closing costs 1.35 a spread, −$135 for one.
  const credit = closeNowTicket({ symbol: "APLD", legs: [heldLeg({ side: "put", strike: 90, quantity: 1 }, 60), heldLeg({ side: "put", strike: 95, direction: "short", quantity: 1 }, 195)],
    account: null, contracts: 1 })!;
  expect(credit).toMatchObject({ net: -1.35, limit: 1.35, credit: false, proceeds: -135 });
  // Legs that are not one vertical give no ticket.
  expect(closeNowTicket({ symbol: "IREN", legs: [heldLeg({ strike: 40, quantity: 2 }, 600), heldLeg({ strike: 45, direction: "short", quantity: 1 }, 120)],
    account: null, contracts: 1 })).toBeNull();
});

test("a short leg's worth from its cost and P&L has the sign right", () => {
  const empty = { rows: {}, open: false, checked: 0 };
  // Sold at 1.00 (cost $100 a contract), two of them, now −$40: worth $240 (1.20 a share), not $160.
  const short = { usd: -40, quantity: null, mark: null, tick: null, option: terms({ direction: "short", quantity: 2, cost: 100 }) } as unknown as DeskBook;
  expect(legWorth(short, empty)).toEqual({ worth: 240, live: false });
  const long = { usd: 100, quantity: null, mark: null, tick: null, option: terms({ quantity: 2, cost: 250 }) } as unknown as DeskBook;
  expect(legWorth(long, empty)).toEqual({ worth: 600, live: false });
});
