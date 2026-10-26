import type { DecisionRecord, GmailHealth, PositionQuote, SyncJob, TradePhoneAlert } from "@/lib/api";
import type { LevelAlert } from "@/lib/alerts";
import type { Earnings } from "@/lib/symbolInfo";
import { getCurrentMark, type OpenPositionRow } from "@/lib/dashboard";

/** Integrity first, then the data feeding the journal, then dated events,
 * fired alerts, and open WAIT choices. Lower number sorts first. */
export const ATTENTION_PRIORITY = { integrity: 0, data: 1, soon: 2, alert: 3, follow_up: 4 } as const;
export type AttentionPriority = keyof typeof ATTENTION_PRIORITY;

export type AttentionItem = {
  /** Stable: rule plus record ID, so a re-render never reorders ties. */
  id: string;
  priority: AttentionPriority;
  title: string;
  detail: string;
  /** Short time cue at the right edge ("Today", "10/16", "2h ago"). */
  when: string;
  href: string;
  /** What the sort uses within a priority: an ISO date or time. */
  sortKey: string;
  /** How many positions this one row stands for (the same contract held in several accounts); absent means one. */
  count?: number;
};

/** How each source arrived. `null` means the request failed. */
export type AttentionInputs = {
  rows: OpenPositionRow[];
  quotes: Record<string, PositionQuote>;
  quoteError: boolean;
  today: string; // ET calendar date, YYYY-MM-DD
  now: number; // epoch milliseconds
  decisions: DecisionRecord[];
  alerts: LevelAlert[] | null;
  jobs: SyncJob[] | null;
  gmail: GmailHealth | null;
  /** Per underlying of an open option; a missing key was not requested. */
  earnings: Record<string, Earnings | null>;
  /** Phone alerts per open option trade ID; a missing key was not requested, `null` failed. */
  phoneAlerts?: Record<string, TradePhoneAlert[] | null>;
};

export type AttentionResult = { items: AttentionItem[]; unavailable: string[] };

/** Expirations within this many calendar days count as upcoming. Three days
 * spans a weekend; holidays are not assumed, so the date itself is shown. */
export const EXPIRY_WINDOW_DAYS = 3;
/** Fired price alerts stay listed this long after they fired. */
export const ALERT_WINDOW_MS = 24 * 3600 * 1000;

