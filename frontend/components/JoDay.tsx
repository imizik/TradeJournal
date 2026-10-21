"use client";
import { useCallback, useEffect, useState } from "react";
import { api, type ScannerCandidateRow, type ScannerDay } from "@/lib/api";
import { getPlans, type PlanState, type PlansView, type PlanView } from "@/lib/conditionalPlans";
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
type Item = { key: string; at: string | null; label: string; icon: "done" | "warn" | "watch" | "next" | "skip"; badge?: [string, Tone]; detail?: React.ReactNode };
export type JoDayData = { morning: MorningView | null; reads: MarketReadSession | null; readsOff: boolean; plans: PlansView | null; scanner: ScannerDay | null; failed: string[] };

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
          readsOff: !!readsView && (!readsView.market_watch_enabled || !readsView.reads_available),
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
const activePlan = (p: PlanView, checked: string) => ACTIVE.includes(p.state) && Date.parse(p.expires_at) > Date.parse(checked);

/** One plain sentence: the briefing, reads in, setups and the next scheduled job. */
export function joHeadline(data: JoDayData, day: string, live: boolean): { text: string; trouble: boolean } {
  const parts: string[] = [];
  let trouble = data.failed.length > 0;
  const f = data.morning?.delivery?.fulfilment;
  if (f === "on_time") parts.push("Briefing on time");
  else if (f === "late") { parts.push("Briefing late"); trouble = true; }
  else if (f === "missing") { parts.push("Briefing missing"); trouble = true; }
  else if (f === "pending") parts.push("Briefing not in yet");
  else if (data.morning?.briefing) parts.push("Briefing saved");
  const slots = data.reads?.slots.filter((s) => s.expected) ?? [];
  if (slots.length) {
    const due = slots.filter((s) => s.delivery !== "pending");
    const inCount = slots.filter((s) => s.status === "read_seen").length;
    parts.push(`${inCount} of ${live ? slots.length : due.length} market reads in`);
    if (slots.some((s) => s.delivery === "missing" || s.delivery === "late")) trouble = true;
  }
  const extra = data.reads?.reads_not_credited_to_a_slot.length ?? 0;
  if (extra) parts.push(`${extra} extra ${extra === 1 ? "read" : "reads"}`);
  const watches = plansFor(data, day);
  if (watches.length) parts.push(`${watches.length} price ${watches.length === 1 ? "watch" : "watches"}`);
  const setups = data.scanner?.candidates.length ?? 0;
  parts.push(setups ? `${setups} ${setups === 1 ? "setup" : "setups"}` : "no setups");
  if (live) {
    const next = data.reads?.slots.find((s) => s.expected && s.delivery === "pending" && !s.read);
    parts.push(next ? `next: ${slotTime(next.slot)} market read` : "nothing else scheduled today");
  }
  return { text: parts.join(" · "), trouble };
}

const viewWord: Record<MarketReadText["view"], string> = { up: "Leaning up", down: "Leaning down", mixed: "Mixed", no_view: "No view" };

function ReadText({ read }: { read: MarketReadText }) {
  return <div className="space-y-2 text-sm">
    <p><span className="text-muted-foreground">{viewWord[read.view]}{read.is_correction ? " · correction" : ""}: </span>{read.main_text}</p>
    <p><span className="text-muted-foreground">Other case: </span>{read.alternative_text}</p>
    <p><span className="text-muted-foreground">Wrong if: </span>{read.invalidation_text}</p>
    <p className="text-muted-foreground">What changed: {read.change_summary}</p>
  </div>;
}

function readBadge(read: MarketReadText | null): string {
  if (!read) return "Market read";
  return `Market read · ${viewWord[read.view].toLowerCase()}${read.is_correction ? " · correction" : ""}`;
}

