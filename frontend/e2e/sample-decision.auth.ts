import { test, expect, type Browser, type Page } from "@playwright/test";
import { frozenWindow } from "../lib/frozen-evidence";
import { historicalExpiryInstant } from "../lib/historicalExpiry";
const ownerOrigin = `http://127.0.0.1:${process.env.SAMPLE_OWNER_PORT ?? 3141}`;
const assistantOrigin = `http://127.0.0.1:${process.env.SAMPLE_ASSISTANT_PORT ?? 3142}`;

async function login(page: Page, browser: Browser, write: boolean, replay = false) {
  const owner = await browser.newContext({ baseURL: ownerOrigin });
  const session = await (await owner.request.get("/api/access/me")).json();
  const run = (await (await owner.request.get("/api/backend/practice/runs")).json()).runs.find((item: { policy_version: string }) => item.policy_version === (replay ? "practice-sample-replay-long-15m-v1" : "practice-sample-long-15m-v1"));
  expect(run).toBeTruthy();
  const identity = `sample-${Date.now()}-${write ? "writer" : "reader"}`;
  const created = await owner.request.post("/api/access/assistants", { headers: { Origin: ownerOrigin, "x-tj-csrf": session.csrf }, data: { identifier: identity, grants: { symbols: write ? ["MU", "NBIS"] : ["MU", "NBIS", "RNXT", "AAPL", "RCAT"], run_ids: [run.id], journal_read: !write, decision_write: write, sample_replay: replay } } });
  expect(created.status()).toBe(201);
  const key = (await created.json()).key;
  await page.goto("/login");
  await page.getByLabel("Assistant ID").fill(identity);
  await page.getByLabel("Access key").fill(key);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("heading", { name: write ? "Today" : "Dashboard", exact: true })).toBeVisible();
  await owner.close();
  return run;
}

test("writer inspects frozen MU/NBIS facts, saves TAKE/WAIT, reloads and reopens exact records", async ({ page, browser }) => {
  const errors: string[] = [];
  const forbiddenReads: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("request", request => { if (/\/api\/backend\/(fills|trades|accounts|stats|daily-review)(?:[/?]|$)/.test(request.url())) forbiddenReads.push(request.url()); });
  const run = await login(page, browser, true);
  await expect(page.getByText("Simulated decision trial", { exact: true })).toBeVisible();
  const mu = page.getByRole("article", { name: "MU sample opportunity" });
  await expect(mu.getByText(/300 timestamped price facts/)).toBeVisible();
  await mu.getByLabel("MU choice").selectOption("take");
  await mu.getByLabel("MU reason").fill("Exercise TAKE uses the frozen MU trigger, stop, guard and target.");
  await mu.getByRole("button", { name: "Save MU decision", exact: true }).click();
  await expect(mu.getByText("SIMULATED · UNARMED", { exact: true })).toBeVisible();
  const nbis = page.getByRole("article", { name: "NBIS sample opportunity" });
  await nbis.getByLabel("NBIS choice").selectOption("wait");
  await nbis.getByLabel("NBIS reason").fill("Wait for the sample range to resolve.");
  await nbis.getByLabel("NBIS wait condition").fill("Reassess after the simulated close above the range.");
  await nbis.getByRole("button", { name: "Save NBIS decision", exact: true }).click();
  await expect(nbis.getByRole("button", { name: "Reopen saved NBIS decision" })).toBeVisible();
  const before = (await (await page.request.get("/api/backend/decisions")).json()).decisions;
  expect(before).toHaveLength(2);
  expect(new Set(before.map((record: { actor: string }) => record.actor)).size).toBe(1);
  await page.goto(`/daily/${run.day}`);
  await expect(page.getByRole("heading", { name: "Simulated decision practice" })).toBeVisible();
  await page.reload();
  await page.getByRole("button", { name: "Reopen saved MU decision" }).click();
  await expect(page.getByRole("article", { name: "MU sample opportunity" }).getByRole("status")).toContainText("original record reopened");
  const after = (await (await page.request.get("/api/backend/decisions")).json()).decisions;
  expect(after.map((record: { id: string; record_sha256: string }) => [record.id, record.record_sha256])).toEqual(before.map((record: { id: string; record_sha256: string }) => [record.id, record.record_sha256]));
  const auth = await (await page.request.get("/api/access/me")).json();
  expect((await page.request.get("/api/backend/fills")).status()).toBe(403);
  expect((await page.request.post(`/api/backend/decisions/${before[0].id}/arm`, { headers: { Origin: assistantOrigin, "x-tj-csrf": auth.csrf }, data: { operation_id: "forbidden" } })).status()).toBe(403);
  expect(forbiddenReads).toEqual([]);
  expect(errors).toEqual([]);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
  await page.screenshot({ path: test.info().outputPath("sample-saved-decisions-phone.png"), animations: "disabled" });
});

