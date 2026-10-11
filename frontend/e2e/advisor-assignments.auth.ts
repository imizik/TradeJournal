import { test, expect } from "@playwright/test";
import { spawn, execFileSync, type ChildProcess } from "node:child_process";
import { readFileSync, unlinkSync, writeFileSync } from "node:fs";
import path from "node:path";
import http from "node:http";

const root = path.resolve(__dirname, "../..");
const directory = `${process.env.ADVISOR_OWNER_TEST_DIR}/managed`;
const python = `${root}/backend/.venv/bin/python`;
const args = ["-B", "-m", "tests.advisor_assignment_fixture"];
const env = { NODE_ENV: "test" as const, PATH: process.env.PATH, PYTHON_DOTENV_DISABLED: "1" };
const origin = `http://127.0.0.1:${process.env.AUTH_OWNER_PORT ?? 3129}`;
const publicOrigin = `http://127.0.0.1:${process.env.AUTH_ASSISTANT_PORT ?? 3130}`;
let processFixture: ChildProcess;
const logs: string[] = [];
const run = (operation: string) => execFileSync(python, [...args, operation, directory], { cwd: `${root}/backend`, env, stdio: ["ignore", "pipe", "pipe"] });
async function start() {
  processFixture = spawn(python, [...args, "serve", directory], { cwd: `${root}/backend`, env, stdio: ["ignore", "pipe", "pipe"] });
  processFixture.stderr?.on("data", chunk => logs.push(String(chunk)));
  await expect.poll(() => new Promise<number>(resolve => {
    const request = http.get({ socketPath: `${directory}/backend.sock`, path: "/owner/advisor/assignments" }, response => { response.resume(); resolve(response.statusCode!); });
    request.on("error", () => resolve(0));
  }), { timeout: 10000 }).toBe(200);
}
async function stop() {
  if (processFixture?.exitCode === null) { const done = new Promise(resolve => processFixture.once("exit", resolve)); processFixture.kill("SIGTERM"); await done; }
  try { unlinkSync(`${directory}/backend.sock`); } catch { /* stopped listener */ }
}
test.beforeAll(async () => { run("init"); await start(); });
test.afterAll(async () => { await stop(); writeFileSync(test.info().outputPath("manager-process.log"), logs.join("")); });

test("owner creates two distinct questions without restart, reopens exact answers and revokes access", async ({ browser }) => {
  const context = await browser.newContext({ baseURL: origin }); const page = await context.newPage();
  const errors: string[] = []; page.on("pageerror", error => errors.push(error.message));
  await page.goto("/advisor-review");
  await page.getByRole("link", { name: "Manage advisor questions" }).click();
  await expect(page.getByText("No questions yet. Create an invented question above.")).toBeVisible();
  await page.screenshot({ path: test.info().outputPath("advisor-questions-empty-desktop.png"), fullPage: true });
  await page.getByLabel("Question", { exact: true }).fill("What is missing from this invented setup?");
  await page.getByLabel("Your invented plan").fill("Wait for verified trigger and risk inputs.");
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "Create and assign question" }).click();
  await expect(page.getByTestId("advisor-assignment-record")).toContainText("Status: pending");
  await page.screenshot({ path: test.info().outputPath("advisor-questions-pending-desktop.png"), fullPage: true });
  run("save"); // Generated OAuth fixture, not actual Jo.
  const first = JSON.parse(readFileSync(`${directory}/saved.json`, "utf8"));
  await page.getByRole("button", { name: "Reload saved questions" }).click();
  await expect(page.getByTestId("advisor-assignment-record")).toContainText("Status: answered");
  await page.getByText("Exact saved advisor receipt", { exact: true }).click();
  expect(JSON.parse(await page.getByTestId("advisor-receipt").innerText())).toEqual(first.receipt);
  await page.getByText("Immutable original request", { exact: true }).click();
  expect(JSON.parse(await page.getByTestId("assignment-original").innerText())).toEqual(first.request);
  await page.screenshot({ path: test.info().outputPath("advisor-questions-answered-desktop.png"), fullPage: true });
  await page.getByLabel("Question", { exact: true }).fill("Which invented inputs are still missing?");
  await page.getByLabel("Your invented plan").fill("Wait; do not infer a live signal.");
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "Create and assign question" }).click();
  await expect(page.getByTestId("advisor-assignment-record")).toContainText("Status: pending");
  const list = await (await context.request.get("/api/advisor-assignments")).json();
  expect(list.assignments).toHaveLength(2); expect(list.selected).not.toBe(first.request.assignment_id);
  await page.getByRole("button", { name: "Revoke assignment", exact: true }).click();
  await expect(page.getByTestId("advisor-assignment-record")).toContainText("Status: revoked");
  run("denied");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: test.info().outputPath("advisor-questions-revoked-phone.png"), fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
  await page.getByRole("button", { name: /What is missing from this invented setup/ }).click();
  await expect(page.getByText("Summary: Wait for verified inputs", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Revoke assignment", exact: true }).click();
  await expect(page.getByTestId("advisor-assignment-record")).toContainText("Status: revoked");
  // Restart after the second-assignment proof; ledger and both saved request identities survive.
  await stop(); await start();
  await page.reload();
  await page.getByRole("button", { name: /What is missing from this invented setup/ }).click();
  await page.getByText("Exact saved advisor receipt", { exact: true }).click();
  expect(JSON.parse(await page.getByTestId("advisor-receipt").innerText())).toEqual(first.receipt);
  await page.getByText("Immutable original request", { exact: true }).click();
  expect(JSON.parse(await page.getByTestId("assignment-original").innerText())).toEqual(first.request);
  await page.screenshot({ path: test.info().outputPath("advisor-questions-recovered-phone.png"), fullPage: true });
  const state = await (await context.request.get("/api/advisor-assignments")).json();
  expect(state.assignments.every((item: { status: string }) => item.status === "revoked")).toBe(true);
  // Existing owner CSRF and audience authority are required for every mutation.
  for (const headers of [{ Origin: origin }, { Origin: "https://wrong.invalid", "x-tj-csrf": "fake" }] as Record<string, string>[]) {
    expect((await context.request.post("/api/advisor-assignments", { headers, data: { revoke: first.request.assignment_id } })).status()).toBe(403);
  }
  const other = await browser.newContext({ baseURL: publicOrigin });
  expect((await other.request.get("/api/advisor-assignments")).status()).toBe(401);
  await other.close();
  await page.route("**/api/advisor-assignments*", route => route.fulfill({ status: 503, json: { detail: "Fixture unavailable. Reload saved questions." } }));
  await page.getByRole("button", { name: "Reload saved questions" }).click();
  await expect(page.getByTestId("advisor-assignments").getByRole("alert")).toContainText("Fixture unavailable");
  await expect(page.getByTestId("advisor-assignment-record")).toHaveCount(0);
  await page.screenshot({ path: test.info().outputPath("advisor-questions-unavailable-phone.png"), fullPage: true });
  expect(errors).toEqual([]);
  await context.close();
});
