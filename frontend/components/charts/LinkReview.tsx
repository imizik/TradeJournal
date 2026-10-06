"use client";

import { useState } from "react";
import { Link2, Loader2, X } from "lucide-react";
import { etTime } from "@/lib/charts";
import { captureTime, captureTitle, TIMING_LABEL } from "@/lib/captures";
import type { Capture, CaptureReview, CaptureSetup, CaptureTiming, LinkCandidate } from "@/lib/captures";

const TIMING_STYLE: Record<CaptureTiming, string> = { pre_entry: "text-emerald-300", unverified: "text-amber-300", retrospective: "text-slate-400" };

function Candidate({ row, busy, onLink }: { row: LinkCandidate; busy: boolean; onLink(): void }) {
  return <li className="flex items-center gap-2">
    <span className="min-w-0 flex-1"><span className="text-slate-200">{row.contract}</span>
      <span className="block text-[10px] text-slate-500">entered {etTime(row.entry_time, true)} {row.entry_time_reliable ? `${etTime(row.entry_time)} ET` : "(no time of day)"}
        {row.timing && <> · <span className={TIMING_STYLE[row.timing]}>{TIMING_LABEL[row.timing]}</span></>}</span></span>
    <button type="button" disabled={busy} onClick={onLink} className="inline-flex min-h-8 shrink-0 items-center gap-1 rounded border border-sky-500/40 px-2 text-sky-200 hover:bg-sky-500/15 disabled:opacity-40"><Link2 size={11} />Link</button>
  </li>;
}

/**
 * Needs linking (C3.6): saved plans waiting to be tied to the trade they were
 * for. Matches are suggestions; only the user's Link confirms one. A plan
 * linked after its entry stays labeled retrospective. The coverage count
 * measures capture of intent, never trading discipline or results.
 */
