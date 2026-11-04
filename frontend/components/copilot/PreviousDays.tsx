"use client";

import { useState } from "react";
import { mainHistory, type InvestigationSummary } from "@/lib/copilot";

export default function PreviousDays({ active, open }: { active: string; open(id: string): void }) {
  const [rows, setRows] = useState<InvestigationSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [more, setMore] = useState(false);
  const [error, setError] = useState("");
  async function load(older = false) {
    setLoading(true);
    setError("");
    try {
      const { chats } = await mainHistory(older ? rows.at(-1)?.created_at : undefined);
      setRows(prev => older ? [...prev, ...chats] : chats);
      setMore(chats.length === 30);
    } catch { setError("Could not load previous days."); }
    finally { setLoading(false); }
  }
  return <details className="min-w-36 text-sm" onToggle={event => { if (event.currentTarget.open) void load(); }}>
    <summary className="cursor-pointer py-2">Previous days</summary>
    {rows.filter(row => row.id !== active).map(row => <button type="button" className="block min-h-11 text-left underline"
      key={row.id} onClick={() => open(row.id)}>{row.title}</button>)}
    {loading ? <p>Loading…</p> : error ? <button type="button" onClick={() => void load()}>{error} Retry</button>
      : !rows.some(row => row.id !== active) ? <p className="text-muted-foreground">No other Main chats yet.</p> : null}
    {more && <button type="button" disabled={loading} onClick={() => void load(true)}>Older chats</button>}
  </details>;
}
