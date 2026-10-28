import { expect, test, type Page } from "@playwright/test";

// The desk's Context pane: Chart (default), Timeline and Your history for the open thread. Every lab route is stubbed
// in the browser, so no model runs and nothing reaches the e2e backend; the pane only reads.
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

type Desk = { picture?: "ok" | string; timeline?: object; history?: object };

async function lab(page: Page, desk: Desk = {}) {
  const reads: string[] = [];
  await page.route("**/copilot/status", (route) => route.fulfill({ json: ON }));
  await page.route("**/copilot/investigations?*", (route) => route.fulfill({ json: { investigations: [] } }));
  await page.route(`**/copilot/investigations/${INV}`, (route) => route.fulfill({ json: record }));
  await page.route("**/copilot/chat", (route) => route.abort());
  await page.route(`**/copilot/desk/${INV}/*`, (route) => {
    const part = new URL(route.request().url()).pathname.split("/").pop()!;
    reads.push(`${route.request().method()} ${part}`);
    if (part === "picture") {
      const picture = desk.picture ?? "ok";
      return picture === "ok" ? route.fulfill({ status: 200, contentType: "image/png", body: PNG })
        : route.fulfill({ status: 404, json: { detail: picture } });
    }
    return route.fulfill({ json: part === "timeline" ? desk.timeline ?? TIMELINE : desk.history ?? HISTORY });
  });
  await page.goto(`/copilot-lab?investigation=${INV}`);
  await expect(page.getByText("It held the open; the group leads.")).toBeVisible();
  return { reads, pane: page.getByRole("complementary", { name: "Context" }) };
}

test("the Context pane opens on today's chart, and Timeline and Your history read only when asked", async ({ page }) => {
  const { reads, pane } = await lab(page);
  await expect(pane).toContainText("NBIS");
  await expect(pane).toContainText("today");
  await expect(pane.getByRole("link", { name: "Open in Charts →" })).toHaveAttribute("href", "/charts?symbol=NBIS");
  const tabs = pane.getByRole("tablist", { name: "Context" });
  await expect(tabs.getByRole("tab", { name: "Chart" })).toHaveAttribute("aria-selected", "true");
  await expect(pane.getByRole("img", { name: /NBIS today: minute bars/ })).toBeVisible();
  await page.waitForTimeout(200);
  expect(reads).toEqual(["GET picture"]); // the other tabs wait

  await tabs.getByRole("tab", { name: "Timeline" }).click();
  const timeline = pane.getByRole("list", { name: "Timeline" });
  await expect(timeline.getByRole("listitem")).toHaveCount(4);
  await expect(timeline.getByRole("listitem").first()).toContainText("Decision: Decision");
  await expect(timeline.getByRole("listitem").first()).toContainText("Holding: the group is still bid.");
  await expect(timeline.getByRole("listitem").nth(1)).toContainText("Ping held back · give-back");
  // Today's rows by the New York clock, an earlier one by its day.
  await expect(timeline.getByRole("listitem").first().locator("time")).toHaveText(/^\d{2}:\d{2}$/);
  await expect(timeline.getByRole("listitem").last().locator("time")).toHaveText(/^[A-Z][a-z]{2} \d{1,2}$/);

  await tabs.getByRole("tab", { name: "Your history" }).click();
  await expect(pane.getByRole("img", { name: "3 won, 9 did not" })).toBeVisible();
  await expect(pane).toContainText(HISTORY.sentence);
  await expect(pane).toContainText("At 92.3, 3.8% below the planned entry 95.9, over the last 180 days. Evidence to weigh, not a rule.");
  expect(reads).toEqual(["GET picture", "GET timeline", "GET history"]); // reads only, nothing posted
  await pane.screenshot({ path: test.info().outputPath("desk-context-history.png") });
});

test("each tab says what is unavailable or missing", async ({ page }) => {
  const { pane } = await lab(page, {
    picture: "No NBIS minute bars for today yet.",
    timeline: { state: "ok", symbol: "NBIS", rows: [], count: 0, unavailable: ["pings"], recent_days: 7 },
    history: { state: "missing", symbol: "NBIS", reason: "No plan invalidation yet. Once you confirm a plan card, your record at its invalidation shows here." },
  });
  const tabs = pane.getByRole("tablist", { name: "Context" });
  await expect(pane).toContainText("Chart unavailable: No NBIS minute bars for today yet.");
  await expect(pane.getByRole("img")).toHaveCount(0);
  await tabs.getByRole("tab", { name: "Timeline" }).click();
  await expect(pane).toContainText("Nothing has touched this thread in the last 7 days.");
  await expect(pane).toContainText("Could not read: pings.");
  await tabs.getByRole("tab", { name: "Your history" }).click();
  await expect(pane).toContainText("No plan invalidation yet. Once you confirm a plan card, your record at its invalidation shows here.");
});

test("on a 375 px phone the Context tab shows the pane, and its tabs fit", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  const { pane } = await lab(page);
  await page.getByRole("tablist", { name: "Desk" }).getByRole("tab", { name: "Context" }).click();
  await expect(pane.getByRole("img", { name: /NBIS today: minute bars/ })).toBeVisible();
  const tabs = pane.getByRole("tablist", { name: "Context" });
  await tabs.getByRole("tab", { name: "Timeline" }).click();
  await expect(pane.getByRole("list", { name: "Timeline" }).getByRole("listitem")).toHaveCount(4);
  expect((await tabs.getByRole("tab", { name: "Timeline" }).boundingBox())!.height).toBeGreaterThanOrEqual(36);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
  await page.screenshot({ path: test.info().outputPath("desk-context-375.png"), fullPage: true });
});
