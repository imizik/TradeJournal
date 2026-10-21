"use client";
import { useEffect, useState } from "react";
import { getMarketReads, type MarketReadPacket, type MarketReadSession, type MarketReadSlot, type MarketReadsView } from "@/lib/marketReads";

const zone = "America/New_York";
const clock = (value: string) => new Date(value).toLocaleTimeString("en-US", { timeZone: zone, hour: "numeric", minute: "2-digit", second: "2-digit" }) + " ET";
const minuteOfDay = (m: number) => new Date(Date.UTC(2000, 0, 1, Math.floor(m / 60), m % 60)).toLocaleTimeString("en-US", { timeZone: "UTC", hour: "numeric", minute: "2-digit" });
const day = (value: string) => new Date(`${value}T12:00:00Z`).toLocaleDateString("en-US", { timeZone: "UTC", weekday: "short", month: "short", day: "numeric" });
const button = "inline-flex min-h-11 items-center justify-center rounded-md border px-3 text-sm hover:bg-secondary disabled:opacity-50";
const warn = "border-amber-500/40 bg-amber-500/10 text-amber-200";
const muted = "border-border bg-secondary/40 text-muted-foreground";

/** The measured delay; on time or late is the slot's delivery badge. */
function delay(seconds: number) {
  const s = Math.abs(seconds), m = Math.floor(s / 60), rest = s % 60;
  const text = m ? `${m} min${rest ? ` ${rest} s` : ""}` : `${rest} s`;
  return `${text} ${seconds < 0 ? "before" : "after"} the slot`;
}

function packet(p: MarketReadPacket) {
  const flags = p.quality_flags.length;
  const text: Record<string, string> = {
    published: "published",
    published_partial: `published with ${flags} disclosed ${flags === 1 ? "gap" : "gaps"}`,
    failed: `failed${p.error_code ? ` (${p.error_code})` : ""}`,
    started: "started, outcome unknown",
    skipped_exchange_closed: "skipped: market closed",
    skipped_outside_regular_session: "skipped: outside the regular session",
    no_receipt: "no publisher receipt",
    not_due: "not due yet",
    unreadable: "receipt unreadable",
    unknown: "receipts unavailable on this server",
  };
  const label = text[p.status] ?? p.status;
  return `Packet ${p.slot.replace("-", ":")}: ${label}${p.attempts > 1 ? ` · attempt ${p.attempts}` : ""}`;
}

const minutes = (seconds: number) => seconds < 90 ? `${seconds} s` : `${Math.round(seconds / 60)} min`;
const short = (value: string) => new Date(value).toLocaleTimeString("en-US", { timeZone: zone, hour: "numeric", minute: "2-digit" }) + " ET";
const outcomeText = { sent: "sent", failed: "couldn’t be sent; retrying", unknown: "outcome unknown, may have reached your phone; not resent" };

function badge(s: MarketReadSlot): [string, string] {
  switch (s.delivery) {
    case "on_time": return ["On time", muted];
    case "late": return [`Late · ${minutes(s.late_by_seconds ?? 0)} past due`, warn];
    case "missing": return ["Missing", warn];
    case "pending": return [s.deadline ? `Due by ${short(s.deadline)}` : "Upcoming", muted];
    case "not_expected": return ["Not expected", muted];
    case "unknown": return ["Unknown", warn];
  }
}

