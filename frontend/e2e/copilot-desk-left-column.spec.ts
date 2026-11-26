import { expect, test, type Page } from "@playwright/test";

// The desk's left column (docs/copilot-lab.md § The desk), money and safety first: the book with "At risk now" under its
// heading, Watching, the day's block, How I'm doing this week (REAL beside PAPER), one neutral My rules line, then Practice (paper, the two QQQ paper books, Replay)
// with one line each that opens its full section in place. The paper line is open by itself while a paper position or
// working paper order exists. Every route is stubbed with invented numbers, so nothing reaches the e2e backend.
const ON = {
  enabled: true, backend: "fake", evidence: "live", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
const NOW = new Date("2026-11-13T16:00:00Z"); // Friday 11:00 New York, in the session
const epoch = (iso: string) => Date.parse(iso) / 1000;
const g = (pnl: number, trades: number, win: number | null) => ({ trades, pnl, win_rate: win });
const stats = (pnl: number, trades: number, win: number | null) => ({ ...g(pnl, trades, win), avg_win: null, avg_loss: null, largest_loss: null, curve: [] });
const SPLIT = { followed: g(184.5, 3, 66.7), broken: g(-260, 2, 0), unclear: g(0, 0, null), unrecorded: 0, by_rule: [] };
const KINDS = [{ kind: "max_loss", words: "Max loss per trade ${n}", unit: "$", min: 1, max: 1000000, why_not: null },
  { kind: "max_trades_day", words: "No more than {n} trades a day", unit: "trades", min: 1, max: 100, why_not: null }];
const LOSS = { kind: "max_loss", n: 300, book: "real", goal: "Max loss per trade $300", text: "max loss $220 (goal $300)", ok: true, stale: null };
const DAYS = { kind: "max_trades_day", n: 5, book: "real", goal: "No more than 5 trades a day", text: "most trades in a day 6 (Tue; goal 5)", ok: false, stale: null };
const OPEN = {
  id: "11111111-1111-4111-8111-111111111111", symbol: "NBIS", instrument: "option", option_type: "call", expiry: "2026-11-20",
  label: "NBIS $100 Call 11/20/26", bias: "long", credit: false, width: null, multiplier: 100, quantity: 2, remaining: 2, per_share: -3.4,
  cash: -680, basis: -680, stock: 98.05, note: null, stop: null, target: null, opened_at: epoch("2026-11-13T15:00:00Z"), source: "mine",
  status: "open", closed_at: null, realized: 0, legs: [{ quote: "NBIS261120C00100000", action: "buy", strike: 100 }], awaiting_close: false,
  mark: { per_share: 3.6, value: 720, pnl: 40, pct: 5.9, at: epoch("2026-11-13T15:59:00Z") }, auto: false, touched: {}, exiting: false, held: 0,
};
const BOOK = {
  run: { id: "r1", number: 1, starting_cash: 10000, started_at: epoch("2026-11-10T15:00:00Z") },
  account: { cash: 9320, collateral: 0, reserved: 0, buying_power: 9320, equity: 10040, pnl: 40, unpriced: 0, prices_at: null },
  positions: [], closed: [], orders: [],
  score: { paper: { ...stats(62.5, 6, 50), open_pnl: null, by_source: [], rules: SPLIT }, real: stats(-312, 3, 33.3), real_rules: null,
    week: { monday: "2026-11-09", real: stats(-145.5, 2, 50), paper: stats(0, 0, null) } },
  my_rules: [{ id: "r_stop000001", text: "Stop before I enter", check: { kind: "stop_set" } }, { id: "r_aplus00001", text: "Only A+ setups", check: null }],
  earlier: [], market_open: true, review: null,
  goals: { goals: [LOSS, DAYS], kinds: KINDS, max: 2, monday: "2026-11-09", label: "This week", progress: [LOSS, DAYS] },
};
const OVERNIGHT = { enabled: true, state: "holding", symbol: "QQQ", stake: 10000, backtest: { mean_bp: 4.2, years: "2016-2026" },
  nights: [{ day: "2026-11-12", status: "open", entry_at: epoch("2026-11-12T20:59:00Z"), entry: 674.25, exit_day: null, exit_at: null, exit: null, bp: null, dollars: null, note: null },
    { day: "2026-11-11", status: "closed", entry_at: epoch("2026-11-11T20:59:00Z"), entry: 681.1, exit_day: "2026-11-12", exit_at: epoch("2026-11-12T14:30:00Z"), exit: 682.4, bp: 19.1, dollars: 19.09, note: null }],
  totals: { closed: 1, missed: 0, mean_bp: 19.1, dollars: 19.09, up: 1 } };
const MOMENTUM = { enabled: true, symbol: "QQQ", stake: 10000, now: epoch("2026-11-13T16:00:00Z"), backtest: { mean_bp: 4.4, years: "2022-2026" }, holding: null,
  days: [{ day: "2026-11-12", bp: -6.2, dollars: -6.2, trades: [] }], totals: { days: 1, days_traded: 0, mean_bp: -6.2, dollars: -6.2, up: 0, missed_checks: 0 } };
const BOARD_ROW = { open: 0, unresolved: 0, pnl_2x: 0, exits: {}, graduated: false, status: "PAPER · 0 of 20 days, 0 of 40 trades" };
const PROVING = { enabled: true, graduate_trades: 40, graduate_days: 20, graduate_score: 3, review_days: 10, bracket: { take_profit: 0.2, stop: 0.15, hold_minutes: 60, flat_minutes: 5 },
  board: [{ ...BOARD_ROW, source: "open_window", name: "9:45 MU/NBIS rule", closed: 12, green: 7, pnl: 184, pnl_2x: 40, avg: 15.33, open: 1, status: "PAPER · 6 of 20 days, 12 of 40 trades" },
    { ...BOARD_ROW, source: "radar_setup", name: "Radar setups", closed: 9, green: 3, pnl: -212, avg: -23.56 },
    { ...BOARD_ROW, source: "jo_morning", name: "Jo's morning picks", closed: 0, green: 0, pnl: 0, avg: null }],
  recent: [{ source: "open_window", day: "2026-11-13", symbol: "MU", direction: "up", state: "closed", entry: 2, exit: 2.45, reason: "take_profit", pnl: 43.7, note: null, contract: "MU1" }] };
const REPLAY = { score: { ...stats(132, 4, 50) }, trades: [],
  runs: [{ id: "x1", day: "2026-11-06", starting_cash: 10000, started_at: epoch("2026-11-07T15:00:00Z"), open_at: null, close_at: null, symbols: ["NBIS"], realized: 132, trades: 4, left_open: 0 }] };
const SESSION = {
  as_of: "2026-11-13T16:00:00Z", now: epoch("2026-11-13T16:00:00Z"), day: "2026-11-13", phase: "regular",
  open: epoch("2026-11-13T14:30:00Z"), close: epoch("2026-11-13T21:00:00Z"), events: [], time_stops: [], pings: null, prep: null,
  indices: [], quote_issue: null, realized_today: 0, sections: {}, to_answer: { alerts: { count: 0, rows: [] }, radar: null },
};
const READS: Record<string, unknown> = {
  "/copilot/desk/threads": { as_of: "2026-11-13T16:00:00Z", quotes_at: null, quote_issue: null, day: { phase: "regular", need_you: 0, streak: null },
    sections: { positions: "ok" }, plans: [], robinhood: { state: "off" }, threads: [] },
  "/copilot/desk/session": SESSION,
  "/copilot/desk/watching": { state: "ok", symbols: [], count: 0, max: 30, imported_at: null, robinhood: "off", levels: {}, setups: {} },
  "/copilot/desk/sparks": { as_of: "2026-11-13T16:00:00Z", spy_change_pct: 0.4, rows: {} },
  "/copilot/desk/overnight": OVERNIGHT,
  "/copilot/desk/momentum": MOMENTUM,
  "/copilot/desk/proving-ground": PROVING,
  "/copilot/paper/replay": REPLAY,
  "/copilot/investigations": { investigations: [] },
  "/copilot/tickets": { plans: [] },
  "/copilot/exposure": { state: "ok", at_risk_usd: 680, positions: 1, usual_day_usd: 2100, sample_days: 60, as_of: "2026-11-13T16:00:00Z", line: "At risk now: $680 in 1 option · usual day $2,100" },
  "/copilot/paper": BOOK,
};

async function open(page: Page, width: number, book: object = BOOK, folded: string[] | null = null, overrides: Record<string, unknown> = {}) {
  const reads: Record<string, unknown> = { ...READS, "/copilot/paper": book, ...overrides };
  // His folds on this device size (DeskUse.tsx): a folded piece is a slim stub.
  if (folded) reads["/copilot/desk/use"] = { size: width < 768 ? "phone" : "desk", today: "2026-11-13", window_days: 14, window_start: "2026-10-31",
    first_day: "2026-10-30", days_with_use: 3, pieces: {}, folds: { folded, snoozed_until: null } };
  await page.setViewportSize({ width, height: 900 });
  await page.clock.install({ time: NOW });
  await page.route("**/api/backend/**", route => route.fulfill({ status: 404, json: { detail: "Not in this test." } }));
  await page.route("**/copilot/status", route => route.fulfill({ json: ON }));
  await page.route("**/copilot/chat", route => route.abort());
  const found = (url: string) => Object.keys(reads).find(p => new URL(url).pathname.endsWith(p));
  await page.route(url => !!found(url.toString()), route => route.fulfill({ json: reads[found(route.request().url())!] }));
  await page.route("**/copilot/desk/minute?*", route => route.fulfill({ json: { reads: new URL(route.request().url()).searchParams.getAll("read").map(target => {
    const body = reads[target.split("?")[0]];
    return body ? { status: 200, body } : { status: 404, body: { detail: "Not in this test." } };
  }) } }));
  // The laptop folds Practice to one line; these tests read its lines, so this tab starts with it open.
  await page.addInitScript(() => { if (!window.sessionStorage.getItem("desk.practice.v1")) window.sessionStorage.setItem("desk.practice.v1", JSON.stringify({ practice: true })); });
  await page.goto("/copilot-lab");
  if (width < 768) await page.getByTestId("desk-view-book").click();
  if (width < 768) { // a phone keeps Practice, paper, rules and the scorecard under More (November 26, 2026)
    await page.getByTestId("desk-top-more").click();
    await page.getByTestId("desk-top-practice").click();
  }
  return reads; // a test may change what the next read returns
}

const top = async (page: Page, id: string) => (await page.getByTestId(id).boundingBox())!.y;

for (const width of [1440, 375]) {
  test(`money and safety first: the book with what is at risk, Watching, the day's block, My rules, then Practice, at ${width}px`, async ({ page }) => {
    await open(page, width);
    const book = page.getByTestId("desk-book");
    // What is at risk, in the book's heading line; the full line (in how many options, against a usual day) on hover.
    await expect(book.getByTestId("exposure-line")).toHaveText("· at risk $680");
    await expect(book.getByTestId("exposure-line")).toBeVisible();
    await expect(book.getByTestId("exposure-line")).toHaveAttribute("title", "At risk now: $680 in 1 option · usual day $2,100");
    await expect(page.getByTestId("since-you-looked")).toBeVisible();
    await expect(page.getByTestId("practice-line-replay")).toBeVisible();
    const order = ["desk-book", "desk-watching", "since-you-looked", "desk-scorecard", "rules-goals", "desk-practice"];
    for (let i = 1; i < order.length; i++) expect(await top(page, order[i - 1])).toBeLessThan(await top(page, order[i]));
    // Practice: one line each, with its mark and figure, in this order.
    const practice = page.getByTestId("desk-practice");
    await expect(practice.getByTestId("practice-line-paper")).toContainText("PaperMine· nothing open or working+$62.50 closed");
    await expect(practice.getByTestId("practice-line-overnight")).toContainText("PaperQQQ overnight· holding· +19.1 bp avg");
    await expect(practice.getByTestId("practice-line-momentum")).toContainText("PaperQQQ momentum· flat· −6.2 bp avg");
    await expect(practice.getByTestId("practice-line-replay")).toContainText("Replay4 trades+$132.00");
    for (const [id, mode] of [["paper", "paper"], ["overnight", "paper"], ["momentum", "paper"], ["replay", "replay"]]) {
      await expect(practice.getByTestId(`practice-line-${id}`).getByTestId("mode-mark")).toHaveAttribute("data-mode", mode);
    }
    // Rules and goals are not inside any paper frame; nothing of a closed line's section shows.
    await expect(page.getByTestId("rules-goals").locator("xpath=ancestor::*[@data-testid='desk-paper']")).toHaveCount(0);
    for (const id of ["desk-paper", "desk-overnight", "desk-momentum", "replay-practice"]) await expect(page.getByTestId(id)).toHaveCount(0);
    expect((await page.evaluate(() => document.documentElement.scrollWidth))).toBeLessThanOrEqual(width);
  });
}

for (const width of [1440, 390]) {
  test(`QQQ receipt gaps are visible before opening Practice details at ${width}px`, async ({ page }, testInfo) => {
    await open(page, width, BOOK, null, {
      "/copilot/desk/overnight": { ...OVERNIGHT, state: "flat", nights: [], totals: { ...OVERNIGHT.totals, closed: 0 },
        coverage: { missing: 1, latest_missing_day: "2026-11-12", unknown_days: 0 } },
      "/copilot/desk/momentum": { ...MOMENTUM, days: [], totals: { ...MOMENTUM.totals, days: 0 },
        coverage: { missing: 6, latest_missing_day: "2026-11-12", unknown_days: 1 } },
    });
    const practice = page.getByTestId("desk-practice");
    const overnight = practice.getByTestId("practice-line-overnight");
    const momentum = practice.getByTestId("practice-line-momentum");
    await expect(overnight).toContainText("1 unrecorded window");
    await expect(momentum).toContainText("6 unrecorded checks");
    await expect(momentum).toContainText("calendar incomplete");
    await overnight.click();
    await momentum.click();
    await expect(practice.getByTestId("desk-overnight")).toContainText("1 entry window without a receipt in the last 14 days. Latest Nov 12.");
    await expect(practice.getByTestId("desk-momentum")).toContainText("6 checks without a receipt in the last 14 days. Latest Nov 12.");
    await expect(practice.getByTestId("desk-momentum")).toContainText("Calendar coverage unavailable for 1 day.");
    const box = (await practice.boundingBox())!;
    expect(box.x + box.width).toBeLessThanOrEqual(width);
    await practice.screenshot({ path: testInfo.outputPath(`qqq-paper-coverage-${width}.png`) });
  });
}

for (const width of [1440, 375]) {
  test(`How I'm doing this week: REAL beside PAPER, outside the paper frame, at ${width}px`, async ({ page }) => {
    await open(page, width);
    const card = page.getByTestId("desk-scorecard");
    await expect(card.getByRole("heading")).toHaveText("How I'm doing · this week");
    // Two labelled columns, REAL then PAPER, each with trades, P&L and win rate; a side with no closed trade shows dashes.
    await expect(card.getByRole("columnheader").getByTestId("mode-mark")).toHaveText(["Real", "Paper"]);
    await expect(card.getByRole("rowheader")).toHaveText(["Trades", "P&L", "Win rate"]);
    await expect(card.getByTestId("scorecard-real")).toHaveText(["2", "−$145.50", "50%"]);
    await expect(card.getByTestId("scorecard-paper")).toHaveText(["0", "—", "—"]);
    // Not inside any paper frame or the Practice block; Replay keeps its own score in Practice.
    for (const frame of ["desk-paper", "desk-practice"]) await expect(card.locator(`xpath=ancestor::*[@data-testid='${frame}']`)).toHaveCount(0);
    await expect(card).not.toContainText("Replay");
    await expect(page.getByTestId("practice-line-replay")).toContainText("Replay4 trades+$132.00");
    const box = (await card.boundingBox())!;
    expect(box.x + box.width).toBeLessThanOrEqual(width);
    await card.screenshot({ path: test.info().outputPath(`desk-scorecard-${width}.png`) });
  });
}

test("How I'm doing folds like the column's other pieces: a slim stub, one tap shows it", async ({ page }) => {
  await open(page, 1440, BOOK, ["scorecard"]);
  const stub = page.getByTestId("fold-stub-scorecard");
  await expect(stub).toContainText("How I'm doing · folded");
  await expect(page.getByTestId("desk-scorecard")).toBeHidden();
  await stub.click();
  await expect(page.getByTestId("desk-scorecard")).toBeVisible();
});

test("an older paper read without this week's score shows no scorecard", async ({ page }) => {
  await open(page, 1440, { ...BOOK, score: { ...BOOK.score, week: undefined } });
  await expect(page.getByTestId("rules-goals")).toBeVisible();
  await expect(page.getByTestId("desk-scorecard")).toHaveCount(0);
});

test("a Practice line opens its full section in place and stays open for this tab; Replay a day opens Replay", async ({ page }) => {
  await open(page, 1440);
  const line = page.getByTestId("practice-line-overnight");
  await expect(line).toHaveAttribute("aria-expanded", "false");
  await line.click();
  await expect(line).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByTestId("practice-overnight").getByTestId("desk-overnight-state")).toContainText("Holding since Nov 12");
  await page.getByTestId("practice-line-replay").click();
  await expect(page.getByTestId("practice-replay").getByTestId("replay-practice")).toContainText("Replay practice");
  await page.reload();
  await expect(page.getByTestId("practice-overnight").getByTestId("desk-overnight")).toBeVisible();
  await expect(page.getByTestId("practice-replay").getByTestId("replay-practice")).toBeVisible();
  await page.getByTestId("practice-line-overnight").click();
  await expect(page.getByTestId("desk-overnight")).toHaveCount(0);
  await page.getByTestId("practice-replay-open").click();
  await expect(page.getByTestId("desk-replay")).toBeVisible();
});

