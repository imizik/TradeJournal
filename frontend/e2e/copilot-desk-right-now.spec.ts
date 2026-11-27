import { expect, test, type Page } from "@playwright/test";

// Right now (docs/copilot-lab.md § The desk, Right now): before a conversation has a word in it, the copilot's column
// lists each open position that needs a look, most urgent first, with one question to ask; the book row of a position
// with no plan carries how far over its cut line it trades; a Feed row keeps one first step in view and its other
// actions as quiet links. Every route is stubbed with invented numbers.
const ON = { enabled: true, backend: "fake", evidence: "live", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 } };
const NOW = new Date("2026-11-13T16:00:00Z");
const epoch = (iso: string) => Date.parse(iso) / 1000;
const opt = (q: string, side: string, strike: number, expiry: string, qty: number, cost: number) => ({
  tick: { quote: q, scale: 100, cost, quantity: qty, sign: 1 },
  option: { side, strike, expiry, direction: "long", quantity: qty, multiplier: 100, cost, greeks: null } });
const T = (id: string, symbol: string, inst: string, value: [string, string], status: [string, string], book: object) => ({
  key: `trade:${id}`, group: "watch", symbol, title: `${symbol} ${inst}`, instrument: inst, trade_id: id,
  value: { text: value[0], tone: value[1] }, status: { text: status[0], tone: status[1] }, path: `/trades/${id}`, hidden: false,
  meter: null, investigation_id: null, radar_event_id: null, changed_at: null, book });
const NBIS = "11111111-1111-4111-8111-111111111111", ORCL = "22222222-2222-4222-8222-222222222222", MU = "33333333-3333-4333-8333-333333333333";
const THREADS = {
  as_of: "2026-11-13T16:00:00Z", quotes_at: null, quote_issue: null, day: { phase: "regular", need_you: 1, streak: null },
  sections: { positions: "ok" }, plans: [], robinhood: { state: "off" },
  threads: [
    T(ORCL, "ORCL", "11/14/26 250C", ["−$412.00", "loss"], ["Past cut line", "loss"],
      { usd: -412, pct: -38.1, expiry: "2026-11-14", days_held: 1, track: null, state: "no_plan", planned: false, stop_pct: null, quantity: 2, mark: 335, cut_line: 378, ...opt("ORCL261114C00250000", "call", 250, "2026-11-14", 2, 541) }),
    T(NBIS, "NBIS", "11/20/26 100C", ["+$140.00", "win"], ["On plan", "muted"],
      { usd: 140, pct: 20.6, expiry: "2026-11-20", days_held: 0, track: null, state: "on_plan", planned: true, stop_pct: 3.1, quantity: 2, mark: 410, cut_line: 238, plan_levels: { stop: 95.5, target: 108 }, ...opt("NBIS261120C00100000", "call", 100, "2026-11-20", 2, 340) }),
    T(MU, "MU", "11/21/26 240P", ["−$65.00", "loss"], ["Giving back", "warn"],
      { usd: -65, pct: -8.1, expiry: "2026-11-21", days_held: 2, track: null, state: "giving_back", planned: false, stop_pct: null, quantity: 1, mark: 735, cut_line: 560, ...opt("MU261121P00240000", "put", 240, "2026-11-21", 1, 800) }),
  ],
};
const SESSION = { as_of: "2026-11-13T16:00:00Z", now: epoch("2026-11-13T16:00:00Z"), day: "2026-11-13", phase: "regular",
  open: epoch("2026-11-13T14:30:00Z"), close: epoch("2026-11-13T21:00:00Z"), events: [], time_stops: [], pings: null, prep: null,
  indices: [], quote_issue: null, realized_today: -120, sections: {},
  to_answer: { alerts: { count: 1, rows: [{ id: "a1", trade_id: ORCL, symbol: "ORCL", contract: "ORCL 11/14/26 250C", kind: "giveback", at: epoch("2026-11-13T15:51:00Z"), today: true, feedback: null }] }, radar: null } };
