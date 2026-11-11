"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowLeft, CalendarCheck, ExternalLink, Sparkles } from "lucide-react";
import WatchDayLink from "@/components/replay/WatchDayLink";
import { apiUrl } from "@/lib/api";
import { cn } from "@/lib/utils";

export type FeedSource = "Alert" | "Plan" | "Radar" | "Radar setup" | "News" | "Calendar" | "Copilot note" | "r/wallstreetbets" | "NYT";
/** One feed row (``app/engine/desk_feed.py``). ``plan``: "setup" (a Radar setup card's own Plan it) or "own" (his own
 * position or plan); never on news, calendar or Radar events. */
export type FeedItem = {
  id: string; source: FeedSource; at: number; has_time: boolean; symbol: string | null; text: string; detail: string | null;
  publisher: string | null; url: string | null; href: string | null; investigation_id: string | null; radar_event_id: string | null;
  setup: { id: string; event_id: string; words: string; levels_line: string; contract_line: string | null; record: string | null;
    paper_record: string | null; plan_state: string; investigation_id: string | null } | null;
  plan: "setup" | "own" | null; mine: boolean; upcoming: boolean; chatter?: boolean;
};
/** One buzz chip (``app/engine/chatter.py`` ``buzz``): mentions in the last hour against the same hour on recent days;
 * ``multiple`` null without enough history ("no usual yet") or when it is usually never named then. */
export type ChatterBuzz = { symbol: string; count: number; usual: number | null; multiple: number | null; history: boolean; held: boolean };
export type ChatterState = "on" | "not set up" | "unavailable";
/** The Feed's chatter block: shown only behind its own Chatter filter, never in ``items``. */
export type DeskChatter = { sources: Record<string, ChatterState>; buzz: ChatterBuzz[]; record: string | null; items: FeedItem[] };
export type DeskFeedBody = { as_of: string; now: number; day: string; items: FeedItem[]; total: number;
  sources: Record<string, string>; unavailable: string[]; chatter?: DeskChatter };

const SEEN_KEY = "desk.feed.seen.v1";
const READ_MS = 60_000;
const ACTION = "inline-flex min-h-11 items-center gap-1 rounded-md border px-2.5 text-xs text-muted-foreground hover:bg-secondary hover:text-foreground sm:min-h-7";
const FILTERS = [["mine", "Mine"], ["market", "Market"], ["all", "Mine + Market"]] as const;
type Filter = (typeof FILTERS)[number][0] | "chatter";

