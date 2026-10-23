import { expect, test, type Page } from "@playwright/test";
import type { MarketReadPacket, MarketReadSession, MarketReadSlot, MarketReadsView, SlotDelivery } from "../lib/marketReads";

const slotAt: Record<string, string> = { "09:50": "13:50", "11:00": "15:00", "12:30": "16:30", "14:00": "18:00" };
const at = (day: string, utc: string, seconds = 0) => new Date(Date.parse(`${day}T${utc}:00Z`) + seconds * 1000).toISOString().replace(".000Z", ".000000Z");
const prep: Record<string, string> = { "09:50": "09-49", "11:00": "10-59", "12:30": "12-29", "14:00": "13-59" };
const packet = (slot: string, extra: Partial<MarketReadPacket> = {}): MarketReadPacket => ({ slot: prep[slot],
  status: "published", attempts: 1, recorded_at: null, snapshot_id: "mws_a", error_code: null, quality_flags: [], ...extra });

function slot(day: string, name: string, extra: Partial<MarketReadSlot> = {}): MarketReadSlot {
  return { slot: name, scheduled_at: at(day, slotAt[name]), expected: true, not_expected_reason: null, operation_id: `mw-scheduled-v1:${day}:${name}`,
    packet: packet(name), status: "no_read_seen", read_id: null, attribution: null, received_at: null, read: null, receipt_delay_seconds: null,
    read_used_slot_packet: null, deadline: at(day, slotAt[name], 15 * 60), delivery: "missing", late_by_seconds: null, ...extra };
}
const read = (day: string, name: string, seconds: number, attribution: "operation_id" | "time_window" = "time_window") =>
  slot(day, name, { status: "read_seen", read_id: `mwr_${name}`, attribution, received_at: at(day, slotAt[name], seconds), receipt_delay_seconds: seconds, read_used_slot_packet: true,
    delivery: seconds <= 900 ? "on_time" : "late", late_by_seconds: seconds <= 900 ? null : seconds - 900 });
const off = { state: "off" as const, checked_at: null, notices: [] };

function session(day: string, slots: MarketReadSlot[], extra: Partial<MarketReadSession> = {}): MarketReadSession {
  const summary = { read_seen: 0, no_read_seen: 0, upcoming: 0, not_expected: 0, unknown: 0 };
  const delivery: Record<SlotDelivery, number> = { on_time: 0, late: 0, missing: 0, pending: 0, not_expected: 0, unknown: 0 };
  slots.forEach((s) => { summary[s.status] += 1; delivery[s.delivery] += 1; });
  return { session_date: day, hours: { status: "open", open: 570, close: 960 }, slots, reads_not_credited_to_a_slot: [], summary,
    delivery_summary: delivery, watchdog: off, ...extra };
}

const monday = "2026-10-19";
const view = (sessions: MarketReadSession[], extra: Partial<MarketReadsView> = {}): MarketReadsView => ({
  checked_at: "2026-10-20T21:00:00.000000Z", market_watch_enabled: true, reads_available: true, receipts_available: true,
  attribution_window_minutes: 30, deadline_minutes: 15, reads_through: "2026-10-20T20:59:30.000000Z", sessions, limits: [],
  importer: { running: true, outbox_configured: true, last_ingest: "2026-10-20T20:59:30.000000Z", current: true }, ...extra });

async function open(page: Page, body: MarketReadsView) {
  await page.route("**/jo/market-reads", (route) => route.fulfill({ json: body }));
  await page.goto("/morning/market-reads");
  await expect(page.getByTestId("market-reads")).toBeVisible();
}

async function fitsPhone(page: Page, name: string) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
  await page.screenshot({ path: test.info().outputPath(`market-reads-${name}-phone.png`), fullPage: true });
}

test.beforeEach(async ({ page }) => { await page.setViewportSize({ width: 390, height: 844 }); });

