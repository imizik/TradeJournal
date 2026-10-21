import { expect, test, type Page } from "@playwright/test";
import type { PlansView, PlanView } from "../lib/conditionalPlans";
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

function reads(day: string, live: boolean): MarketReadsView {
  const first = slot(day, "09:50", { status: "read_seen", read_id: "mwr_1", received_at: iso(day, "09:50"), delivery: "on_time",
    packet: { slot: "09-49", status: "published_partial", attempts: 1, recorded_at: null, snapshot_id: "mws_a", error_code: null, quality_flags: ["gap:headlines"] },
    read: text("SPY is holding its opening range; no clean break yet.") });
  const rest = ["11:00", "12:30", "14:00"].map((name) => live ? slot(day, name)
    : slot(day, name, { status: "no_read_seen", delivery: "missing" }));
  return { checked_at: new Date().toISOString(), market_watch_enabled: true, reads_available: true, receipts_available: true,
    attribution_window_minutes: 30, deadline_minutes: 15, reads_through: new Date().toISOString(), limits: [],
    importer: { running: true, outbox_configured: true, last_ingest: new Date().toISOString(), current: true },
    sessions: [{ session_date: day, hours: { status: "open", open: 570, close: 960 }, slots: [first, ...rest],
      reads_not_credited_to_a_slot: [{ read_id: "mwr_2", received_at: iso(day, "10:45"), event_wake_id: null,
        read: text("Correction: SPY recovered above VWAP, so the bearish note no longer holds.", { is_correction: true }) }],
      summary: { read_seen: 1, no_read_seen: live ? 0 : 3, upcoming: live ? 3 : 0, not_expected: 0, unknown: 0 },
      delivery_summary: { on_time: 1, late: 0, missing: live ? 0 : 3, pending: live ? 3 : 0, not_expected: 0, unknown: 0 },
      watchdog: { state: "on", checked_at: null, notices: [] } }] };
}

function morning(day: string): MorningView {
  return { day, state: "ready", late: false, stale: false, archived: false, deadline: iso(day, "09:15"), checked_at: new Date().toISOString(),
    automation: { enabled: true, last_pass: null, unavailable: false },
    delivery: { calendar: "open", publication: "published", fulfilment: "on_time", deadline: iso(day, "09:15"), publish_at: iso(day, "08:45"),
      packet_id: "p1", published_at: iso(day, "08:45"), briefing_id: "b1", available_at: iso(day, "08:56"), submitted_at: iso(day, "08:56"),
      import_lag_seconds: 9, late_by_seconds: 0, origin: "unknown", other_briefings: 0, notifications: { chatgpt: "not_observable", watchdog: null } },
    packet: null, versions: [], feedback: { rating: null, first_opened_at: null },
    briefing: { id: "b1", received_at: iso(day, "08:56"), redacted_at: null, body: { summary: "Two expiries need decisions before new risk.",
      items: [{ symbol: "APLD", what_matters: "Review the six $24 calls expiring Friday.", why_personal: "", what_changed: "", contrary_evidence: "", watch_out: "", evidence_ids: [] },
        { symbol: "NBIS", what_matters: "Verify price before acting on the compute-shortage headline.", why_personal: "", what_changed: "", contrary_evidence: "", watch_out: "", evidence_ids: [] }] } } };
}

function plans(day: string, live: boolean): PlansView {
  const watch: PlanView = { plan_id: "plan_1", actor: "check_1", session_date: day, symbol: "MU", direction: "long", trigger_price: 140, invalidation_price: 137.5,
    confirm_bars: 2, rationale: "Owner asked to track a breakout over 140.", source: { kind: "check", id: "c", sha256: "s", observed_at: iso(day, "10:20"), price: 139.2 },
    expires_at: live ? new Date(Date.now() + 3_600_000).toISOString() : iso(day, "14:20"), created_at: iso(day, "10:21"), accepted_by_monitor: true, cancel_requested: false,
    state: live ? "watching" : "expired", reason: null, state_at: null, monitoring: true, heartbeat_at: null, last_bar: null, last_evaluated_at: null, events: [], deliveries: [] };
  return { checked_at: new Date().toISOString(), enabled: true, app_flag: true, stock_watch: true, configured: true,
    readiness: { heartbeat: "fresh" }, max_daily_plans: 24, plans_today: 1, limit: 50, delivery: { channel: "ntfy", configured: true }, plans: [watch] };
}

