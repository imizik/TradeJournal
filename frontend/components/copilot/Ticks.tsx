"use client";

/** The desk's live-price pieces (``lib/deskTicks.ts``): a number that tints for a moment when it moves, and the quiet
 * "prices as of" line once a price is no longer live. */

import { useEffect, useRef, useState, type ReactNode } from "react";
import { cn } from "@/lib/utils";

const FLASH_MS = 600;

/** ``children`` with a faint green or red tint for ``FLASH_MS`` after ``value`` goes up or down; nothing else moves. */
export function Flash({ value, children, className }: { value: number | null | undefined; children: ReactNode; className?: string }) {
  const previous = useRef(value);
  const [way, setWay] = useState<0 | 1 | -1>(0);
  useEffect(() => {
    const was = previous.current;
    previous.current = value;
    if (value == null || was == null || value === was) return;
    setWay(value > was ? 1 : -1);
    const timer = setTimeout(() => setWay(0), FLASH_MS);
    return () => clearTimeout(timer);
  }, [value]);
  return (
    <span data-flash={way === 0 ? undefined : way > 0 ? "up" : "down"}
      className={cn("rounded-sm transition-colors duration-500", way > 0 && "bg-emerald-400/15", way < 0 && "bg-rose-400/15", className)}>
      {children}
    </span>
  );
}

const clock = (seconds: number) => new Date(seconds * 1000).toLocaleTimeString("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit", second: "2-digit" });

/** "prices 10:04:31": shown only while a price on screen is no longer live, with the time of its last good read. */
export function PricesAsOf({ at }: { at: number | null }) {
  if (at === null) return null;
  return <span role="status" data-testid="prices-as-of" className="text-[11px] tabular-nums text-muted-foreground">prices {clock(at)}</span>;
}
