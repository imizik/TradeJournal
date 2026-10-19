import { expect, test } from "@playwright/test";

const day = "2026-10-19";
async function seed(page: import("@playwright/test").Page) {
  const packetResponse = await page.request.post("/api/backend/jo/packets", { data: {
    operation_id: `morning-${crypto.randomUUID()}`, day, as_of: `${day}T12:45:00Z`, scope: "Invented approved-account context and saved Charts watchlist",
    evidence: [{ id: "watchlist", kind: "fact", text: "Saved Charts watchlist: MU, SPY", source: "Charts saved workspace", observed_at: `${day}T12:00:00Z`, retrieved_at: `${day}T12:45:00Z` },
      { id: "thesis", kind: "belief", text: "I want confirmation before adding to MU.", source: "Explicit owner memory", observed_at: `${day}T12:00:00Z`, retrieved_at: `${day}T12:45:00Z` },
      { id: "schedule", kind: "fact", text: JSON.stringify({ deadline: `${day}T13:15:00Z` }), source: "Morning publication schedule", retrieved_at: `${day}T12:45:00Z` }],
    gaps: ["No live quote or verified earnings date; check current conditions."], memory_revision_ids: [],
  } });
  expect(packetResponse.ok()).toBeTruthy();
  const packet = await packetResponse.json();
  const body = { operation_id: `brief-${crypto.randomUUID()}`, packet_id: packet.id, author: "Jo", prompt_version: "browser-fixture",
    summary: "Keep MU on watch. Your saved preference is to wait for confirmation; this packet does not establish a new entry.",
    summary_evidence_ids: ["watchlist", "thesis"], items: [{ symbol: "MU", what_matters: "MU remains on your saved watchlist.",
      why_personal: "You asked to wait for confirmation before adding.", what_changed: "No prior brief was supplied, so change is unverified.",
      contrary_evidence: "This is a preference, not proof that price will rise.", watch_out: "Confirm the current price and earnings date. Waiting is a valid choice.", evidence_ids: ["watchlist", "thesis"] }],
    limitations: ["Invented browser fixture; no trading action is implied."] };
  const response = await page.request.post("/api/backend/jo/briefings", { data: body });
  expect(response.ok()).toBeTruthy();
  const brief = await response.json();
  expect((await (await page.request.post("/api/backend/jo/briefings", { data: body })).json()).id).toBe(brief.id);
  return { packet, brief, body };
}

test("saved morning brief reopens, cites evidence, links Charts and persists feedback on phone", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const { brief } = await seed(page);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(`/morning?day=${day}&id=${brief.id}`);
  const panel = page.getByTestId("morning-briefing");
  await expect(panel).toContainText("Keep MU on watch.");
  await expect(panel).toContainText("Arrived after the deadline");
  await expect(page.getByRole("link", { name: "Open MU chart" })).toHaveAttribute("href", "/charts?symbol=MU");
  await page.screenshot({ path: test.info().outputPath("morning-brief-desktop.png") });
  await expect(page.getByText("Confirm the current price and earnings date. Waiting is a valid choice.", { exact: true })).toBeVisible();
  await expect(page.getByText("This is a preference, not proof that price will rise.", { exact: true })).not.toBeVisible();
  await page.getByText("Reasoning and sources", { exact: true }).click();
  await panel.getByRole("link", { name: "thesis", exact: true }).first().click();
  await expect(page.getByText("I want confirmation before adding to MU.", { exact: true })).toBeVisible();
  await expect(page.getByText("thesis · Belief / interpretation")).toBeVisible();
  await page.getByText("Continue with Jo", { exact: true }).click();
  await expect(page.getByLabel("Jo context reference")).toHaveValue(new RegExp(brief.id));
  await page.getByRole("button", { name: "Useful", exact: true }).click();
  await expect(page.getByRole("button", { name: "Useful", exact: true })).toHaveAttribute("aria-pressed", "true");
  await page.reload();
  await expect(page.getByRole("button", { name: "Useful", exact: true })).toHaveAttribute("aria-pressed", "true");
  const saved = await (await page.request.get(`/api/backend/jo/morning?day=${day}&briefing_id=${brief.id}`)).json();
  expect(saved.feedback.first_opened_at).toBeTruthy();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: test.info().outputPath("morning-brief-phone.png") });
  const missed = page.getByRole("button", { name: "Missed something", exact: true });
  await missed.scrollIntoViewIfNeeded();
  await expect(missed).toBeInViewport();
  await missed.click();
  await expect(missed).toHaveAttribute("aria-pressed", "true");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await page.getByRole("link", { name: "Open MU chart" }).click();
  await expect(page).toHaveURL(/\/charts\?symbol=MU/);
  expect(errors).toEqual([]);
});

