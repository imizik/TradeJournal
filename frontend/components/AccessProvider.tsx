"use client";
import { createContext, useContext, useEffect } from "react";
import { PRIVATE_ACCESS, type AppAccess } from "@/lib/accessTypes";
const Context = createContext<AppAccess>(PRIVATE_ACCESS);
export function useAppAccess() { return useContext(Context); }
export default function AccessProvider({ access, children }: { access: AppAccess; children: React.ReactNode }) {
  useEffect(() => {
    if (!access.enabled || !access.csrf) return;
    const original = window.fetch;
    const wrapped: typeof fetch = (input, init) => {
      const raw = input instanceof Request ? input.url : String(input);
      const url = new URL(raw, window.location.href);
      const method = (init?.method ?? (input instanceof Request ? input.method : "GET")).toUpperCase();
      if (url.origin === window.location.origin && url.pathname.startsWith("/api/") && !["GET", "HEAD"].includes(method)) {
        const headers = new Headers(init?.headers ?? (input instanceof Request ? input.headers : undefined));
        headers.set("x-tj-csrf", access.csrf);
        return original(input, { ...init, headers });
      }
      return original(input, init);
    };
    window.fetch = wrapped;
    return () => { if (window.fetch === wrapped) window.fetch = original; };
  }, [access]);
  return <Context.Provider value={access}>{children}</Context.Provider>;
}
