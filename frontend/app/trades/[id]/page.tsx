import { api, Fill, Trade } from "@/lib/api";
import { notFound } from "next/navigation";

function pnlColor(val: number | null | undefined) {
  if (val == null) return "text-muted-foreground";
  return val >= 0 ? "text-emerald-400" : "text-red-400";
}

function fmt$(val: number | null | undefined) {
  if (val == null) return "-";
  return `${val >= 0 ? "+" : ""}$${val.toFixed(2)}`;
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

export default async function TradeDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  let trade: Trade;
  let fills: Fill[];

  try {
    [trade, fills] = await Promise.all([api.trade(id), api.tradeFills(id)]);
  } catch {
    notFound();
  }

  const statusColor =
    trade.status === "open"
      ? "bg-blue-900/40 text-blue-300"
      : trade.status === "expired"
        ? "bg-muted text-muted-foreground"
        : "bg-muted text-foreground/70";

  const sizeLabel = trade.instrument_type === "stock" ? "Shares" : "Contracts";
  const returnTo = `/trades?ticker=${encodeURIComponent(trade.ticker)}`;

  return (
    <div className="max-w-3xl space-y-6">
      <div className="flex items-center gap-3">
        <a href="/trades" className="text-sm text-muted-foreground hover:text-foreground">
          Back to Trades
        </a>
        <h1 className="text-xl font-semibold text-foreground">{tradeTitle(trade)}</h1>
        <span className={`rounded px-2 py-0.5 text-xs font-medium ${statusColor}`}>
          {trade.status}
        </span>
      </div>

      <div className="rounded-lg border bg-card p-5">
        <h2 className="mb-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Trade Summary
        </h2>
        <div className="grid grid-cols-2 gap-x-8">
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
              value={trade.hold_duration_mins != null ? `${Math.round(trade.hold_duration_mins)}m` : "-"}
            />
            <Row label="Entry Bucket" value={trade.entry_time_bucket ?? "-"} />
            <Row label="Opened" value={new Date(trade.opened_at).toLocaleString()} />
            <Row label="Closed" value={trade.closed_at ? new Date(trade.closed_at).toLocaleString() : "-"} />
            <Row label="Expired Worthless" value={trade.expired_worthless ? "Yes" : "No"} />
          </div>
        </div>
      </div>

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
          {fills.map((fill) => (
            <a
              key={fill.id}
              href={`/fills/${fill.id}?returnTo=${encodeURIComponent(returnTo)}`}
              className="flex items-center gap-4 rounded-md bg-muted px-4 py-3 text-sm transition-colors hover:bg-muted/80"
            >
              <span
                className={`w-20 rounded px-2 py-0.5 text-center text-xs font-semibold ${
                  isEntryFill(fill) ? "bg-blue-900/40 text-blue-300" : "bg-orange-900/40 text-orange-300"
                }`}
              >
                {isEntryFill(fill) ? "ENTRY" : "EXIT"}
              </span>
              <span className="text-xs text-muted-foreground">{new Date(fill.executed_at).toLocaleString()}</span>
              <span className="font-medium">{fill.contracts}x @ ${fill.price}</span>
              <span className="text-muted-foreground">${(fill.contracts * fill.price).toFixed(2)} total</span>
              {fill.iv_at_fill != null && (
                <span className="text-xs text-muted-foreground">IV {(fill.iv_at_fill * 100).toFixed(1)}%</span>
              )}
              {fill.delta_at_fill != null && (
                <span className="text-xs text-muted-foreground">Delta {fill.delta_at_fill.toFixed(2)}</span>
              )}
              <span className="ml-auto text-xs font-medium text-foreground/80">Edit fill</span>
            </a>
          ))}
        </div>
      </div>

      <div className="rounded-lg border bg-card p-5">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">AI Review</h2>
        </div>
        {trade.ai_review ? (
          <AiReview raw={trade.ai_review} />
        ) : (
          <p className="text-sm text-muted-foreground">No review yet. AI review coming in a future step.</p>
        )}
      </div>
    </div>
  );
}

function AiReview({ raw }: { raw: string }) {
  try {
    const review = JSON.parse(raw);
    return (
      <div className="space-y-3 text-sm">
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
        <div className="flex gap-4 text-xs">
          <span>
            Entry: <span className="font-medium">{review.entry_quality}</span>
          </span>
          <span>
            Exit: <span className="font-medium">{review.exit_quality}</span>
          </span>
        </div>
        {review.suggestions?.length > 0 && (
          <ul className="list-inside list-disc space-y-1 text-foreground/70">
            {review.suggestions.map((suggestion: string, index: number) => (
              <li key={index}>{suggestion}</li>
            ))}
          </ul>
        )}
      </div>
    );
  } catch {
    return <p className="text-sm text-muted-foreground">{raw}</p>;
  }
}
