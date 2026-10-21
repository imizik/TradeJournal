import { expect, test, type Page } from "@playwright/test";
import type { PlanRefusal, PlansView, PlanView } from "../lib/conditionalPlans";
import type { MorningView } from "../lib/joMorning";
import type { MarketReadSlot, MarketReadsView, MarketReadText } from "../lib/marketReads";

// Jo's day on the Daily Review joins four existing records; each is stubbed here so the
// timeline can be judged with realistic content. Trades and thoughts come from the seeded backend.
const today = new Date().toLocaleDateString("en-CA", { timeZone: "America/New_York" });
const iso = (day: string, et: string) => new Date(`${day}T${et}:00-04:00`).toISOString();

const text = (main: string, extra: Partial<MarketReadText> = {}): MarketReadText => ({ view: "mixed", main_text: main,
  alternative_text: "This could stay a choppy range under the opening high.", invalidation_text: "Weakens if SPY loses 769.73 again.",
  change_summary: "First read of the day.", is_correction: false, ...extra });

function slot(day: string, name: string, extra: Partial<MarketReadSlot> = {}): MarketReadSlot {
  return { slot: name, scheduled_at: iso(day, name), expected: true, not_expected_reason: null, operation_id: `mw-scheduled-v1:${day}:${name}`,
    packet: { slot: name, status: "not_due", attempts: 0, recorded_at: null, snapshot_id: null, error_code: null, quality_flags: [] },
    status: "upcoming", read_id: null, attribution: null, received_at: null, read: null, receipt_delay_seconds: null,
    read_used_slot_packet: null, deadline: iso(day, name), delivery: "pending", late_by_seconds: null, ...extra };
}

// The server's clock for each stub (an ET time on the stubbed day), so no test depends on when the suite runs.
type Mode = { live: boolean; now: string; watchOff?: boolean };

function reads(day: string, { live, now, watchOff }: Mode): MarketReadsView {
  const first = slot(day, "09:50", { status: "read_seen", read_id: "mwr_1", received_at: iso(day, "09:50"), delivery: "on_time",
    packet: { slot: "09-49", status: "published_partial", attempts: 1, recorded_at: null, snapshot_id: "mws_a", error_code: null, quality_flags: ["gap:headlines"] },
    read: text("SPY is holding its opening range; no clean break yet.") });
  const rest = live ? ["11:00", "12:30", "14:00"].map((name) => slot(day, name)) : [
    slot(day, "11:00", { status: "no_read_seen", delivery: "missing" }), slot(day, "12:30", { status: "no_read_seen", delivery: "missing" }),
    slot(day, "14:00", { status: "read_seen", read_id: "mwr_3", received_at: iso(day, "14:22"), delivery: "late", late_by_seconds: 420,
      read: text("Afternoon chop; MU holding above 140.") })];
  return { checked_at: iso(day, now), market_watch_enabled: !watchOff, reads_available: true, receipts_available: true,
    attribution_window_minutes: 30, deadline_minutes: 15, reads_through: iso(day, now), limits: [],
    importer: { running: true, outbox_configured: true, last_ingest: iso(day, now), current: true },
    sessions: [{ session_date: day, hours: { status: "open", open: 570, close: 960 }, slots: [first, ...rest],
      reads_not_credited_to_a_slot: [{ read_id: "mwr_2", received_at: iso(day, "10:45"), event_wake_id: null,
        read: text("Correction: SPY recovered above VWAP, so the bearish note no longer holds.", { is_correction: true }) }],
      summary: { read_seen: live ? 1 : 2, no_read_seen: live ? 0 : 2, upcoming: live ? 3 : 0, not_expected: 0, unknown: 0 },
      delivery_summary: { on_time: 1, late: live ? 0 : 1, missing: live ? 0 : 2, pending: live ? 3 : 0, not_expected: 0, unknown: 0 },
      watchdog: { state: "on", checked_at: null, notices: [] } }] };
}

