import { expect, test, type Page } from "@playwright/test";
import { answerParts } from "../lib/copilot";

// Comparing two choices on the desk (docs/copilot-lab.md § How the copilot reasons): an answer's "Compare: A | B" line
// and its rows render side by side with the scenario names as headers, and stack as two labelled cards at 375 px with
// nothing scrolling sideways. Every lab route is stubbed in the browser and the answer is a saved one, so no model runs.
const INV = "99999999-9999-4999-8999-999999999999";
const ANSWER = "Verdict: Wait — The evidence leans to waiting for 95.9.\n\n_(Simulated model — scripted text from the tool results, not Claude.)_\n\n"
  + "Read: Thesis holds · Timing early · Contract n/a\n\n"
  + "Compare: enter now | wait for 95.9\nNeeds: the group to keep leading | a 5m close above 95.9 on volume\n"
  + "Risks: buying under a level that rejected twice | paying up a dollar higher\nBreaks if: NBIS loses 92.3 | 95.9 never closes above\n\n"
  + "Against: CRWV is up 2.4% and NBIS often follows it within the hour.\n\nChanges if: NBIS closes above 95.9 before 11:00.";
const ON = {
  enabled: true, backend: "fake", evidence: "fixture", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true, transcriber: { configured: true, provider: "test" } },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
const SAVED = {
  id: INV, source: "copilot", title: "Enter now or wait?", symbol: "NBIS", status: "open", conclusion: null, revision: 1,
  message_count: 2, has_findings: false, created_at: "2026-10-29T14:00:00Z", updated_at: "2026-10-29T14:05:00Z",
  transcript: [{ role: "user", content: "NBIS: enter now or wait for 95.9, which?" }, { role: "assistant", content: ANSWER }], evidence: [], findings: null,
};
const DESK = {
  as_of: "2026-10-29T14:00:00Z", quotes_at: null, quote_issue: null, day: { phase: "regular", need_you: 0, streak: null },
  sections: { positions: "ok", plans: "ok", investigations: "ok", radar: "off" }, threads: [],
};

async function lab(page: Page) {
  await page.route("**/copilot/status", (route) => route.fulfill({ json: ON }));
  await page.route("**/copilot/desk/threads", (route) => route.fulfill({ json: DESK }));
  await page.route("**/copilot/desk/*/timeline", (route) => route.fulfill({ json: { events: [], sources: {} } }));
  await page.route("**/copilot/investigations?*", (route) => route.fulfill({ json: { investigations: [] } }));
  await page.route("**/copilot/investigations/*", (route) => route.fulfill({ json: SAVED }));
  await page.route("**/charts/alerts", (route) => route.fulfill({ json: { alerts: [], phone: true } }));
  await page.route("**/copilot/research-jobs?*", (route) => route.fulfill({ json: { jobs: [], queue_enabled: false, daily_budget_usd: 2, spent_today_usd: 0 } }));
  await page.route("**/copilot/quote?*", (route) => route.fulfill({ json: { symbol: "NBIS", last: 94.35, trade_time: 1, fetched_at: 1, age_s: 2, issue: null, fresh: true } }));
  await page.route("**/charts/captures/setup", (route) => route.fulfill({ json: { accounts: [], default_account_id: null, templates: [], max_templates: 3,
    transcriber: { configured: false, provider: "off", note: "" } } }));
  await page.route("**/copilot/time-stops?*", (route) => route.fulfill({ json: { time_stops: [], enabled: false } }));
  await page.goto(`/copilot-lab?investigation=${INV}`);
  return page.getByRole("region", { name: "Conversation" }).getByTestId("copilot-answer");
}

test("the parser takes a compare block only with its Compare line and two rows", () => {
  const parts = answerParts(ANSWER)!;
  expect(parts.compare).toEqual({ a: "enter now", b: "wait for 95.9", rows: [
    { label: "Needs", a: "the group to keep leading", b: "a 5m close above 95.9 on volume" },
    { label: "Risks", a: "buying under a level that rejected twice", b: "paying up a dollar higher" },
    { label: "Breaks if", a: "NBIS loses 92.3", b: "95.9 never closes above" },
  ] });
  expect(parts.body).toBe("_(Simulated model — scripted text from the tool results, not Claude.)_");
  expect(parts.against).toMatch(/^CRWV/);
  const one = answerParts("Verdict: Wait — Not yet.\n\nCompare: now | later\nNeeds: x | y\n\nThe group leads.")!;
  expect(one.compare).toBeNull();
  expect(one.body).toBe("Compare: now | later\nNeeds: x | y\n\nThe group leads."); // left in the body, as before
});

test("at 1440 px two choices sit side by side under their names, rows labelled on the left", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const answer = await lab(page);
  await expect(answer.getByTestId("copilot-verdict")).toHaveText("Wait");
  const grid = answer.getByRole("table", { name: "Compare enter now and wait for 95.9" });
  await expect(grid).toBeVisible();
  await expect(answer.getByTestId("copilot-compare-cards")).toBeHidden();
  await expect(grid.getByRole("columnheader")).toHaveText(["", "enter now", "wait for 95.9"]);
  await expect(grid.getByRole("rowheader")).toHaveText(["Needs", "Risks", "Breaks if"]);
  await expect(grid.getByRole("row").nth(1).getByRole("cell")).toHaveText(["the group to keep leading", "a 5m close above 95.9 on volume"]);
  const [a, b] = await grid.getByRole("columnheader").evaluateAll((cells) => cells.slice(1).map((cell) => cell.getBoundingClientRect().x));
  expect(b).toBeGreaterThan(a + 100); // side by side, not stacked
  await expect(answer).not.toContainText("Compare:");
  await expect(answer.getByTestId("copilot-against")).toBeVisible();
  // Each cell can be disputed on its own: its row, its side and its words go into the message box, unsent.
  await grid.getByRole("row").nth(1).getByRole("cell").nth(1).getByRole("button", { name: "Push back on this" }).click();
  await expect(page.getByLabel("Message")).toHaveValue('Push back on "Needs (wait for 95.9): a 5m close above 95.9 on volume": ');
  await page.screenshot({ path: test.info().outputPath("compare-1440.png") });
});

test("at 375 px the choices stack as two labelled cards, A then B, and nothing scrolls sideways", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  const answer = await lab(page);
  await expect(answer.getByTestId("copilot-compare-grid")).toBeHidden();
  const first = answer.getByRole("region", { name: "A: enter now" });
  const second = answer.getByRole("region", { name: "B: wait for 95.9" });
  await expect(first).toContainText("Needs" + "the group to keep leading");
  await expect(second).toContainText("Breaks if" + "95.9 never closes above");
  expect((await first.boundingBox())!.y).toBeLessThan((await second.boundingBox())!.y);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
  expect(await answer.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);
  await answer.screenshot({ path: test.info().outputPath("compare-375.png") });
});
