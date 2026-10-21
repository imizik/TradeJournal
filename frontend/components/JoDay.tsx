"use client";
import { useCallback, useEffect, useState } from "react";
import { api, type ScannerCandidateRow, type ScannerDay } from "@/lib/api";
import { getPlans, refusalRule, refusalWords, type PlanState, type PlansView, type PlanView } from "@/lib/conditionalPlans";
import { getMorning, type MorningView } from "@/lib/joMorning";
import { getMarketReads, type MarketReadSession, type MarketReadText } from "@/lib/marketReads";

/** Read-only view of what Jo did, is watching and will do on one ET date, joined from the
 * existing briefing, market-read, price-watch and scanner records. It adds no data or jobs. */

const zone = "America/New_York";
const time = (value: string) => new Date(value).toLocaleTimeString("en-US", { timeZone: zone, hour: "numeric", minute: "2-digit" });
const slotTime = (slot: string) => { const [h, m] = slot.split(":").map(Number); return `${h % 12 || 12}:${String(m).padStart(2, "0")}`; };
const ok = "border-emerald-500/40 bg-emerald-500/10 text-emerald-300";
const warn = "border-amber-500/40 bg-amber-500/10 text-amber-200";
const muted = "border-border bg-secondary/40 text-muted-foreground";
const link = "text-sm text-primary hover:underline";
const ACTIVE: PlanState[] = ["pending_activation", "watching", "triggered"];

type Tone = string;
type Item = { key: string; at: string | null; label: string; sub?: string; icon: "done" | "warn" | "watch" | "next" | "skip"; badge?: [string, Tone]; detail?: React.ReactNode };
type Part = { text: string; tone?: "trouble" | "news" };
export type JoDayData = { morning: MorningView | null; reads: MarketReadSession | null; readsOff: "unavailable" | "watch_off" | null; plans: PlansView | null; scanner: ScannerDay | null; failed: string[] };

/** Loads the four existing Jo records for a date; each one can fail on its own without hiding the rest. */
export function useJoDay(day: string, live: boolean) {
  const [data, setData] = useState<JoDayData | null>(null);
  const [revision, setRevision] = useState(0);
  const refresh = useCallback(() => setRevision((r) => r + 1), []);
  useEffect(() => {
    const controller = new AbortController();
    Promise.allSettled([getMorning(day, null, controller.signal), getMarketReads(controller.signal, day), getPlans(controller.signal), api.scannerDay(day)])
      .then(([morning, reads, plans, scanner]) => {
        if (controller.signal.aborted) return;
        const value = <T,>(r: PromiseSettledResult<T>) => r.status === "fulfilled" ? r.value : null;
        const readsView = value(reads);
        setData({ morning: value(morning), reads: readsView?.sessions.find((s) => s.session_date === day) ?? null,
          readsOff: !readsView ? null : !readsView.reads_available ? "unavailable" : !readsView.market_watch_enabled ? "watch_off" : null,
          plans: value(plans), scanner: value(scanner),
          failed: [["the morning briefing", morning], ["market reads", reads], ["price watches", plans], ["scanner setups", scanner]]
            .filter(([, r]) => (r as PromiseSettledResult<unknown>).status === "rejected").map(([name]) => name as string) });
      });
    return () => controller.abort();
  }, [day, revision]);
  useEffect(() => {
    if (!live) return;
    const timer = window.setInterval(refresh, 60_000);
    return () => window.clearInterval(timer);
  }, [live, refresh]);
  return { data, refresh };
}

const plansFor = (data: JoDayData, day: string) => (data.plans?.plans ?? []).filter((p) => p.session_date === day);
const refusalsFor = (data: JoDayData, day: string) => (data.plans?.refusals ?? []).filter((r) => r.session_date === day);
const activePlan = (p: PlanView, checked: string) => ACTIVE.includes(p.state) && Date.parse(p.expires_at) > Date.parse(checked);

