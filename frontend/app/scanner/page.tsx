import Link from "next/link";
import ScannerFreshness from "@/components/ScannerFreshness";
import ScannerTickers from "@/components/ScannerTickers";
import { api } from "@/lib/serverApi";
import type { ScannerCandidateRow, ScannerScorecard, ScannerIsaacScore } from "@/lib/api";

export const dynamic = "force-dynamic";

const STATUS: Record<ScannerCandidateRow["status"], { label: string; className: string }> = {
  no_contract: { label: "Paper: no contract", className: "bg-muted text-muted-foreground" },
  pending_entry: { label: "Paper: awaiting entry", className: "bg-sky-500/15 text-sky-300" },
  open: { label: "Paper: open", className: "bg-sky-500/15 text-sky-300" },
  exiting: { label: "Paper: exiting", className: "bg-sky-500/15 text-sky-300" },
  exit: { label: "Paper: closed", className: "bg-secondary text-foreground" },
  unresolved: { label: "Paper: unresolved", className: "bg-amber-500/15 text-amber-300" },
};

const EXIT_REASON: Record<string, string> = {
  stop: "Stop",
  target: "Target",
  time_stop: "60-min time stop",
  flat: "Flat by close",
};

function nyTime(iso: string, seconds = false) {
  return new Date(iso).toLocaleTimeString("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit", ...(seconds ? { second: "2-digit" } : {}) });
}

function nyDate(now: Date) {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York" }).format(now);
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
    { label: "Shadow · TAKEs", count: score.take, priced: score.shadow_priced, pnl: score.shadow_priced ? score.shadow_pnl : null, hint: "on-time TAKE decisions", evidence: score.group_evidence.takes },
    { label: "Rules · skipped", count: score.skip, priced: score.skipped_priced, pnl: score.skipped_priced ? score.skipped_rules_pnl : null, hint: "on-time SKIP decisions", evidence: score.group_evidence.skipped },
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
                <td className={`py-2 pl-2 text-right tabular-nums ${(row.pnl ?? 0) > 0 ? "text-emerald-400" : (row.pnl ?? 0) < 0 ? "text-red-400" : "text-foreground"}`}>
                  <div>{row.pnl === null ? "No evaluated trades" : money(row.pnl)}</div>
                  <div className="text-[11px] font-normal text-muted-foreground">{row.priced} priced</div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-xs leading-5 text-muted-foreground">
        TAKE {score.take} · SKIP {score.skip} · late {score.late} · no response {score.no_response} · unresolved {score.unresolved} · not published {score.not_published} · published/evaluated {score.shadow_setups} · clean order {score.clean_order}
      </p>
      <p className="mt-1 text-xs text-muted-foreground">No response means published without a decision; email send status does not prove receipt. P&L is per contract after commission; each amount includes the priced count shown beside it.</p>
      <IsaacComparison label="All linked trades" score={score.isaac} />
      <details className="mt-3 border-t pt-3">
        <summary className="min-h-11 cursor-pointer text-sm font-medium">No prior setup email comparison</summary>
        <p className="text-xs text-muted-foreground">Excludes every setup with an assisted linked trade. Missing, late and unpublished shadow decisions are excluded from disagreements.</p>
        <IsaacComparison label="No prior setup email" score={score.independent} />
      </details>
    </section>
  );
}

