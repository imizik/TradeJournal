"use client";

/**
 * The desk's "what's moving" strip (docs/copilot-lab.md § The desk): one thin row that answers "where is the action
 * today?". Group tiles first (SPY, QQQ, IWM, the sector ETFs, his Watching list and his Research groups), coloured by
 * the day's change; then the day's biggest movers, his names first, each with a short reason only when the app already
 * has one. A tile selects its symbol on the desk in place; a group tile lists its members to pick from. Quiet by
 * design: no counts, badges or anything to rate or dismiss. The sign and number are always written out, so the colour
 * is never the only signal.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { useKeptState } from "@/components/copilot/DeskMemory";
import { deskGet, everyDeskMinute } from "@/lib/deskMinute";
import { nyDay } from "@/lib/desk";
import { cn } from "@/lib/utils";

export type MovingMember = { symbol: string; change_pct: number | null };
export type MovingGroup = { key: string; label: string; kind: "index" | "sector" | "watching" | "research"; symbol: string | null;
  change_pct: number; members: MovingMember[] };
export type MovingMover = { symbol: string; change_pct: number; mine: boolean; reason?: string | null };
export type DeskMoving = { state: "ok" | "unavailable"; mode: "live" | "close" | null; session: string | null; as_of: string;
  reason: string | null; groups: MovingGroup[]; movers: MovingMover[] };

const COLLAPSED_KEY = "desk.moving.collapsed.v1";

export async function getDeskMoving(signal?: AbortSignal): Promise<DeskMoving> {
  const response = await deskGet("/copilot/desk/moving", signal);
  if (!response.ok) {
    await response.text().catch(() => ""); // read the refusal through, so the request ends (an unread body holds it open)
    throw new Error(`Request failed (${response.status}).`);
  }
  return await response.json() as DeskMoving;
}

/** ``GET /copilot/desk/moving`` on open and once a minute while the page shows; the last good read is kept for the
 * desk's remount. ``failed`` once a read fails with nothing in hand. */
function useMoving(on: boolean): { data: DeskMoving | null; failed: boolean } {
  const [data, setData] = useKeptState<DeskMoving | null>("desk.moving", null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (!on) return;
    let controller = new AbortController();
    const read = () => {
      controller.abort();
      controller = new AbortController();
      getDeskMoving(controller.signal).then(next => { setData(next); setFailed(false); })
        .catch(error => { if ((error as Error).name !== "AbortError") setFailed(true); });
    };
    read();
    const stop = everyDeskMinute(read);
    return () => { controller.abort(); stop(); };
  }, [on, setData]);
  return { data, failed };
}

/** "+1.2%" / "−0.8%" with an arrow, so the direction reads without colour. */
export function pctText(value: number): string {
  const arrow = value > 0 ? "▲" : value < 0 ? "▼" : "";
  return `${arrow}${value > 0 ? "+" : value < 0 ? "−" : ""}${Math.abs(value).toFixed(1)}%`;
}

/** The tile's tint: four steps each way by the size of the move, the desk's emerald and rose. */
export function heat(value: number): string {
  const size = Math.abs(value);
  const step = size < 0.25 ? 0 : size < 1 ? 1 : size < 2.5 ? 2 : 3;
  if (step === 0) return "border-border bg-secondary/40";
  return value > 0
    ? ["", "border-emerald-500/20 bg-emerald-500/10", "border-emerald-500/30 bg-emerald-500/20", "border-emerald-400/45 bg-emerald-500/35"][step]
    : ["", "border-rose-500/20 bg-rose-500/10", "border-rose-500/30 bg-rose-500/20", "border-rose-400/45 bg-rose-500/35"][step];
}

const numberTone = (value: number | null) => value == null || Math.abs(value) < 0.05 ? "text-muted-foreground" : value > 0 ? "text-emerald-200" : "text-rose-200";

function closeLabel(data: DeskMoving): string {
  if (data.mode !== "close" || !data.session) return "";
  if (data.session === nyDay(new Date(data.as_of))) return "At the close";
  const day = new Date(`${data.session}T12:00:00Z`).toLocaleDateString("en-US", { weekday: "short", timeZone: "UTC" });
  return `At ${day}'s close`;
}

const TILE = "inline-flex h-7 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-md border px-2 text-xs focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary";

/**
 * The strip. ``onSelect`` puts a symbol on the desk in place (the chart switches and the copilot follows); nothing here
 * navigates. Collapsed, it is one short line; the choice is remembered on this device.
 */
