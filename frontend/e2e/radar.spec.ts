import { expect, test } from "@playwright/test";
import { radarChartContext, radarReturnHref, radarSession } from "../lib/radar";

const API = `http://127.0.0.1:${Number(process.env.E2E_BACKEND_PORT || 8099)}`;
const EVENT = "rad_sample_mu_20261020_1";

test.beforeEach(async ({ request }) => {
  expect((await request.post(`${API}/__test/radar-seed`)).ok()).toBeTruthy();
});

for (const [size, width, height] of [["desktop", 1440, 900], ["phone", 390, 844]] as const) {
  test(`radar feed, detail, rating and chart link on ${size}`, async ({ page, request }) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.setViewportSize({ width, height });
    await page.goto("/radar");
    await expect(page.getByTestId("radar-coverage")).toContainText("Recorded · 169 symbols");
    await expect(page.getByTestId("radar-coverage")).toContainText("1 missing");
    // Never visited before, so the sample event is new.
    const newSection = page.getByRole("region", { name: "New since your last visit" });
    const card = newSection.getByTestId("radar-event");
    await expect(card).toContainText("MU up 4.1% while SMH is up 0.6%");
    await expect(card).toContainText("Now: Extended");
    await expect(card.getByTestId("radar-rules-tag")).toHaveCount(0);  // only radar-rules-v0 events carry the provisional tag
    // The latest news check: catalyst headline first, marked against the move, never called its cause.
    await expect(card.getByTestId("radar-news-line")).toHaveText(
      "News nearby: Micron raises quarterly revenue forecast on AI memory demand · benzinga · 10:41 AM (before the move)");
    await expect(page.getByTestId("radar-movers")).toBeVisible();
    expect((await card.boundingBox())!.y).toBeLessThan((await page.getByTestId("radar-movers").boundingBox())!.y);
    await page.screenshot({ path: test.info().outputPath(`radar-first-glance-${page.viewportSize()!.width}.png`) });
    await card.getByRole("button").first().click();
    const original = page.getByRole("region", { name: "Original evidence" });
    await expect(original).toContainText("As first saved");
    await expect(original.getByRole("row")).toHaveCount(3);
    await expect(page.getByRole("region", { name: "Revisions" })).toContainText("Lead widened from 3.5 to 4.8 points");
    const news = page.getByRole("region", { name: "News nearby" });
    await expect(news.getByRole("link")).toHaveCount(2);
    await expect(news.getByRole("link", { name: "Memory stocks extend gains as Micron leads chip names" }))
      .toHaveAttribute("href", "https://example.com/news/memory-stocks");
    await expect(news).toContainText("benzinga · 11:20 AM (after the move)");
    await expect(news).toContainText("Checked 11:13 AM (headlines found) · 11:28 AM (headlines found)");
    await expect(news).not.toContainText("caused");
    await page.getByRole("button", { name: "Too late", exact: true }).click();
    await expect(page.getByRole("button", { name: "Too late", exact: true })).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByRole("link", { name: /Open chart · MU/ })).toHaveAttribute("href", "/charts?symbol=MU");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
    await page.screenshot({ path: test.info().outputPath(`radar-${size}.png`), fullPage: true });

    // The visit was recorded when the page opened, so a reload moves the event to Earlier and keeps the rating.
    await page.reload();
    await expect(page.getByRole("region", { name: "New since your last visit" })).toHaveCount(0);
    const earlier = page.getByRole("region", { name: "Earlier in this session" }).getByTestId("radar-event");
    await expect(earlier).toContainText("Rated: Too late");
    const saved = await (await request.get(`${API}/radar/events/${EVENT}`)).json();
    expect(saved.rating).toBe("too_late");
    expect(errors).toEqual([]);
  });
}

for (const [size, width, height] of [["desktop", 1440, 900], ["phone", 390, 844]] as const) {
  test(`radar movers panel is a plain ranking on ${size}`, async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.setViewportSize({ width, height });
    await page.goto("/radar");
    const panel = page.getByTestId("radar-movers");
    await expect(panel.getByTestId("radar-movers-header")).toHaveText("SPY −1.4% · QQQ −1.9% · 168 of 169 symbols · 11:12");
    await expect(panel).toContainText("not alerts");
    const leaders = panel.getByRole("region", { name: "Leaders" });
    const laggards = panel.getByRole("region", { name: "Laggards" });
    await expect(leaders.getByTestId("radar-mover")).toHaveCount(10);
    await expect(laggards.getByTestId("radar-mover")).toHaveCount(10);
    const spot = leaders.getByTestId("radar-mover").first();
    await expect(spot).toContainText("SPOT");
    await expect(spot).toContainText("+10.6%");
    await expect(spot).toContainText("+12.0%"); // versus SPY
    await expect(spot).toContainText("Opening gap +10.0%");
    await expect(spot).toContainText("Since open +0.5%"); // opened at the gap: from open +0.5%, under a third of the day move
    const target = new URL((await spot.getByRole("link", { name: "SPOT" }).getAttribute("href"))!, "http://fixture");
    expect(target.searchParams.get("symbol")).toBe("SPOT");
    expect(target.searchParams.get("radar_session")).toBe("2026-10-20");
    expect(target.searchParams.get("radar_group")).toBeNull();
    expect(radarChartContext(target.searchParams)?.symbol).toBe("SPOT");
    const cohr = laggards.getByTestId("radar-mover").first();
    await expect(cohr).toContainText("COHR");
    await expect(cohr).toContainText("−13.3%");
    await expect(cohr).toContainText("Opening gap 0.0%");
    await expect(cohr).toContainText("Since open −13.3%");
    await expect(cohr).toContainText("−0.2%"); // last 15 min, from the earlier seeded pass
    await expect(panel.getByTestId("radar-mover-group").first()).toContainText("median");
    await expect(panel.getByTestId("radar-mover-group").first()).toContainText("most:");
    if (size === "phone") {
      const a = await leaders.boundingBox();
      const b = await laggards.boundingBox();
      expect(b!.y).toBeGreaterThan(a!.y + a!.height - 1); // stacked
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
    await panel.screenshot({ path: test.info().outputPath(`radar-movers-${size}.png`) });
    expect(errors).toEqual([]);
  });
}

