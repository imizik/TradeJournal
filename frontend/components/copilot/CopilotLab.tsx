"use client";

import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore, type CSSProperties, type PointerEvent as ReactPointerEvent } from "react";
import { createPortal } from "react-dom";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import dynamic from "next/dynamic";
import { ArrowLeft, Briefcase, CalendarCheck, ChartCandlestick, Ellipsis, LayoutGrid, ListChecks, Menu, MessageCircle, MessagesSquare, Moon, PanelLeft, Search, Sunrise, TableProperties, X } from "lucide-react";
import { openNavMenu, useDeskTabSlot, useFoldedNav } from "@/components/Nav";
import CheckACall from "@/components/copilot/CheckACall";
import ClosePass, { closeSteps } from "@/components/copilot/ClosePass";
import CommandPalette, { KBD, useJumpKey, type PaletteCommand } from "@/components/copilot/CommandPalette";
import DeskChain, { type ChainPick } from "@/components/copilot/DeskChain";
import { usePaperBook } from "@/components/copilot/DeskPaper";
import { PositionNotes } from "@/components/copilot/DeskNotes";
import { HowImDoing, Practice, RulesAndGoals, openDeskPlace, type DeskPlace } from "@/components/copilot/DeskPractice";
import DeskReplay from "@/components/copilot/DeskReplay";
import ReplayLiveLine from "@/components/copilot/ReplayLiveLine";
import PaperReviewCard from "@/components/copilot/PaperReview";
import DeskTicket, { TICKET_EVENT, openTicket, useTicketPlans, type TicketPick } from "@/components/copilot/DeskTicket";
const DeskRoll = dynamic(() => import("@/components/copilot/DeskRoll"), { ssr: false });
import type { RollFrom } from "@/lib/rollTicket";
import { useDeskActionHost } from "@/components/copilot/DeskActionCard";
import type { AnyClosingTicket } from "@/lib/closingTicket";
import CopilotPanel, { rememberedThread, type HomeActions, type PanelLink } from "@/components/copilot/CopilotPanel";
import DecisionBar from "@/components/copilot/DecisionBar";
import PingCard from "@/components/copilot/PingCard";
import FillLinkBar, { FillsToLink, useFillLinks } from "@/components/copilot/FillLinkBar";
import RadarDecision from "@/components/copilot/RadarDecision";
import { ThreadAlertAnswers, ThreadHitRating } from "@/components/copilot/ProofAnswers";
import DayReport from "@/components/copilot/DayReport";
import WatchDayLink from "@/components/replay/WatchDayLink";
import { planContext } from "@/components/copilot/PlanATrade";
import { WEEK_REVIEW_CONTEXT } from "@/components/copilot/ReviewMyWeek";
import ArmChecklist from "@/components/copilot/ArmChecklist";
import DayChecklist from "@/components/copilot/DayChecklist";
import DeskFeed, { feedQuestion, useDeskFeed, useFeedNew, type FeedItem } from "@/components/copilot/DeskFeed";
import { useDeskUnusual } from "@/components/copilot/DeskUnusual";
import { scannerGuides, useDeskScanner, type DeskScannerRow } from "@/components/copilot/DeskScanner";
import { marketWords, useDeskSession } from "@/components/copilot/SessionTape";
import { Book, CentreChart, DayFacts, NeedsStrip, RiskWord, SinceYouLooked, dayMoneyWords, positionRows, useSparks } from "@/components/copilot/Cockpit";
import type { DeskChartActions, DeskGuide } from "@/components/copilot/DeskChart";
import MorningBrief from "@/components/copilot/MorningBrief";
import Watching, { useWatching } from "@/components/copilot/Watching";
import { useDeskEvents } from "@/components/copilot/EarningsTag";
import { MovingStrip } from "@/components/copilot/MovingStrip";
import PreviousDays from "@/components/copilot/PreviousDays";
import ThreadRail from "@/components/copilot/ThreadRail";
import ThisWeek from "@/components/copilot/ThisWeek";
import { ScalpShortlistNudge } from "@/components/ScalpShortlistPanel";
import DeskThreadTop, { HorizonPick } from "@/components/copilot/ThreadHead";
import { useCopilotOn } from "@/components/copilot/useCopilotOn";
import { WHAT_MATTERS_PROMPT, copilotLabHref, mainChatLabel, type CardLink, type FeedLink, type InvestigationSummary } from "@/lib/copilot";
import { useKept } from "@/components/copilot/DeskMemory";
import { afterClose, answerSymbol, deskLinkIn, deskNeeds, liveOn, refreshRobinhood, type DeskLive, deskSymbolThread, nyDay, readOpened, saveFollow, saveHorizon, saveOpened, threadInUrl, toReview, type DeskCommand, type DeskPlan, type DeskThreads, type DeskHorizon, type DeskHooks, type DeskNeed, type DeskThread, type DeskThreadRef } from "@/lib/desk";
import { cn } from "@/lib/utils";
import type { DeskTicks } from "@/lib/deskTicks";
import { DeskAccounts, activeAccount, forAccount } from "@/components/copilot/DeskAccounts";
import { ChainPicker, PhoneOrders, PhoneValue, usePhone } from "@/components/copilot/DeskPhone";
import DeskHealthDot, { DeskStatusLine, reportBookLive } from "@/components/copilot/DeskHealth";
import { DeskSyncCenter, openSyncCenter } from "@/components/DashboardActions";
import DeskJournal, { openJournal } from "@/components/copilot/DeskJournal";
import { DeskLogs, openRadarLog, openScannerHistory } from "@/components/copilot/DeskLogs";
import { DeskResearch } from "@/components/copilot/DeskResearch";
import { ModeSwitch, PaperValue, setDeskMode, useDeskMode } from "@/components/copilot/DeskMode";
import ModeMark, { type Mode } from "@/components/copilot/ModeMark";
import { DeskUseRoot, Fold, FoldMore, FoldSuggestion, useCountOpen, useDeskUse } from "@/components/copilot/DeskUse";
import { PIECE, countOpen, countTap } from "@/lib/deskUse";
import { DESK_PLACES, PLACE, placeFromWords, type DeskPlaceId } from "@/lib/deskPlaces";
import styles from "./CopilotLab.module.css";

// The Grid's code loads the first time its tab opens.
const DeskGrid = dynamic(() => import("@/components/copilot/DeskGrid"), { ssr: false });

/** The close pass in progress (its New York day), kept for this tab: a thread with no conversation opens by its link. */
const CLOSING_KEY = "desk.closing.v1";
const CENTRE_KEY = "desk.centre.v1";
/** The New York day Start the day's checklist was last opened in this browser: until then the Day button is amber before the open. */
const STARTED_KEY = "desk.day.started.v1";
/** "Plan a trade" with nothing known: the owner names the ticker. The thread list's own button makes the same link. */
const PLAN_HREF = copilotLabHref("", planContext(), { kind: "copilot", ref: null });
const PREP_PROMPT = "Prep the day: what is armed, what news or earnings touch my positions and watches, and what would change a plan before the open?";
const ARM_PROMPT = "Arm today's plans: for each plan I mean to trade today, check its entry, invalidation and time stop against the pre-market, and propose any alert or time stop still missing for me to confirm.";
const CLOSE_PROMPT = "Close the day: for each position and plan today, did I follow the plan, and what is the one thing to repeat or change tomorrow?";

/** What opens the Data health list: the top bar's dot when it shows (a money source behind, or a phone), else the status line. */
const HEALTH_OPENER = '[data-testid="desk-health"], [data-testid="desk-status-line"]';
/** ⌘K's "Today" says the book's open P&L at its last read (the book's own rows carry the live prices). */
const NO_TICKS: DeskTicks = { rows: {}, open: false, checked: 0 };

/** Below 1180 px the copilot is a sheet (CopilotLab.module.css); below 768 px the thread list covers the screen. */
const sheetLayout = () => typeof window !== "undefined" && window.matchMedia("(max-width: 1179px)").matches;
const narrow = () => typeof window !== "undefined" && window.matchMedia("(max-width: 767px)").matches;

/** The dock's tabs under the chart: the selected ticker's tools in the order he works (his position, pick a contract,
 * build the ticket), then his notes and Check a call. ``use`` is the tab's counted piece (lib/deskUse.ts). */
type DockTab = "position" | "chain" | "ticket" | "notes" | "check";
const DOCK_TABS: readonly { id: DockTab; label: string; key?: string; use: string }[] = [
  { id: "position", label: "Position", use: "tab.position" },
  { id: "chain", label: "Chain", key: "O", use: "tab.chain" },
  { id: "ticket", label: "Ticket", key: "T", use: "tab.ticket" },
  { id: "notes", label: "Notes", use: "tab.notes" },
  { id: "check", label: "Check a call", key: "L", use: "tab.check" },
];
/** A place in the centre (the copilot's view cards and ⌘K name these): the chart, a dock tab, or the Grid. */
type CentreTab = "chart" | "chain" | "ticket" | "check" | "grid" | "position" | "notes";
/** The centre's places with a key (``lib/deskPlaces.ts``): the chart (always on top), the dock's Chain, Ticket and Check
 * a call, and the Grid of many tickers, which takes the whole centre until Back to chart. ``key`` is the place's desk key. */
const CENTRE_TABS: readonly { id: CentreTab; label: string; key: string; hint: string }[] = (["chart", "chain", "ticket", "check", "grid"] as const)
  .map(id => { const place = PLACE.get(id)!; return { id, label: place.label, key: place.key!, hint: place.hint }; });
/** The chart's share of the centre's height over the dock, kept for this browser (the splitter between them). */
const SHARE_KEY = "desk.dock.share.v1";
const SHARE = { min: 0.4, max: 0.8, start: 0.62 };
/** A phone runs the chart, then the dock: a Ticket opened there comes into view under the top row, after the view's own
 * scroll (``toView``). Wider, the dock sits under the chart on screen already. */
function showDock() {
  if (!narrow()) return;
  requestAnimationFrame(() => requestAnimationFrame(() => document.querySelector<HTMLElement>('[data-testid="desk-dock"]')?.scrollIntoView({ block: "start" })));
}
/** A phone's views (CopilotLab.module.css): one shows at a time, picked on the desk's own tab bar at the bottom
 * (Positions, Chart, Chain, Orders; Ask opens the copilot's sheet) and the Feed chip in the top row. ``chain`` is the
 * ticker's view on its Chain, under a row of ticker chips; ``orders`` lists Robinhood's working orders and today's fills. */
type DeskView = "book" | "ticker" | "chain" | "orders" | "feed";
const noSubscribe = () => () => {};
/** A phone's view changed: the page goes to where that view starts. */
function toView(view: DeskView) {
  requestAnimationFrame(() => {
    // Positions starts at the page's top (the clock and the value block); the other views start right under the top
    // row, which stays at the top of the screen.
    if (view === "book") window.scrollTo({ top: 0 });
    else document.getElementById("desk-cockpit")?.scrollIntoView({ block: "start" });
  });
}

const shortDay = (iso: string) => new Date(iso).toLocaleDateString("en-US", { timeZone: "America/New_York", month: "short", day: "numeric" });

/** You are here: "Now › a conversation about no ticker", or "NBIS › its conversation · Oct 29". Now goes back to the
 * desk's front door. */
function Breadcrumb({ thread, link, saved, onMain }: { thread: DeskThreadRef | null; link: PanelLink | null; saved: InvestigationSummary[]; onMain(): void }) {
  const symbol = thread ? thread.symbol : link?.symbol || null;
  const at = thread && saved.find(t => t.id === thread.id)?.updated_at;
  const leaf = thread ? thread.title : symbol ? (link?.radar ? "Radar hit" : "Decision") : null;
  return (
    <nav aria-label="You are here" data-testid="desk-breadcrumb" className="z-10 mb-3 flex min-w-0 items-baseline gap-1.5 bg-background py-1 text-xs text-muted-foreground lg:sticky lg:top-0 lg:shadow-[0_-24px_0_0_hsl(var(--background))]">
      {symbol ? <span className="shrink-0 font-semibold text-foreground">{symbol}</span> : (
        <button type="button" onClick={onMain} className="relative shrink-0 font-semibold after:absolute after:-inset-x-2 after:-inset-y-3.5 after:content-[''] hover:text-foreground hover:underline sm:after:hidden">Now</button>
      )}
      {leaf && <><span aria-hidden>›</span><span className="min-w-0 truncate text-foreground" title={leaf}>{leaf}</span></>}
      {at && <span className="shrink-0 tabular-nums">· {shortDay(at)}</span>}
    </nav>
  );
}

/** Typing somewhere: a desk key never fires there. */
function typing(target: EventTarget | null) {
  if (!(target instanceof HTMLElement)) return false;
  return target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName) || target.closest("[role=textbox]") !== null;
}

/**
 * The Copilot desk, a cockpit (docs/copilot-lab.md § The desk): the top bar (one row since the calm pass: the mode
 * switch and the desk's buttons; the market's line and the day's money are ⌘K's "Today" and hovers), the Needs-you strip (the one most urgent item), then three columns: the book of followed positions
 * with the time of day's block under it (the morning brief, Since you looked, or the day report), the centre (the
 * selected symbol's Chart and tools), and the side: the copilot (today's Main chat or the open thread, its decision,
 * close pass or checklist on top) with the Feed of what the app knows today behind its tab. Selecting a position drives
 * the centre and the copilot. Below 1180 px the copilot is a sheet opened by "Ask the copilot" and by any Ask action
 * and the Feed a drawer; a phone shows one view at a time (Positions, Chart, Chain, Orders on its own tab bar; the Feed chip). The thread list is a drawer. While
 * the lab is off only the conversation shows, saying so. ⌘K (Ctrl+K) or Jump to or ask… opens the palette; while not typing,
 * J / K open the next or previous thread, N starts a plan, [ toggles the thread list, a place's key opens it and Escape
 * closes the drawer or the sheet.
 *
 * The page remounts the desk for each deep link it loads; a symbol or context link the desk opens itself (a position
 * picked in the book, a feed item's Ask, Plan a trade) is followed in place (``go``): the address changes with the
 * History API and the copilot starts that conversation, so the book, the top bar, the strip and the centre stay mounted.
 *
 * Where things live (the 2026-11-13 layout pass): what needs him and his positions keep the top and the left; the centre
 * is the selected ticker's tools only (the chart always on top, the dock under it: Position, Chain, Ticket, Notes, Check
 * a call; the Grid over both until Back to chart); the right is the copilot
 * with the Feed behind its tab, so the chart stays while he reads ideas. A phone shows one view at a time, picked on the
 * desk's own tab bar (Positions, Chart, Chain, Orders, Ask) or the Feed chip, and the copilot as its sheet. Every place has a key (C O T L G, F, B, /) and a ⌘K
 * command.
 */
