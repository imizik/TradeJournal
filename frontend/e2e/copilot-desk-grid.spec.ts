import { expect, test, type Page } from "@playwright/test";
import { fakeChartSettings } from "./fixtures/chartSettings";

// The centre's Grid (docs/copilot-lab.md § The desk): 4, 6 or 9 small live charts filled with the followed held names,
// then the Watching list; a hidden ticker never in a slot; pins kept per device; one batched bars read for every tile;
// a click opens the name on the full Chart tab in place; two columns on a phone with no sideways scroll.
// Every lab route is stubbed in the browser (the e2e backend runs with the lab off); nothing reaches Robinhood or a model.
const ON = {
  enabled: true, backend: "fake", evidence: "live", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
// Friday November 13, 2026, 11:00 in New York: in the session.
const NOW = new Date("2026-11-13T16:00:00Z");
const epoch = (iso: string) => Date.parse(iso) / 1000;
const OPEN = epoch("2026-11-13T14:30:00Z");
const ids = ["11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222", "33333333-3333-4333-8333-333333333333"];
const position = (symbol: string, id: string, hidden = false) => ({
  key: `trade:${id}`, group: "watch", symbol, title: `${symbol} 11/20/26 50C`, instrument: "11/20/26 50C", trade_id: id,
  value: { text: "−$120.00", tone: "loss" }, status: { text: "No plan yet", tone: "muted" }, path: `/trades/${id}`, hidden,
  meter: null, investigation_id: null, radar_event_id: null, changed_at: null,
  book: { usd: -120, pct: -12, expiry: "2026-11-20", days_held: 1, track: null, state: "no_plan", planned: false, stop_pct: null },
});
// ORCL and MU are held and followed; IREN is held and set to Not following.
const THREADS = {
  as_of: "2026-11-13T16:00:00Z", quotes_at: null, quote_issue: null, day: { phase: "regular", need_you: 0, streak: null },
  sections: { positions: "ok" }, plans: [], robinhood: { state: "off" },
  threads: [position("ORCL", ids[0]), position("MU", ids[1]), position("IREN", ids[2], true)],
};
const SESSION = {
  as_of: "2026-11-13T16:00:00Z", now: epoch("2026-11-13T16:00:00Z"), day: "2026-11-13", phase: "regular",
  open: OPEN, close: epoch("2026-11-13T21:00:00Z"), events: [], time_stops: [], pings: null, prep: null,
  indices: [{ symbol: "SPY", last: 580.1, change_pct: 0.42 }], quote_issue: null, realized_today: 0, sections: {},
};
const WATCHING = ["NVDA", "RKLB", "AMD", "PLTR", "HOOD", "TSLA", "MSFT", "META", "SMCI"];
const BASE: Record<string, number> = { ORCL: 250, MU: 210, NVDA: 190, RKLB: 60, AMD: 240, PLTR: 180, HOOD: 140, TSLA: 430, MSFT: 510, META: 600, SMCI: 40 };

function bars(symbol: string, step: number) {
  const base = BASE[symbol] ?? 50;
  const prior = Array.from({ length: 30 * 60 / step }, (_, i) => {
    const close = base * 0.99 + i * 0.01;
    return { time: OPEN - 86400 + 390 * 60 - 1800 + i * step, open: close, high: close + 0.05, low: close - 0.05, close, volume: 100, extended: false, vwap: null, prior: true };
  });
  const today = Array.from({ length: 90 * 60 / step }, (_, i) => {
    const close = base + Math.sin(i / 7) * base * 0.004 + i * base * 0.0001;
    return { time: OPEN + i * step, open: close - 0.05, high: close + 0.1, low: close - 0.1, close, volume: 100, extended: false, vwap: base, prior: false };
  });
  return [...prior, ...today];
}

type Seen = { grid: URL[]; charts: string[] };

async function open(page: Page, { width = 1440, height = 900, pins }: { width?: number; height?: number; pins?: (string | null)[] } = {}) {
  const seen: Seen = { grid: [], charts: [] };
  await page.setViewportSize({ width, height });
  await page.clock.install({ time: NOW });
  if (pins) await page.addInitScript(saved => window.localStorage.setItem("desk.grid.v1", saved), JSON.stringify({ size: 6, timeframe: "5m", pins }));
  await page.route("**/copilot/status", route => route.fulfill({ json: ON }));
  await page.route("**/copilot/desk/threads", route => route.fulfill({ json: THREADS }));
  await page.route("**/copilot/desk/session", route => route.fulfill({ json: SESSION }));
  await page.route("**/copilot/desk/pings*", route => route.fulfill({ json: { day: "2026-11-13", since: "2026-11-12", alerts: { state: "ok", rows: [] }, radar: { state: "off", reason: null, rows: [] } } }));
  await page.route("**/copilot/desk/feed", route => route.fulfill({ json: { as_of: "2026-11-13T16:00:00Z", now: epoch("2026-11-13T16:00:00Z"), day: "2026-11-13", total: 0, sources: {}, unavailable: [], items: [] } }));
  await page.route("**/copilot/desk/sparks?*", route => route.fulfill({ json: { as_of: "2026-11-13T16:00:00Z", spy_change_pct: 0.4, rows: {
    ORCL: { points: [250, 248, 246], change_pct: -1.2 }, NVDA: { points: [189, 190], change_pct: 0.8, last: 190.12 } } } }));
  await page.route("**/copilot/desk/ticks?*", route => route.fulfill({ json: { state: "ok", as_of: "2026-11-13T16:00:00Z", poll_seconds: 5,
    rows: { NVDA: { last: 191.5, change_pct: 1.21, prev_close: 189.21, at: epoch("2026-11-13T16:00:00Z") } } } }));
  await page.route("**/copilot/desk/events?*", route => route.fulfill({ json: { state: "ok", today: "2026-11-13", loading: false,
    rows: { NVDA: { symbol: "NVDA", date: "2026-11-18", status: "confirmed", trading_days: 3, label: "ER Wed", tone: "grey", through: [] } } } }));
  await page.route("**/copilot/desk/watching", route => route.fulfill({ json: {
    state: "ok", symbols: [...WATCHING, "IREN"], count: 10, max: 30, imported_at: null, robinhood: "off", levels: {}, setups: {} } }));
  await page.route("**/copilot/desk/grid?*", route => {
    const url = new URL(route.request().url());
    seen.grid.push(url);
    const step = url.searchParams.get("timeframe") === "5m" ? 300 : 60;
    // GONE is set to Not following on the server only (no row here): the read leaves it out.
    const names = (url.searchParams.get("symbols") ?? "").split(",").filter(s => s && s !== "GONE");
    return route.fulfill({ json: { state: "ok", as_of: epoch("2026-11-13T16:00:00Z"), day: "2026-11-13", timeframe: url.searchParams.get("timeframe"), step, live: true,
      rows: Object.fromEntries(names.map(s => [s, { state: "ok", bars: bars(s, step), last: BASE[s] ?? 50, change_pct: null, source: "alpaca",
        read_at: epoch("2026-11-13T16:00:00Z") - (s === "AMD" ? 600 : 0), stale: s === "AMD",
        levels: s === "MU" ? [{ price: 211, role: "entry", label: null }, { price: 207, role: "invalidation", label: null }] : [] }])) } });
  });
  await page.route("**/copilot/investigations?*", route => route.fulfill({ json: { investigations: [] } }));
  await page.route("**/copilot/desk/*/{picture,chart}*", route => {
    seen.charts.push(decodeURIComponent(new URL(route.request().url()).pathname.split("/").slice(-2)[0]));
    return route.fulfill({ status: 503, json: { detail: "No chart in this test." } });
  });
  await page.goto("/copilot-lab");
  await expect(page.getByTestId("desk-book")).toBeVisible();
  await page.getByRole("tablist", { name: "Centre" }).getByRole("tab", { name: "Grid" }).click();
  await expect(page.getByTestId("desk-grid")).toBeVisible();
  return seen;
}

const tiles = (page: Page) => page.getByTestId("grid-tile");

test("his Charts levels and drawings show thin on their tiles, read from the shared chart settings and never saved", async ({ page, context }) => {
  const store = await fakeChartSettings(context, { revision: 3, data: {
    levels: { MU: [{ id: "mu-level", price: 210.5, label: "Breakout" }], NVDA: [{ id: "nv-hidden", price: 190, label: "Old", hidden: true }] },
    drawings: { MU: [{ id: "mu-trend", kind: "trend", points: [{ time: OPEN + 600, price: 209 }, { time: OPEN + 3000, price: 211 }], color: "#67d5eb", width: 3, drawn_on: "2026-11-13" },
      { id: "mu-note", kind: "note", points: [{ time: OPEN + 600, price: 210 }], color: "#e2e8f0", width: 1, drawn_on: "2026-11-13", text: "Watch" }] },
  } });
  await open(page);
  const tile = (symbol: string) => tiles(page).filter({ has: page.getByRole("button", { name: `Open ${symbol} on the chart` }) }).getByTestId("grid-chart");
  await expect(tile("MU")).toHaveAttribute("data-drawings", "2"); // the level and the trend line; a note is left off a tile
  await expect(tile("NVDA")).toHaveAttribute("data-drawings", "0"); // a hidden level stays hidden, as in Charts
  await expect(tile("ORCL")).toHaveAttribute("data-drawings", "0");
  await tiles(page).nth(1).screenshot({ path: test.info().outputPath("grid-tile-drawings.png") });
  expect(store.saves).toEqual([]);
});
const names = (page: Page) => tiles(page).evaluateAll(nodes => nodes.map(n => n.getAttribute("data-symbol")));

test("slots: held first, then Watching in order; a hidden ticker never; one batched read for every tile", async ({ page }) => {
  const seen = await open(page);
  await expect(tiles(page)).toHaveCount(6);
  await expect.poll(() => names(page)).toEqual(["ORCL", "MU", "NVDA", "RKLB", "AMD", "PLTR"]);
  await expect(page.getByTestId("grid-chart")).toHaveCount(6);
  expect(seen.grid).toHaveLength(1); // one read for all six tiles, not one each
  expect(seen.grid[0].searchParams.get("symbols")).toBe("ORCL,MU,NVDA,RKLB,AMD,PLTR");
  expect(seen.grid[0].searchParams.get("timeframe")).toBe("5m");
  // NVDA's tile: the ticker's live price and change, and its earnings tag.
  const nvda = tiles(page).filter({ has: page.getByRole("button", { name: "Open NVDA on the chart" }) });
  await expect(nvda.getByTestId("grid-last")).toHaveText("191.50");
  await expect(nvda.getByTestId("grid-change")).toHaveText("+1.21%");
  await expect(nvda.getByTestId("earnings-tag")).toHaveText("ER Wed");
  // AMD's re-read failed on the server: its bars show greyed with their time, never as now.
  await expect(tiles(page).nth(4).getByTestId("grid-stale")).toHaveText("bars 10:50 AM");
  await expect(nvda.getByTestId("grid-stale")).toHaveCount(0);

  await page.getByRole("group", { name: "Charts in the grid" }).getByRole("button", { name: "9" }).click();
  await expect.poll(() => names(page)).toEqual(["ORCL", "MU", "NVDA", "RKLB", "AMD", "PLTR", "HOOD", "TSLA", "MSFT"]);
  expect(seen.grid.at(-1)!.searchParams.get("symbols")!.split(",")).not.toContain("IREN");
  await page.getByRole("group", { name: "Charts in the grid" }).getByRole("button", { name: "4" }).click();
  await expect.poll(() => names(page)).toEqual(["ORCL", "MU", "NVDA", "RKLB"]);
  await page.getByRole("group", { name: "Candles" }).getByRole("button", { name: "1m" }).click();
  await expect.poll(() => seen.grid.at(-1)!.searchParams.get("timeframe")).toBe("1m");
  // Kept on this device: a reload comes back to four 1m charts on the Grid.
  await page.reload();
  await expect(page.getByTestId("desk-grid")).toHaveAttribute("data-size", "4");
  await expect(page.getByTestId("desk-grid")).toHaveAttribute("data-timeframe", "1m");
});

test("pins: a pinned name keeps its slot, the rest fill around it, and a hidden pin never shows", async ({ page }) => {
  // IREN pinned to slot 1 (not followed: skipped), TSLA pinned to slot 3.
  await open(page, { pins: [null, "IREN", null, "TSLA", "GONE", null, null, null, null] });
  await expect.poll(() => names(page)).toEqual(["ORCL", "MU", "NVDA", "TSLA", "RKLB", "AMD"]);
  await expect(tiles(page).nth(3)).toHaveAttribute("data-pinned", "true");
  // Put SMCI in the first slot by hand, then unpin TSLA: the slots fill themselves again.
  await tiles(page).nth(0).getByRole("button", { name: "Put another ticker in ORCL's slot" }).click();
  await page.getByRole("textbox", { name: "Ticker for slot 1" }).fill("smci");
  await page.getByRole("button", { name: "Pin here" }).click();
  await expect.poll(() => names(page)).toEqual(["SMCI", "ORCL", "MU", "TSLA", "NVDA", "RKLB"]);
  await tiles(page).nth(3).getByRole("button", { name: "Unpin TSLA from this slot" }).click();
  await expect.poll(() => names(page)).toEqual(["SMCI", "ORCL", "MU", "NVDA", "RKLB", "AMD"]);
  // Pinning a name where it already sits keeps it there.
  await tiles(page).nth(4).getByRole("button", { name: "Pin RKLB to this slot" }).click();
  await expect(tiles(page).nth(4)).toHaveAttribute("data-pinned", "true");
  const saved = await page.evaluate(() => JSON.parse(window.localStorage.getItem("desk.grid.v1") ?? "{}").pins);
  expect(saved.slice(0, 5)).toEqual(["SMCI", "IREN", null, null, "RKLB"]);
});

test("a tile's click opens the name on the full Chart tab in place, the copilot following", async ({ page }) => {
  const seen = await open(page);
  await expect(page.getByTestId("grid-chart")).toHaveCount(6);
  await page.evaluate(() => { (window as unknown as { kept: string }).kept = "still here"; });
  await page.getByRole("button", { name: "Open RKLB on the chart" }).click();
  await expect(page.getByRole("tablist", { name: "Centre" }).getByRole("tab", { name: "Chart" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByTestId("desk-chart")).toContainText("RKLB");
  await expect.poll(() => seen.charts).toContain("symbol:RKLB");
  await expect(page).toHaveURL(/\/copilot-lab\?symbol=RKLB$/);
  await expect(page.getByRole("region", { name: "Conversation" }).getByTestId("desk-breadcrumb")).toContainText("RKLB");
  expect(await page.evaluate(() => (window as unknown as { kept?: string }).kept)).toBe("still here"); // no reload
  // A held name opens as its book row does: the row is marked.
  await page.getByRole("tablist", { name: "Centre" }).getByRole("tab", { name: "Grid" }).click();
  await page.getByRole("button", { name: "Open MU on the chart" }).click();
  await expect(page.getByTestId("desk-chart")).toContainText("MU");
});

test("on a phone the grid is two columns of tiles with no sideways scroll", async ({ page }) => {
  await open(page, { width: 393, height: 852 });
  await page.getByRole("group", { name: "Charts in the grid" }).getByRole("button", { name: "9" }).click();
  await expect(tiles(page)).toHaveCount(9);
  const lefts = await tiles(page).evaluateAll(nodes => [...new Set(nodes.map(n => Math.round(n.getBoundingClientRect().left)))]);
  expect(lefts).toHaveLength(2);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
});
