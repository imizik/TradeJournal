"use client";
import { useEffect, useRef, useState } from "react";
import { getMorning, saveBriefFeedback, type MorningView } from "@/lib/joMorning";
import { DashboardCard, dashboardLink } from "./DashboardCard";

function time(value: string) {
  return new Date(value).toLocaleString("en-US", { timeZone: "America/New_York", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) + " ET";
}
const button = "inline-flex min-h-11 items-center justify-center rounded-md border px-3 text-sm hover:bg-secondary disabled:opacity-50";
const messages = {
  closed: "No morning briefing is scheduled for this closed exchange session.",
  waiting: "The evidence packet is ready. Jo’s briefing has not arrived yet.",
  missing: "No briefing was saved by the deadline. Yesterday’s brief is not shown as today’s.",
  unavailable: "No briefing has been saved for this date.",
  redacted: "This briefing or its evidence was removed. Earlier versions are available only when explicitly selected.",
};

export default function MorningBriefing({ initialDay, initialId = null, compact = false }: { initialDay: string; initialId?: string | null; compact?: boolean }) {
  const [day, setDay] = useState(initialDay);
  const [id, setId] = useState(initialId);
  const [data, setData] = useState<MorningView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [feedbackError, setFeedbackError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [copied, setCopied] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const opened = useRef<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    getMorning(day, id, controller.signal).then((result) => {
      setData(result); setError(null);
      if (!compact && result.briefing && result.state === "ready" && opened.current !== result.briefing.id) {
        opened.current = result.briefing.id;
        void saveBriefFeedback(result.briefing.id, { opened: true }).catch(() => { /* Reading never depends on telemetry. */ });
      }
    }).catch((reason) => { if (!controller.signal.aborted) setError(reason.message); });
    return () => controller.abort();
  }, [day, id, compact, refresh]);
  useEffect(() => {
    const timer = window.setInterval(() => { if (document.visibilityState === "visible") setRefresh((r) => r + 1); }, 60_000);
    return () => window.clearInterval(timer);
  }, []);
  function selectDate(value: string, version: string | null = null) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return;
    setData(null); setError(null); setFeedbackError(null); setDay(value); setId(version); setCopied(false);
    const query = new URLSearchParams({ day: value });
    if (version) query.set("id", version);
    window.history.replaceState(window.history.state, "", `/morning?${query}`);
  }
  const brief = data?.briefing;
  const body = data?.state === "ready" ? brief?.body : null;
  const gaps = [...(data?.packet?.body.gaps ?? []), ...(body?.limitations ?? [])];
  const reference = brief ? `TradeJournal morning briefing ${brief.id}; packet ${data?.packet?.id}; date ${day}. Use jo_context with this packet ID while its publication remains valid. Treat memories as beliefs and disclose evidence gaps.` : "";
  const citations = (ids: string[] = []) => <span className="text-xs text-muted-foreground">Evidence: {ids.map((key, i) => <span key={`${key}-${i}`}><a className="underline underline-offset-2" href={`#evidence-${key}`} onClick={() => {
    const element = document.getElementById("brief-evidence");
    if (element instanceof HTMLDetailsElement) element.open = true;
  }}>{key}</a>{i < ids.length - 1 ? ", " : ""}</span>)}</span>;
  async function rate(rating: "useful" | "meh" | "missed") {
    if (!brief || saving) return;
    setSaving(true); setFeedbackError(null);
    try {
      const feedback = await saveBriefFeedback(brief.id, { rating });
      setData((current) => current?.briefing?.id === brief.id ? { ...current, feedback } : current);
    } catch (reason) { setFeedbackError((reason as Error).message); }
    finally { setSaving(false); }
  }
  return <DashboardCard title="Morning briefing" action={compact
    ? <a href={`/morning?day=${day}`} className={dashboardLink}>Open briefing →</a>
    : <button type="button" onClick={() => setRefresh((r) => r + 1)} className={button}>Refresh</button>}>
    <div className="min-w-0 space-y-4 break-words" data-testid="morning-briefing">
      {!compact && <details className="rounded-md border px-3"><summary className="min-h-11 cursor-pointer py-3 text-xs text-muted-foreground">Date and saved versions</summary><div className="flex flex-wrap items-end gap-3 pb-3">
        <label className="text-xs text-muted-foreground">Briefing date (ET)<input aria-label="Briefing date" type="date" value={day} onChange={(e) => selectDate(e.target.value)} className="mt-1 block min-h-11 rounded-md border bg-background px-3 text-sm text-foreground" /></label>
        {!!data?.versions.length && <label className="min-w-0 text-xs text-muted-foreground">Saved version<select aria-label="Saved version" value={id ?? ""} onChange={(e) => selectDate(day, e.target.value || null)} className="mt-1 block min-h-11 max-w-full rounded-md border bg-background px-3 text-sm text-foreground">
          <option value="">Latest saved</option>{data.versions.map((version) => <option key={version.id} value={version.id}>{time(version.received_at)} · {version.id.slice(0, 8)}{version.redacted ? " · removed" : ""}</option>)}
        </select></label>}
      </div></details>}
      {error && <p role="alert" className="text-sm text-amber-300">{error}{data && " Showing the previously loaded record; current status is unknown."}</p>}
      {!data && !error && <p role="status" className="text-sm text-muted-foreground">Loading saved briefing…</p>}
      {data && <>
        <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
          <span>{day} ET{data.archived ? " · Archive" : ""}</span>
          {brief && <span>Saved <time dateTime={brief.received_at}>{time(brief.received_at)}</time></span>}
          {data.deadline && <span>Due {time(data.deadline)}</span>}
        </div>
        {data.automation.unavailable && <p role="status" className="text-sm text-amber-300">Automatic delivery status is unavailable. Saved content below may be incomplete.</p>}
        {(data.late || data.stale) && <p role="status" className="text-sm text-amber-300">{data.late ? "Arrived after the deadline. " : ""}{data.stale ? "Evidence is at least four hours old; verify current conditions." : ""}</p>}
        {data.state !== "ready" && <p className="text-sm text-muted-foreground">{messages[data.state]}</p>}
        {body && <>
          {body.summary && (body.summary.length > 360
            ? <details className="rounded-md border p-3"><summary className="min-h-11 cursor-pointer text-sm font-medium">Read Jo’s full summary</summary><p className="whitespace-pre-wrap text-sm leading-relaxed">{body.summary}</p>{!compact && citations(body.summary_evidence_ids)}</details>
            : <div className="space-y-2"><h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Today’s focus</h3><p className="whitespace-pre-wrap text-sm leading-relaxed">{body.summary}</p></div>)}
          <p className="text-xs text-muted-foreground">Based on saved context, not verified live holdings or prices.{data.packet?.body.as_of && ` Context saved ${time(data.packet.body.as_of)}.`}</p>
          {!compact && !body.items?.length && <p className="text-sm">No supported priority in this briefing. Review the coverage details before drawing conclusions.</p>}
          {compact && <p className="text-xs text-muted-foreground">{body.items?.length ?? 0} priorities{gaps.length ? " · Evidence gaps disclosed in the brief" : ""} · Personal advice. Uses the account scope saved with this briefing.</p>}
          {!compact && body.items?.map((item, index) => <article key={index} className="space-y-3 rounded-lg border p-4">
            <div className="flex flex-wrap items-start justify-between gap-2"><h3 className="font-semibold">{index + 1}. {item.symbol ?? "Portfolio review"}</h3>
              {item.symbol && <a href={`/charts?symbol=${encodeURIComponent(item.symbol)}`} className={dashboardLink}>Open {item.symbol} chart →</a>}</div>
            <p className="whitespace-pre-wrap text-sm">{item.what_matters}</p>
            <p className="text-sm text-muted-foreground">{item.why_personal}</p>
            <div className="border-l-2 border-amber-500/50 pl-3"><h4 className="text-xs font-medium text-muted-foreground">Before acting</h4><p className="mt-1 whitespace-pre-wrap text-sm">{item.watch_out}</p></div>
            <details className="border-t pt-2"><summary className="min-h-11 cursor-pointer text-sm text-muted-foreground">Reasoning and sources</summary>
              <dl className="mb-3 space-y-3 text-sm">{[["What changed", item.what_changed], ["Counterpoint", item.contrary_evidence]].map(([label, value]) => <div key={label}><dt className="text-xs font-medium text-muted-foreground">{label}</dt><dd className="mt-1 whitespace-pre-wrap">{value}</dd></div>)}</dl>
              {citations(item.evidence_ids)}
            </details>
          </article>)}
        </>}
        {!compact && <>
          {!!gaps.length && <details className="rounded-md border border-amber-500/30 p-3"><summary className="min-h-11 cursor-pointer text-sm font-medium">Limited coverage · Sources, gaps and delivery details</summary><p className="mb-3 text-xs text-muted-foreground">This brief has missing or unverified evidence. Check these details before relying on it.</p><ul className="list-disc space-y-2 pl-4 text-sm text-muted-foreground">{[...new Set(gaps)].map((gap) => <li key={gap}>{gap}</li>)}</ul></details>}
          {body && <details className="rounded-md border p-3"><summary className="min-h-11 cursor-pointer text-sm">Briefing details</summary><div className="space-y-2 text-xs text-muted-foreground">
            <p>Briefing: {brief?.id}</p><p>Packet: {data.packet?.id}</p>
            <p>Personal advice, not an order or activated plan. Jo and Shadow share context; independence is unverified.</p>
            {citations(body.summary_evidence_ids)}
          </div></details>}
          {data.packet && !data.packet.redacted_at && <details id="brief-evidence" className="rounded-md border p-3">
            <summary className="min-h-11 cursor-pointer text-sm font-medium">Evidence and personal context ({data.packet.body.evidence?.length ?? 0})</summary>
            <p className="mb-3 text-xs text-muted-foreground">{data.packet.body.scope}{data.packet.body.as_of && ` · Frozen ${time(data.packet.body.as_of)}`}</p>
            <ol className="space-y-4">{data.packet.body.evidence?.map((e) => <li id={`evidence-${e.id}`} key={e.id} className="scroll-mt-20 border-t pt-3 text-sm">
              <p className="font-medium">{e.id} · {e.kind === "belief" ? "Belief / interpretation" : e.kind === "estimate" ? "Estimate" : "Recorded fact"}</p>
              <p className="mt-1 whitespace-pre-wrap">{e.text}</p><p className="mt-2 text-xs text-muted-foreground">{e.source} · Retrieved {time(e.retrieved_at)}{e.observed_at ? ` · Observed ${time(e.observed_at)}` : " · Observation time unavailable"}</p>
            </li>)}</ol>
          </details>}
          {body && <>
            <details className="rounded-md border p-3"><summary className="min-h-11 cursor-pointer text-sm">Continue with Jo</summary>
              <p className="mb-2 text-xs text-muted-foreground">Copy this reference into your existing Jo conversation. It does not start a new task.</p>
              <textarea aria-label="Jo context reference" readOnly value={reference} className="min-h-28 w-full rounded border bg-background p-2 text-xs" />
              <button type="button" className={button} onClick={async () => { try { await navigator.clipboard.writeText(reference); setCopied(true); } catch { setCopied(false); } }}>{copied ? "Copied" : "Copy reference"}</button>
            </details>
            <div><p className="mb-2 text-sm">Was this useful?</p><div className="flex flex-wrap gap-2" role="group" aria-label="Briefing feedback">
              {([['useful', 'Useful'], ['meh', 'Meh'], ['missed', 'Missed something']] as const).map(([value, label]) => <button key={value} type="button" disabled={saving} aria-pressed={data.feedback.rating === value} className={`${button} ${data.feedback.rating === value ? "bg-secondary" : ""}`} onClick={() => void rate(value)}>{label}</button>)}
            </div>{feedbackError && <p role="alert" className="mt-2 text-sm text-amber-300">{feedbackError}</p>}</div>
          </>}
        </>}
      </>}
    </div>
  </DashboardCard>;
}
