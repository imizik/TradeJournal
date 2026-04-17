import { api } from "@/lib/api";

function pnlColor(val: number | null | undefined) {
  if (val == null) return "text-muted-foreground";
  return val >= 0 ? "text-emerald-400" : "text-red-400";
}

function fmtPct(val: number | null | undefined) {
  if (val == null) return "—";
  return `${val >= 0 ? "+" : ""}${(val * 100).toFixed(1)}%`;
}

function fmt$(val: number | null | undefined) {
  if (val == null) return "—";
  return `${val >= 0 ? "+" : ""}$${val.toFixed(0)}`;
}

function WinBar({ rate }: { rate: number }) {
  const pct = Math.round(rate * 100);
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 rounded-full bg-secondary h-2 overflow-hidden">
        <div
          className={`h-full rounded-full ${pct >= 50 ? "bg-emerald-400" : "bg-red-400"}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-xs tabular-nums w-10 text-right">{pct}%</span>
    </div>
  );
}

export default async function AnalyticsPage() {
  const stats = await api.stats();

  return (
    <div className="space-y-8">
      <h1 className="text-xl font-semibold text-foreground">Analytics</h1>

      {/* By ticker */}
      <Section title="By Ticker">
        <table className="w-full text-sm">
          <thead className="bg-muted text-xs text-muted-foreground uppercase">
            <tr>
              <Th>Ticker</Th>
              <Th>Trades</Th>
              <Th>Win Rate</Th>
              <Th>Total P&L</Th>
              <Th>Avg P&L %</Th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {Object.entries(stats.by_ticker)
              .sort((a, b) => b[1].total_pnl - a[1].total_pnl)
              .map(([ticker, s]) => (
                <tr key={ticker} className="hover:bg-muted/50">
                  <Td><span className="font-semibold">{ticker}</span></Td>
                  <Td>{s.count}</Td>
                  <Td><WinBar rate={s.win_rate} /></Td>
                  <Td><span className={pnlColor(s.total_pnl)}>{fmt$(s.total_pnl)}</span></Td>
                  <Td><span className={pnlColor(s.avg_pnl_pct)}>{fmtPct(s.avg_pnl_pct)}</span></Td>
                </tr>
              ))}
          </tbody>
        </table>
      </Section>

      {/* By time bucket */}
      <Section title="By Entry Time">
        {Object.keys(stats.by_time_bucket).length === 0 ? (
          <p className="text-sm text-muted-foreground px-4 py-3">No data yet.</p>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-muted text-xs text-muted-foreground uppercase">
              <tr>
                <Th>Bucket</Th>
                <Th>Trades</Th>
                <Th>Win Rate</Th>
                <Th>Total P&L</Th>
                <Th>Avg P&L %</Th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {Object.entries(stats.by_time_bucket).map(([bucket, s]) => (
                <tr key={bucket} className="hover:bg-muted/50">
                  <Td><span className="font-semibold capitalize">{bucket}</span></Td>
                  <Td>{s.count}</Td>
                  <Td><WinBar rate={s.win_rate} /></Td>
                  <Td><span className={pnlColor(s.total_pnl)}>{fmt$(s.total_pnl)}</span></Td>
                  <Td><span className={pnlColor(s.avg_pnl_pct)}>{fmtPct(s.avg_pnl_pct)}</span></Td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>

      {/* By tag */}
      <Section title="By Tag">
        {Object.keys(stats.by_tag).length === 0 ? (
          <p className="text-sm text-muted-foreground px-4 py-3">No tags yet. Add tags from trade detail pages.</p>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-muted text-xs text-muted-foreground uppercase">
              <tr>
                <Th>Tag</Th>
                <Th>Trades</Th>
                <Th>Win Rate</Th>
                <Th>Total P&L</Th>
                <Th>Avg P&L %</Th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {Object.entries(stats.by_tag).map(([tag, s]) => (
                <tr key={tag} className="hover:bg-muted/50">
                  <Td><span className="font-semibold">{tag}</span></Td>
                  <Td>{s.count}</Td>
                  <Td><WinBar rate={s.win_rate} /></Td>
                  <Td><span className={pnlColor(s.total_pnl)}>{fmt$(s.total_pnl)}</span></Td>
                  <Td><span className={pnlColor(s.avg_pnl_pct)}>{fmtPct(s.avg_pnl_pct)}</span></Td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>

      {/* Behavioral flags */}
      {Object.keys(stats.behavioral_flags).length > 0 && (
        <Section title="Behavioral Flags">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 p-4">
            {Object.entries(stats.behavioral_flags).map(([flag, count]) => (
              <div key={flag} className="rounded-md bg-amber-900/20 border border-amber-900/40 p-3">
                <p className="text-xs font-medium text-amber-300">{flag.replace(/_/g, " ")}</p>
                <p className="mt-1 text-2xl font-semibold text-amber-200">{count}</p>
              </div>
            ))}
          </div>
        </Section>
      )}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground">{title}</h2>
      <div className="rounded-lg border bg-card overflow-hidden">{children}</div>
    </section>
  );
}

function Th({ children }: { children: React.ReactNode }) {
  return <th className="px-4 py-2 text-left font-medium">{children}</th>;
}

function Td({ children }: { children: React.ReactNode }) {
  return <td className="px-4 py-3">{children}</td>;
}
