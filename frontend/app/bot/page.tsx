"use client";

import { useEffect, useState, useCallback } from "react";
import {
  Play,
  Square,
  RefreshCw,
  TrendingUp,
  TrendingDown,
  Activity,
  DollarSign,
  Target,
  Zap,
  ChevronRight,
  Sparkles,
  Shield,
  Layers,
  Globe,
  Bitcoin,
  BarChart3,
  Gauge,
  Eye,
  Brain,
  Clock,
  Sun,
  Moon,
  Cpu,
  LineChart,
} from "lucide-react";
import { cn } from "@/lib/utils";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface MasterBotStatus {
  is_running: boolean;
  mode: string;
  market_regime: string;
  regime_confidence?: number;
  vix_level: number;
  initial_capital: number;
  cash: number;
  total_value: number;
  total_pnl: number;
  total_pnl_pct: number;
  positions: {
    options: number;
    crypto: number;
    total: number;
  };
  allocations: Record<string, number>;
  last_scan: string | null;
  opportunities_count: number;
  risk_summary: {
    risk_mode: string;
    portfolio_delta: number;
    portfolio_theta: number;
    portfolio_vega: number;
    delta_utilization: number;
    vega_utilization: number;
    buying_power_used_pct: number;
  };
  ml_metrics?: {
    rl_training_steps: number;
    dqn_epsilon: number;
    episode_reward: number;
    total_episodes: number;
    hmm_fitted: boolean;
    garch_fitted: boolean;
  };
  live_trading_enabled?: boolean;
  broker_connected?: boolean;
}

interface BrokerStatus {
  alpaca: { configured: boolean; connected: boolean; mode: string };
  binance: { configured: boolean; connected: boolean; mode: string };
  is_live_trading: boolean;
}

interface Opportunity {
  symbol: string;
  asset_class: string;
  strategy: string;
  expected_return: number;
  max_profit: number;
  max_loss: number;
  probability_of_profit: number;
  risk_reward_ratio: number;
  iv_rank: number;
  score: number;
  rationale: string;
  ml_confidence?: number;
  bayesian_confidence?: number;
}

interface OptionsPosition {
  id: string;
  symbol: string;
  strategy_name: string;
  entry_time: string;
  entry_iv: number;
  current_pnl: number;
  max_profit: number;
  max_loss: number;
  greeks: { delta: number; theta: number; vega: number };
}

interface CryptoPosition {
  id: string;
  symbol: string;
  derivative_type: string;
  side: string;
  entry_price: number;
  size: number;
  leverage: number;
  current_price: number;
  unrealized_pnl: number;
  greeks: { delta: number; iv: number };
}

interface CommentaryEntry {
  timestamp: string;
  message: string;
  category: string;
}

interface BotPerformance {
  total_return: number;
  total_pnl: number;
  win_rate: number;
  total_trades: number;
  open_positions: number;
  current_value: number;
  portfolio_theta: number;
  portfolio_delta: number;
  market_regime: string;
  vix_level: number;
  opportunities_scanned: number;
}

// Utility to check if US market is open
const isMarketOpen = (): { open: boolean; session: string } => {
  const now = new Date();
  const etOptions = { timeZone: "America/New_York" };
  const etTime = new Date(now.toLocaleString("en-US", etOptions));
  const hours = etTime.getHours();
  const minutes = etTime.getMinutes();
  const day = etTime.getDay();

  const timeInMinutes = hours * 60 + minutes;
  const marketOpen = 9 * 60 + 30; // 9:30 AM
  const marketClose = 16 * 60; // 4:00 PM

  if (day === 0 || day === 6) {
    return { open: false, session: "Weekend" };
  }
  if (timeInMinutes >= marketOpen && timeInMinutes < marketClose) {
    return { open: true, session: "Market Open" };
  }
  return { open: false, session: "After Hours" };
};

