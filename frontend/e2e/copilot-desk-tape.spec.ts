import { expect, test, type Page, type Route } from "@playwright/test";

// The desk's Tape (docs/copilot-lab.md § The desk): the chart header's Tape button opens the selected ticker's Level 2
// and time & sales from the same manual depth session Charts uses. Closed by default and remembered; opening starts the
// stream, closing stops it; a print is green or red only when the ARCA book of the same moment says it was at the ask or
// bid; big prints are bold; another session holding the bridge is named, not fought; indexes start nothing; a phone
// shows the spread and a short tape only. The lab's routes and the depth session are stubbed; every number is invented.
const ON = {
  enabled: true, backend: "fake", evidence: "fixture", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
const RX = 1_763_049_600_000; // the bridge's receive clock for the invented session

const level = (price: number, volume: number) => ({ price, volume, order_count: null, mpid: "ARCA" });
const BOOK = { event: "book", symbol: "US.NBIS", received_ms: RX, books: [{
  exchange: "ARCA", source_time_ms: RX - 20, estimated_age_ms: 20, order_volume_precision: 0,
  bids: [level(94.1, 400), level(94.09, 900), level(94.08, 1200), level(94.07, 300), level(94.06, 700), level(94.05, 100)],
  asks: [level(94.12, 300), level(94.13, 500), level(94.14, 2500), level(94.15, 800), level(94.16, 200)],
}] };
const print = (i: number, price: number, volume: number, at = RX + 100) => ({ price, volume, time_ms: at - 5, sequence: i, received_ms: at });
// One at the bid price that arrived before the book (no colour: the later book is not its moment), 24 small prints
// between the quotes, then one at the ask, one at the bid, one big one at the ask, and one that came long after the book
// (no colour: no book of its moment).
const PRINTS = [
  print(28, 94.1, 100, RX - 100),
  ...Array.from({ length: 24 }, (_, i) => print(i, 94.11, 100)),
  print(24, 94.12, 200), print(25, 94.1, 300), print(26, 94.12, 5000), print(27, 94.2, 100, RX + 5_000),
];
const STREAM = [
  { event: "status", phase: "subscribed", kind: "order_book" },
  BOOK,
  { event: "trades", symbol: "US.NBIS", trades: PRINTS, dropped: 0 },
].map(line => JSON.stringify(line)).join("\n") + "\n";

type Depth = { posts: string[]; answer: (route: Route) => Promise<void> };

async function desk(page: Page, symbol: string, depth: Depth, { width = 1440, height = 900 } = {}) {
  await page.setViewportSize({ width, height });
  await page.route("**/copilot/status", route => route.fulfill({ json: ON }));
  await page.route("**/copilot/investigations?*", route => route.fulfill({ json: { investigations: [] } }));
  await page.route("**/copilot/chat", route => route.abort());
  await page.route("**/copilot/desk/read", route => route.fulfill({ json: { state: "hidden" } }));
  await page.route("**/copilot/desk/*/{picture,chart}*", route => route.fulfill({ status: 503, json: { detail: "No chart in this test." } }));
  await page.route("**/api/level2-lab/session**", async route => {
    if (route.request().method() === "GET") return route.fulfill({ json: { enabled: true } });
    depth.posts.push(new URL(route.request().url()).search);
    return depth.answer(route);
  });
  await page.goto(`/copilot-lab?symbol=${symbol}`);
  await expect(page.getByTestId("desk-chart")).toBeAttached();
}

const streaming = (): Depth => ({ posts: [], answer: route => route.fulfill({ status: 200, contentType: "application/x-ndjson", body: STREAM }) });

test("Tape is closed by default, opens the ticker's book and prints, and stays open across a reload", async ({ page }) => {
  const depth = streaming();
  await desk(page, "NBIS", depth);
  const toggle = page.getByTestId("tape-toggle");
  await expect(toggle).toHaveAttribute("aria-pressed", "false");
  await expect(page.getByTestId("desk-tape")).toHaveCount(0);
  expect(depth.posts).toEqual([]); // nothing reaches the depth service while it is closed

  await toggle.click();
  const tape = page.getByTestId("desk-tape");
  await expect(tape.getByTestId("tape-spread")).toContainText("Bid 94.10 × 400 · Ask 94.12 × 300 · Spread 2¢ (0.02%)");
  expect(depth.posts).toEqual(["?symbol=NBIS"]);
  // Five levels a side, bids beside asks.
  await expect(tape.getByTestId("tape-levels").locator("tbody tr")).toHaveCount(5);
  await expect(tape.getByTestId("tape-levels").locator("tbody tr").first()).toContainText("40094.1094.12300");
  const rows = tape.getByTestId("tape-prints").locator("li");
  await expect(rows).toHaveCount(29);
  // Newest first: the late print is plain, the big one is at the ask and bold, then at the bid, at the ask, then between.
  await expect(rows.nth(0)).not.toHaveAttribute("data-side", /.*/);
  await expect(rows.nth(1)).toHaveAttribute("data-side", "ask");
  await expect(rows.nth(1)).toHaveAttribute("data-big", "true");
  await expect(rows.nth(1)).toContainText("5,000");
  await expect(rows.nth(2)).toHaveAttribute("data-side", "bid");
  await expect(rows.nth(2)).toContainText("at bid");
  await expect(rows.nth(3)).toHaveAttribute("data-side", "ask");
  await expect(rows.nth(3)).not.toHaveAttribute("data-big", /.*/);
  await expect(rows.nth(4)).not.toHaveAttribute("data-side", /.*/);
  await expect(rows.nth(28)).toContainText("94.10");
  await expect(rows.nth(28)).not.toHaveAttribute("data-side", /.*/); // before the book: never matched with a later one
  // The stub's stream ended: the tape says so and does not reconnect by itself.
  await expect(tape.getByTestId("tape-status")).toHaveText("The tape ended.");
  expect(depth.posts).toHaveLength(1);

  await page.reload();
  await expect(page.getByTestId("tape-toggle")).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId("desk-tape").getByTestId("tape-prints").locator("li")).toHaveCount(29);

  await page.getByTestId("tape-toggle").click();
  await expect(page.getByTestId("desk-tape")).toHaveCount(0);
  await page.reload();
  await expect(page.getByTestId("desk-chart")).toBeAttached();
  await expect(page.getByTestId("tape-toggle")).toHaveAttribute("aria-pressed", "false");
});

