"use client";

// Small presentational + editable primitives shared across cockpit views.
// Text/number editors keep local state and commit on blur (or Enter) so typing
// never triggers a full-workspace re-render or a save per keystroke.

import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";
import {
  MON_BADGE,
  MON_LABEL,
  qualityColor,
  riskColor,
  STATUS_BADGE,
  STATUS_DOT,
  TYPE_BADGE,
  TYPE_LABEL,
} from "@/lib/research/constants";
import type { CoType, Mon, Status } from "@/lib/research/types";

export function MonBadge({ mon }: { mon: Mon }) {
  return (
    <span
      className={cn(
        "rounded px-1.5 py-0.5 text-[10px] font-semibold tracking-wide",
        MON_BADGE[mon]
      )}
    >
      {MON_LABEL[mon]}
    </span>
  );
}

export function TypeBadge({ type }: { type: CoType }) {
  return (
    <span
      className={cn(
        "rounded border px-1.5 py-0.5 text-[10px] font-semibold tracking-wide",
        TYPE_BADGE[type]
      )}
    >
      {TYPE_LABEL[type]}
    </span>
  );
}

export function StatusBadge({ status }: { status: Status }) {
  return (
    <span
      className={cn(
        "rounded px-1.5 py-0.5 text-[11px] font-medium",
        STATUS_BADGE[status]
      )}
    >
      {status}
    </span>
  );
}

export function PositionDot({ open }: { open: boolean }) {
  if (!open) return null;
  return (
    <span
      title="Open position in journal"
      className="inline-block h-2 w-2 shrink-0 rounded-full bg-emerald-400"
    />
  );
}

export function StatusDot({ status }: { status: Status }) {
  return (
    <span
      title={status}
      className={cn("inline-block h-2 w-2 shrink-0 rounded-full", STATUS_DOT[status])}
    />
  );
}

export function PriceTag({ price }: { price: number | null | undefined }) {
  return (
    <span className="font-mono text-xs tabular-nums text-foreground/80">
      {price == null ? "—" : `$${price.toFixed(2)}`}
    </span>
  );
}

export function StarRating({
  value,
  onChange,
  size = "text-base",
}: {
  value: number;
  onChange: (n: number) => void;
  size?: string;
}) {
  return (
    <div className="flex gap-0.5">
      {[1, 2, 3, 4, 5].map((n) => (
        <button
          key={n}
          type="button"
          onClick={() => onChange(value === n ? 0 : n)}
          className={cn(
            "leading-none",
            size,
            n <= value ? "text-amber-400" : "text-muted-foreground/30"
          )}
        >
          ★
        </button>
      ))}
    </div>
  );
}

export function Select<T extends string>({
  value,
  onChange,
  options,
  className,
}: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: string }[];
  className?: string;
}) {
  return (
    <select
      value={value}
      suppressHydrationWarning
      onChange={(e) => onChange(e.target.value as T)}
      className={cn(
        "rounded border border-border bg-card px-2 py-1 text-xs text-foreground/90 outline-none focus:border-ring",
        className
      )}
    >
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

export function EditableText({
  value,
  onCommit,
  placeholder,
  className,
  mono,
}: {
  value: string;
  onCommit: (v: string) => void;
  placeholder?: string;
  className?: string;
  mono?: boolean;
}) {
  const [local, setLocal] = useState(value);
  const focused = useRef(false);
  useEffect(() => {
    if (!focused.current) setLocal(value);
  }, [value]);

  return (
    <input
      value={local}
      placeholder={placeholder}
      onFocus={() => (focused.current = true)}
      onChange={(e) => setLocal(e.target.value)}
      onBlur={() => {
        focused.current = false;
        if (local !== value) onCommit(local);
      }}
      onKeyDown={(e) => {
        if (e.key === "Enter") (e.target as HTMLInputElement).blur();
      }}
      className={cn(
        "w-full rounded border border-border bg-background px-2 py-1 text-xs text-foreground/90 outline-none focus:border-ring",
        mono && "font-mono",
        className
      )}
    />
  );
}

export function EditableTextarea({
  value,
  onCommit,
  placeholder = "—",
  minHeight = 64,
  className,
}: {
  value: string;
  onCommit: (v: string) => void;
  placeholder?: string;
  minHeight?: number;
  className?: string;
}) {
  const [local, setLocal] = useState(value);
  const focused = useRef(false);
  useEffect(() => {
    if (!focused.current) setLocal(value);
  }, [value]);

  return (
    <textarea
      value={local}
      placeholder={placeholder}
      style={{ minHeight }}
      onFocus={() => (focused.current = true)}
      onChange={(e) => setLocal(e.target.value)}
      onBlur={() => {
        focused.current = false;
        if (local !== value) onCommit(local);
      }}
      className={cn(
        "w-full resize-y rounded border border-border bg-background px-2 py-1.5 text-[13px] leading-relaxed text-foreground/90 outline-none focus:border-ring",
        className
      )}
    />
  );
}

export function ScoreCell({
  value,
  kind,
  onCommit,
}: {
  value: number;
  kind: "q" | "r";
  onCommit: (n: number) => void;
}) {
  const [local, setLocal] = useState(String(value ?? 0));
  const focused = useRef(false);
  useEffect(() => {
    if (!focused.current) setLocal(String(value ?? 0));
  }, [value]);

  const commit = () => {
    focused.current = false;
    let n = parseInt(local, 10);
    if (Number.isNaN(n)) n = 0;
    n = Math.max(0, Math.min(10, n));
    setLocal(String(n));
    if (n !== value) onCommit(n);
  };

  return (
    <input
      value={local}
      inputMode="numeric"
      onFocus={() => (focused.current = true)}
      onChange={(e) => setLocal(e.target.value.replace(/[^0-9]/g, ""))}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") (e.target as HTMLInputElement).blur();
      }}
      className={cn(
        "w-9 rounded border border-transparent bg-transparent text-center font-mono text-xs tabular-nums outline-none hover:border-border focus:border-ring",
        kind === "q" ? qualityColor(value) : riskColor(value)
      )}
    />
  );
}
