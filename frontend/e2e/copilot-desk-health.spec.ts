import { expect, test, type Page } from "@playwright/test";

// The desk's data health (docs/copilot-lab.md § Data health): one dot in the top bar, green alone ("All live" as its name)
// when every running source is live, amber naming what is behind, grey alone when it cannot tell. A tap lists each source with its last
// good time; a tap on one says what it affects and the existing fix. It rides the minute's one request (no poll of its
// own). Level 2 is the Tape's session: off with none. Every route is stubbed; every number is invented.
const ON = {
  enabled: true, backend: "fake", evidence: "live", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
// Friday November 13, 2026, 11:00 in New York: in the session.
const NOW = new Date("2026-11-13T16:00:00Z");
const epoch = (iso: string) => Date.parse(iso) / 1000;
const THREADS = {
  as_of: "2026-11-13T16:00:00Z", quotes_at: null, quote_issue: null, day: { phase: "regular", need_you: 0, streak: null },
  sections: { positions: "ok" }, plans: [], robinhood: { state: "off" }, threads: [],
};
const SESSION = {
  as_of: "2026-11-13T16:00:00Z", now: epoch("2026-11-13T16:00:00Z"), day: "2026-11-13", phase: "regular",
  open: epoch("2026-11-13T14:30:00Z"), close: epoch("2026-11-13T21:00:00Z"), events: [], time_stops: [], pings: null, prep: null,
  indices: [], quote_issue: null, realized_today: 0, sections: {},
};
type Row = { id: string; name: string; state: string; line: string; last_at: number | null; affects: string; fix: unknown };
const row = (id: string, name: string, state: string, line: string, fix: unknown = null): Row =>
  ({ id, name, state, line, last_at: epoch("2026-11-13T15:58:00Z"), affects: `${name} affects this.`, fix });
const LIVE: Row[] = [
  row("robinhood", "Robinhood", "live", "Live · read 10:59"),
  row("prices", "Prices", "live", "Live"),
  row("chatter", "Chatter", "live", "Live · read 10:54"),
  row("tradingview", "TradingView", "quiet", "No alerts today · last Thu 15:42"),
  row("gmail", "Fill emails", "live", "Live · last email 10:19"),
  row("radar", "Radar", "live", "Recording · pass 10:59"),
  row("budget", "Copilot budget", "live", "$2.40 left of $4.00 today"),
];
const health = (sources: Row[]) => ({
  as_of: "2026-11-13T16:00:00Z", now: epoch("2026-11-13T16:00:00Z"), phase: "regular",
  overall: sources.some(s => ["stale", "down", "low"].includes(s.state)) ? "bad" : sources.some(s => s.state === "unknown") ? "unknown" : "ok", sources,
});

type Seen = string[];
async function open(page: Page, first: unknown, { width = 1440, height = 900, status = 200 } = {}) {
  const answer = { body: first, status };
  const reads: Record<string, () => { status: number; body: unknown }> = {
    "/copilot/desk/threads": () => ({ status: 200, body: THREADS }),
    "/copilot/desk/session": () => ({ status: 200, body: SESSION }),
    "/copilot/desk/watching": () => ({ status: 200, body: { state: "ok", symbols: [], count: 0, max: 30, imported_at: null, robinhood: "off", levels: {}, setups: {} } }),
    "/copilot/desk/sparks": () => ({ status: 200, body: { as_of: "2026-11-13T16:00:00Z", spy_change_pct: 0.4, rows: {} } }),
    "/copilot/desk/feed": () => ({ status: 200, body: { as_of: "2026-11-13T16:00:00Z", now: epoch("2026-11-13T16:00:00Z"), day: "2026-11-13", total: 0, sources: {}, unavailable: [], items: [] } }),
    "/copilot/investigations": () => ({ status: 200, body: { investigations: [] } }),
    "/copilot/tickets": () => ({ status: 200, body: { plans: [] } }),
    "/copilot/exposure": () => ({ status: 200, body: { line: null } }),
    "/copilot/desk/health": () => ({ status: answer.status, body: answer.body }),
  };
  const seen: Seen = [];
  await page.setViewportSize({ width, height });
  await page.clock.install({ time: NOW });
  page.on("request", request => {
    const url = new URL(request.url());
    if (url.pathname.startsWith("/api/backend/")) seen.push(url.pathname.replace(/^\/api\/backend/, ""));
  });
  await page.route("**/api/backend/**", route => route.fulfill({ status: 404, json: { detail: "Not in this test." } }));
  await page.route("**/copilot/status", route => route.fulfill({ json: ON }));
  for (const [path, read] of Object.entries(reads)) {
    await page.route(url => url.pathname.endsWith(path), route => { const r = read(); return route.fulfill({ status: r.status, json: r.body }); });
  }
  await page.route("**/copilot/desk/minute?*", route => {
    const answers = new URL(route.request().url()).searchParams.getAll("read").map(target => {
      const read = reads[target.split("?")[0]];
      return read ? read() : { status: 404, body: { detail: "Not in this test." } };
    });
    return route.fulfill({ json: { reads: answers } });
  });
  await page.goto("/copilot-lab");
  await expect(page.getByTestId("desk-book")).toBeVisible();
  return { seen, answer };
}

test("all live: one quiet green dot; the list names every source, Level 2 off with no Tape session", async ({ page }) => {
  await open(page, health(LIVE));
  const dot = page.getByTestId("desk-health");
  await expect(dot).toHaveAttribute("data-tone", "ok");
  await expect(dot).toHaveAccessibleName("Data health: All live");
  await expect(dot).toHaveText(""); // quiet: the dot alone
  await dot.click();
  const list = page.getByTestId("desk-health-list");
  await expect(list.getByRole("listitem")).toHaveCount(8);
  await expect(list.getByRole("listitem").nth(2)).toHaveAttribute("data-testid", "health-level2"); // after prices
  await expect(list.getByTestId("health-level2")).toHaveAttribute("data-state", "off");
  await expect(list.getByTestId("health-level2")).toContainText("Off · no Tape session open");
  await expect(list.getByTestId("health-tradingview")).toContainText("No alerts today · last Thu 15:42");
  await page.keyboard.press("Escape");
  await expect(list).toHaveCount(0);
});

test("a source down: the dot turns amber and names it; a tap says what it affects and the existing fix", async ({ page }) => {
  const sources = LIVE.map(r => r.id === "robinhood"
    ? row("robinhood", "Robinhood", "down", "Last read 9:41, signed out", { kind: "text", text: "Sign in again with the Robinhood sign-in helper." })
    : r.id === "gmail" ? row("gmail", "Fill emails", "down", "Gmail disconnected · last email 10:19", { kind: "gmail_reconnect" }) : r);
  await open(page, health(sources));
  const dot = page.getByTestId("desk-health");
  await expect(dot).toHaveAttribute("data-tone", "bad");
  await expect(dot).toHaveText("2 sources behind");
  await expect(dot).toHaveAccessibleName("Data health: 2 sources behind");
  await dot.click();
  const rh = page.getByTestId("health-robinhood");
  await expect(rh).toHaveAttribute("data-state", "down");
  await expect(rh).toContainText("Robinhood");
  await expect(rh).toContainText("Last read 9:41, signed out");
  await rh.getByRole("button").click();
  await expect(page.getByTestId("health-robinhood-more")).toContainText("Robinhood affects this.");
  await expect(page.getByTestId("health-robinhood-more")).toContainText("Sign in again with the Robinhood sign-in helper.");
  await page.getByTestId("health-gmail").getByRole("button").first().click();
  const reconnect = page.getByTestId("health-gmail-more").getByRole("button", { name: "Reconnect Gmail" });
  await expect(reconnect).toBeVisible();
  const asked = page.waitForRequest(request => new URL(request.url()).pathname.endsWith("/auth/gmail/start"));
  await reconnect.click();
  await asked; // the existing sign-in path (stubbed here as a refusal, so the page stays)
});

test("unknown is never green: a source that cannot be told and a failed read both show grey", async ({ page }) => {
  const sources = LIVE.map(r => r.id === "prices" ? row("prices", "Prices", "unknown", "No price read yet") : r);
  await open(page, health(sources));
  await expect(page.getByTestId("desk-health")).toHaveAttribute("data-tone", "unknown");
  await expect(page.getByTestId("desk-health")).toHaveAccessibleName("Data health: Prices unknown");
  await expect(page.getByTestId("desk-health")).toHaveText("");
});

test("a failed health read says unknown, not all live", async ({ page }) => {
  await open(page, { detail: "boom" }, { status: 500 });
  await expect(page.getByTestId("desk-health")).toHaveAttribute("data-tone", "unknown");
  await expect(page.getByTestId("desk-health")).toHaveAccessibleName("Data health: Health unknown");
});

test("a failed read after a good one: grey, and the old rows are not shown as live", async ({ page }) => {
  const { answer } = await open(page, health(LIVE));
  await expect(page.getByTestId("desk-health")).toHaveAccessibleName("Data health: All live");
  answer.status = 500;
  answer.body = { detail: "boom" };
  await page.clock.runFor(61_000);
  await expect(page.getByTestId("desk-health")).toHaveAccessibleName("Data health: Health unknown");
  await page.getByTestId("desk-health").click();
  const list = page.getByTestId("desk-health-list");
  await expect(list).toContainText("Could not check just now");
  await expect(list.getByTestId("health-prices")).toHaveCount(0);
  await expect(list.getByTestId("health-level2")).toHaveAttribute("data-state", "off"); // the Tape's own still shows
});

test("it rides the minute's one request: a change shows on the next beat with no read of its own", async ({ page }) => {
  const { seen, answer } = await open(page, health(LIVE));
  await expect(page.getByTestId("desk-health")).toHaveAccessibleName("Data health: All live");
  await page.clock.runFor(10_000); // the one settle read a few seconds after opening (cold load, not the idle rate)
  await expect.poll(() => seen.filter(p => p === "/copilot/desk/health").length).toBe(2);
  const before = seen.filter(p => p === "/copilot/desk/health").length;
  answer.body = health(LIVE.map(r => r.id === "radar" ? row("radar", "Radar", "stale", "Last pass 10:52") : r));
  await page.clock.runFor(61_000);
  await expect(page.getByTestId("desk-health")).toHaveText("Radar behind");
  expect(seen.filter(p => p === "/copilot/desk/health").length).toBe(before); // asked inside /copilot/desk/minute only
  expect(seen).toContain("/copilot/desk/minute");
});

test("a phone: the dot alone in the header; a tap opens the list on screen", async ({ page }) => {
  await open(page, health(LIVE.map(r => r.id === "chatter" ? row("chatter", "Chatter", "stale", "Last read 9:58") : r)), { width: 390, height: 844 });
  const dot = page.getByTestId("desk-health");
  await expect(dot).toBeVisible();
  await expect(dot).toHaveAccessibleName("Data health: Chatter behind");
  await expect(dot.getByTestId("desk-health-words")).toBeHidden(); // the words are for wider screens
  await dot.click();
  const list = page.getByTestId("desk-health-list");
  await expect(list).toBeInViewport({ ratio: 1 });
  await expect(list.getByTestId("health-chatter")).toContainText("Last read 9:58");
});
