"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

/** The Trades ticker box: filters as you type, keeping the other filters in the URL so they survive a detail round trip. */
export default function TradesTickerInput({ initial }: { initial: string }) {
  const router = useRouter();
  const [value, setValue] = useState(initial);
  useEffect(() => {
    const timer = setTimeout(() => {
      const sp = new URLSearchParams(window.location.search);
      const ticker = value.trim().toUpperCase();
      if (ticker === (sp.get("ticker") ?? "")) return;
      if (ticker) sp.set("ticker", ticker); else sp.delete("ticker");
      const s = sp.toString();
      router.replace(`/trades${s ? `?${s}` : ""}`, { scroll: false });
    }, 250);
    return () => clearTimeout(timer);
  }, [value, router]);
  return (
    <label className="flex items-center gap-1.5">
      <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Ticker</span>
      <input name="ticker" type="search" value={value} onChange={(e) => setValue(e.target.value)} placeholder="All tickers" autoComplete="off"
        className="h-8 w-32 rounded-md border bg-background px-2.5 text-base text-foreground sm:text-sm placeholder:text-muted-foreground" />
    </label>
  );
}
