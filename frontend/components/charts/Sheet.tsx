"use client";

import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";

/**
 * A phone's side panel: a modal bottom sheet over the charts (C1.4, C7.3), so
 * opening it never squeezes the chart canvas. Escape, the backdrop or the
 * panel's own close button dismisses it. The sheet takes focus once, when it
 * opens, so typing in one of its fields is never interrupted.
 */
export default function Sheet({ label, onClose, children }: { label: string; onClose(): void; children: React.ReactNode }) {
  const panel = useRef<HTMLDivElement>(null);
  const close = useRef(onClose);
  useEffect(() => { close.current = onClose; });
  useEffect(() => {
    panel.current?.focus({ preventScroll: true });
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") { event.preventDefault(); close.current(); } };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  return createPortal(<div className="fixed inset-0 z-[80] flex items-end bg-black/60" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
    <div ref={panel} role="dialog" aria-modal="true" aria-label={label} tabIndex={-1}
      className="max-h-[75vh] w-full overflow-y-auto overscroll-contain rounded-t-xl border-t border-slate-600 bg-[#121924] pb-[max(0.5rem,env(safe-area-inset-bottom))] pl-[env(safe-area-inset-left)] pr-[env(safe-area-inset-right)] shadow-2xl outline-none">
      <div className="mx-auto mt-2 h-1 w-10 rounded-full bg-slate-600" aria-hidden />
      {children}
    </div>
  </div>, document.body);
}
