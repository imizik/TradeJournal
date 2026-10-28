import { expect, test, type Page } from "@playwright/test";

// The Briefing's alert scorecard (docs/copilot-lab.md#the-desk): what was decided after each position alert and what
// its contracts then fetched against selling at the alert. Every lab route is stubbed; no model runs.
const ON = {
  enabled: true, backend: "fake", evidence: "live", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
const at = (day: number, h: number, m: number) => Date.UTC(2026, 9, day, h + 4, m) / 1000; // New York (EDT) to epoch seconds
const tally = (t: Partial<Record<string, number>>) => ({ alerts: 0, closed: 0, better: 0, worse: 0, even: 0, open: 0, not_measured: 0, vs_alert_usd: 0, ...t });
const CARD = {
  window_days: 30, alerts: 4, truncated: false,
  summary: { holding: tally({ alerts: 2, closed: 2, better: 1, worse: 1, vs_alert_usd: 335 }), exiting: tally({ alerts: 1, open: 1 }), none: tally({ alerts: 1, not_measured: 1 }) },
  rows: [
    { at: at(27, 10, 31), kind: "giveback", kind_label: "Give-back", contract: "NBIS 11/21/26 100C", symbol: "NBIS", pnl_pct_at_alert: -25.4,
      decision: "holding", decided_at: at(27, 10, 44),
      outcome: { state: "closed", how: "sold", sell_at_alert_usd: 600, basis: "bid", actual_usd: 1040, vs_alert_usd: 440, ended_at: at(28, 11, 5) } },
    { at: at(23, 14, 0), kind: "giveback", kind_label: "Give-back", contract: "APLD 10/24/26 30C", symbol: "APLD", pnl_pct_at_alert: 12.5,
      decision: "holding", decided_at: at(23, 14, 5),
      outcome: { state: "closed", how: "expired", sell_at_alert_usd: 105, basis: "bid", actual_usd: 0, vs_alert_usd: -105, ended_at: at(24, 16, 0) } },
    { at: at(22, 12, 0), kind: "expiry_first", kind_label: "Expires today", contract: "CRWV 10/22/26 135C", symbol: "CRWV", pnl_pct_at_alert: 4.0,
      decision: "exiting", decided_at: at(22, 12, 2), outcome: { state: "open", sell_at_alert_usd: 620, basis: "bid", sold_so_far_usd: 0, contracts_left: 2 } },
    { at: at(21, 11, 0), kind: "giveback", kind_label: "Give-back", contract: "AMD 11/21/26 250C", symbol: "AMD", pnl_pct_at_alert: null,
      decision: null, decided_at: null, outcome: { state: "not_measured", why: "no price at the alert" } },
  ],
  radar: {
    state: "ok", window_days: 30, hits: 3, truncated: false,
    summary: { watching: { hits: 1, measured: 1, kept_going: 1, avg_close_pct: 2.4 }, planning: { hits: 1, measured: 1, kept_going: 0, avg_close_pct: -1.1 },
      passing: { hits: 0, measured: 0, kept_going: 0, avg_close_pct: null }, none: { hits: 1, measured: 0, kept_going: 0, avg_close_pct: null } },
    rows: [
      { event_id: "rv1-mu", at: at(28, 10, 42), symbol: "MU", kind: "relative_to_sector", kind_label: "vs sector", direction: "up", summary: null,
        decision: null, decided_at: null, planned: false, traded: false, after: { hour_pct: 0.8, close_pct: null, why: "the session is still open" } },
      { event_id: "rv1-nvda", at: at(27, 11, 5), symbol: "NVDA", kind: "relative_to_spy", kind_label: "vs SPY", direction: "up", summary: null,
        decision: "watching", decided_at: at(27, 11, 7), planned: false, traded: false, after: { hour_pct: 1.2, close_pct: 2.4, why: null } },
      { event_id: "rv1-amd", at: at(24, 14, 0), symbol: "AMD", kind: "relative_to_spy", kind_label: "vs SPY", direction: "down", summary: null,
        decision: "planning", decided_at: at(24, 14, 3), planned: true, traded: true, after: { hour_pct: null, close_pct: -1.1, why: "no pass recorded then" } },
    ],
  },
};

async function briefing(page: Page, card: unknown = CARD) {
  let reads = 0;
  await page.route("**/copilot/status", (route) => route.fulfill({ json: ON }));
  await page.route("**/copilot/investigations?*", (route) => route.fulfill({ json: { investigations: [] } }));
  await page.route("**/copilot/desk/scorecard", (route) => { reads += 1; return route.fulfill({ json: card }); });
  await page.goto("/copilot-lab");
  return { reads: () => reads };
}

test("the Briefing's scorecard says in one line how holding past alerts compared with selling at them, each alert one click away", async ({ page }) => {
  const { reads } = await briefing(page);
  const card = page.getByRole("region", { name: "Alert scorecard" });
  await expect(card).toContainText("last 30 days · against selling at the alert");
  await expect(card).toContainText("4 alerts. You held 2: 1 better than selling at the alert, 1 worse (net +$335). You exited 1: 1 still open. No decision logged on 1.");
  await expect(card.getByText("NBIS 11/21/26 100C")).toBeHidden(); // each alert waits behind the disclosure
  await card.getByText("Each alert ▾").click();
  await expect(card).toContainText("You logged holding · Sold for $1,040 vs $600 at the alert's bid: +$440");
  await expect(card).toContainText("You logged holding · Expired worthless vs $105 at the alert's bid: −$105");
  await expect(card).toContainText("You logged exiting · Still open · $620 at the alert's bid");
  await expect(card).toContainText("No decision logged · Not measured: no price at the alert");
  await card.screenshot({ path: test.info().outputPath("alert-scorecard-desktop.png") });

  // The same read carries Radar's: each stock hit, what was decided, and how far it went the way Radar flagged it.
  const radar = page.getByRole("region", { name: "Radar scorecard" });
  await expect(radar).toContainText("3 hits. You watched 1 (1 kept going, avg +2.4%). You planned 1 (0 kept going, avg −1.1%). No decision on 1.");
  await radar.getByText("Each hit ▾").click();
  await expect(radar).toContainText("No decision logged · 1h +0.8% · close: the session is still open");
  await expect(radar).toContainText("You logged watching · 1h +1.2% · close +2.4%");
  await expect(radar).toContainText("You logged planning · plan saved, traded · close −1.1%");
  await radar.screenshot({ path: test.info().outputPath("radar-scorecard-desktop.png") });
  expect(reads()).toBe(1);
});

test("while Radar is off the Radar scorecard stays out of the way", async ({ page }) => {
  await briefing(page, { ...CARD, radar: { state: "off", reason: "Radar recording is not switched on." } });
  await expect(page.getByRole("region", { name: "Alert scorecard" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Radar scorecard" })).toHaveCount(0);
});

test("with no alerts it says so, and at 375 px the scorecard fits without sideways scrolling", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await briefing(page);
  await page.getByRole("tablist", { name: "Desk" }).getByRole("tab").nth(1).click();
  const card = page.getByRole("region", { name: "Alert scorecard" });
  await card.getByText("Each alert ▾").click();
  await expect(card).toContainText("Sold for $1,040");
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
  await page.screenshot({ path: test.info().outputPath("alert-scorecard-375.png"), fullPage: true });

  await page.unroute("**/copilot/desk/scorecard");
  await page.route("**/copilot/desk/scorecard", (route) => route.fulfill({ json: { ...CARD, alerts: 0, rows: [],
    summary: { holding: tally({}), exiting: tally({}), none: tally({}) } } }));
  await page.reload();
  await page.getByRole("tablist", { name: "Desk" }).getByRole("tab").nth(1).click();
  await expect(page.getByRole("region", { name: "Alert scorecard" })).toContainText("No position alert was sent to your phone in the last 30 days.");
});
