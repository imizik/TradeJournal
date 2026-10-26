import { expect, test, type Page, type Route } from "@playwright/test";
import type { ChartData, Interval } from "../lib/charts";
import { realisticPanels } from "./fixtures/realisticBars";

// The copilot beside Charts, and the Copilot nav item. The lab routes are stubbed in the browser (the e2e backend
// keeps the lab off) and a turn is a fixed SSE stream, so no model runs.
const ON = {
  enabled: true, backend: "fake", evidence: "live", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
const MRVL = "55555555-5555-4555-8555-555555555555";
const NVDA = "66666666-6666-4666-8666-666666666666";
const ANSWER = "MRVL is leading its group on the 15-minute read.";
const turn = (text: string) => [
  { type: "text", delta: text },
  { type: "done", metrics: { backend: "fake", evidence: "live", model: "fake-scripted", first_text_ms: 1, total_ms: 2, rounds: 1, tool_calls: [],
    usage: { input_tokens: 0, output_tokens: 0, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 }, cost_usd: 0 } },
].map((event) => `event: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`).join("");
const record = (id: string, symbol: string, transcript: { role: string; content: string }[], revision = 1) => ({
  id, source: "copilot", title: transcript[0]?.content.split("\n")[0].slice(0, 80) ?? symbol, symbol, status: "open", conclusion: null, revision,
  message_count: transcript.length, has_findings: false, created_at: "2026-10-24T14:00:00Z", updated_at: "2026-10-24T14:05:00Z",
  transcript, evidence: [], findings: null,
});

type Lab = {
  saved: Map<string, ReturnType<typeof record>>; chats: { messages: { content: string }[]; symbol: string | null }[];
  /** Hold a symbol's investigation list, or the next turn, until the test releases it. */
  holdList?: { symbol: string; until: Promise<void> }; holdChat?: Promise<void>; posts?: { transcript: { role: string; content: string }[] }[];
};
const gate = () => { let open!: () => void; const until = new Promise<void>((resolve) => { open = resolve; }); return { until, open }; };

/** Candles for any symbol (the e2e backend has no Tradier key), so the chart draws beside the panel. */
async function stubCharts(page: Page) {
  await page.route("**/api/backend/charts/workspace?**", (route) => {
    const query = new URL(route.request().url()).searchParams;
    const symbol = query.get("symbol") ?? "MRVL";
    const now = Math.floor(Date.now() / 1000);
    const data: ChartData = { symbol, session: query.get("session") === "regular" ? "regular" : "extended", provider: "Tradier", delayed: false,
      refresh_seconds: 15, checked_at: now, fetched_at: { intraday: now }, panels: realisticPanels((query.get("intervals") ?? "5m").split(",") as Interval[]),
      quotes: [], issues: [], adjustment: { basis: "split_adjusted", status: "ok", source: "alpaca_corporate_actions", as_of: now, splits: [], daily: {},
        dividends: "unsupported", dividends_note: "Dividends are not adjusted.", warnings: [] },
      intraday_as_of: now - 60, history_note: "Synthetic chart data.", fills: [], fills_truncated: false, extras: {} } as ChartData;
    return route.fulfill({ json: data });
  });
}

async function stubLab(page: Page, lab: Lab, enabled = true) {
  await stubCharts(page);
  await page.route("**/copilot/status", (route) => route.fulfill({ json: enabled ? ON : { enabled: false, reason: "Copilot Lab is off." } }));
  await page.route("**/copilot/investigations?*", async (route) => {
    const symbol = new URL(route.request().url()).searchParams.get("symbol");
    if (lab.holdList && symbol === lab.holdList.symbol) await lab.holdList.until;
    return route.fulfill({ json: { investigations: [...lab.saved.values()].filter((r) => !symbol || r.symbol === symbol) } }).catch(() => undefined);
  });
  const save = (route: Route, id: string) => {
    const body = route.request().postDataJSON();
    (lab.posts ??= []).push(body);
    const saved = record(id, body.symbol, body.transcript, (lab.saved.get(id)?.revision ?? 0) + 1);
    lab.saved.set(id, saved);
    return route.fulfill({ status: route.request().method() === "POST" ? 201 : 200, json: saved });
  };
  await page.route("**/copilot/investigations", (route) => save(route, MRVL));
  await page.route("**/copilot/investigations/*", (route) => {
    const id = new URL(route.request().url()).pathname.split("/").at(-1)!;
    return route.request().method() === "PUT" ? save(route, id) : route.fulfill({ json: lab.saved.get(id) });
  });
  await page.route("**/copilot/chat", async (route) => {
    lab.chats.push(route.request().postDataJSON());
    if (lab.holdChat) await lab.holdChat;
    return route.fulfill({ status: 200, headers: { "content-type": "text/event-stream" }, body: turn(ANSWER) }).catch(() => undefined);
  });
  await page.route("**/charts/alerts", (route) => route.fulfill({ json: { alerts: [], phone: true } }));
  await page.route("**/copilot/research-jobs?*", (route) => route.fulfill({ json: { jobs: [], queue_enabled: false, daily_budget_usd: 2, spent_today_usd: 0 } }));
}

const openPanel = async (page: Page) => {
  await page.getByRole("button", { name: "Copilot", exact: true }).click();
  const panel = page.getByTestId("copilot-panel");
  await expect(panel).toBeVisible();
  return panel;
};

const chartSymbol = async (page: Page, symbol: string) => {
  await page.getByLabel("Chart symbol").fill(symbol);
  await page.getByRole("button", { name: "Load symbol" }).click();
};

test("the Charts copilot opens on the chart's symbol, saves a turn, and the lab reopens it", async ({ page }) => {
  const lab: Lab = { saved: new Map(), chats: [] };
  await stubLab(page, lab);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/charts?symbol=MRVL");
  await expect(page.getByTestId("canvas-main").locator("canvas").first()).toBeVisible();
  const panel = await openPanel(page);
  await expect(panel.getByRole("heading", { name: "Copilot · MRVL" })).toBeVisible();
  const message = panel.getByLabel("Message");
  await expect(message).toHaveValue(/^Context: Charts · MRVL \S+ chart\n\n$/); // the page's context, waiting for a question
  // The chart stays in view beside it, narrower rather than covered.
  const chart = (await page.getByTestId("canvas-main").boundingBox())!;
  const side = (await panel.boundingBox())!;
  expect(chart.width).toBeGreaterThan(400);
  expect(chart.x + chart.width).toBeLessThanOrEqual(side.x + 1);
  await message.fill(`${await message.inputValue()}Is MRVL leading its group?`);
  await panel.getByRole("button", { name: "Send" }).click();
  await expect(panel.getByText(ANSWER)).toBeVisible();
  await expect(panel.getByText("Saved", { exact: true })).toBeVisible();
  expect(lab.chats).toHaveLength(1);
  expect(lab.chats[0].symbol).toBe("MRVL");
  expect(lab.chats[0].messages[0].content).toMatch(/^Context: Charts · MRVL \S+ chart\n\nIs MRVL leading its group\?$/);
  await page.screenshot({ path: test.info().outputPath("charts-copilot-desktop.png") });
  await panel.getByRole("link", { name: "Open in lab" }).click();
  await expect(page).toHaveURL(new RegExp(`/copilot-lab\\?investigation=${MRVL}`));
  await expect(page.getByText(ANSWER)).toBeVisible();
  await expect(page.getByLabel("Investigation symbol")).toHaveValue("MRVL");
});

test("a symbol switch is offered, never forced, once a conversation exists; an empty panel just follows", async ({ page }) => {
  const lab: Lab = { saved: new Map(), chats: [] };
  lab.saved.set(NVDA, record(NVDA, "NVDA", [{ role: "user", content: "Is NVDA extended?" }, { role: "assistant", content: "Yes, well above VWAP." }]));
  await stubLab(page, lab);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/charts?symbol=MRVL");
  const panel = await openPanel(page);
  await expect(panel.getByRole("heading", { name: "Copilot · MRVL" })).toBeVisible();
  // Nothing said yet: the panel follows the chart, resuming NVDA's open investigation.
  await chartSymbol(page, "NVDA");
  await expect(panel.getByRole("heading", { name: "Copilot · NVDA" })).toBeVisible();
  await expect(panel.getByText("Yes, well above VWAP.")).toBeVisible();
  await expect(panel.getByRole("status", { name: "Symbol changed" })).toHaveCount(0);
  // With a conversation open, a change is offered, never forced: keeping it keeps asking about NVDA.
  await chartSymbol(page, "MRVL");
  const offer = panel.getByRole("status", { name: "Symbol changed" });
  await expect(offer).toContainText("The page is now on MRVL; this conversation is about NVDA.");
  await expect(panel.getByRole("heading", { name: "Copilot · NVDA" })).toBeVisible(); // not retargeted
  await offer.getByRole("button", { name: "Keep NVDA" }).click();
  await expect(offer).toHaveCount(0);
  await panel.getByLabel("Message").fill("Still extended?");
  await panel.getByRole("button", { name: "Send" }).click();
  await expect(panel.getByText(ANSWER)).toBeVisible();
  expect(lab.chats.map((chat) => chat.symbol)).toEqual(["NVDA"]);
  // A later change offers again; switching starts AMD's own conversation with the chart's context line.
  await chartSymbol(page, "AMD");
  await panel.getByRole("status", { name: "Symbol changed" }).getByRole("button", { name: "Switch to AMD" }).click();
  await expect(panel.getByRole("heading", { name: "Copilot · AMD" })).toBeVisible();
  await expect(panel.getByLabel("Message")).toHaveValue(/^Context: Charts · AMD \S+ chart/);
  expect(lab.chats).toHaveLength(1); // switching sends nothing
});

test("the Copilot nav item shows only while the lab is on", async ({ page }) => {
  const lab: Lab = { saved: new Map(), chats: [] };
  const painted = () => page.evaluate(() => new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done))));
  await stubLab(page, lab, false);
  await page.setViewportSize({ width: 1440, height: 900 });
  let answered = page.waitForResponse((response) => response.url().includes("/copilot/status"));
  await page.goto("/radar");
  await answered;
  await painted();
  await expect(page.getByRole("link", { name: "Radar", exact: true }).first()).toBeVisible();
  await page.getByRole("button", { name: "Labs" }).click(); // the group is folded by default; opened, it still has no Copilot
  await expect(page.getByRole("link", { name: "Strategy Lab", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Copilot", exact: true })).toHaveCount(0);
  await page.unrouteAll({ behavior: "ignoreErrors" });
  await stubLab(page, lab, true);
  answered = page.waitForResponse((response) => response.url().includes("/copilot/status"));
  await page.reload();
  await answered;
  await expect(page.getByRole("link", { name: "Copilot", exact: true }).first()).toHaveAttribute("href", "/copilot-lab"); // Labs stays open on this device
});

test("on a 375 px phone the Charts copilot is the dock's sheet and nothing scrolls sideways", async ({ page }) => {
  const lab: Lab = { saved: new Map(), chats: [] };
  await stubLab(page, lab);
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/charts?symbol=MRVL");
  await expect(page.getByTestId("canvas-main").locator("canvas").first()).toBeVisible();
  const panel = await openPanel(page);
  await expect(page.getByRole("dialog", { name: "Copilot" })).toBeVisible();
  await expect(panel.getByRole("heading", { name: "Copilot · MRVL" })).toBeVisible();
  const send = panel.getByRole("button", { name: "Send" });
  await send.scrollIntoViewIfNeeded();
  await expect(send).toBeInViewport();
  expect((await send.boundingBox())!.height).toBeGreaterThanOrEqual(44);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
  await page.screenshot({ path: test.info().outputPath("charts-copilot-375.png") });
});

test("a follow that answers after the owner has sent is dropped: the turn and a typed draft are kept", async ({ page }) => {
  const lab: Lab = { saved: new Map(), chats: [] };
  lab.saved.set(NVDA, record(NVDA, "NVDA", [{ role: "user", content: "Is NVDA extended?" }, { role: "assistant", content: "Yes, well above VWAP." }]));
  const held = gate();
  lab.holdList = { symbol: "NVDA", until: held.until };
  await stubLab(page, lab);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/charts?symbol=MRVL");
  const panel = await openPanel(page);
  await expect(panel.getByRole("heading", { name: "Copilot · MRVL" })).toBeVisible();
  await chartSymbol(page, "NVDA"); // the empty panel starts to follow NVDA; its read is held
  await panel.getByLabel("Message").fill("Is MRVL leading?");
  await panel.getByRole("button", { name: "Send" }).click();
  await expect(panel.getByText(ANSWER)).toBeVisible();
  held.open(); // NVDA's investigation arrives after the turn
  await expect(panel.getByRole("status", { name: "Symbol changed" })).toContainText("this conversation is about MRVL");
  await expect(panel.getByRole("heading", { name: "Copilot · MRVL" })).toBeVisible();
  await expect(panel.getByText(ANSWER)).toBeVisible();
  await expect(panel.getByText("Yes, well above VWAP.")).toHaveCount(0);
  expect(lab.chats.map((chat) => chat.symbol)).toEqual(["MRVL"]);
});

test("following to a new symbol keeps a draft the owner typed", async ({ page }) => {
  const lab: Lab = { saved: new Map(), chats: [] };
  await stubLab(page, lab);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/charts?symbol=MRVL");
  const panel = await openPanel(page);
  await panel.getByLabel("Message").fill("My own question");
  await chartSymbol(page, "AMD");
  await expect(panel.getByRole("heading", { name: "Copilot · AMD" })).toBeVisible();
  await expect(panel.getByLabel("Message")).toHaveValue("My own question");
});

test("closing the panel mid-turn stops the turn and saves what was asked", async ({ page }) => {
  const lab: Lab = { saved: new Map(), chats: [] };
  const held = gate();
  lab.holdChat = held.until;
  await stubLab(page, lab);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/charts?symbol=MRVL");
  const panel = await openPanel(page);
  const aborted = page.waitForEvent("requestfailed", (request) => request.url().includes("/copilot/chat"));
  await panel.getByLabel("Message").fill("Is MRVL leading?");
  await panel.getByRole("button", { name: "Send" }).click();
  await expect(panel.getByRole("button", { name: "Stop" })).toBeVisible(); // mid-turn
  await page.getByRole("button", { name: "Copilot", exact: true }).click(); // close the dock tab
  await expect(page.getByTestId("copilot-panel")).toHaveCount(0);
  await aborted; // the turn stopped
  await expect.poll(() => lab.posts?.length ?? 0).toBe(1);
  expect(lab.posts![0].transcript[0]).toEqual({ role: "user", content: "Is MRVL leading?" });
  held.open();
  // Reopening resumes that saved investigation.
  const again = await openPanel(page);
  await expect(again.getByText("Is MRVL leading?")).toBeVisible();
});

test("Switch waits for a turn in progress", async ({ page }) => {
  const lab: Lab = { saved: new Map(), chats: [] };
  await stubLab(page, lab);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/charts?symbol=MRVL");
  const panel = await openPanel(page);
  await panel.getByLabel("Message").fill("Is MRVL leading?");
  await panel.getByRole("button", { name: "Send" }).click();
  await expect(panel.getByText(ANSWER)).toBeVisible();
  const held = gate();
  lab.holdChat = held.until;
  await panel.getByLabel("Message").fill("And the group?");
  await panel.getByRole("button", { name: "Send" }).click();
  await expect(panel.getByRole("button", { name: "Stop" })).toBeVisible();
  await chartSymbol(page, "NVDA");
  const offer = panel.getByRole("status", { name: "Symbol changed" });
  await expect(offer.getByRole("button", { name: "Switch to NVDA" })).toBeDisabled();
  await expect(offer).toContainText("after this answer");
  held.open();
  await expect(offer.getByRole("button", { name: "Switch to NVDA" })).toBeEnabled();
  await expect(panel.getByRole("heading", { name: "Copilot · MRVL" })).toBeVisible();
});
