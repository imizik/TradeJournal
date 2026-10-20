"use client";
import { useEffect, useRef, useState } from "react";
import { newClientId } from "@/lib/captures";
import { listMemories, MemorySaveError, saveMemory, type BriefMemory, type MemoryKind, type MemorySave, type MemoryStatus } from "@/lib/joMorning";

const zone = "America/New_York";
const time = (value: string) => new Date(value).toLocaleString("en-US", { timeZone: zone, month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) + " ET";
const kinds: [MemoryKind, string][] = [["thesis", "Thesis"], ["preference", "Preference"], ["lesson", "Lesson"], ["statement", "Statement"]];
const kindName = (kind?: MemoryKind) => kinds.find(([k]) => k === kind)?.[1] ?? "Memory";
const sourceName = { owner_statement: "Your statement", owner_import: "Imported by you", jo_proposal: "Proposed by Jo" } as const;
const button = "inline-flex min-h-11 items-center justify-center rounded-md border px-3 text-sm hover:bg-secondary disabled:opacity-50";
const field = "mt-1 block w-full rounded-md border bg-background px-3 text-sm text-foreground";
const symbolPattern = /^[A-Z]{1,6}(\.[A-Z])?$/;

type Draft = { kind: MemoryKind; symbol: string; original_text: string; interpretation: string };
type Lists = Record<MemoryStatus, BriefMemory[]>;
const emptyDraft: Draft = { kind: "thesis", symbol: "", original_text: "", interpretation: "" };
const draftOf = (m: BriefMemory): Draft => ({ kind: m.body.kind ?? "statement", symbol: m.symbol ?? "", original_text: m.body.original_text ?? "", interpretation: m.body.interpretation ?? "" });
/** The next revision of an existing memory: same identity and provenance, owner-confirmed. */
const revisionOf = (m: BriefMemory, status: MemoryStatus, draft: Draft = draftOf(m)): Omit<MemorySave, "operation_id"> => ({
  memory_id: m.memory_id, base_revision: m.revision, kind: draft.kind, symbol: draft.symbol.trim() || null,
  original_text: draft.original_text.trim(), interpretation: draft.interpretation.trim() || null,
  source: m.body.source ?? "owner_statement", source_reference: m.body.source_reference ?? null, status, owner_confirmed: true,
});
function draftProblem(d: Draft) {
  if (!d.original_text.trim()) return "Write the belief in your own words.";
  if (d.symbol.trim() && !symbolPattern.test(d.symbol.trim())) return "Symbol must be a ticker like MU or BRK.B.";
  return null;
}

function DraftFields({ draft, onChange, idPrefix }: { draft: Draft; onChange: (d: Draft) => void; idPrefix: string }) {
  return <div className="grid gap-3 sm:grid-cols-[10rem_8rem]">
    <label className="text-xs text-muted-foreground">Kind<select value={draft.kind} onChange={(e) => onChange({ ...draft, kind: e.target.value as MemoryKind })} className={`${field} min-h-11`}>
      {kinds.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
    <label className="text-xs text-muted-foreground">Symbol (optional)<input value={draft.symbol} onChange={(e) => onChange({ ...draft, symbol: e.target.value.toUpperCase() })} maxLength={8} className={`${field} min-h-11`} /></label>
    <label className="text-xs text-muted-foreground sm:col-span-2">Your wording<textarea id={`${idPrefix}-text`} value={draft.original_text} onChange={(e) => onChange({ ...draft, original_text: e.target.value })} rows={3} maxLength={4000} className={`${field} py-2`} /></label>
    <label className="text-xs text-muted-foreground sm:col-span-2">Interpretation (optional)<textarea value={draft.interpretation} onChange={(e) => onChange({ ...draft, interpretation: e.target.value })} rows={2} maxLength={4000} className={`${field} py-2`} /></label>
  </div>;
}

export default function MemoryReview() {
  const [lists, setLists] = useState<Lists | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [busy, setBusy] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [notice, setNotice] = useState<string | null>(null);
  const [editing, setEditing] = useState<{ key: string; revision: number; draft: Draft } | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [adding, setAdding] = useState<Draft | null>(null);
  // An uncertain save keeps its operation ID for an exact retry; any change to the request gets a new ID.
  const operations = useRef<Record<string, { id: string; request: string }>>({});

  useEffect(() => {
    const controller = new AbortController();
    Promise.all((["proposed", "active", "retired"] as const).map((status) => listMemories(status, controller.signal)))
      .then(([proposed, active, retired]) => { setLists({ proposed: proposed.items, active: active.items, retired: retired.items }); setLoadError(null); })
      .catch((reason) => { if (!controller.signal.aborted) setLoadError((reason as Error).message); });
    return () => controller.abort();
  }, [refresh]);

  async function submit(key: string, body: Omit<MemorySave, "operation_id">, done: string) {
    if (busy) return;
    const request = JSON.stringify(body);
    if (operations.current[key]?.request !== request) operations.current[key] = { id: `owner-memory-${newClientId()}`, request };
    const operation_id = operations.current[key].id;
    setBusy(key); setNotice(null); setErrors((e) => Object.fromEntries(Object.entries(e).filter(([k]) => k.split(":")[0] !== key.split(":")[0])));
    try {
      await saveMemory({ ...body, operation_id });
      delete operations.current[key];
      setEditing(null); setConfirming(null); setAdding(null); setNotice(done); setRefresh((r) => r + 1);
    } catch (reason) {
      // A definite refusal frees the ID; an unknown outcome keeps it for an exact retry.
      if (reason instanceof MemorySaveError && reason.status < 500) delete operations.current[key];
      // After an unknown outcome, reload so a save that did land is visible before anything is resent.
      else setRefresh((r) => r + 1);
      // Show the newer version instead of leaving a stale edit open on top of it.
      if (reason instanceof MemorySaveError && reason.status === 409) { setEditing(null); setConfirming(null); setRefresh((r) => r + 1); }
      setErrors((e) => ({ ...e, [key]: (reason as Error).message }));
    } finally { setBusy(null); }
  }

  const card = (m: BriefMemory, actions: React.ReactNode) => {
    const editKey = `${m.memory_id}:correct`;
    // An editor opened on an older revision closes once a newer one loads (another change, or an uncertain save that landed).
    const isEditing = editing?.key === editKey && editing.revision === m.revision;
    const keyError = Object.entries(errors).find(([key]) => key.startsWith(`${m.memory_id}:`))?.[1];
    return <li key={m.id} data-testid="memory-card" data-memory-id={m.memory_id} className="space-y-2 rounded-lg border bg-card p-4">
      <p className="text-xs text-muted-foreground">{kindName(m.body.kind)}{m.symbol ? ` · ${m.symbol}` : ""} · revision {m.revision} · {sourceName[m.body.source ?? "owner_statement"]} · saved {time(m.received_at)}</p>
      {isEditing ? <DraftFields draft={editing.draft} onChange={(draft) => setEditing({ key: editKey, revision: m.revision, draft })} idPrefix={m.id} /> : <>
        <p className="whitespace-pre-wrap text-sm leading-relaxed">“{m.body.original_text}”</p>
        {m.body.interpretation && <p className="whitespace-pre-wrap text-sm text-muted-foreground">Interpretation: {m.body.interpretation}</p>}
        {m.body.source_reference && <p className="whitespace-pre-wrap text-xs text-muted-foreground">Reference: {m.body.source_reference}</p>}
      </>}
      <div className="flex flex-wrap items-center gap-2">
        {isEditing ? <>
          <button type="button" className={button} disabled={!!busy || !!draftProblem(editing.draft)} onClick={() => void submit(editKey, revisionOf(m, "active", editing.draft), m.status === "proposed" ? "Saved your edited version as active." : "Correction saved as a new revision.")}>
            {m.status === "proposed" ? "Save and accept" : "Save correction"}</button>
          <button type="button" className={button} disabled={!!busy} onClick={() => setEditing(null)}>Cancel</button>
          {draftProblem(editing.draft) && <p className="text-xs text-amber-300">{draftProblem(editing.draft)}</p>}
        </> : actions}
      </div>
      {keyError && <p role="alert" className="text-sm text-amber-300">{keyError}</p>}
    </li>;
  };
  const editButton = (m: BriefMemory, label: string) => <button type="button" className={button} disabled={!!busy} onClick={() => { setEditing({ key: `${m.memory_id}:correct`, revision: m.revision, draft: draftOf(m) }); setConfirming(null); }}>{label}</button>;
  const retireButton = (m: BriefMemory, label: string, confirmLabel: string, done: string) => confirming === m.memory_id
    ? <><button type="button" className={`${button} border-amber-500/50 text-amber-300`} disabled={!!busy} onClick={() => void submit(`${m.memory_id}:retire`, revisionOf(m, "retired"), done)}>{confirmLabel}</button>
      <button type="button" className={button} disabled={!!busy} onClick={() => setConfirming(null)}>Keep</button></>
    : <button type="button" className={button} disabled={!!busy} onClick={() => setConfirming(m.memory_id)}>{label}</button>;

  return <div className="min-w-0 space-y-6 break-words" data-testid="memory-review">
    <header className="space-y-1">
      <p className="text-xs text-muted-foreground">Morning with Jo</p>
      <h1 className="text-xl font-semibold">Saved memories</h1>
      <p className="text-sm text-muted-foreground">What Jo may use about you. Active memories go into the next morning packet (the latest 30); past briefs keep the exact revision they used. Every change adds a revision; nothing here deletes history.</p>
    </header>
    {notice && <p role="status" className="text-sm text-emerald-400">{notice}</p>}
    {loadError && <p role="alert" className="text-sm text-amber-300">{loadError}{lists && " Showing the previously loaded list."} <button type="button" className="underline" onClick={() => setRefresh((r) => r + 1)}>Retry</button></p>}
    {!lists && !loadError && <p role="status" className="text-sm text-muted-foreground">Loading saved memories…</p>}
    {lists && <>
      <section aria-label="Jo’s proposals" className="space-y-3">
        <h2 className="text-sm font-semibold">Jo’s proposals to review ({lists.proposed.length})</h2>
        {!lists.proposed.length ? <p className="text-sm text-muted-foreground">No proposals waiting. Jo can only suggest memories; none is used until you accept it.</p>
          : <ul className="space-y-3">{lists.proposed.map((m) => card(m, <>
            <button type="button" className={button} disabled={!!busy} onClick={() => void submit(`${m.memory_id}:accept`, revisionOf(m, "active"), "Accepted. Jo can use it from the next morning packet.")}>Accept</button>
            {editButton(m, "Edit before accepting")}
            {retireButton(m, "Decline", "Confirm decline", "Declined. It stays in history as retired and is not used.")}
          </>))}</ul>}
      </section>
      <section aria-label="Active memories" className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm font-semibold">Active ({lists.active.length})</h2>
          {!adding && <button type="button" className={button} disabled={!!busy} onClick={() => { setAdding(emptyDraft); setEditing(null); setConfirming(null); }}>Add a belief</button>}
        </div>
        {adding && <div className="space-y-3 rounded-lg border bg-card p-4">
          <DraftFields draft={adding} onChange={setAdding} idPrefix="new" />
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" className={button} disabled={!!busy || !!draftProblem(adding)} onClick={() => void submit("new:add", { kind: adding.kind, symbol: adding.symbol.trim() || null,
              original_text: adding.original_text.trim(), interpretation: adding.interpretation.trim() || null, source: "owner_statement", status: "active", owner_confirmed: true }, "Saved. Jo can use it from the next morning packet.")}>Save belief</button>
            <button type="button" className={button} disabled={!!busy} onClick={() => setAdding(null)}>Cancel</button>
            {adding.original_text && draftProblem(adding) && <p className="text-xs text-amber-300">{draftProblem(adding)}</p>}
          </div>
          {errors["new:add"] && <p role="alert" className="text-sm text-amber-300">{errors["new:add"]}</p>}
        </div>}
        {!lists.active.length ? <p className="text-sm text-muted-foreground">No active memories. Morning briefs will say no saved beliefs were supplied.</p>
          : <ul className="space-y-3">{lists.active.map((m) => card(m, <>
            {editButton(m, "Correct")}
            {retireButton(m, "Retire", "Confirm retire", "Retired. Future packets leave it out; past briefs keep it.")}
          </>))}</ul>}
        {lists.active.length > 30 && <p className="text-xs text-amber-300">Only the latest 30 active memories go into a morning packet.</p>}
      </section>
      <details className="rounded-md border px-3">
        <summary className="min-h-11 cursor-pointer py-3 text-sm">Retired ({lists.retired.length})</summary>
        {!lists.retired.length ? <p className="pb-3 text-sm text-muted-foreground">Nothing retired.</p>
          : <ul className="space-y-3 pb-3">{lists.retired.map((m) => card(m, null))}</ul>}
      </details>
      {[lists.proposed, lists.active, lists.retired].some((l) => l.length >= 100) && <p className="text-xs text-muted-foreground">Lists show the latest 100 in each group.</p>}
    </>}
  </div>;
}
