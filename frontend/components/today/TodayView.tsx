"use client";

import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";
import { ChevronRight } from "lucide-react";
import PlanATrade, { PLAN_BUTTON } from "@/components/copilot/PlanATrade";
import { useCopilotOn } from "@/components/copilot/useCopilotOn";
import { REVIEW_WEEK } from "@/components/PlanStreak";
import { pnlTone } from "@/components/dashboard/DashboardCard";
import { apiUrl } from "@/lib/api";
import { copilotLabHref } from "@/lib/copilot";
import { money } from "@/lib/format";
import { cn } from "@/lib/utils";
import WatchDayLink from "@/components/replay/WatchDayLink";

// GET /today (backend/app/routers/today.py): every section is built on its own; a failed one reads { state: "unavailable" }.
type Unavailable = { state: "unavailable" };
type Reason = { kind: string; text: string };
type ActRow = { trade_id: string; symbol: string; contract: string; quantity: number; unrealized_usd: number | null; unrealized_pct: number | null; reasons: Reason[] };
type PlanRow = { symbol: string; direction: string | null; thesis: string | null; last: number | null; trigger: "entry" | "invalidation"; price: number; distance_pct: number; position: string; path: string };
type RadarRow = { event_id: string; symbol: string; kind: string | null; direction: string | null; summary: string | null; first_seen_at: string | null; path: string };
type ThesisRow = { symbol: string; kind: string; text: string; fired_at: string | null; delivery: string; path: string };
type Prep = { lines: string[]; fallback: boolean; delivery: string; at: string | null; path: string | null };
type HeldRow = { kind: string; decision: string; symbol: string | null; title: string; body: string; reason: string | null; at: string | null };
export type Today = {
  as_of: string; day: string; quotes_at: number | null; quote_issue: string | null;
  act_now: { state: "ok"; rows: ActRow[]; open_positions: number } | Unavailable;
  plans: { state: "ok"; rows: PlanRow[]; armed: number } | Unavailable;
  new: {
    radar: { state: "ok" | "off"; rows: RadarRow[]; count: number; reason?: string | null } | Unavailable;
    thesis: { state: "ok"; rows: ThesisRow[]; count: number } | Unavailable;
    prep: { state: "ok"; prep: Prep | null } | Unavailable;
  };
  held: { state: "ok"; rows: HeldRow[]; count: number } | Unavailable;
  week: { state: "ok"; show: boolean; current: number; best: number; pending: number; planned: number; total: number; week_pending: number } | Unavailable;
};

const REFRESH_MS = 60_000;
const HELD: Record<string, string> = { merged: "Merged", suppressed: "Quiet window", over_cap: "Over the daily cap" };
const clock = (iso: string | null) => iso ? new Date(iso).toLocaleTimeString("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit" }) : "";
const ok = <T extends { state: string }>(section: T | Unavailable): section is T => section.state !== "unavailable";

const ROW = "flex min-h-11 min-w-0 items-center gap-2 rounded border bg-background/40 px-3 py-2";
const LINK_ROW = `${ROW} hover:bg-muted/30`;

/** A link row while it has somewhere to go, else the same row without a link (a copilot link while the lab is off). */
function Row({ href, label, children, testId }: { href: string | null; label?: string; children: ReactNode; testId: string }) {
  return <li data-testid={testId} className="min-w-0">
    {href
      ? <Link href={href} aria-label={label} className={LINK_ROW}><div className="min-w-0 flex-1">{children}</div><ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden /></Link>
      : <div className={ROW}><div className="min-w-0 flex-1">{children}</div></div>}
  </li>;
}

/** One section: a heading with its count. Empty, it is just that line; failed, it says so and the rest stand. */
function Section({ title, count, unavailable = false, note, children, tone, alert }: {
  title: string; count: number; unavailable?: boolean; note?: ReactNode; children?: ReactNode; tone?: string; alert?: ReactNode;
}) {
  const empty = !unavailable && count === 0;
  return <section aria-label={title} data-testid="today-section" data-empty={empty || undefined} className={cn("min-w-0 rounded-lg border bg-card", empty && "bg-card/50")}>
    <h2 className={cn("flex items-baseline gap-2 px-4 text-sm font-semibold", empty ? "py-2.5 text-muted-foreground" : "py-3")}>
      <span>{title}</span>
      {!unavailable && <span className={cn("tabular-nums", !empty && tone)} data-testid="today-count">{count}</span>}
      {note && <span className="ml-auto text-xs font-normal text-muted-foreground">{note}</span>}
    </h2>
    {unavailable
      ? <p role="status" className="px-4 pb-3 text-sm text-amber-300">Could not read this right now.</p>
      : !empty && children && <div className="px-4 pb-4">{children}</div>}
    {/* A part that failed says so even when the rest of the section is empty. */}
    {!unavailable && alert && <div className="px-4 pb-3">{alert}</div>}
  </section>;
}

