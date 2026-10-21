"use client";

import { useAppAccess } from "@/components/AccessProvider";
import { useCallback, useEffect, useRef, useState } from "react";
import { apiUrl } from "@/lib/api";
import PracticePaperPlan from "@/components/PracticePaperPlan";
import SampleDecisionRoutine from "@/components/SampleDecisionRoutine";
import AdvisorShadowPanel from "@/components/AdvisorShadowPanel";

type Source = { url: string; label: string; formed_at?: string | null; observed_at?: string | null };
type Decision = { id: string; decision: "take" | "wait" | "skip"; rationale: string; policy_version?: string; policy_hash?: string; wait_condition?: string | null; wait_expiry?: string | null; plan?: Record<string, unknown> };
type Context = { captured_at?: string; provider?: string; context_sha256?: string; price_facts?: { name: string; value: number; unit: string; source: string; formed_at: string; observed_at: string }[]; packet?: Record<string, unknown> };
type Opportunity = { id: string; symbol: string; context: Context | null; human: Decision | null; agent: Decision | null; revealed: boolean; comparison_status: string; benchmark: { status?: string; reason?: string; [key: string]: unknown }; paper: { status?: string } | null; agent_paper?: { status?: string } | null; feedback: { rating: string; phone_received: boolean | null } };
type Run = { market_data?: boolean; manual_shadow?: boolean; independence?: string; id: string; day: string; revision?: number; parent_id?: string | null; status: string; result: string | null; error?: string | null; mode: string; comparison: string; late: boolean; created_at: string; finished_at: string | null; deadline: string | null; calendar: { status?: string; [key: string]: unknown }; policy_version: string; policy_hash: string; brief: { title: string; text: string; sources: Source[] }[]; agent: { status: string; error?: string | null; model?: string | null; usage?: Record<string, unknown> | null; cost?: number | null; cost_provenance?: string }; timings: { morning?: { seconds: number; reason?: string }; review?: { seconds: number; reason?: string } }; scheduling_configured?: boolean; counts?: Record<string, number>; opportunities: Opportunity[] };

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
const clock = (value?: string | null) => value ? `${new Date(value).toLocaleTimeString("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit" })} ET` : "unavailable";
const dayLabel = (day: string) => new Date(`${day}T12:00:00Z`).toLocaleDateString("en-US", { timeZone: "UTC", weekday: "short", month: "short", day: "numeric" });

export default function PracticeRoutine({ day }: { day?: string | null }) {
  const { grants } = useAppAccess();
  return (grants.decision_write || grants.market_decision_write) ? <SampleDecisionRoutine day={day} /> : <ReadPracticeRoutine day={day} />;
}

