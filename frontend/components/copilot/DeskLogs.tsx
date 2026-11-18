"use client";

import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { X } from "lucide-react";
import { api, type ScannerDay } from "@/lib/api";
import ScannerDayContent, { nyDate } from "@/components/ScannerDayContent";
import RadarFeedView, { type RadarFeedInitial } from "@/components/RadarFeedView";
import ShadowBookView from "@/components/ShadowBookView";

const DESK_LOG_EVENT = "copilot:desk-log";

type OpenScanner = { kind: "scanner"; day?: string };
type OpenRadar = { kind: "radar" } & RadarFeedInitial;
type OpenRequest = OpenScanner | OpenRadar;

/** Opens the Scanner history drawer on the desk (past days, setups, shadow/Isaac comparison and scorecards). */
export const openScannerHistory = (day?: string) =>
  window.dispatchEvent(new CustomEvent<OpenRequest>(DESK_LOG_EVENT, { detail: { kind: "scanner", day } }));

/** Opens the Radar log drawer on the desk (Developments, event detail + revisions + rating, Outside your list, Shadow book). */
export const openRadarLog = (opts: RadarFeedInitial = {}) =>
  window.dispatchEvent(new CustomEvent<OpenRequest>(DESK_LOG_EVENT, { detail: { kind: "radar", ...opts } }));

function DeskScannerHistoryBody({ initialDay }: { initialDay?: string }) {
  const [day, setDay] = useState<string | undefined>(initialDay);
  const [loaded, setLoaded] = useState<{ data: ScannerDay; at: string; live: boolean } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reloadNonce, setReloadNonce] = useState(0);
  const readVersion = useRef(0);

  useEffect(() => {
    const version = ++readVersion.current;
    let active = true;
    setError(null); // eslint-disable-line react-hooks/set-state-in-effect -- reset transient error when switching day
    void api.scannerDay(day).then((data) => {
      if (!active || version !== readVersion.current) return;
      const now = new Date();
      setLoaded({ data, at: now.toISOString(), live: data.date === nyDate(now) });
    }).catch((err) => {
      if (!active || version !== readVersion.current) return;
      setError(err instanceof Error ? err.message : "Could not load scanner history.");
    });
    return () => { active = false; };
  }, [day, reloadNonce]);

  return (
    <div className="space-y-4">
      {error && (
        <div role="alert" className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">
          {error}{" "}
          <button type="button" onClick={() => setReloadNonce((n) => n + 1)} className="ml-2 underline">
            Retry
          </button>
        </div>
      )}
      {!loaded && !error && <p role="status" className="text-sm text-muted-foreground">Loading scanner history…</p>}
      {loaded && (
        <ScannerDayContent
          data={loaded.data}
          nowIso={loaded.at}
          live={loaded.live}
          onDay={(nextDay) => setDay(nextDay)}
          onRefresh={() => setReloadNonce((n) => n + 1)}
          embedded
        />
      )}
    </div>
  );
}