function ActNow({ section, lab }: { section: Today["act_now"]; lab: boolean }) {
  if (!ok(section)) return <Section title="Act now" count={0} unavailable />;
  return <Section title="Act now" count={section.rows.length} tone="text-amber-300"
    note={section.open_positions ? `${section.open_positions} open` : undefined}>
    <ul className="grid gap-2">{section.rows.map(row => (
      <Row key={row.trade_id} testId="today-act-row" label={`Review ${row.contract}`}
        href={lab ? copilotLabHref(row.symbol, `Review this position: ${row.trade_id}`) : `/trades/${row.trade_id}`}>
        <div className="flex min-w-0 items-baseline gap-2">
          <span className="min-w-0 break-words text-sm font-medium">{row.quantity > 1 ? `${row.quantity}× ` : ""}{row.contract}</span>
          <span className={`ml-auto shrink-0 text-sm tabular-nums ${pnlTone(row.unrealized_usd)}`}>
            {money(row.unrealized_usd, { signed: true, cents: false })}{row.unrealized_pct != null && ` · ${row.unrealized_pct > 0 ? "+" : ""}${row.unrealized_pct.toFixed(0)}%`}
          </span>
        </div>
        <div className="mt-0.5 flex flex-wrap gap-x-2 text-xs tabular-nums text-amber-300">{row.reasons.map(r => <span key={r.kind}>{r.text}</span>)}</div>
      </Row>))}
    </ul>
  </Section>;
}

function Plans({ section, lab }: { section: Today["plans"]; lab: boolean }) {
  if (!ok(section)) return <Section title="Plans near a trigger" count={0} unavailable />;
  return <Section title="Plans near a trigger" count={section.rows.length} tone="text-sky-300"
    note={section.armed ? `${section.armed} armed` : undefined}>
    <ul className="grid gap-2">{section.rows.map(row => (
      <Row key={row.path} testId="today-plan-row" label={`Open the ${row.symbol} plan`} href={lab ? row.path : null}>
        <div className="flex min-w-0 items-baseline gap-2">
          <span className="text-sm font-medium">{row.symbol}</span>
          <span className="ml-auto shrink-0 text-xs tabular-nums">
            {row.trigger === "entry" ? "Entry" : "Invalidation"} {row.price.toFixed(2)} · {Math.abs(row.distance_pct).toFixed(1)}% away
          </span>
        </div>
        {row.thesis && <p className="mt-0.5 truncate text-xs text-muted-foreground">{row.thesis}</p>}
      </Row>))}
    </ul>
  </Section>;
}

function NewSince({ section, lab }: { section: Today["new"]; lab: boolean }) {
  const radar = ok(section.radar) ? section.radar : null;
  const thesis = ok(section.thesis) ? section.thesis : null;
  const prep = ok(section.prep) ? section.prep.prep : null;
  const count = (radar?.count ?? 0) + (thesis?.count ?? 0) + (prep ? 1 : 0);
  const failed = [!radar && "Radar", !thesis && "thesis watch", !ok(section.prep) && "pre-market prep"].filter(Boolean);
  const note = radar?.state === "off" ? "Radar off" : undefined;
  const alert = failed.length > 0 && <p role="status" className="text-xs text-amber-300">Could not read {failed.join(", ")} right now.</p>;
  return <Section title="New since you looked" count={count} note={note} alert={alert}>
    <ul className="grid gap-2">
      {prep && <Row testId="today-prep-row" label="Open today's pre-market prep" href={lab ? prep.path : null}>
        <p className="text-xs font-medium text-muted-foreground">Pre-market prep{prep.fallback ? " · raw facts" : ""} {clock(prep.at)}</p>
        {prep.lines.length ? prep.lines.map((line, i) => <p key={i} className="break-words text-sm">{line}</p>)
          : <p className="text-sm text-muted-foreground">Preparing…</p>}
      </Row>}
      {thesis?.rows.map((row, i) => (
        <Row key={`t${i}`} testId="today-thesis-row" label={`Re-check the ${row.symbol} thesis`} href={lab ? row.path : null}>
          <p className="text-xs text-muted-foreground"><span className="font-medium text-foreground">{row.symbol}</span> · thesis {row.kind} · {clock(row.fired_at)}</p>
          <p className="break-words text-sm">{row.text}</p>
        </Row>))}
      {radar?.rows.map(row => (
        <Row key={row.event_id} testId="today-radar-row" label={`Open the ${row.symbol} Radar event`} href={row.path}>
          <p className="text-xs text-muted-foreground"><span className="font-medium text-foreground">{row.symbol}</span> · Radar · {clock(row.first_seen_at)}</p>
          <p className="break-words text-sm">{row.summary}</p>
        </Row>))}
    </ul>
  </Section>;
}

