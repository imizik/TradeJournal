"use client";

// Workspace store: loads the AI Buildout workspace, applies optimistic edits,
// and debounce-saves them with an optimistic-concurrency revision guard.
// Journal overlays (live quotes, open-position tickers, per-ticker realized
// stats) are fetched once and exposed alongside.

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import { api, type Stats } from "@/lib/api";
import { getWorkspace, saveWorkspace, RevisionConflictError } from "./api";
import { SLUG, SIGNAL_NEXT } from "./constants";
import type {
  ChecklistAnswer,
  Company,
  DeepDive,
  Layer,
  MoatItem,
  Signpost,
  Workspace,
  WorkspaceData,
} from "./types";

export type SaveState = "idle" | "saving" | "saved" | "error";

type ByTicker = Stats["by_ticker"];

export type Overlays = {
  quotes: Record<string, number | null>;
  openTickers: Set<string>;
  byTicker: ByTicker;
  ensureQuotes: (tickers: string[]) => void;
};

type Ctx = {
  data: WorkspaceData;
  revision: number;
  saveState: SaveState;
  patchCompany: (ticker: string, patch: Partial<Company>) => void;
  patchLayer: (id: string, patch: Partial<Layer>) => void;
  patchMoat: (cluster: string, ticker: string, patch: Partial<MoatItem>) => void;
  patchDeep: (ticker: string, patch: Partial<DeepDive>) => void;
  patchSignpost: (id: string, patch: Partial<Signpost>) => void;
  cycleSignpost: (id: string) => void;
  toggleShort: (ticker: string) => void;
  moveShort: (ticker: string, dir: -1 | 1) => void;
  setChecklistAnswer: (
    ticker: string,
    checkId: string,
    patch: Partial<ChecklistAnswer>
  ) => void;
  overlays: Overlays;
};

const WorkspaceContext = createContext<Ctx | null>(null);

export function useWorkspace(): Ctx {
  const ctx = useContext(WorkspaceContext);
  if (!ctx) throw new Error("useWorkspace must be used within WorkspaceProvider");
  return ctx;
}

