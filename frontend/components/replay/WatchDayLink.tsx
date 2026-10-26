"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Clapperboard } from "lucide-react";
import { apiUrl } from "@/lib/api";

// "Watch today": shown only when Watch your day kept a clip (GET /replay lists the kept days). On the Today screen it
// is today's; on a trade page, the newest kept day from the trade's open to its close with the trade's symbol.
type Kept = { date: string; symbols: string[] };

export default function WatchDayLink({ from, to, symbol, label = "Watch today", className }: {
  from: string; to?: string | null; symbol?: string; label?: string; className?: string;
}) {
  const [found, setFound] = useState<Kept | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    fetch(apiUrl("/replay"), { cache: "no-store", signal: controller.signal })
      .then(r => r.ok ? r.json() : { days: [] })
      .then((body: { days: Kept[] }) => setFound(body.days.find(d => d.date >= from && d.date <= (to ?? from)
        && (!symbol || d.symbols.includes(symbol.toUpperCase()))) ?? null))
      .catch(() => undefined);
    return () => controller.abort();
  }, [from, to, symbol]);
  if (!found) return null;
  const href = `/replay/${found.date}${symbol ? `?symbol=${encodeURIComponent(symbol.toUpperCase())}` : ""}`;
  return <Link href={href} data-testid="watch-day" className={className ?? "inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs text-foreground hover:bg-muted"}>
    <Clapperboard size={13} aria-hidden />{label}
  </Link>;
}
