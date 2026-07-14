"use client";

import { FormEvent, useState } from "react";
import { Button } from "@/components/ui/button";
import { getRunTrades } from "@/lib/strategy-lab/api";
import {
  formatDecimal,
  formatDurationMinutes,
  formatMoney,
  formatPercentPoints,
  formatStrategyDateTime,
} from "@/lib/strategy-lab/format";
import type {
  StrategyRunTrade,
  StrategyRunTradeFilters,
  StrategyRunTradeList,
  StrategyTradeDirection,
  StrategyTradeOutcome,
} from "@/lib/strategy-lab/types";

const PAGE_SIZE = 100;

function pnlClass(value: string | null) {
  if (value == null) return "text-muted-foreground";
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return "text-muted-foreground";
  return parsed >= 0 ? "text-emerald-400" : "text-red-400";
}

function outcomeLabel(trade: StrategyRunTrade) {
  if (trade.net_pnl == null) return "Unknown";
  const pnl = Number(trade.net_pnl);
  if (pnl > 0) return "Winner";
  if (pnl < 0) return "Loser";
  return "Breakeven";
}

export default function StrategyRunTradesTable({
  runId,
  sourceTimezone,
  currency,
  initialPage,
}: {
  runId: string;
  sourceTimezone: string;
  currency: string;
  initialPage: StrategyRunTradeList;
}) {
  const [page, setPage] = useState(initialPage);
  const [direction, setDirection] = useState<"all" | StrategyTradeDirection>("all");
  const [outcome, setOutcome] = useState<"all" | StrategyTradeOutcome>("all");
  const [entryDateFrom, setEntryDateFrom] = useState("");
  const [entryDateTo, setEntryDateTo] = useState("");
  const [applied, setApplied] = useState<StrategyRunTradeFilters>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async (filters: StrategyRunTradeFilters, offset: number) => {
    setLoading(true);
    setError(null);
    try {
      const next = await getRunTrades(runId, {
        ...filters,
        limit: PAGE_SIZE,
        offset,
      });
      setPage(next);
      setApplied(filters);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to load simulated trades");
    } finally {
      setLoading(false);
    }
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    void load(
      {
        direction: direction === "all" ? undefined : direction,
        outcome: outcome === "all" ? undefined : outcome,
        entryDateFrom: entryDateFrom || undefined,
        entryDateTo: entryDateTo || undefined,
      },
      0,
    );
  };

  const reset = () => {
    setDirection("all");
    setOutcome("all");
    setEntryDateFrom("");
    setEntryDateTo("");
    void load({}, 0);
  };

  const start = page.total === 0 ? 0 : page.offset + 1;
  const end = Math.min(page.offset + page.items.length, page.total);

  return (
    <section className="overflow-hidden rounded-lg border bg-card">
      <div className="border-b px-5 py-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              Simulated trades
            </h2>
            <p className="mt-1 text-xs text-muted-foreground">
              Source timestamps are displayed in {sourceTimezone}. Filters use source-local entry dates.
            </p>
          </div>
          <p className="text-xs tabular-nums text-muted-foreground">
            {start}–{end} of {page.total}
          </p>
        </div>

        <form onSubmit={submit} className="mt-4 flex flex-wrap items-end gap-3">
          <FilterField label="Direction">
            <select
              value={direction}
              onChange={(event) => setDirection(event.target.value as typeof direction)}
              className="h-9 rounded-md border bg-background px-3 text-sm outline-none focus:border-ring"
            >
              <option value="all">All</option>
              <option value="long">Long</option>
              <option value="short">Short</option>
            </select>
          </FilterField>
          <FilterField label="Outcome">
            <select
              value={outcome}
              onChange={(event) => setOutcome(event.target.value as typeof outcome)}
              className="h-9 rounded-md border bg-background px-3 text-sm outline-none focus:border-ring"
            >
              <option value="all">All</option>
              <option value="winner">Winner</option>
              <option value="loser">Loser</option>
              <option value="breakeven">Breakeven</option>
              <option value="unknown">Missing P&L</option>
            </select>
          </FilterField>
          <FilterField label="Entry from">
            <input
              type="date"
              value={entryDateFrom}
              onChange={(event) => setEntryDateFrom(event.target.value)}
              className="h-9 rounded-md border bg-background px-3 text-sm outline-none focus:border-ring"
            />
          </FilterField>
          <FilterField label="Entry through">
            <input
              type="date"
              value={entryDateTo}
              onChange={(event) => setEntryDateTo(event.target.value)}
              className="h-9 rounded-md border bg-background px-3 text-sm outline-none focus:border-ring"
            />
          </FilterField>
          <Button type="submit" size="sm" disabled={loading}>
            {loading ? "Loading" : "Apply filters"}
          </Button>
          <Button type="button" size="sm" variant="ghost" onClick={reset} disabled={loading}>
            Reset
          </Button>
        </form>
        {error && <p className="mt-3 text-sm text-red-400">{error}</p>}
      </div>

      {page.items.length === 0 ? (
        <div className="px-5 py-10 text-center text-sm text-muted-foreground">
          No simulated trades match these filters.
        </div>
      ) : (
        <div className={`overflow-x-auto transition-opacity ${loading ? "opacity-60" : ""}`}>
          <table className="w-full min-w-[1380px] text-sm">
            <thead className="bg-muted/70 text-xs uppercase text-muted-foreground">
              <tr>
                <Th>#</Th>
                <Th>Side</Th>
                <Th>Entry</Th>
                <Th>Exit</Th>
                <Th>Entry price</Th>
                <Th>Exit price</Th>
                <Th>Qty</Th>
                <Th>Outcome</Th>
                <Th>P&L</Th>
                <Th>Return</Th>
                <Th>MFE</Th>
                <Th>MAE</Th>
                <Th>Hold</Th>
                <Th>Signal</Th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {page.items.map((trade) => (
                <tr key={trade.id} className="hover:bg-muted/40">
                  <Td><span className="font-medium tabular-nums">{trade.trade_number}</span></Td>
                  <Td>
                    <span
                      className={`rounded px-2 py-0.5 text-xs font-medium ${
                        trade.direction === "long"
                          ? "bg-sky-900/40 text-sky-300"
                          : "bg-purple-900/40 text-purple-300"
                      }`}
                    >
                      {trade.direction}
                    </span>
                  </Td>
                  <Td>{formatStrategyDateTime(trade.entry_at, sourceTimezone)}</Td>
                  <Td>{formatStrategyDateTime(trade.exit_at, sourceTimezone)}</Td>
                  <Td>{formatMoney(trade.entry_price, currency, 4)}</Td>
                  <Td>{formatMoney(trade.exit_price, currency, 4)}</Td>
                  <Td>{formatDecimal(trade.quantity, 6)}</Td>
                  <Td>{outcomeLabel(trade)}</Td>
                  <Td><span className={pnlClass(trade.net_pnl)}>{formatMoney(trade.net_pnl, currency)}</span></Td>
                  <Td><span className={pnlClass(trade.return_pct)}>{formatPercentPoints(trade.return_pct, 2)}</span></Td>
                  <Td>{formatMoney(trade.mfe, currency)}</Td>
                  <Td>{formatMoney(trade.mae, currency)}</Td>
                  <Td>{formatDurationMinutes(trade.duration_minutes)}</Td>
                  <Td>
                    <div className="max-w-[220px] truncate" title={trade.entry_signal ?? undefined}>
                      {trade.entry_signal ?? "—"}
                    </div>
                    {trade.exit_signal && (
                      <div className="max-w-[220px] truncate text-xs text-muted-foreground" title={trade.exit_signal}>
                        Exit: {trade.exit_signal}
                      </div>
                    )}
                  </Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="flex items-center justify-between gap-3 border-t px-5 py-3">
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={loading || page.offset === 0}
          onClick={() => void load(applied, Math.max(0, page.offset - page.limit))}
        >
          Previous
        </Button>
        <span className="text-xs text-muted-foreground">
          Page {page.total === 0 ? 0 : Math.floor(page.offset / page.limit) + 1} of{" "}
          {Math.ceil(page.total / page.limit)}
        </span>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={loading || page.offset + page.items.length >= page.total}
          onClick={() => void load(applied, page.offset + page.limit)}
        >
          Next
        </Button>
      </div>
    </section>
  );
}

function FilterField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="grid gap-1 text-xs font-medium text-muted-foreground">
      {label}
      {children}
    </label>
  );
}

function Th({ children }: { children: React.ReactNode }) {
  return <th className="px-3 py-2 text-left font-medium">{children}</th>;
}

function Td({ children }: { children: React.ReactNode }) {
  return <td className="px-3 py-3 align-top">{children}</td>;
}
