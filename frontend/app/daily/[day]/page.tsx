import DailyAiPanel from "@/components/DailyAiPanel";
import { api, Account, Fill, PositionQuote, Trade } from "@/lib/api";

type TradeWithFills = {
  trade: Trade;
  fills: Fill[];
};

type OpenPositionMeta = {
  openedQty: number;
  exitedQty: number;
  qtyLeft: number;
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
  return new Date(value).toLocaleString();
}

function fmtMoney(value: number | null | undefined, decimals = 2) {
  if (value == null) return "-";
  return `$${value.toFixed(decimals)}`;
}

function fmtSignedMoney(value: number | null | undefined) {
  if (value == null) return "-";
  return `${value >= 0 ? "+" : ""}$${value.toFixed(2)}`;
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

function isEntryFill(fill: Fill) {
  return fill.side === "buy_to_open" || fill.side === "sell_to_open" || fill.side === "buy";
}

function buildOpenPositionMeta(trade: Trade, fills: Fill[]): OpenPositionMeta {
  const entryQty = fills.filter(isEntryFill).reduce((sum, fill) => sum + fill.contracts, 0);
  const exitedQty = fills.filter((fill) => !isEntryFill(fill)).reduce((sum, fill) => sum + fill.contracts, 0);
  const openedQty = entryQty || trade.contracts;
  const qtyLeft = Math.max(openedQty - exitedQty, 0);

  return {
    openedQty,
    exitedQty,
    qtyLeft,
  };
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

function accountBadgeClass(account: Account | undefined) {
  return account?.type === "roth_ira"
    ? "bg-purple-900/40 text-purple-300"
    : "bg-sky-900/40 text-sky-300";
}

function currentMark(trade: Trade, quote: PositionQuote | undefined) {
  if (!quote) return null;
  if (trade.instrument_type === "stock") return quote.underlying_price;
  return quote.option_mid ?? quote.option_last_price;
}

function markForPnl(trade: Trade, quote: PositionQuote | undefined) {
  const mark = currentMark(trade, quote);
  if (mark == null) return null;
  return trade.instrument_type === "option" ? mark * 100 : mark;
}

function unrealizedPnl(trade: Trade, meta: OpenPositionMeta, quote: PositionQuote | undefined) {
  if (trade.status !== "open" || meta.qtyLeft <= 0) return null;
  const mark = markForPnl(trade, quote);
  if (mark == null) return null;
  return (mark - trade.avg_entry_premium) * meta.qtyLeft;
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
  const { day } = await params;
  const [trades, accounts] = await Promise.all([api.trades(), api.accounts()]);
  const accountMap = Object.fromEntries(accounts.map((account: Account) => [account.id, account]));
  const todayKey = dateKey(new Date().toISOString());
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

  const [tradeFillEntries, optionQuotes, stockQuotes, savedDailyReview] = await Promise.all([
    Promise.all(selectedTrades.map(async (trade) => [trade.id, await api.tradeFills(trade.id)] as const)),
    optionPositions.length ? api.positionQuotes(optionPositions) : Promise.resolve([] as PositionQuote[]),
    stockTickers.length ? api.stockQuotes(stockTickers) : Promise.resolve({} as Record<string, number | null>),
    selectedDay ? api.dailyReview(selectedDay) : Promise.resolve(null),
  ]);

  const fillsByTradeId = Object.fromEntries(tradeFillEntries);
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
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <a href="/" className="text-sm text-muted-foreground hover:text-foreground">
            Back to Dashboard
          </a>
          <a href="/daily" className="ml-4 text-sm text-muted-foreground hover:text-foreground">
            Review Calendar
          </a>
          <h1 className="mt-2 text-xl font-semibold text-foreground">Daily Review</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {selectedDay === todayKey ? "Current trading day" : "Most recent trading day"}: {dayLabel}
          </p>
        </div>
        <a
          href="/trades"
          className="rounded border border-border px-3 py-2 text-sm font-medium text-foreground transition-colors hover:bg-secondary"
        >
          All Trades
        </a>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-7">
        <StatCard label="Trades" value={String(selectedTrades.length)} />
        <StatCard label="Fills" value={String(fillCount)} />
        <StatCard label="Realized P&L" value={fmtSignedMoney(realizedPnl)} valueClass={pnlColor(realizedPnl)} />
        <StatCard
          label="Unrealized P&L"
          value={totalUnrealizedPnl != null ? fmtSignedMoney(totalUnrealizedPnl) : "-"}
          valueClass={pnlColor(totalUnrealizedPnl)}
        />
        <StatCard label="Marked P&L" value={fmtSignedMoney(totalMarkedPnl)} valueClass={pnlColor(totalMarkedPnl)} />
        <StatCard label="Premium Risked" value={fmtMoney(premiumRisked, 0)} />
        <StatCard label="Winners / Losers" value={`${winners} / ${losers}`} />
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <StatCard label="Opened & Closed" value={String(sameDayTrades.length)} />
        <StatCard label="Opened Only" value={String(openedOnlyTrades.length)} />
        <StatCard label="Closed From Prior" value={String(closedOnlyTrades.length)} />
      </div>

      <DailyAiPanel
        tradeCount={selectedTrades.length}
        day={selectedDay ?? null}
        dayLabel={dayLabel}
        tradeIds={selectedTrades.map((trade) => trade.id)}
        initialReview={savedDailyReview?.review ?? null}
        initialGeneratedAt={savedDailyReview?.generated_at ?? null}
      />

      {selectedTrades.length === 0 ? (
        <section className="rounded-lg border bg-card p-8 text-center text-sm text-muted-foreground">
          No trades found yet.
        </section>
      ) : (
        <>
          <section className="grid gap-4 lg:grid-cols-3">
            {tickerSummary.map((summary) => (
              <div key={summary.ticker} className="rounded-lg border bg-card p-4">
                <div className="flex items-center justify-between gap-3">
                  <h2 className="text-lg font-semibold">{summary.ticker}</h2>
                  <span className={pnlColor(summary.realizedPnl + (summary.unrealizedPnl ?? 0))}>
                    {fmtSignedMoney(summary.realizedPnl + (summary.unrealizedPnl ?? 0))}
                  </span>
                </div>
                <div className="mt-3 grid grid-cols-2 gap-3 text-sm">
                  <MiniMetric label="Trades" value={String(summary.count)} />
                  <MiniMetric label="Still Open" value={String(summary.open)} />
                  <MiniMetric label="Realized" value={fmtSignedMoney(summary.realizedPnl)} valueClass={pnlColor(summary.realizedPnl)} />
                  <MiniMetric
                    label="Unrealized"
                    value={summary.unrealizedPnl != null ? fmtSignedMoney(summary.unrealizedPnl) : "-"}
                    valueClass={pnlColor(summary.unrealizedPnl)}
                  />
                </div>
              </div>
            ))}
          </section>

          <section className="grid gap-4 lg:grid-cols-3">
            <ActivityList title="Opened & Closed Today" trades={sameDayTrades} selectedDay={selectedDay} />
            <ActivityList title="Opened Today" trades={openedOnlyTrades} selectedDay={selectedDay} />
            <ActivityList title="Closed From Prior Days" trades={closedOnlyTrades} selectedDay={selectedDay} />
          </section>

          <section className="overflow-x-auto rounded-lg border bg-card">
            <div className="border-b px-5 py-4">
              <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                Trade Snapshot
              </h2>
            </div>
            <table className="w-full min-w-[1320px] text-sm">
              <thead className="bg-muted text-xs uppercase text-muted-foreground">
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
                        <a href={`/trades/${trade.id}`} className="font-semibold hover:underline">
                          {trade.ticker}
                        </a>
                        <div className="text-xs text-muted-foreground">{tradeLabel(trade)}</div>
                      </Td>
                      <Td>
                        <ActivityBadge activity={activity} />
                      </Td>
                      <Td>
                        <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${accountBadgeClass(account)}`}>
                          {account?.name ?? "-"}
                        </span>
                      </Td>
                      <Td>
                        <span className="rounded bg-muted px-1.5 py-0.5 text-xs font-medium text-foreground/80">
                          {trade.status}
                        </span>
                      </Td>
                      <Td>
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
                      <Td>{fmtMoney(trade.avg_entry_premium)}</Td>
                      <Td>{fmtMoney(trade.avg_exit_premium)}</Td>
                      <Td>
                        <div className="flex flex-col">
                          <span>{fmtMoney(mark)}</span>
                          {quote?.underlying_price != null && trade.instrument_type === "option" && (
                            <span className="text-xs text-muted-foreground">U {fmtMoney(quote.underlying_price)}</span>
                          )}
                        </div>
                      </Td>
                      <Td>
                        <span className={pnlColor(trade.realized_pnl)}>{fmtSignedMoney(trade.realized_pnl)}</span>
                      </Td>
                      <Td>
                        <span className={pnlColor(unrealized)}>{unrealized != null ? fmtSignedMoney(unrealized) : "-"}</span>
                      </Td>
                      <Td>
                        <span className={pnlColor(trade.pnl_pct)}>{fmtPct(trade.pnl_pct)}</span>
                      </Td>
                      <Td>{trade.hold_duration_mins != null ? `${Math.round(trade.hold_duration_mins)}m` : "-"}</Td>
                      <Td>{formatDateTime(trade.opened_at)}</Td>
                      <Td>{formatDateTime(trade.closed_at)}</Td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </section>

          <section className="space-y-4">
            <div>
              <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                Fill Timeline
              </h2>
              <p className="mt-1 text-sm text-muted-foreground">
                Includes every fill attached to the selected trades, including earlier entries for trades closed on this day.
              </p>
            </div>

            {rows.map(({ trade, fills }) => (
              <div key={trade.id} className="rounded-lg border bg-card">
                <div className="flex flex-wrap items-center justify-between gap-3 border-b px-5 py-4">
                  <div>
                    <a href={`/trades/${trade.id}`} className="font-semibold hover:underline">
                      {trade.ticker}
                    </a>
                    <span className="ml-2 text-sm text-muted-foreground">{tradeLabel(trade)}</span>
                  </div>
                  <span className={pnlColor(trade.realized_pnl)}>{fmtSignedMoney(trade.realized_pnl)}</span>
                </div>
                <div className="divide-y divide-border">
                  {fills.map((fill) => {
                    const chips = buildFillChips(fill);
                    return (
                      <a
                        key={fill.id}
                        href={`/fills/${fill.id}?returnTo=${encodeURIComponent(`/daily/${selectedDay}`)}`}
                        className="block px-5 py-4 transition-colors hover:bg-muted/50"
                      >
                        <div className="flex flex-wrap items-center gap-3 text-sm">
                          <span
                            className={`w-16 rounded px-2 py-0.5 text-center text-xs font-semibold ${
                              isEntryFill(fill) ? "bg-blue-900/40 text-blue-300" : "bg-orange-900/40 text-orange-300"
                            }`}
                          >
                            {isEntryFill(fill) ? "ENTRY" : "EXIT"}
                          </span>
                          <span className="text-muted-foreground">{formatDateTime(fill.executed_at)}</span>
                          <span className="font-medium">
                            {fill.side} {fmtQty(fill.contracts)} @ {fmtMoney(fill.price)}
                          </span>
                          <span className="text-muted-foreground">
                            {fmtMoney(fill.contracts * fill.price)} notional
                          </span>
                        </div>
                        {chips.length > 0 && (
                          <div className="mt-3 flex flex-wrap gap-1.5">
                            {chips.map((chip) => (
                              <span key={`${fill.id}-${chip.label}`} className="rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">
                                <span className="text-foreground/60">{chip.label}</span> {chip.value}
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
  );
}

function StatCard({
  label,
  value,
  valueClass = "text-foreground",
}: {
  label: string;
  value: string;
  valueClass?: string;
}) {
  return (
    <div className="rounded-lg border bg-card p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className={`mt-1 text-2xl font-semibold tabular-nums ${valueClass}`}>{value}</p>
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
      <p className="text-xs uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className={`mt-1 font-semibold ${valueClass}`}>{value}</p>
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
    <div className="rounded-lg border bg-card p-4">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">{title}</h2>
        <span className="text-sm font-semibold text-foreground">{trades.length}</span>
      </div>
      {trades.length === 0 ? (
        <p className="mt-3 text-sm text-muted-foreground">None</p>
      ) : (
        <div className="mt-3 space-y-2">
          {trades.map((trade) => (
            <a key={trade.id} href={`/trades/${trade.id}`} className="flex items-center justify-between gap-3 rounded bg-muted px-3 py-2 text-sm hover:bg-muted/80">
              <span className="font-medium">{trade.ticker}</span>
              <ActivityBadge activity={tradeActivityForDay(trade, selectedDay)} />
            </a>
          ))}
        </div>
      )}
    </div>
  );
}

function ActivityBadge({ activity }: { activity: string }) {
  const config =
    activity === "same_day"
      ? { label: "Same Day", cls: "bg-blue-900/40 text-blue-300" }
      : activity === "opened"
        ? { label: "Opened", cls: "bg-emerald-900/40 text-emerald-300" }
        : activity === "closed"
          ? { label: "Closed", cls: "bg-orange-900/40 text-orange-300" }
          : { label: "Carry", cls: "bg-muted text-muted-foreground" };

  return <span className={`whitespace-nowrap rounded px-1.5 py-0.5 text-xs font-medium ${config.cls}`}>{config.label}</span>;
}

function Th({ children }: { children: React.ReactNode }) {
  return <th className="px-4 py-2 text-left font-medium">{children}</th>;
}

function Td({ children }: { children: React.ReactNode }) {
  return <td className="px-4 py-3 align-top">{children}</td>;
}
