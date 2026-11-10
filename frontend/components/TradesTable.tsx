"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";
import { Trade, Account } from "@/lib/api";
import { formatHoldDuration } from "@/lib/dashboard";
import { contractName, fmtDate, money } from "@/lib/format";

/** Rows shown at first and added by each "Show more": a long history stays quick to open and scroll. */
const PAGE = 50;

/** The entry-time bucket in words ("open" → "Open"). */
const bucketName = (value: string) => value.charAt(0).toUpperCase() + value.slice(1).replace(/_/g, " ");

type SortKey =
  | "ticker" | "account" | "opened_at" | "closed_at"
  | "contracts" | "avg_entry_premium" | "avg_exit_premium"
  | "realized_pnl" | "pnl_pct" | "hold_duration_mins" | "status";

type SortDir = "asc" | "desc";

function cmp(a: string | number | null, b: string | number | null, dir: SortDir): number {
  if (a == null && b == null) return 0;
  if (a == null) return 1;
  if (b == null) return -1;
  const result = a < b ? -1 : a > b ? 1 : 0;
  return dir === "asc" ? result : -result;
}

function getSortVal(trade: Trade, key: SortKey, accountMap: Record<string, Account>): string | number | null {
  switch (key) {
    case "ticker": return trade.ticker;
    case "account": return accountMap[trade.account_id]?.name ?? null;
    case "opened_at": return trade.opened_at;
    case "closed_at": return trade.closed_at;
    case "contracts": return trade.contracts;
    case "avg_entry_premium": return trade.avg_entry_premium;
    case "avg_exit_premium": return trade.avg_exit_premium;
    case "realized_pnl": return trade.realized_pnl;
    case "pnl_pct": return trade.pnl_pct;
    case "hold_duration_mins": return trade.hold_duration_mins;
    case "status": return trade.status;
  }
}

function pnlColor(val: number | null | undefined) {
  if (val == null) return "text-muted-foreground";
  return val >= 0 ? "text-emerald-400" : "text-red-400";
}

const fmt$ = (val: number | null | undefined) => money(val, { signed: true, cents: false });

function fmtPct(val: number | null | undefined) {
  if (val == null) return "—";
  return `${val >= 0 ? "+" : ""}${(val * 100).toFixed(1)}%`;
}

const CHIP = "inline-flex h-[22px] items-center whitespace-nowrap rounded-md bg-secondary px-2 text-[11.5px] font-medium";

function StatusBadge({ status }: { status: Trade["status"] }) {
  return <span className={cn(CHIP, status === "open" ? "text-foreground" : "text-muted-foreground")}>{status}</span>;
}

function SortIcon({ active, dir }: { active: boolean; dir: SortDir }) {
  if (!active) return <span className="ml-0.5 text-muted-foreground/30 text-xs">↕</span>;
  return <span className="ml-0.5 text-xs">{dir === "asc" ? "↑" : "↓"}</span>;
}

function Th({
  children,
  sortKey,
  currentSort,
  dir,
  onSort,
  wide,
}: {
  children: React.ReactNode;
  sortKey: SortKey;
  currentSort: SortKey | null;
  dir: SortDir;
  onSort: (key: SortKey) => void;
  wide?: boolean;
}) {
  return (
    <th
      aria-sort={currentSort === sortKey ? (dir === "asc" ? "ascending" : "descending") : "none"}
      className={cn(
        "px-2 py-2 text-left font-medium cursor-pointer select-none whitespace-nowrap hover:text-foreground/80 sm:px-3",
        // A phone fits about four columns; the rest return from sm up, and
        // the ticker still opens the trade for everything they hold.
        wide && "hidden sm:table-cell"
      )}
    >
      <button type="button" onClick={() => onSort(sortKey)} className="inline-flex min-h-11 items-center gap-0.5 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:min-h-9">
        {children}
        <SortIcon active={currentSort === sortKey} dir={dir} />
      </button>
    </th>
  );
}

function Td({ children, wide, num }: { children: React.ReactNode; wide?: boolean; num?: boolean }) {
  return <td className={cn("px-2 py-3 sm:px-3", wide && "hidden sm:table-cell", num && "tabular-nums")}>{children}</td>;
}