const etMinutes = (value: string) => { const [h, m] = new Date(value).toLocaleTimeString("en-GB", { timeZone: zone, hour: "2-digit", minute: "2-digit" }).split(":").map(Number); return h * 60 + m; };
/** Today, after the session's close by the server's clock: the day is a record, not a live screen. */
const afterClose = (data: JoDayData, live: boolean) => {
  const close = data.reads?.hours?.close, now = data.plans?.checked_at ?? data.morning?.checked_at;
  return live && close != null && !!now && etMinutes(now) >= close;
};
const finalEvents = ["triggered", "invalidated", "expired", "cancelled", "unavailable"] as PlanState[];

/** One plain sentence: the briefing, reads in, what went wrong, watch news and the next scheduled job. */
export function joHeadline(data: JoDayData, day: string, live: boolean): { text: string; trouble: boolean; parts: Part[] } {
  const parts: Part[] = [];
  const f = data.morning?.delivery?.fulfilment;
  if (f === "on_time") parts.push({ text: "Briefing on time" });
  else if (f === "late") parts.push({ text: "Briefing late", tone: "trouble" });
  else if (f === "missing") parts.push({ text: "Briefing missing", tone: "trouble" });
  else if (f === "pending") parts.push({ text: "Briefing not in yet" });
  else if (data.morning?.briefing) parts.push({ text: "Briefing saved" });
  const slots = data.reads?.slots.filter((s) => s.expected) ?? [];
  if (slots.length) {
    const due = slots.filter((s) => s.delivery !== "pending");
    const ongoing = live && !afterClose(data, live);
    parts.push({ text: `${slots.filter((s) => s.status === "read_seen").length} of ${ongoing ? slots.length : due.length} market reads in` });
    const missing = slots.filter((s) => s.delivery === "missing").length, late = slots.filter((s) => s.delivery === "late").length;
    if (missing) parts.push({ text: `${missing} missing`, tone: "trouble" });
    if (late) parts.push({ text: `${late} late`, tone: "trouble" });
  }
  const extra = data.reads?.reads_not_credited_to_a_slot.length ?? 0;
  if (extra) parts.push({ text: `${extra} extra ${extra === 1 ? "read" : "reads"}` });
  const watches = plansFor(data, day);
  const fired = watches.flatMap((p) => p.events.filter((e) => e.state === "triggered").map((e) => `${p.symbol} triggered ${time(e.occurred_at)}`));
  fired.forEach((text) => parts.push({ text, tone: "news" }));
  const quiet = watches.filter((p) => !p.events.some((e) => e.state === "triggered")).length;
  if (quiet) parts.push({ text: `${fired.length ? `${quiet} other` : quiet} price ${quiet === 1 ? "watch" : "watches"}` });
  if (watches.some((p) => p.state === "unavailable")) parts.push({ text: "a watch stopped", tone: "trouble" });
  const refused = refusalsFor(data, day).length;
  if (refused) parts.push({ text: `${refused} ${refused === 1 ? "watch" : "watches"} refused`, tone: "trouble" });
  const setups = data.scanner?.candidates.length ?? 0;
  // "No setups" only means something while the scanner was running.
  if (setups || data.scanner?.enabled) parts.push({ text: setups ? `${setups} ${setups === 1 ? "setup" : "setups"}` : "no setups" });
  if (!live && !joItems(data, day, live).done.length) return { text: "No Jo record for this day", trouble: false, parts: [{ text: "No Jo record for this day" }] };
  if (afterClose(data, live)) parts.push({ text: "market closed" });
  else if (live) {
    const next = data.reads?.slots.find((s) => s.expected && s.delivery === "pending" && !s.read);
    parts.push({ text: next ? `next: ${slotTime(next.slot)} market read` : "nothing else scheduled today" });
  }
  if (data.failed.length) parts.push({ text: "some records didn't load", tone: "trouble" });
  return { text: parts.map((p) => p.text).join(" · "), trouble: parts.some((p) => p.tone === "trouble"), parts };
}

const viewWord: Record<MarketReadText["view"], string> = { up: "Leaning up", down: "Leaning down", mixed: "Mixed", no_view: "No view" };

