import { expect, test, type Page } from "@playwright/test";

// The two answers /proof measures, asked on the desk (docs/copilot-lab.md#the-desk): a sent position alert's feedback and a
// Radar hit's rating, saved through the routes the trade page and the Radar feed use. Every route is stubbed in the
// browser; no model runs.
const ON = {
  enabled: true, backend: "fake", evidence: "live", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
const DAY = new Date().toLocaleDateString("en-CA", { timeZone: "America/New_York" });
const now = Math.floor(Date.now() / 1000);
const NBIS_TRADE = "44444444-4444-4444-8444-444444444444";
const APLD_TRADE = "55555555-5555-4555-8555-555555555555";
const GIVEBACK = { id: "a1111111-1111-4111-8111-111111111111", trade_id: NBIS_TRADE, symbol: "NBIS", contract: "NBIS 11/21/26 100C",
  kind: "giveback", at: now - 1800, today: true, feedback: null };
const HELD = { id: "a2222222-2222-4222-8222-222222222222", trade_id: NBIS_TRADE, symbol: "NBIS", contract: "NBIS 11/21/26 100C",
  kind: "hold_hour", at: now - 3600, today: true,
  feedback: { rating: "already_aware", reason: null, version: 1, created_at: now - 3000, updated_at: now - 3000 } };
const EXPIRY = { id: "a3333333-3333-4333-8333-333333333333", trade_id: APLD_TRADE, symbol: "APLD", contract: "APLD 10/24/26 30C",
  kind: "expiry_final", at: now - 86400 * 3, today: false, feedback: null };
const HIT = `rv1-${DAY}-sec-mu-up-1`;
const OLD_HIT = "rv1-2026-10-27-spy-crwv-down-1";
const TO_ANSWER = {
  alerts: { count: 3, rows: [GIVEBACK, HELD, EXPIRY] }, // one more unanswered whose position left the journal
  radar: { count: 2, rows: [{ event_id: HIT, symbol: "MU", kind: "vs sector", at: now - 900, today: true, rating: null },
    { event_id: OLD_HIT, symbol: "CRWV", kind: "vs SPY", at: now - 86400 * 2, today: false, rating: null }] },
};

// The route as the backend sees it, without the frontend's proxy prefix.
const routePath = (url: string) => new URL(url).pathname.replace(/^.*?(?=\/(trades|radar)\/)/, "");

async function desk(page: Page, path: string) {
  const feedback: { url: string; body: Record<string, unknown> }[] = [];
  const ratings: { url: string; body: Record<string, unknown> }[] = [];
  await page.route("**/copilot/status", (route) => route.fulfill({ json: ON }));
  await page.route("**/copilot/investigations?*", (route) => route.fulfill({ json: { investigations: [] } }));
  await page.route("**/copilot/chat", (route) => route.abort());
  await page.route("**/copilot/desk/threads", (route) => route.fulfill({ json: { as_of: new Date().toISOString(), quotes_at: null, quote_issue: null,
    sections: {}, day: { phase: "regular", need_you: 0, streak: null }, threads: [] } }));
  await page.route("**/copilot/desk/session", (route) => route.fulfill({ json: {
    as_of: new Date(now * 1000).toISOString(), now, day: DAY, phase: "regular", open: now - 3600, close: now + 7200,
    events: [], time_stops: [], pings: { sent: 2, held: 0, cap: 12 }, prep: null, indices: [], quote_issue: null,
    to_answer: TO_ANSWER, sections: {},
  } }));
  await page.route("**/trades/*/phone-alerts/*/feedback", (route) => {
    const body = route.request().postDataJSON();
    feedback.push({ url: routePath(route.request().url()), body });
    return route.fulfill({ json: { rating: body.rating, reason: body.reason, version: body.base_version + 1, created_at: now, updated_at: now } });
  });
  await page.route("**/radar/events/*/feedback", (route) => {
    const body = route.request().postDataJSON();
    ratings.push({ url: routePath(route.request().url()), body });
    return route.fulfill({ json: { event_id: HIT, rating: body.rating } });
  });
  await page.route(`**/radar/events/${HIT}`, (route) => route.fulfill({ json: { event: {
    event_id: HIT, session_date: DAY, kind: "relative_to_sector", direction: "up", symbols: ["MU"],
    summary: "MU up 4.1% vs Semis by 3.2% over 30 min.", first_seen_at: `${DAY}T14:42:05.000Z` },
    revisions: [], rating: null, news: null, news_checks: [], plans: { planned: false, traded: false } } }));
  await page.route(`**/day-journal/${DAY}`, (route) => route.fulfill({ json: { day: DAY, entries: [], trade_plans: {} } }));
  await page.goto(path);
  return { feedback, ratings };
}

test("a position ping's thread asks about today's alerts for it, and an answer saves through the trade page's route", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const { feedback } = await desk(page, "/copilot-lab?symbol=NBIS");
  const asked = page.getByRole("region", { name: "Today's alerts" });
  await expect(asked.getByTestId("alert-answer")).toHaveCount(2); // NBIS today only: not APLD's from earlier in the week
  const giveback = asked.getByTestId("alert-answer").filter({ hasText: "Give-back" });
  await expect(asked.getByTestId("alert-answer").filter({ hasText: "Open an hour" })).toContainText("Answered: Already aware");
  await page.getByRole("region", { name: "Conversation" }).screenshot({ path: test.info().outputPath("proof-answers-alert-1440.png") });

  await giveback.getByRole("textbox").fill("Sold half on it");
  await giveback.getByRole("button", { name: "Prompted a review" }).click();
  await expect(giveback).toContainText("Answered: Prompted a review · Sold half on it");
  expect(feedback).toEqual([{ url: `/trades/${NBIS_TRADE}/phone-alerts/${GIVEBACK.id}/feedback`,
    body: { rating: "prompted_review", reason: "Sold half on it", base_version: 0 } }]);

  await giveback.getByRole("button", { name: "Change" }).click();
  await giveback.getByRole("button", { name: "Too late" }).click();
  await expect(giveback).toContainText("Answered: Too late");
  expect(feedback[1].body).toEqual({ rating: "too_late", reason: "Sold half on it", base_version: 1 });
});

