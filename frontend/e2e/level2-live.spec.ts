import { test, expect, type Page } from "@playwright/test";

const sessionPath = "**/api/level2-lab/session";

async function enabledSession(page: Page, ndjson: string | ((route: import("@playwright/test").Route) => Promise<void>)) {
  let posts = 0;
  await page.route(sessionPath, async route => {
    if (route.request().method() === "GET") return route.fulfill({ json: { enabled: true } });
    posts += 1;
    if (typeof ndjson === "string") return route.fulfill({ status: 200, contentType: "application/x-ndjson", body: ndjson });
    return ndjson(route);
  });
  return () => posts;
}

test("live session stays manually disabled when the local service is disabled", async ({ page }) => {
  let posts = 0;
  await page.route(sessionPath, route => {
    if (route.request().method() === "GET") return route.fulfill({ json: { enabled: false } });
    posts += 1;
    return route.fulfill({ status: 503, json: { enabled: false } });
  });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/level2-lab");
  const panel = page.getByTestId("live-depth-session");
  await expect(panel.getByText("Local live service is disabled.")).toBeVisible();
  await expect(panel.getByRole("button", { name: "Connect for 30 seconds" })).toBeDisabled();
  await page.screenshot({ path: test.info().outputPath("level2-live-disabled-desktop.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: test.info().outputPath("level2-live-disabled-phone.png"), fullPage: true });
  expect(posts).toBe(0);
});

test("manual session renders acknowledgements and only the latest book with missing freshness", async ({ page }) => {
  const records = [
    { event: "status", phase: "connecting" },
    { event: "status", phase: "authenticated" },
    { event: "status", phase: "subscribed", kind: "quote", code: 0 },
    { event: "status", phase: "failed", kind: "order_book", code: 429 },
    { event: "status", phase: "subscribed", kind: "ticker", code: 0 },
    { event: "book", symbol: "US.NVDA", received_ms: 1791657000123, books: [
      { exchange: "UNKNOWN", source_time_ms: null, estimated_age_ms: null, order_volume_precision: 3,
        bids: [{ price: 123.4567, volume: 100.25, order_count: null, mpid: null }],
        asks: [{ price: 123.4589, volume: 50.5, order_count: 2, mpid: "DO NOT INFER EXCHANGE" }] },
    ] },
    { event: "book", symbol: "US.NVDA", received_ms: 1791657000456, books: [
      { exchange: "ARCA", source_time_ms: 0, estimated_age_ms: null, order_volume_precision: 2,
        bids: [{ price: 123.4567, volume: 101.25, order_count: 4, mpid: "XNAS" }], asks: [] },
      { exchange: "NASDAQ", source_time_ms: 1791657000400, estimated_age_ms: 2501, order_volume_precision: null,
        bids: [], asks: [{ price: 123.4589, volume: 50.5, order_count: null, mpid: null }] },
      { exchange: "UNKNOWN", source_time_ms: 1791657000410, estimated_age_ms: -5, order_volume_precision: null,
        bids: [{ price: 123.4501, volume: 0, order_count: null, mpid: "XNAS" }], asks: [] },
    ] },
    { event: "summary", report: { authentication: { status: "success", code: 0 }, status: "completed", subscriptions: {
      quote: { status: "success", code: 0 }, order_book: { status: "failed", code: 429 }, ticker: { status: "success", code: 0 },
    }, message_counts: { QUOTE: 1, ORDER_BOOK: 0, TICKER: 2 }, unsubscribe: { status: "success", code: 0 }, closed: true } },
    { event: "provider_error", error: "DO NOT SHOW RAW PROVIDER ERROR" },
    { unexpected: "ignore protocol extension" },
  ].map(record => JSON.stringify(record)).join("\n") + "\n";
  const posts = await enabledSession(page, records);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/level2-lab");
  const panel = page.getByTestId("live-depth-session");
  await expect(panel.getByRole("button", { name: "Connect for 30 seconds" })).toBeEnabled();
  await panel.getByRole("button", { name: "Connect for 30 seconds" }).click();
  await expect(panel.getByText("Session closed. Any retained book is for inspection only.")).toBeVisible();
  await expect(panel.getByText("Authentication: success · Session status: completed")).toBeVisible();
  await expect(panel.getByText("Subscription: failed · code 429")).toBeVisible();
  await expect(panel.getByText("Messages: 0")).toBeVisible();
  await expect(panel.getByText("Exchange: ARCA")).toBeVisible();
  await expect(panel.getByText("Exchange: Unavailable")).toBeVisible();
  await expect(panel.getByText("Stale or invalid at receipt: 2501ms")).toBeVisible();
  await expect(panel.getByText("Stale or invalid at receipt: -5ms")).toBeVisible();
  await expect(panel.getByText("Freshness unavailable")).toBeVisible();
  await expect(panel.getByText("Reported MPIDs (not exchange evidence): XNAS").first()).toBeVisible();
  await expect(panel.getByText("123.4567")).toBeVisible();
  await expect(panel.getByText("101.25")).toBeVisible();
  await expect(panel.getByText("DO NOT SHOW RAW PROVIDER ERROR")).toHaveCount(0);
  expect(posts()).toBe(1);
  await page.screenshot({ path: test.info().outputPath("level2-live-latest-book-desktop.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: test.info().outputPath("level2-live-latest-book-phone.png"), fullPage: true });
});

test("malformed and oversized NDJSON records are ignored without leaking raw text", async ({ page }) => {
  const body = "not json\n" + "x".repeat(256 * 1024 + 1) + "\n"
    + JSON.stringify({ event: "summary", report: { authentication: { status: "failed" }, status: "failed_or_timed_out", subscriptions: {}, message_counts: {}, unsubscribe: { status: "not_needed" }, closed: true } }) + "\n";
  await enabledSession(page, body);
  await page.goto("/level2-lab");
  const panel = page.getByTestId("live-depth-session");
  await panel.getByRole("button", { name: "Connect for 30 seconds" }).click();
  await expect(panel.getByText("An invalid or oversized protocol line was ignored.")).toBeVisible();
  await expect(panel.getByText("Authentication: failed · Session status: failed_or_timed_out")).toBeVisible();
  await expect(panel.getByText("x".repeat(100))).toHaveCount(0);
});

test("stop aborts the manual request and does not reconnect", async ({ page }) => {
  const posts = await enabledSession(page, async route => {
    await new Promise(resolve => setTimeout(resolve, 1200));
    await route.fulfill({ status: 200, contentType: "application/x-ndjson", body: "" }).catch(() => undefined);
  });
  await page.goto("/level2-lab");
  const panel = page.getByTestId("live-depth-session");
  await panel.getByRole("button", { name: "Connect for 30 seconds" }).click();
  await expect(panel.getByRole("button", { name: "Session running…" })).toBeVisible();
  await panel.getByRole("button", { name: "Stop" }).click();
  await expect(panel.getByRole("button", { name: "Reload to start again" })).toBeDisabled();
  await page.waitForTimeout(1400);
  expect(posts()).toBe(1);
});

test("hidden tab and unmount cancel the stream without automatic reconnect", async ({ page }) => {
  const posts = await enabledSession(page, async route => {
    await new Promise(resolve => setTimeout(resolve, 1200));
    await route.fulfill({ status: 200, contentType: "application/x-ndjson", body: "" }).catch(() => undefined);
  });
  await page.goto("/level2-lab");
  const panel = page.getByTestId("live-depth-session");
  await panel.getByRole("button", { name: "Connect for 30 seconds" }).click();
  await page.evaluate(() => { Object.defineProperty(document, "hidden", { configurable: true, value: true }); document.dispatchEvent(new Event("visibilitychange")); });
  await expect(panel.getByRole("button", { name: "Reload to start again" })).toBeDisabled();
  await page.goto("/");
  await page.waitForTimeout(1400);
  expect(posts()).toBe(1);
});
