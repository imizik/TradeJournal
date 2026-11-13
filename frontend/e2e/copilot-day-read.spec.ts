import { expect, test, type Page } from "@playwright/test";

// The day read (docs/copilot-lab.md § The day read): after the close the copilot panel opens with a few lines on the
// owner's day above the day's conversation, asked once on open (the server keeps it for the day), with Ask more carrying
// the read and its facts into the message box and Refresh as the only second read. A day with nothing in it and a spent
// budget are one grey line each; before the close nothing is asked. Every route is stubbed in the browser; no model runs.
const ON = {
  enabled: true, backend: "fake", evidence: "live", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
const DAY = "2026-11-13"; // a Friday
const EVENING = Date.parse("2026-11-13T22:30:00Z") / 1000; // 17:30 New York
const MIDDAY = Date.parse("2026-11-13T16:00:00Z") / 1000; // 11:00 New York
const MAIN = "66666666-6666-4666-8666-666666666666";
const conversation = { id: MAIN, source: "copilot", title: `Main chat · ${DAY}`, symbol: null, status: "open", conclusion: null, main_day: DAY,
  revision: 1, message_count: 0, has_findings: false, created_at: `${DAY}T13:00:00Z`, updated_at: `${DAY}T13:00:00Z`, transcript: [], evidence: [], findings: null };
const TEXT = "P&L: realised -$252.50 today (Roth IRA -$375.00, Individual +$122.50); open Roth IRA +$1,204.00.\n"
  + "Plans: NBIS 100C had a plan saved first; CRWV 120C had none.\n"
  + "Biggest: NBIS 100C lost -$375.00 after you held through the 11:05 give-back alert.\n"
  + "Tomorrow: on a give-back alert like NBIS's, sell at the alert or write why you hold.";
const FACTS = "Today's facts (2026-11-13, as of 17:30 ET).\nRealised today (trades closed today): total -$252.50; Roth IRA -$375.00; Individual +$122.50";

type Asks = { refresh: boolean }[];

async function open(page: Page, answer: (asks: Asks) => unknown, { at = EVENING, width = 1440 } = {}) {
  const asks: Asks = [];
  await page.setViewportSize({ width, height: width < 768 ? 812 : 900 });
  await page.clock.install({ time: new Date(at * 1000) });
  await page.route("**/copilot/status", route => route.fulfill({ json: ON }));
  await page.route("**/copilot/investigations?*", route => route.fulfill({ json: { investigations: [] } }));
  await page.route("**/copilot/chat", route => route.abort());
  await page.route("**/copilot/main-chat", route => route.fulfill({ json: conversation }));
  await page.route("**/copilot/main-chat/history", route => route.fulfill({ json: { chats: [conversation] } }));
  await page.route(`**/copilot/investigations/${MAIN}`, route => route.fulfill({ json: conversation }));
  await page.route("**/copilot/desk/threads", route => route.fulfill({ json: { as_of: new Date(at * 1000).toISOString(), quotes_at: null,
    quote_issue: null, sections: {}, day: { phase: "regular", need_you: 0, streak: null }, threads: [], plans: [], robinhood: { state: "off" } } }));
  await page.route("**/copilot/desk/session", route => route.fulfill({ json: {
    as_of: new Date(at * 1000).toISOString(), now: at, day: DAY, phase: "regular", open: at - 3600, close: at + 7200, events: [], time_stops: [],
    pings: null, indices: [], quote_issue: null, prep: null, realized_today: -252.5, to_answer: { alerts: null, radar: null }, sections: {} } }));
  await page.route("**/copilot/desk/pings*", route => route.fulfill({ json: { day: DAY, since: DAY, alerts: { state: "ok", rows: [] }, radar: { state: "off", reason: null, rows: [] } } }));
  await page.route("**/copilot/desk/day-report", route => route.fulfill({ json: { day: DAY, as_of: new Date(at * 1000).toISOString(), entries: null, checks: null, sections: {} } }));
  await page.route("**/copilot/desk/feed", route => route.fulfill({ json: { as_of: new Date(at * 1000).toISOString(), now: at, day: DAY, total: 0, sources: {}, unavailable: [], items: [] } }));
  await page.route(`**/day-journal/${DAY}`, route => route.fulfill({ json: { day: DAY, entries: [], trade_plans: {} } }));
  await page.route("**/copilot/desk/day-read", route => {
    asks.push({ refresh: (route.request().postDataJSON() as { refresh: boolean }).refresh });
    return route.fulfill({ json: answer(asks) });
  });
  await page.goto("/copilot-lab");
  return asks;
}

const ok = (asks: Asks) => ({ state: "ok", text: asks.at(-1)?.refresh ? TEXT.replace("Tomorrow:", "Tomorrow (again):") : TEXT, facts: FACTS,
  at: EVENING, age_s: 0, cached: asks.length > 1 && !asks.at(-1)?.refresh, cost_usd: 0.04, today: { count: asks.filter(a => a.refresh).length + 1, refused: 0, cost_usd: 0.04 } });

for (const width of [1440, 375]) {
  test(`after the close the panel opens with the read of his day, asked once, refreshed only on his tap (${width} px)`, async ({ page }) => {
    const asks = await open(page, ok, { width });
    if (width < 768) await page.getByRole("button", { name: /Ask the copilot/ }).click();
    const read = page.getByTestId("day-read");
    await expect(read.getByTestId("day-read-text")).toContainText("Biggest: NBIS 100C lost -$375.00");
    await expect(read).toContainText("Your day");
    await expect(read.getByTestId("day-read-age")).toHaveText("Read at 5:30 PM · 1 today · $0.04");
    await expect(read).not.toContainText(/rate|Rate/);
    expect(asks).toEqual([{ refresh: false }]);
    await read.getByTestId("day-read-refresh").click();
    await expect(read.getByTestId("day-read-text")).toContainText("Tomorrow (again):");
    expect(asks).toEqual([{ refresh: false }, { refresh: true }]);
    await read.screenshot({ path: test.info().outputPath(`day-read-${width}.png`) });
  });
}

test("Ask more carries the read and the facts it was written from into the message box", async ({ page }) => {
  await open(page, ok);
  await page.getByTestId("day-read-ask").click();
  const box = page.getByRole("textbox", { name: "Message" });
  await expect(box).toBeFocused();
  await expect(box).toHaveValue(/^Context: the desk's read of my day at 5:30 PM ET:\nP&L: realised -\$252\.50[\s\S]*Tomorrow: on a give-back[\s\S]*\n\nThe day report's facts it was written from:\nToday's facts \(2026-11-13[\s\S]*Individual \+\$122\.50\n\n$/);
});

test("a day with nothing in it is one grey line", async ({ page }) => {
  await open(page, () => ({ state: "quiet", text: "Nothing to read today: no fills and no plans.", at: EVENING, cached: false, today: null }));
  await expect(page.getByTestId("day-read-quiet")).toHaveText("Nothing to read today: no fills and no plans.");
  await expect(page.getByTestId("day-read-refresh")).toHaveCount(0);
});

test("a spent budget is one grey line with no Refresh", async ({ page }) => {
  await open(page, () => ({ state: "budget", message: "No read of your day: today's copilot budget ($4.00) is spent.", today: { count: 0, refused: 1, cost_usd: 0 } }));
  await expect(page.getByTestId("day-read-none")).toHaveText("No read of your day: today's copilot budget ($4.00) is spent.");
  await expect(page.getByTestId("day-read-refresh")).toHaveCount(0);
});

test("before the close nothing is asked", async ({ page }) => {
  const asks = await open(page, ok, { at: MIDDAY });
  await expect(page.getByRole("textbox", { name: "Message" })).toBeVisible();
  await page.clock.runFor(5_000);
  expect(asks).toEqual([]);
  await expect(page.getByTestId("day-read")).toHaveCount(0);
});
