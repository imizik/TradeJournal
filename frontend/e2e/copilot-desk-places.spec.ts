import { expect, test, type Page } from "@playwright/test";
import { DESK_PLACES } from "../lib/deskPlaces";

// Every place on the desk, named once (lib/deskPlaces.ts; docs/copilot-lab.md § Keys and the palette, § Desk actions):
// ⌘K lists each as a command, a short phrase typed there ("nvda chain", "rules") is a "Go to" option on top that goes
// straight there with no model call, and the copilot's show card moves the desk to a place at once, with Undo. Every
// route is stubbed with invented numbers, so nothing reaches the e2e backend, a model, Robinhood or an order.
const ON = {
  enabled: true, backend: "fake", evidence: "live", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
const NOW = new Date("2026-11-13T16:00:00Z"); // Friday 11:00 New York, in the session
const epoch = (iso: string) => Date.parse(iso) / 1000;
const MAIN = "77777777-7777-4777-8777-777777777777";
const g = (pnl: number, trades: number, win: number | null) => ({ trades, pnl, win_rate: win });
const stats = (pnl: number, trades: number, win: number | null) => ({ ...g(pnl, trades, win), avg_win: null, avg_loss: null, largest_loss: null, curve: [] });
const BOOK = {
  run: { id: "r1", number: 1, starting_cash: 10000, started_at: epoch("2026-11-10T15:00:00Z") },
  account: { cash: 10000, collateral: 0, reserved: 0, buying_power: 10000, equity: 10000, pnl: 0, unpriced: 0, prices_at: null },
  positions: [], closed: [], orders: [],
  score: { paper: { ...stats(0, 0, null), open_pnl: null, by_source: [], rules: null }, real: stats(0, 0, null), real_rules: null },
  my_rules: [{ id: "r_stop000001", text: "Stop before I enter", check: { kind: "stop_set" } }],
  earlier: [], market_open: true, review: null, goals: null,
};
const row = (symbol: string, title: string) => ({ key: `watch:${symbol}`, group: "watch", title, status: { text: "Watching", tone: "muted" }, symbol,
  instrument: null, value: null, meter: null, investigation_id: null, trade_id: null, radar_event_id: null, path: null, changed_at: null });
const THREADS = { as_of: "2026-11-13T16:00:00Z", quotes_at: null, quote_issue: null, day: { phase: "regular", need_you: 0, streak: null },
  sections: { positions: "ok" }, plans: [], robinhood: { state: "off" }, threads: [row("NVDA", "NVDA base"), row("AAPL", "AAPL earnings run")] };
const SESSION = { as_of: "2026-11-13T16:00:00Z", now: epoch("2026-11-13T16:00:00Z"), day: "2026-11-13", phase: "regular",
  open: epoch("2026-11-13T14:30:00Z"), close: epoch("2026-11-13T21:00:00Z"), events: [], time_stops: [], pings: null, prep: null,
  indices: [], quote_issue: null, realized_today: 0, sections: {}, to_answer: { alerts: { count: 0, rows: [] }, radar: null } };
const READS: Record<string, unknown> = {
  "/copilot/desk/threads": THREADS,
  "/copilot/desk/session": SESSION,
  "/copilot/desk/watching": { state: "ok", symbols: [], count: 0, max: 30, imported_at: null, robinhood: "off", levels: {}, setups: {} },
  "/copilot/desk/sparks": { as_of: "2026-11-13T16:00:00Z", spy_change_pct: 0.4, rows: {} },
  "/copilot/investigations": { investigations: [] },
  "/copilot/tickets": { plans: [] },
  "/copilot/paper": BOOK,
};
const main = (transcript: unknown[] = []) => ({ id: MAIN, source: "copilot", title: "Main chat", symbol: null, status: "open", conclusion: null,
  revision: 1 + transcript.length, message_count: transcript.length, has_findings: false, created_at: "2026-11-13T14:00:00Z",
  updated_at: "2026-11-13T15:00:00Z", evidence: [], findings: null, transcript, main_day: "2026-11-13" });
const sse = (cards: Record<string, unknown>[]) => [
  ...cards.map(c => ({ type: "tool", id: c.id, name: "desk_action", status: "ok", summary: "desk action",
    provenance: { source: "A desk action for the owner to tap; nothing done", kind: "proposal", as_of: null } })),
  ...cards, { type: "text", delta: "My rules is on the desk now (Undo is on the card)." },
  { type: "done", metrics: { backend: "fake", evidence: "live", model: "fake-scripted", first_text_ms: 1, total_ms: 2, rounds: 2, tool_calls: [],
    usage: { input_tokens: 0, output_tokens: 0, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 }, cost_usd: 0 } },
].map(e => `data: ${JSON.stringify(e)}\n\n`).join("");

async function open(page: Page, cards: Record<string, unknown>[] = []) {
  const seen = { chats: 0, chains: [] as string[], writes: [] as string[] };
  let current = main();
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.clock.install({ time: NOW });
  await page.route("**/api/backend/**", route => {
    const method = route.request().method();
    if (method !== "GET") seen.writes.push(`${method} ${new URL(route.request().url()).pathname}`);
    return route.fulfill({ status: 404, json: { detail: "Not in this test." } });
  });
  await page.route("**/copilot/status", route => route.fulfill({ json: ON }));
  const found = (url: string) => Object.keys(READS).find(p => new URL(url).pathname.endsWith(p));
  await page.route(url => !!found(url.toString()), route => route.fulfill({ json: READS[found(route.request().url())!] }));
  await page.route("**/copilot/desk/minute?*", route => route.fulfill({ json: { reads: new URL(route.request().url()).searchParams.getAll("read").map(target => {
    const body = READS[target.split("?")[0]];
    return body ? { status: 200, body } : { status: 404, body: { detail: "Not in this test." } };
  }) } }));
  await page.route("**/copilot/chain?*", route => { seen.chains.push(new URL(route.request().url()).search); return route.fulfill({ status: 503, json: { detail: "No chain in this test." } }); });
  await page.route("**/copilot/main-chat", route => route.fulfill({ json: current }));
  await page.route("**/copilot/main-chat/history*", route => route.fulfill({ json: { conversations: [] } }));
  await page.route(`**/copilot/investigations/${MAIN}`, route => route.fulfill({ json: current }));
  await page.route(`**/copilot/main-chat/${MAIN}/exchange`, async route => {
    current = main([...current.transcript, ...route.request().postDataJSON().transcript]);
    await route.fulfill({ json: current });
  });
  await page.route(`**/copilot/investigations/${MAIN}/proposals/*/outcome`, route => route.fulfill({ json: current }));
  await page.route("**/copilot/chat", route => { seen.chats += 1; return route.fulfill({ status: 200, headers: { "content-type": "text/event-stream" }, body: sse(cards) }); });
  await page.goto(`/copilot-lab?thread=${MAIN}`);
  await expect(page.getByTestId("desk-book")).toBeVisible();
  return seen;
}

const jump = async (page: Page, text: string) => {
  await page.keyboard.press("ControlOrMeta+k");
  const dialog = page.getByRole("dialog", { name: "Jump to" });
  await dialog.getByRole("combobox", { name: "Jump to" }).fill(text);
  return dialog;
};

test("every place on the desk's one list is a ⌘K command", async ({ page }) => {
  await open(page);
  await page.keyboard.press("ControlOrMeta+k");
  const options = page.getByRole("dialog", { name: "Jump to" }).getByRole("option");
  // The Day checklist's command is named for the time of day (mid-session: "Day checklist").
  for (const place of DESK_PLACES) await expect(options.filter({ hasText: new RegExp(`^${place.label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`) })).not.toHaveCount(0);
});

test("\"nvda chain\" in ⌘K goes straight to NVDA's chain with no model call; an unknown ticker gets no Go to", async ({ page }) => {
  const seen = await open(page);
  let dialog = await jump(page, "zzzz chain");
  await expect(dialog.getByTestId("palette-go")).toHaveCount(0);
  await page.keyboard.press("Escape");
  dialog = await jump(page, "nvda chain");
  await expect(dialog.getByTestId("palette-go")).toHaveText(/^Go to NVDA · Chain/);
  await expect(dialog.getByRole("option").first()).toHaveAttribute("data-testid", "palette-go");
  await page.keyboard.press("Enter");
  await expect(dialog).not.toBeVisible();
  await expect(page.getByRole("tab", { name: "Chain" })).toHaveAttribute("aria-selected", "true");
  await expect.poll(() => seen.chains.at(-1) ?? "").toContain("symbol=NVDA");
  // The other order says the same.
  await jump(page, "chart aapl");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("desk-dock")).toBeVisible(); // the chart on top with its dock, not the Grid
  await expect(page.getByTestId("desk-chart")).toContainText("AAPL");
  expect(seen.chats).toBe(0);
  expect(seen.writes).toEqual([]);
});

