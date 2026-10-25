import { test, expect } from "@playwright/test";
import { bookState, depthSummary, replayAt, sourceTime, type ReplayFrame } from "../lib/level2Replay";

test("synthetic depth math has independent golden values and unavailable boundaries", () => {
  const first = replayAt(0), summary = depthSummary(first, 0)!;
  expect(summary.bidSize).toBe(3220);
  expect(summary.askSize).toBe(2760);
  expect(summary.spreadCents).toBe(2);
  expect(summary.imbalance).toBeCloseTo(460 / 5980, 10);
  expect(sourceTime(0)).toBe("09:30:00");
  expect(bookState(replayAt(7000), 7000)).toBe("fresh");
  expect(bookState(replayAt(8000), 8000)).toBe("stale");
  for (const second of [8, 10, 13, 14]) expect(depthSummary(replayAt(second * 1000), second * 1000)).toBeNull();
  expect(bookState(replayAt(10000), 10000)).toBe("disconnected");
  expect(bookState(replayAt(13000), 13000)).toBe("empty");
  expect(bookState(replayAt(14000), 14000)).toBe("unknown-time");
  expect(depthSummary(replayAt(16000), 16000)).not.toBeNull();
  const zero: ReplayFrame = { ...first, book: { ...first.book,
    bids: first.book.bids.map(level => ({ ...level, size: 0 })),
    asks: first.book.asks.map(level => ({ ...level, size: 0 })),
  } };
  expect(depthSummary(zero, 0)?.imbalance).toBeNull();
  const sparse = { ...first, book: { ...first.book, asks: first.book.asks.slice(0, 4) } };
  expect(depthSummary(sparse, 0)).toBeNull();
  expect(replayAt(-1000)).toBe(first);
  expect(replayAt(Number.NaN)).toBe(first);
  expect(replayAt(90000).offsetMs).toBe(20000);
});

