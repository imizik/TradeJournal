"use client";

import { useCallback, useEffect, useRef, useTransition } from "react";
import { useRouter } from "next/navigation";

const REFRESH_MS = 30_000;

/** Refresh the existing server-rendered view without fetching a second copy of the alerts. */
export default function SignalsRefresh() {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();
  const inFlight = useRef(false);

  useEffect(() => {
    if (!isPending) inFlight.current = false;
  }, [isPending]);

  const refresh = useCallback(() => {
    if (document.hidden || inFlight.current) return;
    inFlight.current = true;
    startTransition(() => router.refresh());
  }, [router]);

  useEffect(() => {
    const timer = window.setInterval(refresh, REFRESH_MS);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, [refresh]);

  return (
    <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-2 text-xs text-muted-foreground">
      <span>Updates every 30 seconds while this tab is visible.</span>
      <button
        type="button"
        onClick={refresh}
        disabled={isPending}
        className="rounded border px-3 py-1.5 font-medium text-foreground hover:bg-secondary disabled:opacity-50"
      >
        {isPending ? "Updating…" : "Refresh now"}
      </button>
    </div>
  );
}
