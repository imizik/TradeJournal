import { expect, test, type Page } from "@playwright/test";

// Where things live on the desk (docs/copilot-lab.md § The desk, Where things live): the centre is the selected ticker's
// tools only (Chart, Chain, Ticket, Check a call, Grid); the Feed sits beside the copilot behind its tab, so the chart
// stays while he reads it and the Feed keeps its place; every place has a key and a ⌘K command; a phone shows one view
// at a time under a switch (Book, the ticker, Feed) with the Needs-you strip on the Book; between 768 and 1180 px the
// Feed is a drawer; outside the session the day's block comes straight after the book. Every route is stubbed.
const ON = {
  enabled: true, backend: "fake", evidence: "live", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
// Friday November 13, 2026, 11:00 in New York: in the session.
const NOW = new Date("2026-11-13T16:00:00Z");
const epoch = (iso: string) => Date.parse(iso) / 1000;
const ORCL = "99999999-9999-4999-8999-999999999999";
const THREADS = {
  as_of: "2026-11-13T16:00:00Z", quotes_at: null, quote_issue: null, day: { phase: "regular", need_you: 1, streak: null },
  sections: { positions: "ok" }, plans: [], robinhood: { state: "off" },
  threads: [{
    key: `trade:${ORCL}`, group: "watch", symbol: "ORCL", title: "ORCL 11/20/26 250C", instrument: "11/20/26 250C", trade_id: ORCL,
    value: { text: "−$120.00", tone: "loss" }, status: { text: "No plan yet", tone: "muted" }, path: `/trades/${ORCL}`, hidden: false,
    meter: null, investigation_id: null, radar_event_id: null, changed_at: null,
    book: { usd: -120, pct: -54.5, expiry: "2026-11-20", days_held: 1, track: null, state: "no_plan", planned: false, stop_pct: null },
  }],
};
const SESSION = {
  as_of: "2026-11-13T16:00:00Z", now: epoch("2026-11-13T16:00:00Z"), day: "2026-11-13", phase: "regular",
  open: epoch("2026-11-13T14:30:00Z"), close: epoch("2026-11-13T21:00:00Z"), events: [], time_stops: [], pings: null, prep: null,
  indices: [], quote_issue: null, realized_today: 0, sections: {},
  // One thing needs him: ORCL's give-back alert, not answered yet.
  to_answer: { alerts: { count: 1, rows: [{ id: "a1", trade_id: ORCL, symbol: "ORCL", contract: "ORCL 11/20/26 250C", kind: "giveback",
    at: epoch("2026-11-13T15:51:00Z"), today: true, feedback: null }] }, radar: null },
};
const item = (over: Record<string, unknown>) => ({
  has_time: true, symbol: null, detail: null, publisher: null, url: null, href: null, investigation_id: null, radar_event_id: null,
  setup: null, plan: null, mine: false, upcoming: false, ...over,
});
const FEED = {
  as_of: "2026-11-13T16:00:00Z", now: epoch("2026-11-13T16:00:00Z"), day: "2026-11-13", total: 3, sources: {}, unavailable: [],
  items: [
    item({ id: "tv:nvda", source: "TradingView", at: epoch("2026-11-13T15:46:00Z"), symbol: "NVDA", text: "ORB break long · 5m at 199.12", mine: true }),
    item({ id: "radar:mu", source: "Radar", at: epoch("2026-11-13T15:10:00Z"), symbol: "MU", text: "MU up 4.1% while SMH is up 0.6%", href: "/radar?event=1" }),
    item({ id: "news:fed", source: "News", at: epoch("2026-11-13T15:00:00Z"), text: "Yields climb before the Fed minutes", publisher: "Reuters" }),
  ],
};
const READS: Record<string, unknown> = {
  "/copilot/desk/threads": THREADS,
  "/copilot/desk/session": SESSION,
  "/copilot/desk/watching": { state: "ok", symbols: ["NVDA"], count: 1, max: 30, imported_at: null, robinhood: "off", levels: {}, setups: {} },
  "/copilot/desk/sparks": { as_of: "2026-11-13T16:00:00Z", spy_change_pct: 0.4, rows: { ORCL: { points: [250, 248, 246], change_pct: -1.2 }, NVDA: { points: [198, 199], change_pct: 0.7, last: 199 } } },
  "/copilot/desk/moving": { state: "ok", mode: "live", session: "2026-11-13", as_of: "2026-11-13T16:00:00Z", reason: null, groups: [], movers: [] },
  "/copilot/desk/feed": FEED,
  "/copilot/investigations": { investigations: [] },
  "/copilot/tickets": { plans: [] },
  "/copilot/unusual": { state: "ok", rows: [], tickers: [], unread: [], no_history: [], stale: [], rule: "" },
  "/copilot/scanner": { state: "off", rows: [] },
  "/copilot/exposure": { line: null },
};

/** A symbol's chart read: 60 two-minute candles. */
function chart(symbol: string) {
  const last = epoch("2026-11-13T16:00:00Z");
  const bars = Array.from({ length: 60 }, (_, i) => {
    const open = 200 + Math.sin(i / 5);
    return { time: last - (59 - i) * 120, open, high: open + 0.4, low: open - 0.4, close: open + 0.1, volume: 1000, extended: false };
  });
  return { symbol, timeframe: "2m", step: 120, as_of: last, live: false, state: "ok", reason: null, bars, studies: {}, reference: [],
    reading: { last: 200, at: last, daily: false, prev_close: 199, vwap: null, vwap_at: null, rvol: null }, levels: [], alerts: [], marks: [], time_stop: null,
    events: { earnings: null, macro: [], note: null } };
}

async function open(page: Page, { width = 1440, height = 900, time = NOW }: { width?: number; height?: number; time?: Date } = {}) {
  await page.setViewportSize({ width, height });
  await page.clock.install({ time });
  await page.route("**/api/backend/**", route => route.fulfill({ status: 404, json: { detail: "Not in this test." } }));
  await page.route("**/copilot/status", route => route.fulfill({ json: ON }));
  for (const [path, body] of Object.entries(READS)) await page.route(url => url.pathname.endsWith(path), route => route.fulfill({ json: body }));
  await page.route("**/copilot/desk/*/chart*", route => {
    const id = decodeURIComponent(new URL(route.request().url()).pathname.split("/").at(-2) ?? "");
    return route.fulfill({ json: chart(id.includes(":") ? id.split(":").pop()! : "QQQ") });
  });
  await page.route("**/copilot/desk/minute?*", route => {
    const reads = new URL(route.request().url()).searchParams.getAll("read").map(target => {
      const body = READS[target.split("?")[0]];
      return body ? { status: 200, body } : { status: 404, body: { detail: "Not in this test." } };
    });
    return route.fulfill({ json: { reads } });
  });
  await page.goto("/copilot-lab");
  await expect(page.getByTestId("desk-book")).toBeVisible();
}

const centre = (page: Page) => page.getByRole("region", { name: "Chart and tools" });
const conversation = (page: Page) => page.getByRole("region", { name: "Conversation" });
const feedPane = (page: Page) => page.getByTestId("desk-feed-pane");

test("the centre is the ticker's tools; the Feed sits beside the copilot, keeps the chart on show and keeps its place", async ({ page }) => {
  await open(page);
  await expect(centre(page).getByRole("tab")).toHaveText(["Chart", "Chain", "Ticket", "Check a call", "Grid"]);
  const side = page.getByRole("tablist", { name: "Side" }).getByRole("tab");
  await expect(side).toHaveText(["Copilot", "Feed1 new"]);
  await expect(side.nth(0)).toHaveAttribute("aria-selected", "true");
  await expect(conversation(page)).toBeVisible();
  await expect(feedPane(page)).toBeHidden();

  // The Feed takes the copilot's column; the chart stays where it is.
  await side.nth(1).click();
  await expect(feedPane(page)).toBeVisible();
  await expect(conversation(page)).toBeHidden();
  await expect(centre(page).getByTestId("desk-chart")).toBeVisible();
  const feed = page.getByTestId("desk-feed");
  // His TradingView alert's Show on chart: the ticker on the chart, in place, with the Feed still beside it.
  await feed.getByTestId("feed-item").getByRole("button", { name: "Show on chart" }).click();
  await expect(centre(page).getByTestId("desk-chart").getByText("NVDA", { exact: true }).first()).toBeVisible();
  await expect(feedPane(page)).toBeVisible();
  // A position picked in the book: the chart moves to it, and the Feed is not taken away.
  await page.getByTestId("desk-book").getByRole("button", { name: "ORCL 11/20/26 250C" }).click();
  await expect(centre(page).getByTestId("desk-chart").getByText("ORCL", { exact: true }).first()).toBeVisible();
  await expect(feedPane(page)).toBeVisible();

  // The Feed is where he left it after a look at the copilot.
  await feed.getByRole("button", { name: "Ideas", exact: true }).click();
  await expect(feed.getByTestId("feed-item")).toHaveText([/MU up 4.1% while SMH is up 0.6%/]);
  await side.nth(0).click();
  await expect(conversation(page)).toBeVisible();
  await expect(feedPane(page)).toBeHidden();
  await side.nth(1).click();
  await expect(feed.getByRole("button", { name: "Ideas", exact: true })).toHaveAttribute("aria-pressed", "true");
  await expect(feed.getByTestId("feed-item")).toHaveText([/MU up 4.1% while SMH is up 0.6%/]);

  // Ask the copilot on a Feed row brings the copilot forward with the question in the box, unsent.
  await feed.getByTestId("feed-item").getByRole("button", { name: "Ask the copilot" }).click();
  await expect(conversation(page)).toBeVisible();
  await expect(side.nth(0)).toHaveAttribute("aria-selected", "true");
  // Now, from the Feed: today's Main chat comes forward too.
  await side.nth(1).click();
  await expect(feedPane(page)).toBeVisible();
  await page.getByRole("link", { name: "Now", exact: true }).click();
  await expect(conversation(page)).toBeVisible();
  await expect(feedPane(page)).toBeHidden();
});

test("every place has a key and a ⌘K command; keys typed in the message box are ignored", async ({ page }) => {
  await open(page);
  const tab = (name: string) => centre(page).getByRole("tab", { name, exact: true });
  for (const [key, name] of [["o", "Chain"], ["t", "Ticket"], ["l", "Check a call"], ["g", "Grid"], ["c", "Chart"]] as const) {
    await page.keyboard.press(key);
    await expect(tab(name)).toHaveAttribute("aria-selected", "true");
  }
  // F shows the Feed, F again the copilot.
  await page.keyboard.press("f");
  await expect(feedPane(page)).toBeVisible();
  await page.keyboard.press("f");
  await expect(feedPane(page)).toBeHidden();
  await expect(conversation(page)).toBeVisible();
  // ⌘K: a place by name.
  await page.keyboard.press("ControlOrMeta+k");
  await page.keyboard.type("chain");
  const palette = page.getByRole("dialog", { name: "Jump to" });
  await expect(palette.getByRole("option")).toHaveText([/^Chain.*O$/]);
  await page.keyboard.press("Enter");
  await expect(tab("Chain")).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("ControlOrMeta+k");
  await page.keyboard.type("feed");
  await page.keyboard.press("Enter");
  await expect(feedPane(page)).toBeVisible();
  // B puts the keys on the book's first row.
  await page.keyboard.press("b");
  await expect(page.getByTestId("desk-book").getByRole("button", { name: "ORCL 11/20/26 250C" })).toBeFocused();
  // / brings the copilot forward and puts the keys in its message box, where a place's key is only a letter.
  await page.keyboard.press("/");
  const message = page.getByRole("textbox", { name: "Message" });
  await expect(message).toBeFocused();
  await expect(feedPane(page)).toBeHidden();
  await page.keyboard.type("cfg");
  await expect(message).toHaveValue("cfg");
  await expect(tab("Chain")).toHaveAttribute("aria-selected", "true");
  await expect(feedPane(page)).toBeHidden();
});

test("a phone: one view at a time under the switch, the strip on the Book, the ticker named on its button", async ({ page }) => {
  await open(page, { width: 390, height: 844 });
  const views = page.getByTestId("desk-views").getByRole("button");
  await expect(views).toHaveText(["Book", "ORCL", "Feed1 new"]);
  // It opens on the Book: what needs him, then his positions; the ticker's tools and the Feed wait behind the switch.
  await expect(views.nth(0)).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId("needs-you")).toBeVisible();
  await expect(page.getByTestId("desk-book")).toBeVisible();
  await expect(centre(page)).toBeHidden();
  await expect(feedPane(page)).toBeHidden();
  expect((await page.getByTestId("needs-you").boundingBox())!.y).toBeLessThan((await page.getByTestId("desk-book").boundingBox())!.y);

  // The Feed: one tap, and the Book's button carries the amber count of what needs him.
  await views.nth(2).click();
  await expect(feedPane(page)).toBeVisible();
  await expect(page.getByTestId("desk-book")).toBeHidden();
  await expect(page.getByTestId("needs-you")).toBeHidden();
  await expect(page.getByTestId("desk-view-needs")).toHaveText("1 need you");
  // A Feed row's Show on chart goes to the ticker's view, named for it, with a chart that fills its width.
  await page.getByTestId("desk-feed").getByTestId("feed-item").getByRole("button", { name: "Show on chart" }).click();
  await expect(views).toHaveText(["Book1 need you", "NVDA", "Feed"]);
  await expect(views.nth(1)).toHaveAttribute("aria-pressed", "true");
  await expect(centre(page).getByTestId("desk-chart").getByText("NVDA", { exact: true }).first()).toBeVisible();
  await expect(centre(page).getByRole("tab")).toHaveText(["Chart", "Chain", "Ticket", "Check a call", "Grid"]);
  await expect(centre(page).getByTestId("desk-chart-canvas")).toHaveAttribute("data-bars", "60");
  await expect.poll(async () => Number((await centre(page).getByTestId("desk-chart-canvas").getAttribute("data-edges"))?.split(",")[0])).toBeLessThan(40);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);

  // Back to the Book: the strip again, no count on the button; a position's row opens its ticker's view.
  await views.nth(0).click();
  await expect(page.getByTestId("needs-you")).toBeVisible();
  await expect(page.getByTestId("desk-view-needs")).toHaveCount(0);
  await page.getByTestId("desk-book").getByRole("button", { name: "ORCL 11/20/26 250C" }).click();
  await expect(views.nth(1)).toHaveAttribute("aria-pressed", "true");
  await expect(views.nth(1)).toHaveText("ORCL");
  await expect(centre(page).getByTestId("desk-chart")).toBeVisible();
  // The copilot is still its sheet, behind the round button.
  await expect(conversation(page)).toBeHidden();
  await page.getByRole("button", { name: /^Ask the copilot/ }).click();
  await expect(conversation(page)).toBeVisible();
});

