"use client";

import { useState } from "react";
import Link from "next/link";
import type { TradingViewAlert } from "@/lib/api";
import { fmtAlertTime, fmtDecimal, statusClasses, verdictClasses, verdictLabel } from "@/lib/tradingview";

type Filter = "all" | "tradeable" | "pending" | "skipped" | "error";
const CARDS: { filter: Filter; label: string; hint: string }[] = [
  { filter: "all", label: "Alerts", hint: "Most recent 200" },
  { filter: "tradeable", label: "Tradeable verdicts", hint: "Long or short scalp" },
  { filter: "pending", label: "Awaiting analysis", hint: "Pending or running" },
  { filter: "skipped", label: "Skipped", hint: "See signal details for the reason" },
  { filter: "error", label: "Errored", hint: "Analysis failed" },
];

function matches(alert: TradingViewAlert, filter: Filter) {
  if (filter === "pending") return alert.analysis_status === "pending" || alert.analysis_status === "running";
  if (filter === "tradeable") return alert.verdict === "long_scalp" || alert.verdict === "short_scalp";
  return filter === "all" || alert.analysis_status === filter;
}

export default function SignalsHistory({ alerts, initialFilter }: { alerts: TradingViewAlert[]; initialFilter: Filter }) {
  const [filter, setFilter] = useState<Filter>(initialFilter);
  function chooseFilter(value: Filter) {
    setFilter(value);
    const params = new URLSearchParams(window.location.search);
    if (value === "all") params.delete("filter"); else params.set("filter", value);
    window.history.replaceState({}, "", `${window.location.pathname}${params.size ? `?${params}` : ""}`);
  }
  function detailHref(alert: TradingViewAlert) {
    const returnTo = filter === "all" ? "/signals" : `/signals?filter=${filter}`;
    return `/signals/${encodeURIComponent(alert.alert_id)}?returnTo=${encodeURIComponent(returnTo)}`;
  }
  const visible = alerts.filter((alert) => matches(alert, filter));
  const counts = Object.fromEntries(CARDS.map((card) => [card.filter, alerts.filter((alert) => matches(alert, card.filter)).length])) as Record<Filter, number>;

  return <>
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
      {CARDS.map((card) => <button key={card.filter} type="button" onClick={() => chooseFilter(card.filter)} aria-pressed={filter === card.filter}
        className={`rounded-lg border bg-card px-4 py-3 text-left transition-colors hover:bg-secondary/60 ${filter === card.filter ? "border-primary/60 ring-1 ring-primary/30" : ""}`}>
        <span className="block text-xs text-muted-foreground">{card.label}</span>
        <span className="mt-1.5 block text-2xl font-medium tabular-nums text-foreground">{counts[card.filter]}</span>
        <span className="mt-1 block text-xs text-muted-foreground">{card.hint}</span>
      </button>)}
    </div>

    <section className="overflow-hidden rounded-lg border bg-card">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b px-3.5 py-2.5">
        <h2 className="text-[13.5px] font-semibold tracking-tight">{filter === "all" ? "Alert History" : `${CARDS.find((card) => card.filter === filter)?.label} · ${visible.length}`}</h2>
        {filter !== "all" && <button type="button" onClick={() => chooseFilter("all")} className="inline-flex min-h-9 items-center text-sm text-muted-foreground hover:text-foreground">Show all alerts</button>}
      </div>
      {alerts.length === 0 ? <div className="p-4 text-sm text-muted-foreground">No alerts received yet. New TradingView alerts will appear here automatically.</div>
        : visible.length === 0 ? <div className="p-4 text-sm text-muted-foreground">No alerts match this category.</div>
          : <>
            <ul className="divide-y sm:hidden">
              {visible.map((alert) => <li key={alert.alert_id} className="flex items-center justify-between gap-3 px-3.5 py-3">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2"><span className="font-semibold">{alert.symbol}</span><span className="text-xs capitalize text-muted-foreground">{alert.side} · {alert.timeframe}</span></div>
                  <p className="mt-1 truncate text-xs text-muted-foreground">{verdictLabel(alert.verdict)} · {alert.analysis_status}</p>
                  {(filter === "skipped" || filter === "error") && <p className="mt-1 text-xs text-muted-foreground">{alert.analysis_error_code?.replace(/_/g, " ") ?? "No reason recorded"}</p>}
                  <p className="mt-1 text-xs tabular-nums text-muted-foreground">{fmtAlertTime(alert.received_at)}</p>
                </div>
                <Link href={detailHref(alert)} className="inline-flex min-h-11 shrink-0 items-center px-2 text-sm font-medium text-foreground underline underline-offset-2">Detail</Link>
              </li>)}
            </ul>
            <div className="hidden overflow-x-auto sm:block">
              <table className="w-full min-w-[1100px] text-sm">
                <thead className="border-b text-xs font-medium text-muted-foreground"><tr>{["Received", "Symbol", "Setup", "Side", "TF", "Price", "Verdict", "Confidence", "Status", ""].map((label, index) => <th key={`${label}-${index}`} className="px-4 py-2 text-left font-medium">{label}</th>)}</tr></thead>
                <tbody>{visible.map((alert) => <tr key={alert.alert_id} className="border-t hover:bg-secondary/40">
                  <td className="whitespace-nowrap px-4 py-2 tabular-nums text-muted-foreground">{fmtAlertTime(alert.received_at)}</td>
                  <td className="px-4 py-2 font-medium text-foreground">{alert.symbol}</td><td className="px-4 py-2 text-muted-foreground">{alert.setup}</td>
                  <td className="px-4 py-2 capitalize">{alert.side}</td><td className="px-4 py-2 text-muted-foreground">{alert.timeframe}</td>
                  <td className="px-4 py-2 tabular-nums">{fmtDecimal(alert.price)}</td>
                  <td className="px-4 py-2"><span className={`inline-flex h-[22px] items-center whitespace-nowrap rounded-md px-2 text-[11.5px] font-medium capitalize ${verdictClasses(alert.verdict)}`}>{verdictLabel(alert.verdict)}</span></td>
                  <td className="px-4 py-2 capitalize text-muted-foreground">{alert.confidence ?? "—"}</td>
                  <td className="px-4 py-2"><span className={`inline-flex h-[22px] items-center whitespace-nowrap rounded-md px-2 text-[11.5px] font-medium capitalize ${statusClasses(alert.analysis_status)}`}>{alert.analysis_status}</span>
                    {(filter === "skipped" || filter === "error") && <p className="mt-1 text-xs text-muted-foreground">{alert.analysis_error_code?.replace(/_/g, " ") ?? "No reason recorded"}</p>}</td>
                  <td className="px-4 py-2 text-right"><Link href={detailHref(alert)} className="inline-flex min-h-9 items-center text-xs font-medium text-foreground underline underline-offset-2">Detail</Link></td>
                </tr>)}</tbody>
              </table>
            </div>
          </>}
    </section>
  </>;
}
