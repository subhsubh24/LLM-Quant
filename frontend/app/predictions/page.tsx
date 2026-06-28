"use client";

import { useState, useEffect, useRef, useMemo } from "react";
import {
  Target,
  Zap,
  CloudSun,
  Shield,
  DollarSign,
  Search,
  RefreshCw,
  AlertTriangle,
  Activity,
  BarChart3,
  Globe,
  ArrowLeftRight,
  Users,
  Radio,
  Eye,
  Layers,
  Bot,
  RotateCw,
  TrendingUp,
  Clock,
  Loader2,
  CheckCircle2,
  XCircle,
  ChevronDown,
} from "lucide-react";
import { cn } from "@/lib/utils";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// ----------------------------------------------------------------
// Types
// ----------------------------------------------------------------

interface MarketOutcome { label: string; price: number; tokenId: string }
interface PredictionMarket {
  id: string; question: string; category: string; outcomes: MarketOutcome[];
  volume: number; liquidity: number; endDate: string; active: boolean; exchange?: "polymarket";
}
interface Opportunity {
  id: string; strategy: string; market: string; side: "BUY" | "SELL";
  entryPrice: number; edge: number; confidence: number; reason: string; timestamp: string;
}
interface Position {
  id: string; market: string; outcome: string; side: "BUY" | "SELL";
  entryPrice: number; currentPrice: number; size: number; pnl: number;
  strategy: string; openedAt: string;
}
interface StrategyConfig {
  id: string; name: string; description: string; icon: any; enabled: boolean;
  color: string; positions: number; pnl: number; config: Record<string, string | number>;
}

// ----------------------------------------------------------------
// Strategy Data
// ----------------------------------------------------------------

const DEFAULT_STRATEGIES: StrategyConfig[] = [
  { id: "weather_arb", name: "Weather Arb", description: "Compare NOAA forecasts to market prices.", icon: CloudSun, enabled: true, color: "cyan", positions: 0, pnl: 0, config: {} },
  { id: "near_certainty", name: "Near-Certainty", description: "Buy 90-99c outcomes at scale.", icon: Target, enabled: true, color: "violet", positions: 0, pnl: 0, config: {} },
  { id: "same_market_arb", name: "Same-Mkt Arb", description: "YES + NO < $1.00? Buy both.", icon: Zap, enabled: true, color: "amber", positions: 0, pnl: 0, config: {} },
  { id: "cross_market_arb", name: "Cross-Mkt Arb", description: "Logical inconsistencies across markets.", icon: Globe, enabled: true, color: "rose", positions: 0, pnl: 0, config: {} },
  { id: "market_making", name: "Market Making", description: "Two-sided liquidity + spread capture.", icon: ArrowLeftRight, enabled: true, color: "blue", positions: 0, pnl: 0, config: {} },
  { id: "flash_crash", name: "Flash Crash", description: "Buy crashed crypto tokens.", icon: AlertTriangle, enabled: true, color: "orange", positions: 0, pnl: 0, config: {} },
  { id: "whale_copy", name: "Whale Copy", description: "Follow top 7.6% profitable wallets.", icon: Users, enabled: true, color: "emerald", positions: 0, pnl: 0, config: {} },
];

const strategyDotColors: Record<string, string> = {
  weather_arb: "bg-cyan-500", near_certainty: "bg-violet-500", same_market_arb: "bg-amber-500",
  cross_market_arb: "bg-rose-500", market_making: "bg-blue-500", flash_crash: "bg-orange-500",
  whale_copy: "bg-emerald-500", logical_implication: "bg-purple-500", no_position_scanner: "bg-teal-500",
  adaptive_threshold: "bg-indigo-500", wallet_divergence: "bg-lime-500",
};

const strategyLabels: Record<string, string> = {
  weather_arb: "Weather", near_certainty: "Near-Certainty", same_market_arb: "Same-Mkt",
  cross_market_arb: "Cross-Mkt", market_making: "MM", flash_crash: "Flash Crash",
  whale_copy: "Whale", logical_implication: "Logical", no_position_scanner: "No Pos",
  adaptive_threshold: "Adaptive", wallet_divergence: "Wallet Div",
};

// ----------------------------------------------------------------
// Small Components
// ----------------------------------------------------------------

function ProgressBar({ value, max = 1, color = "bg-primary" }: { value: number; max?: number; color?: string }) {
  const pct = Math.min((value / max) * 100, 100);
  return (
    <div className="h-1 rounded-full bg-muted overflow-hidden">
      <div className={cn("h-full rounded-full transition-all duration-700", color)} style={{ width: `${pct}%` }} />
    </div>
  );
}

function StatCard({ label, value, color, icon: Icon, sub }: {
  label: string; value: string; color: string; icon: any; sub?: string | null;
}) {
  return (
    <div className="glass-card p-4">
      <div className="flex items-center gap-1.5 mb-2">
        <Icon className="w-3.5 h-3.5 text-muted-foreground" />
        <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">{label}</span>
      </div>
      <p className={cn("text-xl font-bold tabular-nums tracking-tight", color)}>{value}</p>
      {sub && <p className="text-[10px] text-muted-foreground mt-0.5">{sub}</p>}
    </div>
  );
}

