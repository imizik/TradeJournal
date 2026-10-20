"use client";
import { useEffect, useRef, useState } from "react";
import { copyText } from "@/lib/clipboard";
import { getMorning, saveBriefFeedback, type BriefEvidence, type BriefItem, type BriefMemory, type MorningDelivery, type MorningView } from "@/lib/joMorning";
import { DashboardCard, dashboardLink } from "./DashboardCard";

const zone = "America/New_York";
function time(value: string) {
  return new Date(value).toLocaleString("en-US", { timeZone: zone, month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) + " ET";
}
/** Clock time alone when the moment falls on the briefing's own ET date; otherwise the date too. */
function clock(value: string, day: string) {
  const date = new Date(value);
  if (date.toLocaleDateString("en-CA", { timeZone: zone }) !== day) return time(value);
  return date.toLocaleTimeString("en-US", { timeZone: zone, hour: "numeric", minute: "2-digit" }) + " ET";
}
const longDate = (day: string) => new Date(`${day}T12:00:00Z`).toLocaleDateString("en-US", { timeZone: "UTC", weekday: "long", month: "short", day: "numeric", year: "numeric" });
/** The saved source's leading clause ("Alpaca IEX latest trade"); its caveats stay in the evidence details. */
const sourceLabel = (e: BriefEvidence) => e.source.split(";")[0].trim() || e.id;
const memoryKind = (m: BriefMemory) => ({ statement: "Statement", thesis: "Thesis", preference: "Preference", lesson: "Lesson" })[m.body.kind ?? "statement"] ?? "Memory";
const kindLabel = (kind: BriefEvidence["kind"]) => kind === "belief" ? "Belief / interpretation" : kind === "estimate" ? "Estimate" : "Recorded fact";

const button = "inline-flex min-h-11 items-center justify-center rounded-md border px-3 text-sm hover:bg-secondary disabled:opacity-50";
const textButton = "inline-flex min-h-11 items-center text-xs text-primary hover:underline sm:min-h-0";
const messages = {
  closed: "No morning briefing is scheduled for this closed exchange session.",
  waiting: "The evidence packet is ready. Jo’s briefing has not arrived yet.",
  missing: "No briefing was saved by the deadline. Yesterday’s brief is not shown as today’s.",
  unavailable: "No briefing has been saved for this date.",
  redacted: "This briefing or its evidence was removed. Earlier versions are available only when explicitly selected.",
};
const statusLabels = { ready: "Ready", closed: "Market closed", waiting: "Waiting for Jo", missing: "Missing", unavailable: "Not saved", redacted: "Removed" };

const minutes = (seconds: number) => seconds < 90 ? `${seconds} s` : `${Math.round(seconds / 60)} min`;
const outcomeText = { sent: "sent", failed: "couldn’t be sent; retrying", unknown: "outcome unknown, may have reached your phone; not resent" };

/** What is known about the scheduled brief's delivery, and what TradeJournal cannot see. */
function DeliveryStatus({ delivery, pending, day }: { delivery: MorningDelivery; pending: MorningView["automation"]["pending"]; day: string }) {
  if (delivery.fulfilment === "not_expected") return null;
  const due = delivery.deadline ? clock(delivery.deadline, day) : "the deadline";
  const headline = {
    on_time: <>On time. In the journal at {delivery.available_at && clock(delivery.available_at, day)}, due {due}.</>,
    late: <>Late. In the journal at {delivery.available_at && clock(delivery.available_at, day)}, {minutes(delivery.late_by_seconds ?? 0)} after the {due} deadline. The miss stays recorded.</>,
    missing: <>Missing. Nothing reached the journal by {due}.{delivery.publication === "missing" && " The packet for Jo was never published, so Jo had nothing to read."}</>,
    pending: <>Due {due}.{delivery.publication === "missing" && " The packet for Jo hasn’t been published yet."}</>,
    unknown: <>Status unknown: the market calendar or the Jo connection is unavailable, so the app can’t tell which packet was scheduled.</>,
  }[delivery.fulfilment];
  const watchdog = delivery.notifications.watchdog;
  const warn = delivery.fulfilment === "late" || delivery.fulfilment === "missing";
  return <section aria-label="Scheduled delivery" data-testid="brief-delivery" className="text-xs text-muted-foreground">
    <details className="rounded-md border px-3">
      <summary className="min-h-11 cursor-pointer py-2.5"><span className={warn ? "text-amber-300" : "text-foreground"}><span className="font-medium">Scheduled brief:</span> {headline}</span></summary>
      <div className="space-y-1 pb-2.5">
        {delivery.available_at && <p>{delivery.submitted_at
          ? <>Check received it at {clock(delivery.submitted_at, day)}; importing took {minutes(delivery.import_lag_seconds ?? 0)}.</>
          : "Check’s receipt time wasn’t recorded for this brief."} Who started the run (the scheduled task or a manual request) isn’t visible to TradeJournal.</p>}
        {!!delivery.other_briefings && <p>{delivery.other_briefings} other {delivery.other_briefings === 1 ? "brief was" : "briefs were"} saved for this date from a separate packet (a manual or recovery request); {delivery.other_briefings === 1 ? "it doesn’t" : "they don’t"} count as the scheduled delivery.</p>}
        <p>Phone watchdog: {!watchdog || watchdog.state === "unknown" ? "status unavailable."
          : watchdog.state === "off" ? "off, so no phone alert is sent for this brief."
          : watchdog.notices.length ? watchdog.notices.map((n, i) => <span key={i}>{i ? " " : ""}“{n.title}” at {clock(n.at, day)}: {outcomeText[n.outcome]}.</span>)
          : "on; nothing sent for this date."}</p>
        <p>ChatGPT’s own notifications aren’t visible to TradeJournal.</p>
      </div>
    </details>
    {!!pending?.count && <p className="mt-1 text-amber-300">A submission from Jo is waiting to be imported{pending.oldest_submitted_at ? ` (received ${clock(pending.oldest_submitted_at, day)})` : ""}.</p>}
  </section>;
}

function joReference(briefId: string, packetId: string | undefined, day: string, question: string, item: BriefItem | null, index: number, memoryIds: string[] = []) {
  const lines = ["TradeJournal morning briefing — continue from this saved context.", `Briefing ID: ${briefId}`, `Packet ID: ${packetId ?? "unavailable"}`, `Briefing date: ${day} ET`];
  if (item) {
    lines.push(`Priority ${index + 1}: ${item.symbol ?? "Portfolio review"} — ${item.what_matters}`);
    if (item.evidence_ids.length) lines.push(`Evidence IDs: ${item.evidence_ids.join(", ")}`);
    if (memoryIds.length) lines.push(`Saved memory revisions used: ${memoryIds.join(", ")}`);
  }
  lines.push(`My question: ${question.trim() || "(add your question here)"}`);
  lines.push("Use jo_context with this packet ID only while its publication remains valid, and say so if it has expired. Treat memories as beliefs and disclose evidence gaps.");
  return lines.join("\n");
}

export default function MorningBriefing({ initialDay, initialId = null, compact = false }: { initialDay: string; initialId?: string | null; compact?: boolean }) {
  const [day, setDay] = useState(initialDay);
  const [id, setId] = useState(initialId);
  const [data, setData] = useState<MorningView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [feedbackError, setFeedbackError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [asking, setAsking] = useState<number | "brief" | null>(null);
  const [question, setQuestion] = useState("");
  const [copy, setCopy] = useState<"copied" | "failed" | null>(null);
  const [fullSummary, setFullSummary] = useState(false);
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
    setData(null); setError(null); setFeedbackError(null); setDay(value); setId(version); setAsking(null); setCopy(null); setFullSummary(false);
    const query = new URLSearchParams({ day: value });
    if (version) query.set("id", version);
    window.history.replaceState(window.history.state, "", `/morning?${query}`);
  }
  const brief = data?.briefing;
  const body = data?.state === "ready" ? brief?.body : null;
  const packet = data?.packet;
  const gaps = [...new Set([...(packet?.body.gaps ?? []), ...(body?.limitations ?? [])])];
  const evidence = new Map((packet?.body.evidence ?? []).map((e) => [e.id, e]));
  const openDetails = (key: string) => () => {
    const element = document.getElementById(key);
    if (element instanceof HTMLDetailsElement) element.open = true;
  };
  const openEvidence = openDetails("brief-evidence");
  const memories = packet && !packet.redacted_at ? packet.memories ?? [] : [];
  /** The exact revision a cited memory record was copied from: same saved wording and save time, and only when that pairing is unique. */
  const memoryFor = (e?: BriefEvidence) => {
    if (!e || e.kind !== "belief" || !e.observed_at) return null;
    const observed = Date.parse(e.observed_at);
    const matches = memories.filter((m) => !m.redacted_at && m.body.original_text === e.text && Date.parse(m.received_at) === observed);
    return matches.length === 1 ? matches[0] : null;
  };
  const usedMemories = (item: BriefItem) => [...new Map(item.evidence_ids.map((key) => memoryFor(evidence.get(key)))
    .filter((m): m is BriefMemory => !!m).map((m) => [m.id, m])).values()];
  const memoryMeta = (m: BriefMemory) => `${memoryKind(m)}${m.symbol ? ` · ${m.symbol}` : ""} · revision ${m.revision} · saved ${time(m.received_at)}`;
  /** Cited evidence grouped by saved source, linked to the exact record in the evidence list. */
  const sources = (ids: string[] = []) => {
    if (!ids.length) return null;
    const groups: { label: string; first: string; count: number; observed: string | null; known: boolean }[] = [];
    for (const key of ids) {
      const e = evidence.get(key);
      const label = e ? sourceLabel(e) : key;
      let group = groups.find((g) => g.label === label);
      if (!group) groups.push(group = { label, first: key, count: 0, observed: null, known: !!e });
      group.count += 1;
      if (e?.observed_at && (!group.observed || Date.parse(e.observed_at) > Date.parse(group.observed))) group.observed = e.observed_at;
    }
    return <p className="text-xs leading-relaxed text-muted-foreground"><span className="font-medium">Sources: </span>{groups.map((g, i) => <span key={g.first}>
      {g.known && !compact ? <a className="underline underline-offset-2 hover:text-foreground" href={`#evidence-${g.first}`} onClick={openEvidence}>{g.label}{g.count > 1 ? ` ×${g.count}` : ""}</a> : <span>{g.label}{g.count > 1 ? ` ×${g.count}` : ""}</span>}
      {g.observed && <> · {g.count > 1 ? "latest " : ""}observed <time dateTime={g.observed}>{clock(g.observed, day)}</time></>}{i < groups.length - 1 ? "; " : ""}
    </span>)}</p>;
  };
  async function rate(rating: "useful" | "meh" | "missed") {
    if (!brief || saving) return;
    setSaving(true); setFeedbackError(null);
    try {
      const feedback = await saveBriefFeedback(brief.id, { rating });
      setData((current) => current?.briefing?.id === brief.id ? { ...current, feedback } : current);
    } catch (reason) { setFeedbackError((reason as Error).message); }
    finally { setSaving(false); }
  }
  function ask(target: number | "brief") {
    setAsking((current) => current === target ? null : target); setCopy(null);
  }
  const joPanel = (item: BriefItem | null, index: number) => {
    if (!brief) return null;
    const reference = joReference(brief.id, packet?.id, day, question, item, index, item ? usedMemories(item).map((m) => m.id) : []);
    return <div className="space-y-2 rounded-md bg-muted/40 p-3">
      <label className="block text-xs text-muted-foreground">Your question for Jo (optional)
        <input value={question} onChange={(e) => { setQuestion(e.target.value); setCopy(null); }} placeholder={item?.symbol ? `What should I check on ${item.symbol} first?` : "What should I look at first?"} className="mt-1 block min-h-11 w-full rounded-md border bg-background px-3 text-sm text-foreground" />
      </label>
      <textarea aria-label="Jo context reference" readOnly value={reference} rows={6} className="w-full rounded-md border bg-background p-2 font-mono text-xs" />
      <div className="flex flex-wrap items-center gap-3">
        <button type="button" className={button} onClick={async () => setCopy(await copyText(reference) ? "copied" : "failed")}>Copy for Jo</button>
        <p role="status" className={`text-xs ${copy === "failed" ? "text-amber-300" : "text-muted-foreground"}`}>{copy === "copied" ? "Copied. Paste it into your Jo conversation." : copy === "failed" ? "Couldn’t copy. Select the text above and copy it by hand." : ""}</p>
      </div>
      <p className="text-xs text-muted-foreground">This copies text only. It does not open Jo, start a task, or guarantee Jo can still read an expired packet.</p>
    </div>;
  };

  const dateControls = <details className="open:basis-full">
    <summary className="inline-flex min-h-11 cursor-pointer items-center text-primary hover:underline sm:min-h-0">Dates &amp; versions</summary>
    <div className="mt-1 flex flex-wrap items-end gap-3 rounded-md border bg-card p-3 text-muted-foreground shadow-lg">
      <label>Briefing date (ET)<input aria-label="Briefing date" type="date" value={day} onChange={(e) => selectDate(e.target.value)} className="mt-1 block min-h-11 rounded-md border bg-background px-3 text-sm text-foreground" /></label>
      {!!data?.versions.length && <label className="min-w-0">Saved version<select aria-label="Saved version" value={id ?? ""} onChange={(e) => selectDate(day, e.target.value || null)} className="mt-1 block min-h-11 max-w-full rounded-md border bg-background px-3 text-sm text-foreground">
        <option value="">Latest saved</option>{data.versions.map((version) => <option key={version.id} value={version.id}>{time(version.received_at)} · {version.id.slice(0, 8)}{version.redacted ? " · removed" : ""}</option>)}
      </select></label>}
    </div>
  </details>;
  // The delivery block already reports a late scheduled brief; repeat it only for other saved briefs.
  const lateNote = !!data?.late && (compact || data.delivery?.briefing_id !== brief?.id || data.delivery?.fulfilment === "not_expected");
  const status = <>
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
      {data && <><span className={`rounded px-1.5 py-0.5 font-medium ${data.state === "ready" && !data.late && !data.stale ? "bg-secondary text-foreground" : "bg-amber-500/15 text-amber-300"}`}>{data.state === "ready" && data.late ? "Late" : statusLabels[data.state]}</span>
      {compact && <span>{day} ET</span>}
      {data.archived && <span>Archive</span>}
      {brief && <span>Saved <time dateTime={brief.received_at}>{clock(brief.received_at, day)}</time></span>}
      {packet?.body.as_of && <span>Context <time dateTime={packet.body.as_of}>{clock(packet.body.as_of, day)}</time></span>}
      {data.deadline && <span>Due {clock(data.deadline, day)}</span>}</>}
      {!compact && dateControls}
    </div>
    {data?.automation.unavailable && <p role="status" className="text-sm text-amber-300">Automatic delivery status is unavailable. Saved content below may be incomplete.</p>}
    {!compact && data?.delivery && <DeliveryStatus delivery={data.delivery} pending={data.automation.pending} day={day} />}
    {(lateNote || data?.stale) && <p role="status" className="text-sm text-amber-300">{lateNote ? "Arrived after the deadline. " : ""}{data?.stale ? "Evidence is at least four hours old; verify current conditions." : ""}</p>}
    {body && <p className="text-xs text-muted-foreground">{!compact && packet?.body.scope ? `Scope: ${packet.body.scope.split(";")[0].trim()} · ` : ""}Frozen briefing, not a live price feed. Journal holdings are not broker-verified.</p>}
  </>;
  const longSummary = (body?.summary?.length ?? 0) > 360;
  const focus = body?.summary && <section aria-label="Today’s focus" className="space-y-2">
    <h2 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Today’s focus</h2>
    <p data-testid="brief-summary" className={`whitespace-pre-wrap leading-relaxed ${compact ? "text-sm" : "text-base"} ${longSummary && !fullSummary ? "line-clamp-4" : ""}`}>{body.summary}</p>
    {longSummary && <button type="button" aria-expanded={fullSummary} className={textButton} onClick={() => setFullSummary((v) => !v)}>{fullSummary ? "Show less" : "Read Jo’s full summary"}</button>}
    {!compact && sources(body.summary_evidence_ids)}
    {!compact && packet && !packet.redacted_at && !memories.length && <p className="text-xs text-muted-foreground">No saved beliefs or preferences were in this packet, so “why you” rests on positions, watchlist and market evidence. <a href="/morning/memories" className="text-primary hover:underline">Add a belief →</a></p>}
  </section>;

  if (compact) return <DashboardCard title="Morning briefing" action={<a href={`/morning?day=${day}`} className={dashboardLink}>Open briefing →</a>}>
    <div className="min-w-0 space-y-3 break-words" data-testid="morning-briefing">
      {error && <p role="alert" className="text-sm text-amber-300">{error}{data && " Showing the previously loaded record; current status is unknown."}</p>}
      {!data && !error && <p role="status" className="text-sm text-muted-foreground">Loading saved briefing…</p>}
      {status}
      {data && data.state !== "ready" && <p className="text-sm text-muted-foreground">{messages[data.state]}</p>}
      {focus}
      {body && <p className="text-xs text-muted-foreground">{body.items?.length ?? 0} priorities{gaps.length ? " · Evidence gaps disclosed in the brief" : ""} · Personal advice. Uses the account scope saved with this briefing.</p>}
    </div>
  </DashboardCard>;

  return <div className="min-w-0 space-y-6 break-words" data-testid="morning-briefing">
    <header className="space-y-2">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div><p className="text-xs text-muted-foreground">Morning with Jo</p><h1 className="text-xl font-semibold">{longDate(day)}</h1></div>
        <button type="button" onClick={() => setRefresh((r) => r + 1)} className={button}>Refresh</button>
      </div>
      {status}
    </header>
    {error && <p role="alert" className="text-sm text-amber-300">{error}{data && " Showing the previously loaded record; current status is unknown."}</p>}
    {!data && !error && <p role="status" className="text-sm text-muted-foreground">Loading saved briefing…</p>}
    {data && data.state !== "ready" && <p className="text-sm text-muted-foreground">{messages[data.state]}</p>}
    {focus}
    {body && <section aria-label="Priorities" className="space-y-3">
      {!body.items?.length && <p className="text-sm">No supported priority in this briefing. Review the coverage details before drawing conclusions.</p>}
      {body.items?.map((item, index) => <article key={index} className="space-y-3 rounded-lg border bg-card p-4">
        <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
          <h3 className="text-base font-semibold"><span className="mr-2 tabular-nums text-muted-foreground">{index + 1}</span>{item.symbol ?? "Portfolio review"}</h3>
          <div className="flex flex-wrap items-center gap-x-4">
            {item.symbol && <a href={`/charts?symbol=${encodeURIComponent(item.symbol)}`} className={dashboardLink}>Open {item.symbol} chart →</a>}
            <button type="button" aria-expanded={asking === index} className={textButton} onClick={() => ask(index)}>Ask Jo about {item.symbol ?? `priority ${index + 1}`}</button>
          </div>
        </div>
        <p className="whitespace-pre-wrap text-sm leading-relaxed">{item.what_matters}</p>
        <dl className="space-y-2 text-sm">
          {([["Why you", item.why_personal, ""], ["Before acting", item.watch_out, "text-amber-300"], ["What changed", item.what_changed, ""], ["Counterpoint", item.contrary_evidence, ""]] as const)
            .filter(([, value]) => value?.trim()).map(([label, value, tone]) => <div key={label} className="sm:grid sm:grid-cols-[7.5rem_minmax(0,1fr)] sm:gap-3">
              <dt className={`text-xs font-medium sm:pt-0.5 ${tone || "text-muted-foreground"}`}>{label}</dt><dd className="whitespace-pre-wrap leading-relaxed">{value}</dd>
            </div>)}
          {(() => {
            const used = usedMemories(item);
            return used.length > 0 && <div className="sm:grid sm:grid-cols-[7.5rem_minmax(0,1fr)] sm:gap-3">
              <dt className="text-xs font-medium text-muted-foreground sm:pt-0.5">Your saved view</dt>
              <dd className="space-y-1">{used.map((m) => <p key={m.id}><a href={`#memory-${m.id}`} onClick={openDetails("brief-memories")} className="hover:underline">“{m.body.original_text}”</a><span className="block text-xs text-muted-foreground">{memoryMeta(m)}</span></p>)}</dd>
            </div>;
          })()}
        </dl>
        {sources(item.evidence_ids)}
        {asking === index && joPanel(item, index)}
      </article>)}
      <div className="space-y-3">
        <button type="button" aria-expanded={asking === "brief"} className={textButton} onClick={() => ask("brief")}>Ask Jo about this brief</button>
        {asking === "brief" && joPanel(null, 0)}
      </div>
    </section>}
    {body && <section aria-label="Briefing feedback"><p className="mb-2 text-sm">Was this brief useful?</p><div className="flex flex-wrap gap-2" role="group" aria-label="Briefing feedback">
      {([["useful", "Useful"], ["meh", "Meh"], ["missed", "Missed something"]] as const).map(([value, label]) => <button key={value} type="button" disabled={saving} aria-pressed={data?.feedback.rating === value} className={`${button} ${data?.feedback.rating === value ? "bg-secondary" : ""}`} onClick={() => void rate(value)}>{label}</button>)}
    </div>{feedbackError && <p role="alert" className="mt-2 text-sm text-amber-300">{feedbackError}</p>}</section>}
    {data && <div className="space-y-2">
      <a href="/morning/memories" className={textButton}>Saved memories and Jo’s proposals →</a>
      {!!gaps.length && <details className="rounded-md border border-amber-500/30 px-3"><summary className="min-h-11 cursor-pointer py-3 text-sm font-medium">Limited coverage · {gaps.length} {gaps.length === 1 ? "gap" : "gaps"} disclosed</summary><p className="mb-3 text-xs text-muted-foreground">This brief has missing or unverified evidence. Check these details before relying on it.</p><ul className="list-disc space-y-2 pb-3 pl-4 text-sm text-muted-foreground">{gaps.map((gap) => <li key={gap}>{gap}</li>)}</ul></details>}
      {packet && !packet.redacted_at && <details id="brief-evidence" className="rounded-md border px-3">
        <summary className="min-h-11 cursor-pointer py-3 text-sm font-medium">Evidence and personal context ({packet.body.evidence?.length ?? 0})</summary>
        <p className="mb-3 text-xs text-muted-foreground">{packet.body.scope}{packet.body.as_of && ` · Frozen ${time(packet.body.as_of)}`}</p>
        <ol className="space-y-4 pb-3">{packet.body.evidence?.map((e) => <li id={`evidence-${e.id}`} key={e.id} className="scroll-mt-20 border-t pt-3 text-sm">
          <p className="font-medium">{sourceLabel(e)} · {kindLabel(e.kind)}</p>
          <p className="mt-1 whitespace-pre-wrap">{e.text}</p>
          <p className="mt-2 text-xs text-muted-foreground">{e.source} · {e.observed_at ? `Observed ${time(e.observed_at)}` : "Observation time unavailable"} · Retrieved {time(e.retrieved_at)} · ID <code>{e.id}</code>{(() => { const m = memoryFor(e); return m && <> · <a href={`#memory-${m.id}`} onClick={openDetails("brief-memories")} className="underline underline-offset-2">memory revision {m.revision}</a></>; })()}</p>
        </li>)}</ol>
      </details>}
      {!!memories.length && <details id="brief-memories" className="rounded-md border px-3">
        <summary className="min-h-11 cursor-pointer py-3 text-sm font-medium">Your saved memories in this packet ({memories.length})</summary>
        <p className="mb-3 text-xs text-muted-foreground">The exact revisions Jo was given. Later corrections or retirements do not change this brief. <a href="/morning/memories" className="text-primary hover:underline">Review or correct saved memories →</a></p>
        <ol className="space-y-4 pb-3">{memories.map((m) => <li id={`memory-${m.id}`} key={m.id} className="scroll-mt-20 border-t pt-3 text-sm">
          {m.redacted_at ? <p className="text-muted-foreground">Removed memory · revision {m.revision}</p> : <>
            <p className="font-medium">{memoryMeta(m)}</p>
            <p className="mt-1 whitespace-pre-wrap">“{m.body.original_text}”</p>
            {m.body.interpretation && <p className="mt-1 whitespace-pre-wrap text-muted-foreground">Interpretation: {m.body.interpretation}</p>}
          </>}
          <p className="mt-2 text-xs text-muted-foreground">{m.body.source ? `Source ${m.body.source.replace(/_/g, " ")} · ` : ""}Revision ID <code>{m.id}</code> · Memory ID <code>{m.memory_id}</code></p>
        </li>)}</ol>
      </details>}
      {brief && <details className="rounded-md border px-3"><summary className="min-h-11 cursor-pointer py-3 text-sm">Briefing details</summary><div className="space-y-2 pb-3 text-xs text-muted-foreground">
        <p>Briefing: <code>{brief.id}</code></p><p>Packet: <code>{packet?.id ?? "unavailable"}</code></p>
        {brief.body.supersedes_id && <p>Corrects: <code>{brief.body.supersedes_id}</code></p>}
        <p>Personal advice, not an order or activated plan. Jo and Shadow share context; independence is unverified.</p>
      </div></details>}
    </div>}
  </div>;
}
