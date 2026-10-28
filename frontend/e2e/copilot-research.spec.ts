import { expect, test, type Page } from "@playwright/test";

// "Research deeper" on a saved investigation. Every lab and queue route is stubbed in the browser, so nothing reaches
// the e2e backend's (disabled) lab and no job runs.
const ON = {
  enabled: true, backend: "fake", evidence: "fixture", model: "fake-scripted", effort: "medium", fallbacks: false,
  key_configured: false, tools: [], limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
const SOURCE = "11111111-1111-4111-8111-111111111111";
const RESULT = "22222222-2222-4222-8222-222222222222";
const record = (id: string, over: Record<string, unknown> = {}) => ({
  id, source: "copilot", title: "NBIS looks like it might recover", symbol: "NBIS", status: "open", conclusion: null, revision: 1,
  message_count: 2, has_findings: false, created_at: "2026-10-24T14:00:00Z", updated_at: "2026-10-24T14:05:00Z",
  transcript: [{ role: "user", content: "Context: Radar 10:41 AM: NBIS up 3%\n\nIs the neocloud group confirming the NBIS bounce?" },
    { role: "assistant", content: "Not yet." }],
  evidence: [], findings: null, ...over,
});
const result = record(RESULT, { source: "research_job", title: "Is the neocloud group confirming?", message_count: 1, has_findings: true,
  created_at: "2026-10-24T14:20:00Z", updated_at: "2026-10-24T14:20:00Z", transcript: [{ role: "user", content: "q" }],
  findings: { summary: "Financing stress, not demand, is driving the group.", key_findings: [], counterpoints: [], what_would_change: [], citations: [] } });
const job = (status: string, over: Record<string, unknown> = {}) => ({
  id: "job-1", kind: "question", status, input: { question: "Why is NBIS lagging CRWV?", symbols: ["NBIS"], from_investigation: SOURCE },
  attempts: status === "queued" ? 0 : 1, error: null, cost_usd: null, investigation_id: null,
  created_at: "2026-10-24T14:10:00Z", finished_at: null, ...over,
});

type Queue = { enabled: boolean; jobs: ReturnType<typeof job>[]; reads: number; posted: unknown[]; urls?: string[] };

async function lab(page: Page, queue: Queue, withResult = () => false) {
  await page.clock.install({ time: new Date("2026-10-24T14:10:00Z") });
  await page.addInitScript((id) => window.localStorage.setItem("tradejournal.copilot-lab.current.v2", id), SOURCE);
  await page.route("**/copilot/status", (route) => route.fulfill({ json: ON }));
  await page.route("**/copilot/investigations?*", (route) =>
    route.fulfill({ json: { investigations: withResult() ? [result, record(SOURCE)] : [record(SOURCE)] } }));
  await page.route("**/copilot/investigations/*", (route) =>
    route.fulfill({ json: route.request().url().endsWith(RESULT) ? result : record(SOURCE) }));
  await page.route(/\/copilot\/research-jobs(\?.*)?$/, (route) => {
    if (route.request().method() === "POST") {
      queue.posted.push(route.request().postDataJSON());
      queue.jobs = [job("queued")];
      return route.fulfill({ status: 201, json: { job: queue.jobs[0], created: true, queue_enabled: queue.enabled } });
    }
    queue.reads += 1;
    (queue.urls ??= []).push(route.request().url());
    return route.fulfill({ json: { jobs: queue.jobs, queue_enabled: queue.enabled, daily_budget_usd: 2, spent_today_usd: 0 } });
  });
  await page.goto("/copilot-lab");
  await expect(page.getByRole("button", { name: "Thread actions" })).toBeVisible(); // the saved investigation is open
}

test("no Research deeper while the research queue is disabled", async ({ page }) => {
  const queue: Queue = { enabled: false, jobs: [], reads: 0, posted: [] };
  await lab(page, queue);
  await expect.poll(() => queue.reads).toBeGreaterThan(0);
  await expect(page.getByRole("button", { name: "Research deeper" })).toHaveCount(0);
});

test("Research deeper queues a linked job, follows it to done, then offers its result", async ({ page }) => {
  const queue: Queue = { enabled: true, jobs: [], reads: 0, posted: [] };
  let finished = false;
  await lab(page, queue, () => finished);
  await page.getByRole("button", { name: "Research deeper" }).click();
  // Prefilled with the investigation's symbol and its latest question, without the pasted context line.
  await expect(page.getByLabel("Research symbol")).toHaveValue("NBIS");
  await expect(page.getByLabel("Research question")).toHaveValue("Is the neocloud group confirming the NBIS bounce?");
  await page.getByLabel("Research question").fill("Why is NBIS lagging CRWV?");
  await page.getByRole("button", { name: "Queue research" }).click();
  await expect(page.getByText("Research · queued")).toBeVisible();
  expect(queue.posted).toEqual([{ question: "Why is NBIS lagging CRWV?", symbols: ["NBIS"], investigation_id: SOURCE }]);
  // One job at a time per investigation: no second request while this one waits or runs.
  await expect(page.getByRole("button", { name: "Research deeper" })).toHaveCount(0);
  // Only this investigation's jobs are read, so newer jobs elsewhere cannot push it off the page.
  expect(queue.urls!.every((url) => new URL(url).searchParams.get("from_investigation") === SOURCE)).toBe(true);

  queue.jobs = [job("running")];
  await page.clock.runFor(10_000);
  await expect(page.getByText("Research · running")).toBeVisible();
  await expect(page.getByRole("button", { name: "Research deeper" })).toHaveCount(0);

  queue.jobs = [job("done", { cost_usd: 0.42, investigation_id: RESULT, finished_at: "2026-10-24T14:20:00Z" })];
  finished = true;
  await page.clock.runFor(10_000);
  await expect(page.getByText("Research · done")).toBeVisible();
  await expect(page.getByRole("button", { name: "Research deeper" })).toBeVisible(); // free to ask again
  await expect(page.getByRole("list", { name: "Research jobs" })).toContainText("$0.42");
  // The result is one click away here; the desk's thread list (not this panel) lists saved investigations.
  await expect(page.getByRole("button", { name: "Open result" })).toBeVisible();
  await page.screenshot({ path: test.info().outputPath("research-deeper-done.png") });

  // Polling stops once nothing is waiting or running.
  const reads = queue.reads;
  await page.clock.runFor(60_000);
  expect(queue.reads).toBe(reads);

  // Discuss: a new conversation on the result's symbol with the result as its opening context, not sent.
  await page.getByRole("button", { name: "Discuss this result" }).click();
  await expect(page.getByLabel("Message")).toHaveValue(/^Context: background research "Is the neocloud group confirming\?" \(saved .+ ET\): Financing stress, not demand/);
  await expect(page.getByTestId("copilot-scope")).toHaveText("About NBIS");
  await expect(page.getByText(/Ask about an opportunity/)).toBeVisible();
});

test("a failed job shows its error and stops polling", async ({ page }) => {
  const queue: Queue = { enabled: true, jobs: [job("running")], reads: 0, posted: [] };
  await lab(page, queue);
  await expect(page.getByText("Research · running")).toBeVisible();
  queue.jobs = [job("failed", { error: "The research job timed out.", cost_usd: 0.1 })];
  await page.clock.runFor(10_000);
  await expect(page.getByText("Research · failed")).toBeVisible();
  await expect(page.getByRole("list", { name: "Research jobs" })).toContainText("The research job timed out.");
  await expect(page.getByRole("button", { name: "Open result" })).toHaveCount(0);
  const reads = queue.reads;
  await page.clock.runFor(60_000);
  expect(queue.reads).toBe(reads);
});

test("a finished job shows whether it was material and what happened to its phone ping", async ({ page }) => {
  const material = { material_change: true, material_reason: "Bernstein downgrade adds a financing risk", status: "sent" };
  const queue: Queue = { enabled: true, reads: 0, posted: [], jobs: [
    job("done", { cost_usd: 0.3, investigation_id: RESULT, finished_at: "2026-10-24T14:20:00Z", notify: material }),
    job("done", { id: "job-2", investigation_id: RESULT, finished_at: "2026-10-24T13:20:00Z",
      notify: { material_change: false, material_reason: "", status: "skipped", reason: "not material" } }),
    job("done", { id: "job-3", investigation_id: RESULT, finished_at: "2026-10-24T12:20:00Z",
      notify: { ...material, status: "skipped", reason: "daily ping limit reached" } }),
  ] };
  await lab(page, queue);
  const list = page.getByRole("list", { name: "Research jobs" });
  await expect(list).toContainText("Material · Bernstein downgrade adds a financing risk");
  await expect(list).toContainText("phone ping sent");
  await expect(list).toContainText("Not material");
  await expect(list).toContainText("no phone ping (daily ping limit reached)");
  await list.screenshot({ path: test.info().outputPath("research-job-materiality.png") });
});