export function MovingStrip({ on, selected, onSelect }: { on: boolean; selected: string | null; onSelect(symbol: string): void }) {
  const { data, failed } = useMoving(on);
  const [collapsed, setCollapsed] = useState(false);
  const [open, setOpen] = useState<{ key: string; left: number; top: number } | null>(null);
  const popover = useRef<HTMLDivElement>(null);
  useEffect(() => {
    try { setCollapsed(window.localStorage.getItem(COLLAPSED_KEY) === "1"); } catch { /* the default: open */ } // eslint-disable-line react-hooks/set-state-in-effect -- read once after mount, the server render has no storage
  }, []);
  const toggle = () => {
    const next = !collapsed;
    setCollapsed(next);
    setOpen(null);
    try { window.localStorage.setItem(COLLAPSED_KEY, next ? "1" : "0"); } catch { /* this view only */ }
  };
  const close = useCallback(() => setOpen(null), []);
  useEffect(() => {
    if (!open) return;
    // Its own tile is not "away": the tile's click toggles it shut.
    const inside = (target: EventTarget | null) => target instanceof Node && (!!popover.current?.contains(target)
      || !!(target instanceof Element && target.closest(`[data-moving-key="${CSS.escape(open.key)}"]`)));
    const away = (event: Event) => { if (!inside(event.target)) close(); };
    const key = (event: KeyboardEvent) => { if (event.key === "Escape") close(); };
    // It is placed where its tile was: any scroll but its own list's moves the tile away from it.
    const scrolled = (event: Event) => { if (!popover.current?.contains(event.target as Node)) close(); };
    document.addEventListener("pointerdown", away, true);
    document.addEventListener("keydown", key);
    window.addEventListener("resize", close);
    window.addEventListener("scroll", scrolled, true);
    return () => {
      document.removeEventListener("pointerdown", away, true); document.removeEventListener("keydown", key);
      window.removeEventListener("resize", close); window.removeEventListener("scroll", scrolled, true);
    };
  }, [open, close]);
  if (!on) return null;
  const pick = (symbol: string) => { setOpen(null); onSelect(symbol); };
  const openGroup = (group: MovingGroup, target: HTMLElement) => {
    if (open?.key === group.key) { setOpen(null); return; }
    const box = target.getBoundingClientRect();
    setOpen({ key: group.key, left: Math.max(8, Math.min(box.left, window.innerWidth - 232)), top: box.bottom + 4 });
  };
  const shown = open ? data?.groups.find(g => g.key === open.key) : undefined;
  const unavailable = (failed && !data) || data?.state === "unavailable";
  const label = data ? closeLabel(data) : "";

  return (
    <section aria-label="What's moving" data-testid="desk-moving" className={cn("relative flex min-w-0 items-center gap-2", collapsed ? "h-6" : "h-9")}>
      <button type="button" onClick={toggle} aria-expanded={!collapsed} data-testid="desk-moving-toggle"
        className="relative inline-flex shrink-0 items-center gap-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground hover:text-foreground after:absolute after:-inset-2.5 after:content-[''] sm:after:hidden">
        {collapsed ? <ChevronRight size={13} aria-hidden /> : <ChevronDown size={13} aria-hidden />}Moving
      </button>
      {!collapsed && (unavailable ? (
        <p data-testid="desk-moving-unavailable" className="truncate text-xs text-muted-foreground">{data?.reason ?? "Market moves are unavailable right now."}</p>
      ) : data && (
        <div data-testid="desk-moving-row"
          className="flex min-w-0 flex-1 items-center gap-1.5 overflow-x-auto overscroll-x-contain [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          {label && <span data-testid="desk-moving-close" className="shrink-0 text-xs text-muted-foreground">{label}</span>}
          {data.groups.map(group => {
            const members = group.members.length > 0;
            const text = <><span className="text-foreground/90">{group.label}</span><span className={cn("tabular-nums", numberTone(group.change_pct))}>{pctText(group.change_pct)}</span></>;
            return members ? (
              <button key={group.key} type="button" data-testid="desk-moving-group" data-moving-key={group.key} aria-haspopup="dialog" aria-expanded={open?.key === group.key}
                title={group.symbol ? `${group.symbol}: ${group.label}` : group.label}
                onClick={event => openGroup(group, event.currentTarget)}
                className={cn(TILE, heat(group.change_pct), open?.key === group.key && "ring-1 ring-foreground/40")}>
                {text}
              </button>
            ) : (
              <button key={group.key} type="button" data-testid="desk-moving-group" onClick={() => group.symbol && pick(group.symbol)}
                aria-current={group.symbol === selected || undefined}
                className={cn(TILE, heat(group.change_pct), group.symbol === selected && "ring-1 ring-foreground/50")}>
                {text}
              </button>
            );
          })}
          {data.movers.length > 0 && <span aria-hidden className="mx-0.5 h-4 w-px shrink-0 bg-border" />}
          {data.movers.map(mover => (
            <button key={mover.symbol} type="button" data-testid="desk-moving-mover" onClick={() => pick(mover.symbol)}
              aria-current={mover.symbol === selected || undefined}
              title={mover.mine ? "Yours: held or watched" : "A Radar mover"}
              className={cn(TILE, heat(mover.change_pct), mover.symbol === selected && "ring-1 ring-foreground/50")}>
              <span className={cn("font-semibold", mover.mine ? "text-foreground" : "text-foreground/80")}>{mover.symbol}</span>
              <span className={cn("tabular-nums", numberTone(mover.change_pct))}>{pctText(mover.change_pct)}</span>
              {mover.reason && <span className="text-[11px] text-muted-foreground">{mover.reason}</span>}
            </button>
          ))}
        </div>
      ))}
      {open && shown && (
        <div ref={popover} role="dialog" aria-label={`${shown.label} members`} data-testid="desk-moving-members"
          style={{ left: open.left, top: open.top }}
          className="fixed z-40 max-h-72 w-56 overflow-y-auto rounded-lg border bg-card p-1 shadow-xl">
          {shown.symbol && (
            <button type="button" onClick={() => pick(shown.symbol!)}
              className="flex min-h-9 w-full items-center justify-between rounded-md px-2 text-left text-xs hover:bg-secondary">
              <span className="font-semibold text-foreground">{shown.symbol}<span className="ml-1.5 font-normal text-muted-foreground">{shown.label}</span></span>
              <span className={cn("tabular-nums", numberTone(shown.change_pct))}>{pctText(shown.change_pct)}</span>
            </button>
          )}
          {shown.members.map(member => (
            <button key={member.symbol} type="button" onClick={() => pick(member.symbol)}
              className="flex min-h-9 w-full items-center justify-between rounded-md px-2 text-left text-xs hover:bg-secondary">
              <span className="text-foreground">{member.symbol}</span>
              <span className={cn("tabular-nums", numberTone(member.change_pct))}>{member.change_pct == null ? "—" : pctText(member.change_pct)}</span>
            </button>
          ))}
        </div>
      )}
    </section>
  );
}