/** Desk drawers for Scanner history (``⌘K › Scanner history``) and the Radar log (``⌘K › Radar log``). */
export function DeskLogs() {
  const [active, setActive] = useState<{ request: OpenRequest; key: number } | null>(null);
  const params = useSearchParams();

  useEffect(() => {
    const onOpen = (event: Event) => {
      const detail = (event as CustomEvent<OpenRequest>).detail;
      if (!detail || (detail.kind !== "scanner" && detail.kind !== "radar")) return;
      setActive((prev) => ({ request: detail, key: (prev?.key ?? 0) + 1 }));
    };
    window.addEventListener(DESK_LOG_EVENT, onOpen);
    return () => window.removeEventListener(DESK_LOG_EVENT, onOpen);
  }, []);

  useEffect(() => {
    const desk = params.get("desk");
    if (desk !== "scanner" && desk !== "radar") return;
    const rest = new URLSearchParams(params.toString());
    if (desk === "scanner") {
      const rawDay = params.get("day");
      const day = rawDay && /^\d{4}-\d{2}-\d{2}$/.test(rawDay) ? rawDay : undefined;
      setActive((prev) => ({ request: { kind: "scanner", day }, key: (prev?.key ?? 0) + 1 })); // eslint-disable-line react-hooks/set-state-in-effect -- URL handoff opens drawer once
      rest.delete("desk");
      rest.delete("day");
      rest.delete("history");
    } else {
      const request: OpenRadar = {
        kind: "radar",
        event: params.get("event"),
        rate: params.get("rate"),
        session: params.get("session"),
        groups: params.get("groups"),
      };
      setActive((prev) => ({ request, key: (prev?.key ?? 0) + 1 }));
      for (const key of ["desk", "event", "rate", "session", "groups", "log"]) rest.delete(key);
    }
    window.history.replaceState(null, "", `/copilot-lab${rest.size ? `?${rest}` : ""}`);
  }, [params]);

  const kind = active?.request.kind ?? null;
  useEffect(() => {
    if (!kind) return;
    const before = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const closeLabel = kind === "scanner" ? "Close scanner history" : "Close radar log";
    const testId = kind === "scanner" ? "desk-scanner-history" : "desk-radar-log";
    const frame = requestAnimationFrame(() => document.querySelector<HTMLElement>(`[aria-label="${closeLabel}"]`)?.focus());
    const key = (event: KeyboardEvent) => {
      if (document.querySelector("dialog[open]")) return;
      if (event.key === "Escape") { event.stopImmediatePropagation(); event.preventDefault(); setActive(null); return; }
      if (event.key !== "Tab") {
        if (!event.metaKey && !event.ctrlKey) event.stopImmediatePropagation();
        return;
      }
      const box = document.querySelector<HTMLElement>(`[data-testid="${testId}"]`);
      const items = box ? Array.from(box.querySelectorAll<HTMLElement>('a[href], button, summary, input, select, textarea, [tabindex]:not([tabindex="-1"])')).filter(el => !el.hasAttribute("disabled") && el.offsetParent !== null) : [];
      if (!items.length) return;
      const first = items[0], last = items[items.length - 1];
      if (!box!.contains(document.activeElement)) { event.preventDefault(); first.focus(); }
      else if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    window.addEventListener("keydown", key, true);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("keydown", key, true);
      const back = before?.isConnected ? before : document.querySelector<HTMLElement>('[data-use="palette"]');
      back?.focus();
    };
  }, [kind]);

  if (!active) return null;
  const isScanner = active.request.kind === "scanner";
  const closeLabel = isScanner ? "Close scanner history" : "Close radar log";
  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/50 backdrop-blur-sm" onClick={() => setActive(null)} />
      <aside
        role="dialog"
        aria-modal="true"
        aria-label={isScanner ? "Scanner history" : "Radar log"}
        data-testid={isScanner ? "desk-scanner-history" : "desk-radar-log"}
        className="fixed right-0 top-0 z-50 flex h-screen w-full max-w-4xl flex-col border-l border-border bg-background shadow-2xl"
      >
        <header className="flex items-start justify-between gap-4 border-b border-border px-5 py-4">
          <div>
            <h2 className="text-base font-semibold text-foreground">{isScanner ? "Scanner history" : "Radar log"}</h2>
            <p className="mt-1 text-xs text-muted-foreground">
              {isScanner
                ? "Past days, setups, shadow decisions, scorecards and scanner universe."
                : "Developments, event detail with revisions and ratings, Outside your list and the Shadow book."}
            </p>
          </div>
          <button
            type="button"
            onClick={() => setActive(null)}
            aria-label={closeLabel}
            className="inline-flex min-h-11 min-w-11 items-center justify-center rounded p-1.5 text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground sm:min-h-8 sm:min-w-8"
          >
            <X className="h-4 w-4" />
          </button>
        </header>
        <div className="min-h-0 flex-1 space-y-6 overflow-y-auto p-4">
          {active.request.kind === "scanner" ? (
            <DeskScannerHistoryBody key={`${active.key}-${active.request.day ?? ""}`} initialDay={active.request.day} />
          ) : (
            <div className="space-y-6">
              <RadarFeedView key={active.key} initial={active.request} embedded />
              <ShadowBookView key={`shadow-${active.key}`} />
            </div>
          )}
        </div>
      </aside>
    </>
  );
}