function addDays(day: string, days: number): string {
  const date = new Date(`${day}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

function shortDate(day: string): string {
  return `${Number(day.slice(5, 7))}/${Number(day.slice(8, 10))}`;
}

function money(value: number | null): string {
  return value == null ? "?" : `${value < 0 ? "-" : "+"}$${Math.abs(value).toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
}

function percent(value: number | null): string {
  return value == null ? "?" : `${value < 0 ? "" : "+"}${Math.round(value * 100)}%`;
}

function ago(now: number, at: number): string {
  const minutes = Math.max(0, Math.round((now - at) / 60000));
  if (minutes < 60) return `${Math.max(1, minutes)}m ago`;
  const hours = Math.round(minutes / 60);
  return hours < 24 ? `${hours}h ago` : `${Math.round(hours / 24)}d ago`;
}

function contract(row: OpenPositionRow): string {
  const { trade } = row;
  if (trade.instrument_type !== "option") return trade.ticker;
  const strike = trade.strike != null ? `${trade.strike}` : "?";
  const side = trade.option_type ? trade.option_type[0].toUpperCase() : "";
  return `${trade.ticker} ${strike}${side}${trade.expiration ? ` ${shortDate(trade.expiration)}` : ""}`;
}

function isPracticeSample(record: DecisionRecord): boolean {
  const packet = record.evidence?.packet as { sample_data?: boolean; replay_exercise?: boolean; historical_replay?: boolean } | undefined;
  return packet?.sample_data === true || packet?.replay_exercise === true || packet?.historical_replay === true;
}

/** A deterministic list of things worth a look. Descriptive only: it never
 * suggests a trade, and a source that failed is named rather than read as
 * "nothing to report". */
export function buildAttention(input: AttentionInputs): AttentionResult {
  const { rows, quotes, today, now } = input;
  const items: AttentionItem[] = [];
  const unavailable: string[] = [];
  const tradeHref = (id: string) => `/trades/${encodeURIComponent(id)}`;

  for (const row of rows) {
    const { trade, meta } = row;
    const expiration = trade.instrument_type === "option" ? trade.expiration?.slice(0, 10) ?? null : null;
    if (trade.instrument_type === "option" && !expiration) {
      items.push({ id: `no-expiry:${trade.id}`, priority: "integrity", title: `${trade.ticker} option has no expiration`,
        detail: "The record is open without an expiration date, so expiry checks cannot run for it.", when: "Record",
        href: tradeHref(trade.id), sortKey: "" });
    } else if (expiration && expiration < today) {
      items.push({ id: `expired-open:${trade.id}`, priority: "integrity", title: `${contract(row)} still open after expiry`,
        detail: `Expired ${shortDate(expiration)} but the journal still shows ${meta.qtyLeft} open. Check its fills; a rebuild may be needed.`,
        when: "Record", href: tradeHref(trade.id), sortKey: expiration });
    }
    // A failed quote request is already disclosed above the panel; listing
    // every position again would bury the rest of the list.
    const expired = expiration != null && expiration < today;
    if (!input.quoteError && !expired && getCurrentMark(trade, quotes[trade.id]) == null) {
      items.push({ id: `no-price:${trade.id}`, priority: "integrity", title: `${contract(row)} has no price`,
        detail: "No current mark, so its unrealized P&L is left out of the total.", when: "Now",
        href: tradeHref(trade.id), sortKey: trade.ticker });
    }
    if (meta.avgCostLeft == null || meta.direction === "unknown") {
      items.push({ id: `no-basis:${trade.id}`, priority: "integrity", title: `${contract(row)} has no cost basis`,
        detail: "Its fills do not add up to a remaining cost, so its P&L cannot be computed.", when: "Record",
        href: tradeHref(trade.id), sortKey: trade.ticker });
    }
    if (expiration && expiration >= today && expiration <= addDays(today, EXPIRY_WINDOW_DAYS)) {
      const isToday = expiration === today;
      items.push({ id: `expiring:${trade.id}`, priority: "soon", title: `${contract(row)} expires ${isToday ? "today" : shortDate(expiration)}`,
        detail: `${meta.qtyLeft} contract${meta.qtyLeft === 1 ? "" : "s"} open.`, when: isToday ? "Today" : shortDate(expiration),
        href: tradeHref(trade.id), sortKey: expiration });
    }
    // A give-back alert stays listed for the rest of its ET day while the position is open, so a dismissed push is not lost.
    const phone = input.phoneAlerts?.[trade.id];
    const giveback = phone?.filter((alert) => alert.kind === "giveback"
      && new Date(alert.detected_at * 1000).toLocaleDateString("en-CA", { timeZone: "America/New_York" }) === today)
      .sort((a, b) => b.detected_at - a.detected_at)[0];
    if (giveback) {
      items.push({ id: `giveback:${giveback.id}`, priority: "alert", title: `${contract(row)} gave back its gain`,
        detail: `Peak ${money(giveback.peak_gain)} (${percent(giveback.peak_gain_pct)}), ${money(giveback.gain)} (${percent(giveback.gain_pct)}) at the alert. ${meta.qtyLeft} open now.`,
        when: ago(now, giveback.detected_at * 1000), href: `${tradeHref(trade.id)}?alert=${encodeURIComponent(giveback.id)}`,
        sortKey: String(1e10 - giveback.detected_at).padStart(11, "0") });
    }
    if (expiration && expiration >= today) {
      const earnings = input.earnings[trade.ticker];
      const next = earnings?.state === "ready" ? earnings.next : null;
      if (next && next.date >= today && next.date <= expiration) {
        const sameDay = next.date === expiration;
        items.push({ id: `earnings:${trade.id}`, priority: "soon",
          title: `${trade.ticker} earnings ${shortDate(next.date)}, ${sameDay ? "on" : "before"} expiry`,
          detail: `${contract(row)} expires ${shortDate(expiration)}. Report date ${next.status}${sameDay ? "; time of day is not published" : ""} (${earnings!.source}).`,
          when: next.date === today ? "Today" : shortDate(next.date), href: `/charts?symbol=${encodeURIComponent(trade.ticker)}`, sortKey: next.date });
      }
    }
  }
  const earningsGaps = Object.entries(input.earnings).filter(([, value]) => value == null || value.state === "unavailable" || value.state === "loading").map(([symbol]) => symbol).sort();
  if (earningsGaps.length) unavailable.push(`Earnings dates for ${earningsGaps.join(", ")}`);
  const phoneGaps = rows.filter(({ trade }) => input.phoneAlerts?.[trade.id] === null).map(contract).sort();
  if (phoneGaps.length) unavailable.push(`Phone alerts for ${phoneGaps.join(", ")}`);

  const { gmail } = input;
  if (gmail == null) unavailable.push("Gmail import status");
  else if (gmail.status === "down" || gmail.status === "degraded") {
    items.push({ id: "gmail", priority: "data", title: gmail.status === "down" ? "New fills are not arriving" : "Fill import is degraded",
      detail: gmail.message, when: "Now", href: "/?sync=open", sortKey: gmail.status === "down" ? "0" : "1" });
  }

  if (input.jobs == null) unavailable.push("Sync job status");
  else for (const job of input.jobs) {
    if (job.status !== "failed") continue;
    const at = job.finished_at ?? job.updated_at ?? job.last_run_at;
    items.push({ id: `job:${job.job_type}`, priority: "data", title: `${job.label} failed`,
      detail: job.error_summary || job.message || "The last run ended with an error.", when: at ? ago(now, Date.parse(at)) : "Last run",
      // Newest failure first; Gmail ("0"/"1") still leads the data tier.
      href: "/?sync=open", sortKey: `2${String(1e13 - (at ? Date.parse(at) : 0)).padStart(14, "0")}` });
  }

  if (input.alerts == null) unavailable.push("Price alerts");
  else for (const alert of input.alerts) {
    const event = alert.event;
    if (alert.state !== "fired" || !event || now - event.event_at * 1000 > ALERT_WINDOW_MS || event.event_at * 1000 > now + 60000) continue;
    const verb = alert.condition === "closes_beyond" ? `closed ${alert.direction === "up" ? "above" : "below"}` : alert.condition === "crosses" ? "crossed" : "touched";
    items.push({ id: `alert:${alert.id}`, priority: "alert", title: `${alert.symbol} ${verb} ${event.level.toFixed(2)}`,
      detail: `${alert.label ? `${alert.label} · ` : ""}Fired at ${event.price.toFixed(2)}.`, when: ago(now, event.event_at * 1000),
      href: `/charts?symbol=${encodeURIComponent(alert.symbol)}`, // Newest first: a fixed-width countdown sorts as text in reverse time.
      sortKey: String(1e10 - event.event_at).padStart(11, "0") });
  }

  // A later human choice on the same opportunity supersedes the WAIT.
  const latestHuman = new Map<string, string>();
  for (const record of input.decisions) {
    if (record.actor !== "human") continue;
    const held = latestHuman.get(record.opportunity_id);
    if (held == null || record.received_at > held) latestHuman.set(record.opportunity_id, record.received_at);
  }
  for (const record of input.decisions) {
    if (latestHuman.get(record.opportunity_id) !== record.received_at) continue;
    if (record.decision !== "wait" || record.actor !== "human" || isPracticeSample(record) || !record.wait_expiry) continue;
    const ends = Date.parse(record.wait_expiry);
    if (!Number.isFinite(ends) || ends <= now) continue;
    const endsText = new Date(ends).toLocaleString("en-US", { timeZone: "America/New_York", month: "numeric", day: "numeric", hour: "numeric", minute: "2-digit" });
    items.push({ id: `wait:${record.id}`, priority: "follow_up", title: `${record.symbol} WAIT still open`,
      detail: `${record.wait_condition ?? "No condition saved."} · ends ${endsText} ET`, when: `Ends ${shortDate(new Date(ends).toLocaleDateString("en-CA", { timeZone: "America/New_York" }))}`,
      href: `/practice?decision=${encodeURIComponent(record.id)}#saved-decisions`, sortKey: record.wait_expiry });
  }

  // The same contract in two accounts raises the same item twice; one row says so instead. The row keeps the
  // lowest ID (and its link) whatever order the positions arrived in, so the list is stable.
  const merged = new Map<string, AttentionItem>();
  for (const item of items) {
    const key = `${item.priority}\u0000${item.title}\u0000${item.detail}\u0000${item.when}`;
    const held = merged.get(key);
    if (!held) { merged.set(key, item); continue; }
    held.count = (held.count ?? 1) + 1;
    if (item.id < held.id) { held.id = item.id; held.href = item.href; held.sortKey = item.sortKey; }
  }
  const list = [...merged.values()];
  list.sort((a, b) => ATTENTION_PRIORITY[a.priority] - ATTENTION_PRIORITY[b.priority]
    || a.sortKey.localeCompare(b.sortKey) || a.id.localeCompare(b.id));
  return { items: list, unavailable };
}
