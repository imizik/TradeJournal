import { expect, test, type Page } from "@playwright/test";

// Open-trade phone alerts on the trade page. The seeded backend has them switched off; the
// switched-on case fakes the one read, since firing needs live option quotes (covered in pytest).
type SeedTrade = { id: string; ticker: string; status: string; instrument_type: string; expiration: string; strike: number };

async function openAapl(page: Page): Promise<SeedTrade> {
  const trades = await (await page.request.get("/api/backend/trades")).json() as SeedTrade[];
  return trades.find(t => t.ticker === "AAPL" && t.status === "open" && t.instrument_type === "option")!;
}

test.beforeEach(async ({ page }) => { await page.setViewportSize({ width: 390, height: 844 }); });

test("switched off with nothing sent: the trade page shows no phone alerts section", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  const trade = await openAapl(page);
  const read = page.waitForResponse(r => r.url().includes(`/trades/${trade.id}/phone-alerts`));
  await page.goto(`/trades/${trade.id}`);
  expect(await (await read).json()).toEqual({ enabled: false, giveback_dollar_floor_applies: true, alerts: [], watch: null });
  await expect(page.getByRole("heading", { name: "Trade Summary" })).toBeVisible();
  await expect(page.getByTestId("trade-phone-alerts")).toHaveCount(0);
  expect(errors).toEqual([]);
});

test("switched on: the watch state and each alert's delivery read plainly at phone width", async ({ page }) => {
  const trade = await openAapl(page);
  const at = Date.parse("2026-10-21T15:02:00Z") / 1000;
  await page.route(`**/trades/${trade.id}/phone-alerts`, route => route.fulfill({ json: {
    enabled: true,
    watch: { peak_gain: 1109, peak_gain_pct: 0.38, armed: true, peak_at: at - 1800 },
    alerts: [
      { kind: "giveback", detected_at: at, contracts: 6, mark: 412, bid: 410, gain: 40, gain_pct: 0.01, peak_gain: 1109,
        peak_gain_pct: 0.38, delivery: "sent", error: null, delivered_at: at + 2 },
      { kind: "hold_hour", detected_at: at + 1800, contracts: 6, mark: 380, bid: 378, gain: -120, gain_pct: -0.05, peak_gain: 1109,
        peak_gain_pct: 0.38, delivery: "sent", error: null, delivered_at: at + 1802 },
      { kind: "expiry_final", detected_at: at + 3600, contracts: 6, mark: null, bid: null, gain: null, gain_pct: null,
        peak_gain: null, peak_gain_pct: null, delivery: "unknown", error: "timed out", delivered_at: null },
    ],
  } }));
  await page.goto(`/trades/${trade.id}`);
  const section = page.getByTestId("trade-phone-alerts");
  await expect(section).toContainText("Watching for a give-back: best so far +$1,109 (+38%)");
  await expect(section).toContainText("Give-back triggered · Oct 21, 2026, 11:02 AM ET · accepted by ntfy; phone display unconfirmed");
  await expect(section).toContainText("Was up +$1,109 (+38%), at +$40 (+1%) with 6 open");
  await expect(section).toContainText("Open an hour: re-decide · Oct 21, 2026, 11:32 AM ET · accepted by ntfy; phone display unconfirmed");
  await expect(section).toContainText("at -$120 (-5%) with 6 open");
  await expect(section).toContainText("30 minutes to the close · Oct 21, 2026, 12:02 PM ET · may have reached your phone, so it was not resent");
  await expect(section).toContainText("no live quote, 6 open");
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
  await section.screenshot({ path: test.info().outputPath("trade-phone-alerts-phone.png") });
});