function IsaacComparison({ label, score }: { label: string; score: ScannerIsaacScore }) {
  const labels = { shadow_only: "Shadow TAKE · no linked trade", isaac_only: "Isaac traded · Shadow SKIP", both_took: "Shadow TAKE · linked trade", both_passed: "Shadow SKIP · no linked trade" };
  return (
    <div className="mt-3 border-t pt-3" aria-label={label}>
      <h3 className="text-sm font-semibold">Isaac · {label}</h3>
      <p className="mt-1 text-xs text-muted-foreground">{score.traded} / {score.setups} setups linked · {score.assisted} with email before entry · {score.independent} without prior setup email · {score.closed} closed trades</p>
      <p className="mt-1 text-sm tabular-nums">{score.priced ? `${money(score.pnl_per_contract)} / contract · ${money(score.pnl_dollars)} actual dollars` : "No evaluated trades"}</p>
      <p className="mt-1 text-[11px] text-amber-300">
        {score.evidence === "not enough" ? "Not enough evidence" : "30+ traded setups"}
        {(["assisted", "independent", "closed"] as const).map((key) => score.group_evidence[key] === "not enough" ? ` · ${key === "assisted" ? "email before entry" : key === "independent" ? "no prior email" : "closed"}: <30` : ` · ${key === "assisted" ? "email before entry" : key === "independent" ? "no prior email" : "closed"}: 30+`)}
      </p>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full min-w-[480px] text-xs" aria-label={`${label} disagreements`}>
          <thead className="text-muted-foreground"><tr>
            <th className="py-2 text-left font-medium">Disagreements</th>
            <th className="p-2 text-right font-medium">Count</th>
            <th className="p-2 text-right font-medium">Rules / ct</th>
            <th className="p-2 text-right font-medium">Shadow / ct</th>
            <th className="py-2 pl-2 text-right font-medium">Isaac / ct</th>
          </tr></thead>
          <tbody>{(Object.keys(labels) as Array<keyof typeof labels>).map((key) => {
            const group = score.disagreements[key];
            return <tr key={key} className="border-t align-top">
              <td className="py-2 pr-2"><div>{labels[key]}</div><div className="mt-1 text-[11px] text-amber-300">{group.evidence === "not enough" ? "Not enough evidence" : "30+ in group"}</div></td>
              <td className="p-2 text-right tabular-nums">{group.count}</td>
              <td className="p-2 text-right tabular-nums">{money(group.rules_priced ? group.rules_pnl : null)}<div className="text-muted-foreground">{group.rules_priced} priced</div></td>
              <td className="p-2 text-right tabular-nums">{money(group.shadow_priced ? group.shadow_pnl : null)}<div className="text-muted-foreground">{group.shadow_priced} priced</div></td>
              <td className="py-2 pl-2 text-right tabular-nums">{money(group.isaac_priced ? group.isaac_pnl_per_contract : null)}<div className="text-muted-foreground">{group.isaac_priced} priced</div>{group.isaac_priced > 0 && <div className="mt-1 text-muted-foreground">{money(group.isaac_pnl_dollars)} actual $</div>}</td>
            </tr>;
          })}</tbody>
        </table>
      </div>
      <p className="mt-2 text-[11px] text-muted-foreground">Counts are setups; results sum priced trades per contract. Shadow SKIP with no linked trade shows rules results only. Assisted means an email was sent before entry; it does not prove the email was read or followed. No prior email does not establish independence.</p>
    </div>
  );
}

