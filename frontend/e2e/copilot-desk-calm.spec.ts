import { expect, test, type Page } from "@playwright/test";
import { writeFileSync } from "node:fs";
import path from "node:path";

// The calm pass (docs/copilot-lab.md § The desk): a busy desk after the close, as the owner saw it on 2026-11-16 (REAL,
// Robinhood stale, a Needs-you alert, eight options, NBIS on the chart, an answered thread). The top bar is one row, the
// chart's header never overlaps itself, health is said once (the book and the status line agree), and only one amber
// thing asks at a time. Every route is stubbed; every number is invented.
const ON = {
  enabled: true, backend: "fake", evidence: "live", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
// Monday November 16, 2026, 17:51 in New York: after the close.
const NOW = new Date("2026-11-16T22:51:00Z");
const epoch = (iso: string) => Date.parse(iso) / 1000;
const AS_OF = epoch("2026-11-16T21:30:00Z"); // Robinhood's last read, 16:30
const NBIS = "11111111-1111-4111-8111-111111111111";
const id = (n: number) => `aaaaaaaa-aaaa-4aaa-8aaa-${String(n).padStart(12, "0")}`;
const row = (fields: Record<string, unknown>) => ({
  symbol: null, instrument: null, value: null, meter: null, investigation_id: null, trade_id: null, radar_event_id: null, path: null,
  changed_at: null, hidden: false, ...fields,
});
const OPTIONS: [string, string, number, number, string, number][] = [
  ["NBIS", "11/21/26 105C", -412, -38.2, "2026-11-21", 2],
  ["NVDA", "11/16/26 190C", -96, -61.0, "2026-11-16", 1],
  ["MU", "11/20/26 100C", 140, 22.4, "2026-11-20", 3],
  ["CRWV", "12/18/26 90C", -310, -18.9, "2026-12-18", 6],
  ["APLD", "11/20/26 31C", 55, 12.1, "2026-11-20", 2],
  ["AMD", "11/27/26 240C", -205, -27.3, "2026-11-27", 4],
  ["TSLA", "11/20/26 420C", -88, -9.6, "2026-11-20", 1],
  ["PLTR", "12/18/26 180C", 190, 15.2, "2026-12-18", 8],
];
const THREADS = {
  as_of: "2026-11-16T22:51:00Z", quotes_at: null, quote_issue: null, day: { phase: "post", need_you: 1, streak: null },
  sections: { positions: "ok", plans: "ok", investigations: "ok" }, plans: [],
  robinhood: { state: "stale", as_of: AS_OF, issue: null },
  threads: OPTIONS.map(([symbol, contract, usd, pct, expiry, days], i) => row({
    key: `trade:${id(i)}`, group: i === 1 ? "act" : "watch", symbol, title: `${symbol} ${contract}`, instrument: contract, trade_id: id(i),
    investigation_id: symbol === "NBIS" ? NBIS : null, value: { text: `${usd < 0 ? "−" : "+"}$${Math.abs(usd)}.00`, tone: usd < 0 ? "loss" : "gain" },
    status: { text: "No plan yet", tone: "muted" }, path: `/trades/${id(i)}`,
    book: { usd, pct, expiry, days_held: days, track: null, state: "no_plan", planned: false, stop_pct: null, option: true },
  })),
};
const SESSION = {
  as_of: "2026-11-16T22:51:00Z", now: epoch("2026-11-16T22:51:00Z"), day: "2026-11-16", phase: "post",
  open: epoch("2026-11-16T14:30:00Z"), close: epoch("2026-11-16T21:00:00Z"), events: [], time_stops: [], pings: null, prep: null,
  indices: [{ symbol: "SPY", last: 650, change_pct: -1.92 }, { symbol: "QQQ", last: 560, change_pct: -2.67 }, { symbol: "VIX", last: 22, change_pct: 18.7 }],
  quote_issue: null, realized_today: 539, sections: {},
  to_answer: { alerts: { count: 1, rows: [{ id: "a1", trade_id: id(1), symbol: "NVDA", contract: "NVDA 11/16/26 190C", kind: "held_hour",
    at: epoch("2026-11-16T19:40:00Z"), today: true, feedback: null }] }, radar: null },
};
type Health = { id: string; name: string; state: string; line: string; last_at: number | null; affects: string; fix: null };
const source = (id: string, name: string, state: string, line: string, last_at: number | null = AS_OF): Health =>
  ({ id, name, state, line, last_at, affects: `${name} affects this.`, fix: null });
/** The minute's health read as the owner's screen had it: Robinhood green beside a book that said stale. */
const HEALTH_ROWS = [
  source("robinhood", "Robinhood", "live", "Live · read 17:50", epoch("2026-11-16T22:50:00Z")),
  source("prices", "Prices", "closed", "Market closed"),
  source("chatter", "Chatter", "live", "Live · read 17:40"),
  source("tradingview", "TradingView", "quiet", "No alerts today"),
  source("gmail", "Fill emails", "live", "Live · last email 15:10"),
  source("radar", "Radar", "closed", "Market closed"),
  source("budget", "Copilot budget", "live", "$2.40 left of $4.00 today", null),
  source("self_check", "Self-check", "down", "1 of 6 failed 9:31: replay", epoch("2026-11-16T14:31:00Z")),
];
const health = (rows: Health[]) => ({ as_of: "2026-11-16T22:51:00Z", now: epoch("2026-11-16T22:51:00Z"), phase: "post", overall: "bad", sources: rows });

/** NBIS: 2-minute candles through the session to 107.44, no previous close in the read (the header takes the book's
 * change, "−7.56% today"), VWAP and volume, earnings ahead (estimated). */
function nbisChart() {
  const close = epoch("2026-11-16T21:00:00Z");
  const bars = Array.from({ length: 120 }, (_, i) => {
    const open = 116 - i * 0.07 + Math.sin(i / 6) * 0.8;
    return { time: close - (120 - i) * 120, open, high: open + 0.4, low: open - 0.4, close: open - 0.05, volume: 2000 + (i % 7) * 300, extended: false };
  });
  return { symbol: "NBIS", timeframe: "2m", step: 120, as_of: epoch("2026-11-16T22:51:00Z"), live: false, state: "ok", reason: null, bars,
    studies: { vwap: bars.map(b => b.close + 0.1), ema9: bars.map(b => b.close - 0.1), ema21: bars.map(b => b.close + 0.3), rvol: bars.map(() => 1.1) }, reference: [],
    reading: { last: 107.44, at: epoch("2026-11-16T22:51:00Z"), daily: false, prev_close: null, vwap: 107.55, vwap_at: epoch("2026-11-16T20:59:00Z"), rvol: 1.1 },
    levels: [], alerts: [{ id: "al1", price: 110, text: "NBIS crosses 110.00", source: "chart", removable: true }],
    marks: [],
    time_stop: null,
    events: { earnings: { next: { date: "2027-02-12", status: "estimated", label: null, implied: null }, last: null }, macro: [], note: null } };
}
const saved = { id: NBIS, source: "copilot", title: "NBIS plan", symbol: "NBIS", status: "open", conclusion: null, revision: 1, message_count: 2,
  has_findings: false, created_at: "2026-11-16T20:00:00Z", updated_at: "2026-11-16T22:40:00Z", evidence: [], findings: null,
  transcript: [{ role: "user", content: "Why is NBIS down today?" }, { role: "assistant", content:
    "NBIS fell 7.6% with the AI-infrastructure group: CRWV −9%, APLD −6%. No company news today. It closed under VWAP 107.55 on 1.1× usual volume.\n\nYour 105C has 5 days left and is down 38%; the plan has no invalidation saved, so nothing on the chart says where you are wrong." }] };

async function busyDesk(page: Page, { width = 1440, height = 900, healthRows = HEALTH_ROWS, path: at = `/copilot-lab?investigation=${NBIS}`, robinhood = THREADS.robinhood as unknown } = {}) {
  const reads: Record<string, unknown> = {
    "/copilot/desk/threads": { ...THREADS, robinhood },
    "/copilot/desk/session": SESSION,
    "/copilot/desk/health": health(healthRows),
    "/copilot/desk/watching": { state: "ok", symbols: [], count: 0, max: 30, imported_at: null, robinhood: "off", levels: {}, setups: {} },
    "/copilot/desk/sparks": { as_of: "2026-11-16T22:51:00Z", spy_change_pct: -1.92,
      rows: Object.fromEntries(OPTIONS.map(([symbol], i) => [symbol, { points: [100, 99 - i % 3, 98, 97 + i % 2], change_pct: symbol === "NBIS" ? -7.56 : -2 - i / 3 }])) },
    "/copilot/desk/moving": { state: "ok", mode: "live", session: "2026-11-16", as_of: "2026-11-16T22:51:00Z", reason: null,
      groups: [{ key: "SPY", label: "SPY", kind: "index", symbol: "SPY", change_pct: -1.92, members: [] }], movers: [] },
    "/copilot/desk/feed": { as_of: "2026-11-16T22:51:00Z", now: epoch("2026-11-16T22:51:00Z"), day: "2026-11-16", total: 0, sources: {}, unavailable: [], items: [] },
    "/copilot/investigations": { investigations: [] },
    "/copilot/tickets": { plans: [] },
    "/copilot/unusual": { state: "ok", rows: [], tickers: [], unread: [], no_history: [], stale: [], rule: "" },
    "/copilot/scanner": { state: "off", rows: [] },
    "/copilot/exposure": { state: "ok", at_risk_usd: 1969, positions: 5, usual_day_usd: 1068, sample_days: 20, as_of: "2026-11-16T22:51:00Z",
      line: "At risk now: $1,969 in 5 options · usual day $1,068" },
  };
  await page.setViewportSize({ width, height });
  await page.clock.install({ time: NOW });
  await page.route("**/api/backend/**", route => route.fulfill({ status: 404, json: { detail: "Not in this test." } }));
  await page.route("**/copilot/status", route => route.fulfill({ json: ON }));
  for (const [p, json] of Object.entries(reads)) await page.route(url => url.pathname.endsWith(p), route => route.fulfill({ json }));
  await page.route(`**/copilot/investigations/${NBIS}`, route => route.fulfill({ json: saved }));
  await page.route("**/copilot/chat", route => route.abort());
  await page.route("**/copilot/research-jobs?*", route => route.fulfill({ json: { jobs: [], queue_enabled: true, daily_budget_usd: 2, spent_today_usd: 0 } }));
  await page.route("**/copilot/desk/*/news*", route => route.fulfill({ json: { state: "none", groups: [], complete_from: null, as_of: epoch("2026-11-16T22:51:00Z") } }));
  await page.route("**/copilot/desk/*/chart*", route => route.fulfill({ json: nbisChart() }));
  await page.route("**/copilot/desk/minute?*", route => {
    const answers = new URL(route.request().url()).searchParams.getAll("read").map(target => {
      const json = reads[target.split("?")[0]];
      return json ? { status: 200, body: json } : { status: 404, body: { detail: "Not in this test." } };
    });
    return route.fulfill({ json: { reads: answers } });
  });
  await page.goto(at);
  await expect(page.getByTestId("desk-book")).toBeVisible();
}

/** What the first screen offers: visible buttons, links and tabs, and visible pieces of text outside them. */
async function firstScreen(page: Page) {
  return page.evaluate(() => {
    const W = window.innerWidth, H = window.innerHeight;
    const shown = (el: Element) => {
      const box = el.getBoundingClientRect();
      if (box.width < 2 || box.height < 2 || box.bottom <= 0 || box.top >= H || box.right <= 0 || box.left >= W) return false;
      for (let at: Element | null = el; at; at = at.parentElement) {
        const style = getComputedStyle(at);
        if (style.display === "none" || style.visibility === "hidden" || style.opacity === "0") return false;
      }
      return true;
    };
    const desk = document.querySelector("[data-on]") ?? document.body;
    const controls = [...desk.querySelectorAll("button, a[href], [role=tab], [role=button], select, textarea")].filter(shown);
    const inControl = (el: Element) => !!el.closest("button, a[href], [role=tab], [role=button]");
    const texts = [...desk.querySelectorAll("*")].filter(el => !inControl(el) && [...el.childNodes].some(n => n.nodeType === 3 && n.textContent!.trim())
      && shown(el) && !el.closest(".sr-only"));
    return { controls: controls.length, texts: texts.length };
  });
}

for (const width of [1440, 1280]) {
  test(`one top-bar row and a chart header that never overlaps itself at ${width} px`, async ({ page }) => {
    await busyDesk(page, { width });
    // The bar: Menu, Desk, the mode switch, then the buttons, all on one line; no market line, day money or accounts row.
    const bar = page.locator("header").filter({ has: page.getByRole("heading", { name: "Desk" }) }).locator("xpath=..");
    const centres = await bar.locator("button:visible, a:visible, h1:visible").evaluateAll(els => els.map(el => {
      const box = el.getBoundingClientRect();
      return box.top + box.height / 2;
    }));
    expect(centres.length).toBeGreaterThan(4);
    expect(Math.max(...centres) - Math.min(...centres)).toBeLessThan(8);
    expect((await bar.boundingBox())!.height).toBeLessThan(60);
    for (const gone of ["desk-status", "desk-pnl", "desk-accounts"]) await expect(page.getByTestId(gone)).toHaveCount(0);
    await expect(bar.getByRole("link", { name: "Now" })).toHaveCount(0);
    await expect(bar.getByRole("button", { name: "Plan a trade" })).toHaveCount(0);

    // The chart's header: the price and today's change sit whole before the timeframes, never under them.
    const head = page.getByTestId("desk-chart-head");
    await expect(head.getByTestId("desk-reading-last")).toHaveText("107.44");
    await expect(head.getByTestId("desk-reading").locator('[data-part="change"]')).toHaveText("−7.56%");
    await expect(head.getByTestId("desk-reading").locator('[data-part="change"]')).toHaveAttribute("title", /^The book's change today/);
    const reading = (await head.getByTestId("desk-reading").boundingBox())!;
    const title = (await head.getByTestId("desk-chart-title").boundingBox())!;
    const frames = (await head.getByRole("group", { name: "Timeframe" }).boundingBox())!;
    expect(reading.x + reading.width).toBeLessThanOrEqual(title.x + title.width + 0.5); // not clipped
    expect(title.x + title.width).toBeLessThanOrEqual(frames.x); // not over the timeframes
    const tops = await head.locator("button:visible").evaluateAll(els => els.map(el => el.getBoundingClientRect().top));
    expect(Math.max(...tops) - Math.min(...tops)).toBeLessThan(8); // one row
  });
}

test("a phone: one top row, no market line under it; its health dot stays (no status line there)", async ({ page }) => {
  await busyDesk(page, { width: 375, height: 812, path: "/copilot-lab" });
  const row = page.getByTestId("desk-views").locator("xpath=..");
  expect((await row.boundingBox())!.height).toBeLessThan(60);
  await expect(page.getByTestId("desk-status")).toHaveCount(0);
  // The value block comes straight under the top row.
  const rowBottom = (await row.boundingBox())!.y + (await row.boundingBox())!.height;
  const value = (await page.getByTestId("desk-value").boundingBox())!;
  expect(value.y - rowBottom).toBeLessThan(24);
  await expect(page.getByTestId("desk-health")).toHaveAttribute("data-tone", "red");
  await expect(page.getByTestId("desk-status-line")).toHaveCount(0);
  await expect(page.getByTestId("needs-you")).toBeVisible();
  await expect(page.getByTestId("desk-book").getByRole("button", { name: /^NVDA / })).toBeVisible();
});

test("health said once: the book's stale Robinhood is the status line's and the bar's, in red; all fine says so once", async ({ page }) => {
  await busyDesk(page);
  // The health read said Robinhood was live; the book's read said stale as of 16:30. Both now say behind.
  await expect(page.getByTestId("book-live")).toHaveText("Robinhood stale · as of 4:30 PM");
  const status = page.getByTestId("desk-status-line");
  await expect(status.getByTestId("status-robinhood")).toHaveAttribute("data-tone", "red");
  await expect(status.getByTestId("status-robinhood")).toHaveText("Robinhood behind since 16:30");
  await expect(status.getByTestId("status-self_check")).toHaveText("Self-check down since 09:31");
  // Fine sources are not listed one by one: the full list is a tap away.
  await expect(status.getByTestId("status-chatter")).toHaveCount(0);
  await expect(page.getByTestId("desk-health")).toHaveAttribute("data-tone", "red"); // a money source behind: the bar says it too
  await status.click();
  await expect(page.getByTestId("health-robinhood")).toContainText("The book says stale · as of 16:30");
  await expect(page.getByTestId("health-chatter")).toHaveAttribute("data-state", "live");
});

test("the book read live, the health read behind (only its orders, say): the book says the status line's words, ↻ kept", async ({ page }) => {
  const behind = HEALTH_ROWS.map(r => r.id === "robinhood"
    ? source("robinhood", "Robinhood", "stale", "Positions live · orders last read 16:30", AS_OF) : r);
  await busyDesk(page, { healthRows: behind, path: "/copilot-lab", robinhood: { state: "ok", joined: true, as_of: epoch("2026-11-16T22:50:00Z"), accounts: [] } });
  await expect(page.getByTestId("book-live")).toHaveText("Robinhood behind since 16:30");
  await expect(page.getByTestId("status-robinhood")).toHaveText("Robinhood behind since 16:30");
  await expect(page.getByTestId("book-live-again")).toHaveAccessibleName("Read Robinhood again");
});

test("a live read whose join failed: the book says unavailable, and so does the status line", async ({ page }) => {
  const live = HEALTH_ROWS.map(r => r.id === "self_check" ? source("self_check", "Self-check", "live", "6 of 6 passed 9:31") : r);
  await busyDesk(page, { healthRows: live, path: "/copilot-lab", robinhood: { state: "ok", joined: false, as_of: AS_OF } });
  await expect(page.getByTestId("book-live")).toHaveText("Robinhood unavailable · as of 4:30 PM");
  await expect(page.getByTestId("status-robinhood")).toHaveAttribute("data-tone", "red");
  await expect(page.getByTestId("status-fine")).toHaveCount(0);
});

test("nothing behind: no dot in the bar, and the status line says it once", async ({ page }) => {
  const fine = HEALTH_ROWS.map(r => r.id === "self_check" ? source("self_check", "Self-check", "live", "6 of 6 passed 9:31") : r);
  await busyDesk(page, { healthRows: fine, path: "/copilot-lab", robinhood: { state: "off" } });
  await expect(page.getByTestId("status-fine")).toHaveText("Market closed · all fine");
  await expect(page.getByTestId("desk-health")).toHaveCount(0);
  await expect(page.getByTestId("book-live")).toHaveCount(0);
});

test("one amber thing at a time; the book is one heading line; the chart is candles; an answer has one row under it", async ({ page }) => {
  await busyDesk(page);
  // The Needs-you strip asks; the Day button is plain.
  await expect(page.getByTestId("needs-you")).toBeVisible();
  await expect(page.getByTestId("desk-day-button")).not.toHaveAttribute("data-amber", "true");

  // The book: "Your book · 8 · at risk $1,969" and REAL; "usual day" and the day's money on hover; no sparkline.
  const book = page.getByTestId("desk-book");
  await expect(book.getByTestId("book-head").getByRole("heading")).toHaveText(/^Your book · 8/);
  await expect(book.getByTestId("exposure-line")).toHaveText("· at risk $1,969");
  await expect(book.getByTestId("exposure-line")).toHaveAttribute("title", "At risk now: $1,969 in 5 options · usual day $1,068");
  await expect(book.getByTestId("book-head").getByRole("heading")).toHaveAttribute("title", /Open −\$726 · Realized today \+\$539/);
  await expect(book.getByRole("img", { name: /today$/ })).toHaveCount(0);
  // Positions stay, with their P&L and tags; the pen and the eye wait for the row's hover.
  await expect(book.getByRole("button", { name: /^NVDA / })).toContainText("0DTE · ");
  const tools = book.getByTestId("book-row-tools").first();
  await expect(tools).toHaveCSS("opacity", "0");
  await book.locator("li").filter({ has: page.getByRole("button", { name: /^NVDA / }) }).hover();
  await expect(tools).toHaveCSS("opacity", "1");

  // The chart: no facts lines, no corner read-out until the pointer is on it, no key row (no paper or momentum marks
  // drawn, Real mode: the key is the ⓘ's), no library logo.
  const centre = page.getByRole("region", { name: "Chart and tools" });
  await expect(centre.getByTestId("desk-chart-facts")).toBeHidden();
  await expect(centre.getByTestId("desk-chart-readout")).toBeHidden();
  await expect(centre.getByTestId("desk-chart-legend")).toBeHidden(); // only inside the closed ⓘ
  await expect(centre.locator("#tv-attr-logo")).toHaveCount(0);
  await centre.getByTestId("desk-chart-canvas").hover();
  await expect(centre.getByTestId("desk-chart-readout")).toBeVisible();
  // The ⓘ: every fact that left the default view, the key and the library's attribution.
  await centre.getByTestId("desk-chart-info").click();
  const info = page.getByTestId("desk-chart-info-panel");
  await expect(info.getByTestId("desk-chart-lines")).toContainText("no plan lines saved");
  await expect(info.getByTestId("desk-chart-earnings")).toHaveText("Earnings Feb 12 (est.)");
  await expect(info.getByTestId("desk-reading-facts")).toContainText("−0.10% vs VWAP 107.55");
  await expect(info.getByTestId("desk-chart-legend")).toContainText("your fills");
  await expect(info.getByRole("link", { name: "TradingView Lightweight Charts™" })).toHaveAttribute("href", "https://www.tradingview.com/");
  await page.keyboard.press("Escape");
  await expect(info).toBeHidden();

  // The earnings chip's card shows on hover and goes with it; focus left on the chip never reopens it.
  const chip = centre.getByTestId("desk-chart-event").first();
  await chip.hover();
  await expect(centre.getByTestId("desk-chart-event-tip")).toBeVisible();
  await page.mouse.move(5, 5);
  await expect(centre.getByTestId("desk-chart-event-tip")).toHaveCount(0);
  await chip.click();
  await page.mouse.move(5, 5);
  await chip.evaluate(el => { (el as HTMLElement).blur(); (el as HTMLElement).focus(); }); // the window coming back
  await expect(centre.getByTestId("desk-chart-event-tip")).toHaveCount(0);

  // The copilot: one row under the answer (Helped / Didn't as icons, Research deeper); no suggestion chips mid-conversation.
  const talk = page.getByRole("region", { name: "Conversation" });
  const rate = talk.getByRole("group", { name: "Rate this answer" });
  await expect(rate.getByRole("button")).toHaveCount(2);
  await expect(rate.getByRole("button", { name: "Helped" })).toBeVisible();
  await expect(talk.getByRole("button", { name: "Research deeper" })).toBeVisible();
  await expect(talk.getByRole("group", { name: "Suggestions" })).toHaveCount(0);
});

test("everything that left the bar is still one ⌘K away", async ({ page }) => {
  await busyDesk(page);
  await page.getByRole("button", { name: "Jump to a thread or command" }).click();
  const box = page.getByRole("dialog", { name: "Jump to" });
  await box.getByRole("combobox").fill("spy");
  await expect(box.getByRole("option").first()).toContainText("Today: Closed 16:00 · SPY −1.92% QQQ −2.67% VIX +18.70%");
  await expect(box.getByRole("option").first()).toContainText("Open −$726 · Realized today +$539");
  await box.getByRole("combobox").fill("plan a trade");
  await expect(box.getByRole("option").first()).toContainText("Plan a trade");
  await box.getByRole("combobox").fill("now");
  await expect(box.getByRole("option").first()).toContainText("Now");
  await box.getByRole("combobox").fill("data health");
  await box.getByRole("option").first().click();
  await expect(page.getByTestId("desk-health-list")).toBeVisible();
});

// Before/after evidence for the pull request: screenshots and counts, written where CALM_SHOTS points. Skipped otherwise.
test("calm: screenshots and first-screen counts", async ({ page }) => {
  const dir = process.env.CALM_SHOTS;
  test.skip(!dir, "CALM_SHOTS is not set");
  const label = process.env.CALM_LABEL ?? "after";
  const counts: Record<string, unknown> = {};
  for (const width of [1440, 375]) {
    // A phone opens on its Positions view (a thread's link would open the copilot's sheet over it).
    await busyDesk(page, { width, height: width < 768 ? 812 : 900, ...(width < 768 ? { path: "/copilot-lab" } : {}) });
    await expect(page.getByTestId("desk-chart-canvas").first()).toBeAttached();
    await page.waitForTimeout(1500);
    counts[width] = await firstScreen(page);
    await page.screenshot({ path: path.join(dir!, `${label}-${width}.png`) });
  }
  writeFileSync(path.join(dir!, `${label}-counts.json`), JSON.stringify(counts, null, 2));
});
