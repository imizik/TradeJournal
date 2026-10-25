"use client";

import { use, useEffect, useState } from "react";
import { api, Fill, FillMarketContext, Trade, TradePathMetrics } from "@/lib/api";
import AlpacaContextSection from "@/components/AlpacaContextSection";
import TradePathSection from "@/components/TradePathSection";
import AuditPanel from "@/components/AuditPanel";
import Link from "next/link";
import { ChartCandlestick } from "lucide-react";
import { chartLink, newYorkSeconds } from "@/lib/chartJournal";
import { formatHoldDuration } from "@/lib/dashboard";
import { fetchTradePlans, type Capture } from "@/lib/captures";
import PlanSummary from "@/components/charts/PlanSummary";
import TradeAdvice from "@/components/TradeAdvice";
import TradePhoneAlerts from "@/components/TradePhoneAlerts";
import { useCopilotOn } from "@/components/copilot/useCopilotOn";
import { copilotLabHref } from "@/lib/copilot";

function pnlColor(val: number | null | undefined) {
  if (val == null) return "text-muted-foreground";
  return val >= 0 ? "text-emerald-400" : "text-red-400";
}

function fmt$(val: number | null | undefined) {
  if (val == null) return "-";
  return `${val >= 0 ? "+" : "-"}$${Math.abs(val).toFixed(2)}`;
}

function fmtPct(val: number | null | undefined) {
  if (val == null) return "-";
  return `${val >= 0 ? "+" : ""}${(val * 100).toFixed(1)}%`;
}

function Row({ label, value, valueClass }: { label: string; value: string; valueClass?: string }) {
  return (
    <div className="flex justify-between border-b border-border py-2 text-sm last:border-0">
      <span className="text-muted-foreground">{label}</span>
      <span className={`font-medium ${valueClass ?? "text-foreground"}`}>{value}</span>
    </div>
  );
}

function isEntryFill(fill: Fill) {
  return fill.side === "buy_to_open" || fill.side === "sell_to_open" || fill.side === "buy";
}

function tradeTitle(trade: Trade) {
  if (trade.instrument_type === "stock") {
    return `${trade.ticker} | stock`;
  }
  return `${trade.ticker} $${trade.strike} ${trade.option_type} | ${trade.expiration}`;
}

/** Trade times in New York time, labelled, whatever the viewing device's zone. */
const etTime = (value: string) => `${new Date(value).toLocaleString("en-US", { timeZone: "America/New_York", month: "numeric", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit", second: "2-digit" })} ET`;

