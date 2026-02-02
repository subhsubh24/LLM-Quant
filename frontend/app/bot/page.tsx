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
  ChevronRight,
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
  Newspaper,
  AlertTriangle,
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
  capital_deployed?: number;
  capital_deployed_pct?: number;
  crypto_metrics?: {
    long_exposure: number;
    short_exposure: number;
    net_exposure: number;
    total_exposure: number;
    unrealized_pnl: number;
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
  llm_summary?: string;
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
  rationale: string;
  entry_time: string;
  greeks: { delta: number; iv: number };
}

interface Trade {
  timestamp: string;
  symbol: string;
  action: string;
  type: string;
  strategy: string;
  rationale: string;
  expected_return: number;
  score: number;
  ml_confidence: number;
  regime: string;
  live_executed: boolean;
}

interface CommentaryEntry {
  timestamp: string;
  message: string;
  category: string;
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
  const marketOpen = 9 * 60 + 30;
  const marketClose = 16 * 60;

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
  const [trades, setTrades] = useState<Trade[]>([]);
  const [commentary, setCommentary] = useState<CommentaryEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState(false);
  const [marketSession, setMarketSession] = useState(isMarketOpen());

  const [capital, setCapital] = useState("100000");
  const [mode, setMode] = useState("balanced");

  useEffect(() => {
    const interval = setInterval(() => {
      setMarketSession(isMarketOpen());
    }, 60000);
    return () => clearInterval(interval);
  }, []);

