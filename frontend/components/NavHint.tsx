"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

/** Portal keeps the label outside the scrolling navigation rail. */
export default function NavHint({ label, children }: { label: string; children: ReactNode }) {
  const anchor = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState<{ left: number; top: number } | null>(null);
  useEffect(() => {
    const hide = () => setPosition(null);
    // A newly added page can make the rail scroll as the pointer enters a link.
    // Keep that label at its current anchor; dismiss when the link moves away.
    const onScroll = () => setPosition(current => {
      const element = anchor.current;
      if (!current || !element || (!element.matches(":hover") && !element.contains(document.activeElement))) return null;
      const rect = element.getBoundingClientRect();
      return { left: rect.right + 8, top: rect.top + rect.height / 2 };
    });
    window.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", hide);
    return () => {
      window.removeEventListener("scroll", onScroll, true);
      window.removeEventListener("resize", hide);
    };
  }, []);
  useEffect(() => {
    if (!position) return;
    const dismiss = (event: KeyboardEvent) => { if (event.key === "Escape") setPosition(null); };
    window.addEventListener("keydown", dismiss);
    return () => window.removeEventListener("keydown", dismiss);
  }, [position]);
  const show = (element: HTMLElement) => {
    const rect = element.getBoundingClientRect();
    setPosition({ left: rect.right + 8, top: rect.top + rect.height / 2 });
  };
  return (
    <div ref={anchor} onMouseEnter={event => show(event.currentTarget)} onMouseLeave={() => setPosition(null)}
      onFocus={event => show(event.currentTarget)} onBlur={() => setPosition(null)}
      onClick={() => setPosition(null)}>
      {children}
      {position && createPortal(
        <span role="tooltip" style={position} className="pointer-events-none fixed z-[100] -translate-y-1/2 whitespace-nowrap rounded-md border border-border bg-popover px-3 py-1.5 text-xs font-medium text-popover-foreground shadow-md">
          {label}
        </span>, document.body
      )}
    </div>
  );
}
