import type { ReactNode } from "react";

export function DashboardCard({ title, action, children, className = "", id }: {
  title: string; action?: ReactNode; children: ReactNode; className?: string; id?: string;
}) {
  return <section id={id} aria-label={title} className={`min-w-0 rounded-lg border bg-card ${className}`}>
    <div className="flex flex-wrap items-center justify-between gap-2 border-b px-3.5 py-2.5">
      <h2 className="text-[13.5px] font-semibold tracking-tight">{title}</h2>
      {action}
    </div>
    <div className="p-4">{children}</div>
  </section>;
}

export function SummaryFigure({ label, value, detail, tone = "text-foreground" }: {
  label: string; value: string; detail: string; tone?: string;
}) {
  return <div className="min-w-0 px-4 py-3">
    <p className="text-xs text-muted-foreground">{label}</p>
    <p className={`mt-1.5 text-2xl font-medium tabular-nums ${tone}`}>{value}</p>
    <p className="mt-1 text-xs text-muted-foreground">{detail}</p>
  </div>;
}

export const pnlTone = (value: number | null) => value == null || value === 0 ? "text-muted-foreground" : value > 0 ? "text-emerald-400" : "text-red-400";

export const dashboardLink = "inline-flex min-h-11 items-center text-xs text-primary hover:underline sm:min-h-0";
