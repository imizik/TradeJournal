"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { captureTime, fetchPlanLink, linkCapture, TIMING_LABEL, type LinkPlan, type PlanLinkPage } from "@/lib/captures";

const big = "inline-flex min-h-12 w-full items-center justify-center rounded-md px-4 text-base font-semibold";
const quiet = "inline-flex min-h-11 items-center justify-center rounded-md border px-4 font-medium hover:bg-muted";

function PlanText({ plan }: { plan: LinkPlan }) {
  return <>
    <p className="font-medium text-foreground">{plan.setup}</p>
    <p className="text-xs text-muted-foreground">Captured {captureTime(plan.received_at)} · {TIMING_LABEL[plan.timing]}</p>
    {plan.wording && <p className="whitespace-pre-wrap break-words">{plan.wording}</p>}
    {plan.note && <p className="whitespace-pre-wrap break-words text-muted-foreground">{plan.note}</p>}
  </>;
}

function Done({ page, plan, again }: { page: PlanLinkPage; plan: LinkPlan; again?: boolean }) {
  return <section aria-label="Linked" className="space-y-3 rounded-lg border border-emerald-500/40 bg-emerald-500/5 p-4 text-sm">
    <h2 className="text-base font-semibold text-emerald-300">{again ? "Already linked" : "Linked"}</h2>
    <p>{page.trade.contract} is linked to your plan &ldquo;{plan.setup}&rdquo; (captured {captureTime(plan.received_at)}, {TIMING_LABEL[plan.timing].toLowerCase()}).</p>
    <div className="flex flex-wrap gap-2">
      <Link href={`/trades/${page.trade.id}`} className={quiet}>Open the trade</Link>
      {plan.investigation_id && <Link href={`/copilot-lab?investigation=${plan.investigation_id}`} className={quiet}>Open its investigation</Link>}
    </div>
  </section>;
}

/**
 * The one-tap link page the link ping opens. The owner's tap on Link is the link: it calls the existing capture link
 * route, which keeps every linking rule. "Not this plan" changes nothing.
 */
export default function PlanLinkConfirm({ tradeId }: { tradeId: string }) {
  const [page, setPage] = useState<PlanLinkPage | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [working, setWorking] = useState<string | null>(null);
  const [refused, setRefused] = useState<string | null>(null);
  const [linked, setLinked] = useState<LinkPlan | null>(null);
  const [declined, setDeclined] = useState(false);

  useEffect(() => {
    let active = true;
    fetchPlanLink(tradeId).then(data => { if (active) setPage(data); },
      failure => { if (active) setLoadError(failure instanceof Error ? failure.message : "This position could not be loaded."); });
    return () => { active = false; };
  }, [tradeId]);

  if (loadError) return <p role="alert" className="text-sm text-amber-300">{loadError}</p>;
  if (!page) return <p role="status" className="text-sm text-muted-foreground">Loading the position…</p>;

  async function link(plan: LinkPlan) {
    if (working) return;
    setWorking(plan.capture_id);
    setRefused(null);
    try {
      await linkCapture(plan.capture_id, tradeId);
      setLinked(plan);
    } catch (failure) {
      setRefused(failure instanceof Error ? failure.message : "It was not linked.");
      // What changed elsewhere (another device linked it) shows on the reread.
      fetchPlanLink(tradeId).then(setPage, () => {});
    } finally {
      setWorking(null);
    }
  }

  const { trade, candidates } = page;
  const several = candidates.length > 1;
  return <div className="space-y-4">
    <section aria-label="Position" className="rounded-lg border bg-card p-4 text-sm">
      <p className="text-base font-semibold text-foreground">{trade.contract}</p>
      <p className="text-muted-foreground">
        {trade.opened.charAt(0).toUpperCase() + trade.opened.slice(1)} {trade.fill}
        {trade.opened_at_reliable ? ` at ${captureTime(trade.opened_at)}` : ", time of day not recorded"}
        {trade.status !== "open" && ` · ${trade.status}`}
      </p>
    </section>
    {linked ? <Done page={page} plan={linked} />
      : page.linked.length ? <Done page={page} plan={page.linked[0]} again />
      : <>
        {refused && <p role="alert" className="rounded border border-amber-500/40 bg-amber-500/5 p-3 text-sm text-amber-200">Not linked. {refused}</p>}
        {candidates.length === 0 ? <p className="text-sm text-muted-foreground">No saved plan is waiting to be linked to this position.</p>
          : !declined && <>
            <p className="text-sm text-foreground">{several ? `${candidates.length} of your saved plans match this fill. Which one was it?` : "Was this your plan?"}</p>
            <ul className="space-y-3">{candidates.map(plan => <li key={plan.capture_id} className="space-y-2 rounded-lg border bg-card p-4 text-sm">
              <PlanText plan={plan} />
              <button type="button" onClick={() => link(plan)} disabled={working !== null}
                aria-label={several ? `Link ${plan.setup} captured ${captureTime(plan.received_at)}` : "Link"}
                className={`${big} bg-primary text-primary-foreground disabled:opacity-60`}>{working === plan.capture_id ? "Linking…" : "Link"}</button>
            </li>)}</ul>
            <button type="button" onClick={() => setDeclined(true)} className={`${quiet} w-full`}>{several ? "None of these" : "Not this plan"}</button>
          </>}
        {(declined || candidates.length === 0) && <section aria-label="Not linked" className="space-y-2 text-sm">
          {declined && <p className="text-muted-foreground">Nothing was linked. You can close this page.</p>}
          <div className="flex flex-wrap gap-2">
            <Link href={page.plan_path} className={`${quiet} bg-primary text-primary-foreground hover:bg-primary/90`}>Plan it now</Link>
            <Link href={`/trades/${trade.id}`} className={quiet}>Open the trade</Link>
            {declined && candidates.length > 0 && <button type="button" onClick={() => setDeclined(false)} className={quiet}>Back to the plans</button>}
          </div>
        </section>}
      </>}
  </div>;
}
