import { expect, test, type Page } from "@playwright/test";

// Saved-advice links (Dots step 5). The check owner reader is never running here, so connected
// cases fake its two reads; journal activity, links and unlinks go through the real seeded backend.
const CHECK = "chk_0f8c2a8e-1d6b-4c3a-9e1f-2b7a5c4d3e21";
type SeedTrade = { id: string; ticker: string; option_type: string | null; strike: number | null; expiration: string | null; opened_at: string; status: string };

async function nvda(page: Page): Promise<SeedTrade> {
  const trades = await (await page.request.get("/api/backend/trades")).json() as SeedTrade[];
  return trades.find(t => t.ticker === "NVDA" && t.status === "closed")!;
}

function savedCheck(trade: SeedTrade) {
  // The day before the seeded NVDA entry: inside the five-day window, before the trade.
  const received = new Date(Date.parse(`${trade.opened_at.slice(0, 10)}T12:00:00Z`) - 86_400_000).toISOString();
  const idea = { ticker: "NVDA", side: "long", instrument: "option", option_type: "call", horizon: "intraday",
    strike: trade.strike, expiration: trade.expiration, stop: null };
  const summary = { check_id: CHECK, received_at: received, ticker: "NVDA", side: "long", instrument: "option", option_type: "call",
    horizon: "intraday", verdict: "wait", model_verdict: "wait", total_ms: 640 };
  const detail = { schema_version: "check-owner-detail-v1", check_id: CHECK, received_at: received, record_sha256: "a".repeat(64), idea, free_text: null,
    answer: { verdict: "wait", rules_version: "pretrade-rules-v1", wait_for: null, reasons: [{ source: "live", text: "Conditional plan, not a Go." }],
      would_change: null, risk_check: { stop: null, note: "no stop given; none invented" },
      history: { as_of_ny: received.slice(0, 16), cohorts: [], trades_used: 0, available: true },
      live: { price: 901, vwap: 899, rvol: 1.2, market_state: "rth", setup_score: 3, trigger: null, invalidation: null, generated_at: received },
      option: null, caveats: [] },
    features: { state: "current", generated_at: received, age_seconds: 60 }, timings_ms: { total: 640 }, errors: [],
    model_verdict: { received_at: received, verdict: "wait", summary: "Conditional plan, not a Go." }, result: null };
  return { summary, detail };
}

async function connect(page: Page, trade: SeedTrade, detailStatus = 200) {
  const { summary, detail } = savedCheck(trade);
  await page.route("**/api/check-owner/checks", route => route.fulfill({ json: { schema_version: "check-owner-list-v1", checks: [summary], total: 1, limit: 50 } }));
  await page.route("**/api/check-owner/grades", route => route.fulfill({ status: 503, json: { detail: "unavailable" } }));
  await page.route(`**/api/check-owner/checks/${CHECK}`, route => detailStatus === 200 ? route.fulfill({ json: detail })
    : route.fulfill({ status: 503, json: { detail: "Saved pre-trade checks unavailable. The check owner reader may be stopped; nothing was sent to Jo." } }));
}

async function fitsPhone(page: Page, name: string) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
  await page.screenshot({ path: test.info().outputPath(`check-links-${name}-phone.png`), fullPage: true });
}

test.beforeEach(async ({ page }) => { await page.setViewportSize({ width: 390, height: 844 }); });

test("switched off: review and trade pages say saved advice isn't connected", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.goto("/advisor-review");
  await expect(page.getByRole("heading", { name: "Advisor review", exact: true })).toBeVisible();
  await expect(page.getByTestId("advisor-owner-review")).toHaveCount(0);
  await expect(page.getByText("Authenticated owner entrance required")).toHaveCount(0);
  await expect(page.getByTestId("pretrade-checks-dormant")).toContainText("Saved advice isn't connected to the journal yet");
  await fitsPhone(page, "off-review");
  await page.goto(`/trades/${(await nvda(page)).id}`);
  await expect(page.getByTestId("trade-advice")).toContainText("Saved advice isn't connected to the journal yet");
  await fitsPhone(page, "off-trade");
  expect(errors).toEqual([]);
});

