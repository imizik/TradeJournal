import Link from "next/link";
import { api } from "@/lib/serverApi";
import type { ScannerCandidateRow, ScannerScorecard } from "@/lib/api";

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

function Scorecard({ label, score }: { label: string; score: ScannerScorecard }) {
  const rows = [
    { label: "Rules · all setups", count: score.setups, priced: score.rules_priced, pnl: score.rules_pnl, hint: "all setups", evidence: score.group_evidence.rules },
    { label: "Shadow · TAKEs", count: score.take, priced: score.shadow_priced, pnl: score.shadow_pnl, hint: "on-time TAKE decisions", evidence: score.group_evidence.takes },
    { label: "Rules · skipped", count: score.skip, priced: score.skipped_priced, pnl: score.skipped_rules_pnl, hint: "on-time SKIP decisions", evidence: score.group_evidence.skipped },
  ];
  return (
    <section className="min-w-0 rounded-lg border bg-card p-4" aria-label={`${label} scorecard`}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-sm font-semibold text-foreground">{label}</h2>
        <span className={`text-xs ${score.evidence === "not enough" ? "text-amber-300" : "text-muted-foreground"}`}>
          {score.evidence === "not enough" ? "Not enough evidence" : "30+ decisions"} · {score.decisions} decisions
        </span>
      </div>
      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-xs text-muted-foreground">
            <tr>
              <th className="pb-2 text-left font-medium">Group</th>
              <th className="pb-2 text-right font-medium">Count</th>
              <th className="pb-2 text-right font-medium">P&L</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.label} className="border-t">
                <td className="py-2 pr-2">
                  <div className="font-medium text-foreground">{row.label}</div>
                  <div className="text-xs text-muted-foreground">{row.hint}</div>
                  <div className={`text-[11px] ${row.evidence === "not enough" ? "text-amber-300" : "text-muted-foreground"}`}>
                    {row.evidence === "not enough" ? "Not enough evidence" : "30+ in group"}
                  </div>
                </td>
                <td className="px-2 py-2 text-right tabular-nums text-foreground">{row.count}</td>
                <td className={`py-2 pl-2 text-right tabular-nums ${row.pnl > 0 ? "text-emerald-400" : row.pnl < 0 ? "text-red-400" : "text-foreground"}`}>
                  <div>{money(row.pnl)}</div>
                  <div className="text-[11px] font-normal text-muted-foreground">{row.priced} priced</div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-xs leading-5 text-muted-foreground">
        TAKE {score.take} · SKIP {score.skip} · late {score.late} · no response {score.no_response} · unresolved {score.unresolved} · clean order {score.clean_order}
      </p>
      <p className="mt-1 text-xs text-muted-foreground">P&L is per contract after commission; each amount includes the priced count shown beside it.</p>
    </section>
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

function emailLabel(c: ScannerCandidateRow) {
  const status = String(c.events.email?.status ?? "");
  if (status === "sent") return { label: "Sent", className: "text-emerald-300" };
  if (status === "expired") return { label: "Expired", className: "text-amber-300" };
  if (status === "skipped_daily_cap") return { label: "Capped", className: "text-amber-300" };
  return { label: "—", className: "text-muted-foreground" };
}

function shadowDecisionLabel(c: ScannerCandidateRow) {
  if (c.shadow.decision) return c.shadow.decision === "take" ? "TAKE" : "SKIP";
  const labels: Record<ScannerCandidateRow["shadow"]["status"], string> = {
    no_contract: "No contract",
    awaiting_decision: "Awaiting",
    no_response: "No response",
    skipped: "SKIP",
    late: "Late",
    pending_entry: "TAKE · pending",
    open: "TAKE · open",
    exiting: "TAKE · exiting",
    exit: "TAKE · closed",
    unresolved: "Unresolved",
  };
  return labels[c.shadow.status];
}

function ShadowDecision({ c }: { c: ScannerCandidateRow }) {
  const detail = c.shadow.reason;
  return (
    <details className="relative max-w-56">
      <summary className="list-none cursor-pointer whitespace-nowrap rounded px-1 py-1 font-medium text-foreground hover:bg-secondary focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring">
        {shadowDecisionLabel(c)}
      </summary>
      <div className="mt-1 w-56 max-w-[calc(100vw-2rem)] space-y-1 rounded border bg-background p-2 text-xs shadow-lg">
        {detail && <p className="whitespace-normal text-foreground">{detail}</p>}
        {c.shadow.labels.length > 0 && (
          <div className="flex flex-wrap gap-1 pt-1">
            {c.shadow.labels.map((label) => (
              <span key={label} className="rounded bg-muted px-1.5 py-0.5 text-muted-foreground">{label}</span>
            ))}
          </div>
        )}
      </div>
    </details>
  );
}

function shadowResult(c: ScannerCandidateRow) {
  if (c.shadow.result) {
    return <span className={c.shadow.result.pnl > 0 ? "text-emerald-400" : c.shadow.result.pnl < 0 ? "text-red-400" : "text-foreground"}>{money(c.shadow.result.pnl)}</span>;
  }
  if (c.shadow.status === "unresolved") return <span className="text-xs text-amber-300">{c.shadow.unresolved_reason || "Unresolved"}</span>;
  if (c.shadow.entry) return <span className="text-xs text-muted-foreground">Open</span>;
  return <span className="text-xs text-muted-foreground">—</span>;
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
          one-contract paper trade: buy at the ask, sell at the bid, 60-minute time stop. Shadow Isaac takes or
          skips those setups for a separate paper book with the same contract and exits. Nothing here places
          real orders or changes your fills or trades.
        </p>
        {!data.enabled && (
          <p className="mt-2 text-sm text-amber-300">The scanner is switched off on this server, so no new setups are being recorded.</p>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-2 text-sm">
        <Link href={`/scanner?day=${shiftDay(data.date, -1)}`} className="inline-flex min-h-11 items-center rounded border px-3 hover:bg-secondary">
          ← Previous day
        </Link>
        <span className="px-1 font-medium text-foreground">{data.date}</span>
        <Link href={`/scanner?day=${shiftDay(data.date, 1)}`} className="inline-flex min-h-11 items-center rounded border px-3 hover:bg-secondary">
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

      <div className="grid gap-3 xl:grid-cols-2">
        <Scorecard label="Day scorecard" score={data.scorecard.day} />
        <Scorecard label="Cumulative scorecard" score={data.scorecard.cumulative} />
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
                  <th className="px-4 py-2 text-left font-medium">Email</th>
                  <th className="px-4 py-2 text-left font-medium">Shadow Isaac</th>
                  <th className="px-4 py-2 text-left font-medium">Timing</th>
                  <th className="px-4 py-2 text-left font-medium">Clean order</th>
                  <th className="px-4 py-2 text-left font-medium">Shadow result</th>
                </tr>
              </thead>
              <tbody>
                {data.candidates.map((c) => {
                  const status = STATUS[c.status];
                  const entry = c.events.entry;
                  const exit = c.events.exit;
                  const email = emailLabel(c);
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
                      <td className={`whitespace-nowrap px-4 py-2 text-xs ${email.className}`}>{email.label}</td>
                      <td className="px-4 py-2">
                        <ShadowDecision c={c} />
                      </td>
                      <td className="whitespace-nowrap px-4 py-2 text-xs text-muted-foreground">
                        {c.shadow.timing === "on_time" ? "On time" : c.shadow.timing === "late" ? "Late" : c.shadow.status === "no_response" ? "No response" : "—"}
                      </td>
                      <td className="whitespace-nowrap px-4 py-2 text-xs">
                        {c.shadow.clean_order === true ? <span className="text-emerald-300">Yes</span> : c.shadow.clean_order === false ? <span className="text-amber-300">No</span> : <span className="text-muted-foreground">—</span>}
                      </td>
                      <td className="whitespace-nowrap px-4 py-2 tabular-nums">{shadowResult(c)}</td>
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
