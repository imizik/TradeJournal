"use client";

import { useTransition } from "react";
import { useRouter } from "next/navigation";

export default function WorkspaceError({ reset }: { reset: () => void }) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const retry = () => startTransition(() => { router.refresh(); reset(); });
  return <section role="alert" className="rounded-lg border bg-card p-4">
    <h1 className="text-lg font-semibold">Workspace could not load</h1>
    <p className="mt-2 text-sm text-muted-foreground">Workspace data is unavailable. Retry before relying on the summary.</p>
    <button onClick={retry} disabled={pending} className="mt-3 min-h-11 rounded-md border px-4 text-sm hover:bg-secondary">{pending ? "Retrying…" : "Try again"}</button>
  </section>;
}
