"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowLeft, ExternalLink } from "lucide-react";
import { deskGet, everyDeskMinute } from "@/lib/deskMinute";
import { useKeptState } from "@/components/copilot/DeskMemory";
import { cn } from "@/lib/utils";
import type { ChainPick } from "@/components/copilot/DeskChain";
import { UnusualList, type UnusualReply } from "@/components/copilot/DeskUnusual";
import { ScannerList, type DeskScannerReply, type DeskScannerRow } from "@/components/copilot/DeskScanner";

export type FeedSource = "Alert" | "Plan" | "Radar" | "Radar setup" | "News" | "Calendar" | "Copilot note" | "TradingView" | "r/wallstreetbets" | "NYT";
/** One feed row (``app/engine/desk_feed.py``). ``plan``: "setup" (a Radar setup card's own Plan it) or "own" (his own
 * position or plan); never on news, calendar or Radar events. */
export type FeedItem = {
  id: string; source: FeedSource; at: number; has_time: boolean; symbol: string | null; text: string; detail: string | null;
  publisher: string | null; url: string | null; href: string | null; investigation_id: string | null; radar_event_id: string | null;
  setup: { id: string; event_id: string; words: string; levels_line: string; contract_line: string | null; record: string | null;
    paper_record: string | null; plan_state: string; investigation_id: string | null } | null;
  plan: "setup" | "own" | null; mine: boolean; upcoming: boolean; chatter?: boolean;
  /** A chatter buzz row whose counts are not current: shown grey. */
  stale?: boolean;
};
/** One buzz chip (``app/engine/chatter.py`` ``buzz``): ApeWisdom's r/wallstreetbets mentions in the last 24h against
 * the 24h before (``multiple`` null when none were counted then) and the rank change. ``stale``: counts not updated
 * since ``as_of``, shown grey with that time. */
export type ChatterBuzz = { symbol: string; count: number; before: number | null; multiple: number | null; rank: number | null;
  rank_before: number | null; climbed: number | null; held: boolean; as_of: number; stale: boolean };
export type ChatterState = "on" | "stale" | "not set up" | "unavailable";
/** The Feed's chatter block: shown only behind its own Chatter filter, never in ``items``. */
export type DeskChatter = { sources: Record<string, ChatterState>; buzz: ChatterBuzz[]; items: FeedItem[] };
/** ``tradingview.last_at``: when his newest stored TradingView alert (on a ticker he follows) came in, or null. */
export type DeskFeedBody = { as_of: string; now: number; day: string; items: FeedItem[]; total: number;
  sources: Record<string, string>; unavailable: string[]; chatter?: DeskChatter; tradingview?: { last_at: number | null } };

const SEEN_KEY = "desk.feed.seen.v1";
const ACTION = "inline-flex min-h-11 items-center gap-1 rounded-md border px-2.5 text-xs text-muted-foreground hover:bg-secondary hover:text-foreground sm:min-h-7";
/** The Feed's four groups: what is his, ideas he could act on, the market's news, and everything. Ideas and Market each
 * carry a small second row (Radar, Scanner, Unusual options; News & calendar, Chatter) when there is more than one. */
const GROUPS = [["mine", "Mine"], ["ideas", "Ideas"], ["market", "Market"], ["all", "All"]] as const;
type Group = (typeof GROUPS)[number][0];
type Idea = "radar" | "scanner" | "unusual";
type MarketPick = "news" | "chatter";
/** What the list shows: a group, or one of its second row's picks. */
type Filter = "mine" | "all" | Idea | MarketPick;
const RADAR: readonly FeedSource[] = ["Radar", "Radar setup"];
const isRadar = (item: FeedItem) => RADAR.includes(item.source);

