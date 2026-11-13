import { expect, test, type Page } from "@playwright/test";

// The desk read (docs/copilot-lab.md § The desk read): selecting a ticker with no conversation open shows a few lines on it
// in the copilot after a 1.5 s wait, kept per ticker (a reselect shows it with its age and asks nothing), Refresh and Ask
// more, nothing for a ticker he does not follow, one grey line when the day's budget is spent, and Auto-read off asking
// nothing at all. Every lab route is stubbed in the browser; nothing reaches a model.
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

const READ = (symbol: string, refresh = false) => `Verdict: Hold — ${symbol} ${refresh ? "still holds" : "holds"} above your 24.10 entry.\n- Last 25.40, 5.4% over your entry, as of 10:58.\n- Space names up 3.1% on a launch-contract headline at 9:40.\nChanges if: a close back under 24.10.`;

type Reads = { asked: { symbol: string; refresh: boolean }[]; hidden: Set<string> };

async function open(page: Page, { width = 1440, height = 900 } = {}) {
  const reads: Reads = { asked: [], hidden: new Set(["HOOD"]) };
  await page.setViewportSize({ width, height });
  await page.clock.install({ time: NOW });
  await page.route("**/copilot/status", route => route.fulfill({ json: ON }));
  await page.route("**/copilot/desk/threads", route => route.fulfill({ json: THREADS }));
  await page.route("**/copilot/desk/session", route => route.fulfill({ json: SESSION }));
  await page.route("**/copilot/desk/pings*", route => route.fulfill({ json: { day: "2026-11-13", since: "2026-11-12", alerts: { state: "ok", rows: [] }, radar: { state: "off", reason: null, rows: [] } } }));
  await page.route("**/copilot/desk/feed", route => route.fulfill({ json: { as_of: "2026-11-13T16:00:00Z", now: epoch("2026-11-13T16:00:00Z"), day: "2026-11-13", total: 0, sources: {}, unavailable: [], items: [] } }));
  await page.route("**/copilot/desk/sparks?*", route => route.fulfill({ json: SPARKS((new URL(route.request().url()).searchParams.get("watch") ?? "").split(",")) }));
  await page.route("**/copilot/desk/watching", route => route.fulfill({ json: watching(NAMES) }));
  await page.route("**/copilot/investigations?*", route => route.fulfill({ json: { investigations: [] } }));
  await page.route("**/copilot/desk/*/{picture,chart}*", route => route.fulfill({ status: 503, json: { detail: "No chart in this test." } }));
  await page.route("**/copilot/desk/read", route => {
    const { symbol, refresh } = route.request().postDataJSON() as { symbol: string; refresh: boolean };
    reads.asked.push({ symbol, refresh });
    const today = { count: reads.asked.length, refused: 0, cost_usd: 0.05 * reads.asked.length };
    if (reads.hidden.has(symbol)) return route.fulfill({ json: { state: "hidden" } });
    if (symbol === "TSLA") return route.fulfill({ json: { state: "budget", message: "No automatic read: today's copilot budget ($4.00) is spent.", today } });
    const at = epoch("2026-11-13T16:00:00Z");
    return route.fulfill({ json: { state: "ok", text: READ(symbol, refresh), at, expires_at: at + 1800, age_s: 0, cached: false, cost_usd: 0.05, today } });
  });
  await page.goto("/copilot-lab");
  await expect(page.getByTestId("desk-book")).toBeVisible();
  await expect(page.getByTestId("desk-watching")).toBeVisible();
  await page.getByTestId("desk-watching").getByTestId("watching-more").click(); // every watched name, HOOD and TSLA too
  return reads;
}

const watchRow = (page: Page, symbol: string) => page.getByTestId("desk-watching").getByTestId("watch-row")
  .getByRole("button", { name: new RegExp(`^${symbol}.*, watching$`) });
const read = (page: Page) => page.getByTestId("desk-read");