export default function CopilotLab({ link: linkProp = null, close = false, daily: dailyProp = false, feed: feedLink = null, card: cardLink = null }: {
  link?: PanelLink | null; close?: boolean; daily?: boolean;
  /** A Radar or scanner ping's card (?feed=): the desk opens with the Feed forward on it. */
  feed?: FeedLink | null;
  /** A position ping's ?card=: the desk opens on its ticker with the ping card (``PingCard``) first, the copilot's sheet closed. */
  card?: CardLink | null;
}) {
  const on = useCopilotOn();
  const router = useRouter();
  // The desk link on show: the one the page loaded, then each one followed in place. Followed, it is no longer Now.
  const [view, setView] = useState<{ link: PanelLink | null; daily: boolean }>({ link: linkProp, daily: dailyProp });
  const { link, daily } = view;
  const navFolded = useFoldedNav();
  const session = useDeskSession(on);
  // Below 1180 px the copilot is a sheet: a deep link or a saved thread opens on it, Now on the cockpit.
  // A position ping's card comes first: the conversation waits behind Ask.
  const [sheet, setSheet] = useState(!daily && !feedLink && !cardLink);
  const [card, setCard] = useState<CardLink | null>(cardLink);
  const [command, setCommand] = useState<DeskCommand | null>(null);
  const [thread, setThread] = useState<DeskThreadRef | null>(null);
  // Now: today's Main chat (or the desk's bare address while it opens). An earlier day's Main chat is that day's
  // conversation only.
  const today = session.data?.day ?? nyDay();
  const onNow = thread ? !!thread.mainDay && thread.mainDay === today : daily;
  // The book's last read shows at once on a remount (the thread list reads it again behind it).
  const [keptRows, keepRows] = useKept<{ rows: DeskThread[]; live: DeskLive | null }>("desk.rows");
  const [rows, setRows] = useState<DeskThread[]>(() => keptRows?.rows ?? []);
  const [rowsRead, setRowsRead] = useState(!!keptRows);
  const [rowsFresh, setRowsFresh] = useState(false); // read since this mount, not only kept
  const [live, setLive] = useState<DeskLive | null>(() => keptRows?.live ?? null);
  // The account line's tap: the book narrowed to one account (its masked number), until tapped again.
  const [pickedAccount, setAccount] = useState<string | null>(null);
  const account = activeAccount(live, pickedAccount);
  // The line went unavailable (or the account left it): the pick ends, so its return does not narrow the book unasked.
  if (pickedAccount !== null && account === null) setAccount(null);
  // The thread list's armed plans (a level reached today is a strip item) and which of its sources read.
  const [plans, setPlans] = useState<DeskPlan[]>([]);
  const [sections, setSections] = useState<DeskThreads["sections"] | null>(null);
  const [rowsFailed, setRowsFailed] = useState<string | null>(null);
  // When the positions last read (ISO): Replay's live line says "as of" it when a later read fails.
  const [positionsAt, setPositionsAt] = useState<string | null>(null);
  const readRows = useCallback((next: DeskThread[], feed?: DeskLive, read?: { plans: DeskPlan[]; sections: DeskThreads["sections"]; asOf: string }) => {
    setRows(next); setLive(feed ?? null); setRowsRead(true); setRowsFresh(true); keepRows({ rows: next, live: feed ?? null });
    if (read) { setPlans(read.plans); setSections(read.sections); if (read.sections?.positions !== "unavailable") setPositionsAt(read.asOf); }
  }, [keepRows]);
  // The book's Robinhood state is the health read's too (DeskHealth.tsx): the status line and the book say the same.
  // What the book shows: a read whose join with the journal failed ("ok", not joined) shows as unavailable.
  const liveState = rowsFresh && live ? (live.state === "ok" && !liveOn(live) ? "unavailable" : live.state) : null;
  const liveAsOf = rowsFresh ? live?.as_of ?? null : null;
  useEffect(() => {
    reportBookLive(on && liveState ? { state: liveState, as_of: liveAsOf } : null);
    return () => reportBookLive(null);
  }, [on, liveState, liveAsOf]);
  const [saved, setSaved] = useState<InvestigationSummary[]>([]);
  const [palette, setPalette] = useState(false);
  const [topMore, setTopMore] = useState(false); // a phone's top row More (Threads)
  // Replay (DeskReplay): paper trading on a past day. While it runs the live desk stays mounted but hidden, so leaving
  // puts it back exactly as it was; of its live pieces only the REAL line in Replay's header shows beside a replayed price.
  const [replay, setReplay] = useState(false);
  // The desk's mode (DeskMode.tsx): Real or Paper as kept for this browser, Replay whenever a replay is open, however it
  // opened. A view only: nothing is sent and no order or account behaves differently.
  const viewMode = useDeskMode();
  const mode: Mode = replay ? "replay" : viewMode;
  const [threadsShown, setThreadsShown] = useState(false);
  const toggleThreads = useCallback(() => setThreadsShown(shown => !shown), []);
  // The centre: the symbol the owner picked in the book (else the copilot's, else the first followed position), on Chart
  // or the Feed.
  const [picked, setPicked] = useState<string | null>(null);
  const [pickedKey, setPickedKey] = useState<string | null>(null);
  // The centre: the chart always on top, the dock under it (``dockPick``; null: Position when a position is selected,
  // else Chain), or the Grid over both until Back to chart.
  const [grid, setGrid] = useState(false);
  const [dockPick, setDockPick] = useState<DockTab | null>(null);
  // The dock's tab and the Grid survive a link that reopens the desk (a checked call's Plan it) for this browser tab.
  // A ping's card (?feed=) opens on the chart's default dock.
  useEffect(() => {
    if (feedLink) return;
    try {
      const kept = window.sessionStorage.getItem(CENTRE_KEY);
      if (kept === "grid") setGrid(true); // eslint-disable-line react-hooks/set-state-in-effect -- the store is read after hydration
      else if (kept === "check" || kept === "chain" || kept === "notes") setDockPick(kept);
    } catch { /* the chart's default dock */ }
  }, [feedLink]);
  // The splitter between the chart and the dock (from 1024 px): the chart's share of the centre, kept for this browser.
  const [share, setShare] = useState(SHARE.start);
  useEffect(() => { try { const kept = Number(window.localStorage.getItem(SHARE_KEY)); if (kept >= SHARE.min && kept <= SHARE.max) setShare(kept); } catch { /* the default share */ } }, []); // eslint-disable-line react-hooks/set-state-in-effect -- the store is read after hydration
  const keepShare = useCallback((next: number) => {
    const value = Math.round(Math.min(SHARE.max, Math.max(SHARE.min, next)) * 100) / 100;
    setShare(value);
    try { window.localStorage.setItem(SHARE_KEY, String(value)); } catch { /* this visit only */ }
  }, []);
  // Dragging the splitter: the chart's part ends about where the pointer is.
  const dragSplit = useCallback((event: ReactPointerEvent<HTMLElement>) => {
    const centre = document.getElementById("desk-centre");
    if (!centre || event.button !== 0) return;
    event.preventDefault();
    const box = centre.getBoundingClientRect();
    const at = (y: number) => Math.min(SHARE.max, Math.max(SHARE.min, (y - box.top) / box.height));
    const move = (e: PointerEvent) => setShare(at(e.clientY));
    const up = (e: PointerEvent) => {
      window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); window.removeEventListener("pointercancel", up);
      keepShare(at(e.clientY));
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    window.addEventListener("pointercancel", up);
  }, [keepShare]);
  // The Feed sits beside the copilot, never over the chart: from 1180 px it takes the copilot's column while shown (the
  // Copilot | Feed tabs), from 768 px it is a drawer on the right, and a phone shows it as one of its views (the Feed chip).
  const [feedShown, setFeedShown] = useState(!!feedLink);
  const feedKept = useRef(false);
  useEffect(() => { feedKept.current = feedShown; }, [feedShown]);
  // A phone shows one view at a time (its tab bar at the bottom, the Feed chip in its top row). It opens on Positions; a link that names a ticker (a ping's) opens on that ticker's view, under the copilot's sheet.
  // A ping's ?feed= opens on the Feed (its view on a phone; the drawer or the side's Feed tab wider).
  const [phoneView, setPhoneView] = useState<DeskView>(feedLink ? "feed" : linkProp?.symbol || cardLink ? "ticker" : "book");
  // Once, on the link's load: a phone's Feed is its view, not the drawer; wider, the Feed is the drawer or the side's tab
  // and the phone's view goes back to what a link without ?feed= opens on (so "the Feed is open" follows feedShown alone).
  useEffect(() => { if (!feedLink) return; if (narrow()) setFeedShown(false); else setPhoneView(linkProp?.symbol ? "ticker" : "book"); }, []); // eslint-disable-line react-hooks/set-state-in-effect, react-hooks/exhaustive-deps
  // The width crossed 768 px (a phone turned on its side): the Feed on show stays on show in the new layout's way, so
  // "the Feed is open" never means a view or a drawer that is not on screen.
  useEffect(() => {
    const query = window.matchMedia("(max-width: 767px)");
    const flip = () => {
      if (query.matches) { if (feedKept.current) { setFeedShown(false); setPhoneView("feed"); } }
      else setPhoneView(view => { if (view === "feed") setFeedShown(true); return view === "feed" ? "book" : view; });
    };
    query.addEventListener("change", flip);
    return () => query.removeEventListener("change", flip);
  }, []);
  // The copilot comes forward (its sheet below 1180 px, its column beside the Feed's tab above).
  const showCopilot = useCallback(() => { setSheet(true); setFeedShown(false); }, []);
  // The selected ticker's tools come forward: a phone's ticker view; below 1180 px the Feed's drawer gives way.
  const showCentre = useCallback((smooth = true) => {
    if (narrow()) { setPhoneView("ticker"); toView("ticker"); }
    else if (sheetLayout()) { setFeedShown(false); document.getElementById("desk-centre")?.scrollIntoView({ behavior: smooth ? "smooth" : "auto", block: "start" }); }
  }, []);
  const showBook = useCallback(() => { if (narrow()) { setPhoneView("book"); toView("book"); } }, []);
  const showFeed = useCallback(() => {
    if (narrow()) { setPhoneView("feed"); toView("feed"); }
    else { setFeedShown(true); if (sheetLayout()) setSheet(false); }
  }, []);
  // The phone's tab bar: Chart (the ticker's view; a Chain the Chain tab opened goes back to the dock's default), Chain
  // (the same view on its Chain, with the ticker chips over it and the chart out of the way) and Orders.
  const showChart = useCallback(() => {
    setGrid(false); setDockPick(pick => pick === "chain" ? null : pick);
    setPhoneView("ticker"); toView("ticker");
  }, []);
  const showChain = useCallback(() => { setGrid(false); setDockPick("chain"); setPhoneView("chain"); toView("chain"); }, []);
  const showOrders = useCallback(() => { setPhoneView("orders"); toView("orders"); }, []);
  useEffect(() => { try { window.sessionStorage.setItem(CENTRE_KEY, grid ? "grid" : dockPick ?? "chart"); } catch { /* this view only */ } }, [grid, dockPick]);
  // On a phone the dock's tab strip scrolls: keep the chosen tab in it (a link can choose Ticket), never moving the page.
  useEffect(() => {
    const strip = document.querySelector<HTMLElement>('[role="tablist"][aria-label="Centre"]');
    const tab = strip?.querySelector<HTMLElement>('[aria-selected="true"]');
    if (!strip || !tab || strip.scrollWidth <= strip.clientWidth) return;
    const box = strip.getBoundingClientRect(), at = tab.getBoundingClientRect();
    if (at.left < box.left) strip.scrollLeft -= box.left - at.left + 8;
    else if (at.right > box.right) strip.scrollLeft += at.right - box.right + 8;
  }, [dockPick, grid]);
  // The Ticket tab: a saved plan's ticket opens from its card, its thread's header, a book row or the tab's own list
  // (``openTicket``), or from a link (?ticket=) made where the desk was not open.
  const tickets = useTicketPlans(on);
  const paper = usePaperBook(on);
  const [ticketFor, setTicketFor] = useState<string | null>(null);
  const [ticketPick, setTicketPick] = useState<TicketPick | null>(null); // the Chain tab's Put on ticket
  const [ticketClose, setTicketClose] = useState<AnyClosingTicket | null>(null); // a held option's Close at target / stop, or a copilot close card
  const [ticketRoll, setTicketRoll] = useState<RollFrom | null>(null); // a held option's Roll
  const [checkSeed, setCheckSeed] = useState<{ text: string; n: number } | null>(null); // the Chain tab's Check it
  const checkOpen = !grid && dockPick === "check";
  useEffect(() => { if (!checkOpen) setCheckSeed(null); }, [checkOpen]); // eslint-disable-line react-hooks/set-state-in-effect -- the Chain's contract fills Check a call once, not on every later visit
  const ticketLinked = useRef(false); // a ?ticket= link on a phone: the Ticket comes into view once the book above it has read
  useEffect(() => {
    // The Ticket comes up in the dock; the chart above it stays as it is (a phone, one column, scrolls to the Ticket).
    const show = (id: string | null, pick: TicketPick | null = null, close: AnyClosingTicket | null = null, roll: RollFrom | null = null) => { setTicketFor(id); setTicketPick(pick); setTicketClose(close); setTicketRoll(roll); setGrid(false); setDockPick("ticket"); showCentre(); showDock(); };
    const onTicket = (event: Event) => {
      event.preventDefault();
      const detail = (event as CustomEvent<{ investigationId?: string; pick?: TicketPick; close?: AnyClosingTicket; roll?: RollFrom }>).detail;
      if (detail.roll) show(null, null, null, detail.roll);
      else if (detail.close) show(null, null, detail.close);
      else if (detail.investigationId) show(detail.investigationId, detail.pick ?? null);
    };
    const linked = new URLSearchParams(window.location.search).get("ticket");
    if (linked) { show(linked); ticketLinked.current = true; }
    window.addEventListener(TICKET_EVENT, onTicket);
    return () => window.removeEventListener(TICKET_EVENT, onTicket);
  }, [showCentre]);
  const feed = useDeskFeed(on);
  const feedOpen = feedShown || phoneView === "feed";
  const feedNew = useFeedNew(feed.data, on && feedOpen);
  const [scanLines, setScanLines] = useState<{ symbol: string; lines: DeskGuide[] } | null>(null); // a Scanner row's levels on the chart
  const [chainFocus, setChainFocus] = useState<{ pick: ChainPick; n: number } | null>(null); // a Feed row's unusual contract
  const chainOpen = !grid && dockPick === "chain";
  // Unusual activity and the scanner are read only for the Feed (and the Chain's unusual marks): not on load, only from the
  // first time either opens, then on the shared minute as before.
  const [feedRead, setFeedRead] = useState(false);
  if (!feedRead && (feedOpen || chainOpen)) setFeedRead(true);
  const unusual = useDeskUnusual(on && feedRead);
  const scanner = useDeskScanner(on && feedRead);
  // The phone's Chain view is the ticker's view on its Chain: anything that moves the dock off it (a contract's Put on
  // ticket, a key, ⌘K) leaves it for the ticker's own view, so the chart comes back with the tab it opened.
  useEffect(() => { if (phoneView === "chain" && !chainOpen) setPhoneView("ticker"); }, [phoneView, chainOpen]); // eslint-disable-line react-hooks/set-state-in-effect -- follows the dock
  useEffect(() => { if (!chainOpen) setChainFocus(null); }, [chainOpen]); // eslint-disable-line react-hooks/set-state-in-effect -- the pick opens the Chain once, not on every later visit
  // The tickers opened today in this browser: opening one clears its strip items (``deskNeeds``); nothing is dismissed.
  const [opened, setOpened] = useState<Record<string, number>>({});
  useEffect(() => { setOpened(readOpened(nyDay())); }, []); // eslint-disable-line react-hooks/set-state-in-effect -- the store is read after hydration
  const jumpKey = useJumpKey();
  const tabSlot = useDeskTabSlot(); // the phone tab bar's slot while it is the desk's (Nav.tsx)
  const phone = usePhone();
  const hydrated = useSyncExternalStore(noSubscribe, () => true, () => false); // the first render cannot know it is a phone
  // A phone draws the chart (and loads its library and first read) only once its ticker or Chain view is shown; after
  // that it stays, so going back to it is instant.
  const [chartShown, setChartShown] = useState(false);
  const chartNow = hydrated && (!phone || phoneView === "ticker" || phoneView === "chain");
  useEffect(() => { if (chartNow) setChartShown(true); }, [chartNow]); // eslint-disable-line react-hooks/set-state-in-effect -- latches once
  // How he uses the desk: quiet counts, and the pieces he folded away on this device size (DeskUse.tsx).
  const use = useDeskUse(on);
  // The account line folded away: a narrowed book would hide the other accounts with nothing on screen saying so.
  // A phone lists the accounts in its value block whatever the fold, so there the pick stands.
  if (pickedAccount !== null && use.hidden("accounts") && !narrow()) setAccount(null);
  useCountOpen("side.feed", on && feedOpen);
  useCountOpen("threads", on && threadsShown);
  useCountOpen("palette", on && palette);
  const desk = useRef<HTMLDivElement>(null);
  const [deciding, setDeciding] = useState(false);
  const sent = useRef(0);
  const [answering, setAnswering] = useState(false); // the close pass's fills to link, in the conversation pane
  const [arming, setArming] = useState(false); // Arm today's plans' checklist, in the conversation pane
  const [dayList, setDayList] = useState(false); // the Day button's checklist, in the conversation pane
  // The open thread is in the address (below). Now in place marks ``toNow``: the Main chat it opens replaces the bare
  // address, as a fresh load's does.
  const addressed = useRef<string | null>(null);
  const toNow = useRef(false);
  // A desk link followed in place: the address changes (a step Back undoes; the same address again replaces itself), the
  // copilot starts its conversation as a fresh load of it would. Anything else (a Radar hit, an investigation, another
  // page) is a navigation.
  const followLink = useCallback((next: PanelLink) => {
    setView({ link: next, daily: false });
    setCommand({ kind: "link", link: next, n: ++sent.current });
    showCopilot();
    setArming(false);
    setAnswering(false);
    setDayList(false);
  }, [showCopilot]);
  // Now (the top bar's, the breadcrumb's, Back to the bare address): today's Main chat in place, its address replacing
  // the bare one as a fresh load's does.
  const onNowShown = useRef(onNow);
  useEffect(() => { onNowShown.current = onNow; }, [onNow]);
  const goNow = useCallback((push: boolean) => {
    if (onNowShown.current) return; // already on today's Main chat
    if (push && window.location.search) window.history.pushState(null, "", "/copilot-lab");
    toNow.current = true;
    setView({ link: null, daily: true });
    setCommand({ kind: "now", n: ++sent.current });
    setSheet(false);
    setFeedShown(false); // beside the Feed, Now brings the copilot's column forward
    setArming(false);
    setAnswering(false);
    setDayList(false);
  }, []);
  const actions = useMemo<HomeActions>(() => ({
    open: id => { setCommand({ kind: "open", id, n: ++sent.current }); showCopilot(); if (narrow()) setThreadsShown(false); },
    ask: text => { setCommand({ kind: "ask", text, n: ++sent.current }); showCopilot(); },
    // Back to Now from any thread or deep link, without carrying its conversation into the new view.
    home: () => goNow(true),
  }), [goNow, showCopilot]);
  const fill = useCallback((text: string) => { setCommand({ kind: "fill", text, n: ++sent.current }); showCopilot(); }, [showCopilot]);
  // ⌘K's "Ask the copilot": the words sent now in the open conversation, as its message box would send them.
  const askHere = useCallback((text: string) => { setCommand({ kind: "ask", text, here: true, n: ++sent.current }); showCopilot(); }, [showCopilot]);
  const go = useCallback((href: string) => {
    const next = deskLinkIn(href);
    if (!next) { router.push(href); return; }
    const to = new URL(href, window.location.origin);
    const same = to.pathname === window.location.pathname && to.search === window.location.search;
    window.history[same ? "replaceState" : "pushState"](null, "", `${to.pathname}${to.search}`);
    followLink(next);
  }, [router, followLink]);
  // Anything else that changes the address to such a link (a link inside the copilot, Next's own Back) is followed too,
  // and so is the bare address (the nav's Desk) while the desk shows something other than Now.
  const params = useSearchParams();
  // "Redo in replay" on a real closed trade (``redoHref``): Replay opens on that trade. The address drops the link once
  // it is read, so a reload or Back never starts a second redo.
  const [redo, setRedo] = useState<string | null>(null);
  useEffect(() => {
    const id = params.get("redo");
    if (!id) return;
    setRedo(id); setReplay(true);
    const rest = new URLSearchParams(params.toString());
    rest.delete("redo");
    window.history.replaceState(null, "", `/copilot-lab${rest.size ? `?${rest}` : ""}`);
  }, [params]);
  // More → How I use the desk (``/copilot-lab?desk=use``): the view opens once and the address drops the word.
  const openUse = use.openView;
  const useReady = use.enabled;
  useEffect(() => {
    // Waits for the desk to be on (its status reads first), keeping the word in the address until then.
    if (!useReady || params.get("desk") !== "use") return;
    openUse();
    const rest = new URLSearchParams(params.toString());
    rest.delete("desk");
    window.history.replaceState(null, "", `/copilot-lab${rest.size ? `?${rest}` : ""}`);
  }, [params, openUse, useReady]);
  const shownLink = useRef(link);
  useEffect(() => { shownLink.current = link; }, [link]);
  useEffect(() => {
    const next = deskLinkIn(`/copilot-lab?${params.toString()}`);
    if (next && JSON.stringify(next) !== JSON.stringify(shownLink.current)) followLink(next); // the address moved
    else if (!params.size && !toNow.current) goNow(false);
  }, [params, followLink, goNow]);
  // Plan a trade (N, ⌘K and the Ticket's empty state): a new conversation with "Plan a trade: " in the box, unsent. Off
  // the bar since the calm pass, so its use is counted here (the "plan" piece) rather than by a tap on a bar button.
  const planTrade = useCallback(() => { countTap("plan"); go(PLAN_HREF); }, [go]);
  const [refresh, setRefresh] = useState(0);
  // The copilot's desk action cards: a view card moves the centre (Undo puts it back); a tap that changed a list reads again.
  // A card names the chart, a dock tab or the Grid. "Chart" (and an Undo back to it) closes the Grid and puts a Chain,
  // Ticket or Check a call the card opened back to the dock's default; his own Position or Notes stays.
  const placeCentre = useCallback((tab: CentreTab) => {
    if (tab === "grid") { setGrid(true); return; }
    setGrid(false);
    setDockPick(was => tab !== "chart" ? tab : was === "position" || was === "notes" ? was : null);
  }, []);
  const viewTab = grid ? "grid" : dockPick === "chain" || dockPick === "ticket" || dockPick === "check" ? dockPick : "chart";
  // A show card's place moves the desk the way ⌘K does (``moveTo``, below), and hands back its Undo.
  const moveRef = useRef<(place: DeskPlaceId, symbol?: string | null) => () => void>(() => () => undefined);
  const moveCard = useCallback((place: DeskPlaceId, symbol?: string | null) => moveRef.current(place, symbol), []);
  useDeskActionHost({ picked, tab: viewTab, rows, go, setPicked, setPickedKey, setTab: placeCentre, setRefresh, setSheet, showCentre, moveTo: moveCard });
  // Mark plan done in the thread menu: only for a plan row (armed and not entered, or exited), never a held position's.
  const [planSymbol, setPlanSymbol] = useState<string | null>(null);
  // A decision or an alert still asking today: a conversation opens on it, at the top of the thread.
  const asking = deciding || !!session.data?.to_answer?.alerts?.rows.some(a => a.today && !a.feedback && a.symbol === thread?.symbol);
  const [turnText, setTurnText] = useState<string | null>(null);
  // Now opens at its top, above the day's conversation, as a thread asking something does.
  const hooks = useMemo<DeskHooks>(() => ({ command, onThread: setThread, holdTop: asking || onNow, onAnswer: setTurnText,
    planDone: planSymbol ? { symbol: planSymbol, done: () => setRefresh(n => n + 1) } : null }), [command, planSymbol, asking, onNow]);

  // The open thread is in the address, so Back and a reload come back to it: opening another adds a step, and the thread
  // the desk reopened by itself takes the bare address's place. Only the address changes, so the lab stays mounted.
  const reopened = useRef<string | null>(null);
  useEffect(() => { reopened.current = rememberedThread(); }, []);
  const threadId = thread?.id ?? null;
  const threadMain = !!thread?.mainDay;
  useEffect(() => {
    if (threadId === addressed.current) return;
    // Only the Main chat Now opened (or the thread the desk reopened) takes the bare address's place; a thread the owner
    // opens from Now adds a step, so Back returns to Now even before (or without) today's Main chat.
    const quiet = (toNow.current && threadMain) || (!addressed.current && ((daily && threadMain) || threadId === reopened.current));
    toNow.current = false;
    addressed.current = threadId;
    reopened.current = null;
    // A desk link followed in place already has its address.
    if (threadId === threadInUrl() || (!threadId && (!window.location.search || deskLinkIn(`${window.location.pathname}${window.location.search}`)))) return;
    window.history[quiet ? "replaceState" : "pushState"](null, "", threadId ? `/copilot-lab?thread=${threadId}` : "/copilot-lab?view=new");
  }, [threadId, threadMain, daily]);
  useEffect(() => {
    const back = () => {
      const id = threadInUrl();
      const next = deskLinkIn(`${window.location.pathname}${window.location.search}`);
      if (id) actions.open(id);
      else if (next) followLink(next); // a desk link: its conversation starts again in place
      else if (!window.location.search) goNow(false);
      else window.location.reload(); // another deep link: its question comes back with it
    };
    window.addEventListener("popstate", back);
    return () => window.removeEventListener("popstate", back);
  }, [actions, followLink, goNow]);

  // A row opens the way the thread list opens it: an investigation in place, anything else by its link.
  const pick = useCallback((row: DeskThread) => {
    if (narrow()) setThreadsShown(false); // over the whole screen it gives way; beside the copilot it stays
    if (row.investigationId) actions.open(row.investigationId);
    else if (row.path) go(row.path);
  }, [actions, go]);

  // A row in the book opens the way the thread list's ticker does: its own conversation, else the symbol's newest open one,
  // else its link; a position whose link leaves the desk (its trade page) opens the symbol's desk view instead.
  const openRow = useCallback((row: DeskThread) => {
    const talk = saved.filter(t => t.symbol && t.symbol === row.symbol && t.status !== "closed").sort((a, b) => b.updated_at.localeCompare(a.updated_at))[0];
    if (row.investigationId) actions.open(row.investigationId);
    else if (talk) actions.open(talk.id);
    else if (row.path?.startsWith("/copilot-lab") || !row.symbol) pick(row);
    else go(`/copilot-lab?${new URLSearchParams({ symbol: row.symbol })}`);
  }, [actions, pick, go, saved]);

  // Fills waiting for their plan: one bar at the top of the symbol's thread, and "N fills to link" opening each in turn.
  const fills = useFillLinks(rows, pick, () => setRefresh(n => n + 1));

  // The day's phase command: Prep the day before the open on a weekday, Close the day after 16:00 (New York clock).
  const [dayPhase, setDayPhase] = useState<"pre" | "close" | null>(null);
  useEffect(() => {
    const read = () => {
      const now = new Date();
      const parts = Object.fromEntries(new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", weekday: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23" })
        .formatToParts(now).map(p => [p.type, p.value]));
      const minute = Number(parts.hour) * 60 + Number(parts.minute);
      const weekday = !["Sat", "Sun"].includes(parts.weekday);
      setDayPhase(afterClose(now.toISOString()) ? "close" : weekday && minute >= 4 * 60 && minute < 9 * 60 + 30 ? "pre" : null);
    };
    read();
    const timer = setInterval(read, 60_000);
    return () => clearInterval(timer);
  }, []);

  // Close the day: a pass through each thread still asking its close question (``toReview``, list order). Each opens on its
  // question; an answer or Skip opens the next. Then, in the conversation pane, the fills waiting to link
  // (``closeSteps``), one at a time; the last one ends the pass. With none left it puts the day's question in the box,
  // unsent. Alert and Radar ratings are never asked here. Nothing goes to the model.
  const reviewed = useRef(new Set<string>()); // answered or skipped this visit, before the list reads it back
  const closing = useRef(false);
  useEffect(() => {
    try { closing.current = window.sessionStorage.getItem(CLOSING_KEY) === nyDay(); } catch { /* no pass to resume */ }
  }, []);
  const setClosing = useCallback((on: boolean) => {
    closing.current = on;
    try { if (on) window.sessionStorage.setItem(CLOSING_KEY, nyDay()); else window.sessionStorage.removeItem(CLOSING_KEY); } catch { /* this page only */ }
  }, []);
  const review = useCallback((row: DeskThread) => {
    if (row.investigationId) actions.open(row.investigationId);
    else go(`/copilot-lab?${new URLSearchParams({ symbol: row.symbol! })}`); // opens on the symbol's question
  }, [actions, go]);
  const [passed, setPassed] = useState<ReadonlySet<string>>(() => new Set()); // answered or skipped this visit
  const steps = dayPhase === "close" ? closeSteps(fills.waiting, passed) : [];
  const pass = useCallback((id: string) => setPassed(prev => new Set(prev).add(id)), []);
  // "N of M done": every followed thread asked today (one per symbol) and, after 16:00, the fills to link. A skip is not done.
  const asked = new Map(rows.filter(r => r.close && r.symbol && !r.hidden).map(r => [r.symbol, !!r.close!.reviewed]));
  const fillsHere = dayPhase === "close" ? fills.answeredHere : 0;
  const tally = {
    done: [...asked.values()].filter(Boolean).length + fillsHere,
    total: asked.size + (dayPhase === "close" ? fills.waiting.length : 0) + fillsHere,
  };
  const closeDay = useCallback(() => {
    const [next] = toReview(rows, nyDay(), reviewed.current);
    setClosing(!!next);
    if (next) review(next);
    else if (steps.length) { setAnswering(true); showCopilot(); }
    else fill(CLOSE_PROMPT);
  }, [rows, review, fill, setClosing, steps.length, showCopilot]);
  // ``?close=1`` (the evening review ping) starts the pass once the list and the session have read, after the close: the
  // first unreviewed thread by a page load of its link (the pass carries on in this tab), else the fills to link here. With nothing left, or read before the close (a tab kept open stays as it is), the desk just opens.
  const closeLink = useRef(close);
  const sessionRead = !!(session.data || session.error);
  useEffect(() => {
    if (!ticketLinked.current || !rowsFresh || !sessionRead) return;
    ticketLinked.current = false;
    showCentre(false);
    showDock();
  }, [rowsFresh, sessionRead, showCentre]);
  useEffect(() => {
    if (!closeLink.current || !rows.length || !sessionRead) return;
    closeLink.current = false;
    if (dayPhase !== "close") return;
    const [next] = toReview(rows, nyDay());
    if (next) {
      setClosing(true);
      window.location.replace(next.investigationId ? `/copilot-lab?investigation=${next.investigationId}`
        : `/copilot-lab?${new URLSearchParams({ symbol: next.symbol! })}`);
    } else if (steps.length) { setAnswering(true); showCopilot(); } // eslint-disable-line react-hooks/set-state-in-effect -- the link starts the pass once
  }, [rows, sessionRead, dayPhase, setClosing, steps.length, showCopilot]);
  const onReviewed = useCallback((symbol: string) => {
    reviewed.current.add(symbol);
    setRefresh(n => n + 1);
    if (!closing.current) return;
    const [next] = toReview(rows, nyDay(), reviewed.current);
    setClosing(!!next);
    if (next) review(next);
    else if (steps.length) setAnswering(true);
  }, [rows, review, setClosing, steps.length]);
  const closeStep = answering ? steps[0] : undefined;
  useEffect(() => { if (answering && !steps.length) setAnswering(false); }, [answering, steps.length]); // eslint-disable-line react-hooks/set-state-in-effect -- the last answer ends the pass

  // The desk bar's phase action: before the open on a weekday, Arm today's plans (a checklist of the armed plans in the
  // conversation pane; nothing is armed, sized or sent from it); after 16:00, Close the day.
  // Opening another thread leaves the checklist or the pass; Main chat arriving under Now (a first open, from no thread)
  // does not, so ?close=1's pass or an early Arm survives a Main chat that loads after it started.
  const lastThread = useRef<string | null>(null);
  useEffect(() => {
    const was = lastThread.current;
    lastThread.current = thread?.id ?? null;
    if (was !== null) { setArming(false); setAnswering(false); setDayList(false); }
  }, [thread?.id]);
  // The Day button (the top bar's, ⌘K's, D): Start the day before the open and through the session, Close the day after
  // 16:00, one checklist in the conversation pane. Opening it reads nothing new and sends nothing (DayChecklist.tsx). It
  // is amber only while something is still to do: before the open until its list was opened today, after the close while
  // any close question or fill waits.
  const dayKind = dayPhase === "close" ? "close" : "start";
  const dayLeft = Math.max(0, tally.total - tally.done);
  const [started, setStarted] = useState<string | null>(null);
  useEffect(() => { try { setStarted(window.localStorage.getItem(STARTED_KEY)); } catch { /* amber until opened */ } }, []); // eslint-disable-line react-hooks/set-state-in-effect -- the store is read after hydration
  const dayToDo = dayPhase === "pre" ? started !== nyDay() : dayPhase === "close" ? dayLeft > 0 : false;
  const copilotShown = !arming && !answering && !feedShown && (sheet || !sheetLayout());
  const toggleDay = useCallback(() => {
    if (dayList && copilotShown) { setDayList(false); return; }
    setDayList(true); setArming(false); setAnswering(false); showCopilot();
    if (dayPhase === "pre") { const day = nyDay(); setStarted(day); try { window.localStorage.setItem(STARTED_KEY, day); } catch { /* this visit only */ } }
  }, [dayList, copilotShown, dayPhase, showCopilot]);
  const dayShown = dayList && copilotShown; // on screen: not under Arm or the close pass, a closed sheet or the Feed
  useCountOpen("day", on && dayShown);
  // Your day: the day read sits at the top of Now; the checklist gives way to it.
  const openDayRead = useCallback(() => {
    setDayList(false);
    goNow(true);
    showCopilot();
    requestAnimationFrame(() => requestAnimationFrame(() => desk.current?.querySelector('[data-testid="day-read"]')?.scrollIntoView({ block: "nearest" })));
  }, [goNow, showCopilot]);
  // A centre tab by its key or the palette: the tab, and on a phone the ticker's view with it.
  const showNow = use.showNow;
  // C (the chart) leaves the dock as it is and closes the Grid; a dock tab opens under the chart; G opens the Grid.
  const openCentre = useCallback((tab: CentreTab) => {
    showNow(`tab.${tab}`);
    if (tab === "grid") setGrid(true);
    else { setGrid(false); if (tab !== "chart") setDockPick(tab); }
    showCentre();
  }, [showCentre, showNow]);
  // The copilot's message box: the copilot comes forward, then the box takes the keys.
  const focusCopilot = useCallback(() => {
    showCopilot();
    requestAnimationFrame(() => desk.current?.querySelector<HTMLTextAreaElement>("textarea[aria-label='Message']")?.focus());
  }, [showCopilot]);
  // The book: a phone's Book view, and the keys on its first row (Tab and Enter from there).
  const focusBook = useCallback(() => {
    showBook();
    requestAnimationFrame(() => desk.current?.querySelector<HTMLElement>("[data-desk-book] li button")?.focus());
  }, [showBook]);
  // Folded pieces other than the centre's tabs (those have their own commands, which show a folded tab for now).
  const foldedPieces = useMemo(() => [...PIECE.keys()].filter(id => !id.startsWith("tab.") && use.folded(id)), [use]);
  // A place on the book side (or the top bar), from the palette or its key: the phone's Book view comes forward, a piece he
  // folded away shows for now, and the place scrolls into view, opened (``click``) when it is a fold or an editor. A
  // place inside a line under the book (``place``: a Practice line, My rules) opens that line first.
  const reveal = useCallback((pieces: string[], where: string | string[], click = false, place?: DeskPlace) => {
    for (const piece of pieces) showNow(piece);
    if (place) openDeskPlace(place);
    showBook();
    requestAnimationFrame(() => requestAnimationFrame(() => {
      const target = (Array.isArray(where) ? where : [`[data-testid="${where}"]`]).map(q => desk.current?.querySelector<HTMLElement>(q)).find(Boolean);
      if (!target) return;
      target.scrollIntoView({ block: "nearest" });
      if (click && target.getAttribute("aria-expanded") !== "true") target.click();
      else target.focus({ preventScroll: true });
    }));
  }, [showNow, showBook]);
  // Replay a past day; Redo opens the same screen on its "Redo my worst" list.
  const openReplay = useCallback((redoList = false) => {
    setReplay(true);
    if (redoList) setTimeout(() => document.querySelector<HTMLElement>('[data-testid="redo-worst"]')?.scrollIntoView({ block: "center" }), 600);
  }, []);
  // The mode switch: Replay opens Replay (as R does); Real or Paper is kept for this browser. Replay's own switch leaves
  // through its Back to live (``DeskReplay``), which sells what is open at the replay clock first.
  const pickMode = useCallback((next: Mode) => { if (next === "replay") openReplay(); else setDeskMode(next); }, [openReplay]);
  // Every place on the desk (``lib/deskPlaces.ts``, the one list) and how its palette command opens it: the ticker's tools,
  // the Feed, the copilot's message box, the thread list, Now, and the book side's places, each of which also has a button
  // where it lives. One per place, or this does not compile.
  const placeRun = useMemo<Record<DeskPlaceId, () => void>>(() => ({
    chart: () => openCentre("chart"), chain: () => openCentre("chain"), ticket: () => openCentre("ticket"), check: () => openCentre("check"),
    position: () => openCentre("position"), notes: () => openCentre("notes"),
    grid: () => openCentre("grid"),
    feed: showFeed, copilot: focusCopilot, book: focusBook, threads: toggleThreads,
    now: () => { goNow(true); showCopilot(); },
    paper: () => reveal(["paper"], "desk-paper", false, "paper"),
    rules: () => reveal([], "rules-toggle", true, "rules"),
    goals: () => reveal([], "goals-set", true, "rules"),
    watchlist: () => reveal(["watching"], "desk-watching"),
    note: () => reveal([], ['[data-desk-book] li[data-selected] [data-testid="desk-note-button"]', '[data-desk-book] [data-testid="desk-note-button"]'], true),
    // The top bar's dot while a money source is behind (and on a phone), else the status line: both open the same list.
    health: () => desk.current?.querySelector<HTMLElement>(HEALTH_OPENER)?.click(),
    replay: () => openReplay(), redo: () => openReplay(true), day: toggleDay,
  }), [openCentre, showFeed, focusCopilot, focusBook, toggleThreads, goNow, showCopilot, reveal, openReplay, toggleDay]);
  // The desk as a move found it, for the move's Undo: the views a place changes, and which lines and editors were open.
  const shownNow = useRef({ grid, dockPick, feedShown, phoneView, threadsShown, dayList, replay, sheet });
  useEffect(() => { shownNow.current = { grid, dockPick, feedShown, phoneView, threadsShown, dayList, replay, sheet }; });
  // A move to a place from the copilot's show card or ⌘K's "Go to" (with the ticker it names): as its palette command,
  // except that a place which toggles (the thread list, the Day checklist, Data health) only opens. It only moves the desk:
  // an editor opens, nothing is saved, armed or sent. Returns its Undo: the views back as they were, and every line or
  // editor it opened closed again.
  const moveTo = useCallback((place: DeskPlaceId, symbol: string | null = null): (() => void) => {
    const was = shownNow.current;
    const open = new Set(Array.from(desk.current?.querySelectorAll('[aria-expanded="true"]') ?? []));
    if (symbol) { setPicked(symbol); setPickedKey(null); }
    if (place === "threads") setThreadsShown(true);
    // A note on a named ticker: that ticker's own book row only, never another position's line.
    else if (place === "note" && symbol) reveal([], ['[data-desk-book] li[data-selected] [data-testid="desk-note-button"]'], true);
    else if (place === "day") { if (!dayShown) toggleDay(); }
    else if (place === "health") { if (desk.current?.querySelector(HEALTH_OPENER)?.getAttribute("aria-expanded") !== "true") placeRun.health(); }
    else placeRun[place]();
    return () => {
      const opened = Array.from(desk.current?.querySelectorAll<HTMLElement>('[aria-expanded="true"][data-testid]') ?? []).filter(el => !open.has(el));
      for (const el of opened.reverse()) el.click(); // the editor inside a line first, then the line
      setGrid(was.grid); setDockPick(was.dockPick); setFeedShown(was.feedShown); setPhoneView(was.phoneView); setThreadsShown(was.threadsShown);
      setDayList(was.dayList); setReplay(was.replay); setSheet(was.sheet);
    };
  }, [placeRun, dayShown, toggleDay, reveal]);
  useEffect(() => { moveRef.current = moveTo; }, [moveTo]);
  const marketLine = marketWords(session.data);
  const moneyLine = dayMoneyWords(rows, NO_TICKS, session.data?.realized_today, rowsFresh);
  const todayWords = useMemo(() => ({ market: marketLine, money: moneyLine }), [marketLine, moneyLine]);
  const commands = useMemo<PaletteCommand[]>(() => [
    { id: "plan", name: "Plan a trade", hint: "A new plan; you name the symbol. Nothing is sent.", key: "N", run: planTrade },
    { id: "week", name: "Review my week", hint: "Asks the copilot now: planned vs unplanned, follow-through, exits", run: () => actions.ask(WEEK_REVIEW_CONTEXT) },
    { id: "matters", name: "What matters right now?", hint: "Asks the copilot now, across your positions, watches and investigations", run: () => actions.ask(WHAT_MATTERS_PROMPT) },
    ...(dayPhase === "pre" ? [
      { id: "arm", name: "Arm today's plans", hint: "Each armed plan: still good, change or drop. Nothing is sent.", run: () => { setArming(true); showCopilot(); } },
      { id: "prep", name: "Prep the day", hint: "Puts a prep question in the box, unsent", run: () => fill(PREP_PROMPT) }] : []),
    ...(dayPhase === "close" ? [{ id: "close", name: "Close the day", hint: "Each close question and fill to link, one at a time. Nothing is sent.", run: closeDay }] : []),
    // The Day button's checklist: its name follows the clock (``closeDay`` keeps the name "Close the day").
    { id: "day", name: dayPhase === "pre" ? "Start the day" : dayPhase === "close" ? "Close-of-day checklist" : PLACE.get("day")!.label, key: PLACE.get("day")!.key,
      hint: dayKind === "start" ? "Brief, plans to arm, goals, prep question. Nothing is sent." : "Your day, to review, paper next to real, rules, goals, tomorrow. Nothing is sent.", run: placeRun.day },
    // Every other place on the desk, each with its key where it has one.
    ...DESK_PLACES.filter(p => p.id !== "day").map(p => ({ id: `go-${p.id}`, name: p.label, hint: p.hint, key: p.key, run: placeRun[p.id] })),
    // The mode switch's Real and Paper (its Replay is the Replay place above). Nothing is sent.
    { id: "mode-paper", name: "Paper mode", hint: "Paper first: tickets lead with Fill on paper, the paper value beside the real. Nothing is sent.", run: () => pickMode("paper") },
    { id: "mode-real", name: "Real mode", hint: "The desk as your real accounts show it", run: () => pickMode("real") },
    { id: "whats-working", name: "What's working", hint: "Where your money comes from and where it leaks, real beside paper", run: () => reveal(["scorecard"], "whats-working-toggle", true) },
    { id: "desk-use", name: "How I use the desk", hint: "What you use most and least; fold away what you don't", run: openUse },
    // The old pages' pieces the desk has no home for yet (the pages themselves now open the desk).
    { id: "sync", name: "Data sync", hint: "Run a sync or one job, job history, Gmail. Rebuild and Resync All ask first.", run: openSyncCenter },
    { id: "journal", name: "Journal summary", hint: "Today's, this week's and all-time P&L, performance and the latest trades", run: openJournal },
    { id: "scanner-history", name: "Scanner history", hint: "Past days, scorecards, shadow decisions and the scanner's tickers", run: () => openScannerHistory() },
    { id: "radar-log", name: "Radar log", hint: "Every Radar event with its evidence, Outside your list and the Shadow book", run: () => openRadarLog() },
    { id: "daily-practice", name: "Daily practice", hint: "Prepare morning setups and save choices in Practice", run: () => reveal([], "practice-line-daily", false, "daily") },
    { id: "saved-decisions", name: "Saved decisions", hint: "Frozen choices, evidence and practice paper timelines", run: () => reveal([], "practice-line-saved-decisions", false, "saved-decisions") },
    { id: "scalp-shortlist", name: "9:40 scalp shortlist", hint: "20-session opening paper study, history and rules", run: () => reveal([], "practice-line-scalp", false, "scalp") },
    { id: "decision-replay", name: "Decision replay lab", hint: "Revisit two frozen moments from a synthetic options trade", run: () => reveal([], "practice-line-decision-replay", false, "decision-replay") },
    // The market's line and the day's money, off the top bar since the calm pass: one fact command (it moves
    // nothing), after the ones that act, so a typed word such as "close" still leads with Close the day.
    ...(todayWords.market || todayWords.money ? [{ id: "today", name: `Today${todayWords.market ? `: ${todayWords.market}` : ""}`,
      hint: todayWords.money ?? "SPY, QQQ and VIX today", run: () => undefined }] : []),
    // A piece he folded away is still one command away: it shows for now, where it lives.
    ...foldedPieces.map(id => ({ id: `fold-${id}`, name: PIECE.get(id)!.label, hint: "Folded · shows it for now", run: () => {
      showNow(id);
      const area = PIECE.get(id)!.area;
      if (area === "Left") showBook(); else if (area === "Centre") { setGrid(false); showCentre(); } else if (area === "Right") showFeed();
      requestAnimationFrame(() => document.querySelector(`[data-use="${id}"]`)?.scrollIntoView({ block: "nearest" }));
    } })),
  ], [actions, dayPhase, dayKind, placeRun, fill, planTrade, closeDay, showFeed, showCopilot, openUse, foldedPieces, showNow, showBook, showCentre, pickMode, todayWords, go, reveal]);

  // J / K walk the conversations the thread list shows, subthreads included, in its order.
  const [walk, setWalk] = useState<string[]>([]);
  const step = useCallback((by: 1 | -1) => {
    if (!walk.length) return;
    const at = walk.indexOf(thread?.id ?? "");
    const next = at < 0 ? (by > 0 ? 0 : walk.length - 1) : (at + by + walk.length) % walk.length;
    actions.open(walk[next]);
  }, [walk, thread?.id, actions]);

  useEffect(() => {
    if (!on || replay) return;  // the desk's keys act on the live desk, hidden while a replay runs
    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.isComposing || typing(event.target)) return;
      // The open dialog itself, not state: Escape closes it before React re-renders this listener.
      if (desk.current?.querySelector("dialog[open]")) return;
      const key = event.key.toLowerCase();
      // ⌘K or Ctrl+K on any platform: outside a field neither does anything in the browser.
      if (key === "k" && (event.metaKey || event.ctrlKey) && !event.altKey && !event.shiftKey) {
        event.preventDefault();
        setPalette(true);
        return;
      }
      // The Research sheet covers the desk: its keys are the sheet's, not the desk's.
      if (document.querySelector('[data-testid="desk-research"]')) return;
      if (event.metaKey || event.ctrlKey || event.altKey || event.shiftKey) return;
      if (key === "j" || key === "k") { event.preventDefault(); countTap("keys"); step(key === "j" ? 1 : -1); }
      else if (event.key === "[") { event.preventDefault(); countTap("keys"); toggleThreads(); }
      else if (key === "n" && !event.repeat) {
        // A new plan leaves this conversation: never over words not yet sent.
        const box = desk.current?.querySelector<HTMLTextAreaElement>("textarea[aria-label='Message']");
        if (box?.value.trim()) return;
        event.preventDefault();
        countTap("keys");
        planTrade();
      }
      // Escape closes the thread list's drawer, else the Feed's drawer (below 1180 px), else the copilot's sheet.
      else if (event.key === "Escape") {
        setThreadsShown(shown => {
          if (!shown) { if (feedKept.current && sheetLayout()) setFeedShown(false); else setSheet(false); }
          return false;
        });
      }
      // A place by its key: C chart, O chain (options), T ticket, L check a call, G grid, F feed, B book, / the message box.
      else if (!event.repeat) {
        const tab = CENTRE_TABS.find(t => t.key.toLowerCase() === key);
        if (tab) { event.preventDefault(); countTap("keys"); openCentre(tab.id); }
        else if (key === "f") { event.preventDefault(); countTap("keys"); if (feedKept.current) showCopilot(); else showFeed(); }
        else if (key === "b") { event.preventDefault(); countTap("keys"); focusBook(); }
        else if (key === "p") { event.preventDefault(); countTap("keys"); reveal(["paper"], "desk-paper", false, "paper"); }
        else if (key === "w") { event.preventDefault(); countTap("keys"); reveal(["watching"], "desk-watching"); }
        else if (key === "r") { event.preventDefault(); countTap("keys"); openReplay(); }
        else if (key === "d") { event.preventDefault(); countTap("keys"); toggleDay(); }
        else if (event.key === "/") { event.preventDefault(); countTap("keys"); focusCopilot(); }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [on, replay, step, planTrade, toggleThreads, openCentre, showFeed, focusBook, showCopilot, focusCopilot, reveal, openReplay, toggleDay]);

  // The open symbol's row in the thread list (a position or a plan): its close question and horizon, as the list shows them.
  const deskRow = useCallback((symbol: string | null | undefined) =>
    symbol ? rows.find(r => r.symbol === symbol && r.close) ?? rows.find(r => r.symbol === symbol && r.horizon) ?? null : null, [rows]);
  const barFor = (symbol: string | null) => {
    const row = deskRow(symbol);
    return { close: row?.close ?? null, plan: row ? () => pick(row) : undefined };
  };
  const threadRow = deskRow(thread?.symbol);
  const markable = threadRow && threadRow.key === `plan:${thread?.id}` && threadRow.value?.text !== "In position" ? threadRow.symbol : null;
  useEffect(() => { setPlanSymbol(markable); }, [markable]); // eslint-disable-line react-hooks/set-state-in-effect -- from the list's read
  const changeHorizon = useCallback(async (symbol: string | null | undefined, horizon: DeskHorizon) => {
    if (!symbol) return;
    await saveHorizon(symbol, horizon);
    setRefresh(n => n + 1);
  }, []);
  // Following a ticker: shown at once (the thread list applies ``follow`` ahead of its next read), saved as a day-journal
  // entry so every device agrees; a failed save puts it back and the caller says so.
  const [follow, setFollow] = useState<Readonly<Record<string, boolean>>>({});
  const changeFollow = useCallback(async (symbol: string, following: boolean) => {
    setFollow(prev => ({ ...prev, [symbol]: following }));
    try {
      await saveFollow(symbol, following);
    } catch (failure) {
      setFollow(prev => ({ ...prev, [symbol]: !following }));
      throw failure;
    }
    setRefresh(n => n + 1);
  }, []);
  const followRead = useCallback((symbol: string) => setFollow(prev => {
    const next = { ...prev };
    delete next[symbol];
    return next;
  }), []);
  // A ticker's follow switch for its header: null when the desk has no row about it.
  const followingOf = (symbol: string | null | undefined) =>
    symbol && rows.some(r => r.symbol === symbol) ? !rows.some(r => r.symbol === symbol && r.hidden) : null;
  const linkRow = !thread && link?.symbol ? deskRow(link.symbol) : null;
  const alertRows = session.data?.to_answer?.alerts?.rows; // a position's thread offers its alerts sent today a rating

  // The copilot's ticker: the open thread's, a deep link's, or (Main chat) the one its latest turn is about.
  const day = thread ? !thread.symbol : !link?.symbol;
  const known = useMemo(() => rows.flatMap(r => r.symbol ? [r.symbol] : []), [rows]);
  const focus = day ? answerSymbol(turnText, known) : null;
  const talking = thread ? thread.symbol : link?.symbol ?? null;
  // The centre follows the book's pick, else the copilot's ticker (a day conversation's: the ticker its latest answer is
  // about, ``answerSymbol``; an answer with no clear subject shows the market), else the first followed position; none
  // is the market.
  const followed = useMemo(() => positionRows(rows).filter(r => !r.hidden), [rows]);
  const centreSymbol = picked ?? talking ?? focus ?? (day && turnText ? null : followed[0]?.symbol ?? null);
  // Another ticker on the chart drops a Scanner row's lines for good.
  useEffect(() => { if (scanLines && scanLines.symbol !== centreSymbol) setScanLines(null); }, [scanLines, centreSymbol]); // eslint-disable-line react-hooks/set-state-in-effect -- follows the chart's ticker
  // The row tapped when two contracts share the ticker: the Position panel acts on that one.
  const centreRow = centreSymbol ? followed.find(r => r.key === pickedKey && r.symbol === centreSymbol) ?? followed.find(r => r.symbol === centreSymbol)
    ?? rows.find(r => r.symbol === centreSymbol && r.key.startsWith("trade:")) ?? null : null;
  // His open paper positions in the centre's ticker: each gets its own Position panel under the chart, marked PAPER.
  const centrePaper = useMemo(() => centreSymbol ? (paper.book?.positions ?? []).filter(p => p.symbol === centreSymbol) : [], [centreSymbol, paper.book]);
  // The dock's tab: his pick, else Position when he holds the ticker (real or paper), else the Chain. A ticker set to Not
  // following stays quiet: no chain read until he opens the Chain.
  const quietTicker = !!centreSymbol && rows.some(r => r.symbol === centreSymbol && r.hidden);
  // A Chain he folded away is not opened for him either.
  const dockTab: DockTab = dockPick ?? (centreRow?.book || centrePaper.length || quietTicker || use.hidden("tab.chain") ? "position" : "chain");
  // How he uses the desk: the Grid's opens, the chart's when he comes back from it, and each dock tab he picks (the
  // dock's own default, which follows the ticker, is not an open of his; a tap inside it counts as its tab's).
  const centreOpened = useRef<{ grid: boolean; pick: DockTab | null } | null>(null);
  useEffect(() => {
    if (!on) return;
    const was = centreOpened.current;
    centreOpened.current = { grid, pick: dockPick };
    if (!was) return;
    if (grid && !was.grid) countOpen("tab.grid");
    if (!grid && was.grid) countOpen("tab.chart");
    if (!grid && dockPick && dockPick !== was.pick) countOpen(DOCK_TABS.find(t => t.id === dockPick)!.use);
  }, [on, grid, dockPick]);
  // The keyboard's place follows the Grid: Back to chart when it opens, the Grid's button when it closes (only when
  // nothing else holds the focus).
  const gridShown = useRef(grid);
  useEffect(() => {
    if (gridShown.current === grid) return;
    gridShown.current = grid;
    const idle = !document.activeElement || document.activeElement === document.body;
    if (idle) requestAnimationFrame(() => document.querySelector<HTMLElement>(grid ? '[data-testid="grid-back"]' : '[data-testid="grid-open"]')?.focus({ preventScroll: true }));
  }, [grid]);
  // The chart reads by the conversation when it is about that ticker (its plan's lines), else by the position's plan.
  const centreThread = useMemo<DeskThreadRef | null>(() => {
    if (!centreSymbol) return null;
    if (thread && !thread.mainDay && thread.symbol === centreSymbol) return thread;
    const id = centreRow?.investigationId;
    return id ? { id, symbol: centreSymbol, title: centreSymbol, refreshKey: 0 } : null;
  }, [centreSymbol, thread, centreRow?.investigationId]);
  // The Watching list under the book: its names (none held: those are the book's) ride the sparks read.
  const watching = useWatching(on, refresh);
  const held = useMemo(() => new Set(positionRows(rows).flatMap(r => r.symbol ? [r.symbol] : [])), [rows]);
  // Only once the book has read: before that a held name would show here, then jump to the book.
  const watched = useMemo(() => rowsRead ? (watching.data?.symbols ?? []).filter(s => !held.has(s)) : [], [rowsRead, watching.data, held]);
  const sparks = useSparks(on ? [...(centreSymbol ? [centreSymbol] : []), ...followed.flatMap(r => r.symbol ? [r.symbol] : [])] : [], on ? watched : []);
  // Earnings tags for the book and the Watching list: one read for both, kept for half an hour.
  const events = useDeskEvents(on && rowsRead, followed, watched);
  // ⌘K's "Go to": a short phrase naming a place ("rules", "nvda chain") goes straight there. Its ticker must be one the
  // desk already shows (the book's and the thread list's rows, the Watching list), never one he set to Not following.
  const goTo = useCallback((query: string): PaletteCommand | null => {
    const quiet = new Set(rows.filter(r => r.hidden && r.symbol).map(r => r.symbol!));
    const known = new Set([...rows.flatMap(r => r.symbol ? [r.symbol] : []), ...(watching.data?.symbols ?? [])].filter(s => !quiet.has(s)));
    const found = placeFromWords(query, known);
    if (!found) return null;
    const { place, symbol } = found;
    // A place on its own is its palette command, brought to the top (and not listed twice).
    if (!symbol) return commands.find(c => c.id === (place.id === "day" ? "day" : `go-${place.id}`)) ?? null;
    return { id: `goto-${place.id}`, name: `Go to ${symbol ? `${symbol} · ` : ""}${place.label}`, hint: place.hint, key: place.key, run: () => { moveTo(place.id, symbol); } };
  }, [rows, watching.data, moveTo, commands]);
  // A thread opened from anywhere but the book (the drawer, J / K, the palette, a link) takes the centre with it.
  const lastTalking = useRef(talking);
  useEffect(() => {
    if (talking === lastTalking.current) return;
    lastTalking.current = talking;
    if (talking && talking !== picked) setPicked(null); // eslint-disable-line react-hooks/set-state-in-effect -- the copilot's ticker moved
  }, [talking, picked]);

  // Selecting a position: the centre shows it at once; where the copilot sits beside it, the copilot opens it too. On a
  // sheet layout the copilot waits for Ask, so the chart stays in view.
  const select = useCallback((row: DeskThread) => {
    setPicked(row.symbol);
    setPickedKey(row.key);
    setGrid(false);
    setDockPick(null); // the dock's default: its Position
    // Beside the Feed, the copilot opens it behind the Feed's tab: picking a row never takes the Feed away.
    if (!sheetLayout()) { if (row.symbol !== talking) { openRow(row); setFeedShown(feedKept.current); } }
    else showCentre();
  }, [openRow, talking, showCentre]);
  // A watched name (no row of its own) opens the way a position without one does: the symbol's newest open
  // conversation, else its desk view, in place.
  const openWatched = useCallback((symbol: string) => {
    const talk = saved.filter(t => t.symbol === symbol && t.status !== "closed").sort((a, b) => b.updated_at.localeCompare(a.updated_at))[0];
    if (talk) actions.open(talk.id);
    else go(`/copilot-lab?${new URLSearchParams({ symbol })}`);
  }, [saved, actions, go]);
  // Selecting a watched row: exactly as a position's.
  const selectWatched = useCallback((symbol: string) => {
    setPicked(symbol);
    setPickedKey(null);
    setGrid(false);
    setDockPick(null);
    if (!sheetLayout()) { if (symbol !== talking) { openWatched(symbol); setFeedShown(feedKept.current); } }
    else showCentre();
  }, [openWatched, talking, showCentre]);
  // A Grid tile: the name on the full Chart tab, in place, as its book row or Watching row would open it.
  const openFromGrid = useCallback((symbol: string) => {
    const row = followed.find(r => r.symbol === symbol);
    if (row) select(row);
    else selectWatched(symbol);
  }, [followed, select, selectWatched]);
  const gridHeld = useMemo(() => [...new Set(followed.flatMap(r => r.symbol ? [r.symbol] : []))], [followed]);
  const gridHidden = useMemo(() => new Set(rows.flatMap(r => r.hidden && r.symbol ? [r.symbol] : [])), [rows]);
  // A ticker chip over the phone's Chain: that ticker's chain, in place.
  const pickChain = useCallback((symbol: string) => { setPicked(symbol); setPickedKey(null); setGrid(false); setDockPick("chain"); }, []);
  const askWatched = useCallback((symbol: string) => { setPicked(symbol); setPickedKey(null); if (symbol !== talking) openWatched(symbol); showCopilot(); }, [openWatched, talking, showCopilot]);
  const planWatched = useCallback((symbol: string) => go(copilotLabHref(symbol, planContext(), { kind: "copilot", ref: null })), [go]);
  // The ping card read its ticker: the centre shows it (a plan conversation's link names no symbol of its own).
  const cardSymbol = useCallback((symbol: string) => { setPicked(symbol); setPickedKey(null); }, []);
  // Ask the copilot (the sheet's button): about the picked position (or watched name) when the copilot is on another ticker.
  const askCopilot = () => {
    const row = picked && picked !== talking ? followed.find(r => r.symbol === picked) : undefined;
    if (row) openRow(row);
    else if (picked && picked !== talking && watched.includes(picked)) openWatched(picked);
    showCopilot();
  };

  // A feed item's Ask: its question in the box, unsent, in the item's own thread (a plan's), else the symbol's open
  // conversation, else the symbol's desk view; an item with no symbol in today's conversation (or a new one when another
  // thread is open). A phone opens the sheet.
  const askAbout = useCallback((symbol: string | null, text: string, investigationId: string | null = null) => {
    if (symbol) setPicked(symbol);
    const talk = investigationId ?? (symbol ? deskRow(symbol)?.investigationId ?? rows.find(r => r.symbol === symbol && r.investigationId)?.investigationId
      ?? saved.filter(t => t.symbol === symbol && t.status !== "closed").sort((a, b) => b.updated_at.localeCompare(a.updated_at))[0]?.id ?? null : null);
    if (talk) { setCommand({ kind: "open", id: talk, text, n: ++sent.current }); showCopilot(); }
    else if (symbol) go(copilotLabHref(symbol, text));
    else if (!thread || thread.mainDay === today) fill(text);
    else go(copilotLabHref("", text));
  }, [today, deskRow, rows, saved, go, thread, fill, showCopilot]);
  const askFeed = useCallback((item: FeedItem) => askAbout(item.symbol, feedQuestion(item, today), item.investigation_id), [askAbout, today]);
  // The chart's level menu: Plan from here follows its desk link in place; Ask scopes the copilot like a feed item's Ask.
  // The Chain tab's actions: Check a call with the contract in the box, the plan flow, a saved plan's ticket.
  const chainCheck = useCallback((text: string) => { setCheckSeed(seed => ({ text, n: (seed?.n ?? 0) + 1 })); setGrid(false); setDockPick("check"); showCentre(); }, [showCentre]);
  const chainPlan = useCallback((pick: ChainPick, line: string) => go(copilotLabHref(pick.symbol, planContext(line), { kind: "copilot", ref: null })), [go]);
  const chainTicket = useCallback((id: string, pick: ChainPick) => openTicket(id, { expiry: pick.expiry, strike: pick.strike,
    ...(pick.short != null ? { short: pick.short, kind: pick.side } : {}) }), []);
  // An Unusual options row: its contract selected in the Chain tab, in place.
  const openUnusual = useCallback((pick: ChainPick) => { setPicked(pick.symbol); setPickedKey(null); setChainFocus(f => ({ pick, n: (f?.n ?? 0) + 1 })); setGrid(false); setDockPick("chain"); showCentre(); }, [showCentre]);
  // A TradingView alert row: its ticker on the desk chart, in place, where the alert's marker sits; the dock under it
  // opens on its default (the position, else the Chain).
  const openFeedChart = useCallback((symbol: string) => { setPicked(symbol); setPickedKey(null); setGrid(false); setDockPick(null); showCentre(); }, [showCentre]);
  // A Scanner row: its ticker on the desk chart, in place, with the scanner's levels as thin lines.
  const openScanner = useCallback((row: DeskScannerRow) => { setPicked(row.symbol); setPickedKey(null); setScanLines({ symbol: row.symbol, lines: scannerGuides(row) }); setGrid(false); setDockPick(null); showCentre(); }, [showCentre]);
  // A scanner ping's card: its ticker on the chart with the scanner's levels, once the scanner has read, without moving
  // a phone off the Feed.
  const scanLinked = useRef(false);
  useEffect(() => {
    if (scanLinked.current || feedLink?.kind !== "scanner" || !feedLink.id) return;
    const row = scanner?.rows.find(r => r.id === feedLink.id);
    if (!row) return;
    scanLinked.current = true;
    setPicked(row.symbol); setPickedKey(null); // eslint-disable-line react-hooks/set-state-in-effect -- follows the scanner's first read
    setScanLines({ symbol: row.symbol, lines: scannerGuides(row) });
  }, [scanner, feedLink]);
  const chartActions = useMemo<DeskChartActions>(() => ({ go, ask: (symbol, text) => askAbout(symbol, text) }), [go, askAbout]);
  // A feed item's Plan it: a Radar setup card opens on its own Plan it (the desk's Radar card); his own position or plan
  // opens its plan thread, else the plan form for the symbol. Nothing is saved or sent from the feed.
  const planFeed = useCallback((item: FeedItem) => {
    if (item.plan === "setup" && item.href) { go(item.href); return; }
    const id = item.investigation_id ?? (item.symbol ? deskRow(item.symbol)?.investigationId ?? rows.find(r => r.symbol === item.symbol && r.investigationId)?.investigationId : null);
    if (id) actions.open(id);
    else if (item.symbol) go(copilotLabHref(item.symbol, planContext(), { kind: "copilot", ref: null }));
  }, [go, deskRow, rows, actions]);

  // Opening a ticker (picking its book row, a strip item, its thread or its desk view) counts as having seen it today.
  useEffect(() => {
    const day = nyDay();
    for (const symbol of [picked, talking]) if (symbol) setOpened(saveOpened(day, symbol)); // eslint-disable-line react-hooks/set-state-in-effect -- the owner opened it
  }, [picked, talking]);

  // The strip: what needs a decision now (``deskNeeds``' documented order), each item clearing itself.
  const closingNow = dayPhase === "close";
  const needs = on && rowsRead ? deskNeeds({ rows, alerts: session.data?.to_answer?.alerts?.rows ?? [], plans, day: nyDay(), closing: closingNow,
    fills: fills.waiting.length, opened }) : [];
  // What the strip could not check: said in one quiet line instead of an empty strip that looks like "nothing waits".
  const unchecked = !on ? null : rowsFailed || sections?.positions === "unavailable" ? "positions"
    : sections?.plans === "unavailable" ? "plans" : session.error ? "today's alerts"
    : session.data?.sections?.alerts_to_answer === "unavailable" ? "today's alerts" : null;
  // One amber thing at a time: while the strip asks something, the Day button is plain (it keeps its count in words).
  const dayAmber = dayToDo && needs.length === 0;
  const openNeed = (row: DeskThread) => { setPicked(row.symbol); openRow(row); showCopilot(); };
  // The same words as the copilot's own "Why is it moving?" about that ticker, sent in today's conversation.
  const askWhy = (need: DeskNeed) => actions.ask(`Why is ${need.symbol} moving today?`);
  const openSymbol = (need: DeskNeed) => need.row ? openNeed(need.row) : need.symbol ? (setPicked(need.symbol), go(`/copilot-lab?${new URLSearchParams({ symbol: need.symbol })}`)) : undefined;
  const needActions = (need: DeskNeed) => {
    const row = need.row;
    switch (need.kind) {
      case "alert": return [{ label: "Open it", primary: true, run: () => openSymbol(need) }, { label: "Ask why", run: () => askWhy(need) }];
      case "level": return [{ label: "Open the plan", primary: true, run: () => openSymbol(need) }, { label: "Ask why", run: () => askWhy(need) }];
      case "card": return [{ label: "Open the card", primary: true, run: () => { setPicked(row!.symbol); pick(row!); } }];
      case "expiring": return [{ label: "Open it", primary: true, run: () => openSymbol(need) }];
      case "fill": return [{ label: "Link it", primary: true, run: () => { fills.start(); showCopilot(); } }];
    }
  };

  // The day's block by the time of day, one block each, under Watching: the morning brief before the open (nothing until
  // it is written), the day report after the close, else what changed since the owner last looked. Arm today's plans and Close
  // the day are not repeated here: Close the day is one quiet link under the day report (and in ⌘K), never the strip.
  const booked = forAccount(rows, live, account);
  const lower = dayPhase === "pre" ? <MorningBrief prep={session.data?.prep} fill={fill} max={3} />
    : dayPhase === "close" ? (
      <section aria-label="Day report" data-testid="day-report" className="space-y-1.5">
        <DayReport rows={rows} rowsRead={rowsRead} onOpen={select} />
        <button type="button" onClick={closeDay} data-testid="close-the-day"
          className="inline-flex min-h-11 items-center px-1 text-xs text-muted-foreground hover:text-foreground sm:min-h-0">Close the day{tally.total > tally.done ? ` · ${tally.total - tally.done} to review` : ""} →</button>
        {/* Watch your day's replay of today, only once one was kept: the day's one way back to it from the desk. */}
        <WatchDayLink from={today} className="inline-flex min-h-11 items-center gap-1.5 px-1 text-xs text-muted-foreground hover:text-foreground sm:min-h-0" />
      </section>
    ) : <SinceYouLooked rows={rows} session={session.data} read={rowsRead} />;

  // The status line's first words: the mode's mark and whose book. Real names the account line's account (label and
  // masked number, never the full one); paper and replay say the real book is untouched.
  const shownAccounts = rowsFresh && liveOn(live) ? (live?.accounts ?? []).filter(a => !account || a.masked === account) : [];
  const realWho = !shownAccounts.length ? "from the journal" : shownAccounts.length <= 2 ? shownAccounts.map(a => `${a.label} ${a.masked}`).join(" + ")
    : `${shownAccounts.length} accounts`;
  const statusMark = mode === "real" ? <ModeMark mode="real" detail={realWho} />
    : mode === "paper" ? <ModeMark mode="paper" detail="real book unchanged" /> : <ModeMark mode="replay" detail="real and paper books unchanged" />;
  const openPaper = placeRun.paper;

  return (
    <div ref={desk} className={styles.desk} data-on={on} data-mode={mode} data-sheet={sheet ? "open" : "closed"} data-threads={threadsShown ? "shown" : "hidden"}
      data-view={phoneView} data-feed={feedShown ? "shown" : "hidden"}>
      <DeskUseRoot use={use}>
      {/* The desk's head: the top bar and, at its right, the desk's buttons. On a phone the buttons' row comes first and
          stays at the top of the screen, starting with the Feed chip; the views are the desk's own tab bar at the bottom
          (CopilotLab.module.css). */}
      <div className={styles.head} style={replay ? { display: "none" } : undefined}>
      {on && (
        <div className={styles.topRow}>
          {/* A phone's Feed: a chip in the row that stays put, so it is one tap from every view and its count is never
              cut short. Wider, the Feed is the side's tab or a drawer. */}
          <div data-testid="desk-views" className={styles.views}>
            <button type="button" aria-pressed={phoneView === "feed"} data-testid="desk-view-feed" data-use="view.feed"
              onClick={() => phoneView === "feed" ? showBook() : showFeed()} title="Yours, ideas and the market today ( F )"
              className={cn("inline-flex min-h-11 min-w-11 items-center justify-center gap-1.5 whitespace-nowrap rounded-md border px-3 text-sm max-[369px]:px-2",
                phoneView === "feed" ? "bg-secondary font-semibold text-foreground" : "text-muted-foreground")}>
              Feed
              {feedNew.count > 0 && <span data-testid="feed-new-phone" className="text-xs tabular-nums text-muted-foreground">{feedNew.count}<span className="sr-only"> new</span></span>}
            </button>
          </div>
          <div className={styles.barActions}>
            {/* Data health, said once: from 768 px the status line along the bottom has it, so the bar shows the dot only
                while a money source is behind (red); a phone (no status line) keeps the dot as it was. */}
            <div data-use="health" className="contents"><DeskHealthDot onlyRed={!phone} /></div>
            {/* The Day button: the day's routine as one checklist, by the New York clock. A phone keeps an icon and one word.
                One amber thing at a time: while the Needs-you strip asks something, it stays plain (its count in words). */}
            <button type="button" onClick={toggleDay} aria-pressed={dayShown} data-testid="desk-day-button" data-use="day" data-phase={dayPhase ?? "session"}
              data-amber={dayAmber || undefined}
              title={dayPhase === "pre" ? "Start the day: brief, plans to arm, goals, prep ( D )" : dayPhase === "close" ? "Close the day: your day, to review, paper next to real, rules, goals ( D )" : "The day's checklist ( D )"}
              className={cn("inline-flex min-h-11 min-w-10 items-center justify-center gap-1.5 whitespace-nowrap rounded-md border px-2 text-xs sm:min-w-11 max-sm:flex-col max-sm:gap-0.5 max-sm:px-1 max-sm:text-[10px] max-sm:leading-none sm:min-h-8 sm:px-2.5",
                dayAmber ? "border-primary bg-primary font-semibold text-primary-foreground hover:bg-primary/90" : cn("text-muted-foreground hover:text-foreground", dayShown && "bg-secondary"))}>
              {dayPhase === "pre" ? <Sunrise size={14} aria-hidden /> : dayPhase === "close" ? <Moon size={14} aria-hidden /> : <CalendarCheck size={14} aria-hidden />}
              {dayPhase === "pre" ? <><span className="sm:hidden">Start</span><span className="max-sm:hidden">Start the day</span></>
                : dayPhase === "close" ? <><span className="sm:hidden">Close{dayLeft ? ` · ${dayLeft}` : ""}</span><span className="max-sm:hidden">Close the day{dayLeft ? ` · ${dayLeft} to review` : ""}</span></>
                : "Day"}
            </button>
            {/* Now (today's Main chat) and Plan a trade are not on the bar: ⌘K has both (Plan a trade with N), the
                breadcrumb's Now goes back to today, and Plan a trade sits on the chart, the Chain and the Feed. */}
            {/* Between 768 and 1180 px the Feed is a drawer on the right: this opens it (wider, it is the tab beside the copilot; a phone has its view). */}
            <button type="button" onClick={() => feedShown ? setFeedShown(false) : showFeed()} aria-pressed={feedShown} title="Yours, ideas and the market today ( F )"
              className={cn(styles.feedButton, "min-h-11 items-center gap-1.5 rounded-md border px-2.5 text-xs text-muted-foreground hover:text-foreground sm:min-h-8", feedShown && "bg-secondary")}>
              Feed{feedNew.count > 0 && <span data-testid="feed-new-bar" className="tabular-nums">{feedNew.count}<span className="sr-only"> new</span></span>}
            </button>
            {/* No count here: what needs him is the strip's, counted once there. A phone keeps Threads in the top row's
                More (it rarely opens there), so the row is the Feed, the health dot, the Day and Jump to. */}
            {!phone && <button type="button" onClick={toggleThreads} aria-pressed={threadsShown} aria-label="Threads" data-use="threads" title="The thread list and previous days ( [ )"
              className={cn("inline-flex min-h-11 min-w-11 items-center justify-center gap-1.5 rounded-md border px-2 text-xs text-muted-foreground hover:text-foreground sm:min-h-8", threadsShown && "bg-secondary")}>
              <PanelLeft size={15} aria-hidden /><span className="hidden sm:inline">Threads</span>
            </button>}
            <button type="button" onClick={() => setPalette(true)} aria-label="Jump to a thread or command, or ask the copilot" aria-haspopup="dialog" data-use="palette"
              className="inline-flex min-h-11 min-w-11 items-center justify-center gap-2 rounded-md border bg-card px-2.5 text-xs text-muted-foreground hover:text-foreground sm:min-h-8">
              {/* A phone keeps the bar short: icons only, as the button's label already says. */}
              <Search size={14} aria-hidden /><span className="hidden sm:inline">Jump to or ask…</span><kbd className={cn(KBD, "hidden md:inline")}>{jumpKey}</kbd>
            </button>
            {phone && (
              <div className="relative">
                <button type="button" onClick={() => setTopMore(was => !was)} aria-expanded={topMore} aria-label="More: threads" data-testid="desk-top-more"
                  className={cn("inline-flex min-h-11 min-w-11 items-center justify-center rounded-md border text-muted-foreground hover:text-foreground", (topMore || threadsShown) && "bg-secondary")}>
                  <Ellipsis size={16} aria-hidden />
                </button>
                {topMore && (
                  <div role="menu" data-testid="desk-top-menu" className="absolute right-0 top-full z-30 mt-1 w-56 rounded-lg border bg-card p-1 shadow-lg">
                    <button type="button" role="menuitem" onClick={() => { setTopMore(false); toggleThreads(); }} aria-pressed={threadsShown} data-use="threads"
                      className="flex min-h-11 w-full items-center gap-2 rounded-md px-2.5 text-left text-sm hover:bg-secondary">
                      <PanelLeft size={15} aria-hidden />Threads and previous days
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}
      <header className={styles.bar}>
        {/* A wide screen folds the app's navigation into this button, so the desk has the full width; a phone keeps its tabs. */}
        {navFolded && (
          <button type="button" onClick={openNavMenu} aria-label="Open menu" title="All pages, sync and the plan streak"
            className="-ml-1.5 hidden h-8 items-center gap-1.5 rounded-md px-2 text-xs text-muted-foreground hover:bg-secondary hover:text-foreground md:inline-flex">
            <Menu size={15} aria-hidden />Menu
          </button>
        )}
        <h1 className={styles.title}><MessagesSquare size={17} aria-hidden />Desk</h1>
        {/* Real, Paper or Replay: a view only (a phone has it at the top of Positions). */}
        {on && <div className={cn("contents", styles.wideOnly)}><ModeSwitch mode={mode} onPick={pickMode} /></div>}
        {/* One row (the calm pass): the market's line (the clock, SPY / QQQ / VIX) and the day's money are not here. The
            money is the book's (its heading's hover has Open and Realized today, a live account line sits under it); the
            market's line is ⌘K's "Today" and the status line's hover. */}
        {/* Paper mode: the paper book's value beside the real accounts, each with its mark. */}
        {on && viewMode === "paper" && <div className={cn("contents", styles.wideOnly)}><PaperValue book={paper.book} failed={paper.failed} onOpen={openPaper} className="sm:order-last" /></div>}
        {on && <ScalpShortlistNudge onOpen={() => reveal([], "practice-line-scalp", false, "scalp")} />}
      </header>
      </div>
      {/* Replay never hides real money: one REAL line in its header from the rows, feed and session the hidden desk
          keeps reading (every account, whatever the account line's pick), read only. */}
      {on && replay && <DeskReplay symbol={centreSymbol} redo={redo} onLeave={to => { setReplay(false); setRedo(null); if (to) setDeskMode(to); }}
        live={<ReplayLiveLine rows={rows} live={rowsFresh ? live : null} read={rowsRead} day={today} need={needs[0] ?? null}
          failed={!!rowsFailed || sections?.positions === "unavailable"} asOf={positionsAt} />} />}
      <div id="desk-cockpit" className={styles.cockpit} style={replay ? { display: "none" } : undefined}>
        {/* A phone's Positions opens on what the account is worth and how the book is doing, in one block. */}
        {on && phone && (
          <div data-use="accounts" className={styles.value}>
            {/* The mode switch sits at the top of Positions on a phone (its top row has no room), beside the total; Paper
                adds the paper value under it. */}
            <PhoneValue live={rowsFresh ? live : null} rows={rows} booked={booked} active={account} onPick={setAccount} day={today}
              realized={session.data?.realized_today ?? null} aside={
                <div className="flex shrink-0 flex-col items-end gap-1">
                  <ModeSwitch mode={mode} onPick={pickMode} />
                  {viewMode === "paper" && <PaperValue book={paper.book} failed={paper.failed} onOpen={openPaper} />}
                </div>} />
          </div>
        )}
        {/* A phone's Orders: Robinhood's working orders, then today's fills. Read only. */}
        {on && phone && <div data-use="view.orders" className={styles.orders}><PhoneOrders rows={booked.rows} live={booked.live} /></div>}
        {on && (
          <div className={styles.strip}>
            {/* A phone shows the strip on its Book view; on the other two the Book's button carries the amber count. */}
            {needs.length > 0 && <div className={styles.needs} data-use="needs"><NeedsStrip needs={needs} actions={needActions} /></div>}
            {unchecked && <p data-testid="needs-you-unchecked" className="px-1 pt-1 text-xs text-muted-foreground">Needs you could not check {unchecked} just now; it will read again in a minute.</p>}
            {/* What's moving: one thin row across the book and the centre, folded until opened; a tile selects its symbol in
                place, as a watched name does. A phone puts it under the book. */}
            <div className={styles.moving}><Fold id="moving"><MovingStrip on={on} selected={centreSymbol} onSelect={selectWatched} /></Fold></div>
          </div>
        )}
        {on && (
          <aside aria-label="Threads" className={styles.rail}>
            <div className="flex items-center justify-between">
              <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Threads</span>
              <button type="button" onClick={() => setThreadsShown(false)} aria-label="Close the thread list"
                className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-md text-muted-foreground hover:bg-secondary hover:text-foreground sm:min-h-8 sm:min-w-8">
                <X size={15} aria-hidden />
              </button>
            </div>
            <ThreadRail actions={actions} active={thread?.id ?? null} activeSymbol={talking} main={onNow}
              pick={pick} onRows={readRows} onReadFailed={setRowsFailed} onWalk={setWalk} onSaved={setSaved} refresh={refresh} follow={follow} onFollow={changeFollow} onFollowRead={followRead}
              phase={fills.waiting.length > 0 && <FillsToLink count={fills.waiting.length} onStart={() => { setThreadsShown(false); fills.start(); }} />} />
            {threadsShown && <ThisWeek />}
          </aside>
        )}
        {on && (
          <div className={styles.book}>
            {/* Money and safety first: his real positions and working orders, with what is at risk now under the heading
                (never folded). Then Watching, the day's block, his rules and goals, and Practice (paper and replay). */}
            <div data-use="book" className="contents"><Book rows={booked.rows} sparks={sparks} earnings={events} selected={centreSymbol} selectedKey={pickedKey} day={today} read={rowsRead} updating={rowsRead && !rowsFresh} onSelect={select} onFollow={changeFollow}
              risk={<RiskWord session={session.data} />} realized={session.data?.realized_today ?? null}
              // The live account line (a phone has it in its value block): each account's figures, a tap narrows the book.
              accounts={!phone && <div className={cn("min-w-0 px-3 pb-1.5", styles.wideOnly)}><Fold id="accounts" compact><DeskAccounts live={rowsFresh && liveOn(live) ? live : null} rows={rows} active={account} onPick={setAccount} stacked /></Fold></div>}
              filter={account ? { label: live?.accounts?.find(a => a.masked === account)?.label ?? account, onShowAll: () => setAccount(null) } : null}
              live={booked.live} onRefreshLive={() => { refreshRobinhood().catch(() => { /* the line says so on the next read */ }).finally(() => setRefresh(n => n + 1)); }} /></div>
            {/* After 14 days of desk use: one quiet card offering to fold what he never opens. Never folds unasked. */}
            <FoldSuggestion />
            <Fold id="watching"><Watching data={rowsRead ? watching.data : null} failed={watching.failed} sparks={sparks} earnings={events} held={held} selected={centreSymbol}
              onSelect={selectWatched} onAsk={askWatched} onPlan={planWatched} onChange={watching.set} /></Fold>
            {/* The day's block (the brief, Since you looked, the day report) and the practice goal under it. */}
            <div data-use="dayblock" className="contents">{lower}<DayFacts /></div>
            {/* How I'm doing this week: real beside paper, outside the paper frame (replay keeps its own score in Practice). */}
            <Fold id="scorecard"><HowImDoing book={paper.book} /></Fold>
            {/* His rules and goals: one neutral line, outside the paper frame, since they cover real trades too. */}
            <RulesAndGoals book={paper.book} />
            {/* Practice: his paper book, the QQQ overnight and momentum paper books and Replay, one line each. Never real money. */}
            <Practice on={on} paper={paper} symbol={centreSymbol} review={<PaperReviewCard review={paper.book?.review} onAsk={actions.ask} />} onReplay={() => setReplay(true)}
              onPick={selectWatched} />
          </div>
        )}
        {on && (
          <section id="desk-centre" aria-label="Chart and tools" className={styles.centre} data-grid={grid ? "open" : undefined} data-mode={viewMode}
            style={{ "--desk-share": share } as CSSProperties}>
            {/* The chart never leaves: it stays on top, and the selected ticker's tools dock under it (Position, Chain,
                Ticket, Notes, Check a call). The Grid of many tickers takes the whole centre until Back to chart. The Feed
                is not here: it sits beside the copilot, so the chart stays while he reads it. A phone's Chain view puts
                the tickers it can open above the Chain, as chips. */}
            {/* A position ping lands here: what fired and Close / Trim / Set stop, over the ticker's chart. */}
            {card && <PingCard card={card} rows={rows} ordersLive={liveOn(booked.live) && booked.live?.orders_read === true} onSymbol={cardSymbol} onAsk={fill} onPlan={planWatched} onDismiss={() => setCard(null)} />}
            {phone && <div className={styles.chainPick}><ChainPicker held={gridHeld} watched={watched.filter(s => !gridHidden.has(s))} selected={centreSymbol} onPick={pickChain} /></div>}
            {grid ? (
              <div data-testid="desk-grid-view" className={styles.gridView}>
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 pt-2.5">
                  <button type="button" onClick={() => openCentre("chart")} data-testid="grid-back" title="Back to the selected ticker's chart ( C )"
                    className="inline-flex min-h-11 items-center gap-1.5 rounded-md border px-2.5 text-xs font-medium text-foreground hover:bg-secondary sm:min-h-8">
                    <ArrowLeft size={14} aria-hidden />Back to chart
                  </button>
                  <span className="text-sm font-semibold">Grid</span>
                  <span className="text-xs text-muted-foreground">Your positions and watched names</span>
                  {/* A folded Grid shown for now: Keep showing is here too. */}
                  <FoldMore ids={["tab.grid"]} onOpen={() => openCentre("grid")} className="ml-auto" />
                </div>
                <div className="p-3"><DeskGrid held={gridHeld} watched={watched} hidden={gridHidden} sparks={sparks} earnings={events} selected={centreSymbol} onOpen={openFromGrid} /></div>
              </div>
            ) : (
              <CentreChart symbol={centreSymbol} thread={centreThread} row={centreRow} sparks={sparks} actions={chartActions} rows={rows} earnings={events} onReplay={() => setReplay(true)}
                guides={scanLines && scanLines.symbol === centreSymbol ? scanLines.lines : undefined}
                paper={centrePaper} paperOrders={paper.book?.orders} onPlan={planWatched} ordersLive={liveOn(booked.live)}
                className={styles.centreBody} chartClassName={styles.chartPart} chartLater={!chartNow && !chartShown} dock={position => (
                  <div data-testid="desk-dock" className={styles.dock}>
                    {/* From 1024 px: drag (or arrow keys) to give the chart or the dock more room; kept for this browser. */}
                    <div role="separator" aria-orientation="horizontal" aria-label="Chart and dock size" aria-valuemin={SHARE.min * 100} aria-valuemax={SHARE.max * 100}
                      aria-valuenow={Math.round(share * 100)} tabIndex={0} data-testid="dock-splitter" className={styles.splitter} onPointerDown={dragSplit}
                      onKeyDown={event => { if (event.key === "ArrowUp" || event.key === "ArrowDown") { event.preventDefault(); keepShare(share + (event.key === "ArrowUp" ? -0.04 : 0.04)); } }} />
                    {/* The strip's bottom line is an inset shadow, so a tab's underline paints over it without spilling past the
                        scroll box. A tab he folded away waits in More at the strip's end (one tap shows it for now); its key and
                        ⌘K still open it. */}
                    <div className={cn(styles.dockTabs, "flex items-center gap-1 pr-1.5 shadow-[inset_0_-1px_0_hsl(var(--border))]")}>
                      <div role="tablist" aria-label="Centre" className="flex min-w-0 flex-1 overflow-x-auto px-1 pt-1 [scrollbar-width:none] sm:gap-1 sm:px-2">
                        {DOCK_TABS.filter(t => !use.hidden(t.use) || dockTab === t.id).map(({ id, label, key, use: piece }) => (
                          <button key={id} type="button" role="tab" aria-selected={dockTab === id} onClick={() => setDockPick(id)} title={key ? `${label} ( ${key} )` : label} data-use={piece}
                            className={cn("min-h-11 shrink-0 whitespace-nowrap border-b-2 px-1.5 text-sm sm:min-h-9 sm:px-2.5",
                              dockTab === id ? "border-foreground text-foreground" : "border-transparent text-muted-foreground hover:text-foreground")}>
                            {/* A phone shows "Check" so the five tabs and the Grid fit its width; the name stays whole. */}
                            {id === "check" ? <>Check<span className="max-sm:sr-only"> a call</span></> : label}
                          </button>
                        ))}
                      </div>
                      {!use.hidden("tab.grid") && (
                        <button type="button" onClick={() => openCentre("grid")} data-use="tab.grid" data-testid="grid-open" title="Your positions and watched names, several charts at once ( G )"
                          className="inline-flex min-h-11 min-w-11 shrink-0 items-center justify-center gap-1.5 rounded-md px-2 text-sm text-muted-foreground hover:bg-secondary hover:text-foreground sm:min-h-8 sm:min-w-0">
                          <LayoutGrid size={14} aria-hidden /><span className="max-sm:sr-only">Grid</span>
                        </button>
                      )}
                      <FoldMore ids={[...DOCK_TABS.map(t => t.use), "tab.grid"]} onOpen={id => openCentre(id.slice(4) as CentreTab)} />
                    </div>
                    <div role="tabpanel" aria-label={DOCK_TABS.find(t => t.id === dockTab)!.label} data-testid="dock-panel" data-use={DOCK_TABS.find(t => t.id === dockTab)!.use} className={styles.dockPanel}>
                      {dockTab === "check" ? <CheckACall seed={checkSeed} />
                        : dockTab === "chain" ? <DeskChain symbol={centreSymbol} plans={tickets.plans} onCheck={chainCheck} onPlan={chainPlan} onTicket={chainTicket} unusual={unusual?.rows} focus={chainFocus} />
                        : dockTab === "ticket" && ticketRoll ? <div data-use="ticket.roll" className="contents"><DeskRoll key={`${ticketRoll.symbol}|${ticketRoll.expiry}|${ticketRoll.strike}|${ticketRoll.held}`} from={ticketRoll} onClose={() => setTicketRoll(null)}
                          onPlaced={symbol => { setTicketRoll(null); setPicked(symbol); setPickedKey(null); setDockPick(null); }} /></div>
                        : dockTab === "ticket" ? <DeskTicket plans={tickets.plans} failed={tickets.failed} open={ticketFor} pick={ticketPick} close={ticketClose} onOpen={id => { setTicketFor(id); setTicketPick(null); setTicketClose(null); }} onClose={() => { setTicketFor(null); setTicketPick(null); setTicketClose(null); }}
                          onPlaced={symbol => { setTicketFor(null); setTicketClose(null); setPicked(symbol); setPickedKey(null); setDockPick(null); }} onPlan={planTrade} />
                        : dockTab === "notes" ? <PositionNotes key={centreRow?.key ?? centreSymbol ?? ""} row={centreRow?.book ? centreRow : null} symbol={centreSymbol} paper={centrePaper} />
                        : position}
                    </div>
                  </div>
                )} />
            )}
          </section>
        )}
        {/* Paper mode: the centre's corner chip, on its dashed frame (from 768 px). */}
        {on && viewMode === "paper" && <span data-testid="desk-centre-paper" className={styles.paperChip}><ModeMark mode="paper" detail="fills shown" /></span>}
        {/* The right side: the copilot, and the Feed behind its tab (CopilotLab.module.css lays the two out by width). */}
        <div className={styles.side}>
        {on && (
          <div role="tablist" aria-label="Side" className={styles.sideTabs}>
            <button type="button" role="tab" aria-selected={!feedShown} onClick={showCopilot} data-use="side.copilot" title="The copilot ( / )"
              className={cn("min-h-9 shrink-0 whitespace-nowrap border-b-2 px-2.5 text-sm", !feedShown ? "border-foreground text-foreground" : "border-transparent text-muted-foreground hover:text-foreground")}>
              Copilot{talking && <span className="ml-1.5 text-xs text-muted-foreground">{talking}</span>}
            </button>
            <button type="button" role="tab" aria-selected={feedShown} onClick={showFeed} data-use="side.feed" title="Yours, ideas and the market today ( F )"
              className={cn("min-h-9 shrink-0 whitespace-nowrap border-b-2 px-2.5 text-sm", feedShown ? "border-foreground text-foreground" : "border-transparent text-muted-foreground hover:text-foreground")}>
              Feed{feedNew.count > 0 && <span data-testid="feed-new" className="ml-1.5 text-xs tabular-nums text-muted-foreground">{feedNew.count}<span className="sr-only"> new</span></span>}
            </button>
          </div>
        )}
        {on && (
          <div id="desk-feed" data-testid="desk-feed-pane" className={styles.feed}>
            <div className={styles.feedBar}>
              <span className="text-sm font-semibold">Feed</span>
              <button type="button" onClick={() => setFeedShown(false)} aria-label="Close the Feed"
                className="ml-auto inline-flex min-h-11 items-center gap-1 rounded-md border px-2.5 text-xs text-muted-foreground hover:text-foreground">
                <X size={14} aria-hidden />Desk
              </button>
            </div>
            <DeskFeed data={feed.data} failed={feed.failed} since={feedNew.since} onAsk={askFeed} onPlan={planFeed} onChart={openFeedChart} unusual={unusual} onUnusual={openUnusual}
              scanner={scanner} onScanner={openScanner} onScannerPlan={go} focus={feedLink} />
          </div>
        )}
        <section aria-label="Conversation" className={styles.thread}>
          {on && (
            <div className={styles.sheetBar}>
              <MessageCircle size={15} aria-hidden className="text-muted-foreground" />
              <span className="text-sm font-semibold">Copilot</span>
              {talking && <span className="rounded-full bg-muted px-2 py-0.5 text-xs">About {talking}</span>}
              <button type="button" onClick={() => setSheet(false)} aria-label="Back to the desk"
                className="ml-auto inline-flex min-h-11 items-center gap-1 rounded-md border px-2.5 text-xs text-muted-foreground hover:text-foreground">
                <X size={14} aria-hidden />Desk
              </button>
            </div>
          )}
          {on && thread?.mainDay && (
            <div className="mb-3 flex flex-wrap items-start justify-between gap-2 pt-2">
              <h2 className="text-base font-semibold">{mainChatLabel({ title: thread.title, main_day: thread.mainDay })}</h2><PreviousDays active={thread.id} open={actions.open} />
            </div>
          )}
          {on && !thread?.mainDay && (thread || link) && <Breadcrumb thread={thread} link={link} saved={saved} onMain={actions.home} />}
          {/* The decision when one is asked (the ladder shrinks to a line), else the full plan ladder; the conversation
              follows. A position ping's link names only the symbol when no plan conversation exists: it opens on the
              decision. A desk Radar row names the hit too: it opens on watching, passing or planning it. */}
          {on && arming && (
            <ArmChecklist onClose={() => setArming(false)} onDropped={() => setRefresh(n => n + 1)}
              ask={() => { setArming(false); fill(ARM_PROMPT); }}
              change={(plan, text) => { setArming(false); setCommand({ kind: "open", id: plan.investigationId!, text, n: ++sent.current }); showCopilot(); }} />
          )}
          {on && !arming && !closeStep && dayList && (
            <DayChecklist kind={dayKind} early={dayPhase === "pre"} prep={session.data?.prep} plans={plans} book={paper.book} bookFailed={paper.failed} toReview={dayLeft} fill={fill}
              onClose={() => setDayList(false)} onArm={() => { setArming(true); showCopilot(); }} onPrep={() => fill(PREP_PROMPT)}
              onDayRead={openDayRead} onReview={() => { setDayList(false); closeDay(); }} onTomorrow={() => fill(CLOSE_PROMPT)} />
          )}
          {on && !arming && closeStep && (
            <ClosePass key={closeStep.id} done={tally.done} total={tally.total}
              onSkip={() => pass(closeStep.id)} onEnd={() => { setAnswering(false); setClosing(false); }} body={
                <FillLinkBar tradeId={closeStep.id} titles={fills.titles} onDone={(id, how) => { fills.answer(id, how); pass(id); }} />} />
          )}
          {on && !arming && !closeStep && !dayList && (!thread && link?.symbol && link.radar ? (
            <><RadarDecision key={link.radar} eventId={link.radar} symbol={link.symbol} fill={fill} /><ThreadHitRating key={`rate-${link.radar}`} eventId={link.radar} /></>
          ) : !thread && link?.symbol && !link.investigation ? (
            <div className="mb-4 space-y-3">
              {/* Held: the header row carries the symbol and its horizon. Not held: they sit on their own line. */}
              <DeskThreadTop thread={deskSymbolThread(link.symbol)} heldOnly compact={deciding} horizon={linkRow?.horizon ?? null}
                onHorizon={horizon => changeHorizon(link.symbol, horizon)} following={followingOf(link.symbol)}
                onFollow={following => changeFollow(link.symbol!, following)} fallback={
                <p className="flex items-center gap-2 text-xs text-muted-foreground">
                  <Link href={`/charts?symbol=${encodeURIComponent(link.symbol)}`} aria-label={`Open ${link.symbol} chart`} title={`Open ${link.symbol} in Charts`}
                    className="inline-flex min-h-11 items-center gap-1 font-medium text-foreground underline-offset-2 sm:min-h-0 hover:text-primary hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary">{link.symbol}<ChartCandlestick size={13} aria-hidden className="text-muted-foreground" /></Link>
                  {linkRow?.horizon && <HorizonPick horizon={linkRow.horizon} onChange={horizon => changeHorizon(link.symbol, horizon)} />}
                </p>} />
              {fills.bar(link.symbol)}
              <DecisionBar key={link.symbol} symbol={link.symbol} {...barFor(link.symbol)} onActive={setDeciding} fill={fill} onReviewed={onReviewed} />
              <ThreadAlertAnswers symbol={link.symbol} rows={alertRows} />
            </div>
          ) : thread && !thread.mainDay ? (
            <DeskThreadTop key={fills.linked} thread={thread} compact={deciding} horizon={threadRow?.horizon ?? null} stage={threadRow?.close?.kind === "exit" ? "Exited" : null} adopted={threadRow?.adopted ?? false} onHorizon={horizon => changeHorizon(thread.symbol, horizon)}
              following={followingOf(thread.symbol)} onFollow={following => changeFollow(thread.symbol!, following)} hero={
              <>{fills.bar(thread.symbol)}<DecisionBar key={thread.symbol ?? ""} symbol={thread.symbol ?? null} {...barFor(thread.symbol)} onActive={setDeciding} fill={fill} onReviewed={onReviewed} />
                <ThreadAlertAnswers symbol={thread.symbol ?? null} rows={alertRows} /></>} />
          ) : null)}
          <CopilotPanel variant="page" link={link} desk={hooks} daily={daily} />
        </section>
        </div>
      </div>
      {/* The status line along the bottom, from 768 px (a phone has its tab bar there): the mode, whose book, how fresh
          prices are and every source behind the desk; a tap opens the Data health list. */}
      {on && !phone && <div data-use="health" className="contents"><DeskStatusLine mark={statusMark} market={marketWords(session.data)} className={styles.statusLine} /></div>}
      {/* The Data Sync Center (Data health's "Data sync" and ⌘K's): hidden until opened. */}
      {on && <DeskSyncCenter />}
      {on && <DeskJournal />}
      {on && <DeskLogs />}
      {/* The chart ticker's research (the chart's More, ⌘K's "Research NVDA"): hidden, and no reads, until opened. */}
      {on && <DeskResearch />}
      {/* A phone's tab bar is the desk's own: Positions, the ticker's Chart, Chain, Orders and Ask, then the app's More
          (Nav.tsx keeps its slot). Each counts as its view's piece (view.*). */}
      {/* Under the copilot's open sheet (which covers the bar) the desk's tabs wait hidden; More stays. */}
      {on && !replay && tabSlot && createPortal(<>
        {([["book", "Positions", Briefcase, showBook], ["ticker", centreSymbol ?? "Market", ChartCandlestick, showChart],
          ["chain", "Chain", TableProperties, showChain], ["orders", "Orders", ListChecks, showOrders]] as const).map(([id, label, Icon, run]) => {
          const active = phoneView === id;
          return (
            <button key={id} type="button" onClick={() => run()} aria-pressed={active} data-testid={`desk-view-${id}`} data-use={`view.${id}`}
              className={cn("relative flex min-h-14 min-w-0 flex-1 flex-col items-center justify-center gap-0.5 px-0.5 text-[11px] font-medium transition-colors",
                active ? "text-foreground" : "text-muted-foreground hover:text-foreground", sheet && "hidden")}>
              <Icon className={cn("h-5 w-5 shrink-0", active && "text-primary")} aria-hidden />
              <span className="max-w-full truncate">{label}</span>
              {/* Off Positions, what needs him is counted on its tab, amber. */}
              {id === "book" && !active && needs.length > 0 && <span data-testid="desk-view-needs"
                className="absolute right-[calc(50%-20px)] top-1.5 min-w-4 rounded-full bg-primary px-1 text-center text-[10px] font-semibold leading-4 tabular-nums text-primary-foreground">
                {needs.length}<span className="sr-only"> need you</span></span>}
            </button>
          );
        })}
        <button type="button" onClick={askCopilot} aria-pressed={sheet} data-testid="desk-view-ask" data-use="view.ask"
          aria-label={`Ask the copilot${picked && picked !== talking ? ` about ${picked}` : ""}`}
          className={cn("flex min-h-14 min-w-0 flex-1 flex-col items-center justify-center gap-0.5 text-[11px] font-medium text-muted-foreground transition-colors hover:text-foreground",
            sheet && "hidden")}>
          <MessageCircle className="h-5 w-5" aria-hidden />Ask
        </button>
      </>, tabSlot)}
      {/* The round button: from 768 px, where the copilot is a sheet; a phone's Ask is its tab bar's. */}
      {on && !replay && <button type="button" onClick={askCopilot} className={cn(styles.ask, "min-h-11 items-center gap-1.5 rounded-full border border-foreground/30 bg-card px-4 text-sm font-medium text-foreground shadow-lg hover:bg-secondary max-sm:size-12 max-sm:justify-center max-sm:px-0")}>
        <MessageCircle size={15} aria-hidden className="text-muted-foreground max-sm:size-5 max-sm:text-foreground" /><span className="max-sm:sr-only">Ask the copilot{picked && picked !== talking ? ` about ${picked}` : ""}</span>
      </button>}
      {on && !replay && <CommandPalette open={palette} onClose={() => setPalette(false)} threads={rows.filter(r => r.group !== "pinned")} commands={commands} research={centreSymbol ?? "QQQ"} onThread={pick} onConversation={actions.open} goTo={goTo} onAsk={askHere} />}
      </DeskUseRoot>
    </div>
  );
}
