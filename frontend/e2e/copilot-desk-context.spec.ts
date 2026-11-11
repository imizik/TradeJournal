import { expect, test, type Page } from "@playwright/test";

// The cockpit's centre: the Chart of the open thread's ticker (or the market), its timeframes, and its Timeline folded
// under it; and This week, folded at the foot of the thread list's drawer. Every lab route is stubbed in the browser, so
// no model runs and nothing reaches the e2e backend; the centre only reads.
const ON = {
  enabled: true, backend: "fake", evidence: "fixture", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
const INV = "33333333-3333-4333-8333-333333333333";
const record = {
  id: INV, source: "copilot", title: "Is the NBIS reclaim real?", symbol: "NBIS", status: "open", conclusion: null, revision: 1,
  message_count: 2, has_findings: false, created_at: "2026-10-27T14:00:00Z", updated_at: "2026-10-27T14:00:00Z",
  transcript: [{ role: "user", content: "Is the NBIS reclaim real?" }, { role: "assistant", content: "It held the open; the group leads." }],
  evidence: [], findings: null,
};
// A 2x1 PNG: the picture itself is the server's (tests/test_copilot_desk_context.py); here only that it shows.
const PNG = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAIAAAABCAIAAAB7QOjdAAAADUlEQVR4nGMQEpUBIgAByACHeNSWqgAAAABJRU5ErkJggg==", "base64");
const now = Math.floor(Date.now() / 1000);
// Monday October 26, 2026 09:45 and Tuesday 10:31 in New York (EDT, UTC-4).
const MON_0945 = Date.UTC(2026, 9, 26, 13, 45) / 1000;
const TUE_1031 = Date.UTC(2026, 9, 27, 14, 31) / 1000;
const TIMELINE = {
  state: "ok", symbol: "NBIS", count: 4, unavailable: [], recent_days: 7, rows: [
    { kind: "decision", at: now - 60, text: "Decision", detail: "Holding: the group is still bid." },
    { kind: "ping", at: now - 600, text: "Ping held back · give-back", detail: "NBIS 100C gave back half" },
    { kind: "alert", at: now - 3600, text: "Entry hit", detail: "at 95.92 · pinged" },
    { kind: "thesis", at: now - 3 * 86400, text: "News · thesis watch", detail: "NBIS signs a data-centre lease" },
  ],
};
const HISTORY = {
  state: "ok", symbol: "NBIS", level: 92.3, side: "below", entry: 95.9, entry_from: "planned", distance_pct: -3.75, trades: 31, crossed: 12,
  won: 3, not_won: 9, recovered: 5, median_from_cross_pct: -18, small: false, window_days: 180, simulated: false,
  sentence: "12 of 31 past NBIS calls crossed a level 3.8% below entry while held: 3 won, 9 did not. 5 recovered to breakeven; median -18% from the cross.",
  note: "Evidence to weigh, not a rule.",
};

// The proof reads as the backend writes them; the pane shows their labels and samples, never recomputes them.
const EXIT_HABITS = { go_live: "2026-10-21", window: 20, since_go_live: 12, recent_trades: 12, baseline_trades: 40, habits: [], alerts: [],
  alerts_total: 14, responses: {}, feedback: { total: 14, responded: 9, unanswered: 5, counts: {} },
  verdict: { verdict: "not_helping", reason: "Give-back rate went up.", rule: "Each habit's rate falls.", sample: 12 } };
const RADAR_PROOF = { state: "ok", reason: null, rule_version: "rv1", sessions: 4, events: 30,
  setups: [{ kind: "dip_turn", direction: "up", cards: 6, with_contract: 5, planned: 2, paper_closed: 4, paper_green: 3, paper_pnl: 210, unresolved: 1 },
    { kind: "gap_reversal", direction: "down", cards: 1, with_contract: 1, planned: 0, paper_closed: 0, paper_green: 0, paper_pnl: 0, unresolved: 0 }],
  verdict: { verdict: "not_enough_data", reason: "Needs 20 rated.", rule: "60% useful and ahead.", rated: 6, timed: 4, useful_share: 0.5, ahead_share: null } };

type Desk = { picture?: "ok" | string; timeline?: object; history?: object };

async function lab(page: Page, desk: Desk = {}) {
  const reads: string[] = [];
  const timeframes: (string | null)[] = [];
  await page.route("**/copilot/status", (route) => route.fulfill({ json: ON }));
  await page.route("**/copilot/investigations?*", (route) => route.fulfill({ json: { investigations: [] } }));
  await page.route(`**/copilot/investigations/${INV}`, (route) => route.fulfill({ json: record }));
  await page.route("**/copilot/chat", (route) => route.abort());
  await page.route(`**/copilot/desk/${INV}/*`, (route) => {
    const part = new URL(route.request().url()).pathname.split("/").pop()!;
    reads.push(`${route.request().method()} ${part}`);
    if (part === "picture") {
      timeframes.push(new URL(route.request().url()).searchParams.get("timeframe"));
      const picture = desk.picture ?? "ok";
      return picture === "ok" ? route.fulfill({ status: 200, contentType: "image/png", body: PNG })
        : route.fulfill({ status: 404, json: { detail: picture } });
    }
    return route.fulfill({ json: part === "timeline" ? desk.timeline ?? TIMELINE : desk.history ?? HISTORY });
  });
  await page.goto(`/copilot-lab?investigation=${INV}`);
  await expect(page.getByText("It held the open; the group leads.")).toBeVisible();
  return { reads, timeframes, pane: page.getByRole("region", { name: "Chart and feed" }) };
}

test("the centre opens on the open thread's chart beside the conversation, and its Timeline reads only when unfolded", async ({ page }) => {
  const { reads, pane } = await lab(page);
  await expect(page.getByRole("region", { name: "Conversation" }).getByText("It held the open; the group leads.")).toBeVisible();
  await expect(pane.getByRole("tab", { name: "Chart" })).toHaveAttribute("aria-selected", "true");
  await expect(pane.getByRole("tab")).toHaveText(["Chart", "Feed"]); // no tab for what does not exist yet
  await expect(pane.getByTestId("desk-chart")).toContainText("NBIS");
  await expect(pane.getByRole("link", { name: "Open in Charts →" })).toHaveAttribute("href", "/charts?symbol=NBIS");
  await expect(pane.getByRole("img", { name: /NBIS today: minute bars/ })).toBeVisible();
  await page.waitForTimeout(200);
  expect(reads).toEqual(["GET picture"]); // the timeline waits

  await pane.getByRole("button", { name: "Timeline ▾" }).click();
  const timeline = pane.getByRole("list", { name: "Timeline" });
  await expect(timeline.getByRole("listitem")).toHaveCount(4);
  await expect(timeline.getByRole("listitem").first()).toContainText("Decision: Decision");
  await expect(timeline.getByRole("listitem").first()).toContainText("Holding: the group is still bid.");
  await expect(timeline.getByRole("listitem").nth(1)).toContainText("Ping held back · give-back");
  // Today's rows by the New York clock, an earlier one by its day.
  await expect(timeline.getByRole("listitem").first().locator("time")).toHaveText(/^\d{2}:\d{2}$/);
  await expect(timeline.getByRole("listitem").last().locator("time")).toHaveText(/^[A-Z][a-z]{2} \d{1,2}$/);
  expect(reads).toEqual(["GET picture", "GET timeline"]); // reads only, nothing posted
  await pane.screenshot({ path: test.info().outputPath("desk-centre-timeline.png") });
});

test("the chart's timeframe buttons switch the picture read, and the legend names fills, pings and Radar", async ({ page }) => {
  const { reads, timeframes, pane } = await lab(page);
  const group = pane.getByRole("group", { name: "Timeframe" });
  await expect(group.getByRole("button", { name: "2m" })).toHaveAttribute("aria-pressed", "true");
  await expect(pane.getByRole("img", { name: /NBIS today: minute bars with .*pings and Radar hits/ })).toBeVisible();
  const legend = pane.getByLabel("Legend");
  await expect(legend).toContainText("your fills");
  await expect(legend).toContainText("pings");
  await expect(legend).toContainText("Radar");

  await group.getByRole("button", { name: "15m" }).click();
  await expect(group.getByRole("button", { name: "15m" })).toHaveAttribute("aria-pressed", "true");
  await expect(pane.getByRole("img", { name: /NBIS recent sessions: 15-minute bars/ })).toBeVisible();
  await group.getByRole("button", { name: "1D" }).click();
  await expect(pane.getByRole("img", { name: "NBIS the last few months: daily bars" })).toBeVisible();
  await expect(legend).toContainText("marked on 2m and 15m");
  expect(timeframes).toEqual(["2m", "15m", "1D"]);
  expect(reads).toEqual(["GET picture", "GET picture", "GET picture"]); // reads only
});

test("the chart and the timeline each say what is unavailable or missing", async ({ page }) => {
  const { pane } = await lab(page, {
    picture: "No NBIS minute bars for today yet.",
    timeline: { state: "ok", symbol: "NBIS", rows: [], count: 0, unavailable: ["pings"], recent_days: 7 },
  });
  await expect(pane).toContainText("Chart unavailable: No NBIS minute bars for today yet.");
  await expect(pane.getByRole("img")).toHaveCount(0);
  await pane.getByRole("button", { name: "Timeline ▾" }).click();
  await expect(pane).toContainText("Nothing has touched this thread in the last 7 days.");
  await expect(pane).toContainText("Could not read: pings.");
});

test("on a 375 px phone the centre sits under the book and the copilot is a sheet over it", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  const { pane } = await lab(page); // a thread's link opens on the copilot's sheet
  await page.getByRole("button", { name: "Back to the desk" }).click();
  await expect(pane.getByRole("img", { name: /NBIS today: minute bars/ })).toBeVisible();
  await pane.getByRole("button", { name: "Timeline ▾" }).click();
  await expect(pane.getByRole("list", { name: "Timeline" }).getByRole("listitem")).toHaveCount(4);
  expect((await pane.getByRole("tab", { name: "Feed" }).boundingBox())!.height).toBeGreaterThanOrEqual(44);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
  await page.screenshot({ path: test.info().outputPath("desk-centre-375.png"), fullPage: true });
});

