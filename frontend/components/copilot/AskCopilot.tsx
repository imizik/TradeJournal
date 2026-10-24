"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useAppAccess } from "@/components/AccessProvider";
import { copilotLabHref, getCopilotStatus } from "@/lib/copilot";

/** One status read shared by every button; only an answer is kept, so a failed read is retried on the next mount. */
let enabled: Promise<boolean> | null = null;

function labEnabled(): Promise<boolean> {
  enabled ??= getCopilotStatus().then(status => status.enabled, () => {
    enabled = null;
    return false;
  });
  return enabled;
}

/** "Ask copilot" link into the lab, prefilled. Owner-only, and nothing at all while the lab is off. */
export default function AskCopilot({ symbol, context, className }: { symbol: string; context?: string; className?: string }) {
  const { owner } = useAppAccess();
  const [on, setOn] = useState(false);
  useEffect(() => {
    if (!owner) return;
    let live = true;
    void labEnabled().then(value => { if (live) setOn(value); });
    return () => { live = false; };
  }, [owner]);
  if (!owner || !on) return null;
  return (
    <Link href={copilotLabHref(symbol, context)} className={className ?? "inline-flex h-9 items-center rounded-md border px-3 text-xs font-medium text-foreground hover:bg-secondary"}>
      Ask copilot · {symbol}
    </Link>
  );
}
