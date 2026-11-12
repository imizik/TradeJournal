import { expect, test, type Page } from "@playwright/test";

// The cockpit's after-close day report (docs/copilot-lab.md#the-desk): one card in the book's lower block with a line each
// for Today, How the pings did, Calls you checked and Open without a plan, each opening its rows on tap. The app scores
// everything itself; nothing to answer. Every route is stubbed in the browser; no model runs.
const ON = {
  enabled: true, backend: "fake", evidence: "live", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
const DAY = "2026-10-23"; // a Friday
const now = Math.floor(Date.parse("2026-10-23T21:30:00Z") / 1000); // 17:30 New York: the day report shows
const SINCE = new Date(Date.parse(`${DAY}T12:00:00Z`) - 86_400_000).toISOString().slice(0, 10); // the previous day reads "yesterday"
const MAIN = "66666666-6666-4666-8666-666666666666";
const checkRow = (fields: Record<string, unknown>) => ({
  id: String(fields.label), checked_at: "2026-10-23T14:05:00Z", day: DAY, symbol: String(fields.label).split(" ")[0], verdict: "Draft", side: "call",
  decision: "neither", state: "measured", why: null, way: "up", basis: "stock", contract: null, contract_note: "no contract identified", ...fields });
const REPORT = {
  day: DAY, as_of: new Date(now * 1000).toISOString(), sections: { entries: "ok", checks: "ok" },
  entries: { entries: 3, planned: 2, late: 0, pending: 0, rows: [
    { contract: "NBIS 100C", state: "planned", at: now - 20000 }, { contract: "MU 90P", state: "planned", at: now - 15000 },
    { contract: "APLD 30C", state: "unplanned", at: now - 9000 }] },
  checks: {
    today: { checked: 4, up: 1, down: 1, flat: 0, not_measured: 2 }, window: { days: 30, checked: 14, up: 5, down: 7, flat: 0, not_measured: 2 }, capped: false,
    rows: [
      checkRow({ label: "NVDA 10/30 105C", stock: { at_check: 100, close: 103, pct: 3 }, decision: "planned", contract: { at_check: 3, close: 4.5, pct: 50 }, contract_note: null, basis: "contract" }),
      checkRow({ label: "QQQ 10/23 660P", side: "put", verdict: "Pass", decision: "passed", stock: { at_check: 660, close: 665, pct: 0.76 }, way: "down" }),
      checkRow({ label: "AMD", state: "not_measured", why: "no closing price stored yet", way: null }),
      checkRow({ label: "TSLA", state: "not_measured", why: "no price was stored when you checked", way: null }),
    ] },
};
const POSITION = { key: "trade:t1", group: "watch", symbol: "AAPL", title: "AAPL 11/20/26 230C", instrument: "11/20/26 230C", value: { text: "+$120.00", tone: "gain" },
  status: { text: "No plan", tone: "attention" }, meter: null, investigation_id: null, trade_id: "t1", radar_event_id: null, path: null, changed_at: null,
  horizon: "swing", close: null, fillToLink: null, hidden: false,
  book: { usd: 120, pct: 20, expiry: "2026-11-20", days_held: 4, track: null, state: "no_plan", stop_pct: null } };
const alert = (contract: string, kind_label: string, outcome: Record<string, unknown>, ago: number) => ({
  at: now - ago, kind: "giveback", kind_label, contract, symbol: contract.split(" ")[0], pnl_pct_at_alert: 40, decision: null, decided_at: null, outcome });
const PINGS = {
  day: DAY, since: SINCE,
  alerts: { state: "ok", rows: [
    alert("NBIS 11/21/26 100C", "Give-back", { state: "closed", how: "sold", sell_at_alert_usd: 600, basis: "bid", actual_usd: 420, vs_alert_usd: -180, ended_at: now }, 600),
    alert("APLD 11/14/26 30C", "Held an hour", { state: "closed", how: "expired", sell_at_alert_usd: 105, basis: "bid", actual_usd: 0, vs_alert_usd: -105, ended_at: now }, 3600),
    alert("SLS 12/19/26 3C", "Expires next session", { state: "closed", how: "sold", sell_at_alert_usd: 200, basis: "mark", actual_usd: 340, vs_alert_usd: 140, ended_at: now }, 7200),
    alert("MU 11/21/26 110C", "Give-back", { state: "not_measured", why: "no price at the alert" }, 9000),
  ] },
  radar: { state: "ok", reason: null, rows: [
    { event_id: "rv1-mu", at: now - 5400, symbol: "MU", kind: "relative_to_sector", kind_label: "vs sector", direction: "up", summary: null,
      after: { hour_pct: 0.8, close_pct: 1.6, why: null }, setup: false, paper: null },
    { event_id: "rd-dip-nbis", at: now - 4000, symbol: "NBIS", kind: "dip_turn", kind_label: "Dip turning up", direction: "up", summary: null,
      after: { hour_pct: null, close_pct: null, why: "the session is still open" }, setup: true,
      paper: { state: "closed", pnl: -42, exit_reason: "invalidation", note: null } },
  ] },
};
const conversation = { id: MAIN, source: "copilot", title: `Main chat · ${DAY}`, symbol: null, status: "open", conclusion: null, main_day: DAY,
  revision: 1, message_count: 0, has_findings: false, created_at: `${DAY}T13:00:00Z`, updated_at: `${DAY}T13:00:00Z`, transcript: [], evidence: [], findings: null };

const pingUrls: string[] = [];

async function now_(page: Page, pings: unknown = PINGS, report: unknown = REPORT, threads: unknown[] = [POSITION], realized = 245) {
  const writes: string[] = [];
  pingUrls.length = 0;
  await page.route("**/copilot/status", (route) => route.fulfill({ json: ON }));
  await page.route("**/copilot/investigations?*", (route) => route.fulfill({ json: { investigations: [] } }));
  await page.route("**/copilot/chat", (route) => route.abort());
  await page.route("**/copilot/main-chat", (route) => route.fulfill({ json: conversation }));
  await page.route("**/copilot/main-chat/history", (route) => route.fulfill({ json: { chats: [conversation] } }));
  await page.route(`**/copilot/investigations/${MAIN}`, (route) => route.fulfill({ json: conversation }));
  await page.route("**/copilot/desk/threads", (route) => route.fulfill({ json: { as_of: new Date().toISOString(), quotes_at: null, quote_issue: null,
    sections: {}, day: { phase: "regular", need_you: 0, streak: null }, threads } }));
  await page.route("**/copilot/desk/session", (route) => route.fulfill({ json: {
    as_of: new Date(now * 1000).toISOString(), now, day: DAY, phase: "regular", open: now - 3600, close: now + 7200,
    events: [], time_stops: [], pings: { sent: 6, held: 0, cap: 12 }, indices: [], quote_issue: null, prep: null, realized_today: realized,
    to_answer: { alerts: { count: 4, rows: [] }, radar: null }, sections: {},
  } }));
  await page.route("**/copilot/desk/pings*", (route) => { pingUrls.push(route.request().url()); return route.fulfill({ json: pings }); });
  await page.route("**/copilot/desk/day-report", (route) => route.fulfill({ json: report }));
  await page.route("**/copilot/desk/to-rate", (route) => { writes.push("to-rate read"); return route.abort(); });
  await page.route("**/trades/*/phone-alerts/*/feedback", (route) => { writes.push("alert"); return route.abort(); });
  await page.route("**/radar/events/*/feedback", (route) => { writes.push("radar"); return route.abort(); });
  await page.route(`**/day-journal/${DAY}`, (route) => route.fulfill({ json: { day: DAY, entries: [], trade_plans: {} } }));
  await page.clock.install({ time: new Date(now * 1000) });
  await page.goto("/copilot-lab");
  return writes;
}

const PINGS_SUMMARY = "4 alerts · selling at the alert would have been better on 2, worse on 1 · 1 not measured · "
  + "2 Radar hits · 1 kept going · 1 not measured · paper: 0 of 1 setup green";

for (const width of [1440, 375]) {
  test(`the day report is one card of three lines that open their rows on tap, asking nothing (${width} px)`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 375 ? 812 : 900 });
    const writes = await now_(page);
    const card = page.getByTestId("day-report-card");
    await expect(page.getByTestId("day-report-card")).toHaveCount(1); // one card, not ten
    await expect(card.locator(":scope > details")).toHaveCount(3);
    // In this order, each a single line.
    await expect(card.locator(":scope > details > summary")).toHaveText([
      /^Today · 3 entries, 2 with a plan saved before the fill/,
      new RegExp(`^How the pings did · ${PINGS_SUMMARY.replace(/[$.]/g, "\\$&")}`),
      /^Calls checked, last 30 days, since you checked: 14 · 5 up, 7 down, 2 not measured · Today: 4 \(1 up, 1 down, 2 not measured\)/,
    ]);
    // Realized P&L is the top bar's and a position without a plan is the book's: neither is repeated in the card.
    await expect(page.getByTestId("desk-pnl")).toContainText("Realized today +$245");
    await expect(card).not.toContainText(/realized|\$245|Open without a plan/i);
    await expect(card.getByTestId("pings-alert").first()).toBeHidden(); // collapsed by default
    await expect(page.getByTestId("pings-recap")).toHaveCount(0); // the pings are folded in, never shown twice
    expect(pingUrls.every(url => url.includes("day_only=true"))).toBe(true); // today's pings only
    await card.screenshot({ path: test.info().outputPath(`day-report-collapsed-${width}.png`) });

    for (const line of await card.locator(":scope > details > summary").all()) await line.click();
    await expect(card.getByTestId("report-entry")).toHaveText([/NBIS 100C.*plan saved first/, /MU 90P.*plan saved first/, /APLD 30C.*no plan/]);
    await expect(card.getByTestId("pings-alert").first()).toContainText("Sold for $420 vs $600 at the alert's bid: −$180");
    await expect(card.getByTestId("pings-alert").filter({ hasText: "MU" })).toContainText("Not measured: no price at the alert");
    await expect(card.getByTestId("pings-hit").filter({ hasText: "NBIS up" })).toContainText("Paper −$42 a contract (invalidation)");
    const calls = card.getByTestId("checked-call");
    await expect(calls).toHaveCount(4);
    await expect(calls.filter({ hasText: "NVDA 10/30 105C" })).toContainText("planned it");
    await expect(calls.filter({ hasText: "NVDA 10/30 105C" })).toContainText(/NVDA 100\.00 → 103\.00\s*\+3\.0% at the close · contract 3\.00 → 4\.50\s*\+50%/);
    // A passed call is reported the same flat way: the price move, never money missed.
    await expect(calls.filter({ hasText: "QQQ" })).toContainText("you passed");
    await expect(calls.filter({ hasText: "QQQ" })).toContainText(/QQQ 660\.00 → 665\.00\s*\+0\.8% at the close/);
    await expect(calls.filter({ hasText: "AMD" })).toContainText("Not measured: no closing price stored yet");
    await expect(card.getByRole("button", { name: /Useful|Prompted a review|Already|Helped|Rate/ })).toHaveCount(0); // nothing to answer
    await expect(card).not.toContainText(/\b(buy|sell|hold|take) (it|now|this)\b|\bmissed\b|\bleft on the table\b|\bshould\b/i); // counts, not advice
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    await card.screenshot({ path: test.info().outputPath(`day-report-open-${width}.png`) });
    expect(writes).toEqual([]);
  });
}

test("a line with nothing in it is absent", async ({ page }) => {
  await now_(page, PINGS,
    { ...REPORT, entries: { entries: 0, planned: 0, late: 0, pending: 0, rows: [] }, checks: { ...REPORT.checks, window: { days: 30, checked: 0, up: 0, down: 0, flat: 0, not_measured: 0 }, today: { checked: 0, up: 0, down: 0, flat: 0, not_measured: 0 }, rows: [] } },
    []);
  // Only the pings remain of the three lines; no Close the day button of its own (it is in ⌘K, and in the strip when anything is left).
  await expect(page.getByTestId("day-report-card").locator(":scope > details > summary")).toHaveText([/^How the pings did/]);
  await expect(page.getByTestId("day-report")).not.toContainText("Close the day");
});

test("a day with nothing at all says so in one sentence", async ({ page }) => {
  await now_(page, { ...PINGS, alerts: { state: "ok", rows: [] }, radar: { state: "off", reason: "off", rows: [] } },
    { ...REPORT, entries: { entries: 0, planned: 0, late: 0, pending: 0, rows: [] }, checks: null }, [], 0);
  await expect(page.getByTestId("day-report-card")).toHaveText("Nothing to report today: no entries, pings or checked calls.");
});
