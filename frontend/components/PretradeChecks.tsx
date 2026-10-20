"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { advisorStamp } from "./AdvisorReceiptView";
import CheckActivity from "./CheckActivity";

type Verdict = "go" | "wait" | "pass" | "insufficient_data";
type Summary = { check_id: string; received_at: string; ticker: string; side: string; instrument: string; option_type: string | null;
  horizon: string; verdict: Verdict; model_verdict: Verdict | null; total_ms: number };
type Listing = { schema_version: "check-owner-list-v1"; checks: Summary[]; total: number; limit: number };
type Cohort = { name: string; definition: Record<string, string | null>; trades: number; distinct_days: number; enough: boolean;
  note?: string; win_rate?: number | null; avg_pnl?: number | null; total_pnl?: number | null; median_mfe_pct?: number | null;
  median_mae_pct?: number | null; loser_pattern?: string };
type OptionInfo = { contract: string; bid: number | null; ask: number | null; mid: number | null; spread_pct: number | null;
  iv: number | null; delta: number | null; theta_per_contract_per_day: number | null; cost_per_contract: number | null; dte: number | null;
  at_stop?: { estimated_premium: number; estimated_loss_per_contract: number } };
type Detail = {
  schema_version: "check-owner-detail-v1"; check_id: string; received_at: string; record_sha256: string;
  idea: Record<string, string | number | null>; free_text: string | null;
  answer: { verdict: Verdict; rules_version: string; wait_for: { condition: string | null; expires_at: string } | null;
    reasons: { source: string; text: string }[]; would_change: string | null;
    risk_check: { stop: number | null; note?: string; reference_price?: number; distance_pct?: number; scorer_invalidation?: string | null };
    history: { as_of_ny: string; cohorts: Cohort[]; trades_used: number; available?: boolean };
    live: { price: number | null; vwap: number | null; rvol: number | null; market_state: string | null; setup_score: number | null;
      trigger: string | null; invalidation: string | null; generated_at: string | null };
    option?: OptionInfo | null;
    caveats: string[] };
  features: { state: string; generated_at: string | null; age_seconds: number | null };
  timings_ms: Record<string, number>; errors: string[];
  model_verdict: { received_at: string; verdict: Verdict; summary: string } | null;
  result?: Result | null;
};
type Move = { state: string; move_pct?: number; best_pct?: number; worst_pct?: number; last_price?: number;
  reference_price?: number; stop_hit_ny?: string | null; window?: { from_ny: string; to_ny: string } };
type Result = { outcome: { state: string; trade_count?: number; wins?: number; total_pnl?: number | null }; move: Move };
type Group = { checks: number; measured: number; enough: boolean; note?: string; median_move_pct?: number; went_the_idea_way?: number;
  traded?: number; traded_pnl?: number | null; pnl?: number | null };
type Grades = { schema_version: "check-owner-grades-v1"; days: number; checks: number; settled: number;
  grade: { final_checks: number; followed: number; by_rules_verdict: Record<"go" | "wait" | "pass", Group>;
    overrode: { total: number; traded_against_wait_or_pass: Group; skipped_a_go: Group };
    jo: { with_verdict: number; agrees_with_rules: number } } };

const LABEL: Record<Verdict, string> = { go: "Go", wait: "Wait", pass: "Pass", insufficient_data: "Not enough data" };
const TONE: Record<Verdict, string> = {
  go: "border-emerald-600 text-emerald-700 dark:text-emerald-400", wait: "border-amber-500 text-amber-700 dark:text-amber-400",
  pass: "border-red-600 text-red-700 dark:text-red-400", insufficient_data: "border-muted-foreground text-muted-foreground",
};
const COHORT: Record<string, string> = { same_setup: "Same setup", same_ticker_side: "Same ticker and side" };

const Pill = ({ verdict }: { verdict: Verdict }) =>
  <span className={`inline-flex shrink-0 items-center rounded border px-1.5 py-0.5 text-xs font-medium ${TONE[verdict] ?? TONE.insufficient_data}`}>{LABEL[verdict] ?? verdict}</span>;
const idea = (c: { ticker: string | number | null; side: string | number | null; instrument: string | number | null; option_type?: string | number | null }) =>
  [c.ticker, c.side, c.instrument === "option" ? (c.option_type ?? "option") : c.instrument].filter(Boolean).join(" · ");