test("\"rules\" in ⌘K opens My rules and its editor", async ({ page }) => {
  const seen = await open(page);
  const dialog = await jump(page, "rules");
  await expect(dialog.getByTestId("palette-go")).toHaveText(/^My rules/); // a place on its own: its own command, on top
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("rules-goals-toggle")).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByTestId("rules-goals").getByTestId("rules-editor")).toBeVisible();
  expect(seen.chats).toBe(0);
});

test("the copilot's show card with place=rules opens My rules at once, saving nothing, and Undo puts the desk back", async ({ page }) => {
  const card = { type: "proposal", id: "a_rules", kind: "desk_action", action: "show", symbol: null, timeframe: null, place: "rules",
    made_at: Date.parse("2026-11-13T15:59:00Z") / 1000 };
  const seen = await open(page, [card]);
  await expect(page.getByTestId("rules-goals-toggle")).toHaveAttribute("aria-expanded", "false");
  await page.getByLabel("Message").fill("Open my rules");
  await page.getByLabel("Message").press("Enter");
  const shown = page.getByTestId("desk-action").and(page.locator('[data-action="show"]'));
  await expect(shown).toContainText("Show My rules");
  await expect(shown).toContainText("Moved the desk: My rules");
  await expect(page.getByTestId("rules-goals").getByTestId("rules-editor")).toBeVisible();
  await shown.getByRole("button", { name: "Undo" }).click();
  await expect(shown).toContainText("Undone: the desk is back as it was.");
  await expect(page.getByTestId("rules-goals-toggle")).toHaveAttribute("aria-expanded", "false");
  await expect(page.getByTestId("rules-goals").getByTestId("rules-editor")).toHaveCount(0);
  expect(seen.writes.filter(w => !w.includes("/proposals/") && !w.includes("/exchange") && !w.includes("/desk/use"))).toEqual([]);
});
