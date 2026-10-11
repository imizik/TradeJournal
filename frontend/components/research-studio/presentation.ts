import type { Definition } from "./types";

export const field = "w-full min-w-0 rounded-md border bg-background px-3 py-2 text-sm outline-none focus:ring-1 focus:ring-ring";
export const button = "inline-flex items-center justify-center gap-2 rounded-md border px-3 py-2 text-sm font-medium transition-colors hover:bg-secondary disabled:cursor-not-allowed disabled:opacity-40";
export const primary = button + " bg-primary text-primary-foreground hover:bg-primary/90";
export const card = "min-w-0 rounded-lg border bg-card p-4 sm:p-5";
export const titles: Record<string,string> = {
  minutes: "Time since the open", rvol: "Relative volume", gap: "Opening gap",
  day_move: "Move since yesterday", trend: "Distance from the 20-day average",
  trend_slope: "Five-session trend", rel_strength: "Strength versus SPY",
  spy_trend: "SPY trend", spy_day: "SPY daily move", vwap_distance: "Distance from session VWAP",
  vol_ratio: "Short versus long volatility", spy_vol: "SPY volatility",
  open_trend: "Opening trend position", move_15m_atr: "15-minute price move",
};
export const n = (v: number | null | undefined) => v == null ? "Unavailable" : v.toFixed(3);
export const et = (stamp: string) => new Date(stamp).toLocaleString("en-US", {timeZone:"America/New_York",dateStyle:"medium",timeStyle:"short"});
export const time = (minute: number) => Number.isFinite(minute) ? String(Math.floor(minute/60)).padStart(2,"0")+":"+String(minute%60).padStart(2,"0") : "";
export const minutes = (clock: string) => clock ? Number(clock.slice(0,2))*60+Number(clock.slice(3,5)) : 0;
export const horizonLabel = (h: string) => h === "session_close" ? "Session close" : h.replace("m"," minutes");
export const returnValue = (v: number | null | undefined, unit: string, difference=false) =>
  v == null ? "Unavailable" : n(v)+(unit==="percent" ? difference ? " pp" : "%" : " ATR");
export function question(d: Definition) {
  return d.predicates.map(p => {
    const label=titles[p.feature] || p.feature;
    const unit=p.feature==="rvol" ? "×" : p.feature==="minutes" ? " min" : p.feature==="rel_strength" ? " pp" : p.feature==="spy_vol" ? "%" : p.feature==="vol_ratio" ? " (ATR5 / ATR20)" : p.feature==="vwap_distance" ? " chart ATR14" : p.feature.startsWith("spy_") ? " SPY daily ATR14" : " daily ATR14";
    const bound=p.minimum!==null && p.maximum!==null ? "between "+p.minimum+unit+" and "+p.maximum+unit :
      p.minimum!==null ? "at least "+p.minimum+unit : "at most "+p.maximum+unit;
    return label.toLowerCase()+" "+bound;
  }).join(" · ");
}
