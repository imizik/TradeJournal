"use client";

import { useAppAccess } from "@/components/AccessProvider";
import Link, { useLinkStatus } from "next/link";
import NavHint from "@/components/NavHint";
import { usePathname } from "next/navigation";
import { useEffect, useState, useSyncExternalStore } from "react";
import { useCopilotOn } from "@/components/copilot/useCopilotOn";
import PlanATrade from "@/components/copilot/PlanATrade";
import PlanStreakChip from "@/components/PlanStreak";
import { Bot, Crosshair, LayoutDashboard, MessagesSquare, FileText, BarChart2, ChartCandlestick, Activity, ClipboardList, FlaskConical, GitBranch, Radio, Radar, Rocket, Scale, Target, Telescope, ChevronRight, ClipboardCheck, Menu, Sun, PanelLeftClose, PanelLeftOpen, X } from "lucide-react";
import { cn } from "@/lib/utils";
import StatusPanel, { useAnyJobRunning } from "@/components/StatusPanel";
import { useGmailHealth } from "@/lib/useGmailHealth";
import type { GmailHealth } from "@/lib/api";
import { fullScreenRoute } from "@/components/AppMain";

/** On a clicked link while its page loads: the click answers at once, and a fast page
 * is not held back by a loading screen (React delays revealing those by ~300ms). */
function Pending({ corner = false }: { corner?: boolean }) {
  const { pending } = useLinkStatus();
  return <span aria-hidden data-testid={pending ? "nav-pending" : undefined}
    className={cn("h-1.5 w-1.5 shrink-0 rounded-full bg-primary transition-opacity", pending ? "animate-pulse opacity-100" : "opacity-0", corner ? "absolute right-1 top-1" : "ml-auto")} />;
}

/** Whether the charts page and the desk show the full sidebar instead of the icon rail (or the desk's Menu button), on
 * this device only (C7.3). */
const CHARTS_NAV_KEY = "tradejournal.charts.nav.v1";

// On the desk the rail folds into one Menu button in the desk bar, so the desk gets the full width: the bar reads whether
// the navigation is folded and opens the menu through this small store.
let folded = false;
let opener: (() => void) | null = null;
const foldListeners = new Set<() => void>();
function setFolded(next: boolean) {
  if (folded === next) return;
  folded = next;
  foldListeners.forEach(listener => listener());
}
const subscribeFolded = (listener: () => void) => { foldListeners.add(listener); return () => { foldListeners.delete(listener); }; };
/** True while the navigation is folded into the desk bar's Menu button (a wide screen on the desk, rail not expanded). */
export const useFoldedNav = () => useSyncExternalStore(subscribeFolded, () => folded, () => false);
export const openNavMenu = () => opener?.();

type NavItem = { href: string; label: string; icon: typeof Bot };

/** The three pages always in view. */
const PRIMARY: NavItem[] = [
  { href: "/today", label: "Today", icon: Sun }, // owner-only: what matters right now
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/charts", label: "Charts", icon: ChartCandlestick },
];

/** Everything else, folded away until asked for. */
const GROUPS: { name: string; items: NavItem[] }[] = [
  { name: "Journal", items: [
    { href: "/trades", label: "Trades", icon: FileText },
    { href: "/fills", label: "Fills", icon: Activity },
    { href: "/daily", label: "Daily Review", icon: ClipboardList },
    { href: "/analytics", label: "Analytics", icon: BarChart2 },
  ] },
  { name: "Market", items: [
    { href: "/radar", label: "Radar", icon: Telescope },
    { href: "/scanner", label: "Scanner", icon: Radar },
    { href: "/signals", label: "Signals", icon: Radio },
    { href: "/morning", label: "Jo", icon: Bot },
    { href: "/proof", label: "Proof", icon: ClipboardCheck },
    { href: "/experiments", label: "Experiments", icon: FlaskConical },
  ] },
  { name: "Practice", items: [
    { href: "/practice", label: "Daily Practice", icon: Target },
    { href: "/advisor-review", label: "Advisor review", icon: Scale },
    { href: "/strategy-lab", label: "Strategy Lab", icon: GitBranch },
    { href: "/level2-lab", label: "Level 2 lab", icon: FlaskConical },
  ] },
  { name: "Research", items: [
    { href: "/research-studio", label: "Research Studio", icon: FlaskConical },
    { href: "/research/companies", label: "Company Research", icon: FileText },
    { href: "/research/ai-buildout", label: "AI Buildout", icon: FileText },
  ] },
];