const ny = (at: number, options: Intl.DateTimeFormatOptions) => new Date(at * 1000).toLocaleString("en-US", { timeZone: "America/New_York", ...options });
/** "10:40" today, "Thu 08:30" on another day; a date-only item reads "Today" or "Thu". */
export function feedWhen(item: Pick<FeedItem, "at" | "has_time">, day: string): string {
  const other = new Date(item.at * 1000).toLocaleDateString("en-CA", { timeZone: "America/New_York" }) !== day;
  const clock = ny(item.at, { hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
  const weekday = ny(item.at, { weekday: "short" });
  if (!item.has_time) return other ? weekday : "Today";
  return other ? `${weekday} ${clock}` : clock;
}

/** "just now", "12 min ago", "2 h ago": how long before the feed's read a TradingView alert came in. */
export function feedAgo(at: number, now: number): string {
  const minutes = Math.floor(Math.max(0, now - at) / 60);
  return minutes < 1 ? "just now" : minutes < 60 ? `${minutes} min ago` : `${Math.floor(minutes / 60)} h ago`;
}

/** Under Mine on a day with no TradingView alert yet: when the last one came ("Thu 15:42" this week, else "Oct 30"),
 * so a quiet webhook shows as quiet. Nothing when there has never been one, or one came today. */
export function tradingViewQuiet(data: DeskFeedBody): string | null {
  const last = data.tradingview?.last_at ?? null;
  if (last === null || data.items.some(i => i.source === "TradingView")) return null;
  if (new Date(last * 1000).toLocaleDateString("en-CA", { timeZone: "America/New_York" }) === data.day) return null;
  const when = data.now - last < 6 * 86_400 ? feedWhen({ at: last, has_time: true }, data.day) : ny(last, { month: "short", day: "numeric" });
  return `No TradingView alerts today. Last one ${when}.`;
}

/** The question "Ask the copilot" puts in the box, unsent: the item as the feed shows it. A headline is quoted as the
 * publisher's words, named as such. */
export function feedQuestion(item: FeedItem, day: string): string {
  const when = feedWhen(item, day);
  if (item.chatter) {
    return `About this ${item.source} item (${when}${item.symbol ? `, ${item.symbol}` : ""}), quoted as posted: "${item.text}". What is it about, and does it touch my positions or plans?`;
  }
  if (item.source === "TradingView") {
    return `About my TradingView alert (${when}${item.symbol ? `, ${item.symbol}` : ""}): "${item.text}". What is the chart doing now, and does it touch my positions or plans?`;
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
    const load = () => deskGet("/copilot/desk/feed", controller.signal)
      // A refusal is read through too, so the request ends (an unread body holds it open).
      .then(async r => (r.ok ? r.json() : r.text().catch(() => "").then(() => Promise.reject(new Error(String(r.status))))))
      .then((body: DeskFeedBody) => { setData(body); setFailed(false); })
      .catch(() => { if (!controller.signal.aborted) setFailed(true); });
    load();
    const stop = everyDeskMinute(load); // the shared minute: one request with the desk's other reads, none while hidden
    return () => { controller.abort(); stop(); };
  }, [on]);
  return { data, failed };
}

/** How many of his own items (Mine: his book, plans and day) arrived since the Feed was last opened in this browser; on a
 * first visit, all of today's so far. Ideas and the market's news never count: the tab badges only what is his. */
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
  const count = !data || seen === undefined ? 0 : data.items.filter(i => i.mine && !i.upcoming && i.at > (seen ?? 0)).length;
  return { count, since };
}

/**
 * The Feed, beside the copilot (docs/copilot-lab.md § The desk): one stream of what the app already knows today, from
 * ``GET /copilot/desk/feed``, in four groups: **Mine** (the default: his book, plans and day), **Ideas** (things he could
 * act on that are not his yet: Radar's events and setup cards, the setup scanner's candidates while it is on, and unusual
 * options on his held and watched names, one tap apart on a small second row), **Market** (the rest: headlines and the
 * calendar, and Chatter beside them while a chatter source has rows) and **All** (Mine, Radar and Market's news
 * together, never the Scanner, Unusual or Chatter lists). Tapping a symbol shows that symbol's story, with a way back.
 * Each row: its source, time, symbol and words, and the same small actions: Ask the copilot, Open in Charts, the
 * headline at its publisher, and Plan it only on a Radar setup card or his own position or plan. Facts only; nothing here
 * is an order. A source that could not be read is left out quietly. The copilot's own questions (What matters right
 * now?, Review my week) are in the copilot and ⌘K, not repeated here.
 * **TradingView** rows (under Mine, counted as new): his own alerts that reached the webhook today, with what fired, the
 * price then and how long ago; Show on chart puts the ticker on the desk chart (its marker there), On Signals opens the
 * stored alert. A day with none says once, in grey, when the last one came; never a sound or a pop-up.
 * **Chatter** (r/wallstreetbets buzz from ApeWisdom's counts, NYT headlines): its rows never show under the other picks,
 * never count as new, and carry only Ask the copilot and their link; what a chatter source did not deliver is said only
 * under it.
 * **Unusual options** (``DeskUnusual``): unusual contracts on his held and watched names; a row selects the contract in
 * the Chain tab. **Scanner** (``DeskScanner``), while the setup scanner is switched on: today's candidates; a row opens
 * the ticker on the desk chart with the scanner's levels. Neither counts as new or mixes into the other picks.
 */
