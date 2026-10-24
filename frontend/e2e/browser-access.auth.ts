import { test, expect } from "@playwright/test";
const ownerOrigin = `http://127.0.0.1:${process.env.AUTH_OWNER_PORT ?? 3129}`;
const publicOrigin = `http://127.0.0.1:${process.env.AUTH_ASSISTANT_PORT ?? 3130}`;

test("cloud-style login, restricted SSR/UI, mutation denial, and owner revocation", async ({ page, browser }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("heading", { name: "TradeJournal assistant sign-in" })).toBeVisible();
  const anonymous = await page.request.get("/api/backend/fills");
  expect(anonymous.status()).toBe(401);
  const rsc = await page.request.get("/?_rsc=probe", { headers: { RSC: "1", "x-tj-role": "owner" } });
  expect(await rsc.text()).not.toContain("Roth IRA");
  const owner = await browser.newContext({ baseURL: ownerOrigin });
  const ownerPage = await owner.newPage();
  await ownerPage.goto("/");
  await expect(ownerPage.getByRole("heading", { name: "Dashboard", exact: true })).toBeVisible();
  const ownerSession = await (await owner.request.get("/api/access/me")).json();
  expect(ownerSession.owner).toBe(true);
  const identifier = `dot-${Date.now()}`;
  const created = await owner.request.post("/api/access/assistants", { headers: { Origin: ownerOrigin, "x-tj-csrf": ownerSession.csrf }, data: { identifier, grants: { symbols: ["SPY", "QQQ", "IWM", "AAPL", "MSFT", "MU", "NBIS"], run_ids: [], journal_read: false } } });
  expect(created.status()).toBe(201);
  const credential = await created.json();
  await page.getByLabel("Assistant ID").fill(identifier);
  await page.getByLabel("Access key").fill(credential.key);
  const journalRequests: string[] = [];
  page.on("request", request => { if (/\/api\/backend\/(accounts|fills|trades|stats|gmail|sync)/.test(request.url())) journalRequests.push(request.url()); });
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Today", exact: true })).toBeVisible();
  await expect(page.getByText("Read-only assistant access")).toBeVisible();
  await expect(page.getByText("Sample journal · read-only trial", { exact: true })).toBeVisible();
  await expect(page.getByText("No practice runs are shared with this assistant for this day.")).toBeVisible();
  await expect(page.getByText("No decision records are shared with this assistant.")).toBeVisible();
  await expect(page.getByRole("link", { name: "Fills", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Prepare today", exact: true })).toBeDisabled();
  expect(journalRequests).toEqual([]);
  const assistantSession = await (await page.request.get("/api/access/me")).json();
  const forbidden = await page.request.post("/api/backend/fills", { headers: { Origin: publicOrigin, "x-tj-csrf": assistantSession.csrf }, data: {} });
  expect(forbidden.status()).toBe(403);
  expect((await page.request.get("/api/backend/advisor-shadow/runs/00000000-0000-0000-0000-000000000001")).status()).toBe(403);
  expect((await page.request.get("/api/backend/jo/morning?day=2026-10-19")).status()).toBe(403);
  expect((await page.request.get("/api/backend/day-journal/2026-10-19")).status()).toBe(403);
  expect((await page.request.post("/api/backend/day-journal/2026-10-19/entries", { headers: { Origin: publicOrigin, "x-tj-csrf": assistantSession.csrf }, data: { operation_id: "refused-thought", kind: "outlook", text: "Must not save" } })).status()).toBe(403);
  expect((await page.request.post("/api/backend/jo/briefings/00000000-0000-0000-0000-000000000001/feedback", { headers: { Origin: publicOrigin, "x-tj-csrf": assistantSession.csrf }, data: { rating: "useful" } })).status()).toBe(403);
  expect((await page.request.get("/api/backend/scanner/settings")).status()).toBe(403);
  expect((await page.request.put("/api/backend/scanner/settings", { headers: { Origin: publicOrigin, "x-tj-csrf": assistantSession.csrf }, data: { symbols: ["MU"], base_revision: 0 } })).status()).toBe(403);
  for (const action of ["advisor-handoff", "advisor-import"]) {
    expect((await page.request.post(`/api/backend/advisor-shadow/runs/00000000-0000-0000-0000-000000000001/${action}`, { headers: { Origin: publicOrigin, "x-tj-csrf": assistantSession.csrf }, data: {} })).status()).toBe(403);
  }
  expect((await page.request.post("/api/backend/advisor-shadow/runs/00000000-0000-0000-0000-000000000001/advisor-packet", { headers: { Origin: publicOrigin, "x-tj-csrf": assistantSession.csrf }, data: { question: "forged", user_plan: "forged" } })).status()).toBe(403);
  const forbiddenPage = await page.request.get("/access");
  expect(forbiddenPage.status()).toBe(403);
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page).toHaveURL(/\/login$/);
  await page.getByLabel("Assistant ID").fill(identifier);
  await page.getByLabel("Access key").fill(credential.key);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Today", exact: true })).toBeVisible();
  await page.goto("/charts?symbol=MU");
  await expect(page.getByRole("link", { name: "Charts", exact: true }).first()).toBeVisible();
  await page.goto("/daily");
  await expect(page.getByTestId("practice-routine").getByRole("heading", { level: 2, name: /^Daily practice/ })).toBeVisible();
  expect(journalRequests).toEqual([]);
  const revoked = await owner.request.post(`/api/access/assistants/${identifier}/revoke`, { headers: { Origin: ownerOrigin, "x-tj-csrf": ownerSession.csrf }, data: {} });
  expect(revoked.status()).toBe(200);
  await page.goto("/");
  await expect(page).toHaveURL(/\/login$/);
  // A private owner cookie cannot be replayed through the public entrance.
  await page.context().addCookies(await owner.cookies());
  await page.goto("/");
  await expect(page).toHaveURL(/\/login$/);
  await owner.close();
});

test("owner credential UI, CSRF refusal, and access key dismissal", async ({ browser }) => {
  const owner = await browser.newContext({ baseURL: ownerOrigin });
  const page = await owner.newPage();
  await page.goto("/access");
  await expect(page.getByRole("heading", { name: "Assistant access", exact: true })).toBeVisible();
  await page.getByLabel("Assistant ID").fill(`ui-dot-${Date.now()}`);
  await page.getByRole("button", { name: "Create assistant login" }).click();
  await expect(page.getByRole("heading", { name: "Access key · shown once" })).toBeVisible();
  await page.getByRole("button", { name: "Dismiss key" }).click();
  await expect(page.getByRole("heading", { name: "Access key · shown once" })).toHaveCount(0);
  const refused = await page.request.post("/api/access/assistants", { headers: { Origin: ownerOrigin, "x-tj-csrf": "forged" }, data: {} });
  expect(refused.status()).toBe(403);
  const callback = await page.request.get("/api/backend/auth/gmail/callback?error=access_denied", { maxRedirects: 0 });
  expect(callback.status()).toBe(307);
  expect(callback.headers().location).toBe("/?gmail_auth=error");
  const classSymbol = await page.request.get("/api/backend/charts/symbol/BRK%2FB/overview");
  expect([200, 503]).toContain(classSymbol.status());
  const traversal = await page.request.get("/api/backend/charts/symbol/BRK%2F..%2F..%2Faccess%2Fme/overview");
  expect([400, 404]).toContain(traversal.status());
  const escaped = await page.request.get("/api/backend/%252e%252e/access/me");
  expect([400, 404]).toContain(escaped.status());
  await page.goto("/practice");
  await page.getByText("Save a human decision", { exact: true }).click();
  await page.getByLabel("Symbol", { exact: true }).fill("SPY");
  await page.getByRole("button", { name: "Freeze market context", exact: true }).click();
  await expect(page.getByText(/Saved server context for SPY/)).toBeVisible();
  await page.getByLabel(/^Your choice/).selectOption("wait");
  const condition = `Authenticated owner WAIT ${Date.now()}`;
  await page.getByLabel("What would change your decision?").fill(condition);
  await page.getByLabel("Waiting ends").fill(new Date(Date.now() + 3600_000).toISOString().slice(0, 16));
  await page.getByRole("button", { name: "Save immutable decision", exact: true }).click();
  await expect(page.getByText(/Saved decision /)).toBeVisible();
  await page.reload();
  const saved = page.locator("details[data-decision-id]").filter({ hasText: condition });
  await saved.locator("summary").click();
  await expect(saved.getByText(condition, { exact: true })).toBeVisible();
  await owner.close();
});

test("owner can save scanner tickers through the authenticated UI", async ({ browser }) => {
  const owner = await browser.newContext({ baseURL: ownerOrigin });
  const page = await owner.newPage();
  await page.goto("/scanner");
  const panel = page.getByRole("region", { name: "Scanner tickers" });
  await panel.getByRole("button", { name: "Edit tickers" }).click();
  await panel.getByRole("button", { name: "Remove AAPL", exact: true }).click();
  await panel.getByLabel("Add tickers").fill("NVDA");
  await panel.getByRole("button", { name: "Save tickers", exact: true }).click();
  await expect(panel.getByRole("status")).toContainText("Saved");
  await page.reload();
  await expect(panel.getByLabel("Saved tickers")).toContainText("NVDA");
  await expect(panel.getByLabel("Saved tickers")).not.toContainText("AAPL");
  await owner.close();
});

test("assistant login fits phone width", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/login");
  await expect(page.getByLabel("Assistant ID")).toBeVisible();
  await expect(page.getByLabel("Access key")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
  await expect(page.getByRole("button", { name: "Sign in", exact: true })).toBeInViewport();
  // Keep the phone viewport fixed. Headless Chromium can briefly reject a
  // capture while its compositor initializes; retry only the evidence capture,
  // never the layout assertions, and still fail if capture remains unavailable.
  await expect(async () => {
    await page.screenshot({ path: test.info().outputPath("assistant-login-phone.png"), animations: "disabled" });
  }).toPass({ timeout: 5_000, intervals: [100, 250, 500] });
});

test("journal calendar dates hydrate across browser locales and timezones", async ({ browser }) => {
  const context = await browser.newContext({ baseURL: ownerOrigin, locale: "en-GB", timezoneId: "Pacific/Honolulu" });
  const page = await context.newPage();
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.goto("/");
  const trades = await (await context.request.get("/api/backend/trades")).json();
  const expiration = trades.find((trade: { ticker: string; expiration: string; status: string }) => trade.ticker === "AAPL" && trade.status === "open").expiration;
  const date = new Intl.DateTimeFormat("en-US", { timeZone: "UTC" }).format(new Date(`${expiration}T12:00:00Z`));
  await expect(page.getByRole("table").first().getByText(date, { exact: true }).first()).toBeVisible();
  await page.getByTestId("journal-details").locator(":scope > summary").click();
  await page.getByRole("button", { name: "1M", exact: true }).click();
  await expect(page.getByText("1M Closed P&L", { exact: true })).toBeVisible();
  expect(errors).toEqual([]);
  await context.close();
});

test("native login submission never puts an access key in the URL", async ({ browser }) => {
  const context = await browser.newContext({ baseURL: publicOrigin, javaScriptEnabled: false });
  const page = await context.newPage();
  await page.goto("/login");
  await expect(page.getByRole("button", { name: "Sign in", exact: true })).toBeDisabled();
  await page.getByLabel("Assistant ID").fill("native-proof");
  await page.getByLabel("Access key").fill("synthetic-native-proof-key");
  const sent = page.waitForRequest(request => request.url().startsWith(publicOrigin + "/login") && request.isNavigationRequest());
  // Bypass React intentionally: this is the browser's pre-hydration fallback.
  await page.evaluate(() => document.querySelector("form")!.submit());
  const request = await sent;
  expect(request.method()).toBe("POST");
  expect(new URL(request.url()).search).toBe("");
  expect(request.postData()).toContain("synthetic-native-proof-key");
  expect((await context.request.get("/api/backend/trades")).status()).toBe(401);
  await context.close();
});

test("an assistant with a saved Level 2 dock preference gets no Level 2 tab, panel or request, and the endpoint denies it", async ({ page, browser }) => {
  const owner = await browser.newContext({ baseURL: ownerOrigin });
  const ownerPage = await owner.newPage();
  await ownerPage.goto("/");
  const ownerSession = await (await owner.request.get("/api/access/me")).json();
  const identifier = `dot-l2-${Date.now()}`;
  const created = await owner.request.post("/api/access/assistants", { headers: { Origin: ownerOrigin, "x-tj-csrf": ownerSession.csrf }, data: { identifier, grants: { symbols: ["MU", "NVDA"], run_ids: [], journal_read: false } } });
  expect(created.status()).toBe(201);
  const credential = await created.json();
  await page.goto("/login");
  await page.getByLabel("Assistant ID").fill(identifier);
  await page.getByLabel("Access key").fill(credential.key);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByText("Read-only assistant access")).toBeVisible();
  const assistantSession = await (await page.request.get("/api/access/me")).json();
  // A saved Level 2 dock preference gives an assistant no tab, no panel and no Level 2 request; the endpoint itself still denies it.
  const level2Requests: string[] = [];
  page.on("request", request => { if (request.url().includes("/api/level2-lab")) level2Requests.push(`${request.method()} ${request.url()}`); });
  await page.evaluate(() => localStorage.setItem("tradejournal.charts.dock.v1", JSON.stringify({ open: true, tab: "level2" })));
  await page.goto("/charts?symbol=NVDA");
  await expect(page.getByRole("button", { name: "Watchlist", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Level 2", exact: true })).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Level 2" })).toHaveCount(0);
  await expect(page.getByTestId("live-depth-session")).toHaveCount(0);
  expect(level2Requests).toEqual([]);
  const level2Get = await page.request.get("/api/level2-lab/session");
  expect(level2Get.status()).toBe(403);
  const level2Post = await page.request.post("/api/level2-lab/session", { headers: { Origin: publicOrigin, "x-tj-csrf": assistantSession.csrf, "Content-Type": "application/x-level2-start" } });
  expect(level2Post.status()).toBe(403);
  await expect(page.getByRole("link", { name: "Charts", exact: true }).first()).toBeVisible();
});


