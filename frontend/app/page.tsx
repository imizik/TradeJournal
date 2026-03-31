export default function DashboardPage() {
  return (
    <div>
      <h1 className="text-2xl font-bold text-slate-900">Dashboard</h1>
      <p className="mt-2 text-slate-600">Overview of your trading activity.</p>
      <div className="mt-6 grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        <div className="rounded-lg border bg-white p-4 shadow-sm">
          <h3 className="font-medium text-slate-900">Realized P&amp;L</h3>
          <p className="mt-1 text-2xl font-semibold">—</p>
        </div>
        <div className="rounded-lg border bg-white p-4 shadow-sm">
          <h3 className="font-medium text-slate-900">Trade Count</h3>
          <p className="mt-1 text-2xl font-semibold">—</p>
        </div>
        <div className="rounded-lg border bg-white p-4 shadow-sm">
          <h3 className="font-medium text-slate-900">Fills</h3>
          <p className="mt-1 text-2xl font-semibold">—</p>
        </div>
      </div>
    </div>
  );
}
