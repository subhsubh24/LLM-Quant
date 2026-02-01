"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  FlaskConical,
  TrendingUp,
  BarChart3,
  GraduationCap,
  Terminal,
  Brain,
  Layers,
  Bitcoin,
  Globe,
  Coins,
} from "lucide-react";
import { cn } from "@/lib/utils";

const stocksNavigation = [
  { name: "Terminal", href: "/dashboard", icon: Terminal },
  { name: "Trading", href: "/trading", icon: TrendingUp },
  { name: "Options", href: "/options", icon: Layers },
  { name: "Quant Bot", href: "/bot", icon: Brain },
];

const cryptoNavigation = [
  { name: "Crypto", href: "/crypto", icon: Bitcoin },
];

const commonNavigation = [
  { name: "AI Insights", href: "/insights", icon: Brain },
  { name: "Research", href: "/research", icon: FlaskConical },
  { name: "Analytics", href: "/performance", icon: BarChart3 },
  { name: "Learn", href: "/learn", icon: GraduationCap },
];

export function Sidebar() {
  const pathname = usePathname();

  const NavLink = ({ item }: { item: { name: string; href: string; icon: any } }) => {
    const isActive = pathname === item.href || pathname.startsWith(item.href + "/");
    return (
      <Link
        href={item.href}
        className={cn(
          "flex items-center gap-2 px-3 py-2 rounded text-xs font-medium font-mono uppercase tracking-wide transition-colors",
          isActive
            ? "bg-primary text-primary-foreground"
            : "text-muted-foreground hover:bg-secondary hover:text-foreground"
        )}
      >
        <item.icon className="w-4 h-4" />
        {item.name}
      </Link>
    );
  };

  return (
    <aside className="w-56 border-r border-border bg-card flex flex-col">
      {/* Logo */}
      <div className="h-12 flex items-center px-4 border-b border-border">
        <Link href="/dashboard" className="flex items-center gap-2">
          <div className="w-7 h-7 rounded bg-bloomberg-orange flex items-center justify-center">
            <span className="text-background font-bold text-xs font-mono">QL</span>
          </div>
          <span className="font-bold text-sm font-mono text-bloomberg-orange">QUANTLAB</span>
        </Link>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-2 py-3 space-y-3 overflow-y-auto">
        {/* Stocks Section */}
        <div>
          <div className="px-3 py-1.5 text-[10px] font-semibold text-bloomberg-orange font-mono tracking-wider flex items-center gap-1.5">
            <TrendingUp className="w-3 h-3" />
            STOCKS
          </div>
          <div className="space-y-0.5">
            {stocksNavigation.map((item) => (
              <NavLink key={item.name} item={item} />
            ))}
          </div>
        </div>

        {/* Crypto Section */}
        <div>
          <div className="px-3 py-1.5 text-[10px] font-semibold text-yellow-500 font-mono tracking-wider flex items-center gap-1.5">
            <Bitcoin className="w-3 h-3" />
            CRYPTO
          </div>
          <div className="space-y-0.5">
            {cryptoNavigation.map((item) => (
              <NavLink key={item.name} item={item} />
            ))}
          </div>
        </div>

        {/* Common Section */}
        <div>
          <div className="px-3 py-1.5 text-[10px] font-semibold text-muted-foreground font-mono tracking-wider flex items-center gap-1.5">
            <Globe className="w-3 h-3" />
            TOOLS
          </div>
          <div className="space-y-0.5">
            {commonNavigation.map((item) => (
              <NavLink key={item.name} item={item} />
            ))}
          </div>
        </div>
      </nav>

      {/* Status */}
      <div className="p-3 border-t border-border">
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <div className="w-2 h-2 rounded-full bg-positive animate-pulse" />
          <span className="font-mono">CONNECTED</span>
        </div>
      </div>

      {/* Disclaimer */}
      <div className="px-3 pb-3">
        <div className="p-2 rounded bg-secondary/50 border border-border">
          <p className="text-[10px] text-muted-foreground leading-tight font-mono">
            PAPER TRADING ONLY
            <br />
            NOT FINANCIAL ADVICE
          </p>
        </div>
      </div>
    </aside>
  );
}