test("a symbol opened with no saved conversation charts it by the symbol", async ({ page }) => {
  const reads: string[] = [];
  await page.route("**/copilot/status", (route) => route.fulfill({ json: ON }));
  await page.route("**/copilot/investigations?*", (route) => route.fulfill({ json: { investigations: [] } }));
  await page.route("**/copilot/chat", (route) => route.abort());
  await page.route(/\/copilot\/desk\/symbol(:|%3A)NBIS\//, (route) => {
    const part = new URL(route.request().url()).pathname.split("/").pop()!;
    reads.push(`${route.request().method()} ${part}`);
    if (part === "picture") return route.fulfill({ status: 200, contentType: "image/png", body: PNG });
    return route.fulfill({ json: { ...TIMELINE, count: 1, rows: [{ kind: "fill", at: now - 900, text: "Bought 5 NBIS stock at 94.20", detail: "the open position" }] } });
  });
  await page.goto("/copilot-lab?symbol=NBIS");
  const pane = page.getByRole("region", { name: "Chart and feed" });
  await expect(pane.getByRole("img", { name: /NBIS today: minute bars/ })).toBeVisible();
  await expect(pane.getByRole("link", { name: "Open in Charts →" })).toHaveAttribute("href", "/charts?symbol=NBIS");
  await pane.getByRole("button", { name: "Timeline ▾" }).click();
  await expect(pane.getByRole("list", { name: "Timeline" }).getByRole("listitem")).toHaveText([/Bought 5 NBIS stock at 94.20.*the open position/]);
  expect(reads).toEqual(["GET picture", "GET timeline"]); // reads only, nothing posted
});

