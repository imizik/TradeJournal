"use client";
import { useState, useSyncExternalStore } from "react";

const subscribe = () => () => {};

async function post(action: string, body?: object) {
  const response = await fetch(`/api/lock/${action}`, {
    method: "POST", cache: "no-store",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  const detail = response.ok ? "" : ((await response.json().catch(() => ({}))) as { detail?: string }).detail ?? "Something went wrong.";
  return { ok: response.ok, detail };
}

/** The private app's one sign-in: the owner passphrase, remembered on this device for 30 days. */
export default function OwnerSignIn({ signedIn, next, reportOnly }: { signedIn: boolean; next: string; reportOnly: boolean }) {
  const ready = useSyncExternalStore(subscribe, () => true, () => false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function signIn(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true); setError("");
    const passphrase = String(new FormData(event.currentTarget).get("passphrase") ?? "");
    const result = await post("sign-in", { passphrase }).catch(() => ({ ok: false, detail: "The server could not be reached." }));
    if (result.ok) {
      // Shown in place of a locked page: reload that page. Opened directly: go to `next`.
      if (window.location.pathname === "/sign-in") window.location.assign(next); else window.location.reload();
      return;
    }
    setError(result.detail); setBusy(false);
  }

  async function signOut(everywhere: boolean) {
    if (everywhere && !window.confirm("Sign out every phone and computer? Each one will need the passphrase again.")) return;
    setBusy(true); setError("");
    const result = await post(everywhere ? "sign-out-everywhere" : "sign-out").catch(() => ({ ok: false, detail: "The server could not be reached." }));
    if (!result.ok) { setError(result.detail); setBusy(false); return; }
    // A full reload drops every piece of signed-in client state along with the cookie.
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination
    window.location.assign(`/sign-in?${everywhere ? "ended=all" : "ended=this"}`);
  }

  return (
    <main className="mx-auto flex min-h-[70vh] w-full max-w-sm flex-col justify-center px-5 py-10">
      <h1 className="text-xl font-semibold">Trade Journal</h1>
      {reportOnly && <p className="mt-2 rounded border border-border px-3 py-2 text-sm text-muted-foreground">The lock is in report-only mode: nothing is refused yet. Sign in on each of your devices now.</p>}
      {signedIn ? (
        <section className="mt-6 grid gap-3" aria-label="This device is signed in">
          <p className="text-muted-foreground">This device is signed in.</p>
          <a href={next} className="rounded bg-primary px-3 py-2 text-center font-medium text-primary-foreground">Open the journal</a>
          <button type="button" disabled={busy || !ready} onClick={() => signOut(false)} className="rounded border border-border px-3 py-2">Sign out on this device</button>
          <button type="button" disabled={busy || !ready} onClick={() => signOut(true)} className="rounded border border-border px-3 py-2 text-red-300">Sign out everywhere</button>
        </section>
      ) : (
        <form method="post" onSubmit={signIn} className="mt-6 grid gap-4">
          {/* Lets the phone's and the Mac's password manager file the passphrase under one name. */}
          <input type="text" name="username" autoComplete="username" defaultValue="Trade Journal owner" readOnly hidden />
          <label className="grid gap-1 text-sm">
            <span className="text-muted-foreground">Passphrase</span>
            <input name="passphrase" type="password" autoComplete="current-password" required maxLength={256} autoFocus
              autoCapitalize="none" autoCorrect="off" spellCheck={false}
              className="block w-full rounded border border-border bg-background px-3 py-2 text-base" />
          </label>
          <button disabled={busy || !ready} className="rounded bg-primary px-3 py-2 font-medium text-primary-foreground disabled:opacity-60">{busy ? "Signing in…" : "Sign in"}</button>
          <p className="text-xs text-muted-foreground">This device stays signed in for 30 days, or until it is unused for 7.</p>
        </form>
      )}
      {error && <p role="alert" className="mt-4 text-sm text-red-400">{error}</p>}
      <SignedOutNotice />
    </main>
  );
}

function SignedOutNotice() {
  const ended = useSyncExternalStore(subscribe, () => new URLSearchParams(window.location.search).get("ended"), () => null);
  if (ended === "all") return <p className="mt-4 text-sm text-muted-foreground">Every device is signed out.</p>;
  if (ended === "this") return <p className="mt-4 text-sm text-muted-foreground">This device is signed out.</p>;
  return null;
}
