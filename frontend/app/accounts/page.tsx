export default function AccountsPage() {
  return (
    <div className="space-y-4">
      <div className="flex items-baseline gap-2">
        <h1 className="text-xl font-semibold">Accounts</h1>
        <span className="text-sm text-muted-foreground">Manage your brokerage accounts.</span>
      </div>
      <section aria-label="Accounts list" className="rounded-lg border bg-card">
        <div className="border-b px-3.5 py-2.5">
          <h2 className="text-[13.5px] font-semibold tracking-tight">Your accounts</h2>
        </div>
        <p className="p-4 text-sm text-muted-foreground">No accounts yet.</p>
      </section>
    </div>
  );
}
