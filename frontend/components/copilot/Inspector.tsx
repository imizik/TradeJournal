"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import Link from "next/link";
import { REVIEW_WEEK, usePlanStreak, type PlanStreakEntry } from "@/components/PlanStreak";
import {
  DESK_MARKET, DESK_TIMEFRAMES, getDeskHistory, getDeskPicture, getDeskSession, getDeskTimeline,
  type ContextTab, type DeskHistory, type DeskTimeframe, type DeskSession, type DeskSessionEvent, type DeskThreadRef, type DeskTimeline, type DeskTimelineRow,
} from "@/lib/desk";
import { cn } from "@/lib/utils";

const NY = "America/New_York";
const nyDay = (seconds: number) => new Date(seconds * 1000).toLocaleDateString("en-US", { timeZone: NY });
/** Today's rows by the New York clock, earlier ones by their day. */
const when = (seconds: number) => nyDay(seconds) === nyDay(Date.now() / 1000)
  ? new Date(seconds * 1000).toLocaleTimeString("en-US", { timeZone: NY, hour: "2-digit", minute: "2-digit", hourCycle: "h23" })
  : new Date(seconds * 1000).toLocaleDateString("en-US", { timeZone: NY, month: "short", day: "numeric" });

const KIND: Record<DeskTimelineRow["kind"], { label: string; dot: string }> = {
  alert: { label: "Alert", dot: "bg-primary" },
  time_stop: { label: "Time stop", dot: "bg-primary/50" },
  revisit: { label: "Revisit", dot: "bg-muted-foreground" },
  fill: { label: "Fill", dot: "bg-foreground" },
  thesis: { label: "Thesis watch", dot: "bg-sky-400" },
  ping: { label: "Ping", dot: "bg-violet-400" },
  decision: { label: "Decision", dot: "bg-emerald-400" },
};
const TABS: { id: ContextTab; label: string }[] = [{ id: "chart", label: "Chart" }, { id: "timeline", label: "Timeline" }, { id: "history", label: "Your history" }];
const MAX_TILES = 40;
type DayTab = "chart" | "timeline" | "week";
const DAY_TABS: { id: DayTab; label: string }[] = [{ id: "chart", label: "Chart" }, { id: "timeline", label: "Timeline" }, { id: "week", label: "This week" }];
// The market picture draws fills amber and pings violet (desk_context.market_picture); the day's timeline keeps those.
const DAY_DOT: Record<DeskSessionEvent["kind"], string> = { fill: "bg-primary", ping: "bg-violet-400", radar: "bg-sky-400", decision: "bg-emerald-400" };
const DAY_SOURCES: Record<string, string> = { fills: "fills", pings: "pings", radar: "Radar", decisions: "decisions", time_stops: "time stops", prep: "prep" };
const REFRESH_MS = 60_000;
// This week's tiles: planned before entry, not (no plan, or one saved late), or a suggested plan waiting to be linked.
const WEEK_TILE: Record<PlanStreakEntry["state"], { mark: string; label: string; tone: string }> = {
  planned: { mark: "+", label: "planned", tone: "bg-emerald-400/15 text-emerald-300" },
  late: { mark: "−", label: "plan saved late", tone: "bg-rose-400/15 text-rose-300" },
  unplanned: { mark: "−", label: "no plan", tone: "bg-rose-400/15 text-rose-300" },
  pending: { mark: "·", label: "waiting to be linked", tone: "bg-muted text-muted-foreground" },
};
/** ``Tue 10:31`` by the New York clock. */
const weekClock = (seconds: number) => new Date(seconds * 1000).toLocaleString("en-US",
  { timeZone: NY, weekday: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).replace(",", "");

const Quiet = ({ children }: { children: ReactNode }) => <p className="text-sm text-muted-foreground">{children}</p>;
const failed = (failure: unknown) => failure instanceof Error ? failure.message : "Unavailable right now.";

/** The server's picture (ping-picture renderer) of the thread's symbol, or the market's, on ``timeframe`` (today's
 * minutes when none). The last picture stays up while a newer one is read. */
function ChartTab({ id, refreshKey, alt, timeframe }: { id: string; refreshKey: number; alt: string; timeframe?: DeskTimeframe }) {
  const [shown, setShown] = useState<{ url: string } | { reason: string } | null>(null);
  const current = useRef<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    getDeskPicture(id, controller.signal, timeframe).then(result => {
      if (controller.signal.aborted) {
        if ("url" in result) URL.revokeObjectURL(result.url);
        return;
      }
      if (current.current) URL.revokeObjectURL(current.current);
      current.current = "url" in result ? result.url : null;
      setShown(result);
    }).catch(failure => { if (!controller.signal.aborted) setShown({ reason: failed(failure) }); });
    return () => controller.abort();
  }, [id, refreshKey, timeframe]);
  useEffect(() => () => { if (current.current) URL.revokeObjectURL(current.current); }, []);
  if (!shown) return <Quiet>Reading today&apos;s chart…</Quiet>;
  if ("reason" in shown) return <Quiet>Chart unavailable: {shown.reason}</Quiet>;
  return (
    // An object URL of the server's PNG: next/image has nothing to optimise here.
    // eslint-disable-next-line @next/next/no-img-element
    <img src={shown.url} width={720} height={360} className="h-auto w-full rounded border" alt={alt} />
  );
}

