import { expect, test, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";

const backend = path.resolve(__dirname, "../../backend");
const venvPython = path.join(backend, ".venv/bin/python");
const python = existsSync(venvPython) ? venvPython : "python3";
const alertId = "v1:1.0.0:SPY:5:1737561600000:e2e_break:long";
const detailPath = `/signals/${encodeURIComponent(alertId)}`;

function fixture(status: "reset" | "pending" | "running" | "done" | "skipped" | "error") {
  execFileSync(python, [path.join(__dirname, "fixtures/signals.py"), status], { cwd: backend });
}

async function openWithClock(page: Page, url = "/signals") {
  await page.clock.install();
  await page.goto(url);
  await page.waitForLoadState("networkidle");
  // The installed clock keeps running until it is paused, so a time read in
  // this process can already be in the page's past when pauseAt arrives
  // ("Cannot fast-forward to the past"). Pause a second ahead of the page's own
  // clock instead; the page's only timer is the 30s refresh.
  const now = await page.evaluate(() => Date.now());
  await page.clock.pauseAt(now + 1_000);
}

async function tick(page: Page) {
  const response = page.waitForResponse((r) =>
    r.request().headers().rsc === "1" && new URL(r.url()).pathname.startsWith("/signals"),
  );
  await page.clock.fastForward(30_000);
  expect((await response).ok()).toBe(true);
  await expect(page.getByRole("button", { name: "Refresh now" })).toBeEnabled();
}

// Browser visibility is read-only. Override it to exercise the same event that
// browsers dispatch when a phone/app/tab is backgrounded, deterministically.
async function visibility(page: Page, hidden: boolean) {
  await page.evaluate((value) => {
    Object.defineProperty(document, "hidden", { configurable: true, value });
    document.dispatchEvent(new Event("visibilitychange"));
  }, hidden);
}

test.beforeEach(() => fixture("reset"));
test.afterEach(() => fixture("reset"));

test("signals receive new alerts and verdicts without reloading the document", async ({ page }) => {
  let documents = 0;
  page.on("request", (request) => {
    if (request.isNavigationRequest() && request.frame() === page.mainFrame()) documents += 1;
  });
  await openWithClock(page);
  await expect(page.getByText("No alerts received yet.", { exact: false })).toBeVisible();

  fixture("pending");
  await tick(page);
  const row = page.getByRole("row").filter({ hasText: "e2e_break" });
  await expect(row.getByText("pending", { exact: true })).toBeVisible();
  await expect(row.getByText("214.32", { exact: true })).toBeVisible();
  await expect(page.getByText("Awaiting analysis", { exact: true }).locator("..")).toContainText("1");

  fixture("done");
  await tick(page);
  await expect(row.getByText("long scalp", { exact: true })).toBeVisible();
  await expect(row.getByText("high", { exact: true })).toBeVisible();
  await expect(page.getByText("Awaiting analysis", { exact: true }).locator("..")).toContainText("0");
  await expect(page.getByText("Tradeable verdicts", { exact: true }).locator("..")).toContainText("1");
  expect(documents).toBe(1);
});

test("signal detail refreshes running analysis and its completed assessment", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  fixture("pending");
  await openWithClock(page);
  await page.getByRole("link", { name: "Detail", exact: true }).click();
  await expect(page.getByText("Waiting for analysis.", { exact: false })).toBeVisible();

  fixture("running");
  await page.getByRole("button", { name: "Refresh now" }).click();
  await expect(page.getByText("Analysis is running.", { exact: false })).toBeVisible();

  fixture("done");
  await tick(page);
  await expect(page.getByRole("heading", { name: "Assessment", exact: true })).toBeVisible();
  await expect(page.getByText("Price reclaimed the opening range", { exact: true })).toBeVisible();
  await expect(page.getByText("long scalp", { exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("signals pause when hidden, resume immediately, and stop on navigation", async ({ page }) => {
  await openWithClock(page);
  const refreshes: string[] = [];
  page.on("request", (r) => {
    if (r.headers().rsc === "1" && new URL(r.url()).pathname === "/signals") refreshes.push(r.url());
  });
  await visibility(page, true);
  fixture("pending");
  await page.clock.fastForward(90_000);
  expect(refreshes).toHaveLength(0);
  await expect(page.getByText("No alerts received yet.", { exact: false })).toBeVisible();

  await visibility(page, false);
  await expect(page.getByRole("cell", { name: "SPY", exact: true })).toBeVisible();
  expect(refreshes).toHaveLength(1);

  await page.getByRole("link", { name: "Trades", exact: true }).first().click();
  await expect(page.getByRole("heading", { name: "Trades", exact: true })).toBeVisible();
  const afterNavigation: string[] = [];
  page.on("request", (r) => {
    if (r.headers().rsc === "1" && !r.headers()["next-router-prefetch"]) afterNavigation.push(r.url());
  });
  await page.clock.fastForward(90_000);
  await visibility(page, true);
  await visibility(page, false);
  expect(afterNavigation).toHaveLength(0);
});

test("a slow refresh keeps the last view and prevents overlapping requests", async ({ page }) => {
  fixture("pending");
  await openWithClock(page);
  let release!: () => void;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  let requests = 0;
  await page.route("**/signals?*", async (route) => {
    requests += 1;
    await gate;
    await route.continue();
  });
  try {
    await page.clock.fastForward(30_000);
    await expect(page.getByRole("button", { name: "Updating…" })).toBeDisabled();
    await expect(page.getByRole("cell", { name: "SPY", exact: true })).toBeVisible();
    await page.clock.fastForward(90_000);
    await visibility(page, true);
    await visibility(page, false);
    expect(requests).toBe(1);
    fixture("done");
  } finally {
    release();
  }
  await expect(page.getByText("long scalp", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Refresh now" })).toBeEnabled();
  await tick(page);
  expect(requests).toBe(2);
});

test("skipped and failed details show their recorded reasons", async ({ page }) => {
  fixture("skipped");
  await page.goto(detailPath);
  await expect(page.getByText("This alert was recorded without a verdict.", { exact: false })).toContainText(
    "Alpaca credentials are not configured",
  );
  await expect(page.getByRole("heading", { name: "Analysis Error" })).toHaveCount(0);

  fixture("error");
  await page.getByRole("button", { name: "Refresh now" }).click();
  await expect(page.getByRole("heading", { name: "Analysis Error" })).toBeVisible();
  await expect(page.getByText("Synthetic scorer failure", { exact: true })).toBeVisible();
});