test("a restricted historical chart returns to a granted live symbol", async ({ page, browser }) => {
  const owner = await browser.newContext({ baseURL: ownerOrigin });
  try {
    const session = await (await owner.request.get("/api/access/me")).json();
    const identifier = `chart-return-${Date.now()}`;
    const created = await owner.request.post("/api/access/assistants", { headers: { Origin: ownerOrigin, "x-tj-csrf": session.csrf },
      data: { identifier, grants: { symbols: ["MU", "NVDA"], run_ids: [], journal_read: false } } });
    expect(created.status()).toBe(201);
    const credential = await created.json();
    await page.goto("/login");
    await page.getByLabel("Assistant ID").fill(identifier);
    await page.getByLabel("Access key").fill(credential.key);
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    await expect(page.getByText("Read-only assistant access")).toBeVisible();
    const symbols: string[] = [];
    page.on("request", request => {
      const url = new URL(request.url());
      if (url.pathname === "/api/backend/charts/workspace") symbols.push(url.searchParams.get("symbol") ?? "");
    });
    const from = Date.parse("2026-07-14T13:40:00Z") / 1000;
    await page.goto(`/charts?symbol=NVDA&from=${from}&to=${from + 2400}`);
    await expect.poll(() => symbols.includes("NVDA")).toBe(true);
    const banner = page.getByRole("status", { name: "Past trade view" });
    await expect(banner).toBeVisible();
    const before = symbols.length;
    await banner.getByRole("button", { name: "Back to live" }).click();
    await expect(banner).toHaveCount(0);
    await expect.poll(() => symbols.slice(before).includes("MU")).toBe(true);
    expect(symbols.every(symbol => ["MU", "NVDA"].includes(symbol))).toBe(true);
    await expect(page.getByRole("status", { name: "Saved chart snapshot" })).toHaveCount(0);
  } finally { await owner.close(); }
});

