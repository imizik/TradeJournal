"use client";

import { useEffect, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

/** Portal keeps the label outside the scrolling navigation rail. */
export default function NavHint({ label, children }: { label: string; children: ReactNode }) {
  const [position, setPosition] = useState<{ left: number; top: number } | null>(null);
  useEffect(() => {
    const hide = () => setPosition(null);
    window.addEventListener("scroll", hide, true);
    window.addEventListener("resize", hide);
    return () => {
      window.removeEventListener("scroll", hide, true);
      window.removeEventListener("resize", hide);
    };
  }, []);
  const show = (element: HTMLElement) => {
    const rect = element.getBoundingClientRect();
    setPosition({ left: rect.right + 8, top: rect.top + rect.height / 2 });
  };
  return (
    <div onMouseEnter={event => show(event.currentTarget)} onMouseLeave={() => setPosition(null)}
      onFocus={event => show(event.currentTarget)} onBlur={() => setPosition(null)}
      onClick={() => setPosition(null)} onKeyDown={event => { if (event.key === "Escape") setPosition(null); }}>
      {children}
      {position && createPortal(
        <span role="tooltip" style={position} className="pointer-events-none fixed z-[100] -translate-y-1/2 whitespace-nowrap rounded-md border border-border bg-popover px-3 py-1.5 text-xs font-medium text-popover-foreground shadow-md">
          {label}
        </span>, document.body
      )}
    </div>
  );
}