const Dot = ({ tone, children }: { tone: string; children: ReactNode }) => (
  <span><span aria-hidden className={cn("mr-1 inline-block h-1.5 w-1.5 rounded-full align-middle", tone)} />{children}</span>
);
const SPAN: Record<DeskTimeframe, string> = { "2m": "today: minute bars", "15m": "recent sessions: 15-minute bars", "1D": "the last few months: daily bars" };

/** The thread's chart on 2m (today), 15m (recent sessions) or 1D (a few months), and what its dots are: the owner's
 * fills, the phone pings sent and Radar hits on the symbol today, so an alert can be judged against what price did
 * next. The dots and the plan's lines show on the intraday views. */
function ThreadChart({ thread }: { thread: DeskThreadRef }) {
  const [timeframe, setTimeframe] = useState<DeskTimeframe>("2m");
  return (
    <div className="space-y-2">
      <div role="group" aria-label="Timeframe" className="flex gap-1">
        {DESK_TIMEFRAMES.map(item => (
          <button key={item} type="button" aria-pressed={timeframe === item} onClick={() => setTimeframe(item)}
            className={cn("min-h-9 rounded border px-2 text-xs tabular-nums sm:min-h-0 sm:py-0.5",
              timeframe === item ? "border-primary text-foreground" : "border-transparent text-muted-foreground hover:text-foreground")}>
            {item}
          </button>
        ))}
      </div>
      <ChartTab id={thread.id} refreshKey={thread.refreshKey} timeframe={timeframe}
        alt={`${thread.symbol} ${SPAN[timeframe]}${timeframe === "1D" ? "" : " with the plan's entry and invalidation lines, your fills, and today's pings and Radar hits"}`} />
      <p aria-label="Legend" className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
        <Dot tone="bg-primary">your fills</Dot>
        <Dot tone="bg-violet-400">pings</Dot>
        <Dot tone="bg-sky-400">Radar</Dot>
        {timeframe === "1D" && <span>· marked on 2m and 15m</span>}
      </p>
    </div>
  );
}

