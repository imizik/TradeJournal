import { expect, test, type Page } from "@playwright/test";

// Headlines on the desk chart (docs/copilot-lab.md § The desk): a marker at each group's candle, amber beside a big
// move, hover or tap opens the headlines with their source, time and link, Ask hands one with its move to the copilot,
// and the News toggle in the studies row hides them and is remembered. The lab's routes are stubbed in the browser;
// every headline and link is invented and no model runs.
const ON = {
  enabled: true, backend: "fake", evidence: "fixture", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
const now = Math.floor(Date.now() / 1000);
const STEP = 120;
const last = now - (now % STEP);
const bars = Array.from({ length: 60 }, (_, i) => {
  const open = i === 40 ? 94.6 : 94 + Math.sin(i / 5) * 0.2;
  const close = i === 40 ? 97.2 : open + 0.05;
  return { time: last - (59 - i) * STEP, open, high: Math.max(open, close) + 0.1, low: Math.min(open, close) - 0.1, close, volume: 1000, extended: false };
});

function chartRead(timeframe: string) {
  return {
    symbol: "NBIS", timeframe, step: STEP, as_of: now, live: false, state: "ok", reason: null, bars, studies: {}, reference: [],
    reading: { last: bars[59].close, at: bars[59].time + 60, daily: false, prev_close: 93.1, vwap: null, vwap_at: null, rvol: null },
    levels: [], alerts: [], marks: [], time_stop: null,
  };
}

const item = (at: number, headline: string, url: string, session = "regular") =>
  ({ at, before: false, session, headline, source: "benzinga", url });
const NEWS = {
  symbol: "NBIS", timeframe: "2m", as_of: now, state: "ok", reason: null, source: "Benzinga via Alpaca",
  groups: [
    { time: bars[10].time, count: 1, emphasis: false, move: null, items: [item(bars[10].time + 30, "Invented: analyst note on data-centre capacity", "https://example.com/one")] },
    { time: bars[40].time, count: 2, emphasis: true,
      move: { start: bars[38].time, end: bars[40].time + STEP, pct: 2.75, range_pct: 3.0 },
      items: [item(bars[40].time + 40, "Invented: wins a large GPU cloud contract", "https://example.com/two"),
        item(bars[40].time + 10, "Invented: shares halted briefly", "https://example.com/three")] },
  ],
};

async function desk(page: Page) {
  const reads: string[] = [];
  await page.route("**/copilot/status", (route) => route.fulfill({ json: ON }));
  await page.route("**/copilot/investigations?*", (route) => route.fulfill({ json: { investigations: [] } }));
  await page.route("**/copilot/chat", (route) => route.abort());
  await page.route("**/copilot/desk/read", (route) => route.fulfill({ json: { state: "hidden" } }));
  await page.route(/\/copilot\/desk\/symbol(:|%3A)NBIS\//, (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/chart")) return route.fulfill({ json: chartRead(url.searchParams.get("timeframe") ?? "2m") });
    if (url.pathname.endsWith("/news")) {
      reads.push(url.searchParams.get("timeframe") ?? "");
      return route.fulfill({ json: NEWS });
    }
    return route.fulfill({ json: { state: "ok", symbol: "NBIS", count: 0, unavailable: [], recent_days: 7, rows: [] } });
  });
  await page.route("**/charts/alerts**", (route) => route.fulfill({ json: { alerts: [], phone: true } }));
  await page.goto("/copilot-lab?symbol=NBIS");
  const pane = page.getByRole("region", { name: "Chart and tools" });
  await expect(pane.getByTestId("desk-chart-canvas")).toHaveAttribute("data-bars", "60");
  return { pane, reads };
}