test("linked from Morning; the real backend without records says evidence is unknown", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/morning");
  await page.getByRole("link", { name: "Jo’s scheduled market reads →" }).click();
  await expect(page).toHaveURL(/\/morning\/market-reads$/);
  await expect(page.getByTestId("reads-evidence")).toContainText("whether Jo's reads arrived is unknown");
  await expect(page.getByTestId("reads-evidence")).toContainText("packet status is unknown");
  await expect(page.getByText("No read seen", { exact: true })).toHaveCount(0);
  await fitsPhone(page, "unknown");
  expect(errors).toEqual([]);
});

test("measured delays, on-time/late/missing delivery and publisher outcomes", async ({ page }) => {
  await open(page, view([session(monday, [
    read(monday, "09:50", 130),
    read(monday, "11:00", 17 * 60 + 30, "operation_id"),
    slot(monday, "12:30", { packet: packet("12:30", { status: "started", snapshot_id: null }) }),
    slot(monday, "14:00", { packet: packet("14:00", { status: "failed", error_code: "snapshot_collection_failed", snapshot_id: null, attempts: 2 }) }),
  ], { reads_not_credited_to_a_slot: [{ read_id: "mwr_after_window", received_at: at(monday, "18:45"), event_wake_id: "wake-fixture", read: { view: "up", main_text: "Correction: SPY reclaimed VWAP; the weak-tape worry no longer holds.",
    alternative_text: "Could stall at 771.", invalidation_text: "Loses VWAP again.", change_summary: "Corrects the 9:50 read.", is_correction: true } }] })]));
  const slots = page.getByTestId("read-slot");
  await expect(page.getByTestId("session-summary")).toHaveText("2 of 4 due slots with a read");
  await expect(page.getByTestId("session-delivery")).toHaveText("1 on time · 1 late · 2 missing");
  await expect(slots.nth(0).getByTestId("slot-badge")).toHaveText("On time");
  await expect(slots.nth(1).getByTestId("slot-badge")).toHaveText("Late · 3 min past due");
  await expect(slots.nth(0).getByTestId("slot-delay")).toContainText("2 min 10 s after the slot");
  await expect(slots.nth(0)).toContainText("Matched by time: the first read within 30 min of the slot. A manual or setup read can count; the scheduled run is unverified. Used this slot's packet.");
  await expect(slots.nth(1).getByTestId("slot-delay")).toContainText("17 min 30 s after the slot");
  await expect(slots.nth(1)).toContainText("Schedule reference matched. The app cannot verify who started the run.");
  await expect(slots.nth(2).getByTestId("slot-badge")).toHaveText("Missing");
  await expect(slots.nth(2)).toContainText("No read was seen in TradeJournal by 12:45 PM ET. The cause is not visible to the app.");
  await expect(slots.nth(2).getByTestId("slot-packet")).toHaveText("Packet 12:29: started, outcome unknown");
  await expect(slots.nth(3).getByTestId("slot-packet")).toHaveText("Packet 13:59: failed (snapshot_collection_failed) · attempt 2");
  await page.getByText("Extra reads outside the schedule (1)").click();
  await expect(page.getByTestId("extra-read")).toContainText("2:45:00 PM ET · market-alert link unverified");
  // What Jo said, not just when: the extra read's own words show, with no raw record ID.
  await expect(page.getByTestId("extra-read")).toContainText("the weak-tape worry no longer holds");
  await expect(page.getByTestId("extra-read")).not.toContainText("mwr_after_window");
  await expect(page.getByTestId("session-watchdog")).toHaveText("Phone watchdog: off, so no phone alert is sent for a missing read.");
  await fitsPhone(page, "measured");
});

test("a saved read with unknown attribution is not presented as a time match", async ({ page }) => {
  await open(page, view([session(monday, [
    { ...read(monday, "09:50", 130), attribution: null },
  ])]));
  const slot = page.getByTestId("read-slot");
  await expect(slot).toContainText("The read's link to this scheduled slot is unknown.");
  await expect(slot).not.toContainText("Matched by time");
  await expect(slot).not.toContainText("Schedule reference matched");
});

