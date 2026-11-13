import { expect, test, type Page, type Request } from "@playwright/test";

// The desk's walls (docs/copilot-lab.md § Walls): the Charts strike ladder's put wall, call wall, gamma flip, max pain and
// expected move as an off-by-default study on the desk chart (hover says what each is, the level menu snaps to one), and
// as one line plus strike marks on the Chain tab; one read a minute shared by both; stale draws nothing and greys the
// line. Every lab route is stubbed in the browser with invented numbers: no provider is read and nothing reaches the
// e2e backend's alerts.
const ON = {
  enabled: true, backend: "fake", evidence: "fixture", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
const now = Math.floor(Date.now() / 1000);
const NEAREST = "2026-11-12";
const ASSUMPTION = "Dealer side assumed: dealers long calls and short puts. Open interest does not say who holds a contract, so the walls are positioning, the flip and the gamma a model.";

/** 60 candles of the asked timeframe around 94 (93.4 to 95.4), no plan, no marks. */
function chartRead(timeframe = "2m") {
  const step = timeframe === "15m" ? 900 : 120, last = now - (now % step);
  const bars = Array.from({ length: 60 }, (_, i) => {
    const open = 94.3 + Math.sin(i / 5);
    return { time: last - (59 - i) * step, open, high: open + 0.1, low: open - 0.1, close: open + (i % 3 === 0 ? -0.05 : 0.05), volume: 1000, extended: false };
  });
  return {
    symbol: "NBIS", timeframe, step, as_of: now, live: false, state: "ok", reason: null, bars, studies: {}, reference: [],
    reading: { last: bars[59].close, at: bars[59].time + 60, daily: false, prev_close: 93.1, vwap: null, vwap_at: null, rvol: null },
    levels: [], alerts: [], marks: [], time_stop: null,
  };
}

/** The walls as ``GET /copilot/desk/walls`` answers: invented strikes inside the candles' range. */
function walls(state: "ready" | "stale" = "ready", expiration = NEAREST) {
  return {
    symbol: "NBIS", state, expiration, spot: 94.3, fetched_at: now - (state === "stale" ? 400 : 20), age_s: state === "stale" ? 400 : 20,
    levels: [
      { kind: "put_wall", name: "Put wall", price: 93.5, hint: "Put wall: the strike with the most put open interest in this expiry; often acts as a floor." },
      { kind: "call_wall", name: "Call wall", price: 95, hint: "Call wall: the strike with the most call open interest in this expiry; often acts as a ceiling." },
      { kind: "gamma_flip", name: "Gamma flip", price: 94, hint: "Gamma flip: where dealer gamma is modelled to change sign. A model estimate on an assumed dealer side." },
      { kind: "max_pain", name: "Max pain", price: 94.5, hint: "Max pain: the strike where this expiry's open contracts would pay their holders least." },
    ],
    expected_move: { move: 0.5, percent: 0.005, low: 93.8, high: 94.8, expiration, hint: "Expected move: what the at-the-money straddle prices for this expiry, either way." },
    flip_note: null, assumption: ASSUMPTION, message: state === "stale" ? "The option chain could not be read again just now." : null,
    simulated: false, refresh_seconds: 60,
  };
}

function chain(expiration = NEAREST) {
  const cell = (strike: number, side: "call" | "put") => ({
    symbol: `NBIS261112${side === "call" ? "C" : "P"}${String(strike * 1000).padStart(8, "0")}`, bid: 1, ask: 1.1, mark: 1.05, last: null,
    spread: 0.1, spread_pct: 9.5, wide: false, spread_note: null, volume: 100, open_interest: 900, delta: 0.5, iv: 60, quoted_at: now - 20,
    state: "ok", multiplier: 100, held: null, planned: false,
  });
  return {
    symbol: "NBIS", state: "ok", session: "open", poll_seconds: 15, simulated: false, root: "NBIS", centred_on: "price",
    expiries: [{ date: NEAREST, days: 0, kind: "0dte", held: false }, { date: "2026-11-20", days: 8, kind: "monthly", held: false }],
    expiration, spot: 94.3, spot_at: now - 5, spot_issue: null, atm_strike: 94.5, fetched_at: now - 3, age_s: 3, stale: false, message: null,
    rows: [93, 93.5, 94, 94.5, 95, 95.5].map(strike => ({ strike, atm: strike === 94.5, levels: [], call: cell(strike, "call"), put: cell(strike, "put") })),
    levels: [],
  };
}

async function desk(page: Page) {
  const reads: string[] = [];
  const posted: Request[] = [];
  const reply = { state: "ready" as "ready" | "stale" };
  await page.route("**/copilot/status", (route) => route.fulfill({ json: ON }));
  await page.route("**/copilot/investigations?*", (route) => route.fulfill({ json: { investigations: [] } }));
  await page.route("**/copilot/chat", (route) => route.abort());
  await page.route(/\/copilot\/desk\/symbol(:|%3A)NBIS\//, (route) => new URL(route.request().url()).pathname.endsWith("/chart")
    ? route.fulfill({ json: chartRead(new URL(route.request().url()).searchParams.get("timeframe") ?? "2m") })
    : route.fulfill({ json: { state: "ok", symbol: "NBIS", count: 0, unavailable: [], recent_days: 7, rows: [] } }));
  await page.route("**/copilot/desk/read", (route) => route.fulfill({ json: { state: "hidden" } }));
  await page.route(/\/copilot\/desk\/walls\?/, (route) => {
    const url = new URL(route.request().url());
    reads.push(url.search);
    const expiration = url.searchParams.get("expiration");
    // A later expiry answers stale: the Chain line greys and marks nothing.
    return route.fulfill({ json: expiration ? walls("stale", expiration) : walls(reply.state) });
  });
  await page.route(/\/copilot\/chain\?/, (route) => route.fulfill({ json: chain(new URL(route.request().url()).searchParams.get("expiration") ?? NEAREST) }));
  await page.route("**/copilot/tickets", (route) => route.fulfill({ json: { plans: [] } }));
  await page.route("**/copilot/unusual", (route) => route.fulfill({ json: { state: "ok", rows: [], tickers: [], unread: [], no_history: [], stale: [], held: [], message: null, simulated: false } }));
  await page.route("**/charts/alerts**", (route) => {
    if (route.request().method() === "POST") {
      posted.push(route.request());
      const body = route.request().postDataJSON();
      return route.fulfill({ json: { alerts: [{ id: "made-1", symbol: "NBIS", price: body.price, created_on: "2026-11-12", condition: "crosses", interval: null,
        session: "regular", direction: "up", source_kind: "level", source_id: "desk", label: body.label, plan_role: null, state: "active", armed_at: now, event: null }], phone: true } });
    }
    return route.fulfill({ json: { alerts: [], phone: true } });
  });
  await page.goto("/copilot-lab?symbol=NBIS");
  const pane = page.getByRole("region", { name: "Chart and feed" });
  await expect(pane.getByTestId("desk-chart-canvas")).toHaveAttribute("data-bars", "60");
  return { pane, reads, posted, reply };
}

/** Moves the pointer down the middle of the chart until the walls tooltip names ``name``; returns where. */
async function hoverTo(page: Page, pane: ReturnType<Page["getByRole"]>, name: string) {
  const box = (await pane.getByTestId("desk-chart-canvas").boundingBox())!;
  const tip = pane.getByTestId("desk-walls-tip");
  for (let y = box.y + 8; y < box.y + box.height * 0.85; y += 2) {
    await page.mouse.move(box.x + box.width * 0.5, y);
    if (await tip.count() && (await tip.textContent())?.startsWith(name)) return { x: box.x + box.width * 0.5, y };
  }
  throw new Error(`No ${name} line under the pointer`);
}

test("Walls is off until turned on, then draws the four lines with plain-words hovers and a level menu at the wall", async ({ page }) => {
  const { pane, reads, posted } = await desk(page);
  const canvas = pane.getByTestId("desk-chart-canvas");
  const toggle = pane.getByTestId("desk-study-walls");
  await expect(toggle).toHaveAttribute("aria-pressed", "false");
  await expect(canvas).toHaveAttribute("data-walls", "off");
  expect(reads).toEqual([]); // off: nothing read

  await toggle.click();
  await expect(canvas).toHaveAttribute("data-walls", "4");
  expect(reads).toEqual(["?symbol=NBIS"]);
  await expect(toggle).toHaveText(/^Walls \S+/); // the expiry it is for
  await expect(toggle).toHaveAttribute("title", /Dealer side assumed: long calls, short puts/);
  const marks = pane.getByTestId("desk-chart-marks");
  await expect(marks).toContainText("Call wall 95.00");
  await expect(marks).toContainText("Put wall 93.50");
  await expect(marks).toContainText("Expected move 93.80 to 94.80");
  await expect(marks).toContainText("Open interest does not say who holds a contract");
  await pane.screenshot({ path: test.info().outputPath("desk-walls-chart.png") });

  // Hovering the call wall says what it is, and that the dealer side is assumed.
  const at = await hoverTo(page, pane, "Call wall");
  const tip = pane.getByTestId("desk-walls-tip");
  await expect(tip).toContainText("the strike with the most call open interest");
  await expect(tip).toContainText("often acts as a ceiling");
  await expect(tip).toContainText("dealer side assumed (long calls, short puts), not known");
  await pane.screenshot({ path: test.info().outputPath("desk-walls-hover.png") });

  // A right-click there opens the level menu at the wall's own price; the alert is the wall's.
  await page.mouse.click(at.x, at.y, { button: "right" });
  const menu = pane.getByTestId("desk-level-menu");
  await expect(menu).toHaveAttribute("aria-label", "At 95.00");
  await expect(menu.getByTestId("desk-level-menu-wall")).toHaveText("NBIS Call wall ·");
  await expect(menu.getByRole("menuitem", { name: "Plan from here…" })).toBeVisible();
  await menu.getByRole("menuitem", { name: "Alert when price crosses here" }).click();
  await expect(pane.getByTestId("desk-chart-status")).toContainText("Alert set: NBIS");
  expect(posted.map((request) => request.postDataJSON())).toMatchObject([{ symbol: "NBIS", price: 95, label: "Call wall, from the desk", source_id: "desk" }]);

  // Remembered after a reload, and one choice for every timeframe.
  await page.reload();
  await expect(pane.getByTestId("desk-study-walls")).toHaveAttribute("aria-pressed", "true");
  await expect(canvas).toHaveAttribute("data-walls", "4");
  await pane.getByRole("group", { name: "Timeframe" }).getByRole("button", { name: "15m" }).click();
  await expect(canvas).toHaveAttribute("data-timeframe", "15m");
  await expect(pane.getByTestId("desk-study-walls")).toHaveAttribute("aria-pressed", "true");
  await expect(canvas).toHaveAttribute("data-walls", "4");
});

test("a stale read draws nothing on the chart", async ({ page }) => {
  await page.addInitScript(() => window.localStorage.setItem("desk.chart.studies.v1", JSON.stringify({ all: { walls: true } })));
  const { pane, reply } = await desk(page);
  reply.state = "stale";
  await page.reload();
  const canvas = pane.getByTestId("desk-chart-canvas");
  await expect(canvas).toHaveAttribute("data-walls", "stale");
  await expect(pane.getByTestId("desk-study-walls")).toHaveText("Walls stale");
  await expect(pane.getByTestId("desk-chart-marks")).not.toContainText("Call wall");
});

test("the Chain tab reads the walls in one line, marks the wall strikes, shares the chart's read and greys a stale one", async ({ page }) => {
  await page.addInitScript(() => window.localStorage.setItem("desk.chart.studies.v1", JSON.stringify({ all: { walls: true } })));
  const { pane, reads } = await desk(page);
  await expect(pane.getByTestId("desk-chart-canvas")).toHaveAttribute("data-walls", "4");
  await pane.getByRole("tab", { name: "Chain" }).click();
  const tab = pane.getByTestId("desk-chain");
  const line = tab.getByTestId("chain-walls");
  await expect(line).toHaveText("Walls 93.5 / 95 · flip 94 · max pain 94.5 · expected move ±0.50 · dealer side assumed");
  await expect(line).toHaveAttribute("data-state", "ready");
  await expect(line).toHaveAttribute("title", ASSUMPTION);
  await expect(tab.locator("tr[data-strike='95']").getByTestId("chain-wall")).toHaveText("call wall");
  await expect(tab.locator("tr[data-strike='93.5']").getByTestId("chain-wall")).toHaveText("put wall");
  await expect(tab.locator("tr[data-strike='94.5']").getByTestId("chain-wall")).toHaveText("max pain");
  await expect(tab.getByTestId("chain-wall")).toHaveCount(3); // the flip is a price, not a strike: in the line only
  expect(reads).toEqual(["?symbol=NBIS"]); // the chart's read served the Chain tab too
  await pane.screenshot({ path: test.info().outputPath("desk-walls-chain.png") });

  // Another expiry reads its own walls; a stale one is grey with its time and why, and marks nothing.
  await tab.getByRole("radiogroup", { name: "Expiry" }).getByRole("radio").nth(1).click();
  await expect(line).toHaveAttribute("data-state", "stale");
  await expect(line).toContainText(/^Walls 93\.5 \/ 95 · .* · as of \d{1,2}:\d{2} [AP]M ET, not current: The option chain could not be read again just now\.$/);
  await expect(tab.getByTestId("chain-wall")).toHaveCount(0);
  expect(reads).toEqual(["?symbol=NBIS", "?symbol=NBIS&expiration=2026-11-20"]);
});