export function ReadText({ read }: { read: MarketReadText }) {
  return <div className="space-y-2 text-sm">
    <p><span className="text-muted-foreground">{viewWord[read.view]}{read.is_correction ? " · correction" : ""}: </span>{read.main_text}</p>
    <p><span className="text-muted-foreground">Other case: </span>{read.alternative_text}</p>
    <p><span className="text-muted-foreground">Wrong if: </span>{read.invalidation_text.replace(/^wrong if:?\s*/i, "")}</p>
    <p className="text-muted-foreground">What changed: {read.change_summary}</p>
  </div>;
}

/** The read's lean, plus the start of its main text so a row can be scanned without opening it. */
function readLabel(prefix: string, read: MarketReadText | null) {
  const label = read ? `${prefix} · ${viewWord[read.view].toLowerCase()}${read.is_correction ? " · correction" : ""}` : prefix;
  const text = read?.main_text.trim() ?? "";
  const cut = /\s/.test(text[120] ?? " ") ? text.slice(0, 120) : text.slice(0, 120).replace(/\s+\S*$/, "");
  return { label, sub: text ? (text.length > 120 ? `${cut.trimEnd()}…` : text) : undefined };
}

const minutesAfter = (later: string, earlier: string) => Math.round((Date.parse(later) - Date.parse(earlier)) / 60000);

function shadowBadge(c: ScannerCandidateRow): [string, Tone] {
  if (c.shadow.decision === "take") return ["Jo: TAKE", ok];
  if (c.shadow.decision === "skip") return ["Jo: SKIP", muted];
  const labels: Partial<Record<ScannerCandidateRow["shadow"]["status"], string>> = { awaiting_decision: "Waiting for Jo", no_response: "Jo didn't answer", late: "Jo answered late", not_published: "Not sent to Jo", no_contract: "No contract" };
  return [labels[c.shadow.status] ?? c.shadow.status, c.shadow.status === "no_response" || c.shadow.status === "late" ? warn : muted];
}