test("ladder, heatmap and failure states are truthful on desktop and phone", async ({ page }) => {
  const errors: string[] = [], forbiddenRequests: string[] = [], sockets: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("websocket", socket => sockets.push(socket.url()));
  page.on("request", request => {
    const url = request.url();
    // Existing shell reads job status (market_context.py) and the nav's plan streak (a journal count), not provider calls.
    const shellStatusRead = request.method() === "GET" && [
      "/api/backend/market-context/enrich/status", "/api/backend/market-context/trade-path/status", "/api/backend/charts/captures/streak",
    ].includes(new URL(url).pathname);
    if ((!shellStatusRead && /\/api\/backend\/(charts|quotes|market-context)|moomoo|openapi/i.test(url)) || (url.includes("/api/backend/") && !["GET", "HEAD"].includes(request.method()))) forbiddenRequests.push(`${request.method()} ${url}`);
  });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/level2-lab");
  await expect(page.getByRole("heading", { name: "Level 2 lab", exact: true })).toBeVisible();
  await expect(page.getByText("SYNTHETIC REPLAY", { exact: true })).toBeVisible();
  await expect(page.getByTestId("replay-progress")).toContainText("Paused");
  await expect(page.getByTestId("bid-total")).toHaveText("3,220");
  await expect(page.getByTestId("ask-total")).toHaveText("2,760");
  await expect(page.getByTestId("book-imbalance")).toHaveText("+7.7%");
  await expect(page.getByTestId("book-spread")).toHaveText("$0.02");
  await expect(page.getByRole("table", { name: "Synthetic depth ladder" }).getByRole("row")).toHaveCount(9);
  await expect(page.getByRole("table").getByRole("cell", { name: "—", exact: true })).toHaveCount(2);
  await expect(page.locator("svg rect[data-column='1']")).toHaveCount(0);
  await page.screenshot({ path: test.info().outputPath("level2-fresh-desktop.png"), fullPage: true });

  for (const [button, expectedState] of [
    ["Stale", "Stale simulated book"], ["Disconnect", "Simulated disconnect"],
    ["Empty", "Empty simulated book"], ["Unknown time", "Source time unavailable"],
  ]) {
    await page.getByRole("button", { name: button, exact: true }).click();
    await expect(page.getByTestId("book-state")).toHaveText(expectedState);
    await expect(page.getByTestId("book-imbalance")).toHaveText("Unavailable");
    await expect(page.getByTestId("book-spread")).toHaveText("Unavailable");
    await expect(page.getByTestId("bid-total")).toHaveText("Unavailable");
    const second = Number(await page.getByLabel("Replay position").inputValue());
    await expect(page.locator(`svg rect[data-column='${second}']`)).toHaveCount(0);
    await page.screenshot({ path: test.info().outputPath(`level2-${button.toLowerCase().replaceAll(" ", "-")}-desktop.png`), fullPage: true });
  }
  await expect(page.getByTestId("book-source-time")).toHaveText("unavailable");
  await expect(page.getByTestId("book-age")).toHaveText("Unavailable");
  await page.getByRole("button", { name: "Recovery", exact: true }).click();
  await expect(page.getByTestId("book-state")).toHaveText("Fresh simulated book");
  for (const second of [8, 9, 10, 11, 12, 13, 14, 17]) await expect(page.locator(`svg rect[data-column='${second}']`)).toHaveCount(0);
  await expect(page.locator("svg rect[data-column='16']")).toHaveCount(16);
  await page.screenshot({ path: test.info().outputPath("level2-recovery-desktop.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("button", { name: "Play replay" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: test.info().outputPath("level2-recovery-phone.png"), fullPage: true });
  const heatmap = page.getByRole("region", { name: "Scrollable liquidity heatmap" });
  await heatmap.focus();
  await page.keyboard.press("End");
  await expect.poll(() => heatmap.evaluate(element => element.scrollLeft)).toBeGreaterThan(0);
  await page.getByRole("button", { name: "Stale", exact: true }).click();
  await expect(page.getByTestId("book-state")).toHaveText("Stale simulated book");
  await page.screenshot({ path: test.info().outputPath("level2-stale-phone.png"), fullPage: true });
  await page.getByLabel("Replay position").focus();
  await page.keyboard.press("Home");
  await expect(page.getByLabel("Replay position")).toHaveValue("0");
  await page.keyboard.press("ArrowRight");
  await expect(page.getByLabel("Replay position")).toHaveValue("1");
  await page.getByRole("button", { name: "Step 1s", exact: true }).click();
  await expect(page.getByLabel("Replay position")).toHaveValue("2");
  await page.getByRole("button", { name: "Reset", exact: true }).click();
  await expect(page.locator("svg rect[data-column='1']")).toHaveCount(0);
  await page.getByRole("button", { name: "Open menu" }).click();
  await expect(page.getByRole("dialog", { name: "Menu" }).getByRole("link", { name: "Level 2 lab" })).toBeVisible();
  await page.getByRole("button", { name: "Close menu" }).click();
  expect(errors).toEqual([]);
  expect(forbiddenRequests).toEqual([]);
  expect(sockets).toEqual([]);
});

test("playback pauses, changes speed, stops at end and resets on reload without storing replay", async ({ page }) => {
  const clockStart = new Date("2026-10-09T13:30:00Z");
  await page.clock.install({ time: clockStart });
  await page.clock.pauseAt(new Date(clockStart.getTime() + 1000));
  await page.addInitScript(() => {
    const original = Storage.prototype.setItem;
    const writes: string[] = [];
    Object.assign(window, { depthStorageWrites: writes });
    Storage.prototype.setItem = function(key, value) { writes.push(key); return original.call(this, key, value); };
  });
  await page.goto("/level2-lab");
  await page.getByRole("button", { name: "Play replay" }).click();
  await page.clock.runFor(2500);
  await expect(page.getByTestId("replay-progress")).toHaveText("2.5 / 20.0s · Playing");
  await page.getByRole("button", { name: "Pause replay" }).click();
  await page.clock.runFor(2000);
  await expect(page.getByTestId("replay-progress")).toHaveText("2.5 / 20.0s · Paused");
  await page.getByLabel("Replay speed").selectOption("4");
  await page.getByRole("button", { name: "Play replay" }).click();
  await page.clock.runFor(1000);
  await expect(page.getByTestId("replay-progress")).toHaveText("6.5 / 20.0s · Playing");
  await page.evaluate(() => {
    Object.defineProperty(document, "hidden", { configurable: true, value: true });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await expect(page.getByRole("button", { name: "Play replay" })).toBeVisible();
  await page.clock.runFor(1000);
  await expect(page.getByTestId("replay-progress")).toHaveText("6.5 / 20.0s · Paused");
  await page.evaluate(() => Object.defineProperty(document, "hidden", { configurable: true, value: false }));
  await page.getByRole("button", { name: "Play replay" }).click();
  await page.clock.runFor(4000);
  await expect(page.getByTestId("replay-progress")).toHaveText("20.0 / 20.0s · Ended");
  await expect(page.getByRole("button", { name: "Step 1s" })).toBeDisabled();
  await page.screenshot({ path: test.info().outputPath("level2-ended-desktop.png"), fullPage: true });
  await page.clock.runFor(2000);
  await expect(page.getByTestId("replay-progress")).toHaveText("20.0 / 20.0s · Ended");
  await page.getByRole("button", { name: "Play replay" }).click();
  await expect(page.getByTestId("replay-progress")).toHaveText("0.0 / 20.0s · Playing");
  expect(await page.evaluate(() => (window as unknown as { depthStorageWrites: string[] }).depthStorageWrites)).toEqual([]);
  await page.reload();
  await expect(page.getByTestId("replay-progress")).toHaveText("0.0 / 20.0s · Paused");
});