function ReadPracticeRoutine({ day }: { day?: string | null }) {
  const { owner } = useAppAccess();
  const selectedDay = day ?? localDay();
  const [runs, setRuns] = useState<Run[]>([]);
  const [active, setActive] = useState<Run | null>(null);
  const [comparison, setComparison] = useState<"independent" | "assisted">("independent");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [errorAt, setErrorAt] = useState<string | null>(null);
  // Errors from one setup's controls show inside that setup, next to the control.
  const fail = useCallback((message: string, oppId: string | null = null) => { setError(message); setErrorAt(oppId); }, []);
  const [timer, setTimer] = useState<{ phase: "morning" | "review"; started: number; runId: string } | null>(null);
  const [reviewFilter, setReviewFilter] = useState("all");
  const [timingReason, setTimingReason] = useState("");
  const activeRunId = active?.id;
  const selectedRun = useRef<string | null>(null);
  const linkedEntry = useRef<{ id: string; session: string } | null | undefined>(undefined);
  const requestedSession = useRef<string | null>(null);
  const currentRun = useRef<Run | null>(null);
  const currentRunSession = useRef<string | null>(null);
  const readVersion = useRef(0);
  const [loadingRun, setLoadingRun] = useState<string | null>(null);
  const [runSession, setRunSession] = useState<string | null>(null);
  // A historical deep-link is intentional; the request's session, not the
  // returned run's day, determines whether a later session made it stale.
  const showRun = useCallback((run: Run | null) => { currentRun.current = run; currentRunSession.current = selectedDay; setActive(run); setRunSession(selectedDay); }, [selectedDay]);
  const restoreSelection = useCallback(() => {
    selectedRun.current = currentRunSession.current === selectedDay ? currentRun.current?.id ?? null : null;
    setLoadingRun(null);
  }, [selectedDay]);

  const loadRun = useCallback(async (id: string, explicit = true) => {
    if (explicit) linkedEntry.current = null;
    selectedRun.current = id; // Selection intent precedes its network response.
    const version = ++readVersion.current;
    setLoadingRun(id);
    try {
      const run = await request<Run>(`/practice/runs/${encodeURIComponent(id)}`);
      if (version !== readVersion.current) return;
      if (linkedEntry.current?.id === id && linkedEntry.current.session === selectedDay) linkedEntry.current = null;
      showRun(run);
      setLoadingRun(null);
    } catch (err) {
      if (version !== readVersion.current) return;
      restoreSelection();
      fail(err instanceof Error ? err.message : "Could not load practice run.");
    }
  }, [selectedDay, showRun, restoreSelection, fail]);
  const load = useCallback(async () => {
    const version = ++readVersion.current;
    const intended = selectedRun.current;
    if (linkedEntry.current === undefined) {
      const id = new URLSearchParams(window.location.search).get("practice_run");
      linkedEntry.current = id ? { id, session: selectedDay } : null;
    }
    const linkedRunId = linkedEntry.current?.id;
    fail("");
    try {
      const data = await request<{ runs: Run[] }>(`/practice/runs?day=${encodeURIComponent(selectedDay)}`);
      if (version !== readVersion.current) return;
      setRuns(data.runs);
      if (linkedRunId && (!intended || intended === linkedRunId)) await loadRun(linkedRunId, false);
      else if (intended) await loadRun(intended, false);
      else if (data.runs[0]) await loadRun(data.runs[0].id, false);
      else { selectedRun.current = null; showRun(null); setLoadingRun(null); }
    } catch (err) { if (version === readVersion.current) { restoreSelection(); fail(err instanceof Error ? err.message : "Could not load practice runs."); } }
  }, [selectedDay, loadRun, showRun, restoreSelection, fail]);
  // Reload on session changes, not on each returned run. Stale reads cannot select a run.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => {
    if (requestedSession.current !== selectedDay) {
      requestedSession.current = selectedDay;
      selectedRun.current = null;
      if (linkedEntry.current && linkedEntry.current.session !== selectedDay) linkedEntry.current = null;
    }
    void load();
    return () => { readVersion.current++; };
  }, [load, selectedDay]);
  const activeStatus = active?.status;
  useEffect(() => {
    if (!activeRunId || loadingRun || !["queued", "preparing"].includes(activeStatus ?? "")) return;
    const id = window.setInterval(() => { if (selectedRun.current === activeRunId) void loadRun(activeRunId, false); }, 2000);
    return () => window.clearInterval(id);
  }, [activeRunId, activeStatus, loadingRun, loadRun]);

  async function prepare() {
    setBusy(true); fail("");
    const version = ++readVersion.current;
    try { const run = await request<Run>("/practice/prepare", { mode: "manual", comparison });
      if (version === readVersion.current) { linkedEntry.current = null; selectedRun.current = run.id; showRun(run); setLoadingRun(null); }
      setRuns((prior) => [run, ...prior.filter((item) => item.id !== run.id)]);
    }
    catch (err) { if (version === readVersion.current) { restoreSelection(); fail(err instanceof Error ? err.message : "Preparation failed."); } }
    finally { setBusy(false); }
  }
  async function retryRevision() {
    if (!active || loadingRun || selectedRun.current !== active.id || runSession !== selectedDay) return;
    if (active.day !== localDay()) return fail("Historical sessions cannot be prepared again with current market facts.");
    setBusy(true); fail("");
    const version = ++readVersion.current;
    try {
      const run = await request<Run>("/practice/prepare", { mode: "manual", comparison: "assisted", revision: (active.revision ?? 0) + 1, parent_id: active.parent_id ?? active.id });
      if (version === readVersion.current) { linkedEntry.current = null; selectedRun.current = run.id; showRun(run); setLoadingRun(null); }
      setRuns((prior) => [run, ...prior.filter((item) => item.id !== run.id)]);
    } catch (err) { if (version === readVersion.current) { restoreSelection(); fail(err instanceof Error ? err.message : "Revision could not be prepared."); } }
    finally { setBusy(false); }
  }
  async function update(next: Run) {
    if (selectedRun.current === next.id) { readVersion.current++; showRun(next); setLoadingRun(null); }
    setRuns((prior) => prior.map((run) => run.id === next.id ? next : run));
  }
  async function submitChoice(opp: Opportunity, body: ChoiceBody) {
    if (!active || loadingRun || selectedRun.current !== active.id || runSession !== selectedDay) return;
    setBusy(true); fail("");
    try { await update(await request<Run>(`/practice/opportunities/${encodeURIComponent(opp.id)}/choice`, body)); }
    catch (err) { fail(err instanceof Error ? err.message : "Choice could not be saved.", opp.id); }
    finally { setBusy(false); }
  }
  async function action(path: string, body: unknown, oppId: string | null = null) { if (!active || loadingRun || selectedRun.current !== active.id || runSession !== selectedDay) return false; setBusy(true); fail(""); try { await update(await request<Run>(path, body)); return true; } catch (err) { fail(err instanceof Error ? err.message : "Action failed.", oppId); return false; } finally { setBusy(false); } }
  async function reveal(opp: Opportunity) { await action(`/practice/opportunities/${encodeURIComponent(opp.id)}/reveal`, {}, opp.id); }
  async function timing() {
    if (!active || !timer) return;
    if (selectedRun.current !== timer.runId) return fail("Select the run where this timer began before saving its time.");
    if (active.id !== timer.runId || loadingRun) return fail("Wait for the selected run to load before saving its time.");
    const seconds = Math.max(0, Math.round(performance.now() - timer.started) / 1000);
    const saved = await action(`/practice/runs/${encodeURIComponent(active.id)}/timing`, { phase: timer.phase, seconds, ...(timingReason.trim() ? { reason: timingReason.trim() } : {}) });
    if (saved) { setTimer(null); setTimingReason(""); }
  }
  const selectableRuns = active && !runs.some((run) => run.id === active.id) ? [active, ...runs] : runs;
  const visibleAgentCounts = active ? Object.fromEntries(["take", "wait", "skip"].map((decision) => [
    decision,
    active.opportunities.filter((opp) => (active.comparison === "assisted" || opp.revealed) && opp.agent?.decision === decision).length,
  ])) : { take: 0, wait: 0, skip: 0 };

  const [now, setNow] = useState(() => Date.now());
  useEffect(() => { const id = window.setInterval(() => setNow(Date.now()), 30_000); return () => window.clearInterval(id); }, []);

  if (active?.market_data) return <SampleDecisionRoutine day={day} marketOnly />;
  const opportunities = active?.opportunities ?? [];
  const answered = opportunities.filter((opp) => opp.human).length;
  const preparing = ["queued", "preparing"].includes(active?.status ?? "");
  const isToday = active?.day === localDay();
  const deadlineMs = active?.deadline ? Date.parse(active.deadline) : NaN;
  const minutesLeft = Number.isFinite(deadlineMs) ? Math.ceil((deadlineMs - now) / 60_000) : null;
  const headline = !active ? "" : preparing ? "Preparing today's setups…"
    : opportunities.length === 0 ? "No setups for this run. No choice is implied."
    : answered === opportunities.length ? `All ${opportunities.length} setup${opportunities.length === 1 ? "" : "s"} answered`
    : `${isToday ? "Today" : dayLabel(active.day)}: choose Take, Wait or Skip on ${opportunities.length} setup${opportunities.length === 1 ? "" : "s"}${active.deadline ? ` by ${clock(active.deadline)}` : ""}`;
  const progress = !active || opportunities.length === 0 ? "" : [
    `${answered} of ${opportunities.length} answered`,
    isToday && minutesLeft !== null && answered < opportunities.length ? (minutesLeft > 0 ? `${minutesLeft} min left` : `past the ${clock(active.deadline)} cutoff`) : "",
    active.comparison === "assisted" ? "Assisted: agent picks show as they arrive, so this run doesn't test independence" : "Independent: the agent's picks stay hidden until you both commit and you reveal them",
  ].filter(Boolean).join(" · ");
  const timingText = active ? `Timing: morning ${active.timings?.morning ? `${active.timings.morning.seconds}s${active.timings.morning.reason ? ` (${active.timings.morning.reason})` : ""}` : "unrecorded"}; review ${active.timings?.review ? `${active.timings.review.seconds}s${active.timings.review.reason ? ` (${active.timings.review.reason})` : ""}` : "unrecorded"}` : "";
  // Mirrors the server's existing TAKE refusals so the reason shows before saving.
  const takeUnavailable = !active ? null : active.calendar?.status !== "open" ? `Take needs a verified open market session; this run's calendar is ${active.calendar?.status ?? "unavailable"}.` : !isToday ? "Take can only be saved on the run's own session day." : null;
  const canAct = !!active && !loadingRun && runSession === selectedDay;
  const shown = opportunities.filter((opp) => reviewFilter === "all" || (reviewFilter === "nonresponse" ? !opp.human : reviewFilter === "coverage" ? opp.benchmark?.status !== "complete" : ["useful", "not_useful", "unrated"].includes(reviewFilter) ? opp.feedback?.rating === reviewFilter : ["unarmed", "armed", "triggered", "expired", "missed", "rejected", "open", "closed", "unresolved"].includes(reviewFilter) ? opp.paper?.status === reviewFilter || opp.agent_paper?.status === reviewFilter : opp.human?.decision === reviewFilter || ((active?.comparison === "assisted" || opp.revealed) && opp.agent?.decision === reviewFilter)));
  return <fieldset disabled={!owner} className="min-w-0"><section className="min-w-0 space-y-4 rounded-lg border bg-card p-4 [overflow-wrap:anywhere]" data-testid="practice-routine">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h2 className="text-sm font-semibold uppercase tracking-wide">Daily practice <span className="font-normal normal-case tracking-normal text-muted-foreground">· {dayLabel(selectedDay)}</span></h2>
      <div className="flex flex-wrap items-center gap-2">
        <label className="min-w-0 max-w-full text-sm"><span className="sr-only">Comparison</span><select aria-label="Comparison mode" value={comparison} onChange={(e) => setComparison(e.target.value as typeof comparison)} className="block w-full min-w-0 max-w-full rounded border bg-background p-2 sm:w-auto"><option value="independent">Independent (agent hidden until both commit)</option><option value="assisted">Assisted</option></select></label>
        <button type="button" disabled={busy} onClick={prepare} className={`rounded px-3 py-2 text-sm disabled:opacity-50 ${active ? "border" : "bg-primary text-primary-foreground"}`}>{busy ? "Working…" : "Prepare today"}</button>
        <button type="button" onClick={load} className="rounded border px-3 py-2 text-sm">Reload run</button>
      </div>
    </div>
    {selectableRuns.length > 1 && <label className="block text-sm">Saved run <select aria-label="Saved run" value={loadingRun ?? active?.id ?? ""} onChange={(e) => void loadRun(e.target.value)} className="block w-full min-w-0 max-w-full rounded border bg-background p-2">{selectableRuns.map((run) => <option key={run.id} value={run.id}>{stamp(run.created_at)} · {run.status}{run.revision ? ` · revision ${run.revision}` : ""} · {run.id}</option>)}</select></label>}
    {active && <div className="flex flex-wrap items-center gap-2" aria-label="Attention timing"><button type="button" disabled={!!timer || !canAct} onClick={() => setTimer({ phase: "morning", started: performance.now(), runId: active.id })} className="rounded border px-3 py-1.5 text-xs">Start morning timing</button><button type="button" disabled={!!timer || !canAct} onClick={() => setTimer({ phase: "review", started: performance.now(), runId: active.id })} className="rounded border px-3 py-1.5 text-xs">Start review timing</button>{timer && <><label className="min-w-0 text-xs">Reason if over five minutes<input value={timingReason} onChange={(event) => setTimingReason(event.target.value)} className="mt-1 w-full rounded border bg-background p-1.5" /></label><button type="button" onClick={timing} className="rounded border px-3 py-1.5 text-xs">Save {timer.phase} time</button></>}</div>}
    {error && !errorAt && <p role="alert" className="break-words text-sm text-red-600">{error}</p>}
    {loadingRun && <p role="status" className="text-sm text-muted-foreground">Loading selected run…</p>}
    {!active && !error && <p className="text-sm text-muted-foreground">{owner ? "No run prepared for this session. Prepare today builds the morning's setups to answer before the 9:00 ET cutoff." : "No practice runs are shared with this assistant for this day."}</p>}
    {active && (!loadingRun || loadingRun === active.id) && runSession === selectedDay && <div className="space-y-4" data-testid="practice-run">
      <div className="space-y-2 rounded border border-primary/40 p-3 text-sm">
        <p className="text-base font-semibold">{headline}</p>
        {progress && <p className="text-muted-foreground">{progress}</p>}
        {opportunities.length > 0 && <div className="h-1.5 rounded bg-muted" aria-hidden="true"><div className="h-1.5 rounded bg-primary" style={{ width: `${Math.round((answered / opportunities.length) * 100)}%` }} /></div>}
        <p className="text-xs text-muted-foreground">Run {active.status.toUpperCase()} · {active.result ?? "result pending"}{active.late ? " · LATE" : ""} · {timingText}</p>
        {((active.timings?.morning?.seconds ?? 0) + (active.timings?.review?.seconds ?? 0)) > 300 && <p className="text-amber-700">Morning and review together exceeded five minutes. Keep the recorded time and add a reason if helpful.</p>}
      </div>
      {(active.status === "failed" || active.error) && <p role="status" className="break-words rounded border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-700">Preparation {active.status === "failed" ? "failed" : "issue"}{active.error ? `: ${active.error}` : ""}. Choices you save are still recorded on this run.</p>}
      {active.late && <p className="rounded border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-700">Prepared after the {active.deadline ? clock(active.deadline) : "9:00 ET"} cutoff, so this run is marked late.</p>}
      <details className="rounded border p-3 text-sm"><summary className="cursor-pointer font-medium">Morning brief: market tape, news and setup board</summary><div className="mt-2 grid gap-2 md:grid-cols-3">{["MARKET TAPE", "IMPORTANT NEWS", "SETUP BOARD"].map((title) => { const item = active.brief?.find((part) => part.title.toUpperCase() === title); return <article key={title} className="min-w-0 rounded border p-3"><h3 className="font-semibold">{title.charAt(0) + title.slice(1).toLowerCase()}</h3><p className="mt-2 whitespace-pre-wrap break-words text-sm">{item?.text ?? "Unavailable in this run."}</p>{item?.sources?.map((source) => { const symbol = source.label.split(" ")[0]; const opportunity = active.opportunities?.find((candidate) => candidate.symbol === symbol); const localPath = `${day ? `/daily/${day}` : owner ? "/practice" : "/"}#practice-opportunity-${opportunity?.id ?? ""}`; return <p key={source.url} className="mt-2 break-words text-xs"><a href={opportunity ? localPath : source.url.startsWith("/") ? apiUrl(source.url) : source.url} className="underline">{source.label}</a> · formed {stamp(source.formed_at)} · observed {stamp(source.observed_at)}</p>; })}</article>; })}</div></details>
      {owner && active.manual_shadow && <AdvisorShadowPanel key={active.id} runId={active.id} onRefresh={async () => { if (selectedRun.current === active.id) await loadRun(active.id, false); }} />}
      {opportunities.length > 0 && <label className="flex flex-wrap items-center gap-2 text-sm">Show <select aria-label="Review records" value={reviewFilter} onChange={(e) => setReviewFilter(e.target.value)} className="min-w-0 max-w-full rounded border bg-background p-2"><option value="all">All setups</option><option value="take">TAKE</option><option value="wait">WAIT</option><option value="skip">SKIP</option><option value="nonresponse">Not answered</option><option value="coverage">Missing benchmark coverage</option><option value="useful">Alerts rated useful</option><option value="not_useful">Alerts rated not useful</option><option value="unrated">Unrated alerts</option><option value="unarmed">Unarmed TAKE</option><option value="armed">Unfilled / armed</option><option value="triggered">Triggered, entry pending</option><option value="expired">Expired</option><option value="missed">Missed trigger</option><option value="rejected">Rejected entry</option><option value="open">Open paper</option><option value="closed">Closed paper</option><option value="unresolved">Unresolved paper</option></select></label>}
      <div className="space-y-3">{shown.map((opp) => <article key={opp.id} id={`practice-opportunity-${opp.id}`} className="min-w-0 space-y-3 rounded border p-3" data-testid="practice-opportunity">
        <div className="flex flex-wrap items-baseline justify-between gap-2"><h3 className="font-semibold">{opp.symbol} {!opp.human && <span className="text-xs font-normal text-muted-foreground">· not answered</span>}</h3><span className="text-xs text-muted-foreground">{opp.comparison_status}</span></div>
        {!opp.human && <FactSummary context={opp.context} />}
        {opp.human ? <div className="rounded bg-muted p-2 text-sm"><p><strong>Your choice: {opp.human.decision.toUpperCase()}</strong> · {opp.human.rationale}</p>{opp.human.wait_condition && <p>Wait for {opp.human.wait_condition} until {stamp(opp.human.wait_expiry)}</p>}{opp.human.decision === "take" && <p>Trigger {String(opp.human.plan?.trigger_level ?? "—")} · Stop {String(opp.human.plan?.stop ?? "—")} · Target {String(opp.human.plan?.target ?? "—")}</p>}<details className="mt-1 text-xs text-muted-foreground"><summary className="cursor-pointer">Saved record</summary><p>Frozen decision {opp.human.id} · policy {opp.human.policy_version ?? "unavailable"} · hash {opp.human.policy_hash ?? "unavailable"}</p>{opp.human.decision === "take" && <pre className="overflow-auto whitespace-pre-wrap">{objText(opp.human.plan)}</pre>}</details></div>
          : <ChoiceForm opp={opp} takeUnavailable={takeUnavailable} busy={busy} onSubmit={(body) => void submitChoice(opp, body)} onInvalid={(message) => fail(message, opp.id)} />}
        {opp.human?.decision === "take" && <PracticePaperPlan recordId={opp.human.id} />}
        {(opp.revealed || active.comparison === "assisted") && <div className="rounded border border-sky-500/30 p-2 text-sm"><strong>Agent choice: {opp.agent?.decision?.toUpperCase() ?? "Unavailable"}</strong>{opp.agent && <><p>{opp.agent.rationale}</p>{opp.human && <p className="font-medium">{opp.human.decision === opp.agent.decision ? "Agreement" : "Disagreement"}: you {opp.human.decision.toUpperCase()} · agent {opp.agent.decision.toUpperCase()}</p>}{opp.agent.wait_condition && <p>Agent WAIT condition: {opp.agent.wait_condition} · expires {stamp(opp.agent.wait_expiry)}</p>}<details className="mt-1 text-xs text-muted-foreground"><summary className="cursor-pointer">Saved agent record</summary><p>Frozen decision {opp.agent.id} · policy {opp.agent.policy_version ?? "unavailable"} · hash {opp.agent.policy_hash ?? "unavailable"}</p>{opp.agent.decision === "take" && opp.agent.plan && <pre className="overflow-auto whitespace-pre-wrap">Original agent TAKE plan {objText(opp.agent.plan)}</pre>}</details></>}</div>}
        {!opp.revealed && active.comparison === "independent" && opp.human && <div className="flex flex-wrap items-center gap-2 text-sm"><button type="button" disabled={busy} onClick={() => void reveal(opp)} className="rounded border px-3 py-2 disabled:opacity-50">Reveal agent choice</button><span className="text-xs text-muted-foreground">Works once the agent has committed too.</span></div>}
        {error && errorAt === opp.id && <p role="alert" className="break-words text-sm text-red-600">{error}</p>}
        <details className="rounded bg-muted p-2 text-xs"><summary className="cursor-pointer text-sm">After the close: outcome, paper and alert feedback</summary><div className="mt-2 space-y-2 break-words"><p>Benchmark {opp.benchmark?.status ?? "unavailable"}{opp.benchmark?.reason ? ` · ${opp.benchmark.reason}` : ""}</p><p>Your paper {opp.paper?.status ?? (opp.human?.decision === "take" ? "unarmed" : "none")} · agent paper {opp.agent_paper?.status ?? (opp.agent?.decision === "take" ? "unavailable" : "none")}</p>{opp.context?.price_facts?.length === 0 && <p className="text-amber-700">Coverage gap: no frozen price facts; WAIT/SKIP remain available, TAKE validation may refuse.</p>}{!opp.context && <p className="text-amber-700">Coverage gap: no frozen context.</p>}
          <div className="flex flex-wrap items-center gap-2 text-sm"><label>Alert feedback <select aria-label={`Alert feedback ${opp.symbol}`} value={opp.feedback?.rating ?? "unrated"} onChange={(e) => void action(`/practice/opportunities/${encodeURIComponent(opp.id)}/feedback`, { rating: e.target.value, phone_received: opp.feedback?.phone_received ?? null }, opp.id)} className="rounded border bg-background p-2"><option value="unrated">Unrated</option><option value="useful">Useful</option><option value="not_useful">Not useful</option></select></label><label>Phone receipt <select aria-label={`Phone receipt ${opp.symbol}`} value={opp.feedback?.phone_received == null ? "unreported" : opp.feedback.phone_received ? "yes" : "no"} onChange={(e) => void action(`/practice/opportunities/${encodeURIComponent(opp.id)}/feedback`, { rating: opp.feedback?.rating ?? "unrated", phone_received: e.target.value === "unreported" ? null : e.target.value === "yes" }, opp.id)} className="rounded border bg-background p-2"><option value="unreported">Unreported</option><option value="yes">Yes</option><option value="no">No</option></select></label></div>
          <details><summary className="cursor-pointer">Benchmark record</summary><pre className="overflow-auto">{objText(opp.benchmark)}</pre></details>{opp.paper && <details><summary className="cursor-pointer">Your paper timeline and base/3× cost outcomes</summary><pre className="overflow-auto">{objText(opp.paper)}</pre></details>}{opp.agent_paper && <details><summary className="cursor-pointer">Agent paper timeline and base/3× cost outcomes</summary><pre className="overflow-auto">{objText(opp.agent_paper)}</pre></details>}</div></details>
        <details className="text-xs text-muted-foreground"><summary className="cursor-pointer">Saved setup details</summary>{opp.context ? <div className="mt-2 space-y-2"><p>Opportunity {opp.id}</p><p>Captured {stamp(opp.context.captured_at)} · {opp.context.provider} · context {opp.context.context_sha256}</p>{opp.context.price_facts?.map((fact, i) => <p key={`${fact.name}-${i}`} className="break-words">{fact.name}: {fact.value} {fact.unit} · source {fact.source} · formed {stamp(fact.formed_at)} · observed {stamp(fact.observed_at)}</p>)}<pre className="overflow-auto rounded bg-muted p-2">{objText(opp.context.packet)}</pre></div> : <p className="mt-2">Opportunity {opp.id} · frozen context unavailable; TAKE cannot be assumed valid.</p>}</details>
      </article>)}</div>
      {opportunities.some((opp) => !opp.human) && <p className="text-sm text-muted-foreground">Setups you don&apos;t answer are recorded as no response, never as SKIP.</p>}
      <details className="rounded border p-3 text-sm"><summary className="cursor-pointer font-medium">Run details</summary><div className="mt-2 space-y-1 text-xs">
        <p>{active.status.toUpperCase()} · {active.result ?? "result pending"}{active.late ? " · LATE" : ""} · {active.mode} preparation · {active.comparison} comparison{active.independence ? ` · independence ${active.independence}` : ""}</p>
        <p>Created {stamp(active.created_at)} · finished {stamp(active.finished_at)} · deadline {stamp(active.deadline)}</p>
        <p>Calendar {active.calendar?.status ?? "unavailable"} · policy {active.policy_version} · hash {active.policy_hash}</p>
        <p>Run {active.id} · revision {active.revision ?? 0}{active.parent_id ? ` · revises ${active.parent_id}` : " · original run"}</p>
        <p>Agent {active.agent?.status ?? "disabled"}{active.agent?.error ? ` · ${active.agent.error}` : ""} · model {active.agent?.model ?? "unavailable"} · cost {active.agent?.cost == null ? "unavailable" : active.agent.cost} ({active.agent?.cost_provenance ?? "cost provenance unavailable"})</p>
        <p>Your choices: TAKE {active.counts?.take ?? 0} · WAIT {active.counts?.wait ?? 0} · SKIP {active.counts?.skip ?? 0} · no response {opportunities.filter((o) => !o.human).length}</p>
        <p>Visible agent choices: TAKE {visibleAgentCounts.take} · WAIT {visibleAgentCounts.wait} · SKIP {visibleAgentCounts.skip}</p>
        <p>08:50 scheduling is {active.scheduling_configured ? "configured; timer execution remains unobserved" : "disabled"}. Choices and paper practice stay separate from journal fills; arming a paper plan remains explicit.</p>
        <details><summary className="cursor-pointer">Agent usage</summary><pre className="overflow-auto">{active.agent?.usage ? objText(active.agent.usage) : "unavailable"}</pre></details>
        <details><summary className="cursor-pointer">Agent runtime and cost provenance</summary><pre className="overflow-auto whitespace-pre-wrap">{objText(active.agent)}</pre></details>
        <div className="flex flex-wrap gap-2 pt-1">{!preparing && (active.revision ?? 0) < 10 && isToday && <button type="button" disabled={busy} onClick={() => void retryRevision()} className="rounded border px-3 py-2 text-sm disabled:opacity-50">Prepare assisted revision</button>}{!preparing && <button type="button" disabled={busy} onClick={() => void action(`/practice/runs/${encodeURIComponent(active.id)}/benchmark`, {})} className="rounded border px-3 py-2 text-sm disabled:opacity-50">Refresh underlying benchmark</button>}</div>
      </div></details>
    </div>}
  </section></fieldset>;
}

