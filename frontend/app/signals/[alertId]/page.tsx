import Link from "next/link";
import { notFound } from "next/navigation";
import { api, TradingViewAlertDetail, TradingViewSnapshotValue } from "@/lib/api";
import {
  fmtAlertTime,
  fmtScore,
  snapshotText,
  statusClasses,
  verdictClasses,
  verdictLabel,
} from "@/lib/tradingview";

export const dynamic = "force-dynamic";

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</dt>
      <dd className="mt-1 text-sm text-foreground">{value}</dd>
    </div>
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="overflow-hidden rounded-lg border bg-card">
      <div className="border-b px-5 py-4">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          {title}
        </h2>
      </div>
      <div className="px-5 py-4">{children}</div>
    </section>
  );
}

function SnapshotGrid({ values }: { values: Record<string, TradingViewSnapshotValue> }) {
  const entries = Object.entries(values);
  if (entries.length === 0) {
    return <p className="text-sm text-muted-foreground">None sent by the indicator.</p>;
  }
  return (
    <dl className="grid gap-4 sm:grid-cols-3 lg:grid-cols-4">
      {entries.map(([key, value]) => (
        <Field key={key} label={key} value={<span className="tabular-nums">{snapshotText(value)}</span>} />
      ))}
    </dl>
  );
}

function ReasonList({ items, tone }: { items: string[]; tone: "for" | "against" }) {
  if (items.length === 0) {
    return <p className="text-sm text-muted-foreground">None.</p>;
  }
  return (
    <ul className="space-y-1.5">
      {items.map((item) => (
        <li key={item} className="flex gap-2 text-sm">
          <span className={tone === "for" ? "text-emerald-400" : "text-red-400"}>
            {tone === "for" ? "+" : "−"}
          </span>
          <span className="text-muted-foreground">{item}</span>
        </li>
      ))}
    </ul>
  );
}

export default async function SignalDetailPage({
  params,
}: {
  params: Promise<{ alertId: string }>;
}) {
  const { alertId } = await params;

  let alert: TradingViewAlertDetail;
  try {
    alert = await api.tradingViewAlert(decodeURIComponent(alertId));
  } catch {
    notFound();
  }

  const scalp = alert.assessment?.assessment ?? null;

  return (
    <div className="space-y-6">
      <div>
        <Link href="/signals" className="text-xs font-medium text-sky-400 hover:underline">
          ← Signals
        </Link>
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <h1 className="text-xl font-semibold text-foreground">
            {alert.symbol} {alert.setup}
          </h1>
          <span
            className={`rounded-full px-2.5 py-0.5 text-xs font-medium capitalize ${verdictClasses(alert.verdict)}`}
          >
            {verdictLabel(alert.verdict)}
          </span>
          <span
            className={`rounded-full px-2.5 py-0.5 text-xs font-medium capitalize ${statusClasses(alert.analysis_status)}`}
          >
            {alert.analysis_status}
          </span>
        </div>
        <p className="mt-2 font-mono text-xs break-all text-muted-foreground">{alert.alert_id}</p>
      </div>

      <Card title="Alert">
        <dl className="grid gap-4 sm:grid-cols-3 lg:grid-cols-4">
          <Field label="Side" value={<span className="capitalize">{alert.side}</span>} />
          <Field label="Price" value={<span className="tabular-nums">{alert.price}</span>} />
          <Field label="Timeframe" value={alert.timeframe} />
          <Field label="Bar time" value={fmtAlertTime(alert.bar_time)} />
          <Field label="Received" value={fmtAlertTime(alert.received_at)} />
          <Field label="Indicator version" value={alert.indicator_version} />
          <Field label="Contract version" value={`v${alert.contract_version}`} />
          <Field label="Parser revision" value={alert.parser_revision} />
        </dl>
      </Card>

      <Card title="Indicator Levels">
        <SnapshotGrid values={alert.levels} />
      </Card>

      <Card title="Indicator Context">
        <SnapshotGrid values={alert.context} />
      </Card>

      {alert.analysis_status === "skipped" && (
        <Card title="Analysis">
          <p className="text-sm text-muted-foreground">
            This alert was never graded. The scalp analyzer reads live market data, so an alert
            that arrives while the worker is down goes stale and is skipped rather than scored
            against a market that has since moved. The signal itself is still recorded above.
          </p>
        </Card>
      )}

      {alert.analysis_error && (
        <Card title="Analysis Error">
          <p className="text-sm text-red-400">{alert.analysis_error_code}</p>
          <pre className="mt-2 overflow-x-auto whitespace-pre-wrap text-xs text-muted-foreground">
            {alert.analysis_error}
          </pre>
        </Card>
      )}

      {scalp && (
        <>
          <Card title="Assessment">
            <dl className="grid gap-4 sm:grid-cols-3 lg:grid-cols-6">
              <Field label="Setup score" value={fmtScore(scalp.setup_score)} />
              <Field label="Liquidity" value={fmtScore(scalp.liquidity_score)} />
              <Field label="Risk" value={fmtScore(scalp.risk_score)} />
              <Field label="Bias" value={<span className="capitalize">{scalp.bias}</span>} />
              <Field label="Market" value={<span className="capitalize">{scalp.market_state}</span>} />
              <Field label="Scorer" value={alert.scorer_revision ?? "—"} />
            </dl>

            <div className="mt-6 grid gap-6 lg:grid-cols-2">
              <div>
                <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Reasons for
                </h3>
                <ReasonList items={scalp.reasons_for} tone="for" />
              </div>
              <div>
                <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Reasons against
                </h3>
                <ReasonList items={scalp.reasons_against} tone="against" />
              </div>
            </div>

            {scalp.missing.length > 0 && (
              <div className="mt-6">
                <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Missing data
                </h3>
                <p className="text-sm text-amber-400">{scalp.missing.join(", ")}</p>
              </div>
            )}
          </Card>

          <Card title="Plan">
            <dl className="grid gap-4 sm:grid-cols-2">
              <Field
                label="Trigger"
                value={
                  scalp.trigger ? (
                    <span>
                      <span className="tabular-nums">{scalp.trigger.price}</span>{" "}
                      <span className="text-muted-foreground">({scalp.trigger.level})</span>
                      {scalp.trigger.description && (
                        <span className="mt-1 block text-xs text-muted-foreground">
                          {scalp.trigger.description}
                        </span>
                      )}
                    </span>
                  ) : (
                    "—"
                  )
                }
              />
              <Field
                label="Invalidation"
                value={
                  scalp.invalidation ? (
                    <span>
                      <span className="tabular-nums">{scalp.invalidation.price}</span>{" "}
                      <span className="text-muted-foreground">({scalp.invalidation.level})</span>
                      {scalp.invalidation.description && (
                        <span className="mt-1 block text-xs text-muted-foreground">
                          {scalp.invalidation.description}
                        </span>
                      )}
                    </span>
                  ) : (
                    "—"
                  )
                }
              />
            </dl>

            <h3 className="mb-2 mt-6 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Targets
            </h3>
            {scalp.targets.length === 0 ? (
              <p className="text-sm text-muted-foreground">None.</p>
            ) : (
              <ul className="space-y-1.5">
                {scalp.targets.map((target) => (
                  <li key={target.level} className="flex gap-3 text-sm">
                    <span className="tabular-nums text-foreground">{target.price}</span>
                    <span className="text-muted-foreground">{target.level}</span>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          {scalp.disclaimer && (
            <p className="text-xs text-muted-foreground">{scalp.disclaimer}</p>
          )}
        </>
      )}
    </div>
  );
}