export default function TradeDetailPage({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<{ returnTo?: string; alert?: string }> }) {
  const { id } = use(params);
  // Back returns to the page that opened the trade (e.g. a Daily Review day); only same-site paths are followed.
  const { returnTo: from, alert } = use(searchParams);
  const back = from && from.startsWith("/") && !from.startsWith("//") ? { href: from, label: from.startsWith("/daily") ? "Back to Daily Review" : "Back" } : { href: "/trades", label: "Back to Trades" };
  const [tradeError, setTradeError] = useState(false);
  const [trade, setTrade] = useState<Trade | null>(null);
  const [fills, setFills] = useState<Fill[] | null>(null);
  const [alpacaContexts, setAlpacaContexts] = useState<Record<string, FillMarketContext>>({});
  const [pathMetrics, setPathMetrics] = useState<TradePathMetrics | null>(null);
  const [reviewLoading, setReviewLoading] = useState(false);
  const [reviewError, setReviewError] = useState<string | null>(null);
  // Pre-trade plans linked to this trade (Charts C3.6); null while loading or unreadable.
  const [plans, setPlans] = useState<Capture[] | null>(null);
  // Owner-only, and only while Copilot Lab is on.
  const copilotOn = useCopilotOn();

  useEffect(() => {
    Promise.all([api.trade(id), api.tradeFills(id)])
      .then(([t, f]) => {
        setTrade(t);
        setFills(f);
        // Fetch Alpaca context for all fills in one batch call
        if (f.length > 0) {
          api.bulkFillMarketContext(f.map((fill) => fill.id))
            .then(setAlpacaContexts)
            .catch(() => {});
        }
        api.tradePathMetrics(id)
          .then(setPathMetrics)
          .catch(() => {});
        fetchTradePlans(id)
          .then((data) => setPlans(data.captures))
          .catch(() => {});
      })
      .catch(() => {
        setTrade(null);
        setFills(null);
        setTradeError(true);
      });
  }, [id]);

  if (tradeError) return <div role="alert" className="space-y-3"><p>This position could not be loaded. It may no longer be in the journal.</p><Link href="/trades" className="underline">Back to Trades</Link><p>Reload the page to try again.</p></div>;

  if (!trade || !fills) {
    return <div className="text-center text-muted-foreground">Loading...</div>;
  }

  // Owner-only, lab on, open positions: the lab prefilled to talk through the decision now.
  const askHref = copilotOn && trade.status === "open" ? copilotLabHref(trade.ticker, `Review this position: ${trade.id}`) : undefined;

  const handleReviewClick = async () => {
    setReviewLoading(true);
    setReviewError(null);
    try {
      const updated = await api.reviewTrade(id);
      setTrade(updated);
    } catch (err) {
      setReviewError(err instanceof Error ? err.message : "Failed to generate review");
    } finally {
      setReviewLoading(false);
    }
  };

  const statusColor =
    trade.status === "open"
      ? "bg-blue-900/40 text-blue-300"
      : trade.status === "expired"
        ? "bg-muted text-muted-foreground"
        : "bg-muted text-foreground/70";

  const sizeLabel = trade.instrument_type === "stock" ? "Shares" : "Contracts";
  const returnTo = `/trades?ticker=${encodeURIComponent(trade.ticker)}`;
  const planSection = plans && plans.length > 0 && <section aria-label="Pre-trade plan" className="rounded-lg border bg-card p-5">
    <h2 className="mb-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Pre-trade plan</h2>
    <div className="space-y-3">{plans.map((capture) => <PlanSummary key={capture.id} capture={capture} />)}</div>
  </section>;

  return (
    <div className="flex flex-col gap-6 lg:flex-row lg:items-start">
    {/* Left column — main content */}
    <div className="flex-1 min-w-0 space-y-6">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <a href={back.href} className="text-sm text-muted-foreground hover:text-foreground">
          {back.label}
        </a>
        <h1 className="text-xl font-semibold text-foreground">{tradeTitle(trade)}</h1>
        <span className={`rounded px-2 py-0.5 text-xs font-medium ${statusColor}`}>
          {trade.status}
        </span>
        {newYorkSeconds(trade.opened_at) !== null && <Link href={chartLink({ symbol: trade.ticker, from: newYorkSeconds(trade.opened_at)!, to: newYorkSeconds(trade.closed_at) ?? newYorkSeconds(trade.opened_at), trade: trade.id })}
          className="ml-auto inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs text-foreground hover:bg-muted"><ChartCandlestick size={13} />Open on chart</Link>}
        {copilotOn && trade.status !== "open" && <Link href={copilotLabHref(trade.ticker, `Review this trade: ${trade.id}`)}
          className="inline-flex items-center rounded-md border px-2.5 py-1 text-xs text-foreground hover:bg-muted">Review with copilot</Link>}
        {/* From a position alert the selected alert carries this as its primary action instead. */}
        {askHref && !alert && <Link href={askHref}
          className="inline-flex items-center rounded-md border px-2.5 py-1 text-xs text-foreground hover:bg-muted">Ask copilot about this position</Link>}
      </div>

      {alert && <TradePhoneAlerts key={id} tradeId={id} alertId={alert} symbol={trade.ticker} status={trade.status} askHref={askHref} />}
      {/* An alert asks you to review your exit plan, so the plan follows it rather than the summary. */}
      {alert && planSection}

      <div className="rounded-lg border bg-card p-5">
        <h2 className="mb-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Trade Summary
        </h2>
        <div className="grid grid-cols-1 gap-x-8 sm:grid-cols-2">
          <div>
            <Row label={sizeLabel} value={String(trade.contracts)} />
            <Row label="Avg Entry" value={`$${trade.avg_entry_premium}`} />
            <Row label="Avg Exit" value={trade.avg_exit_premium != null ? `$${trade.avg_exit_premium}` : "-"} />
            <Row label="Premium Paid" value={`$${trade.total_premium_paid}`} />
            <Row label="Realized P&L" value={fmt$(trade.realized_pnl)} valueClass={pnlColor(trade.realized_pnl)} />
            <Row label="P&L %" value={fmtPct(trade.pnl_pct)} valueClass={pnlColor(trade.pnl_pct)} />
          </div>
          <div>
            <Row
              label="Hold Duration"
              value={trade.hold_duration_mins != null ? formatHoldDuration(trade.hold_duration_mins) : "-"}
            />
            <Row label="Entry Bucket" value={trade.entry_time_bucket ?? "-"} />
            <Row label="Opened" value={etTime(trade.opened_at)} />
            <Row label="Closed" value={trade.closed_at ? etTime(trade.closed_at) : "-"} />
            <Row label="Expired Worthless" value={trade.expired_worthless ? "Yes" : "No"} />
          </div>
        </div>
      </div>

      {!alert && planSection}

      {!alert && <TradePhoneAlerts key={id} tradeId={id} symbol={trade.ticker} status={trade.status} />}

      <TradeAdvice tradeId={id} />

      <div className="rounded-lg border bg-card p-5">
        <div className="mb-3 flex items-center justify-between gap-3">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Fill Timeline
          </h2>
          <p className="text-xs text-muted-foreground">
            Edit a fill to correct the position history. Saving rebuilds trades and returns you to the ticker view.
          </p>
        </div>
        <div className="space-y-2">
          {fills.map((fill) => {
            const chips: { label: string; value: string }[] = [];
            if (fill.underlying_price_at_fill != null) chips.push({ label: "Underlying", value: `$${fill.underlying_price_at_fill.toFixed(2)}` });
            if (fill.vwap_at_fill != null) chips.push({ label: "VWAP", value: `$${fill.vwap_at_fill.toFixed(2)}` });
            if (fill.iv_at_fill != null) chips.push({ label: "IV", value: `${(fill.iv_at_fill * 100).toFixed(1)}%` });
            if (fill.delta_at_fill != null) chips.push({ label: "Δ", value: fill.delta_at_fill.toFixed(2) });
            if (fill.gamma_at_fill != null) chips.push({ label: "Γ", value: fill.gamma_at_fill.toFixed(4) });
            if (fill.theta_at_fill != null) chips.push({ label: "Θ", value: fill.theta_at_fill.toFixed(4) });
            if (fill.vega_at_fill != null) chips.push({ label: "V", value: fill.vega_at_fill.toFixed(4) });
            if (fill.rsi_14_at_fill != null) chips.push({ label: "RSI", value: fill.rsi_14_at_fill.toFixed(1) });
            if (fill.macd_at_fill != null) chips.push({ label: "MACD", value: fill.macd_at_fill.toFixed(3) });
            if (fill.macd_signal_at_fill != null) chips.push({ label: "Sig", value: fill.macd_signal_at_fill.toFixed(3) });
            if (fill.ema_9h_at_fill != null) chips.push({ label: "EMA9h", value: `$${fill.ema_9h_at_fill.toFixed(2)}` });
            if (fill.ema_9_at_fill != null) chips.push({ label: "EMA9d", value: `$${fill.ema_9_at_fill.toFixed(2)}` });
            if (fill.ema_20_at_fill != null) chips.push({ label: "EMA20d", value: `$${fill.ema_20_at_fill.toFixed(2)}` });
            if (fill.sma_20_at_fill != null) chips.push({ label: "SMA20d", value: `$${fill.sma_20_at_fill.toFixed(2)}` });
            if (fill.sma_50_at_fill != null) chips.push({ label: "SMA50d", value: `$${fill.sma_50_at_fill.toFixed(2)}` });
            return (
              <a
                key={fill.id}
                href={`/fills/${fill.id}?returnTo=${encodeURIComponent(returnTo)}`}
                className="block rounded-md bg-muted px-4 py-3 text-sm transition-colors hover:bg-muted/80"
              >
                {/* Wraps on a phone: five fixed cells clipped the Edit fill link. */}
                <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
                  <span
                    className={`w-20 shrink-0 rounded px-2 py-0.5 text-center text-xs font-semibold ${
                      isEntryFill(fill) ? "bg-blue-900/40 text-blue-300" : "bg-orange-900/40 text-orange-300"
                    }`}
                  >
                    {isEntryFill(fill) ? "ENTRY" : "EXIT"}
                  </span>
                  <span className="text-xs text-muted-foreground">{etTime(fill.executed_at)}</span>
                  <span className="font-medium">{fill.contracts}x @ ${fill.price}</span>
                  <span className="text-muted-foreground">${(fill.contracts * fill.price).toFixed(2)} total</span>
                  <span className="text-xs font-medium text-foreground/80 sm:ml-auto">Edit fill</span>
                </div>
                {chips.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {chips.map(({ label, value }) => (
                      <span key={label} className="rounded bg-background/60 px-1.5 py-0.5 text-xs text-muted-foreground">
                        <span className="text-foreground/50">{label}</span> {value}
                      </span>
                    ))}
                  </div>
                )}
              </a>
            );
          })}
        </div>
      </div>

      {fills && Object.keys(alpacaContexts).length > 0 && (
        <AlpacaContextSection fills={fills} contexts={alpacaContexts} />
      )}

      {pathMetrics && <TradePathSection metrics={pathMetrics} />}

      <div className="rounded-lg border bg-card p-5">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">AI Review</h2>
          {(trade.ai_review || reviewLoading) && (
            <button
              onClick={handleReviewClick}
              disabled={reviewLoading}
              className="text-xs font-medium text-blue-400 hover:text-blue-300 disabled:text-muted-foreground"
            >
              {reviewLoading ? "Generating..." : "Regenerate"}
            </button>
          )}
        </div>
        {reviewError && <p className="mb-2 text-sm text-red-400">{reviewError}</p>}
        {trade.ai_review ? (
          <AiReview raw={trade.ai_review} />
        ) : reviewLoading ? (
          <p className="text-sm text-muted-foreground">Generating review on your Claude plan (usually under a minute)...</p>
        ) : (
          <button
            onClick={handleReviewClick}
            disabled={reviewLoading}
            className="rounded bg-blue-900/40 px-3 py-2 text-sm font-medium text-blue-300 hover:bg-blue-900/60 disabled:bg-muted disabled:text-muted-foreground"
          >
            Generate Review
          </button>
        )}
      </div>
    </div>

    {/* Right column — sticky audit panel (below the trade on small screens) */}
    <div className="lg:sticky lg:top-6 lg:self-start">
      <AuditPanel tradeId={id} />
    </div>
    </div>
  );
}

