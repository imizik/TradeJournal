"use client";

import Link from "next/link";
import { useState } from "react";
import CopilotPanel from "@/components/copilot/CopilotPanel";
import { useCopilotOn } from "@/components/copilot/useCopilotOn";
import { CONTEXT_MAX, copilotLabHref } from "@/lib/copilot";

const BUTTON = "inline-flex h-9 items-center rounded-md border px-3 text-xs font-medium text-foreground hover:bg-secondary";

/** "Ask copilot", prefilled with the symbol and a context line; nothing is sent. A link into the lab, or with ``drawer``
 * the same panel opened in place over the page (full screen on a phone). Owner-only, and nothing while the lab is off. */
export default function AskCopilot({ symbol, context, className, drawer = false }: { symbol: string; context?: string; className?: string; drawer?: boolean }) {
  const on = useCopilotOn();
  const [open, setOpen] = useState(false);
  if (!on) return null;
  if (!drawer) return <Link href={copilotLabHref(symbol, context)} className={className ?? BUTTON}>Ask copilot · {symbol}</Link>;
  return (
    <>
      <button type="button" onClick={() => setOpen(true)} aria-expanded={open} className={className ?? BUTTON}>Ask copilot · {symbol}</button>
      {open && (
        <div role="dialog" aria-label={`Copilot for ${symbol}`}
          className="fixed inset-0 z-[80] overflow-y-auto overscroll-contain bg-[#121924] sm:inset-y-0 sm:left-auto sm:right-0 sm:w-[28rem] sm:border-l sm:border-slate-700 sm:shadow-2xl">
          <CopilotPanel variant="panel" link={{ symbol, context: (context ?? "").trim().slice(0, CONTEXT_MAX), investigation: null }} onClose={() => setOpen(false)} />
        </div>
      )}
    </>
  );
}
