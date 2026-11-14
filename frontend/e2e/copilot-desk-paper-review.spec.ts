import { expect, test, type Page } from "@playwright/test";

// The top of the desk's Paper section (docs/copilot-lab.md § Paper): the newest Friday paper review with its date, shown
// until the next one, and the "How am I doing?" chip, which asks the copilot that question (the copilot reads the paper
// book with get_paper_book). Every lab route is stubbed in the browser (the e2e backend runs with the lab off). Invented
// numbers.
const ON = {
  enabled: true, backend: "fake", evidence: "live", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
const NOW = new Date("2026-11-16T15:00:00Z"); // Monday 10:00 New York: last Friday's review is still the newest
const at = (iso: string) => Date.parse(iso) / 1000;
const DESK = {
  as_of: NOW.toISOString(), quotes_at: null, quote_issue: null, day: { phase: "regular", need_you: 0, streak: null },
  sections: { positions: "ok" }, plans: [], threads: [{ key: "briefing", group: "pinned", title: "Briefing", symbol: null, instrument: null, value: null,
    meter: null, investigation_id: null, trade_id: null, radar_event_id: null, path: null, changed_at: null, status: { text: "Nothing new.", tone: "muted" } }],
};
const stats = (pnl: number, trades: number, win: number | null) => ({ trades, pnl, win_rate: win, avg_win: pnl > 0 ? pnl : null, avg_loss: pnl < 0 ? pnl : null,
  largest_loss: pnl < 0 ? pnl : null, curve: [{ day: "2026-11-13", pnl }] });
const REVIEW = {
  day: "2026-11-13", monday: "2026-11-09", at: at("2026-11-13T21:45:00Z"),
  text: "Week: paper +$129.50 over 2 closed, real -$180.00 over 2.\nWorked: NBIS $100 Call 11/20/26, realised +$140.00: you sold into the target you set.\n"
    + "Stops and targets: NBIS took its 105 target; MU and AMD have no stop.\nNext week: set a stop before the entry, as you did on NBIS.",
};
const MAIN = "66666666-6666-4666-8666-666666666666";
const MAIN_CHAT = { id: MAIN, source: "copilot", title: "Main chat · 2026-11-16", symbol: null, status: "open", conclusion: null, main_day: "2026-11-16",
  revision: 1, message_count: 0, has_findings: false, created_at: "2026-11-16T13:00:00Z", updated_at: "2026-11-16T13:00:00Z", transcript: [], evidence: [], findings: null };
const BOOK = {
  run: { id: "r1", number: 1, starting_cash: 10000, started_at: at("2026-11-05T15:00:00Z") },
  account: { cash: 10129.5, collateral: 0, buying_power: 10129.5, equity: 10129.5, pnl: 129.5, unpriced: 0 },
  positions: [], closed: [], score: { paper: { ...stats(129.5, 2, 50), open_pnl: null }, real: stats(-180, 2, 0) },
  earlier: [], market_open: true, review: REVIEW,
};

async function open(page: Page, width: number, book: object = BOOK) {
  const chats: unknown[] = [];
  await page.setViewportSize({ width, height: 900 });
  await page.clock.install({ time: NOW });
  await page.route("**/copilot/status", route => route.fulfill({ json: ON }));
  await page.route("**/copilot/desk/threads", route => route.fulfill({ json: DESK }));
  await page.route("**/copilot/investigations?*", route => route.fulfill({ json: { investigations: [] } }));
  await page.route(url => url.pathname.endsWith("/copilot/paper"), route => route.fulfill({ json: book }));
  // Today's main conversation, so a phone's ask never waits on the e2e backend (its lab is off).
  await page.route("**/copilot/main-chat", route => route.fulfill({ json: MAIN_CHAT }));
  await page.route("**/copilot/main-chat/history*", route => route.fulfill({ json: { conversations: [] } }));
  await page.route(`**/copilot/investigations/${MAIN}`, route => route.fulfill({ json: MAIN_CHAT }));
  await page.route("**/copilot/chat", route => { chats.push(route.request().postDataJSON()); return route.abort(); });
  await page.goto("/copilot-lab");
  if (width < 768) await page.getByTestId("desk-view-book").click();
  const paper = page.getByTestId("desk-paper");
  await expect(paper).toBeVisible();
  return { paper, chats };
}

for (const width of [1440, 375]) {
  test(`the newest paper review shows with its date, and How am I doing? asks the copilot, at ${width}px`, async ({ page }) => {
    const { paper, chats } = await open(page, width);
    const review = paper.getByTestId("paper-review");
    await expect(review).toContainText("Paper review · Fri, Nov 13");
    const text = paper.getByTestId("paper-review-text");
    await expect(text.locator("p")).toHaveCount(4);
    await expect(text).toContainText("Week: paper +$129.50 over 2 closed, real -$180.00 over 2.");
    await expect(text).toContainText("Next week: set a stop before the entry, as you did on NBIS.");
    // It sits above the paper account line.
    const reviewBox = (await review.boundingBox())!, accountBox = (await paper.getByTestId("paper-account").boundingBox())!;
    expect(reviewBox.y).toBeLessThan(accountBox.y);
    const chip = paper.getByTestId("paper-how-am-i-doing");
    expect((await chip.boundingBox())!.height).toBeGreaterThanOrEqual(width < 768 ? 44 : 28);
    await chip.click();
    await expect.poll(() => chats.length).toBe(1);
    expect(JSON.stringify(chats[0])).toContain("How am I doing on paper?");
  });
}

test("with no review yet the chip still asks, and no review line is shown", async ({ page }) => {
  const { paper, chats } = await open(page, 1440, { ...BOOK, review: null });
  await expect(paper.getByTestId("paper-how-am-i-doing")).toBeVisible();
  await expect(paper.getByTestId("paper-review-text")).toHaveCount(0);
  await expect(paper.getByTestId("paper-review")).not.toContainText("Paper review ·");
  await paper.getByTestId("paper-how-am-i-doing").click();
  await expect.poll(() => chats.length).toBe(1);
});
