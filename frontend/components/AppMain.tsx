"use client";

import { usePathname } from "next/navigation";

/** The charts workspace (C7.3) and the Copilot desk take the whole screen beside a navigation rail; every other page keeps
 * the padded journal shell. */
export const fullScreenRoute = (pathname: string) =>
  pathname === "/charts" || pathname.startsWith("/charts/") || pathname === "/copilot-lab";

/**
 * The page column. On `/charts` a desktop gets no page padding and no page
 * scrolling: the workspace sizes its charts from the height left after the
 * Gmail banner, which stays above it when there is something to act on. Clipped, not hidden: a hidden box can still be
 * scrolled by script (a scrollIntoView inside the desk's copilot), which used to strand the page out of reach.
 */
export default function AppMain({ banner, children }: { banner: React.ReactNode; children: React.ReactNode }) {
  const charts = fullScreenRoute(usePathname());
  if (!charts) {
    return (
      // pb on a phone clears the tab bar fixed at the bottom (Nav).
      <main className="min-w-0 flex-1 p-3 pb-[calc(4.5rem+env(safe-area-inset-bottom))] md:p-6 md:pb-6">
        {banner}
        {children}
      </main>
    );
  }
  // No phone title bar here (Nav), so the top padding clears the status bar and the notch itself when the app runs
  // full screen from the home screen (env() is 0 in a browser tab and on a desktop).
  return (
    <main data-shell="charts" className="flex min-w-0 flex-1 flex-col p-2 pb-[calc(4rem+env(safe-area-inset-bottom))] pt-[calc(0.5rem+env(safe-area-inset-top))] md:pb-[calc(0.5rem+env(safe-area-inset-bottom))] lg:h-dvh lg:overflow-clip lg:p-0">
      <div className="shrink-0 empty:hidden lg:px-2 lg:pt-2 [&>*]:!mb-2">{banner}</div>
      {children}
    </main>
  );
}
