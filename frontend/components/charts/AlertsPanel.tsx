import { Bell, BellOff, RotateCcw, Trash2 } from "lucide-react";
import { alertText, deliveryText } from "@/lib/alerts";
import type { AlertsPayload, LevelAlert } from "@/lib/alerts";
import { etTime, price } from "@/lib/charts";

const MAX_ACTIVE = 20;

/**
 * Every level alert (C5.1), whichever symbol is charted: what it waits for,
 * whether it fired and when, and what happened to the phone message. Alerts are
 * made from the chart menu; here they are re-armed or removed. `prices` holds
 * each alert's price on the chart's basis where its symbol is on screen.
 */
export default function AlertsPanel({ data, prices, narrow, onRearm, onRemove }: {
  data: AlertsPayload | null; prices: Map<string, number>; narrow: boolean;
  onRearm(alert: LevelAlert): void; onRemove(alert: LevelAlert): void;
}) {
  const alerts = data?.alerts ?? [];
  const active = alerts.filter((alert) => alert.state === "active").length;
  const icon = `inline-flex shrink-0 items-center justify-center rounded text-slate-500 hover:bg-slate-800 ${narrow ? "h-11 w-11" : "h-6 w-6"}`;
  return <section className="border-t border-slate-700/40 p-3" aria-label="Price alerts">
    <div className="mb-2 flex items-center justify-between"><h2 className="text-xs font-medium text-slate-200">Alerts</h2>
      <span className="text-[10px] text-slate-600">{active}/{MAX_ACTIVE} active</span></div>
    {data && !data.phone && <p className="mb-2 text-[10px] leading-4 text-amber-300">Phone alerts are not set up on this server, so alerts show here only.</p>}
    {alerts.length ? <ul className="space-y-2">{alerts.map((alert) => {
      const shown = prices.get(alert.id) ?? alert.price;
      const text = `${alert.symbol} ${alertText(alert, shown)}`;
      const event = alert.event;
      return <li key={alert.id} className="text-[11px]" aria-label={`${text}, ${alert.state}`}>
        <div className="flex items-center gap-1.5">
          {alert.state === "active" ? <Bell size={12} className="shrink-0 text-amber-300" aria-hidden /> : <BellOff size={12} className="shrink-0 text-slate-500" aria-hidden />}
          <span className={`min-w-0 flex-1 truncate ${alert.state === "active" ? "text-slate-200" : "text-slate-500"}`} title={alert.label}>{text}</span>
          {alert.state === "fired" && <button aria-label={`Re-arm ${text}`} title="Arm it again from the current price" onClick={() => onRearm(alert)} className={`${icon} hover:text-slate-200`}><RotateCcw size={12} /></button>}
          <button aria-label={`Remove ${text}`} title="Remove this alert" onClick={() => onRemove(alert)} className={`${icon} hover:text-rose-300`}><Trash2 size={12} /></button>
        </div>
        <p className="ml-[18px] truncate text-[10px] text-slate-500">{[alert.label, alert.session === "extended" ? "extended hours" : "regular hours"].filter(Boolean).join(" · ")}</p>
        {event && <p className="ml-[18px] text-[10px] text-slate-400">
          Fired {etTime(event.event_at, true)} {etTime(event.event_at)} ET at {price(event.price)}{event.source === "minute_bars" ? " (1-minute bar)" : ""} · <span
            className={event.delivery === "sent" ? "text-emerald-400" : "text-amber-300"} title={event.error ?? undefined}>{deliveryText(event, !!data?.phone)}</span></p>}
      </li>;
    })}</ul> : <p className="text-[11px] leading-5 text-slate-500">Right-click (long-press on a phone) a level, a horizontal ray or an automatic level to set an alert. It reaches your phone with this page closed.</p>}
  </section>;
}
