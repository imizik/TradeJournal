import { apiUrl } from "./api";
import type { WatchdogNotice } from "./joMorning";

export type SlotStatus = "read_seen" | "no_read_seen" | "upcoming" | "not_expected" | "unknown";
/** Judged on the Check receipt time against the slot's deadline (slot + deadline_minutes, a proposed tolerance). */
export type SlotDelivery = "on_time" | "late" | "missing" | "pending" | "not_expected" | "unknown";
export type MarketReadPacket = { slot: string; status: string; attempts: number; recorded_at: string | null; snapshot_id: string | null;
  error_code: string | null; quality_flags: string[] };
/** Jo's own words for one read, as the Check service saved them; null when only timing is known. */
export type MarketReadText = { view: "up" | "down" | "mixed" | "no_view"; main_text: string; alternative_text: string;
  invalidation_text: string; change_summary: string; is_correction: boolean };
/** One scheduled Jo read. receipt_delay_seconds is measured from the slot time to the Check receipt. */
export type MarketReadSlot = { slot: string; scheduled_at: string; expected: boolean | null;
  not_expected_reason: "exchange_closed" | "after_close" | "exchange_calendar_unavailable" | null; operation_id: string;
  packet: MarketReadPacket; status: SlotStatus; read_id: string | null; attribution: "operation_id" | "time_window" | null;
  received_at: string | null; read: MarketReadText | null; receipt_delay_seconds: number | null; read_used_slot_packet: boolean | null;
  deadline: string | null; delivery: SlotDelivery; late_by_seconds: number | null };
export type MarketReadSession = { session_date: string; hours: { status: "open" | "closed"; open: number | null; close: number | null } | null;
  slots: MarketReadSlot[]; reads_not_credited_to_a_slot: { read_id: string; received_at: string; event_wake_id: string | null; read: MarketReadText | null }[];
  summary: Record<SlotStatus, number>; delivery_summary: Record<SlotDelivery, number>;
  watchdog: { state: "on" | "off" | "unknown"; checked_at: string | null; notices: WatchdogNotice[] } };
export type MarketReadsView = { checked_at: string; market_watch_enabled: boolean; reads_available: boolean; receipts_available: boolean;
  attribution_window_minutes: number; deadline_minutes: number; reads_through: string; sessions: MarketReadSession[]; limits: string[];
  importer: { running: boolean; outbox_configured: boolean; last_ingest: string | null; current: boolean } };

/** All recent weekdays, or one `day` (YYYY-MM-DD) for the Daily Review. */
export async function getMarketReads(signal?: AbortSignal, day?: string): Promise<MarketReadsView> {
  const response = await fetch(apiUrl(`/jo/market-reads${day ? `?day=${encodeURIComponent(day)}` : ""}`), { cache: "no-store", signal });
  if (!response.ok) throw new Error("Scheduled read records could not load.");
  return response.json();
}