type Fact = NonNullable<Context["price_facts"]>[number];
const FIELD_WORDS: Record<string, string> = { o: "open", h: "high", l: "low", c: "close", vw: "VWAP" };
const factField = (fact: Fact) => FIELD_WORDS[fact.name.split(":").pop() ?? ""] ?? fact.name;
const factLabel = (fact: Fact) => `${fact.value} · ${factField(fact)} of bar ending ${clock(fact.formed_at)}`;
const newestFirst = (facts: Fact[]) => [...facts].sort((a, b) => Date.parse(b.formed_at) - Date.parse(a.formed_at));

function FactSummary({ context }: { context: Context | null }) {
  if (!context) return <p className="text-sm text-amber-700">No saved market context for this setup, so a Take can&apos;t be planned. Wait or Skip still work.</p>;
  const facts = newestFirst(context.price_facts ?? []);
  if (!facts.length) return <p className="text-sm text-amber-700">No verified price facts were saved for this setup, so a Take can&apos;t be planned. Wait or Skip still work.</p>;
  const latest = facts.filter((fact) => fact.formed_at === facts[0].formed_at);
  return <p className="text-sm text-muted-foreground">Latest bar ending {clock(facts[0].formed_at)}: {latest.map((fact) => `${factField(fact)} ${fact.value}`).join(" · ")} · {facts.length} price facts saved {stamp(context.captured_at)}</p>;
}