export default function DeskFeed({ data, failed, since, onAsk, onPlan, onChart, unusual = null, onUnusual, scanner = null, onScanner, onScannerPlan }: {
  data: DeskFeedBody | null; failed: boolean; since: number | null; onAsk(item: FeedItem): void; onPlan(item: FeedItem): void;
  /** A row's Show on chart: its ticker on the desk chart, in place (a TradingView alert's marker sits there). */
  onChart?(symbol: string): void;
  unusual?: UnusualReply | null; onUnusual?(pick: ChainPick): void;
  scanner?: DeskScannerReply | null; onScanner?(row: DeskScannerRow): void; onScannerPlan?(href: string): void;
}) {
  // The picks hold while he stays on the desk (a link that reopens it included), so the Feed is where he left it.
  const [group, setGroup] = useKeptState<Group>("desk.feed.group", "mine");
  const [ideaPick, setIdea] = useKeptState<Idea>("desk.feed.idea", "radar");
  const [marketPick, setMarket] = useKeptState<MarketPick>("desk.feed.market", "news");
  const [symbol, setSymbol] = useState<string | null>(null);
  const chatter = data?.chatter ?? null;
  const chatterOn = (chatter?.items.length ?? 0) > 0;
  const scannerOn = !!scanner && scanner.state !== "off";
  const idea: Idea = ideaPick === "scanner" && !scannerOn ? "radar" : ideaPick;
  const marketShown: MarketPick = marketPick === "chatter" && !chatterOn ? "news" : marketPick;
  const filter: Filter = group === "ideas" ? idea : group === "market" ? marketShown : group;
  // Chatter gone (nothing to show this minute): back to News & calendar for good, so it never reopens without a tap.
  useEffect(() => { if (marketPick === "chatter" && data && !chatterOn) setMarket("news"); }, [marketPick, data, chatterOn, setMarket]); // follows the feed's own read
  const items = useMemo(() => {
    if ((filter === "chatter" || filter === "unusual" || filter === "scanner") && !symbol) return filter === "chatter" ? chatter?.items ?? [] : [];
    const all = (data?.items ?? []).filter(i => !i.chatter);
    if (symbol) return all.filter(i => i.symbol === symbol);
    // Mine: his book, plans and day. Radar: every Radar event and setup card. News & calendar: the rest that is not his.
    return all.filter(i => filter === "all" || (filter === "mine" ? i.mine : filter === "radar" ? isRadar(i) : !i.mine && !isRadar(i)));
  }, [data, chatter, filter, symbol]);
  const day = data?.day ?? "";
  const notMine = (data?.items ?? []).filter(i => !i.mine).length;
  const ideas: readonly (readonly [Idea, string])[] = [["radar", "Radar"], ...(scannerOn ? [["scanner", "Scanner"] as const] : []), ["unusual", "Unusual options"]];
  const markets: readonly (readonly [MarketPick, string])[] = chatterOn ? [["news", "News & calendar"], ["chatter", "Chatter"]] : [];
  const chatterNote = chatterWhy(chatter);
  const quietLine = data && filter === "mine" && !symbol ? tradingViewQuiet(data) : null;

  return (
    <section aria-label="Feed" data-testid="desk-feed" className="space-y-2">
      {symbol ? (
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" onClick={() => setSymbol(null)} className={ACTION}><ArrowLeft size={13} aria-hidden />All items</button>
          <span className="text-sm"><span className="font-semibold">{symbol}</span><span className="text-muted-foreground"> · its story today</span></span>
        </div>
      ) : (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
          <div role="group" aria-label="Show" className="inline-flex flex-wrap rounded-md border p-0.5">
            {GROUPS.map(([id, label]) => (
              <button key={id} type="button" aria-pressed={group === id} onClick={() => setGroup(id)}
                className={cn("min-h-11 rounded px-2.5 text-xs sm:min-h-7", group === id ? "bg-secondary font-medium text-foreground" : "text-muted-foreground hover:text-foreground")}>
                {label}
              </button>
            ))}
          </div>
          {group === "ideas" && <SubPicks<Idea> label="Ideas" picks={ideas} value={idea} onPick={setIdea} />}
          {group === "market" && markets.length > 0 && <SubPicks<MarketPick> label="Market" picks={markets} value={marketShown} onPick={setMarket} />}
        </div>
      )}
      {filter === "chatter" && !symbol && chatter && <ChatterHead chatter={chatter} day={day} />}
      {filter === "unusual" && !symbol ? <UnusualList reply={unusual} onPick={pick => onUnusual?.(pick)} />
        : filter === "scanner" && !symbol ? <ScannerList reply={scanner} onOpen={row => onScanner?.(row)} onPlan={href => onScannerPlan?.(href)} /> : <>
      {!data && (failed ? <p className="text-xs text-muted-foreground">The feed could not be read right now.</p>
        : <p className="text-xs text-muted-foreground">Reading the feed…</p>)}
      {data && !items.length && (
        <p className="rounded-md border bg-card px-3 py-2.5 text-xs text-muted-foreground">
          {filter === "mine" && !symbol && notMine ? `Nothing on your book or plans yet today. Ideas and Market have ${notMine}.` : "Nothing here yet today."}
        </p>
      )}
      {items.length > 0 && (
        <ol className="divide-y rounded-lg border bg-card">
          {items.map((item, i) => (
            <FeedRow key={item.id} item={item} day={day} fresh={!item.chatter && since !== null && !item.upcoming && item.at > since}
              ahead={!item.chatter && item.upcoming && !items[i - 1]?.upcoming} now={data?.now ?? 0} onSymbol={setSymbol} onAsk={onAsk} onPlan={onPlan} onChart={onChart} />
          ))}
        </ol>
      )}
      {data && filter !== "chatter" && data.total > data.items.length && !symbol && (
        <p className="px-1 text-xs text-muted-foreground">Showing the first {data.items.length} of {data.total}.</p>
      )}
      {quietLine && <p data-testid="feed-tradingview-quiet" className="px-1 text-xs text-muted-foreground">{quietLine}</p>}
      {chatterNote && filter === "chatter" && <p data-testid="feed-chatter-note" className="px-1 text-xs text-muted-foreground">{chatterNote}</p>}
      </>}
    </section>
  );
}

