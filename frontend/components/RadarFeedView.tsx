"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  MEASURE_LABELS, RATINGS, RULE_TAGS, STATUS_TEXT, coverageLine, getEvent, getFeed, headlineMeta, measureText, newsLine, nyTime, rateEvent,
  recordVisit, radarEventChartHref, radarEventId, radarRating, radarSession, type RadarDetail, type RadarFeed, type RadarFeedEvent, type RadarNews, type RadarRating,
} from "@/lib/radar";
import AskCopilot from "@/components/copilot/AskCopilot";
import PlanATrade from "@/components/copilot/PlanATrade";
import RadarMovers from "@/components/RadarMovers";
import { cn } from "@/lib/utils";

const NEVER_VISITED = "1970-01-01T00:00:00Z";
const STATE_TONE = { off: "text-muted-foreground", no_data: "text-muted-foreground", recording: "text-emerald-300", stale: "text-amber-300" } as const;
const DIRECTION = {
  up: { label: "Up", className: "bg-emerald-500/10 text-emerald-300" },
  down: { label: "Down", className: "bg-rose-500/10 text-rose-300" },
};
const KIND = { relative_to_spy: "vs SPY", relative_to_sector: "vs sector", group_move: "Group move", dip_turn: "Dip turning up" };

function Evidence({ rows }: { rows: RadarDetail["event"]["evidence"] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead className="text-muted-foreground">
          <tr><th className="pb-1 text-left font-medium">Symbol</th><th className="pb-1 text-right font-medium">Last</th>
            <th className="pb-1 text-right font-medium">Change</th><th className="pb-1 text-right font-medium">Quote time</th></tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={`${row.symbol}-${row.pass_id}-${i}`} className="border-t">
              <td className="py-1 font-medium text-foreground">{row.symbol}</td>
              <td className="py-1 text-right tabular-nums">{row.last.toFixed(2)}</td>
              <td className="py-1 text-right tabular-nums">{measureText("change_pct", row.change_pct)}</td>
              <td className="py-1 text-right tabular-nums text-muted-foreground">{nyTime(row.retrieved_at, true)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Measures({ values }: { values: Record<string, number> }) {
  return (
    <dl className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
      {Object.entries(values).map(([key, value]) => (
        <div key={key} className="flex gap-1.5">
          <dt className="text-muted-foreground">{MEASURE_LABELS[key] ?? key}</dt>
          <dd className="font-medium tabular-nums text-foreground">{measureText(key, value)}</dd>
        </div>
      ))}
    </dl>
  );
}

const CHECK_TEXT: Record<RadarNews["status"], string> = {
  found: "headlines found", none_found: "no news found — cause unknown", unavailable: "news unavailable — cause unknown",
};

function News({ news, checks, sessionDate }: { news: RadarNews | null; checks: RadarNews[]; sessionDate: string }) {
  return (
    <section aria-label="News nearby" className="space-y-1.5">
      <h3 className="text-xs font-semibold text-foreground">News nearby</h3>
      {!news && <p className="text-xs text-muted-foreground">News not checked yet.</p>}
      {news && news.status !== "found" && <p className="text-xs text-muted-foreground">{newsLine(news, sessionDate)}.</p>}
      {news && news.headlines.length > 0 && (
        <ul className="space-y-1.5">
          {news.headlines.map((h) => (
            <li key={h.url} className="min-w-0 text-xs">
              <a href={h.url} target="_blank" rel="noopener noreferrer" className="break-words text-foreground underline decoration-muted-foreground/40 underline-offset-2 hover:decoration-foreground">{h.headline}</a>
              <span className="block text-muted-foreground">{headlineMeta(h, sessionDate)}</span>
            </li>
          ))}
        </ul>
      )}
      {checks.length > 0 && (
        <p className="text-xs text-muted-foreground">
          Checked {checks.map((c) => `${nyTime(c.checked_at)} (${CHECK_TEXT[c.status]})`).join(" · ")}. Headlines published near the move; not shown to be its cause.
        </p>
      )}
    </section>
  );
}

function Detail({ event, onRated }: { event: RadarFeedEvent; onRated: (rating: RadarRating) => void }) {
  const [detail, setDetail] = useState<RadarDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [rating, setRating] = useState<RadarRating | null>(event.rating);
  useEffect(() => {
    let live = true;
    getEvent(event.event_id).then((d) => { if (live) { setDetail(d); setRating(d.rating); } }, () => { if (live) setError("The saved event could not load."); });
    return () => { live = false; };
  }, [event.event_id]);
  async function rate(value: RadarRating) {
    setError(null);
    try { await rateEvent(event.event_id, value); setRating(value); onRated(value); }
    catch { setError("That rating was not saved."); }
  }
  if (!detail) return <p className="text-xs text-muted-foreground" role={error ? "alert" : "status"}>{error ?? "Loading the saved event…"}</p>;
  const symbol = detail.event.chart?.symbol ?? detail.event.symbols[0];
  return (
    <div className="space-y-3">
      <section aria-label="Original evidence" className="space-y-1.5">
        <h3 className="text-xs font-semibold text-foreground">As first saved · {nyTime(detail.event.first_seen_at, true)}</h3>
        <Measures values={detail.event.measures} />
        <Evidence rows={detail.event.evidence} />
        <p className="text-xs text-muted-foreground">
          Recording then: {detail.event.coverage.passes_recorded} of {detail.event.coverage.passes_expected} passes
          {detail.event.coverage.symbols_missing.length ? ` · missing ${detail.event.coverage.symbols_missing.join(", ")}` : ""}
          {" "}· {detail.event.rule_version}{RULE_TAGS[detail.event.rule_version] ? ` (${RULE_TAGS[detail.event.rule_version]})` : ""}
          {" "}· {detail.event.universe_version}
        </p>
      </section>
      <News news={detail.news} checks={detail.news_checks} sessionDate={detail.event.session_date} />
      <section aria-label="Revisions" className="space-y-2">
        <h3 className="text-xs font-semibold text-foreground">Later readings</h3>
        {detail.revisions.length === 0 && <p className="text-xs text-muted-foreground">No later readings yet.</p>}
        {detail.revisions.map((r) => (
          <div key={r.revision} className="space-y-1.5 rounded-md border bg-secondary/30 p-2">
            <p className="text-xs"><span className="font-medium text-foreground">{STATUS_TEXT[r.status]}</span>
              <span className="text-muted-foreground"> · {nyTime(r.recorded_at, true)}</span></p>
            {r.note && <p className="text-xs text-muted-foreground">{r.note}</p>}
            <Measures values={r.measures} />
            <Evidence rows={r.evidence} />
          </div>
        ))}
      </section>
      <div className="flex flex-wrap items-center gap-2">
        {detail.plans?.planned && <span aria-label="Plan marks" className="flex gap-1 text-[11px] font-medium">
          <span className="rounded bg-sky-500/15 px-1.5 py-0.5 text-sky-300">Planned</span>
          {detail.plans.traded && <span className="rounded bg-emerald-500/15 px-1.5 py-0.5 text-emerald-300">Traded</span>}</span>}
        <PlanATrade symbol={symbol} origin="radar_event" originRef={event.event_id} line={`Radar ${nyTime(detail.event.first_seen_at, true)}: ${event.summary}`} />
        <Link href={radarEventChartHref(detail.event)} className="inline-flex h-9 items-center rounded-md border px-3 text-xs font-medium text-foreground hover:bg-secondary">
          Open chart · {symbol}
        </Link>
        <AskCopilot drawer symbol={symbol} origin={{ kind: "radar_event", ref: event.event_id }} context={`Radar ${nyTime(detail.event.first_seen_at, true)}: ${event.summary}`} />
      </div>
      <div role="group" aria-label="Was this useful?" className="space-y-1.5">
        <p className="text-xs text-muted-foreground">Was this useful? {rating ? "Your saved answer is highlighted." : "Not rated yet."}</p>
        <div className="grid grid-cols-2 gap-2 sm:flex">
          {RATINGS.map(({ value, label }) => (
            <button key={value} type="button" aria-pressed={rating === value} onClick={() => rate(value)}
              className={cn("h-10 rounded-md border px-3 text-xs font-medium transition-colors sm:h-9",
                rating === value ? "border-sky-500/50 bg-sky-500/15 text-sky-200" : "text-muted-foreground hover:bg-secondary hover:text-foreground")}>
              {label}
            </button>
          ))}
        </div>
      </div>
      {error && <p role="alert" className="text-xs text-amber-300">{error}</p>}
    </div>
  );
}

function EventCard({ event, fresh, open, linked, onToggle, onRated }: {
  event: RadarFeedEvent; fresh: boolean; open: boolean; linked: boolean; onToggle: () => void; onRated: (rating: RadarRating) => void;
}) {
  const ref = useRef<HTMLLIElement>(null);
  useEffect(() => { if (linked && open) ref.current?.scrollIntoView({ block: "start" }); }, [linked, open]);
  const direction = DIRECTION[event.direction];
  const against = event.group ?? event.benchmark;
  const keys = Object.keys(event.measures).filter((k) => k !== "benchmark_change_pct" && k !== "change_pct").slice(0, 3);
  return (
    <li ref={ref} className="rounded-lg border bg-card" data-testid="radar-event">
      <button type="button" onClick={onToggle} aria-expanded={open} className="w-full min-w-0 p-3 text-left">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className={cn("rounded px-1.5 py-0.5 text-[11px] font-medium", direction.className)}>{direction.label}</span>
          <span className="text-sm font-semibold text-foreground">{event.symbols.join(", ")}</span>
          <span className="text-xs text-muted-foreground">{KIND[event.kind]} · {against}</span>
          {fresh && <span className="rounded bg-sky-500/15 px-1.5 py-0.5 text-[11px] text-sky-300">New</span>}
          {RULE_TAGS[event.rule_version] && (
            <span className="rounded border border-amber-500/30 px-1.5 py-0.5 text-[11px] text-amber-300" data-testid="radar-rules-tag">
              {RULE_TAGS[event.rule_version]}
            </span>
          )}
        </div>
        <p className="mt-1.5 text-sm text-foreground">{event.summary}</p>
        <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
          {keys.map((k) => <span key={k}>{MEASURE_LABELS[k] ?? k} <span className="tabular-nums text-foreground">{measureText(k, event.measures[k])}</span></span>)}
          <span>First seen {nyTime(event.first_seen_at)}</span>
          <span>{event.latest_status ? `Now: ${STATUS_TEXT[event.latest_status]}` : "No later reading yet"}</span>
          {event.rating && <span>Rated: {RATINGS.find((r) => r.value === event.rating)?.label}</span>}
        </div>
        <p className="mt-1 break-words text-xs text-muted-foreground" data-testid="radar-news-line">{newsLine(event.news, event.session_date)}</p>
      </button>
      {open && <div className="border-t p-3"><Detail event={event} onRated={onRated} /></div>}
    </li>
  );
}

export default function RadarFeedView() {
  const [feed, setFeed] = useState<RadarFeed | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [session, setSession] = useState<string | undefined>();
  const [sessionReady, setSessionReady] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const [linked, setLinked] = useState<string | null>(null); // the event a phone alert's tap asked for
  useEffect(() => {
    let live = true;
    (async () => {
      const params = new URLSearchParams(window.location.search);
      const event = radarEventId(params.get("event"));
      const rate = radarRating(params.get("rate"));
      let day = params.get("session");
      if (event) {
        if (rate) {
          // A phone alert's Useful / Not useful action: the tap is the rating, saved once through the usual feedback
          // route before the event shows. It is dropped from the address first, so a reload (or a second effect run
          // in React strict mode) cannot repeat it.
          const url = new URL(window.location.href); url.searchParams.delete("rate");
          window.history.replaceState(window.history.state, "", url);
          try { await rateEvent(event, rate); } catch { if (live) setNotice("That rating was not saved. You can rate the event below."); }
        }
        if (!day) { try { day = (await getEvent(event)).event.session_date; } catch { /* the feed's default session, then */ } }
      }
      if (!live) return;
      setLinked(event); setOpen(event);
      setSession(radarSession(day)); setSessionReady(true);
    })();
    return () => { live = false; };
  }, []);
  // The last visit as it was when this page opened; opening the page records a new one.
  const baseline = useRef<string | null>(null);
  const visited = useRef(false);
  const wanted = useRef<string | undefined>(undefined);

  const load = useCallback(async (day: string | undefined, signal?: AbortSignal) => {
    try {
      const next = await getFeed(day, baseline.current ?? undefined, signal);
      if (wanted.current !== day) return; // the session changed while this read was in flight
      if (!visited.current) {
        visited.current = true;
        baseline.current = next.last_visit_at ?? NEVER_VISITED;
        if (next.state !== "off") recordVisit(next.generated_at).catch(() => {});
      }
      setFeed(next);
      setError(null);
    } catch (e) {
      if ((e as Error).name !== "AbortError") setError("Radar could not be reached. Try again in a moment.");
    }
  }, []);

  useEffect(() => {
    if (!sessionReady) return;
    const controller = new AbortController();
    wanted.current = session;
    void load(session, controller.signal);
    return () => controller.abort();
  }, [load, session, sessionReady]);

  const live = feed?.coverage?.live;
  useEffect(() => {
    if (!live) return;
    const timer = setInterval(() => void load(session), 60_000);
    return () => clearInterval(timer);
  }, [live, load, session]);

  if (error && !feed) return <p role="alert" className="rounded-lg border bg-card p-3 text-sm text-amber-300">{error}</p>;
  if (!feed) return <p role="status" className="text-sm text-muted-foreground">Loading Radar…</p>;

  const today = new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York" }).format(new Date());
  const fresh = new Set(feed.since_last_visit);
  const newEvents = feed.events.filter((e) => fresh.has(e.event_id)).reverse();
  const earlier = feed.events.filter((e) => !fresh.has(e.event_id)).reverse();
  const rated = (id: string) => (rating: RadarRating) =>
    setFeed((f) => f && { ...f, events: f.events.map((e) => e.event_id === id ? { ...e, rating } : e) });
  const card = (e: RadarFeedEvent) => (
    <EventCard key={e.event_id} event={e} fresh={fresh.has(e.event_id)} open={open === e.event_id} linked={linked === e.event_id}
      onToggle={() => setOpen(open === e.event_id ? null : e.event_id)} onRated={rated(e.event_id)} />
  );

  return (
    <div className="space-y-4">
      <div className="rounded-lg border bg-card px-3 py-2.5" role="status" data-testid="radar-coverage">
        <p className={cn("text-sm", STATE_TONE[feed.state])}>{coverageLine(feed)}</p>
        {feed.session && feed.state !== "off" && (
          <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <label htmlFor="radar-session">Session</label>
            <select id="radar-session" value={feed.session} onChange={(e) => { setOpen(null); setSession(e.target.value);
              const url = new URL(window.location.href); url.searchParams.set("session", e.target.value);
              window.history.replaceState(window.history.state, "", url); }}
              className="h-9 rounded-md border bg-background px-2 text-xs text-foreground">
              {Array.from(new Set([feed.session, ...(feed.sessions ?? [])])).sort().reverse().map((d) => <option key={d} value={d}>{d}</option>)}
            </select>
            {feed.coverage && <span>Universe {feed.coverage.universe_version}</span>}
          </div>
        )}
        {feed.coverage && feed.coverage.symbols_missing.length > 0 && (
          <p className="mt-1 text-xs text-muted-foreground">Not in the latest pass: {feed.coverage.symbols_missing.slice(0, 12).join(", ")}{feed.coverage.symbols_missing.length > 12 ? "…" : ""}</p>
        )}
      </div>
      {error && <p role="alert" className="text-xs text-amber-300">{error}</p>}
      {notice && <p role="alert" className="text-xs text-amber-300">{notice}</p>}

      {feed.state !== "off" && <h2 className="text-base font-semibold">Developments</h2>}

      {feed.state !== "off" && feed.events.length === 0 && (
        <p className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
          {feed.state === "no_data" ? "Nothing has been recorded for this session yet." : "Radar has not produced any developments yet for this session. The recording above shows what it has covered."}
        </p>
      )}
      {newEvents.length > 0 && (
        <section aria-label="New since your last visit" className="space-y-2">
          <h2 className="text-sm font-semibold text-foreground">New since your last visit</h2>
          <ul className="space-y-2">{newEvents.map(card)}</ul>
        </section>
      )}
      {earlier.length > 0 && (
        <section aria-label={feed.session === today ? "Earlier today" : "Earlier in this session"} className="space-y-2">
          <h2 className="text-sm font-semibold text-foreground">{feed.session === today ? "Earlier today" : "Earlier in this session"}</h2>
          <ul className="space-y-2">{earlier.map(card)}</ul>
        </section>
      )}
      {feed.state !== "off" && <RadarMovers session={session ?? feed.session ?? undefined} />}
    </div>
  );
}