test("a headline marker opens its headlines, and Ask hands the headline and the move to the copilot", async ({ page }) => {
  const { pane, reads } = await desk(page);
  const canvas = pane.getByTestId("desk-chart-canvas");
  await expect(canvas).toHaveAttribute("data-news", "2");
  expect(reads).toContain("2m");
  const marks = pane.getByTestId("desk-news-mark");
  await expect(marks).toHaveCount(2);
  await expect(marks.nth(0)).toHaveAttribute("data-emphasis", "false");
  await expect(marks.nth(1)).toHaveAttribute("data-emphasis", "true");
  await expect(marks.nth(1)).toHaveText("2");
  await expect(pane.getByTestId("desk-study-news")).toHaveText("News 3");

  // Hover: the headlines, newest first, with source, time and a link out.
  await marks.nth(1).hover();
  const tip = pane.getByTestId("desk-news-tip");
  await expect(tip).toBeVisible();
  await expect(tip).toContainText(/^Moved \+2\.8% .*–.* ET \(range 3\.0%\)/);
  await expect(tip.getByTestId("desk-news-item")).toHaveCount(2);
  await expect(tip.getByRole("link").first()).toHaveText("Invented: wins a large GPU cloud contract");
  await expect(tip.getByRole("link").first()).toHaveAttribute("href", "https://example.com/two");
  await expect(tip.getByRole("link").first()).toHaveAttribute("target", "_blank");
  // A headline from an earlier New York day carries its date ("Nov 13 11:22 PM ET"): the bars run off the real clock,
  // so just after midnight ET the headlines fall on yesterday.
  await expect(tip.getByTestId("desk-news-item").first()).toContainText(/benzinga\s?· (?:[A-Z][a-z]{2} \d{1,2} )?\d{1,2}:\d{2} [AP]M ET/);
  await pane.screenshot({ path: test.info().outputPath("desk-news-tip.png") });

  // Leaving it closes it; a tap pins it open, and the pointer may move into it.
  await page.mouse.move(5, 5);
  await expect(tip).toBeHidden();
  await marks.nth(1).click();
  await expect(tip).toBeVisible();
  await page.mouse.move(5, 5);
  await page.waitForTimeout(400);
  await expect(tip).toBeVisible();

  // Ask: the copilot is about NBIS with the headline quoted and the move beside it; nothing is sent.
  await tip.getByTestId("desk-news-ask").first().click();
  await expect(tip).toBeHidden();
  const message = page.getByRole("textbox", { name: "Message" });
  await expect(message).toHaveValue(new RegExp(
    '^Context: NBIS headline \\(benzinga, (?:[A-Z][a-z]{2} \\d{1,2} )?\\d{1,2}:\\d{2} [AP]M ET\\): "Invented: wins a large GPU cloud contract"\\. ' +
    "NBIS moved \\+2\\.8% .*–.* ET on the 2m chart, well beyond its typical candle\\. " +
    "Did this headline move it, and does it touch my positions or plans\\?"));
  await expect(page).toHaveURL(/\/copilot-lab\?symbol=NBIS&context=NBIS\+headline/);
});

test("the News toggle hides the markers and is remembered; the 1D chart asks for none", async ({ page }) => {
  const { pane, reads } = await desk(page);
  const canvas = pane.getByTestId("desk-chart-canvas");
  const toggle = pane.getByTestId("desk-study-news");
  await expect(canvas).toHaveAttribute("data-news", "2");
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-pressed", "false");
  await expect(pane.getByTestId("desk-news-mark")).toHaveCount(0);
  await expect(canvas).toHaveAttribute("data-news", "off");
  await page.reload();
  await expect(canvas).toHaveAttribute("data-bars", "60");
  await expect(pane.getByTestId("desk-study-news")).toHaveAttribute("aria-pressed", "false");
  await expect(pane.getByTestId("desk-news-mark")).toHaveCount(0);
  await pane.getByTestId("desk-study-news").click();
  await expect(pane.getByTestId("desk-news-mark")).toHaveCount(2);

  const count = reads.length;
  await pane.getByRole("button", { name: "1D", exact: true }).click();
  await expect(canvas).toHaveAttribute("data-timeframe", "1D");
  await expect(pane.getByTestId("desk-study-news")).toHaveCount(0);
  await expect(pane.getByTestId("desk-news-mark")).toHaveCount(0);
  expect(reads.length).toBe(count);
});
