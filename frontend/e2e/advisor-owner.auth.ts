import { test, expect } from "@playwright/test";
import { spawn, execFileSync, type ChildProcess } from "node:child_process";
import { existsSync, readFileSync, writeFileSync, unlinkSync } from "node:fs";
import path from "node:path";
import http from "node:http";

const ownerOrigin = `http://127.0.0.1:${process.env.AUTH_OWNER_PORT ?? 3129}`;
const publicOrigin = `http://127.0.0.1:${process.env.AUTH_ASSISTANT_PORT ?? 3130}`;
const root = path.resolve(__dirname, "../..");
const directory = process.env.ADVISOR_OWNER_TEST_DIR!;
test.describe.configure({ mode: "serial" });
const python = existsSync(`${root}/backend/.venv/bin/python`) ? `${root}/backend/.venv/bin/python` : process.env.PYTHON || "python3";
const fixture = ["-B", "-m", "tests.advisor_owner_fixture"];
const clean = { PATH: process.env.PATH, NODE_ENV: "test" as const, PYTHON_DOTENV_DISABLED: "1" };
let child: ChildProcess;
const logs: string[] = [];
const run = (operation: string) => execFileSync(python, [...fixture, operation, directory], { cwd: `${root}/backend`, env: clean });
const expected = () => JSON.parse(readFileSync(`${directory}/expected.json`, "utf8"));
async function direct() {
  return new Promise<{ status: number; body: string }>((resolve, reject) => {
    const request = http.get({ socketPath: `${directory}/owner.sock`, path: "/owner/advisor" }, response => {
      const chunks: Buffer[] = []; response.on("data", chunk => chunks.push(chunk));
      response.on("end", () => resolve({ status: response.statusCode!, body: Buffer.concat(chunks).toString() }));
    }); request.on("error", reject);
  });
}
async function start() {
  child = spawn(python, [...fixture, "serve", directory], { cwd: `${root}/backend`, env: clean, stdio: ["ignore", "pipe", "pipe"] });
  child.stdout?.on("data", value => logs.push(String(value))); child.stderr?.on("data", value => logs.push(String(value)));
  // Readiness probes do not retry a product assertion or advisor save.
  await expect.poll(async () => { try { return (await direct()).status; } catch { return 0; } }, { timeout: 10000 }).toBe(200);
}
async function stop() {
  if (child?.exitCode === null) { const ended = new Promise<void>(resolve => child.once("exit", () => resolve())); child.kill("SIGTERM"); await ended; }
  try { unlinkSync(`${directory}/owner.sock`); } catch { /* listener may already be removed */ }
}
test.beforeAll(async () => { run("init-empty"); await start(); });
test.afterAll(async () => { await stop(); writeFileSync(test.info().outputPath("owner-reader-process.log"), logs.join("")); });