  const fetchData = useCallback(async () => {
    try {
      const [statusRes, oppsRes, posRes, commentaryRes, tradesRes, brokerRes] = await Promise.all([
        fetch(`${API_BASE}/api/master-bot/status`),
        fetch(`${API_BASE}/api/master-bot/opportunities`),
        fetch(`${API_BASE}/api/master-bot/positions`),
        fetch(`${API_BASE}/api/master-bot/commentary`),
        fetch(`${API_BASE}/api/master-bot/trades`),
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
      if (tradesRes.ok) {
        const data = await tradesRes.json();
        setTrades(data.trades || []);
      }
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
      stock_options: { bg: "bg-blue-600", text: "text-white", icon: <BarChart3 className="w-3 h-3" /> },
      etf_options: { bg: "bg-violet-600", text: "text-white", icon: <Layers className="w-3 h-3" /> },
      commodity_options: { bg: "bg-amber-600", text: "text-white", icon: <Globe className="w-3 h-3" /> },
      crypto_perpetual: { bg: "bg-orange-600", text: "text-white", icon: <Bitcoin className="w-3 h-3" /> },
      crypto_options: { bg: "bg-yellow-600", text: "text-white", icon: <Bitcoin className="w-3 h-3" /> },
    };
    return styles[assetClass] || { bg: "bg-slate-600", text: "text-white", icon: <Activity className="w-3 h-3" /> };
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[600px]">
        <div className="text-center">
          <div className="relative w-16 h-16 mx-auto mb-4">
            <div className="absolute inset-0 rounded-full border-2 border-gray-200" />
            <div className="absolute inset-0 rounded-full border-2 border-transparent border-t-blue-500 animate-spin" />
            <Brain className="absolute inset-0 m-auto w-6 h-6 text-blue-500" />
          </div>
          <p className="text-gray-500 text-sm">Initializing ML Models...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen p-8">
      <div className="max-w-7xl mx-auto space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <div className="w-12 h-12 rounded-2xl bg-gradient-to-br from-blue-500 to-indigo-600 flex items-center justify-center shadow-lg">
              <Brain className="w-6 h-6 text-white" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-gray-900">Master Quant Bot</h1>
              <p className="text-gray-500 text-sm">Autonomous Trading System</p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            {/* Market Session Badge */}
            <div className={cn(
              "flex items-center gap-2 px-4 py-2 rounded-full text-sm font-medium",
              marketSession.open
                ? "bg-emerald-50 text-emerald-600 ring-1 ring-emerald-200"
                : "bg-gray-100 text-gray-600 ring-1 ring-gray-200"
            )}>
              {marketSession.open ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
              {marketSession.session}
            </div>
            <button
              onClick={fetchData}
              className="p-2.5 rounded-xl bg-white hover:bg-gray-50 transition-colors border border-gray-200"
            >
              <RefreshCw className="w-4 h-4 text-gray-500" />
            </button>
          </div>
        </div>

        {/* Live Feeds Status */}
        {brokerStatus && (
          <div className="flex items-center gap-6 px-4 py-3 rounded-xl bg-white border border-gray-200 shadow-sm">
            <span className="text-xs text-gray-400 uppercase tracking-wider font-medium">Live Feeds</span>
            <div className="flex items-center gap-6">
              <div className="flex items-center gap-2">
                <div className={cn(
                  "w-2.5 h-2.5 rounded-full",
                  brokerStatus.alpaca?.connected
                    ? "bg-emerald-500 shadow-lg shadow-emerald-500/50"
                    : "bg-gray-300"
                )} />
                <span className={cn(
                  "text-sm font-medium",
                  brokerStatus.alpaca?.connected ? "text-emerald-600" : "text-gray-400"
                )}>
                  Alpaca
                </span>
              </div>
              <div className="flex items-center gap-2">
                <div className={cn(
                  "w-2.5 h-2.5 rounded-full",
                  brokerStatus.binance?.connected
                    ? "bg-emerald-500 shadow-lg shadow-emerald-500/50"
                    : "bg-gray-300"
                )} />
                <span className={cn(
                  "text-sm font-medium",
                  brokerStatus.binance?.connected ? "text-emerald-600" : "text-gray-400"
                )}>
                  Binance
                </span>
              </div>
            </div>
            {!marketSession.open && (
              <div className="ml-auto flex items-center gap-2 text-amber-600 text-sm">
                <Bitcoin className="w-4 h-4" />
                <span>Crypto markets active 24/7</span>
              </div>
            )}
          </div>
        )}

        {/* Start Panel */}
        {!status?.is_running && (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <div className="lg:col-span-2 rounded-2xl bg-white border border-gray-200 shadow-sm p-6">
              <div className="flex items-center gap-3 mb-6">
                <Cpu className="w-5 h-5 text-blue-500" />
                <h2 className="text-lg font-semibold text-gray-900">Configure & Launch</h2>
              </div>

              <div className="grid grid-cols-2 gap-4 mb-6">
                <div>
                  <label className="block text-sm text-gray-500 mb-2 font-medium">Initial Capital</label>
                  <div className="relative">
                    <span className="absolute left-4 top-1/2 -translate-y-1/2 text-gray-400 font-medium">$</span>
                    <input
                      type="number"
                      value={capital}
                      onChange={(e) => setCapital(e.target.value)}
                      className="w-full pl-8 pr-4 py-3.5 bg-gray-50 border border-gray-200 rounded-xl text-gray-900 text-lg font-semibold focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 focus:outline-none transition-all"
                    />
                  </div>
                </div>
                <div>
                  <label className="block text-sm text-gray-500 mb-2 font-medium">Strategy Mode</label>
                  <select
                    value={mode}
                    onChange={(e) => setMode(e.target.value)}
                    className="w-full px-4 py-3.5 bg-gray-50 border border-gray-200 rounded-xl text-gray-900 text-lg font-semibold focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 focus:outline-none transition-all appearance-none cursor-pointer"
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
                className="w-full py-4 bg-gradient-to-r from-blue-500 to-indigo-600 rounded-xl font-bold text-white text-lg hover:from-blue-400 hover:to-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-3 transition-all shadow-lg"
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

            <div className="rounded-2xl bg-gradient-to-br from-blue-50 to-indigo-50 border border-blue-200 p-6">
              <div className="flex items-center gap-2 text-blue-600 mb-4">
                <Shield className="w-5 h-5" />
                <span className="font-semibold">Paper Trading</span>
              </div>
              <p className="text-sm text-gray-600 leading-relaxed mb-4">
                All trades are simulated. No real money at risk.
              </p>
              <div className="space-y-2.5 text-sm">
                {["DQN + PPO Reinforcement Learning", "HMM Market Regime Detection", "GARCH Volatility Forecasting", "Black-Litterman Optimization"].map((item, i) => (
                  <div key={i} className="flex items-center gap-2 text-gray-600">
                    <div className="w-1.5 h-1.5 rounded-full bg-blue-500" />
                    {item}
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* Running Dashboard */}
        {status?.is_running && (
          <div className="space-y-6">
            {/* After Hours Warning */}
            {!marketSession.open && (
              <div className="flex items-center gap-3 px-4 py-3 rounded-xl bg-amber-50 border border-amber-200 text-amber-700">
                <AlertTriangle className="w-5 h-5" />
                <span className="font-medium">Stock market closed - Trading CRYPTO only</span>
                <span className="text-amber-600 text-sm ml-auto">Stock positions will resume when market opens</span>
              </div>
            )}

            {/* Key Metrics */}
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
              <div className="rounded-2xl bg-white border border-gray-200 shadow-sm p-5">
                <div className="flex items-center justify-between mb-3">
                  <span className="text-sm text-gray-500 font-medium">Portfolio Value</span>
                  <div className="w-10 h-10 rounded-xl bg-blue-50 flex items-center justify-center">
                    <DollarSign className="w-5 h-5 text-blue-500" />
                  </div>
                </div>
                <div className="text-3xl font-bold text-gray-900">
                  ${status.total_value?.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                </div>
              </div>

              <div className="rounded-2xl bg-white border border-gray-200 shadow-sm p-5">
                <div className="flex items-center justify-between mb-3">
                  <span className="text-sm text-gray-500 font-medium">Total P&L</span>
                  <div className={cn(
                    "w-10 h-10 rounded-xl flex items-center justify-center",
                    status.total_pnl >= 0 ? "bg-emerald-50" : "bg-red-50"
                  )}>
                    {status.total_pnl >= 0 ? (
                      <TrendingUp className="w-5 h-5 text-emerald-500" />
                    ) : (
                      <TrendingDown className="w-5 h-5 text-red-500" />
                    )}
                  </div>
                </div>
                <div className={cn(
                  "text-3xl font-bold",
                  status.total_pnl >= 0 ? "text-emerald-600" : "text-red-600"
                )}>
                  {status.total_pnl >= 0 ? "+" : ""}${status.total_pnl?.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                </div>
                <div className={cn(
                  "text-sm font-medium mt-1",
                  status.total_pnl_pct >= 0 ? "text-emerald-500" : "text-red-500"
                )}>
                  {status.total_pnl_pct >= 0 ? "+" : ""}{status.total_pnl_pct?.toFixed(2)}%
                </div>
              </div>

              <div className="rounded-2xl bg-white border border-gray-200 shadow-sm p-5">
                <div className="flex items-center justify-between mb-3">
                  <span className="text-sm text-gray-500 font-medium">Active Positions</span>
                  <div className="w-10 h-10 rounded-xl bg-violet-50 flex items-center justify-center">
                    <Layers className="w-5 h-5 text-violet-500" />
                  </div>
                </div>
                <div className="text-3xl font-bold text-gray-900">
                  {(status.positions?.options || 0) + (status.positions?.crypto || 0)}
                </div>
                <div className="text-sm text-gray-500 mt-1">
                  {status.positions?.options || 0} options · {status.positions?.crypto || 0} crypto
                </div>
              </div>

              <div className="rounded-2xl bg-white border border-gray-200 shadow-sm p-5">
                <div className="flex items-center justify-between mb-3">
                  <span className="text-sm text-gray-500 font-medium">Cash Available</span>
                  <div className="w-10 h-10 rounded-xl bg-amber-50 flex items-center justify-center">
                    <Target className="w-5 h-5 text-amber-500" />
                  </div>
                </div>
                <div className="text-3xl font-bold text-gray-900">
                  ${status.cash?.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                </div>
              </div>
            </div>

            {/* Trade Log - Table Format */}
            <div className="rounded-2xl bg-white border border-gray-200 shadow-sm overflow-hidden">
              <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <ChevronRight className="w-4 h-4 text-blue-500" />
                  <span className="font-semibold text-gray-900">Trade Log</span>
                </div>
                <span className="text-sm text-gray-500">{trades.length} executions</span>
              </div>
              <div className="overflow-x-auto">
                {trades.length === 0 ? (
                  <div className="text-center py-8 text-gray-500">No trades executed yet</div>
                ) : (
                  <table className="w-full text-sm">
                    <thead className="bg-gray-50 text-gray-600 text-xs uppercase">
                      <tr>
                        <th className="px-4 py-3 text-left font-medium">Time</th>
                        <th className="px-4 py-3 text-left font-medium">Asset</th>
                        <th className="px-4 py-3 text-left font-medium">Position</th>
                        <th className="px-4 py-3 text-left font-medium">Strategy</th>
                        <th className="px-4 py-3 text-left font-medium">Score</th>
                        <th className="px-4 py-3 text-left font-medium">Regime</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100">
                      {[...trades].reverse().slice(0, 20).map((trade, i) => {
                        const isLong = trade.action === "BUY";
                        return (
                          <tr key={i} className="hover:bg-gray-50">
                            <td className="px-4 py-3 text-gray-500 whitespace-nowrap">
                              {new Date(trade.timestamp).toLocaleTimeString()}
                            </td>
                            <td className="px-4 py-3 font-medium text-gray-900">
                              {trade.symbol}
                            </td>
                            <td className="px-4 py-3">
                              <span className={cn(
                                "text-xs px-2 py-1 rounded font-bold",
                                isLong ? "bg-emerald-100 text-emerald-700" : "bg-red-100 text-red-700"
                              )}>
                                {isLong ? "LONG" : "SHORT"}
                              </span>
                            </td>
                            <td className="px-4 py-3 text-gray-600">
                              {trade.strategy}
                            </td>
                            <td className="px-4 py-3 text-gray-900 font-medium">
                              {trade.score}
                            </td>
                            <td className="px-4 py-3 text-gray-500 text-xs">
                              {trade.regime?.replace(/_/g, ' ')}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                )}
              </div>
            </div>

            {/* Market Regime */}
            <div className={cn(
              "rounded-2xl p-5 border",
              status.market_regime === "high_volatility"
                ? "bg-red-50 border-red-200"
                : status.market_regime === "low_volatility"
                ? "bg-emerald-50 border-emerald-200"
                : "bg-blue-50 border-blue-200"
            )}>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-4">
                  <div className={cn(
                    "w-12 h-12 rounded-xl flex items-center justify-center",
                    status.market_regime === "high_volatility" ? "bg-red-100" :
                    status.market_regime === "low_volatility" ? "bg-emerald-100" :
                    "bg-blue-100"
                  )}>
                    <Gauge className={cn(
                      "w-6 h-6",
                      status.market_regime === "high_volatility" ? "text-red-600" :
                      status.market_regime === "low_volatility" ? "text-emerald-600" :
                      "text-blue-600"
                    )} />
                  </div>
                  <div>
                    <div className="text-lg font-bold text-gray-900 capitalize">
                      {status.market_regime?.replace(/_/g, " ")} Regime
                    </div>
                    <div className="text-sm text-gray-500">
                      VIX: {status.vix_level?.toFixed(1)} · Confidence: {((status.regime_confidence || 0.5) * 100).toFixed(0)}%
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-6">
                  <div className="text-right">
                    <div className="text-2xl font-bold text-gray-900">{status.opportunities_count || 0}</div>
                    <div className="text-sm text-gray-500">opportunities</div>
                  </div>
                  <button
                    onClick={triggerScan}
                    className="px-5 py-2.5 rounded-xl bg-white hover:bg-gray-50 border border-gray-200 text-gray-700 font-medium flex items-center gap-2 transition-colors shadow-sm"
                  >
                    <Eye className="w-4 h-4" />
                    Scan Now
                  </button>
                </div>
              </div>
            </div>

            {/* Key Metrics */}
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
              <div className="rounded-xl bg-white border border-gray-200 shadow-sm p-4">
                <div className="flex items-center justify-between mb-3">
                  <span className="text-sm text-gray-500">Open Positions</span>
                  <span className="text-xl font-bold text-gray-900">{status.positions?.total || 0}</span>
                </div>
                <div className="text-xs text-gray-500">
                  {status.positions?.crypto || 0} crypto · {status.positions?.options || 0} options
                </div>
              </div>
              <div className="rounded-xl bg-white border border-gray-200 shadow-sm p-4">
                <div className="flex items-center justify-between mb-3">
                  <span className="text-sm text-gray-500">Unrealized P&L</span>
                  <span className={cn(
                    "text-xl font-bold",
                    (status.crypto_metrics?.unrealized_pnl || 0) >= 0 ? "text-emerald-600" : "text-red-600"
                  )}>
                    ${(status.crypto_metrics?.unrealized_pnl || 0).toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}
                  </span>
                </div>
                <div className="text-xs text-gray-500">from open positions</div>
              </div>
              <div className="rounded-xl bg-white border border-gray-200 shadow-sm p-4">
                <div className="flex items-center justify-between mb-3">
                  <span className="text-sm text-gray-500">Net Exposure</span>
                  <span className={cn(
                    "text-xl font-bold",
                    (status.crypto_metrics?.net_exposure || 0) > 0 ? "text-emerald-600" :
                    (status.crypto_metrics?.net_exposure || 0) < 0 ? "text-red-600" : "text-gray-900"
                  )}>
                    ${Math.abs(status.crypto_metrics?.net_exposure || 0).toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}
                  </span>
                </div>
                <div className="text-xs text-gray-500">
                  {(status.crypto_metrics?.net_exposure || 0) > 0 ? "net long" :
                   (status.crypto_metrics?.net_exposure || 0) < 0 ? "net short" : "neutral"}
                </div>
              </div>
              <div className="rounded-xl bg-white border border-gray-200 shadow-sm p-4">
                <div className="flex items-center justify-between mb-3">
                  <span className="text-sm text-gray-500">Capital Deployed</span>
                  <span className="text-xl font-bold text-gray-900">{status.capital_deployed_pct?.toFixed(1) || "0"}%</span>
                </div>
                <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
                  <div className="h-full bg-amber-500 rounded-full" style={{ width: `${Math.min(100, status.capital_deployed_pct || 0)}%` }} />
                </div>
              </div>
            </div>

            {/* Main Grid */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              {/* Opportunities */}
              <div className="rounded-2xl bg-white border border-gray-200 shadow-sm overflow-hidden">
                <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Target className="w-4 h-4 text-cyan-500" />
                    <span className="font-semibold text-gray-900">Top Opportunities</span>
                  </div>
                  <span className="text-sm text-gray-500">{opportunities.length} found</span>
                </div>
                <div className="p-4 space-y-3 max-h-[400px] overflow-y-auto">
                  {opportunities.length === 0 ? (
                    <div className="text-center py-12">
                      <div className="w-14 h-14 mx-auto mb-3 rounded-full bg-gray-100 flex items-center justify-center">
                        <Eye className="w-6 h-6 text-gray-400" />
                      </div>
                      <p className="text-gray-500">Scanning markets...</p>
                    </div>
                  ) : (
                    opportunities.slice(0, 6).map((opp, i) => {
                      const style = getAssetClassStyle(opp.asset_class);
                      const summary = opp.llm_summary || opp.rationale;
                      return (
                        <div key={i} className="p-4 rounded-xl bg-gray-50 border border-gray-100 hover:border-gray-200 transition-all">
                          <div className="flex items-start justify-between mb-2">
                            <div className="flex items-center gap-2">
                              <span className="font-bold text-gray-900">{opp.symbol}</span>
                              <span className={cn("px-2 py-0.5 rounded text-xs font-medium", style.bg, style.text)}>
                                {opp.strategy}
                              </span>
                            </div>
                            <div className="text-lg font-bold text-cyan-600">{opp.score.toFixed(0)}</div>
                          </div>
                          <p className="text-sm text-gray-700 mb-3 leading-relaxed">{summary}</p>
                          <div className="flex items-center gap-4 text-xs text-gray-500">
                            <span className="text-emerald-600 font-medium">{opp.expected_return?.toFixed(0)}% exp. return</span>
                            <span>{opp.probability_of_profit?.toFixed(0)}% win rate</span>
                            <span>IV: {opp.iv_rank?.toFixed(0)}%</span>
                          </div>
                        </div>
                      );
                    })
                  )}
                </div>
              </div>

              {/* Activity */}
              <div className="rounded-2xl bg-white border border-gray-200 shadow-sm overflow-hidden">
                <div className="px-5 py-4 border-b border-gray-100 flex items-center gap-2">
                  <Activity className="w-4 h-4 text-cyan-500" />
                  <span className="font-semibold text-gray-900">Bot Activity</span>
                </div>
                <div className="p-4 space-y-2 max-h-[400px] overflow-y-auto">
                  {commentary.length === 0 ? (
                    <div className="text-center py-12">
                      <div className="w-14 h-14 mx-auto mb-3 rounded-full bg-gray-100 flex items-center justify-center">
                        <Activity className="w-6 h-6 text-gray-400" />
                      </div>
                      <p className="text-gray-500">Waiting for activity...</p>
                    </div>
                  ) : (
                    [...commentary].reverse().map((entry, i) => (
                      <div
                        key={i}
                        className={cn(
                          "p-3 rounded-xl text-sm border-l-3",
                          entry.category === "trade" ? "bg-emerald-50 border-l-emerald-500" :
                          entry.category === "risk" ? "bg-red-50 border-l-red-500" :
                          entry.category === "scan" ? "bg-blue-50 border-l-blue-500" :
                          entry.category === "analysis" ? "bg-violet-50 border-l-violet-500" :
                          entry.category === "system" ? "bg-amber-50 border-l-amber-500" :
                          "bg-gray-50 border-l-gray-400"
                        )}
                        style={{ borderLeftWidth: '3px' }}
                      >
                        <div className="text-gray-700 leading-relaxed">{entry.message}</div>
                        <div className="text-xs text-gray-500 mt-1.5 flex items-center gap-1.5">
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
              {/* Options */}
              <div className="rounded-2xl bg-white border border-gray-200 shadow-sm overflow-hidden">
                <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Layers className="w-4 h-4 text-blue-500" />
                    <span className="font-semibold text-gray-900">Options</span>
                  </div>
                  <span className="px-3 py-1 rounded-full bg-blue-50 text-blue-600 text-xs font-bold">
                    {optionsPositions.length} positions
                  </span>
                </div>
                <div className="p-4 space-y-3 max-h-[300px] overflow-y-auto">
                  {optionsPositions.length === 0 ? (
                    <div className="text-center py-8 text-gray-500">No options positions</div>
                  ) : (
                    optionsPositions.map((pos) => (
                      <div key={pos.id} className="p-4 rounded-xl bg-gray-50 border border-gray-100">
                        <div className="flex items-center justify-between mb-2">
                          <span className="font-bold text-gray-900 text-lg">{pos.symbol}</span>
                          <span className={cn(
                            "text-lg font-bold",
                            (pos.current_pnl || 0) >= 0 ? "text-emerald-600" : "text-red-600"
                          )}>
                            {(pos.current_pnl || 0) >= 0 ? "+" : ""}${pos.current_pnl?.toFixed(0) || 0}
                          </span>
                        </div>
                        <div className="text-sm text-gray-500 mb-2">{pos.strategy_name}</div>
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

              {/* Crypto */}
              <div className="rounded-2xl bg-white border border-gray-200 shadow-sm overflow-hidden">
                <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Bitcoin className="w-4 h-4 text-orange-500" />
                    <span className="font-semibold text-gray-900">Crypto</span>
                  </div>
                  <span className="px-3 py-1 rounded-full bg-orange-50 text-orange-600 text-xs font-bold">
                    {cryptoPositions.length} positions
                  </span>
                </div>
                <div className="p-4 space-y-3 max-h-[300px] overflow-y-auto">
                  {cryptoPositions.length === 0 ? (
                    <div className="text-center py-8 text-gray-500">No crypto positions</div>
                  ) : (
                    cryptoPositions.map((pos) => (
                      <div key={pos.id} className="p-4 rounded-xl bg-gray-50 border border-gray-100">
                        <div className="flex items-center justify-between mb-2">
                          <div className="flex items-center gap-2">
                            <span className="font-bold text-gray-900 text-lg">{pos.symbol}</span>
                            <span className={cn(
                              "text-xs px-2 py-0.5 rounded-md font-bold",
                              pos.side === "long"
                                ? "bg-emerald-50 text-emerald-600"
                                : "bg-red-50 text-red-600"
                            )}>
                              {pos.side?.toUpperCase()}
                            </span>
                          </div>
                          <span className={cn(
                            "text-lg font-bold",
                            (pos.unrealized_pnl || 0) >= 0 ? "text-emerald-600" : "text-red-600"
                          )}>
                            {(pos.unrealized_pnl || 0) >= 0 ? "+" : ""}${pos.unrealized_pnl?.toFixed(2) || 0}
                          </span>
                        </div>
                        <div className="text-sm text-gray-500 mb-2">{pos.derivative_type}</div>
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

            {/* ML Metrics */}
            {status.ml_metrics && (
              <div className="rounded-2xl bg-gradient-to-r from-violet-50 to-blue-50 border border-violet-200 p-5">
                <div className="flex items-center gap-2 mb-4">
                  <Brain className="w-4 h-4 text-violet-500" />
                  <span className="font-semibold text-gray-900">ML Training Status</span>
                </div>
                <div className="grid grid-cols-2 lg:grid-cols-4 gap-6">
                  <div>
                    <div className="text-gray-500 text-sm">RL Steps</div>
                    <div className="text-gray-900 font-bold text-xl">{status.ml_metrics.rl_training_steps?.toLocaleString()}</div>
                  </div>
                  <div>
                    <div className="text-gray-500 text-sm">DQN Epsilon</div>
                    <div className="text-gray-900 font-bold text-xl">{status.ml_metrics.dqn_epsilon?.toFixed(4)}</div>
                  </div>
                  <div>
                    <div className="text-gray-500 text-sm">Episode Reward</div>
                    <div className="text-gray-900 font-bold text-xl">{status.ml_metrics.episode_reward?.toFixed(2)}</div>
                  </div>
                  <div>
                    <div className="text-gray-500 text-sm mb-1">Models Fitted</div>
                    <div className="flex items-center gap-3">
                      <span className={cn("text-sm font-bold", status.ml_metrics.hmm_fitted ? "text-emerald-600" : "text-gray-400")}>
                        HMM {status.ml_metrics.hmm_fitted ? "✓" : "○"}
                      </span>
                      <span className={cn("text-sm font-bold", status.ml_metrics.garch_fitted ? "text-emerald-600" : "text-gray-400")}>
                        GARCH {status.ml_metrics.garch_fitted ? "✓" : "○"}
                      </span>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* Stop Button */}
            <div className="flex justify-center pt-4">
              <button
                onClick={stopBot}
                className="px-8 py-3 rounded-xl bg-red-50 border border-red-200 text-red-600 hover:bg-red-100 transition-colors flex items-center gap-2 font-semibold"
              >
                <Square className="w-4 h-4" />
                Stop Trading Bot
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
