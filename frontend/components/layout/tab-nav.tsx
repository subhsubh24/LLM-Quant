"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { BarChart3, Target, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";

const tabs = [
  { href: "/dashboard", label: "Dashboard", icon: BarChart3 },
  { href: "/predictions", label: "Predictions", icon: Target },
  { href: "/bot", label: "Quant Bot", icon: Sparkles },
];

export function TabNav() {
  const pathname = usePathname();

  return (
    <nav className="sticky top-0 z-50 bg-white/80 backdrop-blur-xl border-b border-gray-200/60">
      <div className="flex items-center h-14 px-8 gap-1">
        <span className="text-sm font-bold tracking-tight text-gray-900 mr-6">QuantLab</span>
        {tabs.map((tab) => {
          const active = pathname === tab.href;
          return (
            <Link
              key={tab.href}
              href={tab.href}
              className={cn(
                "flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors",
                active
                  ? "bg-gray-900 text-white"
                  : "text-gray-500 hover:text-gray-900 hover:bg-gray-100"
              )}
            >
              <tab.icon className="w-4 h-4" />
              {tab.label}
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