test("direct owner BFF reads exact isolated receipt after uncertain save, reload, reader restart and revocation", async ({ browser }) => {
  const context = await browser.newContext({ baseURL: ownerOrigin });
  const page = await context.newPage(); const writes: string[] = [];
  page.on("request", request => { if (request.method() !== "GET" && /advisor/.test(request.url())) writes.push(request.url()); });
  await page.goto("/advisor-review");
  await expect(page.getByText("No advisor response has been received.")).toBeVisible();
  await expect(page.getByText(/An absent receipt is not proof a pending save failed/)).toBeVisible();
  await page.screenshot({ path: test.info().outputPath("owner-missing-receipt-desktop.png"), fullPage: true });
  // Commit once, discard the saver response. This page can only GET recovery.
  run("save");
  await page.getByRole("button", { name: "Reload advisor record" }).click();
  await page.getByText("Exact saved advisor receipt", { exact: true }).click();
  expect(JSON.parse(await page.getByTestId("advisor-receipt").innerText())).toEqual(expected().receipt);
  await page.getByText("Frozen request identity and packet", { exact: true }).click();
  expect(JSON.parse(await page.getByTestId("advisor-owner-request").innerText())).toEqual(expected().request);
  const opportunity = expected().request.packet.opportunities[0];
  const fact = opportunity.price_facts[0];
  await expect(page.getByText(new RegExp(`${opportunity.symbol}.*${fact.name}:.*${fact.value}`))).toBeVisible();
  await expect(page.getByText(/Request origin manual-paste · saved answer oauth-mcp · comparison assisted/)).toBeVisible();
  await expect(page.getByText(/INVENTED DEMO ONLY · INDEPENDENCE UNVERIFIED · OWNER READ ONLY/)).toBeVisible();
  await page.screenshot({ path: test.info().outputPath("owner-receipt-desktop.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.evaluate(() => window.scrollTo(0, 0));
  await expect(page.getByRole("heading", { name: "Advisor review", exact: true })).toBeInViewport();
  await page.screenshot({ path: test.info().outputPath("owner-receipt-phone.png"), fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
  await expect(page.getByRole("button", { name: "Reload advisor record" })).toBeInViewport();
  await expect(page.locator("input,textarea,input[type=file]")).toHaveCount(0);
  for (const action of ["POST", "PUT", "DELETE"]) expect((await context.request.fetch("/api/advisor-owner", { method: action })).status()).toBe(405);
  expect((await context.request.get("/api/advisor-owner?run_id=other")).status()).toBe(400);
  await stop(); await start(); run("revoke");
  await page.reload(); await page.getByText("Exact saved advisor receipt", { exact: true }).click();
  expect(JSON.parse(await page.getByTestId("advisor-receipt").innerText())).toEqual(expected().receipt);
  await expect(page.getByText("Advisor assignment revoked. Owner recovery remains available.")).toBeVisible();
  await page.goto("/"); await page.goto("/advisor-review");
  const response = await context.request.get("/api/advisor-owner");
  expect(response.status()).toBe(200);
  expect(response.headers()["cache-control"]).toBe("no-store");
  const record = await response.json();
  expect(record.request).toEqual(expected().request); expect(record.receipt).toEqual(expected().receipt);
  expect(JSON.parse((await direct()).body).receipt).toEqual(record.receipt);
  expect(writes).toEqual([]);
  await context.close();
});

test("owner UI clears stale content during delayed/error/dormant reads and assistants cannot retrieve", async ({ browser }) => {
  const context = await browser.newContext({ baseURL: ownerOrigin }); const page = await context.newPage();
  await page.goto("/advisor-review"); await expect(page.getByText("Summary:")).toBeVisible();
  let release!: () => void; const held = new Promise<void>(resolve => { release = resolve; });
  await page.route("**/api/advisor-owner", async route => { const response = await route.fetch(); await held; await route.fulfill({ response }); });
  await page.getByRole("button", { name: "Reload advisor record" }).click();
  await expect(page.getByRole("status")).toHaveText("Reading the isolated advisor record…");
  await expect(page.getByTestId("advisor-saved-answer")).toHaveCount(0);
  release(); await expect(page.getByText("Summary:")).toBeVisible(); await page.unroute("**/api/advisor-owner");
  const config = JSON.parse(readFileSync(`${directory}/owner.json`, "utf8"));
  writeFileSync(`${directory}/owner.json`, JSON.stringify({ ...config, enabled: false }));
  await page.getByRole("button", { name: "Reload advisor record" }).click();
  await expect(page.getByTestId("advisor-owner-review").getByRole("alert")).toContainText("no write or retry was sent");
  await expect(page.getByTestId("advisor-saved-answer")).toHaveCount(0);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: test.info().outputPath("owner-dormant-phone.png"), fullPage: true });
  writeFileSync(`${directory}/owner.json`, JSON.stringify(config));
  await page.getByRole("button", { name: "Reload advisor record" }).click(); await expect(page.getByText("Summary:")).toBeVisible();
  const publicContext = await browser.newContext({ baseURL: publicOrigin });
  expect((await publicContext.request.get("/api/advisor-owner")).status()).toBe(401);
  const session = await (await context.request.get("/api/access/me")).json();
  const id = `owner-reader-denial-${Date.now()}`;
  const created = await context.request.post("/api/access/assistants", { headers: { Origin: ownerOrigin, "x-tj-csrf": session.csrf }, data: { identifier: id, grants: { symbols: ["MU"], run_ids: [], journal_read: false } } });
  expect(created.status()).toBe(201); const credential = await created.json();
  const assistant = await publicContext.newPage(); await assistant.goto("/login");
  await assistant.getByLabel("Assistant ID").fill(id); await assistant.getByLabel("Access key").fill(credential.key);
  await assistant.getByRole("button", { name: "Sign in", exact: true }).click(); await expect(assistant).toHaveURL(publicOrigin + "/");
  expect((await publicContext.request.get("/api/advisor-owner")).status()).toBe(403);
  expect((await publicContext.request.get("/advisor-review")).status()).toBe(403);
  await expect(assistant.getByRole("link", { name: "Advisor review", exact: true })).toHaveCount(0);
  await publicContext.close(); await context.close();
});

test("connection status shows one line per item with recovery, no secrets, desktop and phone", async ({ browser }) => {
  const context = await browser.newContext({ baseURL: ownerOrigin }); const page = await context.newPage();
  const status = page.getByTestId("advisor-connection-status");
  await page.goto("/advisor-review");
  await expect(status.getByTestId("advisor-connection-line")).toHaveCount(4);
  await expect(status).toContainText(/Sign-in keys: Current until .* ET\./);
  await expect(status).toContainText("Advisor: Advisor config and Jo's profile are on.");
  await expect(status).toContainText("Selected question: Revoked."); // Revoked by the first test.
  await expect(status).toContainText(/Last Jo save: .* ET\. Jo read the question before saving\./);
  const advisor = JSON.parse(readFileSync(`${directory}/advisor.json`, "utf8"));
  for (const secret of [advisor.client_id, advisor.profiles[0].subject, "invented-public-key", expected().request.request_sha256, directory])
    expect(await status.innerText()).not.toContain(secret);
  const api = await context.request.get("/api/advisor-owner/status");
  expect(api.status()).toBe(200); expect(api.headers()["cache-control"]).toBe("no-store");
  for (const secret of [advisor.client_id, advisor.profiles[0].subject, "invented-public-key", directory]) expect(await api.text()).not.toContain(secret);
  run("keys-expired"); run("advisor-disabled");
  await status.getByRole("button", { name: "Check again" }).click();
  await expect(status).toContainText(/Sign-in keys: Expired at .* ET\. Jo's sign-ins and calls are refused\./);
  await expect(status).toContainText("Operator: run the key check, start the key refresh once");
  await expect(status).toContainText("Advisor: The advisor config is turned off.");
  await page.screenshot({ path: test.info().outputPath("owner-status-problems-desktop.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.evaluate(() => window.scrollTo(0, 0));
  await expect(status.getByRole("heading", { name: "Advisor connection" })).toBeInViewport();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
  await page.screenshot({ path: test.info().outputPath("owner-status-problems-phone.png"), fullPage: true });
  await stop();
  await status.getByRole("button", { name: "Check again" }).click();
  await expect(status.getByRole("alert")).toContainText("start the sockets before the services");
  await start(); run("keys-fresh");
  await status.getByRole("button", { name: "Check again" }).click();
  await expect(status).toContainText(/Sign-in keys: Current until/);
  for (const action of ["POST", "PUT", "DELETE"]) expect((await context.request.fetch("/api/advisor-owner/status", { method: action })).status()).toBe(405);
  expect((await context.request.get("/api/advisor-owner/status?state=fresh")).status()).toBe(400);
  const publicContext = await browser.newContext({ baseURL: publicOrigin });
  expect((await publicContext.request.get("/api/advisor-owner/status")).status()).toBe(401);
  await publicContext.close(); await context.close();
});