function AiReview({ raw }: { raw: string }) {
  try {
    const review = JSON.parse(raw);
    return (
      <div className="space-y-3 text-sm">
        {review.source_data_stale && (
          <p className="rounded border border-amber-500/50 bg-amber-950/30 p-3 text-amber-200">
            This saved analysis used older fill times or market context. Regenerate it after enrichment finishes.
          </p>
        )}
        {review.strategy && (
          <div className="rounded bg-blue-900/30 px-3 py-2">
            <span className="text-xs font-medium text-blue-300">{review.strategy}</span>
          </div>
        )}
        {review.flags?.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {review.flags.map((flag: string) => (
              <span key={flag} className="rounded bg-amber-900/40 px-2 py-0.5 text-xs font-medium text-amber-300">
                {flag}
              </span>
            ))}
          </div>
        )}
        <p className="text-foreground/80">{review.summary}</p>
        <div className="space-y-1 text-xs">
          <p>
            <span className="text-muted-foreground">Entry: </span><span className="font-medium">{review.entry_quality}</span>
          </p>
          <p>
            <span className="text-muted-foreground">Exit: </span><span className="font-medium">{review.exit_quality}</span>
          </p>
        </div>
        {review.market_read && (
          <p className="text-xs"><span className="text-muted-foreground">Market: </span>{review.market_read}</p>
        )}
        {review.plan_check && (
          <p className="text-xs"><span className="text-muted-foreground">Plan vs trade: </span>{review.plan_check}</p>
        )}
        {review.suggestions?.length > 0 && (
          <ul className="list-inside list-disc space-y-1 text-foreground/70">
            {review.suggestions.map((suggestion: string, index: number) => (
              <li key={index}>{suggestion}</li>
            ))}
          </ul>
        )}
        {review.data_gaps?.length > 0 && (
          <p className="text-xs text-amber-300/80">Missing: {review.data_gaps.join(" · ")}</p>
        )}
        {review.generated_by && <p className="text-[11px] text-muted-foreground">Written by {review.generated_by}</p>}
      </div>
    );
  } catch {
    return <p className="text-sm text-muted-foreground">{raw}</p>;
  }
}