type ChoiceBody = { decision: Decision["decision"]; rationale: string; wait_condition?: string; wait_expiry?: string; plan?: Record<string, unknown> };
const isoOrNull = (local: string) => { const parsed = new Date(local); return local && Number.isFinite(parsed.getTime()) ? parsed.toISOString() : null; };

function ChoiceForm({ opp, takeUnavailable, busy, onSubmit, onInvalid }: { opp: Opportunity; takeUnavailable: string | null; busy: boolean; onSubmit: (body: ChoiceBody) => void; onInvalid: (message: string) => void }) {
  const facts = newestFirst(opp.context?.price_facts ?? []);
  const [decision, setDecision] = useState<Decision["decision"] | "">("");
  const [rationale, setRationale] = useState("");
  const [waitCondition, setWaitCondition] = useState("");
  const [expiry, setExpiry] = useState("");
  const [refs, setRefs] = useState({ trigger_fact: "", stop_fact: "", target_fact: "" });
  const [guard, setGuard] = useState({ min: "", max: "" });
  const [freshMinutes, setFreshMinutes] = useState("60");
  const value = (name: string) => facts.find((fact) => fact.name === name)?.value;
  const [trigger, stop, target] = [value(refs.trigger_fact), value(refs.stop_fact), value(refs.target_fact)];
  const expiryIso = isoOrNull(expiry);
  const risk = trigger !== undefined && stop !== undefined ? trigger - stop : null;
  const reward = trigger !== undefined && target !== undefined ? target - trigger : null;
  function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!decision) return onInvalid("Choose Take, Wait or Skip.");
    if (decision === "wait" && (!waitCondition.trim() || !expiryIso)) return onInvalid("WAIT requires a condition and expiry.");
    if (decision === "take" && (!refs.trigger_fact || !refs.stop_fact || !refs.target_fact || !guard.max || !expiryIso)) return onInvalid("TAKE needs a trigger, stop, target, entry range and plan expiry.");
    // The A1 server validation is unchanged; this assembles the same plan the JSON field used to accept.
    onSubmit({ decision, rationale, ...(decision === "wait" ? { wait_condition: waitCondition, wait_expiry: expiryIso! } : {}),
      ...(decision === "take" ? { plan: { instrument: "stock", direction: "long", trigger: { kind: "close_beyond_level", interval: "15m", session: "regular" },
        ...refs, trigger_level: trigger, stop, target, entry_guard: { min: Number(guard.min), max: Number(guard.max) }, expiry: expiryIso,
        max_holding_sessions: 2, freshness_limit_seconds: Math.round(Number(freshMinutes) * 60), cost_model: { version: "p0-cost-v1", slippage_bps: 1, slippage_per_share: 0.01 } } } : {}) });
  }
  const factSelect = (role: keyof typeof refs, label: string) => <label className="grid min-w-0 gap-1 text-sm">{label}<select required value={refs[role]} onChange={(event) => { setRefs({ ...refs, [role]: event.target.value }); if (role === "trigger_fact") setGuard({ ...guard, min: String(value(event.target.value) ?? "") }); }} className="w-full min-w-0 rounded border bg-background p-2"><option value="">Choose a saved price</option>{facts.map((fact) => <option key={fact.name} value={fact.name}>{factLabel(fact)}</option>)}</select></label>;
  return <form onSubmit={submit} className="space-y-2">
    <div role="radiogroup" aria-label={`Decision ${opp.symbol}`} className="grid grid-cols-3 gap-2">{(["take", "wait", "skip"] as const).map((choice) => <label key={choice} className={`flex min-h-11 cursor-pointer items-center justify-center rounded border text-sm has-[:disabled]:cursor-not-allowed has-[:disabled]:opacity-50 ${decision === choice ? "border-primary bg-primary/15 font-semibold" : ""}`}><input type="radio" name={`decision-${opp.id}`} value={choice} checked={decision === choice} disabled={choice === "take" && (!facts.length || !!takeUnavailable)} onChange={() => { setDecision(choice); setExpiry(""); }} className="sr-only" />{choice.charAt(0).toUpperCase() + choice.slice(1)}</label>)}</div>
    {facts.length > 0 && takeUnavailable && <p className="text-xs text-muted-foreground">{takeUnavailable} Wait or Skip still work.</p>}
    <label className="grid gap-1 text-sm">Reason<input required value={rationale} onChange={(event) => setRationale(event.target.value)} className="w-full rounded border bg-background p-2" /></label>
    {decision === "wait" && <div className="grid gap-2 sm:grid-cols-2"><label className="grid gap-1 text-sm">Wait for<input required value={waitCondition} onChange={(event) => setWaitCondition(event.target.value)} className="w-full rounded border bg-background p-2" /></label><label className="grid gap-1 text-sm">Until<input required type="datetime-local" value={expiry} onChange={(event) => setExpiry(event.target.value)} className="w-full rounded border bg-background p-2" /></label></div>}
    {decision === "take" && <div className="space-y-2">
      <div className="grid gap-2 sm:grid-cols-3">{factSelect("trigger_fact", "Trigger (15-min close above)")}{factSelect("stop_fact", "Stop")}{factSelect("target_fact", "Target")}</div>
      <div className="grid gap-2 sm:grid-cols-3"><label className="grid gap-1 text-sm">Enter only between<input required type="number" min="0" step="any" value={guard.min} onChange={(event) => setGuard({ ...guard, min: event.target.value })} className="w-full rounded border bg-background p-2" /></label><label className="grid gap-1 text-sm">and<input required type="number" min="0" step="any" value={guard.max} onChange={(event) => setGuard({ ...guard, max: event.target.value })} className="w-full rounded border bg-background p-2" /></label><label className="grid gap-1 text-sm">Plan expires<input required type="datetime-local" value={expiry} onChange={(event) => setExpiry(event.target.value)} className="w-full rounded border bg-background p-2" /></label></div>
      {risk !== null && reward !== null && <p className="text-xs text-muted-foreground">{risk > 0 && reward > 0 ? `Risk ${risk.toFixed(2)} per share · reward ${reward.toFixed(2)} · about ${(reward / risk).toFixed(1)}R from the trigger, before costs (preview only, not saved)` : "The stop must be below the trigger and the target above it."}</p>}
      <details className="text-xs text-muted-foreground"><summary className="cursor-pointer">Set by the practice policy</summary><p className="mt-1">Long shares · enters on a regular-session 15-minute close above the trigger · holds up to 2 sessions · costs p0-cost-v1 (1 bp + $0.01 per share). The server checks every term when you save.</p><label className="mt-1 grid max-w-xs gap-1">Use prices no older than (minutes)<input required type="number" min="1" max="1440" step="1" value={freshMinutes} onChange={(event) => setFreshMinutes(event.target.value)} className="rounded border bg-background p-1.5" /></label></details>
    </div>}
    {(decision === "wait" || decision === "take") && <p className="text-xs text-muted-foreground">{expiryIso ? `Saves as ${stamp(expiryIso)}.` : "Times use this device's time zone; the saved time shows in Eastern."}</p>}
    <button disabled={busy} className="min-h-11 w-full rounded bg-primary px-3 py-2 text-sm text-primary-foreground disabled:opacity-50 sm:w-auto">Save choice (final)</button>
  </form>;
}
