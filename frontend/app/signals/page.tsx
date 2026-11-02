import Link from "next/link";
import SignalsRefresh from "@/components/SignalsRefresh";
import { api } from "@/lib/serverApi";
import type { TradingViewAlert } from "@/lib/api";
import {
  fmtAlertTime,
  fmtDecimal,
  statusClasses,
  verdictClasses,
  verdictLabel,
} from "@/lib/tradingview";

export const dynamic = "force-dynamic";

function Th({ children }: { children?: React.ReactNode }) {
  return <th className="px-4 py-2 text-left font-medium">{children}</th>;
}

function Pill({ className, children }: { className: string; children: React.ReactNode }) {
  return (
    <span className={`inline-flex h-[22px] items-center whitespace-nowrap rounded-md px-2 text-[11.5px] font-medium capitalize ${className}`}>
      {children}
    </span>
  );
}

function SummaryCard({ label, value, hint }: { label: string; value: number; hint?: string }) {
  return (
    <div className="rounded-lg border bg-card px-4 py-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1.5 text-2xl font-medium tabular-nums text-foreground">{value}</div>
      {hint && <div className="mt-1 text-xs text-muted-foreground">{hint}</div>}
    </div>
  );
}

export default async function SignalsPage() {
  const alerts = await api.tradingViewAlerts("limit=200");

  const counts = alerts.reduce(
    (acc, alert) => {
      acc.total += 1;
      if (alert.analysis_status === "pending" || alert.analysis_status === "running") acc.pending += 1;
      if (alert.analysis_status === "skipped") acc.skipped += 1;
      if (alert.analysis_status === "error") acc.errored += 1;
      if (alert.verdict === "long_scalp" || alert.verdict === "short_scalp") acc.tradeable += 1;
      return acc;
    },
    { total: 0, pending: 0, skipped: 0, errored: 0, tradeable: 0 }
  );

  return (
    <div className="space-y-4">
      <div>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-baseline gap-2">
            <h1 className="text-xl font-semibold">Signals</h1>
            <span className="text-sm tabular-nums text-muted-foreground">{counts.total} recent</span>
          </div>
          <SignalsRefresh />
        </div>
        <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
          TradingView alerts and their latest scalp analysis. Read-only: nothing here places an order or
          changes your fills and trades.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <SummaryCard label="Alerts" value={counts.total} hint="Most recent 200" />
        <SummaryCard label="Tradeable verdicts" value={counts.tradeable} hint="long or short scalp" />
        <SummaryCard label="Awaiting analysis" value={counts.pending} hint="Pending or running" />
        <SummaryCard
          label="Skipped"
          value={counts.skipped}
          hint="See signal details for the reason"
        />
        <SummaryCard label="Errored" value={counts.errored} hint="Analysis failed" />
      </div>

      <section className="overflow-hidden rounded-lg border bg-card">
        <div className="border-b px-3.5 py-2.5">
          <h2 className="text-[13.5px] font-semibold tracking-tight">
            Alert History
          </h2>
        </div>

        {alerts.length === 0 ? (
          <div className="p-4 text-sm text-muted-foreground">
            No alerts received yet. New TradingView alerts will appear here automatically.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1100px] text-sm">
              <thead className="border-b text-xs font-medium text-muted-foreground">
                <tr>
                  <Th>Received</Th>
                  <Th>Symbol</Th>
                  <Th>Setup</Th>
                  <Th>Side</Th>
                  <Th>TF</Th>
                  <Th>Price</Th>
                  <Th>Verdict</Th>
                  <Th>Confidence</Th>
                  <Th>Status</Th>
                  <Th></Th>
                </tr>
              </thead>
              <tbody>
                {alerts.map((alert: TradingViewAlert) => (
                  <tr key={alert.alert_id} className="border-t hover:bg-secondary/40">
                    <td className="whitespace-nowrap px-4 py-2 tabular-nums text-muted-foreground">
                      {fmtAlertTime(alert.received_at)}
                    </td>
                    <td className="px-4 py-2 font-medium text-foreground">{alert.symbol}</td>
                    <td className="px-4 py-2 text-muted-foreground">{alert.setup}</td>
                    <td className="px-4 py-2 capitalize">{alert.side}</td>
                    <td className="px-4 py-2 text-muted-foreground">{alert.timeframe}</td>
                    <td className="px-4 py-2 tabular-nums">{fmtDecimal(alert.price)}</td>
                    <td className="px-4 py-2">
                      <Pill className={verdictClasses(alert.verdict)}>
                        {verdictLabel(alert.verdict)}
                      </Pill>
                    </td>
                    <td className="px-4 py-2 capitalize text-muted-foreground">
                      {alert.confidence ?? "—"}
                    </td>
                    <td className="px-4 py-2">
                      <Pill className={statusClasses(alert.analysis_status)}>
                        {alert.analysis_status}
                      </Pill>
                    </td>
                    <td className="px-4 py-2 text-right">
                      <Link
                        href={`/signals/${encodeURIComponent(alert.alert_id)}`}
                        className="inline-flex min-h-11 items-center text-xs font-medium text-foreground underline underline-offset-2 hover:text-muted-foreground sm:min-h-0"
                      >
                        Detail
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
