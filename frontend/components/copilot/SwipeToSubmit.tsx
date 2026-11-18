"use client";

/**
 * Swipe-up confirmation for a paper order (the Paper button's and CloseRow's Fill and Place limit).
 *
 * On touch devices (coarse pointer) with motion enabled, renders a vertical violet paper track
 * where dragging the thumb past 80% submits once; otherwise the thumb springs back. On desktop
 * (fine pointer), when reduced motion is preferred, or before hydration completes, renders a
 * plain focusable button with the same label.
 */

import {
  useCallback,
  useRef,
  useState,
  useSyncExternalStore,
  type KeyboardEvent,
  type PointerEvent,
} from "react";
import { ArrowUp, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

const COARSE_QUERY = "(pointer: coarse)";
const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";
const SWIPE_THRESHOLD = 0.8;
const FALLBACK_TRAVEL_PX = 96;

export type SwipeToSubmitProps = {
  label: string;
  onSubmit(): void | Promise<void>;
  disabled?: boolean;
  busy?: boolean;
  className?: string;
  testId?: string;
};

function getSwipeSnapshot(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return false;
  return window.matchMedia(COARSE_QUERY).matches && !window.matchMedia(REDUCED_MOTION_QUERY).matches;
}

function getServerSnapshot(): boolean {
  return false;
}

function subscribePointer(listener: () => void): () => void {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return () => {};
  const coarse = window.matchMedia(COARSE_QUERY);
  const reduced = window.matchMedia(REDUCED_MOTION_QUERY);
  coarse.addEventListener("change", listener);
  reduced.addEventListener("change", listener);
  return () => {
    coarse.removeEventListener("change", listener);
    reduced.removeEventListener("change", listener);
  };
}

function measureMaxTravel(track: HTMLDivElement | null, thumb: HTMLDivElement | null): number {
  if (!track || !thumb) return FALLBACK_TRAVEL_PX;
  const style = window.getComputedStyle(track);
  const padTop = parseFloat(style.paddingTop) || 0;
  const padBottom = parseFloat(style.paddingBottom) || 0;
  const trackHeight = track.clientHeight || track.getBoundingClientRect().height;
  const thumbHeight = thumb.clientHeight || thumb.getBoundingClientRect().height;
  if (trackHeight <= 0 || thumbHeight <= 0) return FALLBACK_TRAVEL_PX;
  return Math.max(1, trackHeight - padTop - padBottom - thumbHeight);
}

export default function SwipeToSubmit({
  label,
  onSubmit,
  disabled = false,
  busy = false,
  className,
  testId,
}: SwipeToSubmitProps) {
  const swipeEnabled = useSyncExternalStore(subscribePointer, getSwipeSnapshot, getServerSnapshot);
  const [pending, setPending] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [drag, setDrag] = useState({ offset: 0, ratio: 0 });

  const trackRef = useRef<HTMLDivElement>(null);
  const thumbRef = useRef<HTMLDivElement>(null);
  const submittingRef = useRef(false);
  const dragRef = useRef<{ pointerId: number; startY: number; maxTravel: number } | null>(null);

  const isBusy = busy || pending;
  const blocked = disabled || isBusy;

  const triggerSubmit = useCallback(async () => {
    if (disabled || busy || submittingRef.current) return;
    submittingRef.current = true;
    setPending(true);
    try {
      await onSubmit();
    } finally {
      submittingRef.current = false;
      setPending(false);
      setDrag({ offset: 0, ratio: 0 });
    }
  }, [busy, disabled, onSubmit]);

  const handleKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (blocked) return;
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      void triggerSubmit();
    }
  };

  const handlePointerDown = (e: PointerEvent<HTMLDivElement>) => {
    if (blocked || !e.isPrimary) return;
    if (e.pointerType === "mouse" && e.button !== 0) return;

    const maxTravel = measureMaxTravel(trackRef.current, thumbRef.current);
    try {
      e.currentTarget.setPointerCapture(e.pointerId);
    } catch {
      // Ignore synthetic events where pointer capture is unavailable.
    }
    dragRef.current = { pointerId: e.pointerId, startY: e.clientY, maxTravel };
    setDragging(true);
    setDrag({ offset: 0, ratio: 0 });
  };

  const handlePointerMove = (e: PointerEvent<HTMLDivElement>) => {
    const active = dragRef.current;
    if (!active || active.pointerId !== e.pointerId) return;
    if (blocked) {
      dragRef.current = null;
      setDragging(false);
      setDrag({ offset: 0, ratio: 0 });
      return;
    }
    const offset = Math.min(active.maxTravel, Math.max(0, active.startY - e.clientY));
    setDrag({ offset, ratio: offset / active.maxTravel });
  };

  const releaseCapture = (target: HTMLDivElement, pointerId: number) => {
    try {
      if (target.hasPointerCapture?.(pointerId)) {
        target.releasePointerCapture(pointerId);
      }
    } catch {
      // Ignore synthetic events without active pointer capture.
    }
  };

  const handlePointerUp = (e: PointerEvent<HTMLDivElement>) => {
    const active = dragRef.current;
    if (!active || active.pointerId !== e.pointerId) return;
    dragRef.current = null;
    releaseCapture(e.currentTarget, e.pointerId);
    setDragging(false);

    if (blocked) {
      setDrag({ offset: 0, ratio: 0 });
      return;
    }

    const offset = Math.min(active.maxTravel, Math.max(0, active.startY - e.clientY));
    const ratio = offset / active.maxTravel;
    if (ratio >= SWIPE_THRESHOLD) {
      setDrag({ offset: active.maxTravel, ratio: 1 });
      void triggerSubmit();
    } else {
      setDrag({ offset: 0, ratio: 0 });
    }
  };

  const handlePointerCancel = (e: PointerEvent<HTMLDivElement>) => {
    const active = dragRef.current;
    if (!active || active.pointerId !== e.pointerId) return;
    dragRef.current = null;
    releaseCapture(e.currentTarget, e.pointerId);
    setDragging(false);
    setDrag({ offset: 0, ratio: 0 });
  };

  if (!swipeEnabled) {
    return (
      <button
        type="button"
        data-testid={testId}
        disabled={blocked}
        onClick={() => void triggerSubmit()}
        className={cn(
          "inline-flex min-h-11 w-full items-center justify-center gap-1.5 rounded-md border border-violet-400 bg-violet-400 px-3 text-xs font-semibold text-black transition-colors hover:bg-violet-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-300 disabled:cursor-not-allowed disabled:opacity-45 sm:min-h-8",
          className,
        )}
      >
        {isBusy && <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin" aria-hidden />}
        <span>{isBusy ? "Sending…" : label}</span>
      </button>
    );
  }

  const ready = drag.ratio >= SWIPE_THRESHOLD;

  return (
    <div
      ref={trackRef}
      className={cn(
        "relative flex h-36 w-full select-none flex-col justify-end overflow-hidden rounded-lg border border-dashed border-violet-400/60 bg-violet-950/20 p-1.5",
        blocked && "cursor-not-allowed opacity-45",
        className,
      )}
    >
      <div
        aria-hidden
        style={{ transform: `scaleY(${drag.ratio})` }}
        className={cn(
          "pointer-events-none absolute inset-0 origin-bottom bg-violet-400/20",
          dragging ? "transition-none" : "transition-transform duration-200 ease-out",
        )}
      />
      <span className="pointer-events-none relative z-10 flex flex-1 items-center justify-center px-3 text-center text-xs font-medium text-violet-200">
        {isBusy ? "Sending…" : label}
      </span>
      <div
        ref={thumbRef}
        role="button"
        data-testid={testId}
        tabIndex={blocked ? -1 : 0}
        aria-label={isBusy ? "Sending…" : label}
        aria-disabled={blocked || undefined}
        onKeyDown={handleKeyDown}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerCancel={handlePointerCancel}
        style={{ transform: `translate3d(0, -${drag.offset}px, 0)` }}
        className={cn(
          "relative z-10 flex min-h-11 w-full touch-none items-center justify-center gap-1.5 rounded-md border border-violet-400 px-3 text-xs font-semibold text-black focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-300",
          ready ? "bg-violet-300" : "bg-violet-400",
          blocked ? "cursor-not-allowed" : "cursor-grab active:cursor-grabbing",
          dragging ? "transition-none" : "transition-transform duration-200 ease-out",
        )}
      >
        {isBusy ? (
          <Loader2 className="h-4 w-4 shrink-0 animate-spin" aria-hidden />
        ) : (
          <ArrowUp className="h-4 w-4 shrink-0" aria-hidden />
        )}
        <span className="text-[11px] uppercase tracking-wide">
          {isBusy ? "Sending…" : ready ? "Release to send" : "Swipe up"}
        </span>
      </div>
    </div>
  );
}