const planStates: Record<PlanState, string> = { pending_activation: "saved, not monitored yet", watching: "watching", triggered: "triggered (not entered)",
  invalidated: "cancelled by its invalidation price", expired: "expired", cancelled: "cancelled", unavailable: "monitoring failed" };

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
      done.push({ key: `slot-${s.slot}`, at: s.received_at, icon: s.delivery === "late" ? "warn" : "done", label: `Scheduled ${readBadge(s.read).toLowerCase()}${s.delivery === "late" ? ` (${slotTime(s.slot)} slot)` : ""}`,
        badge: s.delivery === "late" ? [`Late · ${Math.round((s.late_by_seconds ?? 0) / 60)} min past due`, warn] : s.packet.status === "published_partial" ? ["Data had gaps", warn] : ["On time", ok],
        detail: s.read ? <ReadText read={s.read} /> : <p className="text-sm text-muted-foreground">Jo&apos;s words for this read weren&apos;t saved in the app; only its timing is known.</p> });
    } else if (s.delivery === "pending" || s.status === "upcoming") {
      if (live) next.push({ key: `slot-${s.slot}`, at: s.scheduled_at, icon: "next", label: "Market read", badge: ["Upcoming", muted] });
    } else if (s.delivery === "missing") {
      done.push({ key: `slot-${s.slot}`, at: s.scheduled_at, icon: "warn", label: `${slotTime(s.slot)} market read`, badge: ["Missing", warn],
        detail: <p className="text-sm text-muted-foreground">No read arrived by the deadline. The cause isn&apos;t visible to the app.</p> });
    } else if (s.delivery === "unknown" && s.expected) {
      done.push({ key: `slot-${s.slot}`, at: s.scheduled_at, icon: "warn", label: `${slotTime(s.slot)} market read`, badge: ["Unknown", warn] });
    }
  }
  for (const r of data.reads?.reads_not_credited_to_a_slot ?? []) {
    done.push({ key: r.read_id, at: r.received_at, icon: "done", label: `Extra ${readBadge(r.read).toLowerCase()}${r.event_wake_id ? " · answered a market alert" : ""}`,
      badge: ["Unscheduled", muted], detail: r.read ? <ReadText read={r.read} /> : undefined });
  }

  const checked = data.plans?.checked_at ?? new Date().toISOString();
  for (const p of plansFor(data, day)) {
    const label = `${p.symbol} ${p.direction} watch: ${p.confirm_bars} closes ${p.direction === "long" ? "above" : "below"} ${p.trigger_price}`;
    const detail = <div className="space-y-1 text-sm"><p>{p.rationale}</p>
      <p className="text-muted-foreground">Cancels on a close {p.direction === "long" ? "below" : "above"} {p.invalidation_price} · ends {time(p.expires_at)} · phone alert only, never an order</p></div>;
    done.push({ key: p.plan_id, at: p.created_at, icon: "watch", label: `Saved ${label}`, badge: [planStates[p.state], ACTIVE.includes(p.state) ? ok : muted], detail });
    if (live && activePlan(p, checked)) watching.push({ key: `w-${p.plan_id}`, at: null, icon: "watch", label, badge: [p.monitoring ? `Watching until ${time(p.expires_at)}` : "Monitor not reporting", p.monitoring ? ok : warn], detail });
  }

  for (const c of data.scanner?.candidates ?? []) {
    done.push({ key: c.id, at: c.detected_at, icon: c.shadow.decision === "take" ? "done" : "skip", label: `Setup: ${c.symbol} ${c.setup === "orb" ? "opening-range breakout" : "fade"} ${c.direction}`,
      badge: shadowBadge(c), detail: c.shadow.reason ? <p className="text-sm">{c.shadow.reason}</p> : undefined });
  }
  if (live && data.scanner?.enabled) {
    const mon = data.scanner.monitoring;
    watching.push({ key: "scanner", at: null, icon: "watch", label: `Setup scanner on ${mon.symbols_selected} stocks${mon.last_judged_bar_end ? ` · last bar ${time(mon.last_judged_bar_end)}` : ""}`,
      badge: mon.state === "fresh" ? ["Running", ok] : mon.state === "stale" || mon.state === "not_running" ? ["Not keeping up", warn] : ["Market closed", muted] });
  }
  if (live && !plansFor(data, day).some((p) => activePlan(p, checked)) && data.plans?.enabled) {
    watching.push({ key: "no-watch", at: null, icon: "skip", label: "No active price watches", badge: [`${data.plans.plans_today ?? 0} of ${data.plans.max_daily_plans} used today`, muted] });
  }

  const byTime = (a: Item, b: Item) => Date.parse(a.at ?? "") - Date.parse(b.at ?? "");
  return { done: done.sort(byTime), watching, next: next.sort(byTime) };
}

const icons: Record<Item["icon"], [string, string]> = { done: ["✓", "text-emerald-400"], warn: ["!", "text-amber-300"], watch: ["◉", "text-sky-300"], next: ["○", "text-muted-foreground"], skip: ["–", "text-muted-foreground"] };

function Row({ item }: { item: Item }) {
  const [glyph, tone] = icons[item.icon];
  const head = <div className="flex min-w-0 items-start gap-x-3 py-2 text-sm">
    <span className="w-[4.5rem] shrink-0 whitespace-nowrap tabular-nums text-muted-foreground">{item.at ? time(item.at) : "now"}</span>
    <span aria-hidden="true" className={`w-3 shrink-0 text-center ${tone}`}>{glyph}</span>
    <span className="flex min-w-0 flex-1 flex-wrap items-center justify-between gap-x-3 gap-y-1">
      <span className="min-w-0 break-words">{item.label}</span>
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
        {headline ? <p className={`mt-1 text-base ${headline.trouble ? "text-amber-200" : "text-foreground"}`} data-testid="jo-day-headline">{headline.text}</p>
          : <p role="status" className="mt-1 text-sm text-muted-foreground">Loading Jo&apos;s records…</p>}
      </div>
      <button type="button" onClick={refresh} className="inline-flex min-h-11 items-center rounded-md border px-3 text-sm hover:bg-secondary">Refresh</button>
    </div>
    {data?.failed.length ? <p role="alert" className={`rounded-md border px-3 py-2 text-sm ${warn}`}>Couldn&apos;t load {data.failed.join(", ")}. What&apos;s shown may be incomplete.</p> : null}
    {data?.readsOff && <p className="text-xs text-muted-foreground">Market-read records aren&apos;t available on this server, so reads can&apos;t be shown.</p>}
    {items && <>
      <Group title="Done" items={items.done} empty={live ? "Nothing from Jo yet today." : "No Jo activity recorded for this day."} />
      {live && <Group title="Watching now" items={items.watching} empty="Nothing is being watched right now." />}
      {live && <Group title="Coming up" items={items.next} empty="Nothing else scheduled today." />}
    </>}
    <p className="flex flex-wrap gap-x-4 gap-y-1">
      <a className={link} href={`/morning?day=${day}`}>Briefing →</a>
      <a className={link} href="/morning/market-reads">All market reads →</a>
      <a className={link} href="/morning/watches">Price watches →</a>
      <a className={link} href={`/scanner?day=${day}`}>Scanner for this day →</a>
    </p>
  </section>;
}