const item = (o: Record<string, unknown>) => ({ has_time: true, symbol: null, detail: null, publisher: null, url: null, href: null, investigation_id: null, radar_event_id: null, setup: null, plan: null, mine: false, upcoming: false, ...o });
const FEED = { as_of: "2026-11-13T16:00:00Z", now: epoch("2026-11-13T16:00:00Z"), day: "2026-11-13", total: 5, sources: {}, unavailable: [], items: [
  item({ id: "tv:nvda", source: "TradingView", at: epoch("2026-11-13T15:46:00Z"), symbol: "NVDA", text: "ORB break long · 5m at 199.12", mine: true }),
  item({ id: "radar:mu", source: "Radar", at: epoch("2026-11-13T15:10:00Z"), symbol: "MU", text: "MU up 4.1% while SMH is up 0.6%", href: "/radar?event=1" }),
  item({ id: "radar:crwv", source: "Radar", at: epoch("2026-11-13T14:58:00Z"), symbol: "CRWV", text: "CRWV volume 3.2× usual in the first 30 minutes", href: "/radar?event=2" }),
  item({ id: "news:fed", source: "News", at: epoch("2026-11-13T15:00:00Z"), text: "Yields climb before the Fed minutes", publisher: "Reuters", url: "https://example.com/yields" }),
  item({ id: "news:orcl", source: "News", at: epoch("2026-11-13T14:40:00Z"), symbol: "ORCL", text: "Oracle slips as cloud capex worries return", publisher: "Bloomberg" }) ] };
const READS: Record<string, unknown> = {
  "/copilot/desk/threads": THREADS, "/copilot/desk/session": SESSION,
  "/copilot/desk/watching": { state: "ok", symbols: ["NVDA", "CRWV", "TSLA"], count: 3, max: 30, imported_at: null, robinhood: "off", levels: {}, setups: {} },
  "/copilot/desk/sparks": { as_of: "2026-11-13T16:00:00Z", spy_change_pct: 0.4, rows: {} },
  "/copilot/desk/moving": { state: "ok", mode: "live", session: "2026-11-13", as_of: "2026-11-13T16:00:00Z", reason: null, groups: [], movers: [] },
  "/copilot/desk/feed": FEED, "/copilot/investigations": { investigations: [] }, "/copilot/tickets": { plans: [] },
  "/copilot/unusual": { state: "ok", rows: [], tickers: [], unread: [], no_history: [], stale: [], rule: "" },
  "/copilot/scanner": { state: "off", rows: [] },
  "/copilot/exposure": { state: "ok", at_risk_usd: 2112, positions: 3, usual_day_usd: 2100, sample_days: 60, as_of: "2026-11-13T16:00:00Z", line: "At risk now: $2,112 in 3 options · usual day $2,100" },
};
function chart(symbol: string) {
  const last = epoch("2026-11-13T16:00:00Z");
  const bars = Array.from({ length: 90 }, (_, i) => { const open = 100 + Math.sin(i / 7) * 2 + i * 0.03; return { time: last - (89 - i) * 120, open, high: open + 0.5, low: open - 0.45, close: open + (i % 3 ? 0.2 : -0.2), volume: 1000 + i * 10, extended: false }; });
  return { symbol, timeframe: "2m", step: 120, as_of: last, live: false, state: "ok", reason: null, bars, studies: {}, reference: [],
    reading: { last: 102, at: last, daily: false, prev_close: 100.5, vwap: null, vwap_at: null, rvol: null }, levels: [], alerts: [], marks: [], time_stop: null, events: { earnings: null, macro: [], note: null } };
}
async function open(page: Page, width: number, height: number, threads: object = THREADS, priced = true) {
  const reads: Record<string, unknown> = { ...READS, "/copilot/desk/threads": threads };
  await page.setViewportSize({ width, height });
  await page.clock.install({ time: NOW });
  await page.route("**/api/backend/**", r => r.fulfill({ status: 404, json: { detail: "Not in this test." } }));
  await page.route("**/copilot/status", r => r.fulfill({ json: ON }));
  await page.route("**/copilot/chat", r => r.abort());
  for (const [p, body] of Object.entries(reads)) await page.route(u => u.pathname.endsWith(p), r => r.fulfill({ json: body }));
  await page.route("**/charts/symbol/*/you*", r => r.fulfill({ json: { symbol: "ORCL", closed_trades: 9, win_rate: 0.33, realized_pnl: -1240 } }));
  await page.route("**/copilot/desk/*/chart*", r => { const id = decodeURIComponent(new URL(r.request().url()).pathname.split("/").at(-2) ?? ""); return r.fulfill({ json: chart(id.includes(":") ? id.split(":").pop()! : "QQQ") }); });
  await page.route("**/copilot/desk/ticks?*", r => { if (!priced) return r.fulfill({ status: 503, json: { detail: "off" } }); const at = epoch("2026-11-13T15:59:30Z"); const L: Record<string, [number, number]> = {
    ORCL261114C00250000: [3.35, 249.1], NBIS261120C00100000: [4.1, 101.8], MU261121P00240000: [7.35, 236.2], ORCL: [249.1, 252.9], NBIS: [101.8, 99.6], MU: [236.2, 234.0], NVDA: [199.3, 197.9], CRWV: [96.4, 92.1], TSLA: [402.5, 405.0] };
    return r.fulfill({ json: { open: true, checked: at, rows: Object.fromEntries(Object.entries(L).map(([k, [last, prev]]) => [k, { last, prev_close: k.length > 6 ? null : prev, change_pct: k.length > 6 ? null : (last - prev) / prev * 100, at }])) } }); });
  await page.route("**/copilot/desk/minute?*", r => r.fulfill({ json: { reads: new URL(r.request().url()).searchParams.getAll("read").map(t => { const b = reads[t.split("?")[0]]; return b ? { status: 200, body: b } : { status: 404, body: { detail: "x" } }; }) } }));
  await page.goto("/copilot-lab");
  await expect(page.getByTestId("desk-book")).toBeVisible();
}

