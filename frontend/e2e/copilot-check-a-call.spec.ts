import { expect, test, type Page } from "@playwright/test";

// The desk's Check a call tab (docs/copilot-lab.md § Check a call): paste a Discord call, see what was read (blanks marked
// for him to set) and the card, then Plan it (the plan flow with the levels as editable text, never a ticket) or Pass;
// the day's checked calls below. Every lab route is stubbed in the browser, so no model runs.
const ON = {
  enabled: true, backend: "fake", evidence: "fixture", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
const ID = "44444444-4444-4444-8444-444444444444";
const CHECKED = {
  id: ID, checked_at: "2026-11-11T15:41:00Z", day: "2026-11-11", source: "desk", raw: "entry: odte qqq 660 p", symbol: "QQQ",
  reading: { ticker: "QQQ", expiry: "2026-11-11", strike: 660, side: "put", entry: null, stop: null, target: null },
  verdict: "Pass", underlying_price: 666.1, outcome: null, outcome_at: null, planned: false, plan_href: null,
  card: { headline: "QQQ is 0.9% above the strike and rising", tiles: [["QQQ now", "$666.10"], ["660 put", "$0.84 × $0.88"],
    ["Needs by the close", "−0.9%"], ["Your 0DTE puts", "14 trades, 4 up, −$2,140"]],
  against: "A sharp drop this afternoon would pay.", changes_if: "QQQ loses 664, the morning low.", others: [], note: null },
};
const EARLIER = { ...CHECKED, id: "55555555-5555-4555-8555-555555555555", checked_at: "2026-11-11T14:58:00Z", source: "telegram", symbol: "RKLB",
  raw: "rklb 60c", reading: { ...CHECKED.reading, ticker: "RKLB", strike: 60, side: "call", expiry: "2026-11-21" }, verdict: "Draft", outcome: "passed",
  underlying_price: 58.2 };

async function lab(page: Page) {
  const posts: unknown[] = [];
  let passed = false;
  await page.route("**/copilot/status", (route) => route.fulfill({ json: ON }));
  await page.route("**/copilot/investigations?*", (route) => route.fulfill({ json: { investigations: [] } }));
  await page.route("**/copilot/chat", (route) => route.abort());
  await page.route("**/copilot/checks", async (route) => {
    if (route.request().method() === "POST") {
      posts.push(route.request().postDataJSON());
      return route.fulfill({ json: CHECKED });
    }
    return route.fulfill({ json: { day: "2026-11-11", checks: [EARLIER] } });
  });
  await page.route(`**/copilot/checks/${ID}/pass`, (route) => { passed = true; return route.fulfill({ json: { ...CHECKED, outcome: "passed", outcome_at: "2026-11-11T15:43:00Z" } }); });
  await page.route("**/copilot/desk/threads", (route) => route.fulfill({ json: { groups: [], sections: {} } }));
  await page.goto("/copilot-lab?view=new");
  const pane = page.getByRole("region", { name: "Chart and tools" });
  await pane.getByRole("tab", { name: "Check a call" }).click();
  return { posts, pane, passed: () => passed };
}

test("a pasted call shows what was read, the card, Plan it into the plan flow and Pass", async ({ page }) => {
  const { posts, pane, passed } = await lab(page);
  const tab = pane.getByTestId("check-a-call");
  await expect(tab.getByTestId("call-check-today")).toContainText("RKLB 60 call 11/21");
  await expect(tab.getByTestId("call-check-today")).toContainText("you passed");
  await expect(tab).toContainText("long-press the Discord message, tap Share, then Telegram and the TradeJournal bot");

  await tab.getByRole("textbox", { name: "The Discord message" }).fill("entry: odte qqq 660 p");
  await tab.getByTestId("call-check-run").click();
  expect(posts).toEqual([{ text: "entry: odte qqq 660 p" }]);
  const card = tab.getByTestId("call-check-card");
  await expect(card.getByTestId("call-check-verdict")).toHaveText("Pass");
  await expect(card).toContainText("QQQ is 0.9% above the strike and rising");
  await expect(card).toContainText("Your 0DTE puts");
  const reading = card.getByTestId("call-check-reading");
  await expect(reading).toContainText("11/11 (0DTE)");
  await expect(reading.locator("[data-empty=true]")).toHaveCount(3); // entry, stop and target: his to set
  await reading.getByRole("textbox", { name: "Your stop" }).fill("664");

  const href = await card.getByTestId("call-check-plan").getAttribute("href");
  const link = new URL(href!, "http://x");
  expect(link.pathname).toBe("/copilot-lab");
  expect(link.searchParams.get("origin")).toBe(`checked_call:${ID}`);
  expect(link.searchParams.get("context")).toBe(
    "Plan a trade: QQQ 660 put 11/11 (0DTE), from a Discord call I checked (my stop 664). My own entry trigger, invalidation, target and time stop:");
  for (const word of ["ticket", "buy", "sell", "take it"]) expect((await card.textContent())!.toLowerCase()).not.toContain(word);

  await card.getByTestId("call-check-pass").click();
  await expect(card).toContainText("Passed at 10:43.");
  expect(passed()).toBe(true);
  await expect(tab.getByTestId("call-check-today").getByRole("listitem")).toHaveCount(2);
});
