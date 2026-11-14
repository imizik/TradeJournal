"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import dynamic from "next/dynamic";
import { ChartCandlestick, Menu, MessageCircle, MessagesSquare, PanelLeft, Plus, Search, X } from "lucide-react";
import { openNavMenu, useFoldedNav } from "@/components/Nav";
import CheckACall from "@/components/copilot/CheckACall";
import ClosePass, { closeSteps } from "@/components/copilot/ClosePass";
import CommandPalette, { KBD, useJumpKey, type PaletteCommand } from "@/components/copilot/CommandPalette";
import DeskChain, { type ChainPick } from "@/components/copilot/DeskChain";
import DeskPaper, { usePaperBook } from "@/components/copilot/DeskPaper";
import DeskOvernight from "@/components/copilot/DeskOvernight";
import DeskTicket, { TICKET_EVENT, openTicket, useTicketPlans, type TicketPick } from "@/components/copilot/DeskTicket";
import DeskRoll from "@/components/copilot/DeskRoll";
import type { RollFrom } from "@/lib/rollTicket";
import { useDeskActionHost } from "@/components/copilot/DeskActionCard";
import type { AnyClosingTicket } from "@/lib/closingTicket";
import CopilotPanel, { rememberedThread, type HomeActions, type PanelLink } from "@/components/copilot/CopilotPanel";
import DecisionBar from "@/components/copilot/DecisionBar";
import FillLinkBar, { FillsToLink, useFillLinks } from "@/components/copilot/FillLinkBar";
import RadarDecision from "@/components/copilot/RadarDecision";
import { ThreadAlertAnswers, ThreadHitRating } from "@/components/copilot/ProofAnswers";
import DayReport from "@/components/copilot/DayReport";
import WatchDayLink from "@/components/replay/WatchDayLink";
import { planContext } from "@/components/copilot/PlanATrade";
import { WEEK_REVIEW_CONTEXT } from "@/components/copilot/ReviewMyWeek";
import ArmChecklist from "@/components/copilot/ArmChecklist";
import DeskFeed, { feedQuestion, useDeskFeed, useFeedNew, type FeedItem } from "@/components/copilot/DeskFeed";
import { useDeskUnusual } from "@/components/copilot/DeskUnusual";
import { scannerGuides, useDeskScanner, type DeskScannerRow } from "@/components/copilot/DeskScanner";
import { DeskStatus, useDeskSession } from "@/components/copilot/SessionTape";
import { Book, CentreChart, DayFacts, DayPnl, NeedsStrip, SinceYouLooked, positionRows, useSparks } from "@/components/copilot/Cockpit";
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
import { WHAT_MATTERS_PROMPT, copilotLabHref, mainChatLabel, type FeedLink, type InvestigationSummary } from "@/lib/copilot";
import { useKept } from "@/components/copilot/DeskMemory";
import { afterClose, answerSymbol, deskLinkIn, deskNeeds, refreshRobinhood, type DeskLive, deskSymbolThread, nyDay, readOpened, saveFollow, saveHorizon, saveOpened, threadInUrl, toReview, type DeskCommand, type DeskPlan, type DeskThreads, type DeskHorizon, type DeskHooks, type DeskNeed, type DeskThread, type DeskThreadRef } from "@/lib/desk";
import { cn } from "@/lib/utils";
import { DeskAccounts, activeAccount, forAccount } from "@/components/copilot/DeskAccounts";
import DeskHealthDot from "@/components/copilot/DeskHealth";
import styles from "./CopilotLab.module.css";

// The Grid's code loads the first time its tab opens.
const DeskGrid = dynamic(() => import("@/components/copilot/DeskGrid"), { ssr: false });

/** The close pass in progress (its New York day), kept for this tab: a thread with no conversation opens by its link. */
const CLOSING_KEY = "desk.closing.v1";
const CENTRE_KEY = "desk.centre.v1";
/** "Plan a trade" with nothing known: the owner names the ticker. The thread list's own button makes the same link. */
const PLAN_HREF = copilotLabHref("", planContext(), { kind: "copilot", ref: null });
const PREP_PROMPT = "Prep the day: what is armed, what news or earnings touch my positions and watches, and what would change a plan before the open?";
const ARM_PROMPT = "Arm today's plans: for each plan I mean to trade today, check its entry, invalidation and time stop against the pre-market, and propose any alert or time stop still missing for me to confirm.";
const CLOSE_PROMPT = "Close the day: for each position and plan today, did I follow the plan, and what is the one thing to repeat or change tomorrow?";