export default function LinkReview({ review, loading, error, setup, onLink, onUnlink, onTracking, onClose }: {
  review: CaptureReview | null; loading: boolean; error: string; setup: CaptureSetup | null;
  onLink(captureId: string, tradeId: string): Promise<void>; onUnlink(captureId: string): Promise<void>;
  onTracking(on: boolean, accounts: string[]): Promise<void>; onClose(): void;
}) {
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  const [more, setMore] = useState<string | null>(null);
  const [chosen, setChosen] = useState<string[] | null>(null);
  const run = (work: () => Promise<void>) => { setBusy(true); setProblem(""); work().catch((err: Error) => setProblem(err.message)).finally(() => setBusy(false)); };
  const byId = new Map((review?.captures ?? []).map((capture) => [capture.id, capture]));
  const summary = review?.summary;
  const accounts = setup?.accounts ?? [];
  const picked = chosen ?? (review?.tracking.accounts.length ? review.tracking.accounts : setup?.default_account_id ? [setup.default_account_id] : []);
  const plan = (capture: Capture) => capture.wording ?? capture.note ?? (capture.transcript?.status === "ready" ? capture.transcript.text : capture.mode === "discretionary" ? "Discretionary: no explicit plan" : "");
  return <div className="p-3 text-[11px] text-slate-300" role="region" aria-label="Needs linking">
    <div className="flex items-start gap-2">
      <h2 className="min-w-0 flex-1 text-sm font-semibold text-slate-100">Plans and trades</h2>
      <button aria-label="Close needs linking" onClick={onClose} className="-m-1 inline-flex h-8 w-8 items-center justify-center rounded text-slate-500 hover:bg-slate-800 hover:text-slate-200"><X size={14} /></button>
    </div>
    {loading && <p role="status" className="mt-2 flex items-center gap-1.5 text-slate-400"><Loader2 size={12} className="animate-spin" />Reading plans and trades…</p>}
    {error && <p role="alert" className="mt-2 text-rose-300">{error}</p>}
    {problem && <p role="alert" className="mt-2 text-amber-300">{problem}</p>}
    {review && <>
      <section aria-label="Plan coverage" className="mt-2 rounded border border-slate-700/60 p-2">
        {summary ? <>
          <p className="text-slate-100"><span className="font-semibold">{summary.confirmed} of {summary.eligible}</span> recorded trades since {etTime(summary.since, true)} have a confirmed pre-entry plan{summary.confirmed_discretionary ? ` (${summary.confirmed_discretionary} discretionary)` : ""}.</p>
          <p className="mt-1 text-slate-400">{summary.needs_linking} needs linking · {summary.no_capture} no plan · {summary.retrospective} after entry · {summary.unverified} timing unverified</p>
          {summary.excluded > 0 && <p className="text-slate-500">{summary.excluded} excluded: no time of day recorded for the entry.</p>}
          <p className="mt-1 text-[10px] leading-4 text-slate-500">Counts plans saved before each entry, by the server&apos;s receipt time. It measures capture, not discipline or results, and covers only trades in the journal.</p>
          <button type="button" disabled={busy} onClick={() => run(() => onTracking(false, []))} className="mt-1 min-h-8 rounded border border-slate-700 px-2 text-slate-300 hover:bg-slate-800 disabled:opacity-40">Stop counting</button>
        </> : <>
          <p className="text-slate-300">Count how many of your trades from now on have a plan saved before the entry.</p>
          <div className="mt-1 flex flex-wrap gap-x-3">{accounts.map((account) => <label key={account.id} className="flex min-h-8 items-center gap-1.5">
            <input type="checkbox" checked={picked.includes(account.id)} onChange={(e) => setChosen(e.target.checked ? [...picked, account.id] : picked.filter((id) => id !== account.id))} />{account.label}</label>)}</div>
          <button type="button" disabled={busy || !picked.length} onClick={() => run(() => onTracking(true, picked))} className="mt-1 min-h-8 rounded bg-sky-600 px-2 text-white hover:bg-sky-500 disabled:opacity-40">Start counting from now</button>
        </>}
      </section>
      <section aria-label="Plans to link" className="mt-3 space-y-3">
        {!review.needs_linking.length && !review.unresolved.length && <p className="text-slate-500">Every recent plan is linked or marked not taken.</p>}
        {review.unresolved.map((id) => { const capture = byId.get(id); if (!capture) return null; return <article key={id} aria-label={`${captureTitle(capture)} plan`} className="rounded border border-amber-500/30 p-2">
          <p className="text-slate-100">{captureTitle(capture)} <span className="text-slate-500">· saved {captureTime(capture.received_at)}</span></p>
          <p className="text-amber-300">{capture.link?.unresolved ? capture.link.note : ""}</p>
          <button type="button" disabled={busy} onClick={() => run(() => onUnlink(id))} className="mt-1 min-h-8 rounded border border-slate-700 px-2 hover:bg-slate-800">Unlink</button>
        </article>; })}
        {review.needs_linking.map((item) => { const capture = byId.get(item.capture_id); if (!capture) return null; return <article key={item.capture_id} aria-label={`${captureTitle(capture)} plan`} className="rounded border border-slate-700/60 p-2">
          <p className="text-slate-100">{captureTitle(capture)} <span className="text-slate-500">· {capture.account_label} · saved {captureTime(capture.received_at)}</span></p>
          {plan(capture) && <p className="truncate text-slate-400">{plan(capture)}</p>}
          {item.suggestions.length ? <>
            <p className="mt-1 text-slate-500">{item.suggestions.length > 1 ? "These trades could be it. Choose the one this plan was for:" : "This trade could be it:"}</p>
            <ul className="mt-1 space-y-1">{item.suggestions.map((row) => <Candidate key={row.trade_id} row={row} busy={busy} onLink={() => run(() => onLink(capture.id, row.trade_id))} />)}</ul>
          </> : <p className="mt-1 text-slate-500">No trade entered within ten minutes of this plan yet.</p>}
          {item.others.length > 0 && (more === capture.id
            ? <><p className="mt-2 text-slate-500">Other trades within a week (linking one keeps its timing label):</p>
              <ul className="mt-1 space-y-1">{item.others.map((row) => <Candidate key={row.trade_id} row={row} busy={busy} onLink={() => run(() => onLink(capture.id, row.trade_id))} />)}</ul></>
            : <button type="button" onClick={() => setMore(capture.id)} className="mt-1 min-h-8 text-sky-300 hover:underline">Link another trade…</button>)}
        </article>; })}
      </section>
    </>}
  </div>;
}