test("briefing date never falls back, versions stay explicit and load/feedback failures are honest", async ({ page }) => {
  const { brief, body } = await seed(page);
  const correction = await (await page.request.post("/api/backend/jo/briefings", { data: { ...body,
    operation_id: `correct-${crypto.randomUUID()}`, summary: "Corrected morning view", items: [], supersedes_id: brief.id } })).json();
  await page.goto(`/morning?day=${day}&id=${correction.id}`);
  await expect(page.getByTestId("morning-briefing")).toContainText("Corrected morning view");
  await expect(page.getByText("No supported priority in this briefing.", { exact: false })).toBeVisible();
  await page.getByText("Date and saved versions", { exact: true }).click();
  await page.getByLabel("Saved version").selectOption(brief.id);
  await expect(page.getByTestId("morning-briefing")).toContainText("Keep MU on watch.");
  await page.route("**/jo/briefings/*/feedback", (route) => route.fulfill({ status: 503, json: { detail: "Fixture unavailable" } }));
  await page.getByRole("button", { name: "Meh", exact: true }).click();
  await expect(page.getByTestId("morning-briefing").getByRole("alert")).toContainText("Feedback was not saved");
  await page.getByLabel("Briefing date").fill("2026-01-01");
  await expect(page.getByTestId("morning-briefing")).toContainText("No briefing has been saved for this date");
  await expect(page.getByTestId("morning-briefing")).not.toContainText("Keep MU on watch");
  await page.screenshot({ path: test.info().outputPath("morning-missing-desktop.png") });
  await page.route("**/jo/morning?**", (route) => route.fulfill({ status: 503, json: { detail: "Fixture unavailable" } }));
  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  await expect(page.getByTestId("morning-briefing").getByRole("alert")).toContainText("The briefing could not load");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: test.info().outputPath("morning-error-phone.png") });
});


test("verbose saved briefs retain exact text behind details while risks stay visible", async ({ page }) => {
  const { body } = await seed(page);
  const longSummary = "Manual activation test; exact source timestamps and receipt checks. ".repeat(12);
  const diagnostic = "operation_id morning-fixture; independence-unverified; no live research used.";
  const response = await page.request.post("/api/backend/jo/briefings", { data: { ...body,
    operation_id: `legacy-${crypto.randomUUID()}`, summary: longSummary, limitations: [diagnostic] } });
  expect(response.ok()).toBeTruthy();
  const brief = await response.json();
  await page.goto(`/morning?day=${day}&id=${brief.id}`);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByText(longSummary.trim(), { exact: true })).not.toBeVisible();
  await expect(page.getByText(diagnostic, { exact: true })).not.toBeVisible();
  await expect(page.getByText("Confirm the current price and earnings date. Waiting is a valid choice.", { exact: true })).toBeVisible();
  await expect(page.getByText(/Based on saved context, not verified live holdings or prices/)).toBeVisible();
  await page.getByText("Read Jo’s full summary", { exact: true }).click();
  await expect(page.getByText(longSummary.trim(), { exact: true })).toBeVisible();
  await page.getByText("Read Jo’s full summary", { exact: true }).click();
  await page.getByText("Limited coverage · Sources, gaps and delivery details", { exact: true }).click();
  await expect(page.getByText(diagnostic, { exact: true })).toBeVisible();
  await expect(page.getByText("No live quote or verified earnings date; check current conditions.", { exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
});
