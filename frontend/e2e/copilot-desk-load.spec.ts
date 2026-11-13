import { expect, test, type Page, type Route } from "@playwright/test";

// What an open desk asks the server while it sits idle (docs/copilot-lab.md § What an open desk asks): in the session, live
// prices every few seconds and the minute's re-reads as ONE request; nothing at all while the page is hidden; one catch-up
// read when it shows again. Pins the idle rate so new desk pieces cannot quietly add pollers. Every route is stubbed.
const ON = {
  enabled: true, backend: "fake", evidence: "live", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
// Friday November 13, 2026, 11:00 in New York: in the session.
const NOW = new Date("2026-11-13T16:00:00Z");
const epoch = (iso: string) => Date.parse(iso) / 1000;
const ORCL = "99999999-9999-4999-8999-999999999999";
const CALL = "ORCL261120C00050000";
const THREADS = {
  as_of: "2026-11-13T16:00:00Z", quotes_at: null, quote_issue: null, day: { phase: "regular", need_you: 0, streak: null },
  sections: { positions: "ok" }, plans: [], robinhood: { state: "off" },
  threads: [{
    key: `trade:${ORCL}`, group: "watch", symbol: "ORCL", title: "ORCL 11/20/26 50C", instrument: "11/20/26 50C", trade_id: ORCL,
    value: { text: "−$120.00", tone: "loss" }, status: { text: "No plan yet", tone: "muted" }, path: `/trades/${ORCL}`, hidden: false,
    meter: null, investigation_id: null, radar_event_id: null, changed_at: null,
    book: { usd: -120, pct: -54.5, expiry: "2026-11-20", days_held: 1, track: null, state: "no_plan", planned: false, stop_pct: null,
      tick: { quote: CALL, scale: 100, cost: 220, quantity: 1, sign: 1 } },
  }],
};
const SESSION = {
  as_of: "2026-11-13T16:00:00Z", now: epoch("2026-11-13T16:00:00Z"), day: "2026-11-13", phase: "regular",
  open: epoch("2026-11-13T14:30:00Z"), close: epoch("2026-11-13T21:00:00Z"), events: [], time_stops: [], pings: null, prep: null,
  indices: [], quote_issue: null, realized_today: 0, sections: {},
};
// The desk's reads by path (no query): each answers the same whether asked alone or inside the minute's one request.
const READS: Record<string, unknown> = {
  "/copilot/desk/threads": THREADS,
  "/copilot/desk/session": SESSION,
  "/copilot/desk/watching": { state: "ok", symbols: ["NVDA", "MU"], count: 2, max: 30, imported_at: null, robinhood: "off", levels: {}, setups: {} },
  "/copilot/desk/sparks": { as_of: "2026-11-13T16:00:00Z", spy_change_pct: 0.4, rows: {
    ORCL: { points: [250, 248, 246], change_pct: -1.2 }, NVDA: { points: [99, 100, 100.5], change_pct: 0.5, last: 100.5 } } },
  "/copilot/desk/moving": { state: "unavailable", mode: "live", as_of: "2026-11-13T16:00:00Z", groups: [], movers: [] },
  "/copilot/desk/feed": { as_of: "2026-11-13T16:00:00Z", now: epoch("2026-11-13T16:00:00Z"), day: "2026-11-13", total: 0, sources: {}, unavailable: [], items: [] },
  "/copilot/investigations": { investigations: [] },
  "/copilot/tickets": { plans: [] },
  "/copilot/unusual": { state: "ok", rows: [] },
  "/copilot/scanner": { state: "off", rows: [] },
  "/copilot/exposure": { line: null },
};

type Seen = { at: number; path: string };

async function open(page: Page, seen: Seen[]) {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.clock.install({ time: NOW });
  const record = async (route: Route) => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace(/^\/api\/backend/, "");
    seen.push({ at: await page.evaluate(() => Date.now()).catch(() => 0), path });
    return path;
  };
  // Anything not named below: a plain refusal, read through like any other.
  await page.route("**/api/backend/**", async route => { await record(route); return route.fulfill({ status: 404, json: { detail: "Not in this test." } }); });
  await page.route("**/copilot/status", route => route.fulfill({ json: ON }));
  for (const [path, body] of Object.entries(READS)) {
    await page.route(url => url.pathname.endsWith(path), async route => { await record(route); return route.fulfill({ json: body }); });
  }
  await page.route("**/copilot/desk/*/chart*", async route => { await record(route); return route.fulfill({ status: 503, json: { detail: "No chart in this test." } }); });
  await page.route("**/copilot/desk/minute?*", async route => {
    await record(route);
    const reads = new URL(route.request().url()).searchParams.getAll("read").map(target => {
      const body = READS[target.split("?")[0]];
      return body ? { status: 200, body } : { status: 404, body: { detail: "Not in this test." } };
    });
    return route.fulfill({ json: { reads } });
  });
  await page.route("**/copilot/desk/ticks?*", async route => {
    await record(route);
    const at = Math.floor(await page.evaluate(() => Date.now() / 1000));
    return route.fulfill({ json: { state: "ok", as_of: "", poll_seconds: 5, closes_at: epoch("2026-11-13T21:00:00Z"), rows: {
      [CALL]: { last: 1.0, change_pct: null, prev_close: null, at }, ORCL: { last: 247, change_pct: -1.0, prev_close: 249.5, at },
      NVDA: { last: 101, change_pct: 1.25, prev_close: 99.5, at }, MU: { last: 120, change_pct: 0.1, prev_close: 119.9, at } } } });
  });
  await page.goto("/copilot-lab");
  await expect(page.getByTestId("desk-book")).toBeVisible();
}