/** What touched the thread, newest first, the New York time on the right and a dot by kind. */
function TimelineTab({ thread }: { thread: DeskThreadRef }) {
  const [read, setRead] = useState<{ data: DeskTimeline } | { error: string } | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    getDeskTimeline(thread.id, controller.signal).then(data => { if (!controller.signal.aborted) setRead({ data }); })
      .catch(failure => { if (!controller.signal.aborted) setRead({ error: failed(failure) }); });
    return () => controller.abort();
  }, [thread.id, thread.refreshKey]);
  if (!read) return <Quiet>Reading the timeline…</Quiet>;
  if ("error" in read) return <Quiet>Timeline unavailable: {read.error}</Quiet>;
  const { rows, unavailable, recent_days } = read.data;
  return (
    <div className="space-y-2">
      {rows.length ? (
        <ol aria-label="Timeline" className="space-y-2">
          {rows.map((row, i) => (
            <li key={`${row.kind}-${row.at}-${i}`} className="flex items-start gap-2 text-sm">
              <span aria-hidden className={cn("mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full", KIND[row.kind].dot)} />
              <span className="min-w-0 flex-1 break-words">
                <span className="sr-only">{KIND[row.kind].label}: </span>
                <span className="text-foreground">{row.text}</span>
                {row.detail && <span className="block text-xs text-muted-foreground">{row.detail}</span>}
              </span>
              <time dateTime={new Date(row.at * 1000).toISOString()} className="shrink-0 text-xs tabular-nums text-muted-foreground">{when(row.at)}</time>
            </li>
          ))}
        </ol>
      ) : <Quiet>Nothing has touched this thread in the last {recent_days} days.</Quiet>}
      {unavailable.length > 0 && <p className="text-xs text-muted-foreground">Could not read: {unavailable.join(", ")}.</p>}
    </div>
  );
}

/** The owner's own record at the plan's invalidation: a tile per past trade that crossed it while held, won or not,
 * and the server's one sentence from those counts. */
function HistoryTab({ thread }: { thread: DeskThreadRef }) {
  const [read, setRead] = useState<{ data: DeskHistory } | { error: string } | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    getDeskHistory(thread.id, controller.signal).then(data => { if (!controller.signal.aborted) setRead({ data }); })
      .catch(failure => { if (!controller.signal.aborted) setRead({ error: failed(failure) }); });
    return () => controller.abort();
  }, [thread.id, thread.refreshKey]);
  if (!read) return <Quiet>Reading your history…</Quiet>;
  if ("error" in read) return <Quiet>Your history is unavailable: {read.error}</Quiet>;
  const data = read.data;
  if (data.state !== "ok") return <Quiet>{data.reason}</Quiet>;
  const tiles = [...Array(data.won).fill("won"), ...Array(data.not_won).fill("did not win")] as string[];
  return (
    <div className="space-y-2 text-sm">
      {tiles.length > 0 && (
        <div role="img" aria-label={`${data.won} won, ${data.not_won} did not`} className="flex flex-wrap items-center gap-1">
          {tiles.slice(0, MAX_TILES).map((tile, i) => (
            <span key={i} title={tile} className={cn("h-3 w-3 rounded-sm", tile === "won" ? "bg-emerald-400/80" : "bg-rose-400/80")} />
          ))}
          {tiles.length > MAX_TILES && <span className="text-xs tabular-nums text-muted-foreground">+{tiles.length - MAX_TILES}</span>}
        </div>
      )}
      <p className="text-foreground">{data.sentence}</p>
      <p className="text-xs text-muted-foreground">
        At <span className="tabular-nums">{data.level}</span>, <span className="tabular-nums">{Math.abs(data.distance_pct).toFixed(1)}%</span> {data.side} the
        {data.entry_from === "planned" ? " planned entry " : " price "}<span className="tabular-nums">{data.entry}</span>, over the last {data.window_days} days.
        {" "}Evidence to weigh, not a rule.{data.simulated ? " Simulated." : ""}
      </p>
    </div>
  );
}

function TabBar<T extends string>({ tabs, tab, onTab }: { tabs: { id: T; label: string }[]; tab: T; onTab(tab: T): void }) {
  return (
    <div role="tablist" aria-label="Context" className="flex gap-3 border-b text-xs">
      {tabs.map(item => (
        <button key={item.id} type="button" role="tab" aria-selected={tab === item.id} onClick={() => onTab(item.id)}
          className={cn("-mb-px min-h-9 border-b-2 pb-1 sm:min-h-0", tab === item.id ? "border-primary text-foreground" : "border-transparent text-muted-foreground hover:text-foreground")}>
          {item.label}
        </button>
      ))}
    </div>
  );
}

/** Today across everything, newest first: the time stops still ahead (hollow), what happened (the session timeline's
 * fills, pings sent, Radar events and decisions) and when the prep was written. */
