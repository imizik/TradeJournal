"use client";

import { useEffect } from "react";
import { cn } from "@/lib/utils";
import { useWorkspace } from "@/lib/research/store";
import { LAYER_CLUSTER, MON_OPTIONS } from "@/lib/research/constants";
import type { LayerTextField } from "@/lib/research/types";
import {
  EditableTextarea,
  MonBadge,
  PositionDot,
  Select,
  TypeBadge,
} from "./primitives";

function Field({
  label,
  color,
  value,
  onCommit,
  full,
  minHeight,
}: {
  label: string;
  color?: string;
  value: string;
  onCommit: (v: string) => void;
  full?: boolean;
  minHeight?: number;
}) {
  return (
    <div
      className={cn(
        "rounded-md border border-border bg-card p-3",
        full && "md:col-span-2"
      )}
    >
      <div
        className={cn(
          "mb-1.5 font-mono text-[10px] uppercase tracking-wide",
          color ?? "text-muted-foreground"
        )}
      >
        {label}
      </div>
      <EditableTextarea value={value} onCommit={onCommit} minHeight={minHeight} />
    </div>
  );
}

export default function StackView({
  activeLayer,
  onOpenMoat,
  onOpenTicker,
}: {
  activeLayer: string;
  onOpenMoat: (cluster: string) => void;
  onOpenTicker: (ticker: string) => void;
}) {
  const { data, patchLayer, overlays } = useWorkspace();
  const l = data.layers[activeLayer];
  const num = data.order.indexOf(activeLayer) + 1;
  const cluster = LAYER_CLUSTER[activeLayer];

  const inLayer = Object.values(data.companies).filter(
    (c) => c.layer === activeLayer
  );
  const anchors = inLayer.filter((c) => c.cap === "mega" || c.cap === "large");
  const candidates = inLayer.filter(
    (c) => c.cap !== "mega" && c.cap !== "large"
  );

  useEffect(() => {
    overlays.ensureQuotes(inLayer.map((c) => c.ticker));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeLayer]);

  if (!l) return null;

  const set =
    (f: LayerTextField) => (v: string) =>
      patchLayer(activeLayer, { [f]: v } as Partial<import("@/lib/research/types").Layer>);

  const Chip = ({ ticker, type }: { ticker: string; type: import("@/lib/research/types").CoType }) => (
    <button
      type="button"
      onClick={() => onOpenTicker(ticker)}
      className="flex items-center gap-1.5 rounded-md border border-border bg-card px-2 py-1 hover:border-ring"
    >
      <span className="font-mono text-xs font-semibold text-foreground">{ticker}</span>
      <TypeBadge type={type} />
      <PositionDot open={overlays.openTickers.has(ticker)} />
    </button>
  );

  return (
    <div className="max-w-5xl p-5">
      <div className="mb-4 flex items-start gap-3">
        <div className="mt-1 shrink-0 rounded border border-border px-2 py-1 font-mono text-[11px] text-muted-foreground">
          {String(num).padStart(2, "0")}
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-xl font-semibold tracking-tight text-foreground">
            {l.name}
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <span className="font-mono text-[10px] tracking-wide text-muted-foreground">
              MONETIZES VIA
            </span>
            <Select
              value={l.mon}
              onChange={(v) => patchLayer(activeLayer, { mon: v })}
              options={MON_OPTIONS}
            />
            <MonBadge mon={l.mon} />
            {!l.whyMoney && (
              <span className="rounded border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 font-mono text-[9px] text-amber-300">
                SKELETON — NEEDS RESEARCH
              </span>
            )}
          </div>
        </div>
        {cluster && (
          <button
            type="button"
            onClick={() => onOpenMoat(cluster)}
            className="mt-1 shrink-0 rounded-md border border-border bg-card px-3 py-2 font-mono text-xs text-primary hover:border-ring"
          >
            ◧ Moat comparison →
          </button>
        )}
      </div>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <Field label="What this layer does" full value={l.what} onCommit={set("what")} minHeight={52} />
        <Field
          label="▲ Why it could make money"
          color="text-emerald-300"
          value={l.whyMoney}
          onCommit={set("whyMoney")}
          minHeight={72}
        />
        <Field
          label="▼ Why it could fail"
          color="text-red-300"
          value={l.whyFail}
          onCommit={set("whyFail")}
          minHeight={72}
        />
        <Field
          label="◆ Key bottleneck / demand driver"
          color="text-amber-300"
          full
          value={l.bottleneck}
          onCommit={set("bottleneck")}
        />
        <Field label="Metrics that matter" value={l.metrics} onCommit={set("metrics")} minHeight={90} />
        <Field label="Red flags" value={l.redFlags} onCommit={set("redFlags")} minHeight={90} />
      </div>

      <div className="mt-5">
        <div className="mb-2 font-mono text-[10px] uppercase tracking-wide text-muted-foreground">
          Anchors (mega / large) · {anchors.length}
        </div>
        <div className="flex flex-wrap gap-2">
          {anchors.length === 0 && (
            <span className="text-xs text-muted-foreground">— none —</span>
          )}
          {anchors.map((c) => (
            <Chip key={c.ticker} ticker={c.ticker} type={c.type} />
          ))}
        </div>
        <div className="mb-2 mt-4 font-mono text-[10px] uppercase tracking-wide text-muted-foreground">
          Candidates (mid / small / micro) · {candidates.length}
        </div>
        <div className="flex flex-wrap gap-2">
          {candidates.length === 0 && (
            <span className="text-xs text-muted-foreground">— none —</span>
          )}
          {candidates.map((c) => (
            <Chip key={c.ticker} ticker={c.ticker} type={c.type} />
          ))}
        </div>
      </div>
    </div>
  );
}
