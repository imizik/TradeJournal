"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { LayoutDashboard, FileText, BarChart2, Activity, ClipboardList, FlaskConical, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import StatusPanel, { useAnyJobRunning } from "@/components/StatusPanel";

const navItems = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/daily", label: "Daily Review", icon: ClipboardList },
  { href: "/trades", label: "Trades", icon: FileText },
  { href: "/analytics", label: "Analytics", icon: BarChart2 },
  { href: "/fills", label: "Fills", icon: Activity },
  { href: "/research/ai-buildout", label: "Research", icon: FlaskConical },
];

export function Nav() {
  const pathname = usePathname();
  const [panelOpen, setPanelOpen] = useState(false);
  const anyRunning = useAnyJobRunning();

  return (
    <>
      <nav className="flex h-screen w-56 shrink-0 flex-col border-r bg-card p-4 sticky top-0">
        <div className="mb-6">
          <h1 className="text-lg font-semibold text-foreground">Trade Journal</h1>
        </div>

        <ul className="space-y-1">
          {navItems.map(({ href, label, icon: Icon }) => {
            const isActive =
              pathname === href || (href !== "/" && pathname.startsWith(href));
            return (
              <li key={href}>
                <Link
                  href={href}
                  className={cn(
                    "flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                    isActive
                      ? "bg-secondary text-foreground"
                      : "text-muted-foreground hover:bg-secondary hover:text-foreground"
                  )}
                >
                  <Icon className="h-4 w-4" />
                  {label}
                </Link>
              </li>
            );
          })}
        </ul>

        <div className="mt-auto" />

        {/* Trigger button — bottom right corner of sidebar */}
        <div className="flex justify-end pb-1 pt-3">
          <button
            onClick={() => setPanelOpen((o) => !o)}
            title="Sync & enrichment status"
            className={cn(
              "relative flex items-center gap-1.5 rounded-md px-2 py-1.5 text-xs transition-colors",
              panelOpen
                ? "bg-secondary text-foreground"
                : "text-muted-foreground hover:bg-secondary hover:text-foreground"
            )}
          >
            {anyRunning && (
              <span className="relative flex h-2 w-2">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-sky-400 opacity-75" />
                <span className="relative inline-flex h-2 w-2 rounded-full bg-sky-500" />
              </span>
            )}
            <span className="text-[11px] font-medium">Sync</span>
            <ChevronRight
              className={cn(
                "h-3.5 w-3.5 transition-transform duration-200",
                panelOpen && "rotate-180"
              )}
            />
          </button>
        </div>
      </nav>

      {/* Drawer — fixed, independent of nav DOM, slides in from left */}
      <StatusPanel open={panelOpen} onClose={() => setPanelOpen(false)} />
    </>
  );
}
