import { expect, test, type Page } from "@playwright/test";

// The e2e backend runs with the lab off, so these tests stand in only for its status read (and an empty
// investigation list). Nothing here sends a turn.
const API = `http://127.0.0.1:${Number(process.env.E2E_BACKEND_PORT || 8099)}`;
const ON = {
  enabled: true, backend: "fake", evidence: "fixture", model: "fake-scripted", effort: "medium", fallbacks: false,
  key_configured: false, tools: [], limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};

async function labOn(page: Page) {
  await page.route("**/copilot/status", (route) => route.fulfill({ json: ON }));
  await page.route("**/copilot/investigations?*", (route) => route.fulfill({ json: { investigations: [] } }));
}

async function openMuEvent(page: Page) {
  await page.goto("/radar");
  await page.getByRole("region", { name: "New since your last visit" }).getByTestId("radar-event").getByRole("button").first().click();
  await expect(page.getByRole("region", { name: "Original evidence" })).toContainText("As first saved");
}

test.beforeEach(async ({ request }) => {
  expect((await request.post(`${API}/__test/radar-seed`)).ok()).toBeTruthy();
});

/** Asserts after the status answer has arrived and React has painted, so an absent link is a real "no". */
async function noLinkOnceAnswered(page: Page, answered: Promise<unknown>) {
  await answered;
  await page.evaluate(() => new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done))));
  // Neither the link, the drawer button, the Charts dock tab nor the nav item.
  await expect(page.getByText(/^Ask copilot/)).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Copilot", exact: true })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Copilot", exact: true })).toHaveCount(0);
}

const statusAnswer = (page: Page) => page.waitForResponse((response) => response.url().includes("/copilot/status"));

async function noEntryPoints(page: Page) {
  let answered = statusAnswer(page);
  await openMuEvent(page);
  await expect(page.getByRole("link", { name: /Open chart · MU/ })).toBeVisible();
  await noLinkOnceAnswered(page, answered);
  answered = statusAnswer(page);
  await page.goto("/charts?symbol=MU");
  const info = page.getByRole("region", { name: "Symbol info", exact: true });
  await info.getByRole("tab", { name: "Overview", exact: true }).click();
  await noLinkOnceAnswered(page, answered);
}

test("no Ask copilot entry point while the lab is off", async ({ page }) => {
  await noEntryPoints(page);  // the e2e backend's own answer
});

for (const [label, reply] of [
  ["says off", { json: { enabled: false, reason: "Copilot Lab is off." } }],
  ["fails", { status: 500, json: { detail: "boom" } }],
] as const) {
  test(`no Ask copilot entry point in Radar or Charts when status ${label}`, async ({ page }) => {
    let reads = 0;
    await page.route("**/copilot/status", (route) => { reads += 1; return route.fulfill(reply); });
    await noEntryPoints(page);
    expect(reads).toBeGreaterThan(0);
  });
}

test("Radar's Ask copilot opens the copilot in place, prefilled with the event and unsent", async ({ page }) => {
  let chats = 0;
  await labOn(page);
  await page.route("**/copilot/chat", (route) => { chats += 1; return route.abort(); });
  await openMuEvent(page);
  await page.getByRole("button", { name: "Ask copilot · MU" }).click();
  const drawer = page.getByRole("dialog", { name: "Copilot for MU" });
  await expect(drawer.getByRole("heading", { name: "Copilot · MU" })).toBeVisible();
  await expect(drawer.getByLabel("Message")).toHaveValue(/^Context: Radar .+: MU up 4\.1% while SMH is up 0\.6%/);
  await expect(drawer.getByText(/Ask about an opportunity/)).toBeVisible(); // nothing was sent
  await expect(page).toHaveURL(/\/radar/); // still on Radar, beside the event
  await page.waitForTimeout(300);
  expect(chats).toBe(0);
  await drawer.getByRole("button", { name: "Close copilot" }).click();
  await expect(drawer).toHaveCount(0);
});

test("Radar's copilot drawer closes on Escape or its backdrop, and fills a phone", async ({ page }) => {
  await labOn(page);
  await openMuEvent(page);
  const ask = page.getByRole("button", { name: "Ask copilot · MU" });
  await ask.click();
  const drawer = page.getByRole("dialog", { name: "Copilot for MU" });
  await expect(drawer).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(drawer).toHaveCount(0);
  await expect(ask).toBeFocused(); // focus returns to the button that opened it
  await ask.click();
  await page.getByTestId("copilot-drawer-backdrop").click({ position: { x: 20, y: 300 } });
  await expect(drawer).toHaveCount(0);
  await page.setViewportSize({ width: 375, height: 812 });
  await ask.click();
  const box = (await drawer.boundingBox())!;
  expect([box.x, box.width]).toEqual([0, 375]); // full screen on a phone
  await expect(drawer.getByLabel("Message")).toHaveValue(/^Context: Radar .+MU up 4\.1%/);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
});

test("Charts' Overview offers Ask copilot for the current symbol", async ({ page }) => {
  await labOn(page);
  await page.goto("/charts?symbol=MU");
  const info = page.getByRole("region", { name: "Symbol info", exact: true });
  await info.getByRole("tab", { name: "Overview", exact: true }).click();
  await expect(info.getByRole("link", { name: "Ask copilot · MU" })).toHaveAttribute("href", "/copilot-lab?symbol=MU");
});

test("the lab fits a 375 px phone without sideways scrolling", async ({ page }) => {
  await labOn(page);
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/copilot-lab?symbol=NBIS&context=Radar%2010%3A41%20AM%3A%20NBIS%20up%203%25%20while%20its%20group%20is%20flat");
  await expect(page.getByLabel("Message")).toHaveValue(/^Context: Radar 10:41 AM/);
  const send = page.getByRole("button", { name: "Send" });
  await expect(send).toBeInViewport();
  expect((await send.boundingBox())!.height).toBeGreaterThanOrEqual(44); // a thumb-sized target
  expect(await page.getByLabel("Message").evaluate((box) => getComputedStyle(box).fontSize)).toBe("16px"); // iOS does not zoom
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
  await page.screenshot({ path: test.info().outputPath("copilot-lab-375.png") });
});