for (const [status, line] of [["none_found", "No news found — cause unknown"], ["unavailable", "News unavailable — cause unknown"]] as const) {
  test(`radar says the cause is unknown when news is ${status}`, async ({ page, request }) => {
    expect((await request.post(`${API}/__test/radar-seed?news=${status}`)).ok()).toBeTruthy();
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto("/radar");
    const card = page.getByTestId("radar-event");
    await expect(card.getByTestId("radar-news-line")).toHaveText(line);
    await card.getByRole("button").first().click();
    const news = page.getByRole("region", { name: "News nearby" });
    await expect(news).toContainText(`${line}.`);
    await expect(news.getByRole("link")).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
    if (status === "none_found") await page.screenshot({ path: test.info().outputPath("radar-no-news-phone.png"), fullPage: true });
  });
}


test("a Radar phone alert tap opens the event and its Useful action saves the rating", async ({ page, request }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/radar?event=${EVENT}&rate=useful`);
  // The tap is the rating: saved before the event shows, then dropped from the address so a reload cannot repeat it.
  await expect(page.getByRole("region", { name: "Original evidence" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Useful", exact: true })).toHaveAttribute("aria-pressed", "true");
  const address = new URL(page.url());
  expect(address.searchParams.get("rate")).toBeNull();
  expect(address.searchParams.get("event")).toBe(EVENT);
  expect((await (await request.get(`${API}/radar/events/${EVENT}`)).json()).rating).toBe("useful");
  await page.screenshot({ path: test.info().outputPath("radar-alert-tap-phone.png"), fullPage: true });
  expect(errors).toEqual([]);
});


test("Radar navigation context rejects invalid dates and keeps return links internal", () => {
  const query = new URLSearchParams({ radar_symbol: "NVDA", radar_session: "2026-10-20",
    radar_at: "2026-10-20T15:12:00Z", radar_group: "AI & compute", radar_groups: "all", return: "https://example.com" });
  const context = radarChartContext(query)!;
  expect(context.group).toBe("AI & compute");
  expect(radarReturnHref(context)).toBe("/radar?session=2026-10-20&groups=all#radar-group-AI%20%26%20compute");
  for (const [key, value] of [["radar_symbol", "../bad"], ["radar_session", "2026-02-30"],
    ["radar_at", "bad"], ["radar_at", "2026-10-21T15:12:00Z"], ["radar_at", "2026-10-20T15:12:00"], ["radar_group", " "]]) {
    const invalid = new URLSearchParams(query); invalid.set(key, value);
    expect(radarChartContext(invalid)).toBeNull();
  }
  expect(radarSession("2026-02-30")).toBeUndefined();
  expect(radarSession("../../")).toBeUndefined();
});


test("Radar empty events and stale rankings remain explicit on phone", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.route("**/radar/feed*", async route => {
    const response = await route.fetch();
    const body = await response.json();
    await route.fulfill({ json: { ...body, events: [], since_last_visit: [] } });
  });
  await page.route("**/radar/movers?*", async route => {
    const response = await route.fetch();
    const body = await response.json();
    await route.fulfill({ json: { ...body, state: "stale", reason: "Recording has fallen behind; these numbers are from the last pass shown." } });
  });
  await page.goto("/radar");
  const empty = page.getByText("Radar has not produced any developments yet", { exact: false });
  await expect(empty).toBeVisible();
  const panel = page.getByTestId("radar-movers");
  await expect(panel).toContainText("Recording has fallen behind");
  await expect(panel).toContainText("missing or invalid timestamps are excluded");
  expect((await empty.boundingBox())!.y).toBeLessThan((await panel.boundingBox())!.y);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  await page.screenshot({ path: test.info().outputPath("radar-empty-stale-phone.png") });
});