/** The owner's two housekeeping pages, as quiet links beside Sync. */
const QUIET: NavItem[] = [
  { href: "/access", label: "Assistant access", icon: FileText },
  { href: "/deploys", label: "Deploys", icon: Rocket },
];

const isCurrent = (pathname: string, href: string) => pathname === href || (href !== "/" && pathname.startsWith(href));

/** Which groups are open, on this device only. The current page's group opens by itself without being remembered, and a
 * click can still close it until the next page. */
const NAV_GROUPS_KEY = "tradejournal.nav.groups.v1";
type NavGroups = { isOpen: (name: string) => boolean; toggle: (name: string) => void };
function useNavGroups(pathname: string): NavGroups {
  const [remembered, setRemembered] = useState<Record<string, boolean>>({});
  const [closedHere, setClosedHere] = useState<string | null>(null);
  useEffect(() => {
    try { setRemembered(JSON.parse(localStorage.getItem(NAV_GROUPS_KEY) ?? "{}") ?? {}); } catch { /* all folded */ }
  }, []);
  useEffect(() => setClosedHere(null), [pathname]);
  const isOpen = (name: string) => !!remembered[name] || (closedHere !== `${pathname}|${name}` && !!GROUPS.find(group => group.name === name)?.items.some(item => isCurrent(pathname, item.href)));
  const toggle = (name: string) => {
    const open = !isOpen(name);
    const next = { ...remembered, [name]: open };
    setRemembered(next);
    setClosedHere(open ? null : `${pathname}|${name}`);
    try { localStorage.setItem(NAV_GROUPS_KEY, JSON.stringify(next)); } catch { /* remembered for this visit only */ }
  };
  return { isOpen, toggle };
}

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
    <NavHint label={`${text}. ${health.message}`}>
      <span role="status" className="flex h-6 w-10 items-center justify-center">
        <span className={cn("inline-block h-2 w-2 rounded-full", dot)} />
        <span className="sr-only">{text}</span>
      </span>
    </NavHint>
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
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-muted-foreground opacity-75" />
          <span className="relative inline-flex h-2 w-2 rounded-full bg-muted-foreground" />
        </span>
      )}
      <span className="text-[11px] font-medium">Sync</span>
      {!compact && <ChevronRight className={cn("h-3.5 w-3.5 transition-transform duration-200", open && "rotate-180")} />}
    </button>
  );
}

/** While the Copilot Lab is on, the desk is home: it takes Today's place, first in the menu and on the phone's tab bar
 * (Today forwards there). */
const DESK = { href: "/copilot-lab", label: "Desk", icon: MessagesSquare };
function withDesk<T extends { href: string }>(items: T[], copilot: boolean): T[] {
  if (!copilot) return items;
  return items.map(item => (item.href === "/today" ? { ...item, ...DESK } : item));
}

/** Which pages this viewer may open: the owner sees all; an assistant sees the practice pages and, with journal access, the journal. */
function shownHref(href: string, owner: boolean, enabled: boolean, journal: boolean, frozenOnly = false) {
  if (!owner && frozenOnly) return ["/", "/daily"].includes(href);
  if (href === "/access") return owner && enabled;
  return owner || ["/", "/charts", "/daily", ...(journal ? ["/trades", "/fills", "/analytics"] : [])].includes(href);
}