test("with no ticker the centre charts the market, and This week sits folded at the foot of the thread list", async ({ page }) => {
  const reads: string[] = [];
  await page.route("**/copilot/status", (route) => route.fulfill({ json: ON }));
  await page.route("**/copilot/investigations?*", (route) => route.fulfill({ json: { investigations: [] } }));
  await page.route("**/copilot/chat", (route) => route.abort());
  await page.route("**/copilot/desk/market/picture", (route) => { reads.push("market"); return route.fulfill({ status: 200, contentType: "image/png", body: PNG }); });
  await page.route("**/copilot/desk/session", (route) => route.fulfill({ json: {
    as_of: new Date(now * 1000).toISOString(), now, day: "2026-10-28", phase: "regular", open: now - 3600, close: now + 7200,
    events: [
      { kind: "fill", at: now - 3000, symbol: "NBIS", text: "Bought NBIS" },
      { kind: "ping", at: now - 1200, symbol: "NBIS", text: "Give-back ping · NBIS" },
    ],
    time_stops: [{ symbol: "CRWV", at: now + 1800, clock: "14:30" }], pings: { sent: 1, held: 0, cap: 12 },
    prep: { at: now - 7200, line: "Two positions, one draft." }, indices: [], quote_issue: null,
    sections: { fills: "ok", pings: "unavailable", radar: "off" },
  } }));
  await page.route("**/charts/captures/streak", (route) => route.fulfill({ json: {
    show: true, since: now - 86400 * 30, tracking: true, current: 6, best: 9, pending: 0,
    this_week: { planned: 3, total: 4, pending: 0, start: now - 86400 * 2, entries: [
      { trade_id: "trade-1", contract: "NBIS 11/20/26 100C", short: "NBIS 100C", entry_time: MON_0945, state: "planned", capture_id: "plan-1" },
      { trade_id: "trade-2", contract: "CRWV 11/20/26 90C", short: "CRWV 90C", entry_time: MON_0945 + 3600, state: "unplanned" },
      { trade_id: "trade-3", contract: "NBIS 11/20/26 105C", short: "NBIS 105C", entry_time: TUE_1031, state: "planned", capture_id: "plan-3" },
      { trade_id: "trade-4", contract: "IREN 11/20/26 40C", short: "IREN 40C", entry_time: TUE_1031 + 600, state: "planned", capture_id: "plan-4" },
    ] }, last_break: null,
  } }));
  await page.route("**/analytics/exit-habits", (route) => route.fulfill({ json: EXIT_HABITS }));
  await page.route("**/radar/proof", (route) => route.fulfill({ json: RADAR_PROOF }));
  await page.route("**/copilot/answer-scorecard*", (route) => route.fulfill({ json: {
    state: "ok", window: { days: 7, since: "2026-10-19T00:00", until: "2026-10-26T15:00" },
    turns: { total: 23, by_kind: { ask: 20, plan: 3 }, by_source: { desk: 23 } },
    answers: { total: 23, rated: 9, helped: 7, didnt: 2, helped_rate: 0.778, pushback: 2, pushback_rate: 0.087, follow_ups: 5, follow_up_rate: 0.217, failed: 1 },
    by_kind: {}, latency: { ask: { turns: 19, first_text_ms: { p50: 4100, p90: 9800 }, total_ms: { p50: 6000, p90: 12000 }, max_silence_ms_p50: 3900 } },
    failed: { timeout: 1 }, cost: { total_usd: 0.38, per_turn_usd: 0.0165, top_threads: [], cache: { read_tokens: 0, input_tokens: 0, read_share: null } } } }));
  await page.route("**/copilot/brief-scorecard*", (route) => route.fulfill({ json: {
    state: "ok", days: 7, briefs: 4, named: 23, moved: 7, unknown: 2, as_of: "2026-11-06T15:00:00-05:00", rows: [
      { day: "2026-11-06", named: 5, moved: 1, unknown: 0, state: "in_progress" },
      { day: "2026-11-05", named: 6, moved: 2, unknown: 0, state: "ok" },
      { day: "2026-11-04", named: 7, moved: 3, unknown: 2, state: "ok" },
      { day: "2026-11-03", named: 5, moved: 1, unknown: 0, state: "ok" },
    ] } }));
  await page.goto("/copilot-lab?view=briefing");
  const centre = page.getByRole("region", { name: "Chart and feed" });
  await expect(centre.getByRole("img", { name: /QQQ today: minute bars with your fills/ })).toBeVisible();
  await expect(centre.getByRole("link", { name: "Open in Charts →" })).toHaveAttribute("href", "/charts?symbol=QQQ");
  await expect(centre).toContainText("your fills");
  expect(reads).toEqual(["market"]);

  await page.getByRole("button", { name: /^Threads(?:,|$)/ }).click();
  const pane = page.getByRole("complementary", { name: "Threads" });
  await pane.getByTestId("this-week").locator("summary").click();
  // The two proofs first, as /proof reads them, each with what it rests on.
  const proof = pane.getByRole("region", { name: "Proof this week" });
  await expect(pane.getByTestId("week-copilot-line")).toHaveText("Copilot: Helped 7 of 9 rated · 23 answers · first text 4.1 s median · $0.38");
  await expect(pane.getByTestId("week-copilot-detail")).toHaveText("Pushed back on 2 · 5 follow-ups · 1 failed");
  await expect(pane.getByTestId("week-brief-line")).toHaveText("Morning brief: named 23 symbols over 4 briefs · 7 moved 3+ pts vs SPY by the close · 2 without bars");
  await expect(pane.getByTestId("week-brief-row")).toHaveText(["Fri Nov 6: 5 named, 1 moved (in progress)", "Thu Nov 5: 6 named, 2 moved",
    "Wed Nov 4: 7 named, 3 moved, 2 without bars", "Tue Nov 3: 5 named, 1 moved"]);
  await expect(proof.getByTestId("week-proof-alerts")).toHaveText("Alerts: No consistent decrease · based on 9 of 14 alerts answered");
  await expect(proof.getByTestId("week-proof-radar")).toHaveText("Radar: Not enough data · 6 hits rated");
  await expect(proof.getByTestId("week-proof-setup-line")).toHaveText(["Dip turning up: 6 cards · 2 planned · paper 3 of 4 green, +$210",
    "Gap up turning down: 1 card · 0 planned · no paper result yet"]);
  await expect(proof.getByRole("link", { name: "Open Proof →" })).toHaveAttribute("href", "/proof");
  const tiles = pane.getByRole("list", { name: "This week's entries" }).getByRole("link");
  await expect(tiles).toHaveText(["+", "−", "+", "+"]);
  await expect(tiles.nth(2)).toHaveAttribute("title", "NBIS 105C · Tue 10:31 · planned");
  await expect(tiles.nth(1)).toHaveAttribute("title", "CRWV 90C · Mon 10:45 · no plan");
  await expect(tiles.nth(2)).toHaveAttribute("href", "/trades/trade-3");
  await expect(pane).toContainText("3 of 4 entries this week were planned before entry.");
  await expect(pane).toContainText("Plan streak 6, best 9. One more planned entry makes 7 in a row.");
  await pane.screenshot({ path: test.info().outputPath("desk-context-week.png") });
});

