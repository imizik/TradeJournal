"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Bell, BellOff, BellPlus, Check, ChevronLeft, ChevronRight, Copy, Eye, EyeOff, Layers, Lock, LockOpen, LocateFixed, Plus, RotateCcw, Trash2 } from "lucide-react";
import { alertText } from "@/lib/alerts";
import type { AlertCondition, AlertSource, LevelAlert } from "@/lib/alerts";
import { LEVEL_LABEL_MAX, price } from "@/lib/charts";
import type { AutoZone, Interval } from "@/lib/charts";
import { LEVEL_COLOR, NOTE_MAX, PALETTE, TOOL_NAMES } from "@/lib/drawings";
import type { Drawing } from "@/lib/drawings";
import { summary } from "./SelectionBar";

/** What a right-click or long press on a chart asks for: the item there (`id`), or the chart at `price` (null off the candle pane). */
export type MenuRequest = { clientX: number; clientY: number; touch: boolean; price: number | null; id: string | null; auto?: string | null; reset(): void };
export type MenuItem = { layer: "levels"; level: { id: string; label: string; price: number; color?: string; hidden?: boolean; locked?: boolean } } | { layer: "drawings"; drawing: Drawing } | { layer: "auto"; zone: AutoZone };
/**
 * Alerts on the item (C5.1): what a new one would watch (`source`, null for an
 * item that has no single price), the alerts already on it, the candle a
 * "closes beyond" alert waits for, and whether the server can reach the phone.
 */
export type MenuAlerts = { source: AlertSource | null; existing: (LevelAlert & { shown: number })[]; interval: Interval; phone: boolean;
  onCreate(condition: AlertCondition): void; onRearm(id: string): void; onRemove(id: string): void };
/** A change the menu makes to its item: `label` is a level's name or a note's text. */
export type MenuPatch = { label?: string; color?: string; hidden?: boolean; locked?: boolean };
export type LayerToggle = { key: string; label: string; on: boolean; toggle(): void };
export type HiddenItem = { id: string; name: string; show(): void };

const ITEM = "[role=menuitem]:not([disabled]),[role=menuitemcheckbox]:not([disabled])";

/**
 * The chart's context menu (C1.3). On empty chart: add a level at the price,
 * copy the price, reset this chart's scales, and the Layers view (show or hide
 * levels, drawings, fills and studies; show items hidden one by one). On a
 * level or drawing: its label or text and color inline, lock, hide,
 * duplicate and delete. Each change to an item is one undo step.
 *
 * Opened by a mouse it sits at the pointer; by touch it is a bottom sheet with
 * 44px rows. Esc, a click outside, scrolling or resizing closes it; a label
 * being edited is saved first unless Esc closed it. It renders on the body,
 * above full-screen charts and clear of the workspace's spacing.
 */