/** Splits the day's records into done, watching now and coming up. */
export function joItems(data: JoDayData, day: string, live: boolean) {
  const done: Item[] = [], watching: Item[] = [], next: Item[] = [];
  const m = data.morning, d = m?.delivery;
  if (d?.publication === "published" && d.published_at) {
    done.push({ key: "packet", at: d.published_at, icon: "done", label: "Morning data sent to Jo",
      badge: !m?.briefing && d.deadline ? [`Briefing due ${time(d.deadline)}`, muted] : undefined });
  }
  if (m?.briefing && !m.briefing.redacted_at) {
    const symbols = (m.briefing.body.items ?? []).map((i) => i.symbol).filter(Boolean) as string[];
    done.push({ key: "brief", at: d?.available_at ?? m.briefing.received_at, icon: d?.fulfilment === "late" ? "warn" : "done",
      label: `Morning briefing${symbols.length ? `: ${symbols.slice(0, 3).join(", ")}${symbols.length > 3 ? ` +${symbols.length - 3} more` : ""}` : ""}`,
      badge: d?.fulfilment === "on_time" ? [`On time${d.deadline ? ` · due ${time(d.deadline)}` : ""}`, ok]
        : d?.fulfilment === "late" ? [`Late${d.late_by_seconds ? ` by ${Math.round(d.late_by_seconds / 60)} min` : ""}`, warn] : undefined,
      detail: <div className="space-y-2 text-sm">
        {m.briefing.body.summary && <p>{m.briefing.body.summary}</p>}
        {(m.briefing.body.items ?? []).map((i, n) => <p key={n}><span className="font-medium">{i.symbol ?? "Market"}: </span>{i.what_matters}</p>)}
        <a className={link} href={`/morning?day=${day}`}>Full briefing with evidence →</a>
      </div> });
  } else if (d?.fulfilment === "missing") {
    done.push({ key: "brief", at: d.deadline, icon: "warn", label: "Morning briefing", badge: ["Missing", warn] });
  } else if (d?.fulfilment === "pending" && live) {
    next.push({ key: "brief", at: d.deadline, icon: "next", label: "Morning briefing", badge: [d.deadline ? `Due by ${time(d.deadline)}` : "Upcoming", muted] });
  }

  for (const s of data.reads?.slots ?? []) {
    if (s.expected === false) continue;
    if (s.received_at) {
      done.push({ key: `slot-${s.slot}`, at: s.received_at, icon: s.delivery === "late" ? "warn" : "done", ...readLabel(`${slotTime(s.slot)} read`, s.read),
        badge: s.delivery === "late" ? [`Late · ${minutesAfter(s.received_at, s.scheduled_at)} min after ${slotTime(s.slot)}`, warn] : s.packet.status === "published_partial" ? ["On time · data had gaps", warn] : ["On time", ok],
        detail: s.read ? <ReadText read={s.read} /> : <p className="text-sm text-muted-foreground">Jo&apos;s words for this read weren&apos;t saved in the app; only its timing is known.</p> });
    } else if (s.delivery === "pending" || s.status === "upcoming") {
      if (live) next.push({ key: `slot-${s.slot}`, at: s.scheduled_at, icon: "next", label: `${slotTime(s.slot)} market read`, badge: ["Upcoming", muted] });
    } else if (s.delivery === "missing") {
      done.push({ key: `slot-${s.slot}`, at: s.scheduled_at, icon: "warn", label: `${slotTime(s.slot)} read`, badge: ["Missing", warn],
        detail: <p className="text-sm text-muted-foreground">No read arrived by the deadline. The cause isn&apos;t visible to the app.</p> });
    } else if (s.delivery === "unknown" && s.expected) {
      done.push({ key: `slot-${s.slot}`, at: s.scheduled_at, icon: "warn", label: `${slotTime(s.slot)} read`, badge: ["Unknown", warn] });
    }
  }
  for (const r of data.reads?.reads_not_credited_to_a_slot ?? []) {
    done.push({ key: r.read_id, at: r.received_at, icon: "done", ...readLabel(`Extra read${r.event_wake_id ? " · answered a market alert" : ""}`, r.read),
      badge: ["Unscheduled", muted], detail: r.read ? <ReadText read={r.read} /> : undefined });
  }

  const checked = data.plans?.checked_at ?? new Date().toISOString();
  for (const p of plansFor(data, day)) {
    const label = `${p.symbol} ${p.direction} watch: ${p.confirm_bars} closes ${p.direction === "long" ? "above" : "below"} ${p.trigger_price}`;
    const detail = <div className="space-y-1 text-sm"><p>{p.rationale}</p>
      <p className="text-muted-foreground">Cancels on a close {p.direction === "long" ? "below" : "above"} {p.invalidation_price} · ends {time(p.expires_at)} · phone alert only, never an order</p></div>;
    done.push({ key: p.plan_id, at: p.created_at, icon: "watch", label: `Saved ${label}`, badge: ["Saved", muted], detail });
    // Each outcome is its own row, so a trigger stays in the record after the watch ends.
    for (const e of p.events.filter((ev) => finalEvents.includes(ev.state))) {
      const sent = p.deliveries.filter((x) => x.event_state === e.state).at(-1);
      const price = e.bar ? ` · close ${e.bar.close}` : "";
      const words: Record<string, string> = { triggered: `${p.symbol} watch triggered${price}`, invalidated: `${p.symbol} watch cancelled: closed ${p.direction === "long" ? "below" : "above"} ${p.invalidation_price}${price}`,
        expired: `${p.symbol} watch ended at its expiry`, cancelled: `${p.symbol} watch cancelled`, unavailable: `${p.symbol} watch stopped: monitoring failed` };
      done.push({ key: `${p.plan_id}-${e.state}`, at: e.occurred_at, icon: e.state === "unavailable" ? "warn" : e.state === "triggered" ? "watch" : "skip",
        label: words[e.state], sub: e.state === "triggered" ? "Alert only: no order was placed." : undefined,
        badge: sent ? (sent.outcome === "sent" ? ["Phone alert sent", e.state === "triggered" ? ok : muted] : sent.outcome === "failed" ? ["Phone alert failed", warn]
          : sent.outcome === "unknown" ? ["Phone alert may have sent", warn] : ["No phone alert", muted]) : e.state === "unavailable" ? ["Not watched", warn] : undefined });
    }
    if (live && !afterClose(data, live) && activePlan(p, checked)) {
      const trig = p.events.find((e) => e.state === "triggered");
      watching.push({ key: `w-${p.plan_id}`, at: null, icon: "watch", label: trig ? `${p.symbol} triggered ${time(trig.occurred_at)}: still checking for a close ${p.direction === "long" ? "below" : "above"} ${p.invalidation_price}` : label,
        badge: !p.monitoring ? ["Monitor not reporting", warn] : [`Until ${time(p.expires_at)}`, ok], detail });
    }
  }

  for (const r of refusalsFor(data, day)) {
    const rule = refusalRule(r);
    done.push({ key: r.refusal_id, at: r.created_at, icon: "warn", label: `Jo couldn't watch ${r.symbol ?? "a stock"}: ${refusalWords(r, data.plans?.max_daily_plans)}`,
      badge: ["Not saved", warn], detail: <div className="space-y-1 text-sm">
        {rule && <p>Jo asked for: {r.symbol ?? "a stock"} {rule}{r.expires_at ? ` · until ${time(r.expires_at)}` : ""}</p>}
        <p className="text-muted-foreground">Refused: {r.reason}. Nothing was saved or watched.</p></div> });
  }

  for (const c of data.scanner?.candidates ?? []) {
    done.push({ key: c.id, at: c.detected_at, icon: c.shadow.decision === "take" ? "done" : "skip", label: `Setup: ${c.symbol} ${c.setup === "orb" ? "opening-range breakout" : "fade"} ${c.direction}`,
      badge: shadowBadge(c), detail: c.shadow.reason ? <p className="text-sm">{c.shadow.reason}</p> : undefined });
  }
  if (live && !afterClose(data, live) && data.scanner?.enabled) {
    const mon = data.scanner.monitoring;
    watching.push({ key: "scanner", at: null, icon: "watch", label: `Setup scanner on ${mon.symbols_selected} stocks${mon.last_judged_bar_end ? ` · last bar ${time(mon.last_judged_bar_end)}` : ""}`,
      badge: mon.state === "fresh" ? ["Running", ok] : mon.state === "stale" || mon.state === "not_running" ? ["Not keeping up", warn] : ["Market closed", muted] });
  }
  if (live && !afterClose(data, live) && !plansFor(data, day).some((p) => activePlan(p, checked)) && data.plans?.enabled) {
    watching.push({ key: "no-watch", at: null, icon: "skip", label: "No active price watches", badge: [`${data.plans.plans_today ?? 0} of ${data.plans.max_daily_plans} used today`, muted] });
  }

  const byTime = (a: Item, b: Item) => Date.parse(a.at ?? "") - Date.parse(b.at ?? "");
  return { done: done.sort(byTime), watching, next: next.sort(byTime), closed: afterClose(data, live) };
}