function morning(day: string, { now }: Mode): MorningView {
  return { day, state: "ready", late: false, stale: false, archived: false, deadline: iso(day, "09:15"), checked_at: iso(day, now),
    automation: { enabled: true, last_pass: null, unavailable: false },
    delivery: { calendar: "open", publication: "published", fulfilment: "on_time", deadline: iso(day, "09:15"), publish_at: iso(day, "08:45"),
      packet_id: "p1", published_at: iso(day, "08:45"), briefing_id: "b1", available_at: iso(day, "08:56"), submitted_at: iso(day, "08:56"),
      import_lag_seconds: 9, late_by_seconds: 0, origin: "unknown", other_briefings: 0, notifications: { chatgpt: "not_observable", watchdog: null } },
    packet: null, versions: [], feedback: { rating: null, first_opened_at: null },
    briefing: { id: "b1", received_at: iso(day, "08:56"), redacted_at: null, body: { summary: "Two expiries need decisions before new risk.",
      items: [{ symbol: "APLD", what_matters: "Review the six $24 calls expiring Friday.", why_personal: "", what_changed: "", contrary_evidence: "", watch_out: "", evidence_ids: [] },
        { symbol: "NBIS", what_matters: "Verify price before acting on the compute-shortage headline.", why_personal: "", what_changed: "", contrary_evidence: "", watch_out: "", evidence_ids: [] }] } } };
}

function plans(day: string, { live, now }: Mode): PlansView {
  const watch: PlanView = { plan_id: "plan_1", actor: "check_1", session_date: day, symbol: "MU", direction: "long", trigger_price: 140, invalidation_price: 137.5,
    confirm_bars: 2, rationale: "Owner asked to track a breakout over 140.", source: { kind: "check", id: "c", sha256: "s", observed_at: iso(day, "10:20"), price: 139.2 },
    expires_at: iso(day, "14:20"), created_at: iso(day, "10:21"), accepted_by_monitor: true, cancel_requested: false,
    state: live ? "triggered" : "expired", reason: null, state_at: null, monitoring: live, heartbeat_at: null, last_bar: null, last_evaluated_at: null,
    events: [{ state: "triggered", reason: "confirmed_closes", occurred_at: iso(day, "10:54"),
      bar: { time: 0, end_time: 0, open: 140.6, high: 140.7, low: 140.5, close: 140.6 } },
      ...(live ? [] : [{ state: "expired" as const, reason: "monitoring_window_ended", occurred_at: iso(day, "14:20"), bar: null }])],
    deliveries: [{ event_state: "triggered", attempt: 1, result: "accepted", outcome: "sent", error_code: null, transport_receipt_id: null, occurred_at: iso(day, "10:54") }] };
  return { checked_at: iso(day, now), enabled: true, app_flag: true, stock_watch: true, configured: true,
    readiness: { heartbeat: "fresh" }, max_daily_plans: 24, plans_today: 1, limit: 50, delivery: { channel: "ntfy", configured: true }, plans: [watch] };
}

async function stub(page: Page, day: string, mode: Mode) {
  await page.route("**/jo/morning?**", (route) => route.fulfill({ json: morning(day, mode) }));
  await page.route("**/jo/market-reads?**", (route) => route.fulfill({ json: reads(day, mode) }));
  await page.route("**/jo/conditional-plans", (route) => route.fulfill({ json: plans(day, mode) }));
}
const midday = { live: true, now: "11:05" };