const SESSION: Record<string, string> = { rth: "regular session", premarket: "premarket", afterhours: "after hours", closed: "market closed" };
const num = (value: number | null | undefined, digits = 2) => value == null ? "—" : value.toFixed(digits);
const pct = (value: number | null | undefined) => value == null ? "—" : `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;
const money = (value: number | null | undefined) => value == null ? "—" : `${value < 0 ? "−" : ""}$${Math.abs(value).toFixed(0)}`;
const OUTCOME: Record<string, string> = { traded: "You traded it", no_closed_trade: "No closed trade on it",
  pending: "Pending", not_linked: "Not linked (swing)" };

function AfterCheck({ result }: { result: Result }) {
  const { outcome, move } = result;
  return <section aria-label="After the check"><h4 className="font-medium">After the check</h4>
    <p>{OUTCOME[outcome.state] ?? outcome.state}{outcome.state === "traded" && <> · {outcome.trade_count} trade{outcome.trade_count === 1 ? "" : "s"}, {outcome.wins} won, {money(outcome.total_pnl)}</>}</p>
    {move.state === "complete"
      ? <p className="text-muted-foreground">Price in the idea&apos;s direction until {move.window?.to_ny.slice(11)} ET: {pct(move.move_pct)} at the end, best {pct(move.best_pct)}, worst {pct(move.worst_pct)}{move.stop_hit_ny ? <> · stop hit {move.stop_hit_ny.slice(11)}</> : null}</p>
      : <p className="text-muted-foreground">Price move not measured ({move.state.replace(/_/g, " ")}).</p>}
  </section>;
}

function GradeRow({ label, group }: { label: string; group: Group }) {
  return <tr className="border-t">
    <th scope="row" className="py-1.5 pr-2 text-left font-medium">{label}</th>
    <td className="px-2 text-right tabular-nums">{group.checks}</td>
    <td className="px-2 text-right tabular-nums">{group.measured ? `${group.went_the_idea_way ?? 0}/${group.measured}` : "—"}</td>
    <td className="px-2 text-right tabular-nums">{pct(group.median_move_pct)}</td>
    <td className="whitespace-nowrap pl-2 text-right tabular-nums">{group.traded ? `${group.traded} · ${money(group.traded_pnl)}` : "—"}</td>
  </tr>;
}

function GradeView({ value }: { value: Grades }) {
  const { grade } = value;
  const against = grade.overrode.traded_against_wait_or_pass, skipped = grade.overrode.skipped_a_go;
  const thin = (["go", "wait", "pass"] as const).every(v => !grade.by_rules_verdict[v].enough);
  return <section aria-label="How the checks did" className="mt-3 border-t pt-3" data-testid="pretrade-grades">
    <h3 className="font-medium">How the checks did <span className="font-normal text-muted-foreground">last {value.days} days · {value.settled} of {value.checks} settled</span></h3>
    {grade.final_checks === 0 ? <p className="mt-1 text-muted-foreground">Nothing settled yet. A check settles after its window ends and the journal has its trades; ask Jo to review the day.</p> : <>
      <div className="mt-1 overflow-x-auto"><table className="w-full min-w-[20rem] text-sm">
        <thead className="text-xs text-muted-foreground"><tr><th className="text-left font-normal">Rules said</th><th className="px-2 text-right font-normal">Checks</th>
          <th className="px-2 text-right font-normal">Went its way</th><th className="px-2 text-right font-normal">Median move</th><th className="pl-2 text-right font-normal">You traded · P&amp;L</th></tr></thead>
        <tbody><GradeRow label="Go" group={grade.by_rules_verdict.go} /><GradeRow label="Wait" group={grade.by_rules_verdict.wait} /><GradeRow label="Pass" group={grade.by_rules_verdict.pass} /></tbody>
      </table></div>
      <p className="mt-2">You followed the rules {grade.followed} time{grade.followed === 1 ? "" : "s"} and overrode them {grade.overrode.total}.</p>
      {against.checks > 0 && <p className="text-muted-foreground">Traded against a Wait or Pass: {against.checks} · {money(against.pnl)}</p>}
      {skipped.checks > 0 && <p className="text-muted-foreground">Skipped a Go: {skipped.checks} · median move after {pct(skipped.median_move_pct)}</p>}
      <p className="text-muted-foreground">Jo saved its own verdict on {grade.jo.with_verdict}; it agreed with the rules on {grade.jo.agrees_with_rules}.</p>
      {thin && <p className="mt-1 text-xs text-muted-foreground">Not enough evidence yet: each group needs 10 settled checks before it means much.</p>}
    </>}
  </section>;
}

// Not switched on is configuration, not an outage: the section stays out of the way.
const DORMANT = "Pre-trade check review is not switched on yet";
class Dormant extends Error {}

async function readJson<T>(url: string, signal: AbortSignal, schema: string): Promise<T> {
  const response = await fetch(url, { cache: "no-store", redirect: "error", signal });
  const body = await response.json();
  if (response.status === 503 && body.detail === DORMANT) throw new Dormant(DORMANT);
  if (!response.ok) throw new Error(body.detail ?? "Saved pre-trade checks unavailable.");
  if (body.schema_version !== schema) throw new Error("Unsupported pre-trade check response.");
  return body as T;
}

function CohortLine({ cohort }: { cohort: Cohort }) {
  const d = cohort.definition;
  const where = [d.underlying, d.side, d.time_bucket && `${d.time_bucket} of day`, d.vwap_bucket && `${d.vwap_bucket} VWAP`].filter(Boolean).join(" · ");
  return <li className="py-1.5">
    <p><span className="font-medium">{COHORT[cohort.name] ?? cohort.name}</span> <span className="text-muted-foreground">({where})</span></p>
    <p>{cohort.trades} trades over {cohort.distinct_days} days{cohort.enough
      ? <> · won {cohort.win_rate == null ? "—" : `${Math.round(cohort.win_rate * 100)}%`} · average P&amp;L {num(cohort.avg_pnl)} · median best {num(cohort.median_mfe_pct, 3)}% / worst {num(cohort.median_mae_pct, 3)}%</>
      : <> · {cohort.note ?? "not enough history"}</>}</p>
    {cohort.loser_pattern && <p className="text-muted-foreground">{cohort.loser_pattern}</p>}
  </li>;
}

function CheckDetail({ value, journal }: { value: Detail; journal: boolean }) {
  const { answer } = value;
  return <div className="space-y-3 border-t pt-3" data-testid="pretrade-check-detail">
    <div className="flex flex-wrap items-center gap-2"><Pill verdict={answer.verdict} /><span className="font-medium">{idea(value.idea as never)}</span>
      <span className="text-muted-foreground">{value.idea.horizon}{value.idea.stop != null && <> · stop {value.idea.stop}</>}</span></div>
    {answer.wait_for && <p><span className="font-medium">Wait for:</span> {answer.wait_for.condition ?? "no trigger given"} (until {advisorStamp(answer.wait_for.expires_at)})</p>}
    {answer.reasons.length > 0 && <ul className="list-disc space-y-0.5 pl-5">{answer.reasons.map((r, i) => <li key={i} className="break-words"><span className="text-muted-foreground">{r.source}:</span> {r.text}</li>)}</ul>}
    {answer.would_change && <p><span className="font-medium">Would change:</span> {answer.would_change}</p>}
    <p><span className="font-medium">Stop:</span> {answer.risk_check.stop == null ? (answer.risk_check.note ?? "none given")
      : <>{answer.risk_check.stop}{answer.risk_check.distance_pct != null && <> · {answer.risk_check.distance_pct}% from {answer.risk_check.reference_price}</>}{answer.risk_check.note && <> · {answer.risk_check.note}</>}</>}</p>
    <section aria-label="Live data"><h4 className="font-medium">Live data</h4>
      <p>Price {num(answer.live.price)} · VWAP {num(answer.live.vwap)} · RVOL {num(answer.live.rvol)} · setup {answer.live.setup_score ?? "—"} · {SESSION[answer.live.market_state ?? ""] ?? "session unknown"}</p>
      {answer.live.trigger && <p className="text-muted-foreground">Trigger: {answer.live.trigger}</p>}
      {answer.live.invalidation && <p className="text-muted-foreground">Invalidation: {answer.live.invalidation}</p>}
    </section>
    {answer.option && <section aria-label="Option"><h4 className="font-medium">Option <span className="font-normal text-muted-foreground">{answer.option.contract}{answer.option.dte != null && <> · {answer.option.dte} DTE</>}</span></h4>
      <p>Bid {num(answer.option.bid)} · ask {num(answer.option.ask)} · spread {answer.option.spread_pct == null ? "—" : `${answer.option.spread_pct}%`} · IV {answer.option.iv == null ? "—" : `${Math.round(answer.option.iv * 100)}%`} · delta {num(answer.option.delta)}</p>
      <p>Cost {answer.option.cost_per_contract == null ? "—" : `$${answer.option.cost_per_contract}`}/contract · time decay {answer.option.theta_per_contract_per_day == null ? "—" : `${answer.option.theta_per_contract_per_day < 0 ? "−" : ""}$${Math.abs(answer.option.theta_per_contract_per_day)}`}/day{answer.option.at_stop && <> · at your stop ≈ ${answer.option.at_stop.estimated_loss_per_contract} loss/contract (delta estimate)</>}</p>
    </section>}
    <section aria-label="Your similar trades"><h4 className="font-medium">Your similar trades <span className="font-normal text-muted-foreground">closed before {answer.history.as_of_ny.replace("T", " ")} ET</span></h4>
      {answer.history.available === false ? <p>No trade history was available for this check.</p>
        : <ul className="divide-y">{answer.history.cohorts.map(c => <CohortLine key={c.name} cohort={c} />)}</ul>}
    </section>
    {answer.caveats.length > 0 && <section aria-label="Caveats"><h4 className="font-medium">Caveats</h4>
      <ul className="list-disc pl-5 text-muted-foreground">{answer.caveats.map((c, i) => <li key={i} className="break-words">{c}</li>)}</ul></section>}
    {value.result && <AfterCheck result={value.result} />}
    {journal && <CheckActivity checkId={value.check_id} facts={{ ticker: value.idea.ticker as string | null, received_at: value.received_at,
      instrument: value.idea.instrument as string | null, option_type: value.idea.option_type as string | null,
      strike: value.idea.strike, expiration: value.idea.expiration as string | null }} />}
    <section aria-label="Jo's note"><h4 className="font-medium">Jo</h4>
      {value.model_verdict ? <p className="break-words"><Pill verdict={value.model_verdict.verdict} /> {value.model_verdict.summary} <span className="text-muted-foreground">({advisorStamp(value.model_verdict.received_at)})</span></p>
        : <p className="text-muted-foreground">Jo didn&apos;t attach a note.</p>}
    </section>
    {value.free_text && <p className="break-words text-muted-foreground">Your words to Jo (stored, never used in the rules): {value.free_text}</p>}
    <p className="break-words text-xs text-muted-foreground">Asked {advisorStamp(value.received_at)} · {answer.rules_version} · history {value.features.state} · {value.timings_ms.total} ms · record {value.record_sha256.slice(0, 12)}</p>
  </div>;
}

// journal: rendered by the private journal, which adds what the journal recorded afterwards (Dots step 5).
export default function PretradeChecks({ journal = false }: { journal?: boolean }) {
  const [listing, setListing] = useState<Listing | null>(null);
  const [grades, setGrades] = useState<Grades | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [dormant, setDormant] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [detailError, setDetailError] = useState("");
  const sequence = useRef(0);
  const controller = useRef<AbortController | null>(null);

  const reload = useCallback(async () => {
    const current = ++sequence.current;
    controller.current?.abort();
    const pending = new AbortController(); controller.current = pending;
    setLoading(true); setError(""); setOpen(null); setDetail(null);
    try {
      const body = await readJson<Listing>("/api/check-owner/checks", pending.signal, "check-owner-list-v1");
      if (current === sequence.current) setListing(body);
      // Grades are secondary: a failure hides them and leaves the list usable.
      const graded = await readJson<Grades>("/api/check-owner/grades", pending.signal, "check-owner-grades-v1").catch(() => null);
      if (current === sequence.current) setGrades(graded);
    } catch (err) {
      if (current === sequence.current && !pending.signal.aborted && err instanceof Dormant) setDormant(true);
      else if (current === sequence.current && !pending.signal.aborted) { setListing(null); setError(err instanceof Error ? err.message : "Saved pre-trade checks unavailable."); }
    } finally { if (current === sequence.current) setLoading(false); }
  }, []);

  const toggle = useCallback(async (checkId: string) => {
    const current = ++sequence.current;
    controller.current?.abort();
    if (open === checkId) { setOpen(null); setDetail(null); return; }
    const pending = new AbortController(); controller.current = pending;
    setOpen(checkId); setDetail(null); setDetailError("");
    try {
      const body = await readJson<Detail>(`/api/check-owner/checks/${checkId}`, pending.signal, "check-owner-detail-v1");
      if (current === sequence.current) setDetail(body);
    } catch (err) {
      if (current === sequence.current && !pending.signal.aborted) setDetailError(err instanceof Error ? err.message : "Check unavailable.");
    }
  }, [open]);

  useEffect(() => {
    let active = true;
    queueMicrotask(() => { if (active) void reload(); });
    return () => { active = false; sequence.current += 1; controller.current?.abort(); };
  }, [reload]);

  // ?check=chk_… (from a trade's page) opens that check once the list has loaded.
  const wanted = useRef<string | null>(null);
  useEffect(() => {
    const value = new URLSearchParams(window.location.search).get("check");
    if (listing && !loading && value && /^chk_[0-9a-f-]{36}$/.test(value) && wanted.current !== value) { wanted.current = value; void toggle(value); }
  }, [listing, loading, toggle]);

  if (dormant) return journal ? <section className="mx-auto mb-4 max-w-4xl rounded border bg-card p-3 text-sm" data-testid="pretrade-checks-dormant">
    <h2 className="font-semibold">Pre-trade checks</h2>
    <p className="mt-1">Saved advice isn&apos;t connected to the journal yet, so Jo&apos;s checks and what happened after them can&apos;t be shown here.</p>
  </section> : null;
  return <section className="mx-auto mb-4 max-w-4xl rounded border bg-card p-3 text-sm" data-testid="pretrade-checks" aria-labelledby="pretrade-checks-heading">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h2 id="pretrade-checks-heading" className="font-semibold">Pre-trade checks</h2>
      <button type="button" onClick={() => void reload()} disabled={loading} className="min-h-11 rounded border px-3 py-2 text-sm disabled:opacity-50">Refresh</button>
    </div>
    <p className="mt-1 text-muted-foreground">What Jo asked, the rules&apos; answer and the data behind it. Saved checks never change.</p>
    {loading && <p role="status" className="mt-2">Loading saved checks…</p>}
    {error && <p role="alert" className="mt-2 break-words">{error}</p>}
    {listing && listing.checks.length === 0 && <p className="mt-2">No checks yet. Ask Jo for a pre-trade check during market hours.</p>}
    {listing && open && !listing.checks.some(c => c.check_id === open) && <div className="border-t pb-3" data-testid="pretrade-check-linked">
      {!detail && !detailError && <p role="status">Opening the saved check…</p>}
      {detailError && <p role="alert" className="break-words">{detailError}</p>}
      {detail && <CheckDetail value={detail} journal={journal} />}
    </div>}
    {listing && listing.checks.length > 0 && <>
      <ul className="mt-2 divide-y">{listing.checks.map(c => <li key={c.check_id} data-testid="pretrade-check-row">
        <button type="button" onClick={() => void toggle(c.check_id)} aria-expanded={open === c.check_id}
          className="flex min-h-11 w-full flex-wrap items-center gap-x-3 gap-y-1 py-2 text-left">
          <Pill verdict={c.verdict} />
          <span className="font-medium">{idea(c)}</span>
          <span className="text-muted-foreground">{advisorStamp(c.received_at)}</span>
          <span className="ml-auto text-muted-foreground">{c.model_verdict ? <>Jo: {LABEL[c.model_verdict] ?? c.model_verdict}</> : "No Jo note"}</span>
        </button>
        {open === c.check_id && <div className="pb-3">
          {!detail && !detailError && <p role="status">Opening the saved check…</p>}
          {detailError && <p role="alert" className="break-words">{detailError}</p>}
          {detail && <CheckDetail value={detail} journal={journal} />}
        </div>}
      </li>)}</ul>
      {listing.total > listing.checks.length && <p className="mt-1 text-xs text-muted-foreground">Showing the newest {listing.checks.length} of {listing.total}.</p>}
      {grades && <GradeView value={grades} />}
    </>}
  </section>;
}
