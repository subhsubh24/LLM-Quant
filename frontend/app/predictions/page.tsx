"use client";

import { useState, useEffect, useRef } from "react";
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

const DEMO_STRATEGIES: StrategyConfig[] = [
  {
    id: "weather_arb",
    name: "Weather Arbitrage",
    description: "Compare NOAA forecasts to market prices. Buy undervalued temperature buckets.",
    icon: CloudSun,
    enabled: true,
    color: "cyan",
    positions: 8,
    pnl: 127.50,
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
    description: "Buy 95-99c outcomes at scale. Penny profits × thousands of trades.",
    icon: Target,
    enabled: true,
    color: "violet",
    positions: 42,
    pnl: 892.30,
    config: {
      "Min price": "$0.95",
      "Max price": "$0.99",
      "Min volume": "$50,000",
      "Max hours to resolution": "72h",
      "Max position": "$10.00",
    },
  },
  {
    id: "same_market_arb",
    name: "Same-Market Arbitrage",
    description: "YES + NO < $1.00? Buy both, guaranteed profit. Windows last milliseconds.",
    icon: Zap,
    enabled: false,
    color: "amber",
    positions: 0,
    pnl: 0,
    config: {
      "Min discount": "2.5%",
      "Min liquidity": "$1,000",
      "Max per trade": "$50.00",
    },
  },
  {
    id: "cross_market_arb",
    name: "Cross-Market Arbitrage",
    description: "Find logical inconsistencies between related markets.",
    icon: Globe,
    enabled: false,
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
    description: "Provide two-sided liquidity, capture bid-ask spread + Q-score rebates. Swisstony: $5 → $3.7M.",
    icon: ArrowLeftRight,
    enabled: true,
    color: "blue",
    positions: 15,
    pnl: 2340.80,
    config: {
      "Target spread": "2c",
      "Max spread": "3c (Q-score)",
      "Min liquidity": "$10,000",
      "Max volatility": "10%",
      "Rebalance at": "60% one-sided",
    },
  },
  {
    id: "flash_crash",
    name: "Flash Crash",
    description: "Buy crashed BTC/ETH tokens on 15-min markets. Two-leg arb when YES+NO < $0.97. 0x8dxd: $313 → $438K.",
    icon: AlertTriangle,
    enabled: true,
    color: "orange",
    positions: 3,
    pnl: 478.20,
    config: {
      "Crash threshold": "15%",
      "Max combined cost": "$0.97",
      "Min volume": "$5,000",
      "Target markets": "BTC, ETH, SOL",
    },
  },
  {
    id: "whale_copy",
    name: "Whale Copy Trading",
    description: "Follow top 7.6% profitable wallets. Wallet basket consensus (80%+ must agree) before entry.",
    icon: Users,
    enabled: false,
    color: "emerald",
    positions: 0,
    pnl: 0,
    config: {
      "Min trade size": "$1,000",
      "Max entry odds": "80c",
      "Basket consensus": "80%",
      "Tracked wallets": "Theo4, Fredi9999, Len93",
    },
  },
];