test("owner position-alert URL survives a fresh session and session renewal", async ({ browser }) => {
  const lookup = await browser.newContext({ baseURL: ownerOrigin });
  const trades = await (await lookup.request.get("/api/backend/trades")).json() as { id: string; instrument_type: string }[];
  const trade = trades.find(t => t.instrument_type === "option")!;
  await lookup.close();
  const owner = await browser.newContext({ baseURL: ownerOrigin });
  const page = await owner.newPage();
  const id = "10000000-0000-0000-0000-000000000001";
  await page.route(`**/trades/${trade.id}/phone-alerts`, route => route.fulfill({ json: {
    enabled: false, watch: null, alerts: [{ id, kind: "giveback", detected_at: 1792594920, contracts: 2,
      mark: 412, bid: 410, gain: 24, gain_pct: 0.03, peak_gain: 204, peak_gain_pct: 0.255, delivery: "sent", error: null, delivered_at: 1792594922 }],
  } }));
  const target = `/trades/${trade.id}?alert=${id}`;
  for (let visit = 0; visit < 2; visit++) {
    await owner.clearCookies();
    await page.goto(target);
    await expect(page).toHaveURL(ownerOrigin + target);
    await expect(page.getByTestId("selected-position-alert")).toContainText("at trigger +$24 (+3%)");
    expect((await (await owner.request.get("/api/access/me")).json()).owner).toBe(true);
  }
  await owner.close();
});

test("concurrent owner reads renew without evicting their in-flight sessions", async ({ browser }) => {
  const owner = await browser.newContext({ baseURL: ownerOrigin });
  try {
    for (const renew of [false, true]) {
      if (renew) {
        // Keep this browser's old cookie, but evict its session using the real
        // four-session cap. Renewal must work without relaxing that cap.
        for (let i = 0; i < 4; i++) {
          const other = await browser.newContext({ baseURL: ownerOrigin });
          try { expect((await other.request.get("/api/access/me")).status()).toBe(200); }
          finally { await other.close(); }
        }
        const backend = `http://127.0.0.1:${process.env.AUTH_BACKEND_PORT ?? 8129}`;
        expect((await owner.request.get(`${backend}/access/me`, { headers: { "x-tj-gateway": "o".repeat(43) } })).status()).toBe(401);
      }
      const responses = await Promise.all(Array.from({ length: 16 }, () => owner.request.get("/api/backend/accounts")));
      expect(responses.map(response => response.status())).toEqual(Array(16).fill(200));
      expect((await (await owner.request.get("/api/access/me")).json()).owner).toBe(true);
    }
  } finally { await owner.close(); }
});