test("closing the Tape stops a running stream", async ({ page }) => {
  // A stream that stays open: the stub never answers until the browser aborts.
  await page.addInitScript(() => {
    const original = window.fetch.bind(window);
    window.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
      const url = input instanceof Request ? input.url : String(input);
      if ((init?.method ?? "GET") === "POST" && url.includes("/api/level2-lab/session") && init?.signal) {
        Object.assign(window, { tapeAborted: false });
        init.signal.addEventListener("abort", () => Object.assign(window, { tapeAborted: true }), { once: true });
        return new Promise<Response>((_, reject) => init.signal!.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")), { once: true }));
      }
      return original(input, init);
    }) as typeof window.fetch;
  });
  await desk(page, "NBIS", streaming());
  await page.getByTestId("tape-toggle").click();
  await expect(page.getByTestId("tape-status")).toHaveText("Connecting NBIS…");
  // The desk's data health shows the session as Level 2 while it runs, and off once the Tape closes.
  await page.getByTestId("desk-health").click();
  await expect(page.getByTestId("health-level2")).toHaveAttribute("data-state", "live");
  await expect(page.getByTestId("health-level2")).toContainText("Live · NBIS");
  await page.keyboard.press("Escape");
  await page.getByTestId("tape-toggle").click();
  await expect(page.getByTestId("desk-tape")).toHaveCount(0);
  await expect.poll(() => page.evaluate(() => (window as unknown as { tapeAborted: boolean }).tapeAborted)).toBe(true);
  await page.getByTestId("desk-health").click();
  await expect(page.getByTestId("health-level2")).toHaveAttribute("data-state", "off");
});

