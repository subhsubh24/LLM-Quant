"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import {
  Target,
  Sun,
  Moon,
  Activity,
  Wifi,
  WifiOff,
  ChevronLeft,
  ChevronRight,
  LogOut,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useTheme } from "next-themes";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// Prediction-markets-only (ROADMAP A1): the stock "Dashboard" and "Quant Bot"
// surfaces were retired along with the stock/crypto backend. The Predictions panel
// is the single monitoring/control surface for the owner.
const tabs = [
  {
    href: "/predictions",
    label: "Predictions",
    icon: Target,
    description: "Market scanner",
  },
];

export function TabNav() {
  const pathname = usePathname();
  const router = useRouter();
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  const [apiStatus, setApiStatus] = useState<"online" | "offline" | "checking">("checking");
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  const logout = useCallback(async () => {
    try {
      await fetch("/api/auth/logout", { method: "POST" });
    } catch {}
    router.replace("/login");
    router.refresh();
  }, [router]);

  // The login page is a full-screen overlay — don't render the sidebar there.
  if (pathname === "/login") return null;

  const checkApi = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/debug/routes-loaded`, {
        signal: AbortSignal.timeout(3000),
      });
      setApiStatus(res.ok ? "online" : "offline");
    } catch {
      setApiStatus("offline");
    }
  }, []);

  useEffect(() => {
    checkApi();
    const interval = setInterval(checkApi, 30000);
    return () => clearInterval(interval);
  }, [checkApi]);

  return (
    <nav
      className={cn(
        "fixed top-0 left-0 h-screen z-50 flex flex-col border-r border-border/60 bg-card/95 backdrop-blur-xl transition-all duration-300",
        collapsed ? "w-[68px]" : "w-[var(--sidebar-width)]"
      )}
    >
      {/* Logo */}
      <div className={cn(
        "flex items-center h-16 px-5 border-b border-border/60",
        collapsed && "justify-center px-0"
      )}>
        <div className="flex items-center gap-3 min-w-0">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-violet-500 to-indigo-600 flex items-center justify-center flex-shrink-0">
            <Activity className="w-4 h-4 text-white" />
          </div>
          {!collapsed && (
            <div className="slide-in-left">
              <span className="text-sm font-bold tracking-tight text-foreground">QuantLab</span>
              <span className="block text-[10px] text-muted-foreground font-medium">Research & Trading</span>
            </div>
          )}
        </div>
      </div>

      {/* Nav Items */}
      <div className="flex-1 py-4 px-3 space-y-1">
        {!collapsed && (
          <span className="text-[10px] uppercase tracking-widest text-muted-foreground font-semibold px-3 mb-2 block">
            Navigation
          </span>
        )}
        {tabs.map((tab) => {
          const active = pathname === tab.href;
          return (
            <Link
              key={tab.href}
              href={tab.href}
              className={cn(
                "flex items-center gap-3 rounded-xl text-sm font-medium transition-all duration-150 group relative",
                collapsed ? "justify-center p-3" : "px-3 py-2.5",
                active
                  ? "bg-primary/10 text-primary"
                  : "text-muted-foreground hover:text-foreground hover:bg-muted/60"
              )}
            >
              {active && (
                <div className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-5 bg-primary rounded-r-full" />
              )}
              <tab.icon className={cn("w-[18px] h-[18px] flex-shrink-0", active && "text-primary")} />
              {!collapsed && (
                <div className="min-w-0">
                  <span className="block leading-tight">{tab.label}</span>
                  <span className={cn(
                    "block text-[10px] leading-tight mt-0.5",
                    active ? "text-primary/60" : "text-muted-foreground/60"
                  )}>
                    {tab.description}
                  </span>
                </div>
              )}
              {collapsed && (
                <div className="absolute left-full ml-2 px-2 py-1 bg-popover text-popover-foreground text-xs rounded-md shadow-lg border border-border opacity-0 group-hover:opacity-100 pointer-events-none transition-opacity whitespace-nowrap z-50">
                  {tab.label}
                </div>
              )}
            </Link>
          );
        })}
      </div>

      {/* Bottom section */}
      <div className="border-t border-border/60 p-3 space-y-2">
        {/* API Status */}
        <div className={cn(
          "flex items-center gap-2 px-3 py-2 rounded-lg text-xs",
          apiStatus === "online" ? "text-green-500" : apiStatus === "offline" ? "text-red-400" : "text-muted-foreground"
        )}>
          {apiStatus === "online" ? (
            <Wifi className="w-3.5 h-3.5" />
          ) : apiStatus === "offline" ? (
            <WifiOff className="w-3.5 h-3.5" />
          ) : (
            <Activity className="w-3.5 h-3.5 animate-pulse" />
          )}
          {!collapsed && (
            <span className="font-medium">
              {apiStatus === "online" ? "API Connected" : apiStatus === "offline" ? "API Offline" : "Checking..."}
            </span>
          )}
        </div>

        {/* Theme Toggle */}
        {mounted && (
          <button
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            className={cn(
              "flex items-center gap-2 px-3 py-2 rounded-lg text-xs text-muted-foreground hover:text-foreground hover:bg-muted/60 w-full",
              collapsed && "justify-center"
            )}
          >
            {theme === "dark" ? <Sun className="w-3.5 h-3.5" /> : <Moon className="w-3.5 h-3.5" />}
            {!collapsed && <span className="font-medium">{theme === "dark" ? "Light Mode" : "Dark Mode"}</span>}
          </button>
        )}

        {/* Collapse Toggle */}
        <button
          onClick={() => setCollapsed(!collapsed)}
          className={cn(
            "flex items-center gap-2 px-3 py-2 rounded-lg text-xs text-muted-foreground hover:text-foreground hover:bg-muted/60 w-full",
            collapsed && "justify-center"
          )}
        >
          {collapsed ? <ChevronRight className="w-3.5 h-3.5" /> : <ChevronLeft className="w-3.5 h-3.5" />}
          {!collapsed && <span className="font-medium">Collapse</span>}
        </button>

        {/* Logout */}
        <button
          onClick={logout}
          className={cn(
            "flex items-center gap-2 px-3 py-2 rounded-lg text-xs text-muted-foreground hover:text-red-400 hover:bg-red-500/10 w-full",
            collapsed && "justify-center"
          )}
        >
          <LogOut className="w-3.5 h-3.5" />
          {!collapsed && <span className="font-medium">Sign out</span>}
        </button>
      </div>
    </nav>
  );
}
