import type { IPrimitivePaneRenderer, IPrimitivePaneView, ISeriesApi, ISeriesPrimitive, SeriesAttachedParameter, SeriesType, Time } from "lightweight-charts";
import { apiUrl } from "./api";
import { etTime, price } from "./charts";
import type { Interval } from "./charts";

/**
 * Level alerts (C5.1). The server judges them whether or not a chart is open
 * and sends the phone message; the chart draws a bell at each one's price and
 * lists them. Prices are on the chart's split-adjusted basis as of `created_on`,
 * moved by later splits as a saved level is.
 */
export type AlertCondition = "touches" | "crosses" | "closes_beyond";
export type AlertEvent = {
  level: number; price: number; source: "stream" | "minute_bars" | "closed_bar"; event_at: number; detected_at: number;
  delivery: "pending" | "sending" | "sent" | "expired"; attempts: number; delivered_at: number | null; error: string | null;
};
export type LevelAlert = {
  id: string; symbol: string; price: number; created_on: string; condition: AlertCondition; interval: Interval | null;
  session: "regular" | "extended"; direction: "up" | "down"; source_kind: "level" | "drawing" | "auto"; source_id: string | null;
  label: string; state: "active" | "fired"; armed_at: number; event: AlertEvent | null;
};
/** Every alert, and whether this server can send to the phone. */
export type AlertsPayload = { alerts: LevelAlert[]; phone: boolean };
/** What a new alert is made from: a level, a horizontal ray or an automatic level, at a price on today's basis. */
export type AlertSource = { kind: LevelAlert["source_kind"]; id: string; label: string; price: number };
export const CLOSE_INTERVALS: Interval[] = ["1m", "3m", "5m", "15m", "30m", "1h", "4h"];

async function send(path: string, method: "POST" | "DELETE", body?: unknown): Promise<AlertsPayload> {
  const response = await fetch(apiUrl(path), { method, cache: "no-store", headers: body ? { "Content-Type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined });
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new Error(typeof data?.detail === "string" ? data.detail : "The alert could not be saved. Try again.");
  return data as AlertsPayload;
}
export const createAlert = (body: { symbol: string; price: number; reference: number; condition: AlertCondition; interval: Interval | null;
  session: LevelAlert["session"]; source_kind: AlertSource["kind"]; source_id: string; label: string }) => send("/charts/alerts", "POST", body);
export const rearmAlert = (id: string, value: number, reference: number) => send(`/charts/alerts/${id}/rearm`, "POST", { price: value, reference });
export const removeAlert = (id: string) => send(`/charts/alerts/${id}`, "DELETE");

/** "Crosses above 581.20", "Touches 581.20", "5m close below 581.20". */
export function alertText(alert: Pick<LevelAlert, "condition" | "interval" | "direction">, at: number): string {
  const side = alert.direction === "up" ? "above" : "below";
  return alert.condition === "touches" ? `Touches ${price(at)}` : alert.condition === "crosses" ? `Crosses ${side} ${price(at)}` : `${alert.interval} close ${side} ${price(at)}`;
}
/** What happened to the phone message. */
export function deliveryText(event: AlertEvent, phone: boolean): string {
  if (event.delivery === "sent") return `Sent to phone ${event.delivered_at ? `${etTime(event.delivered_at)} ET` : ""}`.trim();
  if (event.delivery === "expired") return "Not sent: over six hours late";
  if (!phone) return "Not sent: phone alerts are not set up on this server";
  return event.attempts ? `Retrying phone message (${event.attempts} tries)` : "Sending to phone…";
}

// ---- the bell on the chart ----

type Target = Parameters<IPrimitivePaneRenderer["draw"]>[0];
export type AlertMark = { id: string; price: number; fired: boolean };
const ACTIVE = "#f4c66b";
const FIRED = "#64748b";

/** A bell at each alert's price, at the pane's right edge just below the line: amber while armed, gray once fired. */
export class AlertLayer implements ISeriesPrimitive<Time> {
  private marks: AlertMark[] = [];
  private placed: (AlertMark & { y: number })[] = [];
  private series: ISeriesApi<SeriesType, Time> | null = null;
  private requestUpdate: (() => void) | null = null;
  private readonly renderer: IPrimitivePaneRenderer = { draw: (target) => this.draw(target) };
  private readonly views: readonly IPrimitivePaneView[] = [{ zOrder: () => "top", renderer: () => this.renderer }];

  attached({ series, requestUpdate }: SeriesAttachedParameter<Time>) { this.series = series; this.requestUpdate = requestUpdate; }
  detached() { this.series = null; this.requestUpdate = null; }
  set(marks: AlertMark[]) { this.marks = marks; this.updateAllViews(); this.requestUpdate?.(); }
  updateAllViews() {
    const series = this.series;
    this.placed = series ? this.marks.flatMap((mark) => { const y = series.priceToCoordinate(mark.price); return y === null ? [] : [{ ...mark, y }]; }) : [];
  }
  paneViews() { return this.views; }

  private draw(target: Target) {
    target.useBitmapCoordinateSpace(({ context, bitmapSize, horizontalPixelRatio: h, verticalPixelRatio: v }) => {
      context.save();
      for (const { y, fired } of this.placed) {
        const cx = bitmapSize.width - 12 * h, cy = (y + 9) * v, r = 5 * h;
        if (cy < -2 * r || cy > bitmapSize.height + 2 * r) continue;
        context.fillStyle = "#10151e";
        context.beginPath();
        context.arc(cx, cy, r * 1.6, 0, Math.PI * 2);
        context.fill();
        context.fillStyle = fired ? FIRED : ACTIVE;
        context.beginPath();
        context.moveTo(cx - r, cy + r * 0.55);
        context.lineTo(cx + r, cy + r * 0.55);
        context.lineTo(cx + r * 0.7, cy + r * 0.2);
        context.lineTo(cx + r * 0.7, cy - r * 0.2);
        context.arc(cx, cy - r * 0.2, r * 0.7, 0, Math.PI, true);
        context.lineTo(cx - r * 0.7, cy + r * 0.2);
        context.closePath();
        context.fill();
        context.beginPath();
        context.arc(cx, cy + r * 0.85, r * 0.25, 0, Math.PI * 2);
        context.fill();
      }
      context.restore();
    });
  }
}
