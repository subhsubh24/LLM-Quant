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
  Clock,
  Zap,
  Settings,
  ArrowUpRight,
  ArrowDownRight,
  ChevronRight,
  Sparkles,
  Percent,
  LineChart,
  Shield,
  Layers,
} from "lucide-react";
import { cn } from "@/lib/utils";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface BotStatus {
  is_running: boolean;
  mode: string;
  asset_class: string;
  initial_capital: number;
  cash: number;
  total_value: number;
  total_pnl: number;
  total_pnl_pct: number;
  positions_count: number;
  trades_count: number;
  last_scan: string | null;
  risk_summary: {
    risk_mode: string;
    portfolio_delta: number;
    portfolio_theta: number;
    portfolio_vega: number;
    delta_utilization: number;
    vega_utilization: number;
    buying_power_used_pct: number;
  };
  strategy_info: {
    preferred_strategies: string[];
    target_delta: number;
    min_iv_rank: number;
    profit_target: string;
  };
}

interface OptionsPosition {
  id: string;
  symbol: string;
  strategy_name: string;
  entry_time: string;
  entry_iv: number;
  entry_price: number;
  current_price: number;
  current_pnl: number;
  days_in_trade: number;
  max_profit: number;
  max_loss: number;
  greeks: {
    delta: number;
    theta: number;
    vega: number;
  };
  legs_count: number;
}

interface OptionsTrade {
  id: string;
  timestamp: string;
  symbol: string;
  strategy_name: string;
  action: string;
  net_premium: number;
  pnl: number;
  rationale: string;
  iv_at_trade: number;
  underlying_at_trade: number;
}

interface BotPerformance {
  total_return: number;
  total_pnl: number;
  win_rate: number;
  avg_win: number;
  avg_loss: number;
  total_trades: number;
  open_positions: number;
  current_value: number;
  portfolio_theta: number;
  portfolio_delta: number;
}

interface CommentaryEntry {
  timestamp: string;
  message: string;
  category: string;
}

interface IVAnalysis {
  [symbol: string]: {
    symbol: string;
    current_iv: number;
    iv_rank: number;
    iv_percentile: number;
    is_high_iv: boolean;
    premium_selling_favorable: boolean;
  };
}

