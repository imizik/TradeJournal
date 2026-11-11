import { expect, test, type Page } from "@playwright/test";

// The day report's "How the pings did" (docs/copilot-lab.md#the-desk), the book's lower block after the close: one collapsed line saying what followed the phone pings since
// the previous trading session, each alert and alerted Radar hit underneath on tap. Nothing to answer; it replaced the
// Rate yesterday card. Every route is stubbed in the browser; no model runs.
const ON = {
  enabled: true, backend: "fake", evidence: "live", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
const DAY = "2026-10-23"; // a Friday
const now = Math.floor(Date.parse("2026-10-23T21:30:00Z") / 1000); // 17:30 New York: the day report shows
const SINCE = new Date(Date.parse(`${DAY}T12:00:00Z`) - 86_400_000).toISOString().slice(0, 10); // the previous day reads "yesterday"
const MAIN = "66666666-6666-4666-8666-666666666666";
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

async function now_(page: Page, pings: unknown = PINGS) {
  const writes: string[] = [];
  await page.route("**/copilot/status", (route) => route.fulfill({ json: ON }));
  await page.route("**/copilot/investigations?*", (route) => route.fulfill({ json: { investigations: [] } }));
  await page.route("**/copilot/chat", (route) => route.abort());
  await page.route("**/copilot/main-chat", (route) => route.fulfill({ json: conversation }));
  await page.route("**/copilot/main-chat/history", (route) => route.fulfill({ json: { chats: [conversation] } }));
  await page.route(`**/copilot/investigations/${MAIN}`, (route) => route.fulfill({ json: conversation }));
  await page.route("**/copilot/desk/threads", (route) => route.fulfill({ json: { as_of: new Date().toISOString(), quotes_at: null, quote_issue: null,
    sections: {}, day: { phase: "regular", need_you: 0, streak: null }, threads: [] } }));
  await page.route("**/copilot/desk/session", (route) => route.fulfill({ json: {
    as_of: new Date(now * 1000).toISOString(), now, day: DAY, phase: "regular", open: now - 3600, close: now + 7200,
    events: [], time_stops: [], pings: { sent: 6, held: 0, cap: 12 }, indices: [], quote_issue: null, prep: null,
    to_answer: { alerts: { count: 4, rows: [] }, radar: null }, sections: {},
  } }));
  await page.route("**/copilot/desk/pings", (route) => route.fulfill({ json: pings }));
  await page.route("**/copilot/desk/to-rate", (route) => { writes.push("to-rate read"); return route.abort(); });
  await page.route("**/trades/*/phone-alerts/*/feedback", (route) => { writes.push("alert"); return route.abort(); });
  await page.route("**/radar/events/*/feedback", (route) => { writes.push("radar"); return route.abort(); });
  await page.route(`**/day-journal/${DAY}`, (route) => route.fulfill({ json: { day: DAY, entries: [], trade_plans: {} } }));
  await page.clock.install({ time: new Date(now * 1000) });
  await page.goto("/copilot-lab");
  return writes;
}

for (const width of [1440, 375]) {
  test(`How the pings did says what followed in one line and lists each ping on tap, asking nothing (${width} px)`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 375 ? 812 : 900 });
    const writes = await now_(page);
    const card = page.getByRole("region", { name: "How the pings did" });
    await expect(card.getByTestId("pings-verdict")).toHaveText(
      "Since yesterday: 4 alerts · selling at the alert would have been better on 2, worse on 1 · 1 not measured · "
      + "2 Radar hits · 1 kept going · 1 not measured · paper: 0 of 1 setup green");
    await expect(card.getByTestId("pings-alert")).toHaveCount(4);
    await expect(card.getByTestId("pings-alert").first()).toBeHidden(); // collapsed by default
    await expect(page.getByText("Rate yesterday")).toHaveCount(0);
    await page.getByTestId("day-report").screenshot({ path: test.info().outputPath(`pings-recap-collapsed-${width}.png`) });

    await card.locator("summary").click();
    await expect(card.getByTestId("pings-alert").first()).toContainText("Sold for $420 vs $600 at the alert's bid: −$180");
    await expect(card.getByTestId("pings-alert").filter({ hasText: "MU" })).toContainText("Not measured: no price at the alert");
    const hits = card.getByTestId("pings-hit");
    await expect(hits.filter({ hasText: "MU up" })).toContainText("1h +0.8% · close +1.6%");
    await expect(hits.filter({ hasText: "NBIS up" })).toContainText("Setup · Dip turning up");
    await expect(hits.filter({ hasText: "NBIS up" })).toContainText("Paper −$42 a contract (invalidation)");
    await expect(card.getByRole("button", { name: /Useful|Prompted a review|Already/ })).toHaveCount(0); // nothing to answer
    await expect(card).not.toContainText(/\b(sell|hold) (it|now|this)\b/i); // counts, not advice
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    await card.screenshot({ path: test.info().outputPath(`pings-recap-open-${width}.png`) });
    expect(writes).toEqual([]);
  });
}

test("with no pings since the previous session the line says so", async ({ page }) => {
  await now_(page, { ...PINGS, alerts: { state: "ok", rows: [] }, radar: { state: "off", reason: "off", rows: [] } });
  await expect(page.getByRole("region", { name: "How the pings did" }).getByTestId("pings-verdict")).toHaveText("Since yesterday: no pings.");
});