const DEMO_OPPORTUNITIES: Opportunity[] = [
  {
    id: "1",
    strategy: "weather_arb",
    market: "NYC temperature Feb 26 — 35-40°F",
    side: "BUY",
    entryPrice: 0.12,
    edge: 0.78,
    confidence: 0.92,
    reason: "NOAA forecasts 37°F. Bucket priced at $0.12 (88% edge).",
    timestamp: "2 min ago",
  },
  {
    id: "2",
    strategy: "near_certainty",
    market: "Will the sun rise tomorrow?",
    side: "BUY",
    entryPrice: 0.98,
    edge: 0.018,
    confidence: 0.99,
    reason: "Near-certain outcome at $0.98. $0.02/share profit, $45K volume.",
    timestamp: "5 min ago",
  },
  {
    id: "3",
    strategy: "weather_arb",
    market: "Chicago temperature Feb 26 — 25-30°F",
    side: "BUY",
    entryPrice: 0.09,
    edge: 0.81,
    confidence: 0.88,
    reason: "NOAA forecasts 27°F. Bucket severely underpriced at $0.09.",
    timestamp: "8 min ago",
  },
  {
    id: "4",
    strategy: "near_certainty",
    market: "Super Bowl LX will have a winner",
    side: "BUY",
    entryPrice: 0.97,
    edge: 0.028,
    confidence: 0.99,
    reason: "Game is tomorrow. $0.03/share, $120K volume, 12h to resolution.",
    timestamp: "12 min ago",
  },
  {
    id: "5",
    strategy: "weather_arb",
    market: "Seattle precipitation Feb 26 — Yes",
    side: "BUY",
    entryPrice: 0.22,
    edge: 0.58,
    confidence: 0.85,
    reason: "NOAA: 90% chance of rain. Market only pricing 22%.",
    timestamp: "15 min ago",
  },
  {
    id: "6",
    strategy: "market_making",
    market: "Will TikTok ban be enforced by April 2026?",
    side: "BUY",
    entryPrice: 0.42,
    edge: 0.035,
    confidence: 0.80,
    reason: "MM opportunity: spread=3.5c | liq=$245K | vol=$1.8M | Q-score=0.89",
    timestamp: "1 min ago",
  },
  {
    id: "7",
    strategy: "flash_crash",
    market: "BTC 15-min Up or Down — 2:30PM round",
    side: "BUY",
    entryPrice: 0.94,
    edge: 0.041,
    confidence: 0.95,
    reason: "FLASH CRASH: Down crashed 22% to $0.08 | Both sides: $0.94 → 4.1% net profit",
    timestamp: "30 sec ago",
  },
  {
    id: "8",
    strategy: "market_making",
    market: "Fed rate decision March 2026 — Hold",
    side: "BUY",
    entryPrice: 0.65,
    edge: 0.028,
    confidence: 0.80,
    reason: "MM opportunity: spread=2.8c | liq=$1.2M | vol=$8.9M | Q-score=0.92",
    timestamp: "3 min ago",
  },
  {
    id: "9",
    strategy: "whale_copy",
    market: "Will ETH exceed $5,000 by June 2026?",
    side: "BUY",
    entryPrice: 0.38,
    edge: 0.15,
    confidence: 0.88,
    reason: "WHALE CONSENSUS: 4/5 tracked wallets buying \"Yes\" at $0.38 | Whales: Theo4, Fredi9999, Len93 | Total size: $127K",
    timestamp: "7 min ago",
  },
];

const DEMO_POSITIONS: Position[] = [
  { id: "1", market: "NYC temp Feb 25 — 32-37°F", outcome: "Yes", side: "BUY", entryPrice: 0.14, currentPrice: 0.67, size: 5.0, pnl: 2.65, strategy: "weather_arb", openedAt: "6h ago" },
  { id: "2", market: "Will BTC be above $90K on Feb 28?", outcome: "Yes", side: "BUY", entryPrice: 0.96, currentPrice: 0.98, size: 10.0, pnl: 0.20, strategy: "near_certainty", openedAt: "2h ago" },
  { id: "3", market: "Chicago temp Feb 25 — 20-25°F", outcome: "Yes", side: "BUY", entryPrice: 0.11, currentPrice: 0.82, size: 5.0, pnl: 3.55, strategy: "weather_arb", openedAt: "8h ago" },
  { id: "4", market: "Fed rate decision March — Hold", outcome: "Yes", side: "BUY", entryPrice: 0.97, currentPrice: 0.98, size: 10.0, pnl: 0.10, strategy: "near_certainty", openedAt: "1h ago" },
  { id: "5", market: "Atlanta temp Feb 25 — 50-55°F", outcome: "Yes", side: "BUY", entryPrice: 0.18, currentPrice: 0.45, size: 5.0, pnl: 1.35, strategy: "weather_arb", openedAt: "4h ago" },
  { id: "6", market: "Will TikTok ban be enforced by April?", outcome: "Yes", side: "BUY", entryPrice: 0.42, currentPrice: 0.44, size: 25.0, pnl: 0.50, strategy: "market_making", openedAt: "15min ago" },
  { id: "7", market: "BTC 15-min Up or Down — 1:45PM", outcome: "Up+Down", side: "BUY", entryPrice: 0.93, currentPrice: 1.00, size: 50.0, pnl: 3.50, strategy: "flash_crash", openedAt: "20min ago" },
  { id: "8", market: "Oscar Best Picture 2026 — Film A", outcome: "Film A", side: "BUY", entryPrice: 0.33, currentPrice: 0.35, size: 25.0, pnl: 0.50, strategy: "market_making", openedAt: "30min ago" },
  { id: "9", market: "BTC 15-min Up or Down — 2:00PM", outcome: "Up+Down", side: "BUY", entryPrice: 0.95, currentPrice: 1.00, size: 50.0, pnl: 2.50, strategy: "flash_crash", openedAt: "10min ago" },
];

