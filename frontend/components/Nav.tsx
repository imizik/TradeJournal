"use client";

import { useAppAccess } from "@/components/AccessProvider";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { LayoutDashboard, FileText, BarChart2, ChartCandlestick, Activity, ClipboardList, FlaskConical, GitBranch, Radio, ChevronRight, Menu, PanelLeftClose, PanelLeftOpen, X } from "lucide-react";
import { cn } from "@/lib/utils";
import StatusPanel, { useAnyJobRunning } from "@/components/StatusPanel";
import { useGmailHealth } from "@/lib/useGmailHealth";
import type { GmailHealth } from "@/lib/api";
import { fullScreenRoute } from "@/components/AppMain";

/** Whether the charts page shows the full sidebar instead of the icon rail, on this device only (C7.3). */
const CHARTS_NAV_KEY = "tradejournal.charts.nav.v1";

const navItems = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/access", label: "Assistant access", icon: FileText },
  { href: "/charts", label: "Charts", icon: ChartCandlestick },
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

function SyncStatusLine({ inline = false }: { inline?: boolean }) {
  const health = useGmailHealth();
  if (!health) return null;
  const { label, dot } = SYNC_STATUS[health.status];
  return (
    <p className={cn("flex shrink-0 items-center gap-1.5 text-[11px] text-muted-foreground", !inline && "mt-1")} title={health.message}>
      <span className={cn("inline-block h-1.5 w-1.5 rounded-full", dot)} />
      {health.action === "reconnect_gmail" ? "Gmail disconnected" : label}
    </p>
  );
}

/** The rail's sync state: a dot, named for screen readers and in its tooltip. */
function SyncStatusDot() {
  const health = useGmailHealth();
  if (!health) return null;
  const { label, dot } = SYNC_STATUS[health.status];
  const text = health.action === "reconnect_gmail" ? "Gmail disconnected" : label;
  return (
    <span role="status" title={`${text}. ${health.message}`} className="flex h-6 w-10 items-center justify-center">
      <span className={cn("inline-block h-2 w-2 rounded-full", dot)} />
      <span className="sr-only">{text}</span>
    </span>
  );
}

/** Opens the sync/enrichment drawer. Shared by the sidebar, the charts rail and the phone bar. */
function SyncTrigger({ open, running, onToggle, compact = false }: { open: boolean; running: boolean; onToggle: () => void; compact?: boolean }) {
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
      {!compact && <ChevronRight className={cn("h-3.5 w-3.5 transition-transform duration-200", open && "rotate-180")} />}
    </button>
  );
}

/** Which pages this viewer may open: the owner sees all; an assistant sees the practice pages and, with journal access, the journal. */
function shownHref(href: string, owner: boolean, enabled: boolean, journal: boolean, frozenOnly = false) {
  if (!owner && frozenOnly) return ["/", "/daily"].includes(href);
  if (href === "/access") return owner && enabled;
  return owner || ["/", "/charts", "/daily", ...(journal ? ["/trades", "/fills", "/analytics"] : [])].includes(href);
}

/** The phone tab bar's pages; everything else is under More. */
const TABS = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/charts", label: "Charts", icon: ChartCandlestick },
  { href: "/daily", label: "Daily", icon: ClipboardList },
  { href: "/trades", label: "Trades", icon: FileText },
];

/** Sync needs attention: delayed or stopped (a scheduled-only setup is normal and says nothing). */
const syncTrouble = (health: GmailHealth | null) => !!health && (health.status === "degraded" || health.status === "down");

/**
 * The More tab: opens the menu, and for the owner carries a dot (and says so to
 * a screen reader) while sync needs attention. Only the owner reads sync health:
 * an assistant session never calls the journal's endpoints.
 */
function MoreTab({ open, onOpen, owner }: { open: boolean; onOpen: () => void; owner: boolean }) {
  return owner ? <OwnerMoreTab open={open} onOpen={onOpen} /> : <MoreButton open={open} onOpen={onOpen} trouble={null} />;
}

