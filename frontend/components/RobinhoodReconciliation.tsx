import type { RobinhoodReconciliation as Reconciliation, RobinhoodReconciliationRow as Row } from "@/lib/api";
import { contractName, wallClockET } from "@/lib/format";

// docs/robinhood-order-fills.md: how Robinhood's order history pairs with the journal's fills. Read only; nothing here
// changes a fill. Problems come first; a mismatch shows both versions for the owner to correct by hand.
const OUTCOMES: Record<Row["outcome"], string> = {
  mismatch: "Mismatch",
  order_only: "Robinhood only",
  email_only: "Email only",
  pending: "Waiting for email",
  matched: "Matched",
};

const SOURCES: Record<string, string> = { email: "Email", manual: "Manual", roll: "Roll", robinhood: "Robinhood" };

function contract(row: Row) {
  return row.instrument === "stock" ? `${row.ticker} stock` : contractName(row);
}

function amount(contracts: number | null, price: number | null) {
  if (contracts == null || price == null) return "-";
  return `${Number(contracts.toFixed(6))} @ $${price.toFixed(2)}`;
}

function when(value: string | null) {
  return value ? wallClockET(value, { seconds: true }) : "";
}

function action(row: Row) {
  if (row.action === "wrote_fill") return "Written to the journal";
  if (row.action === "would_write_fill") return "Would be written (shadow)";
  return null;
}

export function RobinhoodReconciliation({ data }: { data: Reconciliation }) {
  const problems = data.rows.filter((row) => row.outcome !== "matched");
  const matched = data.counts.matched ?? 0;
  const last = data.last_pass.at ? wallClockET(new Date(data.last_pass.at * 1000).toISOString()) : null;
  return (
    <section className="overflow-hidden rounded-lg border bg-card" aria-label="Robinhood order history">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 border-b px-3.5 py-2.5">
        <h2 className="text-[13.5px] font-semibold tracking-tight">Robinhood order history</h2>
        <span className="text-xs text-muted-foreground">
          {data.mode === "shadow" ? "Shadow: recording only, no fill written" : data.mode === "on" ? "On" : "Off"}
          {data.feed === "off" ? " · read feed off" : ""}
          {last ? ` · last read ${last} (${data.last_pass.state})` : ""}
        </span>
        <span className="ml-auto text-xs tabular-nums text-muted-foreground">
          {(Object.keys(OUTCOMES) as Row["outcome"][]).map((key) => `${OUTCOMES[key]} ${data.counts[key] ?? 0}`).join(" · ")}
          {` · last ${data.days} days`}
        </span>
      </div>
      {problems.length === 0 ? (
        <div className="p-3.5 text-sm text-muted-foreground">
          {matched ? `Every order in the last ${data.days} days matches a fill in the journal.` : "No orders read yet."}
        </div>
      ) : (
        <ul className="divide-y divide-border text-sm">
          {problems.map((row, i) => (
            <li key={`${row.outcome}-${row.order?.ref ?? row.journal?.fill_id ?? i}`} className="grid gap-1 px-3.5 py-2.5 sm:grid-cols-[9rem_1fr_1fr]">
              <div>
                <span className="font-medium">{OUTCOMES[row.outcome]}</span>
                <div className="text-xs text-muted-foreground">
                  {row.account.label} {row.account.masked}
                </div>
              </div>
              <div>
                <span className="font-semibold">{contract(row)}</span>{" "}
                <span className="text-muted-foreground">
                  {row.side}
                  {row.recurring ? " · recurring buy" : ""}
                </span>
                {row.note ? <div className="text-xs text-muted-foreground">{row.note}</div> : null}
                {action(row) ? <div className="text-xs font-medium">{action(row)}</div> : null}
              </div>
              <div className="grid gap-0.5 text-xs tabular-nums">
                <div>
                  <span className="text-muted-foreground">Robinhood: </span>
                  {row.order ? `${amount(row.order.contracts, row.order.price)} ${when(row.order.last_at)} · order …${row.order.ref}` : "-"}
                </div>
                <div>
                  <span className="text-muted-foreground">Journal: </span>
                  {row.journal
                    ? `${amount(row.journal.contracts, row.journal.price)} ${when(row.journal.at)} · ${SOURCES[row.journal.source] ?? row.journal.source}`
                    : "-"}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