test("private journal opens saved checks without requesting the isolated advisor trial", async ({ page }) => {
  const trialReads: string[] = [];
  page.on("request", request => { if (request.url().includes("/api/advisor-owner")) trialReads.push(request.url()); });
  await connect(page, await nvda(page));
  await page.goto("/");
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.getByRole("link", { name: "Advisor review", exact: true }).click();
  await expect(page.getByTestId("pretrade-check-row")).toHaveCount(1);
  await expect(page.getByTestId("advisor-owner-review")).toHaveCount(0);
  await page.getByTestId("pretrade-check-row").getByRole("button").click();
  await expect(page.getByTestId("pretrade-check-detail")).toBeVisible();
  await page.screenshot({ path: test.info().outputPath("advisor-review-private-desktop.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await fitsPhone(page, "private-review");
  expect(trialReads).toEqual([]);
});

test("possible later activity is labelled for review, then linked and unlinked by the owner", async ({ page }) => {
  const trade = await nvda(page);
  await connect(page, trade);
  await page.goto(`/advisor-review?check=${CHECK}`);
  const activity = page.getByTestId("check-activity");
  await expect(page.getByText("Loading saved checks…")).toHaveCount(0);
  await expect(activity).toContainText("Later activity — review needed");
  const possible = activity.getByTestId("check-possible");
  await expect(possible).toHaveCount(1);
  await expect(possible).toContainText("NVDA");
  await expect(possible).toContainText("P&L +$1300.00");  // The engine's realized P&L for the seeded trade.
  await expect(possible).not.toContainText(/followed|overrode|outdated/i);  // Only the disclaimer may use these words.
  await fitsPhone(page, "possible");

  await possible.getByRole("button", { name: "Link trade" }).click();
  await expect(activity.getByTestId("check-linked")).toHaveCount(1);
  await expect(activity).not.toContainText("Later activity — review needed");
  await fitsPhone(page, "linked");

  await page.goto(`/trades/${trade.id}`);
  const advice = page.getByTestId("trade-advice");
  await expect(advice).toContainText("Rules: Wait · Jo: Wait · NVDA long option");
  await expect(advice).toContainText("you linked this trade");
  await fitsPhone(page, "trade");
  await advice.getByRole("link").click();
  await expect(page.getByTestId("check-linked")).toHaveCount(1);

  await page.getByTestId("check-linked").getByRole("button", { name: "Unlink" }).click();
  await expect(page.getByTestId("check-possible")).toHaveCount(1);
  await expect(page.getByTestId("check-linked")).toHaveCount(0);
});

test("a check the reader can't return shows no journal activity", async ({ page }) => {
  await connect(page, await nvda(page), 503);
  await page.goto(`/advisor-review?check=${CHECK}`);
  await expect(page.getByTestId("pretrade-checks")).toContainText("Saved pre-trade checks unavailable");
  await expect(page.getByTestId("check-activity")).toHaveCount(0);
});

test("a linked check older than the list still opens, and a redacted one shows no matches", async ({ page }) => {
  const trade = await nvda(page);
  const { detail } = savedCheck(trade);
  await page.route("**/api/check-owner/checks", route => route.fulfill({ json: { schema_version: "check-owner-list-v1", checks: [], total: 60, limit: 50 } }));
  await page.route("**/api/check-owner/grades", route => route.fulfill({ status: 503, json: { detail: "unavailable" } }));
  await page.route(`**/api/check-owner/checks/${CHECK}`, route => route.fulfill({ json: { ...detail, idea: { ...detail.idea, ticker: null } } }));
  await page.goto(`/advisor-review?check=${CHECK}`);
  const opened = page.getByTestId("pretrade-check-linked");
  await expect(opened.getByTestId("pretrade-check-detail")).toBeVisible();
  await expect(opened.getByTestId("check-activity")).toContainText("This saved check has no ticker or time to match on");
  await expect(opened.getByTestId("check-possible")).toHaveCount(0);
  await fitsPhone(page, "redacted");
});
