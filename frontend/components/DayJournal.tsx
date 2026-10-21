"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useAppAccess } from "@/components/AccessProvider";
import { api, type DayJournal as DayJournalData, type DayJournalEntry, type DayJournalWrite, type DayTradePlan } from "@/lib/api";
import { DAY_JOURNAL_KINDS, chartPathLink, dateET, kindLabel, planText, readDraft, storeDraft, timestampET, type SavedDraft } from "@/lib/dayJournal";

const uid = () => typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
const newWrite = (kind: DayJournalEntry["kind"]): DayJournalWrite => ({ operation_id: uid(), kind, text: "", symbol: null, not_traded: false });

export default function DayJournal({ day, review = false, initialData, onEntrySaved }: { day: string; review?: boolean; initialData?: DayJournalData | null; onEntrySaved?: () => void }) {
  const { owner } = useAppAccess();
  const [journal, setJournal] = useState<DayJournalData | null>(initialData ?? null);
  const [loading, setLoading] = useState(!initialData);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [draft, setDraft] = useState<SavedDraft | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const [storageWarning, setStorageWarning] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const saveLock = useRef(false);

  const load = useCallback(async () => {
    setLoading(true); setLoadError(null);
    try { setJournal(await api.dayJournal(day)); }
    catch { setLoadError("Please try again."); }
    finally { setLoading(false); }
  }, [day]);

  useEffect(() => {
    // Drafts live in the browser only, so read them after the client hydrates.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setDraft(readDraft(day));
    setSaveError(null); setSaveMessage(null);
    if (!initialData) void load();
  }, [day, initialData, load, refresh]);

  const changeDraft = (next: SavedDraft | null) => {
    setStorageWarning(!storeDraft(day, next));
    setDraft(next);
  };

  const startDraft = (kind: DayJournalEntry["kind"]) => {
    changeDraft({ write: newWrite(kind), attempted: false }); setSaveError(null); setSaveMessage(null);
  };
  const editDraft = (change: Partial<DayJournalWrite>) => {
    if (draft && !draft.attempted) changeDraft({ ...draft, write: { ...draft.write, ...change } });
  };
  const save = async () => {
    if (!draft || saveLock.current || !draft.write.text.trim()) return;
    const immutable = { ...draft, attempted: true, write: { ...draft.write, text: draft.write.text.trim() } };
    saveLock.current = true; changeDraft(immutable); setSaving(true); setSaveError(null); setSaveMessage(null);
    try {
      const entry = await api.addDayJournalEntry(day, immutable.write);
      setJournal((current) => current ? { ...current, entries: [...current.entries.filter((item) => item.id !== entry.id), entry].sort((a, b) => a.created_at.localeCompare(b.created_at)) } : current);
      const cleared = storeDraft(day, null);
      setDraft(null); setStorageWarning(!cleared); setSaveMessage("Saved to your day journal."); onEntrySaved?.();
    } catch {
      setSaveError("Could not confirm this save. Your draft remains here. Retry the same save; if it already went through, it will not create a duplicate.");
    } finally { saveLock.current = false; setSaving(false); }
  };

  const entries = useMemo(() => journal?.entries ?? [], [journal]);
  const plans = journal?.trade_plans;
  const hasPlans = !!plans && (Object.values(plans.by_trade ?? {}).some((items) => items.length) || !!plans.not_traded?.length);
  const planCard = (plan: DayTradePlan, key: string, notTraded: boolean) => <li key={key} className="rounded border bg-background/30 p-3">
    <div className="flex flex-wrap items-center gap-2 text-xs"><span className="rounded bg-sky-900/40 px-2 py-1 text-sky-200">Trade plan</span>{plan.underlying && <a href={chartPathLink(plan.underlying, day)} className="text-primary underline">{plan.underlying} chart for {day}</a>}{plan.side && <span>{plan.side}</span>}{notTraded && <span className="rounded bg-amber-900/40 px-2 py-1 text-amber-200">Not taken</span>}<time className="text-muted-foreground" dateTime={plan.captured_at}>Saved {timestampET(plan.captured_at)}</time></div>
    {planText(plan) && <p className="mt-2 whitespace-pre-wrap text-sm">{planText(plan)}</p>}
    {!!plan.later_notes?.length && <ol className="mt-3 space-y-2 border-l border-border pl-3">{plan.later_notes.map((note, index) => <li key={`${note.created_at}-${index}`}><p className="text-xs text-muted-foreground">{note.kind ? `${followUpKind(note.kind)} · ` : ""}{timestampET(note.created_at)}</p><p className="mt-1 whitespace-pre-wrap text-sm">{note.text}</p></li>)}</ol>}
  </li>;
  const title = review ? "Your thoughts that day" : "Your plan & thoughts";
  return <section className="rounded-lg border bg-card p-5" aria-label={title} data-testid="day-journal">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">{title}</h2>
        <p className="mt-1 text-sm text-muted-foreground">Your original notes stay saved and separate from Jo’s briefing. Times show when each note was saved (ET). Symbol links open that day’s chart for path inspection; available historical bars vary.</p></div>
      <button type="button" aria-label="Refresh saved day journal" onClick={() => setRefresh((value) => value + 1)} className="min-h-11 rounded border px-3 text-sm hover:bg-secondary">Refresh</button>
    </div>

    {owner && <div className="mt-4 rounded-md border bg-background/40 p-4">
      {!draft ? <div className="flex flex-wrap gap-2">{DAY_JOURNAL_KINDS.map(([kind, label]) => <button key={kind} type="button" onClick={() => startDraft(kind)} className="min-h-11 rounded border px-3 text-sm hover:bg-secondary" data-testid={`day-journal-add-${kind}`}>{label}</button>)}</div> : <div className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2"><p className="text-sm font-medium">{kindLabel(draft.write.kind)} · saved under {day} ET</p>
          {!draft.attempted && <button type="button" onClick={() => changeDraft(null)} className="min-h-11 text-sm text-muted-foreground underline">Discard draft</button>}</div>
        <label className="block text-sm">Your words<textarea aria-label="Your words" value={draft.write.text} onChange={(event) => editDraft({ text: event.target.value })} disabled={draft.attempted || saving} rows={4} maxLength={5000} required className="mt-1 block w-full rounded-md border bg-background p-3 text-sm text-foreground disabled:opacity-80" placeholder="What do you expect, what would change your mind, or what did you notice?" data-testid="day-journal-text" /></label>
        <div className="flex flex-wrap items-end gap-3">
          <label className="text-sm">Symbol (optional)<input aria-label="Symbol (optional)" value={draft.write.symbol ?? ""} onChange={(event) => editDraft({ symbol: event.target.value.trim().toUpperCase() || null })} disabled={draft.attempted || saving} maxLength={12} className="mt-1 block min-h-11 w-32 rounded-md border bg-background px-3 text-sm" /></label>
          {draft.write.kind === "idea" && <label className="flex min-h-11 items-center gap-2 text-sm"><input type="checkbox" checked={draft.write.not_traded ?? false} onChange={(event) => editDraft({ not_traded: event.target.checked })} disabled={draft.attempted || saving} />Mark as not traded</label>}
          <button type="button" onClick={() => void save()} disabled={!draft.write.text.trim() || saving} className="min-h-11 rounded bg-foreground px-4 text-sm font-medium text-background disabled:opacity-50" data-testid="day-journal-save">{saving ? "Saving…" : draft.attempted ? "Retry same save" : "Save thought"}</button>
        </div>
        {draft.attempted && <p className="text-xs text-muted-foreground">This draft stays unchanged until its save is confirmed. Retrying will not create a duplicate.</p>}
      </div>}
      {saveError && <p role="alert" className="mt-3 text-sm text-red-300">{saveError}</p>}
      {saveMessage && <p role="status" className="mt-3 text-sm text-emerald-300">{saveMessage}</p>}
      {storageWarning && <p role="alert" className="mt-3 text-sm text-amber-200">This browser could not keep a local copy of your draft. It remains here while this page stays open; a reload may clear it.</p>}
    </div>}

    {loading ? <p role="status" className="mt-4 text-sm text-muted-foreground">Loading saved thoughts…</p>
      : loadError ? <div className="mt-4 rounded border border-amber-500/40 p-3 text-sm"><p role="alert" className="text-amber-200">Saved thoughts could not be loaded: {loadError}</p><button type="button" onClick={() => void load()} className="mt-2 min-h-11 text-primary underline">Try again</button></div>
      : entries.length === 0 ? <p className="mt-4 text-sm text-muted-foreground">No thoughts saved for {day} yet.</p>
      : <ol className="mt-4 space-y-3" aria-label="Your saved thought timeline">{entries.map((entry) => <li key={entry.id} id={`thought-${entry.id}`} className="rounded border bg-background/30 p-3" data-testid="day-journal-entry">
        <div className="flex flex-wrap items-center gap-2 text-xs"><span className="rounded bg-blue-900/40 px-2 py-1 font-semibold text-blue-200">You</span><span className="font-medium text-foreground">{kindLabel(entry.kind)}</span>{entry.symbol && <a href={chartPathLink(entry.symbol, entry.day)} className="text-primary underline">{entry.symbol} chart for {entry.day}</a>}{entry.not_traded && <span className="rounded bg-amber-900/40 px-2 py-1 text-amber-200">Not traded</span>}<time className="text-muted-foreground" dateTime={entry.created_at}>{timestampET(entry.created_at)}</time></div>
        {(entry.day !== day || dateET(entry.created_at) !== day) && <p className="mt-1 text-xs text-amber-200">Saved under {entry.day} ET at {timestampET(entry.created_at)}{dateET(entry.created_at) !== entry.day ? ` (recorded on ${dateET(entry.created_at)} ET)` : ""}. Shown while reviewing {day} ET; original date and time are unchanged.</p>}
        <p className="mt-2 whitespace-pre-wrap text-sm text-foreground/90">{entry.text}</p>
      </li>)}</ol>}
    {!loading && !loadError && hasPlans && <div className="mt-5 border-t pt-4" aria-label="Saved trade plans and ideas">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Saved trade plans &amp; ideas</h3>
      <p className="mt-1 text-xs text-muted-foreground">Per-trade plans stay separate from these notes. Original capture and later note times are shown in ET.</p>
      {Object.entries(plans?.by_trade ?? {}).map(([tradeId, tradePlans]) => <div key={tradeId} className="mt-3"><p className="mb-2 text-xs text-muted-foreground">Trade <a className="text-primary underline" href={`/trades/${encodeURIComponent(tradeId)}`}>{tradeId}</a></p><ol className="space-y-2">{tradePlans.map((plan, index) => planCard(plan, `${tradeId}-${index}`, !!plan.marked_not_taken))}</ol></div>)}
      {!!plans?.not_traded?.length && <div className="mt-3"><p className="mb-2 text-xs text-muted-foreground">No linked trade</p><ol className="space-y-2">{plans.not_traded.map((plan, index) => planCard(plan, `unlinked-${index}`, !!plan.marked_not_taken))}</ol></div>}
    </div>}
  </section>;
}

function followUpKind(kind: string) {
  if (kind === "transcript_correction" || kind === "correction") return "Correction";
  if (kind === "review") return "Review note";
  return "Follow-up note";
}
