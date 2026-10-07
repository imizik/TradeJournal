"use client";

import { useState } from "react";
import { ChevronDown, ChevronUp, ExternalLink } from "lucide-react";
import { useClock } from "@/lib/chartStore";
import { ago, listedNews, newYorkTime, readAt } from "@/lib/symbolInfo";
import type { NewsArticle, SymbolNews } from "@/lib/symbolInfo";

const TONE = { positive: "text-emerald-300", negative: "text-rose-300", neutral: "text-slate-300" };

function Article({ article, symbol, minute }: { article: NewsArticle; symbol: string; minute: number }) {
  const [open, setOpen] = useState(false);
  const mine = article.sentiment.find((s) => s.ticker === symbol);
  const more = article.tickers.length - 1;
  return <li className="space-y-1 py-2">
    <div className="flex items-start justify-between gap-2">
      <a href={article.url} target="_blank" rel="noopener noreferrer" className="min-w-0 text-slate-100 hover:text-sky-300">{article.headline}</a>
      <button aria-expanded={open} aria-label={`${open ? "Hide" : "Show"} summary: ${article.headline}`} onClick={() => setOpen(!open)} className="flex min-h-11 min-w-11 shrink-0 items-center justify-center text-slate-500 hover:text-slate-200 lg:min-h-0 lg:min-w-0">
        {open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
      </button>
    </div>
    <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[10px] text-slate-500">
      <time dateTime={article.published_at} title={newYorkTime(article.published_at)}>{ago(article.published_at, minute * 60_000)}</time>
      <span>{article.publisher ?? "Unknown source"}</span>
      {more > 0 && <span title={article.tickers.join(", ")} className="rounded border border-slate-700 px-1.5 py-0.5">+{more} tickers</span>}
      {mine && <span title={`Polygon's sentiment for ${symbol}, not ours${mine.reasoning ? `: ${mine.reasoning}` : ""}`} className={`rounded border border-slate-700 px-1.5 py-0.5 ${TONE[mine.sentiment]}`}>Polygon: {mine.sentiment}</span>}
    </p>
    {open && <div className="space-y-1 text-slate-300">
      <p>{article.summary ?? "No summary from the provider."}</p>
      {article.sentiment.map((s) => <p key={s.ticker} className="text-[10px] text-slate-400"><span className={TONE[s.sentiment]}>{s.ticker} {s.sentiment}</span> · Polygon&apos;s opinion{s.reasoning ? `: ${s.reasoning}` : ""}</p>)}
      <a href={article.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-sky-300">Read at {article.publisher ?? "the source"} <ExternalLink size={11} aria-hidden /></a>
    </div>}
  </li>;
}

/** The News tab (T1.2). The parent re-reads each minute while it is open; new headlines wait behind "N new" instead of shifting the list. */
export default function SymbolInfoNews({ data }: { data: SymbolNews }) {
  const [focused, setFocused] = useState(true);
  const [seen, setSeen] = useState(() => new Set(data.articles.map((a) => a.id)));
  const minute = useClock((now) => Math.floor(now / 60));
  const current = listedNews(data.articles, focused);
  const fresh = current.filter((a) => !seen.has(a.id)).length;
  const rows = listedNews(data.articles.filter((a) => seen.has(a.id)), focused);
  const hidden = data.articles.filter((a) => a.roundup).length;
  const reading = data.sources.filter((s) => s.state !== "ok");
  const bothDown = data.sources.every((s) => s.state === "failed" || s.state === "not_configured");
  return <div className="space-y-3 text-[11px]">
    <div className="flex items-center justify-between gap-2">
      <label className="flex min-h-11 items-center gap-2 text-slate-300 lg:min-h-0" title="Hides articles that tag more than three symbols">
        <input type="checkbox" checked={focused} onChange={(event) => setFocused(event.target.checked)} /> Focused
      </label>
      {fresh > 0 && <button onClick={() => setSeen(new Set(data.articles.map((a) => a.id)))} className="min-h-11 rounded border border-sky-400/50 px-3 py-2 text-sky-300 lg:min-h-0">{fresh} new</button>}
    </div>
    {rows.length > 0 ? <ul className="divide-y divide-slate-700/40">{rows.map((a) => <Article key={a.id} article={a} symbol={data.symbol} minute={minute} />)}</ul>
      : data.articles.length > 0 ? <p className="text-slate-500">No focused headlines. {hidden} roundup {hidden === 1 ? "article is" : "articles are"} hidden; turn Focused off to read {hidden === 1 ? "it" : "them"}.</p>
      : bothDown ? null : <p className="text-slate-500">No news in the last {data.days} days.</p>}
    {reading.map((s) => <p key={s.provider} role="status" className="text-[10px] text-amber-300">
      {s.label}: {s.message ?? "unavailable"}{s.state === "stale" && s.fetched_at !== null ? ` Copy ${readAt(s.fetched_at)}.` : ""}</p>)}
    <p className="text-[10px] text-slate-500">{data.sources.filter((s) => s.state === "ok" || s.state === "stale").map((s) => s.label).join(" + ") || "No source"} · observed · newest first{data.sources.some((s) => s.provider === "polygon" && s.state !== "failed" && s.state !== "not_configured") ? ` · ${data.sentiment_note}` : ""}</p>
  </div>;
}
