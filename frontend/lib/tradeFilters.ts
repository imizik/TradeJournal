import type { Account, Trade } from "@/lib/api";

/** Exact account IDs take precedence. The legacy account-type filter remains available for older links. */
export function filterTradesByAccount<T extends Pick<Trade, "account_id">>(
  trades: T[],
  accountMap: Record<string, Pick<Account, "type">>,
  accountId?: string,
  accountType?: string,
) {
  if (accountId) return trades.filter((trade) => trade.account_id === accountId);
  if (accountType && accountType !== "all") {
    return trades.filter((trade) => accountMap[trade.account_id]?.type === accountType);
  }
  return trades;
}
