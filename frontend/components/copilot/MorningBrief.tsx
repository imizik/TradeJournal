"use client";

import { Sunrise } from "lucide-react";
import { answerParts } from "@/lib/copilot";
import type { DeskSession } from "@/lib/desk";

const hhmm = (epoch: number) => new Date(epoch * 1000).toLocaleTimeString("en-GB", { timeZone: "America/New_York", hour: "2-digit", minute: "2-digit" });
/** A saved line as words: no list marker or bold. */
const plain = (line: string) => line.replace(/^\s*(?:[-*•]|\d+[.)])\s+/, "").replace(/\*\*/g, "").trim();
const idOf = (path: string | null | undefined) => {
  try { return path ? new URL(path, "http://desk").searchParams.get("investigation") : null; } catch { return null; }
};

/**
 * Today's morning brief at the top of Main chat (docs/copilot-lab.md § The desk), so the day's thread starts with it
 * instead of it waiting in its own view. It reads the desk's one session read (``prep``): the brief's saved lines, at most
 * ten, with its verdict and headline when it has them, and a link to its own thread for follow-ups. A brief whose turn
 * failed says the raw facts stand in. Nothing before the brief is written; nothing here calls a model.
 */
export default function MorningBrief({ prep, open }: { prep: DeskSession["prep"] | undefined; open(id: string): void }) {
  const lines = prep?.lines ?? [];
  if (!prep || !lines.length) return null;
  const parts = prep.fallback ? null : answerParts(lines.join("\n"));
  const body = (parts ? parts.body.split("\n") : lines).map(plain).filter(Boolean);
  const id = idOf(prep.path);
  return (
    <section aria-label="Morning brief" data-testid="morning-brief" className="mb-6 rounded-lg border bg-card px-4 py-3">
      <header className="mb-2 flex flex-wrap items-baseline gap-x-2 text-xs text-muted-foreground">
        <Sunrise size={13} aria-hidden className="self-center text-primary" />
        <h3 className="text-sm font-semibold text-foreground">Morning brief</h3>
        {prep.at !== null && <span className="tabular-nums">{hhmm(prep.at)} ET</span>}
        {prep.fallback && <span className="text-primary">Copilot turn failed: raw facts</span>}
        {id && <button type="button" onClick={() => open(id)} className="ml-auto text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline">Ask about it →</button>}
      </header>
      {parts && (
        <p className="mb-1.5 text-sm">
          <span className="mr-1.5 rounded bg-secondary px-1.5 py-0.5 text-[11px] font-medium">{parts.verdict}</span>
          <span className="font-medium">{parts.headline}</span>
        </p>
      )}
      <ul className="list-disc space-y-1 pl-5 text-sm text-foreground/90 marker:text-muted-foreground">
        {body.map((line, i) => <li key={i}>{line}</li>)}
      </ul>
      {parts?.against && <p className="mt-2 text-xs text-primary/90">Against: {parts.against}</p>}
      {parts?.changesIf && <p className="mt-1 text-xs text-muted-foreground">Changes if: {parts.changesIf}</p>}
    </section>
  );
}
