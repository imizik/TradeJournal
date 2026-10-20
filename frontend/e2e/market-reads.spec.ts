import { expect, test, type Page } from "@playwright/test";
import type { MarketReadPacket, MarketReadSession, MarketReadSlot, MarketReadsView } from "../lib/marketReads";

const slotAt: Record<string, string> = { "09:50": "13:50", "11:00": "15:00", "12:30": "16:30", "14:00": "18:00" };
const at = (day: string, utc: string, seconds = 0) => new Date(Date.parse(`${day}T${utc}:00Z`) + seconds * 1000).toISOString().replace(".000Z", ".000000Z");
const prep: Record<string, string> = { "09:50": "09-49", "11:00": "10-59", "12:30": "12-29", "14:00": "13-59" };
const packet = (slot: string, extra: Partial<MarketReadPacket> = {}): MarketReadPacket => ({ slot: prep[slot],
  status: "published", attempts: 1, recorded_at: null, snapshot_id: "mws_a", error_code: null, quality_flags: [], ...extra });

function slot(day: string, name: string, extra: Partial<MarketReadSlot> = {}): MarketReadSlot {
  return { slot: name, scheduled_at: at(day, slotAt[name]), expected: true, not_expected_reason: null, operation_id: `mw-scheduled-v1:${day}:${name}`,
    packet: packet(name), status: "no_read_seen", read_id: null, attribution: null, received_at: null, receipt_delay_seconds: null,
    read_used_slot_packet: null, ...extra };
}
const read = (day: string, name: string, seconds: number, attribution: "operation_id" | "time_window" = "time_window") =>
  slot(day, name, { status: "read_seen", read_id: `mwr_${name}`, attribution, received_at: at(day, slotAt[name], seconds), receipt_delay_seconds: seconds, read_used_slot_packet: true });

function session(day: string, slots: MarketReadSlot[], extra: Partial<MarketReadSession> = {}): MarketReadSession {
  const summary = { read_seen: 0, no_read_seen: 0, upcoming: 0, not_expected: 0, unknown: 0 };
  slots.forEach((s) => { summary[s.status] += 1; });
  return { session_date: day, hours: { status: "open", open: 570, close: 960 }, slots, reads_not_credited_to_a_slot: [], summary, ...extra };
}

const monday = "2026-10-19";
const view = (sessions: MarketReadSession[], extra: Partial<MarketReadsView> = {}): MarketReadsView => ({
  checked_at: "2026-10-20T21:00:00.000000Z", market_watch_enabled: true, reads_available: true, receipts_available: true,
  attribution_window_minutes: 30, sessions, limits: [], ...extra });

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

test("measured delays, missing reads and publisher outcomes, with no on-time label", async ({ page }) => {
  await open(page, view([session(monday, [
    read(monday, "09:50", 130),
    read(monday, "11:00", 17 * 60 + 30, "operation_id"),
    slot(monday, "12:30", { packet: packet("12:30", { status: "started", snapshot_id: null }) }),
    slot(monday, "14:00", { packet: packet("14:00", { status: "failed", error_code: "snapshot_collection_failed", snapshot_id: null, attempts: 2 }) }),
  ], { reads_not_credited_to_a_slot: [{ read_id: "mwr_after_window", received_at: at(monday, "18:45"), event_wake_id: null }] })]));
  const slots = page.getByTestId("read-slot");
  await expect(page.getByTestId("session-summary")).toHaveText("2 of 4 due slots with a read");
  await expect(slots.nth(0).getByTestId("slot-delay")).toContainText("2 min 10 s after the slot");
  await expect(slots.nth(0)).toContainText("Linked by time: the first read within 30 min of the slot. Used this slot's packet.");
  await expect(slots.nth(1).getByTestId("slot-delay")).toContainText("17 min 30 s after the slot");
  await expect(slots.nth(1)).toContainText("Linked by its scheduled operation ID.");
  await expect(slots.nth(2).getByTestId("slot-badge")).toHaveText("No read seen");
  await expect(slots.nth(2)).toContainText("The cause is not visible to the app.");
  await expect(slots.nth(2).getByTestId("slot-packet")).toHaveText("Packet 12:29: started, outcome unknown");
  await expect(slots.nth(3).getByTestId("slot-packet")).toHaveText("Packet 13:59: failed (snapshot_collection_failed) · attempt 2");
  await page.getByText("Other reads not credited to a slot (1)").click();
  await expect(page.getByText("2:45:00 PM ET")).toBeVisible();
  await expect(page.getByText(/on time|late\b/i)).toHaveCount(0);
  await fitsPhone(page, "measured");
});

test("holiday, early close and skipped packets are not expected", async ({ page }) => {
  const holiday = "2026-11-26", half = "2026-11-27";
  await open(page, view([
    session(half, [read(half, "09:50", 45), slot(half, "11:00", { status: "upcoming", packet: packet("11:00", { status: "no_receipt", snapshot_id: null }) }),
      slot(half, "12:30"), slot(half, "14:00", { expected: false, not_expected_reason: "after_close", status: "not_expected",
        packet: packet("14:00", { status: "skipped_outside_regular_session", snapshot_id: null }) })], { hours: { status: "open", open: 570, close: 780 } }),
    session(holiday, ["09:50", "11:00", "12:30", "14:00"].map((name) => slot(holiday, name, { expected: false, not_expected_reason: "exchange_closed",
      status: "not_expected", packet: packet(name, { status: "skipped_exchange_closed", snapshot_id: null }) })), { hours: { status: "closed", open: null, close: null } }),
  ]));
  const [early, closed] = [page.getByTestId("read-session").nth(0), page.getByTestId("read-session").nth(1)];
  await expect(early).toContainText("9:30 AM–1:00 PM · early close");
  await expect(early.getByTestId("session-summary")).toHaveText("1 of 2 due slots with a read · 1 upcoming");
  await expect(early.locator("[data-status=not_expected]")).toContainText("After the 1:00 PM close.");
  await expect(early.locator("[data-status=not_expected]")).toContainText("Packet 13:59: skipped: outside the regular session");
  await expect(early.locator("[data-status=upcoming]")).toContainText("Packet 10:59: no publisher receipt");
  await expect(closed).toContainText("Market closed");
  await expect(closed.getByTestId("session-summary")).toHaveCount(0);
  await expect(closed.locator("[data-status=not_expected]")).toHaveCount(4);
  await fitsPhone(page, "holiday");
});
