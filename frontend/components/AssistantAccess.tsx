"use client";
import { useEffect, useState } from "react";
import { useAppAccess } from "./AccessProvider";
type Assistant = { identifier: string; enabled: boolean; expires_at: string; grants: { symbols: string[]; run_ids: string[]; journal_read: boolean; decision_write?: boolean; sample_replay?: boolean } };
export default function AssistantAccess() {
  const { csrf, sample_data, sample_decision_writes_enabled, sample_replay_enabled } = useAppAccess();
  const [items, setItems] = useState<Assistant[]>([]);
  const [secret, setSecret] = useState<{ identifier: string; key: string } | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function load() {
    const response = await fetch("/api/access/assistants", { cache: "no-store" });
    if (!response.ok) throw new Error("Assistant access could not be loaded.");
    setItems(await response.json());
  }
  useEffect(() => { load().catch(err => setError(err.message)); }, []);
  async function write(path: string, body: unknown) {
    const response = await fetch(`/api/access/${path}`, { method: "POST", headers: { "Content-Type": "application/json", "x-tj-csrf": csrf }, body: JSON.stringify(body) });
    if (!response.ok) throw new Error("Access change was refused. Check the ID and grants.");
    const value = await response.json();
    if (value.key) setSecret(value);
    await load();
  }
  async function create(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError(""); setSecret(null);
    const form = new FormData(event.currentTarget);
    try {
      await write("assistants", { identifier: String(form.get("identifier")).trim().toLowerCase(), grants: {
        symbols: String(form.get("symbols")).split(",").map(s => s.trim().toUpperCase()).filter(Boolean),
        run_ids: String(form.get("runs")).split(",").map(s => s.trim()).filter(Boolean), journal_read: sample_data && form.get("journal") === "on", decision_write: sample_decision_writes_enabled && form.get("writer") === "on",
        sample_replay: sample_replay_enabled && form.get("replay") === "on" } });
    } catch (err) { setError(err instanceof Error ? err.message : "Access change failed."); }
    finally { setBusy(false); }
  }
  async function action(item: Assistant, kind: "reset" | "revoke") {
    setBusy(true); setError(""); setSecret(null);
    try { await write(`assistants/${encodeURIComponent(item.identifier)}/${kind}`, kind === "reset" ? { grants: item.grants } : {}); }
    catch (err) { setError(err instanceof Error ? err.message : "Access change failed."); }
    finally { setBusy(false); }
  }
  return <div className="max-w-3xl space-y-6"><h1 className="text-2xl font-semibold">Assistant access</h1><p className="text-muted-foreground">Create a separate scoped login. Revocation and key reset invalidate its sessions. Access keys expire after 30 days.</p><form onSubmit={create} className="grid gap-4 rounded border p-4"><label>Assistant ID<input required name="identifier" pattern="[a-z][a-z0-9_-]{2,63}" className="mt-1 block w-full rounded border bg-background p-2" placeholder="dot-inspector" /></label><label>Allowed market symbols<input required name="symbols" defaultValue="SPY,QQQ,IWM,AAPL,MSFT,MU,NBIS" className="mt-1 block w-full rounded border bg-background p-2" /></label><label>Practice run IDs to share<input name="runs" className="mt-1 block w-full rounded border bg-background p-2" placeholder="Comma-separated run IDs; leave empty for no practice access" /></label>{sample_decision_writes_enabled && <label><input type="checkbox" name="writer" /> Save only this assistant’s own simulated decisions (one sample run, up to two symbols, no journal access)</label>}{sample_replay_enabled && <label><input type="checkbox" name="replay" /> Start only this assistant’s own TAKE sample replays (requires decision saving)</label>}{sample_data && <label><input type="checkbox" name="journal" /> Allow read-only inspection of this installation’s sample journal</label>}<p className="text-sm text-muted-foreground">Market access does not change the paper-practice policy or grant journal access.</p><button disabled={busy} className="rounded bg-primary p-2 text-primary-foreground">Create assistant login</button></form>{secret && <section className="space-y-2 rounded border border-amber-500 p-4"><h2 className="font-semibold">Access key · shown once</h2><p>Assistant ID: {secret.identifier}</p><label>Access key<input type="password" readOnly value={secret.key} autoComplete="off" className="block w-full rounded border bg-background p-2" /></label><p className="text-sm">Enter this through the Dot’s private website sign-in flow. Keep it out of chat.</p><button onClick={() => navigator.clipboard.writeText(secret.key).catch(() => setError("Clipboard unavailable. Select the access key to copy it."))} className="mr-3 underline">Copy access key</button><button onClick={() => setSecret(null)} className="underline">Dismiss key</button></section>}{error && <p role="alert" className="text-red-400">{error}</p>}<div className="space-y-3">{items.map(item => <section key={item.identifier} className="flex flex-wrap items-center justify-between gap-3 rounded border p-4"><div><h2 className="font-semibold">{item.identifier} · {item.enabled ? "Enabled" : "Revoked"}</h2><p className="text-sm">{item.grants.symbols.join(", ")} · {item.grants.run_ids.length} shared practice runs</p></div><div className="flex gap-3"><button disabled={busy} onClick={() => action(item, "reset")} className="underline">Reset key</button><button disabled={busy || !item.enabled} onClick={() => action(item, "revoke")} className="underline">Revoke access</button></div></section>)}</div></div>;
}
