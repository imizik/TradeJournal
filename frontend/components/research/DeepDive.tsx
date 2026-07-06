"use client";

import { useEffect, useMemo } from "react";
import Link from "next/link";
import { cn } from "@/lib/utils";
import { useWorkspace } from "@/lib/research/store";
import { DEEP_FIELDS, STATUS_OPTIONS } from "@/lib/research/constants";
import { EditableTextarea, MonBadge, Select, StarRating, TypeBadge } from "./primitives";

const TONE_LABEL: Record<string, string> = {
  ai: "text-sky-300",
  risk: "text-amber-300",
  bull: "text-emerald-300",
  bear: "text-red-300",
  neutral: "text-muted-foreground",
};

export default function DeepDive({
  ticker,
  onSetTicker,
}: {
  ticker: string;
  onSetTicker: (t: string) => void;
}) {
  const { data, patchCompany, patchDeep, toggleShort, overlays } = useWorkspace();

  const companyOptions = useMemo(
    () =>
      Object.values(data.companies)
        .sort((a, b) => (a.ticker < b.ticker ? -1 : 1))
        .map((c) => ({ ticker: c.ticker, label: `${c.ticker} · ${c.name}` })),
    [data.companies]
  );

  const c = data.companies[ticker];
  const deep = data.deepDives[ticker] ?? {};

  useEffect(() => {
    overlays.ensureQuotes([ticker]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticker]);

  if (!c) return null;

  const price = overlays.quotes[ticker];
  const open = overlays.openTickers.has(ticker);
  const stat = overlays.byTicker[ticker];

  return (
    <div className="max-w-5xl p-5">
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <select
          value={ticker}
          suppressHydrationWarning
          onChange={(e) => onSetTicker(e.target.value)}
          className="rounded-md border border-border bg-card px-3 py-1.5 font-mono text-sm font-semibold text-foreground outline-none focus:border-ring"
        >
          {companyOptions.map((o) => (
            <option key={o.ticker} value={o.ticker}>
              {o.label}
            </option>
          ))}
        </select>
        <span className="text-base font-semibold text-foreground/90">{c.name}</span>
        <MonBadge mon={c.mon} />
        <TypeBadge type={c.type} />
        <StarRating value={c.stars} onChange={(n) => patchCompany(ticker, { stars: n })} />
        <Select
          value={c.status}
          onChange={(v) => patchCompany(ticker, { status: v })}
          options={STATUS_OPTIONS.map((x) => ({ value: x, label: x }))}
        />
        <button
          type="button"
          onClick={() => toggleShort(ticker)}
          className={cn(
            "rounded-md border px-3 py-1 font-mono text-xs",
            c.short
              ? "border-primary bg-primary/10 text-primary"
              : "border-border bg-card text-muted-foreground hover:text-foreground"
          )}
        >
          {c.short ? "✚ pinned" : "✛ pin to shortlist"}
        </button>
      </div>

      {/* Journal overlay */}
      <div className="mb-4 flex flex-wrap items-center gap-4 rounded-md border border-border bg-card px-4 py-2.5 text-xs">
        <span className="font-mono text-[10px] uppercase tracking-wide text-muted-foreground">
          Journal
        </span>
        <Metric label="Price" value={price == null ? "—" : `$${price.toFixed(2)}`} />
        <Metric
          label="Position"
          value={open ? "OPEN" : "—"}
          valueClass={open ? "text-emerald-400" : "text-muted-foreground"}
        />
        <Metric label="Closed trades" value={stat ? String(stat.count) : "0"} />
        <Metric
          label="Realized PnL"
          value={stat ? `${stat.total_pnl >= 0 ? "+" : ""}$${stat.total_pnl.toFixed(0)}` : "—"}
          valueClass={stat ? (stat.total_pnl >= 0 ? "text-emerald-400" : "text-red-400") : ""}
        />
        <Metric
          label="Win rate"
          value={stat ? `${(stat.win_rate * 100).toFixed(0)}%` : "—"}
        />
        <Link
          href={`/trades?ticker=${ticker}`}
          className="ml-auto font-mono text-[11px] text-muted-foreground hover:text-foreground"
        >
          view trades →
        </Link>
      </div>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        {DEEP_FIELDS.map((f) => (
          <div
            key={f.key}
            className={cn(
              "rounded-md border border-border bg-card p-3",
              f.full && "md:col-span-2"
            )}
          >
            <div
              className={cn(
                "mb-1.5 font-mono text-[10px] uppercase tracking-wide",
                TONE_LABEL[f.tone ?? "neutral"]
              )}
            >
              {f.label}
            </div>
            <EditableTextarea
              value={deep[f.key] ?? ""}
              onCommit={(v) =>
                patchDeep(ticker, { [f.key]: v } as Partial<import("@/lib/research/types").DeepDive>)
              }
            />
          </div>
        ))}
      </div>
    </div>
  );
}

function Metric({
  label,
  value,
  valueClass,
}: {
  label: string;
  value: string;
  valueClass?: string;
}) {
  return (
    <span className="flex items-center gap-1.5">
      <span className="text-muted-foreground">{label}</span>
      <span className={cn("font-mono tabular-nums text-foreground/90", valueClass)}>
        {value}
      </span>
    </span>
  );
}
