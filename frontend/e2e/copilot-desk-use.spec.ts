import { expect, test, type Page } from "@playwright/test";

// How he uses the desk (docs/copilot-lab.md § How I use the desk): the desk counts quietly (piece ids, opens, taps, time on
// screen; no text, no tickers) and saves at most once every five minutes; after 14 days of use one quiet card offers to
// fold what he never opens; a folded tab waits in More, one tap shows it for now and a second keeps it showing; "How I
// use the desk" lists every piece least used first and says when counts could not be saved. Folds are per device size.
// Every route is stubbed with invented numbers, so nothing reaches the e2e backend.
const ON = {
  enabled: true, backend: "fake", evidence: "live", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
const NOW = new Date("2026-11-13T16:00:00Z"); // Friday 11:00 New York
const THREADS = {
  as_of: "2026-11-13T16:00:00Z", quotes_at: null, quote_issue: null, day: { phase: "regular", need_you: 0, streak: null },
  sections: { positions: "ok" }, plans: [], robinhood: { state: "off" }, threads: [],
};
const READS: Record<string, unknown> = {
  "/copilot/desk/threads": THREADS,
  "/copilot/desk/watching": { state: "ok", symbols: [], count: 0, max: 30, imported_at: null, robinhood: "off", levels: {}, setups: {} },
  "/copilot/desk/sparks": { as_of: "2026-11-13T16:00:00Z", spy_change_pct: 0.4, rows: {} },
  "/copilot/investigations": { investigations: [] },
  "/copilot/tickets": { plans: [] },
  "/copilot/exposure": { line: null },
};
type Summary = { days_with_use: number; pieces: Record<string, { opens: number; taps: number; seen_s: number; last_used: string | null }>;
  folds: { folded: string[]; snoozed_until: string | null } };
const summary = (s: Summary, size = "desk") => ({ size, today: "2026-11-13", window_days: 14, window_start: "2026-10-31", first_day: "2026-10-30", ...s });
// Fourteen days of use on a computer: Grid and the Tape were on screen but never opened; the Chain is used every day.
const FOURTEEN: Summary = {
  days_with_use: 14, folds: { folded: [], snoozed_until: null },
  pieces: {
    "tab.grid": { opens: 0, taps: 0, seen_s: 21_600, last_used: "2026-10-20" },
    "chart.tape": { opens: 0, taps: 1, seen_s: 18_000, last_used: null },
    "tab.chain": { opens: 31, taps: 40, seen_s: 9_000, last_used: "2026-11-13" },
    "paper": { opens: 0, taps: 12, seen_s: 30_000, last_used: "2026-11-12" },
  },
};

type Seen = { posts: { size: string; rows: Record<string, unknown>[] }[]; puts: Record<string, unknown>[]; gets: string[] };

async function open(page: Page, width: number, use: Summary, opts: { failSave?: boolean } = {}) {
  const seen: Seen = { posts: [], puts: [], gets: [] };
  await page.setViewportSize({ width, height: 900 });
  await page.clock.install({ time: NOW });
  await page.route("**/api/backend/**", route => route.fulfill({ status: 404, json: { detail: "Not in this test." } }));
  await page.route("**/copilot/status", route => route.fulfill({ json: ON }));
  await page.route("**/copilot/chat", route => route.abort());
  for (const [p, body] of Object.entries(READS)) await page.route(url => url.pathname.endsWith(p), route => route.fulfill({ json: body }));
  await page.route("**/copilot/desk/minute?*", route => {
    const reads = new URL(route.request().url()).searchParams.getAll("read").map(target => {
      const body = READS[target.split("?")[0]];
      return body ? { status: 200, body } : { status: 404, body: { detail: "Not in this test." } };
    });
    return route.fulfill({ json: { reads } });
  });
  let folds = { ...use.folds };
  await page.route(url => url.pathname.endsWith("/copilot/desk/use"), route => {
    const request = route.request();
    if (request.method() === "POST") {
      seen.posts.push(request.postDataJSON());
      return opts.failSave ? route.fulfill({ status: 500, json: { detail: "down" } }) : route.fulfill({ json: { saved: 1, skipped: 0 } });
    }
    const size = new URL(request.url()).searchParams.get("size") ?? "desk";
    seen.gets.push(size);
    return route.fulfill({ json: summary({ ...use, folds }, size) });
  });
  await page.route(url => url.pathname.endsWith("/copilot/desk/folds"), route => {
    const body = route.request().postDataJSON();
    seen.puts.push(body);
    folds = { folded: body.folded, snoozed_until: body.snoozed_until };
    return route.fulfill({ json: folds });
  });
  await page.goto("/copilot-lab");
  await expect(page.getByTestId("desk-book")).toBeVisible();
  return seen;
}
const PIECE_ID = /^[a-z][a-z0-9.-]{0,39}$/;

test("counts are piece ids only, and wait at least five minutes before one save", async ({ page }) => {
  const seen = await open(page, 1440, { days_with_use: 2, pieces: {}, folds: { folded: [], snoozed_until: null } });
  await page.getByRole("tab", { name: "Grid" }).click();
  await page.getByRole("tab", { name: "Chart" }).click();
  await page.clock.runFor(4 * 60_000);
  expect(seen.posts).toEqual([]); // nothing sent before five minutes
  await page.clock.runFor(75_000);
  await expect.poll(() => seen.posts.length).toBe(1);
  const [{ size, rows }] = seen.posts;
  expect(size).toBe("desk");
  for (const row of rows) {
    expect(Object.keys(row).sort()).toEqual(["day", "opens", "piece", "seen_s", "taps"]);
    expect(row.piece).toMatch(PIECE_ID);
    expect(row.day).toBe("2026-11-13");
  }
  const grid = rows.find(r => r.piece === "tab.grid")!;
  expect(grid).toMatchObject({ opens: 1, taps: 1 });
  expect(rows.find(r => r.piece === "tab.chart")?.seen_s).toBeGreaterThan(0); // its tab on screen, in 15-second buckets
  expect(JSON.stringify(rows)).not.toMatch(/NBIS|QQQ|SPY/); // never a ticker
  // Saved: the same open and tap are never sent twice.
  await page.clock.runFor(6 * 60_000);
  await expect.poll(() => seen.posts.length).toBe(2);
  expect(seen.posts[1].rows.find(r => r.piece === "tab.grid")).toMatchObject({ opens: 0, taps: 0 }); // only its new seconds on screen
});

test("after 14 days one card offers to fold what he never opens; folded tabs wait in More, one tap away", async ({ page }) => {
  const seen = await open(page, 1440, FOURTEEN);
  const card = page.getByTestId("fold-suggestion");
  await expect(card).toContainText("You haven't opened Grid or Tape in 2 weeks. Fold them?");
  await card.getByRole("button", { name: "Fold all" }).click();
  await expect.poll(() => seen.puts.at(-1)).toEqual({ size: "desk", folded: ["chart.tape", "tab.grid"], snoozed_until: null });
  await expect(card).toBeHidden();
  const centre = page.locator("#desk-centre");
  await expect(centre.getByRole("tab", { name: "Grid" })).toHaveCount(0);
  // The folded Tape waits in the chart header's More as a folded entry, one tap from showing; its switch is gone.
  await centre.getByTestId("desk-chart-more").click();
  await expect(centre.getByTestId("chart-more-folded-chart.tape")).toContainText("Tape (Level 2)folded");
  await expect(page.getByTestId("tape-toggle")).toHaveCount(0);
  await page.keyboard.press("Escape");
  // One tap shows it for now; the tab stays while he is on it.
  await centre.getByTestId("fold-more").first().click();
  await centre.getByRole("button", { name: "Grid tab" }).click();
  await expect(centre.getByRole("tab", { name: "Grid" })).toHaveAttribute("aria-selected", "true");
  expect(seen.puts).toHaveLength(1); // showing for now saves nothing
  // A second tap keeps it showing.
  await centre.getByTestId("fold-more").first().click();
  await centre.getByRole("button", { name: "Keep showing" }).first().click();
  await expect.poll(() => seen.puts.at(-1)).toEqual({ size: "desk", folded: ["chart.tape"], snoozed_until: null });
  // ⌘K still finds the folded Tape: it shows for now.
  await page.keyboard.press("Control+k");
  await page.keyboard.type("Tape");
  await page.keyboard.press("Enter");
  await centre.getByTestId("desk-chart-more").click();
  await expect(page.getByTestId("tape-toggle")).toBeVisible();
  await expect(centre.getByTestId("chart-more-folded-chart.tape")).toContainText("for now");
});

test("Not now snoozes the card for 14 days and folds nothing", async ({ page }) => {
  const seen = await open(page, 1440, FOURTEEN);
  await page.getByTestId("fold-suggestion").getByRole("button", { name: "Not now" }).click();
  await expect.poll(() => seen.puts.at(-1)).toEqual({ size: "desk", folded: [], snoozed_until: "2026-11-27" });
  await expect(page.getByTestId("fold-suggestion")).toBeHidden();
  await expect(page.locator("#desk-centre").getByRole("tab", { name: "Grid" })).toBeVisible();
});

test("How I use the desk lists every piece least used first, with its switch, and says when counts are paused", async ({ page }) => {
  const seen = await open(page, 1440, FOURTEEN, { failSave: true });
  await page.locator("#desk-centre").getByRole("tab", { name: "Chain" }).click();
  await page.keyboard.press("Control+k");
  await page.keyboard.type("How I use");
  await page.keyboard.press("Enter");
  const view = page.getByTestId("desk-use-view");
  await expect(view).toBeVisible();
  // Opening it tried to save first; the save failed, so it says so instead of showing zeros.
  await expect(view.getByTestId("desk-use-paused")).toContainText("Counts paused since");
  expect(seen.posts.length).toBe(1);
  await expect(view.getByTestId("desk-use-tab.chain")).toContainText("32 opens"); // 31 saved + 1 still on this device
  // Safety pieces are never foldable.
  await expect(view.getByTestId("desk-use-book")).toContainText("Always shown");
  await expect(view.getByTestId("desk-use-needs")).toContainText("Always shown");
  // Least used first: Grid (never opened) is above the Chain.
  const order = await view.locator("li[data-testid^='desk-use-']").evaluateAll(items => items.map(i => i.getAttribute("data-testid")));
  expect(order.indexOf("desk-use-tab.grid")).toBeLessThan(order.indexOf("desk-use-tab.chain"));
  await view.getByRole("group", { name: "Paper: fold or show" }).getByRole("button", { name: "Fold" }).click();
  await expect.poll(() => seen.puts.at(-1)).toEqual({ size: "desk", folded: ["paper"], snoozed_until: null });
  await page.keyboard.press("Escape");
});

test("a phone keeps its own folds: a folded section is a slim stub, one tap shows it", async ({ page }) => {
  const seen = await open(page, 390, { ...FOURTEEN, folds: { folded: ["paper", "watching"], snoozed_until: "2026-11-20" } });
  expect(seen.gets).toContain("phone");
  await expect(page.getByTestId("fold-suggestion")).toBeHidden(); // snoozed until Nov 20
  const stub = page.getByTestId("fold-stub-watching");
  await expect(stub).toBeVisible();
  await expect(stub).toContainText("Watching · folded");
  await stub.click();
  await expect(page.getByTestId("fold-now-watching")).toContainText("Folded · shown for now");
  await page.getByTestId("fold-now-watching").getByRole("button", { name: "Keep showing" }).click();
  await expect.poll(() => seen.puts.at(-1)).toEqual({ size: "phone", folded: ["paper"], snoozed_until: "2026-11-20" });
  expect(seen.gets).not.toContain("desk"); // a phone never reads the computer's folds first
});

test("More's link opens How I use the desk once the desk is on, and drops the word from the address", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.clock.install({ time: NOW });
  await page.route("**/api/backend/**", route => route.fulfill({ status: 404, json: { detail: "Not in this test." } }));
  // The lab's status answers late, so the link is read before the desk is on.
  await page.route("**/copilot/status", async route => { await new Promise(r => setTimeout(r, 800)); return route.fulfill({ json: ON }); });
  for (const [p, body] of Object.entries(READS)) await page.route(url => url.pathname.endsWith(p), route => route.fulfill({ json: body }));
  await page.route(url => url.pathname.endsWith("/copilot/desk/use"), route => route.fulfill({ json: summary(FOURTEEN) }));
  await page.goto("/copilot-lab?desk=use");
  await expect(page.getByTestId("desk-use-view")).toBeVisible();
  await expect(page).toHaveURL(/\/copilot-lab$/);
});

test("Day facts carries the at-risk line: never folded, even if a saved list names it", async ({ page }) => {
  await open(page, 1440, { ...FOURTEEN, pieces: { ...FOURTEEN.pieces, dayfacts: { opens: 0, taps: 0, seen_s: 9_000, last_used: null } },
    folds: { folded: ["dayfacts"], snoozed_until: null } });
  await expect(page.getByTestId("fold-stub-dayfacts")).toHaveCount(0);
  await expect(page.getByTestId("fold-suggestion")).not.toContainText("Day facts");
});
