"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";
import { Trade, Account } from "@/lib/api";
import { formatHoldDuration } from "@/lib/dashboard";
import { money } from "@/lib/format";

/** Rows shown at first and added by each "Show more": a long history stays quick to open and scroll. */
const PAGE = 50;

/** An expiration as a short calendar date ("Oct 9"), with the year when it is not this year ("Jan 15, 2027"). */
function fmtExpiry(value: string, thisYear: number) {
  const [year, month, day] = value.slice(0, 10).split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, day)).toLocaleDateString("en-US", { timeZone: "UTC", month: "short", day: "numeric", ...(year === thisYear ? {} : { year: "numeric" }) });
}

/** The entry-time bucket in words ("open" → "Open"). */
const bucketName = (value: string) => value.charAt(0).toUpperCase() + value.slice(1).replace(/_/g, " ");

type SortKey =
  | "ticker" | "account" | "strike" | "option_type" | "expiration"
  | "contracts" | "avg_entry_premium" | "avg_exit_premium"
  | "realized_pnl" | "pnl_pct" | "hold_duration_mins"
  | "entry_time_bucket" | "status";

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
    case "strike": return trade.strike;
    case "option_type": return trade.option_type;
    case "expiration": return trade.expiration;
    case "contracts": return trade.contracts;
    case "avg_entry_premium": return trade.avg_entry_premium;
    case "avg_exit_premium": return trade.avg_exit_premium;
    case "realized_pnl": return trade.realized_pnl;
    case "pnl_pct": return trade.pnl_pct;
    case "hold_duration_mins": return trade.hold_duration_mins;
    case "entry_time_bucket": return trade.entry_time_bucket;
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

function StatusBadge({ status }: { status: Trade["status"] }) {
  const cls =
    status === "open"
      ? "bg-blue-900/40 text-blue-300"
      : status === "expired"
      ? "bg-muted text-muted-foreground"
      : "bg-muted text-foreground/70";
  return (
    <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${cls}`}>
      {status}
    </span>
  );
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
      className={cn(
        "px-2 py-2 text-left font-medium cursor-pointer select-none whitespace-nowrap hover:text-foreground/80 sm:px-4",
        // A phone fits about four columns; the rest return from sm up, and
        // the ticker still opens the trade for everything they hold.
        wide && "hidden sm:table-cell"
      )}
      onClick={() => onSort(sortKey)}
    >
      {children}
      <SortIcon active={currentSort === sortKey} dir={dir} />
    </th>
  );
}

function Td({ children, wide }: { children: React.ReactNode; wide?: boolean }) {
  return <td className={cn("px-2 py-3 sm:px-4", wide && "hidden sm:table-cell")}>{children}</td>;
}

export default function TradesTable({
  trades,
  accountMap,
}: {
  trades: Trade[];
  accountMap: Record<string, Account>;
}) {
  const [sort, setSort] = useState<{ key: SortKey; dir: SortDir } | null>(null);
  const [shown, setShown] = useState(PAGE);
  // One account in the list: its badge on every row says nothing.
  const showAccount = new Set(trades.map((t) => t.account_id)).size > 1;
  const thisYear = new Date().getFullYear();

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
        <thead className="bg-muted text-xs text-muted-foreground uppercase">
          <tr>
            <Th {...thProps("ticker")}>Ticker</Th>
            {showAccount && <Th {...thProps("account", true)}>Account</Th>}
            <Th {...thProps("strike", true)}>Strike</Th>
            <Th {...thProps("option_type", true)}>Type</Th>
            <Th {...thProps("expiration", true)}>Expiry</Th>
            <Th {...thProps("contracts")}>Contracts</Th>
            <Th {...thProps("avg_entry_premium", true)}>Entry</Th>
            <Th {...thProps("avg_exit_premium", true)}>Exit</Th>
            <Th {...thProps("realized_pnl")}>P&amp;L</Th>
            <Th {...thProps("pnl_pct", true)}>P&amp;L %</Th>
            <Th {...thProps("hold_duration_mins", true)}>Hold</Th>
            <Th {...thProps("entry_time_bucket", true)}>Entered</Th>
            <Th {...thProps("status")}>Status</Th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {sorted.length === 0 && (
            <tr>
              <td colSpan={showAccount ? 13 : 12} className="px-4 py-8 text-center text-muted-foreground">
                No trades found.
              </td>
            </tr>
          )}
          {sorted.slice(0, shown).map((t) => (
            <tr key={t.id} className="hover:bg-muted/50">
              <Td>
                <a href={`/trades/${t.id}`} className="font-semibold hover:underline">
                  {t.ticker}
                </a>
              </Td>
              {showAccount && (
                <Td wide>
                  <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${
                    accountMap[t.account_id]?.type === "roth_ira"
                      ? "bg-purple-900/40 text-purple-300"
                      : "bg-sky-900/40 text-sky-300"
                  }`}>
                    {accountMap[t.account_id]?.name ?? "—"}
                  </span>
                </Td>
              )}
              <Td wide>{t.strike != null ? money(t.strike) : <span className="text-muted-foreground/40">—</span>}</Td>
              <Td wide>{t.option_type ? <span className="uppercase">{t.option_type}</span> : <span className="text-muted-foreground/40">—</span>}</Td>
              <Td wide><span className="whitespace-nowrap">{t.expiration ? fmtExpiry(t.expiration, thisYear) : <span className="text-muted-foreground/40">—</span>}</span></Td>
              <Td>{t.contracts}</Td>
              <Td wide>{money(t.avg_entry_premium)}</Td>
              <Td wide>{t.avg_exit_premium != null ? money(t.avg_exit_premium) : <span className="text-muted-foreground/40">—</span>}</Td>
              <Td><span className={pnlColor(t.realized_pnl)}>{fmt$(t.realized_pnl)}</span></Td>
              <Td wide><span className={pnlColor(t.pnl_pct)}>{fmtPct(t.pnl_pct)}</span></Td>
              <Td wide><span className="whitespace-nowrap">{t.hold_duration_mins != null ? formatHoldDuration(t.hold_duration_mins) : "—"}</span></Td>
              <Td wide>{t.entry_time_bucket ? bucketName(t.entry_time_bucket) : "—"}</Td>
              <Td><StatusBadge status={t.status} /></Td>
            </tr>
          ))}
        </tbody>
      </table>
      {sorted.length > shown && (
        <div className="flex flex-wrap items-center justify-between gap-2 border-t px-4 py-3 text-xs text-muted-foreground">
          <span>Showing {shown.toLocaleString()} of {sorted.length.toLocaleString()} trades</span>
          <div className="flex gap-2">
            <button type="button" onClick={() => setShown((count) => count + PAGE)} className="rounded-md border px-3 py-1.5 font-medium text-foreground hover:bg-secondary">Show {Math.min(PAGE, sorted.length - shown)} more</button>
            <button type="button" onClick={() => setShown(sorted.length)} className="rounded-md px-3 py-1.5 hover:bg-secondary hover:text-foreground">Show all</button>
          </div>
        </div>
      )}
    </div>
  );
}