test("a Radar hit's thread rates it beside the decision, through the Radar feed's route", async ({ page }) => {
  const { ratings } = await desk(page, `/copilot-lab?symbol=MU&radar=${HIT}`);
  await expect(page.getByRole("region", { name: "Radar hit" })).toContainText("MU up 4.1%");
  const rate = page.getByRole("region", { name: "Rate this hit" });
  await expect(page.getByRole("region", { name: "Radar hit" }).getByRole("button", { name: "Useful" })).toHaveCount(0); // beside, not inside
  await rate.getByRole("button", { name: "Useful" }).click();
  await expect(rate).toContainText("Rated: Useful");
  expect(ratings).toEqual([{ url: `/radar/events/${HIT}/feedback`, body: { rating: "useful" } }]);
});

for (const width of [1440, 375]) {
  test(`the Briefing counts what waits on an answer and answers it in place (${width} px)`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 375 ? 812 : 900 });
    const { feedback, ratings } = await desk(page, "/copilot-lab");
    if (width === 375) await page.getByRole("tab", { name: "Main" }).click(); // a phone opens on the thread list
    const alerts = page.getByTestId("briefing-alerts-to-answer");
    const hits = page.getByTestId("briefing-hits-to-rate");
    await expect(alerts.locator("summary")).toHaveText("3 alerts to answer ▾");
    await expect(hits.locator("summary")).toHaveText("2 Radar hits to rate ▾");

    await alerts.locator("summary").click();
    await expect(alerts.getByTestId("alert-answer")).toHaveCount(2); // the answered one is not listed
    await expect(alerts).toContainText("1 older not listed here.");
    const expiry = alerts.getByTestId("alert-answer").filter({ hasText: "APLD" });
    await expiry.getByRole("button", { name: "Not useful" }).click();
    await expect(expiry).toContainText("Answered: Not useful");
    await expect(alerts.locator("summary")).toHaveText("2 alerts to answer ▾");
    expect(feedback).toEqual([{ url: `/trades/${APLD_TRADE}/phone-alerts/${EXPIRY.id}/feedback`, body: { rating: "not_useful", reason: null, base_version: 0 } }]);

    await hits.locator("summary").click();
    const old = hits.getByTestId("hit-to-rate").filter({ hasText: "CRWV" });
    await old.getByRole("button", { name: "Already knew" }).click();
    await expect(old).toContainText("Rated: Already knew");
    await expect(hits.locator("summary")).toHaveText("1 Radar hit to rate ▾");
    expect(ratings).toEqual([{ url: `/radar/events/${OLD_HIT}/feedback`, body: { rating: "already_knew" } }]);

    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    await page.getByRole("region", { name: "Conversation" }).screenshot({ path: test.info().outputPath(`proof-answers-briefing-${width}.png`) });
  });
}