function Held({ section }: { section: Today["held"] }) {
  if (!ok(section)) return <Section title="Held back" count={0} unavailable />;
  return <Section title="Held back" count={section.count}>
    <ul className="grid gap-2">{section.rows.map((row, i) => (
      <li key={i} data-testid="today-held-row" className="min-h-11 min-w-0 rounded border bg-background/40 px-3 py-2">
        <p className="text-xs text-muted-foreground">{HELD[row.decision] ?? row.decision} · {row.kind} · {clock(row.at)}</p>
        <p className="break-words text-sm font-medium">{row.title}</p>
        <p className="line-clamp-3 whitespace-pre-line break-words text-xs text-muted-foreground">{row.body}</p>
      </li>))}
    </ul>
  </Section>;
}

function Week({ section, lab }: { section: Today["week"]; lab: boolean }) {
  if (!ok(section)) return <Section title="Your week so far" count={0} unavailable />;
  const body = <div data-testid="today-week" className="flex flex-wrap items-baseline gap-x-4 gap-y-1 text-sm tabular-nums">
    <span><span className="font-semibold">{section.planned}</span> of {section.total} entries planned</span>
    <span className="text-muted-foreground">Streak {section.current} · best {section.best}</span>
    {section.week_pending > 0 && <span className="text-muted-foreground">{section.week_pending} pending</span>}
  </div>;
  return <section aria-label="Your week so far" data-testid="today-section" className="min-w-0 rounded-lg border bg-card">
    <h2 className="px-4 py-3 text-sm font-semibold">Your week so far</h2>
    <div className="px-4 pb-4">{lab ? <Link href={REVIEW_WEEK} aria-label="Review my week" className="block min-h-11 rounded py-2 hover:bg-muted/30">{body}</Link> : body}</div>
  </section>;
}

/**
 * The owner's Today screen: what matters right now, top to bottom, each row one tap from acting on it. Refreshed every
 * minute while the page is visible. While the Copilot Lab is off the page still reads, and copilot links are left out.
 */
export default function TodayView() {
  const lab = useCopilotOn();
  const [body, setBody] = useState<Today | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let controller = new AbortController();
    const read = () => {
      controller.abort();
      controller = new AbortController();
      const signal = controller.signal;
      fetch(apiUrl("/today"), { cache: "no-store", signal })
        .then(r => r.ok ? r.json() : Promise.reject(new Error(`Request failed (${r.status}).`)))
        .then((next: Today) => { setBody(next); setError(null); })
        .catch(failure => { if (!signal.aborted) setError(failure instanceof Error ? failure.message : "Today is unavailable."); });
    };
    read();
    const timer = setInterval(() => { if (document.visibilityState === "visible") read(); }, REFRESH_MS);
    const shown = () => { if (document.visibilityState === "visible") read(); };
    document.addEventListener("visibilitychange", shown);
    return () => { controller.abort(); clearInterval(timer); document.removeEventListener("visibilitychange", shown); };
  }, []);

  return <div className="mx-auto max-w-2xl space-y-3" data-testid="today">
    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
      <h1 className="text-lg font-semibold text-foreground">Today</h1>
      {body && <p className="text-xs text-muted-foreground" data-testid="today-as-of">As of {clock(body.as_of)} ET</p>}
      {body && error && <p className="text-xs text-amber-300">Not refreshed</p>}
      {body?.quote_issue && <p className="text-xs text-amber-300">Prices: {body.quote_issue}</p>}
      {body && <WatchDayLink from={body.day} className="ml-auto inline-flex h-9 items-center gap-1.5 self-center rounded-md border px-3 text-sm font-medium hover:bg-muted/30" />}
    </div>
    {error && !body ? <p role="status" className="text-sm text-amber-300">Today could not load: {error}</p>
      : !body ? <p role="status" className="text-sm text-muted-foreground">Reading what matters now…</p>
      : <>
        <ActNow section={body.act_now} lab={lab} />
        <Plans section={body.plans} lab={lab} />
        <NewSince section={body.new} lab={lab} />
        <Held section={body.held} />
        <Week section={body.week} lab={lab} />
        {lab && <div className="grid grid-cols-2 gap-2 pt-1">
          <PlanATrade className={`${PLAN_BUTTON} h-11 text-sm`} />
          <Link href={REVIEW_WEEK} className="inline-flex h-11 items-center justify-center rounded-md border px-3 text-sm font-medium hover:bg-muted/30">Review my week</Link>
        </div>}
      </>}
  </div>;
}
