"use client";

import { useSyncExternalStore } from "react";
import { api, GmailHealth } from "@/lib/api";

// One poll shared by every subscriber (the nav line and the banner): once on
// mount, then the app-wide 30s cadence skipped while the tab is hidden, plus
// an immediate check when a hidden tab (a phone coming back) becomes visible.
const POLL_MS = 30000;

let health: GmailHealth | null = null;
let timer: ReturnType<typeof setInterval> | null = null;
const listeners = new Set<() => void>();

async function refresh() {
  try {
    health = await api.gmailHealth();
  } catch {
    return; // keep the last answer; the API may be restarting
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
