"use client";

import { useCallback, useEffect, useState } from "react";
import { apiUrl } from "@/lib/api";
import PracticePaperPlan from "@/components/PracticePaperPlan";

type Source = { url: string; label: string; formed_at?: string | null; observed_at?: string | null };
type Decision = { id: string; decision: "take" | "wait" | "skip"; rationale: string; policy_version?: string; policy_hash?: string; wait_condition?: string | null; wait_expiry?: string | null; plan?: Record<string, unknown> };
type Context = { captured_at?: string; provider?: string; context_sha256?: string; price_facts?: { name: string; value: number; unit: string; source: string; formed_at: string; observed_at: string }[]; packet?: Record<string, unknown> };
type Opportunity = { id: string; symbol: string; context: Context | null; human: Decision | null; agent: Decision | null; revealed: boolean; comparison_status: string; benchmark: { status?: string; reason?: string; [key: string]: unknown }; paper: { status?: string } | null; agent_paper?: { status?: string } | null; feedback: { rating: string; phone_received: boolean | null } };
type Run = { id: string; day: string; revision?: number; parent_id?: string | null; status: string; result: string | null; error?: string | null; mode: string; comparison: string; late: boolean; created_at: string; finished_at: string | null; deadline: string | null; calendar: { status?: string; [key: string]: unknown }; policy_version: string; policy_hash: string; brief: { title: string; text: string; sources: Source[] }[]; agent: { status: string; error?: string | null; model?: string | null; usage?: Record<string, unknown> | null; cost?: number | null; cost_provenance?: string }; timings: { morning?: { seconds: number; reason?: string }; review?: { seconds: number; reason?: string } }; scheduling_configured?: boolean; counts?: Record<string, number>; opportunities: Opportunity[] };