test("this week's proof lines say when a proof read is missing or fails", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.route("**/copilot/status", (route) => route.fulfill({ json: ON }));
  await page.route("**/copilot/investigations?*", (route) => route.fulfill({ json: { investigations: [] } }));
  await page.route("**/copilot/chat", (route) => route.abort());
  await page.route("**/charts/captures/streak", (route) => route.fulfill({ json: { show: false } }));
  await page.route("**/analytics/exit-habits", (route) => route.fulfill({ status: 500, json: { detail: "boom" } }));
  await page.route("**/radar/proof", (route) => route.fulfill({ json: { state: "off", reason: "Radar is not recording.", setups: [] } }));
  await page.route("**/copilot/answer-scorecard*", (route) => route.fulfill({ status: 500, json: { detail: "boom" } }));
  await page.route("**/copilot/brief-scorecard*", (route) => route.fulfill({ status: 500, json: { detail: "boom" } }));
  await page.goto("/copilot-lab?view=briefing");
  await page.getByRole("button", { name: /^Threads(?:,|$)/ }).click();
  const pane = page.getByRole("complementary", { name: "Threads" });
  await pane.getByTestId("this-week").locator("summary").click();
  const proof = pane.getByRole("region", { name: "Proof this week" });
  await expect(pane.getByTestId("week-copilot-line")).toHaveText("Copilot: could not load");
  await expect(pane.getByTestId("week-brief-line")).toHaveText("Morning brief: could not load");
  await expect(proof.getByTestId("week-proof-alerts")).toHaveText("Alerts: could not load");
  await expect(proof.getByTestId("week-proof-radar")).toHaveText("Radar: Not enough data · Radar is not recording.");
  await expect(proof.getByTestId("week-proof-setups")).toHaveText("Setup cards:No setup cards yet."); // an empty scorecard says so
  await expect(pane).toContainText("No entries are tracked yet.");  // the week's record still shows below
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
});

