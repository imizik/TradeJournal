"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import CopilotPanel from "@/components/copilot/CopilotPanel";
import { useCopilotOn } from "@/components/copilot/useCopilotOn";
import { CONTEXT_MAX, copilotLabHref, type LinkOrigin } from "@/lib/copilot";

const BUTTON = "inline-flex h-9 items-center rounded-md border px-3 text-xs font-medium text-foreground hover:bg-secondary";

/** "Ask copilot", prefilled with the symbol and a context line; nothing is sent. A link into the lab, or with ``drawer``
 * the same panel opened in place over the page (full screen on a phone). Owner-only, and nothing while the lab is off. */
export default function AskCopilot({ symbol, context, className, drawer = false, origin = null }: {
  symbol: string; context?: string; className?: string; drawer?: boolean;
  /** What prompted the conversation; a plan confirmed in it records it (docs/copilot-lab.md § Origin). */
  origin?: LinkOrigin | null;
}) {
  const on = useCopilotOn();
  const [open, setOpen] = useState(false);
  const opener = useRef<HTMLButtonElement>(null);
  const dialog = useRef<HTMLDivElement>(null);
  const prefill = (context ?? "").trim().slice(0, CONTEXT_MAX);
  const originKey = origin ? `${origin.kind}:${origin.ref ?? ""}` : "";
  // eslint-disable-next-line react-hooks/exhaustive-deps -- keyed by the origin's value, not its object
  const link = useMemo(() => ({ symbol, context: prefill, investigation: null, origin }), [symbol, prefill, originKey]);

  // Escape closes; focus moves into the drawer and back to the button that opened it.
  useEffect(() => {
    if (!open) return;
    const button = opener.current;
    dialog.current?.focus();
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") setOpen(false); };
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("keydown", onKey); button?.focus(); };
  }, [open]);

  if (!on) return null;
  if (!drawer) return <Link href={copilotLabHref(symbol, context, origin)} className={className ?? BUTTON}>Ask copilot · {symbol}</Link>;
  return (
    <>
      <button ref={opener} type="button" onClick={() => setOpen(true)} aria-expanded={open} className={className ?? BUTTON}>Ask copilot · {symbol}</button>
      {open && (
        <>
          <div aria-hidden="true" data-testid="copilot-drawer-backdrop" onClick={() => setOpen(false)} className="fixed inset-0 z-[79] hidden bg-black/40 sm:block" />
          <div ref={dialog} role="dialog" aria-modal="true" aria-label={`Copilot for ${symbol}`} tabIndex={-1}
            className="fixed inset-0 z-[80] overflow-y-auto overscroll-contain bg-[#121924] outline-none sm:inset-y-0 sm:left-auto sm:right-0 sm:w-[28rem] sm:border-l sm:border-slate-700 sm:shadow-2xl">
            {/* Keyed by what it opened on: another event's symbol or summary starts its own conversation. */}
            <CopilotPanel key={`${symbol}|${prefill}`} variant="panel" link={link} onClose={() => setOpen(false)} />
          </div>
        </>
      )}
    </>
  );
}
