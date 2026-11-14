"use client";

/**
 * The Tape's open state and its chart-header button (docs/copilot-lab.md § The desk), apart from the panel itself
 * (``DeskTape``) so the desk loads the panel's code only when the Tape is opened.
 */

import { useCallback, useEffect, useState } from "react";
import { useAppAccess } from "@/components/AccessProvider";
import { DESK_CHANGED_EVENT, DESK_TAPE_KEY } from "@/lib/deskAction";
import { cn } from "@/lib/utils";

const OPEN_KEY = DESK_TAPE_KEY;

/** Whether the tape is open, remembered on this device (closed until the owner opens it). */
export function useTapeOpen(): [boolean, (next: boolean) => void] {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    try { setOpen(window.localStorage.getItem(OPEN_KEY) === "open"); } catch { /* closed */ } // eslint-disable-line react-hooks/set-state-in-effect -- the store is read after hydration
    // A copilot card that opens the Tape wrote it where this reads (``lib/deskAction.ts``): follow it.
    const follow = (event: Event) => { const tape = (event as CustomEvent<{ tape?: boolean }>).detail?.tape; if (tape !== undefined) setOpen(tape); };
    window.addEventListener(DESK_CHANGED_EVENT, follow);
    return () => window.removeEventListener(DESK_CHANGED_EVENT, follow);
  }, []);
  const pick = useCallback((next: boolean) => {
    setOpen(next);
    try { window.localStorage.setItem(OPEN_KEY, next ? "open" : "closed"); } catch { /* this view only */ }
  }, []);
  return [open, pick];
}

/** The chart header's Tape button; nothing for an assistant (the depth route is the owner's). */
export function TapeToggle({ open, onToggle }: { open: boolean; onToggle(next: boolean): void }) {
  const { owner } = useAppAccess();
  if (!owner) return null;
  return (
    <button type="button" aria-pressed={open} onClick={() => onToggle(!open)} data-testid="tape-toggle" title="Level 2 and time & sales"
      className={cn("min-h-11 rounded border px-2 text-xs sm:min-h-0 sm:py-0.5",
        open ? "border-foreground/60 text-foreground" : "border-transparent text-muted-foreground hover:text-foreground")}>
      Tape
    </button>
  );
}
