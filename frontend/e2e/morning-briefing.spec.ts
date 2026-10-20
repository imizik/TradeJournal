import { expect, test } from "@playwright/test";

const day = "2026-10-19";
async function seed(page: import("@playwright/test").Page) {
  const memoryResponse = await page.request.post("/api/backend/jo/memories", { data: {
    operation_id: `memory-${crypto.randomUUID()}`, kind: "thesis", symbol: "MU", original_text: "I want confirmation before adding to MU.",
    interpretation: "Wait for a confirmed move before adding shares.", source: "owner_statement", status: "active", owner_confirmed: true } });
  expect(memoryResponse.ok()).toBeTruthy();
  const memory = await memoryResponse.json();
  const packetResponse = await page.request.post("/api/backend/jo/packets", { data: {
    operation_id: `morning-${crypto.randomUUID()}`, day, as_of: memory.received_at, scope: "Invented approved-account context and saved Charts watchlist",
    evidence: [{ id: "watchlist", kind: "fact", text: "Saved Charts watchlist: MU, SPY", source: "Charts saved workspace", observed_at: `${day}T12:00:00Z`, retrieved_at: `${day}T12:45:00Z` },
      { id: "thesis", kind: "belief", text: "I want confirmation before adding to MU.", source: "Explicit owner memory; not a market fact", observed_at: memory.received_at, retrieved_at: memory.received_at },
      { id: "position-1", kind: "fact", text: JSON.stringify({ instrument: "option", symbol: "MU", strike: 120, expiration: "2026-10-23", open_quantity: 2, cost_unit: "USD per contract" }), source: "Saved journal fills; FIFO remaining lots", retrieved_at: `${day}T12:45:00Z` },
      { id: "position-2", kind: "fact", text: JSON.stringify({ instrument: "stock", symbol: "MU", open_quantity: 10, cost_unit: "USD per share" }), source: "Saved journal fills; FIFO remaining lots", retrieved_at: `${day}T12:45:00Z` },
      { id: "market-MU", kind: "fact", text: "MU: last reported trade $118.40; recent at collection (age 6 seconds).", source: "Alpaca IEX latest trade; not a consolidated executable quote", observed_at: `${day}T12:44:54Z`, retrieved_at: `${day}T12:45:00Z` },
      { id: "headline-1", kind: "fact", text: "MU — Invented fixture headline about memory pricing", source: "Alpaca / Benzinga headline; article claims are not independently verified", observed_at: `${day}T11:30:00Z`, retrieved_at: `${day}T12:45:00Z` },
      { id: "schedule", kind: "fact", text: JSON.stringify({ deadline: `${day}T13:15:00Z` }), source: "Morning publication schedule", retrieved_at: `${day}T12:45:00Z` }],
    gaps: ["No live quote or verified earnings date; check current conditions."], memory_revision_ids: [memory.id],
  } });
  expect(packetResponse.ok()).toBeTruthy();
  const packet = await packetResponse.json();
  const body = { operation_id: `brief-${crypto.randomUUID()}`, packet_id: packet.id, author: "Jo", prompt_version: "browser-fixture",
    summary: "Keep MU on watch. Your saved preference is to wait for confirmation; this packet does not establish a new entry.",
    summary_evidence_ids: ["watchlist", "thesis"], items: [{ symbol: "MU", what_matters: "MU remains on your saved watchlist.",
      why_personal: "You asked to wait for confirmation before adding.", what_changed: "No prior brief was supplied, so change is unverified.",
      contrary_evidence: "This is a preference, not proof that price will rise.", watch_out: "Confirm the current price and earnings date. Waiting is a valid choice.", evidence_ids: ["watchlist", "thesis", "position-1", "position-2", "market-MU", "headline-1"] },
      { symbol: null, what_matters: "Confirm the journal import finished before relying on the two MU option contracts shown as open.", why_personal: "Your saved fills are the only position record in this packet.",
        what_changed: "First brief for this account scope; no earlier comparison.", contrary_evidence: "Saved fills can lag the broker.", watch_out: "Check the Fills page for this morning's import before acting.", evidence_ids: ["position-1", "position-2"] }],
    limitations: ["Invented browser fixture; no trading action is implied."] };
  const response = await page.request.post("/api/backend/jo/briefings", { data: body });
  expect(response.ok()).toBeTruthy();
  const brief = await response.json();
  expect((await (await page.request.post("/api/backend/jo/briefings", { data: body })).json()).id).toBe(brief.id);
  return { packet, brief, body, memory };
}

