"use client";

import { useEffect, useState } from "react";
import { apiUrl } from "@/lib/api";
import { timeET } from "@/lib/format";
import { DashboardCard } from "./dashboard/DashboardCard";

// GET /deploys: the release the server runs, the releases still installed, and deploy/autodeploy.py's
// readable state (its latest check and its recent decisions). See backend/app/routers/deploys.py.
type Decision = { at: string; commit: string; release: string; title: string; outcome: string; detail: string };
type Checked = { at: string; result: string; enabled: boolean; hold: string | null; auto_migrate: boolean; repository: string };
type Deploys = {
  server: boolean;
  running: { release_id: string; commit: string; live_since: string } | null;
  previous: { release_id: string; commit: string } | null;
  releases: { release_id: string; commit: string; installed_at: string }[];
  autodeploy: { history?: Decision[]; checked?: Checked } | null;
};

const OUTCOME: Record<string, { label: string; tone: string }> = {
  deployed: { label: "Deployed", tone: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300" },
  "needs-migration": { label: "Waiting: database change", tone: "border-amber-500/40 bg-amber-500/10 text-amber-300" },
  diverged: { label: "Not installed", tone: "border-amber-500/40 bg-amber-500/10 text-amber-300" },
  "rolled-back": { label: "Rolled back", tone: "border-amber-500/40 bg-amber-500/10 text-amber-300" },
  "backup-failed": { label: "Backup failed", tone: "border-red-500/40 bg-red-500/10 text-red-300" },
  failed: { label: "Failed", tone: "border-red-500/40 bg-red-500/10 text-red-300" },
};
const GOOD = "border-emerald-500/40 bg-emerald-500/10 text-emerald-300";
const WAIT = "border-amber-500/40 bg-amber-500/10 text-amber-300";
const BAD = "border-red-500/40 bg-red-500/10 text-red-300";
const QUIET = "border-border bg-muted text-muted-foreground";
// The timer runs every three minutes; a check older than this means it stopped.
const STALE_MINUTES = 15;

/** The latest pass's one-line result (from autodeploy.main), as a headline and a tone. */
function checkTone(result: string): { label: string; tone: string } {
  if (result.startsWith("Up to date") || result.startsWith("The server already runs")) return { label: "Up to date", tone: GOOD };
  if (result.startsWith("Deployed")) return { label: "Just deployed", tone: GOOD };
  if (result.startsWith("Failed")) return { label: "Failed", tone: BAD };
  if (result.startsWith("Automatic deployment is off") || result.startsWith("No verified build")) return { label: "Idle", tone: QUIET };
  return { label: "Update waiting", tone: WAIT };
}

const short = (commit: string | null | undefined) => commit ? commit.slice(0, 12) : "—";

function Commit({ commit, repository }: { commit: string; repository?: string }) {
  if (!repository) return <code className="text-xs">{short(commit)}</code>;
  return <a href={`https://github.com/${repository}/commit/${commit}`} target="_blank" rel="noreferrer" className="font-mono text-xs text-primary hover:underline">{short(commit)}</a>;
}

function Badge({ label, tone }: { label: string; tone: string }) {
  return <span className={`shrink-0 rounded-md border px-2 py-0.5 text-xs font-semibold ${tone}`}>{label}</span>;
}

export default function DeploysView() {
  const [body, setBody] = useState<Deploys | null>(null);
  const [error, setError] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    let controller = new AbortController();
    const load = () => {
      controller.abort();
      controller = new AbortController();
      const signal = controller.signal;
      fetch(apiUrl("/deploys"), { cache: "no-store", signal })
        .then((r) => r.ok ? r.json() : Promise.reject(new Error(String(r.status))))
        .then((next: Deploys) => { setBody(next); setError(false); setNow(Date.now()); })
        .catch(() => { if (!signal.aborted) setError(true); });
    };
    load();
    const timer = window.setInterval(load, 60_000);
    return () => { window.clearInterval(timer); controller.abort(); };
  }, []);

  if (error && !body) return <p className="text-sm text-red-400">Could not load deploy status.</p>;
  if (!body) return <p className="text-sm text-muted-foreground">Loading…</p>;
  if (!body.server || !body.running) {
    return <DashboardCard title="Not on the server">
      <p className="text-sm text-muted-foreground">This app is not running from a deployed release (a laptop or dev copy), so there is nothing to show. Open this page on the VPS app.</p>
    </DashboardCard>;
  }

  const { running, previous, releases } = body;
  const history = [...(body.autodeploy?.history ?? [])].reverse();
  const checked = body.autodeploy?.checked;
  const repository = checked?.repository;
  const liveTitle = history.find((d) => d.commit === running.commit && d.outcome === "deployed")?.title;
  const status = checked ? checkTone(checked.result) : null;
  const stale = checked ? now - new Date(checked.at).getTime() > STALE_MINUTES * 60_000 : false;

  return <div className="space-y-4">
    <DashboardCard title="Live now">
      <div className="space-y-1.5" data-testid="deploys-live">
        <p className="text-base font-semibold">{liveTitle ?? "Deployed by hand, or before this page kept history"}</p>
        <p className="text-sm text-muted-foreground">
          <Commit commit={running.commit} repository={repository} /> · {running.release_id} · live since {timeET(running.live_since)}
        </p>
      </div>
    </DashboardCard>

    <DashboardCard title="Automatic deploys">
      {!checked ? <p className="text-sm text-muted-foreground">The auto-deployer has not reported yet. It writes this after its next check (every three minutes).</p> :
        <div className="space-y-2" data-testid="deploys-check">
          <div className="flex flex-wrap items-center gap-2">
            {status && <Badge {...status} />}
            <span className="text-sm">{checked.result}</span>
          </div>
          {stale && <p className="text-sm text-amber-300">No check since {timeET(checked.at)}. The auto-deploy timer may have stopped.</p>}
          <p className="text-xs text-muted-foreground">
            Last checked {timeET(checked.at, { seconds: true })} · {checked.enabled ? "on" : "off"}
            {checked.hold ? ` · holds ${checked.hold} New York on weekdays` : " · no market-hours hold"}
            {` · database changes ${checked.auto_migrate ? "applied automatically after a backup" : "wait for a person"}`}
          </p>
        </div>}
    </DashboardCard>

    <DashboardCard title="Recent decisions">
      {history.length === 0 ? <p className="text-sm text-muted-foreground">None recorded yet. Each deploy, hold or failure appears here from now on.</p> :
        <ul className="divide-y" data-testid="deploys-history">
          {history.map((d) => {
            const outcome = OUTCOME[d.outcome] ?? { label: d.outcome, tone: QUIET };
            return <li key={`${d.at}-${d.commit}-${d.outcome}`} className="py-2.5 first:pt-0 last:pb-0">
              <div className="flex flex-wrap items-center gap-2">
                <Badge {...outcome} />
                <span className="min-w-0 text-sm">{d.title}</span>
              </div>
              <p className="mt-1 text-xs text-muted-foreground"><Commit commit={d.commit} repository={repository} /> · {timeET(d.at)}</p>
              {d.outcome !== "deployed" && <p className="mt-1 whitespace-pre-line break-words text-xs text-muted-foreground">{d.detail}</p>}
            </li>;
          })}
        </ul>}
    </DashboardCard>

    <DashboardCard title="Installed on the server">
      <ul className="divide-y" data-testid="deploys-releases">
        {releases.map((r) => <li key={r.release_id} className="flex flex-wrap items-center gap-2 py-2 first:pt-0 last:pb-0">
          <span className="min-w-0 flex-1 truncate text-sm">{r.release_id}</span>
          {r.release_id === running.release_id && <Badge label="Live" tone={GOOD} />}
          {r.release_id === previous?.release_id && <Badge label="Rollback target" tone={QUIET} />}
          <Commit commit={r.commit} repository={repository} />
          <span className="text-xs text-muted-foreground">installed {timeET(r.installed_at)}</span>
        </li>)}
      </ul>
    </DashboardCard>
  </div>;
}
