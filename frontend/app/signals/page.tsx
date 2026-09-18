import Link from "next/link";
import { api, TradingViewAlert } from "@/lib/api";
import {
  fmtAlertTime,
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
    <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium capitalize ${className}`}>
      {children}
    </span>
  );
}

function SummaryCard({ label, value, hint }: { label: string; value: number; hint?: string }) {
  return (
    <div className="rounded-lg border bg-card px-5 py-4">
      <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="mt-1 text-2xl font-semibold text-foreground">{value}</div>
      {hint && <div className="mt-1 text-xs text-muted-foreground">{hint}</div>}
    </div>
  );
}

export default async function SignalsPage() {
  const alerts = await api.tradingViewAlerts("limit=200");

  const counts = alerts.reduce(
    (acc, alert) => {
      acc.total += 1;
      if (alert.analysis_status === "skipped") acc.skipped += 1;
      if (alert.analysis_status === "error") acc.errored += 1;
      if (alert.verdict === "long_scalp" || alert.verdict === "short_scalp") acc.tradeable += 1;
      return acc;
    },
    { total: 0, skipped: 0, errored: 0, tradeable: 0 }
  );

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-foreground">Signals</h1>
        <p className="mt-2 max-w-3xl text-sm text-muted-foreground">
          Live TradingView alerts delivered to the webhook ingress, each graded by the scalp
          analyzer at the moment it arrived. These are decision-support records only — they are
          isolated from journal fills and FIFO trades, and nothing here places an order.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <SummaryCard label="Alerts" value={counts.total} hint="Most recent 200" />
        <SummaryCard label="Tradeable verdicts" value={counts.tradeable} hint="long or short scalp" />
        <SummaryCard
          label="Unanalyzed"
          value={counts.skipped}
          hint="Arrived while the worker was down or stale"
        />
        <SummaryCard label="Errored" value={counts.errored} hint="Analysis failed" />
      </div>

      <section className="overflow-hidden rounded-lg border bg-card">
        <div className="border-b px-5 py-4">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Alert History
          </h2>
        </div>

        {alerts.length === 0 ? (
          <div className="px-5 py-10 text-center text-sm text-muted-foreground">
            No alerts received yet. Start the ingress with{" "}
            <code className="rounded bg-muted px-1.5 py-0.5 text-xs">
              TRADINGVIEW_INGRESS_ENABLED=true
            </code>{" "}
            and point your TradingView alert at its webhook URL.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1100px] text-sm">
              <thead className="bg-muted text-xs uppercase text-muted-foreground">
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
                    <td className="whitespace-nowrap px-4 py-2 text-muted-foreground">
                      {fmtAlertTime(alert.received_at)}
                    </td>
                    <td className="px-4 py-2 font-medium text-foreground">{alert.symbol}</td>
                    <td className="px-4 py-2 text-muted-foreground">{alert.setup}</td>
                    <td className="px-4 py-2 capitalize">{alert.side}</td>
                    <td className="px-4 py-2 text-muted-foreground">{alert.timeframe}</td>
                    <td className="px-4 py-2 tabular-nums">{alert.price}</td>
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
                        className="text-xs font-medium text-sky-400 hover:underline"
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
