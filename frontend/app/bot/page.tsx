"use client";

import { useEffect, useState, useCallback } from "react";
import {
  Bot,
  Play,
  Square,
  RefreshCw,
  TrendingUp,
  TrendingDown,
  Activity,
  DollarSign,
  Target,
  AlertCircle,
  CheckCircle,
  Clock,
  BarChart3,
  Zap,
  Settings,
  ArrowUpRight,
  ArrowDownRight,
  Pause,
  ChevronRight,
  Sparkles,
  Bitcoin,
  Building,
} from "lucide-react";
import { cn } from "@/lib/utils";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface MarketStatus {
  is_open: boolean;
  status: string;
  message: string;
  current_time_et: string;
  next_open?: string;
}

interface BotStatus {
  is_running: boolean;
  mode: string;
  asset_class: string;
  active_trading_mode: string;
  market_status: MarketStatus;
  initial_capital: number;
  cash: number;
  total_value: number;
  total_pnl: number;
  total_pnl_pct: number;
  positions_count: number;
  trades_count: number;
  last_scan: string | null;
  scan_interval_seconds: number;
}

interface BotPosition {
  symbol: string;
  asset_class: string;
  quantity: number;
  entry_price: number;
  current_price: number;
  market_value: number;
  unrealized_pnl: number;
  unrealized_pnl_pct: number;
  entry_time: string;
  holding_period: string;
  stop_loss_price: number;
  take_profit_price: number;
}

interface TradeRationale {
  decision: string;
  confidence: number;
  primary_reason: string;
  factors: Record<string, number>;
  signals_summary: string;
  risk_assessment: string;
  expected_return: string;
  expected_holding_period: string;
  stop_loss: string;
  take_profit: string;
}

interface BotTrade {
  id: string;
  timestamp: string;
  asset_class: string;
  symbol: string;
  side: string;
  quantity: number;
  price: number;
  value: number;
  rationale: TradeRationale;
  status: string;
  pnl: number;
}

interface BotPerformance {
  total_return: number;
  cagr: number;
  volatility: number;
  sharpe_ratio: number;
  max_drawdown: number;
  win_rate: number;
  total_trades: number;
  current_value: number;
}

interface CommentaryEntry {
  timestamp: string;
  message: string;
  category: string;
  data: Record<string, any>;
}

