"use client";

import { useSyncExternalStore } from "react";
import { api, GmailHealth } from "@/lib/api";

// One poll shared by every subscriber (the nav line and the banner): once on
// mount, then the app-wide 30s cadence skipped while the tab is hidden, plus
// an immediate check when a hidden tab (a phone coming back) becomes visible.
const POLL_MS = 30000;

let health: GmailHealth | null = null;
type HealthSnapshot = { health: GmailHealth | null; state: "checking" | "ready" | "unavailable"; lastSuccessAt: string | null };
const INITIAL_SNAPSHOT: HealthSnapshot = { health: null, state: "checking", lastSuccessAt: null };
let snapshot: HealthSnapshot = INITIAL_SNAPSHOT;
let timer: ReturnType<typeof setInterval> | null = null;
const listeners = new Set<() => void>();

async function refresh() {
  try {
    health = await api.gmailHealth();
    snapshot = { health, state: "ready", lastSuccessAt: new Date().toISOString() };
  } catch {
    // Legacy consumers retain the last health object; status-aware consumers
    // can disclose that it is historical. All subscribers still share one poll.
    snapshot = { ...snapshot, state: "unavailable" };
  }
  listeners.forEach((listener) => listener());
}

function onVisible() {
  if (!document.hidden) void refresh();
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  if (listeners.size === 1) {
    void refresh();
    timer = setInterval(() => {
      if (!document.hidden) void refresh();
    }, POLL_MS);
    document.addEventListener("visibilitychange", onVisible);
  }
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0) {
      if (timer) clearInterval(timer);
      timer = null;
      document.removeEventListener("visibilitychange", onVisible);
    }
  };
}

export function useGmailHealth(): GmailHealth | null {
  return useSyncExternalStore(subscribe, () => health, () => null);
}

export function useGmailHealthSnapshot() {
  return useSyncExternalStore(subscribe, () => snapshot, () => INITIAL_SNAPSHOT);
}
