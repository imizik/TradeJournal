"use client";

import { useMemo, useState } from "react";
import { cn } from "@/lib/utils";
import { useWorkspace } from "@/lib/research/store";
import {
  SIGNAL_BADGE,
  STATUS_DOT,
  TABS,
} from "@/lib/research/constants";
import type { Status } from "@/lib/research/types";
import LayerSidebar from "./LayerSidebar";
import StackView from "./StackView";
import WatchlistTable from "./WatchlistTable";
import MoatLab from "./MoatLab";
import ConvictionView from "./ConvictionView";
import Shortlist from "./Shortlist";
import Checklist from "./Checklist";
import DeepDive from "./DeepDive";

const COUNTER_STATUSES: { status: Status; short: string }[] = [
  { status: "Researching", short: "RES" },
  { status: "Watchlist", short: "WL" },
  { status: "Position", short: "POS" },
  { status: "Passed", short: "PASS" },
];

export default function Cockpit() {
  const { data, saveState, patchSignpost, cycleSignpost } = useWorkspace();

  const firstLayer = data.order[0] ?? "";
  const [view, setView] = useState("stack");
  const [activeLayer, setActiveLayer] = useState(
    data.layers["gpus"] ? "gpus" : firstLayer
  );
  const clusterIds = Object.keys(data.moat);
  const [moatCluster, setMoatCluster] = useState(
    data.moat["semis"] ? "semis" : clusterIds[0] ?? ""
  );
  const [focusTicker, setFocusTicker] = useState(
    data.companies["AIP"] ? "AIP" : Object.keys(data.companies)[0] ?? ""
  );

  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    Object.values(data.companies).forEach((co) => {
      c[co.status] = (c[co.status] ?? 0) + 1;
    });
    return c;
  }, [data.companies]);

  const openTicker = (t: string) => {
    setFocusTicker(t);
    setView("deepdive");
  };
  const openMoat = (cluster: string) => {
    setMoatCluster(cluster);
    setView("moat");
  };
  const selectLayer = (id: string) => {
    setActiveLayer(id);
    setView("stack");
  };

  return (
    <div className="flex h-[calc(100vh-3rem)] flex-col overflow-hidden rounded-lg border border-border bg-background">
      {/* Top bar */}
      <div className="flex h-11 shrink-0 items-center gap-4 border-b border-border bg-card px-3">
        <div className="whitespace-nowrap font-mono text-[13px] font-semibold tracking-wide text-primary">
          ▰ AI BUILDOUT{" "}
          {/* eslint-disable-next-line react/jsx-no-comment-textnodes -- "//" here is a visual separator, not a comment */}
          <span className="text-muted-foreground/50">//</span> COCKPIT
        </div>
        <div className="flex gap-0.5 rounded-md border border-border p-0.5">
          {TABS.map((t) => (
            <button
              key={t.v}
              type="button"
              onClick={() => setView(t.v)}
              className={cn(
                "rounded px-2.5 py-1 font-mono text-[11px] font-semibold tracking-wide",
                view === t.v
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              {t.label}
            </button>
          ))}
        </div>
        <div className="ml-auto flex items-center gap-3">
          {COUNTER_STATUSES.map((c) => (
            <div
              key={c.status}
              title={c.status}
              className="flex items-center gap-1 font-mono text-[10px] text-muted-foreground"
            >
              <span className={cn("h-1.5 w-1.5 rounded-sm", STATUS_DOT[c.status])} />
              <span className="font-semibold text-foreground/80">{counts[c.status] ?? 0}</span>
              {c.short}
            </div>
          ))}
          <SaveIndicator state={saveState} />
        </div>
      </div>

      {/* Macro signposts */}
      <div className="flex shrink-0 items-stretch border-b border-border bg-card/40">
        <div className="flex items-center border-r border-border px-3 font-mono text-[9px] leading-tight tracking-wide text-muted-foreground">
          MACRO
          <br />
          SIGNPOSTS
        </div>
        {data.signposts.map((s) => (
          <div
            key={s.id}
            className="flex min-w-0 flex-1 flex-col justify-center gap-1 border-r border-border px-3 py-1.5"
          >
            <div className="flex items-center justify-between gap-2">
              <span className="truncate text-[10px] text-muted-foreground" title={s.label}>
                {s.label}
              </span>
              <button
                type="button"
                onClick={() => cycleSignpost(s.id)}
                className={cn(
                  "shrink-0 rounded px-1.5 py-0.5 font-mono text-[9px] font-bold",
                  SIGNAL_BADGE[s.level]
                )}
              >
                {s.level}
              </button>
            </div>
            <input
              defaultValue={s.notes}
              onBlur={(e) => {
                if (e.target.value !== s.notes) patchSignpost(s.id, { notes: e.target.value });
              }}
              placeholder="note…"
              className="w-full border-b border-border bg-transparent py-0.5 font-mono text-[10px] text-foreground/80 outline-none focus:border-ring"
            />
          </div>
        ))}
      </div>

      {/* Body */}
      <div className="flex min-h-0 flex-1">
        <LayerSidebar activeLayer={activeLayer} onSelect={selectLayer} />
        <main className="min-w-0 flex-1 overflow-auto">
          {view === "stack" && (
            <StackView activeLayer={activeLayer} onOpenMoat={openMoat} onOpenTicker={openTicker} />
          )}
          {view === "watchlist" && <WatchlistTable onOpenTicker={openTicker} />}
          {view === "moat" && (
            <MoatLab moatCluster={moatCluster} onSetCluster={setMoatCluster} onOpenTicker={openTicker} />
          )}
          {view === "conviction" && <ConvictionView onOpenTicker={openTicker} />}
          {view === "shortlist" && <Shortlist onOpenTicker={openTicker} />}
          {view === "checklist" && <Checklist ticker={focusTicker} onSetTicker={setFocusTicker} />}
          {view === "deepdive" && <DeepDive ticker={focusTicker} onSetTicker={setFocusTicker} />}
        </main>
      </div>
    </div>
  );
}

function SaveIndicator({ state }: { state: "idle" | "saving" | "saved" | "error" }) {
  const map = {
    idle: { text: "", cls: "" },
    saving: { text: "Saving…", cls: "text-amber-400" },
    saved: { text: "Saved", cls: "text-emerald-400" },
    error: { text: "Save failed", cls: "text-red-400" },
  } as const;
  const { text, cls } = map[state];
  if (!text) return null;
  return <span className={cn("font-mono text-[10px]", cls)}>{text}</span>;
}
