import { expect, test, type Page } from "@playwright/test";

// His weekly goals on the desk (docs/copilot-lab.md § Weekly goals): with none set, the Paper section shows only a small
// "Set this week's goals" control; setting one or two takes a pick and a number; the line then shows the server's
// progress with ✓/✗, a goal whose source is behind is grey with why and never ticked, and the Friday review card carries
// a Goals row. Every route is stubbed with invented numbers, so nothing reaches the e2e backend.
const ON = {
  enabled: true, backend: "fake", evidence: "live", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
const NOW = new Date("2026-11-13T16:00:00Z"); // Friday 11:00 New York
const epoch = (iso: string) => Date.parse(iso) / 1000;
const stats = (pnl: number, trades: number, win: number | null) => ({ trades, pnl, win_rate: win, avg_win: null, avg_loss: null, largest_loss: null, curve: [] });
const KINDS = [
  { kind: "rules_pct", words: "Follow all my rules on {n}% of trades", unit: "%", min: 1, max: 100, why_not: null },
  { kind: "max_loss", words: "Max loss per trade ${n}", unit: "$", min: 1, max: 1000000, why_not: null },
  { kind: "max_trades_day", words: "No more than {n} trades a day", unit: "trades", min: 1, max: 100, why_not: null },
];
const NONE = { goals: [], kinds: KINDS, max: 2, monday: "2026-11-09", label: "This week", progress: [] };
const LOSS = { kind: "max_loss", n: 300, book: "real", goal: "Max loss per trade $300", text: "max loss $220 (goal $300)", ok: true, stale: null };
const DAYS = { kind: "max_trades_day", n: 5, book: "real", goal: "No more than 5 trades a day", text: "most trades in a day 6 (Tue; goal 5)", ok: false, stale: null };
const BOOK = {
  run: { id: "r1", number: 1, starting_cash: 10000, started_at: epoch("2026-11-10T15:00:00Z") },
  account: { cash: 9924.5, collateral: 0, reserved: 0, buying_power: 9924.5, equity: 9924.5, pnl: -75.5, unpriced: 0, prices_at: null },
  positions: [], closed: [], orders: [],
  score: { paper: { ...stats(-75.5, 6, 33.3), open_pnl: null, by_source: [] }, real: stats(-312, 3, 33.3), real_rules: null },
  my_rules: [], earlier: [], market_open: true, goals: NONE,
  review: { day: "2026-11-06", monday: "2026-11-02", at: epoch("2026-11-06T21:50:00Z"), text: "Week: paper +$120.00, real −$80.00.\nNext week: set the stop before the entry.",
    goals: [{ ...LOSS, text: "max loss $410 (goal $300)", ok: false }] },
};
const READS: Record<string, unknown> = {
  "/copilot/desk/threads": { as_of: "2026-11-13T16:00:00Z", quotes_at: null, quote_issue: null, day: { phase: "regular", need_you: 0, streak: null },
    sections: { positions: "ok" }, plans: [], robinhood: { state: "off" }, threads: [] },
  "/copilot/desk/watching": { state: "ok", symbols: [], count: 0, max: 30, imported_at: null, robinhood: "off", levels: {}, setups: {} },
  "/copilot/desk/sparks": { as_of: "2026-11-13T16:00:00Z", spy_change_pct: 0.4, rows: {} },
  "/copilot/investigations": { investigations: [] },
  "/copilot/tickets": { plans: [] },
  "/copilot/exposure": { line: null },
  "/copilot/paper": BOOK,
};

async function open(page: Page, width: number, goals: object = NONE) {
  const seen = { saves: [] as unknown[] };
  const reads: Record<string, unknown> = { ...READS, "/copilot/paper": { ...BOOK, goals } };
  await page.setViewportSize({ width, height: 900 });
  await page.clock.install({ time: NOW });
  await page.route("**/api/backend/**", route => route.fulfill({ status: 404, json: { detail: "Not in this test." } }));
  await page.route("**/copilot/status", route => route.fulfill({ json: ON }));
  await page.route("**/copilot/chat", route => route.abort());
  await page.route(url => Object.keys(READS).some(p => url.pathname.endsWith(p)),
    route => route.fulfill({ json: reads[Object.keys(READS).find(p => new URL(route.request().url()).pathname.endsWith(p))!] }));
  await page.route("**/copilot/desk/minute?*", route => {
    const found = new URL(route.request().url()).searchParams.getAll("read").map(target => {
      const body = reads[target.split("?")[0]];
      return body ? { status: 200, body } : { status: 404, body: { detail: "Not in this test." } };
    });
    return route.fulfill({ json: { reads: found } });
  });
  await page.route("**/copilot/goals", route => {
    const body = route.request().postDataJSON();
    seen.saves.push(body);
    const set = { ...NONE, goals: body.goals, progress: body.goals.length ? [LOSS, DAYS] : [] };
    reads["/copilot/paper"] = { ...BOOK, goals: set };
    return route.fulfill({ json: set });
  });
  await page.goto("/copilot-lab");
  return seen;
}

async function paperSection(page: Page, width: number) {
  if (width < 768) await page.getByTestId("desk-view-book").click();
  return page.getByTestId("desk-paper");
}

for (const width of [1440, 375]) {
  test(`with no goals only the small control shows; setting two takes a pick and a number at ${width}px`, async ({ page }) => {
    const seen = await open(page, width);
    const paper = await paperSection(page, width);
    const goals = paper.getByTestId("goals");
    await expect(goals.getByTestId("goals-set")).toHaveText("Set this week's goals");
    await expect(goals.getByTestId("goals-line")).toHaveCount(0);
    await goals.getByTestId("goals-set").click();
    const editor = goals.getByTestId("goals-editor");
    await editor.getByLabel("Goal 1", { exact: true }).selectOption("max_loss");
    await expect(editor.getByLabel("Goal 1 N")).toHaveValue("300");  // a sensible number already in
    await editor.getByRole("button", { name: "Add a goal" }).click();
    await expect(editor.getByTestId("goals-editor-row")).toHaveCount(2);
    await expect(editor.getByRole("button", { name: "Add a goal" })).toHaveCount(0);  // two at most
    await editor.getByLabel("Goal 2", { exact: true }).selectOption("max_trades_day");
    await editor.getByTestId("goals-save").click();
    await expect(editor).toBeHidden();
    expect(seen.saves.at(-1)).toEqual({ goals: [{ kind: "max_loss", n: 300, book: "real" }, { kind: "max_trades_day", n: 5, book: "real" }] });
    const line = goals.getByTestId("goals-line");
    await expect(line).toContainText("This week:");
    await expect(line.getByTestId("goal-progress").first()).toHaveText("max loss $220 (goal $300)✓");
    await expect(line.getByTestId("goal-progress").nth(1)).toHaveText("most trades in a day 6 (Tue; goal 5)✗");
    // The review card's row: last week's goal, measured over last week.
    await expect(paper.getByTestId("paper-review-goals")).toHaveText("Goals:max loss $410 (goal $300)✗");
    const box = await paper.boundingBox();
    expect(box!.width).toBeLessThanOrEqual(width);
  });
}

test("a goal whose source is behind is grey with why and its time, never ticked", async ({ page }) => {
  const stale = "Real trades as of Nov 12, 2:15 PM ET: new fills are not arriving.";
  await open(page, 1440, { ...NONE, goals: [{ kind: "max_loss", n: 300, book: "real" }], progress: [{ ...LOSS, ok: null, stale }] });
  const goals = (await paperSection(page, 1440)).getByTestId("goals");
  const item = goals.getByTestId("goal-progress");
  await expect(item).toHaveAttribute("data-stale", "true");
  await expect(item).toHaveText("max loss $220 (goal $300)");  // no ✓
  await expect(goals.getByTestId("goals-stale")).toHaveText(stale);
});

test("on a weekend the line names next week's goals with nothing measured yet, and Clear removes them", async ({ page }) => {
  const seen = await open(page, 1440, { ...NONE, label: "Next week", monday: "2026-11-16", goals: [{ kind: "rules_pct", n: 80, book: "paper" }, { kind: "max_trades_day", n: 5, book: "real" }], progress: [] });
  const goals = (await paperSection(page, 1440)).getByTestId("goals");
  await expect(goals.getByTestId("goals-line")).toContainText("Next week:Follow all my rules on 80% of trades (paper) · No more than 5 trades a day");
  await goals.getByTestId("goals-set").click();
  await goals.getByTestId("goals-clear").click();
  expect(seen.saves.at(-1)).toEqual({ goals: [] });
  await expect(goals.getByTestId("goals-set")).toHaveText("Set this week's goals");
});