function DayTimelineTab() {
  const [read, setRead] = useState<{ data: DeskSession } | { error: string } | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    getDeskSession(controller.signal).then(data => { if (!controller.signal.aborted) setRead({ data }); })
      .catch(failure => { if (!controller.signal.aborted) setRead({ error: failed(failure) }); });
    return () => controller.abort();
  }, []);
  if (!read) return <Quiet>Reading today&apos;s timeline…</Quiet>;
  if ("error" in read) return <Quiet>Timeline unavailable: {read.error}</Quiet>;
  const { events, time_stops, now, prep, sections } = read.data;
  const rows = [
    ...time_stops.filter(stop => stop.at > now).reverse().map(stop => ({ key: `stop-${stop.symbol}-${stop.at}`, at: stop.at, dot: null, label: "Time stop ahead", text: `${stop.symbol} time stop`, detail: null as string | null })),
    ...[...events].reverse().map((event, i) => ({ key: `${event.kind}-${event.at}-${i}`, at: event.at, dot: DAY_DOT[event.kind], label: event.kind, text: event.text, detail: null as string | null })),
    ...(prep?.at ? [{ key: "prep", at: prep.at, dot: "bg-muted-foreground", label: "Prep", text: "Pre-market prep written", detail: prep.line }] : []),
  ];
  const missing = Object.entries(sections).filter(([name, state]) => state === "unavailable" && DAY_SOURCES[name]).map(([name]) => DAY_SOURCES[name]);
  return (
    <div className="space-y-2">
      {rows.length ? (
        <ol aria-label="Timeline" className="space-y-2">
          {rows.map(row => (
            <li key={row.key} className="flex items-start gap-2 text-sm">
              <span aria-hidden className={cn("mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full", row.dot ?? "border border-primary")} />
              <span className="min-w-0 flex-1 break-words">
                <span className="sr-only">{row.label}: </span>
                <span className={row.dot ? "text-foreground" : "text-muted-foreground"}>{row.text}</span>
                {row.detail && <span className="block text-xs text-muted-foreground">{row.detail}</span>}
              </span>
              <time dateTime={new Date(row.at * 1000).toISOString()} className="shrink-0 text-xs tabular-nums text-muted-foreground">{when(row.at)}</time>
            </li>
          ))}
        </ol>
      ) : <Quiet>Nothing yet today.</Quiet>}
      {missing.length > 0 && <p className="text-xs text-muted-foreground">Could not read: {missing.join(", ")}.</p>}
    </div>
  );
}

/** This week's entries, planned before entry or not (the plan streak's own counts, so tiles by kind, not by day), and the
 * streak with what one more planned entry makes. */
function WeekTab() {
  const streak = usePlanStreak();
  if (!streak) return <Quiet>Reading this week…</Quiet>;
  if (!streak.show) return <Quiet>No entries are tracked yet. Once a plan is saved before an entry, this week&apos;s record shows here.</Quiet>;
  const { planned, total, pending, entries } = streak.this_week;
  // The latest entries when there are more than fit, still oldest first; each opens its trade, where the linked plan shows.
  const shown = entries.slice(-MAX_TILES);
  return (
    <div className="space-y-2 text-sm">
      {shown.length > 0 && (
        <ol aria-label="This week's entries" className="flex flex-wrap items-center gap-1">
          {entries.length > MAX_TILES && <li className="text-xs tabular-nums text-muted-foreground">+{entries.length - MAX_TILES} earlier</li>}
          {shown.map(entry => {
            const tile = WEEK_TILE[entry.state];
            const label = `${entry.short} · ${weekClock(entry.entry_time)} · ${tile.label}`;
            return (
              <li key={entry.trade_id}>
                <Link href={`/trades/${encodeURIComponent(entry.trade_id)}`} title={label} aria-label={label}
                  className={cn("flex h-8 w-8 items-center justify-center rounded text-xs tabular-nums hover:ring-1 hover:ring-primary sm:h-6 sm:w-6", tile.tone)}>
                  {tile.mark}
                </Link>
              </li>
            );
          })}
        </ol>
      )}
      <p className="text-foreground">
        {total ? <><span className="tabular-nums">{planned}</span> of <span className="tabular-nums">{total}</span> entries this week were planned before entry.</> : "No entries yet this week."}
        {pending > 0 && <> <span className="tabular-nums">{pending}</span> waiting to be linked.</>}
      </p>
      <p className="text-xs text-muted-foreground">
        Plan streak <span className="tabular-nums">{streak.current}</span>, best <span className="tabular-nums">{streak.best}</span>.
        {streak.current > 0 ? <> One more planned entry makes <span className="tabular-nums">{streak.current + 1}</span> in a row.</>
          : streak.last_break ? <> Last unplanned: {streak.last_break.contract}{streak.last_break.reason === "late" ? " (plan saved late)" : ""}.</> : null}
      </p>
      <Link href={REVIEW_WEEK} className="inline-flex min-h-11 items-center text-xs text-muted-foreground hover:text-primary sm:min-h-0">Review my week →</Link>
    </div>
  );
}