function Slot({ s, close, window }: { s: MarketReadSlot; close: number | null; window: number }) {
  const [label, tone] = badge(s);
  return <li data-testid="read-slot" data-status={s.status} data-delivery={s.delivery} className="min-w-0 space-y-1 border-t py-3 first:border-t-0">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <span className="font-medium">{s.slot} ET</span>
      <span data-testid="slot-badge" className={`rounded-full border px-2 py-0.5 text-xs ${tone}`}>{label}</span>
    </div>
    {s.received_at && <p className="text-sm" data-testid="slot-delay">
      Received {clock(s.received_at)} · <strong>{delay(s.receipt_delay_seconds!)}</strong></p>}
    {s.read_id && <p className="text-xs text-muted-foreground">
      {s.attribution === "operation_id" ? "Linked by its scheduled operation ID." : `Linked by time: the first read within ${window} min of the slot.`}
      {s.read_used_slot_packet === true ? " Used this slot's packet." : s.read_used_slot_packet === false ? " Used a different packet." : ""}</p>}
    {s.status === "no_read_seen" && s.delivery === "missing" && <p className="text-sm text-muted-foreground">No read was seen in TradeJournal by {short(s.deadline!)}. The cause is not visible to the app.</p>}
    {s.status === "no_read_seen" && s.delivery === "unknown" && <p className="text-sm text-muted-foreground">No read seen, but the app hasn’t checked for reads since the {short(s.deadline!)} deadline, so one may still arrive.</p>}
    {s.status === "not_expected" && <p className="text-sm text-muted-foreground">{s.not_expected_reason === "after_close" ? `After the ${close !== null ? minuteOfDay(close) : ""} close.` : "Market closed."}</p>}
    {s.status === "unknown" && <p className="text-sm text-muted-foreground">{s.expected === null ? "Exchange hours are unknown for this day, so whether this read was due is unknown." : "Read records are not available on this server."}</p>}
    <p className="text-xs text-muted-foreground" data-testid="slot-packet">{packet(s.packet)}</p>
  </li>;
}

function hours(h: MarketReadSession["hours"]) {
  if (!h) return "Hours unknown";
  if (h.status === "closed") return "Market closed";
  return `${minuteOfDay(h.open!)}–${minuteOfDay(h.close!)}${h.close! < 960 ? " · early close" : ""}`;
}

/** The watchdog keeps seven days of notices and reports only its current switch. */
function Watchdog({ w, kept }: { w: MarketReadSession["watchdog"]; kept: boolean }) {
  return <p className="mt-2 text-xs text-muted-foreground" data-testid="session-watchdog">Phone watchdog: {w.state === "unknown" ? "status unavailable."
    : !kept && !w.notices.length ? "no record kept for this date."
    : w.state === "off" ? "off, so no phone alert is sent for a missing read."
    : w.notices.length ? w.notices.map((n, i) => <span key={i}>{i ? " " : ""}“{n.title}” at {short(n.at)}: {outcomeText[n.outcome]}{(n.attempts ?? 1) > 1 ? ` after ${n.attempts} attempts` : ""}.</span>)
    : "on; nothing sent for this date."}</p>;
}

function Session({ s, window, today }: { s: MarketReadSession; window: number; today: string }) {
  const expected = s.summary.read_seen + s.summary.no_read_seen;
  const d = s.delivery_summary;
  return <li data-testid="read-session" className="min-w-0 rounded-lg border bg-card p-4">
    <div className="flex flex-wrap items-baseline justify-between gap-2">
      <h2 className="font-semibold">{day(s.session_date)}</h2>
      <span className="text-xs text-muted-foreground">{hours(s.hours)}</span>
    </div>
    {expected > 0 && <p className="text-sm text-muted-foreground" data-testid="session-summary">{s.summary.read_seen} of {expected} due {expected === 1 ? "slot" : "slots"} with a read{s.summary.upcoming ? ` · ${s.summary.upcoming} upcoming` : ""}</p>}
    {expected > 0 && <p className="text-sm" data-testid="session-delivery">{d.on_time} on time{d.late ? ` · ${d.late} late` : ""}{d.missing ? ` · ${d.missing} missing` : ""}{d.unknown ? ` · ${d.unknown} unknown` : ""}</p>}
    <ul className="mt-1">{s.slots.map((slot) => <Slot key={slot.slot} s={slot} close={s.hours?.close ?? null} window={window} />)}</ul>
    {!!s.reads_not_credited_to_a_slot.length && <details className="mt-2 rounded-md border px-3">
      <summary className="min-h-11 cursor-pointer py-3 text-sm">Other reads not credited to a slot ({s.reads_not_credited_to_a_slot.length})</summary>
      <ul className="space-y-1 pb-3 text-sm text-muted-foreground">{s.reads_not_credited_to_a_slot.map((r) =>
        <li key={r.read_id}>{clock(r.received_at)}{r.event_wake_id ? " · answered an event wake" : ""} · <code className="break-all text-xs">{r.read_id}</code></li>)}</ul>
    </details>}
    {s.hours?.status !== "closed" && <Watchdog w={s.watchdog} kept={(Date.parse(today) - Date.parse(s.session_date)) / 86400000 < 7} />}
  </li>;
}

