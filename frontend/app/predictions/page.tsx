"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import {
  Target,
  Zap,
  CloudSun,
  TrendingUp,
  TrendingDown,
  Shield,
  DollarSign,
  Clock,
  Search,
  RefreshCw,
  ChevronRight,
  AlertTriangle,
  Activity,
  BarChart3,
  Percent,
  Globe,
  Thermometer,
  ArrowUpRight,
  ArrowDownRight,
  Pause,
  Play,
  Settings2,
  ArrowLeftRight,
  Users,
  Radio,
  Eye,
  Layers,
  Wallet,
  Bot,
  CircleDot,
  ChevronDown,
  ExternalLink,
  RotateCw,
} from "lucide-react";

// ----------------------------------------------------------------
// Types
// ----------------------------------------------------------------

interface MarketOutcome {
  label: string;
  price: number;
  tokenId: string;
}

interface PredictionMarket {
  id: string;
  question: string;
  category: string;
  outcomes: MarketOutcome[];
  volume: number;
  liquidity: number;
  endDate: string;
  active: boolean;
  exchange?: "polymarket";
}

interface Opportunity {
  id: string;
  strategy: string;
  market: string;
  side: "BUY" | "SELL";
  entryPrice: number;
  edge: number;
  confidence: number;
  reason: string;
  timestamp: string;
}

interface Position {
  id: string;
  market: string;
  outcome: string;
  side: "BUY" | "SELL";
  entryPrice: number;
  currentPrice: number;
  size: number;
  pnl: number;
  strategy: string;
  openedAt: string;
}

interface StrategyConfig {
  id: string;
  name: string;
  description: string;
  icon: any;
  enabled: boolean;
  color: string;
  positions: number;
  pnl: number;
  config: Record<string, string | number>;
}

// ----------------------------------------------------------------
// Demo Data
// ----------------------------------------------------------------

const DEFAULT_STRATEGIES: StrategyConfig[] = [
  {
    id: "weather_arb",
    name: "Weather Arbitrage",
    description: "Compare NOAA forecasts to market prices. Buy undervalued temperature buckets.",
    icon: CloudSun,
    enabled: true,
    color: "cyan",
    positions: 0,
    pnl: 0,
    config: {
      "Entry threshold": "$0.15",
      "Exit threshold": "$0.45",
      "Max position": "$5.00",
      "Locations": "NYC, CHI, SEA, ATL, DAL",
      "Scan interval": "2 min",
    },
  },
  {
    id: "near_certainty",
    name: "Near-Certainty Harvest",
    description: "Buy 90-99c outcomes at scale. Penny profits × thousands of trades.",
    icon: Target,
    enabled: true,
    color: "violet",
    positions: 0,
    pnl: 0,
    config: {
      "Min price": "$0.90",
      "Max price": "$0.99",
      "Min volume": "$5,000",
      "Max hours to resolution": "720h",
      "Max position": "$10.00",
    },
  },
  {
    id: "same_market_arb",
    name: "Same-Market Arb",
    description: "YES + NO < $1.00? Buy both, guaranteed profit. Windows last milliseconds.",
    icon: Zap,
    enabled: true,
    color: "amber",
    positions: 0,
    pnl: 0,
    config: {
      "Min discount": "1%",
      "Min liquidity": "$1,000",
      "Max per trade": "$50.00",
    },
  },
  {
    id: "cross_market_arb",
    name: "Cross-Market Arb",
    description: "Find logical inconsistencies between related markets.",
    icon: Globe,
    enabled: true,
    color: "rose",
    positions: 0,
    pnl: 0,
    config: {
      "Min inconsistency": "10%",
      "Min shared keywords": "3",
      "Max position": "$20.00",
    },
  },
  {
    id: "market_making",
    name: "Market Making",
    description: "Provide two-sided liquidity, capture bid-ask spread + Q-score rebates.",
    icon: ArrowLeftRight,
    enabled: true,
    color: "blue",
    positions: 0,
    pnl: 0,
    config: {
      "Target spread": "2c",
      "Max spread": "3c (Q-score)",
      "Min liquidity": "$1,000",
      "Max volatility": "10%",
      "Rebalance at": "60% one-sided",
    },
  },
  {
    id: "flash_crash",
    name: "Flash Crash",
    description: "Buy crashed BTC/ETH tokens on 15-min markets. Two-leg arb when YES+NO < $0.97.",
    icon: AlertTriangle,
    enabled: true,
    color: "orange",
    positions: 0,
    pnl: 0,
    config: {
      "Crash threshold": "15%",
      "Max combined cost": "$0.97",
      "Min volume": "$5,000",
      "Target markets": "BTC, ETH, SOL",
    },
  },
  {
    id: "whale_copy",
    name: "Whale Copy",
    description: "Follow top 7.6% profitable wallets. Basket consensus (80%+ must agree) before entry.",
    icon: Users,
    enabled: true,
    color: "emerald",
    positions: 0,
    pnl: 0,
    config: {
      "Min trade size": "$1,000",
      "Max entry odds": "80c",
      "Basket consensus": "80%",
    },
  },
];

const strategyColors: Record<string, { border: string; bg: string; text: string; badge: string; dot: string }> = {
  weather_arb: { border: "border-cyan-200", bg: "bg-cyan-50/50", text: "text-cyan-600", badge: "bg-cyan-100 text-cyan-700", dot: "bg-cyan-500" },
  near_certainty: { border: "border-violet-200", bg: "bg-violet-50/50", text: "text-violet-600", badge: "bg-violet-100 text-violet-700", dot: "bg-violet-500" },
  same_market_arb: { border: "border-amber-200", bg: "bg-amber-50/50", text: "text-amber-600", badge: "bg-amber-100 text-amber-700", dot: "bg-amber-500" },
  cross_market_arb: { border: "border-rose-200", bg: "bg-rose-50/50", text: "text-rose-600", badge: "bg-rose-100 text-rose-700", dot: "bg-rose-500" },
  market_making: { border: "border-blue-200", bg: "bg-blue-50/50", text: "text-blue-600", badge: "bg-blue-100 text-blue-700", dot: "bg-blue-500" },
  flash_crash: { border: "border-orange-200", bg: "bg-orange-50/50", text: "text-orange-600", badge: "bg-orange-100 text-orange-700", dot: "bg-orange-500" },
  whale_copy: { border: "border-emerald-200", bg: "bg-emerald-50/50", text: "text-emerald-600", badge: "bg-emerald-100 text-emerald-700", dot: "bg-emerald-500" },
  // Advanced strategies from backend
  logical_implication: { border: "border-purple-200", bg: "bg-purple-50/50", text: "text-purple-600", badge: "bg-purple-100 text-purple-700", dot: "bg-purple-500" },
  no_position_scanner: { border: "border-teal-200", bg: "bg-teal-50/50", text: "text-teal-600", badge: "bg-teal-100 text-teal-700", dot: "bg-teal-500" },
  adaptive_threshold: { border: "border-indigo-200", bg: "bg-indigo-50/50", text: "text-indigo-600", badge: "bg-indigo-100 text-indigo-700", dot: "bg-indigo-500" },
  wallet_divergence: { border: "border-lime-200", bg: "bg-lime-50/50", text: "text-lime-600", badge: "bg-lime-100 text-lime-700", dot: "bg-lime-500" },
};