for (const width of [1440, 375]) {
  test(`an open paper position opens the paper line by itself, its P&L on the line, at ${width}px`, async ({ page }) => {
    await open(page, width, { ...BOOK, positions: [OPEN] });
    const line = page.getByTestId("practice-line-paper");
    await expect(line).toHaveAttribute("aria-expanded", "true");
    await expect(line).toContainText("1 open");
    await expect(line.getByTestId("practice-paper-pnl")).toHaveText("+$40.00");
    const paper = page.getByTestId("practice-paper").getByTestId("desk-paper");
    await expect(paper.getByTestId("paper-position")).toContainText("NBIS $100 Call 11/20/26");
    const box = (await paper.getByTestId("paper-pnl").boundingBox())!;
    expect(box.x + box.width).toBeLessThanOrEqual(width);
  });
}

test("the proving ground line names the leading source and opens to the board by source", async ({ page }) => {
  await open(page, 1440);
  const line = page.getByTestId("practice-line-proving");
  await expect(line).toContainText("Proving ground· 9:45 MU/NBIS rule +$184 (not proven)");
  await line.click();
  const board = page.getByTestId("desk-proving-board");
  await expect(board.getByTestId("desk-proving-open_window")).toContainText("9:45 MU/NBIS rule12 +1 open7 of 12+$184PAPER · 6 of 20 days, 12 of 40 trades");
  await expect(board.getByTestId("desk-proving-jo_morning")).toContainText("—");
  await page.getByTestId("desk-proving").screenshot({ path: test.info().outputPath("desk-proving.png") });
});

