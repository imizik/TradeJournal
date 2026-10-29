import { expect, test, type Page } from "@playwright/test";

// Linking a new fill to its plan on the desk (docs/copilot-lab.md § The desk, Link a fill where you are): the bar at the
// thread top, "N fills to link" opening each in turn, Link with Undo through the existing capture link routes, and No
// plan writing nothing. Every lab route and the link routes are stubbed in the browser; nothing here sends a turn.
const ON = {
  enabled: true, backend: "fake", evidence: "live", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
const NBIS_INV = "11111111-1111-4111-8111-111111111111";
const NBIS_TRADE = "55555555-5555-4555-8555-555555555555";
const CRWV_TRADE = "66666666-6666-4666-8666-666666666666";
const NBIS_PLAN = "aaaaaaaa-0000-4000-8000-000000000001";
const CRWV_PLAN = "aaaaaaaa-0000-4000-8000-000000000002";
const NOW = new Date("2026-10-23T15:00:00Z"); // 11:00 New York, a Friday
const epoch = (iso: string) => Date.parse(iso) / 1000;
const row = (fields: Record<string, unknown>) => ({
  symbol: null, instrument: null, value: null, meter: null, investigation_id: null, trade_id: null, radar_event_id: null, path: null,
  changed_at: null, fill_to_link: null, ...fields,
});
const BRIEFING = row({ key: "briefing", group: "pinned", title: "Briefing", status: { text: "What matters right now? One turn across everything", tone: "muted" } });
const NBIS_ROWS = [
  row({ key: `plan:${NBIS_INV}`, group: "near", symbol: "NBIS", title: "NBIS 95C long", instrument: "long", value: { text: "Fill to link", tone: "attention" },
    status: { text: "0.4% to entry 95.90", tone: "attention" }, investigation_id: NBIS_INV, fill_to_link: NBIS_TRADE }),
  row({ key: `trade:${NBIS_TRADE}`, group: "watch", symbol: "NBIS", title: "NBIS 10/23/26 95C", instrument: "10/23/26 95C",
    value: { text: "+$40.00", tone: "gain" }, status: { text: "Fill to link", tone: "attention" }, trade_id: NBIS_TRADE,
    path: "/copilot-lab?symbol=NBIS", fill_to_link: NBIS_TRADE }),
];
const CRWV_ROW = row({ key: `trade:${CRWV_TRADE}`, group: "act", symbol: "CRWV", title: "CRWV 10/23/26 100P", instrument: "10/23/26 100P",
  value: { text: "−$20.00", tone: "loss" }, status: { text: "Fill to link", tone: "attention" }, trade_id: CRWV_TRADE,
  path: "/copilot-lab?symbol=CRWV", fill_to_link: CRWV_TRADE });
const desk = (threads: unknown[]) => ({
  as_of: "2026-10-23T15:00:00Z", quotes_at: null, quote_issue: null, day: { phase: "regular", need_you: 0, streak: null },
  sections: { positions: "ok", plans: "ok", investigations: "ok", decisions: "ok", radar: "ok", thesis: "ok", prep: "ok", week: "ok", phase: "ok" },
  threads: [BRIEFING, ...(threads as { group: string }[]).sort((a, b) => Number(b.group === "act") - Number(a.group === "act"))],
});
const SESSION = {
  as_of: "2026-10-23T15:00:00Z", now: epoch("2026-10-23T15:00:00Z"), day: "2026-10-23", phase: "regular",
  open: epoch("2026-10-23T13:30:00Z"), close: epoch("2026-10-23T20:00:00Z"), events: [], time_stops: [], pings: { sent: 0, held: 0, cap: 12 },
  prep: null, indices: [], quote_issue: null,
  sections: { hours: "ok", phase: "ok", fills: "ok", pings: "ok", radar: "ok", decisions: "ok", time_stops: "ok", prep: "ok", indices: "ok" },
};
const candidate = (id: string, minute: number, investigation: string | null) => ({
  capture_id: id, setup: "Copilot plan", mode: "discretionary", wording: "Entry: crosses 95.9.", note: null,
  received_at: epoch(`2026-10-23T14:${minute}:00Z`), timing: "pre_entry", investigation_id: investigation,
});
const linkPage = (trade: string, contract: string, opened: string, candidates: unknown[]) => ({
  trade: { id: trade, ticker: contract.split(" ")[0], contract, status: "open", opened, fill: "1 at $2.10", opened_at: epoch("2026-10-23T14:31:00Z"),
    opened_at_reliable: true },
  candidates, linked: [], plan_path: "/copilot-lab?symbol=X",
});
const PAGES: Record<string, unknown> = {
  [NBIS_TRADE]: linkPage(NBIS_TRADE, "NBIS 10/23/26 95C", "opened", [candidate(NBIS_PLAN, 28, NBIS_INV)]),
  [CRWV_TRADE]: linkPage(CRWV_TRADE, "CRWV 10/23/26 100P", "opened", [candidate(CRWV_PLAN, 29, null)]),
};

async function lab(page: Page) {
  const linked: string[] = [], unlinked: string[] = [], chats: unknown[] = [];
  let threads = desk([...NBIS_ROWS, CRWV_ROW]);
  await page.clock.install({ time: NOW });
  await page.route("**/copilot/status", route => route.fulfill({ json: ON }));
  await page.route("**/copilot/desk/threads", route => route.fulfill({ json: threads }));
  await page.route("**/copilot/desk/session", route => route.fulfill({ json: SESSION }));
  await page.route("**/copilot/practice*", route => route.fulfill({ json: { goal: null, this_week: null } }));
  await page.route("**/copilot/investigations?*", route => route.fulfill({ json: { investigations: [] } }));
  await page.route(`**/copilot/investigations/${NBIS_INV}`, route => route.fulfill({ json: {
    id: NBIS_INV, source: "copilot", title: "NBIS 95C long", symbol: "NBIS", status: "open", conclusion: null, revision: 1, message_count: 2,
    has_findings: false, created_at: "2026-10-23T14:00:00Z", updated_at: "2026-10-23T14:05:00Z", evidence: [], findings: null,
    transcript: [{ role: "user", content: "Plan a trade: NBIS" }, { role: "assistant", content: "NBIS answer: enter at 95.90." }] } }));
  await page.route("**/copilot/chat", route => { chats.push(route.request().postDataJSON()); return route.abort(); });
  await page.route("**/charts/alerts", route => route.fulfill({ json: { alerts: [], phone: true } }));
  await page.route("**/copilot/time-stops?*", route => route.fulfill({ json: { time_stops: [], enabled: true } }));
  await page.route("**/copilot/research-jobs?*", route => route.fulfill({ json: { jobs: [], queue_enabled: false, daily_budget_usd: 2, spent_today_usd: 0 } }));
  await page.route("**/trades/*/plan-link", route => route.fulfill({ json: PAGES[route.request().url().split("/trades/")[1].split("/")[0]] }));
  await page.route("**/charts/captures/*/link", route => {
    const id = route.request().url().split("/captures/")[1].split("/")[0];
    const trade = JSON.parse(route.request().postData() ?? "{}").trade_id;
    linked.push(`${id} ${trade}`);
    if (trade === NBIS_TRADE) threads = desk([CRWV_ROW]); // linked: the list's next read has the NBIS fill planned
    return route.fulfill({ json: {} });
  });
  await page.route("**/charts/captures/*/unlink", route => {
    unlinked.push(route.request().url().split("/captures/")[1].split("/")[0]);
    threads = desk([...NBIS_ROWS, CRWV_ROW]);
    return route.fulfill({ json: {} });
  });
  await page.goto("/copilot-lab");
  await expect(page.getByRole("navigation", { name: "Thread list" }).getByTestId("desk-day")).toBeVisible();
  return { linked, unlinked, chats };
}

const conversation = (page: Page) => page.getByRole("region", { name: "Conversation" });
const bar = (page: Page) => conversation(page).getByRole("group", { name: "Fill to link" });

test("2 fills to link opens each in turn: Link calls the link route, No plan writes nothing", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const { linked, unlinked, chats } = await lab(page);
  const list = page.getByRole("navigation", { name: "Thread list" });
  // One fill per trade: NBIS's plan and its position are one fill to link.
  await expect(list.getByRole("button", { name: "2 fills to link" })).toBeVisible();
  await expect(conversation(page).getByRole("button", { name: "2 fills to link" })).toBeVisible(); // the Briefing counts them too

  // The first in list order opens by its symbol link (the desk remounts); No plan there opens the next.
  await list.getByRole("button", { name: "2 fills to link" }).click();
  await expect(page).toHaveURL(url => url.searchParams.get("symbol") === "CRWV");
  await expect(bar(page)).toContainText("Bought CRWV 10/23/26 100P 10:31");
  await bar(page).getByRole("button", { name: "No plan" }).click();
  expect(await page.evaluate(() => window.localStorage.getItem("desk.no-plan.v1"))).toBe(JSON.stringify([CRWV_TRADE]));

  await expect(conversation(page).getByText("NBIS answer: enter at 95.90.")).toBeVisible(); // the plan's thread, next in the list
  await expect(bar(page)).toContainText("Bought NBIS 10/23/26 95C 10:31");
  await expect(list.getByRole("button", { name: "1 fill to link" })).toBeVisible();
  await bar(page).getByRole("button", { name: "Link to plan “NBIS 95C long”" }).click(); // named by its desk thread
  await expect(bar(page).getByRole("status")).toHaveText("Linked to plan “NBIS 95C long”");
  await expect(bar(page).getByRole("button", { name: "Undo" })).toBeVisible();
  expect(linked).toEqual([`${NBIS_PLAN} ${NBIS_TRADE}`]);

  // The Undo window ends: the list reads again, nothing is left to link and the pass ends.
  await page.clock.fastForward(9_000);
  await expect(bar(page)).toBeHidden();
  await expect(list.getByRole("button", { name: /fills? to link/ })).toBeHidden();
  expect(await page.evaluate(() => window.sessionStorage.getItem("desk.linking.v1"))).toBeNull();

  // No plan sent nothing to the link routes; no turn ran.
  expect(linked).toEqual([`${NBIS_PLAN} ${NBIS_TRADE}`]);
  expect(unlinked).toEqual([]);
  expect(chats).toEqual([]);
});

test("Undo unlinks through the unlink route, and the bar fits a 375 px phone", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  const { linked, unlinked } = await lab(page);
  await page.goto("/copilot-lab?symbol=NBIS");
  await expect(bar(page)).toContainText("Bought NBIS 10/23/26 95C 10:31");
  const box = await bar(page).boundingBox();
  expect(box && box.x >= 0 && box.x + box.width <= 375).toBe(true);
  await bar(page).getByRole("button", { name: "Link to plan “NBIS 95C long”" }).click();
  await bar(page).getByRole("button", { name: "Undo" }).click();
  await expect(bar(page).getByRole("button", { name: "Link to plan “NBIS 95C long”" })).toBeVisible();
  expect(linked).toEqual([`${NBIS_PLAN} ${NBIS_TRADE}`]);
  expect(unlinked).toEqual([NBIS_PLAN]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
});
