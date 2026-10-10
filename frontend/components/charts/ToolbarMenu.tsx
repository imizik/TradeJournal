"use client";

import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";

/**
 * A toolbar button that opens a small panel of controls under it (C7.3): the
 * studies, and the settings that do not earn a place in the toolbar itself. It
 * is not modal, so hotkeys keep working while it is open and a toggle inside
 * reads its state with `aria-pressed` as it did in the toolbar. Escape (before
 * any other use of Escape), a press outside it, or its button closes it.
 * `floating` puts the panel over the page, beside its button, for a button in
 * a box that clips (a smaller chart's header); it opens up when there is more
 * room above.
 */
export default function ToolbarMenu({ label, title, className, panelClassName = "", align = "left", above = false, floating = false, children, content }: {
  /** The panel's name; the button is named by its content. */
  label: string; title?: string; className: string; panelClassName?: string; align?: "left" | "right";
  /** Open upwards, from the status strip at the foot of the screen. */
  above?: boolean;
  floating?: boolean;
  /** The panel's controls; one that opens a dialog closes the panel first. */
  children: React.ReactNode; content(close: () => void): React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const [spot, setSpot] = useState<React.CSSProperties>({});
  const id = useId();
  const inside = (node: Node | null) => !!node && (!!root.current?.contains(node) || !!panel.current?.contains(node));
  const toggle = () => {
    if (floating && !open && trigger.current) {
      const box = trigger.current.getBoundingClientRect();
      const [below, over] = [window.innerHeight - box.bottom, box.top];
      const right = Math.max(4, window.innerWidth - box.right);
      setSpot(below >= over ? { top: box.bottom + 4, right, maxHeight: below - 12 } : { bottom: window.innerHeight - box.top + 4, right, maxHeight: over - 12 });
    }
    setOpen((v) => !v);
  };
  useEffect(() => {
    if (!open) return;
    const away = (event: PointerEvent) => { if (!inside(event.target as Node)) setOpen(false); };
    // Capture: this Escape runs before the workspace's, which would otherwise also put a tool away or leave full screen.
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      event.preventDefault();
      setOpen(false);
      if (inside(document.activeElement)) trigger.current?.focus();
    };
    // A floating panel stays beside its button only while nothing under it scrolls or resizes.
    const shut = (event: Event) => { if (!inside(event.target as Node)) setOpen(false); };
    window.addEventListener("pointerdown", away, true);
    window.addEventListener("keydown", onKey, true);
    if (floating) { window.addEventListener("resize", shut); window.addEventListener("scroll", shut, true); }
    return () => { window.removeEventListener("pointerdown", away, true); window.removeEventListener("keydown", onKey, true); window.removeEventListener("resize", shut); window.removeEventListener("scroll", shut, true); };
  }, [open, floating]);
  const body = open && <div ref={panel} id={id} role="group" aria-label={label} style={floating ? spot : undefined}
    className={`${floating ? "fixed z-[70] overflow-y-auto" : `absolute z-[60] ${above ? "bottom-full mb-1" : "top-full mt-1"} ${align === "right" ? "right-0" : "left-0"}`} rounded-lg border border-slate-600 bg-[#121924] p-2 shadow-2xl ${panelClassName}`}>{content(() => setOpen(false))}</div>;
  return <div ref={root} className="relative">
    <button ref={trigger} aria-expanded={open} aria-controls={open ? id : undefined} title={title} onClick={toggle} className={className}>{children}</button>
    {floating && body ? createPortal(body, document.body) : body}
  </div>;
}
