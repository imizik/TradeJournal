"use client";

/**
 * Notes on the book (docs/copilot-lab.md § Notes on a trade): a small Note control on each position row and each fresh
 * fill line opens one text line in place (Enter saves, Esc cancels); saved notes show as short grey lines under the row
 * with their time, newest last. Saved with the trade (``lib/deskNotes.ts``), so the Journal, the day report and the
 * copilot's read of the ticker see the same words. Never a plan, never a change to a fill, a trade or its P&L.
 */

import { NotebookPen } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { NOTE_MAX, addDeskNote, getDeskNotes, type DeskNote, type DeskNotes, type NoteTarget } from "@/lib/deskNotes";
import { cn } from "@/lib/utils";

const ET = "America/New_York";
const SHOWN = 3; // the newest few under a row; the rest are one "N earlier" word away

/** "10:42" today, "11/12 10:42" on an earlier day (New York); outside 9:00-4:59 the clock keeps its AM/PM ("8:17 PM"). */
export function noteTime(at: number | null, now = Date.now() / 1000): string {
  if (at == null) return "";
  const day = (s: number) => new Date(s * 1000).toLocaleDateString("en-US", { timeZone: ET, month: "numeric", day: "numeric" });
  const full = new Date(at * 1000).toLocaleTimeString("en-US", { timeZone: ET, hour: "numeric", minute: "2-digit" });
  const hour = Number(new Date(at * 1000).toLocaleString("en-US", { timeZone: ET, hour: "numeric", hour12: false }));
  const clock = hour >= 9 && hour < 17 ? full.replace(/\s?[AP]M$/, "") : full;
  return day(at) === day(now) ? clock : `${day(at)} ${clock}`;
}

export type DeskNotesState = {
  data: DeskNotes;
  /** The one row or fill line whose text line is open (its id), or null. */
  open: string | null;
  setOpen(id: string | null): void;
  save(target: NoteTarget, text: string): Promise<void>;
};

/** The book's notes: one read when the set of trades and fill lines changes (no polling), and each save added in place. */
export function useDeskNotes(trades: string[], fills: string[]): DeskNotesState {
  const [data, setData] = useState<DeskNotes>({ trades: {}, fills: {} });
  const [open, setOpen] = useState<string | null>(null);
  const tradeKey = [...new Set(trades)].sort().join(",");
  const fillKeyList = [...new Set(fills)].sort().join("\n");
  useEffect(() => {
    if (!tradeKey && !fillKeyList) return;
    const controller = new AbortController();
    getDeskNotes(tradeKey ? tradeKey.split(",") : [], fillKeyList ? fillKeyList.split("\n") : [], controller.signal)
      .then(setData).catch(() => { /* notes are extra: the book reads without them */ });
    return () => controller.abort();
  }, [tradeKey, fillKeyList]);
  const save = useCallback(async (target: NoteTarget, text: string) => {
    const saved = await addDeskNote(target, text);
    setData(current => ({ ...current, trades: { ...current.trades, [saved.trade_id]: [...(current.trades[saved.trade_id] ?? []), saved.note] } }));
  }, []);
  return useMemo(() => ({ data, open, setOpen, save }), [data, open, save]);
}

/** The small Note control: a pen, beside the row's eye. Its name ("Note on this position") leaves out the ticker, which
 * the row's own button carries, so a search for the row by name finds the row alone. */
export function NoteButton({ notes, id, label, className }: { notes: DeskNotesState; id: string; label: string; className?: string }) {
  const open = notes.open === id;
  return (
    <button type="button" data-testid="desk-note-button" aria-label={`Note on ${label}`} aria-expanded={open}
      title="Note: why you're in, or why you left (saved with the trade)"
      onClick={() => notes.setOpen(open ? null : id)}
      className={cn("flex w-8 shrink-0 items-center justify-center text-muted-foreground/40 hover:bg-secondary hover:text-foreground",
        open && "text-foreground", className)}>
      <NotebookPen size={13} aria-hidden />
    </button>
  );
}

/** One text line: Enter saves, Esc (or Enter on nothing) closes. The desk's keys never fire while typing here. */
function NoteInput({ label, onSave, onClose }: { label: string; onSave(text: string): Promise<void>; onClose(): void }) {
  const [text, setText] = useState("");
  const [saving, setSaving] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);
  const lock = useRef(false);
  const key = async (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); onClose(); return; }
    if (event.key !== "Enter" || event.nativeEvent.isComposing) return;
    event.preventDefault();
    const words = text.trim();
    if (!words) { onClose(); return; }
    if (lock.current) return;
    lock.current = true; setSaving(true); setFailed(null);
    try { await onSave(words); onClose(); }
    catch (error) { setFailed(error instanceof Error ? error.message : "Not saved. Try again."); }
    finally { lock.current = false; setSaving(false); }
  };
  return (
    <span className="block">
      <input autoFocus type="text" data-testid="desk-note-input" aria-label={`Note on ${label}`} value={text} maxLength={NOTE_MAX}
        disabled={saving} onChange={event => setText(event.target.value)} onKeyDown={event => void key(event)}
        placeholder="Why you're in, or why you left · Enter saves, Esc cancels"
        className="h-8 w-full rounded border bg-background px-2 text-xs text-foreground placeholder:text-muted-foreground/70 disabled:opacity-60" />
      {failed && <span role="alert" className="mt-0.5 block text-[11px] text-rose-300">{failed}</span>}
    </span>
  );
}

/** A row's saved notes (grey, one line each, newest last) and its open text line. Nothing when there is neither. */
export function NoteLines({ notes, id, trade, target, label, className, as: Tag = "span", selected = false }: {
  notes: DeskNotesState; id: string; trade: string | null; target: NoteTarget | null; label: string; className?: string;
  /** ``li`` directly in the book's list; a ``span`` inside a line. */
  as?: "li" | "span";
  /** The picked book row's notes: a phone's ticker view keeps that row's lines (``data-selected``, CopilotLab.module.css). */
  selected?: boolean;
}) {
  const saved: DeskNote[] = (trade && notes.data.trades[trade]) || [];
  const open = notes.open === id && target !== null;
  if (!saved.length && !open) return null;
  const shown = saved.slice(-SHOWN);
  return (
    <Tag data-testid="desk-notes" data-selected={selected || undefined} className={cn("flex min-w-0 flex-col gap-0.5 text-[11px] text-muted-foreground", className)}>
      {saved.length > SHOWN && <span className="text-muted-foreground/70">{saved.length - SHOWN} earlier</span>}
      {shown.map(note => (
        <span key={note.id} data-testid="desk-note" title={note.text} className="flex min-w-0 gap-1.5">
          <span className="shrink-0 tabular-nums text-muted-foreground/70">{noteTime(note.at)}</span>
          <span className="min-w-0 truncate">{note.text}</span>
        </span>
      ))}
      {open && target && <NoteInput label={label} onSave={text => notes.save(target, text)} onClose={() => notes.setOpen(null)} />}
    </Tag>
  );
}