function Toast({ message, type }: { message: string; type: "success" | "error" | "info" }) {
  const icons = { success: CheckCircle2, error: XCircle, info: Activity };
  const colors = { success: "text-green-500", error: "text-red-500", info: "text-primary" };
  const Icon = icons[type];
  return (
    <div className="fixed bottom-6 right-6 z-50 toast-in">
      <div className="glass-card px-4 py-3 flex items-center gap-2 shadow-lg border border-border">
        <Icon className={cn("w-4 h-4", colors[type])} />
        <span className="text-sm text-foreground">{message}</span>
      </div>
    </div>
  );
}

// ----------------------------------------------------------------
// Component
// ----------------------------------------------------------------

export default function PredictionsPage() {
  const [strategies, setStrategies] = useState<StrategyConfig[]>(DEFAULT_STRATEGIES);
  const [markets, setMarkets] = useState<PredictionMarket[]>([]);
  const [opportunities, setOpportunities] = useState<Opportunity[]>([]);
  const [livePositions, setLivePositions] = useState<Position[]>([]);
  const [activeTab, setActiveTab] = useState<"scanner" | "analysis" | "markets" | "positions" | "portfolio">("scanner");
  const [scanning, setScanning] = useState(false);
  const [scanLoading, setScanLoading] = useState(false);
  const [scanCount, setScanCount] = useState(0);
  const [lastScan, setLastScan] = useState<string>("Never");
  const [searchQuery, setSearchQuery] = useState("");
  const [exchangeFilter] = useState<"all" | "polymarket">("all");
  const [isLive, setIsLive] = useState(false);
  const [loading, setLoading] = useState(true);
  const [botRunning, setBotRunning] = useState(false);
  const [botStatus, setBotStatus] = useState<any>(null);
  const [analysisLog, setAnalysisLog] = useState<any[]>([]);
  const [equityCurve, setEquityCurve] = useState<any[]>([]);
  const [portfolioSummary, setPortfolioSummary] = useState<any>(null);
  const [polyStatus, setPolyStatus] = useState<any>({ connected: null });
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [toast, setToast] = useState<{ message: string; type: "success" | "error" | "info" } | null>(null);
  const streamRef = useRef<HTMLDivElement>(null);
  const analysisRef = useRef<HTMLDivElement>(null);

  const showToast = (message: string, type: "success" | "error" | "info" = "info") => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 3000);
  };

  // ----------------------------------------------------------------
  // API Helpers
  // ----------------------------------------------------------------

  const mapMarket = (m: any): PredictionMarket => ({
    id: m.id || m.condition_id, question: m.question, category: m.category || "Unknown",
    outcomes: (m.outcomes || []).map((o: any) => ({ label: o.label, price: o.price || o.midpoint || 0, tokenId: o.token_id })),
    volume: m.total_volume || 0, liquidity: m.liquidity || 0, endDate: m.end_date || "",
    active: m.active ?? true, exchange: m.exchange || "polymarket",
  });

  const mapOpportunity = (opp: any): Opportunity => ({
    id: opp.id || `${opp.strategy}-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
    strategy: opp.strategy, market: opp.market || opp.market_question || "",
    side: opp.side || "BUY", entryPrice: opp.entry_price || opp.price || 0,
    edge: opp.edge || 0, confidence: opp.confidence || 0,
    reason: opp.reason || "", timestamp: opp.timestamp || new Date().toLocaleTimeString(),
  });

  const fetchStrategies = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/prediction-markets/strategies`);
      if (!res.ok) return;
      const data = await res.json();
      if (data.strategies?.length > 0) {
        setStrategies((prev) => prev.map((s) => {
          const live = data.strategies.find((ls: any) => ls.name === s.id);
          return live ? { ...s, positions: live.positions || 0, pnl: live.total_pnl || 0 } : s;
        }));
        setScanCount(data.total_scans || 0);
        setIsLive(true);
      }
    } catch {}
  };

  const fetchMarkets = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/prediction-markets/markets?limit=50`);
      if (!res.ok) return;
      const data = await res.json();
      if (data.markets?.length > 0) { setMarkets(data.markets.map(mapMarket)); setIsLive(true); }
    } catch {}
  };

  const runScan = async () => {
    setScanLoading(true);
    addLog("scan", "Starting scan across all enabled strategies...");
    try {
      const res = await fetch(`${API_BASE}/api/prediction-markets/bot/scan-now`, { method: "POST" });
      if (!res.ok) throw new Error("Scan failed");
      const data = await res.json();
      if (data.bot_running) {
        setBotRunning(true);
        addLog("info", "Bot loop auto-started — scans will repeat automatically");
      }
      setScanCount(data.total_scans || scanCount + 1);
      setLastScan(new Date().toLocaleTimeString());
      setIsLive(true);
      showToast("Scan queued successfully", "success");
      addLog("scan", `Scan queued (background). Bot running: ${data.bot_running}`);
      setTimeout(async () => {
        try { await Promise.all([fetchBotOpportunities(), fetchPositions(), fetchStrategies()]); } catch {}
      }, 3000);
    } catch {
      try {
        const res = await fetch(`${API_BASE}/api/prediction-markets/scan`, { method: "POST" });
        if (res.ok) {
          const data = await res.json();
          if (data.opportunities?.length > 0) setOpportunities(data.opportunities.map(mapOpportunity));
          setScanCount(data.scan_number || scanCount + 1);
          setLastScan(new Date().toLocaleTimeString());
          showToast(`Found ${data.opportunities?.length || 0} opportunities`, "success");
        }
      } catch {
        addLog("info", "Scan failed (API unavailable)");
        showToast("Scan failed — API unavailable", "error");
      }
    } finally {
      setScanLoading(false);
    }
  };

  const fetchBotStatus = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/prediction-markets/bot/status`);
      if (res.ok) {
        const data = await res.json();
        setBotStatus(data);
        setBotRunning(data.running);
        setIsLive(true);
        setLastUpdated(new Date());
        if (data.activity_log?.length > 0) mergeActivityLog(data.activity_log);
        if (data.total_scans) setScanCount(data.total_scans);
      }
    } catch {}
  };

  const fetchPositions = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/prediction-markets/portfolio`);
      if (res.ok) {
        const data = await res.json();
        setPortfolioSummary(data);
        if (data.positions?.length > 0) {
          setLivePositions(data.positions.map((p: any, i: number) => ({
            id: String(i), market: p.market_question || p.market_id,
            outcome: p.outcome_label || p.token_id, side: p.side === "long" ? "BUY" : "SELL",
            entryPrice: p.avg_entry_price, currentPrice: p.current_price,
            size: p.market_value, pnl: p.total_pnl, strategy: p.strategy,
            openedAt: p.opened_at ? new Date(p.opened_at).toLocaleTimeString() : "",
          })));
        }
      }
    } catch {}
  };

  const fetchEquityCurve = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/prediction-markets/pnl-history?limit=200`);
      if (res.ok) { const data = await res.json(); setEquityCurve(data.snapshots || []); }
    } catch {}
  };

  const fetchBotOpportunities = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/prediction-markets/bot/activity?limit=50`);
      if (res.ok) {
        const data = await res.json();
        if (data.entries?.length > 0) mergeActivityLog(data.entries);
        if (data.total_scans) setScanCount(data.total_scans);
        if (data.opportunities?.length > 0) {
          setOpportunities(data.opportunities.map(mapOpportunity));
          setIsLive(true);
          setLastScan(new Date().toLocaleTimeString());
        }
      }
    } catch {}
  };

  const mergeActivityLog = (entries: any[]) => {
    setAnalysisLog((prev) => {
      const existingIds = new Set(prev.map((e: any) => e.id));
      const newEntries = entries
        .filter((e: any) => !existingIds.has(e.id))
        .map((e: any) => ({
          ...e,
          timestamp: e.timestamp ? new Date(e.timestamp).toLocaleTimeString() : new Date().toLocaleTimeString(),
        }));
      if (newEntries.length === 0) return prev;
      return [...newEntries, ...prev].slice(0, 200);
    });
  };

  const addLog = (type: "scan" | "signal" | "execute" | "skip" | "info", message: string, strategy?: string) => {
    setAnalysisLog((prev) => [{
      id: `local-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
      timestamp: new Date().toLocaleTimeString(), type, strategy, message,
    }, ...prev].slice(0, 200));
  };

  const resetPortfolio = async () => {
    if (!confirm("Reset all paper trading positions and P&L?")) return;
    // SIDE-EFFECT INTEGRITY: only clear the UI + claim "reset" if the backend reset
    // ACTUALLY succeeded. Never optimistically show success for an op we can't verify.
    try {
      const res = await fetch(`${API_BASE}/api/prediction-markets/portfolio/reset`, { method: "POST" });
      if (!res.ok) throw new Error(`reset failed (${res.status})`);
    } catch {
      showToast("Reset failed — backend unreachable; nothing was reset", "error");
      return; // do NOT wipe the UI or claim success when the effect didn't happen
    }
    // Reset truly succeeded — now reflect it.
    setStrategies(DEFAULT_STRATEGIES.map(s => ({ ...s, positions: 0, pnl: 0 })));
    setOpportunities([]); setLivePositions([]); setEquityCurve([]);
    setPortfolioSummary(null); setScanCount(0); setAnalysisLog([]);
    addLog("info", "Portfolio reset.");
    showToast("Portfolio reset", "success");
    // Re-pull from the backend so the panel reflects the real post-reset state.
    try { await Promise.all([fetchPositions(), fetchStrategies()]); } catch {}
  };

  const checkPolymarketConnection = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/prediction-markets/status`);
      if (res.ok) { const data = await res.json(); setPolyStatus(data); }
    } catch { setPolyStatus({ connected: false }); }
  };

  const toggleBot = async () => {
    // SIDE-EFFECT INTEGRITY: only flip state + claim started/stopped if the request
    // ACTUALLY succeeded. A failed stop must NOT show "Bot stopped" while it keeps running.
    try {
      if (botRunning) {
        const res = await fetch(`${API_BASE}/api/prediction-markets/bot/stop`, { method: "POST" });
        if (res.ok) {
          setBotRunning(false);
          addLog("info", "Bot stopped");
          showToast("Bot stopped", "info");
        } else {
          showToast("Failed to stop bot — it may still be running", "error");
        }
      } else {
        const res = await fetch(`${API_BASE}/api/prediction-markets/bot/start`, { method: "POST" });
        if (res.ok) {
          setBotRunning(true);
          addLog("info", "Bot started — automated scan → execute loop running every 120s");
          showToast("Bot started", "success");
        } else {
          showToast("Failed to start bot", "error");
        }
      }
      await fetchBotStatus(); // re-sync to the real bot state regardless
    } catch {
      showToast("Bot action failed — backend unreachable", "error");
    }
  };

  // ----------------------------------------------------------------
  // Effects
  // ----------------------------------------------------------------

  useEffect(() => {
    const init = async () => {
      await checkPolymarketConnection();
      await fetchBotStatus();
      await fetchPositions();
      await fetchBotOpportunities();
      await fetchMarkets();
      await fetchStrategies();
      setLoading(false);
    };
    init();
  }, []);

  useEffect(() => {
    if (activeTab === "portfolio") { fetchPositions(); fetchEquityCurve(); }
    else if (activeTab === "positions") { fetchPositions(); fetchStrategies(); }
    else if (activeTab === "analysis" || activeTab === "scanner") fetchBotOpportunities();
  }, [activeTab]);

  useEffect(() => {
    if (!isLive) return;
    const interval = setInterval(async () => {
      try { await fetchBotStatus(); } catch {}
      try { await fetchPositions(); } catch {}
      if (activeTab === "analysis" || activeTab === "scanner") {
        try { await fetchBotOpportunities(); } catch {}
      }
    }, 45000);
    return () => clearInterval(interval);
  }, [activeTab, isLive]);

  const toggleStrategy = (id: string) => {
    setStrategies((prev) => prev.map((s) => (s.id === id ? { ...s, enabled: !s.enabled } : s)));
  };

  // ----------------------------------------------------------------
  // Derived State
  // ----------------------------------------------------------------

  const positionCount = livePositions.length;
  const totalPnl = portfolioSummary?.total_pnl ?? strategies.reduce((sum, s) => sum + s.pnl, 0);
  const unrealizedPnl = useMemo(() => livePositions.reduce((s, p) => s + p.pnl, 0), [livePositions]);
  const enabledCount = strategies.filter((s) => s.enabled).length;
  const effectiveScanCount = botStatus?.total_scans || scanCount;
  const lastScanOpps = botStatus?.last_scan_opportunities || 0;
  const filteredMarkets = markets.filter((m) =>
    (exchangeFilter === "all" || m.exchange === exchangeFilter) &&
    (!searchQuery || m.question.toLowerCase().includes(searchQuery.toLowerCase()) || m.category.toLowerCase().includes(searchQuery.toLowerCase()))
  );

  const equityBounds = useMemo(() => {
    if (equityCurve.length === 0) return { min: 0, max: 100, range: 1 };
    const values = equityCurve.map((x: any) => x.total_value_usd || 100);
    const min = Math.min(...values);
    const max = Math.max(...values);
    return { min, max, range: max - min || 1 };
  }, [equityCurve]);

  const timeAgo = lastUpdated
    ? `${Math.round((Date.now() - lastUpdated.getTime()) / 1000)}s ago`
    : null;

  // ----------------------------------------------------------------
  // Render
  // ----------------------------------------------------------------

  return (
    <div className="min-h-screen">
      {/* Toast */}
      {toast && <Toast message={toast.message} type={toast.type} />}

      {/* Header */}
      <div className="sticky top-0 z-30 bg-card/90 backdrop-blur-xl border-b border-border/60">
        <div className="px-6 lg:px-8">
          <div className="flex items-center justify-between h-14">
            <div className="flex items-center gap-3">
              <h1 className="text-sm font-bold text-foreground">Predictions</h1>
              {polyStatus.connected ? (
                <span className="flex items-center gap-1 text-[10px] font-medium text-green-500">
                  <span className="status-dot live" />
                  Live
                </span>
              ) : polyStatus.connected === false ? (
                <span className="flex items-center gap-1 text-[10px] font-medium text-muted-foreground">
                  <span className="status-dot offline" />
                  Offline
                </span>
              ) : null}
              {lastUpdated && (
                <span className="text-[10px] text-muted-foreground tabular-nums font-mono">
                  <Clock className="w-2.5 h-2.5 inline mr-0.5 -mt-px" />
                  {timeAgo}
                </span>
              )}
            </div>

            <div className="flex items-center gap-2">
              <button onClick={resetPortfolio} className="px-2.5 py-1.5 rounded-lg text-[11px] font-medium text-muted-foreground hover:text-red-500 hover:bg-red-500/10 transition-colors">
                Reset
              </button>
              <div className="w-px h-4 bg-border" />
              <button
                onClick={runScan} disabled={scanLoading}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-semibold bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-50 transition-opacity"
              >
                {scanLoading ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
                {scanLoading ? "Scanning..." : "Scan + Execute"}
              </button>
              <button
                onClick={toggleBot}
                className={cn(
                  "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-semibold border transition-colors",
                  botRunning
                    ? "bg-green-500/10 text-green-500 border-green-500/20"
                    : "bg-muted text-muted-foreground border-border hover:text-foreground"
                )}
              >
                {botRunning ? (
                  <><span className="w-1.5 h-1.5 rounded-full bg-green-500 pulse-live" /> Bot On</>
                ) : (
                  <><Bot className="w-3 h-3" /> Bot Off</>
                )}
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Scanning progress banner */}
      {scanLoading && (
        <div className="bg-primary">
          <div className="px-6 lg:px-8 py-2 flex items-center gap-2">
            <Loader2 className="w-3 h-3 text-primary-foreground animate-spin" />
            <span className="text-[11px] font-medium text-primary-foreground/90">
              Scanning {enabledCount} strategies across Polymarket... This takes ~2 minutes.
            </span>
          </div>
          <div className="h-0.5 bg-primary-foreground/20 overflow-hidden">
            <div className="h-full w-1/3 bg-primary-foreground/40 rounded-full progress-indeterminate" />
          </div>
        </div>
      )}

      <div className="px-6 lg:px-8 py-5">
        {/* Stats Row */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-5 stagger-children">
          {loading ? (
            Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="glass-card p-4 space-y-2">
                <div className="skeleton h-3 w-20" />
                <div className="skeleton h-6 w-24" />
              </div>
            ))
          ) : (
            <>
              <StatCard label="Total P&L" value={`${totalPnl >= 0 ? "+" : ""}$${totalPnl.toFixed(2)}`}
                color={totalPnl >= 0 ? "text-green-500" : "text-red-500"} icon={DollarSign}
                sub={portfolioSummary?.total_exposure ? `$${portfolioSummary.total_exposure.toFixed(2)} exposure` : null} />
              <StatCard label="Open Positions" value={String(positionCount)} color="text-foreground" icon={Activity}
                sub={positionCount > 0 ? `${new Set(livePositions.map(p => p.strategy)).size} strategies` : null} />
              <StatCard label="Strategies" value={`${enabledCount}/${strategies.length}`} color="text-foreground" icon={Zap}
                sub={botRunning ? "Bot running" : "Bot idle"} />
              <StatCard label="Scans" value={String(effectiveScanCount)} color="text-foreground" icon={BarChart3}
                sub={lastScanOpps > 0 ? `${lastScanOpps} opps last scan` : null} />
            </>
          )}
        </div>

        {/* Strategy Strip */}
        <div className="flex gap-1.5 mb-5 overflow-x-auto pb-1">
          {strategies.map((strategy) => {
            const dotColor = strategyDotColors[strategy.id] || "bg-gray-500";
            return (
              <button key={strategy.id} onClick={() => toggleStrategy(strategy.id)}
                className={cn(
                  "flex-shrink-0 flex items-center gap-2 px-3 py-2 rounded-xl border text-left transition-all",
                  strategy.enabled
                    ? "glass-card hover:border-primary/30"
                    : "border-border bg-muted/30 opacity-40"
                )}
              >
                <div className={cn("w-2 h-2 rounded-full flex-shrink-0", dotColor, !strategy.enabled && "opacity-40")} />
                <div className="min-w-0">
                  <span className="text-[11px] font-semibold text-foreground whitespace-nowrap">{strategy.name}</span>
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] text-muted-foreground tabular-nums">{strategy.positions} pos</span>
                    <span className={cn("text-[10px] font-semibold tabular-nums", strategy.pnl >= 0 ? "text-green-500" : "text-red-500")}>
                      {strategy.pnl >= 0 ? "+" : ""}${strategy.pnl.toFixed(2)}
                    </span>
                  </div>
                </div>
              </button>
            );
          })}
        </div>

        {/* Tabs */}
        <div className="flex items-center gap-0.5 mb-5 border-b border-border/60">
          {([
            { key: "scanner" as const, label: "Scanner", dot: botRunning },
            { key: "analysis" as const, label: "Analysis", dot: analysisLog.length > 0 },
            { key: "markets" as const, label: "Markets" },
            { key: "positions" as const, label: positionCount > 0 ? `Positions (${positionCount})` : "Positions" },
            { key: "portfolio" as const, label: "Portfolio" },
          ]).map((tab) => (
            <button key={tab.key} onClick={() => setActiveTab(tab.key)}
              className={cn(
                "px-4 py-2.5 text-xs font-medium border-b-2 -mb-px transition-colors",
                activeTab === tab.key
                  ? "border-primary text-foreground"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              )}
            >
              {tab.label}
              {tab.dot && <span className="inline-block w-1.5 h-1.5 rounded-full bg-primary ml-1.5 -mt-1 pulse-live" />}
            </button>
          ))}
        </div>

        {/* ============ SCANNER ============ */}
        {activeTab === "scanner" && (
          <div className="space-y-4 fade-in">
            {botRunning && botStatus && (
              <div className="glass-card p-4">
                <div className="flex items-center gap-6 flex-wrap">
                  <div className="flex items-center gap-2">
                    <span className="status-dot live" />
                    <span className="text-[11px] font-semibold text-foreground">Bot Running</span>
                  </div>
                  <div className="flex items-center gap-4 text-[11px] tabular-nums">
                    <span className="text-muted-foreground">Scans <span className="font-semibold text-foreground">{botStatus.total_scans || 0}</span></span>
                    <span className="text-muted-foreground">Executions <span className="font-semibold text-foreground">{botStatus.total_executions || 0}</span></span>
                    <span className="text-muted-foreground">Positions <span className="font-semibold text-foreground">{botStatus.portfolio?.total_positions || positionCount}</span></span>
                    {botStatus.risk_manager && (
                      <>
                        <span className="text-muted-foreground">Daily P&L{" "}
                          <span className={cn("font-semibold", (botStatus.risk_manager.daily_pnl || 0) >= 0 ? "text-green-500" : "text-red-500")}>
                            ${(botStatus.risk_manager.daily_pnl || 0).toFixed(2)}
                          </span>
                        </span>
                        <span className="text-muted-foreground">Circuit{" "}
                          <span className={cn("font-semibold", botStatus.risk_manager.circuit_breaker_active ? "text-red-500" : "text-green-500")}>
                            {botStatus.risk_manager.circuit_breaker_active ? "TRIPPED" : "OK"}
                          </span>
                        </span>
                      </>
                    )}
                  </div>
                </div>
              </div>
            )}

            <div className="glass-card overflow-hidden">
              <div className="px-5 py-3 border-b border-border/60 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="status-dot live" />
                  <span className="text-sm font-semibold text-foreground">Opportunity Stream</span>
                  {opportunities.length > 0 && (
                    <span className="text-[10px] text-muted-foreground tabular-nums px-1.5 py-0.5 bg-muted rounded-md font-bold">{opportunities.length}</span>
                  )}
                </div>
                <button onClick={runScan} disabled={scanLoading}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-semibold bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-50"
                >
                  {scanLoading ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
                  {scanLoading ? "Scanning..." : "Scan + Execute"}
                </button>
              </div>
              <div ref={streamRef} className="max-h-[520px] overflow-y-auto">
                {opportunities.length > 0 ? opportunities.map((opp, i) => {
                  const dotColor = strategyDotColors[opp.strategy] || "bg-gray-500";
                  return (
                    <div key={opp.id} className="px-5 py-3 border-b border-border/20 hover:bg-muted/20 transition-colors fade-in" style={{ animationDelay: `${i * 40}ms` }}>
                      <div className="flex items-start justify-between gap-4">
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-1.5 mb-1">
                            <span className="flex items-center gap-1 text-[10px] font-semibold px-1.5 py-0.5 rounded-md bg-muted text-muted-foreground">
                              <span className={cn("w-1.5 h-1.5 rounded-full", dotColor)} />
                              {strategyLabels[opp.strategy] || opp.strategy}
                            </span>
                            <span className={cn(
                              "text-[10px] font-semibold px-1.5 py-0.5 rounded-md",
                              opp.side === "BUY" ? "bg-green-500/10 text-green-500" : "bg-red-500/10 text-red-500"
                            )}>{opp.side}</span>
                            <span className="text-[10px] text-muted-foreground tabular-nums font-mono">{opp.timestamp}</span>
                          </div>
                          <p className="text-xs text-foreground font-medium truncate">{opp.market}</p>
                          <p className="text-[11px] text-muted-foreground mt-0.5 line-clamp-1">{opp.reason}</p>
                        </div>
                        <div className="text-right flex-shrink-0 w-20">
                          <p className="text-lg font-bold text-green-500 tabular-nums leading-tight">
                            {(opp.edge * 100).toFixed(1)}%
                          </p>
                          <div className="flex items-center gap-1 mt-1 justify-end">
                            <div className="w-12 h-1 bg-muted rounded-full overflow-hidden">
                              <div className="h-full bg-primary rounded-full transition-all duration-500" style={{ width: `${opp.confidence * 100}%` }} />
                            </div>
                            <span className="text-[10px] text-muted-foreground tabular-nums">{(opp.confidence * 100).toFixed(0)}%</span>
                          </div>
                        </div>
                      </div>
                    </div>
                  );
                }) : (
                  <div className="py-20 text-center fade-in">
                    <div className="w-12 h-12 rounded-2xl bg-muted flex items-center justify-center mx-auto mb-3">
                      <Radio className="w-6 h-6 text-muted-foreground" />
                    </div>
                    <p className="text-sm text-foreground font-medium">No signals yet</p>
                    <p className="text-xs text-muted-foreground mt-1 mb-4">Run a scan to find opportunities across Polymarket</p>
                    <button onClick={runScan} disabled={scanLoading}
                      className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-xs font-semibold bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-50"
                    >
                      {scanLoading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
                      {scanLoading ? "Scanning..." : "Scan + Execute"}
                    </button>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        {/* ============ ANALYSIS ============ */}
        {activeTab === "analysis" && (
          <div className="glass-card overflow-hidden fade-in">
            <div className="px-5 py-3 border-b border-border/60 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="status-dot live" />
                <span className="text-sm font-semibold text-foreground">Live Analysis</span>
                <span className="text-[10px] text-muted-foreground tabular-nums px-1.5 py-0.5 bg-muted rounded-md font-bold">{analysisLog.length}</span>
              </div>
              <div className="flex items-center gap-2">
                <button onClick={fetchBotOpportunities} className="flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground transition-colors">
                  <RotateCw className="w-3 h-3" /> Refresh
                </button>
                <button onClick={() => setAnalysisLog([])} className="text-[11px] text-muted-foreground hover:text-foreground transition-colors">Clear</button>
              </div>
            </div>
            <div ref={analysisRef} className="max-h-[600px] overflow-y-auto">
              {analysisLog.length > 0 ? analysisLog.map((entry) => {
                const types: Record<string, { bg: string; label: string }> = {
                  scan: { bg: "bg-blue-500/10 text-blue-400", label: "SCAN" },
                  signal: { bg: "bg-green-500/10 text-green-400", label: "SIGNAL" },
                  execute: { bg: "bg-primary/10 text-primary", label: "EXEC" },
                  skip: { bg: "bg-muted text-muted-foreground", label: "SKIP" },
                  info: { bg: "bg-amber-500/10 text-amber-400", label: "INFO" },
                };
                const t = types[entry.type] || types.info;
                const dotColor = entry.strategy ? strategyDotColors[entry.strategy] : null;
                return (
                  <div key={entry.id} className="px-5 py-2 border-b border-border/20 hover:bg-muted/20 transition-colors">
                    <div className="flex items-start gap-2">
                      <span className="text-[10px] text-muted-foreground tabular-nums whitespace-nowrap mt-0.5 w-[60px] flex-shrink-0 font-mono">{entry.timestamp}</span>
                      <span className={cn("text-[10px] font-semibold px-1.5 py-0.5 rounded-md whitespace-nowrap", t.bg)}>{t.label}</span>
                      {dotColor && (
                        <span className="flex items-center gap-1 text-[10px] font-semibold px-1.5 py-0.5 rounded-md bg-muted text-muted-foreground whitespace-nowrap">
                          <span className={cn("w-1.5 h-1.5 rounded-full", dotColor)} />
                          {strategyLabels[entry.strategy!] || entry.strategy}
                        </span>
                      )}
                      <p className="text-[11px] text-foreground/80 leading-relaxed min-w-0">{entry.message}</p>
                    </div>
                  </div>
                );
              }) : (
                <div className="py-20 text-center fade-in">
                  <div className="w-12 h-12 rounded-2xl bg-muted flex items-center justify-center mx-auto mb-3">
                    <Eye className="w-6 h-6 text-muted-foreground" />
                  </div>
                  <p className="text-sm text-foreground font-medium">No analysis entries</p>
                  <p className="text-xs text-muted-foreground mt-1 mb-4">Run a scan or start the bot to see live rationales</p>
                  <button onClick={runScan} disabled={scanLoading}
                    className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-xs font-semibold bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-50"
                  >
                    {scanLoading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
                    {scanLoading ? "Scanning..." : "Run First Scan"}
                  </button>
                </div>
              )}
            </div>
          </div>
        )}

        {/* ============ MARKETS ============ */}
        {activeTab === "markets" && (
          <div className="glass-card overflow-hidden fade-in">
            <div className="px-5 py-3 border-b border-border/60">
              <div className="flex items-center gap-3">
                <div className="relative flex-1">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground" />
                  <input type="text" placeholder="Search markets..." value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    className="w-full pl-9 pr-4 py-2 bg-muted/50 rounded-lg text-xs text-foreground placeholder-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/20 border border-border" />
                </div>
                <span className="text-[10px] font-bold text-muted-foreground tabular-nums px-2 py-1 bg-muted rounded-md">{filteredMarkets.length}</span>
              </div>
            </div>
            <div className="max-h-[600px] overflow-y-auto">
              {filteredMarkets.map((market) => (
                <div key={market.id} className="px-5 py-3 border-b border-border/20 hover:bg-muted/20 transition-colors">
                  <div className="flex items-start justify-between mb-2">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-1.5 mb-0.5">
                        <span className="text-[10px] font-medium px-1.5 py-0.5 rounded-md bg-muted text-muted-foreground">{market.category}</span>
                        {market.endDate && <span className="text-[10px] text-muted-foreground">Ends {new Date(market.endDate).toLocaleDateString()}</span>}
                      </div>
                      <p className="text-xs font-medium text-foreground">{market.question}</p>
                    </div>
                    <div className="text-right ml-4 flex-shrink-0 text-[10px] text-muted-foreground tabular-nums">
                      <p>${(market.volume / 1e6).toFixed(1)}M vol</p>
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {market.outcomes.map((o, i) => (
                      <div key={i} className="flex items-center gap-1.5 px-2 py-1 rounded-lg bg-muted/50 border border-border/60">
                        <span className="text-[11px] text-muted-foreground">{o.label}</span>
                        <span className={cn("text-[11px] font-bold tabular-nums", o.price >= 0.5 ? "text-green-500" : "text-foreground")}>
                          {(o.price * 100).toFixed(0)}c
                        </span>
                        <div className="w-8 h-1 bg-muted rounded-full overflow-hidden">
                          <div className={cn("h-full rounded-full", o.price >= 0.5 ? "bg-green-500" : "bg-muted-foreground/40")} style={{ width: `${o.price * 100}%` }} />
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ============ POSITIONS ============ */}
        {activeTab === "positions" && (
          <div className="glass-card overflow-hidden fade-in">
            <div className="px-5 py-3 border-b border-border/60 flex items-center justify-between">
              <span className="text-sm font-semibold text-foreground">{positionCount} Open Positions</span>
              <span className={cn("text-sm font-bold tabular-nums", unrealizedPnl >= 0 ? "text-green-500" : "text-red-500")}>
                Unrealized: {unrealizedPnl >= 0 ? "+" : ""}${unrealizedPnl.toFixed(2)}
              </span>
            </div>
            {livePositions.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead className="bg-muted/50">
                    <tr>
                      {["Market", "Strategy", "Side", "Entry", "Current", "Size", "P&L"].map((h) => (
                        <th key={h} className="text-left text-[10px] font-semibold text-muted-foreground uppercase tracking-wider py-2.5 px-4">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {livePositions.map((pos) => {
                      const dotColor = strategyDotColors[pos.strategy] || "bg-gray-500";
                      return (
                        <tr key={pos.id} className="border-b border-border/20 hover:bg-muted/20 transition-colors">
                          <td className="py-3 px-4">
                            <p className="text-xs font-medium text-foreground truncate max-w-[280px]">{pos.market}</p>
                            <p className="text-[10px] text-muted-foreground">{pos.outcome}</p>
                          </td>
                          <td className="py-3 px-4">
                            <span className="flex items-center gap-1 text-[10px] font-semibold px-1.5 py-0.5 rounded-md bg-muted text-muted-foreground w-fit">
                              <span className={cn("w-1.5 h-1.5 rounded-full", dotColor)} />
                              {strategyLabels[pos.strategy] || pos.strategy}
                            </span>
                          </td>
                          <td className="py-3 px-4">
                            <span className={cn("text-[11px] font-semibold", pos.side === "BUY" ? "text-green-500" : "text-red-500")}>{pos.side}</span>
                          </td>
                          <td className="py-3 px-4 tabular-nums font-mono text-foreground">${pos.entryPrice.toFixed(2)}</td>
                          <td className="py-3 px-4 tabular-nums font-mono text-foreground">${pos.currentPrice.toFixed(2)}</td>
                          <td className="py-3 px-4 tabular-nums font-mono text-foreground">${pos.size.toFixed(2)}</td>
                          <td className="py-3 px-4">
                            <span className={cn("font-semibold tabular-nums font-mono", pos.pnl >= 0 ? "text-green-500" : "text-red-500")}>
                              {pos.pnl >= 0 ? "+" : ""}${pos.pnl.toFixed(2)}
                            </span>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="py-20 text-center fade-in">
                <div className="w-12 h-12 rounded-2xl bg-muted flex items-center justify-center mx-auto mb-3">
                  <Layers className="w-6 h-6 text-muted-foreground" />
                </div>
                <p className="text-sm text-foreground font-medium">No open positions</p>
                <p className="text-xs text-muted-foreground mt-1 mb-4">Run a scan to find and execute trades</p>
                <button onClick={runScan} disabled={scanLoading}
                  className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-xs font-semibold bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-50"
                >
                  {scanLoading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
                  Scan + Execute
                </button>
              </div>
            )}
          </div>
        )}

        {/* ============ PORTFOLIO ============ */}
        {activeTab === "portfolio" && (
          <div className="space-y-4 fade-in">
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 stagger-children">
              {[
                { l: "Total Value", v: `$${portfolioSummary?.total_exposure?.toFixed(2) || "0.00"}`, c: "text-foreground" },
                { l: "Total P&L", v: `${(portfolioSummary?.total_pnl || 0) >= 0 ? "+" : ""}$${(portfolioSummary?.total_pnl || 0).toFixed(2)}`, c: (portfolioSummary?.total_pnl || 0) >= 0 ? "text-green-500" : "text-red-500" },
                { l: "Fees", v: `$${portfolioSummary?.total_fees?.toFixed(2) || "0.00"}`, c: "text-foreground" },
                { l: "Orders", v: String(portfolioSummary?.total_orders || 0), c: "text-foreground" },
              ].map((i) => (
                <div key={i.l} className="glass-card p-4">
                  <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">{i.l}</span>
                  <p className={cn("text-xl font-bold tabular-nums mt-1", i.c)}>{i.v}</p>
                </div>
              ))}
            </div>

            <div className="glass-card p-5">
              <h2 className="text-sm font-semibold text-foreground mb-4">Equity Curve</h2>
              {equityCurve.length > 0 ? (
                <div className="h-44 flex items-end gap-px">
                  {equityCurve.map((s: any, i: number) => {
                    const height = ((s.total_value_usd - equityBounds.min) / equityBounds.range) * 100;
                    const isPositive = (s.unrealized_pnl + s.realized_pnl) >= 0;
                    return (
                      <div key={i} className={cn("flex-1 rounded-t transition-all hover:opacity-70", isPositive ? "bg-green-500/70" : "bg-red-500/70")}
                        style={{ height: `${Math.max(height, 2)}%` }}
                        title={`$${s.total_value_usd?.toFixed(2)} | ${new Date(s.snapshot_at).toLocaleString()}`} />
                    );
                  })}
                </div>
              ) : (
                <div className="h-44 flex items-center justify-center">
                  <div className="text-center">
                    <div className="w-12 h-12 rounded-2xl bg-muted flex items-center justify-center mx-auto mb-3">
                      <TrendingUp className="w-6 h-6 text-muted-foreground" />
                    </div>
                    <p className="text-xs text-muted-foreground">Start the bot to build an equity curve</p>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="px-6 lg:px-8 py-3">
        <div className="flex items-center gap-1.5 text-[10px] text-muted-foreground/60">
          <Shield className="w-3 h-3" />
          Paper trading (dry_run). {isLive ? "Connected to Polymarket." : "Backend offline."}
        </div>
      </div>
    </div>
  );
}
