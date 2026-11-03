import { api } from "@/lib/serverApi";
import type { Account, Fill } from "@/lib/api";
import { AddManualFill } from "@/components/ManualFillForm";
import { cn } from "@/lib/utils";
import { wallClockET } from "@/lib/format";

function sourceLabel(fill: Fill) {
  return fill.raw_email_id.startsWith("manual:") ? "Manual" : "Email";
}

function fmtDateTime(value: string) {
  return wallClockET(value, { year: true, seconds: true });
}

// Phones drop the year and seconds so the price column still fits; the time and "ET" wrap as one piece.
function fmtDateTimeShort(value: string) {
  return wallClockET(value).replace(/ (AM|PM) ET$/, " $1 ET");
}

function fmtPrice(fill: Fill) {
  return `$${fill.price.toFixed(2)}`;
}

function fmtQty(fill: Fill) {
  const rounded = Number(fill.contracts.toFixed(6));
  return String(rounded);
}

function detailLabel(fill: Fill) {
  if (fill.instrument_type === "stock") return "Stock";
  const optionType = fill.option_type ? fill.option_type.toUpperCase() : "-";
  const strike = fill.strike != null ? `$${fill.strike}` : "-";
  const expiration = fill.expiration ?? "-";
  return `${optionType} ${strike} | ${expiration}`;
}

export default async function FillsPage() {
  const [fills, accounts] = await Promise.all([api.fills(), api.accounts()]);
  const accountMap = Object.fromEntries(accounts.map((account: Account) => [account.id, account]));

  return (
    <div className="space-y-4">
      <AddManualFill accounts={accounts}>
        <div className="flex items-baseline gap-2">
          <h1 className="text-xl font-semibold">Fills</h1>
          <span className="text-sm tabular-nums text-muted-foreground">{fills.length} recorded</span>
        </div>
        <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
          Fills from your broker emails arrive here automatically. Add a manual fill for anything Gmail never had:
          transferred positions, missing cost basis or older starter lots.
        </p>
      </AddManualFill>

      <section className="overflow-hidden rounded-lg border bg-card">
        <div className="border-b px-3.5 py-2.5">
          <h2 className="text-[13.5px] font-semibold tracking-tight">
            Fill History
          </h2>
        </div>

        {fills.length === 0 ? (
          <div className="p-4 text-sm text-muted-foreground">
            No fills yet. Import email fills or add a manual fill.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm sm:min-w-[1280px]">
              <thead className="border-b text-xs font-medium text-muted-foreground">
                <tr>
                  <Th>Executed</Th>
                  <Th wide>Account</Th>
                  <Th>Ticker</Th>
                  <Th wide>Instrument</Th>
                  <Th>Side</Th>
                  <Th>Qty</Th>
                  <Th>Price</Th>
                  <Th wide>Underlying</Th>
                  <Th wide>IV</Th>
                  <Th wide>Delta</Th>
                  <Th wide>RSI</Th>
                  <Th wide>Source</Th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {fills.map((fill) => {
                  const href = `/fills/${fill.id}?returnTo=${encodeURIComponent("/fills")}`;
                  return (
                    <tr key={fill.id} className="relative hover:bg-muted/50">
                      <Td num>
                        <a href={href} className="absolute inset-0" aria-label={`View fill ${fill.id}`} />
                        <span className="sm:hidden">{fmtDateTimeShort(fill.executed_at)}</span>
                        <span className="hidden sm:inline">{fmtDateTime(fill.executed_at)}</span>
                      </Td>
                      <Td wide>{accountMap[fill.account_id]?.name ?? "-"}</Td>
                      <Td>
                        <div className="flex flex-col">
                          <span className="font-semibold">{fill.ticker}</span>
                          <span className="text-xs text-muted-foreground">{detailLabel(fill)}</span>
                        </div>
                      </Td>
                      <Td wide>
                        <span className="capitalize">{fill.instrument_type}</span>
                      </Td>
                      <Td>{fill.side}</Td>
                      <Td num>{fmtQty(fill)}</Td>
                      <Td num>{fmtPrice(fill)}</Td>
                      <Td wide num>{fill.underlying_price_at_fill != null ? `$${fill.underlying_price_at_fill.toFixed(2)}` : "-"}</Td>
                      <Td wide num>{fill.iv_at_fill != null ? `${(fill.iv_at_fill * 100).toFixed(1)}%` : "-"}</Td>
                      <Td wide num>{fill.delta_at_fill != null ? fill.delta_at_fill.toFixed(2) : "-"}</Td>
                      <Td wide num>{fill.rsi_14_at_fill != null ? fill.rsi_14_at_fill.toFixed(1) : "-"}</Td>
                      <Td wide>
                        <span className="relative z-10 inline-flex h-[22px] items-center rounded-md bg-secondary px-2 text-[11.5px] font-medium text-muted-foreground">
                          {sourceLabel(fill)}
                        </span>
                      </Td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

// Phones keep executed time, ticker, side, quantity and price; the enrichment
// columns return from sm up, and a row still opens the full fill.
function Th({ children, wide }: { children: React.ReactNode; wide?: boolean }) {
  return <th className={cn("px-1 py-2 text-left font-medium sm:px-4", wide && "hidden sm:table-cell")}>{children}</th>;
}

function Td({ children, wide, num }: { children: React.ReactNode; wide?: boolean; num?: boolean }) {
  return <td className={cn("px-1 py-3 align-top sm:px-4", wide && "hidden sm:table-cell", num && "tabular-nums")}>{children}</td>;
}