test("a phone turned on its side keeps the Feed on show, as the drawer, and back as its view", async ({ page }) => {
  await open(page, { width: 390, height: 844 });
  await page.getByTestId("desk-view-feed").click();
  await expect(feedPane(page)).toBeVisible();
  await page.setViewportSize({ width: 844, height: 390 });
  await expect(feedPane(page)).toBeVisible();
  await expect(page.getByRole("button", { name: /^Feed/ })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId("desk-book")).toBeVisible(); // the drawer sits over the centre; the book is beside it
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByTestId("desk-view-feed")).toHaveAttribute("aria-pressed", "true");
  await expect(feedPane(page)).toBeVisible();
  await expect(page.getByTestId("desk-book")).toBeHidden();
});

test("between 768 and 1180 px the Feed is a drawer from the top bar; Escape closes it", async ({ page }) => {
  await open(page, { width: 1024, height: 768 });
  await expect(page.getByRole("tablist", { name: "Side" })).toBeHidden();
  await expect(page.getByTestId("desk-views")).toBeHidden();
  const button = page.getByRole("button", { name: /^Feed/ });
  await expect(button.getByTestId("feed-new-bar")).toHaveText("1 new");
  await button.click();
  await expect(feedPane(page)).toBeVisible();
  await expect(page.getByTestId("desk-book")).toBeVisible(); // the book stays beside it
  await page.keyboard.press("Escape");
  await expect(feedPane(page)).toBeHidden();
  await button.click();
  await feedPane(page).getByRole("button", { name: "Close the Feed" }).click();
  await expect(feedPane(page)).toBeHidden();
});

test("the day's block comes straight after the book outside the session, and under Watching in it", async ({ page }) => {
  const top = async (locator: ReturnType<Page["getByTestId"]>) => (await locator.boundingBox())!.y;
  const watching = () => page.getByRole("region", { name: "Watching" });
  await open(page);
  await expect(page.getByTestId("since-you-looked")).toBeVisible();
  expect(await top(page.getByTestId("desk-book"))).toBeLessThan(await top(watching()));
  expect(await top(watching())).toBeLessThan(await top(page.getByTestId("since-you-looked")));
});

test("after the close the day report comes before Watching", async ({ page }) => {
  const top = async (locator: ReturnType<Page["getByTestId"]>) => (await locator.boundingBox())!.y;
  await open(page, { time: new Date("2026-11-13T21:30:00Z") }); // 16:30 New York
  await expect(page.getByTestId("day-report")).toBeVisible();
  expect(await top(page.getByTestId("desk-book"))).toBeLessThan(await top(page.getByTestId("day-report")));
  expect(await top(page.getByTestId("day-report"))).toBeLessThan(await top(page.getByRole("region", { name: "Watching" })));
});
