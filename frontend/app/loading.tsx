export default function Loading() {
  return <div role="status" aria-label="Loading workspace" className="space-y-4">
    <p className="text-sm text-muted-foreground">Loading workspace…</p>
    <div className="h-24 animate-pulse rounded-lg border bg-card" />
    <div className="h-48 animate-pulse rounded-lg border bg-card" />
  </div>;
}
