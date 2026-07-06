"use client";

import { useEffect, useMemo } from "react";
import { useWorkspace } from "@/lib/research/store";
import { MonBadge, PositionDot, StarRating, StatusBadge, TypeBadge } from "./primitives";

export default function ConvictionView({
  onOpenTicker,
}: {
  onOpenTicker: (t: string) => void;
}) {
  const { data, patchCompany, overlays } = useWorkspace();

  const rows = useMemo(
    () =>
      Object.values(data.companies)
        .filter((c) => (c.stars ?? 0) >= 4 || (c.q ?? 0) >= 8)
        .sort((a, b) => (b.stars || 0) - (a.stars || 0) || (b.q || 0) - (a.q || 0)),
    [data.companies]
  );

  useEffect(() => {
    overlays.ensureQuotes(rows.map((r) => r.ticker));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows.length]);

  return (
    <div className="p-5">
      <div className="text-lg font-semibold text-foreground">Conviction View</div>
      <div className="mb-4 text-xs text-muted-foreground">
        Auto-surfaced: every name scored ★4–5 or business quality ≥ 8, across all layers.
      </div>

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        {rows.map((c) => {
          const price = overlays.quotes[c.ticker];
          return (
            <div key={c.ticker} className="rounded-md border border-border bg-card p-3">
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => onOpenTicker(c.ticker)}
                  className="flex items-center gap-1.5 font-mono text-sm font-semibold text-foreground hover:text-primary"
                >
                  <PositionDot open={overlays.openTickers.has(c.ticker)} />
                  {c.ticker}
                </button>
                <span className="truncate text-xs text-muted-foreground">{c.name}</span>
                <span className="ml-auto font-mono text-xs tabular-nums text-foreground/70">
                  {price == null ? "" : `$${price.toFixed(2)}`}
                </span>
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <StarRating value={c.stars} onChange={(n) => patchCompany(c.ticker, { stars: n })} size="text-sm" />
                <span className="font-mono text-[10px] text-muted-foreground">Q {c.q}</span>
                <span className="font-mono text-[10px] text-muted-foreground">AI {c.ai}</span>
                <MonBadge mon={c.mon} />
                <TypeBadge type={c.type} />
                <StatusBadge status={c.status} />
              </div>
              {c.thesis && (
                <div className="mt-2 line-clamp-3 text-xs leading-relaxed text-foreground/80">
                  {c.thesis}
                </div>
              )}
            </div>
          );
        })}
        {rows.length === 0 && (
          <div className="text-sm text-muted-foreground">
            Nothing meets the conviction bar yet. Raise stars or quality scores in the Watchlist.
          </div>
        )}
      </div>
    </div>
  );
}
