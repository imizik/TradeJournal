"use client";

import { useEffect, useState } from "react";
import { coverageLine, getFeed, headlineMeta, newsLine, nyTime, STATUS_TEXT, type RadarFeed } from "@/lib/radar";
import { DashboardCard, dashboardLink } from "./DashboardCard";

/** Reading the Dashboard must not mark the Radar feed visited or rate events. */
export default function RadarPreview() {
  const [feed, setFeed] = useState<RadarFeed | null>(null);
  const [error, setError] = useState(false);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    getFeed(undefined, undefined, controller.signal).then((next) => {
      setFeed(next); setError(false);
    }).catch(() => { if (!controller.signal.aborted) setError(true); });
    return () => controller.abort();
  }, [refresh]);
  const events = feed?.state !== "off" ? [...(feed?.events ?? [])]
    .sort((a, b) => b.first_seen_at.localeCompare(a.first_seen_at)).slice(0, 3) : [];
  return <DashboardCard title="Radar discoveries" action={<a href="/radar" className={dashboardLink}>Open Radar →</a>}>
    <div className="min-w-0 space-y-3 break-words" data-testid="radar-preview">
      {error && <p role="status" className="text-xs text-amber-300">Radar could not load.{feed && " Showing the previous snapshot; current status is unknown."}</p>}
      {!feed && !error && <p role="status" className="text-sm text-muted-foreground">Loading saved discoveries…</p>}
      {feed && <p className={`text-xs ${feed.state === "stale" ? "text-amber-300" : "text-muted-foreground"}`}>
        {feed.session && <span>{feed.session} ET · </span>}{coverageLine(feed)}
      </p>}
      {events.length > 0 ? <ul className="divide-y divide-border">
        {events.map((event) => {
          const symbol = event.chart?.symbol ?? event.symbols[0];
          return <li key={event.event_id} className="space-y-1 py-2 first:pt-0">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <span className="text-sm font-medium">{event.group ?? event.symbols.join(", ")}</span>
              {symbol && <a href={`/charts?symbol=${encodeURIComponent(symbol)}`} className={dashboardLink}>Open {symbol} chart →</a>}
            </div>
            <p className="line-clamp-2 text-sm">{event.summary}</p>
            <p className="line-clamp-2 text-xs text-muted-foreground">{newsLine(event.news, event.session_date)}</p>
            <details className="text-xs" data-testid="radar-preview-context">
              <summary className="min-h-11 cursor-pointer py-2 text-primary sm:min-h-8">Full move &amp; saved news</summary>
              <p className="whitespace-pre-wrap py-2 text-sm">{event.summary}</p>
              <p className="text-muted-foreground">Saved news near the detection, not a confirmed cause or a live news feed.</p>
              {event.news?.status === "found" && event.news.headlines.length > 0
                ? <div className="space-y-2 py-2">{event.news.headlines.map((headline, index) => <div key={`${headline.url}:${index}`}>
                    <p>{headline.headline}</p><p className="text-muted-foreground">{headlineMeta(headline, event.session_date)}</p>
                  </div>)}</div>
                : <p className="py-2 text-muted-foreground">{newsLine(event.news, event.session_date)}</p>}
              {event.news?.checked_at && <p className="text-muted-foreground">News checked <time dateTime={event.news.checked_at}>{new Date(event.news.checked_at).toLocaleString("en-US", { timeZone: "America/New_York", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })} ET</time></p>}
              <a href="/radar" className={dashboardLink}>Inspect saved evidence in Radar →</a>
            </details>
            <p className="text-xs text-muted-foreground">Detected <time dateTime={event.first_seen_at}>{nyTime(event.first_seen_at)} ET</time>
              {event.latest_status && ` · ${STATUS_TEXT[event.latest_status]}`} · saved evidence in Radar</p>
          </li>;
        })}
      </ul> : feed && feed.state !== "off" && <p className="text-sm text-muted-foreground">No saved discoveries in this session. This does not mean nothing moved.</p>}
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
        <span>{feed?.generated_at ? <>Snapshot <time dateTime={feed.generated_at}>{nyTime(feed.generated_at)} ET</time> · refresh for updates</> : "Saved Radar feed · no live scan runs here"}</span>
        <button type="button" onClick={() => setRefresh((value) => value + 1)} className="inline-flex min-h-11 items-center text-primary hover:underline sm:min-h-8">Refresh Radar</button>
      </div>
    </div>
  </DashboardCard>;
}