/** A group's second row: plain words, the picked one underlined. */
function SubPicks<T extends string>({ label, picks, value, onPick }: { label: string; picks: readonly (readonly [T, string])[]; value: T; onPick(pick: T): void }) {
  return (
    <div role="group" aria-label={label} className="inline-flex flex-wrap gap-x-2.5">
      {picks.map(([id, text]) => (
        <button key={id} type="button" aria-pressed={value === id} onClick={() => onPick(id)}
          className={cn("min-h-11 border-b text-xs sm:min-h-7", value === id ? "border-foreground font-medium text-foreground" : "border-transparent text-muted-foreground hover:text-foreground")}>
          {text}
        </button>
      ))}
    </div>
  );
}

/** Under the Chatter filter, which of its sources is not showing: nothing when every set-up source has rows. */
function chatterWhy(chatter: DeskChatter | null): string | null {
  if (!chatter) return null;
  const sources = Object.entries(chatter.sources).filter(([, state]) => state !== "not set up");
  const has = new Set(chatter.items.map(i => i.source as string));
  // r/wallstreetbets read fine but with nothing at 2× its day before: no buzz, not "nothing read".
  const parts = sources.flatMap(([name, state]) => state === "unavailable" ? [`${name} could not be read`]
    : has.has(name) ? [] : name === "r/wallstreetbets" ? [`no buzz on ${name} right now`] : [`nothing from ${name} yet`]);
  if (!parts.length) return null;
  const said = parts.join("; ");
  return `${said.startsWith("r/") ? said[0] : said[0].toUpperCase()}${said.slice(1)}.`; // "r/wallstreetbets" keeps its r/
}

const APEWISDOM = "Counts from ApeWisdom, a third party; may stop in 2027 if Reddit closes its access.";

/** The Chatter filter's head: buzz chips (ticker and its multiple of the 24h before, outlined when he holds it), grey
 * with their time when the counts are stale, and one line saying whose counts they are. Counts only. */
