import Link from "next/link";

export default function NotFound() {
  return (
    <div className="mx-auto max-w-md space-y-3 py-16 text-center">
      <h1 className="text-xl font-semibold">Page not found</h1>
      <p className="text-sm text-muted-foreground">That address does not match a page in the journal.</p>
      <Link href="/" className="inline-flex min-h-11 items-center rounded-md border px-3 text-sm">Back to Dashboard</Link>
    </div>
  );
}