export default function BotPage() {
  const [status, setStatus] = useState<BotStatus | null>(null);
  const [positions, setPositions] = useState<BotPosition[]>([]);
  const [trades, setTrades] = useState<BotTrade[]>([]);
  const [performance, setPerformance] = useState<BotPerformance | null>(null);
  const [commentary, setCommentary] = useState<CommentaryEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState(false);
  const [selectedTrade, setSelectedTrade] = useState<BotTrade | null>(null);

  const [capital, setCapital] = useState("10000");
  const [mode, setMode] = useState("balanced");
  const [assetClass, setAssetClass] = useState("both");

  const fetchData = useCallback(async () => {
    try {
      const [statusRes, positionsRes, tradesRes, perfRes, commentaryRes] = await Promise.all([
        fetch(`${API_BASE}/api/bot/status`),
        fetch(`${API_BASE}/api/bot/positions`),
        fetch(`${API_BASE}/api/bot/trades?limit=20`),
        fetch(`${API_BASE}/api/bot/performance`),
        fetch(`${API_BASE}/api/bot/commentary?limit=30`),
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
    } catch (err) {
      console.error("Failed to fetch bot data:", err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    // Fast refresh for real-time updates
    const interval = setInterval(fetchData, 2000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const startBot = async () => {
    setStarting(true);
    try {
      const res = await fetch(
        `${API_BASE}/api/bot/start?capital=${capital}&mode=${mode}&asset_class=${assetClass}`,
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
      await fetch(`${API_BASE}/api/bot/stop`, { method: "POST" });
      await fetchData();
    } catch (err) {
      console.error("Failed to stop bot:", err);
    }
  };

  const triggerScan = async () => {
    try {
      await fetch(`${API_BASE}/api/bot/scan`, { method: "POST" });
      await fetchData();
    } catch (err) {
      console.error("Failed to trigger scan:", err);
    }
  };

  const formatCurrency = (val: number) =>
    new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(val);

  const formatPct = (val: number) => `${val >= 0 ? "+" : ""}${val.toFixed(2)}%`;

  return (
    <div className="ml-64 min-h-screen bg-gray-50/50 p-8">
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-3xl font-bold text-gray-900 tracking-tight">Quant Bot</h1>
          <p className="text-gray-500 mt-1">Autonomous HFT trading with multi-factor signals</p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={triggerScan}
            disabled={!status?.is_running}
            className="px-4 py-2 bg-white rounded-xl text-sm font-medium text-gray-700 hover:bg-gray-50 shadow-sm border border-gray-200 disabled:opacity-50 flex items-center gap-2"
          >
            <Zap className="w-4 h-4" />
            Scan Now
          </button>
          <button
            onClick={fetchData}
            className="p-2 bg-white rounded-xl hover:bg-gray-50 shadow-sm border border-gray-200"
          >
            <RefreshCw className={cn("w-5 h-5 text-gray-500", loading && "animate-spin")} />
          </button>
        </div>
      </div>

      {/* Market Status Banner */}
      {status?.market_status && (
        <div className={cn(
          "mb-6 p-4 rounded-2xl flex items-center justify-between",
          status.market_status.is_open
            ? "bg-green-50 border border-green-100"
            : "bg-orange-50 border border-orange-100"
        )}>
          <div className="flex items-center gap-3">
            <div className={cn(
              "w-3 h-3 rounded-full",
              status.market_status.is_open ? "bg-green-500 animate-pulse" : "bg-orange-500"
            )} />
            <div>
              <span className={cn(
                "font-semibold",
                status.market_status.is_open ? "text-green-700" : "text-orange-700"
              )}>
                {status.market_status.status}
              </span>
              <span className="text-gray-600 ml-2">{status.market_status.message}</span>
            </div>
          </div>
          <div className="flex items-center gap-4 text-sm">
            <div className="flex items-center gap-2">
              {status.market_status.is_open ? (
                <Building className="w-4 h-4 text-green-600" />
              ) : (
                <Bitcoin className="w-4 h-4 text-orange-600" />
              )}
              <span className="font-medium text-gray-700">
                Active: {status.active_trading_mode}
              </span>
            </div>
          </div>
        </div>
      )}

      {/* Stats Grid */}
      <div className="grid grid-cols-4 gap-4 mb-6">
        <div className="bg-white rounded-2xl p-6 shadow-sm">
          <div className="flex items-center justify-between mb-4">
            <span className="text-sm font-medium text-gray-500">Portfolio Value</span>
            <div className={cn(
              "w-10 h-10 rounded-xl flex items-center justify-center",
              "bg-blue-50"
            )}>
              <DollarSign className="w-5 h-5 text-blue-600" />
            </div>
          </div>
          <div className="text-3xl font-bold text-gray-900 tracking-tight">
            {formatCurrency(status?.total_value || 0)}
          </div>
          <div className={cn(
            "text-sm mt-1 flex items-center gap-1",
            (status?.total_pnl || 0) >= 0 ? "text-green-600" : "text-red-600"
          )}>
            {(status?.total_pnl || 0) >= 0 ? (
              <ArrowUpRight className="w-4 h-4" />
            ) : (
              <ArrowDownRight className="w-4 h-4" />
            )}
            {formatPct(status?.total_pnl_pct || 0)} all time
          </div>
        </div>

        <div className="bg-white rounded-2xl p-6 shadow-sm">
          <div className="flex items-center justify-between mb-4">
            <span className="text-sm font-medium text-gray-500">Total P&L</span>
            <div className={cn(
              "w-10 h-10 rounded-xl flex items-center justify-center",
              (status?.total_pnl || 0) >= 0 ? "bg-green-50" : "bg-red-50"
            )}>
              {(status?.total_pnl || 0) >= 0 ? (
                <TrendingUp className="w-5 h-5 text-green-600" />
              ) : (
                <TrendingDown className="w-5 h-5 text-red-600" />
              )}
            </div>
          </div>
          <div className={cn(
            "text-3xl font-bold tracking-tight",
            (status?.total_pnl || 0) >= 0 ? "text-green-600" : "text-red-600"
          )}>
            {formatCurrency(status?.total_pnl || 0)}
          </div>
          <div className="text-sm text-gray-500 mt-1">
            From {formatCurrency(status?.initial_capital || 0)}
          </div>
        </div>

        <div className="bg-white rounded-2xl p-6 shadow-sm">
          <div className="flex items-center justify-between mb-4">
            <span className="text-sm font-medium text-gray-500">Win Rate</span>
            <div className="w-10 h-10 rounded-xl bg-purple-50 flex items-center justify-center">
              <Target className="w-5 h-5 text-purple-600" />
            </div>
          </div>
          <div className="text-3xl font-bold text-gray-900 tracking-tight">
            {performance?.win_rate?.toFixed(1) || 0}%
          </div>
          <div className="text-sm text-gray-500 mt-1">
            {status?.trades_count || 0} total trades
          </div>
        </div>

        <div className="bg-white rounded-2xl p-6 shadow-sm">
          <div className="flex items-center justify-between mb-4">
            <span className="text-sm font-medium text-gray-500">Sharpe Ratio</span>
            <div className="w-10 h-10 rounded-xl bg-orange-50 flex items-center justify-center">
              <BarChart3 className="w-5 h-5 text-orange-600" />
            </div>
          </div>
          <div className="text-3xl font-bold text-gray-900 tracking-tight">
            {performance?.sharpe_ratio?.toFixed(2) || "0.00"}
          </div>
          <div className="text-sm text-gray-500 mt-1">
            Max DD: {performance?.max_drawdown?.toFixed(2) || 0}%
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
                      className="input-field"
                      placeholder="10000"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      Trading Mode
                    </label>
                    <select
                      value={mode}
                      onChange={(e) => setMode(e.target.value)}
                      className="select-field"
                    >
                      <option value="aggressive">Aggressive (HFT)</option>
                      <option value="balanced">Balanced (1-5 Days)</option>
                      <option value="conservative">Conservative</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      Asset Class
                    </label>
                    <select
                      value={assetClass}
                      onChange={(e) => setAssetClass(e.target.value)}
                      className="select-field"
                    >
                      <option value="both">Stocks + Crypto (24/7)</option>
                      <option value="stocks">Stocks Only</option>
                      <option value="crypto">Crypto Only (24/7)</option>
                    </select>
                  </div>
                  <button
                    onClick={startBot}
                    disabled={starting}
                    className="w-full py-3 rounded-xl bg-gray-900 text-white font-semibold hover:bg-gray-800 disabled:opacity-50 flex items-center justify-center gap-2"
                  >
                    <Play className="w-5 h-5" />
                    {starting ? "Starting..." : "Start Trading"}
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
                        <span>Assets:</span>
                        <span className="font-medium capitalize">{status.asset_class}</span>
                      </div>
                      <div className="flex justify-between">
                        <span>Interval:</span>
                        <span className="font-medium">{status.scan_interval_seconds}s</span>
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

          {/* Cash Balance */}
          <div className="bg-white rounded-2xl shadow-sm p-6 mt-4">
            <h3 className="text-sm font-medium text-gray-500 mb-4">Cash Available</h3>
            <div className="text-2xl font-bold text-gray-900">
              {formatCurrency(status?.cash || 0)}
            </div>
            <div className="mt-4 h-2 bg-gray-100 rounded-full overflow-hidden">
              <div
                className="h-full bg-blue-500 rounded-full"
                style={{
                  width: `${((status?.cash || 0) / (status?.total_value || 1)) * 100}%`,
                }}
              />
            </div>
            <div className="flex justify-between text-xs text-gray-500 mt-2">
              <span>Invested</span>
              <span>Cash</span>
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
            <div className="max-h-[300px] overflow-y-auto">
              {commentary.length > 0 ? (
                <div className="divide-y divide-gray-50">
                  {[...commentary].reverse().map((entry, idx) => (
                    <div
                      key={idx}
                      className={cn(
                        "p-3 text-xs",
                        entry.category === "trade" && "bg-blue-50",
                        entry.category === "signal" && "bg-green-50",
                        entry.category === "risk" && "bg-red-50",
                        entry.category === "market" && "bg-orange-50"
                      )}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <span className="text-gray-800 leading-relaxed">{entry.message}</span>
                        <span className="text-gray-400 whitespace-nowrap">
                          {new Date(entry.timestamp).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit', second: '2-digit'})}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="p-6 text-center text-gray-400 text-sm">
                  {status?.is_running ? "Waiting for bot activity..." : "Start the bot to see live commentary"}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Positions & Trades */}
        <div className="col-span-9 space-y-6">
          {/* Active Positions */}
          <div className="bg-white rounded-2xl shadow-sm overflow-hidden">
            <div className="p-6 border-b border-gray-100 flex items-center justify-between">
              <h2 className="font-semibold text-gray-900 flex items-center gap-2">
                <Target className="w-5 h-5 text-gray-400" />
                Active Positions
                <span className="ml-2 px-2 py-0.5 bg-gray-100 text-gray-600 text-sm rounded-full">
                  {positions.length}
                </span>
              </h2>
            </div>
            {positions.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead className="bg-gray-50">
                    <tr>
                      <th className="text-left text-xs font-medium text-gray-500 uppercase tracking-wider py-3 px-6">Asset</th>
                      <th className="text-right text-xs font-medium text-gray-500 uppercase tracking-wider py-3 px-6">Quantity</th>
                      <th className="text-right text-xs font-medium text-gray-500 uppercase tracking-wider py-3 px-6">Entry</th>
                      <th className="text-right text-xs font-medium text-gray-500 uppercase tracking-wider py-3 px-6">Current</th>
                      <th className="text-right text-xs font-medium text-gray-500 uppercase tracking-wider py-3 px-6">P&L</th>
                      <th className="text-right text-xs font-medium text-gray-500 uppercase tracking-wider py-3 px-6">Stop / Target</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {positions.map((pos) => (
                      <tr key={pos.symbol} className="hover:bg-gray-50">
                        <td className="py-4 px-6">
                          <div className="flex items-center gap-3">
                            <div className={cn(
                              "w-10 h-10 rounded-xl flex items-center justify-center",
                              pos.asset_class === "crypto" ? "bg-orange-100" : "bg-blue-100"
                            )}>
                              {pos.asset_class === "crypto" ? (
                                <Bitcoin className="w-5 h-5 text-orange-600" />
                              ) : (
                                <Building className="w-5 h-5 text-blue-600" />
                              )}
                            </div>
                            <div>
                              <div className="font-semibold text-gray-900">{pos.symbol}</div>
                              <div className="text-xs text-gray-500 capitalize">{pos.asset_class}</div>
                            </div>
                          </div>
                        </td>
                        <td className="py-4 px-6 text-right font-mono text-gray-900">
                          {pos.quantity.toFixed(4)}
                        </td>
                        <td className="py-4 px-6 text-right font-mono text-gray-500">
                          {formatCurrency(pos.entry_price)}
                        </td>
                        <td className="py-4 px-6 text-right font-mono text-gray-900">
                          {formatCurrency(pos.current_price)}
                        </td>
                        <td className="py-4 px-6 text-right">
                          <div className={cn(
                            "font-semibold",
                            pos.unrealized_pnl >= 0 ? "text-green-600" : "text-red-600"
                          )}>
                            {formatCurrency(pos.unrealized_pnl)}
                          </div>
                          <div className={cn(
                            "text-xs",
                            pos.unrealized_pnl >= 0 ? "text-green-500" : "text-red-500"
                          )}>
                            {formatPct(pos.unrealized_pnl_pct)}
                          </div>
                        </td>
                        <td className="py-4 px-6 text-right text-sm">
                          <span className="text-red-500">{formatCurrency(pos.stop_loss_price)}</span>
                          <span className="text-gray-400 mx-1">/</span>
                          <span className="text-green-500">{formatCurrency(pos.take_profit_price)}</span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="p-12 text-center">
                <div className="w-16 h-16 rounded-2xl bg-gray-100 flex items-center justify-center mx-auto mb-4">
                  <Target className="w-8 h-8 text-gray-400" />
                </div>
                <h3 className="text-lg font-medium text-gray-900 mb-1">No Active Positions</h3>
                <p className="text-gray-500 text-sm">Start the bot to begin trading automatically</p>
              </div>
            )}
          </div>

          {/* Recent Trades */}
          <div className="bg-white rounded-2xl shadow-sm overflow-hidden">
            <div className="p-6 border-b border-gray-100">
              <h2 className="font-semibold text-gray-900 flex items-center gap-2">
                <Activity className="w-5 h-5 text-gray-400" />
                Recent Trades
              </h2>
            </div>
            {trades.length > 0 ? (
              <div className="divide-y divide-gray-100 max-h-96 overflow-y-auto">
                {trades.map((trade) => (
                  <div
                    key={trade.id}
                    className="p-4 hover:bg-gray-50 cursor-pointer flex items-center justify-between"
                    onClick={() => setSelectedTrade(trade)}
                  >
                    <div className="flex items-center gap-4">
                      <div className={cn(
                        "w-10 h-10 rounded-xl flex items-center justify-center",
                        trade.side === "BUY" ? "bg-green-100" : "bg-red-100"
                      )}>
                        {trade.side === "BUY" ? (
                          <ArrowUpRight className="w-5 h-5 text-green-600" />
                        ) : (
                          <ArrowDownRight className="w-5 h-5 text-red-600" />
                        )}
                      </div>
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="font-semibold text-gray-900">{trade.symbol}</span>
                          <span className={cn(
                            "px-2 py-0.5 text-xs font-medium rounded-full",
                            trade.side === "BUY" ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700"
                          )}>
                            {trade.side}
                          </span>
                        </div>
                        <div className="text-sm text-gray-500 truncate max-w-md">
                          {trade.rationale.primary_reason}
                        </div>
                      </div>
                    </div>
                    <div className="text-right">
                      <div className="font-semibold text-gray-900">{formatCurrency(trade.value)}</div>
                      {trade.pnl !== 0 && (
                        <div className={cn(
                          "text-sm",
                          trade.pnl >= 0 ? "text-green-600" : "text-red-600"
                        )}>
                          {formatCurrency(trade.pnl)}
                        </div>
                      )}
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
            className="bg-white rounded-3xl w-full max-w-xl max-h-[80vh] overflow-y-auto m-4 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="p-6 border-b border-gray-100 flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className={cn(
                  "w-12 h-12 rounded-xl flex items-center justify-center",
                  selectedTrade.side === "BUY" ? "bg-green-100" : "bg-red-100"
                )}>
                  {selectedTrade.side === "BUY" ? (
                    <ArrowUpRight className="w-6 h-6 text-green-600" />
                  ) : (
                    <ArrowDownRight className="w-6 h-6 text-red-600" />
                  )}
                </div>
                <div>
                  <h3 className="text-xl font-bold text-gray-900">{selectedTrade.symbol}</h3>
                  <p className="text-sm text-gray-500">{selectedTrade.side} • {formatCurrency(selectedTrade.value)}</p>
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
              <div className="p-4 rounded-2xl bg-blue-50 border border-blue-100">
                <div className="flex items-center gap-2 mb-2">
                  <Sparkles className="w-5 h-5 text-blue-600" />
                  <span className="font-semibold text-blue-700">AI Rationale</span>
                </div>
                <p className="text-blue-800">{selectedTrade.rationale.primary_reason}</p>
              </div>

              <div>
                <h4 className="text-sm font-medium text-gray-500 mb-3">Factor Scores</h4>
                <div className="space-y-2">
                  {Object.entries(selectedTrade.rationale.factors).map(([key, value]) => (
                    <div key={key} className="flex items-center justify-between">
                      <span className="text-gray-600 capitalize">{key.replace(/_/g, " ")}</span>
                      <div className="flex items-center gap-2">
                        <div className="w-24 h-2 bg-gray-100 rounded-full overflow-hidden">
                          <div
                            className={cn(
                              "h-full rounded-full",
                              value > 0 ? "bg-green-500" : "bg-red-500"
                            )}
                            style={{ width: `${Math.abs(value) * 100}%` }}
                          />
                        </div>
                        <span className={cn(
                          "font-mono text-sm w-12 text-right",
                          value > 0 ? "text-green-600" : "text-red-600"
                        )}>
                          {value > 0 ? "+" : ""}{value.toFixed(2)}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div className="p-4 rounded-xl bg-gray-50">
                  <div className="text-sm text-gray-500 mb-1">Confidence</div>
                  <div className="text-2xl font-bold text-gray-900">
                    {(selectedTrade.rationale.confidence * 100).toFixed(0)}%
                  </div>
                </div>
                <div className="p-4 rounded-xl bg-gray-50">
                  <div className="text-sm text-gray-500 mb-1">Expected Return</div>
                  <div className="text-2xl font-bold text-green-600">
                    {selectedTrade.rationale.expected_return}
                  </div>
                </div>
              </div>

              <div className="p-4 rounded-xl bg-gray-50">
                <div className="text-sm text-gray-500 mb-1">Risk Assessment</div>
                <p className="text-gray-700">{selectedTrade.rationale.risk_assessment}</p>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
