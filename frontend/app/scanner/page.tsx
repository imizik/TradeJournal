import Link from "next/link";
import { api } from "@/lib/serverApi";
import type { ScannerCandidateRow } from "@/lib/api";

export const dynamic = "force-dynamic";

const STATUS: Record<ScannerCandidateRow["status"], { label: string; className: string }> = {
  no_contract: { label: "No contract", className: "bg-muted text-muted-foreground" },
  pending_entry: { label: "Entering", className: "bg-sky-500/15 text-sky-300" },
  open: { label: "Open", className: "bg-sky-500/15 text-sky-300" },
  exiting: { label: "Exiting", className: "bg-sky-500/15 text-sky-300" },
  exit: { label: "Closed", className: "bg-secondary text-foreground" },
  unresolved: { label: "Unresolved", className: "bg-amber-500/15 text-amber-300" },
};

const EXIT_REASON: Record<string, string> = {
  stop: "Stop",
  target: "Target",
  time_stop: "60-min time stop",
  flat: "Flat by close",
};

function nyTime(iso: string) {
  return new Date(iso).toLocaleTimeString("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit" });
}

function money(value: number | null | undefined) {
  if (value === null || value === undefined) return "—";
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return `${sign}$${Math.abs(value).toFixed(2)}`;
}

function shiftDay(day: string, delta: number) {
  const d = new Date(`${day}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() + delta);
  return d.toISOString().slice(0, 10);
}

function Card({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-lg border bg-card px-4 py-3">
      <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="mt-1 text-xl font-semibold tabular-nums text-foreground">{value}</div>
      {hint && <div className="mt-1 text-xs text-muted-foreground">{hint}</div>}
    </div>
  );
}

function setupLabel(c: ScannerCandidateRow) {
  if (c.setup === "orb") return "Opening-range break";
  return c.direction === "long" ? "VWAP fade (long)" : "VWAP fade (short)";
}

function contractLabel(c: ScannerCandidateRow) {
  if (!c.contract) return null;
  const k = c.contract;
  return `${k.expiration.slice(5)} ${k.strike}${k.option_type === "call" ? "C" : "P"} · Δ${Math.abs(k.delta).toFixed(2)}`;
}

function Outcome({ c }: { c: ScannerCandidateRow }) {
  const exit = c.events.exit;
  if (exit) {
    const pnl = Number(exit.pnl);
    return (
      <div>
        <span className={pnl > 0 ? "text-emerald-400" : pnl < 0 ? "text-red-400" : ""}>{money(pnl)}</span>
        <span className="ml-2 text-xs text-muted-foreground">{EXIT_REASON[String(exit.reason)] ?? exit.reason}</span>
      </div>
    );
  }
  const reason = c.events.unresolved?.reason ?? (c.status === "no_contract" ? c.facts.contract_note : null);
  return <span className="text-xs text-muted-foreground">{reason ? String(reason) : "—"}</span>;
}

export default async function ScannerPage({ searchParams }: { searchParams: Promise<{ day?: string }> }) {
  const { day } = await searchParams;
  const data = await api.scannerDay(day);
  const t = data.totals;
  const winRate = t.resolved ? `${Math.round((100 * t.wins) / t.resolved)}%` : "—";

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-foreground">Scanner</h1>
        <p className="mt-2 max-w-3xl text-sm text-muted-foreground">
          Setups found by the rules (VWAP fade and opening-range break) and what each would have done as a
          one-contract paper trade: buy at the ask, sell at the bid, 60-minute time stop. No AI, no alerts and no
          real orders; nothing here touches your fills or trades.
        </p>
        {!data.enabled && (
          <p className="mt-2 text-sm text-amber-300">The scanner is switched off on this server, so no new setups are being recorded.</p>
        )}
      </div>

      <div className="flex items-center gap-3 text-sm">
        <Link href={`/scanner?day=${shiftDay(data.date, -1)}`} className="rounded border px-3 py-1.5 hover:bg-secondary">
          ← Previous day
        </Link>
        <span className="font-medium text-foreground">{data.date}</span>
        <Link href={`/scanner?day=${shiftDay(data.date, 1)}`} className="rounded border px-3 py-1.5 hover:bg-secondary">
          Next day →
        </Link>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <Card label="Setups" value={String(t.candidates)} hint={`${t.no_contract} without a contract`} />
        <Card label="Paper trades" value={String(t.trades)} hint={`${t.unresolved} unresolved`} />
        <Card label="Win rate" value={winRate} hint={`${t.resolved} closed`} />
        <Card label="Paper P&L" value={money(t.pnl)} hint="per contract, after commission" />
        <Card label="At 2× spread" value={money(t.pnl_2x_spread)} hint="pessimistic fills" />
      </div>

      <section className="overflow-hidden rounded-lg border bg-card">
        {data.candidates.length === 0 ? (
          <div className="px-5 py-10 text-center text-sm text-muted-foreground">No setups on this day.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[900px] text-sm">
              <thead className="bg-muted text-xs uppercase text-muted-foreground">
                <tr>
                  <th className="px-4 py-2 text-left font-medium">Time</th>
                  <th className="px-4 py-2 text-left font-medium">Symbol</th>
                  <th className="px-4 py-2 text-left font-medium">Setup</th>
                  <th className="px-4 py-2 text-left font-medium">Stop / target</th>
                  <th className="px-4 py-2 text-left font-medium">Contract</th>
                  <th className="px-4 py-2 text-left font-medium">In / out</th>
                  <th className="px-4 py-2 text-left font-medium">Status</th>
                  <th className="px-4 py-2 text-left font-medium">Result</th>
                </tr>
              </thead>
              <tbody>
                {data.candidates.map((c) => {
                  const status = STATUS[c.status];
                  const entry = c.events.entry;
                  const exit = c.events.exit;
                  return (
                    <tr key={c.id} className="border-t align-top">
                      <td className="whitespace-nowrap px-4 py-2 text-muted-foreground">{nyTime(c.bar_end)}</td>
                      <td className="px-4 py-2 font-medium text-foreground">{c.symbol}</td>
                      <td className="px-4 py-2">
                        <div className="whitespace-nowrap">{setupLabel(c)}</div>
                        {c.flags.length > 0 && (
                          <div className="mt-1 flex flex-wrap gap-1">
                            {c.flags.map((f) => (
                              <span key={f} className="rounded bg-amber-500/15 px-1.5 py-0.5 text-[11px] text-amber-300">
                                {f.replaceAll("_", " ")}
                              </span>
                            ))}
                          </div>
                        )}
                      </td>
                      <td className="whitespace-nowrap px-4 py-2 tabular-nums text-muted-foreground">
                        {c.stop.toFixed(2)} / {c.target.toFixed(2)}
                      </td>
                      <td className="whitespace-nowrap px-4 py-2 text-muted-foreground">{contractLabel(c) ?? "—"}</td>
                      <td className="whitespace-nowrap px-4 py-2 tabular-nums">
                        {entry ? `${Number(entry.ask).toFixed(2)}` : "—"}
                        {exit ? ` → ${Number(exit.bid).toFixed(2)}` : ""}
                      </td>
                      <td className="px-4 py-2">
                        <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${status.className}`}>{status.label}</span>
                      </td>
                      <td className="px-4 py-2">
                        <Outcome c={c} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <p className="text-xs text-muted-foreground">
        Rules {data.scanner_version} · {data.params_hash.slice(0, 12)}. Paper results describe these rules only; they are not
        evidence of an edge until enough trades have closed.
      </p>
    </div>
  );
}
