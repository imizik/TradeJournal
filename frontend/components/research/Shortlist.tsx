"use client";

import { useEffect } from "react";
import Link from "next/link";
import { useWorkspace } from "@/lib/research/store";
import { STATUS_OPTIONS } from "@/lib/research/constants";
import { MonBadge, PositionDot, Select, StatusBadge, TypeBadge } from "./primitives";

export default function Shortlist({
  onOpenTicker,
}: {
  onOpenTicker: (t: string) => void;
}) {
  const { data, patchCompany, toggleShort, moveShort, overlays } = useWorkspace();
  const items = data.shortlistOrder
    .map((t) => data.companies[t])
    .filter((c): c is NonNullable<typeof c> => Boolean(c));

  useEffect(() => {
    overlays.ensureQuotes(items.map((c) => c.ticker));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data.shortlistOrder.join(",")]);

  // Pipeline counts across the whole universe.
  const counts: Record<string, number> = {};
  Object.values(data.companies).forEach((c) => {
    counts[c.status] = (counts[c.status] ?? 0) + 1;
  });

  return (
    <div className="p-5">
      <div className="text-lg font-semibold text-foreground">Top-10 Shortlist &amp; Pipeline</div>
      <div className="mb-3 text-xs text-muted-foreground">
        Pin names from anywhere (✛). {items.length}/10 pinned.
      </div>

      <div className="mb-4 flex flex-wrap gap-2">
        {STATUS_OPTIONS.map((s) => (
          <span key={s} className="rounded-md border border-border bg-card px-2.5 py-1 text-xs">
            <StatusBadge status={s} />
            <span className="ml-1.5 font-mono tabular-nums text-muted-foreground">{counts[s] ?? 0}</span>
          </span>
        ))}
      </div>

      <div className="space-y-2">
        {items.map((c, i) => {
          const price = overlays.quotes[c.ticker];
          return (
            <div
              key={c.ticker}
              className="flex items-center gap-3 rounded-md border border-border bg-card px-3 py-2"
            >
              <span className="w-5 text-center font-mono text-xs text-muted-foreground">{i + 1}</span>
              <div className="flex flex-col">
                <button
                  type="button"
                  onClick={() => moveShort(c.ticker, -1)}
                  disabled={i === 0}
                  className="text-[10px] leading-none text-muted-foreground hover:text-foreground disabled:opacity-20"
                >
                  ▲
                </button>
                <button
                  type="button"
                  onClick={() => moveShort(c.ticker, 1)}
                  disabled={i === items.length - 1}
                  className="text-[10px] leading-none text-muted-foreground hover:text-foreground disabled:opacity-20"
                >
                  ▼
                </button>
              </div>
              <button
                type="button"
                onClick={() => onOpenTicker(c.ticker)}
                className="flex w-20 items-center gap-1.5 font-mono text-sm font-semibold text-foreground hover:text-primary"
              >
                <PositionDot open={overlays.openTickers.has(c.ticker)} />
                {c.ticker}
              </button>
              <span className="w-16 font-mono text-xs tabular-nums text-foreground/70">
                {price == null ? "—" : `$${price.toFixed(2)}`}
              </span>
              <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">{c.name}</span>
              <MonBadge mon={c.mon} />
              <TypeBadge type={c.type} />
              <Select
                value={c.status}
                onChange={(v) => patchCompany(c.ticker, { status: v })}
                options={STATUS_OPTIONS.map((x) => ({ value: x, label: x }))}
              />
              <Link
                href={`/trades?ticker=${c.ticker}`}
                className="font-mono text-[11px] text-muted-foreground hover:text-foreground"
                title="View journal trades"
              >
                journal →
              </Link>
              <button
                type="button"
                onClick={() => toggleShort(c.ticker)}
                title="Unpin"
                className="text-primary hover:text-red-400"
              >
                ✚
              </button>
            </div>
          );
        })}
        {items.length === 0 && (
          <div className="text-sm text-muted-foreground">
            No names pinned yet. Click ✛ on any ticker in the Watchlist or Deep Dive.
          </div>
        )}
      </div>
    </div>
  );
}