test("closing the last paper position keeps the open paper line open", async ({ page }) => {
  const reads = await open(page, 1440, { ...BOOK, positions: [OPEN] });
  await expect(page.getByTestId("desk-paper").getByTestId("paper-position")).toHaveCount(1);
  reads["/copilot/paper"] = BOOK; // the next read: the position closed, nothing open or working
  await page.evaluate(() => window.dispatchEvent(new Event("tradejournal:paper-changed")));
  await expect(page.getByTestId("practice-line-paper")).toContainText("nothing open or working");
  await expect(page.getByTestId("practice-line-paper")).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByTestId("desk-paper").getByTestId("paper-account")).toBeVisible();
});

test("on the laptop Practice is one folded line until opened; the paper key still opens it", async ({ page }) => {
  await page.addInitScript(() => { if (!window.sessionStorage.getItem("desk.practice.v1")) window.sessionStorage.setItem("desk.practice.v1", "{}"); }); // as a new tab: nothing kept open
  await open(page, 1440);
  const toggle = page.getByTestId("practice-toggle");
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await expect(page.getByTestId("practice-line-paper")).toHaveCount(0);
  await toggle.click();
  await expect(page.getByTestId("practice-line-paper")).toBeVisible();
  await toggle.click();
  await expect(page.getByTestId("practice-line-paper")).toHaveCount(0);
  await page.reload(); // his choice holds for this tab
  await expect(page.getByTestId("practice-toggle")).toHaveAttribute("aria-expanded", "false");
  await page.keyboard.press("p"); // the paper key opens the block and its paper line
  await expect(page.getByTestId("practice-line-paper")).toHaveAttribute("aria-expanded", "true");
});