type Alert = { key: string; at: string | null; about: string; outcome: [string, Tone] };
const pushOutcome: Record<"sent" | "failed" | "unknown" | "not_sent", [string, Tone]> = {
  sent: ["Sent to ntfy", ok], failed: ["Failed to send", warn], unknown: ["May have sent", warn], not_sent: ["Not sent", muted] };
const messageOutcome = (m: NonNullable<MarketReadSession["messages"]>[number]): [string, Tone] =>
  m.decision === "suppressed_budget" ? ["Held back: daily message limit", muted]
  : m.decision === "expired_before_send" ? ["Not sent: arrived too late", muted]
  : m.delivery === "accepted" ? pushOutcome.sent : m.delivery === "unknown" ? pushOutcome.unknown
  : m.delivery === "expired" ? ["Not sent: retries ran out", warn] : m.delivery === "failed_pending" ? ["Failed, retrying", warn] : ["Sending", muted];
const eventWord: Partial<Record<PlanState, string>> = { triggered: "triggered", invalidated: "cancelled by its stop level", expired: "ended", cancelled: "cancelled", unavailable: "stopped" };

/** Every phone push the app recorded for the day: price watches, Jo's flagged reads and the watchdog's notices. */
export function phoneAlerts(data: JoDayData, day: string) {
  const alerts: Alert[] = [];
  for (const p of plansFor(data, day)) {
    for (const d of p.deliveries) {
      alerts.push({ key: `${p.plan_id}-${d.event_state}-${d.attempt}-${d.occurred_at}`, at: d.occurred_at,
        about: `${p.symbol} price watch ${d.event_state ? eventWord[d.event_state] ?? d.event_state : "update"}`, outcome: pushOutcome[d.outcome] });
    }
  }
  const reads = data.reads;
  const readFor = (id: string) => {
    const slot = reads?.slots.find((s) => s.read_id === id);
    if (slot) return readLabel(`${slotTime(slot.slot)} read`, slot.read).label;
    const extra = reads?.reads_not_credited_to_a_slot.find((r) => r.read_id === id);
    return extra ? readLabel(`Extra read (${time(extra.received_at)})`, extra.read).label : "a market read";
  };
  for (const m of reads?.messages ?? []) {
    alerts.push({ key: m.message_id, at: m.settled_at ?? m.decided_at, about: `Jo's ${m.is_correction ? "correction" : "message"}: ${readFor(m.read_id)}`, outcome: messageOutcome(m) });
  }
  const notices = [...(data.morning?.delivery?.notifications.watchdog?.notices ?? []), ...(reads?.watchdog.notices ?? [])];
  notices.forEach((n, i) => alerts.push({ key: `watchdog-${i}-${n.at}`, at: n.at ?? null, about: `Watchdog: ${n.title}`, outcome: pushOutcome[n.outcome] ?? pushOutcome.unknown }));
  // Sources whose record couldn't be read: their pushes may exist but aren't shown.
  const unread = [!data.plans ? "price watches" : null, !reads || !data.reads?.messages ? "Jo's read messages" : null,
    !data.morning?.delivery?.notifications.watchdog || data.morning.delivery.notifications.watchdog.state === "unknown" || reads?.watchdog.state === "unknown" || !data.morning || !reads ? "the watchdog" : null]
    .filter(Boolean) as string[];
  return { alerts: alerts.sort((a, b) => Date.parse(a.at ?? "") - Date.parse(b.at ?? "")), unread };
}

