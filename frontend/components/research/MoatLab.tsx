"use client";

import { cn } from "@/lib/utils";
import { useWorkspace } from "@/lib/research/store";
import { MOAT_CLUSTER_LABELS, TYPE_FULL, TYPE_BADGE } from "@/lib/research/constants";
import type { MoatField, MoatItem } from "@/lib/research/types";
import { EditableText, EditableTextarea, PositionDot } from "./primitives";

export default function MoatLab({
  moatCluster,
  onSetCluster,
  onOpenTicker,
}: {
  moatCluster: string;
  onSetCluster: (c: string) => void;
  onOpenTicker: (t: string) => void;
}) {
  const { data, patchMoat, overlays } = useWorkspace();
  const clusterIds = Object.keys(data.moat);
  const cl = data.moat[moatCluster] ?? data.moat[clusterIds[0]];

  const set = (ticker: string, f: MoatField) => (v: string) =>
    patchMoat(moatCluster, ticker, { [f]: v } as Partial<MoatItem>);

  return (
    <div className="p-5">
      <div className="text-lg font-semibold text-foreground">
        Moat &amp; Differentiation Lab
      </div>
      <div className="mb-3 text-xs text-muted-foreground">
        What actually differs between companies that get lumped together.
      </div>

      <div className="mb-4 flex flex-wrap gap-2">
        {clusterIds.map((id) => {
          const on = id === moatCluster;
          return (
            <button
              key={id}
              type="button"
              onClick={() => onSetCluster(id)}
              className={cn(
                "rounded-md border px-3 py-1.5 font-mono text-xs font-semibold",
                on
                  ? "border-primary bg-primary/10 text-primary"
                  : "border-border bg-card text-muted-foreground hover:text-foreground"
              )}
            >
              {MOAT_CLUSTER_LABELS[id] ?? id}
            </button>
          );
        })}
      </div>

      <div className="mb-3 font-mono text-[11px] tracking-wide text-primary">
        {cl?.title}
      </div>

      <div className="flex items-stretch gap-3 overflow-x-auto pb-3">
        {cl?.items.map((m) => (
          <div
            key={m.ticker}
            className={cn(
              "flex w-72 shrink-0 flex-col gap-2 rounded-md border border-border border-t-2 bg-card p-3",
            )}
          >
            <div className="flex items-center justify-between gap-2">
              <button
                type="button"
                onClick={() => onOpenTicker(m.ticker)}
                className="flex items-center gap-1.5 font-mono text-sm font-semibold text-foreground hover:text-primary"
              >
                <PositionDot open={overlays.openTickers.has(m.ticker)} />
                {m.ticker}
              </button>
              <span
                className={cn(
                  "rounded border px-1.5 py-0.5 font-mono text-[8px] font-semibold tracking-wide",
                  TYPE_BADGE[m.type]
                )}
              >
                {TYPE_FULL[m.type]}
              </span>
            </div>
            <MoatCell label="MAKES / SELLS" value={m.makes} onCommit={set(m.ticker, "makes")} />
            <MoatCell label="SPECIFIC MOAT" value={m.moat} onCommit={set(m.ticker, "moat")} />
            <MoatCell
              label="DIFFERENT BECAUSE"
              accent
              value={m.different}
              onCommit={set(m.ticker, "different")}
            />
            <div>
              <CellLabel>VALUE-CHAIN SEAT</CellLabel>
              <EditableText value={m.valueChain} onCommit={set(m.ticker, "valueChain")} mono />
            </div>
            <div className="flex gap-2">
              <div className="flex-1">
                <div className="mb-1 font-mono text-[8px] text-emerald-300">BULL</div>
                <EditableTextarea value={m.bull} onCommit={set(m.ticker, "bull")} minHeight={50} />
              </div>
              <div className="flex-1">
                <div className="mb-1 font-mono text-[8px] text-red-300">BEAR</div>
                <EditableTextarea value={m.bear} onCommit={set(m.ticker, "bear")} minHeight={50} />
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function CellLabel({ children, accent }: { children: React.ReactNode; accent?: boolean }) {
  return (
    <div
      className={cn(
        "mb-1 font-mono text-[8px] tracking-wide",
        accent ? "text-primary" : "text-muted-foreground"
      )}
    >
      {children}
    </div>
  );
}

function MoatCell({
  label,
  value,
  onCommit,
  accent,
}: {
  label: string;
  value: string;
  onCommit: (v: string) => void;
  accent?: boolean;
}) {
  return (
    <div>
      <CellLabel accent={accent}>{label}</CellLabel>
      <EditableTextarea value={value} onCommit={onCommit} minHeight={44} />
    </div>
  );
}
