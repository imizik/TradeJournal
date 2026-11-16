import { expect, test, type Page } from "@playwright/test";

// The momentum paper book on the desk chart (lib/deskMomentumBand.ts): on QQQ's intraday candles, the book's noise band
// today as two thin stepping lines (the hours ahead faint) and its paper entries and exits as pale M marks, behind one
// remembered chip. Nothing on another symbol, when the book is off, on a failed read or with another day's records.
// Every lab route is stubbed in the browser with invented numbers: no provider is read.
const ON = {
  enabled: true, backend: "fake", evidence: "fixture", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
const now = Math.floor(Date.now() / 1000);
const STEP = 120;
const LAST = now - (now % STEP);
const BARS = Array.from({ length: 60 }, (_, i) => {
  const open = 94.3 + Math.sin(i / 5);
  return { time: LAST - (59 - i) * STEP, open, high: open + 0.1, low: open - 0.1, close: open + (i % 3 === 0 ? -0.05 : 0.05), volume: 1000, extended: false };
});
const nyDay = (seconds: number) => new Date(seconds * 1000).toLocaleDateString("en-CA", { timeZone: "America/New_York" });

function chartRead(symbol: string, timeframe = "2m") {
  return {
    symbol, timeframe, step: STEP, as_of: now, live: false, state: "ok", reason: null, bars: BARS, studies: {}, reference: [],
    reading: { last: BARS[59].close, at: BARS[59].time + 60, daily: false, prev_close: 93.1, vwap: null, vwap_at: null, rvol: null },
    levels: [], alerts: [], marks: [], time_stop: null,
  };
}

/** Two checks inside the candles, one hour ahead past them; a long entered at the first and stopped at the second. */
function today(day = nyDay(BARS[59].time)) {
  const first = BARS[10].time, second = BARS[40].time;
  return {
    day, until: LAST + 40 * STEP,
    checks: [
      { minute: 600, at: first, status: "done", price: 95.1, upper: 94.9, lower: 93.7, vwap: 94.4 },
      { minute: 660, at: second, status: "done", price: 94.2, upper: 95.05, lower: 93.55, vwap: 94.5 },
    ],
    ahead: [{ minute: 720, at: LAST + 20 * STEP, upper: 95.2, lower: 93.4 }],
    trades: [{ side: 1, entry_at: first + 5, entry: 95.12, exit_at: second + 5, exit: 94.19, how: "stop", bp: -97.6 }],
  };
}

function book(state: "on" | "off" | "other-day") {
  return {
    enabled: state !== "off", symbol: "QQQ", stake: 10000, now, backtest: { mean_bp: 4.4, years: "2022-2026" }, holding: null, days: [],
    totals: { days: 0, days_traded: 0, mean_bp: null, dollars: null, up: 0, missed_checks: 0 },
    today: state === "off" ? null : today(state === "other-day" ? "2020-01-02" : undefined),
  };
}

async function desk(page: Page, symbol = "QQQ") {
  const reply = { state: "on" as "on" | "off" | "other-day" | "fail" };
  await page.route("**/copilot/status", (route) => route.fulfill({ json: ON }));
  await page.route("**/copilot/investigations?*", (route) => route.fulfill({ json: { investigations: [] } }));
  await page.route("**/copilot/chat", (route) => route.abort());
  await page.route(/\/copilot\/desk\/symbol(:|%3A)[A-Z]+\//, (route) => {
    const url = new URL(route.request().url());
    const asked = decodeURIComponent(url.pathname).match(/symbol:([A-Z]+)\//)?.[1] ?? symbol;
    return url.pathname.endsWith("/chart") ? route.fulfill({ json: chartRead(asked, url.searchParams.get("timeframe") ?? "2m") })
      : route.fulfill({ json: { state: "ok", symbol: asked, count: 0, unavailable: [], recent_days: 7, rows: [] } });
  });
  await page.route("**/copilot/desk/read", (route) => route.fulfill({ json: { state: "hidden" } }));
  await page.route("**/copilot/desk/momentum", (route) => reply.state === "fail"
    ? route.fulfill({ status: 500, json: { detail: "no" } }) : route.fulfill({ json: book(reply.state) }));
  await page.route("**/copilot/tickets", (route) => route.fulfill({ json: { plans: [] } }));
  await page.route("**/copilot/unusual", (route) => route.fulfill({ json: { state: "ok", rows: [], tickers: [], unread: [], no_history: [], stale: [], held: [], message: null, simulated: false } }));
  await page.route("**/charts/alerts**", (route) => route.fulfill({ json: { alerts: [], phone: true } }));
  await page.goto(`/copilot-lab?symbol=${symbol}`);
  const pane = page.getByRole("region", { name: "Chart and tools" });
  await expect(pane.getByTestId("desk-chart-canvas")).toHaveAttribute("data-bars", "60");
  return { pane, reply };
}

test("on QQQ the band steps at each check with the hour ahead faint, the paper trades are M marks, and the chip is remembered", async ({ page }) => {
  const { pane } = await desk(page);
  const canvas = pane.getByTestId("desk-chart-canvas");
  const chip = pane.getByTestId("desk-study-momentum");
  await expect(chip).toHaveAttribute("aria-pressed", "true");
  await expect(chip).toHaveText("Momentum band · paper 93.55–95.05"); // the band in force now
  await expect(canvas).toHaveAttribute("data-momentum", "3");
  await expect(canvas).toHaveAttribute("data-marks", "2");
  const marks = pane.getByTestId("desk-chart-marks");
  await expect(marks).toContainText("93.70 to 94.90");
  await expect(marks).toContainText("Momentum band (ahead)");
  await expect(marks).toContainText("Momentum book · Long entry 95.12 (paper)");
  await expect(marks).toContainText("Momentum book · Long stopped 94.19 · −97.6 bp (paper)");
  await pane.screenshot({ path: test.info().outputPath("desk-momentum-band.png") });

  // Off: no band, no marks; remembered after a reload and on the other intraday timeframe.
  await chip.click();
  await expect(chip).toHaveAttribute("aria-pressed", "false");
  await expect(canvas).toHaveAttribute("data-momentum", "off");
  await expect(canvas).toHaveAttribute("data-marks", "0");
  await expect(marks).not.toContainText("Momentum");
  await page.reload();
  await expect(pane.getByTestId("desk-study-momentum")).toHaveAttribute("aria-pressed", "false");
  await pane.getByRole("group", { name: "Timeframe" }).getByRole("button", { name: "15m" }).click();
  await expect(canvas).toHaveAttribute("data-timeframe", "15m");
  await expect(pane.getByTestId("desk-study-momentum")).toHaveAttribute("aria-pressed", "false");
});

test("nothing on another symbol", async ({ page }) => {
  const { pane } = await desk(page, "NBIS");
  await expect(pane.getByTestId("desk-chart-canvas")).toHaveAttribute("data-momentum", "none");
  await expect(pane.getByTestId("desk-study-walls")).toBeVisible();
  await expect(pane.getByTestId("desk-study-momentum")).toHaveCount(0);
});

for (const state of ["off", "other-day", "fail"] as const) {
  test(`QQQ draws and says nothing when the book read is ${state}`, async ({ page }) => {
    const { pane, reply } = await desk(page);
    await expect(pane.getByTestId("desk-chart-canvas")).toHaveAttribute("data-momentum", "3");
    reply.state = state;
    const answered = page.waitForResponse((response) => response.url().endsWith("/copilot/desk/momentum"));
    await page.reload();
    await answered;
    const canvas = pane.getByTestId("desk-chart-canvas");
    await expect(canvas).toHaveAttribute("data-bars", "60");
    await expect(pane.getByTestId("desk-study-walls")).toBeVisible();
    await expect(canvas).toHaveAttribute("data-momentum", "none");
    await expect(pane.getByTestId("desk-study-momentum")).toHaveCount(0);
    await expect(canvas).toHaveAttribute("data-marks", "0");
  });
}