function PhoneAlerts({ data, day, live }: { data: JoDayData; day: string; live: boolean }) {
  const { alerts, unread } = phoneAlerts(data, day);
  return <div data-testid="jo-phone-alerts">
    <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{live ? "Phone alerts today" : "Phone alerts"}</h3>
    {alerts.length ? <ul className="mt-1">{alerts.map((a) => <li key={a.key} className="border-t first:border-t-0" data-testid="jo-phone-alert">
      <div className="flex min-w-0 items-start gap-x-3 py-2 text-sm">
        <span className="w-[4.5rem] shrink-0 whitespace-nowrap tabular-nums text-muted-foreground">{a.at ? time(a.at) : "—"}</span>
        <span className="flex min-w-0 flex-1 flex-wrap items-center justify-between gap-x-3 gap-y-1">
          <span className="min-w-0 break-words">{a.about}</span>
          <span className={`whitespace-nowrap rounded-full border px-2 py-0.5 text-xs ${a.outcome[1]}`}>{a.outcome[0]}</span>
        </span>
      </div></li>)}</ul>
      : <p className="mt-1 py-2 text-sm text-muted-foreground">No phone alerts recorded{live ? " today" : " for this day"}.</p>}
    <p className="text-xs text-muted-foreground">&ldquo;Sent to ntfy&rdquo; means the push service accepted it; the app can&apos;t see whether your phone showed it.
      ChatGPT&apos;s own notifications aren&apos;t recorded here.{unread.length ? ` Couldn't read the record of ${unread.length > 1 ? `${unread.slice(0, -1).join(", ")} or ${unread.at(-1)}` : unread[0]}, so some pushes may be missing here.` : ""}</p>
  </div>;
}

const icons: Record<Item["icon"], [string, string]> = { done: ["✓", "text-emerald-400"], warn: ["!", "text-amber-300"], watch: ["◉", "text-sky-300"], next: ["○", "text-muted-foreground"], skip: ["–", "text-muted-foreground"] };