export default function MasterQuantBotPage() {
  const [status, setStatus] = useState<MasterBotStatus | null>(null);
  const [brokerStatus, setBrokerStatus] = useState<BrokerStatus | null>(null);
  const [opportunities, setOpportunities] = useState<Opportunity[]>([]);
  const [optionsPositions, setOptionsPositions] = useState<OptionsPosition[]>([]);
  const [cryptoPositions, setCryptoPositions] = useState<CryptoPosition[]>([]);
  const [commentary, setCommentary] = useState<CommentaryEntry[]>([]);
  const [performance, setPerformance] = useState<BotPerformance | null>(null);
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState(false);
  const [marketSession, setMarketSession] = useState(isMarketOpen());

  const [capital, setCapital] = useState("100000");
  const [mode, setMode] = useState("balanced");

  // Update market session every minute
  useEffect(() => {
    const interval = setInterval(() => {
      setMarketSession(isMarketOpen());
    }, 60000);
    return () => clearInterval(interval);
  }, []);

  const fetchData = useCallback(async () => {
    try {
      const [statusRes, oppsRes, posRes, commentaryRes, perfRes, brokerRes] = await Promise.all([
        fetch(`${API_BASE}/api/master-bot/status`),
        fetch(`${API_BASE}/api/master-bot/opportunities?limit=10`),
        fetch(`${API_BASE}/api/master-bot/positions`),
        fetch(`${API_BASE}/api/master-bot/commentary?limit=20`),
        fetch(`${API_BASE}/api/master-bot/performance`),
        fetch(`${API_BASE}/api/broker/status`),
      ]);

      if (statusRes.ok) setStatus(await statusRes.json());
      if (oppsRes.ok) {
        const data = await oppsRes.json();
        setOpportunities(data.opportunities || []);
      }
      if (posRes.ok) {
        const data = await posRes.json();
        setOptionsPositions(data.options_positions || []);
        setCryptoPositions(data.crypto_positions || []);
      }
      if (commentaryRes.ok) {
        const data = await commentaryRes.json();
        setCommentary(data.commentary || []);
      }
      if (perfRes.ok) setPerformance(await perfRes.json());
      if (brokerRes.ok) setBrokerStatus(await brokerRes.json());
    } catch (err) {
      console.error("Failed to fetch bot data:", err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 3000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const startBot = async () => {
    setStarting(true);
    try {
      const res = await fetch(
        `${API_BASE}/api/master-bot/start?capital=${capital}&mode=${mode}`,
        { method: "POST" }
      );
      if (res.ok) await fetchData();
    } catch (err) {
      console.error("Failed to start bot:", err);
    } finally {
      setStarting(false);
    }
  };

  const stopBot = async () => {
    try {
      await fetch(`${API_BASE}/api/master-bot/stop`, { method: "POST" });
      await fetchData();
    } catch (err) {
      console.error("Failed to stop bot:", err);
    }
  };

  const triggerScan = async () => {
    try {
      await fetch(`${API_BASE}/api/master-bot/scan`, { method: "POST" });
      await fetchData();
    } catch (err) {
      console.error("Failed to trigger scan:", err);
    }
  };

  const getAssetClassStyle = (assetClass: string) => {
    const styles: Record<string, { bg: string; text: string; icon: React.ReactNode }> = {
      stock_options: { bg: "bg-blue-500/10", text: "text-blue-400", icon: <BarChart3 className="w-3.5 h-3.5" /> },
      etf_options: { bg: "bg-violet-500/10", text: "text-violet-400", icon: <Layers className="w-3.5 h-3.5" /> },
      commodity_options: { bg: "bg-amber-500/10", text: "text-amber-400", icon: <Globe className="w-3.5 h-3.5" /> },
      crypto_perpetual: { bg: "bg-orange-500/10", text: "text-orange-400", icon: <Bitcoin className="w-3.5 h-3.5" /> },
      crypto_options: { bg: "bg-yellow-500/10", text: "text-yellow-400", icon: <Bitcoin className="w-3.5 h-3.5" /> },
    };
    return styles[assetClass] || { bg: "bg-gray-500/10", text: "text-gray-400", icon: <Activity className="w-3.5 h-3.5" /> };
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[600px]">
        <div className="text-center">
          <div className="relative w-16 h-16 mx-auto mb-4">
            <div className="absolute inset-0 rounded-full border-2 border-gray-700" />
            <div className="absolute inset-0 rounded-full border-2 border-transparent border-t-blue-500 animate-spin" />
            <Brain className="absolute inset-0 m-auto w-6 h-6 text-blue-400" />
          </div>
          <p className="text-gray-400 text-sm">Initializing ML Models...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto space-y-8 pb-12">
      {/* Premium Header */}
      <div className="relative overflow-hidden rounded-3xl bg-gradient-to-br from-gray-900 via-gray-800 to-gray-900 border border-gray-700/50 p-8">
        <div className="absolute top-0 right-0 w-96 h-96 bg-blue-500/5 rounded-full blur-3xl -translate-y-1/2 translate-x-1/2" />
        <div className="absolute bottom-0 left-0 w-64 h-64 bg-violet-500/5 rounded-full blur-3xl translate-y-1/2 -translate-x-1/2" />

        <div className="relative">
          <div className="flex items-start justify-between">
            <div>
              <div className="flex items-center gap-3 mb-2">
                <div className="p-2 rounded-xl bg-gradient-to-br from-blue-500/20 to-violet-500/20 border border-blue-500/20">
                  <Brain className="w-6 h-6 text-blue-400" />
                </div>
                <div>
                  <h1 className="text-2xl font-semibold text-white tracking-tight">Master Quant Bot</h1>
                  <p className="text-sm text-gray-400">PhD-Level Autonomous Trading System</p>
                </div>
              </div>
            </div>

            {/* Trading Session Indicator */}
            <div className="flex items-center gap-4">
              <div className={cn(
                "flex items-center gap-2 px-4 py-2 rounded-full text-sm font-medium transition-all",
                marketSession.open
                  ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                  : "bg-gray-800 text-gray-400 border border-gray-700"
              )}>
                {marketSession.open ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
                {marketSession.session}
              </div>
              <button
                onClick={fetchData}
                className="p-2.5 rounded-xl bg-gray-800/50 border border-gray-700 hover:bg-gray-700/50 transition-all"
              >
                <RefreshCw className="w-4 h-4 text-gray-400" />
              </button>
            </div>
          </div>

          {/* Live Data Feeds */}
          {brokerStatus && (
            <div className="mt-6 flex items-center gap-6">
              <span className="text-xs text-gray-500 uppercase tracking-wider">Live Feeds</span>
              <div className="flex items-center gap-4">
                <div className="flex items-center gap-2">
                  <div className={cn(
                    "w-2 h-2 rounded-full transition-all",
                    brokerStatus.alpaca?.connected
                      ? "bg-emerald-400 shadow-lg shadow-emerald-400/50 animate-pulse"
                      : "bg-gray-600"
                  )} />
                  <span className={cn(
                    "text-sm font-medium",
                    brokerStatus.alpaca?.connected ? "text-emerald-400" : "text-gray-500"
                  )}>
                    Alpaca
                  </span>
                </div>
                <div className="w-px h-4 bg-gray-700" />
                <div className="flex items-center gap-2">
                  <div className={cn(
                    "w-2 h-2 rounded-full transition-all",
                    brokerStatus.binance?.connected
                      ? "bg-emerald-400 shadow-lg shadow-emerald-400/50 animate-pulse"
                      : "bg-gray-600"
                  )} />
                  <span className={cn(
                    "text-sm font-medium",
                    brokerStatus.binance?.connected ? "text-emerald-400" : "text-gray-500"
                  )}>
                    Binance
                  </span>
                </div>
              </div>
              {!marketSession.open && (
                <span className="ml-auto text-xs text-amber-400/80 flex items-center gap-1">
                  <Bitcoin className="w-3.5 h-3.5" />
                  Crypto markets active 24/7
                </span>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Start Panel - when not running */}
      {!status?.is_running && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 rounded-2xl bg-gray-900/50 backdrop-blur border border-gray-800 p-6">
            <div className="flex items-center gap-3 mb-6">
              <Cpu className="w-5 h-5 text-blue-400" />
              <h2 className="text-lg font-medium text-white">Configure & Launch</h2>
            </div>

            <div className="grid grid-cols-2 gap-4 mb-6">
              <div>
                <label className="block text-sm text-gray-400 mb-2 font-medium">Initial Capital</label>
                <div className="relative">
                  <span className="absolute left-4 top-1/2 -translate-y-1/2 text-gray-500">$</span>
                  <input
                    type="number"
                    value={capital}
                    onChange={(e) => setCapital(e.target.value)}
                    className="w-full pl-8 pr-4 py-3 bg-gray-800/50 border border-gray-700 rounded-xl text-white text-lg font-medium focus:border-blue-500/50 focus:ring-2 focus:ring-blue-500/20 focus:outline-none transition-all"
                  />
                </div>
              </div>
              <div>
                <label className="block text-sm text-gray-400 mb-2 font-medium">Strategy Mode</label>
                <select
                  value={mode}
                  onChange={(e) => setMode(e.target.value)}
                  className="w-full px-4 py-3 bg-gray-800/50 border border-gray-700 rounded-xl text-white text-lg font-medium focus:border-blue-500/50 focus:ring-2 focus:ring-blue-500/20 focus:outline-none transition-all appearance-none cursor-pointer"
                >
                  <option value="aggressive">Aggressive</option>
                  <option value="balanced">Balanced</option>
                  <option value="conservative">Conservative</option>
                </select>
              </div>
            </div>

            <button
              onClick={startBot}
              disabled={starting}
              className="w-full py-4 bg-gradient-to-r from-blue-600 to-violet-600 rounded-xl font-semibold text-white text-lg hover:from-blue-500 hover:to-violet-500 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-3 transition-all shadow-lg shadow-blue-500/25 hover:shadow-blue-500/40"
            >
              {starting ? (
                <>
                  <RefreshCw className="w-5 h-5 animate-spin" />
                  Initializing AI Models...
                </>
              ) : (
                <>
                  <Play className="w-5 h-5" />
                  Launch Trading Bot
                </>
              )}
            </button>
          </div>

          <div className="rounded-2xl bg-gradient-to-br from-blue-900/20 to-violet-900/20 border border-blue-500/20 p-6">
            <div className="flex items-center gap-2 text-blue-400 mb-4">
              <Shield className="w-5 h-5" />
              <span className="font-medium">Paper Trading</span>
            </div>
            <p className="text-sm text-gray-400 leading-relaxed mb-4">
              All trades are simulated using real market data. No actual money is at risk.
            </p>
            <div className="space-y-3 text-sm">
              <div className="flex items-center gap-2 text-gray-300">
                <div className="w-1.5 h-1.5 rounded-full bg-blue-400" />
                DQN + PPO Reinforcement Learning
              </div>
              <div className="flex items-center gap-2 text-gray-300">
                <div className="w-1.5 h-1.5 rounded-full bg-violet-400" />
                HMM Market Regime Detection
              </div>
              <div className="flex items-center gap-2 text-gray-300">
                <div className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                GARCH Volatility Forecasting
              </div>
              <div className="flex items-center gap-2 text-gray-300">
                <div className="w-1.5 h-1.5 rounded-full bg-amber-400" />
                Black-Litterman Optimization
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Running Dashboard */}
      {status?.is_running && (
        <div className="space-y-6">
          {/* Key Metrics */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <MetricCard
              label="Portfolio Value"
              value={`$${status.total_value?.toLocaleString(undefined, { maximumFractionDigits: 0 })}`}
              icon={<DollarSign className="w-5 h-5" />}
              gradient="from-blue-500/20 to-blue-600/20"
              iconColor="text-blue-400"
            />
            <MetricCard
              label="Total P&L"
              value={`${status.total_pnl >= 0 ? "+" : ""}$${status.total_pnl?.toLocaleString(undefined, { maximumFractionDigits: 0 })}`}
              subValue={`${status.total_pnl_pct >= 0 ? "+" : ""}${status.total_pnl_pct?.toFixed(2)}%`}
              icon={status.total_pnl >= 0 ? <TrendingUp className="w-5 h-5" /> : <TrendingDown className="w-5 h-5" />}
              gradient={status.total_pnl >= 0 ? "from-emerald-500/20 to-emerald-600/20" : "from-red-500/20 to-red-600/20"}
              iconColor={status.total_pnl >= 0 ? "text-emerald-400" : "text-red-400"}
              valueColor={status.total_pnl >= 0 ? "text-emerald-400" : "text-red-400"}
            />
            <MetricCard
              label="Active Positions"
              value={(status.positions?.options || 0) + (status.positions?.crypto || 0)}
              subValue={`${status.positions?.options || 0} options · ${status.positions?.crypto || 0} crypto`}
              icon={<Layers className="w-5 h-5" />}
              gradient="from-violet-500/20 to-violet-600/20"
              iconColor="text-violet-400"
            />
            <MetricCard
              label="Cash Available"
              value={`$${status.cash?.toLocaleString(undefined, { maximumFractionDigits: 0 })}`}
              icon={<Target className="w-5 h-5" />}
              gradient="from-amber-500/20 to-amber-600/20"
              iconColor="text-amber-400"
            />
          </div>

          {/* Market Regime Banner */}
          <div className={cn(
            "rounded-2xl p-5 border transition-all",
            status.market_regime === "high_volatility"
              ? "bg-red-500/5 border-red-500/20"
              : status.market_regime === "low_volatility"
              ? "bg-emerald-500/5 border-emerald-500/20"
              : status.market_regime === "bull_market"
              ? "bg-green-500/5 border-green-500/20"
              : status.market_regime === "bear_market"
              ? "bg-orange-500/5 border-orange-500/20"
              : "bg-blue-500/5 border-blue-500/20"
          )}>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-4">
                <div className={cn(
                  "p-2.5 rounded-xl",
                  status.market_regime === "high_volatility" ? "bg-red-500/10" :
                  status.market_regime === "low_volatility" ? "bg-emerald-500/10" :
                  "bg-blue-500/10"
                )}>
                  <Gauge className={cn(
                    "w-5 h-5",
                    status.market_regime === "high_volatility" ? "text-red-400" :
                    status.market_regime === "low_volatility" ? "text-emerald-400" :
                    "text-blue-400"
                  )} />
                </div>
                <div>
                  <div className="font-semibold text-white capitalize">
                    {status.market_regime?.replace(/_/g, " ")} Regime
                  </div>
                  <div className="text-sm text-gray-400">
                    VIX: {status.vix_level?.toFixed(1)} · Confidence: {((status.regime_confidence || 0.5) * 100).toFixed(0)}%
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-6 text-sm">
                <div className="text-gray-400">
                  <span className="text-white font-medium">{status.opportunities_count || 0}</span> opportunities
                </div>
                <div className="text-gray-400">
                  Mode: <span className="text-white font-medium capitalize">{status.mode}</span>
                </div>
                {status?.is_running && (
                  <button
                    onClick={triggerScan}
                    className="px-4 py-2 rounded-lg bg-white/5 border border-white/10 hover:bg-white/10 transition-all text-white text-sm font-medium flex items-center gap-2"
                  >
                    <Eye className="w-4 h-4" />
                    Scan Now
                  </button>
                )}
              </div>
            </div>
          </div>

          {/* Greeks & Risk */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <GreekCard
              label="Portfolio Delta"
              value={status.risk_summary?.portfolio_delta?.toFixed(1) || "0"}
              utilization={status.risk_summary?.delta_utilization || 0}
              color="blue"
            />
            <GreekCard
              label="Daily Theta"
              value={`$${status.risk_summary?.portfolio_theta?.toFixed(0) || "0"}`}
              isPositive={(status.risk_summary?.portfolio_theta || 0) > 0}
              color="emerald"
            />
            <GreekCard
              label="Portfolio Vega"
              value={status.risk_summary?.portfolio_vega?.toFixed(1) || "0"}
              utilization={status.risk_summary?.vega_utilization || 0}
              color="violet"
            />
            <GreekCard
              label="Capital Deployed"
              value={`${status.risk_summary?.buying_power_used_pct?.toFixed(0) || "0"}%`}
              utilization={status.risk_summary?.buying_power_used_pct || 0}
              color="amber"
            />
          </div>

          {/* Main Content Grid */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Opportunities */}
            <div className="rounded-2xl bg-gray-900/50 backdrop-blur border border-gray-800 overflow-hidden">
              <div className="px-5 py-4 border-b border-gray-800 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Target className="w-4 h-4 text-blue-400" />
                  <span className="font-medium text-white">Top Opportunities</span>
                </div>
                <span className="text-xs text-gray-500">{opportunities.length} found</span>
              </div>
              <div className="p-4 space-y-3 max-h-[420px] overflow-y-auto">
                {opportunities.length === 0 ? (
                  <div className="text-center py-12">
                    <div className="w-12 h-12 mx-auto mb-3 rounded-full bg-gray-800 flex items-center justify-center">
                      <Eye className="w-5 h-5 text-gray-500" />
                    </div>
                    <p className="text-gray-500 text-sm">Scanning markets...</p>
                  </div>
                ) : (
                  opportunities.map((opp, i) => {
                    const style = getAssetClassStyle(opp.asset_class);
                    return (
                      <div
                        key={i}
                        className="group p-4 rounded-xl bg-gray-800/30 border border-gray-700/50 hover:border-gray-600/50 transition-all"
                      >
                        <div className="flex items-start justify-between mb-2">
                          <div className="flex items-center gap-2">
                            <span className={cn(
                              "px-2 py-1 rounded-lg text-xs font-medium flex items-center gap-1.5",
                              style.bg, style.text
                            )}>
                              {style.icon}
                              {opp.asset_class.split("_")[0]}
                            </span>
                            <span className="font-semibold text-white">{opp.symbol}</span>
                          </div>
                          <div className="text-right">
                            <div className="text-sm font-bold text-blue-400">{opp.score.toFixed(0)}</div>
                            <div className="text-xs text-gray-500">score</div>
                          </div>
                        </div>
                        <div className="text-sm text-gray-300 mb-3">{opp.strategy}</div>
                        <div className="grid grid-cols-3 gap-3 text-xs">
                          <div className="text-center p-2 rounded-lg bg-gray-800/50">
                            <div className="text-emerald-400 font-semibold">{opp.expected_return?.toFixed(0)}%</div>
                            <div className="text-gray-500">return</div>
                          </div>
                          <div className="text-center p-2 rounded-lg bg-gray-800/50">
                            <div className="text-white font-semibold">{opp.probability_of_profit?.toFixed(0)}%</div>
                            <div className="text-gray-500">P(profit)</div>
                          </div>
                          <div className="text-center p-2 rounded-lg bg-gray-800/50">
                            <div className="text-amber-400 font-semibold">{opp.iv_rank?.toFixed(0)}%</div>
                            <div className="text-gray-500">IV rank</div>
                          </div>
                        </div>
                      </div>
                    );
                  })
                )}
              </div>
            </div>

            {/* Activity Feed */}
            <div className="rounded-2xl bg-gray-900/50 backdrop-blur border border-gray-800 overflow-hidden">
              <div className="px-5 py-4 border-b border-gray-800 flex items-center gap-2">
                <Activity className="w-4 h-4 text-blue-400" />
                <span className="font-medium text-white">Bot Activity</span>
              </div>
              <div className="p-4 space-y-2 max-h-[420px] overflow-y-auto">
                {commentary.length === 0 ? (
                  <div className="text-center py-12">
                    <div className="w-12 h-12 mx-auto mb-3 rounded-full bg-gray-800 flex items-center justify-center">
                      <Activity className="w-5 h-5 text-gray-500" />
                    </div>
                    <p className="text-gray-500 text-sm">Waiting for activity...</p>
                  </div>
                ) : (
                  [...commentary].reverse().map((entry, i) => (
                    <div
                      key={i}
                      className={cn(
                        "p-3 rounded-xl text-sm border-l-2 transition-all",
                        entry.category === "trade" ? "bg-emerald-500/5 border-emerald-500" :
                        entry.category === "risk" ? "bg-red-500/5 border-red-500" :
                        entry.category === "scan" ? "bg-blue-500/5 border-blue-500" :
                        entry.category === "analysis" ? "bg-violet-500/5 border-violet-500" :
                        entry.category === "system" ? "bg-amber-500/5 border-amber-500" :
                        "bg-gray-800/30 border-gray-600"
                      )}
                    >
                      <div className="text-gray-200 leading-relaxed">{entry.message}</div>
                      <div className="text-xs text-gray-500 mt-1.5 flex items-center gap-2">
                        <Clock className="w-3 h-3" />
                        {new Date(entry.timestamp).toLocaleTimeString()}
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>

          {/* Positions */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Options Positions */}
            <div className="rounded-2xl bg-gray-900/50 backdrop-blur border border-gray-800 overflow-hidden">
              <div className="px-5 py-4 border-b border-gray-800 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Layers className="w-4 h-4 text-blue-400" />
                  <span className="font-medium text-white">Options</span>
                </div>
                <span className="px-2.5 py-1 rounded-lg bg-blue-500/10 text-blue-400 text-xs font-medium">
                  {optionsPositions.length} positions
                </span>
              </div>
              <div className="p-4 space-y-3 max-h-[320px] overflow-y-auto">
                {optionsPositions.length === 0 ? (
                  <div className="text-center py-8 text-gray-500 text-sm">No options positions</div>
                ) : (
                  optionsPositions.map((pos) => (
                    <div key={pos.id} className="p-4 rounded-xl bg-gray-800/30 border border-gray-700/50">
                      <div className="flex items-center justify-between mb-2">
                        <span className="font-semibold text-white">{pos.symbol}</span>
                        <span className={cn(
                          "font-bold",
                          (pos.current_pnl || 0) >= 0 ? "text-emerald-400" : "text-red-400"
                        )}>
                          {(pos.current_pnl || 0) >= 0 ? "+" : ""}${pos.current_pnl?.toFixed(0) || 0}
                        </span>
                      </div>
                      <div className="text-sm text-gray-400 mb-3">{pos.strategy_name}</div>
                      <div className="flex items-center gap-4 text-xs text-gray-500">
                        <span>Δ {pos.greeks?.delta?.toFixed(2) || 0}</span>
                        <span>Θ {pos.greeks?.theta?.toFixed(2) || 0}</span>
                        <span>IV: {pos.entry_iv || 0}%</span>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>

            {/* Crypto Positions */}
            <div className="rounded-2xl bg-gray-900/50 backdrop-blur border border-gray-800 overflow-hidden">
              <div className="px-5 py-4 border-b border-gray-800 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Bitcoin className="w-4 h-4 text-orange-400" />
                  <span className="font-medium text-white">Crypto</span>
                </div>
                <span className="px-2.5 py-1 rounded-lg bg-orange-500/10 text-orange-400 text-xs font-medium">
                  {cryptoPositions.length} positions
                </span>
              </div>
              <div className="p-4 space-y-3 max-h-[320px] overflow-y-auto">
                {cryptoPositions.length === 0 ? (
                  <div className="text-center py-8 text-gray-500 text-sm">No crypto positions</div>
                ) : (
                  cryptoPositions.map((pos) => (
                    <div key={pos.id} className="p-4 rounded-xl bg-gray-800/30 border border-gray-700/50">
                      <div className="flex items-center justify-between mb-2">
                        <div className="flex items-center gap-2">
                          <span className="font-semibold text-white">{pos.symbol}</span>
                          <span className={cn(
                            "text-xs px-2 py-0.5 rounded-md font-medium",
                            pos.side === "long"
                              ? "bg-emerald-500/10 text-emerald-400"
                              : "bg-red-500/10 text-red-400"
                          )}>
                            {pos.side?.toUpperCase()}
                          </span>
                        </div>
                        <span className={cn(
                          "font-bold",
                          (pos.unrealized_pnl || 0) >= 0 ? "text-emerald-400" : "text-red-400"
                        )}>
                          {(pos.unrealized_pnl || 0) >= 0 ? "+" : ""}${pos.unrealized_pnl?.toFixed(2) || 0}
                        </span>
                      </div>
                      <div className="text-sm text-gray-400 mb-2">{pos.derivative_type}</div>
                      <div className="flex items-center gap-4 text-xs text-gray-500">
                        <span>Size: ${pos.size?.toLocaleString() || 0}</span>
                        <span>{pos.leverage || 1}x</span>
                        <span>Entry: ${pos.entry_price?.toLocaleString() || 0}</span>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>

          {/* ML Metrics (optional) */}
          {status.ml_metrics && (
            <div className="rounded-2xl bg-gradient-to-r from-violet-900/20 to-blue-900/20 border border-violet-500/20 p-5">
              <div className="flex items-center gap-2 mb-4">
                <Brain className="w-4 h-4 text-violet-400" />
                <span className="font-medium text-white">ML Training Status</span>
              </div>
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 text-sm">
                <div>
                  <div className="text-gray-400">RL Steps</div>
                  <div className="text-white font-semibold">{status.ml_metrics.rl_training_steps?.toLocaleString()}</div>
                </div>
                <div>
                  <div className="text-gray-400">DQN Epsilon</div>
                  <div className="text-white font-semibold">{status.ml_metrics.dqn_epsilon?.toFixed(4)}</div>
                </div>
                <div>
                  <div className="text-gray-400">Episode Reward</div>
                  <div className="text-white font-semibold">{status.ml_metrics.episode_reward?.toFixed(2)}</div>
                </div>
                <div>
                  <div className="text-gray-400">Models Fitted</div>
                  <div className="flex items-center gap-2">
                    <span className={cn("w-2 h-2 rounded-full", status.ml_metrics.hmm_fitted ? "bg-emerald-400" : "bg-gray-600")} />
                    <span className="text-white font-semibold">HMM</span>
                    <span className={cn("w-2 h-2 rounded-full", status.ml_metrics.garch_fitted ? "bg-emerald-400" : "bg-gray-600")} />
                    <span className="text-white font-semibold">GARCH</span>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Stop Button */}
          <div className="flex justify-center pt-4">
            <button
              onClick={stopBot}
              className="px-8 py-3 rounded-xl bg-red-500/10 border border-red-500/30 text-red-400 hover:bg-red-500/20 transition-all flex items-center gap-2 font-medium"
            >
              <Square className="w-4 h-4" />
              Stop Trading Bot
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// Metric Card Component
function MetricCard({
  label,
  value,
  subValue,
  icon,
  gradient,
  iconColor,
  valueColor = "text-white"
}: {
  label: string;
  value: string | number;
  subValue?: string;
  icon: React.ReactNode;
  gradient: string;
  iconColor: string;
  valueColor?: string;
}) {
  return (
    <div className="rounded-2xl bg-gray-900/50 backdrop-blur border border-gray-800 p-5 hover:border-gray-700 transition-all">
      <div className="flex items-center justify-between mb-3">
        <span className="text-sm text-gray-400">{label}</span>
        <div className={cn("p-2 rounded-lg bg-gradient-to-br", gradient)}>
          <div className={iconColor}>{icon}</div>
        </div>
      </div>
      <div className={cn("text-2xl font-bold", valueColor)}>{value}</div>
      {subValue && <div className="text-sm text-gray-500 mt-1">{subValue}</div>}
    </div>
  );
}

// Greek Card Component
function GreekCard({
  label,
  value,
  utilization,
  isPositive,
  color
}: {
  label: string;
  value: string;
  utilization?: number;
  isPositive?: boolean;
  color: "blue" | "emerald" | "violet" | "amber";
}) {
  const colors = {
    blue: "bg-blue-500",
    emerald: "bg-emerald-500",
    violet: "bg-violet-500",
    amber: "bg-amber-500",
  };

  return (
    <div className="rounded-2xl bg-gray-900/50 backdrop-blur border border-gray-800 p-4 hover:border-gray-700 transition-all">
      <div className="flex items-center justify-between mb-3">
        <span className="text-sm text-gray-400">{label}</span>
        <span className={cn(
          "text-lg font-bold",
          isPositive !== undefined
            ? (isPositive ? "text-emerald-400" : "text-red-400")
            : "text-white"
        )}>
          {value}
        </span>
      </div>
      {utilization !== undefined && (
        <div className="h-1.5 bg-gray-800 rounded-full overflow-hidden">
          <div
            className={cn("h-full rounded-full transition-all", colors[color])}
            style={{ width: `${Math.min(100, utilization)}%` }}
          />
        </div>
      )}
    </div>
  );
}