test("saved morning brief reopens, cites evidence, links Charts and persists feedback on phone", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const { brief, packet, memory } = await seed(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/morning?day=${day}&id=${brief.id}`);
  await expect(page.getByText("You asked to wait for confirmation before adding.", { exact: true })).toBeInViewport();
  // The first priority's reason sits above the phone tab bar without opening anything.
  expect(await page.evaluate(() => {
    const why = [...document.querySelectorAll("dd")].find((d) => d.textContent === "You asked to wait for confirmation before adding.");
    const bar = [...document.querySelectorAll("nav")].find((n) => getComputedStyle(n).position === "fixed" && n.getBoundingClientRect().bottom >= window.innerHeight - 1);
    return !!why && why.getBoundingClientRect().bottom <= (bar ? bar.getBoundingClientRect().top : window.innerHeight);
  })).toBeTruthy();
  await page.screenshot({ path: test.info().outputPath("morning-brief-phone-first-screen.png") });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(`/morning?day=${day}&id=${brief.id}`);
  const panel = page.getByTestId("morning-briefing");
  await expect(panel).toContainText("Keep MU on watch.");
  await expect(panel).toContainText("Arrived after the deadline");
  await expect(page.getByRole("link", { name: "Open MU chart" })).toHaveAttribute("href", "/charts?symbol=MU");
  await page.screenshot({ path: test.info().outputPath("morning-brief-desktop.png") });
  await expect(page.getByText("Confirm the current price and earnings date. Waiting is a valid choice.", { exact: true })).toBeVisible();
  await expect(page.getByText("This is a preference, not proof that price will rise.", { exact: true })).toBeVisible();
  await expect(panel).toContainText("Saved journal fills ×2");
  await expect(panel).toContainText("Alpaca IEX latest trade · observed 8:44 AM ET");
  await expect(page.getByRole("link", { name: "Open null chart" })).toHaveCount(0);
  await panel.getByRole("link", { name: "Explicit owner memory", exact: true }).first().click();
  await expect(page.getByText("I want confirmation before adding to MU.", { exact: true })).toBeVisible();
  await expect(page.getByText("Explicit owner memory · Belief / interpretation")).toBeVisible();
  await expect(page.locator("#evidence-thesis code")).toHaveText("thesis");
  // The priority names the exact saved revision it relied on; a later correction does not rewrite it.
  const correction = await page.request.post("/api/backend/jo/memories", { data: { operation_id: `memory-fix-${crypto.randomUUID()}`, memory_id: memory.memory_id, base_revision: 1,
    kind: "thesis", symbol: "MU", original_text: "Corrected later: I would add MU on any dip.", source: "owner_statement", status: "active", owner_confirmed: true } });
  expect(correction.ok()).toBeTruthy();
  await page.reload();
  const mu = page.getByRole("article").filter({ hasText: "MU remains on your saved watchlist." });
  await expect(mu.getByText("Your saved view")).toBeVisible();
  await expect(mu).toContainText("Thesis · MU · revision 1");
  await expect(panel).not.toContainText("Corrected later");
  await mu.screenshot({ path: test.info().outputPath("morning-saved-view-desktop.png") });
  await mu.getByRole("link", { name: "“I want confirmation before adding to MU.”" }).click();
  const saved = page.locator(`[id="memory-${memory.id}"]`);
  await expect(saved).toBeVisible();
  await expect(saved).toContainText("Interpretation: Wait for a confirmed move before adding shares.");
  await expect(saved.locator("code").first()).toHaveText(memory.id);
  await expect(page.locator("#evidence-thesis")).toContainText("memory revision 1");
  await expect(page.getByRole("article").filter({ hasText: "Confirm the journal import" }).getByText("Your saved view")).toHaveCount(0);
  await page.getByRole("button", { name: "Ask Jo about MU" }).click();
  await page.getByLabel("Your question for Jo (optional)").fill("Should I wait for the open?");
  const reference = page.getByLabel("Jo context reference");
  await expect(reference).toHaveValue(new RegExp(`Briefing ID: ${brief.id}`));
  await expect(reference).toHaveValue(new RegExp(`Packet ID: ${packet.id}`));
  await expect(reference).toHaveValue(/Priority 1: MU — MU remains on your saved watchlist\./);
  await expect(reference).toHaveValue(/Evidence IDs: watchlist, thesis, position-1/);
  await expect(reference).toHaveValue(/My question: Should I wait for the open\?/);
  await expect(reference).toHaveValue(new RegExp(`Saved memory revisions used: ${memory.id}`));
  await page.getByRole("button", { name: "Copy for Jo" }).click();
  await expect(panel.getByRole("status").filter({ hasText: "Copied" })).toBeVisible();
  await page.evaluate(() => {
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText: () => Promise.reject(new Error("denied")) } });
    document.execCommand = () => false;
  });
  await page.getByRole("button", { name: "Copy for Jo" }).click();
  await expect(panel.getByRole("status").filter({ hasText: "Couldn’t copy" })).toBeVisible();
  await page.getByRole("button", { name: "Useful", exact: true }).click();
  await expect(page.getByRole("button", { name: "Useful", exact: true })).toHaveAttribute("aria-pressed", "true");
  await page.reload();
  await expect(page.getByRole("button", { name: "Useful", exact: true })).toHaveAttribute("aria-pressed", "true");
  const reopened = await (await page.request.get(`/api/backend/jo/morning?day=${day}&briefing_id=${brief.id}`)).json();
  expect(reopened.feedback.first_opened_at).toBeTruthy();
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
  await page.getByText("Dates & versions", { exact: true }).click();
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
  const summaryToggle = page.getByRole("button", { name: "Read Jo’s full summary" });
  await expect(summaryToggle).toHaveAttribute("aria-expanded", "false");
  await expect(page.getByTestId("brief-summary")).toHaveClass(/line-clamp-4/);
  await expect(page.getByText(diagnostic, { exact: true })).not.toBeVisible();
  await expect(page.getByText("Confirm the current price and earnings date. Waiting is a valid choice.", { exact: true })).toBeVisible();
  await expect(page.getByText(/Frozen briefing, not a live price feed/)).toBeVisible();
  await summaryToggle.click();
  await expect(page.getByRole("button", { name: "Show less" })).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByTestId("brief-summary")).not.toHaveClass(/line-clamp-4/);
  await expect(page.getByText(longSummary.trim(), { exact: true })).toBeVisible();
  await page.getByText(/^Limited coverage · \d+ gaps disclosed$/).click();
  await expect(page.getByText(diagnostic, { exact: true })).toBeVisible();
  await expect(page.getByText("No live quote or verified earnings date; check current conditions.", { exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
});

test("delivery states stay explicit: stale, late, missing, waiting, closed, redacted and unknown automation", async ({ page }) => {
  const { brief } = await seed(page);
  const base = await (await page.request.get(`/api/backend/jo/morning?day=${day}&briefing_id=${brief.id}`)).json();
  let view = base;
  await page.route("**/jo/morning?**", (route) => route.fulfill({ json: view }));
  await page.setViewportSize({ width: 390, height: 844 });
  view = { ...base, late: true, stale: true, automation: { ...base.automation, unavailable: true } };
  await page.goto(`/morning?day=${day}&id=${brief.id}`);
  const panel = page.getByTestId("morning-briefing");
  await expect(panel).toContainText("Late");
  await expect(panel).toContainText("Arrived after the deadline.");
  await expect(panel).toContainText("Evidence is at least four hours old; verify current conditions.");
  await expect(panel).toContainText("Automatic delivery status is unavailable.");
  await page.screenshot({ path: test.info().outputPath("morning-late-stale-phone.png") });
  view = { ...base, packet: { ...base.packet, memories: [] } };
  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  await expect(panel).toContainText("No saved beliefs or preferences were in this packet");
  await expect(panel.getByText("Your saved view")).toHaveCount(0);
  for (const [state, text] of [["missing", "No briefing was saved by the deadline. Yesterday’s brief is not shown as today’s."],
    ["waiting", "Jo’s briefing has not arrived yet."], ["closed", "closed exchange session"], ["redacted", "This briefing or its evidence was removed."]] as const) {
    view = { ...base, state, late: false, stale: false, briefing: state === "missing" || state === "waiting" || state === "closed" ? null : base.briefing };
    await page.getByRole("button", { name: "Refresh", exact: true }).click();
    await expect(panel).toContainText(text);
    await expect(panel).not.toContainText("Keep MU on watch");
    await expect(page.getByRole("button", { name: "Useful", exact: true })).toHaveCount(0);
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
});

test("memory review: accept, decline, correct, retire and add beliefs with honest conflicts and retries", async ({ page }) => {
  const tag = crypto.randomUUID().slice(0, 8);
  const propose = async (text: string) => {
    const response = await page.request.post("/api/backend/jo/memories", { data: { operation_id: `proposal-${crypto.randomUUID()}`, kind: "preference", symbol: "MU",
      original_text: text, interpretation: "Jo’s reading of a chat remark.", source: "jo_proposal", source_reference: "Invented chat excerpt", status: "proposed", owner_confirmed: false } });
    expect(response.ok()).toBeTruthy();
    return response.json();
  };
  const accepted = await propose(`Accept me ${tag}: I size down before earnings.`);
  const declined = await propose(`Decline me ${tag}: I never hold overnight.`);
  const latest = async (memoryId: string) => (await (await page.request.get(`/api/backend/jo/memories/${memoryId}?limit=1`)).json()).items[0];
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/morning/memories");
  const review = page.getByTestId("memory-review");
  const cardWith = (text: string) => review.getByTestId("memory-card").filter({ hasText: text });
  await expect(cardWith(`Accept me ${tag}`)).toContainText("Proposed by Jo");
  await page.screenshot({ path: test.info().outputPath("memory-review-phone.png") });

  await cardWith(`Accept me ${tag}`).getByRole("button", { name: "Accept", exact: true }).click();
  await expect(review.getByRole("status")).toContainText("Accepted");
  await expect(review.getByRole("region", { name: "Active memories" }).getByTestId("memory-card").filter({ hasText: `Accept me ${tag}` })).toContainText("revision 2");
  expect(await latest(accepted.memory_id)).toMatchObject({ revision: 2, status: "active", body: { owner_confirmed: true, source: "jo_proposal" } });

  await cardWith(`Decline me ${tag}`).getByRole("button", { name: "Decline", exact: true }).click();
  expect((await latest(declined.memory_id)).status).toBe("proposed");
  await cardWith(`Decline me ${tag}`).getByRole("button", { name: "Confirm decline" }).click();
  await expect(review.getByRole("status")).toContainText("Declined");
  expect((await latest(declined.memory_id)).status).toBe("retired");

  // Correct: a new revision with the owner's wording; the earlier revision stays in history.
  const active = review.locator(`[data-memory-id="${accepted.memory_id}"]`);
  await active.getByRole("button", { name: "Correct" }).click();
  await active.getByLabel("Your wording").fill(`Corrected ${tag}: I size down a week before earnings.`);
  await active.getByRole("button", { name: "Save correction" }).click();
  await expect(cardWith(`Corrected ${tag}`)).toContainText("revision 3");
  expect((await (await page.request.get(`/api/backend/jo/memories/${accepted.memory_id}`)).json()).items.map((r: { revision: number }) => r.revision)).toEqual([3, 2, 1]);

  // Conflict: another change lands while the correction form is open.
  await active.getByRole("button", { name: "Correct" }).click();
  const current = await latest(accepted.memory_id);
  expect((await page.request.post("/api/backend/jo/memories", { data: { ...current.body, operation_id: `elsewhere-${crypto.randomUUID()}`, base_revision: 3, memory_id: accepted.memory_id,
    original_text: `Changed elsewhere ${tag}.` } })).ok()).toBeTruthy();
  await active.getByLabel("Your wording").fill(`Stale edit ${tag}`);
  await active.getByRole("button", { name: "Save correction" }).click();
  await expect(review.getByRole("alert")).toContainText("This memory changed since the page loaded");
  await expect(cardWith(`Changed elsewhere ${tag}`)).toContainText("revision 4");
  expect((await latest(accepted.memory_id)).revision).toBe(4);

  // Retire needs a confirming second click.
  await active.getByRole("button", { name: "Retire" }).click();
  await active.getByRole("button", { name: "Confirm retire" }).click();
  await expect(review.getByRole("status")).toContainText("Retired");
  await review.getByText(/^Retired \(\d+\)$/).click();
  await expect(review.locator("details").getByTestId("memory-card").filter({ hasText: `Changed elsewhere ${tag}` })).toContainText("revision 5");

  // Add: invalid symbol blocks the save; an interrupted save retries with the same operation ID and saves once.
  await review.getByRole("button", { name: "Add a belief" }).click();
  await review.getByLabel("Your wording").fill(`New belief ${tag}: I like MU above its 50-day.`);
  await review.getByLabel("Symbol (optional)").fill("not a ticker");
  await expect(review.getByRole("button", { name: "Save belief" })).toBeDisabled();
  await expect(review).toContainText("Symbol must be a ticker");
  await review.getByLabel("Symbol (optional)").fill("MU");
  const operations: string[] = [];
  let fail = true;
  await page.route("**/jo/memories", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    operations.push(JSON.parse(route.request().postData() ?? "{}").operation_id);
    if (fail) { fail = false; return route.abort("failed"); }
    return route.continue();
  });
  await review.getByRole("button", { name: "Save belief" }).click();
  await expect(review.getByRole("alert")).toContainText("it’s unknown whether this saved");
  await review.getByRole("button", { name: "Save belief" }).click();
  await expect(review.getByRole("status")).toContainText("Saved.");
  expect(operations).toHaveLength(2);
  expect(operations[0]).toBe(operations[1]);
  await expect(cardWith(`New belief ${tag}`)).toContainText("Thesis · MU · revision 1 · Your statement");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: test.info().outputPath("memory-review-desktop.png") });

  await page.route("**/jo/memories?**", (route) => route.fulfill({ status: 503, json: { detail: "Fixture unavailable" } }));
  await page.reload();
  await expect(review.getByRole("alert")).toContainText("Saved memories could not load. Nothing was changed.");
});