function Row({ item }: { item: Item }) {
  const [glyph, tone] = icons[item.icon];
  const head = <div className="flex min-w-0 items-start gap-x-3 py-2 text-sm">
    <span className="w-[4.5rem] shrink-0 whitespace-nowrap tabular-nums text-muted-foreground">{item.at ? time(item.at) : "now"}</span>
    <span aria-hidden="true" className={`w-3 shrink-0 text-center ${tone}`}>{glyph}</span>
    <span className="flex min-w-0 flex-1 flex-wrap items-center justify-between gap-x-3 gap-y-1">
      <span className="min-w-0 break-words">{item.label}{item.sub && <span className="block text-xs text-muted-foreground">{item.sub}</span>}</span>
      {item.badge && <span className={`whitespace-nowrap rounded-full border px-2 py-0.5 text-xs ${item.badge[1]}`}>{item.badge[0]}</span>}
    </span>
  </div>;
  return <li className="border-t first:border-t-0" data-testid="jo-day-item">
    {item.detail ? <details className="group"><summary className="min-h-11 cursor-pointer list-none [&::-webkit-details-marker]:hidden">{head}</summary>
      <div className="pb-3 pl-0 sm:pl-[6.75rem]">{item.detail}</div></details> : head}
  </li>;
}

function Group({ title, items, empty }: { title: string; items: Item[]; empty: string }) {
  return <div>
    <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{title}</h3>
    {items.length ? <ul className="mt-1">{items.map((i) => <Row key={i.key} item={i} />)}</ul> : <p className="mt-1 py-2 text-sm text-muted-foreground">{empty}</p>}
  </div>;
}

export default function JoDay({ day, live }: { day: string; live: boolean }) {
  const { data, refresh } = useJoDay(day, live);
  const headline = data ? joHeadline(data, day, live) : null;
  const items = data ? joItems(data, day, live) : null;
  return <section id="jo" className="scroll-mt-28 space-y-4 rounded-lg border bg-card p-5 md:scroll-mt-16" data-testid="jo-day">
    <div className="flex flex-wrap items-start justify-between gap-2">
      <div>
        <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">Jo&apos;s day</h2>
        {headline ? <p className="mt-1 text-base text-foreground" data-testid="jo-day-headline" data-trouble={headline.trouble}>
          {headline.parts.map((part, i) => <span key={i}>{i ? " · " : ""}<span className={part.tone === "trouble" ? "text-amber-200" : part.tone === "news" ? "text-sky-300" : undefined}>{part.text}</span></span>)}</p>
          : <p role="status" className="mt-1 text-sm text-muted-foreground">Loading Jo&apos;s records…</p>}
      </div>
      <button type="button" onClick={refresh} className="inline-flex min-h-11 items-center rounded-md border px-3 text-sm hover:bg-secondary">Refresh</button>
    </div>
    {data?.failed.length ? <p role="alert" className={`rounded-md border px-3 py-2 text-sm ${warn}`}>Couldn&apos;t load {data.failed.join(", ")}. What&apos;s shown may be incomplete.</p> : null}
    {data?.readsOff && <p className="text-xs text-muted-foreground" data-testid="jo-day-reads-note">{data.readsOff === "unavailable"
      ? "Market-read records aren't available on this server, so reads can't be shown."
      : "Market watch is off on this server, so no new reads will arrive; saved reads are shown."}</p>}
    {items && <>
      {(live || items.done.length > 0) && <Group title="Done" items={items.done} empty="Nothing from Jo yet today." />}
      {live && items.closed && <p className="text-sm text-muted-foreground">The market has closed; nothing is being watched and nothing else is scheduled today.</p>}
      {live && !items.closed && <Group title="Watching now" items={items.watching} empty="Nothing is being watched right now." />}
      {live && !items.closed && <Group title="Coming up" items={items.next} empty="Nothing else scheduled today." />}
    </>}
    {data && (live || items?.done.length) ? <PhoneAlerts data={data} day={day} live={live} /> : null}
    <p className="flex flex-wrap gap-x-4 gap-y-1">
      <a className={link} href={`/morning?day=${day}`}>Briefing →</a>
      <a className={link} href="/morning/market-reads">All market reads →</a>
      <a className={link} href="/morning/watches">Price watches →</a>
      <a className={link} href={`/scanner?day=${day}`}>Scanner for this day →</a>
    </p>
  </section>;
}
