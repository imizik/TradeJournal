import { expect, test } from "@playwright/test";

const session = "2026-11-04";
const picks = [
  { symbol: "ANET", direction: "up", relative_volume: 2.5, sector_lead_pct: 1.2,
    opening_bars: [102, 101, 102, null, 102, 103, 102, 103, 104, 105].map((o, i) =>
      o === null ? null : { o, h: o + 1, l: o - 1, c: o + (i % 3 === 1 ? -0.8 : 0.5) }) },
  { symbol: "MU", direction: "down", relative_volume: 2.1, sector_lead_pct: 0.8 },
];

function body(overrides: Record<string, unknown> = {}) {
  return {
    day: session, today: session, now: `${session}T09:40:30-05:00`,
    sessions: [session],
    live: { day: session, captured_at: `${session}T09:40:05-05:00`, feed: "iex", eligible: 143, picks, movers: [] },
    recap: null, decisions: [], ...overrides,
  };
}

test("dashboard records one timely paper choice per shown direction", async ({ page }) => {
  await page.clock.install({ time: new Date("2026-11-04T14:40:30Z") });
  const saved: Array<{ symbol: string; choice: string }> = [];
  await page.route("**/scalp-shortlist**", async (route) => {
    if (route.request().method() === "POST") {
      const decision = route.request().postDataJSON();
      saved.push(decision);
      return route.fulfill({ json: { ...decision, decided_at: `${session}T09:40:45-05:00`, timely: true } });
    }
    return route.fulfill({ json: body({ decisions: saved.map((decision) => ({ ...decision, decided_at: `${session}T09:40:45-05:00`, timely: true })) }) });
  });
  await page.goto("/");
  const panel = page.getByTestId("scalp-shortlist");
  await expect(panel.getByText("ANET")).toBeVisible();
  await expect(panel.getByText("DOWN")).toBeVisible();
  await expect(panel.getByText(/Live IEX preview/).first()).toBeVisible();
  const candles = panel.getByRole("img", { name: /ANET, 9:30–9:39 ET, 9 one-minute candles/ });
  await expect(candles.locator("rect")).toHaveCount(9);
  await expect(candles.locator("rect").nth(3)).toHaveAttribute("x", "42");
  await expect(panel.getByTestId("scalp-pick-MU")).toContainText("Opening chart unavailable");
  const popup = page.waitForEvent("popup");
  await panel.getByRole("link", { name: "Open ANET chart in a new tab" }).click();
  const chart = await popup;
  await expect(chart).toHaveURL(/\/charts\?symbol=ANET$/);
  await expect(chart.getByRole("textbox", { name: "Chart symbol", exact: true })).toHaveAttribute("placeholder", "ANET");
  await chart.close();
  await page.getByTestId("scalp-pick-ANET").screenshot({ path: test.info().outputPath("scalp-shortlist-live-card.png") });
  await page.setViewportSize({ width: 390, height: 844 });
  await panel.screenshot({ path: test.info().outputPath("scalp-shortlist-live-phone.png") });
  await panel.getByTestId("scalp-pick-ANET").getByRole("button", { name: "Take" }).click();
  await expect(panel.getByText("Take · before 9:41")).toBeVisible();
  await panel.getByTestId("scalp-pick-MU").getByRole("button", { name: "Pass" }).click();
  await expect(panel.getByText("Pass · before 9:41")).toBeVisible();
  expect(saved).toEqual([{ symbol: "ANET", choice: "take" }, { symbol: "MU", choice: "pass" }]);

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByTestId("scalp-pick-ANET").getByRole("button", { name: "Take" })).toHaveCount(0);
  await expect(page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).resolves.toBeTruthy();
  await page.screenshot({ path: test.info().outputPath("scalp-shortlist-dashboard-phone.png"), animations: "disabled" });
});

test("Practice opens the official and shown outcomes for the selected morning", async ({ page }) => {
  await page.clock.install({ time: new Date("2026-11-04T15:20:00Z") });
  const recap = { day: session, captured_at: `${session}T10:15:00-05:00`, eligible: 143,
    shown: [{ symbol: "ANET", direction: "up", return_pct: 0.82 }, { symbol: "MU", direction: "down", return_pct: -0.4 }],
    official: [{ symbol: "ANET", direction: "up", return_pct: 0.82 }],
    movers: [{ symbol: "MU", direction: "down", return_pct: 0.4 }] };
  await page.route("**/scalp-shortlist**", (route) => route.fulfill({ json: body({ recap, today: "2026-11-05",
    decisions: [{ symbol: "ANET", choice: "take", decided_at: `${session}T09:40:45-05:00`, timely: true }] }) }));
  await page.goto("/practice#scalp-shortlist");
  const panel = page.getByTestId("scalp-shortlist");
  await expect(panel.getByLabel("Study morning")).toBeVisible();
  const open = Date.parse(`${session}T09:30:00-05:00`) / 1000;
  await expect(panel.getByRole("link", { name: "Open ANET chart in a new tab" }))
    .toHaveAttribute("href", `/charts?symbol=ANET&from=${open}&to=${open + 9 * 60}`);
  await expect(panel.getByTestId("scalp-recap")).toContainText("ANET UP · Take · also an official pick");
  await expect(panel.getByTestId("scalp-recap")).toContainText("MU DOWN · no response · not an official pick");
  await expect(panel.getByTestId("scalp-recap")).toContainText("+0.82%");
  await expect(panel.getByTestId("scalp-recap")).toContainText("Biggest movers · MU DOWN +0.40%");
  await panel.getByTestId("scalp-recap").screenshot({ path: test.info().outputPath("scalp-shortlist-recap.png") });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).resolves.toBeTruthy();
  await page.screenshot({ path: test.info().outputPath("scalp-shortlist-recap-phone.png"), animations: "disabled" });
});

