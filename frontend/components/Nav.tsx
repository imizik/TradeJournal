"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { LayoutDashboard, FileText, BarChart2, Activity, ClipboardList, FlaskConical, GitBranch, Radio, ChevronRight, Menu, X } from "lucide-react";
import { cn } from "@/lib/utils";
import StatusPanel, { useAnyJobRunning } from "@/components/StatusPanel";
import { useGmailHealth } from "@/lib/useGmailHealth";
import type { GmailHealth } from "@/lib/api";

const navItems = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/daily", label: "Daily Review", icon: ClipboardList },
  { href: "/trades", label: "Trades", icon: FileText },
  { href: "/analytics", label: "Analytics", icon: BarChart2 },
  { href: "/fills", label: "Fills", icon: Activity },
  { href: "/signals", label: "Signals", icon: Radio },
  { href: "/strategy-lab", label: "Strategy Lab", icon: GitBranch },
  { href: "/research/ai-buildout", label: "Research", icon: FlaskConical },
];

const SYNC_STATUS: Record<GmailHealth["status"], { label: string; dot: string }> = {
  live: { label: "Live sync", dot: "bg-emerald-400" },
  degraded: { label: "Sync delayed", dot: "bg-amber-400" },
  down: { label: "Sync stopped", dot: "bg-red-500" },
  off: { label: "Scheduled sync", dot: "bg-muted-foreground" },
};

function SyncStatusLine() {
  const health = useGmailHealth();
  if (!health) return null;
  const { label, dot } = SYNC_STATUS[health.status];
  return (
    <p className="mt-1 flex items-center gap-1.5 text-[11px] text-muted-foreground" title={health.message}>
      <span className={cn("inline-block h-1.5 w-1.5 rounded-full", dot)} />
      {health.action === "reconnect_gmail" ? "Gmail disconnected" : label}
    </p>
  );
}

/** Opens the sync/enrichment drawer. Shared by the sidebar and the phone bar. */
function SyncTrigger({ open, running, onToggle }: { open: boolean; running: boolean; onToggle: () => void }) {
  return (
    <button
      onClick={onToggle}
      title="Sync & enrichment status"
      className={cn(
        "relative flex h-11 items-center gap-1.5 rounded-md px-2 text-xs transition-colors md:h-auto md:py-1.5",
        open ? "bg-secondary text-foreground" : "text-muted-foreground hover:bg-secondary hover:text-foreground"
      )}
    >
      {running && (
        <span className="relative flex h-2 w-2">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-sky-400 opacity-75" />
          <span className="relative inline-flex h-2 w-2 rounded-full bg-sky-500" />
        </span>
      )}
      <span className="text-[11px] font-medium">Sync</span>
      <ChevronRight className={cn("h-3.5 w-3.5 transition-transform duration-200", open && "rotate-180")} />
    </button>
  );
}

function NavLinks({ pathname, onNavigate }: { pathname: string; onNavigate?: () => void }) {
  return (
    <ul className="space-y-1">
      {navItems.map(({ href, label, icon: Icon }) => {
        const isActive = pathname === href || (href !== "/" && pathname.startsWith(href));
        return (
          <li key={href}>
            <Link
              href={href}
              onClick={onNavigate}
              className={cn(
                // min-h-11 keeps every row a comfortable tap target on a phone.
                "flex min-h-11 items-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                isActive
                  ? "bg-secondary text-foreground"
                  : "text-muted-foreground hover:bg-secondary hover:text-foreground"
              )}
            >
              <Icon className="h-4 w-4 shrink-0" />
              {label}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

export function Nav() {
  const pathname = usePathname();
  const [panelOpen, setPanelOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const anyRunning = useAnyJobRunning();

  // A tap on a link should land on the page, not leave the menu covering it.
  useEffect(() => setMenuOpen(false), [pathname]);

  useEffect(() => {
    if (!menuOpen) return;
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && setMenuOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [menuOpen]);

  return (
    <>
      {/* Phone: a bar in normal flow, so no layout needs to reserve space for it. */}
      <header className="sticky top-0 z-30 flex items-center gap-2 border-b bg-card px-2 pb-2 pt-[calc(0.5rem+env(safe-area-inset-top))] md:hidden">
        <button
          onClick={() => setMenuOpen(true)}
          aria-label="Open menu"
          aria-expanded={menuOpen}
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-secondary hover:text-foreground"
        >
          <Menu className="h-5 w-5" />
        </button>
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-base font-semibold text-foreground">Trade Journal</h1>
          <SyncStatusLine />
        </div>
        <SyncTrigger open={panelOpen} running={anyRunning} onToggle={() => setPanelOpen((o) => !o)} />
      </header>

      {menuOpen && (
        <div className="fixed inset-0 z-50 md:hidden">
          <div className="absolute inset-0 bg-black/60" onClick={() => setMenuOpen(false)} aria-hidden />
          <nav className="absolute inset-y-0 left-0 flex w-64 max-w-[80%] flex-col overflow-y-auto border-r bg-card p-4 pt-[calc(1rem+env(safe-area-inset-top))]">
            <div className="mb-6 flex items-start justify-between gap-2">
              <div className="min-w-0">
                <h2 className="text-lg font-semibold text-foreground">Trade Journal</h2>
                <SyncStatusLine />
              </div>
              <button
                onClick={() => setMenuOpen(false)}
                aria-label="Close menu"
                className="-mr-1 flex h-11 w-11 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-secondary hover:text-foreground"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <NavLinks pathname={pathname} onNavigate={() => setMenuOpen(false)} />
          </nav>
        </div>
      )}

      {/* Desktop sidebar */}
      <nav className="sticky top-0 hidden h-screen w-56 shrink-0 flex-col border-r bg-card p-4 md:flex">
        <div className="mb-6">
          <h1 className="text-lg font-semibold text-foreground">Trade Journal</h1>
          <SyncStatusLine />
        </div>

        <NavLinks pathname={pathname} />

        <div className="mt-auto" />

        {/* Trigger button — bottom right corner of sidebar */}
        <div className="flex justify-end pb-1 pt-3">
          <SyncTrigger open={panelOpen} running={anyRunning} onToggle={() => setPanelOpen((o) => !o)} />
        </div>
      </nav>

      {/* Drawer — fixed, independent of nav DOM, slides in from left */}
      <StatusPanel open={panelOpen} onClose={() => setPanelOpen(false)} />
    </>
  );
}
