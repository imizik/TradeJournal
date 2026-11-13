import { expect, test, type Page } from "@playwright/test";

// The desk's Watching list under the book (docs/copilot-lab.md § The desk): the app's own watchlist (the Charts one), a
// compact row per name he watches and does not hold, selected in place like a position, added and removed here (never on
// Robinhood), a held or hidden ticker never shown twice or at all, and folded to one line on a phone.
// Every lab route is stubbed in the browser (the e2e backend runs with the lab off); nothing reaches Robinhood or a model.
const ON = {
  enabled: true, backend: "fake", evidence: "live", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
// Friday November 13, 2026, 11:00 in New York: in the session.
const NOW = new Date("2026-11-13T16:00:00Z");
const epoch = (iso: string) => Date.parse(iso) / 1000;
const ORCL = "99999999-9999-4999-8999-999999999999";
const IREN = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const row = (fields: Record<string, unknown>) => ({
  symbol: null, instrument: null, value: null, meter: null, investigation_id: null, trade_id: null, radar_event_id: null, path: null,
  changed_at: null, ...fields,
});
const book = (fields: Record<string, unknown>) => ({ usd: -120, pct: -12, expiry: "2026-11-20", days_held: 1, track: null, state: "no_plan",
  planned: false, stop_pct: null, ...fields });
const position = (symbol: string, id: string, hidden = false) => row({ key: `trade:${id}`, group: "watch", symbol, title: `${symbol} 11/20/26 50C`,
  instrument: "11/20/26 50C", trade_id: id, value: { text: "−$120.00", tone: "loss" }, status: { text: "No plan yet", tone: "muted" },
  path: `/trades/${id}`, hidden, book: book({}) });
const THREADS = {
  as_of: "2026-11-13T16:00:00Z", quotes_at: null, quote_issue: null, day: { phase: "regular", need_you: 0, streak: null },
  sections: { positions: "ok" }, plans: [], robinhood: { state: "off" },
  // ORCL is held and followed; IREN is held and not followed (hidden everywhere).
  threads: [position("ORCL", ORCL), position("IREN", IREN, true)],
};
const SESSION = {
  as_of: "2026-11-13T16:00:00Z", now: epoch("2026-11-13T16:00:00Z"), day: "2026-11-13", phase: "regular",
  open: epoch("2026-11-13T14:30:00Z"), close: epoch("2026-11-13T21:00:00Z"), events: [], time_stops: [], pings: null, prep: null,
  indices: [{ symbol: "SPY", last: 580.1, change_pct: 0.42 }], quote_issue: null, realized_today: 0, sections: {},
};
const NAMES = ["NVDA", "RKLB", "AMD", "PLTR", "HOOD", "TSLA", "MSFT", "META", "SMCI", "IONQ", "ORCL", "IREN"];
const watching = (symbols: string[]) => ({
  state: "ok", symbols, count: symbols.length, max: 30, imported_at: null, robinhood: "off",
  levels: { NVDA: [{ price: 101, role: "entry" }] }, setups: { IONQ: { at: epoch("2026-11-13T15:42:00Z"), event_id: "rd0-1" } },
});
const MOVES: Record<string, number> = { NVDA: 0.2, RKLB: -6.1, AMD: 1.1, PLTR: 2.4, HOOD: -0.5, TSLA: 3.3, MSFT: 0.1, META: -1.9, SMCI: 5.0, IONQ: 0.3 };
const SPARKS = (watch: string[]) => ({ as_of: "2026-11-13T16:00:00Z", spy_change_pct: 0.4, rows: {
  ORCL: { points: [250, 248, 246], change_pct: -1.2 },
  ...Object.fromEntries(watch.filter(s => MOVES[s] !== undefined).map(s => [s, { points: [99, 100, 100.5], change_pct: MOVES[s], last: 100 }])) } });

type Seen = { sparks: URL[]; added: string[]; removed: string[]; charts: string[] };

async function open(page: Page, { width = 1440, height = 900 } = {}) {
  const seen: Seen = { sparks: [], added: [], removed: [], charts: [] };
  let listed = [...NAMES];
  await page.setViewportSize({ width, height });
  await page.clock.install({ time: NOW });
  await page.route("**/copilot/status", route => route.fulfill({ json: ON }));
  await page.route("**/copilot/desk/threads", route => route.fulfill({ json: THREADS }));
  await page.route("**/copilot/desk/session", route => route.fulfill({ json: SESSION }));
  await page.route("**/copilot/desk/pings*", route => route.fulfill({ json: { day: "2026-11-13", since: "2026-11-12", alerts: { state: "ok", rows: [] }, radar: { state: "off", reason: null, rows: [] } } }));
  await page.route("**/copilot/desk/feed", route => route.fulfill({ json: { as_of: "2026-11-13T16:00:00Z", now: epoch("2026-11-13T16:00:00Z"), day: "2026-11-13", total: 0, sources: {}, unavailable: [], items: [] } }));
  await page.route("**/copilot/desk/sparks?*", route => {
    const url = new URL(route.request().url());
    seen.sparks.push(url);
    return route.fulfill({ json: SPARKS((url.searchParams.get("watch") ?? "").split(",")) });
  });
  await page.route("**/copilot/desk/watching", async route => {
    const request = route.request();
    if (request.method() === "POST") {
      const symbol = request.postDataJSON().symbol as string;
      seen.added.push(symbol);
      if (symbol === "ZZQX") return route.fulfill({ status: 422, json: { detail: "ZZQX is not a symbol the app knows." } });
      listed = [...listed, symbol];
    }
    return route.fulfill({ json: watching(listed) });
  });
  await page.route("**/copilot/desk/watching/*", route => {
    const symbol = decodeURIComponent(new URL(route.request().url()).pathname.split("/").pop()!);
    if (route.request().method() === "DELETE") {
      seen.removed.push(symbol);
      listed = listed.filter(s => s !== symbol);
      return route.fulfill({ json: watching(listed) });
    }
    return route.fulfill({ json: { state: "off", lists: [], not_offered: 0 } });
  });
  await page.route("**/copilot/investigations?*", route => route.fulfill({ json: { investigations: [] } }));
  await page.route("**/copilot/desk/*/{picture,chart}*", route => {
    seen.charts.push(decodeURIComponent(new URL(route.request().url()).pathname.split("/").slice(-2)[0]));
    return route.fulfill({ status: 503, json: { detail: "No chart in this test." } });
  });
  await page.goto("/copilot-lab");
  await expect(page.getByTestId("desk-book")).toBeVisible();
  return seen;
}

const section = (page: Page) => page.getByTestId("desk-watching");
const rows = (page: Page) => section(page).getByTestId("watch-row").getByRole("button", { name: /, watching$/ });

test("the list: near names first, then today's biggest moves, eight shown; held and hidden names never in it", async ({ page }) => {
  const seen = await open(page);
  // Twelve watched: ORCL is held (the book's row only), IREN is held and not followed (nowhere): ten rows.
  await expect(section(page).getByRole("heading")).toHaveText("Watching · 10");
  await expect(rows(page)).toHaveText([/^IONQ/, /^NVDA/, /^RKLB/, /^SMCI/, /^TSLA/, /^PLTR/, /^META/, /^AMD/]);
  await expect(rows(page).filter({ hasText: "NVDA" }).getByTestId("watch-meta")).toHaveText("entry 101.00 · 1.0% away");
  await expect(section(page).getByTestId("watch-setup")).toHaveText(/^Setup 10:42/);
  await expect(section(page).getByRole("button", { name: /ORCL|IREN/ })).toHaveCount(0);
  await expect(page.getByTestId("desk-book").getByRole("button", { name: /^IREN / })).toHaveCount(0);
  await section(page).getByTestId("watching-more").click();
  await expect(rows(page)).toHaveCount(10);
  // The watched names ride the book's sparks read: one read with both lists, never a read of their own.
  const last = seen.sparks.at(-1)!;
  expect(last.searchParams.get("symbols")).toContain("ORCL");
  expect(last.searchParams.get("watch")!.split(",")).toEqual(expect.arrayContaining(["NVDA", "RKLB", "IONQ"]));
  expect(last.searchParams.get("watch")).not.toMatch(/ORCL|IREN/);
  // No amber in the section: nothing here asks for a trade.
  expect(await section(page).evaluate(node => node.innerHTML)).not.toMatch(/amber/);
});

test("selecting a watched row puts it on the chart and the copilot in place, as a position does", async ({ page }) => {
  const seen = await open(page);
  await page.evaluate(() => { (window as unknown as { kept: string }).kept = "still here"; });
  await rows(page).filter({ hasText: "RKLB" }).click();
  await expect(page).toHaveURL(/\/copilot-lab\?symbol=RKLB$/);
  await expect(rows(page).filter({ hasText: "RKLB" })).toHaveAttribute("aria-pressed", "true");
  await expect.poll(() => seen.charts).toContain("symbol:RKLB");
  await expect(page.getByRole("region", { name: "Conversation" }).getByTestId("desk-breadcrumb")).toContainText("RKLB");
  expect(await page.evaluate(() => (window as unknown as { kept?: string }).kept)).toBe("still here"); // no reload
});

test("Add watches a known ticker, refuses an unknown one, and Stop watching takes a name off", async ({ page }) => {
  const seen = await open(page);
  await section(page).getByRole("button", { name: "Add a ticker to watch" }).click();
  await section(page).getByRole("textbox", { name: "Ticker to watch" }).fill("zzqx");
  await section(page).getByRole("button", { name: "Watch", exact: true }).click();
  await expect(section(page).getByTestId("watching-said")).toHaveText("ZZQX is not a symbol the app knows.");
  await section(page).getByRole("textbox", { name: "Ticker to watch" }).fill("asts");
  await section(page).getByRole("button", { name: "Watch", exact: true }).click();
  await expect(section(page).getByRole("heading")).toHaveText("Watching · 11");
  expect(seen.added).toEqual(["ZZQX", "ASTS"]);
  await section(page).getByRole("button", { name: "RKLB: more" }).click();
  await expect(section(page).getByRole("menuitem")).toHaveText(["Ask the copilot", "Plan a trade", "Open in Charts", "Stop watching"]);
  await section(page).getByRole("menuitem", { name: "Stop watching" }).click();
  await expect(section(page).getByRole("heading")).toHaveText("Watching · 10");
  expect(seen.removed).toEqual(["RKLB"]);
  // The import, with the Robinhood connection off, says so; the list still works by hand.
  await section(page).getByRole("button", { name: "Import from Robinhood" }).click();
  await expect(section(page).getByTestId("watch-import")).toContainText("The Robinhood connection is off");
});

test("on a phone the section is one line with its count until tapped", async ({ page }) => {
  await open(page, { width: 393, height: 852 });
  const toggle = section(page).getByTestId("watching-toggle");
  await expect(toggle).toHaveText(/Watching · 10/);
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await expect(section(page).getByTestId("watching-body")).toBeHidden();
  await toggle.click();
  await expect(rows(page)).toHaveCount(8);
  await expect(section(page).getByRole("button", { name: "Add a ticker to watch" })).toBeVisible();
});
