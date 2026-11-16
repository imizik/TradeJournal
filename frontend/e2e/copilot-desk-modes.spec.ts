import { expect, test, type Page } from "@playwright/test";

// The desk's mode switch and status line (docs/copilot-lab.md § Real, paper and replay, § Data health): Real, Paper and
// Replay in the top bar, a view only; Paper frames the centre and shows the paper value beside the real; Replay, however
// it opened, shows on the switch, whose Real and Paper come back in one tap; Paper is kept across a reload, Replay never.
// The status line along the bottom names the mode, whose book, how fresh prices are and each source, a source behind in
// words; a phone has none. Every route is stubbed; every number and account is invented.
const ON = {
  enabled: true, backend: "fake", evidence: "live", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
// Friday November 13, 2026, 11:00 in New York: in the session.
const NOW = new Date("2026-11-13T16:00:00Z");
const epoch = (iso: string) => Date.parse(iso) / 1000;
const LIVE = { state: "ok", joined: true, as_of: "2026-11-13T15:59:00Z", issue: null, accounts: [
  { label: "Roth IRA", masked: "••8267", total_value: 9860.12, day_change: 140, day_change_pct: 1.44, options_value: 4200, cash: 1200.5, buying_power: 1150, open_pnl: 0 }] };
const THREADS = {
  as_of: "2026-11-13T16:00:00Z", quotes_at: null, quote_issue: null, day: { phase: "regular", need_you: 0, streak: null },
  sections: { positions: "ok" }, plans: [], robinhood: LIVE, threads: [],
};
const SESSION = {
  as_of: "2026-11-13T16:00:00Z", now: epoch("2026-11-13T16:00:00Z"), day: "2026-11-13", phase: "regular",
  open: epoch("2026-11-13T14:30:00Z"), close: epoch("2026-11-13T21:00:00Z"), events: [], time_stops: [], pings: null, prep: null,
  indices: [], quote_issue: null, realized_today: 0, sections: {},
};
const stats = { trades: 0, pnl: 0, win_rate: null, avg_win: null, avg_loss: null, largest_loss: null, curve: [] };
const PAPER = {
  run: { id: "11111111-1111-4111-8111-111111111111", number: 1, starting_cash: 10000, started_at: epoch("2026-11-02T14:30:00Z") },
  default_cash: 10000, account: { cash: 10234.5, collateral: 0, reserved: 0, buying_power: 10234.5, equity: 10234.5, pnl: 234.5, unpriced: 0, prices_at: null },
  positions: [], closed: [], orders: [], score: { paper: stats, real: stats }, my_rules: [], earlier: [], market_open: true,
};
type Row = { id: string; name: string; state: string; line: string; last_at: number | null; affects: string; fix: unknown };
// 10:58 New York: the time the rows were last good.
const row = (id: string, name: string, state: string, line: string): Row =>
  ({ id, name, state, line, last_at: epoch("2026-11-13T15:58:00Z"), affects: `${name} affects this.`, fix: null });
const SOURCES: Row[] = [
  row("robinhood", "Robinhood", "live", "Live · read 10:59"),
  row("prices", "Prices", "live", "Live"),
  row("chatter", "Chatter", "live", "Live · read 10:54"),
  row("radar", "Radar", "live", "Recording · pass 10:59"),
];
const health = (sources: Row[]) => ({ as_of: "2026-11-13T16:00:00Z", now: epoch("2026-11-13T16:00:00Z"), phase: "regular", overall: "ok", sources });

async function open(page: Page, { width = 1440, sources = SOURCES } = {}) {
  const reads: Record<string, unknown> = {
    "/copilot/desk/threads": THREADS,
    "/copilot/desk/session": SESSION,
    "/copilot/desk/watching": { state: "ok", symbols: [], count: 0, max: 30, imported_at: null, robinhood: "off", levels: {}, setups: {} },
    "/copilot/desk/sparks": { as_of: "2026-11-13T16:00:00Z", spy_change_pct: 0.4, rows: {} },
    "/copilot/desk/feed": { as_of: "2026-11-13T16:00:00Z", now: epoch("2026-11-13T16:00:00Z"), day: "2026-11-13", total: 0, sources: {}, unavailable: [], items: [] },
    "/copilot/investigations": { investigations: [] },
    "/copilot/tickets": { plans: [] },
    "/copilot/exposure": { line: null },
    "/copilot/paper": PAPER,
    "/copilot/desk/health": health(sources),
  };
  const sent: string[] = [];
  await page.setViewportSize({ width, height: 900 });
  await page.clock.install({ time: NOW });
  page.on("request", request => { if (request.method() !== "GET") sent.push(new URL(request.url()).pathname); });
  await page.route("**/api/backend/**", route => route.fulfill({ status: 404, json: { detail: "Not in this test." } }));
  await page.route("**/copilot/status", route => route.fulfill({ json: ON }));
  for (const [path, body] of Object.entries(reads)) await page.route(url => url.pathname.endsWith(path), route => route.fulfill({ json: body }));
  await page.route("**/copilot/desk/minute?*", route => {
    const answers = new URL(route.request().url()).searchParams.getAll("read").map(target => {
      const body = reads[target.split("?")[0]];
      return body ? { status: 200, body } : { status: 404, body: { detail: "Not in this test." } };
    });
    return route.fulfill({ json: { reads: answers } });
  });
  await page.goto("/copilot-lab");
  await expect(page.getByTestId("desk-book")).toBeVisible();
  return { sent };
}

const headSwitch = (page: Page) => page.locator("header [data-testid=\"mode-switch\"]");

test("the switch's three states: Real as it was, Paper framed with its value beside the real, Replay on its own screen", async ({ page }) => {
  const { sent } = await open(page);
  const modes = headSwitch(page);
  const status = page.getByTestId("desk-status-line");
  // Real: the desk as it always was, the status line naming the account by its label and masked number.
  await expect(modes).toHaveAttribute("data-mode", "real");
  await expect(modes.getByRole("radio", { name: "Real" })).toHaveAttribute("aria-checked", "true");
  await expect(page.locator("#desk-centre")).toHaveAttribute("data-mode", "real");
  await expect(page.getByTestId("desk-centre-paper")).toHaveCount(0);
  await expect(page.getByTestId("desk-paper-value")).toHaveCount(0);
  await expect(status.getByTestId("mode-mark")).toHaveAttribute("data-mode", "real");
  await expect(status.getByTestId("mode-mark")).toHaveText("Real · Roth IRA ••8267");

  // Paper: the dashed frame and its chip, the paper value beside the real accounts (each marked); the real book stays.
  await modes.getByRole("radio", { name: "Paper" }).click();
  await expect(modes).toHaveAttribute("data-mode", "paper");
  await expect(page.locator("#desk-centre")).toHaveAttribute("data-mode", "paper");
  await expect(page.locator("#desk-centre")).toHaveCSS("border-top-style", "dashed");
  await expect(page.getByTestId("desk-centre-paper")).toHaveText("Paper · fills shown");
  await expect(page.getByTestId("desk-paper-value")).toContainText("$10,234.50");
  await expect(page.getByTestId("desk-paper-value")).toContainText("+$234.50");
  await expect(page.getByTestId("desk-paper-value").getByTestId("mode-mark")).toHaveAttribute("data-mode", "paper");
  await expect(page.getByTestId("desk-accounts")).toBeVisible();
  await expect(page.locator("header").getByTestId("mode-mark").first()).toHaveAttribute("data-mode", "real");
  await expect(page.getByTestId("desk-book")).toBeVisible();
  await expect(status.getByTestId("mode-mark")).toHaveText("Paper · real book unchanged");

  // Replay: its own screen, the switch in its header showing Replay; the status line says neither book changes.
  await modes.getByRole("radio", { name: "Replay" }).click();
  await expect(page.getByTestId("desk-replay")).toBeVisible();
  const replaySwitch = page.getByTestId("desk-replay").getByTestId("mode-switch");
  await expect(replaySwitch.getByRole("radio", { name: "Replay" })).toHaveAttribute("aria-checked", "true");
  await expect(status.getByTestId("mode-mark")).toHaveText("Replay · real and paper books unchanged");
  // One tap back to Real.
  await replaySwitch.getByRole("radio", { name: "Real" }).click();
  await expect(page.getByTestId("desk-replay")).toHaveCount(0);
  await expect(headSwitch(page)).toHaveAttribute("data-mode", "real");
  await expect(page.locator("#desk-centre")).toHaveAttribute("data-mode", "real");
  // A view only: nothing was sent (the desk's own opening of today's Main chat aside).
  expect(sent.filter(path => !path.endsWith("/copilot/main-chat"))).toEqual([]);
});

test("Replay opened by R shows on the switch; its Paper returns in one tap", async ({ page }) => {
  await open(page);
  await page.keyboard.press("r");
  await expect(page.getByTestId("desk-replay")).toBeVisible();
  const replaySwitch = page.getByTestId("desk-replay").getByTestId("mode-switch");
  await expect(replaySwitch).toHaveAttribute("data-mode", "replay");
  await replaySwitch.getByRole("radio", { name: "Paper" }).click();
  await expect(page.getByTestId("desk-replay")).toHaveCount(0);
  await expect(headSwitch(page)).toHaveAttribute("data-mode", "paper");
  await expect(page.getByTestId("desk-centre-paper")).toBeVisible();
});

test("Paper is kept across a reload; Replay never is", async ({ page }) => {
  await open(page);
  await headSwitch(page).getByRole("radio", { name: "Paper" }).click();
  await expect(headSwitch(page)).toHaveAttribute("data-mode", "paper");
  await page.reload();
  await expect(page.getByTestId("desk-book")).toBeVisible();
  await expect(headSwitch(page)).toHaveAttribute("data-mode", "paper");
  await expect(page.locator("#desk-centre")).toHaveAttribute("data-mode", "paper");
  // Replay open at a reload: the desk comes back in Paper, not Replay.
  await page.keyboard.press("r");
  await expect(page.getByTestId("desk-replay")).toBeVisible();
  await page.reload();
  await expect(page.getByTestId("desk-book")).toBeVisible();
  await expect(page.getByTestId("desk-replay")).toHaveCount(0);
  await expect(headSwitch(page)).toHaveAttribute("data-mode", "paper");
});

test("the status line names a source behind in words, red where it moves positions; a tap opens the Data health list", async ({ page }) => {
  await open(page, { sources: SOURCES.map(r => r.id === "robinhood" ? row("robinhood", "Robinhood", "stale", "Last read 10:58")
    : r.id === "chatter" ? row("chatter", "Chatter", "stale", "Last read 10:58") : r) });
  const status = page.getByTestId("desk-status-line");
  await expect(status).toBeVisible();
  await expect(status.getByTestId("status-robinhood")).toHaveText("Robinhood behind since 10:58");
  await expect(status.getByTestId("status-robinhood")).toHaveAttribute("data-tone", "red");
  await expect(status.getByTestId("status-chatter")).toHaveText("Chatter behind since 10:58");
  await expect(status.getByTestId("status-chatter")).toHaveAttribute("data-tone", "amber");
  await expect(status.getByTestId("status-radar")).toContainText("Radar");
  // The top bar's dot stays, from the same one read.
  await expect(page.getByTestId("desk-health")).toHaveAccessibleName("Data health: 2 sources behind");
  // Its own row under the cockpit: nothing of the desk sits behind it.
  const line = await status.boundingBox();
  const cockpit = await page.locator("#desk-cockpit").boundingBox();
  expect(line!.y).toBeGreaterThanOrEqual(cockpit!.y + cockpit!.height - 1);
  await status.click();
  const list = page.getByTestId("desk-health-list");
  await expect(list).toBeInViewport({ ratio: 1 });
  await expect(list.getByTestId("health-robinhood")).toContainText("Last read 10:58");
});

test("a phone: no status line; the switch sits at the top of Positions", async ({ page }) => {
  await open(page, { width: 375 });
  await expect(page.getByTestId("desk-status-line")).toHaveCount(0);
  await expect(page.getByTestId("desk-health")).toBeVisible(); // the dot stays its health view
  const modes = page.getByTestId("mode-switch").filter({ visible: true });
  await expect(modes).toHaveCount(1);
  await expect(modes).toBeInViewport();
  await modes.getByRole("radio", { name: "Paper" }).click();
  await expect(modes).toHaveAttribute("data-mode", "paper");
  await expect(page.getByTestId("desk-paper-value").filter({ visible: true })).toContainText("$10,234.50");
  // Nothing in the top row overflows the screen.
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(0);
});