const DEMO_MARKETS: PredictionMarket[] = [
  { id: "1", question: "Will Bitcoin exceed $100,000 by March 2026?", category: "Crypto", outcomes: [{ label: "Yes", price: 0.72, tokenId: "a" }, { label: "No", price: 0.28, tokenId: "b" }], volume: 2500000, liquidity: 450000, endDate: "2026-03-31", active: true },
  { id: "2", question: "NYC temperature Feb 26 — which range?", category: "Weather", outcomes: [{ label: "Below 30°F", price: 0.08, tokenId: "c" }, { label: "30-35°F", price: 0.15, tokenId: "d" }, { label: "35-40°F", price: 0.52, tokenId: "e" }, { label: "Above 40°F", price: 0.25, tokenId: "f" }], volume: 85000, liquidity: 12000, endDate: "2026-02-26", active: true },
  { id: "3", question: "Will the Fed cut rates in March 2026?", category: "Economics", outcomes: [{ label: "Yes", price: 0.35, tokenId: "g" }, { label: "No", price: 0.65, tokenId: "h" }], volume: 8900000, liquidity: 1200000, endDate: "2026-03-19", active: true },
  { id: "4", question: "Will it rain in Seattle on Feb 27?", category: "Weather", outcomes: [{ label: "Yes", price: 0.78, tokenId: "i" }, { label: "No", price: 0.22, tokenId: "j" }], volume: 32000, liquidity: 5000, endDate: "2026-02-27", active: true },
  { id: "5", question: "Oscar Best Picture 2026 — which film?", category: "Entertainment", outcomes: [{ label: "Film A", price: 0.35, tokenId: "k" }, { label: "Film B", price: 0.28, tokenId: "l" }, { label: "Film C", price: 0.22, tokenId: "m" }, { label: "Other", price: 0.15, tokenId: "n" }], volume: 3200000, liquidity: 280000, endDate: "2026-03-02", active: true },
];

// ----------------------------------------------------------------
// Strategy color maps
// ----------------------------------------------------------------

const strategyColors: Record<string, { bg: string; text: string; border: string; badge: string; dot: string }> = {
  weather_arb: { bg: "bg-cyan-50", text: "text-cyan-700", border: "border-cyan-200", badge: "bg-cyan-100 text-cyan-700", dot: "bg-cyan-500" },
  near_certainty: { bg: "bg-violet-50", text: "text-violet-700", border: "border-violet-200", badge: "bg-violet-100 text-violet-700", dot: "bg-violet-500" },
  same_market_arb: { bg: "bg-amber-50", text: "text-amber-700", border: "border-amber-200", badge: "bg-amber-100 text-amber-700", dot: "bg-amber-500" },
  cross_market_arb: { bg: "bg-rose-50", text: "text-rose-700", border: "border-rose-200", badge: "bg-rose-100 text-rose-700", dot: "bg-rose-500" },
  market_making: { bg: "bg-blue-50", text: "text-blue-700", border: "border-blue-200", badge: "bg-blue-100 text-blue-700", dot: "bg-blue-500" },
  flash_crash: { bg: "bg-orange-50", text: "text-orange-700", border: "border-orange-200", badge: "bg-orange-100 text-orange-700", dot: "bg-orange-500" },
  whale_copy: { bg: "bg-emerald-50", text: "text-emerald-700", border: "border-emerald-200", badge: "bg-emerald-100 text-emerald-700", dot: "bg-emerald-500" },
};

const strategyLabels: Record<string, string> = {
  weather_arb: "Weather",
  near_certainty: "Certainty",
  same_market_arb: "Arb",
  cross_market_arb: "Cross-Mkt",
  market_making: "MM",
  flash_crash: "Flash",
  whale_copy: "Whale",
};

// ----------------------------------------------------------------
// Component
// ----------------------------------------------------------------