async function stub(page: Page, day: string, live: boolean) {
  await page.route("**/jo/morning?**", (route) => route.fulfill({ json: morning(day) }));
  await page.route("**/jo/market-reads?**", (route) => route.fulfill({ json: reads(day, live) }));
  await page.route("**/jo/conditional-plans", (route) => route.fulfill({ json: plans(day, live) }));
}

test("today's Daily Review shows what Jo did, is watching and will do, with Jo's own read text", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.setViewportSize({ width: 1440, height: 1000 });
  await stub(page, today, true);
  await page.goto(`/daily/${today}`);
  const jo = page.getByTestId("jo-day");
  await expect(page.getByTestId("jo-day-headline")).toHaveText(/^Briefing on time · 1 of 4 market reads in · 1 extra read · 1 price watch · .* · next: 11:00 market read$/);
  await expect(jo.getByText("Morning briefing: APLD, NBIS")).toBeVisible();
  const first = jo.getByTestId("jo-day-item").filter({ hasText: "Scheduled market read · mixed" });
  await expect(first).toContainText("Data had gaps");
  await first.locator("summary").click();
  await expect(first).toContainText("SPY is holding its opening range");
  await expect(first).toContainText("Wrong if:");
  await expect(jo.getByText("Extra market read · mixed · correction")).toBeVisible();
  await expect(jo.getByText("MU long watch: 2 closes above 140", { exact: true })).toBeVisible();
  await expect(jo.getByRole("heading", { name: "Coming up" })).toBeVisible();
  await expect(jo.getByTestId("jo-day-item").filter({ hasText: "Upcoming" })).toHaveCount(3);
  await jo.screenshot({ path: test.info().outputPath("jo-day-today-desktop.png") });

  // The jump bar stays reachable and moves to each section.
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

test("a past day is a record: missing reads are flagged and nothing is shown as upcoming", async ({ page }) => {
  const past = "2026-10-01";
  await page.setViewportSize({ width: 1440, height: 1000 });
  await stub(page, past, false);
  await page.goto(`/daily/${past}`);
  const jo = page.getByTestId("jo-day");
  await expect(page.getByTestId("jo-day-headline")).toHaveText(/^Briefing on time · 1 of 4 market reads in · 1 extra read · 1 price watch/);
  await expect(page.getByTestId("jo-day-headline")).toHaveClass(/text-amber-200/);
  await expect(jo.getByTestId("jo-day-item").filter({ hasText: "Missing" })).toHaveCount(3);
  await expect(jo.getByRole("heading", { name: "Coming up" })).toHaveCount(0);
  await expect(jo.getByText("expired")).toBeVisible();
});

test("one failed record is named and the rest still show", async ({ page }) => {
  await stub(page, today, true);
  await page.route("**/jo/conditional-plans", (route) => route.fulfill({ status: 503, json: { detail: "down" } }));
  await page.goto(`/daily/${today}`);
  await expect(page.getByTestId("jo-day").getByRole("alert")).toHaveText("Couldn't load price watches. What's shown may be incomplete.");
  await expect(page.getByText("Morning briefing: APLD, NBIS")).toBeVisible();
});

test("the dashboard links to today's Jo timeline", async ({ page }) => {
  await stub(page, today, true);
  await page.goto("/");
  const line = page.getByTestId("jo-today-line");
  await expect(line).toContainText("Briefing on time · 1 of 4 market reads in");
  await line.click();
  await expect(page).toHaveURL(new RegExp(`/daily/${today}#jo$`));
});