test("changing the study morning ignores a late response for the previous morning", async ({ page }) => {
  const other = "2026-11-05";
  await page.clock.install({ time: new Date("2026-11-06T15:00:00Z") });
  let releasePrevious!: () => void;
  const previousPending = new Promise<void>((resolve) => { releasePrevious = resolve; });
  let previousLoads = 0;
  await page.route("**/scalp-shortlist**", async (route) => {
    const url = new URL(route.request().url());
    const day = url.searchParams.get("day");
    if (day === session && previousLoads++ === 0) {
      await previousPending;
      return route.fulfill({ json: body({ day: session, today: "2026-11-06", sessions: [session, other], live: null, recap: null }) });
    }
    if (day === null) return route.fulfill({ json: body({ today: "2026-11-06", sessions: [session, other] }) });
    const selected = day === other ? other : session;
    return route.fulfill({ json: body({ day: selected, today: "2026-11-06", sessions: [session, other], live: null,
      recap: { day: selected, captured_at: `${selected}T10:15:00-04:00`, eligible: 140,
        official: [{ symbol: selected === other ? "MU" : "ANET", direction: "up", return_pct: 0.25 }], shown: [], movers: [] } }) });
  });
  await page.goto("/practice#scalp-shortlist");
  const panel = page.getByTestId("scalp-shortlist");
  await expect(panel.getByLabel("Study morning")).toBeVisible();
  await panel.getByLabel("Study morning").selectOption(other);
  await expect(panel.getByTestId("scalp-recap")).toContainText("MU UP");
  await panel.getByLabel("Study morning").selectOption(session);
  await expect(panel.getByText(`Loading ${session} paper study…`)).toBeVisible();
  await panel.getByLabel("Study morning").selectOption(other);
  await expect(panel.getByTestId("scalp-recap")).toContainText("MU UP");
  releasePrevious();
  await expect(panel.getByLabel("Study morning")).toHaveValue(other);
  await expect(panel.getByTestId("scalp-recap")).toContainText("MU UP");
});

test("Practice keeps a pending paper decision attached to its morning", async ({ page }) => {
  await page.clock.install({ time: new Date("2026-11-04T14:40:30Z") });
  let finish!: () => void;
  const pending = new Promise<void>((resolve) => { finish = resolve; });
  await page.route("**/scalp-shortlist**", async (route) => {
    if (route.request().method() === "POST") await pending;
    return route.fulfill({ json: body() });
  });
  await page.goto("/practice#scalp-shortlist");
  const panel = page.getByTestId("scalp-shortlist");
  await panel.getByTestId("scalp-pick-ANET").getByRole("button", { name: "Take" }).click();
  try {
    await expect(panel.getByLabel("Study morning")).toBeDisabled();
  } finally {
    finish();
  }
  await expect(panel.getByLabel("Study morning")).toBeEnabled();
});

test("a temporary read failure recovers while the morning card is open", async ({ page }) => {
  await page.clock.install({ time: new Date("2026-11-04T14:40:05Z") });
  let reads = 0;
  await page.route("**/scalp-shortlist**", (route) => ++reads === 1
    ? route.fulfill({ status: 503, json: { detail: "Temporarily unavailable" } })
    : route.fulfill({ json: body() }));
  await page.goto("/practice#scalp-shortlist");
  const panel = page.getByTestId("scalp-shortlist");
  await expect(panel.getByRole("alert")).toContainText("503");
  await page.clock.fastForward(11_000);
  await expect(panel.getByTestId("scalp-pick-ANET")).toBeVisible();
});

test("private frontend forwards the study and paper decisions to the actual backend", async ({ request }) => {
  const path = "/api/backend/scalp-shortlist";
  const sessionView = await request.get(path, { params: { day: session } });
  expect(sessionView.status()).toBe(200);
  expect(await sessionView.json()).toMatchObject({ day: session, sessions: expect.arrayContaining([session]) });
  // An out-of-study day exercises the decision handler without recording a choice.
  const rejected = await request.post(`${path}/2026-11-03/decisions`, { data: { symbol: "NVDA", choice: "pass" } });
  expect(rejected.status()).toBe(404);
  expect(await rejected.json()).toEqual({ detail: "Outside the study" });
});