test("simulated charts support indicators and symbol URLs without requesting a live stream", async ({ page, browser }) => {
  const errors: string[] = [];
  const streams: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("request", request => { if (request.url().includes("/charts/stream")) streams.push(request.url()); });
  await login(page, browser, true);
  await page.goto("/charts?symbol=NBIS");
  await expect(page.getByRole("button", { name: "Chart NBIS", exact: true })).toHaveAttribute("aria-current", "true");
  await expect(page.getByRole("region", { name: "NBIS 5m chart", exact: true })).toBeVisible();
  await expect(page.getByText("Simulated chart snapshot", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Chart MU", exact: true }).click();
  await expect(page).toHaveURL(/symbol=MU/);
  await expect(page.getByRole("region", { name: "MU 5m chart", exact: true })).toBeVisible();
  // Studies need explicit numeric/null fields from the real fixture backend.
  await page.getByRole("button", { name: "Indicators", exact: true }).click();
  await page.getByRole("button", { name: "RSI 14", exact: true }).click();
  await page.getByRole("button", { name: "EMA 9", exact: true }).click();
  await page.getByRole("button", { name: "Indicators", exact: true }).click();
  await page.reload();
  await expect(page.getByRole("region", { name: "MU 5m chart", exact: true })).toBeVisible();
  expect(errors).toEqual([]);
  expect(streams).toEqual([]);
});

test("read-only calendar includes the practice-only date and opens its saved evidence", async ({ page, browser }) => {
  const run = await login(page, browser, false);
  await page.goto("/daily");
  const linked = page.getByRole("link", { name: `Review practice ${run.day}`, exact: true });
  await expect(linked).toBeVisible();
  await linked.click();
  await expect(page).toHaveURL(new RegExp(`/daily/${run.day}\\?practice_run=${run.id}`));
  await expect(page.getByText("Daily practice routine", { exact: true })).toBeVisible();
  await page.getByText("Frozen neutral context", { exact: true }).first().click();
  await expect(page.getByText(/sample_fixture/).first()).toBeVisible();
});

test("a slow pre-save reload cannot hide the immutable SKIP receipt", async ({ page, browser }) => {
  await login(page, browser, true);
  const mu = page.getByRole("article", { name: "MU sample opportunity" });
  await expect(mu.getByLabel("MU reason")).toBeVisible();
  let release: (() => void) | undefined;
  let captured: (() => void) | undefined;
  const pending = new Promise<void>(resolve => { release = resolve; });
  const seen = new Promise<void>(resolve => { captured = resolve; });
  await page.route("**/api/backend/practice/runs/*", async route => {
    const original = await route.fetch();
    captured?.();
    await pending;
    await route.fulfill({ response: original });
  });
  await page.getByRole("button", { name: "Reload saved practice" }).click();
  await seen;
  await mu.getByLabel("MU reason").fill("No setup in this simulated exercise.");
  await mu.getByRole("button", { name: "Save MU decision", exact: true }).click();
  await expect(mu.getByRole("button", { name: "Reopen saved MU decision" })).toBeVisible();
  release?.();
  await expect(page.getByRole("button", { name: "Reload saved practice" })).toBeEnabled();
  await expect(mu.getByRole("button", { name: "Reopen saved MU decision" })).toBeVisible();
  await expect(mu.getByLabel("MU reason")).toHaveCount(0);
});

for (const timezoneId of ["America/Los_Angeles", "America/New_York", "UTC"]) {
  test(`WAIT expiry previews and saves the same instant in ${timezoneId}`, async ({ browser }) => {
    const context = await browser.newContext({ baseURL: assistantOrigin, timezoneId });
    const page = await context.newPage();
    const errors: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    try {
      const run = await login(page, browser, true);
      const mu = page.getByRole("article", { name: "MU sample opportunity" });
      await mu.getByLabel("MU choice").selectOption("wait");
      const input = mu.getByLabel(`MU waiting ends (${timezoneId})`, { exact: true });
      const preview = mu.locator("form time[datetime]");
      const deadlineMinute = new Date(Math.floor(new Date(run.deadline).getTime() / 60_000) * 60_000).toISOString();
      await expect(preview).toHaveAttribute("datetime", deadlineMinute);
      // Choose one future UTC instant, then enter its wall time in each browser.
      const instant = new Date(Math.floor((Date.now() + 10 * 60_000) / 60_000) * 60_000);
      const localInput = new Intl.DateTimeFormat("sv-SE", { timeZone: timezoneId,
        year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(instant).replace(" ", "T");
      await input.fill(localInput);
      await expect(preview).toHaveAttribute("datetime", instant.toISOString());
      const eastern = `${instant.toLocaleString("en-US", { timeZone: "America/New_York" })} ET`;
      await expect(preview).toHaveText(eastern);
      await expect(input).toHaveAccessibleDescription(`Will save as ${eastern}. Daily Review shows Eastern time.`);
      if (timezoneId === "America/Los_Angeles") {
        await page.setViewportSize({ width: 390, height: 844 });
        expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
        await mu.screenshot({ path: test.info().outputPath("wait-expiry-preview-phone.png") });
      }
      await input.fill("");
      await expect(mu.getByText("Choose an expiry to preview its Eastern time.", { exact: true })).toBeVisible();
      await expect(preview).toHaveCount(0);
      await input.fill(localInput);
      await mu.getByLabel("MU reason").fill("Verify local-time input and Eastern-time preview preserve the same instant.");
      await mu.getByLabel("MU wait condition").fill("Reassess the invented trigger before this expiry.");
      await mu.getByRole("button", { name: "Save MU decision", exact: true }).click();
      await expect(mu.getByRole("button", { name: "Reopen saved MU decision" })).toBeVisible();
      await mu.getByText("MU · WAIT", { exact: true }).click();
      await expect(mu.getByText(eastern, { exact: true })).toBeVisible();
      const records = (await (await page.request.get("/api/backend/decisions")).json()).decisions;
      expect(records).toHaveLength(1);
      expect(new Date(records[0].wait_expiry).toISOString()).toBe(instant.toISOString());
      await page.goto(`/daily/${run.day}?practice_run=${run.id}`);
      await page.reload();
      await page.getByRole("button", { name: "Reopen saved MU decision" }).click();
      await page.getByRole("article", { name: "MU sample opportunity" }).getByText("MU · WAIT", { exact: true }).click();
      await expect(page.getByRole("article", { name: "MU sample opportunity" }).getByText(eastern, { exact: true })).toBeVisible();
      const reopened = (await (await page.request.get(`/api/backend/decisions/${records[0].id}`)).json());
      expect(reopened.wait_expiry).toBe(records[0].wait_expiry);
      expect(reopened.record_sha256).toBe(records[0].record_sha256);
      expect(errors).toEqual([]);
    } finally { await context.close(); }
  });
}

test("scoped agent starts its own TAKE replay and reopens a complete immutable sample outcome", async ({ page, browser }) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  const run = await login(page, browser, true, true);
  await expect(page.getByText("Simulated paper replay trial", { exact: true })).toBeVisible();
  const before = await (await page.request.get(`/api/backend/practice/runs/${run.id}`)).json();
  expect(JSON.stringify(before)).not.toContain('"nonce"');
  expect(before.opportunities.every((opp: { replay: unknown }) => opp.replay === null)).toBe(true);
  const packets = before.opportunities.map((opp: { context: { packet: { scenario_version: string; recent_minute_bars: { c: number }[] } } }) => opp.context.packet);
  expect(packets.every((packet: { scenario_version: string }) => packet.scenario_version === "sample-scenarios-v2")).toBe(true);
  expect(packets.every((packet: { recent_minute_bars: { c: number }[] }) => new Set(packet.recent_minute_bars.map(bar => bar.c)).size > 40)).toBe(true);
  const mu = page.getByRole("article", { name: "MU sample opportunity" });
  await mu.getByLabel("MU choice").selectOption("take");
  await mu.getByLabel("MU reason").fill("Conditional long plan; the replay must confirm its trigger before entry.");
  await mu.getByRole("button", { name: "Save MU decision", exact: true }).click();
  await expect(mu.getByRole("button", { name: "Reopen saved MU decision", exact: true })).toBeVisible();
  const saved = (await (await page.request.get(`/api/backend/practice/runs/${run.id}`)).json()).opportunities.find((opp: { symbol: string }) => opp.symbol === "MU");
  const button = mu.getByRole("button", { name: "Start MU sample replay", exact: true });
  await expect(button).toBeEnabled();
  await button.dblclick();
  const panel = mu.getByRole("region", { name: "MU sample paper replay" });
  await expect(panel.getByRole("heading", { name: "Sample paper replay · closed", exact: true })).toBeVisible();
  await expect(panel.getByRole("list", { name: "MU replay timeline" }).getByRole("listitem")).toHaveCount(5);
  await expect(panel.getByText("Sample entry per share", { exact: true })).toBeVisible();
  await expect(panel.getByText("Net per share at 3× sample costs", { exact: true })).toBeVisible();
  const complete = (await (await page.request.get(`/api/backend/practice/runs/${run.id}`)).json()).opportunities.find((opp: { symbol: string }) => opp.symbol === "MU");
  expect(complete.choice).toEqual(saved.choice);
  expect(complete.replay.events.map((event: { type: string }) => event.type)).toEqual(["armed", "trigger", "order_intent", "entry", "exit"]);
  const auth = await (await page.request.get("/api/access/me")).json();
  const retry = await page.request.post(`/api/backend/practice/opportunities/${complete.id}/sample-replay`, { headers: { Origin: assistantOrigin, "x-tj-csrf": auth.csrf }, data: {} });
  expect(retry.status()).toBe(200);
  expect((await retry.json()).opportunities.find((opp: { symbol: string }) => opp.symbol === "MU").replay).toEqual(complete.replay);
  expect((await page.request.post(`/api/backend/decisions/${complete.choice.id}/arm`, { headers: { Origin: assistantOrigin, "x-tj-csrf": auth.csrf }, data: { operation_id: "not-live" } })).status()).toBe(403);
  await page.goto(`/daily/${run.day}?practice_run=${run.id}`);
  await page.reload();
  await page.getByRole("button", { name: "Reopen MU sample replay", exact: true }).click();
  await expect(page.getByRole("region", { name: "MU sample paper replay" }).getByRole("status")).toContainText("original replay reopened");
  const reopened = (await (await page.request.get(`/api/backend/practice/runs/${run.id}`)).json()).opportunities.find((opp: { symbol: string }) => opp.symbol === "MU");
  expect(reopened.replay.receipt_sha256).toBe(complete.replay.receipt_sha256);
  expect(reopened.choice.record_sha256).toBe(saved.choice.record_sha256);
  const nbis = page.getByRole("article", { name: "NBIS sample opportunity" });
  await nbis.getByLabel("NBIS reason").fill("No conditional plan selected in this invented exercise.");
  await nbis.getByRole("button", { name: "Save NBIS decision", exact: true }).click();
  await expect(nbis.getByText("SKIP stays unarmed and creates no paper entry.", { exact: true })).toBeVisible();
  await expect(nbis.getByRole("button", { name: "Start NBIS sample replay" })).toHaveCount(0);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
  await page.getByRole("region", { name: "MU sample paper replay" }).screenshot({ path: test.info().outputPath("sample-paper-replay-phone.png") });
  expect(errors).toEqual([]);
});

test("a delayed pre-start reload cannot hide the committed replay receipt", async ({ page, browser }) => {
  await login(page, browser, true, true);
  const mu = page.getByRole("article", { name: "MU sample opportunity" });
  await mu.getByLabel("MU choice").selectOption("take");
  await mu.getByLabel("MU reason").fill("Conditional sample plan before the hidden continuation.");
  await mu.getByRole("button", { name: "Save MU decision", exact: true }).click();
  await expect(mu.getByRole("button", { name: "Start MU sample replay", exact: true })).toBeEnabled();
  let release: (() => void) | undefined;
  let captured: (() => void) | undefined;
  const pending = new Promise<void>(resolve => { release = resolve; });
  const seen = new Promise<void>(resolve => { captured = resolve; });
  await page.route("**/api/backend/practice/runs/*", async route => {
    const before = await route.fetch(); captured?.(); await pending; await route.fulfill({ response: before });
  });
  await page.getByRole("button", { name: "Reload saved practice" }).click();
  await seen;
  await mu.getByRole("button", { name: "Start MU sample replay", exact: true }).click();
  const closed = mu.getByRole("heading", { name: "Sample paper replay · closed", exact: true });
  await expect(closed).toBeVisible();
  release?.();
  await expect(page.getByRole("button", { name: "Reload saved practice" })).toBeEnabled();
  await expect(closed).toBeVisible();
  await expect(mu.getByRole("button", { name: "Start MU sample replay", exact: true })).toHaveCount(0);
});


test("frozen reducer aligns quarters, preserves gaps and refuses invalid source data", () => {
  const start = Date.parse("2026-10-09T13:07:00Z");
  const bars = Array.from({ length: 30 }, (_, i) => ({ t: new Date(start+i*60000).toISOString(),
    o: 100+i, h: 102+i, l: 99+i, c: 101+i, v: 10+i, vw: i === 12 ? null : 100.5+i }));
  const original = JSON.stringify(bars);
  const cutoff = "2026-10-09T13:37:05Z";
  const result = frozenWindow([...bars].reverse(), cutoff);
  expect(JSON.stringify(bars)).toBe(original);
  expect(result.quarters.map(b => [new Date(b.at).toISOString(),b.count,b.complete])).toEqual([
    ["2026-10-09T13:00:00.000Z",8,false], ["2026-10-09T13:15:00.000Z",15,true], ["2026-10-09T13:30:00.000Z",7,false]]);
  expect(result.quarters[1]).toMatchObject({o:108,h:124,l:107,c:123,v:375,vw:122.5});
  expect(result.minutes[12].vw).toBeNull();
  const gap = frozenWindow(bars.filter((_,i) => i !== 12),cutoff);
  expect(gap.minutes).toHaveLength(29);expect(gap.quarters[1]).toMatchObject({count:14,complete:false,v:353});
  for (const invalid of [ [...bars,bars[0]], [{...bars[0],t:"2026-10-09T13:07:01Z"}],
    [{...bars[0],h:90}], [{...bars[0],v:null}], [{...bars[0],o:Infinity}],
    [{...bars[0],t:"2026-10-09T13:37:00Z"}] ]) expect(() => frozenWindow(invalid,cutoff)).toThrow();
  expect(() => frozenWindow(bars,"2026-10-09T13:37:05")).toThrow();
  expect(frozenWindow([{...bars[0],t:"2026-10-09T09:07:00-04:00"}],cutoff).minutes[0].at).toBe(start);
});

test("frozen chart matches the assigned packet through decisions, replay and reload", async ({ page,browser }) => {
  const live: string[] = [], errors: string[] = [];
  page.on("request", request => { if (/\/api\/backend\/(charts|packets)(?:[/?]|$)/.test(request.url())) live.push(request.url()); });
  page.on("pageerror", error => errors.push(error.message));
  const run = await login(page,browser,true,true);
  const before = await (await page.request.get(`/api/backend/practice/runs/${run.id}`)).json();
  const mu = before.opportunities.find((o: {symbol:string}) => o.symbol === "MU");
  const region = page.getByRole("region",{name:"MU frozen evidence chart"});
  await expect(region).toHaveAttribute("data-context-id",mu.context.context_id);
  await expect(region).toHaveAttribute("data-evidence-sha256",mu.context.context_sha256);
  await expect(region.getByRole("img",{name:"MU frozen 1m price and volume"})).toBeVisible();
  await expect(region.locator("g[data-minute-start]")).toHaveCount(60);
  await expect(region.getByTestId("frozen-vwap-legend")).toContainText("supplied packet VWAP per minute");
  await expect(region.getByTestId("frozen-vwap-legend")).not.toContainText("15-minute");
  expect(await region.locator("text[data-time-tick]").count()).toBeGreaterThan(2);
  const nbisRegion = page.getByRole("region",{name:"NBIS frozen evidence chart"});
  const labelBox = await nbisRegion.getByLabel("NBIS frozen plan levels").boundingBox();
  const plotBox = await nbisRegion.getByRole("img").boundingBox();
  expect(labelBox!.y).toBeGreaterThanOrEqual(plotBox!.y+plotBox!.height);
  await expect(nbisRegion.locator("svg text").filter({hasText:"Trigger"})).toHaveCount(0);
  const firstBar = [...mu.context.packet.recent_minute_bars].sort((a,b)=>Date.parse(a.t)-Date.parse(b.t))[0];
  await expect(region.locator(`g[data-minute-start="${new Date(firstBar.t).toISOString()}"] title`)).toContainText(`packet VWAP $${firstBar.vw.toFixed(4)}`);
  await region.getByRole("button",{name:"15m",exact:true}).click();
  await expect(region.getByRole("button",{name:"15m",exact:true})).toHaveAttribute("aria-pressed","true");
  await expect(region.getByTestId("frozen-vwap-legend")).toContainText("per complete 15-minute interval");
  const raw = mu.context.packet.recent_minute_bars as {t:string;o:number;h:number;l:number;c:number;v:number;vw:number|null}[];
  const grouped = new Map<number,typeof raw>();
  for (const bar of [...raw].sort((a,b) => Date.parse(a.t)-Date.parse(b.t))) {
    const key = Math.floor(Date.parse(bar.t)/900000)*900000;grouped.set(key,[...(grouped.get(key)??[]),bar]);
  }
  const table = region.getByRole("table",{name:"MU frozen 15-minute summary"});
  for (const [at,bars] of grouped) {
    const row = table.locator(`tr[data-start="${new Date(at).toISOString()}"]`);
    const cells = await row.getByRole("cell").allTextContents();
    expect(cells).toEqual([`${bars.length===15?"Complete":"Partial"} · ${bars.length}/15`,
      `$${bars.at(-1)!.c.toFixed(4)}`,bars.reduce((n,b)=>n+b.v,0).toLocaleString("en-US"),bars.at(-1)!.vw === null ? "Unavailable" : `$${bars.at(-1)!.vw!.toFixed(4)}`,...[bars[0].o,Math.max(...bars.map(b=>b.h)),Math.min(...bars.map(b=>b.l))].map(p=>`$${p.toFixed(4)}`)]);
  }
  const summary = await table.textContent();
  const article = page.getByRole("article",{name:"MU sample opportunity"});
  await article.getByLabel("MU choice").selectOption("take");await article.getByLabel("MU reason").fill("Frozen-chart workflow proof; conditional sample plan.");
  await article.getByRole("button",{name:"Save MU decision",exact:true}).click();
  await expect(article.getByRole("button",{name:"Start MU sample replay",exact:true})).toBeEnabled();
  await article.getByRole("button",{name:"Start MU sample replay",exact:true}).click();
  await expect(article.getByRole("heading",{name:"Sample paper replay · closed",exact:true})).toBeVisible();
  expect(await table.textContent()).toBe(summary);
  const after = (await (await page.request.get(`/api/backend/practice/runs/${run.id}`)).json()).opportunities.find((o:{symbol:string})=>o.symbol==="MU");
  expect(after.context).toEqual(mu.context);
  await page.reload();await expect(region).toHaveAttribute("data-evidence-sha256",mu.context.context_sha256);
  expect(await table.textContent()).toBe(summary);
  await page.setViewportSize({width:390,height:844});expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBe(390);
  await region.screenshot({path:test.info().outputPath("frozen-evidence-phone.png")});
  await page.setViewportSize({width:1440,height:1000});await article.screenshot({path:test.info().outputPath("frozen-evidence-desktop.png")});
  expect(live).toEqual([]);expect(errors).toEqual([]);
});

test("unusable frozen bars show an explicit unavailable chart without replacing the packet", async ({page,browser}) => {
  const run = await login(page,browser,true,true);
  await page.route(`**/api/backend/practice/runs/${run.id}`,async route => {
    const response = await route.fetch(), body = JSON.parse(await response.text());
    body.opportunities[0].context.packet.recent_minute_bars[0].v = null;
    await route.fulfill({response,json:body});
  });
  await page.getByRole("button",{name:"Reload saved practice"}).click();
  await expect(page.getByText(/Chart unavailable: Invalid frozen price or volume/)).toBeVisible();
  await expect(page.getByText("Inspect frozen packet and rules").first()).toBeVisible();
  await page.unrouteAll({behavior:"wait"});
});


test("isolated supplied VWAP is visible in both minute and quarter views", async ({page,browser}) => {
  await login(page,browser,true,true);
  await page.route("**/api/backend/practice/runs/*",async route => {
    const response=await route.fetch(),body=await response.json();
    const packet=body.opportunities.find((o:{symbol:string})=>o.symbol==="MU").context.packet;
    const grouped=new Map<number,{t:string;vw:number|null}[]>();
    for (const bar of packet.recent_minute_bars as {t:string;vw:number|null}[]) {
      const key=Math.floor(Date.parse(bar.t)/900000);grouped.set(key,[...(grouped.get(key)??[]),bar]);
    }
    const complete=[...grouped.values()].find(bars=>bars.length===15)!;
    complete.sort((a,b)=>Date.parse(a.t)-Date.parse(b.t));
    packet.recent_minute_bars=complete.map((bar,i)=>({...bar,vw:i===14?bar.vw:null}));
    await route.fulfill({response,json:body});
  });
  await page.getByRole("button",{name:"Reload saved practice"}).click();
  const region=page.getByRole("region",{name:"MU frozen evidence chart"});
  await expect(region.getByTestId("frozen-vwap-point")).toBeVisible();
  await expect(region.getByText(/VWAP unavailable for 14 frozen minutes/)).toBeVisible();
  expect(await region.locator("g[data-minute-start] title").allTextContents()).toEqual(expect.arrayContaining([expect.stringContaining("packet VWAP unavailable")]));
  await region.getByRole("button",{name:"15m",exact:true}).click();
  await expect(region.getByTestId("frozen-vwap-point")).toBeVisible();
  await expect(region.getByRole("table").getByText("Complete · 15/15",{exact:true})).toBeVisible();
});


test("widely separated frozen minutes remain partial with a small time axis", async ({page,browser}) => {
  await login(page,browser,true,true);
  await page.route("**/api/backend/practice/runs/*",async route => {
    const response=await route.fetch(), body=await response.json();
    const context=body.opportunities.find((o:{symbol:string})=>o.symbol==="MU").context;
    const source=context.packet.recent_minute_bars.at(-1);
    context.captured_at="2026-10-09T13:01:00Z";
    context.packet.recent_minute_bars=[{...source,t:"0001-01-01T00:00:00Z"},{...source,t:"2026-10-09T13:00:00Z"}];
    await route.fulfill({response,json:body});
  });
  await page.getByRole("button",{name:"Reload saved practice"}).click();
  const region=page.getByRole("region",{name:"MU frozen evidence chart"});
  await expect(region.locator("g[data-minute-start]")).toHaveCount(2);
  expect(await region.locator("text[data-time-tick]").count()).toBeLessThanOrEqual(6);
  await expect(region.getByRole("table").getByText("Partial · 1/15",{exact:true})).toHaveCount(2);
  await page.unrouteAll({behavior:"wait"});
});

test("market pilot saves source-linked own decisions and privately reviews them without execution", async ({page,browser}) => {
  const owner = await browser.newContext({baseURL:ownerOrigin});
  const auth = await (await owner.request.get("/api/access/me")).json();
  const runs = (await (await owner.request.get("/api/backend/practice/runs")).json()).runs;
  const run = runs.find((r:{market_data?:boolean;historical_replay?:boolean;operational_proof?:boolean}) => r.market_data && !r.historical_replay && r.operational_proof);
  expect(run).toBeTruthy();
  const id = run.assigned_agent.replace("agent:", "");
  const created = await owner.request.post("/api/access/assistants", {headers:{Origin:ownerOrigin,"x-tj-csrf":auth.csrf},data:{identifier:id,grants:{symbols:["MU","NBIS"],run_ids:[run.id],journal_read:false,market_decision_write:true}}});
  expect(created.status()).toBe(201);
  await page.goto("/login");
  await page.getByLabel("Assistant ID").fill(id);
  await page.getByLabel("Access key").fill((await created.json()).key);
  await page.getByRole("button",{name:"Sign in",exact:true}).click();
  await expect(page.getByText("Real market decision pilot",{exact:true})).toBeVisible();
  const data = await (await page.request.get(`/api/backend/practice/runs/${run.id}`)).json();
  expect(data.sample_data).toBe(false);
  const mu = page.getByRole("article",{name:"MU market opportunity"});
  const muData = data.opportunities.find((o:{symbol:string})=>o.symbol==="MU");
  await expect(mu.getByText("Frozen real-market evidence",{exact:true})).toBeVisible();
  await expect(mu.getByText(/Supplied minute coverage/)).toBeVisible();
  await expect(mu.getByText(/Packet input failures:/)).toBeVisible();
  await expect(mu.getByRole("link",{name:"Open MU chart"})).toHaveCount(0);
  await mu.getByLabel("MU reason").fill("Provider-shaped browser fixture decision; not a live market result.");
  if (!muData.take_unavailable) {
    await mu.getByLabel("MU choice").selectOption("take");
    await mu.getByLabel("MU trigger source fact").selectOption("minute:0:c");
    await mu.getByLabel("MU stop source fact").selectOption("minute:0:l");
    await mu.getByLabel("MU target source fact").selectOption("minute:0:h");
    await mu.getByLabel("MU maximum reference entry price").fill("110.2");
    await page.setViewportSize({width:390,height:844});
    expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBe(390);
    await page.screenshot({path:test.info().outputPath("market-pilot-plan-editor-phone.png"),animations:"disabled"});
    await page.setViewportSize({width:1280,height:900});
  }
  await mu.getByRole("button",{name:"Save MU decision",exact:true}).click();
  await expect(mu.getByText("PRACTICE · UNARMED",{exact:true})).toBeVisible();
  const nbis = page.getByRole("article",{name:"NBIS market opportunity"});
  await nbis.getByLabel("NBIS choice").selectOption("wait");
  await nbis.getByLabel("NBIS reason").fill("Require more current source evidence before choosing a plan.");
  await nbis.getByLabel("NBIS wait condition").fill("A separately captured fresh provider packet.");
  await nbis.getByRole("button",{name:"Save NBIS decision",exact:true}).click();
  await expect(nbis.getByRole("button",{name:"Reopen saved NBIS decision"})).toBeVisible();
  const before=(await (await page.request.get("/api/backend/decisions")).json()).decisions;
  expect(before).toHaveLength(2);
  expect(before.every((r:{actor:string;policy_version:string})=>r.actor===run.assigned_agent && r.policy_version==="practice-market-decision-only-v1")).toBe(true);
  const take=before.find((r:{decision:string})=>r.decision==="take");
  if(take) expect(take.plan.trigger_source.source).toBe("alpaca_iex");
  await page.goto(`/daily/${run.day}?practice_run=${run.id}`);
  await page.reload();
  await page.getByRole("button",{name:"Reopen saved MU decision"}).click();
  const after=(await (await page.request.get("/api/backend/decisions")).json()).decisions;
  expect(after).toEqual(before);
  const session=await(await page.request.get("/api/access/me")).json();
  for(const path of ["/fills","/trades","/charts/workspace?symbol=MU&watchlist=MU","/packets/analyze?symbol=MU"]) expect((await page.request.get("/api/backend"+path)).status()).toBe(403);
  for(const path of [`/decisions/${before[0].id}/arm`,`/practice/opportunities/${muData.id}/sample-replay`]) expect((await page.request.post("/api/backend"+path,{headers:{Origin:assistantOrigin,"x-tj-csrf":session.csrf},data:{}})).status()).toBe(403);
  const privatePage=await owner.newPage();
  await privatePage.goto(`/daily/${run.day}?practice_run=${run.id}`);
  await expect(privatePage.getByRole("article",{name:"NBIS market opportunity"}).getByText("PRACTICE · UNARMED",{exact:true})).toBeVisible();
  await expect(privatePage.getByRole("button",{name:"Save MU decision"})).toHaveCount(0);
  await privatePage.goto("/");
  const genericCard=privatePage.getByTestId("practice-decisions").locator(`#decision-${before.find((r:{symbol:string})=>r.symbol==="MU").id}`);
  await genericCard.locator("summary").click();
  await expect(genericCard.getByTestId("paper-plan")).toHaveCount(0);
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBe(390);
  await page.screenshot({path:test.info().outputPath("market-pilot-phone.png"),animations:"disabled"});
  await owner.close();
});

test("historical Eastern expiry rejects invalid or ambiguous wall clocks", () => {
  expect(historicalExpiryInstant("2026-10-07 16:00")).toBe("2026-10-07T20:00:00.000Z");
  expect(historicalExpiryInstant("2026-01-07T16:00")).toBe("2026-01-07T21:00:00.000Z");
  for (const value of ["", "2026-02-30 16:00", "2026-03-08 02:30", "2026-11-01 01:30", "10/7/2026 16:00", "2026-10-07 24:00"]) {
    expect(historicalExpiryInstant(value),value).toBeNull();
  }
});

for (const [timezoneId, suffix] of [["America/Los_Angeles", "la"], ["America/New_York", "ny"], ["UTC", "utc"]]) {
  test(`historical expiry keeps the chosen Eastern date in ${timezoneId}`, async ({browser}) => {
    const owner = await browser.newContext({baseURL:ownerOrigin});
    const context = await browser.newContext({baseURL:assistantOrigin, timezoneId});
    try {
      const auth = await (await owner.request.get("/api/access/me")).json();
      const runs = (await (await owner.request.get("/api/backend/practice/runs")).json()).runs;
      const run = runs.find((r:{assigned_agent?:string})=>r.assigned_agent?.startsWith("agent:historical-expiry-") && r.assigned_agent.endsWith(`-${suffix}`));
      expect(run).toBeTruthy();
      const identity = run.assigned_agent.replace("agent:", "");
      const created = await owner.request.post("/api/access/assistants", {headers:{Origin:ownerOrigin,"x-tj-csrf":auth.csrf},data:{identifier:identity,grants:{symbols:["MU","NBIS"],run_ids:[run.id],journal_read:false,market_decision_write:true,historical_replay:true}}});
      expect(created.status()).toBe(201);
      const page = await context.newPage();
      await page.goto("/login");
      await page.getByLabel("Assistant ID").fill(identity);
      await page.getByLabel("Access key").fill((await created.json()).key);
      await page.getByRole("button",{name:"Sign in",exact:true}).click();
      await expect(page.getByText("Historical market replay trial",{exact:true})).toBeVisible();
      await page.goto(`/daily/${run.day}?practice_run=${run.id}`);
      const mu = page.getByRole("article",{name:"MU historical opportunity"});
      await mu.getByLabel("MU choice").selectOption("wait");
      const expiry = mu.getByLabel(/MU waiting ends/);
      await expect(expiry).toHaveValue("");
      await expect(expiry).toHaveAccessibleName("MU waiting ends (historical clock · Eastern time)");
      await mu.getByLabel("MU reason").fill("Wait until the chosen first-session close, not the second-session default.");
      await mu.getByLabel("MU wait condition").fill(`Reassess before ${run.day} at 4 PM ET.`);
      const save = mu.getByRole("button",{name:"Save MU decision",exact:true});
      await expect(save).toBeDisabled();
      const intended = new Date(`${run.day}T20:00:00Z`);
      const cutoff = (await (await page.request.get(`/api/backend/practice/runs/${run.id}`)).json()).opportunities[0].context.packet.simulated_as_of;
      // Derive 16:00 ET for this fixture's actual season, independent of browser timezone.
      const eastern = new Intl.DateTimeFormat("sv-SE",{timeZone:"America/New_York",year:"numeric",month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",hourCycle:"h23"});
      if (eastern.format(intended).slice(-5)!=="16:00") intended.setUTCHours(21);
      await expiry.fill(`${run.day} 13:45`);
      await expect(mu.getByRole("alert")).toContainText("Expiry must be after the historical cutoff");
      await expect(save).toBeDisabled();
      await expiry.fill("2026-02-30 16:00");
      await expect(mu.locator("form time[datetime]")).toHaveCount(0);
      await expect(save).toBeDisabled();
      await expiry.fill(`${run.day} 16:00`);
      const preview = mu.locator("form time[datetime]").first();
      await expect(preview).toHaveAttribute("datetime",intended.toISOString());
      await expect(mu.getByText(intended.toISOString(),{exact:true})).toBeVisible();
      await expect(save).toBeDisabled();
      const confirm = mu.getByRole("checkbox",{name:/Confirm MU expiry/});
      await confirm.check();
      await expect(save).toBeEnabled();
      await mu.getByLabel("MU wait condition").fill(`Updated condition before ${run.day} at 4 PM ET.`);
      await expect(confirm).not.toBeChecked();
      await expect(save).toBeDisabled();
      await confirm.check();
      await expiry.fill(`${run.day} 15:59`);
      await expect(confirm).not.toBeChecked();
      await expect(save).toBeDisabled();
      await expiry.fill(`${run.day} 16:00`);
      await confirm.check();
      if (timezoneId === "America/Los_Angeles") {
        await page.setViewportSize({width:390,height:844});
        expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBe(390);
        await mu.screenshot({path:test.info().outputPath("historical-eastern-expiry-phone.png")});
      }
      await save.click();
      await expect(mu.getByRole("button",{name:"Reopen saved MU decision"})).toBeVisible();
      const saved = (await (await page.request.get(`/api/backend/practice/runs/${run.id}`)).json()).opportunities.find((o:{symbol:string})=>o.symbol==="MU").choice;
      expect(new Date(saved.wait_expiry).toISOString()).toBe(intended.toISOString());
      expect(new Date(saved.input_cutoff).toISOString()).toBe(new Date(cutoff).toISOString());
      await page.reload();
      await mu.getByRole("button",{name:"Reopen saved MU decision"}).click();
      const reopened = await (await page.request.get(`/api/backend/decisions/${saved.id}`)).json();
      expect(reopened).toEqual(saved);
      await expect(mu.getByText(`${intended.toLocaleString("en-US",{timeZone:"America/New_York"})} ET`,{exact:true})).toBeVisible();
    } finally {
      await context.close().catch(()=>{});
      await owner.close().catch(()=>{});
    }
  });
}

test("historical replay preserves source clocks and continuation isolation for its assigned writer", async ({page,browser}) => {
  const errors: string[] = [];
  const forbidden: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("request", request => {
    if (/\/api\/backend\/(charts|packets)(?:[/?]|$)|\/sample-replay(?:[/?]|$)|\/charts\/stream/.test(request.url())) forbidden.push(request.url());
  });
  const owner = await browser.newContext({baseURL:ownerOrigin});
  const auth = await (await owner.request.get("/api/access/me")).json();
  const runs = (await (await owner.request.get("/api/backend/practice/runs")).json()).runs;
  const run = runs.find((item:{historical_replay?:boolean;operational_proof?:boolean;assigned_agent?:string}) => item.historical_replay && item.operational_proof && item.assigned_agent?.startsWith("agent:historical-browser-"));
  expect(run, "the deterministic historical browser proof run must be installed").toBeTruthy();
  const identity = run.assigned_agent.replace("agent:", "");
  const created = await owner.request.post("/api/access/assistants", {headers:{Origin:ownerOrigin,"x-tj-csrf":auth.csrf},data:{identifier:identity,grants:{symbols:["MU","NBIS"],run_ids:[run.id],journal_read:false,market_decision_write:true,historical_replay:true}}});
  expect(created.status()).toBe(201);
  await page.goto("/login");
  await page.getByLabel("Assistant ID").fill(identity);
  await page.getByLabel("Access key").fill((await created.json()).key);
  await page.getByRole("button",{name:"Sign in",exact:true}).click();
  await expect(page.getByText("Historical market replay trial",{exact:true})).toBeVisible();
  await expect(page.getByRole("heading",{name:"Historical market replay practice",exact:true})).toBeVisible();
  const before = await (await page.request.get(`/api/backend/practice/runs/${run.id}`)).json();
  expect(before.sample_data).toBe(false);
  expect(before.market_data).toBe(true);
  expect(before.opportunities.every((item:{replay:unknown}) => item.replay === null)).toBe(true);
  const muData = before.opportunities.find((item:{symbol:string}) => item.symbol === "MU");
  const nbisPacket = before.opportunities.find((item:{symbol:string}) => item.symbol === "NBIS").context.packet;
  expect(muData.context.packet).toMatchObject({historical_replay:true,market_pilot:false,sample_data:false});
  expect(muData.context.packet.simulated_as_of).not.toBe(muData.context.captured_at);
  const mu = page.getByRole("article",{name:"MU historical opportunity"});
  await expect(mu.getByRole("region",{name:"MU frozen evidence chart"})).toBeVisible();
  await expect(mu.getByText(/Simulated information cutoff/)).toBeVisible();
  await expect(mu.getByText(/Real decision deadline/)).toBeVisible();
  await expect(mu.getByText(/120 minutes/)).toBeVisible();
  await expect(mu.getByText(/missing minute slots/)).toBeVisible();
  await expect(mu.getByText(/Packet input failures:/)).toBeVisible();
  await expect(mu.getByRole("link",{name:"Open MU chart"})).toHaveCount(0);
  await expect(mu.getByRole("button",{name:/sample replay/i})).toHaveCount(0);
  const start = Date.parse(nbisPacket.window_start);
  const end = Date.parse(nbisPacket.window_end);
  const supplied = new Set((nbisPacket.recent_minute_bars as {t:string}[]).map(bar=>Date.parse(bar.t)));
  const missing = Array.from({length:(end-start)/60_000},(_,i)=>start+i*60_000).filter(at=>!supplied.has(at));
  const nbis = page.getByRole("article",{name:"NBIS historical opportunity"});
  await expect(nbis.getByText(new RegExp(`${missing.length} missing minute slots? in the declared coverage window`))).toBeVisible();
  await expect(nbis.getByText(/Packet input failures:/)).toBeVisible();
  if (missing.length) {
    await nbis.getByText(`Original missing minute timestamps (${missing.length})`,{exact:true}).click();
    for (const at of missing) await expect(nbis.getByText(`${new Date(at).toLocaleString("en-US",{timeZone:"America/New_York"})} ET`,{exact:true})).toBeVisible();
  }
  await mu.getByLabel("MU choice").selectOption("take");
  await mu.getByLabel("MU reason").fill("Source-linked historical long plan; review only after saving the choice.");
  await mu.getByLabel("MU trigger source fact").selectOption("minute:0:c");
  await mu.getByLabel("MU stop source fact").selectOption("minute:0:l");
  await mu.getByLabel("MU target source fact").selectOption("minute:0:h");
  await mu.getByLabel("MU maximum reference entry price").fill("110.5");
  const expiry = mu.getByLabel(/MU plan ends/);
  await expect(expiry).toHaveValue("");
  const maxWall = new Intl.DateTimeFormat("sv-SE",{timeZone:"America/New_York",year:"numeric",month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",hourCycle:"h23"}).format(new Date(muData.context.packet.plan_expiry_max));
  await expiry.fill(maxWall);
  await mu.getByRole("checkbox",{name:/Confirm MU expiry/}).check();
  await mu.getByRole("button",{name:"Save MU decision",exact:true}).click();
  await expect(mu.getByRole("button",{name:"Start MU historical replay",exact:true})).toBeEnabled();
  const saved = (await (await page.request.get(`/api/backend/practice/runs/${run.id}`)).json()).opportunities.find((item:{symbol:string})=>item.symbol==="MU");
  expect(saved.replay).toBeNull();
  const ownerPage = await owner.newPage();
  await ownerPage.goto(`/daily/${run.day}?practice_run=${run.id}`);
  const ownerMu = ownerPage.getByRole("article",{name:"MU historical opportunity"});
  await expect(ownerMu.getByRole("button",{name:"Start MU historical replay",exact:true})).toBeDisabled();
  await nbis.getByLabel("NBIS choice").selectOption("wait");
  await nbis.getByLabel("NBIS reason").fill("Wait for another source-linked condition.");
  await nbis.getByLabel("NBIS wait condition").fill("Reassess after the next verified session.");
  await nbis.getByLabel(/NBIS waiting ends/).fill(maxWall);
  await nbis.getByRole("checkbox",{name:/Confirm NBIS expiry/}).check();
  await nbis.getByRole("button",{name:"Save NBIS decision",exact:true}).click();
  await expect(nbis.getByRole("region",{name:"NBIS historical paper replay"})).toHaveCount(0);
  await expect(nbis.getByRole("button",{name:"Start NBIS historical replay"})).toHaveCount(0);
  await page.goto(`/daily/${run.day}?practice_run=${run.id}`);
  await page.reload();
  await mu.getByRole("button",{name:"Reopen saved MU decision"}).click();
  const savedCard = mu.locator("details[data-decision-id]");
  await expect(savedCard).toHaveAttribute("open","");
  await savedCard.locator("summary").click();
  await expect(savedCard).not.toHaveAttribute("open","");
  await mu.getByRole("button",{name:"Reopen saved MU decision"}).click();
  await expect(savedCard).toHaveAttribute("open","");
  await expect(mu.getByRole("button",{name:"Start MU historical replay",exact:true})).toBeEnabled();
  await mu.getByRole("button",{name:"Start MU historical replay",exact:true}).click();
  const panel = mu.getByRole("region",{name:"MU historical paper replay"});
  await expect(panel.getByRole("heading",{name:/Historical paper replay · /})).toBeVisible();
  const complete = (await (await page.request.get(`/api/backend/practice/runs/${run.id}`)).json()).opportunities.find((item:{symbol:string})=>item.symbol==="MU");
  expect(complete.replay.clock).toBe("historical_epoch_seconds");
  expect(complete.replay.events.length).toBeGreaterThan(0);
  for (const event of complete.replay.events) expect(Number.isInteger(event.at)).toBe(true);
  const firstEvent = complete.replay.events[0];
  await expect(panel.getByRole("listitem").first().locator("time")).toHaveAttribute("dateTime",new Date(firstEvent.at*1000).toISOString());
  await expect(panel.getByText(/ET/).first()).toBeVisible();
  expect((await (await page.request.get(`/api/backend/practice/runs/${run.id}`)).json()).opportunities.find((item:{symbol:string})=>item.symbol==="NBIS").replay).toBeNull();

  await ownerPage.reload();
  await expect(ownerMu.getByRole("button",{name:"Reopen MU historical replay",exact:true})).toBeVisible();
  await expect(ownerMu.getByRole("button",{name:"Start MU historical replay",exact:true})).toHaveCount(0);
  await ownerMu.getByRole("button",{name:"Reopen MU historical replay",exact:true}).click();
  await expect(ownerMu.getByRole("region",{name:"MU historical paper replay"}).getByRole("status")).toContainText("original replay reopened");
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBe(390);
  expect(forbidden).toEqual([]);
  expect(errors).toEqual([]);
  await owner.close();
});
