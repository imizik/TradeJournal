"use client";

import { useState } from "react";
import Link from "next/link";
import { Sunrise } from "lucide-react";
import { answerParts } from "@/lib/copilot";
import type { DeskSession } from "@/lib/desk";
import { cn } from "@/lib/utils";

const hhmm = (epoch: number) => new Date(epoch * 1000).toLocaleTimeString("en-GB", { timeZone: "America/New_York", hour: "2-digit", minute: "2-digit" });
/** A saved line as words: no list marker or bold. */
const plain = (line: string) => line.replace(/^\s*(?:[-*•]|\d+[.)])\s+/, "").replace(/\*\*/g, "").trim();

/**
 * Today's morning brief at the top of Main chat (docs/copilot-lab.md § The desk), so the day's thread starts with it
 * instead of it waiting in its own view. It reads the desk's one session read (``prep``): the brief's saved lines, at most
 * ten, with its verdict and headline when it has them. Ask about it puts the brief in this Main chat's message box as
 * context, unsent, so the day's questions stay in one conversation. A brief whose turn failed says the raw facts stand in.
 * Nothing before the brief is written; nothing here calls a model.
 */
export default function MorningBrief({ prep, fill, max }: { prep: DeskSession["prep"] | undefined; fill(text: string): void; max?: number }) {
  const [all, setAll] = useState(false);
  const lines = prep?.lines ?? [];
  if (!prep || !lines.length) return null;
  const parts = prep.fallback ? null : answerParts(lines.join("\n"));
  const body = (parts ? parts.body.split("\n") : lines).map(plain).filter(Boolean);
  const said = [parts ? `${parts.verdict} — ${parts.headline}` : null, ...body, parts?.against ? `Against: ${parts.against}` : null,
    parts?.changesIf ? `Changes if: ${parts.changesIf}` : null].filter(Boolean).join(" ");
  // The cockpit cuts it to ``max`` lines (no Against or Changes if) with the rest one tap away.
  const cut = max !== undefined && !all && (body.length > max || !!parts?.against || !!parts?.changesIf);
  const ask = () => fill(`Context: this morning's brief${prep.at !== null ? ` (${hhmm(prep.at)} ET)` : ""}: ${said}`.slice(0, 600) + "\n\n");
  return (
    <section aria-label="Morning brief" data-testid="morning-brief" className={cn("rounded-lg border bg-card", max !== undefined ? "px-3 py-2.5" : "mb-6 px-4 py-3")}>
      <header className="mb-2 flex flex-wrap items-baseline gap-x-2 text-xs text-muted-foreground">
        <Sunrise size={13} aria-hidden className="self-center text-muted-foreground" />
        <h3 className="text-sm font-semibold text-foreground">Morning brief</h3>
        {prep.at !== null && <span className="tabular-nums">{hhmm(prep.at)} ET</span>}
        {prep.fallback && <span>facts only, no summary</span>}
        <button type="button" onClick={ask} className="ml-auto text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline">Ask about it →</button>
      </header>
      {parts && (
        <p className="mb-1.5 text-sm">
          <span className="mr-1.5 rounded bg-secondary px-1.5 py-0.5 text-[11px] font-medium">{parts.verdict}</span>
          <span className="font-medium">{parts.headline}</span>
        </p>
      )}
      <ul className="list-disc space-y-1 pl-5 text-sm text-foreground/90 marker:text-muted-foreground">
        {(cut ? body.slice(0, max) : body).map((line, i) => <li key={i}>{line}</li>)}
      </ul>
      {!cut && parts?.against && <p className="mt-2 text-xs text-muted-foreground">Against: {parts.against}</p>}
      {!cut && parts?.changesIf && <p className="mt-1 text-xs text-muted-foreground">Changes if: {parts.changesIf}</p>}
      {cut && (prep.path ? <Link href={prep.path} className="mt-2 inline-flex min-h-11 items-center text-xs text-muted-foreground hover:text-foreground sm:min-h-0">Read the whole brief →</Link>
        : <button type="button" onClick={() => setAll(true)} className="mt-2 min-h-11 text-xs text-muted-foreground hover:text-foreground sm:min-h-0">Read the whole brief ▾</button>)}
    </section>
  );
}
