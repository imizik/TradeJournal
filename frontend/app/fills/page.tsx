import { api, Account, Fill } from "@/lib/api";
import ManualFillForm from "@/components/ManualFillForm";

function sourceLabel(fill: Fill) {
  return fill.raw_email_id.startsWith("manual:") ? "Manual" : "Email";
}

function fmtDateTime(value: string) {
  return new Date(value).toLocaleString();
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
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-foreground">Fills</h1>
        <p className="mt-2 max-w-3xl text-sm text-muted-foreground">
          Email imports land here automatically, and manual fills let you backfill historical entries that never
          existed in Gmail. This is the right place for transferred positions, missing cost basis, and older starter
          lots you want included in your trade reconstruction.
        </p>
      </div>

      <ManualFillForm accounts={accounts} />

      <section className="overflow-hidden rounded-lg border bg-card">
        <div className="border-b px-5 py-4">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Fill History
          </h2>
        </div>

        {fills.length === 0 ? (
          <div className="px-5 py-8 text-sm text-muted-foreground">
            No fills yet. Import email fills or add a manual fill above.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1280px] text-sm">
              <thead className="bg-muted text-xs uppercase text-muted-foreground">
                <tr>
                  <Th>Executed</Th>
                  <Th>Account</Th>
                  <Th>Ticker</Th>
                  <Th>Instrument</Th>
                  <Th>Side</Th>
                  <Th>Qty</Th>
                  <Th>Price</Th>
                  <Th>Underlying</Th>
                  <Th>IV</Th>
                  <Th>Delta</Th>
                  <Th>RSI</Th>
                  <Th>Source</Th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {fills.map((fill) => {
                  const href = `/fills/${fill.id}?returnTo=${encodeURIComponent("/fills")}`;
                  return (
                    <tr key={fill.id} className="relative hover:bg-muted/50">
                      <Td>
                        <a href={href} className="absolute inset-0" aria-label={`View fill ${fill.id}`} />
                        {fmtDateTime(fill.executed_at)}
                      </Td>
                      <Td>{accountMap[fill.account_id]?.name ?? "-"}</Td>
                      <Td>
                        <div className="flex flex-col">
                          <span className="font-semibold">{fill.ticker}</span>
                          <span className="text-xs text-muted-foreground">{detailLabel(fill)}</span>
                        </div>
                      </Td>
                      <Td>
                        <span className="capitalize">{fill.instrument_type}</span>
                      </Td>
                      <Td>{fill.side}</Td>
                      <Td>{fmtQty(fill)}</Td>
                      <Td>{fmtPrice(fill)}</Td>
                      <Td>{fill.underlying_price_at_fill != null ? `$${fill.underlying_price_at_fill.toFixed(2)}` : "-"}</Td>
                      <Td>{fill.iv_at_fill != null ? `${(fill.iv_at_fill * 100).toFixed(1)}%` : "-"}</Td>
                      <Td>{fill.delta_at_fill != null ? fill.delta_at_fill.toFixed(2) : "-"}</Td>
                      <Td>{fill.rsi_14_at_fill != null ? fill.rsi_14_at_fill.toFixed(1) : "-"}</Td>
                      <Td>
                        <span
                          className={`relative z-10 rounded px-1.5 py-0.5 text-xs font-medium ${
                            sourceLabel(fill) === "Manual"
                              ? "bg-amber-900/30 text-amber-300"
                              : "bg-sky-900/30 text-sky-300"
                          }`}
                        >
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

function Th({ children }: { children: React.ReactNode }) {
  return <th className="px-4 py-2 text-left font-medium">{children}</th>;
}

function Td({ children }: { children: React.ReactNode }) {
  return <td className="px-4 py-3 align-top">{children}</td>;
}
