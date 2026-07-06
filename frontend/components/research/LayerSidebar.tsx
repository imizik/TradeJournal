"use client";

import { cn } from "@/lib/utils";
import { useWorkspace } from "@/lib/research/store";
import type { Mon } from "@/lib/research/types";

const MON_DOT: Record<Mon, string> = {
  scarcity: "bg-emerald-400",
  licensing: "bg-sky-400",
  capex: "bg-red-400",
};

export default function LayerSidebar({
  activeLayer,
  onSelect,
}: {
  activeLayer: string;
  onSelect: (id: string) => void;
}) {
  const { data } = useWorkspace();

  let prevGroup: string | null = null;

  return (
    <aside className="w-60 shrink-0 overflow-y-auto border-r border-border bg-card/40">
      <div className="px-3 pb-1 pt-3">
        <div className="font-mono text-[11px] font-semibold tracking-wide text-foreground/80">
          THE AI BUILDOUT STACK
        </div>
        <div className="mt-0.5 font-mono text-[10px] text-muted-foreground">
          revenue ▲ · raw inputs ▼
        </div>
      </div>
      {data.order.map((id, i) => {
        const l = data.layers[id];
        if (!l) return null;
        const groupLabel = l.group !== prevGroup ? l.group : null;
        prevGroup = l.group;
        const active = id === activeLayer;
        const isStub = !l.whyMoney;
        return (
          <div key={id}>
            {groupLabel && (
              <div className="px-3 pb-1 pt-3 font-mono text-[9px] uppercase tracking-wider text-muted-foreground/70">
                {groupLabel}
              </div>
            )}
            <button
              type="button"
              onClick={() => onSelect(id)}
              className={cn(
                "flex w-full items-center gap-2 px-3 py-1.5 text-left",
                active
                  ? "border-l-2 border-primary bg-secondary"
                  : "border-l-2 border-transparent hover:bg-secondary/50"
              )}
            >
              <span className="w-4 shrink-0 text-right font-mono text-[10px] text-muted-foreground/60">
                {String(i + 1).padStart(2, "0")}
              </span>
              <span className={cn("h-1.5 w-1.5 shrink-0 rounded-full", MON_DOT[l.mon])} />
              <span
                className={cn(
                  "min-w-0 flex-1 truncate text-xs",
                  active ? "font-semibold text-primary" : "text-foreground/80"
                )}
              >
                {l.name}
              </span>
              {isStub && (
                <span className="shrink-0 rounded border border-border px-1 py-px font-mono text-[7px] text-muted-foreground">
                  STUB
                </span>
              )}
            </button>
          </div>
        );
      })}
      <div className="h-5" />
    </aside>
  );
}
