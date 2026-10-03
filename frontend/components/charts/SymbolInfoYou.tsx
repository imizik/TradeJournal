import Link from "next/link";
import type { SymbolJournal, SymbolTrade } from "@/lib/symbolInfo";

const money = (value: number | null) => value == null ? "—" : value.toLocaleString("en-US", { style: "currency", currency: "USD" });
const wallTime = (value: string | null) => value ? `${value.slice(0, 10)} ${value.slice(11, 16)} ET` : "—";
const holding = (minutes: number | null) => minutes == null ? "—" : minutes < 60 ? `${Math.round(minutes)} min` : minutes < 1440 ? `${(minutes / 60).toFixed(1)} h` : `${(minutes / 1440).toFixed(1)} d`;
const contract = (trade: SymbolTrade) => trade.instrument_type === "stock" ? "Stock" : `${trade.strike ?? "—"} ${trade.option_type ?? "option"} · ${trade.expiration ?? "—"}`;

function TradeLink({ trade, symbol }: { trade: SymbolTrade; symbol: string }) {
  return <Link href={`/trades/${trade.id}`} className="block rounded px-1 py-2 hover:bg-slate-800 focus-visible:outline-sky-400">
    <span className="flex justify-between gap-2 text-slate-300"><span className="min-w-0 break-words">{symbol} · {contract(trade)}</span><span className="shrink-0 font-mono">{money(trade.realized_pnl)}</span></span>
    <span className="mt-1 block text-[10px] text-slate-500">{trade.account_name} · {trade.last4} · {trade.status}</span>
    <span className="block text-[10px] text-slate-500">{wallTime(trade.closed_at ?? trade.opened_at)}</span>
  </Link>;
}

export default function SymbolInfoYou({ data }: { data: SymbolJournal }) {
  const checked = new Date(data.as_of).toLocaleString("en-US", { timeZone: "America/New_York", timeZoneName: "short" });
  return <div className="space-y-4 text-[11px]">
    <p className="text-[10px] text-slate-500" title={`Read ${checked}`}>{data.source} · as of {checked}</p>
    {!data.total_trades ? <p className="text-slate-400">No trades on this symbol</p> : <>
      <p className="text-[10px] leading-4 text-slate-500">All journal history. Results use completed trades, including expirations. Open trades are separate.</p>
      <dl className="grid grid-cols-2 gap-x-3 gap-y-3">
        {([
          ["Closed trades", data.closed_trades, "Observed · stored closed and expired trades"],
          ["Realized P&L", money(data.realized_pnl), "Calculated · sum of stored completed-trade P&L; no reconstruction"],
          ["Win rate", data.win_rate == null ? "—" : `${(data.win_rate * 100).toFixed(1)}%`, "Calculated · positive P&L / completed trades; breakeven is not a win"],
          ["Average hold", holding(data.average_hold_mins), `Calculated · ${data.hold_samples} of ${data.closed_trades} completed trades with a stored hold time`],
        ] as const).map(([label, value, note]) => <div key={label} title={`${note} · read ${checked}`}><dt className="text-slate-500">{label}</dt><dd className="mt-1 font-mono text-sm text-slate-200">{value}</dd></div>)}
      </dl>
      {!!data.missing_pnl && <p className="text-amber-300">{data.missing_pnl} completed trades have no P&L. Total and win rate unavailable; best/worst use known results.</p>}
      <div title={`Observed · latest journal fill · read ${checked}`}><span className="text-slate-500">Last traded</span><p className="mt-1 text-slate-300">{wallTime(data.last_traded_at)}</p></div>
      <div><h3 className="text-slate-400">Open positions · {data.open_positions.length} trades</h3>
        {data.open_positions.length ? <><p className="mt-1 text-[10px] text-slate-500">P&L shown is realized on partial exits, when available.</p>{data.open_positions.map((trade) => <TradeLink key={trade.id} trade={trade} symbol={data.symbol} />)}</> : <p className="mt-1 text-slate-500">No open positions</p>}</div>
      <div title={`Calculated · ranked by stored completed-trade P&L · read ${checked}`}><h3 className="text-slate-400">Best trade</h3>{data.best_trade ? <TradeLink trade={data.best_trade} symbol={data.symbol} /> : <p className="mt-1 text-slate-500">—</p>}</div>
      <div title={`Calculated · ranked by stored completed-trade P&L · read ${checked}`}><h3 className="text-slate-400">Worst trade</h3>{data.worst_trade ? <TradeLink trade={data.worst_trade} symbol={data.symbol} /> : <p className="mt-1 text-slate-500">—</p>}</div>
      <div><h3 className="text-slate-400">Recent trades</h3><p className="mt-1 text-[10px] text-slate-500">Latest close or opening · observed</p>{data.recent_trades.map((trade) => <TradeLink key={trade.id} trade={trade} symbol={data.symbol} />)}</div>
    </>}
  </div>;
}
