import { requireAccess } from "@/lib/accessServer";
import { DashboardCard } from "@/components/dashboard/DashboardCard";
import DayReviewWorkflow from "@/components/DayReviewWorkflow";
import ReviewMyWeek from "@/components/copilot/ReviewMyWeek";
import JoDay from "@/components/JoDay";
import PracticeRoutine from "@/components/PracticeRoutine";
import { api } from "@/lib/serverApi";
import type { Account, Fill, FillMarketContext, PositionQuote, Trade } from "@/lib/api";
import { newYorkToday } from "@/lib/format";
import { buildOpenPositionMeta, formatHoldDuration, computeUnrealizedPnl, isEntryFill, type OpenPositionMeta } from "@/lib/dashboard";

type TradeWithFills = {
  trade: Trade;
  fills: Fill[];
};

function dateKey(value: string | null | undefined) {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function formatDate(value: string) {
  return new Date(`${value}T12:00:00`).toLocaleDateString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function formatDateTime(value: string | null | undefined) {
  if (!value) return "-";
  return `${new Date(value).toLocaleString("en-US", { timeZone: "America/New_York", month: "numeric", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit", second: "2-digit" })} ET`;
}

function fmtMoney(value: number | null | undefined, decimals = 2) {
  if (value == null) return "-";
  return `$${value.toFixed(decimals)}`;
}

function fmtSignedMoney(value: number | null | undefined) {
  if (value == null) return "-";
  return `${value >= 0 ? "+" : "-"}$${Math.abs(value).toFixed(2)}`;
}

function fmtPct(value: number | null | undefined) {
  if (value == null) return "-";
  return `${value >= 0 ? "+" : ""}${(value * 100).toFixed(1)}%`;
}

function fmtQty(value: number | null | undefined) {
  if (value == null) return "-";
  return String(Number(value.toFixed(6)));
}

function pnlColor(value: number | null | undefined) {
  if (value == null) return "text-muted-foreground";
  return value >= 0 ? "text-emerald-400" : "text-red-400";
}

/** The neighbouring weekday, so the arrows skip weekends without a calendar lookup. */
function shiftWeekday(day: string, step: 1 | -1) {
  const date = new Date(`${day}T12:00:00Z`);
  do date.setUTCDate(date.getUTCDate() + step);
  while (date.getUTCDay() === 0 || date.getUTCDay() === 6);
  return date.toISOString().slice(0, 10);
}

/** The week's Monday when ``day`` is a Friday (the week's last trading day), so its review can name the week. */
function fridaysMonday(day: string | null) {
  if (!day) return null;
  const date = new Date(`${day}T12:00:00Z`);
  if (date.getUTCDay() !== 5) return null;
  date.setUTCDate(date.getUTCDate() - 4);
  return date.toISOString().slice(0, 10);
}

function tradeActivityKeys(trade: Trade) {
  return [dateKey(trade.opened_at), dateKey(trade.closed_at)].filter(Boolean) as string[];
}

function tradeActivityForDay(trade: Trade, day: string | null) {
  const openedToday = day != null && dateKey(trade.opened_at) === day;
  const closedToday = day != null && dateKey(trade.closed_at) === day;

  if (openedToday && closedToday) return "same_day";
  if (openedToday) return "opened";
  if (closedToday) return "closed";
  return "carry";
}

function tradeLabel(trade: Trade) {
  if (trade.instrument_type === "stock") return "Stock";
  const optionType = trade.option_type ? trade.option_type.toUpperCase() : "-";
  const strike = trade.strike != null ? fmtMoney(trade.strike, 0) : "-";
  return `${optionType} ${strike} ${trade.expiration ?? "-"}`;
}

const CHIP = "inline-flex h-[22px] items-center whitespace-nowrap rounded-md bg-secondary px-2 text-[11.5px] font-medium text-muted-foreground";
const AMBER_CHIP = "inline-flex h-[22px] items-center whitespace-nowrap rounded-md bg-primary/15 px-2 text-[11.5px] font-medium text-primary";

function currentMark(trade: Trade, quote: PositionQuote | undefined) {
  if (!quote) return null;
  if (trade.instrument_type === "stock") return quote.underlying_price;
  return quote.option_mid ?? quote.option_last_price;
}

function unrealizedPnl(trade: Trade, meta: OpenPositionMeta, quote: PositionQuote | undefined) {
  if (trade.status !== "open" || meta.qtyLeft <= 0) return null;
  return computeUnrealizedPnl(trade, meta, quote);
}

function buildFillChips(fill: Fill) {
  const chips: { label: string; value: string }[] = [];
  if (fill.underlying_price_at_fill != null) chips.push({ label: "Underlying", value: fmtMoney(fill.underlying_price_at_fill) });
  if (fill.vwap_at_fill != null) chips.push({ label: "VWAP", value: fmtMoney(fill.vwap_at_fill) });
  if (fill.iv_at_fill != null) chips.push({ label: "IV", value: `${(fill.iv_at_fill * 100).toFixed(1)}%` });
  if (fill.delta_at_fill != null) chips.push({ label: "Delta", value: fill.delta_at_fill.toFixed(2) });
  if (fill.gamma_at_fill != null) chips.push({ label: "Gamma", value: fill.gamma_at_fill.toFixed(4) });
  if (fill.theta_at_fill != null) chips.push({ label: "Theta", value: fill.theta_at_fill.toFixed(4) });
  if (fill.vega_at_fill != null) chips.push({ label: "Vega", value: fill.vega_at_fill.toFixed(4) });
  if (fill.rsi_14_at_fill != null) chips.push({ label: "RSI", value: fill.rsi_14_at_fill.toFixed(1) });
  if (fill.macd_at_fill != null) chips.push({ label: "MACD", value: fill.macd_at_fill.toFixed(3) });
  if (fill.macd_signal_at_fill != null) chips.push({ label: "Signal", value: fill.macd_signal_at_fill.toFixed(3) });
  if (fill.ema_9h_at_fill != null) chips.push({ label: "EMA 9h", value: fmtMoney(fill.ema_9h_at_fill) });
  if (fill.ema_9_at_fill != null) chips.push({ label: "EMA 9d", value: fmtMoney(fill.ema_9_at_fill) });
  if (fill.ema_20_at_fill != null) chips.push({ label: "EMA 20d", value: fmtMoney(fill.ema_20_at_fill) });
  if (fill.sma_20_at_fill != null) chips.push({ label: "SMA 20d", value: fmtMoney(fill.sma_20_at_fill) });
  if (fill.sma_50_at_fill != null) chips.push({ label: "SMA 50d", value: fmtMoney(fill.sma_50_at_fill) });
  return chips;
}

export default async function DailyReviewDayPage({ params }: { params: Promise<{ day: string }> }) {
  const access = await requireAccess();
  if (!access.owner && !access.grants.journal_read) return <PracticeRoutine day={(await params).day} />;
  const { day } = await params;
  const [trades, accounts] = await Promise.all([api.trades(), api.accounts()]);
  const accountMap = Object.fromEntries(accounts.map((account: Account) => [account.id, account]));
  const selectedDay = dateKey(`${day}T12:00:00`);

  const selectedTrades = selectedDay
    ? trades.filter((trade) => tradeActivityKeys(trade).includes(selectedDay))
    : [];

  const optionPositions = selectedTrades
    .filter((trade) => trade.instrument_type === "option" && trade.expiration && trade.strike != null && trade.option_type)
    .map((trade) => ({
      ticker: trade.ticker,
      expiration: trade.expiration!,
      strike: trade.strike!,
      option_type: trade.option_type!,
    }));

  const stockTickers = [
    ...new Set(selectedTrades.filter((trade) => trade.instrument_type === "stock").map((trade) => trade.ticker)),
  ];

  const [tradeFillEntries, optionQuotes, stockQuotes, savedDailyReview, dayJournal] = await Promise.all([
    Promise.all(selectedTrades.map(async (trade) => [trade.id, await api.tradeFills(trade.id)] as const)),
    optionPositions.length ? api.positionQuotes(optionPositions) : Promise.resolve([] as PositionQuote[]),
    stockTickers.length ? api.stockQuotes(stockTickers) : Promise.resolve({} as Record<string, number | null>),
    selectedDay ? api.dailyReview(selectedDay) : Promise.resolve(null),
    selectedDay && access.owner ? api.dayJournal(selectedDay).catch(() => null) : Promise.resolve(null),
  ]);

  const fillsByTradeId = Object.fromEntries(tradeFillEntries);

  // Fetch Alpaca context for all fills in one batch
  const allFillIds = Object.values(fillsByTradeId).flat().map((f) => f.id);
  const alpacaContexts: Record<string, FillMarketContext> = allFillIds.length
    ? await api.bulkFillMarketContext(allFillIds).catch(() => ({}))
    : {};
  const rows: TradeWithFills[] = selectedTrades.map((trade) => ({
    trade,
    fills: fillsByTradeId[trade.id] ?? [],
  }));

  const quotesByTradeId: Record<string, PositionQuote> = {};
  let optionQuoteIndex = 0;
  for (const trade of selectedTrades) {
    if (trade.instrument_type === "option" && trade.expiration && trade.strike != null && trade.option_type) {
      const quote = optionQuotes[optionQuoteIndex];
      if (quote) quotesByTradeId[trade.id] = quote;
      optionQuoteIndex += 1;
    } else if (trade.instrument_type === "stock") {
      quotesByTradeId[trade.id] = {
        ticker: trade.ticker,
        underlying_price: stockQuotes[trade.ticker] ?? null,
        option_last_price: null,
        option_bid: null,
        option_ask: null,
        option_mid: null,
        option_iv: null,
      };
    }
  }

  const openMetaByTradeId = Object.fromEntries(
    rows.map(({ trade, fills }) => [trade.id, buildOpenPositionMeta(trade, fills)] as const),
  );

  const unrealizedPnlByTradeId = Object.fromEntries(
    selectedTrades.map((trade) => {
      const meta = openMetaByTradeId[trade.id];
      return [trade.id, meta ? unrealizedPnl(trade, meta, quotesByTradeId[trade.id]) : null] as const;
    }),
  );

  const realizedPnl = selectedTrades.reduce((sum, trade) => sum + (trade.realized_pnl ?? 0), 0);
  const totalUnrealizedPnl = selectedTrades.reduce<number | null>((sum, trade) => {
    const pnl = unrealizedPnlByTradeId[trade.id];
    if (pnl == null) return sum;
    return (sum ?? 0) + pnl;
  }, null);
  const totalMarkedPnl = realizedPnl + (totalUnrealizedPnl ?? 0);
  const winners = selectedTrades.filter((trade) => (trade.realized_pnl ?? 0) > 0).length;
  const losers = selectedTrades.filter((trade) => (trade.realized_pnl ?? 0) < 0).length;
  const premiumRisked = selectedTrades.reduce((sum, trade) => sum + trade.total_premium_paid, 0);
  const fillCount = rows.reduce((sum, row) => sum + row.fills.length, 0);
  const dayLabel = selectedDay ? formatDate(selectedDay) : "No trade day";
  const sameDayTrades = selectedTrades.filter((trade) => tradeActivityForDay(trade, selectedDay) === "same_day");
  const openedOnlyTrades = selectedTrades.filter((trade) => tradeActivityForDay(trade, selectedDay) === "opened");
  const closedOnlyTrades = selectedTrades.filter((trade) => tradeActivityForDay(trade, selectedDay) === "closed");

  // Aggregate behavioral flags across entry fills for the Session Behavior card
  const entryFillContexts = Object.values(fillsByTradeId)
    .flat()
    .filter(isEntryFill)
    .map((f) => alpacaContexts[f.id])
    .filter(Boolean) as FillMarketContext[];

  const flagCount = (key: keyof FillMarketContext) =>
    entryFillContexts.filter((ctx) => ctx[key] === 1).length;

  const sessionBehavior = entryFillContexts.length > 0 ? {
    total: entryFillContexts.length,
    chase: flagCount("is_chase_entry"),
    trendAligned: flagCount("is_trend_aligned"),
    lateMove: flagCount("is_late_move"),
    vwapReclaim: flagCount("is_vwap_reclaim"),
    orBreakout: flagCount("is_opening_range_breakout"),
    pmBreakout: flagCount("is_premarket_breakout"),
    nearResistance: flagCount("is_near_resistance_on_call_entry"),
    nearSupport: flagCount("is_near_support_on_put_entry"),
  } : null;

  const tickerSummary = [...new Set(selectedTrades.map((trade) => trade.ticker))].map((ticker) => {
    const tickerTrades = selectedTrades.filter((trade) => trade.ticker === ticker);
    return {
      ticker,
      count: tickerTrades.length,
      realizedPnl: tickerTrades.reduce((sum, trade) => sum + (trade.realized_pnl ?? 0), 0),
      unrealizedPnl: tickerTrades.reduce<number | null>((sum, trade) => {
        const pnl = unrealizedPnlByTradeId[trade.id];
        if (pnl == null) return sum;
        return (sum ?? 0) + pnl;
      }, null),
      open: tickerTrades.filter((trade) => trade.status === "open").length,
    };
  });

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <nav aria-label="Daily Review navigation" className="-ml-2 flex flex-wrap items-center text-sm text-muted-foreground">
            {[
              { href: access.owner ? "/dashboard" : "/", label: "Back to Dashboard" }, // the owner's `/` may be the desk
              { href: "/daily", label: "Review Calendar" },
              ...(selectedDay ? [{ href: `/daily/${shiftWeekday(selectedDay, -1)}`, label: "← Previous day" }] : []),
              // No next day from today: a future day has nothing to review.
              ...(selectedDay && shiftWeekday(selectedDay, 1) <= newYorkToday() ? [{ href: `/daily/${shiftWeekday(selectedDay, 1)}`, label: "Next day →" }] : []),
            ].map((link) => (
              <a key={link.href} href={link.href} className="inline-flex min-h-11 items-center whitespace-nowrap px-2 hover:text-foreground md:min-h-8">
                {link.label}
              </a>
            ))}
          </nav>
          <div className="mt-2 flex flex-wrap items-baseline gap-x-2">
            <h1 className="text-xl font-semibold">Daily Review</h1>
            <span className="text-sm tabular-nums text-muted-foreground">
              {selectedDay === newYorkToday() ? "Current trading day" : "Trading day"}: {dayLabel}
            </span>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {fridaysMonday(selectedDay) && <ReviewMyWeek monday={fridaysMonday(selectedDay)!} />}
          <a
            href="/trades"
            className="inline-flex min-h-11 items-center rounded-md border px-3 text-sm font-medium hover:bg-secondary sm:min-h-9"
          >
            All Trades
          </a>
        </div>
      </div>

      <nav
        aria-label="Sections of this day"
        className="sticky top-[calc(3.5625rem+env(safe-area-inset-top))] z-20 -mx-1 flex gap-1 overflow-x-auto rounded-lg border bg-card/95 p-1 backdrop-blur md:top-0"
      >
        {[
          ...(access.owner ? [{ href: "#jo", label: "Jo's day" }, { href: "#thoughts", label: "Your thoughts" }] : []),
          { href: "#ai-review", label: "AI analysis" },
          { href: "#trades", label: `Trades · ${selectedTrades.length}` },
          { href: "#practice", label: "Practice" },
        ].map((section) => (
          <a
            key={section.href}
            href={section.href}
            className="inline-flex min-h-11 shrink-0 items-center rounded-md px-3 text-sm text-muted-foreground hover:bg-secondary hover:text-foreground md:min-h-9"
          >
            {section.label}
          </a>
        ))}
      </nav>

      {access.owner && selectedDay && <JoDay key={selectedDay} day={selectedDay} live={selectedDay === newYorkToday()} />}

      <DayReviewWorkflow
        key={`${selectedDay ?? "invalid-day"}:${savedDailyReview?.generated_at ?? "no-review"}`}
        tradeCount={selectedTrades.length}
        day={selectedDay ?? null}
        dayLabel={dayLabel}
        tradeIds={selectedTrades.map((trade) => trade.id)}
        initialReview={savedDailyReview?.review ?? null}
        initialGeneratedAt={savedDailyReview?.generated_at ?? null}
        initialJournal={dayJournal}
        canEditJournal={access.owner}
      />

      <div id="trades" className="scroll-mt-28 space-y-4 md:scroll-mt-16">
      <section aria-label="Day totals" className="rounded-lg border bg-card">
        <h2 className="border-b px-3.5 py-2.5 text-[13.5px] font-semibold tracking-tight">Trades</h2>
        <dl className="grid p-4 grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-4 xl:grid-cols-7">
          <DayFigure label="Trades" value={String(selectedTrades.length)} />
          <DayFigure label="Fills" value={String(fillCount)} />
          <DayFigure label="Realized P&L" value={fmtSignedMoney(realizedPnl)} valueClass={pnlColor(realizedPnl)} />
          <DayFigure
            label="Unrealized P&L"
            value={totalUnrealizedPnl != null ? fmtSignedMoney(totalUnrealizedPnl) : "-"}
            valueClass={pnlColor(totalUnrealizedPnl)}
          />
          <DayFigure label="Marked P&L" value={fmtSignedMoney(totalMarkedPnl)} valueClass={pnlColor(totalMarkedPnl)} />
          <DayFigure label="Premium Risked" value={fmtMoney(premiumRisked, 0)} />
          <DayFigure label="Winners / Losers" value={`${winners} / ${losers}`} />
        </dl>
      </section>

      {selectedTrades.length === 0 ? (
        <section className="rounded-lg border bg-card p-8 text-center text-sm text-muted-foreground">
          No trades found yet.
        </section>
      ) : (
        <>
          <section className="grid gap-4 lg:grid-cols-3">
            {tickerSummary.map((summary) => (
              <DashboardCard key={summary.ticker} title={summary.ticker} action={
                <span className={`text-sm tabular-nums ${pnlColor(summary.realizedPnl + (summary.unrealizedPnl ?? 0))}`}>
                  {fmtSignedMoney(summary.realizedPnl + (summary.unrealizedPnl ?? 0))}
                </span>}>
                <div className="grid grid-cols-2 gap-3 text-sm">
                  <MiniMetric label="Trades" value={String(summary.count)} />
                  <MiniMetric label="Still Open" value={String(summary.open)} />
                  <MiniMetric label="Realized" value={fmtSignedMoney(summary.realizedPnl)} valueClass={pnlColor(summary.realizedPnl)} />
                  <MiniMetric
                    label="Unrealized"
                    value={summary.unrealizedPnl != null ? fmtSignedMoney(summary.unrealizedPnl) : "-"}
                    valueClass={pnlColor(summary.unrealizedPnl)}
                  />
                </div>
              </DashboardCard>
            ))}
          </section>

          <section className="grid gap-4 lg:grid-cols-3">
            <ActivityList title="Opened & Closed Today" trades={sameDayTrades} selectedDay={selectedDay} />
            <ActivityList title="Opened Today" trades={openedOnlyTrades} selectedDay={selectedDay} />
            <ActivityList title="Closed From Prior Days" trades={closedOnlyTrades} selectedDay={selectedDay} />
          </section>

          {sessionBehavior && (
            <DashboardCard title="Session Behavior" action={
              <span className="text-xs text-muted-foreground">
                {sessionBehavior.total} entry fill{sessionBehavior.total !== 1 ? "s" : ""} with context
              </span>}>
              <div className="flex flex-wrap gap-2">
                <BehaviorChip label="Chase" count={sessionBehavior.chase} total={sessionBehavior.total} warn />
                <BehaviorChip label="Trend Aligned" count={sessionBehavior.trendAligned} total={sessionBehavior.total} good />
                <BehaviorChip label="Late Move" count={sessionBehavior.lateMove} total={sessionBehavior.total} warn />
                <BehaviorChip label="VWAP Reclaim" count={sessionBehavior.vwapReclaim} total={sessionBehavior.total} good />
                <BehaviorChip label="OR Breakout" count={sessionBehavior.orBreakout} total={sessionBehavior.total} good />
                <BehaviorChip label="PM Breakout" count={sessionBehavior.pmBreakout} total={sessionBehavior.total} good />
                <BehaviorChip label="Near Resistance" count={sessionBehavior.nearResistance} total={sessionBehavior.total} warn />
                <BehaviorChip label="Near Support" count={sessionBehavior.nearSupport} total={sessionBehavior.total} good />
              </div>
            </DashboardCard>
          )}

          <section className="overflow-x-auto rounded-lg border bg-card">
            <div className="border-b px-3.5 py-2.5">
              <h2 className="text-[13.5px] font-semibold tracking-tight">
                Trade Snapshot
              </h2>
            </div>
            <table className="w-full min-w-[1320px] text-sm">
              <thead className="border-b text-xs font-medium text-muted-foreground">
                <tr>
                  <Th>Trade</Th>
                  <Th>Activity</Th>
                  <Th>Account</Th>
                  <Th>Status</Th>
                  <Th>Qty</Th>
                  <Th>Entry</Th>
                  <Th>Exit</Th>
                  <Th>Mark</Th>
                  <Th>Realized P&L</Th>
                  <Th>Unreal. P&L</Th>
                  <Th>P&L %</Th>
                  <Th>Hold</Th>
                  <Th>Opened</Th>
                  <Th>Closed</Th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {selectedTrades.map((trade) => {
                  const account = accountMap[trade.account_id];
                  const quote = quotesByTradeId[trade.id];
                  const mark = currentMark(trade, quote);
                  const openMeta = openMetaByTradeId[trade.id];
                  const unrealized = unrealizedPnlByTradeId[trade.id];
                  const activity = tradeActivityForDay(trade, selectedDay);

                  return (
                    <tr key={trade.id} className="hover:bg-muted/50">
                      <Td>
                        <a href={`/trades/${trade.id}?returnTo=${encodeURIComponent(`/daily/${selectedDay}`)}`} className="font-semibold hover:underline">
                          {trade.ticker}
                        </a>
                        <div className="text-xs text-muted-foreground">{tradeLabel(trade)}</div>
                      </Td>
                      <Td>
                        <ActivityBadge activity={activity} />
                      </Td>
                      <Td>
                        <span className={CHIP}>
                          {account?.name ?? "-"}
                        </span>
                      </Td>
                      <Td>
                        <span className={CHIP}>
                          {trade.status}
                        </span>
                      </Td>
                      <Td num>
                        {openMeta && trade.status === "open" ? (
                          <div className="flex flex-col">
                            <span>{fmtQty(openMeta.qtyLeft)}</span>
                            <span className="text-xs text-muted-foreground">
                              opened {fmtQty(openMeta.openedQty)}
                              {openMeta.exitedQty > 0 ? ` | trimmed ${fmtQty(openMeta.exitedQty)}` : ""}
                            </span>
                          </div>
                        ) : (
                          fmtQty(trade.contracts)
                        )}
                      </Td>
                      <Td num>{fmtMoney(trade.avg_entry_premium)}</Td>
                      <Td num>{fmtMoney(trade.avg_exit_premium)}</Td>
                      <Td num>
                        <div className="flex flex-col">
                          <span>{fmtMoney(mark)}</span>
                          {quote?.underlying_price != null && trade.instrument_type === "option" && (
                            <span className="text-xs text-muted-foreground">U {fmtMoney(quote.underlying_price)}</span>
                          )}
                        </div>
                      </Td>
                      <Td num>
                        <span className={pnlColor(trade.realized_pnl)}>{fmtSignedMoney(trade.realized_pnl)}</span>
                      </Td>
                      <Td num>
                        <span className={pnlColor(unrealized)}>{unrealized != null ? fmtSignedMoney(unrealized) : "-"}</span>
                      </Td>
                      <Td num>
                        <span className={pnlColor(trade.pnl_pct)}>{fmtPct(trade.pnl_pct)}</span>
                      </Td>
                      <Td num>{trade.hold_duration_mins != null ? formatHoldDuration(trade.hold_duration_mins) : "-"}</Td>
                      <Td num>{formatDateTime(trade.opened_at)}</Td>
                      <Td num>{formatDateTime(trade.closed_at)}</Td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </section>

          <section className="rounded-lg border bg-card">
            <div className="border-b px-3.5 py-2.5">
              <h2 className="text-[13.5px] font-semibold tracking-tight">
                Fill Timeline
              </h2>
              <p className="mt-1 text-xs text-muted-foreground">
                Includes every fill attached to the selected trades, including earlier entries for trades closed on this day.
              </p>
            </div>

            {rows.map(({ trade, fills }) => (
              <div key={trade.id} className="border-b last:border-b-0">
                <div className="flex flex-wrap items-center justify-between gap-3 border-b bg-secondary/40 px-3.5 py-2.5">
                  <div>
                    <a href={`/trades/${trade.id}?returnTo=${encodeURIComponent(`/daily/${selectedDay}`)}`} className="font-semibold hover:underline">
                      {trade.ticker}
                    </a>
                    <span className="ml-2 text-sm text-muted-foreground">{tradeLabel(trade)}</span>
                  </div>
                  <span className={`text-sm tabular-nums ${pnlColor(trade.realized_pnl)}`}>{fmtSignedMoney(trade.realized_pnl)}</span>
                </div>
                <div className="divide-y divide-border">
                  {fills.map((fill) => {
                    const chips = buildFillChips(fill);
                    const ctx = alpacaContexts[fill.id] ?? null;
                    const alpacaChips = buildAlpacaChips(ctx);
                    const activeFlags = ctx ? buildActiveFlags(ctx) : [];
                    return (
                      <a
                        key={fill.id}
                        href={`/fills/${fill.id}?returnTo=${encodeURIComponent(`/daily/${selectedDay}`)}`}
                        className="block px-3.5 py-3 transition-colors hover:bg-muted/50"
                      >
                        <div className="flex flex-wrap items-center gap-3 text-sm">
                          <span className={`${CHIP} w-16 justify-center ${isEntryFill(fill) ? "!text-foreground" : ""}`}>
                            {isEntryFill(fill) ? "ENTRY" : "EXIT"}
                          </span>
                          <span className="tabular-nums text-muted-foreground">{formatDateTime(fill.executed_at)}</span>
                          <span className="font-medium tabular-nums">
                            {fill.side} {fmtQty(fill.contracts)} @ {fmtMoney(fill.price)}
                          </span>
                          <span className="tabular-nums text-muted-foreground">
                            {fmtMoney(fill.contracts * fill.price)} notional
                          </span>
                          {activeFlags.map((flag) => (
                            <span key={flag.label} className={flag.cls}>
                              {flag.label}
                            </span>
                          ))}
                        </div>
                        {chips.length > 0 && (
                          <div className="mt-3 flex flex-wrap gap-1.5">
                            {chips.map((chip) => (
                              <span key={`${fill.id}-${chip.label}`} className={CHIP}>
                                {chip.label}{" "}<span className="ml-1 tabular-nums text-foreground">{chip.value}</span>
                              </span>
                            ))}
                          </div>
                        )}
                        {alpacaChips.length > 0 && (
                          <div className="mt-1.5 flex flex-wrap gap-1.5">
                            {alpacaChips.map((chip) => (
                              <span key={`${fill.id}-alpaca-${chip.label}`} className={CHIP}>
                                {chip.label}{" "}<span className="ml-1 tabular-nums text-foreground">{chip.value}</span>
                              </span>
                            ))}
                          </div>
                        )}
                      </a>
                    );
                  })}
                </div>
              </div>
            ))}
          </section>
        </>
      )}

      </div>

      {/* Practice is separate from the journal day, so it follows the day's own review and trades. */}
      <div id="practice" className="scroll-mt-28 md:scroll-mt-16"><PracticeRoutine day={selectedDay} /></div>
    </div>
  );
}

function DayFigure({ label, value, valueClass = "text-foreground" }: { label: string; value: string; valueClass?: string }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className={`mt-0.5 text-lg font-medium tabular-nums ${valueClass}`}>{value}</dd>
    </div>
  );
}

function MiniMetric({
  label,
  value,
  valueClass = "text-foreground",
}: {
  label: string;
  value: string;
  valueClass?: string;
}) {
  return (
    <div>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={`mt-1 font-medium tabular-nums ${valueClass}`}>{value}</p>
    </div>
  );
}

function ActivityList({
  title,
  trades,
  selectedDay,
}: {
  title: string;
  trades: Trade[];
  selectedDay: string | null;
}) {
  return (
    <DashboardCard title={title} action={<span className="text-sm tabular-nums text-muted-foreground">{trades.length}</span>}>
      {trades.length === 0 ? (
        <p className="text-sm text-muted-foreground">None</p>
      ) : (
        <div className="space-y-2">
          {trades.map((trade) => (
            <a key={trade.id} href={`/trades/${trade.id}?returnTo=${encodeURIComponent(`/daily/${selectedDay}`)}`} className="flex items-center justify-between gap-3 rounded-md border bg-background/40 px-3 py-2 text-sm hover:bg-muted/30">
              <span className="font-medium">{trade.ticker}</span>
              <ActivityBadge activity={tradeActivityForDay(trade, selectedDay)} />
            </a>
          ))}
        </div>
      )}
    </DashboardCard>
  );
}

function ActivityBadge({ activity }: { activity: string }) {
  const label = activity === "same_day" ? "Same Day" : activity === "opened" ? "Opened" : activity === "closed" ? "Closed" : "Carry";
  return <span className={CHIP}>{label}</span>;
}

function Th({ children }: { children: React.ReactNode }) {
  return <th className="px-4 py-2 text-left font-medium">{children}</th>;
}

function Td({ children, num }: { children: React.ReactNode; num?: boolean }) {
  return <td className={`px-4 py-3 align-top ${num ? "tabular-nums" : ""}`}>{children}</td>;
}

function buildAlpacaChips(ctx: FillMarketContext | null): { label: string; value: string }[] {
  if (!ctx) return [];
  const chips: { label: string; value: string }[] = [];
  if (ctx.entry_vs_vwap_pct != null) {
    const v = ctx.entry_vs_vwap_pct;
    chips.push({ label: "vs VWAP", value: `${v >= 0 ? "+" : ""}${v.toFixed(2)}%` });
  }
  if (ctx.simple_relative_volume != null) chips.push({ label: "RVOL", value: ctx.simple_relative_volume.toFixed(2) + "x" });
  if (ctx.entry_rsi_14 != null) chips.push({ label: "RSI", value: ctx.entry_rsi_14.toFixed(1) });
  if (ctx.entry_gap_pct != null) {
    const v = ctx.entry_gap_pct;
    chips.push({ label: "Gap", value: `${v >= 0 ? "+" : ""}${v.toFixed(2)}%` });
  }
  if (ctx.entry_day_range_used_pct != null) chips.push({ label: "Range used", value: `${ctx.entry_day_range_used_pct.toFixed(1)}%` });
  return chips;
}

function buildActiveFlags(ctx: FillMarketContext): { label: string; cls: string }[] {
  const flags: { label: string; cls: string }[] = [];
  if (ctx.is_chase_entry === 1) flags.push({ label: "Chase", cls: AMBER_CHIP });
  if (ctx.is_late_move === 1) flags.push({ label: "Late Move", cls: AMBER_CHIP });
  if (ctx.is_near_resistance_on_call_entry === 1) flags.push({ label: "Near Resistance", cls: AMBER_CHIP });
  if (ctx.is_near_support_on_put_entry === 1) flags.push({ label: "Near Support", cls: AMBER_CHIP });
  if (ctx.is_trend_aligned === 1) flags.push({ label: "Trend Aligned", cls: CHIP });
  if (ctx.is_vwap_reclaim === 1) flags.push({ label: "VWAP Reclaim", cls: CHIP });
  if (ctx.is_opening_range_breakout === 1) flags.push({ label: "OR Breakout", cls: CHIP });
  if (ctx.is_premarket_breakout === 1) flags.push({ label: "PM Breakout", cls: CHIP });
  if (ctx.is_overnight === 1) flags.push({ label: "Outside regular hours", cls: CHIP });
  return flags;
}

function BehaviorChip({
  label,
  count,
  total,
  warn = false,
}: {
  label: string;
  count: number;
  total: number;
  warn?: boolean;
  good?: boolean;
}) {
  const active = count > 0;
  const cls = !active ? `${CHIP} !bg-transparent` : warn ? AMBER_CHIP : `${CHIP} !text-foreground`;
  return (
    <span className={cls}>
      {label}
      {active && <span className="ml-1.5 tabular-nums">{count}/{total}</span>}
    </span>
  );
}