test("holiday, early close and skipped packets are not expected", async ({ page }) => {
  const holiday = "2026-11-26", half = "2026-11-27";
  await open(page, view([
    session(half, [read(half, "09:50", 45), slot(half, "11:00", { status: "upcoming", delivery: "pending", packet: packet("11:00", { status: "no_receipt", snapshot_id: null }) }),
      slot(half, "12:30"), slot(half, "14:00", { expected: false, not_expected_reason: "after_close", status: "not_expected", delivery: "not_expected", deadline: null,
        packet: packet("14:00", { status: "skipped_outside_regular_session", snapshot_id: null }) })], { hours: { status: "open", open: 570, close: 780 } }),
    session(holiday, ["09:50", "11:00", "12:30", "14:00"].map((name) => slot(holiday, name, { expected: false, not_expected_reason: "exchange_closed",
      status: "not_expected", delivery: "not_expected", deadline: null, packet: packet(name, { status: "skipped_exchange_closed", snapshot_id: null }) })), { hours: { status: "closed", open: null, close: null } }),
  ]));
  const [early, closed] = [page.getByTestId("read-session").nth(0), page.getByTestId("read-session").nth(1)];
  await expect(early).toContainText("9:30 AM–1:00 PM · early close");
  await expect(early.getByTestId("session-summary")).toHaveText("1 of 2 due slots with a read · 1 upcoming");
  await expect(early.locator("[data-status=not_expected]")).toContainText("After the 1:00 PM close.");
  await expect(early.locator("[data-status=not_expected]")).toContainText("Packet 13:59: skipped: outside the regular session");
  await expect(early.locator("[data-status=upcoming]")).toContainText("Packet 10:59: no publisher receipt");
  await expect(early.locator("[data-status=upcoming]").getByTestId("slot-badge")).toHaveText(/^Due by \d{1,2}:15 AM ET$/);
  await expect(closed).toContainText("Market closed");
  await expect(closed.getByTestId("session-summary")).toHaveCount(0);
  await expect(closed.locator("[data-status=not_expected]")).toHaveCount(4);
  await expect(closed.getByTestId("session-watchdog")).toHaveCount(0);
  await fitsPhone(page, "holiday");
});

test("a stalled import leaves slots unknown, and the watchdog's notices are shown", async ({ page }) => {
  const today = "2026-10-21";
  await open(page, view([session(today, [
    read(today, "09:50", 46),
    slot(today, "11:00", { delivery: "unknown" }),
    slot(today, "12:30", { status: "upcoming", delivery: "pending" }),
    slot(today, "14:00", { status: "upcoming", delivery: "pending" }),
  ], { watchdog: { state: "on", checked_at: "2026-10-21T15:20:00Z", notices: [
    { kind: "importer", title: "Jo's market reads aren't being checked", recovered: false, outcome: "unknown", at: "2026-10-21T15:12:00Z" }] } })],
  { importer: { running: true, outbox_configured: true, last_ingest: "2026-10-21T15:05:00.000000Z", current: false } }));
  await expect(page.getByTestId("reads-importer")).toContainText("The app last checked for Jo's reads at 11:05:00 AM ET");
  const pending = page.locator("[data-delivery=unknown]");
  await expect(pending.getByTestId("slot-badge")).toHaveText("Unknown");
  await expect(pending).toContainText("hasn’t checked for reads since the 11:15 AM ET deadline");
  await expect(page.getByTestId("session-delivery")).toHaveText("1 on time · 1 unknown");
  await expect(page.getByTestId("session-watchdog")).toContainText("“Jo's market reads aren't being checked” at 11:12 AM ET: outcome unknown, may have reached your phone; not resent.");
  await fitsPhone(page, "importer");
});
