"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { advisorStamp } from "./AdvisorReceiptView";
import { fetchTradeCheckLinks, type TradeCheckLink } from "@/lib/checkLinks";

// Saved Jo checks the owner linked to this trade (Dots step 5). Links are the owner's; nothing here grades them.
type Saved = { check_id: string; received_at: string; idea: Record<string, string | number | null>; answer: { verdict: string };
  model_verdict: { verdict: string } | null };
const LABEL: Record<string, string> = { go: "Go", wait: "Wait", pass: "Pass", insufficient_data: "Not enough data" };
const DORMANT = "Pre-trade check review is not switched on yet";

async function readCheck(url: string): Promise<{ state: "ok"; body: Saved } | { state: "dormant" | "unavailable" | "forbidden" }> {
  try {
    const response = await fetch(url, { cache: "no-store", redirect: "error" });
    const body = await response.json();
    if (response.status === 503 && body.detail === DORMANT) return { state: "dormant" };
    if (response.status === 403) return { state: "forbidden" };
    return response.ok ? { state: "ok", body } : { state: "unavailable" };
  } catch { return { state: "unavailable" }; }
}

export default function TradeAdvice({ tradeId }: { tradeId: string }) {
  const [links, setLinks] = useState<TradeCheckLink[] | null>(null);
  const [connected, setConnected] = useState<"ok" | "dormant" | "unavailable" | "forbidden" | null>(null);
  const [checks, setChecks] = useState<Record<string, Saved | null>>({});

  useEffect(() => {
    let active = true;
    void (async () => {
      const [found, status] = await Promise.all([fetchTradeCheckLinks(tradeId).then(b => b.links).catch(() => null),
        readCheck("/api/check-owner/checks")]);
      if (!active) return;
      setLinks(found); setConnected(status.state);
      if (status.state !== "ok" || !found?.length) return;
      const ids = [...new Set(found.map(link => link.check_id))];
      const read = await Promise.all(ids.map(id => readCheck(`/api/check-owner/checks/${id}`)));
      if (active) setChecks(Object.fromEntries(ids.map((id, i) => { const r = read[i]; return [id, r.state === "ok" ? r.body : null]; })));
    })();
    return () => { active = false; };
  }, [tradeId]);

  if ((links === null && connected === null) || connected === "forbidden") return null;
  return <section aria-label="Saved advice" data-testid="trade-advice" className="rounded-lg border bg-card p-5 text-sm">
    <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Saved advice</h2>
    {connected === "dormant" && <p>Saved advice isn&apos;t connected to the journal yet{links?.length ? <>; {links.length} saved check{links.length === 1 ? " is" : "s are"} linked and will show once it is</> : null}.</p>}
    {connected === "unavailable" && <p>Saved advice is unavailable right now. The check reader may be stopped.</p>}
    {links === null && connected !== "dormant" && <p>Links to saved advice couldn&apos;t be read.</p>}
    {connected === "ok" && links && links.length === 0 && <p>No saved advice linked. Link a check from <Link href="/advisor-review" className="underline">Advisor review</Link>.</p>}
    {connected === "ok" && links && links.length > 0 && <ul className="divide-y">{links.map(link => {
      const saved = checks[link.check_id];
      return <li key={link.link_id} className="py-2">
        <Link href={`/advisor-review?check=${link.check_id}`} className="font-medium underline">
          {saved ? <>Rules: {LABEL[saved.answer.verdict] ?? saved.answer.verdict}{saved.model_verdict && <> · Jo: {LABEL[saved.model_verdict.verdict] ?? saved.model_verdict.verdict}</>} · {[saved.idea.ticker, saved.idea.side, saved.idea.instrument].filter(Boolean).join(" ")}</> : "Saved check"}
        </Link>
        <span className="text-muted-foreground"> · {saved ? advisorStamp(saved.received_at) : link.check_id} · you linked {link.target === "fill" ? "one fill" : "this trade"}</span>
        {saved === null && <span className="text-muted-foreground"> · the saved check couldn&apos;t be read</span>}
      </li>;
    })}</ul>}
  </section>;
}
