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
  Pause,
  Play,
  ArrowLeftRight,
  Users,
  Radio,
  Eye,
  Layers,
  Wallet,
  Bot,
  RotateCw,
  TrendingUp,
  Clock,
} from "lucide-react";

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

const strategyColors: Record<string, { border: string; bg: string; text: string; badge: string; dot: string }> = {
  weather_arb: { border: "border-cyan-200", bg: "bg-cyan-50/40", text: "text-cyan-600", badge: "bg-cyan-100 text-cyan-700", dot: "bg-cyan-500" },
  near_certainty: { border: "border-violet-200", bg: "bg-violet-50/40", text: "text-violet-600", badge: "bg-violet-100 text-violet-700", dot: "bg-violet-500" },
  same_market_arb: { border: "border-amber-200", bg: "bg-amber-50/40", text: "text-amber-600", badge: "bg-amber-100 text-amber-700", dot: "bg-amber-500" },
  cross_market_arb: { border: "border-rose-200", bg: "bg-rose-50/40", text: "text-rose-600", badge: "bg-rose-100 text-rose-700", dot: "bg-rose-500" },
  market_making: { border: "border-blue-200", bg: "bg-blue-50/40", text: "text-blue-600", badge: "bg-blue-100 text-blue-700", dot: "bg-blue-500" },
  flash_crash: { border: "border-orange-200", bg: "bg-orange-50/40", text: "text-orange-600", badge: "bg-orange-100 text-orange-700", dot: "bg-orange-500" },
  whale_copy: { border: "border-emerald-200", bg: "bg-emerald-50/40", text: "text-emerald-600", badge: "bg-emerald-100 text-emerald-700", dot: "bg-emerald-500" },
  logical_implication: { border: "border-purple-200", bg: "bg-purple-50/40", text: "text-purple-600", badge: "bg-purple-100 text-purple-700", dot: "bg-purple-500" },
  no_position_scanner: { border: "border-teal-200", bg: "bg-teal-50/40", text: "text-teal-600", badge: "bg-teal-100 text-teal-700", dot: "bg-teal-500" },
  adaptive_threshold: { border: "border-indigo-200", bg: "bg-indigo-50/40", text: "text-indigo-600", badge: "bg-indigo-100 text-indigo-700", dot: "bg-indigo-500" },
  wallet_divergence: { border: "border-lime-200", bg: "bg-lime-50/40", text: "text-lime-600", badge: "bg-lime-100 text-lime-700", dot: "bg-lime-500" },
};

const strategyLabels: Record<string, string> = {
  weather_arb: "Weather", near_certainty: "Near-Certainty", same_market_arb: "Same-Mkt",
  cross_market_arb: "Cross-Mkt", market_making: "MM", flash_crash: "Flash Crash",
  whale_copy: "Whale", logical_implication: "Logical", no_position_scanner: "No Pos",
  adaptive_threshold: "Adaptive", wallet_divergence: "Wallet Div",
};

// ----------------------------------------------------------------
// Component
// ----------------------------------------------------------------