/** Below 1180 px the copilot is a sheet (CopilotLab.module.css); below 768 px the thread list covers the screen. */
const sheetLayout = () => typeof window !== "undefined" && window.matchMedia("(max-width: 1179px)").matches;
const narrow = () => typeof window !== "undefined" && window.matchMedia("(max-width: 767px)").matches;

type CentreTab = "chart" | "chain" | "ticket" | "check" | "grid";
/** The centre's tabs: the selected ticker's tools in the order he works (see it, pick a contract, build the ticket),
 * then Check a call and the Grid of many tickers. ``key`` is the tab's desk key. */
const CENTRE_TABS: readonly { id: CentreTab; label: string; key: string; hint: string }[] = [
  { id: "chart", label: "Chart", key: "C", hint: "The selected ticker's chart" },
  { id: "chain", label: "Chain", key: "O", hint: "The selected ticker's option chain" },
  { id: "ticket", label: "Ticket", key: "T", hint: "A plan's ticket to copy. Nothing is sent." },
  { id: "check", label: "Check a call", key: "L", hint: "Paste a call and check it" },
  { id: "grid", label: "Grid", key: "G", hint: "Your positions and watched names, several charts at once" },
];
/** A phone's three views (CopilotLab.module.css): one shows at a time under the switch. */
type DeskView = "book" | "ticker" | "feed";
/** A phone's view changed: the page goes to where that view starts. */
function toView(view: DeskView) {
  requestAnimationFrame(() => {
    // The Book starts at the page's top (the clock and the day's P&L above it); the ticker and the Feed start right under
    // the switch, which stays at the top of the screen.
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
 * The Copilot desk, a cockpit (docs/copilot-lab.md § The desk): the top bar (market phase and clock, SPY / QQQ / VIX,
 * the day's P&L), the Needs-you strip (the one most urgent item), then three columns: the book of followed positions
 * with the time of day's block under it (the morning brief, Since you looked, or the day report), the centre (the
 * selected symbol's Chart and tools), and the side: the copilot (today's Main chat or the open thread, its decision,
 * close pass or checklist on top) with the Feed of what the app knows today behind its tab. Selecting a position drives
 * the centre and the copilot. Below 1180 px the copilot is a sheet opened by "Ask the copilot" and by any Ask action
 * and the Feed a drawer; a phone shows one view at a time (Book, the ticker, Feed). The thread list is a drawer. While
 * the lab is off only the conversation shows, saying so. ⌘K (Ctrl+K) or Jump to… opens the palette; while not typing,
 * J / K open the next or previous thread, N starts a plan, [ toggles the thread list, a place's key opens it and Escape
 * closes the drawer or the sheet.
 *
 * The page remounts the desk for each deep link it loads; a symbol or context link the desk opens itself (a position
 * picked in the book, a feed item's Ask, Plan a trade) is followed in place (``go``): the address changes with the
 * History API and the copilot starts that conversation, so the book, the top bar, the strip and the centre stay mounted.
 *
 * Where things live (the 2026-11-13 layout pass): what needs him and his positions keep the top and the left; the centre
 * is the selected ticker's tools only (Chart, Chain, Ticket, then Check a call and the Grid); the right is the copilot
 * with the Feed behind its tab, so the chart stays while he reads ideas. A phone shows one of three views under a
 * switch (Book, the ticker, Feed) and the copilot as its sheet. Every place has a key (C O T L G, F, B, /) and a ⌘K
 * command.
 */
export default function CopilotLab({ link: linkProp = null, close = false, daily: dailyProp = false, feed: feedLink = null }: {
  link?: PanelLink | null; close?: boolean; daily?: boolean;
  /** A Radar or scanner ping's card (?feed=): the desk opens with the Feed forward on it. */
  feed?: FeedLink | null;
}) {
  const on = useCopilotOn();
  const router = useRouter();
  // The desk link on show: the one the page loaded, then each one followed in place. Followed, it is no longer Now.
  const [view, setView] = useState<{ link: PanelLink | null; daily: boolean }>({ link: linkProp, daily: dailyProp });
  const { link, daily } = view;
  const navFolded = useFoldedNav();
  const session = useDeskSession(on);
  // Below 1180 px the copilot is a sheet: a deep link or a saved thread opens on it, Now on the cockpit.
  const [sheet, setSheet] = useState(!daily && !feedLink);
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
  const readRows = useCallback((next: DeskThread[], feed?: DeskLive, read?: { plans: DeskPlan[]; sections: DeskThreads["sections"] }) => {
    setRows(next); setLive(feed ?? null); setRowsRead(true); setRowsFresh(true); keepRows({ rows: next, live: feed ?? null });
    if (read) { setPlans(read.plans); setSections(read.sections); }
  }, [keepRows]);
  const [saved, setSaved] = useState<InvestigationSummary[]>([]);
  const [palette, setPalette] = useState(false);
  const [threadsShown, setThreadsShown] = useState(false);
  const toggleThreads = useCallback(() => setThreadsShown(shown => !shown), []);
  // The centre: the symbol the owner picked in the book (else the copilot's, else the first followed position), on Chart
  // or the Feed.
  const [picked, setPicked] = useState<string | null>(null);
  const [pickedKey, setPickedKey] = useState<string | null>(null);
  const [centreTab, setCentreTab] = useState<CentreTab>("chart");
  // The tab survives a link that reopens the desk (a checked call's Plan it) for this browser tab.
  // A ping's card (?feed=) opens on the chart.
  useEffect(() => { if (feedLink) return; try { const kept = window.sessionStorage.getItem(CENTRE_KEY); if (kept === "check" || kept === "chain" || kept === "grid") setCentreTab(kept); } catch { /* chart */ } }, [feedLink]); // eslint-disable-line react-hooks/set-state-in-effect -- the store is read after hydration
  // The Feed sits beside the copilot, never over the chart: from 1180 px it takes the copilot's column while shown (the
  // Copilot | Feed tabs), from 768 px it is a drawer on the right, and a phone shows it as one of its three views.
  const [feedShown, setFeedShown] = useState(!!feedLink);
  const feedKept = useRef(false);
  useEffect(() => { feedKept.current = feedShown; }, [feedShown]);
  // A phone shows one view at a time (the switch in its top row): the book, the selected ticker's tools, or the Feed. It
  // opens on the Book; a link that names a ticker (a ping's) opens on that ticker's view, under the copilot's sheet.
  // A ping's ?feed= opens on the Feed (its view on a phone; the drawer or the side's Feed tab wider).
  const [phoneView, setPhoneView] = useState<DeskView>(feedLink ? "feed" : linkProp?.symbol ? "ticker" : "book");
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
  useEffect(() => { try { window.sessionStorage.setItem(CENTRE_KEY, centreTab); } catch { /* this view only */ } }, [centreTab]);
  // On a phone the tab strip scrolls: keep the chosen tab in it (a link can choose Ticket), never moving the page.
  useEffect(() => {
    const strip = document.querySelector<HTMLElement>('[role="tablist"][aria-label="Centre"]');
    const tab = strip?.querySelector<HTMLElement>('[aria-selected="true"]');
    if (!strip || !tab || strip.scrollWidth <= strip.clientWidth) return;
    const box = strip.getBoundingClientRect(), at = tab.getBoundingClientRect();
    if (at.left < box.left) strip.scrollLeft -= box.left - at.left + 8;
    else if (at.right > box.right) strip.scrollLeft += at.right - box.right + 8;
  }, [centreTab]);
  // The Ticket tab: a saved plan's ticket opens from its card, its thread's header, a book row or the tab's own list
  // (``openTicket``), or from a link (?ticket=) made where the desk was not open.
  const tickets = useTicketPlans(on);
  const paper = usePaperBook(on);
  const [ticketFor, setTicketFor] = useState<string | null>(null);
  const [ticketPick, setTicketPick] = useState<TicketPick | null>(null); // the Chain tab's Put on ticket
  const [ticketClose, setTicketClose] = useState<AnyClosingTicket | null>(null); // a held option's Close at target / stop, or a copilot close card
  const [ticketRoll, setTicketRoll] = useState<RollFrom | null>(null); // a held option's Roll
  const [checkSeed, setCheckSeed] = useState<{ text: string; n: number } | null>(null); // the Chain tab's Check it
  useEffect(() => { if (centreTab !== "check") setCheckSeed(null); }, [centreTab]); // eslint-disable-line react-hooks/set-state-in-effect -- the Chain's contract fills Check a call once, not on every later visit
  const ticketLinked = useRef(false); // a ?ticket= link on a phone: the Ticket comes into view once the book above it has read
  useEffect(() => {
    const show = (id: string | null, pick: TicketPick | null = null, close: AnyClosingTicket | null = null, roll: RollFrom | null = null) => { setTicketFor(id); setTicketPick(pick); setTicketClose(close); setTicketRoll(roll); setCentreTab("ticket"); showCentre(); };
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
  const unusual = useDeskUnusual(on);
  const scanner = useDeskScanner(on);
  const [scanLines, setScanLines] = useState<{ symbol: string; lines: DeskGuide[] } | null>(null); // a Scanner row's levels on the chart
  const [chainFocus, setChainFocus] = useState<{ pick: ChainPick; n: number } | null>(null); // a Feed row's unusual contract
  useEffect(() => { if (centreTab !== "chain") setChainFocus(null); }, [centreTab]); // eslint-disable-line react-hooks/set-state-in-effect -- the pick opens the Chain once, not on every later visit
  // The tickers opened today in this browser: opening one clears its strip items (``deskNeeds``); nothing is dismissed.
  const [opened, setOpened] = useState<Record<string, number>>({});
  useEffect(() => { setOpened(readOpened(nyDay())); }, []); // eslint-disable-line react-hooks/set-state-in-effect -- the store is read after hydration
  const jumpKey = useJumpKey();
  const desk = useRef<HTMLDivElement>(null);
  const [deciding, setDeciding] = useState(false);
  const sent = useRef(0);
  const [answering, setAnswering] = useState(false); // the close pass's fills to link, in the conversation pane
  const [arming, setArming] = useState(false); // Arm today's plans' checklist, in the conversation pane
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
  }, []);
  const actions = useMemo<HomeActions>(() => ({
    open: id => { setCommand({ kind: "open", id, n: ++sent.current }); showCopilot(); if (narrow()) setThreadsShown(false); },
    ask: text => { setCommand({ kind: "ask", text, n: ++sent.current }); showCopilot(); },
    // Back to Now from any thread or deep link, without carrying its conversation into the new view.
    home: () => goNow(true),
  }), [goNow, showCopilot]);
  const fill = useCallback((text: string) => { setCommand({ kind: "fill", text, n: ++sent.current }); showCopilot(); }, [showCopilot]);
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
  const shownLink = useRef(link);
  useEffect(() => { shownLink.current = link; }, [link]);
  useEffect(() => {
    const next = deskLinkIn(`/copilot-lab?${params.toString()}`);
    if (next && JSON.stringify(next) !== JSON.stringify(shownLink.current)) followLink(next); // the address moved
    else if (!params.size && !toNow.current) goNow(false);
  }, [params, followLink, goNow]);
  // Plan a trade (the desk bar's New plan, N and ⌘K): a new conversation with "Plan a trade: " in the box, unsent.
  const planTrade = useCallback(() => go(PLAN_HREF), [go]);
  const [refresh, setRefresh] = useState(0);
  // The copilot's desk action cards: a view card moves the centre (Undo puts it back); a tap that changed a list reads again.
  useDeskActionHost({ picked, tab: centreTab, rows, go, setPicked, setPickedKey, setTab: setCentreTab, setRefresh, setSheet, showCentre });
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
    if (was !== null) { setArming(false); setAnswering(false); }
  }, [thread?.id]);
  // A centre tab by its key or the palette: the tab, and on a phone the ticker's view with it.
  const openCentre = useCallback((tab: CentreTab) => { setCentreTab(tab); showCentre(); }, [showCentre]);
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
  const commands = useMemo<PaletteCommand[]>(() => [
    { id: "plan", name: "Plan a trade", hint: "A new plan; you name the symbol. Nothing is sent.", key: "N", run: planTrade },
    { id: "week", name: "Review my week", hint: "One turn: planned vs unplanned, follow-through, exits", run: () => actions.ask(WEEK_REVIEW_CONTEXT) },
    { id: "matters", name: "What matters right now?", hint: "One turn across your positions, watches and investigations", run: () => actions.ask(WHAT_MATTERS_PROMPT) },
    ...(dayPhase === "pre" ? [
      { id: "arm", name: "Arm today's plans", hint: "Each armed plan: still good, change or drop. Nothing is sent.", run: () => { setArming(true); showCopilot(); } },
      { id: "prep", name: "Prep the day", hint: "Puts a prep question in the box, unsent", run: () => fill(PREP_PROMPT) }] : []),
    ...(dayPhase === "close" ? [{ id: "close", name: "Close the day", hint: "Each close question and fill to link, one at a time. Nothing is sent.", run: closeDay }] : []),
    // Every place on the desk, each with its key: the ticker's tools, the Feed, the copilot's message box, the thread list.
    ...CENTRE_TABS.map(tab => ({ id: `go-${tab.id}`, name: tab.label, hint: tab.hint, key: tab.key, run: () => openCentre(tab.id) })),
    { id: "go-feed", name: "Feed", hint: "Yours, ideas and the market today", key: "F", run: showFeed },
    { id: "go-copilot", name: "Copilot", hint: "The conversation and its message box", key: "/", run: focusCopilot },
    { id: "go-book", name: "Book", hint: "Your positions and what needs you", key: "B", run: focusBook },
    { id: "go-threads", name: "Threads", hint: "The thread list and previous days", key: "[", run: toggleThreads },
  ], [actions, dayPhase, fill, planTrade, closeDay, openCentre, showFeed, focusCopilot, focusBook, toggleThreads, showCopilot]);

  // J / K walk the conversations the thread list shows, subthreads included, in its order.
  const [walk, setWalk] = useState<string[]>([]);
  const step = useCallback((by: 1 | -1) => {
    if (!walk.length) return;
    const at = walk.indexOf(thread?.id ?? "");
    const next = at < 0 ? (by > 0 ? 0 : walk.length - 1) : (at + by + walk.length) % walk.length;
    actions.open(walk[next]);
  }, [walk, thread?.id, actions]);

  useEffect(() => {
    if (!on) return;
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
      if (event.metaKey || event.ctrlKey || event.altKey || event.shiftKey) return;
      if (key === "j" || key === "k") { event.preventDefault(); step(key === "j" ? 1 : -1); }
      else if (event.key === "[") { event.preventDefault(); toggleThreads(); }
      else if (key === "n" && !event.repeat) {
        // A new plan leaves this conversation: never over words not yet sent.
        const box = desk.current?.querySelector<HTMLTextAreaElement>("textarea[aria-label='Message']");
        if (box?.value.trim()) return;
        event.preventDefault();
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
        if (tab) { event.preventDefault(); openCentre(tab.id); }
        else if (key === "f") { event.preventDefault(); if (feedKept.current) showCopilot(); else showFeed(); }
        else if (key === "b") { event.preventDefault(); focusBook(); }
        else if (event.key === "/") { event.preventDefault(); focusCopilot(); }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [on, step, planTrade, toggleThreads, openCentre, showFeed, focusBook, showCopilot, focusCopilot]);

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
  const centreRow = centreSymbol ? followed.find(r => r.symbol === centreSymbol) ?? rows.find(r => r.symbol === centreSymbol && r.key.startsWith("trade:")) ?? null : null;
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
    setCentreTab("chart");
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
    setCentreTab("chart");
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
  const askWatched = useCallback((symbol: string) => { setPicked(symbol); setPickedKey(null); if (symbol !== talking) openWatched(symbol); showCopilot(); }, [openWatched, talking, showCopilot]);
  const planWatched = useCallback((symbol: string) => go(copilotLabHref(symbol, planContext(), { kind: "copilot", ref: null })), [go]);
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
  const chainCheck = useCallback((text: string) => { setCheckSeed(seed => ({ text, n: (seed?.n ?? 0) + 1 })); setCentreTab("check"); showCentre(); }, [showCentre]);
  const chainPlan = useCallback((pick: ChainPick, line: string) => go(copilotLabHref(pick.symbol, planContext(line), { kind: "copilot", ref: null })), [go]);
  const chainTicket = useCallback((id: string, pick: ChainPick) => openTicket(id, { expiry: pick.expiry, strike: pick.strike,
    ...(pick.short != null ? { short: pick.short, kind: pick.side } : {}) }), []);
  // An Unusual options row: its contract selected in the Chain tab, in place.
  const openUnusual = useCallback((pick: ChainPick) => { setPicked(pick.symbol); setPickedKey(null); setChainFocus(f => ({ pick, n: (f?.n ?? 0) + 1 })); setCentreTab("chain"); showCentre(); }, [showCentre]);
  // A TradingView alert row: its ticker on the desk chart, in place, where the alert's marker sits.
  const openFeedChart = useCallback((symbol: string) => { setPicked(symbol); setPickedKey(null); setCentreTab("chart"); showCentre(); }, [showCentre]);
  // A Scanner row: its ticker on the desk chart, in place, with the scanner's levels as thin lines.
  const openScanner = useCallback((row: DeskScannerRow) => { setPicked(row.symbol); setPickedKey(null); setScanLines({ symbol: row.symbol, lines: scannerGuides(row) }); setCentreTab("chart"); showCentre(); }, [showCentre]);
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

  // The book's lower block by the time of day, one block each: the morning brief before the open (nothing until it is
  // written), the day report after the close, else what changed since the owner last looked. Arm today's plans and Close
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

  return (
    <div ref={desk} className={styles.desk} data-on={on} data-sheet={sheet ? "open" : "closed"} data-threads={threadsShown ? "shown" : "hidden"}
      data-view={phoneView} data-feed={feedShown ? "shown" : "hidden"}>
      {/* The desk's head: the top bar and, at its right, the desk's buttons. On a phone the buttons' row comes first, stays at
          the top of the screen, and starts with the switch between the desk's three views (CopilotLab.module.css). */}
      <div className={styles.head}>
      {on && (
        <div className={styles.topRow}>
          {/* A phone's switch: one view at a time, the middle one named for the selected ticker. Wider screens show all at once. */}
          <nav id="desk-views" aria-label="Desk views" data-testid="desk-views" className={styles.views}>
            {([["book", "Book"], ["ticker", centreSymbol ?? "Market"], ["feed", "Feed"]] as const).map(([id, label]) => (
              <button key={id} type="button" aria-pressed={phoneView === id} data-testid={`desk-view-${id}`}
                onClick={() => id === "book" ? showBook() : id === "ticker" ? showCentre() : showFeed()}
                className={cn("min-h-11 min-w-0 flex-1 truncate rounded-md px-1 text-sm", phoneView === id ? "bg-secondary font-semibold text-foreground" : "text-muted-foreground")}>
                {label}
                {id === "book" && phoneView !== "book" && needs.length > 0 && <span data-testid="desk-view-needs" className="ml-1.5 text-xs font-semibold tabular-nums text-primary">{needs.length}<span className="sr-only"> need you</span></span>}
                {id === "feed" && feedNew.count > 0 && <span data-testid="feed-new-phone" className="ml-1.5 text-xs tabular-nums text-muted-foreground">{feedNew.count}<span className="sr-only"> new</span></span>}
              </button>
            ))}
          </nav>
          <div className={styles.barActions}>
            {/* Is every source behind the desk live: one dot, a list on a tap. */}
            <DeskHealthDot />
            {/* The desk's front door: today's Main chat in the copilot. */}
            <Link href="/copilot-lab" aria-current={onNow ? "page" : undefined} title="Back to today: Main chat in the copilot"
              onClick={event => { if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return; event.preventDefault(); setFeedShown(false); if (!onNow) goNow(true); }}
              className={cn("inline-flex min-h-11 items-center whitespace-nowrap rounded-md border px-2.5 text-xs sm:min-h-8",
                onNow ? "bg-secondary font-medium text-foreground max-md:hidden" : "text-muted-foreground hover:text-foreground")}>Now</Link>
            {/* Between 768 and 1180 px the Feed is a drawer on the right: this opens it (wider, it is the tab beside the copilot; a phone has its view). */}
            <button type="button" onClick={() => feedShown ? setFeedShown(false) : showFeed()} aria-pressed={feedShown} title="Yours, ideas and the market today ( F )"
              className={cn(styles.feedButton, "min-h-11 items-center gap-1.5 rounded-md border px-2.5 text-xs text-muted-foreground hover:text-foreground sm:min-h-8", feedShown && "bg-secondary")}>
              Feed{feedNew.count > 0 && <span data-testid="feed-new-bar" className="tabular-nums">{feedNew.count}<span className="sr-only"> new</span></span>}
            </button>
            {/* No count here: what needs him is the strip's, counted once there. */}
            <button type="button" onClick={toggleThreads} aria-pressed={threadsShown} aria-label="Threads" title="The thread list and previous days ( [ )"
              className={cn("inline-flex min-h-11 min-w-11 items-center justify-center gap-1.5 rounded-md border px-2 text-xs text-muted-foreground hover:text-foreground sm:min-h-8", threadsShown && "bg-secondary")}>
              <PanelLeft size={15} aria-hidden /><span className="hidden sm:inline">Threads</span>
            </button>
            <button type="button" onClick={() => setPalette(true)} aria-label="Jump to a thread or command" aria-haspopup="dialog"
              className="inline-flex min-h-11 min-w-11 items-center justify-center gap-2 rounded-md border bg-card px-2.5 text-xs text-muted-foreground hover:text-foreground sm:min-h-8">
              {/* A phone keeps the bar short: icons only, as the button's label already says. */}
              <Search size={14} aria-hidden /><span className="hidden sm:inline">Jump to…</span><kbd className={cn(KBD, "hidden md:inline")}>{jumpKey}</kbd>
            </button>
            <button type="button" onClick={planTrade} title="A new plan; you name the symbol. Nothing is sent. ( N )"
              className="inline-flex min-h-11 min-w-11 items-center justify-center gap-1.5 rounded-md border px-2.5 text-xs text-muted-foreground hover:bg-secondary hover:text-foreground sm:min-h-8">
              <Plus size={14} aria-hidden /><span className="sr-only sm:not-sr-only">Plan a trade</span>
            </button>
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
        {on && <DeskStatus data={session.data} />}
        {on && <DayPnl session={session.data} rows={rows} read={rowsFresh} />}
        {on && <DeskAccounts live={rowsFresh ? live : null} rows={rows} active={account} onPick={setAccount} />}
        {on && <ScalpShortlistNudge />}
      </header>
      </div>
      <div id="desk-cockpit" className={styles.cockpit}>
        {on && (
          <div className={styles.strip}>
            {/* A phone shows the strip on its Book view; on the other two the Book's button carries the amber count. */}
            {needs.length > 0 && <div className={styles.needs}><NeedsStrip needs={needs} actions={needActions} /></div>}
            {unchecked && <p data-testid="needs-you-unchecked" className="px-1 pt-1 text-xs text-muted-foreground">Needs you could not check {unchecked} just now; it will read again in a minute.</p>}
            {/* What's moving: one thin row across the book and the centre, folded until opened; a tile selects its symbol in
                place, as a watched name does. A phone puts it under the book. */}
            <div className={styles.moving}><MovingStrip on={on} selected={centreSymbol} onSelect={selectWatched} /></div>
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
            <Book rows={booked.rows} sparks={sparks} earnings={events} selected={centreSymbol} selectedKey={pickedKey} day={today} read={rowsRead} updating={rowsRead && !rowsFresh} onSelect={select} onFollow={changeFollow}
              live={booked.live} onRefreshLive={() => { refreshRobinhood().catch(() => { /* the line says so on the next read */ }).finally(() => setRefresh(n => n + 1)); }} />
            {/* His own paper book: paper positions, Close and Trim, and the scorecard beside his real trades. Never real money. */}
            <DeskPaper book={paper.book} failed={paper.failed} symbol={centreSymbol} />
            {/* The QQQ overnight paper book: the one rule that passed its registered test, recorded live. Hidden until switched on. */}
            <DeskOvernight on={on} />
            {/* Before the open and after the close the day's block (the brief, the day report) comes straight after the
                book; in the session it waits under Watching. */}
            {dayPhase !== null && lower}
            <Watching data={rowsRead ? watching.data : null} failed={watching.failed} sparks={sparks} earnings={events} held={held} selected={centreSymbol}
              onSelect={selectWatched} onAsk={askWatched} onPlan={planWatched} onChange={watching.set} />
            {dayPhase === null && lower}
            <DayFacts session={session.data} />
          </div>
        )}
        {on && (
          <section id="desk-centre" aria-label="Chart and tools" className={styles.centre}>
            {/* The selected ticker's tools in the order he works: Chart, Chain, Ticket; then Check a call and, set apart, the
                Grid of many tickers. The Feed is not here: it sits beside the copilot, so the chart stays while he reads it. */}
            {/* The strip's bottom line is an inset shadow, so a tab's underline paints over it without spilling past the scroll box. */}
            <div role="tablist" aria-label="Centre" className="flex gap-0.5 overflow-x-auto px-1.5 pt-1.5 shadow-[inset_0_-1px_0_hsl(var(--border))] [scrollbar-width:none] sm:gap-1 sm:px-2">
              {CENTRE_TABS.map(({ id, label, key }) => (
                <button key={id} type="button" role="tab" aria-selected={centreTab === id} onClick={() => setCentreTab(id)} title={`${label} ( ${key} )`}
                  className={cn("min-h-11 shrink-0 whitespace-nowrap border-b-2 px-2 text-sm sm:min-h-9 sm:px-2.5", id === "grid" && "ml-auto",
                    centreTab === id ? "border-foreground text-foreground" : "border-transparent text-muted-foreground hover:text-foreground")}>
                  {label}
                </button>
              ))}
            </div>
            <div role="tabpanel" aria-label={CENTRE_TABS.find(t => t.id === centreTab)!.label} className="p-3">
              {centreTab === "check" ? <CheckACall seed={checkSeed} />
                : centreTab === "grid" ? <DeskGrid held={gridHeld} watched={watched} hidden={gridHidden} sparks={sparks} earnings={events} selected={centreSymbol} onOpen={openFromGrid} />
                : centreTab === "chain" ? <DeskChain symbol={centreSymbol} plans={tickets.plans} onCheck={chainCheck} onPlan={chainPlan} onTicket={chainTicket} unusual={unusual?.rows} focus={chainFocus} />
                : centreTab === "ticket" && ticketRoll ? <DeskRoll key={`${ticketRoll.symbol}|${ticketRoll.expiry}|${ticketRoll.strike}|${ticketRoll.held}`} from={ticketRoll} onClose={() => setTicketRoll(null)}
                  onPlaced={symbol => { setTicketRoll(null); setPicked(symbol); setPickedKey(null); setCentreTab("chart"); }} />
                : centreTab === "ticket" ? <DeskTicket plans={tickets.plans} failed={tickets.failed} open={ticketFor} pick={ticketPick} close={ticketClose} onOpen={id => { setTicketFor(id); setTicketPick(null); setTicketClose(null); }} onClose={() => { setTicketFor(null); setTicketPick(null); setTicketClose(null); }}
                onPlaced={symbol => { setTicketFor(null); setTicketClose(null); setPicked(symbol); setPickedKey(null); setCentreTab("chart"); }} onPlan={planTrade} />
                : <CentreChart symbol={centreSymbol} thread={centreThread} row={centreRow} sparks={sparks} actions={chartActions} rows={rows} earnings={events}
                  guides={scanLines && scanLines.symbol === centreSymbol ? scanLines.lines : undefined} />}
            </div>
          </section>
        )}
        {/* The right side: the copilot, and the Feed behind its tab (CopilotLab.module.css lays the two out by width). */}
        <div className={styles.side}>
        {on && (
          <div role="tablist" aria-label="Side" className={styles.sideTabs}>
            <button type="button" role="tab" aria-selected={!feedShown} onClick={showCopilot} title="The copilot ( / )"
              className={cn("min-h-9 shrink-0 whitespace-nowrap border-b-2 px-2.5 text-sm", !feedShown ? "border-foreground text-foreground" : "border-transparent text-muted-foreground hover:text-foreground")}>
              Copilot{talking && <span className="ml-1.5 text-xs text-muted-foreground">{talking}</span>}
            </button>
            <button type="button" role="tab" aria-selected={feedShown} onClick={showFeed} title="Yours, ideas and the market today ( F )"
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
          {on && !arming && closeStep && (
            <ClosePass key={closeStep.id} done={tally.done} total={tally.total}
              onSkip={() => pass(closeStep.id)} onEnd={() => { setAnswering(false); setClosing(false); }} body={
                <FillLinkBar tradeId={closeStep.id} titles={fills.titles} onDone={(id, how) => { fills.answer(id, how); pass(id); }} />} />
          )}
          {on && !arming && !closeStep && (!thread && link?.symbol && link.radar ? (
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
      {/* A phone shows only the round button, so it never sits over a book row's P&L; its name is the same. */}
      {on && <button type="button" onClick={askCopilot} className={cn(styles.ask, "min-h-11 items-center gap-1.5 rounded-full border border-foreground/30 bg-card px-4 text-sm font-medium text-foreground shadow-lg hover:bg-secondary max-sm:size-12 max-sm:justify-center max-sm:px-0")}>
        <MessageCircle size={15} aria-hidden className="text-muted-foreground max-sm:size-5 max-sm:text-foreground" /><span className="max-sm:sr-only">Ask the copilot{picked && picked !== talking ? ` about ${picked}` : ""}</span>
      </button>}
      {on && <CommandPalette open={palette} onClose={() => setPalette(false)} threads={rows.filter(r => r.group !== "pinned")} commands={commands} onThread={pick} onConversation={actions.open} />}
    </div>
  );
}
