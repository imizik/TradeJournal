"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";
import type { Account, PositionQuote, Trade } from "@/lib/api";
import { computeUnrealizedPnl, formatHoldDuration, getCurrentMark, type OpenPositionRow } from "@/lib/dashboard";

export type { OpenPositionMeta, OpenPositionRow } from "@/lib/dashboard";

type SortDir = "asc" | "desc";

type OpenSortKey =
  | "ticker"
  | "account"
  | "instrument_type"
  | "strike"
  | "option_type"
  | "expiration"
  | "qty_left"
  | "avg_cost"
  | "cost_left"
  | "current_price"
  | "unrealized_pnl"
  | "realized"
  | "opened_at"
  | "last_activity";

type ClosedSortKey =
  | "ticker"
  | "account"
  | "instrument_type"
  | "strike"
  | "option_type"
  | "expiration"
  | "realized_pnl"
  | "pnl_pct"
  | "hold_duration_mins"
  | "status";

function cmp(a: string | number | null, b: string | number | null, dir: SortDir): number {
  if (a == null && b == null) return 0;
  if (a == null) return 1;
  if (b == null) return -1;

  const result = a < b ? -1 : a > b ? 1 : 0;
  return dir === "asc" ? result : -result;
}

function pnlColor(val: number | null | undefined) {
  if (val == null) return "text-muted-foreground";
  return val >= 0 ? "text-emerald-400" : "text-red-400";
}

function fmt$(val: number | null | undefined) {
  if (val == null) return "-";
  return `${val >= 0 ? "+" : ""}$${val.toFixed(0)}`;
}

function fmtMoney(val: number | null | undefined) {
  if (val == null) return "-";
  return `$${val.toFixed(2)}`;
}

function fmtPct(val: number | null | undefined) {
  if (val == null) return "-";
  return `${val >= 0 ? "+" : ""}${(val * 100).toFixed(1)}%`;
}

function fmtQty(val: number | null | undefined) {
  if (val == null) return "-";
  return String(Number(val.toFixed(6)));
}

function fmtDateShort(val: string | null | undefined) {
  if (!val) return "-";
  return new Date(val).toLocaleDateString();
}

function fmtOptionType(val: string | null | undefined) {
  if (!val) return <span className="text-muted-foreground/40">-</span>;
  return <span className="uppercase">{val}</span>;
}

function StatusBadge({ status }: { status: Trade["status"] }) {
  const cls =
    status === "open"
      ? "bg-blue-900/40 text-blue-300"
      : status === "expired"
        ? "bg-muted text-muted-foreground"
        : "bg-muted text-foreground/70";

  return <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${cls}`}>{status}</span>;
}

function AccountBadge({ accountMap, accountId }: { accountMap: Record<string, Account>; accountId: string }) {
  const account = accountMap[accountId];
  const cls =
    account?.type === "roth_ira"
      ? "bg-purple-900/40 text-purple-300"
      : "bg-sky-900/40 text-sky-300";

  return <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${cls}`}>{account?.name ?? "-"}</span>;
}

function SortIcon({ active, dir }: { active: boolean; dir: SortDir }) {
  if (!active) return <span className="ml-1 text-xs text-muted-foreground/30">-</span>;
  return <span className="ml-1 text-xs">{dir === "asc" ? "^" : "v"}</span>;
}