export default function PredictionsPage() {
  const [activeTab, setActiveTab] = useState<"scanner" | "markets" | "positions">("scanner");
  const [strategies, setStrategies] = useState(DEMO_STRATEGIES);
  const [scanning, setScanning] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [scanCount, setScanCount] = useState(147);
  const [lastScan, setLastScan] = useState("Just now");
  const streamRef = useRef<HTMLDivElement>(null);

  // Simulate scan counter
  useEffect(() => {
    if (!scanning) return;
    const interval = setInterval(() => {
      setScanCount((c) => c + 1);
      setLastScan("Just now");
    }, 120000); // every 2 min
    return () => clearInterval(interval);
  }, [scanning]);

  // Auto-scroll opportunity stream
  useEffect(() => {
    if (streamRef.current) {
      streamRef.current.scrollTop = 0;
    }
  }, []);

  const toggleStrategy = (id: string) => {
    setStrategies((prev) =>
      prev.map((s) => (s.id === id ? { ...s, enabled: !s.enabled } : s))
    );
  };

  const totalPnl = strategies.reduce((sum, s) => sum + s.pnl, 0);
  const totalPositions = strategies.reduce((sum, s) => sum + s.positions, 0);
  const enabledCount = strategies.filter((s) => s.enabled).length;

  const filteredMarkets = DEMO_MARKETS.filter(
    (m) =>
      !searchQuery ||
      m.question.toLowerCase().includes(searchQuery.toLowerCase()) ||
      m.category.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <div className="ml-64 min-h-screen bg-[#FAFAFA] p-8">
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-3">
            <div className="w-10 h-10 rounded-2xl bg-gradient-to-br from-violet-500 to-purple-600 flex items-center justify-center shadow-lg shadow-violet-500/20">
              <Target className="w-5 h-5 text-white" />
            </div>
            Prediction Markets
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            Polymarket scanner &mdash; 7 strategies: weather arb, certainty harvest, market making, flash crash, whale copy &amp; more
          </p>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 px-4 py-2 rounded-xl bg-white border border-gray-200">
            <div className={`w-2 h-2 rounded-full ${scanning ? "bg-green-500 animate-pulse" : "bg-gray-400"}`} />
            <span className="text-sm font-medium text-gray-700">
              {scanning ? "Scanning" : "Paused"}
            </span>
            <span className="text-xs text-gray-400">#{scanCount}</span>
          </div>
          <button
            onClick={() => setScanning(!scanning)}
            className={`p-2.5 rounded-xl transition-colors ${
              scanning
                ? "bg-gray-100 hover:bg-gray-200 text-gray-600"
                : "bg-violet-100 hover:bg-violet-200 text-violet-700"
            }`}
          >
            {scanning ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4" />}
          </button>
        </div>
      </div>

      {/* Stats Row */}
      <div className="grid grid-cols-4 gap-4 mb-6">
        <div className="card p-5">
          <div className="flex items-center gap-2 mb-1">
            <DollarSign className="w-4 h-4 text-gray-400" />
            <span className="text-xs font-medium text-gray-500 uppercase tracking-wider">Total P&L</span>
          </div>
          <p className={`text-2xl font-bold tabular-nums ${totalPnl >= 0 ? "text-emerald-600" : "text-red-500"}`}>
            {totalPnl >= 0 ? "+" : ""}${totalPnl.toFixed(2)}
          </p>
        </div>
        <div className="card p-5">
          <div className="flex items-center gap-2 mb-1">
            <Activity className="w-4 h-4 text-gray-400" />
            <span className="text-xs font-medium text-gray-500 uppercase tracking-wider">Open Positions</span>
          </div>
          <p className="text-2xl font-bold tabular-nums text-gray-900">{totalPositions}</p>
        </div>
        <div className="card p-5">
          <div className="flex items-center gap-2 mb-1">
            <Zap className="w-4 h-4 text-gray-400" />
            <span className="text-xs font-medium text-gray-500 uppercase tracking-wider">Active Strategies</span>
          </div>
          <p className="text-2xl font-bold tabular-nums text-gray-900">
            {enabledCount}<span className="text-base font-normal text-gray-400">/{strategies.length}</span>
          </p>
        </div>
        <div className="card p-5">
          <div className="flex items-center gap-2 mb-1">
            <BarChart3 className="w-4 h-4 text-gray-400" />
            <span className="text-xs font-medium text-gray-500 uppercase tracking-wider">Markets Scanned</span>
          </div>
          <p className="text-2xl font-bold tabular-nums text-gray-900">{scanCount * 12}</p>
        </div>
      </div>

      {/* Strategy Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        {strategies.map((strategy) => {
          const colors = strategyColors[strategy.id] || strategyColors.weather_arb;
          return (
            <div
              key={strategy.id}
              className={`card p-5 border-2 transition-all cursor-pointer ${
                strategy.enabled ? `${colors.border} ${colors.bg}` : "border-transparent opacity-60"
              }`}
              onClick={() => toggleStrategy(strategy.id)}
            >
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <strategy.icon className={`w-5 h-5 ${strategy.enabled ? colors.text : "text-gray-400"}`} />
                  <span className={`text-sm font-semibold ${strategy.enabled ? "text-gray-900" : "text-gray-500"}`}>
                    {strategy.name}
                  </span>
                </div>
                <div
                  className={`w-8 h-5 rounded-full transition-colors flex items-center px-0.5 ${
                    strategy.enabled ? "bg-violet-500 justify-end" : "bg-gray-300 justify-start"
                  }`}
                >
                  <div className="w-4 h-4 rounded-full bg-white shadow-sm" />
                </div>
              </div>
              <p className="text-xs text-gray-500 mb-3 line-clamp-2">{strategy.description}</p>
              <div className="flex items-center justify-between">
                <span className="text-xs text-gray-400">{strategy.positions} positions</span>
                <span
                  className={`text-sm font-semibold tabular-nums ${
                    strategy.pnl >= 0 ? "text-emerald-600" : "text-red-500"
                  }`}
                >
                  {strategy.pnl >= 0 ? "+" : ""}${strategy.pnl.toFixed(2)}
                </span>
              </div>
            </div>
          );
        })}
      </div>

      {/* Tab Navigation */}
      <div className="flex items-center gap-1 mb-6 bg-gray-100 p-1 rounded-xl w-fit">
        {(["scanner", "markets", "positions"] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-5 py-2 rounded-lg text-sm font-medium transition-colors ${
              activeTab === tab
                ? "bg-white text-gray-900 shadow-sm"
                : "text-gray-500 hover:text-gray-700"
            }`}
          >
            {tab === "scanner" && "Live Scanner"}
            {tab === "markets" && "Browse Markets"}
            {tab === "positions" && `Positions (${totalPositions})`}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      {activeTab === "scanner" && (
        <div className="card overflow-hidden">
          <div className="p-5 border-b border-gray-100 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 rounded-full bg-violet-500 animate-pulse" />
              <h2 className="font-semibold text-gray-900">Opportunity Stream</h2>
              <span className="text-xs text-gray-400">Real-time signals from all active strategies</span>
            </div>
            <button className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-gray-500 hover:bg-gray-50">
              <RefreshCw className="w-3.5 h-3.5" />
              Refresh
            </button>
          </div>
          <div ref={streamRef} className="divide-y divide-gray-50 max-h-[600px] overflow-y-auto">
            {DEMO_OPPORTUNITIES.map((opp) => {
              const colors = strategyColors[opp.strategy] || strategyColors.weather_arb;
              return (
                <div key={opp.id} className="p-5 hover:bg-gray-50/50 transition-colors">
                  <div className="flex items-start justify-between">
                    <div className="flex-1">
                      <div className="flex items-center gap-2 mb-1.5">
                        <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${colors.badge}`}>
                          {strategyLabels[opp.strategy]}
                        </span>
                        <span
                          className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${
                            opp.side === "BUY"
                              ? "bg-emerald-100 text-emerald-700"
                              : "bg-red-100 text-red-700"
                          }`}
                        >
                          {opp.side}
                        </span>
                        <span className="text-xs text-gray-400">{opp.timestamp}</span>
                      </div>
                      <p className="text-sm font-medium text-gray-900 mb-1">{opp.market}</p>
                      <p className="text-xs text-gray-500">{opp.reason}</p>
                    </div>
                    <div className="text-right ml-4 flex-shrink-0">
                      <p className="text-lg font-bold text-emerald-600 tabular-nums">
                        {(opp.edge * 100).toFixed(1)}%
                      </p>
                      <p className="text-[10px] text-gray-400 uppercase tracking-wider">Edge</p>
                      <div className="flex items-center gap-1 mt-1">
                        <div className="w-16 h-1.5 bg-gray-100 rounded-full overflow-hidden">
                          <div
                            className="h-full bg-violet-500 rounded-full"
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
            })}
          </div>
        </div>
      )}

      {activeTab === "markets" && (
        <div className="card overflow-hidden">
          <div className="p-5 border-b border-gray-100">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
              <input
                type="text"
                placeholder="Search markets... (weather, crypto, politics, sports)"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="input-field pl-10"
              />
            </div>
          </div>
          <div className="divide-y divide-gray-50">
            {filteredMarkets.map((market) => (
              <div key={market.id} className="p-5 hover:bg-gray-50/50 transition-colors">
                <div className="flex items-start justify-between mb-3">
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-gray-100 text-gray-600">
                        {market.category}
                      </span>
                      <span className="text-xs text-gray-400">
                        Ends {new Date(market.endDate).toLocaleDateString()}
                      </span>
                    </div>
                    <p className="text-sm font-medium text-gray-900">{market.question}</p>
                  </div>
                  <div className="text-right ml-4 flex-shrink-0">
                    <p className="text-xs text-gray-400">Vol: ${(market.volume / 1000).toFixed(0)}K</p>
                    <p className="text-xs text-gray-400">Liq: ${(market.liquidity / 1000).toFixed(0)}K</p>
                  </div>
                </div>
                <div className="flex flex-wrap gap-2">
                  {market.outcomes.map((outcome, i) => (
                    <div
                      key={i}
                      className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-gray-50 border border-gray-100"
                    >
                      <span className="text-xs text-gray-600">{outcome.label}</span>
                      <span
                        className={`text-sm font-bold tabular-nums ${
                          outcome.price >= 0.5 ? "text-emerald-600" : "text-gray-900"
                        }`}
                      >
                        {(outcome.price * 100).toFixed(0)}c
                      </span>
                      {/* Probability bar */}
                      <div className="w-12 h-1.5 bg-gray-200 rounded-full overflow-hidden">
                        <div
                          className={`h-full rounded-full ${
                            outcome.price >= 0.5 ? "bg-emerald-500" : "bg-gray-400"
                          }`}
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

      {activeTab === "positions" && (
        <div className="card overflow-hidden">
          <div className="p-5 border-b border-gray-100 flex items-center justify-between">
            <h2 className="font-semibold text-gray-900">Open Positions</h2>
            <div className="flex items-center gap-2">
              <span className="text-sm text-gray-500">
                Unrealized P&L:
              </span>
              <span className="text-sm font-bold text-emerald-600 tabular-nums">
                +${DEMO_POSITIONS.reduce((s, p) => s + p.pnl, 0).toFixed(2)}
              </span>
            </div>
          </div>
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
              {DEMO_POSITIONS.map((pos) => {
                const colors = strategyColors[pos.strategy] || strategyColors.weather_arb;
                return (
                  <tr key={pos.id}>
                    <td>
                      <p className="text-sm font-medium text-gray-900">{pos.market}</p>
                      <p className="text-xs text-gray-400">{pos.outcome}</p>
                    </td>
                    <td>
                      <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${colors.badge}`}>
                        {strategyLabels[pos.strategy]}
                      </span>
                    </td>
                    <td>
                      <span
                        className={`text-xs font-semibold ${
                          pos.side === "BUY" ? "text-emerald-600" : "text-red-500"
                        }`}
                      >
                        {pos.side}
                      </span>
                    </td>
                    <td className="tabular-nums text-sm">${pos.entryPrice.toFixed(2)}</td>
                    <td className="tabular-nums text-sm">${pos.currentPrice.toFixed(2)}</td>
                    <td className="tabular-nums text-sm">${pos.size.toFixed(2)}</td>
                    <td>
                      <span
                        className={`text-sm font-semibold tabular-nums ${
                          pos.pnl >= 0 ? "text-emerald-600" : "text-red-500"
                        }`}
                      >
                        {pos.pnl >= 0 ? "+" : ""}${pos.pnl.toFixed(2)}
                      </span>
                    </td>
                    <td className="text-xs text-gray-400">{pos.openedAt}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Footer note */}
      <div className="mt-6 flex items-center gap-2 text-xs text-gray-400">
        <Shield className="w-3.5 h-3.5" />
        <span>Paper trading mode. Connect Polymarket wallet to trade live.</span>
      </div>
    </div>
  );
}
