"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { cn } from "@/lib/utils";
import { useWorkspace } from "@/lib/research/store";
import {
  CAP_OPTIONS,
  MON_OPTIONS,
  PRIO_OPTIONS,
  STATUS_OPTIONS,
  TYPE_OPTIONS,
} from "@/lib/research/constants";
import type { Company } from "@/lib/research/types";
import { EditableText, ScoreCell, Select } from "./primitives";

type Filters = {
  q: string;
  layer: string;
  mon: string;
  type: string;
  cap: string;
  status: string;
  prio: string;
};

const EMPTY_FILTERS: Filters = {
  q: "",
  layer: "",
  mon: "",
  type: "",
  cap: "",
  status: "",
  prio: "",
};

type SortCol =
  | "ticker"
  | "name"
  | "q"
  | "ai"
  | "up"
  | "bsRisk"
  | "valRisk"
  | "ccRisk"
  | "cxRisk";

const NUMERIC_COLS: SortCol[] = ["q", "ai", "up", "bsRisk", "valRisk", "ccRisk", "cxRisk"];

export default function WatchlistTable({
  onOpenTicker,
}: {
  onOpenTicker: (ticker: string) => void;
}) {
  const { data, patchCompany, toggleShort, overlays } = useWorkspace();
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [sort, setSort] = useState<{ col: SortCol | ""; dir: 1 | -1 }>({
    col: "",
    dir: 1,
  });

  const layerOptions = useMemo(
    () => data.order.map((id) => ({ value: id, label: data.layers[id]?.name ?? id })),
    [data.order, data.layers]
  );

  const rows = useMemo(() => {
    let list = Object.values(data.companies).filter((c) => {
      if (filters.layer && c.layer !== filters.layer) return false;
      if (filters.mon && c.mon !== filters.mon) return false;
      if (filters.type && c.type !== filters.type) return false;
      if (filters.cap && c.cap !== filters.cap) return false;
      if (filters.status && c.status !== filters.status) return false;
      if (filters.prio && c.prio !== filters.prio) return false;
      if (filters.q) {
        const t = filters.q.toLowerCase();
        if (
          !c.ticker.toLowerCase().includes(t) &&
          !c.name.toLowerCase().includes(t)
        )
          return false;
      }
      return true;
    });
    if (sort.col) {
      const col = sort.col;
      const num = NUMERIC_COLS.includes(col);
      list = [...list].sort((a, b) => {
        let x: string | number = a[col] as never;
        let y: string | number = b[col] as never;
        if (num) {
          x = Number(x) || 0;
          y = Number(y) || 0;
        } else {
          x = String(x).toLowerCase();
          y = String(y).toLowerCase();
        }
        return x < y ? -sort.dir : x > y ? sort.dir : 0;
      });
    }
    return list;
  }, [data.companies, filters, sort]);

  useEffect(() => {
    overlays.ensureQuotes(rows.map((r) => r.ticker));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows]);

  const total = Object.keys(data.companies).length;

  const setFilter = (k: keyof Filters, v: string) =>
    setFilters((f) => ({ ...f, [k]: v }));

  const toggleSort = (col: SortCol) =>
    setSort((s) => (s.col === col ? { col, dir: (-s.dir as 1 | -1) } : { col, dir: 1 }));

  const set = (t: string, patch: Partial<Company>) => patchCompany(t, patch);

  const Th = ({ col, children, className }: { col?: SortCol; children?: React.ReactNode; className?: string }) => (
    <th
      onClick={col ? () => toggleSort(col) : undefined}
      className={cn(
        "whitespace-nowrap px-2 py-2 text-left font-medium text-muted-foreground",
        col && "cursor-pointer select-none hover:text-foreground/80",
        className
      )}
    >
      {children}
      {col && sort.col === col && (
        <span className="ml-0.5 text-[10px]">{sort.dir === 1 ? "↑" : "↓"}</span>
      )}
    </th>
  );

  return (
    <div className="p-3">
      {/* Filters */}
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <input
          value={filters.q}
          onChange={(e) => setFilter("q", e.target.value)}
          placeholder="⌕ ticker / name"
          className="w-44 rounded border border-border bg-card px-2 py-1.5 font-mono text-xs outline-none focus:border-ring"
        />
        <FilterSelect
          value={filters.layer}
          onChange={(v) => setFilter("layer", v)}
          placeholder="layer · all"
          options={layerOptions}
        />
        <FilterSelect
          value={filters.mon}
          onChange={(v) => setFilter("mon", v)}
          placeholder="monet · all"
          options={MON_OPTIONS}
        />
        <FilterSelect
          value={filters.type}
          onChange={(v) => setFilter("type", v)}
          placeholder="type · all"
          options={TYPE_OPTIONS}
        />
        <FilterSelect
          value={filters.cap}
          onChange={(v) => setFilter("cap", v)}
          placeholder="cap · all"
          options={CAP_OPTIONS.map((c) => ({ value: c, label: c }))}
        />
        <FilterSelect
          value={filters.status}
          onChange={(v) => setFilter("status", v)}
          placeholder="status · all"
          options={STATUS_OPTIONS.map((c) => ({ value: c, label: c }))}
        />
        <FilterSelect
          value={filters.prio}
          onChange={(v) => setFilter("prio", v)}
          placeholder="prio · all"
          options={PRIO_OPTIONS.map((c) => ({ value: c, label: c }))}
        />
        <button
          type="button"
          onClick={() => setFilters(EMPTY_FILTERS)}
          className="rounded border border-border bg-card px-2.5 py-1.5 font-mono text-xs text-muted-foreground hover:text-foreground"
        >
          clear
        </button>
        <span className="ml-auto font-mono text-xs text-muted-foreground">
          {rows.length} / {total} names · click ✛ to pin
        </span>
      </div>

      {/* Table */}
      <div className="overflow-x-auto rounded-md border border-border">
        <table className="w-full border-collapse text-xs">
          <thead className="border-b border-border bg-card/60">
            <tr>
              <Th className="w-6" />
              <Th col="ticker">Ticker</Th>
              <Th>Price</Th>
              <Th col="name">Company</Th>
              <Th>Layer</Th>
              <Th>Cap</Th>
              <Th>Monet.</Th>
              <Th>Type</Th>
              <Th col="q">Qual</Th>
              <Th col="ai">AI</Th>
              <Th col="up">Upside</Th>
              <Th col="bsRisk">BS rk</Th>
              <Th col="valRisk">Val rk</Th>
              <Th col="ccRisk">Cust rk</Th>
              <Th col="cxRisk">Capx rk</Th>
              <Th>Rev gr</Th>
              <Th>GM</Th>
              <Th>FCF</Th>
              <Th>Main thesis</Th>
              <Th>Main bear case</Th>
              <Th>Would BUY</Th>
              <Th>Would SELL</Th>
              <Th>Prio</Th>
              <Th>Status</Th>
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => {
              const price = overlays.quotes[c.ticker];
              const open = overlays.openTickers.has(c.ticker);
              return (
                <tr key={c.ticker} className="border-b border-border/60 align-top hover:bg-secondary/30">
                  <td className="px-1 py-1.5 text-center">
                    <button
                      type="button"
                      title={c.short ? "Unpin from shortlist" : "Pin to shortlist"}
                      onClick={() => toggleShort(c.ticker)}
                      className={cn(
                        "text-sm leading-none",
                        c.short ? "text-primary" : "text-muted-foreground/50 hover:text-foreground"
                      )}
                    >
                      {c.short ? "✚" : "✛"}
                    </button>
                  </td>
                  <td className="whitespace-nowrap px-2 py-1.5">
                    <button
                      type="button"
                      onClick={() => onOpenTicker(c.ticker)}
                      className="flex items-center gap-1.5 font-mono font-semibold text-foreground hover:text-primary"
                    >
                      {open && <span className="h-2 w-2 rounded-full bg-emerald-400" title="Open position" />}
                      {c.ticker}
                    </button>
                  </td>
                  <td className="whitespace-nowrap px-2 py-1.5 font-mono tabular-nums text-foreground/70">
                    {price == null ? "—" : `$${price.toFixed(2)}`}
                  </td>
                  <td className="max-w-[160px] truncate px-2 py-1.5 text-foreground/80" title={c.name}>
                    {c.name}
                  </td>
                  <td className="px-1 py-1">
                    <Select
                      value={c.layer}
                      onChange={(v) => set(c.ticker, { layer: v })}
                      options={layerOptions}
                      className="max-w-[150px]"
                    />
                  </td>
                  <td className="px-1 py-1">
                    <Select value={c.cap} onChange={(v) => set(c.ticker, { cap: v })} options={CAP_OPTIONS.map((x) => ({ value: x, label: x }))} />
                  </td>
                  <td className="px-1 py-1">
                    <Select value={c.mon} onChange={(v) => set(c.ticker, { mon: v })} options={MON_OPTIONS} />
                  </td>
                  <td className="px-1 py-1">
                    <Select value={c.type} onChange={(v) => set(c.ticker, { type: v })} options={TYPE_OPTIONS} />
                  </td>
                  <ScoreTd><ScoreCell value={c.q} kind="q" onCommit={(n) => set(c.ticker, { q: n })} /></ScoreTd>
                  <ScoreTd><ScoreCell value={c.ai} kind="q" onCommit={(n) => set(c.ticker, { ai: n })} /></ScoreTd>
                  <ScoreTd><ScoreCell value={c.up} kind="q" onCommit={(n) => set(c.ticker, { up: n })} /></ScoreTd>
                  <ScoreTd><ScoreCell value={c.bsRisk} kind="r" onCommit={(n) => set(c.ticker, { bsRisk: n })} /></ScoreTd>
                  <ScoreTd><ScoreCell value={c.valRisk} kind="r" onCommit={(n) => set(c.ticker, { valRisk: n })} /></ScoreTd>
                  <ScoreTd><ScoreCell value={c.ccRisk} kind="r" onCommit={(n) => set(c.ticker, { ccRisk: n })} /></ScoreTd>
                  <ScoreTd><ScoreCell value={c.cxRisk} kind="r" onCommit={(n) => set(c.ticker, { cxRisk: n })} /></ScoreTd>
                  <TextTd w={80}><EditableText value={c.rev} onCommit={(v) => set(c.ticker, { rev: v })} mono /></TextTd>
                  <TextTd w={64}><EditableText value={c.gm} onCommit={(v) => set(c.ticker, { gm: v })} mono /></TextTd>
                  <TextTd w={88}><EditableText value={c.fcf} onCommit={(v) => set(c.ticker, { fcf: v })} mono /></TextTd>
                  <TextTd w={240}><EditableText value={c.thesis} onCommit={(v) => set(c.ticker, { thesis: v })} /></TextTd>
                  <TextTd w={240}><EditableText value={c.bear} onCommit={(v) => set(c.ticker, { bear: v })} /></TextTd>
                  <TextTd w={200}><EditableText value={c.buy} onCommit={(v) => set(c.ticker, { buy: v })} /></TextTd>
                  <TextTd w={200}><EditableText value={c.sell} onCommit={(v) => set(c.ticker, { sell: v })} /></TextTd>
                  <td className="px-1 py-1">
                    <Select value={c.prio} onChange={(v) => set(c.ticker, { prio: v })} options={PRIO_OPTIONS.map((x) => ({ value: x, label: x }))} />
                  </td>
                  <td className="px-1 py-1">
                    <Select value={c.status} onChange={(v) => set(c.ticker, { status: v })} options={STATUS_OPTIONS.map((x) => ({ value: x, label: x }))} />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="mt-2 text-right">
        <Link href="/trades" className="font-mono text-[11px] text-muted-foreground hover:text-foreground">
          open journal trades →
        </Link>
      </div>
    </div>
  );
}

function ScoreTd({ children }: { children: React.ReactNode }) {
  return <td className="px-1 py-1 text-center">{children}</td>;
}
function TextTd({ children, w }: { children: React.ReactNode; w: number }) {
  return (
    <td className="px-1 py-1" style={{ minWidth: w }}>
      {children}
    </td>
  );
}

function FilterSelect<T extends string>({
  value,
  onChange,
  placeholder,
  options,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
  options: { value: T; label: string }[];
}) {
  return (
    <select
      value={value}
      suppressHydrationWarning
      onChange={(e) => onChange(e.target.value)}
      className="rounded border border-border bg-card px-2 py-1.5 font-mono text-xs text-foreground/80 outline-none focus:border-ring"
    >
      <option value="">{placeholder}</option>
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}
