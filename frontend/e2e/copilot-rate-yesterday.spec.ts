import { expect, test, type Page } from "@playwright/test";

// Main chat's Rate yesterday card (docs/copilot-lab.md#the-desk): what still waits on a rating since the previous trading
// session, each answered with one tap through its existing route (an alert's feedback, a Radar hit's rating, an answer's
// Helped / Didn't). Every route is stubbed in the browser; no model runs.
const ON = {
  enabled: true, backend: "fake", evidence: "live", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
const DAY = new Date().toLocaleDateString("en-CA", { timeZone: "America/New_York" });
const now = Math.floor(Date.now() / 1000);
const MAIN = "66666666-6666-4666-8666-666666666666";
const EARLIER = "77777777-7777-4777-8777-777777777777";
const NBIS_TRADE = "44444444-4444-4444-8444-444444444444";
const ALERT = "a1111111-1111-4111-8111-111111111111";
const HIT = "rv1-2026-11-06-sec-mu-up-1";
const ITEMS = [
  { key: `answer:${MAIN}:1`, type: "answer", investigation_id: MAIN, index: 1, label: "Should I trim APLD into this strength before the close or…",
    detail: "Main chat", at: now - 600, answers: ["helped", "didnt"] },
  { key: `alert:${ALERT}`, type: "alert", id: ALERT, trade_id: NBIS_TRADE, label: "NBIS 11/21/26 100C", detail: "Give-back", at: now - 86400,
    answers: ["prompted_review", "already_aware", "too_late", "not_useful"] },
  { key: `radar:${HIT}`, type: "radar", event_id: HIT, label: "MU",
    detail: "MU ahead of its sector SMH by 3.5% over 30 min (MU +4.1%, SMH +0.6%)", at: now - 86400 - 3600,
    answers: ["useful", "already_knew", "too_late", "irrelevant"] },
  { key: `answer:${EARLIER}:3`, type: "answer", investigation_id: EARLIER, index: 3, label: "What changed on APLD?", detail: "APLD calls",
    at: now - 86400 - 7200, answers: ["helped", "didnt"] },
];
const conversation = (id: string, title: string, mainDay: string | null) => ({ id, source: "copilot", title, symbol: null, status: "open",
  conclusion: null, main_day: mainDay, revision: 1, message_count: 0, has_findings: false, created_at: `${DAY}T13:00:00Z`,
  updated_at: `${DAY}T13:00:00Z`, transcript: [], evidence: [], findings: null });

// The route as the backend sees it, without the frontend's proxy prefix.
const routePath = (url: string) => new URL(url).pathname.replace(/^.*?(?=\/(trades|radar|copilot)\/)/, "");

async function mainChat(page: Page, { failAnswers = false } = {}) {
  const saved: { url: string; body: Record<string, unknown> }[] = [];
  const main = conversation(MAIN, `Main chat · ${DAY}`, DAY);
  await page.route("**/copilot/status", (route) => route.fulfill({ json: ON }));
  await page.route("**/copilot/investigations?*", (route) => route.fulfill({ json: { investigations: [] } }));
  await page.route("**/copilot/chat", (route) => route.abort());
  await page.route("**/copilot/main-chat", (route) => route.fulfill({ json: main }));
  await page.route("**/copilot/main-chat/history", (route) => route.fulfill({ json: { chats: [main] } }));
  await page.route(`**/copilot/investigations/${MAIN}`, (route) => route.fulfill({ json: main }));
  await page.route("**/copilot/desk/threads", (route) => route.fulfill({ json: { as_of: new Date().toISOString(), quotes_at: null, quote_issue: null,
    sections: {}, day: { phase: "regular", need_you: 0, streak: null }, threads: [] } }));
  await page.route("**/copilot/desk/session", (route) => route.fulfill({ json: {
    as_of: new Date(now * 1000).toISOString(), now, day: DAY, phase: "regular", open: now - 3600, close: now + 7200,
    events: [], time_stops: [], pings: { sent: 0, held: 0, cap: 12 }, indices: [], quote_issue: null,
    prep: { at: now - 7200, line: "Risk-on into CPI.", lines: ["Risk-on into CPI.", "APLD holds 31.20."], fallback: false, path: null },
    to_answer: { alerts: { count: 0, rows: [] }, radar: null }, sections: {},
  } }));
  await page.route("**/copilot/desk/to-rate", (route) => route.fulfill({ json: {
    day: DAY, since: "2026-11-06", count: ITEMS.length, items: ITEMS, sections: { alerts: "ok", radar: "ok", answers: "ok" } } }));
  const record = (route: Parameters<Parameters<Page["route"]>[1]>[0]) => {
    const body = route.request().postDataJSON();
    saved.push({ url: routePath(route.request().url()), body });
    return body;
  };
  await page.route("**/trades/*/phone-alerts/*/feedback", (route) => {
    const body = record(route);
    return route.fulfill({ json: { rating: body.rating, reason: body.reason, version: 1, created_at: now, updated_at: now } });
  });
  await page.route("**/radar/events/*/feedback", (route) => route.fulfill({ json: { event_id: HIT, rating: record(route).rating } }));
  await page.route("**/copilot/investigations/*/messages/*/rating", (route) => {
    record(route);
    return failAnswers ? route.fulfill({ status: 500, json: { detail: "boom" } }) : route.fulfill({ json: main });
  });
  await page.route(`**/day-journal/${DAY}`, (route) => route.fulfill({ json: { day: DAY, entries: [], trade_plans: {} } }));
  await page.goto("/copilot-lab");
  return saved;
}

for (const width of [1440, 390]) {
  test(`today's Main chat opens on what waits on a rating, each saved with one tap through its own route (${width} px)`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    const saved = await mainChat(page);
    const card = page.getByRole("region", { name: "Rate yesterday" });
    await expect(card).toContainText("4 waiting");
    await expect(card.getByTestId("rate-row")).toHaveCount(4);
    await expect(card.getByTestId("rate-row").first()).toContainText("Answer · Should I trim APLD");
    // The card sits above the morning brief, at the top of the day's conversation.
    const [cardBox, briefBox] = [await card.boundingBox(), await page.getByRole("region", { name: "Morning brief" }).boundingBox()];
    expect(cardBox!.y).toBeLessThan(briefBox!.y);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    await page.getByRole("region", { name: "Conversation" }).screenshot({ path: test.info().outputPath(`rate-yesterday-${width}.png`) });

    const alert = card.getByTestId("rate-row").filter({ hasText: "NBIS 11/21/26 100C" });
    await alert.getByRole("button", { name: "Prompted a review" }).click();
    await expect(alert).toHaveCount(0);
    await expect(card).toContainText("3 waiting");
    await expect(card.getByRole("status")).toHaveText("Saved: Alert NBIS 11/21/26 100C · Prompted a review");

    await card.getByTestId("rate-row").filter({ hasText: "Radar · MU" }).getByRole("button", { name: "Useful" }).click();
    await card.getByTestId("rate-row").filter({ hasText: "What changed on APLD?" }).getByRole("button", { name: "Didn't" }).click();
    await expect(card.getByTestId("rate-row")).toHaveCount(1);
    await card.getByTestId("rate-row").getByRole("button", { name: "Helped" }).click();
    await expect(card).toHaveCount(0); // nothing left: the card is gone

    expect(saved).toEqual([
      { url: `/trades/${NBIS_TRADE}/phone-alerts/${ALERT}/feedback`, body: { rating: "prompted_review", reason: null, base_version: 0 } },
      { url: `/radar/events/${HIT}/feedback`, body: { rating: "useful" } },
      { url: `/copilot/investigations/${EARLIER}/messages/3/rating`, body: { rating: "didnt" } },
      { url: `/copilot/investigations/${MAIN}/messages/1/rating`, body: { rating: "helped" } },
    ]);
  });
}

test("a rating that could not be saved keeps its row and says so", async ({ page }) => {
  const saved = await mainChat(page, { failAnswers: true });
  const card = page.getByRole("region", { name: "Rate yesterday" });
  const row = card.getByTestId("rate-row").filter({ hasText: "What changed on APLD?" });
  await row.getByRole("button", { name: "Helped" }).click();
  await expect(row.getByRole("alert")).toHaveText("The rating could not be saved. Try again.");
  await expect(card.getByTestId("rate-row")).toHaveCount(4);
  expect(saved).toEqual([{ url: `/copilot/investigations/${EARLIER}/messages/3/rating`, body: { rating: "helped" } }]);
});
