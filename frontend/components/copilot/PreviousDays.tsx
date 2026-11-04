"use client";

import { useEffect, useRef, useState } from "react";
import { CalendarDays, ChevronDown, Loader2 } from "lucide-react";
import { mainChatLabel, mainHistory, type InvestigationSummary } from "@/lib/copilot";
import { cn } from "@/lib/utils";

/** Earlier days' Main chats, as a small menu beside today's heading. Only days with something said are listed. */
export default function PreviousDays({ active, open }: { active: string; open(id: string): void }) {
  const [rows, setRows] = useState<InvestigationSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [more, setMore] = useState(false);
  const [error, setError] = useState("");
  const menu = useRef<HTMLDetailsElement>(null);
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
  // A press outside or Escape closes the menu, like the thread menu.
  useEffect(() => {
    const away = (event: MouseEvent) => { if (menu.current?.open && !menu.current.contains(event.target as Node)) menu.current.open = false; };
    const key = (event: KeyboardEvent) => { if (event.key === "Escape" && menu.current) menu.current.open = false; };
    window.addEventListener("mousedown", away);
    window.addEventListener("keydown", key);
    return () => { window.removeEventListener("mousedown", away); window.removeEventListener("keydown", key); };
  }, []);
  const shown = rows.filter(row => row.id !== active);
  const item = "flex min-h-11 w-full items-center rounded px-2.5 text-left text-sm hover:bg-secondary sm:min-h-8";
  return <details ref={menu} className="group relative text-sm" onToggle={event => { if (event.currentTarget.open) void load(); }}>
    <summary className="inline-flex min-h-11 cursor-pointer list-none items-center gap-1.5 rounded-md border px-2.5 text-xs text-muted-foreground hover:text-foreground sm:min-h-8 [&::-webkit-details-marker]:hidden">
      <CalendarDays size={14} aria-hidden />Previous days<ChevronDown size={14} aria-hidden className="transition-transform group-open:rotate-180" />
    </summary>
    <div className="absolute right-0 z-30 mt-1 max-h-80 w-56 overflow-y-auto rounded-md border bg-card p-1 shadow-lg">
      {shown.map(row => <button type="button" className={item} key={row.id} onClick={() => { if (menu.current) menu.current.open = false; open(row.id); }}>{mainChatLabel(row)}</button>)}
      {loading ? <p role="status" className="flex items-center gap-1.5 px-2.5 py-2 text-xs text-muted-foreground"><Loader2 size={12} className="animate-spin" aria-hidden />Loading…</p>
        : error ? <button type="button" className={cn(item, "text-xs text-amber-300")} onClick={() => void load()}>{error} Retry</button>
        : !shown.length ? <p className="px-2.5 py-2 text-xs text-muted-foreground">No earlier Main chats yet.</p> : null}
      {more && <button type="button" disabled={loading} className={cn(item, "text-xs text-muted-foreground")} onClick={() => void load(true)}>Older days</button>}
    </div>
  </details>;
}
