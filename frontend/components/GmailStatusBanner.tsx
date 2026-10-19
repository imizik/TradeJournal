"use client";

import { useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { AlertTriangle, Loader2, MailWarning } from "lucide-react";
import { api } from "@/lib/api";
import { useGmailHealth } from "@/lib/useGmailHealth";

// Shown on every page: in full on the Dashboard, as one line elsewhere so it
// does not take a page's (or the charts') height. Also refreshes
// server-rendered data when the backend reports that fills or trades changed,
// so a new execution appears without a manual reload.
export default function GmailStatusBanner() {
  const health = useGmailHealth();
  const router = useRouter();
  const compact = usePathname() !== "/";
  const seenVersion = useRef<string | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!health) return;
    if (seenVersion.current !== null && seenVersion.current !== health.data_version) {
      router.refresh();
    }
    seenVersion.current = health.data_version;
  }, [health, router]);

  if (!health || health.status === "live" || health.status === "off") return null;

  async function reconnect() {
    setConnecting(true);
    setError(null);
    try {
      const { auth_url } = await api.startGmailAuth();
      window.location.assign(auth_url);
    } catch (e) {
      setError((e as Error).message);
      setConnecting(false);
    }
  }

  if (health.action === "reconnect_gmail") {
    return (
      <div role="alert" className={`mb-4 flex flex-wrap items-center rounded-md border border-red-500/30 bg-red-500/10 text-red-200 ${compact ? "gap-2 px-3 py-1 text-xs" : "gap-3 px-4 py-3 text-sm"}`}>
        <MailWarning className="h-4 w-4 shrink-0" />
        <span className={compact ? "min-w-0 flex-1 truncate" : "min-w-0 flex-1"} title={compact ? health.message : undefined}>{compact ? <>Gmail disconnected<span className="hidden sm:inline">: new fills can&apos;t be imported.</span></> : health.message}</span>
        <button
          type="button"
          onClick={reconnect}
          disabled={connecting}
          className={`inline-flex items-center gap-1.5 rounded border border-red-400/40 text-xs font-medium text-red-100 hover:bg-red-500/20 disabled:opacity-60 ${compact ? "px-2 py-0.5" : "px-3 py-1.5"}`}
        >
          {connecting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
          Reconnect Gmail
        </button>
        {error ? <span className="w-full text-xs text-red-300">{error}</span> : null}
      </div>
    );
  }

  const tone = health.status === "down" ? "border-red-500/30 bg-red-500/10 text-red-200" : "border-amber-500/30 bg-amber-500/10 text-amber-200";
  return (
    <div role="status" className={`mb-4 flex items-center rounded-md border ${compact ? "gap-2 px-3 py-1 text-xs" : "gap-3 px-4 py-2.5 text-sm"} ${tone}`}>
      <AlertTriangle className="h-4 w-4 shrink-0" />
      <span className={compact ? "min-w-0 flex-1 truncate" : "min-w-0 flex-1"} title={compact ? health.message : undefined}>{health.message}</span>
    </div>
  );
}
