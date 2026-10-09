"use client";
import { useState, useSyncExternalStore } from "react";
const subscribe = () => () => {};
export default function LoginPage() {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const ready = useSyncExternalStore(subscribe, () => true, () => false);
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); setError(""); setBusy(true);
    const form = new FormData(event.currentTarget);
    try {
      const challenge = await fetch("/api/access/challenge", { cache: "no-store" });
      if (!challenge.ok) throw new Error("Sign-in is unavailable.");
      const { csrf } = await challenge.json();
      const response = await fetch("/api/access/login", { method: "POST", headers: { "Content-Type": "application/json", "x-tj-csrf": csrf }, body: JSON.stringify({ identifier: form.get("identifier"), key: form.get("key") }) });
      if (!response.ok) throw new Error(response.status === 429 ? "Too many attempts. Try again later." : "Sign-in failed.");
      window.location.assign("/");
    } catch (err) { setError(err instanceof Error ? err.message : "Sign-in failed."); }
    finally { setBusy(false); }
  }
  return <main className="mx-auto w-full max-w-md p-6"><h1 className="text-2xl font-semibold">TradeJournal assistant sign-in</h1><p className="mt-2 text-muted-foreground">Use the dedicated app credential provided by the owner.</p><form method="post" onSubmit={submit} className="mt-6 grid gap-4"><label>Assistant ID<input name="identifier" autoComplete="username" required maxLength={64} className="mt-1 block w-full rounded border bg-background p-2" /></label><label>Access key<input name="key" type="password" autoComplete="current-password" required maxLength={128} className="mt-1 block w-full rounded border bg-background p-2" /></label><button disabled={busy || !ready} className="rounded bg-primary p-2 text-primary-foreground">{busy ? "Signing in…" : "Sign in"}</button>{error && <p role="alert" className="text-red-400">{error}</p>}</form></main>;
}
