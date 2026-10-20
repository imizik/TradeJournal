import { apiUrl } from "./api";

export type SlotStatus = "read_seen" | "no_read_seen" | "upcoming" | "not_expected" | "unknown";
export type MarketReadPacket = { slot: string; status: string; attempts: number; recorded_at: string | null; snapshot_id: string | null;
  error_code: string | null; quality_flags: string[] };
/** One scheduled Jo read. receipt_delay_seconds is measured from the slot time to the Check receipt; no tolerance applies. */
export type MarketReadSlot = { slot: string; scheduled_at: string; expected: boolean | null;
  not_expected_reason: "exchange_closed" | "after_close" | "exchange_calendar_unavailable" | null; operation_id: string;
  packet: MarketReadPacket; status: SlotStatus; read_id: string | null; attribution: "operation_id" | "time_window" | null;
  received_at: string | null; receipt_delay_seconds: number | null; read_used_slot_packet: boolean | null };
export type MarketReadSession = { session_date: string; hours: { status: "open" | "closed"; open: number | null; close: number | null } | null;
  slots: MarketReadSlot[]; reads_not_credited_to_a_slot: { read_id: string; received_at: string; event_wake_id: string | null }[];
  summary: Record<SlotStatus, number> };
export type MarketReadsView = { checked_at: string; market_watch_enabled: boolean; reads_available: boolean; receipts_available: boolean;
  attribution_window_minutes: number; sessions: MarketReadSession[]; limits: string[] };

export async function getMarketReads(signal?: AbortSignal): Promise<MarketReadsView> {
  const response = await fetch(apiUrl("/jo/market-reads"), { cache: "no-store", signal });
  if (!response.ok) throw new Error("Scheduled read records could not load.");
  return response.json();
}
