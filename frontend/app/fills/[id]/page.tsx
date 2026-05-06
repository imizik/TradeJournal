import { api, Fill } from "@/lib/api";
import ManualFillForm from "@/components/ManualFillForm";
import { notFound } from "next/navigation";

function fillTitle(fill: Fill) {
  if (fill.instrument_type === "stock") {
    return `${fill.ticker} stock fill`;
  }
  return `${fill.ticker} ${fill.option_type ?? "option"} ${fill.strike ?? "-"} ${fill.expiration ?? "-"}`;
}

function MarketContext({ fill }: { fill: Fill }) {
  const fields: { label: string; value: string }[] = [];
  if (fill.underlying_price_at_fill != null) fields.push({ label: "Underlying Price", value: `$${fill.underlying_price_at_fill.toFixed(2)}` });
  if (fill.vwap_at_fill != null) fields.push({ label: "VWAP", value: `$${fill.vwap_at_fill.toFixed(2)}` });
  if (fill.iv_at_fill != null) fields.push({ label: "IV", value: `${(fill.iv_at_fill * 100).toFixed(1)}%` });
  if (fill.iv_rank_at_fill != null) fields.push({ label: "IV Rank", value: `${(fill.iv_rank_at_fill * 100).toFixed(1)}%` });
  if (fill.delta_at_fill != null) fields.push({ label: "Delta", value: fill.delta_at_fill.toFixed(4) });
  if (fill.gamma_at_fill != null) fields.push({ label: "Gamma", value: fill.gamma_at_fill.toFixed(4) });
  if (fill.theta_at_fill != null) fields.push({ label: "Theta", value: fill.theta_at_fill.toFixed(4) });
  if (fill.vega_at_fill != null) fields.push({ label: "Vega", value: fill.vega_at_fill.toFixed(4) });
  if (fill.rsi_14_at_fill != null) fields.push({ label: "RSI(14)", value: fill.rsi_14_at_fill.toFixed(1) });
  if (fill.macd_at_fill != null) fields.push({ label: "MACD", value: fill.macd_at_fill.toFixed(4) });
  if (fill.macd_signal_at_fill != null) fields.push({ label: "MACD Signal", value: fill.macd_signal_at_fill.toFixed(4) });
  if (fill.ema_9h_at_fill != null) fields.push({ label: "EMA 9 (hourly)", value: `$${fill.ema_9h_at_fill.toFixed(2)}` });
  if (fill.ema_9_at_fill != null) fields.push({ label: "EMA 9 (daily)", value: `$${fill.ema_9_at_fill.toFixed(2)}` });
  if (fill.ema_20_at_fill != null) fields.push({ label: "EMA 20 (daily)", value: `$${fill.ema_20_at_fill.toFixed(2)}` });
  if (fill.sma_20_at_fill != null) fields.push({ label: "SMA 20 (daily)", value: `$${fill.sma_20_at_fill.toFixed(2)}` });
  if (fill.sma_50_at_fill != null) fields.push({ label: "SMA 50 (daily)", value: `$${fill.sma_50_at_fill.toFixed(2)}` });

  if (fields.length === 0) return null;

  return (
    <div className="rounded-lg border bg-card p-5">
      <h2 className="mb-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        Market Context at Fill
      </h2>
      <div className="grid grid-cols-2 gap-x-8 gap-y-0 sm:grid-cols-3 lg:grid-cols-4">
        {fields.map(({ label, value }) => (
          <div key={label} className="flex justify-between border-b border-border py-2 text-sm last:border-0">
            <span className="text-muted-foreground">{label}</span>
            <span className="font-medium text-foreground">{value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default async function FillDetailPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ returnTo?: string }>;
}) {
  const { id } = await params;
  const { returnTo } = await searchParams;

  let fill: Fill;
  let accounts;

  try {
    [fill, accounts] = await Promise.all([api.fill(id), api.accounts()]);
  } catch {
    notFound();
  }

  const cancelHref = returnTo || "/fills";

  return (
    <div className="space-y-6">
      <div>
        <a href={cancelHref} className="text-sm text-muted-foreground hover:text-foreground">
          Back
        </a>
        <h1 className="mt-2 text-xl font-semibold text-foreground">{fillTitle(fill)}</h1>
        <p className="mt-2 max-w-3xl text-sm text-muted-foreground">
          Editing a fill rebuilds trades from scratch using the corrected fill history. If this changes how fills group
          together, the original trade detail URL may no longer exist after save.
        </p>
      </div>

      <MarketContext fill={fill} />

      <ManualFillForm
        accounts={accounts}
        mode="edit"
        initialFill={fill}
        successHref={cancelHref}
        cancelHref={cancelHref}
      />
    </div>
  );
}
