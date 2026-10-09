import { test, expect, type Browser, type Page } from "@playwright/test";
import { frozenWindow } from "../lib/frozen-evidence";
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
  await region.getByRole("button",{name:"15m",exact:true}).click();
  await expect(region.getByRole("button",{name:"15m",exact:true})).toHaveAttribute("aria-pressed","true");
  const raw = mu.context.packet.recent_minute_bars as {t:string;o:number;h:number;l:number;c:number;v:number}[];
  const grouped = new Map<number,typeof raw>();
  for (const bar of [...raw].sort((a,b) => Date.parse(a.t)-Date.parse(b.t))) {
    const key = Math.floor(Date.parse(bar.t)/900000)*900000;grouped.set(key,[...(grouped.get(key)??[]),bar]);
  }
  const table = region.getByRole("table",{name:"MU frozen 15-minute summary"});
  for (const [at,bars] of grouped) {
    const row = table.locator(`tr[data-start="${new Date(at).toISOString()}"]`);
    const cells = await row.getByRole("cell").allTextContents();
    expect(cells).toEqual([`${bars.length===15?"Complete":"Partial"} · ${bars.length}/15`,
      `$${bars.at(-1)!.c.toFixed(4)}`,bars.reduce((n,b)=>n+b.v,0).toLocaleString("en-US"),...[bars[0].o,Math.max(...bars.map(b=>b.h)),Math.min(...bars.map(b=>b.l))].map(p=>`$${p.toFixed(4)}`)]);
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
  await login(page,browser,true,true);
  await page.route("**/api/backend/practice/runs/*",async route => {
    const response = await route.fetch(), body = await response.json();
    body.opportunities[0].context.packet.recent_minute_bars[0].v = null;
    await route.fulfill({response,json:body});
  });
  await page.getByRole("button",{name:"Reload saved practice"}).click();
  await expect(page.getByText(/Chart unavailable: Invalid frozen price or volume/)).toBeVisible();
  await expect(page.getByText("Inspect frozen packet and rules").first()).toBeVisible();
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
  await region.getByRole("button",{name:"15m",exact:true}).click();
  await expect(region.getByTestId("frozen-vwap-point")).toBeVisible();
  await expect(region.getByRole("table").getByText("Complete · 15/15",{exact:true})).toBeVisible();
});