export default function PredictionsPage() {
  const [strategies, setStrategies] = useState<StrategyConfig[]>(DEFAULT_STRATEGIES);
  const [markets, setMarkets] = useState<PredictionMarket[]>([]);
  const [opportunities, setOpportunities] = useState<Opportunity[]>([]);
  const [livePositions, setLivePositions] = useState<Position[]>([]);
  const [activeTab, setActiveTab] = useState<"scanner" | "analysis" | "markets" | "positions" | "portfolio" | "bot">("scanner");
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
  const streamRef = useRef<HTMLDivElement>(null);
  const analysisRef = useRef<HTMLDivElement>(null);

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
      const res = await fetch("/api/prediction-markets/strategies");
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
      const res = await fetch("/api/prediction-markets/markets?limit=50");
      if (!res.ok) return;
      const data = await res.json();
      if (data.markets?.length > 0) { setMarkets(data.markets.map(mapMarket)); setIsLive(true); }
    } catch {}
  };

  const runScan = async () => {
    setScanLoading(true);
    addLog("scan", `Starting scan across all enabled strategies...`);
    try {
      const res = await fetch("/api/prediction-markets/bot/scan-now", { method: "POST" });
      if (!res.ok) throw new Error("Scan failed");
      const data = await res.json();
      // Backend now runs scan in background and auto-starts the bot loop
      if (data.bot_running) {
        setBotRunning(true);
        addLog("info", "Bot loop auto-started — scans will repeat automatically");
      }
      setScanCount(data.total_scans || scanCount + 1);
      setLastScan(new Date().toLocaleTimeString());
      setIsLive(true);
      addLog("scan", `Scan queued (background). Bot running: ${data.bot_running}`);
      // Fetch updated data after a short delay to let the background scan complete
      setTimeout(async () => {
        try { await Promise.all([fetchBotOpportunities(), fetchPositions(), fetchStrategies()]); } catch {}
      }, 3000);
    } catch {
      try {
        const res = await fetch("/api/prediction-markets/scan", { method: "POST" });
        if (res.ok) {
          const data = await res.json();
          if (data.opportunities?.length > 0) setOpportunities(data.opportunities.map(mapOpportunity));
          setScanCount(data.scan_number || scanCount + 1);
          setLastScan(new Date().toLocaleTimeString());
        }
      } catch { addLog("info", "Scan failed (API unavailable)"); }
    } finally {
      setScanLoading(false);
    }
  };

  const fetchBotStatus = async () => {
    try {
      const res = await fetch("/api/prediction-markets/bot/status");
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
      const res = await fetch("/api/prediction-markets/portfolio");
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
      const res = await fetch("/api/prediction-markets/pnl-history?limit=200");
      if (res.ok) { const data = await res.json(); setEquityCurve(data.snapshots || []); }
    } catch {}
  };

  const fetchBotOpportunities = async () => {
    try {
      const res = await fetch("/api/prediction-markets/bot/activity?limit=50");
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
    try {
      await fetch("/api/prediction-markets/portfolio/reset", { method: "POST" });
    } catch {}
    setStrategies(DEFAULT_STRATEGIES.map(s => ({ ...s, positions: 0, pnl: 0 })));
    setOpportunities([]); setLivePositions([]); setEquityCurve([]);
    setPortfolioSummary(null); setScanCount(0); setAnalysisLog([]);
    addLog("info", "Portfolio reset.");
  };

  const checkPolymarketConnection = async () => {
    try {
      const res = await fetch("/api/prediction-markets/status");
      if (res.ok) { const data = await res.json(); setPolyStatus(data); }
    } catch { setPolyStatus({ connected: false }); }
  };

  const toggleBot = async () => {
    try {
      if (botRunning) {
        await fetch("/api/prediction-markets/bot/stop", { method: "POST" });
        setBotRunning(false); addLog("info", "Bot stopped");
      } else {
        const res = await fetch("/api/prediction-markets/bot/start", { method: "POST" });
        if (res.ok) {
          setBotRunning(true);
          addLog("info", "Bot started — automated scan → execute loop running every 120s");
        }
      }
      await fetchBotStatus();
    } catch {}
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
    else if (activeTab === "bot") fetchBotStatus();
    else if (activeTab === "positions") { fetchPositions(); fetchStrategies(); }
    else if (activeTab === "analysis" || activeTab === "scanner") fetchBotOpportunities();
  }, [activeTab]);

  useEffect(() => {
    if (!isLive) return;
    // Poll for updates — sequential calls with generous interval to avoid
    // overwhelming the backend and causing ECONNRESET proxy errors.
    const interval = setInterval(async () => {
      try {
        await fetchBotStatus();
      } catch {}
      try {
        await fetchPositions();
      } catch {}
      if (activeTab === "analysis" || activeTab === "scanner") {
        try { await fetchBotOpportunities(); } catch {}
      }
    }, 45000);
    return () => clearInterval(interval);
  }, [activeTab, isLive]);

  // The backend bot loop handles periodic scanning automatically.
  // No need for frontend-driven scan intervals — the bot auto-starts
  // on the first "Scan + Execute" click.
  // The polling interval below fetches updated results from the backend.

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

  // Pre-calculate equity curve bounds (avoid O(n²) in render)
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

  // Skeleton component for loading state
  const Skeleton = ({ className = "" }: { className?: string }) => (
    <div className={`animate-pulse bg-gray-100 rounded-lg ${className}`} />
  );

  return (
    <div className="min-h-screen bg-[#F8F8FA]">
      {/* ============ HEADER ============ */}
      <div className="sticky top-0 z-30 bg-white/90 backdrop-blur-xl border-b border-gray-200/60">
        <div className="max-w-[1440px] mx-auto px-6">
          <div className="flex items-center justify-between h-14">
            {/* Left: Title + Status */}
            <div className="flex items-center gap-3">
              <h1 className="text-[15px] font-semibold text-gray-900">Predictions</h1>
              {polyStatus.connected ? (
                <span className="flex items-center gap-1 text-[10px] font-medium text-emerald-600">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                  Live
                </span>
              ) : polyStatus.connected === false ? (
                <span className="flex items-center gap-1 text-[10px] font-medium text-gray-400">
                  <span className="w-1.5 h-1.5 rounded-full bg-gray-400" />
                  Offline
                </span>
              ) : null}
              {lastUpdated && (
                <span className="text-[10px] text-gray-400 tabular-nums">
                  <Clock className="w-2.5 h-2.5 inline mr-0.5 -mt-px" />
                  {timeAgo}
                </span>
              )}
            </div>

            {/* Right: Actions */}
            <div className="flex items-center gap-1.5">
              <button onClick={resetPortfolio} className="px-2.5 py-1.5 rounded-md text-[11px] font-medium text-gray-400 hover:text-red-500 hover:bg-red-50">
                Reset
              </button>
              <div className="w-px h-4 bg-gray-200" />
              <button
                onClick={runScan} disabled={scanLoading}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[11px] font-semibold bg-violet-600 text-white hover:bg-violet-700 disabled:opacity-60"
              >
                <RefreshCw className={`w-3 h-3 ${scanLoading ? "animate-spin" : ""}`} />
                {scanLoading ? "Scanning..." : "Scan + Execute"}
              </button>
              <button
                onClick={toggleBot}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[11px] font-semibold border ${
                  botRunning
                    ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                    : "bg-white text-gray-600 border-gray-200 hover:bg-gray-50"
                }`}
              >
                {botRunning ? (
                  <><span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" /> Bot On</>
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
        <div className="bg-violet-600">
          <div className="max-w-[1440px] mx-auto px-6 py-2 flex items-center gap-2">
            <RefreshCw className="w-3 h-3 text-white animate-spin" />
            <span className="text-[11px] font-medium text-white/90">
              Scanning {enabledCount} strategies across Polymarket... This takes ~2 minutes (CLOB enrichment + whale feed).
            </span>
          </div>
        </div>
      )}

      <div className="max-w-[1440px] mx-auto px-6 py-5">
        {/* ============ STATS ROW ============ */}
        <div className="grid grid-cols-4 gap-3 mb-5">
          {loading ? (
            <>
              {[0,1,2,3].map(i => <Skeleton key={i} className="h-[76px]" />)}
            </>
          ) : [
            { label: "Total P&L", value: `${totalPnl >= 0 ? "+" : ""}$${totalPnl.toFixed(2)}`, color: totalPnl >= 0 ? "text-emerald-600" : "text-red-500", icon: DollarSign, sub: portfolioSummary?.total_exposure ? `$${portfolioSummary.total_exposure.toFixed(2)} exposure` : null },
            { label: "Open Positions", value: String(positionCount), color: "text-gray-900", icon: Activity, sub: positionCount > 0 ? `${new Set(livePositions.map(p => p.strategy)).size} strategies` : null },
            { label: "Strategies", value: `${enabledCount}/${strategies.length}`, color: "text-gray-900", icon: Zap, sub: botRunning ? "Bot running" : "Bot idle" },
            { label: "Scans", value: String(effectiveScanCount), color: "text-gray-900", icon: BarChart3, sub: lastScanOpps > 0 ? `${lastScanOpps} opps last scan` : null },
          ].map((s) => (
            <div key={s.label} className="bg-white rounded-xl p-4 border border-gray-100">
              <div className="flex items-center gap-1.5 mb-1.5">
                <s.icon className="w-3.5 h-3.5 text-gray-400" />
                <span className="text-[11px] font-medium text-gray-500 uppercase tracking-wide">{s.label}</span>
              </div>
              <p className={`text-xl font-semibold tabular-nums tracking-tight ${s.color}`}>{s.value}</p>
              {s.sub && <p className="text-[10px] text-gray-400 mt-0.5">{s.sub}</p>}
            </div>
          ))}
        </div>

        {/* ============ STRATEGY STRIP ============ */}
        <div className="flex gap-1.5 mb-5 overflow-x-auto pb-1">
          {strategies.map((strategy) => {
            const c = strategyColors[strategy.id] || strategyColors.weather_arb;
            return (
              <button key={strategy.id} onClick={() => toggleStrategy(strategy.id)}
                className={`flex-shrink-0 flex items-center gap-2 px-3 py-2 rounded-lg border text-left ${
                  strategy.enabled ? `${c.border} ${c.bg}` : "border-gray-100 bg-gray-50/50 opacity-40"
                }`}
              >
                <strategy.icon className={`w-3.5 h-3.5 flex-shrink-0 ${strategy.enabled ? c.text : "text-gray-400"}`} />
                <div className="min-w-0">
                  <span className="text-[11px] font-semibold text-gray-900 whitespace-nowrap">{strategy.name}</span>
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] text-gray-400 tabular-nums">{strategy.positions} pos</span>
                    <span className={`text-[10px] font-semibold tabular-nums ${strategy.pnl >= 0 ? "text-emerald-600" : "text-red-500"}`}>
                      {strategy.pnl >= 0 ? "+" : ""}${strategy.pnl.toFixed(2)}
                    </span>
                  </div>
                </div>
              </button>
            );
          })}
        </div>

        {/* ============ TABS ============ */}
        <div className="flex items-center gap-0.5 mb-5 border-b border-gray-200">
          {([
            { key: "scanner" as const, label: "Scanner" },
            { key: "analysis" as const, label: "Analysis", dot: analysisLog.length > 0 },
            { key: "markets" as const, label: "Markets" },
            { key: "positions" as const, label: positionCount > 0 ? `Positions (${positionCount})` : "Positions" },
            { key: "portfolio" as const, label: "Portfolio" },
            { key: "bot" as const, label: "Bot", dot: botRunning },
          ]).map((tab) => (
            <button key={tab.key} onClick={() => setActiveTab(tab.key)}
              className={`px-4 py-2.5 text-[13px] font-medium border-b-2 -mb-px ${
                activeTab === tab.key ? "border-violet-500 text-gray-900" : "border-transparent text-gray-500 hover:text-gray-700"
              }`}
            >
              {tab.label}
              {tab.dot && <span className="inline-block w-1.5 h-1.5 rounded-full bg-violet-500 ml-1.5 -mt-1 animate-pulse" />}
            </button>
          ))}
        </div>

        {/* ============ SCANNER ============ */}
        {activeTab === "scanner" && (
          <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
            <div className="px-5 py-3 border-b border-gray-100 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-violet-500 animate-pulse" />
                <span className="text-[13px] font-semibold text-gray-900">Opportunity Stream</span>
                {opportunities.length > 0 && (
                  <span className="text-[11px] text-gray-400 tabular-nums">{opportunities.length} signals</span>
                )}
              </div>
              <button onClick={runScan} disabled={scanLoading}
                className="flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-medium text-violet-600 hover:bg-violet-50 disabled:opacity-50"
              >
                <RefreshCw className={`w-3 h-3 ${scanLoading ? "animate-spin" : ""}`} />
                Scan Now
              </button>
            </div>
            <div ref={streamRef} className="divide-y divide-gray-50 max-h-[520px] overflow-y-auto">
              {opportunities.length > 0 ? opportunities.map((opp) => {
                const c = strategyColors[opp.strategy] || strategyColors.weather_arb;
                return (
                  <div key={opp.id} className="px-5 py-3 hover:bg-gray-50/50">
                    <div className="flex items-start justify-between gap-4">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-1.5 mb-1">
                          <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${c.badge}`}>
                            {strategyLabels[opp.strategy] || opp.strategy}
                          </span>
                          <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${
                            opp.side === "BUY" ? "bg-emerald-50 text-emerald-600" : "bg-red-50 text-red-500"
                          }`}>{opp.side}</span>
                          <span className="text-[10px] text-gray-400 tabular-nums">{opp.timestamp}</span>
                        </div>
                        <p className="text-[13px] text-gray-900 font-medium truncate">{opp.market}</p>
                        <p className="text-[11px] text-gray-500 mt-0.5 line-clamp-1">{opp.reason}</p>
                      </div>
                      <div className="text-right flex-shrink-0 w-20">
                        <p className="text-lg font-bold text-emerald-600 tabular-nums leading-tight">
                          {(opp.edge * 100).toFixed(1)}%
                        </p>
                        <div className="flex items-center gap-1 mt-1 justify-end">
                          <div className="w-12 h-1 bg-gray-100 rounded-full overflow-hidden">
                            <div className="h-full bg-violet-400 rounded-full" style={{ width: `${opp.confidence * 100}%` }} />
                          </div>
                          <span className="text-[10px] text-gray-400 tabular-nums">{(opp.confidence * 100).toFixed(0)}%</span>
                        </div>
                      </div>
                    </div>
                  </div>
                );
              }) : (
                <div className="py-20 text-center">
                  <Radio className="w-10 h-10 text-gray-200 mx-auto mb-3" />
                  <p className="text-[13px] text-gray-500 font-medium">No signals yet</p>
                  <p className="text-[11px] text-gray-400 mt-1 mb-4">Run a scan to find opportunities across Polymarket</p>
                  <button onClick={runScan} disabled={scanLoading}
                    className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-[12px] font-semibold bg-violet-600 text-white hover:bg-violet-700 disabled:opacity-60"
                  >
                    <RefreshCw className={`w-3.5 h-3.5 ${scanLoading ? "animate-spin" : ""}`} />
                    {scanLoading ? "Scanning..." : "Run First Scan"}
                  </button>
                </div>
              )}
            </div>
          </div>
        )}

        {/* ============ ANALYSIS ============ */}
        {activeTab === "analysis" && (
          <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
            <div className="px-5 py-3 border-b border-gray-100 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-violet-500 animate-pulse" />
                <span className="text-[13px] font-semibold text-gray-900">Live Analysis</span>
                <span className="text-[11px] text-gray-400">{analysisLog.length} entries</span>
              </div>
              <div className="flex items-center gap-2">
                <button onClick={fetchBotOpportunities} className="flex items-center gap-1 text-[11px] text-gray-400 hover:text-gray-600">
                  <RotateCw className="w-3 h-3" /> Refresh
                </button>
                <button onClick={() => setAnalysisLog([])} className="text-[11px] text-gray-400 hover:text-gray-600">Clear</button>
              </div>
            </div>
            <div ref={analysisRef} className="max-h-[600px] overflow-y-auto divide-y divide-gray-50">
              {analysisLog.length > 0 ? analysisLog.map((entry) => {
                const types: Record<string, { bg: string; label: string }> = {
                  scan: { bg: "bg-blue-50 text-blue-600", label: "SCAN" },
                  signal: { bg: "bg-emerald-50 text-emerald-600", label: "SIGNAL" },
                  execute: { bg: "bg-violet-50 text-violet-600", label: "EXEC" },
                  skip: { bg: "bg-gray-100 text-gray-500", label: "SKIP" },
                  info: { bg: "bg-amber-50 text-amber-600", label: "INFO" },
                };
                const t = types[entry.type] || types.info;
                const sc = entry.strategy ? strategyColors[entry.strategy] : null;
                return (
                  <div key={entry.id} className="px-5 py-2 hover:bg-gray-50/50">
                    <div className="flex items-start gap-2">
                      <span className="text-[10px] text-gray-400 tabular-nums whitespace-nowrap mt-0.5 w-[60px] flex-shrink-0 font-mono">{entry.timestamp}</span>
                      <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded whitespace-nowrap ${t.bg}`}>{t.label}</span>
                      {sc && <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded whitespace-nowrap ${sc.badge}`}>{strategyLabels[entry.strategy!] || entry.strategy}</span>}
                      <p className="text-[11px] text-gray-600 leading-relaxed min-w-0">{entry.message}</p>
                    </div>
                  </div>
                );
              }) : (
                <div className="py-20 text-center">
                  <Eye className="w-10 h-10 text-gray-200 mx-auto mb-3" />
                  <p className="text-[13px] text-gray-500 font-medium">No analysis entries</p>
                  <p className="text-[11px] text-gray-400 mt-1 mb-4">Run a scan or start the bot to see live rationales</p>
                  <button onClick={runScan} disabled={scanLoading}
                    className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-[12px] font-semibold bg-violet-600 text-white hover:bg-violet-700 disabled:opacity-60"
                  >
                    <RefreshCw className={`w-3.5 h-3.5 ${scanLoading ? "animate-spin" : ""}`} />
                    {scanLoading ? "Scanning..." : "Run First Scan"}
                  </button>
                </div>
              )}
            </div>
          </div>
        )}

        {/* ============ MARKETS ============ */}
        {activeTab === "markets" && (
          <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
            <div className="px-5 py-3 border-b border-gray-100">
              <div className="flex items-center gap-3">
                <div className="relative flex-1">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
                  <input type="text" placeholder="Search markets..." value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    className="w-full pl-9 pr-4 py-2 bg-gray-50 rounded-lg text-[13px] text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-violet-500/20 focus:bg-white border-0" />
                </div>
                <span className="text-[11px] font-medium text-gray-400 tabular-nums">{filteredMarkets.length} markets</span>
              </div>
            </div>
            <div className="divide-y divide-gray-50 max-h-[600px] overflow-y-auto">
              {filteredMarkets.map((market) => (
                <div key={market.id} className="px-5 py-3 hover:bg-gray-50/50">
                  <div className="flex items-start justify-between mb-2">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-1.5 mb-0.5">
                        <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-gray-100 text-gray-500">{market.category}</span>
                        {market.endDate && <span className="text-[10px] text-gray-400">Ends {new Date(market.endDate).toLocaleDateString()}</span>}
                      </div>
                      <p className="text-[13px] font-medium text-gray-900">{market.question}</p>
                    </div>
                    <div className="text-right ml-4 flex-shrink-0 text-[10px] text-gray-400 tabular-nums">
                      <p>${(market.volume / 1e6).toFixed(1)}M vol</p>
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {market.outcomes.map((o, i) => (
                      <div key={i} className="flex items-center gap-1.5 px-2 py-1 rounded bg-gray-50 border border-gray-100">
                        <span className="text-[11px] text-gray-600">{o.label}</span>
                        <span className={`text-[11px] font-bold tabular-nums ${o.price >= 0.5 ? "text-emerald-600" : "text-gray-900"}`}>
                          {(o.price * 100).toFixed(0)}c
                        </span>
                        <div className="w-8 h-1 bg-gray-200 rounded-full overflow-hidden">
                          <div className={`h-full rounded-full ${o.price >= 0.5 ? "bg-emerald-400" : "bg-gray-400"}`} style={{ width: `${o.price * 100}%` }} />
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
          <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
            <div className="px-5 py-3 border-b border-gray-100 flex items-center justify-between">
              <span className="text-[13px] font-semibold text-gray-900">{positionCount} Open Positions</span>
              <span className={`text-[13px] font-bold tabular-nums ${unrealizedPnl >= 0 ? "text-emerald-600" : "text-red-500"}`}>
                Unrealized: {unrealizedPnl >= 0 ? "+" : ""}${unrealizedPnl.toFixed(2)}
              </span>
            </div>
            {livePositions.length > 0 ? (
              <table className="data-table">
                <thead><tr><th>Market</th><th>Strategy</th><th>Side</th><th>Entry</th><th>Current</th><th>Size</th><th>P&L</th></tr></thead>
                <tbody>
                  {livePositions.map((pos) => {
                    const c = strategyColors[pos.strategy] || strategyColors.weather_arb;
                    return (
                      <tr key={pos.id}>
                        <td><p className="text-[13px] font-medium text-gray-900 truncate max-w-[280px]">{pos.market}</p><p className="text-[10px] text-gray-400">{pos.outcome}</p></td>
                        <td><span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${c.badge}`}>{strategyLabels[pos.strategy] || pos.strategy}</span></td>
                        <td><span className={`text-[11px] font-semibold ${pos.side === "BUY" ? "text-emerald-600" : "text-red-500"}`}>{pos.side}</span></td>
                        <td className="tabular-nums text-[13px]">${pos.entryPrice.toFixed(2)}</td>
                        <td className="tabular-nums text-[13px]">${pos.currentPrice.toFixed(2)}</td>
                        <td className="tabular-nums text-[13px]">${pos.size.toFixed(2)}</td>
                        <td><span className={`text-[13px] font-semibold tabular-nums ${pos.pnl >= 0 ? "text-emerald-600" : "text-red-500"}`}>{pos.pnl >= 0 ? "+" : ""}${pos.pnl.toFixed(2)}</span></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            ) : (
              <div className="py-20 text-center">
                <Layers className="w-10 h-10 text-gray-200 mx-auto mb-3" />
                <p className="text-[13px] text-gray-500 font-medium">No open positions</p>
                <p className="text-[11px] text-gray-400 mt-1 mb-4">Run a scan to find and execute trades</p>
                <button onClick={runScan} disabled={scanLoading}
                  className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-[12px] font-semibold bg-violet-600 text-white hover:bg-violet-700 disabled:opacity-60"
                >
                  <RefreshCw className={`w-3.5 h-3.5 ${scanLoading ? "animate-spin" : ""}`} />
                  Scan + Execute
                </button>
              </div>
            )}
          </div>
        )}

        {/* ============ PORTFOLIO ============ */}
        {activeTab === "portfolio" && (
          <div className="space-y-4">
            <div className="grid grid-cols-4 gap-3">
              {[
                { l: "Total Value", v: `$${portfolioSummary?.total_exposure?.toFixed(2) || "0.00"}`, c: "text-gray-900" },
                { l: "Total P&L", v: `${(portfolioSummary?.total_pnl || 0) >= 0 ? "+" : ""}$${(portfolioSummary?.total_pnl || 0).toFixed(2)}`, c: (portfolioSummary?.total_pnl || 0) >= 0 ? "text-emerald-600" : "text-red-500" },
                { l: "Fees", v: `$${portfolioSummary?.total_fees?.toFixed(2) || "0.00"}`, c: "text-gray-900" },
                { l: "Orders", v: String(portfolioSummary?.total_orders || 0), c: "text-gray-900" },
              ].map((i) => (
                <div key={i.l} className="bg-white rounded-xl p-4 border border-gray-100">
                  <span className="text-[11px] font-medium text-gray-500 uppercase tracking-wide">{i.l}</span>
                  <p className={`text-xl font-semibold tabular-nums mt-1 ${i.c}`}>{i.v}</p>
                </div>
              ))}
            </div>

            <div className="bg-white rounded-xl p-5 border border-gray-100">
              <h2 className="text-[13px] font-semibold text-gray-900 mb-4">Equity Curve</h2>
              {equityCurve.length > 0 ? (
                <div className="h-44 flex items-end gap-px">
                  {equityCurve.map((s: any, i: number) => {
                    const height = ((s.total_value_usd - equityBounds.min) / equityBounds.range) * 100;
                    const isPositive = (s.unrealized_pnl + s.realized_pnl) >= 0;
                    return (
                      <div key={i} className={`flex-1 rounded-t ${isPositive ? "bg-emerald-400/80" : "bg-red-400/80"} hover:opacity-70`}
                        style={{ height: `${Math.max(height, 2)}%` }}
                        title={`$${s.total_value_usd?.toFixed(2)} | ${new Date(s.snapshot_at).toLocaleString()}`} />
                    );
                  })}
                </div>
              ) : (
                <div className="h-44 flex items-center justify-center">
                  <div className="text-center">
                    <TrendingUp className="w-10 h-10 text-gray-200 mx-auto mb-2" />
                    <p className="text-[13px] text-gray-400">Start the bot to build an equity curve</p>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* ============ BOT ============ */}
        {activeTab === "bot" && (
          <div className="space-y-4">
            <div className="bg-white rounded-xl p-5 border border-gray-100">
              <div className="flex items-center justify-between mb-4">
                <div>
                  <h2 className="text-[13px] font-semibold text-gray-900">Trading Bot</h2>
                  <p className="text-[11px] text-gray-500 mt-0.5">Scan → Kelly size → execute → persist loop</p>
                </div>
                <button onClick={toggleBot}
                  className={`px-4 py-2 rounded-lg text-[12px] font-semibold border ${
                    botRunning ? "bg-red-50 text-red-600 border-red-200 hover:bg-red-100" : "bg-emerald-50 text-emerald-700 border-emerald-200 hover:bg-emerald-100"
                  }`}
                >{botRunning ? "Stop Bot" : "Start Bot"}</button>
              </div>
              <div className="grid grid-cols-3 gap-3">
                <div className="p-3 rounded-lg bg-gray-50">
                  <span className="text-[10px] font-medium text-gray-500 uppercase">Status</span>
                  <div className="flex items-center gap-2 mt-1.5">
                    <span className={`w-2 h-2 rounded-full ${botRunning ? "bg-emerald-500 animate-pulse" : "bg-gray-400"}`} />
                    <span className="text-[13px] font-semibold text-gray-900">{botRunning ? "Running" : "Stopped"}</span>
                  </div>
                </div>
                <div className="p-3 rounded-lg bg-gray-50">
                  <span className="text-[10px] font-medium text-gray-500 uppercase">Scans</span>
                  <p className="text-lg font-bold tabular-nums text-gray-900 mt-1">{botStatus?.total_scans || 0}</p>
                </div>
                <div className="p-3 rounded-lg bg-gray-50">
                  <span className="text-[10px] font-medium text-gray-500 uppercase">Executions</span>
                  <p className="text-lg font-bold tabular-nums text-gray-900 mt-1">{botStatus?.total_executions || 0}</p>
                </div>
              </div>
            </div>

            <div className="bg-white rounded-xl p-5 border border-gray-100">
              <h2 className="text-[13px] font-semibold text-gray-900 mb-3">Risk Manager</h2>
              <div className="grid grid-cols-4 gap-3">
                <div className="p-3 rounded-lg bg-gray-50">
                  <span className="text-[10px] font-medium text-gray-500 uppercase">Daily P&L</span>
                  <p className={`text-[15px] font-bold tabular-nums mt-1 ${(botStatus?.risk_manager?.daily_pnl || 0) >= 0 ? "text-emerald-600" : "text-red-500"}`}>
                    ${(botStatus?.risk_manager?.daily_pnl || 0).toFixed(2)}</p>
                </div>
                <div className="p-3 rounded-lg bg-gray-50">
                  <span className="text-[10px] font-medium text-gray-500 uppercase">Circuit Breaker</span>
                  <p className="text-[13px] font-semibold mt-1.5">
                    {botStatus?.risk_manager?.circuit_breaker_active ? <span className="text-red-600">ACTIVE</span> : <span className="text-emerald-600">OK</span>}
                  </p>
                </div>
                <div className="p-3 rounded-lg bg-gray-50">
                  <span className="text-[10px] font-medium text-gray-500 uppercase">Orders/min</span>
                  <p className="text-[15px] font-bold tabular-nums text-gray-900 mt-1">
                    {botStatus?.risk_manager?.orders_last_minute || 0}<span className="text-[11px] font-normal text-gray-400">/{botStatus?.risk_manager?.max_orders_per_minute || 10}</span>
                  </p>
                </div>
                <div className="p-3 rounded-lg bg-gray-50">
                  <span className="text-[10px] font-medium text-gray-500 uppercase">Positions</span>
                  <p className="text-[15px] font-bold tabular-nums text-gray-900 mt-1">
                    {botStatus?.portfolio?.total_positions || positionCount}<span className="text-[11px] font-normal text-gray-400">/{botStatus?.risk_manager?.max_total_positions || 50}</span>
                  </p>
                </div>
              </div>
              {botStatus?.risk_manager?.disabled_strategies?.length > 0 && (
                <div className="mt-3 p-2.5 rounded-lg bg-red-50 border border-red-100">
                  <span className="text-[10px] font-semibold text-red-600 uppercase">Disabled</span>
                  <div className="flex flex-wrap gap-1 mt-1">
                    {botStatus.risk_manager.disabled_strategies.map((s: string) => (
                      <span key={s} className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-red-100 text-red-600">{s}</span>
                    ))}
                  </div>
                </div>
              )}
            </div>

            <div className="bg-white rounded-xl p-5 border border-gray-100">
              <h2 className="text-[13px] font-semibold text-gray-900 mb-3">Kelly Sizing</h2>
              <div className="grid grid-cols-5 gap-2">
                {[
                  { l: "Fractional", v: botStatus?.kelly_config?.fractional_kelly || 0.25 },
                  { l: "Min Bet", v: `$${botStatus?.kelly_config?.min_bet_usd || 1}` },
                  { l: "Max Bet", v: `$${botStatus?.kelly_config?.max_bet_usd || 50}` },
                  { l: "Min Edge", v: `${((botStatus?.kelly_config?.min_edge || 0.03) * 100).toFixed(0)}%` },
                  { l: "Min Conf", v: `${((botStatus?.kelly_config?.min_confidence || 0.6) * 100).toFixed(0)}%` },
                ].map((i) => (
                  <div key={i.l} className="p-2.5 rounded-lg bg-gray-50 text-center">
                    <span className="text-[10px] font-medium text-gray-500 uppercase">{i.l}</span>
                    <p className="text-[13px] font-bold tabular-nums text-gray-900 mt-1">{i.v}</p>
                  </div>
                ))}
              </div>
            </div>

            <button onClick={runScan} disabled={scanLoading}
              className="w-full py-2.5 rounded-xl bg-violet-600 text-white font-semibold text-[13px] hover:bg-violet-700 disabled:opacity-60 flex items-center justify-center gap-2"
            >
              <RefreshCw className={`w-4 h-4 ${scanLoading ? "animate-spin" : ""}`} />
              {scanLoading ? "Scanning..." : "Run Manual Scan + Execute"}
            </button>
          </div>
        )}
      </div>

      {/* ============ FOOTER ============ */}
      <div className="max-w-[1440px] mx-auto px-6 py-3">
        <div className="flex items-center gap-1.5 text-[10px] text-gray-400">
          <Shield className="w-3 h-3" />
          Paper trading (dry_run). {isLive ? "Connected to Polymarket." : "Backend offline."}
        </div>
      </div>
    </div>
  );
}