/** The phone tab bar's pages; everything else is under More. The owner gets Today (or Desk), Dashboard, Charts and Trades, with Daily Review under More; an assistant keeps Daily Review. */
const TABS = [
  { href: "/today", label: "Today", icon: Sun },
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/charts", label: "Charts", icon: ChartCandlestick },
  { href: "/daily", label: "Daily Review", icon: ClipboardList },
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

/** The phone's thumb-reachable "Plan a trade": a lit tab beside Charts, owner-only and only while the lab is on. */
function PlanTab() {
  return <PlanATrade origin="manual" className="flex min-h-14 flex-1 flex-col items-center justify-center gap-0.5 text-[11px] font-medium text-primary hover:text-primary/90">
    <span className="flex h-6 w-9 items-center justify-center rounded-full bg-primary text-primary-foreground"><Crosshair className="h-4 w-4" aria-hidden /></span>
    <span><span className="sr-only">Plan a trade</span><span aria-hidden>Plan</span></span>
  </PlanATrade>;
}

function NavLink({ item: { href, label, icon: Icon }, pathname, onNavigate, rail = false }: { item: NavItem; pathname: string; onNavigate?: () => void; rail?: boolean }) {
  const isActive = isCurrent(pathname, href);
  const link = (
    <Link
      href={href}
      onClick={onNavigate}
      // The rail shows icons only: the name is the link's label and its tooltip.
      aria-label={rail ? label : undefined}
      aria-current={isActive ? "page" : undefined}
      className={cn(
        // min-h-11 keeps every row a comfortable tap target on a phone.
        rail
          ? "relative flex h-10 w-10 items-center justify-center rounded-md transition-colors"
          : "flex min-h-11 items-center gap-2.5 rounded-md px-2.5 py-2 text-[13.5px] transition-colors md:min-h-9",
        isActive
          ? "bg-secondary font-medium text-foreground"
          : "text-muted-foreground hover:bg-secondary hover:text-foreground"
      )}
    >
      <Icon className="h-4 w-4 shrink-0" />
      {!rail && label}
      <Pending corner={rail} />
    </Link>
  );
  return <li>{rail ? <NavHint label={label}>{link}</NavHint> : link}</li>;
}

/** The three primary links, then (unless on the rail, whose More button opens them) the groups this viewer has pages in. */
function NavLinks({ pathname, groups, onNavigate, rail = false }: { pathname: string; groups?: NavGroups; onNavigate?: () => void; rail?: boolean }) {
  const { owner, grants, enabled } = useAppAccess();
  const journal = owner || !!grants.journal_read;
  const copilot = useCopilotOn(); // the owner's, and only while the lab is on
  const shown = (item: NavItem) => shownHref(item.href, owner, enabled, journal, grants.market_decision_write);
  return <>
    <ul className="space-y-1">
      {withDesk(PRIMARY, copilot).filter(shown).map(item => <NavLink key={item.href} item={item} pathname={pathname} onNavigate={onNavigate} rail={rail} />)}
    </ul>
    {groups && <ul className="mt-3 space-y-1">
      {GROUPS.map(({ name, items }) => {
        const visible = items.filter(shown);
        if (!visible.length) return null;
        const open = groups.isOpen(name);
        return <li key={name}>
          <button type="button" onClick={() => groups.toggle(name)} aria-expanded={open}
            className="flex min-h-11 w-full items-center gap-1.5 rounded-md px-2.5 text-[11px] font-medium uppercase tracking-wider text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground md:min-h-8">
            <ChevronRight aria-hidden className={cn("h-3.5 w-3.5 shrink-0 transition-transform duration-200", open && "rotate-90")} />
            {name}
          </button>
          {open && <ul className="mt-1 space-y-1">
            {visible.map(item => <NavLink key={item.href} item={item} pathname={pathname} onNavigate={onNavigate} />)}
          </ul>}
        </li>;
      })}
    </ul>}
  </>;
}

/** Assistant access and Deploys: the owner's, small and out of the way. */
function QuietLinks({ pathname, onNavigate }: { pathname: string; onNavigate?: () => void }) {
  const { owner, grants, enabled } = useAppAccess();
  return <>
    {QUIET.filter(({ href }) => shownHref(href, owner, enabled, owner || !!grants.journal_read, grants.market_decision_write)).map(({ href, label }) => {
      const active = isCurrent(pathname, href);
      return <Link key={href} href={href} onClick={onNavigate} aria-current={active ? "page" : undefined}
        className={cn("flex h-11 shrink-0 items-center whitespace-nowrap rounded-md px-1 text-[11px] transition-colors hover:bg-secondary hover:text-foreground md:h-auto md:py-1.5", active ? "font-medium text-foreground" : "text-muted-foreground")}>{label}</Link>;
    })}
  </>;
}

export function Nav({ owner = true, journal = true }: { owner?: boolean; journal?: boolean }) {
  const pathname = usePathname();
  const [panelOpen, setPanelOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const anyRunning = useAnyJobRunning(owner);
  const access = useAppAccess();
  const copilot = useCopilotOn(); // the owner's, and only while the lab is on: then the desk is home
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
  // The desk folds the rail into its bar's Menu button; the full sidebar still shows when this device asked for it.
  const deskMenu = pathname === "/copilot-lab" && !wide;
  const rail = chartsRoute && !wide && !deskMenu;
  const groups = useNavGroups(pathname);
  useEffect(() => {
    setFolded(deskMenu);
    opener = () => setMenuOpen(true);
    return () => { setFolded(false); opener = null; };
  }, [deskMenu]);

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
        {owner && <PlanStreakChip variant="compact" />}
        {owner && <SyncTrigger open={panelOpen} running={anyRunning} onToggle={() => setPanelOpen((o) => !o)} />}
      </header>

      {menuOpen && (
        <div role="dialog" aria-modal="true" aria-label="Menu" className={cn("fixed inset-0 z-50", !deskMenu && !rail && "md:hidden")}>
          <div className="absolute inset-0 bg-black/60" onClick={() => setMenuOpen(false)} aria-hidden />
          <nav className="absolute inset-y-0 left-0 flex w-64 max-w-[80%] flex-col overflow-y-auto border-r bg-background p-4 pt-[calc(1rem+env(safe-area-inset-top))]">
            <div className="mb-6 flex items-start justify-between gap-2">
              <div className="min-w-0">
                <h2 className="flex items-center gap-2.5 text-base font-semibold tracking-tight text-foreground"><span aria-hidden className="h-[22px] w-[22px] shrink-0 rounded-md bg-primary" />Trade Journal</h2>
                {owner && <SyncStatusLine />}
                {owner && <PlanStreakChip variant="menu" onNavigate={() => setMenuOpen(false)} />}
                {/* The charts page hides the phone title bar; the Sync drawer stays reachable here. */}
                {owner && <div className="mt-2 -ml-2"><SyncTrigger open={panelOpen} running={anyRunning} onToggle={() => { setMenuOpen(false); setPanelOpen(true); }} /></div>}
                {/* The desk's wide-screen menu: the remembered choice to keep the labelled sidebar open instead. */}
                {deskMenu && <button onClick={() => { setMenuOpen(false); expand(true); }}
                  className="mt-1 -ml-2 hidden min-h-11 items-center gap-1.5 rounded-md px-2 text-xs text-muted-foreground hover:bg-secondary hover:text-foreground md:flex md:min-h-8">
                  <PanelLeftOpen className="h-3.5 w-3.5" aria-hidden />Keep the sidebar open
                </button>}
              </div>
              <button
                onClick={() => setMenuOpen(false)}
                aria-label="Close menu"
                className="-mr-1 flex h-11 w-11 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-secondary hover:text-foreground"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <NavLinks pathname={pathname} groups={groups} onNavigate={() => setMenuOpen(false)} />
            <div className="mt-auto flex flex-wrap items-center gap-1 pt-4"><QuietLinks pathname={pathname} onNavigate={() => setMenuOpen(false)} /></div>
          </nav>
        </div>
      )}

      {/* Phone: the pages used most are one tap away at the bottom; More opens the full menu. */}
      <nav aria-label="Main tabs" className="fixed inset-x-0 bottom-0 z-40 flex border-t bg-card pb-[env(safe-area-inset-bottom)] pl-[env(safe-area-inset-left)] pr-[env(safe-area-inset-right)] md:hidden">
        {withDesk(TABS, copilot).filter(({ href }) => shownHref(href, access.owner, enabled, journalOn, access.grants.market_decision_write) && !(href === "/daily" && access.owner)).map(({ href, label, icon: Icon }) => {
          const active = pathname === href || (href !== "/" && pathname.startsWith(href));
          return (
            <Link key={href} href={href} aria-current={active ? "page" : undefined}
              className={cn("relative flex min-h-14 flex-1 flex-col items-center justify-center gap-0.5 text-[11px] font-medium transition-colors", active ? "text-foreground" : "text-muted-foreground hover:text-foreground")}>
              <Icon className={cn("h-5 w-5", active && "text-primary")} />
              {label}
              <Pending corner />
            </Link>
          );
        }).flatMap((tab) => tab.key === "/charts" ? [tab, <PlanTab key="plan" />] : [tab])}
        <MoreTab open={menuOpen} onOpen={() => setMenuOpen(true)} owner={owner} />
      </nav>

      {/* Desktop: on the charts page, a rail of icons that gives the charts the width */}
      {rail && (
        <nav className="sticky top-0 hidden h-screen w-12 shrink-0 flex-col items-center gap-1 overflow-y-auto border-r bg-background py-2 md:flex">
          <NavHint label="Expand navigation"><button
            onClick={() => expand(true)}
            aria-label="Expand navigation"
            className="mb-1 flex h-10 w-10 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-secondary hover:text-foreground"
          >
            <PanelLeftOpen className="h-4 w-4" />
          </button></NavHint>
          <NavLinks pathname={pathname} rail />
          <NavHint label="More"><button
            onClick={() => setMenuOpen(true)}
            aria-label="More"
            aria-expanded={menuOpen}
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-secondary hover:text-foreground"
          >
            <Menu className="h-4 w-4" />
          </button></NavHint>
          <div className="mt-auto" />
          {owner && <NavHint label="Plan streak"><PlanStreakChip variant="rail" /></NavHint>}
          {owner && <SyncStatusDot />}
          {owner && <SyncTrigger open={panelOpen} running={anyRunning} onToggle={() => setPanelOpen((o) => !o)} compact />}
        </nav>
      )}

      {/* Desktop sidebar */}
      <nav className={cn("sticky top-0 hidden h-screen w-56 shrink-0 flex-col overflow-y-auto border-r bg-background p-3", !rail && !deskMenu && "md:flex")}>
        <div className="mb-4 flex items-start justify-between gap-2 px-1.5 pt-1">
          <div className="min-w-0">
            <h1 className="flex items-center gap-2.5 text-sm font-semibold tracking-tight text-foreground"><span aria-hidden className="h-[22px] w-[22px] shrink-0 rounded-md bg-primary" />Trade Journal</h1>
            {owner && <SyncStatusLine />}
            {owner && <PlanStreakChip />}
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

        <NavLinks pathname={pathname} groups={groups} />

        <div className="mt-auto" />

        {/* Bottom of the sidebar: the owner's quiet links, and the Sync trigger on the right */}
        <div className="flex items-center pb-1 pt-3">
          <QuietLinks pathname={pathname} />
          {owner && <div className="ml-auto"><SyncTrigger open={panelOpen} running={anyRunning} onToggle={() => setPanelOpen((o) => !o)} compact /></div>}
        </div>
      </nav>

      {/* Drawer — fixed, independent of nav DOM, slides in from left */}
      {owner && <StatusPanel open={panelOpen} onClose={() => setPanelOpen(false)} />}
    </>
  );
}
