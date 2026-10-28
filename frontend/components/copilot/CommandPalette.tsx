"use client";

import { useEffect, useId, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { TONE, numeric } from "@/components/copilot/ThreadRail";
import type { DeskThread } from "@/lib/desk";
import { cn } from "@/lib/utils";

/** A palette command: one of the desk's existing paths (ask, fill, plan a trade), never a new one. */
export type PaletteCommand = { id: string; name: string; hint: string; key?: string; run(): void };

type Item = { kind: "thread"; row: DeskThread } | { kind: "command"; command: PaletteCommand };

/** A Mac says ⌘K, anything else Ctrl+K (either key works anywhere). */
export const isMac = () => typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.userAgent);

/** The palette's key as the hint shows it. Only the browser knows the platform, so the first render says ⌘K. */
export function useJumpKey() {
  return useSyncExternalStore(still, isMac, () => true) ? "⌘K" : "Ctrl K";
}
const still = () => () => undefined;

export const KBD = "rounded border border-border px-1 py-px font-mono text-[10px] leading-none text-muted-foreground";

const words = (item: Item) => (item.kind === "thread"
  ? [item.row.symbol, item.row.title, item.row.instrument, item.row.status.text, item.row.value?.text]
  : [item.command.name, item.command.hint]).filter(Boolean).join(" ").toLowerCase();

/**
 * The desk's jump palette (⌘K, or the desk bar's Jump to… button): a search box over the thread list's rows in list order
 * and the desk's commands. Type to filter, arrows and Enter to choose, Escape or a click outside to close. A native modal
 * dialog, so it sits over the page wherever the desk is scrolled and keeps focus inside while open. Choosing only hands
 * the choice back; nothing here sends a turn of its own.
 */
export default function CommandPalette({ open, onClose, threads, commands, onThread }: {
  open: boolean; onClose(): void; threads: DeskThread[]; commands: PaletteCommand[]; onThread(row: DeskThread): void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const id = useId();

  useEffect(() => {
    const node = dialog.current;
    if (!node) return;
    if (open && !node.open) { setQuery(""); setActive(0); node.showModal(); }
    else if (!open && node.open) node.close();
  }, [open]);

  const items = useMemo<Item[]>(() => {
    const terms = query.toLowerCase().split(/\s+/).filter(Boolean);
    const all: Item[] = [...threads.map(row => ({ kind: "thread" as const, row })), ...commands.map(command => ({ kind: "command" as const, command }))];
    return all.filter(item => { const text = words(item); return terms.every(t => text.includes(t)); });
  }, [query, threads, commands]);
  const current = Math.min(active, Math.max(0, items.length - 1));

  useEffect(() => { document.getElementById(`${id}-${current}`)?.scrollIntoView({ block: "nearest" }); }, [current, id]);

  const choose = (item: Item | undefined) => {
    if (!item) return;
    dialog.current?.close(); // now, so the dialog hands focus back before a command (a fill) takes it
    onClose();
    if (item.kind === "thread") onThread(item.row);
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
    const row = item.row;
    return (
      <li key={row.key} id={`${id}-${index}`} role="option" aria-selected={selected} className={base}
        onMouseMove={() => setActive(index)} onClick={() => choose(item)}>
        <span className="shrink-0 font-semibold text-foreground">{row.symbol ?? row.title}</span>
        <span className={cn("min-w-0 truncate text-xs", TONE[row.status.tone] === "text-foreground" ? "text-muted-foreground" : TONE[row.status.tone])}>{row.status.text}</span>
        {row.value && <span className={cn("ml-auto shrink-0 text-xs", TONE[row.value.tone], numeric(row.value.text) && "tabular-nums")}>{row.value.text}</span>}
      </li>
    );
  };

  const threadCount = items.filter(i => i.kind === "thread").length;
  return (
    // A click on the dialog itself is a click on its backdrop: the panel inside fills the box.
    <dialog ref={dialog} aria-label="Jump to" onClose={onClose} onClick={event => { if (event.target === dialog.current) onClose(); }}
      className="mx-auto mb-auto mt-[12vh] w-[min(560px,calc(100%-32px))] max-w-none overflow-hidden rounded-xl border bg-card p-0 text-foreground shadow-2xl backdrop:bg-background/70">
      <div>
        <input autoFocus value={query} placeholder="Jump to a symbol, plan or command…" aria-label="Jump to"
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
          {!items.length && <li className="px-2.5 py-3 text-sm text-muted-foreground">Nothing matches.</li>}
          {threadCount > 0 && <li role="presentation" className="px-2.5 pb-1 pt-2 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Threads</li>}
          {items.slice(0, threadCount).map(option)}
          {items.length > threadCount && <li role="presentation" className="px-2.5 pb-1 pt-2 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Commands</li>}
          {items.slice(threadCount).map((item, i) => option(item, threadCount + i))}
        </ul>
      </div>
    </dialog>
  );
}