export default function OptionsQuantBotPage() {
  const [status, setStatus] = useState<BotStatus | null>(null);
  const [positions, setPositions] = useState<OptionsPosition[]>([]);
  const [trades, setTrades] = useState<OptionsTrade[]>([]);
  const [performance, setPerformance] = useState<BotPerformance | null>(null);
  const [commentary, setCommentary] = useState<CommentaryEntry[]>([]);
  const [ivAnalysis, setIvAnalysis] = useState<IVAnalysis>({});
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState(false);
  const [selectedTrade, setSelectedTrade] = useState<OptionsTrade | null>(null);

  const [capital, setCapital] = useState("100000");
  const [mode, setMode] = useState("balanced");

  const fetchData = useCallback(async () => {
    try {
      const [statusRes, positionsRes, tradesRes, perfRes, commentaryRes, ivRes] = await Promise.all([
        fetch(`${API_BASE}/api/options-bot/status`),
        fetch(`${API_BASE}/api/options-bot/positions`),
        fetch(`${API_BASE}/api/options-bot/trades?limit=20`),
        fetch(`${API_BASE}/api/options-bot/performance`),
        fetch(`${API_BASE}/api/options-bot/commentary?limit=30`),
        fetch(`${API_BASE}/api/options-bot/iv-analysis`),
      ]);

      if (statusRes.ok) setStatus(await statusRes.json());
      if (positionsRes.ok) {
        const data = await positionsRes.json();
        setPositions(data.positions || []);
      }
      if (tradesRes.ok) {
        const data = await tradesRes.json();
        setTrades(data.trades || []);
      }
      if (perfRes.ok) setPerformance(await perfRes.json());
      if (commentaryRes.ok) {
        const data = await commentaryRes.json();
        setCommentary(data.commentary || []);
      }
      if (ivRes.ok) {
        const data = await ivRes.json();
        setIvAnalysis(data.iv_analysis || {});
      }
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
        `${API_BASE}/api/options-bot/start?capital=${capital}&mode=${mode}`,
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
      await fetch(`${API_BASE}/api/options-bot/stop`, { method: "POST" });
      await fetchData();
    } catch (err) {
      console.error("Failed to stop bot:", err);
    }
  };

  const triggerScan = async () => {
    try {
      await fetch(`${API_BASE}/api/options-bot/scan`, { method: "POST" });
      await fetchData();
    } catch (err) {
      console.error("Failed to trigger scan:", err);
    }
  };

  const formatCurrency = (val: number) =>
    new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(val);

  const formatPct = (val: number) => `${val >= 0 ? "+" : ""}${val.toFixed(2)}%`;

  const strategyColors: Record<string, string> = {
    "Iron Condor": "bg-purple-100 text-purple-700",
    "Long Straddle": "bg-blue-100 text-blue-700",
    "Bull Call Spread": "bg-green-100 text-green-700",
    "Bear Put Spread": "bg-red-100 text-red-700",
    "Calendar Spread": "bg-orange-100 text-orange-700",
    "Butterfly": "bg-pink-100 text-pink-700",
  };

  return (
    <div className="min-h-screen p-8">
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-3xl font-bold text-gray-900 tracking-tight">Options Quant Bot</h1>
          <p className="text-gray-500 mt-1">Autonomous options trading with IV analysis & Greeks management</p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={triggerScan}
            disabled={!status?.is_running}
            className="px-4 py-2 bg-white rounded-xl text-sm font-medium text-gray-700 hover:bg-gray-50 shadow-sm border border-gray-200 disabled:opacity-50 flex items-center gap-2"
          >
            <Zap className="w-4 h-4" />
            Scan Markets
          </button>
          <button
            onClick={fetchData}
            className="p-2 bg-white rounded-xl hover:bg-gray-50 shadow-sm border border-gray-200"
          >
            <RefreshCw className={cn("w-5 h-5 text-gray-500", loading && "animate-spin")} />
          </button>
        </div>
      </div>

      {/* Risk Mode Banner */}
      {status?.risk_summary && (
        <div className={cn(
          "mb-6 p-4 rounded-2xl flex items-center justify-between",
          status.risk_summary.risk_mode === "NORMAL"
            ? "bg-green-50 border border-green-100"
            : status.risk_summary.risk_mode === "REDUCED"
            ? "bg-yellow-50 border border-yellow-100"
            : "bg-red-50 border border-red-100"
        )}>
          <div className="flex items-center gap-3">
            <div className={cn(
              "w-3 h-3 rounded-full",
              status.risk_summary.risk_mode === "NORMAL" ? "bg-green-500 animate-pulse" :
              status.risk_summary.risk_mode === "REDUCED" ? "bg-yellow-500" : "bg-red-500"
            )} />
            <div>
              <span className={cn(
                "font-semibold",
                status.risk_summary.risk_mode === "NORMAL" ? "text-green-700" :
                status.risk_summary.risk_mode === "REDUCED" ? "text-yellow-700" : "text-red-700"
              )}>
                Risk Mode: {status.risk_summary.risk_mode}
              </span>
              <span className="text-gray-600 ml-2">
                {status.is_running ? "Actively trading options" : "Bot stopped"}
              </span>
            </div>
          </div>
          <div className="flex items-center gap-6 text-sm">
            <div className="text-center">
              <div className="font-bold text-gray-900">{status.risk_summary.portfolio_delta?.toFixed(0) || 0}</div>
              <div className="text-xs text-gray-500">Delta</div>
            </div>
            <div className="text-center">
              <div className="font-bold text-green-600">${status.risk_summary.portfolio_theta?.toFixed(0) || 0}</div>
              <div className="text-xs text-gray-500">Daily Theta</div>
            </div>
            <div className="text-center">
              <div className="font-bold text-purple-600">{status.risk_summary.portfolio_vega?.toFixed(0) || 0}</div>
              <div className="text-xs text-gray-500">Vega</div>
            </div>
          </div>
        </div>
      )}

      {/* Stats Grid */}
      <div className="grid grid-cols-5 gap-4 mb-6">
        <div className="bg-white rounded-2xl p-5 shadow-sm">
          <div className="flex items-center justify-between mb-3">
            <span className="text-sm font-medium text-gray-500">Portfolio Value</span>
            <DollarSign className="w-5 h-5 text-blue-500" />
          </div>
          <div className="text-2xl font-bold text-gray-900 tracking-tight">
            {formatCurrency(status?.total_value || 0)}
          </div>
          <div className={cn(
            "text-sm mt-1 flex items-center gap-1",
            (status?.total_pnl || 0) >= 0 ? "text-green-600" : "text-red-600"
          )}>
            {(status?.total_pnl || 0) >= 0 ? <ArrowUpRight className="w-4 h-4" /> : <ArrowDownRight className="w-4 h-4" />}
            {formatPct(status?.total_pnl_pct || 0)}
          </div>
        </div>

        <div className="bg-white rounded-2xl p-5 shadow-sm">
          <div className="flex items-center justify-between mb-3">
            <span className="text-sm font-medium text-gray-500">Total P&L</span>
            {(status?.total_pnl || 0) >= 0 ? (
              <TrendingUp className="w-5 h-5 text-green-500" />
            ) : (
              <TrendingDown className="w-5 h-5 text-red-500" />
            )}
          </div>
          <div className={cn(
            "text-2xl font-bold tracking-tight",
            (status?.total_pnl || 0) >= 0 ? "text-green-600" : "text-red-600"
          )}>
            {formatCurrency(status?.total_pnl || 0)}
          </div>
          <div className="text-sm text-gray-500 mt-1">
            From {formatCurrency(status?.initial_capital || 0)}
          </div>
        </div>

        <div className="bg-white rounded-2xl p-5 shadow-sm">
          <div className="flex items-center justify-between mb-3">
            <span className="text-sm font-medium text-gray-500">Win Rate</span>
            <Target className="w-5 h-5 text-purple-500" />
          </div>
          <div className="text-2xl font-bold text-gray-900 tracking-tight">
            {performance?.win_rate?.toFixed(1) || 0}%
          </div>
          <div className="text-sm text-gray-500 mt-1">
            {performance?.total_trades || 0} closed trades
          </div>
        </div>

        <div className="bg-white rounded-2xl p-5 shadow-sm">
          <div className="flex items-center justify-between mb-3">
            <span className="text-sm font-medium text-gray-500">Daily Theta</span>
            <Clock className="w-5 h-5 text-green-500" />
          </div>
          <div className="text-2xl font-bold text-green-600 tracking-tight">
            ${performance?.portfolio_theta?.toFixed(0) || 0}
          </div>
          <div className="text-sm text-gray-500 mt-1">
            Time decay income/day
          </div>
        </div>

        <div className="bg-white rounded-2xl p-5 shadow-sm">
          <div className="flex items-center justify-between mb-3">
            <span className="text-sm font-medium text-gray-500">Open Positions</span>
            <Layers className="w-5 h-5 text-orange-500" />
          </div>
          <div className="text-2xl font-bold text-gray-900 tracking-tight">
            {positions.length}
          </div>
          <div className="text-sm text-gray-500 mt-1">
            Active strategies
          </div>
        </div>
      </div>

      <div className="grid grid-cols-12 gap-6">
        {/* Control Panel */}
        <div className="col-span-3">
          <div className="bg-white rounded-2xl shadow-sm overflow-hidden">
            <div className="p-6 border-b border-gray-100">
              <h2 className="font-semibold text-gray-900 flex items-center gap-2">
                <Settings className="w-5 h-5 text-gray-400" />
                Bot Controls
              </h2>
            </div>
            <div className="p-6">
              {!status?.is_running ? (
                <div className="space-y-4">
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      Starting Capital
                    </label>
                    <input
                      type="number"
                      value={capital}
                      onChange={(e) => setCapital(e.target.value)}
                      className="w-full px-3 py-2 rounded-lg border border-gray-200 focus:ring-2 focus:ring-blue-500"
                      placeholder="100000"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      Trading Mode
                    </label>
                    <select
                      value={mode}
                      onChange={(e) => setMode(e.target.value)}
                      className="w-full px-3 py-2 rounded-lg border border-gray-200 bg-white focus:ring-2 focus:ring-blue-500"
                    >
                      <option value="aggressive">Aggressive (30Δ, High Freq)</option>
                      <option value="balanced">Balanced (20Δ, Mixed)</option>
                      <option value="conservative">Conservative (15Δ, Theta)</option>
                    </select>
                  </div>
                  <div className="p-3 rounded-xl bg-purple-50 text-sm text-purple-700">
                    <p className="font-medium mb-1">Options Strategies:</p>
                    <p className="text-xs text-purple-600">
                      Iron Condors, Straddles, Verticals, Butterflies based on IV rank and Greeks
                    </p>
                  </div>
                  <button
                    onClick={startBot}
                    disabled={starting}
                    className="w-full py-3 rounded-xl bg-gradient-to-r from-purple-600 to-blue-600 text-white font-semibold hover:from-purple-700 hover:to-blue-700 disabled:opacity-50 flex items-center justify-center gap-2"
                  >
                    <Play className="w-5 h-5" />
                    {starting ? "Starting..." : "Start Options Bot"}
                  </button>
                </div>
              ) : (
                <div className="space-y-4">
                  <div className="p-4 rounded-xl bg-green-50 border border-green-100">
                    <div className="flex items-center gap-2 mb-2">
                      <div className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
                      <span className="font-semibold text-green-700">Bot Active</span>
                    </div>
                    <div className="space-y-1 text-sm text-green-600">
                      <div className="flex justify-between">
                        <span>Mode:</span>
                        <span className="font-medium capitalize">{status.mode}</span>
                      </div>
                      <div className="flex justify-between">
                        <span>Target Δ:</span>
                        <span className="font-medium">{status.strategy_info?.target_delta}</span>
                      </div>
                      <div className="flex justify-between">
                        <span>Min IV Rank:</span>
                        <span className="font-medium">{status.strategy_info?.min_iv_rank}%</span>
                      </div>
                    </div>
                  </div>
                  <button
                    onClick={stopBot}
                    className="w-full py-3 rounded-xl bg-red-500 text-white font-semibold hover:bg-red-600 flex items-center justify-center gap-2"
                  >
                    <Square className="w-5 h-5" />
                    Stop Trading
                  </button>
                </div>
              )}
            </div>
          </div>

          {/* Greeks Summary */}
          <div className="bg-white rounded-2xl shadow-sm p-6 mt-4">
            <h3 className="text-sm font-semibold text-gray-700 mb-4 flex items-center gap-2">
              <Shield className="w-4 h-4 text-gray-400" />
              Portfolio Greeks
            </h3>
            <div className="space-y-3">
              <div className="flex justify-between items-center">
                <span className="text-gray-600">Delta (Δ)</span>
                <span className="font-mono font-semibold">{status?.risk_summary?.portfolio_delta?.toFixed(0) || 0}</span>
              </div>
              <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
                <div
                  className="h-full bg-blue-500 rounded-full"
                  style={{ width: `${Math.min(status?.risk_summary?.delta_utilization || 0, 100)}%` }}
                />
              </div>

              <div className="flex justify-between items-center mt-3">
                <span className="text-gray-600">Theta (Θ)</span>
                <span className="font-mono font-semibold text-green-600">
                  ${status?.risk_summary?.portfolio_theta?.toFixed(0) || 0}/day
                </span>
              </div>

              <div className="flex justify-between items-center mt-3">
                <span className="text-gray-600">Vega (ν)</span>
                <span className="font-mono font-semibold">{status?.risk_summary?.portfolio_vega?.toFixed(0) || 0}</span>
              </div>
              <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
                <div
                  className="h-full bg-purple-500 rounded-full"
                  style={{ width: `${Math.min(status?.risk_summary?.vega_utilization || 0, 100)}%` }}
                />
              </div>
            </div>
          </div>

          {/* Live Commentary */}
          <div className="bg-white rounded-2xl shadow-sm mt-4 overflow-hidden">
            <div className="p-4 border-b border-gray-100 flex items-center justify-between">
              <h3 className="font-semibold text-gray-900 flex items-center gap-2">
                <Sparkles className="w-4 h-4 text-purple-500" />
                Bot Thinking
              </h3>
              {status?.is_running && (
                <span className="flex items-center gap-1 text-xs text-green-600">
                  <span className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse" />
                  LIVE
                </span>
              )}
            </div>
            <div className="max-h-[250px] overflow-y-auto">
              {commentary.length > 0 ? (
                <div className="divide-y divide-gray-50">
                  {[...commentary].reverse().slice(0, 15).map((entry, idx) => (
                    <div
                      key={idx}
                      className={cn(
                        "p-3 text-xs",
                        entry.category === "trade" && "bg-blue-50",
                        entry.category === "risk" && "bg-red-50",
                        entry.category === "system" && "bg-gray-50"
                      )}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <span className="text-gray-800 leading-relaxed">{entry.message}</span>
                        <span className="text-gray-400 whitespace-nowrap text-[10px]">
                          {new Date(entry.timestamp).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'})}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="p-6 text-center text-gray-400 text-sm">
                  {status?.is_running ? "Scanning for opportunities..." : "Start the bot to see activity"}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Positions & Trades */}
        <div className="col-span-9 space-y-6">
          {/* Active Options Positions */}
          <div className="bg-white rounded-2xl shadow-sm overflow-hidden">
            <div className="p-6 border-b border-gray-100 flex items-center justify-between">
              <h2 className="font-semibold text-gray-900 flex items-center gap-2">
                <Layers className="w-5 h-5 text-gray-400" />
                Active Options Positions
                <span className="ml-2 px-2 py-0.5 bg-purple-100 text-purple-700 text-sm rounded-full">
                  {positions.length}
                </span>
              </h2>
            </div>
            {positions.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead className="bg-gray-50">
                    <tr>
                      <th className="text-left text-xs font-medium text-gray-500 uppercase tracking-wider py-3 px-6">Strategy</th>
                      <th className="text-right text-xs font-medium text-gray-500 uppercase tracking-wider py-3 px-6">Entry IV</th>
                      <th className="text-right text-xs font-medium text-gray-500 uppercase tracking-wider py-3 px-6">Current P&L</th>
                      <th className="text-right text-xs font-medium text-gray-500 uppercase tracking-wider py-3 px-6">Max Profit</th>
                      <th className="text-right text-xs font-medium text-gray-500 uppercase tracking-wider py-3 px-6">Greeks</th>
                      <th className="text-right text-xs font-medium text-gray-500 uppercase tracking-wider py-3 px-6">DIT</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {positions.map((pos) => (
                      <tr key={pos.id} className="hover:bg-gray-50">
                        <td className="py-4 px-6">
                          <div className="flex items-center gap-3">
                            <div className="w-10 h-10 rounded-xl bg-purple-100 flex items-center justify-center">
                              <LineChart className="w-5 h-5 text-purple-600" />
                            </div>
                            <div>
                              <div className="font-semibold text-gray-900">{pos.symbol}</div>
                              <span className={cn(
                                "text-xs px-2 py-0.5 rounded-full",
                                strategyColors[pos.strategy_name] || "bg-gray-100 text-gray-600"
                              )}>
                                {pos.strategy_name}
                              </span>
                            </div>
                          </div>
                        </td>
                        <td className="py-4 px-6 text-right font-mono text-gray-600">
                          {pos.entry_iv}%
                        </td>
                        <td className="py-4 px-6 text-right">
                          <div className={cn(
                            "font-semibold",
                            pos.current_pnl >= 0 ? "text-green-600" : "text-red-600"
                          )}>
                            {formatCurrency(pos.current_pnl)}
                          </div>
                        </td>
                        <td className="py-4 px-6 text-right text-gray-600">
                          <div className="text-green-600">{formatCurrency(pos.max_profit)}</div>
                          <div className="text-xs text-red-500">{formatCurrency(pos.max_loss)}</div>
                        </td>
                        <td className="py-4 px-6 text-right text-xs font-mono">
                          <div>Δ {pos.greeks.delta?.toFixed(0)}</div>
                          <div className="text-green-600">Θ ${pos.greeks.theta?.toFixed(0)}</div>
                        </td>
                        <td className="py-4 px-6 text-right text-gray-600">
                          {pos.days_in_trade}d
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="p-12 text-center">
                <div className="w-16 h-16 rounded-2xl bg-purple-100 flex items-center justify-center mx-auto mb-4">
                  <Layers className="w-8 h-8 text-purple-400" />
                </div>
                <h3 className="text-lg font-medium text-gray-900 mb-1">No Active Positions</h3>
                <p className="text-gray-500 text-sm">Start the bot to begin trading options automatically</p>
              </div>
            )}
          </div>

          {/* IV Analysis */}
          {Object.keys(ivAnalysis).length > 0 && (
            <div className="bg-white rounded-2xl shadow-sm overflow-hidden">
              <div className="p-6 border-b border-gray-100">
                <h2 className="font-semibold text-gray-900 flex items-center gap-2">
                  <Percent className="w-5 h-5 text-gray-400" />
                  IV Analysis (Premium Selling Opportunities)
                </h2>
              </div>
              <div className="p-6 grid grid-cols-5 gap-4">
                {Object.values(ivAnalysis).slice(0, 10).map((iv) => (
                  <div
                    key={iv.symbol}
                    className={cn(
                      "p-4 rounded-xl border",
                      iv.premium_selling_favorable
                        ? "bg-green-50 border-green-200"
                        : "bg-gray-50 border-gray-200"
                    )}
                  >
                    <div className="font-semibold text-gray-900">{iv.symbol}</div>
                    <div className="text-2xl font-bold mt-1">
                      {iv.iv_rank?.toFixed(0)}%
                    </div>
                    <div className="text-xs text-gray-500">IV Rank</div>
                    {iv.premium_selling_favorable && (
                      <div className="mt-2 text-xs text-green-600 font-medium">
                        ✓ Sell Premium
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Recent Trades */}
          <div className="bg-white rounded-2xl shadow-sm overflow-hidden">
            <div className="p-6 border-b border-gray-100">
              <h2 className="font-semibold text-gray-900 flex items-center gap-2">
                <Activity className="w-5 h-5 text-gray-400" />
                Recent Trades
              </h2>
            </div>
            {trades.length > 0 ? (
              <div className="divide-y divide-gray-100 max-h-80 overflow-y-auto">
                {trades.map((trade) => (
                  <div
                    key={trade.id}
                    className="p-4 hover:bg-gray-50 cursor-pointer flex items-center justify-between"
                    onClick={() => setSelectedTrade(trade)}
                  >
                    <div className="flex items-center gap-4">
                      <div className={cn(
                        "w-10 h-10 rounded-xl flex items-center justify-center",
                        trade.action === "OPEN" ? "bg-blue-100" : "bg-gray-100"
                      )}>
                        {trade.action === "OPEN" ? (
                          <ArrowUpRight className="w-5 h-5 text-blue-600" />
                        ) : (
                          <ArrowDownRight className="w-5 h-5 text-gray-600" />
                        )}
                      </div>
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="font-semibold text-gray-900">{trade.symbol}</span>
                          <span className={cn(
                            "px-2 py-0.5 text-xs font-medium rounded-full",
                            strategyColors[trade.strategy_name] || "bg-gray-100 text-gray-600"
                          )}>
                            {trade.strategy_name}
                          </span>
                          <span className={cn(
                            "px-2 py-0.5 text-xs font-medium rounded-full",
                            trade.action === "OPEN" ? "bg-blue-100 text-blue-700" : "bg-gray-100 text-gray-700"
                          )}>
                            {trade.action}
                          </span>
                        </div>
                        <div className="text-sm text-gray-500 truncate max-w-md">
                          {trade.rationale}
                        </div>
                      </div>
                    </div>
                    <div className="text-right">
                      {trade.action === "CLOSE" && (
                        <div className={cn(
                          "font-semibold",
                          trade.pnl >= 0 ? "text-green-600" : "text-red-600"
                        )}>
                          {formatCurrency(trade.pnl)}
                        </div>
                      )}
                      <div className="text-xs text-gray-500">IV: {trade.iv_at_trade}%</div>
                    </div>
                    <ChevronRight className="w-5 h-5 text-gray-400" />
                  </div>
                ))}
              </div>
            ) : (
              <div className="p-12 text-center">
                <div className="w-16 h-16 rounded-2xl bg-gray-100 flex items-center justify-center mx-auto mb-4">
                  <Activity className="w-8 h-8 text-gray-400" />
                </div>
                <h3 className="text-lg font-medium text-gray-900 mb-1">No Trades Yet</h3>
                <p className="text-gray-500 text-sm">Trades will appear here once the bot executes them</p>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Trade Detail Modal */}
      {selectedTrade && (
        <div
          className="fixed inset-0 bg-black/30 backdrop-blur-sm flex items-center justify-center z-50"
          onClick={() => setSelectedTrade(null)}
        >
          <div
            className="bg-white rounded-3xl w-full max-w-lg max-h-[80vh] overflow-y-auto m-4 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="p-6 border-b border-gray-100 flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className={cn(
                  "w-12 h-12 rounded-xl flex items-center justify-center",
                  selectedTrade.action === "OPEN" ? "bg-blue-100" : "bg-gray-100"
                )}>
                  <LineChart className="w-6 h-6 text-purple-600" />
                </div>
                <div>
                  <h3 className="text-xl font-bold text-gray-900">{selectedTrade.symbol}</h3>
                  <p className="text-sm text-gray-500">{selectedTrade.strategy_name} • {selectedTrade.action}</p>
                </div>
              </div>
              <button
                onClick={() => setSelectedTrade(null)}
                className="p-2 hover:bg-gray-100 rounded-xl"
              >
                <span className="text-2xl text-gray-400">&times;</span>
              </button>
            </div>
            <div className="p-6 space-y-6">
              <div className="p-4 rounded-2xl bg-purple-50 border border-purple-100">
                <div className="flex items-center gap-2 mb-2">
                  <Sparkles className="w-5 h-5 text-purple-600" />
                  <span className="font-semibold text-purple-700">Trade Rationale</span>
                </div>
                <p className="text-purple-800">{selectedTrade.rationale}</p>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div className="p-4 rounded-xl bg-gray-50">
                  <div className="text-sm text-gray-500 mb-1">IV at Trade</div>
                  <div className="text-2xl font-bold text-gray-900">
                    {selectedTrade.iv_at_trade}%
                  </div>
                </div>
                <div className="p-4 rounded-xl bg-gray-50">
                  <div className="text-sm text-gray-500 mb-1">Underlying Price</div>
                  <div className="text-2xl font-bold text-gray-900">
                    {formatCurrency(selectedTrade.underlying_at_trade)}
                  </div>
                </div>
              </div>

              {selectedTrade.action === "CLOSE" && (
                <div className={cn(
                  "p-4 rounded-xl",
                  selectedTrade.pnl >= 0 ? "bg-green-50" : "bg-red-50"
                )}>
                  <div className="text-sm text-gray-500 mb-1">Realized P&L</div>
                  <div className={cn(
                    "text-3xl font-bold",
                    selectedTrade.pnl >= 0 ? "text-green-600" : "text-red-600"
                  )}>
                    {formatCurrency(selectedTrade.pnl)}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