test("with nothing open the paper line waits closed and opens on a tap", async ({ page }) => {
  await open(page, 1440);
  const line = page.getByTestId("practice-line-paper");
  await expect(line).toHaveAttribute("aria-expanded", "false");
  await expect(page.getByTestId("desk-paper")).toHaveCount(0);
  await line.click();
  await expect(page.getByTestId("desk-paper").getByTestId("paper-account")).toBeVisible();
});

for (const width of [1440, 375]) {
  test(`My rules is one line that opens to the split, the rules editor and the goals editor, at ${width}px`, async ({ page }) => {
    await open(page, width);
    const rules = page.getByTestId("rules-goals");
    await expect(rules.getByTestId("rules-goals-line")).toHaveText("My 2 rules · followed on 3 of 5 trades · goals 1 of 2 this week");
    await expect(rules.getByTestId("rules-split")).toHaveCount(0);
    await rules.getByTestId("rules-goals-toggle").click();
    await expect(rules.getByTestId("rules-split")).toContainText("Paper followed +$184.50 66.7%/3 · broken −$260.00 0%/2");
    await rules.getByTestId("rules-toggle").click();
    await expect(rules.getByTestId("rules-editor").getByTestId("rules-editor-row")).toHaveCount(2);
    await expect(rules.getByTestId("goals-line")).toContainText("This week:");
    await rules.getByTestId("goals-set").click();
    await expect(rules.getByTestId("goals-editor").getByTestId("goals-editor-row")).toHaveCount(2);
    const box = (await rules.boundingBox())!;
    expect(box.x + box.width).toBeLessThanOrEqual(width);
  });
}

test("P and Jump to open a place inside its line: the paper line, My rules' editor, the goals editor", async ({ page }) => {
  await open(page, 1440);
  await expect(page.getByTestId("practice-line-paper")).toHaveAttribute("aria-expanded", "false");
  await page.keyboard.press("p");
  await expect(page.getByTestId("practice-line-paper")).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByTestId("desk-paper")).toBeVisible();
  const jump = async (name: string) => {
    await page.getByRole("button", { name: "Jump to a thread or command" }).click();
    await page.getByRole("dialog", { name: "Jump to" }).getByRole("option", { name: new RegExp(`^${name}`) }).click();
  };
  await jump("My rules");
  await expect(page.getByTestId("rules-goals").getByTestId("rules-editor")).toBeVisible();
  await jump("This week's goals");
  await expect(page.getByTestId("rules-goals").getByTestId("goals-editor")).toBeVisible();
});