const ny = (at: number, options: Intl.DateTimeFormatOptions) => new Date(at * 1000).toLocaleString("en-US", { timeZone: "America/New_York", ...options });
/** "10:40" today, "Thu 08:30" on another day; a date-only item reads "Today" or "Thu". */
export function feedWhen(item: Pick<FeedItem, "at" | "has_time">, day: string): string {
  const other = new Date(item.at * 1000).toLocaleDateString("en-CA", { timeZone: "America/New_York" }) !== day;
  const clock = ny(item.at, { hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
  const weekday = ny(item.at, { weekday: "short" });
  if (!item.has_time) return other ? weekday : "Today";
  return other ? `${weekday} ${clock}` : clock;
}

/** The question "Ask the copilot" puts in the box, unsent: the item as the feed shows it. A headline is quoted as the
 * publisher's words, named as such. */
export function feedQuestion(item: FeedItem, day: string): string {
  const when = feedWhen(item, day);
  if (item.chatter) {
    return `About this ${item.source} item (${when}${item.symbol ? `, ${item.symbol}` : ""}), quoted as posted: "${item.text}". What is it about, and does it touch my positions or plans?`;
  }
  if (item.source === "News") {
    return `About the ${item.publisher ?? "news"} headline on ${item.symbol ?? "the market"} (${when}), quoted: "${item.text}". What is it about, and does it touch my positions or plans?`;
  }
  return `About this ${item.source.toLowerCase()} (${when}${item.symbol ? `, ${item.symbol}` : ""}): "${item.text}". What is behind it, and does it touch my positions or plans?`;
}

function readSeen(): number | null {
  try { const v = Number(window.localStorage.getItem(SEEN_KEY)); return Number.isFinite(v) && v > 0 ? v : null; } catch { return null; }
}
function saveSeen(at: number) {
  try { window.localStorage.setItem(SEEN_KEY, String(at)); } catch { /* this visit only */ }
}

/** The feed, read once a minute while the lab is on; the tab's count needs it before the tab is opened. */
export function useDeskFeed(on: boolean): { data: DeskFeedBody | null; failed: boolean } {
  const [data, setData] = useState<DeskFeedBody | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (!on) return;
    const controller = new AbortController();
    const load = () => fetch(apiUrl("/copilot/desk/feed"), { cache: "no-store", signal: controller.signal })
      .then(r => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((body: DeskFeedBody) => { setData(body); setFailed(false); })
      .catch(() => { if (!controller.signal.aborted) setFailed(true); });
    load();
    const timer = setInterval(load, READ_MS);
    return () => { controller.abort(); clearInterval(timer); };
  }, [on]);
  return { data, failed };
}

/** How many items arrived since the Feed was last opened in this browser; on a first visit, all of today's so far. */
export function useFeedNew(data: DeskFeedBody | null, open: boolean): { count: number; since: number | null } {
  const [seen, setSeen] = useState<number | null | undefined>(undefined);
  const [since, setSince] = useState<number | null>(null); // what counted as new when the tab opened, for its dots
  useEffect(() => { setSeen(readSeen()); }, []); // eslint-disable-line react-hooks/set-state-in-effect -- the store is read after hydration
  useEffect(() => {
    if (!open || !data || seen === undefined) return;
    setSince(prev => prev ?? seen ?? 0); // eslint-disable-line react-hooks/set-state-in-effect -- opening the tab marks it looked at
    saveSeen(data.now);
    setSeen(data.now);
  }, [open, data, seen]);
  useEffect(() => { if (!open) setSince(null); }, [open]); // eslint-disable-line react-hooks/set-state-in-effect -- closed: the next open counts afresh
  const count = !data || seen === undefined ? 0 : data.items.filter(i => !i.upcoming && i.at > (seen ?? 0)).length;
  return { count, since };
}

/**
 * The centre's Feed tab (docs/copilot-lab.md § The desk): one stream of what the app already knows today, from
 * ``GET /copilot/desk/feed``. Mine (his book, plans and day), Market, or both; tapping a symbol shows that symbol's story,
 * with a way back. Each row: its source, time, symbol and words, and the same small actions: Ask the copilot, Open in
 * Charts, the headline at its publisher, and Plan it only on a Radar setup card or his own position or plan. Facts
 * only; nothing here is an order. What matters right now?, Review my week and today's replay sit at its foot.
 * **Chatter** (r/wallstreetbets buzz, NYT headlines) is a fourth filter that shows only while a chatter source has rows;
 * its rows never show under the other filters, never count as new, and carry only Ask the copilot and their link.
 */
export default function DeskFeed({ data, failed, since, onAsk, onPlan, onWhatMatters, onReviewWeek }: {
  data: DeskFeedBody | null; failed: boolean; since: number | null;
  onAsk(item: FeedItem): void; onPlan(item: FeedItem): void; onWhatMatters(): void; onReviewWeek(): void;
}) {
  const [picked, setFilter] = useState<Filter>("mine");
  const [symbol, setSymbol] = useState<string | null>(null);
  const chatter = data?.chatter ?? null;
  const chatterOn = (chatter?.items.length ?? 0) > 0;
  const filter: Filter = picked === "chatter" && !chatterOn ? "mine" : picked;
  const items = useMemo(() => {
    if (filter === "chatter" && !symbol) return chatter?.items ?? [];
    const all = (data?.items ?? []).filter(i => !i.chatter);
    if (symbol) return all.filter(i => i.symbol === symbol);
    return all.filter(i => filter === "all" || (filter === "mine") === i.mine);
  }, [data, chatter, filter, symbol]);
  const day = data?.day ?? "";
  const market = (data?.items ?? []).filter(i => !i.mine).length;
  const unread = data?.unavailable.filter(n => n !== "book") ?? [];
  const filters: readonly (readonly [Filter, string])[] = chatterOn ? [...FILTERS, ["chatter", "Chatter"]] : FILTERS;
  const chatterNote = chatterWhy(chatter, chatterOn);

  return (
    <section aria-label="Feed" data-testid="desk-feed" className="space-y-2">
      {symbol ? (
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" onClick={() => setSymbol(null)} className={ACTION}><ArrowLeft size={13} aria-hidden />All items</button>
          <span className="text-sm"><span className="font-semibold">{symbol}</span><span className="text-muted-foreground"> · its story today</span></span>
        </div>
      ) : (
        <div role="group" aria-label="Show" className="inline-flex rounded-md border p-0.5">
          {filters.map(([id, label]) => (
            <button key={id} type="button" aria-pressed={filter === id} onClick={() => setFilter(id)}
              className={cn("min-h-11 rounded px-2.5 text-xs sm:min-h-7", filter === id ? "bg-secondary font-medium text-foreground" : "text-muted-foreground hover:text-foreground")}>
              {label}
            </button>
          ))}
        </div>
      )}
      {filter === "chatter" && !symbol && chatter && <ChatterHead chatter={chatter} />}
      {!data && (failed ? <p className="text-xs text-muted-foreground">The feed could not be read right now.</p>
        : <p className="text-xs text-muted-foreground">Reading the feed…</p>)}
      {data && !items.length && (
        <p className="rounded-md border bg-card px-3 py-2.5 text-xs text-muted-foreground">
          {filter === "mine" && !symbol && market ? `Nothing on your book or plans yet today. Market has ${market}.` : "Nothing here yet today."}
        </p>
      )}
      {items.length > 0 && (
        <ol className="divide-y rounded-lg border bg-card">
          {items.map((item, i) => (
            <FeedRow key={item.id} item={item} day={day} fresh={!item.chatter && since !== null && !item.upcoming && item.at > since}
              ahead={!item.chatter && item.upcoming && !items[i - 1]?.upcoming} onSymbol={setSymbol} onAsk={onAsk} onPlan={onPlan} />
          ))}
        </ol>
      )}
      {data && filter !== "chatter" && data.total > data.items.length && !symbol && (
        <p className="px-1 text-xs text-muted-foreground">Showing the first {data.items.length} of {data.total}.</p>
      )}
      {unread.length > 0 && filter !== "chatter" && <p data-testid="feed-unavailable" className="px-1 text-xs text-muted-foreground">Could not read: {unread.join(", ")}.</p>}
      {chatterNote && (filter === "chatter" || !chatterOn) && <p data-testid="feed-chatter-note" className="px-1 text-xs text-muted-foreground">{chatterNote}</p>}
      <div className="flex flex-wrap gap-2 pt-1">
        <button type="button" onClick={onWhatMatters} className={ACTION}
          title="One copilot turn across your open positions, armed watches and open questions, in today's conversation">
          <Sparkles size={13} aria-hidden />What matters right now?
        </button>
        <button type="button" onClick={onReviewWeek} className={ACTION}
          title="One copilot turn reviewing your latest trading week: planned vs unplanned, follow-through, alerts and exits">
          <CalendarCheck size={13} aria-hidden />Review my week
        </button>
        {day && <WatchDayLink from={day} className={ACTION} />}
      </div>
    </section>
  );
}

/** Why Chatter is missing, or which of its sources is not showing: nothing when no source is set up. */
function chatterWhy(chatter: DeskChatter | null, shown: boolean): string | null {
  if (!chatter) return null;
  const sources = Object.entries(chatter.sources).filter(([, state]) => state !== "not set up");
  const has = new Set(chatter.items.map(i => i.source as string));
  const parts = sources.flatMap(([name, state]) => state === "unavailable" ? [`${name} could not be read`]
    : !has.has(name) ? [`nothing from ${name} yet`] : []);
  if (!parts.length) return null;
  const said = parts.join("; ");
  return shown ? `${said[0].toUpperCase()}${said.slice(1)}.` : `Chatter: ${said}.`;
}

/** The Chatter filter's head: buzz chips (ticker and multiple, outlined when he holds it). His record on entries made
 * during a mention spike sits in each buzz row. Counts only. */
function ChatterHead({ chatter }: { chatter: DeskChatter }) {
  if (!chatter.buzz.length) return null;
  return (
    <ul data-testid="feed-chatter-head" aria-label="Mentions on r/wallstreetbets in the last hour" className="flex flex-wrap gap-1.5">
      {chatter.buzz.map(b => (
        <li key={b.symbol} data-testid="buzz-chip" data-held={b.held || undefined}
          title={`${b.count} post${b.count === 1 ? "" : "s"} in the last hour${b.held ? " · you hold it" : ""}`}
          className={cn("rounded-full border px-2 py-0.5 text-xs tabular-nums",
            b.held ? "border-foreground text-foreground" : "border-transparent bg-secondary text-muted-foreground")}>
          <span className="font-semibold text-foreground">{b.symbol}</span>{" "}
          {b.multiple !== null ? `${b.multiple}×` : b.history ? `${b.count}, usually none` : `${b.count} posts`}
        </li>
      ))}
    </ul>
  );
}

function FeedRow({ item, day, fresh, ahead, onSymbol, onAsk, onPlan }: {
  item: FeedItem; day: string; fresh: boolean; ahead: boolean; onSymbol(symbol: string): void; onAsk(item: FeedItem): void; onPlan(item: FeedItem): void;
}) {
  const chatter = !!item.chatter;
  const open = chatter ? null : item.source === "Radar" || (item.source === "Copilot note" && item.href && !item.href.includes("symbol=")) ? item.href : null;
  return (
    <li data-testid="feed-item" className="min-w-0 px-3 py-2.5">
      {ahead && <p className="-mt-0.5 mb-2 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Coming up</p>}
      <p className="flex min-w-0 items-center gap-2 text-xs text-muted-foreground">
        <span data-testid="feed-source" className="whitespace-nowrap rounded border px-1.5 py-px text-[11px]">{item.source}</span>
        <span className="tabular-nums">{feedWhen(item, day)}</span>
        {fresh && <span aria-label="new" className="size-1.5 rounded-full bg-muted-foreground" />}
        {item.symbol && chatter && <span className="ml-auto font-semibold text-foreground">{item.symbol}</span>}
        {item.symbol && !chatter && (
          <button type="button" onClick={() => onSymbol(item.symbol!)} title={`Only ${item.symbol}'s items`}
            className="ml-auto inline-flex min-h-11 items-center font-semibold text-foreground hover:underline sm:min-h-0">{item.symbol}</button>
        )}
      </p>
      <p className="mt-1 line-clamp-3 break-words text-sm text-foreground">{item.text}</p>
      {item.publisher && !chatter && <p className="text-xs text-muted-foreground">{item.publisher}</p>}
      {item.detail && <p className="line-clamp-2 break-words text-xs text-muted-foreground">{item.detail}</p>}
      {item.setup && (
        <div data-testid="feed-setup" className="mt-1.5 space-y-0.5 rounded-md border bg-background/40 p-2 text-sm">
          <p className="text-foreground">{item.setup.levels_line}</p>
          <p className="text-foreground">{item.setup.contract_line ?? "No liquid contract found."}</p>
          {item.setup.record && <p className="text-xs text-muted-foreground">{item.setup.record}</p>}
          {item.setup.paper_record && <p className="text-xs text-muted-foreground">{item.setup.paper_record}</p>}
          {item.setup.plan_state === "planned" && <p className="text-xs text-muted-foreground">Planned.</p>}
          {item.setup.plan_state === "refused" && <p className="text-xs text-muted-foreground">Not planned.</p>}
        </div>
      )}
      <div className="mt-2 flex flex-wrap gap-1.5">
        <button type="button" onClick={() => onAsk(item)} className={ACTION}>Ask the copilot</button>
        {item.symbol && !chatter && <Link href={`/charts?symbol=${encodeURIComponent(item.symbol)}`} className={ACTION}>Open in Charts</Link>}
        {item.url && (
          <a href={item.url} target="_blank" rel="noopener noreferrer nofollow" className={ACTION}>
            {item.source === "r/wallstreetbets" ? "Open on Reddit" : `Read at ${item.publisher ?? "the source"}`}<ExternalLink size={12} aria-hidden />
          </a>
        )}
        {open && <Link href={open} className={ACTION}>Open</Link>}
        {item.plan && !chatter && <button type="button" onClick={() => onPlan(item)} className={ACTION}>Plan it</button>}
      </div>
    </li>
  );
}