/** The Context pane while the Briefing (or a thread with no symbol) is open: the market today with the day's fills and
 * pings, the day's timeline across everything, and this week's record. The chart reads again each minute while shown. */
function DayContext() {
  const [tab, setTab] = useState<DayTab>("chart");
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const timer = setInterval(() => { if (document.visibilityState === "visible") setTick(n => n + 1); }, REFRESH_MS);
    return () => clearInterval(timer);
  }, []);
  return (
    <div className="space-y-3">
      <div className="flex items-baseline gap-2 text-sm">
        <span className="font-semibold text-foreground">QQQ</span>
        <span className="text-xs text-muted-foreground">market today</span>
        <Link href="/charts?symbol=QQQ" className="ml-auto text-xs text-muted-foreground hover:text-primary">Open in Charts →</Link>
      </div>
      <TabBar<DayTab> tabs={DAY_TABS} tab={tab} onTab={setTab} />
      <div role="tabpanel" aria-label={DAY_TABS.find(item => item.id === tab)!.label}>
        {tab === "chart" ? (
          <div className="space-y-2">
            <ChartTab id={DESK_MARKET} refreshKey={tick} alt="QQQ today: minute bars with your fills and the phone pings sent today" />
            <p className="flex gap-3 text-xs text-muted-foreground">
              <Dot tone="bg-primary">your fills</Dot>
              <Dot tone="bg-violet-400">pings</Dot>
            </p>
          </div>
        ) : tab === "timeline" ? <DayTimelineTab /> : <WeekTab />}
      </div>
    </div>
  );
}

/** The desk's Context pane for the open thread: today's chart first, then its timeline and the owner's history at its
 * invalidation, each read only when its tab opens; ``day`` (the Briefing, or a thread with no symbol) shows the day
 * instead. Read-only: nothing here arms or sends. */
export default function Inspector({ thread, day = false }: { thread: DeskThreadRef | null; day?: boolean }) {
  const [tab, setTab] = useState<ContextTab>("chart");
  if (day) return <DayContext />;
  if (!thread) return <Quiet>Open a thread to see its chart, timeline and your history here.</Quiet>;
  return (
    <div className="space-y-3">
      <div className="flex items-baseline gap-2 text-sm">
        <span className="font-semibold text-foreground">{thread.symbol ?? "Across everything"}</span>
        {thread.symbol && <span className="text-xs text-muted-foreground">today</span>}
        {thread.symbol && <Link href={`/charts?symbol=${encodeURIComponent(thread.symbol)}`} className="ml-auto text-xs text-muted-foreground hover:text-primary">Open in Charts →</Link>}
      </div>
      <TabBar<ContextTab> tabs={TABS} tab={tab} onTab={setTab} />
      <div role="tabpanel" aria-label={TABS.find(item => item.id === tab)!.label}>
        {tab === "chart" ? <ThreadChart key={thread.id} thread={thread} />
          : tab === "timeline" ? <TimelineTab key={thread.id} thread={thread} />
            : <HistoryTab key={thread.id} thread={thread} />}
      </div>
    </div>
  );
}