test("clicking through names asks for the one he stops on, after the wait; a reselect shows the kept read and asks nothing", async ({ page }) => {
  const reads = await open(page);
  await page.clock.pauseAt(new Date("2026-11-13T16:00:05Z"));
  await watchRow(page, "RKLB").click();
  await page.clock.runFor(800);
  await watchRow(page, "NVDA").click();
  await page.clock.runFor(800);
  await watchRow(page, "PLTR").click();
  await page.clock.runFor(800);
  expect(reads.asked).toEqual([]); // nothing yet: each click restarted the wait
  await page.clock.runFor(800);
  await expect(read(page).getByTestId("desk-read-text")).toContainText("PLTR holds above your 24.10 entry");
  expect(reads.asked).toEqual([{ symbol: "PLTR", refresh: false }]);
  await expect(read(page).getByTestId("copilot-verdict")).toHaveText("Hold");
  await expect(read(page).getByTestId("desk-read-age")).toHaveText(/^Read at 11:00 AM · just now$/);
  await expect(read(page).getByTestId("desk-read-switch")).toHaveText(/Auto-read on · 1 today · \$0\.05/);
  // Another name, then back: the kept read at once, with its age; after the wait the server only confirms it (kept there
  // too, so no model call there either).
  await watchRow(page, "SMCI").click();
  await page.clock.runFor(1600);
  await expect(read(page).getByTestId("desk-read-text")).toContainText("SMCI");
  await page.clock.runFor(4 * 60_000);
  await watchRow(page, "PLTR").click();
  await expect(read(page).getByTestId("desk-read-text")).toContainText("PLTR");
  await expect(read(page).getByTestId("desk-read-age")).toHaveText(/4 min ago$/);
  await page.clock.runFor(1000);
  expect(reads.asked.map(r => r.symbol)).toEqual(["PLTR", "SMCI"]);
  await page.clock.runFor(600);
  await expect.poll(() => reads.asked.length).toBe(3);
  expect(reads.asked.at(-1)).toEqual({ symbol: "PLTR", refresh: false });
  // Refresh reads again at once.
  await read(page).getByTestId("desk-read-refresh").click();
  await expect.poll(() => reads.asked.at(-1)).toEqual({ symbol: "PLTR", refresh: true });
  await expect(read(page).getByTestId("desk-read-text")).toContainText("PLTR still holds"); // the refreshed read has landed
  // Once the kept read expires while he is still on it, it is read again (not forced: the server's expires with it).
  for (let minutes = 5; minutes < 30; minutes += 5) {
    await page.clock.runFor(5 * 60_000);
    expect(reads.asked.length).toBe(4); // nothing until it expires
  }
  await page.clock.runFor(5 * 60_000 + 2000);
  await expect.poll(() => reads.asked.length).toBe(5);
  expect(reads.asked.at(-1)).toEqual({ symbol: "PLTR", refresh: false });
});

test("Ask more carries the read into the message box as context", async ({ page }) => {
  await open(page);
  await watchRow(page, "RKLB").click();
  await read(page).getByTestId("desk-read-ask").click();
  const box = page.getByRole("textbox", { name: "Message" });
  await expect(box).toBeFocused();
  await expect(box).toHaveValue(/^Context: the desk's read of RKLB at 11:00 AM ET:\nVerdict: Hold — RKLB holds above your 24.10 entry\.[\s\S]*Changes if: a close back under 24\.10\.\n\n$/);
});

test("a ticker he does not follow shows nothing; a spent budget is one grey line and no read", async ({ page }) => {
  const reads = await open(page);
  await watchRow(page, "HOOD").click();
  await expect.poll(() => reads.asked.length).toBe(1);
  await expect(read(page)).toHaveCount(0);
  await watchRow(page, "TSLA").click();
  await expect(read(page).getByTestId("desk-read-none")).toHaveText("No automatic read: today's copilot budget ($4.00) is spent.");
  await expect(read(page).getByTestId("desk-read-text")).toHaveCount(0);
  await expect(read(page).getByRole("button", { name: "Try again" })).toHaveCount(0);
});

test("a read kept in the browser goes once he stops following the ticker", async ({ page }) => {
  const reads = await open(page);
  await watchRow(page, "PLTR").click();
  await expect(read(page).getByTestId("desk-read-text")).toContainText("PLTR");
  await watchRow(page, "NVDA").click();
  await expect(read(page).getByTestId("desk-read-text")).toContainText("NVDA");
  reads.hidden.add("PLTR"); // set to Not following elsewhere
  await watchRow(page, "PLTR").click();
  await expect(read(page)).toHaveCount(0); // the server's confirmation says hidden: the kept read is gone
  await watchRow(page, "NVDA").click();
  await watchRow(page, "PLTR").click();
  await expect(read(page).getByTestId("desk-read-text")).toHaveCount(0); // never shown again from the browser's memory
  await expect(read(page)).toHaveCount(0);
});

test("Auto-read off asks for nothing, says so in one line, and stays off after a reload", async ({ page }) => {
  const reads = await open(page);
  await watchRow(page, "RKLB").click();
  await expect(read(page).getByTestId("desk-read-text")).toBeVisible();
  await read(page).getByRole("button", { name: "Turn off" }).click();
  await expect(read(page)).toHaveText(/^Auto-read is offTurn on$/);
  await watchRow(page, "NVDA").click();
  await page.waitForTimeout(2000);
  expect(reads.asked.map(r => r.symbol)).toEqual(["RKLB"]);
  await page.reload();
  await watchRow(page, "PLTR").click();
  await expect(read(page)).toHaveText(/^Auto-read is off/);
  await page.waitForTimeout(2000);
  expect(reads.asked.map(r => r.symbol)).toEqual(["RKLB"]);
  await read(page).getByRole("button", { name: "Turn on" }).click();
  await expect(read(page).getByTestId("desk-read-text")).toContainText("PLTR");
});