test("this week says so quietly when no morning brief was written", async ({ page }) => {
  await page.route("**/copilot/status", (route) => route.fulfill({ json: ON }));
  await page.route("**/copilot/investigations?*", (route) => route.fulfill({ json: { investigations: [] } }));
  await page.route("**/copilot/chat", (route) => route.abort());
  await page.route("**/charts/captures/streak", (route) => route.fulfill({ json: { show: false } }));
  await page.route("**/analytics/exit-habits", (route) => route.fulfill({ json: EXIT_HABITS }));
  await page.route("**/radar/proof", (route) => route.fulfill({ json: RADAR_PROOF }));
  await page.route("**/copilot/answer-scorecard*", (route) => route.fulfill({ status: 500, json: { detail: "boom" } }));
  await page.route("**/copilot/brief-scorecard*", (route) => route.fulfill({ json: {
    state: "ok", days: 7, briefs: 0, named: 0, moved: 0, unknown: 0, rows: [], as_of: "2026-11-06T15:00:00-05:00" } }));
  await page.goto("/copilot-lab?view=briefing");
  await page.getByRole("button", { name: /^Threads(?:,|$)/ }).click();
  const pane = page.getByRole("complementary", { name: "Threads" });
  await pane.getByTestId("this-week").locator("summary").click();
  await expect(pane).toContainText("No morning brief in the last 7 days.");
  await expect(pane.getByTestId("week-brief")).toHaveCount(0);
});