export default function ChartMenu({ at, symbol, price: value, item, layers, hidden, alerts, onAddLevel, onCopyPrice, onReset, onEdit, onDuplicate, onDelete, onClose }: {
  at: { x: number; y: number; touch: boolean }; symbol: string; price: number | null; item: MenuItem | null;
  layers: LayerToggle[]; hidden: HiddenItem[]; alerts?: MenuAlerts;
  onAddLevel(price: number): void; onCopyPrice(price: number): void; onReset(): void;
  onEdit(patch: MenuPatch): void; onDuplicate(): void; onDelete(): void; onClose(): void;
}) {
  const panel = useRef<HTMLDivElement>(null);
  const [view, setView] = useState<"main" | "layers">("main");
  const [position, setPosition] = useState<{ left: number; top: number } | null>(null);
  const level = item?.layer === "levels" ? item.level : null;
  const drawing = item?.layer === "drawings" ? item.drawing : null;
  const zone = item?.layer === "auto" ? item.zone : null;
  const labelled = !!level || drawing?.kind === "note";
  const current = level ? level.label : drawing?.text ?? "";
  const [draft, setDraft] = useState(current);
  const saved = useRef(current);
  // Once closed, a blur from the field leaving the page saves nothing (Esc discards).
  const closed = useRef(false);
  // A label typed and not yet saved rides along with the next change, so one
  // action is one edit (and one undo step); closing saves it, unless Esc closed.
  const commit = (patch: MenuPatch = {}) => {
    if (closed.current) return;
    const text = labelled ? draft.trim().slice(0, level ? LEVEL_LABEL_MAX : NOTE_MAX) : "";
    const all = { ...(text && text !== saved.current ? { label: text } : {}), ...patch };
    if (all.label) saved.current = all.label;
    if (Object.keys(all).length) onEdit(all);
  };
  const close = (keep = true) => { if (keep) commit(); closed.current = true; onClose(); };
  const closer = useRef(close);
  useEffect(() => { closer.current = close; });
  // A sheet opens under the finger that held for it. That finger's lift is not a tap, or it would press
  // whichever row (or the backdrop) it lands on: until a new touch starts, a pointer's click is dropped.
  const touched = useRef(false);
  useEffect(() => {
    if (!at.touch) return;
    const down = () => { touched.current = true; };
    window.addEventListener("pointerdown", down, true);
    window.addEventListener("touchstart", down, true);
    return () => { window.removeEventListener("pointerdown", down, true); window.removeEventListener("touchstart", down, true); };
  }, [at.touch]);
  // `detail` is 0 for a click from the keyboard, which is never a lift.
  const dropLift = (event: React.MouseEvent) => { if (!touched.current && event.detail > 0) { event.preventDefault(); event.stopPropagation(); } };

  // A popup stays inside the window: left of the pointer near the right edge, above it near the bottom.
  useLayoutEffect(() => {
    if (at.touch || !panel.current) return;
    const box = panel.current.getBoundingClientRect();
    setPosition({ left: Math.max(8, Math.min(at.x, window.innerWidth - box.width - 8)),
      top: at.y + box.height > window.innerHeight - 8 ? Math.max(8, at.y - box.height) : at.y });
  }, [at, view]);
  // Focus goes to the menu, not a row, so nothing looks chosen until an arrow key picks one.
  useEffect(() => { panel.current?.focus({ preventScroll: true }); }, [view]);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") { event.preventDefault(); closer.current(false); } };
    const outside = (event: Event) => { if (!panel.current?.contains(event.target as Node)) closer.current(); };
    const resize = () => closer.current();
    window.addEventListener("keydown", onKey);
    window.addEventListener("resize", resize);
    // A popup closes on any press, scroll or wheel elsewhere; a sheet closes from its backdrop (below),
    // so the tap that closes it never lands on what is underneath.
    if (!at.touch) {
      window.addEventListener("pointerdown", outside, true);
      window.addEventListener("scroll", outside, true);
      window.addEventListener("wheel", outside, { capture: true, passive: true });
    }
    return () => {
      window.removeEventListener("keydown", onKey); window.removeEventListener("resize", resize);
      window.removeEventListener("pointerdown", outside, true); window.removeEventListener("scroll", outside, true); window.removeEventListener("wheel", outside, true);
    };
  }, [at.touch]);

  // Arrow keys move between the menu's rows; no key reaches the chart's hotkeys while it is open.
  const onKeyDown = (event: React.KeyboardEvent) => {
    event.stopPropagation();
    if (event.key === "Escape") { event.preventDefault(); close(false); return; }
    if ((event.target as HTMLElement).tagName === "INPUT") return;
    if (event.key === "ArrowLeft" && view === "layers") { event.preventDefault(); setView("main"); return; }
    const rows = [...(panel.current?.querySelectorAll<HTMLElement>(ITEM) ?? [])];
    const index = rows.indexOf(document.activeElement as HTMLElement);
    const to = event.key === "ArrowDown" ? (index + 1) % rows.length : event.key === "ArrowUp" ? (index < 0 ? rows.length - 1 : (index - 1 + rows.length) % rows.length)
      : event.key === "Home" ? 0 : event.key === "End" ? rows.length - 1 : null;
    if (to === null || !rows.length) return;
    event.preventDefault();
    rows[to].focus();
  };

  const touch = at.touch;
  const row = `flex w-full items-center gap-2.5 px-3 text-left text-xs text-slate-200 outline-none hover:bg-slate-700/60 focus-visible:bg-slate-700/60 disabled:opacity-40 ${touch ? "h-11" : "h-8"}`;
  const icon = touch ? 16 : 13;
  const swatch = touch ? "h-11 w-11" : "h-6 w-6";
  const name = level ? "Level" : drawing ? TOOL_NAMES[drawing.kind] : zone ? "Auto level" : "Chart";
  const color = level ? level.color ?? LEVEL_COLOR : drawing?.color;
  const locked = !!(level ?? drawing)?.locked;
  const hiddenCount = hidden.length;

  // Alerts (C5.1): those on this item, then the three ways to make one.
  const source = alerts?.source;
  const alertGroup = alerts && (source || alerts.existing.length) ? <div role="menu" aria-label={`${name} alerts`} className="border-t border-slate-700/60 py-1">
    <div className="px-3 pb-1 pt-1.5 text-[10px] uppercase tracking-wider text-slate-500">Alerts{source ? ` at ${price(source.price)}` : ""}</div>
    {alerts.existing.map((alert) => <div key={alert.id} className="flex items-center gap-1 px-3 text-[11px]">
      {alert.state === "active" ? <Bell size={12} className="shrink-0 text-amber-300" aria-hidden /> : <BellOff size={12} className="shrink-0 text-slate-500" aria-hidden />}
      <span className={`min-w-0 flex-1 truncate ${alert.state === "active" ? "text-slate-200" : "text-slate-500"}`}>{alertText(alert, alert.shown)}{alert.state === "fired" ? " · fired" : ""}</span>
      {alert.state === "fired" && <button role="menuitem" aria-label={`Re-arm ${alertText(alert, alert.shown)}`} title="Arm it again from the current price" onClick={() => { close(); alerts.onRearm(alert.id); }}
        className={`inline-flex items-center justify-center rounded text-slate-400 hover:bg-slate-700/60 hover:text-slate-100 ${touch ? "h-11 w-11" : "h-7 w-7"}`}><RotateCcw size={icon} /></button>}
      <button role="menuitem" aria-label={`Remove ${alertText(alert, alert.shown)}`} title="Remove this alert" onClick={() => { close(); alerts.onRemove(alert.id); }}
        className={`inline-flex items-center justify-center rounded text-slate-400 hover:bg-slate-700/60 hover:text-rose-300 ${touch ? "h-11 w-11" : "h-7 w-7"}`}><Trash2 size={icon} /></button>
    </div>)}
    {source && <>
      <button role="menuitem" className={row} title="When a trade reaches this price" onClick={() => { close(); alerts.onCreate("touches"); }}><BellPlus size={icon} />Alert when price touches</button>
      <button role="menuitem" className={row} title="When a trade goes through this price" onClick={() => { close(); alerts.onCreate("crosses"); }}><BellPlus size={icon} />Alert when price crosses</button>
      <button role="menuitem" className={row} title={`When a ${alerts.interval} candle closes on the other side`} onClick={() => { close(); alerts.onCreate("closes_beyond"); }}><BellPlus size={icon} />Alert on a {alerts.interval} close beyond</button>
    </>}
    {!alerts.phone && <p className="px-3 pb-1 pt-1 text-[10px] leading-4 text-amber-300">Phone alerts are not set up on this server, so alerts show here only.</p>}
  </div> : null;

  const body = zone ? <>
    <div className="flex items-center gap-2 border-b border-slate-700/60 px-3 py-2 text-[11px]">
      <span className="h-0.5 w-3 shrink-0 rounded-sm bg-slate-400" />
      <span className="min-w-0 truncate text-slate-300">{zone.label}</span>
      <span className="ml-auto shrink-0 font-mono text-slate-400">{zone.low === zone.high ? price(zone.low) : `${price(zone.low)}–${price(zone.high)}`}</span>
    </div>
    {alertGroup}
  </> : item ? <>
    <div className="flex items-center gap-2 border-b border-slate-700/60 px-3 py-2 text-[11px]">
      <span className={`shrink-0 rounded-sm ${level ? "h-0.5 w-3" : "h-2 w-3"}`} style={{ background: color }} />
      <span className="min-w-0 truncate text-slate-300">{level ? level.label : name}</span>
      <span className="ml-auto shrink-0 font-mono text-slate-400">{level ? price(level.price) : drawing && summary(drawing)}</span>
    </div>
    {labelled && <div className="px-3 pt-2">
      <input aria-label={level ? "Level label" : "Note text"} value={draft} maxLength={level ? LEVEL_LABEL_MAX : NOTE_MAX}
        onChange={(e) => setDraft(e.target.value)} onBlur={() => commit()}
        onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); close(); } }}
        className={`w-full rounded border border-slate-700 bg-[#10151e] px-2 text-xs text-slate-100 outline-none focus:border-sky-600 ${touch ? "h-11" : "h-8"}`} />
    </div>}
    <div role="group" aria-label={`${name} color`} className="flex flex-wrap items-center gap-0.5 px-2 py-1.5">
      {PALETTE.map(([value, label]) => <button key={value} aria-label={label} aria-pressed={color === value} title={label} onClick={() => commit({ color: value })}
        className={`inline-flex ${swatch} items-center justify-center rounded ${color === value ? "ring-1 ring-slate-200" : "hover:bg-slate-700/60"}`}>
        <span className="h-3.5 w-3.5 rounded-full" style={{ background: value }} /></button>)}
    </div>
    <div role="menu" aria-label={`${name} actions`} className="border-t border-slate-700/60 py-1">
      <button role="menuitem" className={row} title={locked ? "Let it drag again" : "Keep it from being dragged; it still selects, restyles and deletes"} onClick={() => { commit({ locked: !locked }); close(false); }}>{locked ? <LockOpen size={icon} /> : <Lock size={icon} />}{locked ? "Unlock" : "Lock"}</button>
      <button role="menuitem" className={row} onClick={() => { commit({ hidden: true }); close(false); }}><EyeOff size={icon} />Hide</button>
      <button role="menuitem" className={row} onClick={() => { close(); onDuplicate(); }}><Copy size={icon} />Duplicate</button>
      <button role="menuitem" className={`${row} text-rose-300`} onClick={() => { close(false); onDelete(); }}><Trash2 size={icon} />Delete</button>
    </div>
    {alertGroup}
  </> : view === "main" ? <div role="menu" aria-label="Chart actions" className="py-1">
    <div className="px-3 pb-1.5 pt-1 text-[11px] text-slate-500"><span className="font-semibold text-slate-300">{symbol}</span>{value !== null && <span className="ml-2 font-mono">{price(value)}</span>}</div>
    {value !== null && <>
      <button role="menuitem" className={row} onClick={() => { onAddLevel(value); close(); }}><Plus size={icon} />Add level at {price(value)}</button>
      <button role="menuitem" className={row} onClick={() => { onCopyPrice(value); close(); }}><Copy size={icon} />Copy price {price(value)}</button>
    </>}
    <button role="menuitem" className={row} onClick={() => { onReset(); close(); }}><LocateFixed size={icon} />Reset chart scale</button>
    <button role="menuitem" aria-haspopup="menu" className={row} onClick={() => setView("layers")}><Layers size={icon} />Layers
      <span className="ml-auto flex items-center gap-1 text-[10px] text-slate-500">{hiddenCount ? `${hiddenCount} hidden` : ""}<ChevronRight size={icon} /></span></button>
  </div> : <div role="menu" aria-label="Layers" className="py-1">
    <button role="menuitem" className={`${row} text-slate-400`} onClick={() => setView("main")}><ChevronLeft size={icon} />Layers</button>
    {layers.map((layer) => <button key={layer.key} role="menuitemcheckbox" aria-checked={layer.on} className={row} onClick={layer.toggle}>
      <span className={`inline-flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-sm border ${layer.on ? "border-sky-400 bg-sky-400/20 text-sky-200" : "border-slate-600"}`}>{layer.on && <Check size={10} />}</span>{layer.label}</button>)}
    {!!hiddenCount && <>
      <div className="mt-1 border-t border-slate-700/60 px-3 pb-1 pt-2 text-[10px] uppercase tracking-wider text-slate-500">Hidden {symbol} items</div>
      {hidden.map((entry) => <button key={entry.id} role="menuitem" aria-label={`Show ${entry.name}`} className={row} onClick={entry.show}><Eye size={icon} /><span className="min-w-0 truncate">{entry.name}</span><span className="ml-auto text-[10px] text-slate-500">Show</span></button>)}
    </>}
  </div>;

  const label = `${name} menu`;
  if (touch) return createPortal(<div className="fixed inset-0 z-[80] flex items-end bg-black/50" onClickCapture={dropLift} onClick={(e) => { if (e.target === e.currentTarget) close(); }}>
    <div ref={panel} role="dialog" aria-label={label} tabIndex={-1} onKeyDown={onKeyDown}
      className="max-h-[70vh] outline-none w-full overflow-y-auto overscroll-contain rounded-t-xl border-t border-slate-600 bg-[#121924] pb-[max(0.5rem,env(safe-area-inset-bottom))] pl-[env(safe-area-inset-left)] pr-[env(safe-area-inset-right)] shadow-2xl">
      <div className="mx-auto my-2 h-1 w-10 rounded-full bg-slate-600" aria-hidden />
      {body}
    </div>
  </div>, document.body);
  // Placed at the pointer, then moved inside the window before it paints.
  return createPortal(<div ref={panel} role="dialog" aria-label={label} tabIndex={-1} onKeyDown={onKeyDown} onContextMenu={(e) => e.preventDefault()}
    style={position ?? { left: at.x, top: at.y }}
    className="fixed z-[80] max-h-[calc(100vh-16px)] w-60 overflow-y-auto overscroll-contain rounded-md outline-none border border-slate-600 bg-[#121924] shadow-2xl">
    {body}
  </div>, document.body);
}
