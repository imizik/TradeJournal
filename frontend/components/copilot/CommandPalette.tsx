"use client";

import { useEffect, useId, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { TONE, numeric } from "@/components/copilot/ThreadRail";
import type { InvestigationSummary } from "@/lib/copilot";
import { searchConversations, type DeskThread } from "@/lib/desk";
import { cn } from "@/lib/utils";

/** A palette command: one of the desk's existing paths (ask, fill, plan a trade), never a new one. */
export type PaletteCommand = { id: string; name: string; hint: string; key?: string; run(): void };

type Item = { kind: "thread"; row: DeskThread } | { kind: "talk"; talk: InvestigationSummary } | { kind: "command"; command: PaletteCommand };

/** How long typing rests before saved conversations are searched, and the shortest search. */
const SEARCH_MS = 200, SEARCH_MIN = 2;
const talkDay = (iso: string) => new Date(iso).toLocaleDateString("en-US", { timeZone: "America/New_York", month: "short", day: "numeric", year: "2-digit" });

/** A Mac says ⌘K, anything else Ctrl+K (either key works anywhere). */
export const isMac = () => typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.userAgent);

/** The palette's key as the hint shows it. Only the browser knows the platform, so the first render says ⌘K. */
export function useJumpKey() {
  return useSyncExternalStore(still, isMac, () => true) ? "⌘K" : "Ctrl K";
}
const still = () => () => undefined;

export const KBD = "rounded border border-border px-1 py-px font-mono text-[10px] leading-none text-muted-foreground";

const words = (item: Exclude<Item, { kind: "talk" }>) => (item.kind === "thread"
  ? [item.row.symbol, item.row.title, item.row.instrument, item.row.status.text, item.row.value?.text]
  : [item.command.name, item.command.hint]).filter(Boolean).join(" ").toLowerCase();

/**
 * The desk's jump palette (⌘K, or the desk bar's Jump to… button): a search box over the thread list's rows in list order,
 * every saved conversation (by title, symbol or conclusion, from the server, so closed and old ones stay reachable) and
 * the desk's commands. Type to filter, arrows and Enter to choose, Escape or a click outside to close. A native modal
 * dialog, so it sits over the page wherever the desk is scrolled and keeps focus inside while open. Choosing only hands
 * the choice back; nothing here sends a turn of its own.
 */