test("today's Daily Review shows what Jo did, is watching and will do, with Jo's own read text", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.setViewportSize({ width: 1440, height: 1000 });
  await stub(page, today, midday);
  await page.goto(`/daily/${today}`);
  const jo = page.getByTestId("jo-day");
  await expect(page.getByTestId("jo-day-headline")).toHaveText(/^Briefing on time · 1 of 4 market reads in · 1 extra read · MU triggered 10:54 AM · next: 11:00 market read$/);
  await expect(page.getByTestId("jo-day-headline")).toHaveAttribute("data-trouble", "false");
  await expect(jo.getByText("Morning data sent to Jo")).toBeVisible();
  await expect(jo.getByText("Morning briefing: APLD, NBIS")).toBeVisible();
  const first = jo.getByTestId("jo-day-item").filter({ hasText: "9:50 read · mixed" });
  await expect(first).toContainText("On time · data had gaps");
  await expect(first).toContainText("SPY is holding its opening range"); // first sentence, before opening
  await first.locator("summary").click();
  await expect(first).toContainText("SPY is holding its opening range");
  await expect(first).toContainText("Wrong if:");
  await expect(jo.getByText("Extra read · mixed · correction")).toBeVisible();
  // The trigger is its own row with price and alert, and the live watch says what it still checks.
  const fired = jo.getByTestId("jo-day-item").filter({ hasText: "MU watch triggered · close 140.6" });
  await expect(fired).toContainText("Phone alert sent");
  await expect(fired).toContainText("Alert only: no order was placed.");
  await expect(jo.getByText("MU triggered 10:54 AM: still checking for a close below 137.5")).toBeVisible();
  await expect(jo.getByRole("heading", { name: "Coming up" })).toBeVisible();
  await expect(jo.getByTestId("jo-day-item").filter({ hasText: "Upcoming" })).toHaveCount(3);
  await jo.screenshot({ path: test.info().outputPath("jo-day-today-desktop.png") });

  // The jump bar stays reachable and moves to each section.
  await expect(page.getByRole("navigation", { name: "Sections of this day" }).getByRole("link", { name: "AI analysis" })).toBeVisible();
  await page.getByRole("navigation", { name: "Sections of this day" }).getByRole("link", { name: /^Trades/ }).click();
  await expect(page).toHaveURL(/#trades$/);
  await expect(page.getByRole("navigation", { name: "Sections of this day" })).toBeInViewport();

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/daily/${today}`);
  await expect(page.getByTestId("jo-day-headline")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  await page.screenshot({ path: test.info().outputPath("jo-day-today-phone.png") });
  expect(errors).toEqual([]);
});

test("a past day is a record: problems are named, lateness counts from the slot, nothing is upcoming", async ({ page }) => {
  const past = "2026-10-01";
  await page.setViewportSize({ width: 1440, height: 1000 });
  await stub(page, past, { live: false, now: "16:05" });
  await page.goto(`/daily/${past}`);
  const jo = page.getByTestId("jo-day");
  const headline = page.getByTestId("jo-day-headline");
  await expect(headline).toHaveText(/^Briefing on time · 2 of 4 market reads in · 2 missing · 1 late · 1 extra read · MU triggered 10:54 AM/);
  await expect(headline).toHaveAttribute("data-trouble", "true");
  // Only the problems are coloured, not the whole sentence.
  await expect(headline.getByText("2 missing", { exact: true })).toHaveClass(/text-amber-200/);
  await expect(headline.getByText("Briefing on time", { exact: true })).not.toHaveClass(/text-amber-200/);
  await expect(jo.getByTestId("jo-day-item").filter({ hasText: "Missing" })).toHaveCount(2);
  await expect(jo.getByTestId("jo-day-item").filter({ hasText: "2:00 read · mixed" })).toContainText("Late · 22 min after 2:00");
  await expect(jo.getByRole("heading", { name: "Coming up" })).toHaveCount(0);
  // The trigger stays in the record after the watch ends.
  await expect(jo.getByText("MU watch triggered · close 140.6")).toBeVisible();
  await expect(jo.getByText("MU watch ended at its expiry")).toBeVisible();
});

test("after today's close the page is a record: no live lists, and the headline says the market closed", async ({ page }) => {
  await stub(page, today, { live: false, now: "16:05" });
  await page.goto(`/daily/${today}`);
  const jo = page.getByTestId("jo-day");
  await expect(page.getByTestId("jo-day-headline")).toHaveText(/ · market closed$/);
  await expect(jo.getByText("The market has closed; nothing is being watched and nothing else is scheduled today.")).toBeVisible();
  await expect(jo.getByRole("heading", { name: "Watching now" })).toHaveCount(0);
  await expect(jo.getByRole("heading", { name: "Coming up" })).toHaveCount(0);
});

test("with market watch off, saved reads still show with a plain note", async ({ page }) => {
  await stub(page, today, { ...midday, watchOff: true });
  await page.goto(`/daily/${today}`);
  await expect(page.getByTestId("jo-day-reads-note")).toHaveText("Market watch is off on this server, so no new reads will arrive; saved reads are shown.");
  await expect(page.getByTestId("jo-day-item").filter({ hasText: "9:50 read · mixed" })).toBeVisible();
});

test("a watch Jo asked for but the app refused is a Done row, with what Jo asked for and why", async ({ page }) => {
  const refusal: PlanRefusal = { refusal_id: "cpr_1", actor: "check_1", session_date: today, symbol: "TSLA", source_kind: "stock_alert", direction: "long",
    trigger_price: 252, invalidation_price: 245, confirm_bars: 2, expires_at: iso(today, "12:20"),
    reason: "TSLA is not one of the owner's selected scanner tickers (MU, SPY)", reason_code: "ticker_not_selected", created_at: iso(today, "10:20") };
  await stub(page, today, midday);
  await page.route("**/jo/conditional-plans", (route) => route.fulfill({ json: { ...plans(today, midday), refusals: [refusal] } }));
  await page.goto(`/daily/${today}`);
  const headline = page.getByTestId("jo-day-headline");
  await expect(headline.getByText("1 watch refused", { exact: true })).toHaveClass(/text-amber-200/);
  const row = page.getByTestId("jo-day-item").filter({ hasText: "Jo couldn't watch TSLA: not one of your scanner tickers" });
  await expect(row).toContainText("10:20");
  await expect(row).toContainText("Not saved");
  await row.locator("summary").click();
  await expect(row).toContainText("Jo asked for: TSLA long · 2 closes above 252, cancel on a close below 245 · until 12:20 PM");
  await expect(row).toContainText("Refused: TSLA is not one of the owner's selected scanner tickers (MU, SPY). Nothing was saved or watched.");
  // It is not counted or shown as a watch.
  await expect(page.getByTestId("jo-day-item").filter({ hasText: "TSLA long watch" })).toHaveCount(0);

  await page.goto("/morning/watches");
  const listed = page.getByTestId("plan-refusal");
  await expect(listed).toHaveCount(1);
  await expect(listed).toContainText("TSLA · Long watch");
  await expect(listed).toContainText("Refused · not saved");
  await expect(listed).toContainText("Jo couldn't watch this: not one of your scanner tickers.");
  await expect(page.getByRole("heading", { name: "Refused requests (1)" })).toBeVisible();
});

test("a past day with no Jo records says so in one line instead of an empty timeline", async ({ page }) => {
  const day = "2026-10-02";
  await page.route("**/jo/morning?**", (route) => route.fulfill({ json: { ...morning(day, { live: false, now: "16:05" }), briefing: null,
    delivery: { ...morning(day, { live: false, now: "16:05" }).delivery!, publication: "not_expected", fulfilment: "not_expected", published_at: null, available_at: null } } }));
  await page.route("**/jo/market-reads?**", (route) => route.fulfill({ json: { ...reads(day, { live: false, now: "16:05" }), sessions: [] } }));
  await page.route("**/jo/conditional-plans", (route) => route.fulfill({ json: { ...plans(day, { live: false, now: "16:05" }), plans: [] } }));
  await page.goto(`/daily/${day}`);
  await expect(page.getByTestId("jo-day-headline")).toHaveText("No Jo record for this day");
  await expect(page.getByTestId("jo-day").getByRole("heading", { name: "Done" })).toHaveCount(0);
  // A past day is labelled as that day, not as the most recent one.
  await expect(page.getByText("Trading day: ")).toBeVisible();
});

test("one failed record is named and the rest still show", async ({ page }) => {
  await stub(page, today, midday);
  await page.route("**/jo/conditional-plans", (route) => route.fulfill({ status: 503, json: { detail: "down" } }));
  await page.goto(`/daily/${today}`);
  await expect(page.getByTestId("jo-day").getByRole("alert")).toHaveText("Couldn't load price watches. What's shown may be incomplete.");
  await expect(page.getByText("Morning briefing: APLD, NBIS")).toBeVisible();
});

test("the dashboard links to today's Jo timeline", async ({ page }) => {
  await stub(page, today, midday);
  await page.goto("/");
  const line = page.getByTestId("jo-today-line");
  await expect(line).toContainText("Briefing on time · 1 of 4 market reads in");
  await line.click();
  await expect(page).toHaveURL(new RegExp(`/daily/${today}#jo$`));
});

