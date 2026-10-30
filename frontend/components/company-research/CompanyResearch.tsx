"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useAppAccess } from "@/components/AccessProvider";
import { apiUrl } from "@/lib/api";

type Quarter = { end: string; fiscal_period: string; fiscal_year: number; gap: boolean; revenue: string | null; eps_diluted: string | null; gross_margin: string | null; operating_margin: string | null; net_income: string | null; evidence: Record<string, { url: string; filed: string; accession: string }> };
type Observation = { id: string; component: string; provider: string; observed_at: string; data: { state?: string; message?: string; quarters?: Quarter[]; coverage_note?: string; blocks?: Record<string, { value?: unknown; source?: string; message?: string }> } };
type Company = { id: string; symbol: string; name: string; followed: boolean; revision: number; thesis: string; assumptions: string[]; latest: Record<string, Observation>; attempts?: Record<string, Observation>; baseline?: boolean; changes?: { period_end: string; metric: string; before: string | null; after: string | null }[] };

async function request<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  const response = await fetch(apiUrl(`/company-research${path}`), { method, cache: "no-store", headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Request could not be completed");
  return data;
}
const money = (value: string | null | undefined) => value == null ? "—" : new Intl.NumberFormat("en-US", { maximumFractionDigits: 2, notation: "compact", style: "currency", currency: "USD" }).format(Number(value));
const pct = (value: string | null | undefined) => value == null ? "—" : `${(Number(value) * 100).toFixed(1)}%`;
const readTime = (value: string) => new Date(value).toLocaleString("en-US", { timeZone: "America/New_York" });

export default function CompanyResearch({ symbol }: { symbol?: string }) {
  const access = useAppAccess();
  const [companies, setCompanies] = useState<Company[]>([]);
  const [ticker, setTicker] = useState("");
  const [error, setError] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [thesis, setThesis] = useState("");
  const [assumptions, setAssumptions] = useState("");
  const [editingRevision, setEditingRevision] = useState<number | null>(null);
  const [tab, setTab] = useState("results");
  const [quarter, setQuarter] = useState(0);
  const [selected, setSelected] = useState<string[]>([]);
  const load = useCallback(async () => {
    try { setCompanies(await request<Company[]>("/companies")); setLoaded(true); }
    catch (e) { setError(String(e)); }
  }, []);
  useEffect(() => { if (access.owner) { request<Company[]>("/companies").then(rows => { setCompanies(rows); setLoaded(true); }).catch(e => setError(String(e))); } }, [access.owner]);
  const company = companies.find(c => c.symbol === symbol?.toUpperCase());
  const actuals = company?.latest.actuals;
  const quarters = actuals?.data.quarters ?? [];
  const activeQuarter = quarters[Math.min(quarter, Math.max(0, quarters.length - 1))];
  async function perform(action: () => Promise<unknown>) {
    setError(""); setBusy(true);
    try { await action(); await load(); } catch (e) { setError(String(e)); } finally { setBusy(false); }
  }
  if (!access.owner) return <p>Company Research is available through the owner entrance.</p>;
  return <main className="mx-auto max-w-6xl space-y-6 p-4 md:p-6">
    <header className="flex flex-wrap items-center justify-between gap-3"><div><Link className="text-sm text-muted-foreground" href="/research/companies">Company Research</Link><h1 className="text-2xl font-semibold">{company ? company.symbol : "Company Research"}</h1><p className="text-sm text-muted-foreground">Results, expectations, and the evidence behind your thesis.</p></div><button className="rounded border px-3 py-2" onClick={load}>Reload saved data</button></header>
    {error && <p role="alert" className="rounded border border-rose-500 p-3">{error}</p>}
    {!loaded && <p role="status">Loading saved research…</p>}
    {!symbol && <>
      <form className="flex flex-wrap gap-2" onSubmit={e => { e.preventDefault(); void perform(async () => { await request("/companies", "POST", { symbol: ticker }); setTicker(""); }); }}><label className="sr-only" htmlFor="research-ticker">Company ticker</label><input id="research-ticker" className="min-w-0 rounded border bg-background p-2" value={ticker} maxLength={15} onChange={e => setTicker(e.target.value)} placeholder="Company ticker" required /><button disabled={busy} className="rounded border px-4 py-2">Add company</button></form>
      {loaded && !companies.length && <p>Follow a company to track its results and expectations. Your list starts empty.</p>}
      <ul className="space-y-2">{companies.map(c => <li key={c.id} className="flex flex-wrap items-center gap-3 rounded border p-3"><input aria-label={`Compare ${c.symbol}`} type="checkbox" checked={selected.includes(c.id)} disabled={!selected.includes(c.id) && selected.length >= 3} onChange={e => setSelected(s => e.target.checked ? [...s, c.id] : s.filter(id => id !== c.id))} /><Link className="font-semibold underline" href={`/research/companies/${encodeURIComponent(c.symbol)}`}>{c.symbol}</Link><span>{c.followed ? "Following" : "Archived"}</span><span className="text-sm text-muted-foreground">{c.latest.actuals ? `Last financials attempt ${readTime(c.latest.actuals.observed_at)} · ${c.latest.actuals.data.state}` : "Awaiting first refresh"}</span></li>)}</ul>
      {selected.length >= 2 && <section aria-label="Company comparison" className="grid gap-3 md:grid-cols-3">{companies.filter(c => selected.includes(c.id)).map(c => { const q = c.latest.actuals?.data.quarters?.filter(q => !q.gap).at(-1); return <div key={c.id} className="rounded border p-4"><h2 className="font-semibold">{c.symbol}</h2><p>Period ended {q?.end ?? "unavailable"}</p><p>Revenue {money(q?.revenue)}</p><p>Gross margin {pct(q?.gross_margin)}</p><p>Operating margin {pct(q?.operating_margin)}</p><p>Diluted EPS {money(q?.eps_diluted)}</p><p className="text-xs text-muted-foreground">Fiscal periods may differ.</p></div>; })}</section>}
    </>}
    {symbol && loaded && !company && <p>Company not followed. Add it from the company list.</p>}
    {company && <>
      <div className="flex flex-wrap gap-2"><button disabled={busy || !company.followed} className="rounded border px-3 py-2" onClick={() => perform(() => request(`/companies/${company.id}/refresh`, "POST"))}>Refresh sources</button><button disabled={busy} className="rounded border px-3 py-2" onClick={() => perform(() => company.followed ? request(`/companies/${company.id}`, "PATCH", { revision: company.revision, thesis: company.thesis, assumptions: company.assumptions, followed: false }) : request("/companies", "POST", { symbol: company.symbol }))}>{company.followed ? "Stop following" : "Restore company"}</button><span className="self-center text-sm text-muted-foreground">Refresh queues a source check. Reload saved data to see progress.</span></div>
      <section aria-label="What changed" className="space-y-2 rounded border p-4"><h2 className="font-semibold">What changed</h2>{company.baseline ? <p>First baseline: history starts with your initial observation.</p> : !company.changes?.length ? <p>No changes between the latest financial observations.</p> : company.changes.map((c, i) => <p key={i}>{c.period_end} · {c.metric.replaceAll("_", " ")}: {c.before ?? "—"} → {c.after ?? "new period"}</p>)}{Object.entries(company.attempts ?? {}).filter(([, a]) => a.data.state === "unavailable").map(([key, a]) => <p key={key} className="text-amber-400">Latest {key} check failed: {a.data.message}. Saved evidence is retained.</p>)}</section><nav aria-label="Company sections" className="flex gap-2"><button className={`rounded border p-3 ${tab === "results" ? "bg-secondary" : ""}`} onClick={() => setTab("results")}>Results &amp; expectations</button><button className={`rounded border p-3 ${tab === "thesis" ? "bg-secondary" : ""}`} onClick={() => setTab("thesis")}>Thesis &amp; research</button></nav>
      {tab === "results" && <>
        <section aria-label="Financial results" className="space-y-3"><h2 className="text-lg font-semibold">Reported financials</h2>{actuals ? <p className="text-sm text-muted-foreground">{actuals.provider} · observed {readTime(actuals.observed_at)}. Historical results were imported at this observation time.</p> : <p>No financial observations saved yet. Refresh sources to collect a baseline.</p>}{actuals?.data.message && <p role="status">{actuals.data.message}</p>}
          {quarters.length > 0 && <><label htmlFor="research-quarter">Fiscal period</label><select id="research-quarter" className="ml-2 max-w-full rounded border bg-background p-2" value={quarter} onChange={e => setQuarter(Number(e.target.value))}>{quarters.map((q, i) => <option key={q.end} value={i}>{q.fiscal_period} FY{q.fiscal_year} · {q.end}{q.gap ? " · unavailable" : ""}</option>)}</select><dl className="grid grid-cols-2 gap-3 rounded border p-4"><dt>Revenue</dt><dd>{money(activeQuarter?.revenue)}</dd><dt>Diluted EPS (GAAP)</dt><dd>{money(activeQuarter?.eps_diluted)}</dd><dt>Net income</dt><dd>{money(activeQuarter?.net_income)}</dd><dt>Gross margin</dt><dd>{pct(activeQuarter?.gross_margin)}</dd><dt>Operating margin</dt><dd>{pct(activeQuarter?.operating_margin)}</dd></dl>{activeQuarter?.gap && <p>Quarter unavailable. Annual results are not substituted for quarterly results.</p>}<details className="rounded border p-3"><summary>Source evidence</summary>{Object.entries(activeQuarter?.evidence ?? {}).map(([metric, source]) => <p className="break-words py-1 text-sm" key={metric}>{metric}: <a className="underline" href={source.url} target="_blank" rel="noreferrer">SEC filing {source.accession}</a> · filed {source.filed}</p>)}</details></>}
        </section>
        <section aria-label="Analyst expectations" className="space-y-3"><h2 className="text-lg font-semibold">Analyst expectations</h2><p className="text-sm">{company.latest.analysts?.data.coverage_note ?? "No analyst observations saved yet."}</p><AnalystDetails observation={company.latest.analysts} /><SourcedNumbers company={company} /></section>
      </>}
      {tab === "thesis" && <section className="space-y-3"><ResearchQuestions company={company} /><h2 className="text-lg font-semibold">Your thesis</h2><p className="whitespace-pre-wrap">{company.thesis || "No thesis saved yet."}</p><ul className="list-disc pl-5">{company.assumptions.map((a, i) => <li key={i}>{a}</li>)}</ul><button className="rounded border p-2" onClick={() => { setThesis(company.thesis); setAssumptions(company.assumptions.join("\n")); setEditingRevision(company.revision); }}>Edit thesis</button>{editingRevision !== null && <form className="space-y-3" onSubmit={e => { e.preventDefault(); void perform(async () => { await request(`/companies/${company.id}`, "PATCH", { revision: editingRevision, thesis, assumptions: assumptions.split("\n").filter(Boolean), followed: company.followed }); setEditingRevision(null); }); }}><label className="block">Thesis<textarea className="block min-h-32 w-full rounded border bg-background p-2" value={thesis} maxLength={6000} onChange={e => setThesis(e.target.value)} /></label><label className="block">Assumptions (up to five, one per line)<textarea className="block min-h-24 w-full rounded border bg-background p-2" value={assumptions} onChange={e => setAssumptions(e.target.value)} /></label><button disabled={busy} className="rounded border p-2">Save thesis</button><button type="button" className="ml-2 rounded border p-2" onClick={() => setEditingRevision(null)}>Cancel</button></form>}</section>}
      <details className="rounded border p-3"><summary>Observation history</summary><History company={company} /></details>
    </>}
  </main>;
}

function History({ company }: { company: Company }) {
  const [rows, setRows] = useState<Observation[]>([]);
  const [error, setError] = useState("");
  return <div><button className="my-2 rounded border p-2" onClick={async () => { try { setRows(await request<Observation[]>(`/companies/${company.id}/history`)); } catch (e) { setError(String(e)); } }}>Load saved history</button>{error && <p role="alert">{error}</p>}{rows.map(r => <p key={r.id} className="py-1 text-sm">{r.component} · {r.provider} · {readTime(r.observed_at)} · {r.data.state ?? "saved"}</p>)}</div>;
}


type Estimate = { period: string; eps?: { avg: number; low: number; high: number; analysts?: number }; revenue?: { avg: number; low: number; high: number; analysts?: number } };
function AnalystDetails({ observation }: { observation?: Observation }) {
  const blocks = observation?.data.blocks;
  const estimates = (blocks?.estimates?.value ?? []) as Estimate[];
  const history = (blocks?.history?.value ?? []) as { quarter: string; actual: number; estimate: number; result: string }[];
  const targets = blocks?.targets?.value as { low?: number; high?: number; mean?: number } | undefined;
  return <div className="space-y-3">{estimates.map(e => <article key={e.period} className="rounded border p-3"><h3 className="font-semibold">{e.period}</h3><p>EPS estimate {money(e.eps?.avg == null ? null : String(e.eps.avg))} · {e.eps?.analysts ?? "Unknown"} analysts</p><p>Revenue estimate {money(e.revenue?.avg == null ? null : String(e.revenue.avg))}</p><p className="text-xs text-muted-foreground">{blocks?.estimates?.source} · fiscal period and accounting basis unresolved</p></article>)}{!estimates.length && <p>Estimates unavailable from current sources.</p>}{targets && <p>Analyst price targets: {money(targets.low == null ? null : String(targets.low))}–{money(targets.high == null ? null : String(targets.high))}. These are analyst opinions.</p>}{history.length > 0 && <details className="rounded border p-3"><summary>Provider-reported earnings history</summary>{history.map(h => <p key={h.quarter} className="py-2">{h.quarter}: actual {money(String(h.actual))}, estimate {money(String(h.estimate))} · provider reports {h.result}</p>)}<p className="text-xs text-muted-foreground">Retrieved retrospectively from {blocks?.history?.source}. This is not a pre-release snapshot recorded by this app.</p></details>}</div>;
}

type Assignment = { id: string; question: string; context_hash: string; status: string; instruction: string; context: unknown };
type Finding = { id: string; actor: string; digest: string; disposition: string; data: { claim: string; kind: string; sources: { url: string; publisher: string; excerpt: string }[] } };
function ResearchQuestions({ company }: { company: Company }) {
  const [question, setQuestion] = useState("");
  const [assignment, setAssignment] = useState<Assignment | null>(null);
  const [savedAssignments, setSavedAssignments] = useState<Assignment[]>([]);
  const [answer, setAnswer] = useState("");
  const [preview, setPreview] = useState<{ digest: string; payload: unknown } | null>(null);
  const [findings, setFindings] = useState<Finding[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { Promise.all([request<Finding[]>(`/companies/${company.id}/findings`), request<Assignment[]>(`/companies/${company.id}/assignments`)]).then(([f, a]) => { setFindings(f); setSavedAssignments(a); }).catch(e => setError(String(e))); }, [company.id]);
  async function action(fn: () => Promise<void>) { setError(""); setBusy(true); try { await fn(); } catch (e) { setError(String(e)); } finally { setBusy(false); } }
  return <section className="space-y-3 rounded border p-4"><h2 className="text-lg font-semibold">Research questions</h2><p className="text-sm text-muted-foreground">Create a question to send to Duet or Dots with the saved company evidence. Imported answers remain owner-supplied research.</p>{error && <p role="alert">{error}</p>}<form className="flex flex-wrap gap-2" onSubmit={e => { e.preventDefault(); void action(async () => { setAssignment(await request<Assignment>("/assignments", "POST", { company_id: company.id, question })); setPreview(null); }); }}><label className="sr-only" htmlFor="research-question">Research question</label><input id="research-question" className="min-w-0 flex-1 rounded border bg-background p-2" value={question} maxLength={2000} onChange={e => setQuestion(e.target.value)} placeholder="What needs investigation?" required /><button className="rounded border p-2" disabled={busy}>Prepare question</button></form>{savedAssignments.length > 0 && <details><summary>Saved questions</summary>{savedAssignments.map(a => <button key={a.id} className="my-1 block rounded border p-2 text-left" onClick={() => { setAssignment(a); setPreview(null); }}>{a.question} · {a.status}</button>)}</details>}{assignment && <><p className="font-semibold">{assignment.question}</p><button className="rounded border p-2" onClick={() => action(async () => { const packet = { ...assignment, response_template: { operation_id: "answer-1", context_hash: assignment.context_hash, kind: "fact", claim: "Your sourced finding", sources: [{ url: "https://example.com/report", publisher: "Issuer", published_at: null, excerpt: "Supporting passage" }] } }; await navigator.clipboard.writeText(JSON.stringify(packet, null, 2)); })}>Copy assignment for researcher</button><label className="block">Paste structured research response<textarea className="block min-h-32 w-full rounded border bg-background p-2" maxLength={65536} value={answer} onChange={e => { setAnswer(e.target.value); setPreview(null); }} /></label><button className="rounded border p-2" disabled={busy} onClick={() => action(async () => { setPreview(await request(`/assignments/${assignment.id}/import`, "POST", { result: JSON.parse(answer) })); })}>Preview response</button>{preview && <div className="space-y-2 rounded border p-3"><p>{(preview.payload as { claim: string }).claim}</p><p className="text-xs">Source citations are supplied by the researcher; importing does not independently verify them.</p><button className="rounded border p-2" disabled={busy} onClick={() => action(async () => { await request(`/assignments/${assignment.id}/import`, "POST", { result: preview.payload, confirmation: preview.digest }); setFindings(await request(`/companies/${company.id}/findings`)); setPreview(null); setAnswer(""); })}>Save research response</button></div>}</>}{findings.map(f => <article className="space-y-2 rounded border p-3" key={f.id}><p>{f.data.claim}</p><p className="text-xs text-muted-foreground">{f.actor} · {f.data.kind}</p>{f.disposition === "proposed" && <div className="flex gap-2">{["accepted", "rejected", "reviewed"].map(disposition => <button key={disposition} className="rounded border p-2" disabled={busy} onClick={() => action(async () => { await request(`/findings/${f.id}`, "PATCH", { digest: f.digest, disposition }); setFindings(await request(`/companies/${company.id}/findings`)); })}>{disposition === "accepted" ? "Accept evidence" : disposition === "rejected" ? "Reject" : "Mark reviewed"}</button>)}</div>}<p className="text-xs">{f.disposition}</p>{f.data.sources.map((source, i) => <div key={i}><a className="break-words underline" href={source.url} target="_blank" rel="noreferrer">{source.publisher}</a><blockquote className="border-l pl-3 text-sm">{source.excerpt}</blockquote></div>)}</article>)}</section>;
}


type SourcedNumber = { id: string; role: string; metric: string; period_end: string; basis: string; currency: string; unit: string; value: string | null; low?: string; high?: string; origin: string; source: { url: string; publisher: string } };
function SourcedNumbers({ company }: { company: Company }) {
  const [numbers, setNumbers] = useState<SourcedNumber[]>([]);
  const [comparisons, setComparisons] = useState<{ actual: SourcedNumber; reference: SourcedNumber; comparison: { state: string; difference?: string; percent?: string; reason?: string; reference?: string } }[]>([]);
  const [error, setError] = useState("");
  useEffect(() => { Promise.all([request<SourcedNumber[]>(`/companies/${company.id}/numbers`), request<typeof comparisons>(`/companies/${company.id}/comparisons`)]).then(([n, c]) => { setNumbers(n); setComparisons(c); }).catch(e => setError(String(e))); }, [company.id]);
  return <section className="space-y-3"><h3 className="font-semibold">Source-backed numbers &amp; guidance</h3>{error && <p role="alert">{error}</p>}{!numbers.length && <p>No accepted extractions yet. Research responses can supply missing guidance and company metrics for your review.</p>}{numbers.map(n => <article key={n.id} className="rounded border p-3"><p>{n.role} · {n.metric.replaceAll("_", " ")} · period ending {n.period_end}</p><p className="font-mono">{n.value ?? `${n.low}–${n.high}`} {n.unit} · {n.currency} · {n.basis}</p><p className="text-xs">{n.origin}</p><a className="underline" href={n.source.url} target="_blank" rel="noreferrer">{n.source.publisher}</a></article>)}{comparisons.map((c, i) => <article className="rounded border p-3" key={i}><p>{c.actual.metric} · {c.actual.period_end} · actual versus {c.reference.role}</p><p>{c.comparison.state === "ready" ? `Difference from ${c.comparison.reference}: ${c.comparison.difference} ${c.actual.unit}${c.comparison.percent ? ` (${(Number(c.comparison.percent) * 100).toFixed(1)}%)` : ""}` : c.comparison.reason}</p></article>)}</section>;
}