export default function CommandPalette({ open, onClose, threads, commands, onThread, onConversation }: {
  open: boolean; onClose(): void; threads: DeskThread[]; commands: PaletteCommand[]; onThread(row: DeskThread): void; onConversation(id: string): void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const id = useId();

  useEffect(() => {
    const node = dialog.current;
    if (!node) return;
    if (open && !node.open) node.showModal();
    else if (!open && node.open) node.close();
  }, [open]);

  const asked = query.trim().length >= SEARCH_MIN ? query.trim() : "";
  const [found, setFound] = useState<{ asked: string; talks: InvestigationSummary[]; failed: boolean } | null>(null);
  useEffect(() => {
    if (!asked) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      searchConversations(asked, controller.signal).then(talks => setFound({ asked, talks, failed: false })).catch(() => {
        if (!controller.signal.aborted) setFound({ asked, talks: [], failed: true });
      });
    }, SEARCH_MS);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [asked]);
  const answer = asked && found?.asked === asked ? found : null;
  const searching = !!asked && !answer;

  const items = useMemo<Item[]>(() => {
    const terms = query.toLowerCase().split(/\s+/).filter(Boolean);
    const matches = (item: Exclude<Item, { kind: "talk" }>) => { const text = words(item); return terms.every(t => text.includes(t)); };
    const listed = new Set(threads.map(row => row.investigationId));
    return [
      ...threads.map(row => ({ kind: "thread" as const, row })).filter(matches),
      ...(answer?.talks ?? []).filter(talk => !listed.has(talk.id)).map(talk => ({ kind: "talk" as const, talk })),
      ...commands.map(command => ({ kind: "command" as const, command })).filter(matches),
    ];
  }, [query, threads, commands, answer]);
  const current = Math.min(active, Math.max(0, items.length - 1));

  useEffect(() => { document.getElementById(`${id}-${current}`)?.scrollIntoView({ block: "nearest" }); }, [current, id]);

  // The search clears on the way out, so a reopened palette is empty before its first keystroke: clearing it on open
  // raced the owner's (or a test's) typing, whose first key could land on the old text.
  const shut = () => { setQuery(""); setActive(0); onClose(); };

  const choose = (item: Item | undefined) => {
    if (!item) return;
    dialog.current?.close(); // now, so the dialog hands focus back before a command (a fill) takes it
    shut();
    if (item.kind === "thread") onThread(item.row);
    else if (item.kind === "talk") onConversation(item.talk.id);
    else item.command.run();
  };

  const option = (item: Item, index: number) => {
    const selected = index === current;
    const base = cn("flex min-h-11 w-full cursor-pointer items-center gap-2.5 rounded-md px-2.5 py-1.5 text-left text-sm sm:min-h-0", selected && "bg-secondary");
    if (item.kind === "command") return (
      <li key={item.command.id} id={`${id}-${index}`} role="option" aria-selected={selected} className={base}
        onMouseMove={() => setActive(index)} onClick={() => choose(item)}>
        <span className="shrink-0 font-medium text-foreground">{item.command.name}</span>
        <span className="min-w-0 truncate text-xs text-muted-foreground">{item.command.hint}</span>
        {item.command.key && <kbd className={cn(KBD, "ml-auto shrink-0")}>{item.command.key}</kbd>}
      </li>
    );
    if (item.kind === "talk") return (
      <li key={item.talk.id} id={`${id}-${index}`} role="option" aria-selected={selected} className={base}
        onMouseMove={() => setActive(index)} onClick={() => choose(item)}>
        {item.talk.symbol && <span className="shrink-0 font-semibold text-foreground">{item.talk.symbol}</span>}
        <span className="min-w-0 truncate text-xs text-foreground" title={item.talk.title}>{item.talk.title}</span>
        {item.talk.status === "closed" && <span className="shrink-0 rounded border px-1 text-[10px] leading-4 text-muted-foreground">Closed</span>}
        <span className="ml-auto shrink-0 text-xs tabular-nums text-muted-foreground">{talkDay(item.talk.updated_at)}</span>
      </li>
    );
    const row = item.row;
    return (
      <li key={row.key} id={`${id}-${index}`} role="option" aria-selected={selected} className={base}
        onMouseMove={() => setActive(index)} onClick={() => choose(item)}>
        <span className="shrink-0 font-semibold text-foreground">{row.symbol ?? row.title}</span>
        {row.symbol && (row.instrument ?? row.title) && <span className="shrink-0 text-xs text-muted-foreground">{row.instrument ?? row.title}</span>}
        <span className={cn("min-w-0 truncate text-xs", TONE[row.status.tone] === "text-foreground" ? "text-muted-foreground" : TONE[row.status.tone])}>{row.status.text}</span>
        {row.value && <span className={cn("ml-auto shrink-0 text-xs", TONE[row.value.tone], numeric(row.value.text) && "tabular-nums")}>{row.value.text}</span>}
      </li>
    );
  };

  const threadCount = items.filter(i => i.kind === "thread").length;
  const talkEnd = threadCount + items.filter(i => i.kind === "talk").length;
  const heading = (text: string) => <li role="presentation" className="px-2.5 pb-1 pt-2 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{text}</li>;
  return (
    // A click on the dialog itself is a click on its backdrop: the panel inside fills the box.
    <dialog ref={dialog} aria-label="Jump to" onClose={shut} onClick={event => { if (event.target === dialog.current) shut(); }}
      className="mx-auto mb-auto mt-[12vh] w-[min(560px,calc(100%-32px))] max-w-none overflow-hidden rounded-xl border bg-card p-0 text-foreground shadow-2xl backdrop:bg-background/70">
      <div>
        <input autoFocus value={query} placeholder="Jump to a symbol, plan, conversation or command…" aria-label="Jump to"
          role="combobox" aria-expanded="true" aria-controls={`${id}-list`} aria-activedescendant={items.length ? `${id}-${current}` : undefined}
          onChange={event => { setQuery(event.target.value); setActive(0); }}
          onKeyDown={event => {
            if (event.key === "ArrowDown" || event.key === "ArrowUp") {
              event.preventDefault();
              if (items.length) setActive((current + (event.key === "ArrowDown" ? 1 : items.length - 1)) % items.length);
            } else if (event.key === "Enter" && !event.nativeEvent.isComposing) {
              event.preventDefault();
              choose(items[current]);
            }
          }}
          className="h-12 w-full border-0 border-b bg-transparent px-4 text-base outline-none placeholder:text-muted-foreground sm:text-[15px]" />
        <ul id={`${id}-list`} role="listbox" aria-label="Threads and commands" className="max-h-[min(60vh,420px)] overflow-y-auto p-1.5">
          {!items.length && !searching && !answer?.failed && <li className="px-2.5 py-3 text-sm text-muted-foreground">Nothing matches.</li>}
          {threadCount > 0 && heading("Threads")}
          {items.slice(0, threadCount).map(option)}
          {talkEnd > threadCount && heading("Conversations")}
          {items.slice(threadCount, talkEnd).map((item, i) => option(item, threadCount + i))}
          {searching && <li role="status" className="px-2.5 py-2 text-xs text-muted-foreground">Searching saved conversations…</li>}
          {answer?.failed && <li role="status" className="px-2.5 py-2 text-xs text-muted-foreground">Saved conversations could not be searched.</li>}
          {items.length > talkEnd && heading("Commands")}
          {items.slice(talkEnd).map((item, i) => option(item, talkEnd + i))}
        </ul>
      </div>
    </dialog>
  );
}