test("an unplanned-entry nudge reads as its own row with what followed, and a capped or held one says why it was not sent", async ({ page }) => {
  const trade = await openAapl(page);
  const at = Date.parse("2026-10-21T14:03:00Z") / 1000;
  const nudge = { kind: "plan_nudge", contract: "AAPL 10/23/26 230C", entry: "2 at $3.10", detected_at: at, contracts: 2, mark: null, bid: null,
    gain: null, gain_pct: null, peak_gain: null, peak_gain_pct: null, error: null };
  await page.route(`**/trades/${trade.id}/phone-alerts`, route => route.fulfill({ json: {
    enabled: false, watch: null,
    alerts: [{ ...nudge, id: "n1", delivery: "sent", delivered_at: at + 2, policy: "sent", then: "plan linked in 6 min" },
      { ...nudge, id: "n2", detected_at: at + 60, delivery: "skipped", delivered_at: null },
      { ...nudge, id: "n3", detected_at: at + 120, delivery: "held", delivered_at: null, policy: "over_cap",
        error: "Not sent: 12 pings already went out today (cap 12). The last 3 of 12 are kept for position and plan pings." }],
  } }));
  await page.goto(`/trades/${trade.id}`);
  const section = page.getByTestId("trade-phone-alerts");
  await expect(section).toContainText("No plan yet: plan nudge · Oct 21, 2026, 10:03 AM ET · accepted by ntfy; phone display unconfirmed · then: plan linked in 6 min");
  await expect(section).toContainText("Opened 2 at $3.10 with no plan linked or suggested");
  await expect(section).toContainText("not sent: today's nudge limit was reached");
  await expect(section).toContainText("10:05 AM ET · Not sent: 12 pings already went out today (cap 12). The last 3 of 12 are kept for position and plan pings.");
  await expect(section).not.toContainText("no live quote");
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
  await section.screenshot({ path: test.info().outputPath("trade-plan-nudge-phone.png") });
});

test("the configured account's SPY exception does not show the $50 arming floor", async ({ page }) => {
  const trade = await openAapl(page);
  const at = Date.parse("2026-10-21T15:02:00Z") / 1000;
  await page.route(`**/trades/${trade.id}/phone-alerts`, route => route.fulfill({ json: {
    enabled: true,
    giveback_dollar_floor_applies: false,
    watch: { peak_gain: 10, peak_gain_pct: 0.1, armed: false, fired: false, peak_at: at },
    alerts: [],
  } }));
  await page.goto(`/trades/${trade.id}`);
  const section = page.getByTestId("trade-phone-alerts");
  await expect(section).toContainText("Not armed yet: arms once it is up 10% (best so far +$10, +10%).");
  await expect(section).not.toContainText("$50");
});

test("older API responses keep the original $50 arming text", async ({ page }) => {
  const trade = await openAapl(page);
  const at = Date.parse("2026-10-21T15:02:00Z") / 1000;
  await page.route(`**/trades/${trade.id}/phone-alerts`, route => route.fulfill({ json: {
    enabled: true,
    watch: { peak_gain: 10, peak_gain_pct: 0.1, armed: false, fired: false, peak_at: at },
    alerts: [],
  } }));
  await page.goto(`/trades/${trade.id}`);
  await expect(page.getByTestId("trade-phone-alerts")).toContainText("Not armed yet: arms once it is up 10% and $50");
});

const alertAt = Date.parse("2026-10-21T15:02:00Z") / 1000;
const linkedAlert = { id: "10000000-0000-0000-0000-000000000001", contract: "AAPL 10/23/26 230C",
  kind: "giveback", detected_at: alertAt, quoted_at: alertAt - 5, contracts: 2, mark: 412, bid: 410,
  gain: 24, gain_pct: 0.03, peak_gain: 204, peak_gain_pct: 0.255, delivery: "sent", error: null, delivered_at: alertAt + 2 };

// The current quote and the linked plan are faked too: the seeded backend has neither a live quote nor a plan for AAPL.
const quotedAt = Math.floor(Date.now() / 1000) - 30;
const nowMark = { mark: 4.3, mark_per_contract: 430, basis: "mid", bid: 4.28, ask: 4.32, last: 4.3, provider: "tradier",
  quoted_at: quotedAt, open: 2, open_pnl: 60 };
