"use client";

import { useEffect, useId, useRef, useState } from "react";

/**
 * A toolbar button that opens a small panel of controls under it (C7.3): the
 * studies, and the settings that do not earn a place in the toolbar itself. It
 * is not modal, so hotkeys keep working while it is open and a toggle inside
 * reads its state with `aria-pressed` as it did in the toolbar. Escape (before
 * any other use of Escape), a press outside it, or its button closes it.
 */
export default function ToolbarMenu({ label, title, className, panelClassName = "", align = "left", above = false, children, content }: {
  /** The panel's name; the button is named by its content. */
  label: string; title?: string; className: string; panelClassName?: string; align?: "left" | "right";
  /** Open upwards, from the status strip at the foot of the screen. */
  above?: boolean;
  /** The panel's controls; one that opens a dialog closes the panel first. */
  children: React.ReactNode; content(close: () => void): React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const id = useId();
  useEffect(() => {
    if (!open) return;
    const away = (event: PointerEvent) => { if (!root.current?.contains(event.target as Node)) setOpen(false); };
    // Capture: this Escape runs before the workspace's, which would otherwise also put a tool away or leave full screen.
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      event.preventDefault();
      setOpen(false);
      if (root.current?.contains(document.activeElement)) trigger.current?.focus();
    };
    window.addEventListener("pointerdown", away, true);
    window.addEventListener("keydown", onKey, true);
    return () => { window.removeEventListener("pointerdown", away, true); window.removeEventListener("keydown", onKey, true); };
  }, [open]);
  return <div ref={root} className="relative">
    <button ref={trigger} aria-expanded={open} aria-controls={open ? id : undefined} title={title} onClick={() => setOpen((v) => !v)} className={className}>{children}</button>
    {open && <div id={id} role="group" aria-label={label}
      className={`absolute z-[60] rounded-lg ${above ? "bottom-full mb-1" : "top-full mt-1"} border border-slate-600 bg-[#121924] p-2 shadow-2xl ${align === "right" ? "right-0" : "left-0"} ${panelClassName}`}>{content(() => setOpen(false))}</div>}
  </div>;
}
