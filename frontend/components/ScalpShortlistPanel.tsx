"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { apiUrl } from "@/lib/api";
import { newYorkToday, timeET } from "@/lib/format";

type Pick = { symbol: string; direction: "up" | "down"; relative_volume?: number; sector_lead_pct?: number; return_pct?: number | null };
type Decision = { symbol: string; choice: "take" | "pass"; decided_at: string; timely: boolean };
type Study = {
  day: string; today: string; now: string; sessions: string[];
  live: null | { day: string; captured_at: string; feed: "iex" | "sip"; eligible: number; picks: Pick[]; movers: Pick[] };
  recap: null | { day: string; captured_at: string; eligible: number; official: Pick[]; shown: Pick[]; movers: Pick[] };
  decisions: Decision[];
};

const moneyMove = (value: number | null | undefined) => value == null ? "Not priced" : `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
const choiceText = (choice: Decision["choice"]) => choice === "take" ? "Take" : "Pass";
const minuteET = (date = new Date()) => {
  const parts = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).formatToParts(date);
  return Number(parts.find((part) => part.type === "hour")?.value ?? 0) * 60 + Number(parts.find((part) => part.type === "minute")?.value ?? 0);
};

async function readStudy(day?: string): Promise<Study> {
  const response = await fetch(apiUrl(`/scalp-shortlist${day ? `?day=${encodeURIComponent(day)}` : ""}`), { cache: "no-store" });
  if (!response.ok) throw new Error(`Study could not load (${response.status}).`);
  return response.json();
}

export default function ScalpShortlistPanel({ history = false }: { history?: boolean }) {
  const [study, setStudy] = useState<Study | null>(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const [selectedDay, setSelectedDay] = useState("");
  const [now, setNow] = useState(0);
  const requestNumber = useRef(0);

  const load = useCallback(async (day?: string) => {
    const request = ++requestNumber.current;
    try {
      const next = await readStudy(day);
      if (request !== requestNumber.current) return;
      setStudy(next); setError(""); setNow(Date.now());
    } catch (e) {
      if (request !== requestNumber.current) return;
      setError(e instanceof Error ? e.message : "Study could not load.");
    }
  }, []);

  // This effect starts the selected read; load updates only from its network response.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { void load(selectedDay || undefined); }, [load, selectedDay]);
  useEffect(() => {
    const id = window.setInterval(() => {
      const minute = minuteET();
      const today = newYorkToday();
      if ((study && !study.sessions.includes(today)) || today < "2026-11-04" || today > "2026-12-02"
          || minute < 9 * 60 + 35 || minute > 10 * 60 + 50
          || (history && selectedDay && selectedDay !== today)) return;
      setNow(Date.now());
      if (document.visibilityState === "visible") void load(history ? (selectedDay || undefined) : undefined);
    }, 10_000);
    return () => window.clearInterval(id);
  }, [history, load, selectedDay, study]);

  async function decide(symbol: string, choice: Decision["choice"]) {
    if (!study || saving) return;
    setSaving(symbol); setNotice("");
    try {
      const response = await fetch(apiUrl(`/scalp-shortlist/${encodeURIComponent(study.day)}/decisions`), {
        method: "POST", cache: "no-store", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ symbol, choice }),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        setNotice(body?.detail ?? (response.status === 409 ? "This session has closed. Refresh to see the result." : "Your choice was not saved. Try again."));
        await load(study.day);
        return;
      }
      await load(study.day);
      setNotice(`${symbol} marked ${choiceText(choice).toLowerCase()}.`);
    } catch {
      setNotice("Could not save your choice. Check the connection and try again.");
    } finally { setSaving(null); }
  }

  const date = selectedDay || study?.day || newYorkToday();
  const current = study?.day === date;
  const timed = current ? study?.decisions.find((decision) => !decision.timely) : undefined;
  const sessionIndex = study?.sessions.indexOf(date) ?? -1;
  const shown = current && study?.live?.day === date ? study.live : null;
  const recap = current && study?.recap?.day === date ? study.recap : null;
  const decisions = current ? study?.decisions ?? [] : [];
  const activeDecisionWindow = current && study?.today === date && !recap && sessionIndex >= 0;
  const minute = minuteET(new Date(now));
  const beforeOpen = activeDecisionWindow && minute < 9 * 60 + 40;
  const canDecide = Boolean(activeDecisionWindow && shown && minute < 9 * 60 + 51);

  if (!history && study && sessionIndex < 0) return null;

  return <section className="min-w-0 rounded-lg border border-primary/30 bg-card" aria-label="9:40 scalp shortlist" data-testid="scalp-shortlist">
    <div className="flex flex-wrap items-center justify-between gap-2 border-b px-3.5 py-2.5">
      <div><h2 className="text-[13.5px] font-semibold tracking-tight">9:40 scalp shortlist</h2><p className="mt-0.5 text-xs text-muted-foreground">20-session paper study{sessionIndex >= 0 ? ` · Morning ${sessionIndex + 1} of 20` : ""}</p></div>
      {history && <Link href="/" className="inline-flex min-h-11 items-center text-xs text-muted-foreground hover:text-foreground sm:min-h-0">Dashboard →</Link>}
    </div>
    <div className="space-y-3 p-4">
      {error && <p role="alert" className="text-sm text-amber-300">{error}</p>}
      {!error && (!study || !current) && <p role="status" className="text-sm text-muted-foreground">Loading {history && selectedDay ? `${date}` : "today’s"} paper study…</p>}
      {study && <>
        {history && <label className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">Study morning
          <select aria-label="Study morning" disabled={saving !== null} value={selectedDay || study.day} onChange={(event) => { setNotice(""); setSelectedDay(event.target.value); }} className="min-h-11 rounded-md border bg-background px-2 text-sm text-foreground">
            {!study.sessions.includes(selectedDay || study.day) && <option value={selectedDay || study.day}>Choose a study morning</option>}
            {[...study.sessions].filter((day) => day <= study.today).reverse().map((day) => <option key={day} value={day}>{day}</option>)}
          </select>
        </label>}
      </>}
      {study && current && sessionIndex < 0 && <p className="text-sm text-muted-foreground">No scalp shortlist session is scheduled for {date}.</p>}
      {study && current && sessionIndex >= 0 && <>
        <p className="text-xs text-muted-foreground">{date} ET · {shown?.feed === "iex" ? "Live IEX preview · official study uses SIP" : "Official list uses SIP"}. Paper stock returns exclude option prices and trading costs.</p>
        {shown ? <>
          <p className="text-xs">{shown.feed === "iex" ? "Live IEX preview" : "Official SIP picks"} · captured {timeET(shown.captured_at, { seconds: true })} · {shown.eligible} stocks eligible</p>
          {shown.picks.length ? <ul className="divide-y divide-border">{shown.picks.map((pick) => {
            const decision = decisions.find((item) => item.symbol === pick.symbol);
            return <li key={pick.symbol} className="flex flex-wrap items-center justify-between gap-3 py-2.5" data-testid={`scalp-pick-${pick.symbol}`}>
              <div className="min-w-28"><p className="text-sm font-semibold">{pick.symbol} <span className={pick.direction === "up" ? "text-emerald-400" : "text-red-400"}>{pick.direction.toUpperCase()}</span></p><p className="text-xs text-muted-foreground">{pick.relative_volume?.toFixed(1)}× usual volume · {pick.sector_lead_pct?.toFixed(2)} pt sector lead</p></div>
              {decision ? <p className="text-xs text-muted-foreground">{choiceText(decision.choice)} · {decision.timely ? "before 9:41" : "late"} · {timeET(decision.decided_at)}</p>
                : canDecide ? <div className="flex gap-2"><button type="button" disabled={saving !== null} onClick={() => void decide(pick.symbol, "take")} className="min-h-11 rounded-md border border-emerald-500/40 px-3 text-sm hover:bg-emerald-500/10 disabled:opacity-50">Take</button><button type="button" disabled={saving !== null} onClick={() => void decide(pick.symbol, "pass")} className="min-h-11 rounded-md border px-3 text-sm hover:bg-secondary disabled:opacity-50">Pass</button></div>
                : <span className="text-xs text-muted-foreground">{minute < 9 * 60 + 40 ? "Decision opens at 9:40" : minute >= 9 * 60 + 51 ? "No choice saved by 9:51" : "Waiting for the first picks"}</span>}
            </li>;
          })}</ul> : <p className="text-sm text-muted-foreground">No stocks met the shortlist rules this morning.</p>}
        </> : <p className="text-sm text-muted-foreground">{beforeOpen ? "Picks arrive after 9:40 ET." : "No picks were captured for this session."}</p>}
        {notice && <p role="status" className="text-xs text-muted-foreground">{notice}</p>}
        {timed && <p className="text-xs text-amber-300">Your {timed.symbol} choice was recorded after the entry window.</p>}
        {recap && <div className="space-y-2 border-t pt-3" data-testid="scalp-recap">
          <h3 className="text-sm font-semibold">9:41–9:51 outcome</h3>
          <ul className="divide-y divide-border">{recap.shown.map((pick) => {
            const decision = decisions.find((item) => item.symbol === pick.symbol);
            return <li key={pick.symbol} className="flex flex-wrap justify-between gap-2 py-2 text-sm"><span>{pick.symbol} {pick.direction.toUpperCase()} {decision ? `· ${choiceText(decision.choice)}` : "· no response"} {recap.official.some((other) => other.symbol === pick.symbol && other.direction === pick.direction) ? "· also an official pick" : "· not an official pick"}</span><span className="tabular-nums">{moneyMove(pick.return_pct)}</span></li>;
          })}</ul>
          <p className="text-xs text-muted-foreground">Official shortlist · {recap.official.map((pick) => `${pick.symbol} ${pick.direction.toUpperCase()} ${moneyMove(pick.return_pct)}`).join(" · ") || "no picks"}</p>
          <p className="text-xs text-muted-foreground">Biggest movers · {recap.movers.map((pick) => `${pick.symbol} ${pick.direction.toUpperCase()} ${moneyMove(pick.return_pct)}`).join(" · ") || "no picks"}</p>
          <p className="text-xs text-muted-foreground">Price movement only, before trading costs. It does not represent an option result or a filled trade.</p>
        </div>}
        {!history && <Link href="/practice#scalp-shortlist" className="inline-flex min-h-11 items-center text-xs text-muted-foreground hover:text-foreground sm:min-h-0">Study history and rules →</Link>}
      </>}
    </div>
  </section>;
}

/** A compact doorway in the full-screen Desk, whose morning remains thread-first. */
export function ScalpShortlistNudge() {
  const [todaySession, setTodaySession] = useState(false);
  useEffect(() => {
    let active = true;
    const check = () => {
      const time = minuteET();
      if (time < 9 * 60 + 35 || time > 10 * 60 + 50) { setTodaySession(false); return; }
      void readStudy().then((data) => { if (active) setTodaySession(data.sessions.includes(data.today)); }).catch(() => { if (active) setTodaySession(false); });
    };
    check();
    const timer = window.setInterval(() => { if (document.visibilityState === "visible") check(); }, 30_000);
    return () => { active = false; window.clearInterval(timer); };
  }, []);
  if (!todaySession) return null;
  return <Link href="/practice#scalp-shortlist" className="inline-flex min-h-11 items-center rounded-md border border-primary/40 px-2.5 text-xs font-medium text-foreground hover:bg-secondary sm:min-h-8">9:40 scalp picks</Link>;
}
