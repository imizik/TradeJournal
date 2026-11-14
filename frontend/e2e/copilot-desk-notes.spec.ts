import { expect, test, type Page, type Request } from "@playwright/test";

// Notes on the book (docs/copilot-lab.md § Notes on a trade): a small Note control on a position row and on a fresh
// fill in the Orders group opens one text line in place; Enter saves it with the trade, Esc cancels, the desk's keys
// do nothing while typing, and saved notes show as grey lines with their time, newest last. Every lab route is stubbed in
// the browser (the e2e backend runs with the lab off). Invented numbers.
const ON = {
  enabled: true, backend: "fake", evidence: "live", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
const NOW = new Date("2026-10-23T15:00:00Z"); // 11:00 New York
const at = (iso: string) => Date.parse(iso) / 1000;
const TRADE = "55555555-5555-4555-8555-555555555555";
const CLOSED = "66666666-6666-4666-8666-666666666666";
const ROTH = { label: "Roth IRA", masked: "••8267" };
const row = (fields: Record<string, unknown>) => ({
  symbol: null, instrument: null, value: null, meter: null, investigation_id: null, trade_id: null, radar_event_id: null, path: null,
  changed_at: null, ...fields,
});
const order = (fields: Record<string, unknown>) => ({
  contract: "MU 11/13/26 835C", symbol: "MU", instrument: "option", action: "Sell to close", working: false, quantity: 2, filled: 2,
  price_kind: "limit", limit: 1.95, avg: 1.93, placed_at: at("2026-10-23T14:35:00Z"), filled_at: at("2026-10-23T14:36:00Z"),
  account: ROTH, pairing: "matched", ...fields,
});
const NBIS = row({
  key: `trade:${TRADE}`, group: "watch", symbol: "NBIS", title: "NBIS 10/30/26 100C", instrument: "10/30/26 100C", trade_id: TRADE,
  value: { text: "+$220.00", tone: "gain" }, status: { text: "Invalidation 92.30 (NBIS) · 1.8% away", tone: "muted" },
  book: { usd: 220, pct: 35.5, expiry: "2026-10-30", days_held: 1, track: { last: 40, entry: 80, tone: "muted" }, state: "on_plan",
    planned: true, stop_pct: -1.8, quantity: 2, mark: 420, account: ROTH, live: "matched" },
});
const ORDERS = [
  order({}), // MU: the fill that closed the position; the journal has its trade
  order({ contract: "APLD 11/27/26 30P", symbol: "APLD", action: "Buy to open", working: true, filled: 0, avg: null, filled_at: null }),
  order({ contract: "IREN 11/20/26 60C", symbol: "IREN", action: "Buy to open", pairing: "provisional" }), // not in the journal yet
];
const LIVE = { state: "ok", joined: true, as_of: at("2026-10-23T14:59:00Z"), issue: null, orders: ORDERS,
  accounts: [{ ...ROTH, total_value: 9860.12, cash: 1200.5, buying_power: 1150 }] };
const DESK = {
  as_of: "2026-10-23T15:00:00Z", quotes_at: null, quote_issue: null, day: { phase: "regular", need_you: 0, streak: null },
  sections: { positions: "ok" }, plans: [], robinhood: LIVE,
  threads: [row({ key: "briefing", group: "pinned", title: "Briefing", status: { text: "Nothing new.", tone: "muted" } }), NBIS],
};
const NOTES = {
  trades: { [TRADE]: [{ id: "n1", text: "Why I'm in: base held at 92", at: at("2026-10-22T14:10:00Z") }] },
  fills: { "MU|MU 11/13/26 835C": CLOSED, "IREN|IREN 11/20/26 60C": null },
};

async function open(page: Page) {
  const posts: Request[] = [];
  await page.clock.install({ time: NOW });
  await page.route("**/copilot/status", route => route.fulfill({ json: ON }));
  await page.route("**/copilot/desk/threads", route => route.fulfill({ json: DESK }));
  await page.route("**/copilot/investigations?*", route => route.fulfill({ json: { investigations: [] } }));
  await page.route("**/copilot/desk/notes*", async route => {
    if (route.request().method() === "GET") return route.fulfill({ json: NOTES });
    posts.push(route.request());
    const body = route.request().postDataJSON();
    return route.fulfill({ json: { trade_id: body.trade_id, note: { id: `n${posts.length + 1}`, text: body.text.trim(), at: at("2026-10-23T14:58:00Z") } } });
  });
  await page.goto("/copilot-lab");
  await expect(page.getByTestId("desk-book")).toBeVisible();
  return posts;
}

for (const width of [1440, 375]) {
  test(`a note on a position and on a closing fill at ${width}px: Enter saves, Esc cancels`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const posts = await open(page);
    const shelf = page.getByTestId("desk-book");
    // The saved note is one grey line under its row, with its day and time (an earlier day).
    const saved = shelf.getByTestId("desk-notes").first().getByTestId("desk-note");
    await expect(saved).toHaveCount(1);
    await expect(saved).toContainText("10/22 10:10");
    await expect(saved).toContainText("Why I'm in: base held at 92");
    // Esc closes the line without saving.
    await shelf.getByRole("button", { name: "Note on NBIS 10/30/26 100C" }).click();
    const input = shelf.getByTestId("desk-note-input");
    await input.fill("never mind");
    await input.press("Escape");
    await expect(input).toHaveCount(0);
    expect(posts).toHaveLength(0);
    // Typing "j" and "k" types: the desk's keys do not fire in the line. Enter saves; the note stacks, newest last.
    await shelf.getByRole("button", { name: "Note on NBIS 10/30/26 100C" }).click();
    await shelf.getByTestId("desk-note-input").pressSequentially("Trim jk at 4.40");
    await expect(shelf.getByTestId("desk-note-input")).toHaveValue("Trim jk at 4.40");
    await shelf.getByTestId("desk-note-input").press("Enter");
    await expect(shelf.getByTestId("desk-note-input")).toHaveCount(0);
    expect(posts[0].postDataJSON()).toEqual({ trade_id: TRADE, text: "Trim jk at 4.40" });
    const lines = shelf.getByTestId("desk-notes").first().getByTestId("desk-note");
    await expect(lines).toHaveCount(2);
    await expect(lines.nth(1)).toContainText("10:58");
    await expect(lines.nth(1)).toContainText("Trim jk at 4.40");
    // The Orders group: the closing fill takes a note on its trade; a working order and a fill not in the journal take none.
    const group = shelf.getByTestId("book-orders");
    await expect(group.getByTestId("desk-note-button")).toHaveCount(1);
    await group.getByRole("button", { name: "Note on MU 11/13/26 835C fill" }).click();
    await group.getByTestId("desk-note-input").fill("Why I left: lost VWAP");
    await group.getByTestId("desk-note-input").press("Enter");
    expect(posts[1].postDataJSON()).toEqual({ trade_id: CLOSED, text: "Why I left: lost VWAP" });
    await expect(group.getByTestId("desk-note")).toContainText("Why I left: lost VWAP");
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    await shelf.screenshot({ path: test.info().outputPath(`desk-notes-${width}.png`) });
  });
}

test("a failed save keeps the words and says why", async ({ page }) => {
  await open(page);
  await page.route("**/copilot/desk/notes", route => route.request().method() === "POST"
    ? route.fulfill({ status: 422, json: { detail: "Write a note of 1 to 300 characters." } }) : route.fallback());
  const shelf = page.getByTestId("desk-book");
  await shelf.getByRole("button", { name: "Note on NBIS 10/30/26 100C" }).click();
  await shelf.getByTestId("desk-note-input").fill("x");
  await shelf.getByTestId("desk-note-input").press("Enter");
  await expect(shelf.getByRole("alert")).toHaveText("Write a note of 1 to 300 characters.");
  await expect(shelf.getByTestId("desk-note-input")).toHaveValue("x");
});