function IsaacTrade({ c }: { c: ScannerCandidateRow }) {
  if (!c.isaac.traded) return <span className="text-xs text-muted-foreground">No linked trade</span>;
  return <details className="min-w-36">
    <summary className="min-h-11 cursor-pointer">
      <span className="font-medium">Traded</span>
      {c.isaac.assisted && <span className="ml-2 rounded bg-amber-500/15 px-1.5 py-0.5 text-[11px] text-amber-300">Assisted</span>}
      <div className="mt-1 whitespace-nowrap text-xs tabular-nums">{c.isaac.status === "open" ? "Open" : c.isaac.pnl_per_contract === null ? "Unpriced" : `${money(c.isaac.pnl_per_contract)} / ct`}</div>
      {c.isaac.extra_trade_ids.length > 0 && <div className="text-xs text-muted-foreground">+{c.isaac.extra_trade_ids.length} more trades</div>}
    </summary>
    <div className="mt-2 space-y-3 text-xs">{c.isaac.trades.map((trade) => <div key={trade.trade_id}>
      <div className="break-all font-medium">Trade {trade.trade_id}</div>
      <div>{trade.contract.expiration} {trade.contract.strike}{trade.contract.option_type === "call" ? "C" : "P"}</div>
      <div>{nyTime(trade.opened_at)} ET · {trade.status} · {trade.assisted ? "Email before entry" : "No prior setup email"}</div>
      <div>{trade.status === "open" ? "Open" : `${money(trade.pnl_per_contract)} / ct · ${money(trade.realized_pnl)} actual $`}</div>
      {trade.contract_differs && <div className="text-muted-foreground">Different strike or expiration</div>}
    </div>)}</div>
  </details>;
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

function price(value: unknown) {
  return `$${Number(value).toFixed(2)}`;
}

// The newest thing that happened to the rules paper trade, with its own time.
function latestEvent(c: ScannerCandidateRow): { text: string; pnl?: number } {
  const { entry, exit, exit_intent: intent, unresolved } = c.events;
  if (exit) return { text: `Paper exit ${nyTime(exit.at, true)} ET · ${EXIT_REASON[String(exit.reason)] ?? exit.reason}`, pnl: Number(exit.pnl) };
  if (unresolved) return { text: `Paper unresolved ${nyTime(unresolved.at, true)} ET · ${String(unresolved.reason)}` };
  if (intent) return { text: `Paper exiting since ${nyTime(intent.at, true)} ET · ${EXIT_REASON[String(intent.reason)] ?? intent.reason}` };
  if (entry) return { text: `Paper entry ${nyTime(entry.at, true)} ET at ${price(entry.ask)} ask` };
  if (c.status === "no_contract") return { text: `No paper trade · ${c.facts.contract_note ? String(c.facts.contract_note) : "no qualifying contract"}` };
  return { text: `Setup bar close ${nyTime(c.bar_end)} ET · waiting for an entry quote` };
}

function Timing({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</dt>
      <dd className="tabular-nums text-foreground">{value}</dd>
      {hint && <dd className="text-xs text-muted-foreground">{hint}</dd>}
    </div>
  );
}

function SetupCard({ c }: { c: ScannerCandidateRow }) {
  const status = STATUS[c.status];
  const { entry, exit } = c.events;
  const latest = latestEvent(c);
  const email = emailLabel(c);
  const deadline = c.paper_deadline;
  return (
    <li className="border-t px-4 py-3 first:border-t-0" aria-label={`${c.symbol} ${setupLabel(c)} ${nyTime(c.bar_end)}`}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="text-base font-semibold text-foreground">{c.symbol}</span>
        <span className="text-sm text-muted-foreground">{setupLabel(c)}</span>
        <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${status.className}`}>{status.label}</span>
      </div>
      <p className="mt-1 text-sm" data-testid="latest-event">
        {latest.text}
        {latest.pnl !== undefined && (
          <span className={`ml-2 font-medium tabular-nums ${latest.pnl > 0 ? "text-emerald-400" : latest.pnl < 0 ? "text-red-400" : ""}`}>{money(latest.pnl)}</span>
        )}
      </p>
      <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-3 lg:grid-cols-6">
        <Timing label="Setup bar close" value={`${nyTime(c.bar_end)} ET`} />
        <Timing label="Paper entry" value={entry ? `${nyTime(entry.at, true)} ET` : "—"} hint={entry ? `${price(entry.ask)} ask` : undefined} />
        <Timing label="Paper exit" value={exit ? `${nyTime(exit.at, true)} ET` : "—"}
          hint={exit ? `${price(exit.bid)} bid · ${EXIT_REASON[String(exit.reason)] ?? exit.reason}` : deadline ? `${deadline.kind === "flat" ? "Flat by" : "Time stop"} ${nyTime(deadline.at, true)} ET` : undefined} />
        <Timing label="Stock stop/target" value={`${c.stop.toFixed(2)} / ${c.target.toFixed(2)}`} />
        <Timing label="Option premium" value={entry ? `${price(entry.ask)}${exit ? ` → ${price(exit.bid)}` : ""}` : "—"} hint={contractLabel(c) ?? "No contract"} />
        {deadline && <Timing label={deadline.kind === "flat" ? "Flat-by-close deadline" : "Time-stop deadline"} value={`${nyTime(deadline.at, true)} ET`} hint={deadline.kind === "flat" ? "before the 60-min time stop" : "entry + 60 min"} />}
      </dl>
      {c.flags.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {c.flags.map((f) => (
            <span key={f} className="rounded bg-amber-500/15 px-1.5 py-0.5 text-[11px] text-amber-300">{f.replaceAll("_", " ")}</span>
          ))}
        </div>
      )}
      <details className="mt-1 text-sm">
        <summary className="min-h-11 cursor-pointer py-2 text-muted-foreground">Comparison detail · Shadow {shadowDecisionLabel(c)} · Isaac {c.isaac.traded ? "traded" : "no linked trade"}</summary>
        <dl className="grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-3 lg:grid-cols-6">
          <div><dt className="text-[11px] uppercase tracking-wide text-muted-foreground">Setup email</dt><dd className={email.className}>{email.label}</dd></div>
          <div><dt className="text-[11px] uppercase tracking-wide text-muted-foreground">Shadow Isaac</dt><dd><ShadowDecision c={c} /></dd></div>
          <div><dt className="text-[11px] uppercase tracking-wide text-muted-foreground">Shadow timing</dt><dd>{c.shadow.timing === "on_time" ? "On time" : c.shadow.timing === "late" ? "Late" : c.shadow.status === "no_response" ? "No response" : "—"}</dd></div>
          <div><dt className="text-[11px] uppercase tracking-wide text-muted-foreground">Clean order</dt><dd>{c.shadow.clean_order === true ? <span className="text-emerald-300">Yes</span> : c.shadow.clean_order === false ? <span className="text-amber-300">No</span> : "—"}</dd></div>
          <div><dt className="text-[11px] uppercase tracking-wide text-muted-foreground">Shadow paper result</dt><dd className="tabular-nums">{shadowResult(c)}</dd></div>
          <div><dt className="text-[11px] uppercase tracking-wide text-muted-foreground">Isaac</dt><dd><IsaacTrade c={c} /></dd></div>
        </dl>
        <p className="mt-2 text-xs text-muted-foreground">Scanner configuration: {c.scanner_version} · {c.params_hash.slice(0, 12)} · {Array.isArray(c.facts.scanner_universe) ? c.facts.scanner_universe.join(", ") : "Original 12-ticker universe"}</p>
      </details>
    </li>
  );
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
    not_published: "Not published",
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
        <p className="text-muted-foreground">Publication: {c.shadow.publication === "written" ? "Recorded" : c.shadow.publication === "expired" ? "Expired before handoff" : "No handoff record"}</p>
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
  const now = new Date();
  const live = data.date === nyDate(now);
  const t = data.totals;
  const winRate = t.resolved ? `${Math.round((100 * t.wins) / t.resolved)}%` : "—";

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-foreground">Scanner</h1>
        <p className="mt-2 max-w-3xl text-sm text-muted-foreground">
          Rules paper trades from the setup scanner: one contract, bought at the ask and sold at the bid. They are not your trades and nothing here places orders.
          {" "}<strong className="font-medium text-foreground">Shadow</strong>{" "}is Jo&apos;s own TAKE or SKIP on each setup, kept as a separate paper book.
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

      <ScannerFreshness updatedAt={now.toISOString()} monitoring={data.monitoring} live={live} />

      <section className="overflow-hidden rounded-lg border bg-card" aria-label="Setups">
        <h2 className="border-b px-4 py-2 text-sm font-semibold text-foreground">Setups · {data.candidates.length}</h2>
        {data.candidates.length === 0 ? (
          <div className="px-5 py-10 text-center text-sm text-muted-foreground">
            {data.session === "closed" ? "The market was closed on this date, so there was no session and no setups." : "No setups on this day."}
          </div>
        ) : (
          <ul>{data.candidates.map((c) => <SetupCard key={c.id} c={c} />)}</ul>
        )}
      </section>

      {/* A day without setups, and a scanner without any history, collapse to one line instead of tables of zeros. */}
      {t.candidates === 0 && data.scorecard.cumulative.setups === 0 ? (
        <p className="text-sm text-muted-foreground" data-testid="scanner-no-history">No setups recorded yet, so there are no paper results or scorecards to show.</p>
      ) : <>
      {t.candidates > 0 && <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <Card label="Setups" value={String(t.candidates)} hint={`${t.no_contract} without a contract`} />
        <Card label="Paper trades" value={String(t.trades)} hint={`${t.unresolved} unresolved`} />
        <Card label="Win rate" value={winRate} hint={`${t.resolved} closed`} />
        <Card label="Rules paper P&L · one contract per priced setup" value={money(t.pnl)} hint="after commission" />
        <Card label="At 2× spread" value={money(t.pnl_2x_spread)} hint="pessimistic fills" />
      </div>}

      <div className="grid gap-3 xl:grid-cols-2">
        {t.candidates > 0 && <Scorecard label="Day scorecard" score={data.scorecard.day} />}
        <Scorecard label="Cumulative scorecard" score={data.scorecard.cumulative} />
      </div>
      </>}

      <ScannerTickers />

      <p className="max-w-3xl text-xs text-muted-foreground">
        Setups are found by the rules (VWAP fade and opening-range break). Each would be a one-contract paper trade: buy at the ask, sell at the bid,
        60-minute time stop. Shadow Isaac takes or skips those setups for a separate paper book with the same contract and exits. Isaac’s matched real
        trades appear alongside them. Matching does not prove a setup was followed; actual contracts and exits may differ. Nothing here places real
        orders or changes your fills or trades.
      </p>
      <p className="text-xs text-muted-foreground">
        Baseline rules {data.scanner_version} · {data.params_hash.slice(0, 12)}. Results include the ticker lists used at detection, including earlier selections. Paper results are not
        evidence of an edge until enough trades have closed.
      </p>
    </div>
  );
}