const rightNow = (page: Page) => page.getByRole("region", { name: "Conversation" }).getByTestId("right-now");

test("the copilot's empty column says what needs a look right now, most urgent first, with one question each", async ({ page }) => {
  await open(page, 1440, 900);
  const items = rightNow(page).getByTestId("right-now-item");
  await expect(items).toHaveCount(2); // NBIS is on plan and far from its stop: nothing to say
  await expect(items.nth(0)).toContainText("ORCL 11/14/26 250C");
  await expect(items.nth(0).getByTestId("right-now-what")).toHaveText("past cut $3.78 · now $3.35 · expires tomorrow");
  await expect(items.nth(1).getByTestId("right-now-what")).toHaveText("giving back · 31% over cut $5.60");
  // The generic hint gives way to it.
  await expect(page.getByText("Ask about an opportunity, push back on the read")).toHaveCount(0);
  // The question goes to the copilot.
  const asked = page.waitForRequest(r => r.url().includes("/copilot/chat"));
  await items.nth(0).getByTestId("right-now-ask").click();
  expect((await asked).postData()).toContain("ORCL 11/14/26 250C is past my cut line $3.78 at $3.35. Cut or hold?");
});

test("a line opens its position on the desk", async ({ page }) => {
  await open(page, 1440, 900);
  await rightNow(page).getByRole("button", { name: "Open MU 11/21/26 240P" }).click();
  await expect(page.getByTestId("desk-chart").getByText("MU", { exact: true }).first()).toBeVisible();
});

test("the book row of a position with no plan says how far over its cut line it trades; a planned one keeps its stop", async ({ page }) => {
  await open(page, 1440, 900);
  const book = page.getByTestId("desk-book");
  await expect(book.getByTestId("book-over-cut")).toHaveCount(1);
  await expect(book.getByTestId("book-over-cut")).toHaveText("31% over cut $5.60");
  await expect(book.getByRole("button", { name: "NBIS 11/20/26 100C" })).toContainText("3.1% to stop");
});

test("a Feed row keeps one first step in view and the rest as quiet links on hover", async ({ page }) => {
  await open(page, 1440, 900);
  await page.getByRole("tablist", { name: "Side" }).getByRole("tab").nth(1).click();
  await page.getByTestId("desk-feed").getByRole("button", { name: "All", exact: true }).click();
  const rows = page.getByTestId("feed-item");
  const radar = rows.filter({ hasText: "CRWV volume" });
  await expect(radar.getByRole("button", { name: "Show on chart" })).toBeVisible();
  const more = radar.getByTestId("feed-more");
  await expect(more).toHaveCSS("opacity", "0");
  await radar.hover();
  await expect(more).toHaveCSS("opacity", "1");
  await expect(more.getByRole("button", { name: "Ask the copilot" })).toBeVisible();
  // A story with no ticker leads with its source.
  const news = rows.filter({ hasText: "Yields climb" });
  await expect(news.getByRole("link", { name: "Read at Reuters" })).toHaveClass(/border/);
});

test("nothing needing a look is one quiet line", async ({ page }) => {
  await open(page, 1440, 900, { ...THREADS, threads: THREADS.threads.filter(t => t.symbol === "NBIS") });
  await expect(rightNow(page).getByTestId("right-now-calm")).toHaveText("Nothing needs you · 1 open, none past a cut line or stop.");
});

test("a cut line with no price yet is never called clear", async ({ page }) => {
  const quiet = THREADS.threads.filter(t => t.symbol !== "ORCL").map(t => t.symbol === "MU" ? { ...t, book: { ...t.book, state: "no_plan" } } : t);
  await open(page, 1440, 900, { ...THREADS, threads: quiet }, false);
  // MU has a cut line and no plan, but no price: it cannot be checked. NBIS is planned.
  await expect(rightNow(page).getByTestId("right-now-unchecked")).toHaveText("No price yet for 1 position with a cut line: not checked against it.");
  await expect(rightNow(page).getByTestId("right-now-calm")).toHaveCount(0);
});