const strategyLabels: Record<string, string> = {
  weather_arb: "Weather",
  near_certainty: "Near-Certainty",
  same_market_arb: "Same-Mkt Arb",
  cross_market_arb: "Cross-Mkt Arb",
  market_making: "Market Making",
  flash_crash: "Flash Crash",
  whale_copy: "Whale Copy",
  logical_implication: "Logical Imp.",
  no_position_scanner: "No Position",
  adaptive_threshold: "Adaptive",
  wallet_divergence: "Wallet Div.",
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
  const [botRunning, setBotRunning] = useState(false);
  const [botStatus, setBotStatus] = useState<any>(null);
  const [analysisLog, setAnalysisLog] = useState<any[]>([]);
  const [equityCurve, setEquityCurve] = useState<any[]>([]);
  const [portfolioSummary, setPortfolioSummary] = useState<any>(null);
  const [polyStatus, setPolyStatus] = useState<any>({ connected: null });
  const [activitySince, setActivitySince] = useState(0); // Track last fetched activity count
  const streamRef = useRef<HTMLDivElement>(null);
  const analysisRef = useRef<HTMLDivElement>(null);

  // Map API market format
  const mapMarket = (m: any): PredictionMarket => ({
    id: m.id || m.condition_id,
    question: m.question,
    category: m.category || "Unknown",
    outcomes: (m.outcomes || []).map((o: any) => ({
      label: o.label,
      price: o.price || o.midpoint || 0,
      tokenId: o.token_id,
    })),
    volume: m.total_volume || 0,
    liquidity: m.liquidity || 0,
    endDate: m.end_date || "",
    active: m.active ?? true,
    exchange: m.exchange || "polymarket",
  });

  const mapOpportunity = (opp: any): Opportunity => ({
    id: opp.id || `${opp.strategy}-${Date.now()}-${Math.random().toString(36).slice(2,6)}`,
    strategy: opp.strategy,
    market: opp.market || opp.market_question || "",
    side: opp.side || "BUY",
    entryPrice: opp.entry_price || opp.price || 0,
    edge: opp.edge || 0,
    confidence: opp.confidence || 0,
    reason: opp.reason || "",
    timestamp: opp.timestamp || new Date().toLocaleTimeString(),
  });

  // Fetch live strategy data from API (positions, P&L, etc.)
  const fetchStrategies = async () => {
    try {
      const res = await fetch("/api/prediction-markets/strategies");
      if (!res.ok) return;
      const data = await res.json();
      if (data.strategies && data.strategies.length > 0) {
        setStrategies((prev) =>
          prev.map((s) => {
            const live = data.strategies.find((ls: any) => ls.name === s.id);
            if (live) {
              return { ...s, positions: live.positions || 0, pnl: live.total_pnl || 0 };
            }
            return s;
          })
        );
        setScanCount(data.total_scans || 0);
        setIsLive(true);
      }
    } catch {
      // API unavailable — keep defaults
    }
  };

  // Fetch live markets from API
  const fetchMarkets = async () => {
    try {
      const res = await fetch("/api/prediction-markets/markets?limit=50");
      if (!res.ok) return;
      const data = await res.json();
      if (data.markets && data.markets.length > 0) {
        setMarkets(data.markets.map(mapMarket));
        setIsLive(true);
      }
    } catch {}
  };

  // Run scanner via API
  const runScan = async () => {
    setScanLoading(true);
    addLog("scan", `Starting scan #${scanCount + 1} across all enabled strategies...`);
    try {
      const res = await fetch("/api/prediction-markets/scan", { method: "POST" });
      if (!res.ok) throw new Error("Scan failed");
      const data = await res.json();
      const num = data.scan_number || scanCount + 1;
      setScanCount(num);
      setLastScan("Just now");
      setIsLive(true);
      if (data.opportunities && data.opportunities.length > 0) {
        setOpportunities(data.opportunities.map(mapOpportunity));
        addLog("scan", `Scan #${num} complete: ${data.opportunities.length} opportunities found across ${data.markets_scanned || "?"} markets`);
        data.opportunities.slice(0, 5).forEach((opp: any) => {
          addLog("signal", `${opp.reason}`, opp.strategy);
        });
      } else {
        addLog("scan", `Scan #${num} complete: no opportunities (${data.markets_scanned || 0} markets checked)`);
      }
    } catch {
      setScanCount((c) => c + 1);
      setLastScan("Just now");
      addLog("info", "Scan ran locally (API unavailable)");
    } finally {
      setScanLoading(false);
    }
  };

  // Fetch bot status
  const fetchBotStatus = async () => {
    try {
      const res = await fetch("/api/prediction-markets/bot/status");
      if (res.ok) {
        const data = await res.json();
        setBotStatus(data);
        setBotRunning(data.running);
        setIsLive(true);

        // Merge activity log from bot into local analysis log
        if (data.activity_log && data.activity_log.length > 0) {
          setAnalysisLog((prev) => {
            const existingIds = new Set(prev.map((e: any) => e.id));
            const newEntries = data.activity_log
              .filter((e: any) => !existingIds.has(e.id))
              .map((e: any) => ({
                ...e,
                timestamp: e.timestamp
                  ? new Date(e.timestamp).toLocaleTimeString()
                  : new Date().toLocaleTimeString(),
              }));
            if (newEntries.length === 0) return prev;
            return [...newEntries, ...prev].slice(0, 200);
          });
        }

        // Update scan count and opportunities from last scan
        if (data.total_scans) setScanCount(data.total_scans);
        if (data.last_scan_result?.executions) {
          setLastScan(data.last_scan_at ? new Date(data.last_scan_at).toLocaleTimeString() : "Just now");
        }
      }
    } catch {}
  };

  // Fetch live positions from executor
  const fetchPositions = async () => {
    try {
      const res = await fetch("/api/prediction-markets/portfolio");
      if (res.ok) {
        const data = await res.json();
        setPortfolioSummary(data);
        if (data.positions && data.positions.length > 0) {
          setLivePositions(data.positions.map((p: any, i: number) => ({
            id: String(i),
            market: p.market_question || p.market_id,
            outcome: p.outcome_label || p.token_id,
            side: p.side === "long" ? "BUY" : "SELL",
            entryPrice: p.avg_entry_price,
            currentPrice: p.current_price,
            size: p.market_value,
            pnl: p.total_pnl,
            strategy: p.strategy,
            openedAt: p.opened_at ? new Date(p.opened_at).toLocaleTimeString() : "",
          })));
        }
      }
    } catch {}
  };

  // Fetch equity curve
  const fetchEquityCurve = async () => {
    try {
      const res = await fetch("/api/prediction-markets/pnl-history?limit=200");
      if (res.ok) {
        const data = await res.json();
        setEquityCurve(data.snapshots || []);
      }
    } catch {}
  };

  // Fetch latest opportunities from bot activity
  const fetchBotOpportunities = async () => {
    try {
      const res = await fetch("/api/prediction-markets/bot/activity?limit=50");
      if (res.ok) {
        const data = await res.json();
        // Merge activity entries
        if (data.entries && data.entries.length > 0) {
          setAnalysisLog((prev) => {
            const existingIds = new Set(prev.map((e: any) => e.id));
            const newEntries = data.entries
              .filter((e: any) => !existingIds.has(e.id))
              .map((e: any) => ({
                ...e,
                timestamp: e.timestamp
                  ? new Date(e.timestamp).toLocaleTimeString()
                  : new Date().toLocaleTimeString(),
              }));
            if (newEntries.length === 0) return prev;
            return [...newEntries, ...prev].slice(0, 200);
          });
        }
        if (data.total_scans) setScanCount(data.total_scans);
      }
    } catch {}
  };

  // Add entry to analysis log
  const addLog = (type: "scan" | "signal" | "execute" | "skip" | "info", message: string, strategy?: string) => {
    const entry = {
      id: `local-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
      timestamp: new Date().toLocaleTimeString(),
      type,
      strategy,
      message,
    };
    setAnalysisLog((prev) => [entry, ...prev].slice(0, 200));
  };

  // Reset paper trading state
  const resetPortfolio = async () => {
    if (!confirm("Reset all paper trading positions and P&L? This cannot be undone.")) return;
    try {
      const res = await fetch("/api/prediction-markets/portfolio/reset", { method: "POST" });
      if (res.ok) {
        setStrategies(DEFAULT_STRATEGIES.map(s => ({ ...s, positions: 0, pnl: 0 })));
        setOpportunities([]);
        setLivePositions([]);
        setEquityCurve([]);
        setPortfolioSummary(null);
        setScanCount(0);
        setAnalysisLog([]);
        addLog("info", "Portfolio reset. All positions cleared, P&L zeroed.");
      }
    } catch {
      setStrategies(DEFAULT_STRATEGIES.map(s => ({ ...s, positions: 0, pnl: 0 })));
      setOpportunities([]);
      setLivePositions([]);
      setEquityCurve([]);
      setPortfolioSummary(null);
      setScanCount(0);
      setAnalysisLog([]);
      addLog("info", "Portfolio reset locally. Backend unavailable.");
    }
  };

  // Check Polymarket connection
  const checkPolymarketConnection = async () => {
    try {
      const res = await fetch("/api/prediction-markets/status");
      if (res.ok) {
        const data = await res.json();
        setPolyStatus(data);
        if (data.connected) {
          addLog("info", `Polymarket connected — Gamma: ${data.gamma_api.latency_ms}ms, CLOB: ${data.clob_api.latency_ms}ms`);
        }
      }
    } catch {
      setPolyStatus({ connected: false });
    }
  };

  // Start/stop bot
  const toggleBot = async () => {
    try {
      if (botRunning) {
        await fetch("/api/prediction-markets/bot/stop", { method: "POST" });
        setBotRunning(false);
        addLog("info", "Bot stopped");
      } else {
        await fetch("/api/prediction-markets/bot/start", { method: "POST" });
        setBotRunning(true);
        addLog("info", "Bot started — automated scanning enabled");
      }
      await fetchBotStatus();
    } catch {}
  };

  // On mount: check connection and fetch data
  useEffect(() => {
    checkPolymarketConnection();
    fetchMarkets();
    fetchStrategies();
    fetchBotStatus();
    fetchPositions();
  }, []);

  // Refresh data when tabs change
  useEffect(() => {
    if (activeTab === "portfolio") {
      fetchPositions();
      fetchEquityCurve();
    } else if (activeTab === "bot") {
      fetchBotStatus();
    } else if (activeTab === "positions") {
      fetchPositions();
      fetchStrategies();
    } else if (activeTab === "analysis") {
      fetchBotOpportunities();
    } else if (activeTab === "scanner") {
      fetchBotOpportunities();
      fetchPositions();
    }
  }, [activeTab]);

  // Auto-poll: refresh bot data and positions every 10s when bot is running
  useEffect(() => {
    const interval = setInterval(() => {
      fetchBotStatus();
      fetchPositions();
      fetchStrategies();
      if (activeTab === "analysis" || activeTab === "scanner") {
        fetchBotOpportunities();
      }
    }, 10000);
    return () => clearInterval(interval);
  }, [activeTab]);

  // Auto-scan every 2 minutes when manual scanning is enabled
  useEffect(() => {
    if (!scanning) return;
    runScan();
    const interval = setInterval(runScan, 120000);
    return () => clearInterval(interval);
  }, [scanning]);

  // Auto-scroll opportunity stream
  useEffect(() => {
    if (streamRef.current) {
      streamRef.current.scrollTop = 0;
    }
  }, [opportunities]);

  const toggleStrategy = (id: string) => {
    setStrategies((prev) =>
      prev.map((s) => (s.id === id ? { ...s, enabled: !s.enabled } : s))
    );
  };

  // Use livePositions.length as the source of truth for position count
  const positionCount = livePositions.length;
  const totalPnl = portfolioSummary?.total_pnl ?? strategies.reduce((sum, s) => sum + s.pnl, 0);
  const enabledCount = strategies.filter((s) => s.enabled).length;
  const marketsScanned = botStatus?.last_scan_result?.opportunities
    ? scanCount * 12
    : scanCount * 12;

  const filteredMarkets = markets.filter(
    (m) =>
      (exchangeFilter === "all" || m.exchange === exchangeFilter) &&
      (!searchQuery ||
        m.question.toLowerCase().includes(searchQuery.toLowerCase()) ||
        m.category.toLowerCase().includes(searchQuery.toLowerCase()))
  );

  // ----------------------------------------------------------------
  // Render
  // ----------------------------------------------------------------

  return (
    <div className="min-h-screen bg-[#F8F8FA]">
      {/* ============ HEADER ============ */}
      <div className="sticky top-0 z-30 bg-white/80 backdrop-blur-xl border-b border-gray-200/60">
        <div className="max-w-[1440px] mx-auto px-6 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-violet-500 to-purple-600 flex items-center justify-center shadow-lg shadow-violet-500/25">
                <Target className="w-4.5 h-4.5 text-white" />
              </div>
              <div>
                <h1 className="text-lg font-semibold text-gray-900 tracking-tight">Prediction Markets</h1>
                <div className="flex items-center gap-2 mt-0.5">
                  {polyStatus.connected === null ? (
                    <span className="text-[10px] font-medium px-1.5 py-0.5 rounded-md bg-gray-100 text-gray-400">Connecting...</span>
                  ) : polyStatus.connected ? (
                    <button
                      onClick={checkPolymarketConnection}
                      className="flex items-center gap-1 text-[10px] font-medium px-1.5 py-0.5 rounded-md bg-emerald-50 text-emerald-600 hover:bg-emerald-100 transition-colors"
                    >
                      <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                      Connected
                    </button>
                  ) : (
                    <button
                      onClick={checkPolymarketConnection}
                      className="flex items-center gap-1 text-[10px] font-medium px-1.5 py-0.5 rounded-md bg-red-50 text-red-500 hover:bg-red-100 transition-colors"
                    >
                      <span className="w-1.5 h-1.5 rounded-full bg-red-400" />
                      Disconnected
                    </button>
                  )}
                  <span className="text-[10px] text-gray-400">{enabledCount} strategies active</span>
                </div>
              </div>
            </div>

            <div className="flex items-center gap-2">
              {/* Bot status indicator */}
              {botRunning && (
                <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-50 border border-emerald-200/60">
                  <div className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
                  <span className="text-xs font-medium text-emerald-700">Bot Active</span>
                  <span className="text-[10px] text-emerald-500 tabular-nums">#{scanCount}</span>
                </div>
              )}
              <button
                onClick={resetPortfolio}
                className="px-3 py-1.5 rounded-lg text-xs font-medium text-gray-400 hover:text-red-500 hover:bg-red-50 transition-colors"
              >
                Reset
              </button>
              <div className="w-px h-5 bg-gray-200" />
              <button
                onClick={() => setScanning(!scanning)}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                  scanning
                    ? "bg-violet-100 text-violet-700 shadow-sm shadow-violet-500/10"
                    : "bg-gray-100 text-gray-600 hover:bg-gray-200"
                }`}
              >
                {scanning ? <Pause className="w-3 h-3" /> : <Play className="w-3 h-3" />}
                {scanning ? "Scanning" : "Auto-Scan"}
              </button>
            </div>
          </div>
        </div>
      </div>

      <div className="max-w-[1440px] mx-auto px-6 py-6">
        {/* ============ STATS ROW ============ */}
        <div className="grid grid-cols-4 gap-3 mb-6">
          {[
            {
              label: "Total P&L",
              value: `${totalPnl >= 0 ? "+" : ""}$${totalPnl.toFixed(2)}`,
              color: totalPnl >= 0 ? "text-emerald-600" : "text-red-500",
              icon: DollarSign,
              sub: portfolioSummary?.total_exposure ? `$${portfolioSummary.total_exposure.toFixed(2)} exposure` : null,
            },
            {
              label: "Open Positions",
              value: String(positionCount),
              color: "text-gray-900",
              icon: Activity,
              sub: positionCount > 0 ? `across ${new Set(livePositions.map(p => p.strategy)).size} strategies` : null,
            },
            {
              label: "Active Strategies",
              value: `${enabledCount}`,
              valueSuffix: `/${strategies.length}`,
              color: "text-gray-900",
              icon: Zap,
              sub: botRunning ? "Bot running" : "Bot stopped",
            },
            {
              label: "Scans Completed",
              value: String(scanCount),
              color: "text-gray-900",
              icon: BarChart3,
              sub: lastScan !== "Never" ? `Last: ${lastScan}` : null,
            },
          ].map((stat) => (
            <div key={stat.label} className="bg-white rounded-xl p-4 border border-gray-100 shadow-sm">
              <div className="flex items-center gap-1.5 mb-2">
                <stat.icon className="w-3.5 h-3.5 text-gray-400" />
                <span className="text-[11px] font-medium text-gray-500 uppercase tracking-wide">{stat.label}</span>
              </div>
              <p className={`text-xl font-semibold tabular-nums ${stat.color}`}>
                {stat.value}
                {(stat as any).valueSuffix && <span className="text-sm font-normal text-gray-400">{(stat as any).valueSuffix}</span>}
              </p>
              {stat.sub && <p className="text-[11px] text-gray-400 mt-0.5">{stat.sub}</p>}
            </div>
          ))}
        </div>

        {/* ============ STRATEGY CARDS ============ */}
        <div className="grid grid-cols-7 gap-2 mb-6">
          {strategies.map((strategy) => {
            const colors = strategyColors[strategy.id] || strategyColors.weather_arb;
            return (
              <button
                key={strategy.id}
                onClick={() => toggleStrategy(strategy.id)}
                className={`relative rounded-xl p-3 text-left transition-all border ${
                  strategy.enabled
                    ? `${colors.border} ${colors.bg} shadow-sm`
                    : "border-gray-100 bg-gray-50/50 opacity-50"
                }`}
              >
                <div className="flex items-center gap-1.5 mb-1.5">
                  <strategy.icon className={`w-3.5 h-3.5 ${strategy.enabled ? colors.text : "text-gray-400"}`} />
                  <span className="text-[11px] font-semibold text-gray-900 truncate">{strategy.name}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-[10px] text-gray-400 tabular-nums">{strategy.positions} pos</span>
                  <span
                    className={`text-[11px] font-semibold tabular-nums ${
                      strategy.pnl >= 0 ? "text-emerald-600" : "text-red-500"
                    }`}
                  >
                    {strategy.pnl >= 0 ? "+" : ""}${strategy.pnl.toFixed(2)}
                  </span>
                </div>
                {/* Toggle dot */}
                <div className={`absolute top-2 right-2 w-2 h-2 rounded-full ${strategy.enabled ? colors.dot : "bg-gray-300"}`} />
              </button>
            );
          })}
        </div>

        {/* ============ TAB NAVIGATION ============ */}
        <div className="flex items-center gap-0.5 mb-5 border-b border-gray-200">
          {([
            { key: "scanner" as const, label: "Live Scanner", icon: Radio },
            { key: "analysis" as const, label: "Analysis", icon: Eye },
            { key: "markets" as const, label: "Markets", icon: Globe },
            { key: "positions" as const, label: `Positions${positionCount > 0 ? ` (${positionCount})` : ""}`, icon: Layers },
            { key: "portfolio" as const, label: "Portfolio", icon: Wallet },
            { key: "bot" as const, label: "Bot", icon: Bot },
          ]).map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium transition-colors border-b-2 -mb-px ${
                activeTab === tab.key
                  ? "border-violet-500 text-gray-900"
                  : "border-transparent text-gray-500 hover:text-gray-700"
              }`}
            >
              <tab.icon className="w-3.5 h-3.5" />
              {tab.label}
              {tab.key === "analysis" && analysisLog.length > 0 && (
                <span className="w-1.5 h-1.5 rounded-full bg-violet-500 animate-pulse" />
              )}
              {tab.key === "bot" && botRunning && (
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
              )}
            </button>
          ))}
        </div>

        {/* ============ LIVE SCANNER TAB ============ */}
        {activeTab === "scanner" && (
          <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
            <div className="px-5 py-3.5 border-b border-gray-100 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <div className="w-2 h-2 rounded-full bg-violet-500 animate-pulse" />
                <h2 className="text-sm font-semibold text-gray-900">Opportunity Stream</h2>
                <span className="text-xs text-gray-400">
                  {opportunities.length > 0 ? `${opportunities.length} signals` : "Waiting for scan..."}
                </span>
              </div>
              <button
                onClick={runScan}
                disabled={scanLoading}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-violet-50 text-violet-600 hover:bg-violet-100 disabled:opacity-50 transition-colors"
              >
                <RefreshCw className={`w-3 h-3 ${scanLoading ? "animate-spin" : ""}`} />
                {scanLoading ? "Scanning..." : "Scan Now"}
              </button>
            </div>
            <div ref={streamRef} className="divide-y divide-gray-50 max-h-[520px] overflow-y-auto">
              {opportunities.length > 0 ? opportunities.map((opp) => {
                const colors = strategyColors[opp.strategy] || strategyColors.weather_arb;
                return (
                  <div key={opp.id} className="px-5 py-3.5 hover:bg-gray-50/50 transition-colors">
                    <div className="flex items-start justify-between">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-1.5 mb-1">
                          <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded-md ${colors.badge}`}>
                            {strategyLabels[opp.strategy] || opp.strategy}
                          </span>
                          <span
                            className={`text-[10px] font-semibold px-1.5 py-0.5 rounded-md ${
                              opp.side === "BUY" ? "bg-emerald-50 text-emerald-600" : "bg-red-50 text-red-500"
                            }`}
                          >
                            {opp.side}
                          </span>
                          <span className="text-[10px] text-gray-400">{opp.timestamp}</span>
                        </div>
                        <p className="text-sm text-gray-900 font-medium truncate">{opp.market}</p>
                        <p className="text-xs text-gray-500 mt-0.5 line-clamp-1">{opp.reason}</p>
                      </div>
                      <div className="text-right ml-4 flex-shrink-0">
                        <p className="text-base font-bold text-emerald-600 tabular-nums">
                          {(opp.edge * 100).toFixed(1)}%
                        </p>
                        <p className="text-[10px] text-gray-400 uppercase tracking-wider">Edge</p>
                        <div className="flex items-center gap-1 mt-1 justify-end">
                          <div className="w-14 h-1 bg-gray-100 rounded-full overflow-hidden">
                            <div
                              className="h-full bg-violet-400 rounded-full"
                              style={{ width: `${opp.confidence * 100}%` }}
                            />
                          </div>
                          <span className="text-[10px] text-gray-400 tabular-nums">
                            {(opp.confidence * 100).toFixed(0)}%
                          </span>
                        </div>
                      </div>
                    </div>
                  </div>
                );
              }) : (
                <div className="py-16 text-center">
                  <Radio className="w-8 h-8 text-gray-300 mx-auto mb-3" />
                  <p className="text-sm text-gray-500 font-medium">No signals yet</p>
                  <p className="text-xs text-gray-400 mt-1">
                    {botRunning ? "Bot is scanning — signals will appear here" : "Start the bot or run a manual scan"}
                  </p>
                </div>
              )}
            </div>
          </div>
        )}

        {/* ============ ANALYSIS TAB ============ */}
        {activeTab === "analysis" && (
          <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
            <div className="px-5 py-3.5 border-b border-gray-100 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <div className="w-2 h-2 rounded-full bg-violet-500 animate-pulse" />
                <h2 className="text-sm font-semibold text-gray-900">Live Analysis</h2>
                <span className="text-xs text-gray-400">Strategy rationales, scan results, and trade logic</span>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={fetchBotOpportunities}
                  className="flex items-center gap-1 text-xs text-gray-400 hover:text-gray-600 transition-colors"
                >
                  <RotateCw className="w-3 h-3" />
                  Refresh
                </button>
                <button
                  onClick={() => setAnalysisLog([])}
                  className="text-xs text-gray-400 hover:text-gray-600 transition-colors"
                >
                  Clear
                </button>
              </div>
            </div>
            <div ref={analysisRef} className="max-h-[600px] overflow-y-auto divide-y divide-gray-50">
              {analysisLog.length > 0 ? analysisLog.map((entry) => {
                const typeStyles: Record<string, { badge: string; label: string }> = {
                  scan: { badge: "bg-blue-50 text-blue-600", label: "SCAN" },
                  signal: { badge: "bg-emerald-50 text-emerald-600", label: "SIGNAL" },
                  execute: { badge: "bg-violet-50 text-violet-600", label: "EXEC" },
                  skip: { badge: "bg-gray-100 text-gray-500", label: "SKIP" },
                  info: { badge: "bg-amber-50 text-amber-600", label: "INFO" },
                };
                const style = typeStyles[entry.type] || typeStyles.info;
                const stratColors = entry.strategy ? strategyColors[entry.strategy] : null;
                return (
                  <div key={entry.id} className="px-5 py-2.5 hover:bg-gray-50/50 transition-colors">
                    <div className="flex items-start gap-2.5">
                      <span className="text-[10px] text-gray-400 tabular-nums whitespace-nowrap mt-0.5 w-16 flex-shrink-0">{entry.timestamp}</span>
                      <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded-md whitespace-nowrap ${style.badge}`}>
                        {style.label}
                      </span>
                      {stratColors && (
                        <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded-md whitespace-nowrap ${stratColors.badge}`}>
                          {strategyLabels[entry.strategy!] || entry.strategy}
                        </span>
                      )}
                      <p className="text-xs text-gray-600 leading-relaxed min-w-0">{entry.message}</p>
                    </div>
                  </div>
                );
              }) : (
                <div className="py-16 text-center">
                  <Eye className="w-8 h-8 text-gray-300 mx-auto mb-3" />
                  <p className="text-sm text-gray-500 font-medium">No analysis entries yet</p>
                  <p className="text-xs text-gray-400 mt-1">Start scanning or enable the bot to see live rationales</p>
                </div>
              )}
            </div>
          </div>
        )}

        {/* ============ BROWSE MARKETS TAB ============ */}
        {activeTab === "markets" && (
          <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
            <div className="px-5 py-3.5 border-b border-gray-100">
              <div className="flex items-center gap-3">
                <div className="relative flex-1">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
                  <input
                    type="text"
                    placeholder="Search markets..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    className="w-full pl-10 pr-4 py-2 bg-gray-50 rounded-lg text-sm text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-violet-500/20 focus:bg-white border-0"
                  />
                </div>
                <span className="text-xs font-medium px-2 py-1 rounded-md bg-purple-50 text-purple-600">
                  {filteredMarkets.length} markets
                </span>
              </div>
            </div>
            <div className="divide-y divide-gray-50 max-h-[600px] overflow-y-auto">
              {filteredMarkets.map((market) => (
                <div key={market.id} className="px-5 py-3.5 hover:bg-gray-50/50 transition-colors">
                  <div className="flex items-start justify-between mb-2">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-1.5 mb-1">
                        <span className="text-[10px] font-medium px-1.5 py-0.5 rounded-md bg-gray-100 text-gray-500">
                          {market.category}
                        </span>
                        {market.endDate && (
                          <span className="text-[10px] text-gray-400">
                            Ends {new Date(market.endDate).toLocaleDateString()}
                          </span>
                        )}
                      </div>
                      <p className="text-sm font-medium text-gray-900">{market.question}</p>
                    </div>
                    <div className="text-right ml-4 flex-shrink-0 text-[10px] text-gray-400">
                      <p>Vol: ${(market.volume / 1000).toFixed(0)}K</p>
                      {market.liquidity > 0 && <p>Liq: ${(market.liquidity / 1000).toFixed(0)}K</p>}
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {market.outcomes.map((outcome, i) => (
                      <div
                        key={i}
                        className="flex items-center gap-2 px-2.5 py-1 rounded-lg bg-gray-50 border border-gray-100"
                      >
                        <span className="text-xs text-gray-600">{outcome.label}</span>
                        <span
                          className={`text-xs font-bold tabular-nums ${
                            outcome.price >= 0.5 ? "text-emerald-600" : "text-gray-900"
                          }`}
                        >
                          {(outcome.price * 100).toFixed(0)}c
                        </span>
                        <div className="w-10 h-1 bg-gray-200 rounded-full overflow-hidden">
                          <div
                            className={`h-full rounded-full ${outcome.price >= 0.5 ? "bg-emerald-400" : "bg-gray-400"}`}
                            style={{ width: `${outcome.price * 100}%` }}
                          />
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ============ POSITIONS TAB ============ */}
        {activeTab === "positions" && (
          <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
            <div className="px-5 py-3.5 border-b border-gray-100 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <h2 className="text-sm font-semibold text-gray-900">Open Positions</h2>
                <span className="text-xs text-gray-400">{positionCount} positions</span>
              </div>
              <div className="flex items-center gap-3">
                <span className="text-xs text-gray-500">Unrealized P&L:</span>
                <span className={`text-sm font-bold tabular-nums ${
                  livePositions.reduce((s, p) => s + p.pnl, 0) >= 0 ? "text-emerald-600" : "text-red-500"
                }`}>
                  {livePositions.length > 0
                    ? `${livePositions.reduce((s, p) => s + p.pnl, 0) >= 0 ? "+" : ""}$${livePositions.reduce((s, p) => s + p.pnl, 0).toFixed(2)}`
                    : "$0.00"}
                </span>
              </div>
            </div>
            {livePositions.length > 0 ? (
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Market</th>
                    <th>Strategy</th>
                    <th>Side</th>
                    <th>Entry</th>
                    <th>Current</th>
                    <th>Size</th>
                    <th>P&L</th>
                    <th>Opened</th>
                  </tr>
                </thead>
                <tbody>
                  {livePositions.map((pos) => {
                    const colors = strategyColors[pos.strategy] || strategyColors.weather_arb;
                    return (
                      <tr key={pos.id}>
                        <td>
                          <p className="text-sm font-medium text-gray-900 truncate max-w-xs">{pos.market}</p>
                          <p className="text-[10px] text-gray-400">{pos.outcome}</p>
                        </td>
                        <td>
                          <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded-md ${colors.badge}`}>
                            {strategyLabels[pos.strategy] || pos.strategy}
                          </span>
                        </td>
                        <td>
                          <span className={`text-xs font-semibold ${pos.side === "BUY" ? "text-emerald-600" : "text-red-500"}`}>
                            {pos.side}
                          </span>
                        </td>
                        <td className="tabular-nums text-sm">${pos.entryPrice.toFixed(2)}</td>
                        <td className="tabular-nums text-sm">${pos.currentPrice.toFixed(2)}</td>
                        <td className="tabular-nums text-sm">${pos.size.toFixed(2)}</td>
                        <td>
                          <span className={`text-sm font-semibold tabular-nums ${pos.pnl >= 0 ? "text-emerald-600" : "text-red-500"}`}>
                            {pos.pnl >= 0 ? "+" : ""}${pos.pnl.toFixed(2)}
                          </span>
                        </td>
                        <td className="text-xs text-gray-400">{pos.openedAt}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            ) : (
              <div className="py-16 text-center">
                <Layers className="w-8 h-8 text-gray-300 mx-auto mb-3" />
                <p className="text-sm text-gray-500 font-medium">No open positions</p>
                <p className="text-xs text-gray-400 mt-1">Positions will appear here when the bot executes trades</p>
              </div>
            )}
          </div>
        )}

        {/* ============ PORTFOLIO TAB ============ */}
        {activeTab === "portfolio" && (
          <div className="space-y-4">
            {/* Portfolio Summary */}
            <div className="grid grid-cols-4 gap-3">
              {[
                { label: "Total Value", value: `$${portfolioSummary?.total_exposure?.toFixed(2) || "0.00"}`, color: "text-gray-900" },
                { label: "Total P&L", value: `${(portfolioSummary?.total_pnl || 0) >= 0 ? "+" : ""}$${(portfolioSummary?.total_pnl || 0).toFixed(2)}`, color: (portfolioSummary?.total_pnl || 0) >= 0 ? "text-emerald-600" : "text-red-500" },
                { label: "Total Fees", value: `$${portfolioSummary?.total_fees?.toFixed(2) || "0.00"}`, color: "text-gray-900" },
                { label: "Orders", value: String(portfolioSummary?.total_orders || 0), color: "text-gray-900" },
              ].map((item) => (
                <div key={item.label} className="bg-white rounded-xl p-4 border border-gray-100 shadow-sm">
                  <span className="text-[11px] font-medium text-gray-500 uppercase tracking-wide">{item.label}</span>
                  <p className={`text-xl font-semibold tabular-nums mt-1 ${item.color}`}>{item.value}</p>
                </div>
              ))}
            </div>

            {/* Equity Curve */}
            <div className="bg-white rounded-xl p-5 border border-gray-100 shadow-sm">
              <h2 className="text-sm font-semibold text-gray-900 mb-4">Equity Curve</h2>
              {equityCurve.length > 0 ? (
                <div className="h-48 flex items-end gap-px">
                  {equityCurve.map((s: any, i: number) => {
                    const maxVal = Math.max(...equityCurve.map((x: any) => x.total_value_usd || 100));
                    const minVal = Math.min(...equityCurve.map((x: any) => x.total_value_usd || 100));
                    const range = maxVal - minVal || 1;
                    const height = ((s.total_value_usd - minVal) / range) * 100;
                    const isPositive = (s.unrealized_pnl + s.realized_pnl) >= 0;
                    return (
                      <div
                        key={i}
                        className={`flex-1 rounded-t transition-all ${isPositive ? "bg-emerald-400/80" : "bg-red-400/80"} hover:opacity-80`}
                        style={{ height: `${Math.max(height, 2)}%` }}
                        title={`$${s.total_value_usd?.toFixed(2)} | ${new Date(s.snapshot_at).toLocaleString()}`}
                      />
                    );
                  })}
                </div>
              ) : (
                <div className="h-48 flex items-center justify-center">
                  <div className="text-center">
                    <BarChart3 className="w-8 h-8 text-gray-300 mx-auto mb-2" />
                    <p className="text-sm text-gray-400">No snapshots yet. Start the bot to build an equity curve.</p>
                  </div>
                </div>
              )}
            </div>

            {/* Polymarket Exposure */}
            {equityCurve.length > 0 && (
              <div className="bg-white rounded-xl p-4 border border-gray-100 shadow-sm">
                <span className="text-[11px] font-medium text-gray-500 uppercase tracking-wide">Polymarket Exposure</span>
                <p className="text-lg font-semibold tabular-nums text-purple-600 mt-1">
                  ${equityCurve[equityCurve.length - 1]?.polymarket_value?.toFixed(2) || "0.00"}
                </p>
              </div>
            )}
          </div>
        )}

        {/* ============ BOT TAB ============ */}
        {activeTab === "bot" && (
          <div className="space-y-4">
            {/* Bot Control */}
            <div className="bg-white rounded-xl p-5 border border-gray-100 shadow-sm">
              <div className="flex items-center justify-between mb-5">
                <div>
                  <h2 className="text-sm font-semibold text-gray-900">Trading Bot</h2>
                  <p className="text-xs text-gray-500 mt-0.5">Automated scan → Kelly size → execute → persist</p>
                </div>
                <button
                  onClick={toggleBot}
                  className={`px-5 py-2 rounded-lg font-semibold text-sm transition-all ${
                    botRunning
                      ? "bg-red-50 text-red-600 hover:bg-red-100 border border-red-200/60"
                      : "bg-emerald-50 text-emerald-700 hover:bg-emerald-100 border border-emerald-200/60"
                  }`}
                >
                  {botRunning ? "Stop Bot" : "Start Bot"}
                </button>
              </div>

              <div className="grid grid-cols-3 gap-3">
                <div className="p-3 rounded-lg bg-gray-50">
                  <span className="text-[10px] font-medium text-gray-500 uppercase tracking-wider">Status</span>
                  <div className="flex items-center gap-2 mt-1.5">
                    <div className={`w-2.5 h-2.5 rounded-full ${botRunning ? "bg-emerald-500 animate-pulse" : "bg-gray-400"}`} />
                    <span className="text-sm font-semibold text-gray-900">{botRunning ? "Running" : "Stopped"}</span>
                  </div>
                </div>
                <div className="p-3 rounded-lg bg-gray-50">
                  <span className="text-[10px] font-medium text-gray-500 uppercase tracking-wider">Scans</span>
                  <p className="text-lg font-bold tabular-nums text-gray-900 mt-1.5">{botStatus?.total_scans || 0}</p>
                </div>
                <div className="p-3 rounded-lg bg-gray-50">
                  <span className="text-[10px] font-medium text-gray-500 uppercase tracking-wider">Executions</span>
                  <p className="text-lg font-bold tabular-nums text-gray-900 mt-1.5">{botStatus?.total_executions || 0}</p>
                </div>
              </div>
            </div>

            {/* Risk Manager */}
            <div className="bg-white rounded-xl p-5 border border-gray-100 shadow-sm">
              <h2 className="text-sm font-semibold text-gray-900 mb-3">Risk Manager</h2>
              <div className="grid grid-cols-4 gap-3">
                <div className="p-3 rounded-lg bg-gray-50">
                  <span className="text-[10px] font-medium text-gray-500 uppercase">Daily P&L</span>
                  <p className={`text-base font-bold tabular-nums mt-1 ${(botStatus?.risk_manager?.daily_pnl || 0) >= 0 ? "text-emerald-600" : "text-red-500"}`}>
                    ${(botStatus?.risk_manager?.daily_pnl || 0).toFixed(2)}
                  </p>
                </div>
                <div className="p-3 rounded-lg bg-gray-50">
                  <span className="text-[10px] font-medium text-gray-500 uppercase">Circuit Breaker</span>
                  <p className="text-sm font-semibold mt-1.5">
                    {botStatus?.risk_manager?.circuit_breaker_active ? (
                      <span className="text-red-600">ACTIVE</span>
                    ) : (
                      <span className="text-emerald-600">OK</span>
                    )}
                  </p>
                </div>
                <div className="p-3 rounded-lg bg-gray-50">
                  <span className="text-[10px] font-medium text-gray-500 uppercase">Orders/min</span>
                  <p className="text-base font-bold tabular-nums text-gray-900 mt-1">
                    {botStatus?.risk_manager?.orders_last_minute || 0}
                    <span className="text-xs font-normal text-gray-400">/{botStatus?.risk_manager?.max_orders_per_minute || 10}</span>
                  </p>
                </div>
                <div className="p-3 rounded-lg bg-gray-50">
                  <span className="text-[10px] font-medium text-gray-500 uppercase">Positions</span>
                  <p className="text-base font-bold tabular-nums text-gray-900 mt-1">
                    {botStatus?.portfolio?.total_positions || positionCount}
                    <span className="text-xs font-normal text-gray-400">/{botStatus?.risk_manager?.max_total_positions || 50}</span>
                  </p>
                </div>
              </div>

              {botStatus?.risk_manager?.disabled_strategies?.length > 0 && (
                <div className="mt-3 p-3 rounded-lg bg-red-50 border border-red-100">
                  <span className="text-[10px] font-semibold text-red-600 uppercase">Disabled Strategies</span>
                  <div className="flex flex-wrap gap-1.5 mt-1.5">
                    {botStatus.risk_manager.disabled_strategies.map((s: string) => (
                      <span key={s} className="text-[10px] font-medium px-1.5 py-0.5 rounded-md bg-red-100 text-red-600">{s}</span>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* Kelly Config */}
            <div className="bg-white rounded-xl p-5 border border-gray-100 shadow-sm">
              <h2 className="text-sm font-semibold text-gray-900 mb-3">Kelly Sizing</h2>
              <div className="grid grid-cols-5 gap-2">
                {[
                  { label: "Fractional Kelly", value: botStatus?.kelly_config?.fractional_kelly || 0.25 },
                  { label: "Min Bet", value: `$${botStatus?.kelly_config?.min_bet_usd || 1}` },
                  { label: "Max Bet", value: `$${botStatus?.kelly_config?.max_bet_usd || 50}` },
                  { label: "Min Edge", value: `${((botStatus?.kelly_config?.min_edge || 0.03) * 100).toFixed(0)}%` },
                  { label: "Min Confidence", value: `${((botStatus?.kelly_config?.min_confidence || 0.6) * 100).toFixed(0)}%` },
                ].map((item) => (
                  <div key={item.label} className="p-2.5 rounded-lg bg-gray-50 text-center">
                    <span className="text-[10px] font-medium text-gray-500 uppercase">{item.label}</span>
                    <p className="text-sm font-bold tabular-nums text-gray-900 mt-1">{item.value}</p>
                  </div>
                ))}
              </div>
            </div>

            {/* Manual Scan Button */}
            <button
              onClick={async () => {
                try {
                  const res = await fetch("/api/prediction-markets/bot/scan-now", { method: "POST" });
                  if (res.ok) {
                    const data = await res.json();
                    addLog("scan", `Manual scan: ${data.opportunities || 0} opportunities → ${data.executed || 0} executed`);
                    fetchBotStatus();
                    fetchPositions();
                    fetchStrategies();
                  }
                } catch {}
              }}
              className="w-full py-2.5 rounded-xl bg-violet-50 text-violet-600 font-semibold text-sm hover:bg-violet-100 border border-violet-200/60 transition-colors"
            >
              Run Manual Scan + Execute
            </button>
          </div>
        )}
      </div>

      {/* ============ FOOTER ============ */}
      <div className="max-w-[1440px] mx-auto px-6 py-4">
        <div className="flex items-center gap-2 text-[11px] text-gray-400">
          <Shield className="w-3 h-3" />
          <span>
            Paper trading mode (dry_run=true). {isLive ? "Connected to Polymarket API." : "API offline — start backend: uvicorn backend.app.api.main:app --port 8000"}
          </span>
        </div>
      </div>
    </div>
  );
}