export default function MarketReads() {
  const [data, setData] = useState<MarketReadsView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    getMarketReads(controller.signal).then((v) => { setData(v); setError(null); })
      .catch((reason) => { if (!controller.signal.aborted) setError((reason as Error).message); });
    return () => controller.abort();
  }, [refresh]);
  return <div className="min-w-0 space-y-6 break-words" data-testid="market-reads">
    <header className="space-y-2">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div><p className="text-xs text-muted-foreground">Jo&apos;s follow-through</p><h1 className="text-xl font-semibold">Scheduled market reads</h1></div>
        <button type="button" onClick={() => setRefresh((r) => r + 1)} className={button}>Refresh</button>
      </div>
      <p className="text-sm text-muted-foreground">Each of Jo&apos;s 9:50, 11:00, 12:30 and 2:00 reads: whether the app prepared its packet, whether a read arrived, and how long after the slot the Check service received it. A read is on time within {data?.deadline_minutes ?? 15} minutes of its slot; that limit is a proposal for you to confirm.</p>
    </header>
    {error && <p role="alert" className="text-sm text-amber-300">{error}{data && " Showing the previously loaded records."}</p>}
    {!data && !error && <p role="status" className="text-sm text-muted-foreground">Loading scheduled reads…</p>}
    {data && <>
      {data.market_watch_enabled && data.reads_available && !data.importer.current && <p data-testid="reads-importer" className={`rounded-lg border p-4 text-sm ${warn}`}>
        {data.importer.outbox_configured ? `The app last checked for Jo's reads ${data.importer.last_ingest ? `at ${clock(data.importer.last_ingest)}` : "before its last restart"}, so a newer read may not show yet. Slots due since then stay unknown, not missing.`
          : "The app isn't set up to receive Jo's reads, so a missing read can't be told apart from one that wasn't imported."}</p>}
      {(!data.reads_available || !data.receipts_available) && <p data-testid="reads-evidence" className={`rounded-lg border p-4 text-sm ${warn}`}>
        {!data.reads_available && "Read records are not available on this server, so whether Jo's reads arrived is unknown. "}
        {!data.receipts_available && "Publisher receipts are not available on this server, so packet status is unknown."}</p>}
      {data.sessions.length ? <ul className="space-y-3">{data.sessions.map((s) => <Session key={s.session_date} s={s} window={data.attribution_window_minutes} today={new Date(data.checked_at).toLocaleDateString("en-CA", { timeZone: zone })} />)}</ul>
        : <p className="text-sm text-muted-foreground">No sessions to show yet.</p>}
      <details className="rounded-md border px-3">
        <summary className="min-h-11 cursor-pointer py-3 text-sm">What these numbers can&apos;t show</summary>
        <ul className="list-disc space-y-1 pb-3 pl-4 text-sm text-muted-foreground">
          <li>The time shown is when the Check service saved the read, not when Jo started.</li>
          <li>A slot with no read has no visible cause here; Jo&apos;s hosted run history is outside the app.</li>
          <li>This screen links reads by time: the first read within {data.attribution_window_minutes} minutes of a slot and before the next wake. A manual or setup read in that window counts for the slot; a later read is listed under other reads, and the slot shows no read seen.</li>
          <li>A packet receipt proves the app prepared it, not that Jo was woken.</li>
          <li>On time is judged on the Check service&apos;s save time. A read after the {data.attribution_window_minutes}-minute window isn&apos;t linked to its slot, so the slot stays missing; a reply to an event wake or a manual read inside the window can stand in for a missed scheduled run.</li>
        </ul>
      </details>
      <p className="text-xs text-muted-foreground">Checked {clock(data.checked_at)} · latest {data.sessions.length} {data.sessions.length === 1 ? "weekday" : "weekdays"}{data.market_watch_enabled ? "" : " · market watch is off on this server"}</p>
    </>}
  </div>;
}