test("phone alerts list every recorded push with its time, subject and outcome, and never claims the phone showed it", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const mode = { live: false, now: "16:05" };
  const view = reads(today, mode);
  const session = view.sessions[0];
  session.messages = [
    { message_id: "mwm_1", read_id: "mwr_1", is_correction: false, decision: "send", reason: null, attempts: 1, delivery: "accepted",
      decided_at: iso(today, "09:51"), settled_at: iso(today, "09:51") },
    { message_id: "mwm_2", read_id: "mwr_2", is_correction: true, decision: "send", reason: null, attempts: 2, delivery: "unknown",
      decided_at: iso(today, "10:45"), settled_at: iso(today, "10:46") },
    { message_id: "mwm_3", read_id: "mwr_3", is_correction: false, decision: "suppressed_budget", reason: "2 used", attempts: 0, delivery: "not_sent",
      decided_at: iso(today, "14:22"), settled_at: null }];
  session.watchdog = { state: "on", checked_at: null, notices: [{ kind: "1100", title: "Jo's 11:00 AM market read is missing", recovered: false, outcome: "failed", at: iso(today, "11:16") }] };
  const brief = morning(today, mode);
  brief.delivery!.notifications.watchdog = { state: "on", checked_at: null, notices: [] };
  await page.route("**/jo/morning?**", (route) => route.fulfill({ json: brief }));
  await page.route("**/jo/market-reads?**", (route) => route.fulfill({ json: view }));
  await page.route("**/jo/conditional-plans", (route) => route.fulfill({ json: plans(today, mode) }));
  await page.goto(`/daily/${today}`);
  const alerts = page.getByTestId("jo-phone-alerts");
  await expect(alerts.getByRole("heading", { name: "Phone alerts today" })).toBeVisible();
  await expect(alerts.getByTestId("jo-phone-alert")).toHaveText([
    /9:51 AM.*Jo's message: 9:50 read · mixed.*Sent to ntfy/,
    /10:46 AM.*Jo's correction: Extra read \(10:45 AM\) · mixed · correction.*May have sent/,
    /10:54 AM.*MU price watch triggered.*Sent to ntfy/,
    /11:16 AM.*Watchdog: Jo's 11:00 AM market read is missing.*Failed to send/,
    /2:22 PM.*Jo's message: 2:00 read · mixed.*Held back: daily message limit/,
  ]);
  await expect(alerts).toContainText("“Sent to ntfy” means the push service accepted it; the app can't see whether your phone showed it.");
  await expect(alerts).not.toContainText("Couldn't read");

  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto(`/daily/${today}`);
  await expect(page.getByTestId("jo-phone-alert")).toHaveCount(5);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  await page.getByTestId("jo-phone-alerts").screenshot({ path: test.info().outputPath("jo-phone-alerts-phone.png") });
  expect(errors).toEqual([]);
});

test("a phone-alert source that couldn't be read is named, not shown as quiet", async ({ page }) => {
  await stub(page, today, midday);
  await page.route("**/jo/conditional-plans", (route) => route.fulfill({ status: 503, json: { detail: "down" } }));
  await page.goto(`/daily/${today}`);
  // This stub is an older server: no read-message history and no watchdog record, so those are unknown too.
  await expect(page.getByTestId("jo-phone-alerts")).toContainText(
    "Couldn't read the record of price watches, Jo's read messages or the watchdog, so some pushes may be missing here.");
});

test("the month calendar invents no Jo status when there is no Jo record", async ({ page }) => {
  await page.goto("/daily");
  await expect(page.getByTestId("jo-calendar-legend")).toContainText("Jo ? a record is unknown, not fine. No mark: no Jo record.");
  await expect(page.getByTestId("jo-calendar-mark")).toHaveCount(0);
});
