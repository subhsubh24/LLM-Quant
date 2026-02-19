"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  FlaskConical,
  BarChart3,
  GraduationCap,
  Activity,
  Bot,
  Settings,
  Zap,
  TrendingUp,
  Bitcoin,
  LineChart,
  Lightbulb,
} from "lucide-react";
import { cn } from "@/lib/utils";

const navigation = [
  { name: "Dashboard", href: "/dashboard", icon: LayoutDashboard, description: "Market Overview" },
  { name: "Quant Bot", href: "/bot", icon: Bot, badge: "LIVE", badgeColor: "green", description: "Automated Trading" },
  { name: "Trading", href: "/trading", icon: TrendingUp, description: "Auto Trader" },
  { name: "Options", href: "/options", icon: LineChart, description: "Options Trading" },
  { name: "Crypto", href: "/crypto", icon: Bitcoin, description: "Cryptocurrency" },
  { name: "Research", href: "/research", icon: FlaskConical, description: "Algorithm Config" },
  { name: "Analytics", href: "/performance", icon: BarChart3, description: "Market Health" },
  { name: "Insights", href: "/insights", icon: Lightbulb, badge: "AI", badgeColor: "orange", description: "AI Analysis" },
  { name: "Learn", href: "/learn", icon: GraduationCap, badge: "AI", badgeColor: "purple", description: "Trade Coaching" },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="fixed left-0 top-0 h-screen w-64 bg-white border-r border-gray-100 flex flex-col z-40">
      {/* Logo */}
      <div className="h-16 flex items-center px-6">
        <Link href="/dashboard" className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-2xl bg-gradient-to-br from-blue-500 to-blue-600 flex items-center justify-center shadow-lg shadow-blue-500/20">
            <Activity className="w-5 h-5 text-white" />
          </div>
          <div>
            <span className="font-semibold text-gray-900 text-lg">QuantLab</span>
            <span className="block text-[10px] text-gray-400 font-medium -mt-0.5">HFT Trading</span>
          </div>
        </Link>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-3 py-4 overflow-y-auto">
        <div className="space-y-1">
          {navigation.map((item) => {
            const isActive = pathname === item.href || pathname.startsWith(item.href + "/");
            const badgeColors: Record<string, { active: string; inactive: string }> = {
              green: { active: "bg-white/20 text-white", inactive: "bg-green-50 text-green-600" },
              purple: { active: "bg-white/20 text-white", inactive: "bg-purple-50 text-purple-600" },
              orange: { active: "bg-white/20 text-white", inactive: "bg-orange-50 text-orange-600" },
            };
            return (
              <Link
                key={item.name}
                href={item.href}
                className={cn(
                  "flex items-center gap-3 px-4 py-3 rounded-xl font-medium transition-all group",
                  isActive
                    ? "bg-gray-900 text-white shadow-lg"
                    : "text-gray-600 hover:bg-gray-50 hover:text-gray-900"
                )}
              >
                <item.icon className={cn("w-5 h-5", isActive ? "text-white" : "text-gray-400 group-hover:text-gray-600")} />
                <div className="flex-1 min-w-0">
                  <span className="text-sm block">{item.name}</span>
                  <span className={cn(
                    "text-[10px] block",
                    isActive ? "text-gray-300" : "text-gray-400"
                  )}>{item.description}</span>
                </div>
                {item.badge && (
                  <span className={cn(
                    "text-[10px] font-semibold px-2 py-0.5 rounded-full",
                    isActive
                      ? badgeColors[item.badgeColor || "green"].active
                      : badgeColors[item.badgeColor || "green"].inactive
                  )}>
                    {item.badge}
                  </span>
                )}
              </Link>
            );
          })}
        </div>
      </nav>

      {/* Market Status */}
      <div className="px-4 py-3">
        <div className="p-4 rounded-2xl bg-gradient-to-br from-gray-50 to-gray-100">
          <div className="flex items-center gap-2 mb-2">
            <div className="w-2 h-2 rounded-full bg-green-500 shadow-lg shadow-green-500/50 animate-pulse" />
            <span className="text-xs font-semibold text-gray-600">MARKETS LIVE</span>
          </div>
          <p className="text-[11px] text-gray-500 leading-relaxed">
            Paper trading mode active. Real-time market data connected.
          </p>
        </div>
      </div>

      {/* User Profile */}
      <div className="px-4 py-4 border-t border-gray-100">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-full bg-gradient-to-br from-purple-500 to-pink-500 flex items-center justify-center">
            <span className="text-white font-semibold text-sm">Q</span>
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-gray-900 truncate">Quant Trader</p>
            <p className="text-xs text-gray-500">Paper Account</p>
          </div>
          <button className="p-2 hover:bg-gray-100 rounded-lg transition-colors">
            <Settings className="w-4 h-4 text-gray-400" />
          </button>
        </div>
      </div>
    </aside>
  );
}
