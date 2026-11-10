"use client";

export default function ErrorPage({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <div className="mx-auto max-w-md space-y-3 py-16 text-center">
      <h1 className="text-xl font-semibold">Something went wrong on this page</h1>
      <p className="text-sm text-muted-foreground">The rest of the app is fine. Try again, or open another page.</p>
      <button type="button" onClick={() => reset()} className="inline-flex min-h-11 items-center rounded-md border px-3 text-sm">Try again</button>
      {error.digest && <p className="text-xs text-muted-foreground">Reference {error.digest}</p>}
    </div>
  );
}
