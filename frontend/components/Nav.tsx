"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { LayoutDashboard, FileText, Activity, Wallet } from "lucide-react";
import { cn } from "@/lib/utils";

const navItems = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/trades", label: "Trades", icon: FileText },
  { href: "/fills", label: "Fills", icon: Activity },
  { href: "/accounts", label: "Accounts", icon: Wallet },
];

export function Nav() {
  const pathname = usePathname();

  return (
    <nav className="w-56 border-r bg-slate-50 p-4">
      <div className="mb-6">
        <h1 className="text-lg font-semibold text-slate-900">Trade Journal</h1>
      </div>
      <ul className="space-y-1">
        {navItems.map(({ href, label, icon: Icon }) => {
          const isActive = pathname === href || (href !== "/" && pathname.startsWith(href));
          return (
            <li key={href}>
              <Link
                href={href}
                className={cn(
                  "flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                  isActive
                    ? "bg-slate-200 text-slate-900"
                    : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
                )}
              >
                <Icon className="h-4 w-4" />
                {label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
