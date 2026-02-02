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
  Settings,
  ChevronRight,
  Sparkles,
  LineChart,
  Shield,
  Layers,
  Globe,
  Bitcoin,
  BarChart3,
  Gauge,
  Eye,
} from "lucide-react";
import { cn } from "@/lib/utils";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface MasterBotStatus {
  is_running: boolean;
  mode: string;
  market_regime: string;
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

  const [capital, setCapital] = useState("100000");
  const [mode, setMode] = useState("balanced");

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

  const getAssetClassIcon = (assetClass: string) => {
    switch (assetClass) {
      case "stock_options":
        return <BarChart3 className="w-4 h-4" />;
      case "etf_options":
        return <Layers className="w-4 h-4" />;
      case "commodity_options":
        return <Globe className="w-4 h-4" />;
      case "crypto_perpetual":
      case "crypto_options":
      case "crypto_spot":
        return <Bitcoin className="w-4 h-4" />;
      default:
        return <Activity className="w-4 h-4" />;
    }
  };

  const getAssetClassColor = (assetClass: string) => {
    switch (assetClass) {
      case "stock_options":
        return "text-blue-700 bg-blue-50";
      case "etf_options":
        return "text-purple-700 bg-purple-50";
      case "commodity_options":
        return "text-amber-700 bg-amber-50";
      case "crypto_perpetual":
        return "text-orange-700 bg-orange-50";
      case "crypto_options":
        return "text-yellow-700 bg-yellow-50";
      case "crypto_spot":
        return "text-emerald-700 bg-emerald-50";
      default:
        return "text-gray-600 bg-gray-100";
    }
  };

  const getRegimeColor = (regime: string) => {
    switch (regime) {
      case "high_volatility":
        return "text-red-700 bg-red-50 border-red-200";
      case "low_volatility":
        return "text-green-700 bg-green-50 border-green-200";
      default:
        return "text-amber-700 bg-amber-50 border-amber-200";
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <div className="animate-spin rounded-full h-8 w-8 border-2 border-blue-500 border-t-transparent" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Broker Status Banner */}
      {brokerStatus && (
        <div className="bg-white rounded-2xl border border-gray-200 px-4 py-3 shadow-sm flex items-center justify-between">
          <div className="flex items-center gap-4">
            <span className="text-sm text-gray-500">Live Data Feeds:</span>
            <div className="flex items-center gap-3">
              <div className="flex items-center gap-2">
                <div className={cn(
                  "w-2 h-2 rounded-full",
                  brokerStatus.alpaca?.connected ? "bg-green-500 animate-pulse" : "bg-gray-300"
                )} />
                <span className={cn(
                  "text-sm",
                  brokerStatus.alpaca?.connected ? "text-green-600" : "text-gray-500"
                )}>
                  Alpaca {brokerStatus.alpaca?.connected ? "(Live)" : "(Offline)"}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <div className={cn(
                  "w-2 h-2 rounded-full",
                  brokerStatus.binance?.connected ? "bg-green-500 animate-pulse" : "bg-gray-300"
                )} />
                <span className={cn(
                  "text-sm",
                  brokerStatus.binance?.connected ? "text-green-600" : "text-gray-500"
                )}>
                  Binance {brokerStatus.binance?.connected ? "(Live)" : "(Offline)"}
                </span>
              </div>
            </div>
          </div>
          <div className="text-xs text-gray-500">
            {brokerStatus.alpaca?.connected || brokerStatus.binance?.connected
              ? "Using LIVE market data"
              : "Using simulated data"}
          </div>
        </div>
      )}

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900 tracking-tight flex items-center gap-2">
            <Sparkles className="w-6 h-6 text-blue-500" />
            Master Quant Bot
          </h1>
          <p className="text-gray-500 mt-1">
            Unified autonomous trading across stocks, options, and crypto derivatives
          </p>
        </div>
        <div className="flex items-center gap-3">
          {status?.is_running && (
            <button
              onClick={triggerScan}
              className="px-4 py-2.5 rounded-xl bg-white border border-gray-200 hover:bg-gray-50 transition-colors flex items-center gap-2 text-sm text-gray-700"
            >
              <Eye className="w-4 h-4 text-blue-500" />
              Scan Markets
            </button>
          )}
          <button
            onClick={fetchData}
            className="p-2.5 rounded-xl bg-white border border-gray-200 hover:bg-gray-50 transition-colors"
          >
            <RefreshCw className="w-5 h-5 text-gray-500" />
          </button>
        </div>
      </div>

      {/* Market Regime Banner */}
      {status?.is_running && (
        <div className={cn(
          "rounded-2xl border px-4 py-3 flex items-center justify-between",
          getRegimeColor(status.market_regime)
        )}>
          <div className="flex items-center gap-3">
            <Gauge className="w-5 h-5" />
            <div>
              <span className="font-semibold capitalize">{status.market_regime.replace("_", " ")} Market</span>
              <span className="text-sm ml-2 opacity-80">VIX: {status.vix_level}</span>
            </div>
          </div>
          <div className="flex items-center gap-4 text-sm">
            <span>{status.opportunities_count} opportunities found</span>
            <span className="opacity-70">|</span>
            <span>Mode: {status.mode}</span>
          </div>
        </div>
      )}

      {/* Control Panel */}
      {!status?.is_running && (
        <div className="bg-white rounded-2xl border border-gray-200 p-6 shadow-sm">
          <h2 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
            <Settings className="w-5 h-5 text-blue-500" />
            Start Master Trading Bot
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <label className="block text-sm text-gray-500 mb-2">Initial Capital</label>
              <div className="relative">
                <DollarSign className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
                <input
                  type="number"
                  value={capital}
                  onChange={(e) => setCapital(e.target.value)}
                  className="w-full pl-9 pr-4 py-2.5 bg-white border border-gray-200 rounded-xl text-gray-900 focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 focus:outline-none"
                />
              </div>
            </div>
            <div>
              <label className="block text-sm text-gray-500 mb-2">Trading Mode</label>
              <select
                value={mode}
                onChange={(e) => setMode(e.target.value)}
                className="w-full px-4 py-2.5 bg-white border border-gray-200 rounded-xl text-gray-900 focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 focus:outline-none"
              >
                <option value="aggressive">Aggressive (Max ROI)</option>
                <option value="balanced">Balanced</option>
                <option value="conservative">Conservative</option>
              </select>
            </div>
            <div className="flex items-end">
              <button
                onClick={startBot}
                disabled={starting}
                className="w-full py-2.5 px-4 bg-gradient-to-r from-blue-500 to-blue-600 rounded-xl font-medium text-white hover:from-blue-600 hover:to-blue-700 disabled:opacity-50 flex items-center justify-center gap-2 shadow-sm"
              >
                {starting ? (
                  <RefreshCw className="w-4 h-4 animate-spin" />
                ) : (
                  <Play className="w-4 h-4" />
                )}
                Start Trading All Markets
              </button>
            </div>
          </div>
          <div className="mt-4 p-3 bg-blue-50 border border-blue-100 rounded-xl">
            <div className="flex items-center gap-2 text-blue-700 text-sm mb-1">
              <Shield className="w-4 h-4" />
              <span className="font-medium">Paper Trading Mode</span>
            </div>
            <p className="text-xs text-gray-600">
              {brokerStatus?.alpaca?.connected || brokerStatus?.binance?.connected
                ? "Using LIVE market data with simulated trades. No real money at risk."
                : "Using simulated data. Connect Alpaca/Binance for live prices."}
            </p>
          </div>
        </div>
      )}

      {/* Running Status */}
      {status?.is_running && (
        <>
          {/* Portfolio Stats */}
          <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
            <div className="bg-white rounded-2xl border border-gray-200 p-5 shadow-sm">
              <div className="text-sm text-gray-500">Portfolio Value</div>
              <div className="text-2xl font-bold text-gray-900 mt-1">
                ${status.total_value?.toLocaleString(undefined, { maximumFractionDigits: 0 })}
              </div>
            </div>
            <div className="bg-white rounded-2xl border border-gray-200 p-5 shadow-sm">
              <div className="text-sm text-gray-500">Total P&L</div>
              <div className={cn(
                "text-2xl font-bold mt-1",
                status.total_pnl >= 0 ? "text-green-600" : "text-red-600"
              )}>
                {status.total_pnl >= 0 ? "+" : ""}${status.total_pnl?.toLocaleString(undefined, { maximumFractionDigits: 0 })}
              </div>
              <div className={cn(
                "text-sm",
                status.total_pnl_pct >= 0 ? "text-green-600" : "text-red-600"
              )}>
                {status.total_pnl_pct >= 0 ? "+" : ""}{status.total_pnl_pct?.toFixed(2)}%
              </div>
            </div>
            <div className="bg-white rounded-2xl border border-gray-200 p-5 shadow-sm">
              <div className="text-sm text-gray-500">Options Positions</div>
              <div className="text-2xl font-bold text-blue-600 mt-1">{status.positions?.options || 0}</div>
            </div>
            <div className="bg-white rounded-2xl border border-gray-200 p-5 shadow-sm">
              <div className="text-sm text-gray-500">Crypto Positions</div>
              <div className="text-2xl font-bold text-orange-600 mt-1">{status.positions?.crypto || 0}</div>
            </div>
            <div className="bg-white rounded-2xl border border-gray-200 p-5 shadow-sm">
              <div className="text-sm text-gray-500">Cash Available</div>
              <div className="text-2xl font-bold text-blue-600 mt-1">
                ${status.cash?.toLocaleString(undefined, { maximumFractionDigits: 0 })}
              </div>
            </div>
          </div>

          {/* Greeks & Risk */}
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            <div className="bg-white rounded-2xl border border-gray-200 p-5 shadow-sm">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm text-gray-500">Portfolio Delta</span>
                <span className="text-lg font-bold text-gray-900">{status.risk_summary?.portfolio_delta?.toFixed(1) || 0}</span>
              </div>
              <div className="h-2 bg-gray-100 rounded-full">
                <div
                  className="h-full bg-blue-500 rounded-full"
                  style={{ width: `${Math.min(100, status.risk_summary?.delta_utilization || 0)}%` }}
                />
              </div>
            </div>
            <div className="bg-white rounded-2xl border border-gray-200 p-5 shadow-sm">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm text-gray-500">Portfolio Theta</span>
                <span className={cn(
                  "text-lg font-bold",
                  (status.risk_summary?.portfolio_theta || 0) > 0 ? "text-green-600" : "text-red-600"
                )}>
                  {status.risk_summary?.portfolio_theta?.toFixed(1) || 0}/day
                </span>
              </div>
              <div className="text-xs text-gray-500">Daily time decay</div>
            </div>
            <div className="bg-white rounded-2xl border border-gray-200 p-5 shadow-sm">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm text-gray-500">Portfolio Vega</span>
                <span className="text-lg font-bold text-gray-900">{status.risk_summary?.portfolio_vega?.toFixed(1) || 0}</span>
              </div>
              <div className="h-2 bg-gray-100 rounded-full">
                <div
                  className="h-full bg-purple-500 rounded-full"
                  style={{ width: `${Math.min(100, status.risk_summary?.vega_utilization || 0)}%` }}
                />
              </div>
            </div>
            <div className="bg-white rounded-2xl border border-gray-200 p-5 shadow-sm">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm text-gray-500">Buying Power Used</span>
                <span className="text-lg font-bold text-gray-900">{status.risk_summary?.buying_power_used_pct?.toFixed(1) || 0}%</span>
              </div>
              <div className="h-2 bg-gray-100 rounded-full">
                <div
                  className="h-full bg-amber-500 rounded-full"
                  style={{ width: `${Math.min(100, status.risk_summary?.buying_power_used_pct || 0)}%` }}
                />
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Top Opportunities */}
            <div className="bg-white rounded-2xl border border-gray-200 p-5 shadow-sm">
              <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
                <Target className="w-5 h-5 text-blue-500" />
                Top Opportunities
              </h3>
              <div className="space-y-3 max-h-[400px] overflow-y-auto">
                {opportunities.length === 0 ? (
                  <div className="text-center py-8 text-gray-400">
                    <Eye className="w-8 h-8 mx-auto mb-2 opacity-50" />
                    <p>Scanning for opportunities...</p>
                  </div>
                ) : (
                  opportunities.map((opp, i) => (
                    <div
                      key={i}
                      className="bg-gray-50 rounded-xl p-3 border border-gray-100 hover:border-blue-200 transition-colors"
                    >
                      <div className="flex items-center justify-between mb-2">
                        <div className="flex items-center gap-2">
                          <span className={cn(
                            "px-2 py-0.5 rounded text-xs flex items-center gap-1",
                            getAssetClassColor(opp.asset_class)
                          )}>
                            {getAssetClassIcon(opp.asset_class)}
                            {opp.asset_class.replace("_", " ")}
                          </span>
                          <span className="font-bold text-gray-900">{opp.symbol}</span>
                        </div>
                        <span className="text-sm font-bold text-blue-600">Score: {opp.score.toFixed(0)}</span>
                      </div>
                      <div className="text-sm text-gray-600 mb-2">{opp.strategy}</div>
                      <div className="grid grid-cols-3 gap-2 text-xs">
                        <div>
                          <span className="text-gray-500">Return</span>
                          <div className="text-green-600 font-medium">{opp.expected_return.toFixed(0)}%</div>
                        </div>
                        <div>
                          <span className="text-gray-500">P(Profit)</span>
                          <div className="text-gray-900 font-medium">{opp.probability_of_profit.toFixed(0)}%</div>
                        </div>
                        <div>
                          <span className="text-gray-500">IV Rank</span>
                          <div className="text-amber-600 font-medium">{opp.iv_rank.toFixed(0)}%</div>
                        </div>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>

            {/* Bot Commentary */}
            <div className="bg-white rounded-2xl border border-gray-200 p-5 shadow-sm">
              <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
                <Activity className="w-5 h-5 text-blue-500" />
                Bot Activity
              </h3>
              <div className="space-y-2 max-h-[400px] overflow-y-auto">
                {commentary.length === 0 ? (
                  <div className="text-center py-8 text-gray-400">
                    <Activity className="w-8 h-8 mx-auto mb-2 opacity-50" />
                    <p>Waiting for activity...</p>
                  </div>
                ) : (
                  [...commentary].reverse().map((entry, i) => (
                    <div
                      key={i}
                      className={cn(
                        "text-sm p-2 rounded-lg border-l-2",
                        entry.category === "trade" ? "bg-green-50 border-green-500" :
                        entry.category === "risk" ? "bg-red-50 border-red-500" :
                        entry.category === "scan" ? "bg-blue-50 border-blue-500" :
                        entry.category === "analysis" ? "bg-purple-50 border-purple-500" :
                        "bg-gray-50 border-gray-300"
                      )}
                    >
                      <div className="text-gray-700">{entry.message}</div>
                      <div className="text-xs text-gray-500 mt-1">
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
            <div className="bg-white rounded-2xl border border-gray-200 p-5 shadow-sm">
              <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
                <Layers className="w-5 h-5 text-blue-500" />
                Options Positions ({optionsPositions.length})
              </h3>
              <div className="space-y-2 max-h-[300px] overflow-y-auto">
                {optionsPositions.length === 0 ? (
                  <div className="text-center py-6 text-gray-400 text-sm">No options positions</div>
                ) : (
                  optionsPositions.map((pos) => (
                    <div
                      key={pos.id}
                      className="bg-gray-50 rounded-xl p-3 border border-gray-100"
                    >
                      <div className="flex items-center justify-between mb-1">
                        <span className="font-bold text-gray-900">{pos.symbol}</span>
                        <span className={cn(
                          "font-bold",
                          pos.current_pnl >= 0 ? "text-green-600" : "text-red-600"
                        )}>
                          {pos.current_pnl >= 0 ? "+" : ""}${pos.current_pnl?.toFixed(0)}
                        </span>
                      </div>
                      <div className="text-sm text-gray-500">{pos.strategy_name}</div>
                      <div className="flex items-center gap-3 mt-2 text-xs text-gray-500">
                        <span>Δ {pos.greeks?.delta?.toFixed(2)}</span>
                        <span>Θ {pos.greeks?.theta?.toFixed(2)}</span>
                        <span>IV: {pos.entry_iv}%</span>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>

            {/* Crypto Positions */}
            <div className="bg-white rounded-2xl border border-gray-200 p-5 shadow-sm">
              <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
                <Bitcoin className="w-5 h-5 text-orange-500" />
                Crypto Positions ({cryptoPositions.length})
              </h3>
              <div className="space-y-2 max-h-[300px] overflow-y-auto">
                {cryptoPositions.length === 0 ? (
                  <div className="text-center py-6 text-gray-400 text-sm">No crypto positions</div>
                ) : (
                  cryptoPositions.map((pos) => (
                    <div
                      key={pos.id}
                      className="bg-gray-50 rounded-xl p-3 border border-gray-100"
                    >
                      <div className="flex items-center justify-between mb-1">
                        <div className="flex items-center gap-2">
                          <span className="font-bold text-gray-900">{pos.symbol}</span>
                          <span className={cn(
                            "text-xs px-2 py-0.5 rounded",
                            pos.side === "long" ? "bg-green-50 text-green-700" : "bg-red-50 text-red-700"
                          )}>
                            {pos.side.toUpperCase()}
                          </span>
                        </div>
                        <span className={cn(
                          "font-bold",
                          pos.unrealized_pnl >= 0 ? "text-green-600" : "text-red-600"
                        )}>
                          {pos.unrealized_pnl >= 0 ? "+" : ""}${pos.unrealized_pnl?.toFixed(2)}
                        </span>
                      </div>
                      <div className="text-sm text-gray-500">{pos.derivative_type}</div>
                      <div className="flex items-center gap-3 mt-2 text-xs text-gray-500">
                        <span>Size: ${pos.size?.toLocaleString()}</span>
                        <span>{pos.leverage}x</span>
                        <span>Entry: ${pos.entry_price?.toLocaleString()}</span>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>

          {/* Stop Button */}
          <div className="flex justify-center">
            <button
              onClick={stopBot}
              className="px-8 py-3 bg-red-50 border border-red-200 rounded-xl text-red-600 hover:bg-red-100 transition-colors flex items-center gap-2 font-medium"
            >
              <Square className="w-5 h-5" />
              Stop Master Bot
            </button>
          </div>
        </>
      )}
    </div>
  );
}