function ChatterHead({ chatter, day }: { chatter: DeskChatter; day: string }) {
  if (!chatter.buzz.length) return null;
  const stale = chatter.buzz.find(b => b.stale);
  return (
    <div data-testid="feed-chatter-head" className="space-y-1">
      <ul aria-label="Mentions on r/wallstreetbets in the last 24h against the 24h before" className="flex flex-wrap gap-1.5">
        {chatter.buzz.map(b => (
          <li key={b.symbol} data-testid="buzz-chip" data-held={b.held || undefined} data-stale={b.stale || undefined}
            title={`${b.count} mention${b.count === 1 ? "" : "s"} in the last 24h, ${b.before ?? "none counted"} the 24h before${
              b.rank ? ` · rank ${b.rank}${b.rank_before ? `, was ${b.rank_before}` : ""}` : ""}${b.held ? " · you hold it" : ""}`}
            className={cn("rounded-full border px-2 py-0.5 text-xs tabular-nums", b.stale && "opacity-60",
              b.held ? (b.stale ? "border-muted-foreground text-muted-foreground" : "border-foreground text-foreground")
                : "border-transparent bg-secondary text-muted-foreground")}>
            <span className={cn("font-semibold", b.stale ? "text-muted-foreground" : "text-foreground")}>{b.symbol}</span>{" "}
            {b.multiple !== null ? `${b.multiple}×` : `${b.count}, none before`}
          </li>
        ))}
      </ul>
      <p data-testid="buzz-note" className="px-1 text-[11px] text-muted-foreground">
        {stale ? `As of ${feedWhen({ at: stale.as_of, has_time: true }, day)}, not updated since. ` : "Last 24h vs the 24h before. "}{APEWISDOM}
      </p>
    </div>
  );
}

function FeedRow({ item, day, fresh, ahead, now, onSymbol, onAsk, onPlan, onChart }: {
  item: FeedItem; day: string; fresh: boolean; ahead: boolean; now: number; onSymbol(symbol: string): void; onAsk(item: FeedItem): void; onPlan(item: FeedItem): void;
  onChart?(symbol: string): void;
}) {
  const chatter = !!item.chatter;
  const tradingView = item.source === "TradingView";
  const open = chatter ? null : item.source === "Radar" || (item.source === "Copilot note" && item.href && !item.href.includes("symbol=")) ? item.href : null;
  return (
    <li data-testid="feed-item" className="min-w-0 px-3 py-2.5">
      {ahead && <p className="-mt-0.5 mb-2 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Coming up</p>}
      <p className="flex min-w-0 items-center gap-2 text-xs text-muted-foreground">
        <span data-testid="feed-source" className="whitespace-nowrap rounded border px-1.5 py-px text-[11px]">{item.source}</span>
        <span className="tabular-nums">{feedWhen(item, day)}{tradingView && now > 0 && <> · {feedAgo(item.at, now)}</>}</span>
        {fresh && <span aria-label="new" className="size-1.5 rounded-full bg-muted-foreground" />}
        {item.symbol && chatter && <span className="ml-auto font-semibold text-foreground">{item.symbol}</span>}
        {item.symbol && !chatter && (
          <button type="button" onClick={() => onSymbol(item.symbol!)} title={`Only ${item.symbol}'s items`}
            className="ml-auto inline-flex min-h-11 items-center font-semibold text-foreground hover:underline sm:min-h-0">{item.symbol}</button>
        )}
      </p>
      <p data-stale={item.stale || undefined} className={cn("mt-1 line-clamp-3 break-words text-sm", item.stale ? "text-muted-foreground" : "text-foreground")}>{item.text}</p>
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
        {/* The same first step on every row about a ticker: its chart on the desk, in place, the Feed still beside it. */}
        {item.symbol && !chatter && onChart && <button type="button" onClick={() => onChart(item.symbol!)} className={ACTION}>Show on chart</button>}
        {item.symbol && !chatter && !tradingView && <Link href={`/charts?symbol=${encodeURIComponent(item.symbol)}`} className={ACTION}>Open in Charts</Link>}
        {item.url && (
          <a href={item.url} target="_blank" rel="noopener noreferrer nofollow" className={ACTION}>
            {item.source === "r/wallstreetbets" ? "Open on Reddit" : `Read at ${item.publisher ?? "the source"}`}<ExternalLink size={12} aria-hidden />
          </a>
        )}
        {open && <Link href={open} className={ACTION}>Open</Link>}
        {tradingView && item.href && <Link href={item.href} className={ACTION}>On Signals</Link>}
        {item.plan && !chatter && <button type="button" onClick={() => onPlan(item)} className={ACTION}>Plan it</button>}
      </div>
    </li>
  );
}