export function WorkspaceProvider({ children }: { children: React.ReactNode }) {
  const [data, setData] = useState<WorkspaceData | null>(null);
  const [revision, setRevision] = useState(0);
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [loadError, setLoadError] = useState<string | null>(null);

  const dataRef = useRef<WorkspaceData | null>(null);
  const revisionRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const savingRef = useRef(false);
  const pendingRef = useRef(false);

  // ---- overlays ----
  const [quotes, setQuotes] = useState<Record<string, number | null>>({});
  const [openTickers, setOpenTickers] = useState<Set<string>>(new Set());
  const [byTicker, setByTicker] = useState<ByTicker>({});
  const requestedQuotes = useRef<Set<string>>(new Set());

  // ---- initial load ----
  useEffect(() => {
    let alive = true;
    getWorkspace(SLUG)
      .then((ws: Workspace) => {
        if (!alive) return;
        dataRef.current = ws.data;
        revisionRef.current = ws.revision;
        setData(ws.data);
        setRevision(ws.revision);
      })
      .catch((e) => alive && setLoadError(String(e)));

    api
      .trades("status=open")
      .then((trades) => {
        if (alive) setOpenTickers(new Set(trades.map((t) => t.ticker)));
      })
      .catch(() => {});
    api
      .stats()
      .then((s) => alive && setByTicker(s.by_ticker ?? {}))
      .catch(() => {});

    return () => {
      alive = false;
    };
  }, []);

  const doSave = useCallback(async () => {
    if (savingRef.current) {
      pendingRef.current = true;
      return;
    }
    if (!dataRef.current) return;
    savingRef.current = true;
    setSaveState("saving");
    try {
      let attempts = 0;
      // Retry loop implements last-write-wins for a single user: on a stale
      // revision, adopt the server's and re-save local edits rather than lose
      // the just-typed change.
      // eslint-disable-next-line no-constant-condition
      while (true) {
        try {
          const res = await saveWorkspace(
            SLUG,
            revisionRef.current,
            dataRef.current
          );
          revisionRef.current = res.revision;
          setRevision(res.revision);
          break;
        } catch (e) {
          if (e instanceof RevisionConflictError && attempts < 3) {
            revisionRef.current = e.current.revision;
            attempts += 1;
            continue;
          }
          throw e;
        }
      }
      setSaveState("saved");
    } catch {
      setSaveState("error");
    } finally {
      savingRef.current = false;
      if (pendingRef.current) {
        pendingRef.current = false;
        void doSave();
      }
    }
  }, []);

  const scheduleSave = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => void doSave(), 500);
  }, [doSave]);

  const mutate = useCallback(
    (updater: (d: WorkspaceData) => WorkspaceData) => {
      const prev = dataRef.current;
      if (!prev) return;
      const next = updater(prev);
      if (next === prev) return;
      dataRef.current = next;
      setData(next);
      setSaveState("saving");
      scheduleSave();
    },
    [scheduleSave]
  );

  const patchCompany = useCallback(
    (ticker: string, patch: Partial<Company>) =>
      mutate((d) =>
        d.companies[ticker]
          ? {
              ...d,
              companies: {
                ...d.companies,
                [ticker]: { ...d.companies[ticker], ...patch },
              },
            }
          : d
      ),
    [mutate]
  );

  const patchLayer = useCallback(
    (id: string, patch: Partial<Layer>) =>
      mutate((d) =>
        d.layers[id]
          ? { ...d, layers: { ...d.layers, [id]: { ...d.layers[id], ...patch } } }
          : d
      ),
    [mutate]
  );

  const patchMoat = useCallback(
    (cluster: string, ticker: string, patch: Partial<MoatItem>) =>
      mutate((d) => {
        const cl = d.moat[cluster];
        if (!cl) return d;
        return {
          ...d,
          moat: {
            ...d.moat,
            [cluster]: {
              ...cl,
              items: cl.items.map((it) =>
                it.ticker === ticker ? { ...it, ...patch } : it
              ),
            },
          },
        };
      }),
    [mutate]
  );

  const patchDeep = useCallback(
    (ticker: string, patch: Partial<DeepDive>) =>
      mutate((d) => ({
        ...d,
        deepDives: {
          ...d.deepDives,
          [ticker]: { ...(d.deepDives[ticker] ?? {}), ...patch },
        },
      })),
    [mutate]
  );

  const patchSignpost = useCallback(
    (id: string, patch: Partial<Signpost>) =>
      mutate((d) => ({
        ...d,
        signposts: d.signposts.map((s) =>
          s.id === id ? { ...s, ...patch } : s
        ),
      })),
    [mutate]
  );

  const cycleSignpost = useCallback(
    (id: string) =>
      mutate((d) => ({
        ...d,
        signposts: d.signposts.map((s) =>
          s.id === id ? { ...s, level: SIGNAL_NEXT[s.level] } : s
        ),
      })),
    [mutate]
  );

  const toggleShort = useCallback(
    (ticker: string) =>
      mutate((d) => {
        const c = d.companies[ticker];
        if (!c) return d;
        const now = !c.short;
        let order = d.shortlistOrder.filter((x) => x !== ticker);
        if (now) {
          if (order.length >= 10) return d; // cap shortlist at 10
          order = [...order, ticker];
        }
        return {
          ...d,
          companies: { ...d.companies, [ticker]: { ...c, short: now } },
          shortlistOrder: order,
        };
      }),
    [mutate]
  );

  const moveShort = useCallback(
    (ticker: string, dir: -1 | 1) =>
      mutate((d) => {
        const o = [...d.shortlistOrder];
        const i = o.indexOf(ticker);
        const j = i + dir;
        if (i < 0 || j < 0 || j >= o.length) return d;
        [o[i], o[j]] = [o[j], o[i]];
        return { ...d, shortlistOrder: o };
      }),
    [mutate]
  );

  const setChecklistAnswer = useCallback(
    (ticker: string, checkId: string, patch: Partial<ChecklistAnswer>) =>
      mutate((d) => {
        const perT = d.checklistByTicker[ticker] ?? {};
        const cur = perT[checkId] ?? { checked: false, notes: "" };
        return {
          ...d,
          checklistByTicker: {
            ...d.checklistByTicker,
            [ticker]: { ...perT, [checkId]: { ...cur, ...patch } },
          },
        };
      }),
    [mutate]
  );

  const ensureQuotes = useCallback((tickers: string[]) => {
    const missing = tickers.filter(
      (t) => t && !requestedQuotes.current.has(t)
    );
    if (missing.length === 0) return;
    missing.forEach((t) => requestedQuotes.current.add(t));
    api
      .stockQuotes(missing)
      .then((res) => setQuotes((prev) => ({ ...prev, ...res })))
      .catch(() => {
        // Allow a later retry if the batch failed.
        missing.forEach((t) => requestedQuotes.current.delete(t));
      });
  }, []);

  if (loadError) {
    return (
      <div className="p-6 text-sm text-red-400">
        Failed to load research workspace: {loadError}
      </div>
    );
  }
  if (!data) {
    return (
      <div className="p-6 text-sm text-muted-foreground">Loading cockpit…</div>
    );
  }

  const value: Ctx = {
    data,
    revision,
    saveState,
    patchCompany,
    patchLayer,
    patchMoat,
    patchDeep,
    patchSignpost,
    cycleSignpost,
    toggleShort,
    moveShort,
    setChecklistAnswer,
    overlays: { quotes, openTickers, byTicker, ensureQuotes },
  };

  return (
    <WorkspaceContext.Provider value={value}>
      {children}
    </WorkspaceContext.Provider>
  );
}
