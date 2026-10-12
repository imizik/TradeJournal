"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { advisorStamp } from "./AdvisorReceiptView";

type Verdict = "go" | "wait" | "pass" | "insufficient_data";
type Summary = { check_id: string; received_at: string; ticker: string; side: string; instrument: string; option_type: string | null;
  horizon: string; verdict: Verdict; model_verdict: Verdict | null; total_ms: number };
type Listing = { schema_version: "check-owner-list-v1"; checks: Summary[]; total: number; limit: number };
type Cohort = { name: string; definition: Record<string, string | null>; trades: number; distinct_days: number; enough: boolean;
  note?: string; win_rate?: number | null; avg_pnl?: number | null; total_pnl?: number | null; median_mfe_pct?: number | null;
  median_mae_pct?: number | null; loser_pattern?: string };
type Detail = {
  schema_version: "check-owner-detail-v1"; check_id: string; received_at: string; record_sha256: string;
  idea: Record<string, string | number | null>; free_text: string | null;
  answer: { verdict: Verdict; rules_version: string; wait_for: { condition: string | null; expires_at: string } | null;
    reasons: { source: string; text: string }[]; would_change: string | null;
    risk_check: { stop: number | null; note?: string; reference_price?: number; distance_pct?: number; scorer_invalidation?: string | null };
    history: { as_of_ny: string; cohorts: Cohort[]; trades_used: number; available?: boolean };
    live: { price: number | null; vwap: number | null; rvol: number | null; market_state: string | null; setup_score: number | null;
      trigger: string | null; invalidation: string | null; generated_at: string | null };
    caveats: string[] };
  features: { state: string; generated_at: string | null; age_seconds: number | null };
  timings_ms: Record<string, number>; errors: string[];
  model_verdict: { received_at: string; verdict: Verdict; summary: string } | null;
};

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

async function readJson<T>(url: string, signal: AbortSignal, schema: string): Promise<T> {
  const response = await fetch(url, { cache: "no-store", redirect: "error", signal });
  const body = await response.json();
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

function CheckDetail({ value }: { value: Detail }) {
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
    <section aria-label="Your similar trades"><h4 className="font-medium">Your similar trades <span className="font-normal text-muted-foreground">closed before {answer.history.as_of_ny.replace("T", " ")} ET</span></h4>
      {answer.history.available === false ? <p>No trade history was available for this check.</p>
        : <ul className="divide-y">{answer.history.cohorts.map(c => <CohortLine key={c.name} cohort={c} />)}</ul>}
    </section>
    {answer.caveats.length > 0 && <section aria-label="Caveats"><h4 className="font-medium">Caveats</h4>
      <ul className="list-disc pl-5 text-muted-foreground">{answer.caveats.map((c, i) => <li key={i} className="break-words">{c}</li>)}</ul></section>}
    <section aria-label="Jo's note"><h4 className="font-medium">Jo</h4>
      {value.model_verdict ? <p className="break-words"><Pill verdict={value.model_verdict.verdict} /> {value.model_verdict.summary} <span className="text-muted-foreground">({advisorStamp(value.model_verdict.received_at)})</span></p>
        : <p className="text-muted-foreground">Jo didn&apos;t attach a note.</p>}
    </section>
    {value.free_text && <p className="break-words text-muted-foreground">Your words to Jo (stored, never used in the rules): {value.free_text}</p>}
    <p className="break-words text-xs text-muted-foreground">Asked {advisorStamp(value.received_at)} · {answer.rules_version} · history {value.features.state} · {value.timings_ms.total} ms · record {value.record_sha256.slice(0, 12)}</p>
  </div>;
}

export default function PretradeChecks() {
  const [listing, setListing] = useState<Listing | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
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
    } catch (err) {
      if (current === sequence.current && !pending.signal.aborted) { setListing(null); setError(err instanceof Error ? err.message : "Saved pre-trade checks unavailable."); }
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

  return <section className="mx-auto mb-4 max-w-4xl rounded border bg-card p-3 text-sm" data-testid="pretrade-checks" aria-labelledby="pretrade-checks-heading">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h2 id="pretrade-checks-heading" className="font-semibold">Pre-trade checks</h2>
      <button type="button" onClick={() => void reload()} disabled={loading} className="min-h-11 rounded border px-3 py-2 text-sm disabled:opacity-50">Refresh</button>
    </div>
    <p className="mt-1 text-muted-foreground">What Jo asked, the rules&apos; answer and the data behind it. Saved checks never change.</p>
    {loading && <p role="status" className="mt-2">Loading saved checks…</p>}
    {error && <p role="alert" className="mt-2 break-words">{error}</p>}
    {listing && listing.checks.length === 0 && <p className="mt-2">No checks yet. Ask Jo for a pre-trade check during market hours.</p>}
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
          {detail && <CheckDetail value={detail} />}
        </div>}
      </li>)}</ul>
      {listing.total > listing.checks.length && <p className="mt-1 text-xs text-muted-foreground">Showing the newest {listing.checks.length} of {listing.total}.</p>}
    </>}
  </section>;
}