const linkedPlan = (tradeId: string) => ({ id: "plan-1", client_id: "plan-1", received_at: alertAt - 7200, client_captured_at: null,
  account_id: "roth", account_label: "Roth", underlying: "AAPL", side: "buy_calls", instrument: "option", mode: "template",
  template_id: null, template_revision: null, setup_label: "Reclaim", wording: "Out on a 5m close back below 228.", note: "Trim half at +40%.",
  strike: 230, expiration: null, quantity: 2, context_state: "unavailable", context: { state: "unavailable", reason: "fixture" },
  image: { state: "unavailable", note: null, bytes: null }, audio: null, transcript: null, not_taken_at: null, notes: [],
  link: { id: "link-1", method: "suggested", linked_at: alertAt - 3600, unlinked_at: null, trade_id: tradeId, contract: "AAPL 230C",
    entry_time: alertAt - 3600, entry_time_reliable: true, status: "open", timing: "pre_entry" } });

for (const width of [390, 1440]) {
  test(`notification selects its exact historical event above the summary at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    const trade = await openAapl(page);
    const errors: string[] = [];
    page.on("pageerror", e => errors.push(e.message));
    await page.route(`**/trades/${trade.id}/phone-alerts`, route => route.fulfill({ json: {
      enabled: false, watch: null, alerts: [{ ...linkedAlert, contract: `${trade.ticker} ${trade.expiration} ${trade.strike}C` }, { ...linkedAlert, id: "later", gain: -50, detected_at: alertAt + 3600 }],
    } }));
    await page.route(`**/charts/journal/trades/${trade.id}/mark`, route => route.fulfill({ json: nowMark }));
    await page.route(`**/charts/captures/for-trade/${trade.id}`, route => route.fulfill({ json: { captures: [linkedPlan(trade.id)] } }));
    await page.goto(`/trades/${trade.id}?alert=${linkedAlert.id}`);
    const selected = page.getByTestId("selected-position-alert");
    await expect(selected.getByRole("heading", { name: "Give-back triggered" })).toBeInViewport();
    const plan = page.getByRole("region", { name: "Pre-trade plan" });
    await expect(plan).toContainText("Out on a 5m close back below 228.");
    if (width === 390) await page.screenshot({ path: test.info().outputPath("position-alert-page-phone.png"), fullPage: true });
    const now = selected.getByTestId("position-now");
    await expect(now).toContainText("Open P&L now +$60");
    await expect(now).toContainText("2 contracts open. Option midpoint $4.30 per share. Bid $4.28 per share.");
    await expect(now).toContainText("Quoted ");
    // The plan the alert asks you to review sits right under it, above the summary.
    const planBox = await plan.boundingBox();
    expect(planBox!.y).toBeGreaterThan((await selected.boundingBox())!.y);
    expect(planBox!.y + planBox!.height).toBeLessThan((await page.getByRole("heading", { name: "Trade Summary" }).boundingBox())!.y);
    await expect(selected).toContainText("Peak +$204 (+26%) → at trigger +$24 (+3%). Gain reached +3% or below after arming.");
    await expect(selected).toContainText("Triggered Oct 21, 2026, 11:02 AM ET");
    await expect(selected).toContainText("Saved snapshot, not a current quote.");
    await expect(selected).toContainText("Option midpoint $4.12 per share. Bid $4.10 per share.");
    await expect(selected).not.toContainText("-$50");
    const chart = selected.getByRole("link", { name: "View underlying chart at alert" });
    await expect(chart).toHaveAttribute("href", `/charts?symbol=AAPL&from=${alertAt}&to=${alertAt}&trade=${trade.id}`);
    const summary = await page.getByRole("heading", { name: "Trade Summary" }).boundingBox();
    const card = await selected.boundingBox();
    expect(card!.y + card!.height).toBeLessThan(summary!.y);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
    await page.screenshot({ path: test.info().outputPath(`position-alert-selected-${width === 390 ? "phone" : "desktop"}.png`) });
    await page.reload();
    await expect(selected).toContainText("at trigger +$24 (+3%)");
    await chart.click();
    await expect(page).toHaveURL(new RegExp(`/charts\\?symbol=AAPL&from=${alertAt}&to=${alertAt}&trade=${trade.id}`));
    await expect(page.getByLabel("Chart symbol", { exact: true })).toHaveAttribute("placeholder", "AAPL");
    await page.goBack();
    await expect(selected).toContainText("at trigger +$24 (+3%)");
    expect(errors).toEqual([]);
  });
}

test("a closed position keeps its old expired alert as historical context", async ({ page }) => {
  const trades = await (await page.request.get("/api/backend/trades")).json() as SeedTrade[];
  const trade = trades.find(t => t.status === "closed" && t.instrument_type === "option")!;
  await page.route(`**/trades/${trade.id}/phone-alerts`, route => route.fulfill({ json: {
    enabled: false, watch: null, alerts: [{ ...linkedAlert, delivery: "expired" }],
  } }));
  await page.goto(`/trades/${trade.id}?alert=${linkedAlert.id}`);
  const selected = page.getByTestId("selected-position-alert");
  await expect(selected).toContainText("This position is now closed.");
  await expect(selected).toContainText("not sent: too late to be useful");
  await expect(selected.getByTestId("position-now")).toHaveCount(0); // nothing open to price
});

test("a current price that cannot be read says so and can be retried", async ({ page }) => {
  const trade = await openAapl(page);
  await page.route(`**/trades/${trade.id}/phone-alerts`, route => route.fulfill({ json: { enabled: false, watch: null, alerts: [linkedAlert] } }));
  let reads = 0;
  await page.route(`**/charts/journal/trades/${trade.id}/mark`, route => ++reads === 1
    ? route.fulfill({ status: 503, json: { detail: "Quotes are unavailable right now." } })
    : route.fulfill({ json: { ...nowMark, quoted_at: quotedAt - 3600, open_pnl: -40 } }));
  await page.goto(`/trades/${trade.id}?alert=${linkedAlert.id}`);
  const now = page.getByTestId("position-now");
  await expect(now).toContainText("Current price unavailable. Quotes are unavailable right now.");
  await expect(page.getByTestId("selected-position-alert")).toContainText("at trigger +$24 (+3%)"); // the snapshot still reads
  await now.getByRole("button", { name: "Try again" }).click();
  await expect(now).toContainText("Open P&L now -$40");
  await expect(now).toContainText("Stale: quoted");
  await now.screenshot({ path: test.info().outputPath("position-now-stale-phone.png") });
});

for (const state of ["missing", "failed", "loading"]) {
  test(`linked alert ${state} is explicit and never substitutes another event`, async ({ page }) => {
    const trade = await openAapl(page);
    await page.route(`**/trades/${trade.id}/phone-alerts`, route => state === "loading" ? new Promise(() => {}) : route.fulfill(
      state === "failed" ? { status: 503, json: {} } : { json: { enabled: false, watch: null, alerts: [linkedAlert] } }));
    await page.goto(`/trades/${trade.id}?alert=wrong-event`);
    const section = page.getByTestId("trade-phone-alerts");
    await expect(section).toContainText(state === "failed" ? "This alert could not be loaded" : state === "loading" ? "Loading the selected alert" : "This alert is unavailable for this position");
    await expect(page.getByTestId("selected-position-alert")).toHaveCount(0);
  });
}

test("a removed position gives a recovery link instead of an endless spinner", async ({ page }) => {
  await page.goto(`/trades/00000000-0000-0000-0000-000000000000?alert=${linkedAlert.id}`);
  await expect(page.getByRole("alert").filter({ hasText: "This position could not be loaded" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Back to Trades" })).toHaveAttribute("href", "/trades");
});