function Th<K extends string>({
  children,
  sortKey,
  currentSort,
  dir,
  onSort,
  wide,
}: {
  children: React.ReactNode;
  sortKey: K;
  currentSort: K | null;
  dir: SortDir;
  onSort: (key: K) => void;
  wide?: boolean;
}) {
  return (
    <th
      className={cn(
        "cursor-pointer select-none whitespace-nowrap px-2 py-2 text-left font-medium hover:text-foreground/80 sm:px-4",
        // Phones keep the few columns worth reading at a glance; the ticker
        // still opens the trade for everything else.
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

function getOpenSortVal(
  { trade, meta }: OpenPositionRow,
  key: OpenSortKey,
  accountMap: Record<string, Account>,
  quotes: Record<string, PositionQuote>,
): string | number | null {
  switch (key) {
    case "ticker":
      return trade.ticker;
    case "account":
      return accountMap[trade.account_id]?.name ?? null;
    case "instrument_type":
      return trade.instrument_type;
    case "strike":
      return trade.strike;
    case "option_type":
      return trade.option_type;
    case "expiration":
      return trade.expiration;
    case "qty_left":
      return meta.qtyLeft;
    case "avg_cost":
      return trade.avg_entry_premium;
    case "cost_left":
      return meta.capitalLeft;
    case "current_price":
      return getCurrentMark(trade, quotes[trade.id]);
    case "unrealized_pnl":
      return computeUnrealizedPnl(trade, meta, quotes[trade.id]);
    case "realized":
      return meta.realizedSoFar;
    case "opened_at":
      return trade.opened_at;
    case "last_activity":
      return meta.lastActivityAt;
  }
}

function getClosedSortVal(
  trade: Trade,
  key: ClosedSortKey,
  accountMap: Record<string, Account>,
): string | number | null {
  switch (key) {
    case "ticker":
      return trade.ticker;
    case "account":
      return accountMap[trade.account_id]?.name ?? null;
    case "instrument_type":
      return trade.instrument_type;
    case "strike":
      return trade.strike;
    case "option_type":
      return trade.option_type;
    case "expiration":
      return trade.expiration;
    case "realized_pnl":
      return trade.realized_pnl;
    case "pnl_pct":
      return trade.pnl_pct;
    case "hold_duration_mins":
      return trade.hold_duration_mins;
    case "status":
      return trade.status;
  }
}

export function OpenPositionsTable({
  rows,
  accountMap,
  quotes = {},
}: {
  rows: OpenPositionRow[];
  accountMap: Record<string, Account>;
  quotes?: Record<string, PositionQuote>;
}) {
  const [sort, setSort] = useState<{ key: OpenSortKey; dir: SortDir } | null>(null);

  function handleSort(key: OpenSortKey) {
    setSort((prev) =>
      prev?.key === key
        ? { key, dir: prev.dir === "asc" ? "desc" : "asc" }
        : { key, dir: "asc" },
    );
  }

  const sorted =
    sort == null
      ? rows
      : [...rows].sort((a, b) =>
          cmp(
            getOpenSortVal(a, sort.key, accountMap, quotes),
            getOpenSortVal(b, sort.key, accountMap, quotes),
            sort.dir,
          ),
        );

  function thProps(key: OpenSortKey, wide = false) {
    return {
      sortKey: key,
      currentSort: sort?.key ?? null,
      dir: sort?.dir ?? "asc",
      onSort: handleSort,
      wide,
    };
  }

  return (
    <div className="overflow-x-auto rounded-lg border bg-card">
      <table className="w-full text-sm sm:min-w-[1380px]">
        <thead className="bg-muted text-xs uppercase text-muted-foreground">
          <tr>
            <Th {...thProps("ticker")}>Ticker</Th>
            <Th {...thProps("account", true)}>Account</Th>
            <Th {...thProps("instrument_type", true)}>Instrument</Th>
            <Th {...thProps("strike", true)}>Strike</Th>
            <Th {...thProps("option_type", true)}>Type</Th>
            <Th {...thProps("expiration", true)}>Expiry</Th>
            <Th {...thProps("qty_left")}>Qty Left</Th>
            <Th {...thProps("avg_cost", true)}>Avg Cost</Th>
            <Th {...thProps("cost_left", true)}>Entry Value Left</Th>
            <Th {...thProps("current_price")}>Mark</Th>
            <Th {...thProps("unrealized_pnl")}>Unreal. P&amp;L</Th>
            <Th {...thProps("realized", true)}>Realized</Th>
            <Th {...thProps("opened_at", true)}>Opened</Th>
            <Th {...thProps("last_activity", true)}>Last Activity</Th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {sorted.map(({ trade, meta }) => {
            const quote = quotes[trade.id];
            const currentMark = getCurrentMark(trade, quote);
            const unrealizedPnl = computeUnrealizedPnl(trade, meta, quote);
            const showUnderlying = trade.instrument_type === "option" && quote?.underlying_price != null;

            return (
              <tr key={trade.id} className="hover:bg-muted/50">
                <Td>
                  <a href={`/trades/${trade.id}`} className="font-semibold hover:underline">
                    {trade.ticker}
                  </a>
                </Td>
                <Td wide>
                  <AccountBadge accountMap={accountMap} accountId={trade.account_id} />
                </Td>
                <Td wide>
                  <span className="capitalize">{trade.instrument_type}</span>
                </Td>
                <Td wide>
                  {trade.strike != null ? fmtMoney(trade.strike) : <span className="text-muted-foreground/40">-</span>}
                </Td>
                <Td wide>{fmtOptionType(trade.option_type)}</Td>
                <Td wide>
                  {trade.expiration ? fmtDateShort(trade.expiration) : <span className="text-muted-foreground/40">-</span>}
                </Td>
                <Td>
                  <div className="flex flex-col">
                    <span className="font-medium">{fmtQty(meta.qtyLeft)}</span>
                    <span className="text-xs text-muted-foreground">
                      {`opened ${fmtQty(meta.openedQty)}${meta.exitedQty > 0 ? ` | trimmed ${fmtQty(meta.exitedQty)}` : ""}`}
                    </span>
                  </div>
                </Td>
                <Td wide>{fmtMoney(trade.avg_entry_premium)}</Td>
                <Td wide>{fmtMoney(meta.capitalLeft)}</Td>
                <Td>
                  <div className="flex flex-col">
                    <span>{currentMark != null ? fmtMoney(currentMark) : <span className="text-muted-foreground/40">--</span>}</span>
                    {showUnderlying && (
                      <span className="text-xs text-muted-foreground">
                        {`U ${fmtMoney(quote?.underlying_price)}`}
                      </span>
                    )}
                  </div>
                </Td>
                <Td>
                  {unrealizedPnl != null ? (
                    <span className={pnlColor(unrealizedPnl)}>{fmt$(unrealizedPnl)}</span>
                  ) : (
                    <span className="text-muted-foreground/40">--</span>
                  )}
                </Td>
                <Td wide>
                  <span className={pnlColor(meta.realizedSoFar)}>{fmt$(meta.realizedSoFar)}</span>
                </Td>
                <Td wide>{fmtDateShort(trade.opened_at)}</Td>
                <Td wide>{fmtDateShort(meta.lastActivityAt)}</Td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function RecentClosedTable({
  trades,
  accountMap,
}: {
  trades: Trade[];
  accountMap: Record<string, Account>;
}) {
  const [sort, setSort] = useState<{ key: ClosedSortKey; dir: SortDir } | null>(null);

  function handleSort(key: ClosedSortKey) {
    setSort((prev) =>
      prev?.key === key
        ? { key, dir: prev.dir === "asc" ? "desc" : "asc" }
        : { key, dir: "asc" },
    );
  }

  const sorted =
    sort == null
      ? trades
      : [...trades].sort((a, b) =>
          cmp(getClosedSortVal(a, sort.key, accountMap), getClosedSortVal(b, sort.key, accountMap), sort.dir),
        );

  function thProps(key: ClosedSortKey, wide = false) {
    return {
      sortKey: key,
      currentSort: sort?.key ?? null,
      dir: sort?.dir ?? "asc",
      onSort: handleSort,
      wide,
    };
  }

  return (
    <div className="overflow-x-auto rounded-lg border bg-card">
      <table className="w-full text-sm">
        <thead className="bg-muted text-xs uppercase text-muted-foreground">
          <tr>
            <Th {...thProps("ticker")}>Ticker</Th>
            <Th {...thProps("account", true)}>Account</Th>
            <Th {...thProps("instrument_type", true)}>Instrument</Th>
            <Th {...thProps("strike", true)}>Strike</Th>
            <Th {...thProps("option_type", true)}>Type</Th>
            <Th {...thProps("expiration", true)}>Expiry</Th>
            <Th {...thProps("realized_pnl")}>P&amp;L</Th>
            <Th {...thProps("pnl_pct", true)}>P&amp;L %</Th>
            <Th {...thProps("hold_duration_mins", true)}>Hold</Th>
            <Th {...thProps("status")}>Status</Th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {sorted.length === 0 && (
            <tr>
              <td colSpan={10} className="px-4 py-8 text-center text-muted-foreground">
                No closed trades yet.
              </td>
            </tr>
          )}
          {sorted.map((trade) => (
            <tr key={trade.id} className="hover:bg-muted/50">
              <Td>
                <a href={`/trades/${trade.id}`} className="font-semibold hover:underline">
                  {trade.ticker}
                </a>
              </Td>
              <Td wide>
                <AccountBadge accountMap={accountMap} accountId={trade.account_id} />
              </Td>
              <Td wide>
                <span className="capitalize">{trade.instrument_type}</span>
              </Td>
              <Td wide>
                {trade.strike != null ? fmtMoney(trade.strike) : <span className="text-muted-foreground/40">-</span>}
              </Td>
              <Td wide>{fmtOptionType(trade.option_type)}</Td>
              <Td wide>
                {trade.expiration ? fmtDateShort(trade.expiration) : <span className="text-muted-foreground/40">-</span>}
              </Td>
              <Td>
                <span className={pnlColor(trade.realized_pnl)}>{fmt$(trade.realized_pnl)}</span>
              </Td>
              <Td wide>
                <span className={pnlColor(trade.pnl_pct)}>{fmtPct(trade.pnl_pct)}</span>
              </Td>
              <Td wide>{formatHoldDuration(trade.hold_duration_mins)}</Td>
              <Td>
                <StatusBadge status={trade.status} />
              </Td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