const count = (seen: Seen[], from: number) => {
  const by: Record<string, number> = {};
  for (const s of seen) if (s.at >= from) by[s.path] = (by[s.path] ?? 0) + 1;
  return by;
};
const total = (by: Record<string, number>) => Object.values(by).reduce((a, b) => a + b, 0);

test("an idle desk in the session asks about 20 times a minute: live prices, and the minute's reads as one request", async ({ page }) => {
  const seen: Seen[] = [];
  await open(page, seen);
  await page.clock.runFor(30_000); // the cold load is not the idle rate
  const from = await page.evaluate(() => Date.now());
  await page.clock.runFor(3 * 60_000);
  const by = count(seen, from);
  const perMinute = total(by) / 3;
  expect(perMinute, JSON.stringify(by)).toBeLessThanOrEqual(20);
  expect(by["/copilot/desk/ticks"] ?? 0).toBeLessThanOrEqual(3 * 12); // every 5 s, one read for every piece
  expect(by["/copilot/desk/minute"] ?? 0).toBeLessThanOrEqual(3); // once a minute, for every minute read together
  expect(by["/copilot/desk/minute"] ?? 0).toBeGreaterThanOrEqual(2);
  for (const path of Object.keys(READS)) expect(by[path] ?? 0, path).toBe(0); // none of them on its own clock
  for (const [path, n] of Object.entries(by)) {
    if (path !== "/copilot/desk/ticks" && path !== "/charts/settings") expect(n, path).toBeLessThanOrEqual(3); // nothing else faster than a minute
  }
});

test("a hidden desk asks nothing; showing it again catches up in one request", async ({ page }) => {
  const seen: Seen[] = [];
  await open(page, seen);
  await page.clock.runFor(30_000);
  await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "hidden" });
    Object.defineProperty(document, "hidden", { configurable: true, get: () => true });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  const hidden = await page.evaluate(() => Date.now());
  await page.clock.runFor(3 * 60_000);
  expect(count(seen, hidden)).toEqual({});
  const back = await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "visible" });
    Object.defineProperty(document, "hidden", { configurable: true, get: () => false });
    document.dispatchEvent(new Event("visibilitychange"));
    return Date.now();
  });
  await page.clock.runFor(2_000);
  await expect.poll(() => count(seen, back)["/copilot/desk/minute"] ?? 0).toBe(1);
  const by = count(seen, back);
  for (const path of Object.keys(READS)) expect(by[path] ?? 0, path).toBe(0);
  // The book still reads the stubbed position after the catch-up (each read got its own answer back).
  await expect(page.getByTestId("desk-book").getByTestId("book-pnl")).toHaveText("−$120−55%");
});