async function request<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(apiUrl(path), { method: body === undefined ? "GET" : "POST", cache: "no-store", headers: body === undefined ? undefined : { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try { const data = await response.json(); detail = data.detail ?? detail; } catch { /* retain status */ }
    throw new Error(detail);
  }
  return response.json();
}

const localDay = () => new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
const stamp = (value?: string | null) => value ? `${new Date(value).toLocaleString("en-US", { timeZone: "America/New_York" })} ET` : "Unavailable";
const objText = (value: unknown) => JSON.stringify(value, null, 2);

export default function PracticeRoutine({ day }: { day?: string | null }) {
  const selectedDay = day ?? localDay();
  const [runs, setRuns] = useState<Run[]>([]);
  const [active, setActive] = useState<Run | null>(null);
  const [comparison, setComparison] = useState<"independent" | "assisted">("independent");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [timer, setTimer] = useState<{ phase: "morning" | "review"; started: number; runId: string } | null>(null);
  const [reviewFilter, setReviewFilter] = useState("all");
  const [timingReason, setTimingReason] = useState("");
  const activeRunId = active?.id;

  const loadRun = useCallback(async (id: string) => {
    const run = await request<Run>(`/practice/runs/${encodeURIComponent(id)}`);
    setActive(run);
    return run;
  }, []);
  const load = useCallback(async () => {
    setError("");
    try {
      const data = await request<{ runs: Run[] }>(`/practice/runs?day=${encodeURIComponent(selectedDay)}`);
      setRuns(data.runs);
      const linkedRunId = new URLSearchParams(window.location.search).get("practice_run");
      if (!activeRunId && linkedRunId) await loadRun(linkedRunId);
      else if (activeRunId && data.runs.some((run) => run.id === activeRunId)) await loadRun(activeRunId);
      else if (data.runs[0]) await loadRun(data.runs[0].id);
      else setActive(null);
    } catch (err) { setError(err instanceof Error ? err.message : "Could not load practice runs."); }
  }, [selectedDay, activeRunId, loadRun]);
  // The run selection is restored by a network response; state updates happen after that response resolves.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { void load(); }, [load]);
  const activeStatus = active?.status;
  useEffect(() => {
    if (!activeRunId || !["queued", "preparing"].includes(activeStatus ?? "")) return;
    const id = window.setInterval(() => { void loadRun(activeRunId).catch((err) => setError(err.message)); }, 2000);
    return () => window.clearInterval(id);
  }, [activeRunId, activeStatus, loadRun]);

  async function prepare() {
    setBusy(true); setError("");
    try { const run = await request<Run>("/practice/prepare", { mode: "manual", comparison }); setActive(run); setRuns((prior) => [run, ...prior.filter((item) => item.id !== run.id)]); }
    catch (err) { setError(err instanceof Error ? err.message : "Preparation failed."); }
    finally { setBusy(false); }
  }
  async function retryRevision() {
    if (!active) return;
    setBusy(true); setError("");
    try {
      const run = await request<Run>("/practice/prepare", { mode: "manual", comparison: "assisted", revision: (active.revision ?? 0) + 1 });
      setActive(run); setRuns((prior) => [run, ...prior.filter((item) => item.id !== run.id)]);
    } catch (err) { setError(err instanceof Error ? err.message : "Revision could not be prepared."); }
    finally { setBusy(false); }
  }
  async function update(next: Run) { setActive(next); setRuns((prior) => prior.map((run) => run.id === next.id ? next : run)); }
  async function submitChoice(opp: Opportunity, form: FormData) {
    if (!active) return;
    setBusy(true); setError("");
    const decision = String(form.get("decision")) as Decision["decision"];
    let plan: Record<string, unknown> | undefined;
    if (decision === "take") {
      try { plan = JSON.parse(String(form.get("plan") || "")); if (!plan || typeof plan !== "object" || Array.isArray(plan)) throw new Error(); }
      catch { setError("TAKE requires a valid plan JSON object with A1 validated terms."); setBusy(false); return; }
    }
    try {
      if (decision === "wait" && (!form.get("wait_condition") || !form.get("wait_expiry"))) throw new Error("WAIT requires a condition and expiry.");
      const waitExpiry = decision === "wait" ? new Date(String(form.get("wait_expiry"))).toISOString() : undefined;
      const next = await request<Run>(`/practice/opportunities/${encodeURIComponent(opp.id)}/choice`, { decision, rationale: String(form.get("rationale") ?? ""), ...(decision === "wait" ? { wait_condition: String(form.get("wait_condition") ?? ""), wait_expiry: waitExpiry } : {}), ...(plan ? { plan } : {}) });
      await update(next);
    } catch (err) { setError(err instanceof Error ? err.message : "Choice could not be saved."); }
    finally { setBusy(false); }
  }
  async function action(path: string, body: unknown) { if (!active) return false; setBusy(true); setError(""); try { await update(await request<Run>(path, body)); return true; } catch (err) { setError(err instanceof Error ? err.message : "Action failed."); return false; } finally { setBusy(false); } }
  async function reveal(opp: Opportunity) { await action(`/practice/opportunities/${encodeURIComponent(opp.id)}/reveal`, {}); }
  async function timing() {
    if (!active || !timer) return;
    if (active.id !== timer.runId) return setError("Select the run where this timer began before saving its time.");
    const seconds = Math.max(0, Math.round(performance.now() - timer.started) / 1000);
    const saved = await action(`/practice/runs/${encodeURIComponent(active.id)}/timing`, { phase: timer.phase, seconds, ...(timingReason.trim() ? { reason: timingReason.trim() } : {}) });
    if (saved) { setTimer(null); setTimingReason(""); }
  }

  return <section className="min-w-0 space-y-4 rounded-lg border bg-card p-4 [overflow-wrap:anywhere]" data-testid="practice-routine">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><h2 className="text-sm font-semibold uppercase tracking-wide">Daily practice routine</h2><p className="mt-1 text-sm text-muted-foreground">{selectedDay} · {active?.mode ?? "manual"} preparation · choices and paper practice stay separate from journal fills.</p></div>
      <button type="button" onClick={load} className="rounded border px-3 py-2 text-sm">Reload run</button>
    </div>
    <div className="flex flex-wrap items-center gap-2">
      <label className="grid min-w-0 max-w-full gap-1 text-sm">Comparison <select aria-label="Comparison mode" value={comparison} onChange={(e) => setComparison(e.target.value as typeof comparison)} className="block w-full min-w-0 max-w-full rounded border bg-background p-2 sm:inline-block sm:w-auto"><option value="independent">Independent (verdict hidden until both commit)</option><option value="assisted">Assisted</option></select></label>
      <button type="button" disabled={busy} onClick={prepare} className="rounded bg-primary px-3 py-2 text-sm text-primary-foreground disabled:opacity-50">{busy ? "Working…" : "Prepare today"}</button>
      {active && <><button type="button" disabled={!!timer} onClick={() => setTimer({ phase: "morning", started: performance.now(), runId: active.id })} className="rounded border px-3 py-2 text-sm">Start morning timing</button><button type="button" disabled={!!timer} onClick={() => setTimer({ phase: "review", started: performance.now(), runId: active.id })} className="rounded border px-3 py-2 text-sm">Start review timing</button>{timer && <><label className="min-w-0 text-sm">Reason if over five minutes<input value={timingReason} onChange={(event) => setTimingReason(event.target.value)} className="mt-1 w-full rounded border bg-background p-2" /></label><button type="button" onClick={timing} className="rounded border px-3 py-2 text-sm">Save {timer.phase} time</button></>}</>}
    </div>
      <p className="text-xs text-muted-foreground">08:50 scheduling is {active?.scheduling_configured ? "configured; timer execution remains unobserved" : "disabled"}. Arming a paper plan remains explicit.</p>
    {error && <p role="alert" className="break-words text-sm text-red-600">{error}</p>}
    {runs.length > 1 && <label className="text-sm">Saved run <select aria-label="Saved run" value={active?.id ?? ""} onChange={(e) => void loadRun(e.target.value)} className="block w-full min-w-0 max-w-full rounded border bg-background p-2">{runs.map((run) => <option key={run.id} value={run.id}>{run.id} · {run.status} · {stamp(run.created_at)}</option>)}</select></label>}
    {!active && !error && <p className="text-sm text-muted-foreground">No run prepared for this session.</p>}
    {active && <div className="space-y-4" data-testid="practice-run">
      <div className="rounded border p-3 text-sm"><p><strong>{active.status.toUpperCase()}</strong> · {active.result ?? "result pending"}{active.late ? " · LATE" : ""}</p><p>Created {stamp(active.created_at)} · finished {stamp(active.finished_at)} · deadline {stamp(active.deadline)}</p><p>Calendar {active.calendar?.status ?? "unavailable"} · policy {active.policy_version} · hash {active.policy_hash}</p><p>Revision {active.revision ?? 0}{active.parent_id ? ` · revises ${active.parent_id}` : " · original run"}</p><p>Agent {active.agent?.status ?? "disabled"}{active.agent?.error ? ` · ${active.agent.error}` : ""} · model {active.agent?.model ?? "unavailable"} · cost {active.agent?.cost == null ? "unavailable" : active.agent.cost} ({active.agent?.cost_provenance ?? "cost provenance unavailable"})</p><details><summary>Agent usage</summary><pre className="overflow-auto">{active.agent?.usage ? objText(active.agent.usage) : "unavailable"}</pre></details>{active.error && <p role="status" className="break-words text-amber-700">Preparation issue: {active.error}</p>}<details><summary>Agent runtime and cost provenance</summary><pre className="overflow-auto whitespace-pre-wrap text-xs">{objText(active.agent)}</pre></details><p>Choices: TAKE {active.counts?.take ?? 0} · WAIT {active.counts?.wait ?? 0} · SKIP {active.counts?.skip ?? 0} · nonresponse {active.opportunities?.filter((o) => !o.human).length ?? 0}</p><p>Timing: morning {active.timings?.morning ? `${active.timings.morning.seconds}s${active.timings.morning.reason ? ` (${active.timings.morning.reason})` : ""}` : "unrecorded"}; review {active.timings?.review ? `${active.timings.review.seconds}s${active.timings.review.reason ? ` (${active.timings.review.reason})` : ""}` : "unrecorded"}</p>{((active.timings?.morning?.seconds ?? 0) + (active.timings?.review?.seconds ?? 0)) > 300 && <p className="text-amber-700">Morning and review together exceeded five minutes. Keep the recorded time and add a reason if helpful.</p>}</div>
      {["queued", "preparing"].includes(active.status) === false && (active.revision ?? 0) < 10 && <button type="button" disabled={busy} onClick={() => void retryRevision()} className="rounded border px-3 py-2 text-sm disabled:opacity-50">Prepare assisted revision</button>}
      {!["queued", "preparing"].includes(active.status) && <button type="button" disabled={busy} onClick={() => void action(`/practice/runs/${encodeURIComponent(active.id)}/benchmark`, {})} className="rounded border px-3 py-2 text-sm disabled:opacity-50">Refresh underlying benchmark</button>}
      <div className="grid gap-2 md:grid-cols-3">{["MARKET TAPE", "IMPORTANT NEWS", "SETUP BOARD"].map((title) => { const item = active.brief?.find((part) => part.title.toUpperCase() === title); return <article key={title} className="min-w-0 rounded border p-3"><h3 className="font-semibold">{title}</h3><p className="mt-2 whitespace-pre-wrap break-words text-sm">{item?.text ?? "Unavailable in this run."}</p>{item?.sources?.map((source) => { const symbol = source.label.split(" ")[0]; const opportunity = active.opportunities?.find((candidate) => candidate.symbol === symbol); const localPath = `${day ? `/daily/${day}` : "/"}#practice-opportunity-${opportunity?.id ?? ""}`; return <p key={source.url} className="mt-2 break-words text-xs"><a href={opportunity ? localPath : source.url.startsWith("/") ? apiUrl(source.url) : source.url} className="underline">{source.label}</a> · formed {stamp(source.formed_at)} · observed {stamp(source.observed_at)}</p>; })}</article>; })}</div>
      {active.opportunities?.length === 0 && <p className="rounded border p-3 text-sm">No setups for this run. No choice is implied.</p>}
      <label className="block text-sm">Review records <select aria-label="Review records" value={reviewFilter} onChange={(e) => setReviewFilter(e.target.value)} className="block w-full min-w-0 max-w-full rounded border bg-background p-2 sm:inline-block sm:w-auto"><option value="all">All opportunities</option><option value="take">TAKE</option><option value="wait">WAIT</option><option value="skip">SKIP</option><option value="nonresponse">Nonresponse</option><option value="coverage">Missing benchmark coverage</option><option value="useful">Alerts rated useful</option><option value="not_useful">Alerts rated not useful</option><option value="unrated">Unrated alerts</option><option value="unarmed">Unarmed TAKE</option><option value="armed">Unfilled / armed</option><option value="triggered">Triggered, entry pending</option><option value="expired">Expired</option><option value="missed">Missed trigger</option><option value="rejected">Rejected entry</option><option value="open">Open paper</option><option value="closed">Closed paper</option><option value="unresolved">Unresolved paper</option></select></label>
      <div className="space-y-3">{active.opportunities?.filter((opp) => reviewFilter === "all" || (reviewFilter === "nonresponse" ? !opp.human : reviewFilter === "coverage" ? opp.benchmark?.status !== "complete" : ["useful", "not_useful", "unrated"].includes(reviewFilter) ? opp.feedback?.rating === reviewFilter : ["unarmed", "armed", "triggered", "expired", "missed", "rejected", "open", "closed", "unresolved"].includes(reviewFilter) ? opp.paper?.status === reviewFilter || opp.agent_paper?.status === reviewFilter : opp.human?.decision === reviewFilter)).map((opp) => <article key={opp.id} id={`practice-opportunity-${opp.id}`} className="min-w-0 space-y-3 rounded border p-3" data-testid="practice-opportunity">
        <div className="flex flex-wrap justify-between gap-2"><h3 className="font-semibold">{opp.symbol} <span className="text-xs font-normal text-muted-foreground">Opportunity {opp.id}</span></h3><span className="text-xs">{opp.comparison_status}</span></div>
        <details><summary className="cursor-pointer text-sm">Frozen neutral context</summary>{opp.context ? <div className="mt-2 space-y-2 text-xs"><p>Captured {stamp(opp.context.captured_at)} · {opp.context.provider} · context {opp.context.context_sha256}</p>{opp.context.price_facts?.map((fact, i) => <p key={`${fact.name}-${i}`} className="break-words">{fact.name}: {fact.value} {fact.unit} · source {fact.source} · formed {stamp(fact.formed_at)} · observed {stamp(fact.observed_at)}</p>)}<pre className="overflow-auto rounded bg-muted p-2">{objText(opp.context.packet)}</pre></div> : <p className="mt-2 text-sm">Frozen context unavailable; TAKE cannot be assumed valid.</p>}</details>
        {opp.human ? <div className="rounded bg-muted p-2 text-sm"><strong>Human: {opp.human.decision.toUpperCase()}</strong> · {opp.human.rationale}<p>Frozen decision {opp.human.id} · policy {opp.human.policy_version ?? "unavailable"} · hash {opp.human.policy_hash ?? "unavailable"}</p>{opp.human.wait_condition && <p>Wait for {opp.human.wait_condition} until {stamp(opp.human.wait_expiry)}</p>}{opp.human.decision === "take" && <details><summary>Frozen TAKE plan</summary><pre className="overflow-auto">{objText(opp.human.plan)}</pre></details>}</div> : <form action={(form) => void submitChoice(opp, form)} className="grid gap-2 sm:grid-cols-2">
          <label className="text-sm">Decision<select name="decision" aria-label={`Decision ${opp.symbol}`} className="mt-1 w-full rounded border bg-background p-2"><option value="skip">SKIP</option><option value="wait">WAIT</option><option value="take">TAKE</option></select></label>
          <label className="text-sm">Rationale<input name="rationale" required className="mt-1 w-full rounded border bg-background p-2" /></label>
          <label className="text-sm sm:col-span-2">WAIT condition<input name="wait_condition" className="mt-1 w-full rounded border bg-background p-2" /></label><label className="text-sm">WAIT expiry<input name="wait_expiry" type="datetime-local" className="mt-1 w-full rounded border bg-background p-2" /></label>
          <label className="text-sm sm:col-span-2">TAKE plan JSON (must satisfy A1 validation)<textarea name="plan" rows={4} placeholder='{"trigger_level":...,"stop":...,"target":...}' className="mt-1 w-full min-w-0 rounded border bg-background p-2 font-mono text-xs" /></label>
          <button disabled={busy} className="w-fit rounded border px-3 py-2 text-sm disabled:opacity-50">Save frozen choice</button>
        </form>}
        {(opp.revealed || active.comparison === "assisted") && <div className="rounded border border-sky-500/30 p-2 text-sm"><strong>Agent choice: {opp.agent?.decision?.toUpperCase() ?? "Unavailable"}</strong>{opp.agent && <><p>{opp.agent.rationale}</p><p>Frozen decision {opp.agent.id} · policy {opp.agent.policy_version ?? "unavailable"} · hash {opp.agent.policy_hash ?? "unavailable"}</p></>}</div>}
        {!opp.revealed && active.comparison === "independent" && <button type="button" disabled={busy || !opp.human} onClick={() => void reveal(opp)} className="rounded border px-3 py-2 text-sm disabled:opacity-50">Reveal agent choice after both commit</button>}
        <details className="rounded bg-muted p-2 text-xs"><summary className="cursor-pointer">Outcome, coverage gaps, and paper status</summary><div className="mt-2 space-y-1 break-words"><p>Benchmark {opp.benchmark?.status ?? "unavailable"}{opp.benchmark?.reason ? ` · ${opp.benchmark.reason}` : ""}</p><pre className="overflow-auto">{objText(opp.benchmark)}</pre><p>Human paper {opp.paper?.status ?? (opp.human?.decision === "take" ? "unarmed" : "none")}</p>{opp.paper && <details><summary>Human paper timeline and base/3× cost outcomes</summary><pre className="overflow-auto">{objText(opp.paper)}</pre></details>}<p>Agent paper {opp.agent_paper?.status ?? (opp.agent?.decision === "take" ? "unavailable" : "none")}</p>{opp.agent_paper && <details><summary>Agent paper timeline and base/3× cost outcomes</summary><pre className="overflow-auto">{objText(opp.agent_paper)}</pre></details>}{opp.context?.price_facts?.length === 0 && <p className="text-amber-700">Coverage gap: no frozen price facts; WAIT/SKIP remain available, TAKE validation may refuse.</p>}{!opp.context && <p className="text-amber-700">Coverage gap: no frozen context.</p>}</div></details>
        {opp.human?.decision === "take" && <PracticePaperPlan recordId={opp.human.id} />}
        <div className="flex flex-wrap items-center gap-2 text-sm"><label>Alert feedback <select aria-label={`Alert feedback ${opp.symbol}`} value={opp.feedback?.rating ?? "unrated"} onChange={(e) => void action(`/practice/opportunities/${encodeURIComponent(opp.id)}/feedback`, { rating: e.target.value, phone_received: opp.feedback?.phone_received ?? null })} className="rounded border bg-background p-2"><option value="unrated">Unrated</option><option value="useful">Useful</option><option value="not_useful">Not useful</option></select></label><label>Phone receipt <select aria-label={`Phone receipt ${opp.symbol}`} value={opp.feedback?.phone_received == null ? "unreported" : opp.feedback.phone_received ? "yes" : "no"} onChange={(e) => void action(`/practice/opportunities/${encodeURIComponent(opp.id)}/feedback`, { rating: opp.feedback?.rating ?? "unrated", phone_received: e.target.value === "unreported" ? null : e.target.value === "yes" })} className="rounded border bg-background p-2"><option value="unreported">Unreported</option><option value="yes">Yes</option><option value="no">No</option></select></label></div>
      </article>)}</div>
      {active.opportunities?.some((opp) => !opp.human) && <p className="text-sm text-amber-700">Nonresponse remains unobserved; it is never counted as SKIP.</p>}
    </div>}
  </section>;
}
