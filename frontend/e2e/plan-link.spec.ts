import { expect, test, type Page } from "@playwright/test";

// The one-tap plan link page the link ping opens (/plans/link?trade=). Its data read and the existing capture link
// route are faked; the ping, the candidates and the link rules are covered in pytest (test_plan_nudges.py).
const TRADE = "11111111-2222-4333-8444-555555555555";
const INV = "7d3f1b2a-0000-4000-8000-000000000abc";
const at = Date.parse("2026-10-21T14:00:00Z") / 1000; // 10:00 New York
const plan = (id: string, setup: string, minutesBefore: number, extra: object = {}) => ({
  capture_id: `aaaaaaaa-0000-4000-8000-00000000000${id}`, setup, mode: "discretionary", wording: "Entry: above 98. Invalidation: below 92.50.",
  note: "Thesis: the group recovers.", received_at: at - minutesBefore * 60, timing: minutesBefore > 0 ? "pre_entry" : "unverified",
  investigation_id: null, ...extra });
const page_ = (candidates: object[], linked: object[] = []) => ({
  trade: { id: TRADE, ticker: "NBIS", contract: "NBIS 11/21/26 100C", status: "open", opened: "opened", fill: "2 at $3.10",
    opened_at: at, opened_at_reliable: true },
  candidates, linked, plan_path: "/copilot-lab?symbol=NBIS&context=Plan%20this%20position%3A%20I%20just%20opened%20NBIS",
});

async function serve(page: Page, body: object, link: (id: string) => { status: number; json: object }) {
  const posted: string[] = [];
  await page.route(`**/trades/${TRADE}/plan-link`, route => route.fulfill({ json: body }));
  await page.route("**/charts/captures/*/link", async route => {
    const id = route.request().url().split("/captures/")[1].split("/")[0];
    posted.push(`${id} ${JSON.parse(route.request().postData() ?? "{}").trade_id}`);
    const answer = link(id);
    await route.fulfill({ status: answer.status, json: answer.json });
  });
  return posted;
}

test.beforeEach(async ({ page }) => { await page.setViewportSize({ width: 375, height: 812 }); });

test("one candidate: Link is one big tap at 375 px, then Linked with the trade and its investigation", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  const only = plan("1", "Copilot plan", 2, { investigation_id: INV });
  const posted = await serve(page, page_([only]), () => ({ status: 200, json: {} }));
  await page.goto(`/plans/link?trade=${TRADE}`);
  await expect(page.getByText("NBIS 11/21/26 100C")).toBeVisible();
  await expect(page.getByText("Opened 2 at $3.10 at 10:00:00 AM ET")).toBeVisible();
  await expect(page.getByText("Was this your plan?")).toBeVisible();
  await expect(page.getByText("Before entry")).toBeVisible();
  const link = page.getByRole("button", { name: "Link", exact: true });
  const box = (await link.boundingBox())!;
  expect(box.height).toBeGreaterThanOrEqual(44);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
  await page.screenshot({ path: test.info().outputPath("plan-link-375.png"), fullPage: true });
  await link.click();
  const done = page.getByRole("region", { name: "Linked" });
  await expect(done.getByRole("heading", { name: "Linked" })).toBeVisible();
  await expect(done.getByRole("link", { name: "Open the trade" })).toHaveAttribute("href", `/trades/${TRADE}`);
  await expect(done.getByRole("link", { name: "Open its investigation" })).toHaveAttribute("href", `/copilot-lab?investigation=${INV}`);
  expect(posted).toEqual([`${only.capture_id} ${TRADE}`]);
  await page.screenshot({ path: test.info().outputPath("plan-link-done-375.png"), fullPage: true });
  expect(errors).toEqual([]);
});

test("several candidates: each has its own Link, and the chosen one is the one linked", async ({ page }) => {
  const first = plan("1", "Group recovery", 3), second = plan("2", "Copilot plan", 0);
  const posted = await serve(page, page_([first, second]), () => ({ status: 200, json: {} }));
  await page.goto(`/plans/link?trade=${TRADE}`);
  await expect(page.getByText("2 of your saved plans match this fill. Which one was it?")).toBeVisible();
  await expect(page.getByRole("button", { name: /^Link / })).toHaveCount(2);
  await expect(page.getByText("Timing unverified")).toBeVisible();
  for (const button of await page.getByRole("button", { name: /^Link / }).all())
    expect((await button.boundingBox())!.height).toBeGreaterThanOrEqual(44);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
  await page.getByRole("button", { name: /^Link Copilot plan/ }).click();
  await expect(page.getByRole("heading", { name: "Linked" })).toBeVisible();
  await expect(page.getByText(/linked to your plan .Copilot plan./)).toBeVisible();
  await expect(page.getByRole("link", { name: "Open its investigation" })).toHaveCount(0); // not from the copilot
  expect(posted).toEqual([`${second.capture_id} ${TRADE}`]);
});

test("a refused link says why and changes nothing here", async ({ page }) => {
  const only = plan("1", "Group recovery", 2);
  await serve(page, page_([only]), () => ({ status: 422,
    json: { detail: "That trade already has a plan linked. A re-entry is a new trade and needs its own plan." } }));
  await page.goto(`/plans/link?trade=${TRADE}`);
  await page.getByRole("button", { name: "Link", exact: true }).click();
  await expect(page.getByRole("alert")).toHaveText("Not linked. That trade already has a plan linked. A re-entry is a new trade and needs its own plan.");
  await expect(page.getByRole("heading", { name: "Linked" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Link", exact: true })).toBeEnabled();
});

test("already linked when opened: shows the linked plan, nothing to tap", async ({ page }) => {
  await serve(page, page_([], [plan("1", "Group recovery", 2)]), () => ({ status: 500, json: {} }));
  await page.goto(`/plans/link?trade=${TRADE}`);
  await expect(page.getByRole("heading", { name: "Already linked" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Link", exact: true })).toHaveCount(0);
});

test("Not this plan links nothing and offers Plan it now", async ({ page }) => {
  const posted = await serve(page, page_([plan("1", "Group recovery", 2)]), () => ({ status: 200, json: {} }));
  await page.goto(`/plans/link?trade=${TRADE}`);
  await page.getByRole("button", { name: "Not this plan" }).click();
  await expect(page.getByText("Nothing was linked. You can close this page.")).toBeVisible();
  await expect(page.getByRole("link", { name: "Plan it now" })).toHaveAttribute("href", /^\/copilot-lab\?symbol=NBIS&context=Plan/);
  const plan_ = (await page.getByRole("link", { name: "Plan it now" }).boundingBox())!;
  expect(plan_.height).toBeGreaterThanOrEqual(44);
  expect(posted).toEqual([]);
});
