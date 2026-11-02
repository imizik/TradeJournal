import { expect, test } from "@playwright/test";

const API = `http://127.0.0.1:${Number(process.env.E2E_BACKEND_PORT || 8099)}`;
test.beforeEach(async ({ request }) => {
  expect((await request.post(`${API}/__test/exit-habits-seed`)).ok()).toBe(true);
  expect((await request.post(`${API}/__test/radar-seed`)).ok()).toBe(true);
});

for (const [size, width, height] of [["desktop", 1440, 1000], ["phone", 390, 844]] as const) {
  test(`existing evidence and feedback links on ${size}`, async ({ page }) => {
    await page.setViewportSize({ width, height });
    const errors: string[] = [];
    const writes: string[] = [];
    page.on("pageerror", e => errors.push(e.message));
    page.on("request", r => { if (r.url().includes("/api/backend/") && r.method() !== "GET") writes.push(r.url()); });
    // Real seeded endpoints: the overview must agree with its existing source, not a new calculation.
    const habits = await (await page.request.get("/api/backend/analytics/exit-habits")).json();
    const radar = await (await page.request.get("/api/backend/radar/proof")).json();
    await page.goto("/experiments");
    await expect(page.getByTestId("experiment-alerts")).toContainText(`${habits.feedback.responded} / ${habits.feedback.total} alerts answered`);
    await expect(page.getByTestId("experiment-radar")).toContainText(`${radar.verdict.rated} / ${radar.events} events rated`);
    const detail = page.locator("#experiment-detail");
    await expect(detail).toContainText(habits.verdict.reason);
    await expect(detail).toContainText("Unanswered does not mean unseen or unhelpful");
    const first = habits.alerts.find((a: { trade_id: string | null }) => a.trade_id);
    await expect(detail.locator(`a[href="/trades/${first.trade_id}?alert=${first.id}"]`)).toBeVisible();
    await expect(page.getByRole("figure", { name: "What you said about the alerts" })).toBeVisible();
    await page.screenshot({ path: test.info().outputPath(`experiments-alerts-${size}.png`), fullPage: true });
    await page.getByTestId("experiment-radar").click();
    await expect(page.getByRole("figure")).toHaveCount(1);
    await expect(detail).toContainText("not certified sessions");
    await expect(detail.getByRole("link", { name: "Rate Radar events" })).toHaveAttribute("href", "/radar");
    await page.getByRole("button", { name: "Refresh evidence" }).click();
    await expect(page.getByTestId("experiment-radar")).toHaveAttribute("aria-expanded", "true");
    await expect(detail).toContainText(radar.rule_version);
    await page.getByTestId("experiment-plans").click();
    await expect(detail).toContainText("Selection-biased");
    await page.getByTestId("experiment-shadow").click();
    await expect(detail).toContainText("separate from Jo's scanner-based Shadow Isaac");
    await expect(detail).toContainText("no winner is declared");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
    expect(writes).toEqual([]);
    expect(errors).toEqual([]);
  });
}

test("unavailable sources and partial scorecards never become zero evidence", async ({ page }) => {
  let fail = true;
  await page.route("**/radar/proof", route => fail ? route.fulfill({ status: 503, json: {} }) : route.continue());
  await page.route("**/copilot/status", route => route.fulfill({ json: { enabled: true } }));
  await page.route("**/copilot/answer-scorecard?*", route => route.fulfill({ json: {
    state: "ok", window: { days: 14, since: "2026-10-19T00:00", until: "2026-11-02T00:00" },
    answers: { state: "unavailable" }, cost: { total_usd: 1.25 },
  } }));
  await page.goto("/experiments");
  await expect(page.getByTestId("experiment-radar")).toContainText("Unavailable");
  await page.getByTestId("experiment-radar").click();
  const detail = page.locator("#experiment-detail");
  await expect(detail).toContainText("unavailable, not zero");
  await expect(detail.getByRole("figure")).toHaveCount(0);
  await page.getByTestId("experiment-copilot").click();
  await expect(page.getByTestId("experiment-copilot")).toContainText("Ratings unavailable");
  await expect(detail).toContainText("$1.25 recorded");
  await expect(detail.getByRole("figure")).toHaveCount(0);
  // Other sources still work, and a refresh recovers a transient failed source.
  await expect(page.getByTestId("experiment-alerts")).toContainText("alerts answered");
  fail = false;
  await page.getByRole("button", { name: "Refresh evidence" }).click();
  await expect(page.getByTestId("experiment-radar")).toContainText("events rated");
  await expect(page.getByTestId("experiment-copilot")).toHaveAttribute("aria-expanded", "true");
});

test("missing scorecard deployment and zero ratings remain distinct", async ({ page }) => {
  let deployed = false;
  await page.route("**/copilot/status", route => route.fulfill({ json: { enabled: true } }));
  await page.route("**/copilot/answer-scorecard?*", route => deployed ? route.fulfill({ json: {
    state: "ok", window: { days: 14, since: "2026-10-19T00:00", until: "2026-11-02T00:00" },
    answers: { total: 8, rated: 0, helped: 0, didnt: 0 }, cost: { state: "unavailable" },
  } }) : route.fulfill({ status: 404, json: { detail: "Not found" } }));
  await page.goto("/experiments");
  await expect(page.getByTestId("experiment-copilot")).toContainText("Unavailable");
  deployed = true;
  await page.getByRole("button", { name: "Refresh evidence" }).click();
  await expect(page.getByTestId("experiment-copilot")).toContainText("0 / 8 saved answers rated");
  await expect(page.getByTestId("experiment-copilot")).toContainText("Needs feedback");
  await page.getByTestId("experiment-copilot").click();
  await expect(page.locator("#experiment-detail")).toContainText("Cost unavailable");
  await expect(page.getByRole("figure", { name: "Saved answer feedback" })).toContainText("Not rated");
});