test("another session holding the bridge is named, not fought", async ({ page }) => {
  const depth: Depth = { posts: [], answer: route => route.fulfill({ status: 409, json: { detail: "Local lab unavailable" } }) };
  await desk(page, "NBIS", depth);
  await page.getByTestId("tape-toggle").click();
  const tape = page.getByTestId("desk-tape");
  await expect(tape.getByTestId("tape-status")).toHaveText(/Another Level 2 stream is running \(Charts, perhaps in another tab\)/);
  await page.waitForTimeout(3_000);
  expect(depth.posts).toHaveLength(1); // no retry loop against a session the desk did not stop
  await tape.getByRole("button", { name: "Try again" }).click();
  await expect.poll(() => depth.posts.length).toBe(2);
});

test("an index starts nothing", async ({ page }) => {
  const depth = streaming();
  await desk(page, "SPX", depth);
  await page.getByTestId("tape-toggle").click();
  await expect(page.getByTestId("desk-tape")).toContainText("SPX is an index: the tape covers US stocks and ETFs only. Nothing was started.");
  await page.waitForTimeout(500);
  expect(depth.posts).toEqual([]);
});

test("a phone shows the spread and a short tape, not the book", async ({ page }) => {
  await desk(page, "NBIS", streaming(), { width: 390, height: 844 });
  await page.getByRole("button", { name: "Back to the desk" }).click(); // the address opens the copilot over the desk
  await page.getByTestId("tape-toggle").click();
  const tape = page.getByTestId("desk-tape");
  await expect(tape.getByTestId("tape-spread")).toBeVisible();
  await expect(tape.getByTestId("tape-levels")).toBeHidden();
  await expect(tape.getByTestId("tape-prints").locator("li:visible")).toHaveCount(8);
});

/** Makes the page look hidden or shown to the app, as switching browser tabs does. */
const setHidden = (page: Page, hidden: boolean) => page.evaluate(value => {
  Object.defineProperty(document, "hidden", { configurable: true, get: () => value });
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => value ? "hidden" : "visible" });
  document.dispatchEvent(new Event("visibilitychange"));
}, hidden);

test("hiding the tab stops the stream and showing it starts again", async ({ page }) => {
  await page.addInitScript(() => {
    const original = window.fetch.bind(window);
    const record = { posts: 0, aborted: 0 };
    Object.assign(window, { tapeRecord: record });
    window.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
      const url = input instanceof Request ? input.url : String(input);
      if ((init?.method ?? "GET") === "POST" && url.includes("/api/level2-lab/session") && init?.signal) {
        record.posts += 1;
        return new Promise<Response>((_, reject) => init.signal!.addEventListener("abort", () => {
          record.aborted += 1; reject(new DOMException("aborted", "AbortError"));
        }, { once: true }));
      }
      return original(input, init);
    }) as typeof window.fetch;
  });
  await desk(page, "NBIS", streaming());
  await page.getByTestId("tape-toggle").click();
  const record = () => page.evaluate(() => (window as unknown as { tapeRecord: { posts: number; aborted: number } }).tapeRecord);
  await expect.poll(record).toEqual({ posts: 1, aborted: 0 });
  await setHidden(page, true);
  await expect.poll(record).toEqual({ posts: 1, aborted: 1 });
  await expect(page.getByTestId("tape-status")).toHaveText("Paused while the page is hidden.");
  await setHidden(page, false);
  await expect.poll(record).toEqual({ posts: 2, aborted: 1 });
  await expect(page.getByTestId("tape-status")).toHaveText("Connecting NBIS…");
});

test("hiding and showing the tab does not retry against another session holding the bridge", async ({ page }) => {
  const depth: Depth = { posts: [], answer: route => route.fulfill({ status: 409, json: { detail: "Local lab unavailable" } }) };
  await desk(page, "NBIS", depth);
  await page.getByTestId("tape-toggle").click();
  await expect(page.getByTestId("tape-status")).toHaveText(/Another Level 2 stream is running/);
  await setHidden(page, true);
  await setHidden(page, false);
  await page.waitForTimeout(3_000);
  expect(depth.posts).toHaveLength(1);
  await expect(page.getByTestId("tape-status")).toHaveText(/Another Level 2 stream is running/);
});
