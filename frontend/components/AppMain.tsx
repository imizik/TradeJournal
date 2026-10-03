"use client";

import { usePathname } from "next/navigation";

/** The charts workspace (C7.3) takes the whole screen beside a navigation rail; every other page keeps the padded journal shell. */
export const fullScreenRoute = (pathname: string) => pathname === "/charts" || pathname.startsWith("/charts/");

/**
 * The page column. On `/charts` a desktop gets no page padding and no page
 * scrolling: the workspace sizes its charts from the height left after the
 * Gmail banner, which stays above it when there is something to act on.
 */
export default function AppMain({ banner, children }: { banner: React.ReactNode; children: React.ReactNode }) {
  const charts = fullScreenRoute(usePathname());
  if (!charts) {
    return (
      <main className="min-w-0 flex-1 p-3 pb-[calc(0.75rem+env(safe-area-inset-bottom))] md:p-6 md:pb-6">
        {banner}
        {children}
      </main>
    );
  }
  return (
    <main data-shell="charts" className="flex min-w-0 flex-1 flex-col p-2 pb-[calc(0.5rem+env(safe-area-inset-bottom))] lg:h-dvh lg:overflow-hidden lg:p-0">
      <div className="shrink-0 empty:hidden lg:px-2 lg:pt-2 [&>*]:!mb-2">{banner}</div>
      {children}
    </main>
  );
}
