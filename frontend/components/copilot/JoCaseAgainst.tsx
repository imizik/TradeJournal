"use client";

import { useEffect, useState } from "react";
import { askRedTeam, getRedTeam, type RedTeam } from "@/lib/copilot";

/**
 * On a confirmed plan card: ask Jo (OpenAI, through its research run) to argue against the plan, then show its answer
 * collapsed. The request only waits for Jo's next run; nothing here calls a model or sends a ping.
 */
export default function JoCaseAgainst({ investigationId, proposalId }: { investigationId: string; proposalId: string }) {
  const [found, setFound] = useState<RedTeam | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "asking" | "failed">("loading");
  const [problem, setProblem] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    getRedTeam(investigationId, controller.signal)
      .then(rows => { setFound(rows.find(r => r.proposal_id === proposalId) ?? null); setState("ready"); })
      .catch(() => { if (!controller.signal.aborted) setState("failed"); });
    return () => controller.abort();
  }, [investigationId, proposalId]);

  async function ask() {
    setState("asking");
    setProblem(null);
    try {
      setFound(await askRedTeam(investigationId, proposalId));
      setState("ready");
    } catch (error) {
      setProblem(error instanceof Error ? error.message : "The request could not be saved.");
      setState("ready");
    }
  }

  if (state === "loading" || state === "failed") return null;
  if (found?.answer) {
    return (
      <details aria-label="Jo's case against" className="rounded border border-amber-500/30 bg-amber-500/5 p-2 text-xs">
        <summary className="cursor-pointer text-foreground">Jo&apos;s case against: {found.answer.title}</summary>
        <p className="mt-2 whitespace-pre-wrap text-foreground/90">{found.answer.body}</p>
        {found.answer.citations.length > 0 && (
          <ul className="mt-2 space-y-0.5 text-muted-foreground">
            {found.answer.citations.map(c => (
              <li key={c.url}><a href={c.url} target="_blank" rel="noreferrer" className="underline">{c.publisher || c.url}</a>{c.published_at ? ` · ${c.published_at}` : ""}</li>
            ))}
          </ul>
        )}
        <p className="mt-2 text-muted-foreground">Research from Jo (OpenAI), not an instruction.</p>
      </details>
    );
  }
  if (found) return <p role="status" className="text-xs text-muted-foreground">Waiting for Jo: it answers in its next research run, outside market hours.</p>;
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs">
      <button type="button" onClick={() => void ask()} disabled={state === "asking"}
        className="min-h-11 rounded border px-3 py-1 text-muted-foreground hover:text-foreground disabled:opacity-40">
        Ask Jo to argue against this</button>
      {problem && <span role="alert" className="text-amber-300">{problem}</span>}
    </div>
  );
}