function OwnerMoreTab({ open, onOpen }: { open: boolean; onOpen: () => void }) {
  const health = useGmailHealth();
  return <MoreButton open={open} onOpen={onOpen} trouble={syncTrouble(health) ? SYNC_STATUS[health!.status] : null} />;
}

function MoreButton({ open, onOpen, trouble }: { open: boolean; onOpen: () => void; trouble: { label: string; dot: string } | null }) {
  return (
    <button onClick={onOpen} aria-label={trouble ? `Open menu, ${trouble.label.toLowerCase()}` : "Open menu"} aria-expanded={open}
      className="relative flex min-h-14 flex-1 flex-col items-center justify-center gap-0.5 text-[11px] font-medium text-muted-foreground hover:text-foreground">
      <Menu className="h-5 w-5" aria-hidden />
      More
      {trouble && <span aria-hidden className={cn("absolute right-[calc(50%-14px)] top-2 h-2 w-2 rounded-full", trouble.dot)} />}
    </button>
  );
}

function NavLinks({ pathname, onNavigate, rail = false }: { pathname: string; onNavigate?: () => void; rail?: boolean }) {
  const { owner, grants, enabled } = useAppAccess();
  const journal = owner || !!grants.journal_read;
  return (
    <ul className="space-y-1">
      {navItems.filter(item => shownHref(item.href, owner, enabled, journal, grants.market_decision_write)).map(({ href, label, icon: Icon }) => {
        const isActive = pathname === href || (href !== "/" && pathname.startsWith(href));
        return (
          <li key={href}>
            <Link
              href={href}
              onClick={onNavigate}
              // The rail shows icons only: the name is the link's label and its tooltip.
              aria-label={rail ? label : undefined}
              aria-current={isActive ? "page" : undefined}
              title={rail ? label : undefined}
              className={cn(
                // min-h-11 keeps every row a comfortable tap target on a phone.
                rail
                  ? "flex h-10 w-10 items-center justify-center rounded-md transition-colors"
                  : "flex min-h-11 items-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                isActive
                  ? "bg-secondary text-foreground"
                  : "text-muted-foreground hover:bg-secondary hover:text-foreground"
              )}
            >
              <Icon className="h-4 w-4 shrink-0" />
              {!rail && label}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

export function Nav({ owner = true, journal = true }: { owner?: boolean; journal?: boolean }) {
  const pathname = usePathname();
  const [panelOpen, setPanelOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const anyRunning = useAnyJobRunning(owner);
  const access = useAppAccess();
  const enabled = access.enabled;
  // The layout passes journal access (owner, or an assistant granted the journal).
  const journalOn = journal;
  // On the charts page the sidebar is a rail of icons unless this device asked for the full one.
  const chartsRoute = fullScreenRoute(pathname);
  const [wide, setWide] = useState(false);
  useEffect(() => {
    try { if (localStorage.getItem(CHARTS_NAV_KEY) === "expanded") setWide(true); } catch { /* the rail */ }
  }, []);
  const expand = (next: boolean) => {
    setWide(next);
    try { localStorage.setItem(CHARTS_NAV_KEY, next ? "expanded" : "collapsed"); } catch { /* remembered for this visit only */ }
  };
  const rail = chartsRoute && !wide;

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
      {/* Phone: a slim title bar in normal flow; navigation is the tab bar at the bottom. The charts page gives this height to the chart. */}
      <header className={cn("sticky top-0 z-30 items-center gap-2 border-b bg-card px-3 pb-1.5 pt-[calc(0.375rem+env(safe-area-inset-top))] md:hidden", chartsRoute ? "hidden" : "flex")}>
        <div className="flex min-w-0 flex-1 items-baseline gap-2">
          <h1 className="truncate text-sm font-semibold text-foreground">Trade Journal</h1>
          {owner && <SyncStatusLine inline />}
        </div>
        {owner && <SyncTrigger open={panelOpen} running={anyRunning} onToggle={() => setPanelOpen((o) => !o)} />}
      </header>

      {menuOpen && (
        <div role="dialog" aria-modal="true" aria-label="Menu" className="fixed inset-0 z-50 md:hidden">
          <div className="absolute inset-0 bg-black/60" onClick={() => setMenuOpen(false)} aria-hidden />
          <nav className="absolute inset-y-0 left-0 flex w-64 max-w-[80%] flex-col overflow-y-auto border-r bg-card p-4 pt-[calc(1rem+env(safe-area-inset-top))]">
            <div className="mb-6 flex items-start justify-between gap-2">
              <div className="min-w-0">
                <h2 className="text-lg font-semibold text-foreground">Trade Journal</h2>
                {owner && <SyncStatusLine />}
                {/* The charts page hides the phone title bar; the Sync drawer stays reachable here. */}
                {owner && <div className="mt-2 -ml-2"><SyncTrigger open={panelOpen} running={anyRunning} onToggle={() => { setMenuOpen(false); setPanelOpen(true); }} /></div>}
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

      {/* Phone: the pages used most are one tap away at the bottom; More opens the full menu. */}
      <nav aria-label="Main tabs" className="fixed inset-x-0 bottom-0 z-40 flex border-t bg-card pb-[env(safe-area-inset-bottom)] pl-[env(safe-area-inset-left)] pr-[env(safe-area-inset-right)] md:hidden">
        {TABS.filter(({ href }) => shownHref(href, access.owner, enabled, journalOn, access.grants.market_decision_write)).map(({ href, label, icon: Icon }) => {
          const active = pathname === href || (href !== "/" && pathname.startsWith(href));
          return (
            <Link key={href} href={href} aria-current={active ? "page" : undefined}
              className={cn("flex min-h-14 flex-1 flex-col items-center justify-center gap-0.5 text-[11px] font-medium transition-colors", active ? "text-foreground" : "text-muted-foreground hover:text-foreground")}>
              <Icon className={cn("h-5 w-5", active && "text-primary")} />
              {label}
            </Link>
          );
        })}
        <MoreTab open={menuOpen} onOpen={() => setMenuOpen(true)} owner={owner} />
      </nav>

      {/* Desktop: on the charts page, a rail of icons that gives the charts the width */}
      {rail && (
        <nav className="sticky top-0 hidden h-screen w-12 shrink-0 flex-col items-center gap-1 overflow-y-auto border-r bg-card py-2 md:flex">
          <button
            onClick={() => expand(true)}
            aria-label="Expand navigation"
            title="Expand navigation"
            className="mb-1 flex h-10 w-10 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-secondary hover:text-foreground"
          >
            <PanelLeftOpen className="h-4 w-4" />
          </button>
          <NavLinks pathname={pathname} rail />
          <div className="mt-auto" />
          {owner && <SyncStatusDot />}
          {owner && <SyncTrigger open={panelOpen} running={anyRunning} onToggle={() => setPanelOpen((o) => !o)} compact />}
        </nav>
      )}

      {/* Desktop sidebar */}
      <nav className={cn("sticky top-0 hidden h-screen w-56 shrink-0 flex-col border-r bg-card p-4", !rail && "md:flex")}>
        <div className="mb-6 flex items-start justify-between gap-2">
          <div className="min-w-0">
            <h1 className="text-lg font-semibold text-foreground">Trade Journal</h1>
            {owner && <SyncStatusLine />}
          </div>
          {chartsRoute && (
            <button
              onClick={() => expand(false)}
              aria-label="Collapse navigation"
              title="Collapse navigation"
              className="-mr-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-secondary hover:text-foreground"
            >
              <PanelLeftClose className="h-4 w-4" />
            </button>
          )}
        </div>

        <NavLinks pathname={pathname} />

        <div className="mt-auto" />

        {/* Trigger button — bottom right corner of sidebar */}
        <div className="flex justify-end pb-1 pt-3">
          {owner && <SyncTrigger open={panelOpen} running={anyRunning} onToggle={() => setPanelOpen((o) => !o)} />}
        </div>
      </nav>

      {/* Drawer — fixed, independent of nav DOM, slides in from left */}
      {owner && <StatusPanel open={panelOpen} onClose={() => setPanelOpen(false)} />}
    </>
  );
}
