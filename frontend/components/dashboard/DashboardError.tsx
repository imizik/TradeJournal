export default function DashboardError({ searchParams }: { searchParams: Record<string, string | string[] | undefined> }) {
  return <section role="alert" className="rounded-lg border bg-card p-4">
    <h1 className="text-lg font-semibold">Workspace could not load</h1>
    <p className="mt-2 text-sm text-muted-foreground">Workspace data is unavailable. Retry before relying on the summary.</p>
    <form action="/" method="get">
      {Object.entries(searchParams).flatMap(([name, value]) => (value === undefined ? [] : Array.isArray(value) ? value : [value]).map((item, index) => <input key={`${name}-${index}`} type="hidden" name={name} value={item} />))}
      <button type="submit" className="mt-3 min-h-11 rounded-md border px-4 text-sm hover:bg-secondary">Try again</button>
    </form>
  </section>;
}