export default function TradesTable({
  trades,
  accountMap,
  thisYear,
  returnTo,
}: {
  trades: Trade[];
  accountMap: Record<string, Account>;
  /** New York's year, from the server, so the server and browser label expiries alike. */
  thisYear: number;
  /** Filtered list to restore after inspecting a trade. */
  returnTo?: string;
}) {
  const [sort, setSort] = useState<{ key: SortKey; dir: SortDir } | null>(null);
  const [shown, setShown] = useState(PAGE);
  // One account in the list: its badge on every row says nothing.
  const showAccount = new Set(trades.map((t) => t.account_id)).size > 1;

  function handleSort(key: SortKey) {
    setSort((prev) =>
      prev?.key === key
        ? { key, dir: prev.dir === "asc" ? "desc" : "asc" }
        : { key, dir: "asc" }
    );
  }

  const sorted =
    sort == null
      ? trades
      : [...trades].sort((a, b) =>
          cmp(getSortVal(a, sort.key, accountMap), getSortVal(b, sort.key, accountMap), sort.dir)
        );

  function thProps(key: SortKey, wide = false) {
    return { sortKey: key, currentSort: sort?.key ?? null, dir: sort?.dir ?? "asc", onSort: handleSort, wide };
  }

  return (
    <div className="overflow-x-auto rounded-lg border bg-card">
      <table className="w-full text-sm">
        <thead className="border-b text-xs font-medium text-muted-foreground">
          <tr>
            <Th {...thProps("ticker")}>Ticker</Th>
            <Th {...thProps("realized_pnl")}>P&amp;L</Th>
            {showAccount && <Th {...thProps("account", true)}>Account</Th>}
            <Th {...thProps("opened_at")}>Opened</Th>
            <Th {...thProps("closed_at", true)}>Closed</Th>
            <Th {...thProps("contracts")}>Quantity</Th>
            <Th {...thProps("avg_entry_premium", true)}>Entry</Th>
            <Th {...thProps("avg_exit_premium", true)}>Exit</Th>
            <Th {...thProps("pnl_pct", true)}>P&amp;L %</Th>
            <Th {...thProps("hold_duration_mins", true)}>Hold</Th>
            <Th {...thProps("status", true)}>Status</Th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {sorted.length === 0 && (
            <tr>
              <td colSpan={showAccount ? 11 : 10} className="px-4 py-8 text-center text-muted-foreground">
                No trades found.
              </td>
            </tr>
          )}
          {sorted.slice(0, shown).map((t) => (
            <tr key={t.id} className="hover:bg-muted/50">
              <Td>
                <a href={`/trades/${t.id}${returnTo ? `?returnTo=${encodeURIComponent(returnTo)}` : ""}`} className="font-semibold hover:underline">
                  {t.ticker}
                </a>
                {t.instrument_type === "option" && (
                  <div className="mt-0.5 text-xs text-muted-foreground sm:whitespace-nowrap">{contractName(t)}</div>
                )}
              </Td>
              <Td num><span className={cn("whitespace-nowrap", pnlColor(t.realized_pnl))}>{fmt$(t.realized_pnl)}</span></Td>
              {showAccount && (
                <Td wide>
                  <span className={cn(CHIP, "text-muted-foreground")}>{accountMap[t.account_id]?.name ?? "—"}</span>
                </Td>
              )}
              <Td>
                <span className="whitespace-nowrap tabular-nums">{fmtDate(t.opened_at, thisYear)}</span>
                {t.entry_time_bucket && <span className="hidden text-xs text-muted-foreground sm:block">{bucketName(t.entry_time_bucket)}</span>}
                {/* Status has no column on a phone; an open trade still says so. */}
                {t.status === "open" && <span className="mt-1 block sm:hidden"><StatusBadge status={t.status} /></span>}
              </Td>
              <Td wide num><span className="whitespace-nowrap">{t.closed_at ? fmtDate(t.closed_at, thisYear) : <span className="text-muted-foreground/40">—</span>}</span></Td>
              <Td><span className="tabular-nums">{t.contracts}</span> <span className="block text-xs text-muted-foreground sm:inline">{t.instrument_type === "stock" ? "shares" : "contracts"}</span></Td>
              <Td wide num>{money(t.avg_entry_premium)}</Td>
              <Td wide num>{t.avg_exit_premium != null ? money(t.avg_exit_premium) : <span className="text-muted-foreground/40">—</span>}</Td>
              <Td wide num><span className={pnlColor(t.pnl_pct)}>{fmtPct(t.pnl_pct)}</span></Td>
              <Td wide num><span className="whitespace-nowrap">{t.hold_duration_mins != null ? formatHoldDuration(t.hold_duration_mins) : "—"}</span></Td>
              <Td wide><StatusBadge status={t.status} /></Td>
            </tr>
          ))}
        </tbody>
      </table>
      {sorted.length > shown && (
        <div className="flex flex-wrap items-center justify-between gap-2 border-t px-4 py-3 text-xs text-muted-foreground">
          <span>Showing {shown.toLocaleString("en-US")} of {sorted.length.toLocaleString("en-US")} trades</span>
          <div className="flex gap-2">
            <button type="button" onClick={() => setShown((count) => count + PAGE)} className="rounded-md border px-3 py-1.5 font-medium text-foreground hover:bg-secondary">Show {Math.min(PAGE, sorted.length - shown)} more</button>
            <button type="button" onClick={() => setShown(sorted.length)} className="rounded-md px-3 py-1.5 hover:bg-secondary hover:text-foreground">Show all</button>
          </div>
        </div>
      )}
    </div>
  );
}
