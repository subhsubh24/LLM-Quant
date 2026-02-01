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

export default function BotPage() {
  const [status, setStatus] = useState<BotStatus | null>(null);
  const [positions, setPositions] = useState<BotPosition[]>([]);
  const [trades, setTrades] = useState<BotTrade[]>([]);
  const [performance, setPerformance] = useState<BotPerformance | null>(null);
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState(false);
  const [selectedTrade, setSelectedTrade] = useState<BotTrade | null>(null);

  // Config state
  const [capital, setCapital] = useState("10000");
  const [mode, setMode] = useState("balanced");
  const [assetClass, setAssetClass] = useState("both");

  const fetchData = useCallback(async () => {
    try {
      const [statusRes, positionsRes, tradesRes, perfRes] = await Promise.all([
        fetch(`${API_BASE}/api/bot/status`),
        fetch(`${API_BASE}/api/bot/positions`),
        fetch(`${API_BASE}/api/bot/trades?limit=20`),
        fetch(`${API_BASE}/api/bot/performance`),
      ]);

      if (statusRes.ok) {
        setStatus(await statusRes.json());
      }
      if (positionsRes.ok) {
        const data = await positionsRes.json();
        setPositions(data.positions || []);
      }
      if (tradesRes.ok) {
        const data = await tradesRes.json();
        setTrades(data.trades || []);
      }
      if (perfRes.ok) {
        setPerformance(await perfRes.json());
      }
    } catch (err) {
      console.error("Failed to fetch bot data:", err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 5000); // Refresh every 5s
    return () => clearInterval(interval);
  }, [fetchData]);

  const startBot = async () => {
    setStarting(true);
    try {
      const res = await fetch(
        `${API_BASE}/api/bot/start?capital=${capital}&mode=${mode}&asset_class=${assetClass}`,
        { method: "POST" }
      );
      if (res.ok) {
        await fetchData();
      }
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
    `$${val.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

  const formatPct = (val: number) =>
    `${val >= 0 ? "+" : ""}${val.toFixed(2)}%`;

  return (
    <div className="min-h-screen bg-background p-2">
      {/* Header */}
      <header className="terminal-panel mb-2 px-4 py-2 flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Bot className="w-5 h-5 text-bloomberg-orange" />
          <h1 className="text-lg font-bold text-bloomberg-orange font-mono">
            QUANT BOT
          </h1>
          <span
            className={cn(
              "text-xs px-2 py-0.5 rounded font-mono",
              status?.is_running
                ? "bg-positive/20 text-positive"
                : "bg-muted text-muted-foreground"
            )}
          >
            {status?.is_running ? "RUNNING" : "STOPPED"}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={triggerScan}
            disabled={!status?.is_running}
            className="px-3 py-1.5 rounded bg-secondary text-sm font-mono hover:bg-secondary/80 disabled:opacity-50"
          >
            <Zap className="w-4 h-4 inline mr-1" />
            SCAN NOW
          </button>
          <button
            onClick={fetchData}
            className="p-1.5 rounded hover:bg-secondary"
          >
            <RefreshCw className={cn("w-4 h-4", loading && "animate-spin")} />
          </button>
        </div>
      </header>

      <div className="grid grid-cols-12 gap-2">
        {/* Control Panel */}
        <div className="col-span-12 lg:col-span-3 space-y-2">
          {/* Start/Stop Controls */}
          <div className="terminal-panel p-3">
            <h2 className="text-sm font-semibold text-bloomberg-orange font-mono mb-3">
              <Settings className="w-4 h-4 inline mr-1" />
              BOT CONTROLS
            </h2>

            {!status?.is_running ? (
              <div className="space-y-3">
                <div>
                  <label className="text-xs text-muted-foreground block mb-1">
                    Starting Capital
                  </label>
                  <input
                    type="number"
                    value={capital}
                    onChange={(e) => setCapital(e.target.value)}
                    className="command-input w-full"
                    placeholder="10000"
                  />
                </div>
                <div>
                  <label className="text-xs text-muted-foreground block mb-1">
                    Trading Mode
                  </label>
                  <select
                    value={mode}
                    onChange={(e) => setMode(e.target.value)}
                    className="command-input w-full"
                  >
                    <option value="aggressive">Aggressive (Day Trading)</option>
                    <option value="balanced">Balanced (1-5 Days)</option>
                    <option value="conservative">Conservative (1-4 Weeks)</option>
                  </select>
                </div>
                <div>
                  <label className="text-xs text-muted-foreground block mb-1">
                    Asset Class
                  </label>
                  <select
                    value={assetClass}
                    onChange={(e) => setAssetClass(e.target.value)}
                    className="command-input w-full"
                  >
                    <option value="both">Stocks & Crypto</option>
                    <option value="stocks">Stocks Only</option>
                    <option value="crypto">Crypto Only</option>
                  </select>
                </div>
                <button
                  onClick={startBot}
                  disabled={starting}
                  className="w-full py-2 rounded bg-positive text-white font-mono text-sm hover:bg-positive/90 disabled:opacity-50"
                >
                  <Play className="w-4 h-4 inline mr-1" />
                  {starting ? "STARTING..." : "START BOT"}
                </button>
              </div>
            ) : (
              <div className="space-y-3">
                <div className="p-2 rounded bg-secondary/30 text-xs">
                  <div className="flex justify-between mb-1">
                    <span className="text-muted-foreground">Mode:</span>
                    <span className="font-mono uppercase">{status.mode}</span>
                  </div>
                  <div className="flex justify-between mb-1">
                    <span className="text-muted-foreground">Assets:</span>
                    <span className="font-mono uppercase">{status.asset_class}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Scan Interval:</span>
                    <span className="font-mono">{status.scan_interval_seconds}s</span>
                  </div>
                </div>
                <button
                  onClick={stopBot}
                  className="w-full py-2 rounded bg-negative text-white font-mono text-sm hover:bg-negative/90"
                >
                  <Square className="w-4 h-4 inline mr-1" />
                  STOP BOT
                </button>
              </div>
            )}
          </div>

          {/* Portfolio Summary */}
          <div className="terminal-panel p-3">
            <h2 className="text-sm font-semibold text-bloomberg-orange font-mono mb-3">
              <DollarSign className="w-4 h-4 inline mr-1" />
              PORTFOLIO
            </h2>
            <div className="space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-muted-foreground">Initial:</span>
                <span className="font-mono">{formatCurrency(status?.initial_capital || 0)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Current:</span>
                <span className="font-mono">{formatCurrency(status?.total_value || 0)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Cash:</span>
                <span className="font-mono">{formatCurrency(status?.cash || 0)}</span>
              </div>
              <div className="border-t border-border pt-2">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">P&L:</span>
                  <span
                    className={cn(
                      "font-mono",
                      (status?.total_pnl || 0) >= 0 ? "text-positive" : "text-negative"
                    )}
                  >
                    {formatCurrency(status?.total_pnl || 0)} ({formatPct(status?.total_pnl_pct || 0)})
                  </span>
                </div>
              </div>
            </div>
          </div>

          {/* Performance Metrics */}
          {performance && !performance.error && (
            <div className="terminal-panel p-3">
              <h2 className="text-sm font-semibold text-bloomberg-orange font-mono mb-3">
                <BarChart3 className="w-4 h-4 inline mr-1" />
                PERFORMANCE
              </h2>
              <div className="grid grid-cols-2 gap-2 text-xs">
                <div className="p-2 rounded bg-secondary/30">
                  <div className="text-muted-foreground">Return</div>
                  <div
                    className={cn(
                      "font-mono text-sm",
                      performance.total_return >= 0 ? "text-positive" : "text-negative"
                    )}
                  >
                    {formatPct(performance.total_return)}
                  </div>
                </div>
                <div className="p-2 rounded bg-secondary/30">
                  <div className="text-muted-foreground">Sharpe</div>
                  <div className="font-mono text-sm">{performance.sharpe_ratio.toFixed(2)}</div>
                </div>
                <div className="p-2 rounded bg-secondary/30">
                  <div className="text-muted-foreground">Win Rate</div>
                  <div className="font-mono text-sm">{performance.win_rate.toFixed(1)}%</div>
                </div>
                <div className="p-2 rounded bg-secondary/30">
                  <div className="text-muted-foreground">Max DD</div>
                  <div className="font-mono text-sm text-negative">
                    {performance.max_drawdown.toFixed(2)}%
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Main Content */}
        <div className="col-span-12 lg:col-span-9 space-y-2">
          {/* Positions */}
          <div className="terminal-panel">
            <div className="px-3 py-2 border-b border-border flex items-center justify-between">
              <h2 className="text-sm font-semibold text-bloomberg-orange font-mono">
                <Target className="w-4 h-4 inline mr-1" />
                ACTIVE POSITIONS ({positions.length})
              </h2>
            </div>
            <div className="overflow-x-auto">
              {positions.length > 0 ? (
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Symbol</th>
                      <th>Type</th>
                      <th className="text-right">Qty</th>
                      <th className="text-right">Entry</th>
                      <th className="text-right">Current</th>
                      <th className="text-right">P&L</th>
                      <th className="text-right">Stop</th>
                      <th className="text-right">Target</th>
                      <th>Holding</th>
                    </tr>
                  </thead>
                  <tbody>
                    {positions.map((pos) => (
                      <tr key={pos.symbol}>
                        <td className="font-semibold">{pos.symbol}</td>
                        <td>
                          <span
                            className={cn(
                              "text-xs px-1.5 py-0.5 rounded",
                              pos.asset_class === "crypto"
                                ? "bg-yellow-500/20 text-yellow-500"
                                : "bg-blue-500/20 text-blue-500"
                            )}
                          >
                            {pos.asset_class.toUpperCase()}
                          </span>
                        </td>
                        <td className="text-right font-mono">{pos.quantity.toFixed(4)}</td>
                        <td className="text-right font-mono">${pos.entry_price.toFixed(2)}</td>
                        <td className="text-right font-mono">${pos.current_price.toFixed(2)}</td>
                        <td
                          className={cn(
                            "text-right font-mono",
                            pos.unrealized_pnl >= 0 ? "text-positive" : "text-negative"
                          )}
                        >
                          {formatCurrency(pos.unrealized_pnl)}
                          <br />
                          <span className="text-xs">{formatPct(pos.unrealized_pnl_pct)}</span>
                        </td>
                        <td className="text-right font-mono text-negative">
                          ${pos.stop_loss_price.toFixed(2)}
                        </td>
                        <td className="text-right font-mono text-positive">
                          ${pos.take_profit_price.toFixed(2)}
                        </td>
                        <td className="text-xs text-muted-foreground">{pos.holding_period}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <div className="p-8 text-center text-muted-foreground">
                  No active positions
                </div>
              )}
            </div>
          </div>

          {/* Recent Trades */}
          <div className="terminal-panel">
            <div className="px-3 py-2 border-b border-border">
              <h2 className="text-sm font-semibold text-bloomberg-orange font-mono">
                <Activity className="w-4 h-4 inline mr-1" />
                RECENT TRADES
              </h2>
            </div>
            <div className="overflow-x-auto max-h-[400px]">
              {trades.length > 0 ? (
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Time</th>
                      <th>Symbol</th>
                      <th>Side</th>
                      <th className="text-right">Qty</th>
                      <th className="text-right">Price</th>
                      <th className="text-right">Value</th>
                      <th className="text-right">P&L</th>
                      <th>Reason</th>
                      <th>Confidence</th>
                    </tr>
                  </thead>
                  <tbody>
                    {trades.map((trade) => (
                      <tr
                        key={trade.id}
                        className="cursor-pointer hover:bg-secondary/50"
                        onClick={() => setSelectedTrade(trade)}
                      >
                        <td className="text-xs text-muted-foreground">
                          {new Date(trade.timestamp).toLocaleTimeString()}
                        </td>
                        <td className="font-semibold">{trade.symbol}</td>
                        <td>
                          <span
                            className={cn(
                              "text-xs px-1.5 py-0.5 rounded font-mono",
                              trade.side === "BUY"
                                ? "bg-positive/20 text-positive"
                                : "bg-negative/20 text-negative"
                            )}
                          >
                            {trade.side}
                          </span>
                        </td>
                        <td className="text-right font-mono">{trade.quantity.toFixed(4)}</td>
                        <td className="text-right font-mono">${trade.price.toFixed(2)}</td>
                        <td className="text-right font-mono">${trade.value.toFixed(2)}</td>
                        <td
                          className={cn(
                            "text-right font-mono",
                            trade.pnl >= 0 ? "text-positive" : "text-negative"
                          )}
                        >
                          {trade.pnl !== 0 ? formatCurrency(trade.pnl) : "-"}
                        </td>
                        <td className="text-xs max-w-[200px] truncate">
                          {trade.rationale.primary_reason}
                        </td>
                        <td>
                          <div className="w-16 h-2 bg-secondary rounded overflow-hidden">
                            <div
                              className="h-full bg-bloomberg-orange"
                              style={{ width: `${trade.rationale.confidence * 100}%` }}
                            />
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <div className="p-8 text-center text-muted-foreground">
                  No trades yet
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Trade Detail Modal */}
      {selectedTrade && (
        <div
          className="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
          onClick={() => setSelectedTrade(null)}
        >
          <div
            className="terminal-panel w-full max-w-2xl max-h-[80vh] overflow-y-auto m-4"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="px-4 py-3 border-b border-border flex items-center justify-between">
              <h3 className="text-lg font-bold text-bloomberg-orange font-mono">
                TRADE RATIONALE
              </h3>
              <button
                onClick={() => setSelectedTrade(null)}
                className="text-muted-foreground hover:text-foreground"
              >
                &times;
              </button>
            </div>
            <div className="p-4 space-y-4">
              {/* Trade Summary */}
              <div className="grid grid-cols-3 gap-3 text-sm">
                <div className="p-2 rounded bg-secondary/30">
                  <div className="text-muted-foreground text-xs">Symbol</div>
                  <div className="font-mono font-bold">{selectedTrade.symbol}</div>
                </div>
                <div className="p-2 rounded bg-secondary/30">
                  <div className="text-muted-foreground text-xs">Action</div>
                  <div
                    className={cn(
                      "font-mono font-bold",
                      selectedTrade.side === "BUY" ? "text-positive" : "text-negative"
                    )}
                  >
                    {selectedTrade.side}
                  </div>
                </div>
                <div className="p-2 rounded bg-secondary/30">
                  <div className="text-muted-foreground text-xs">Value</div>
                  <div className="font-mono">${selectedTrade.value.toFixed(2)}</div>
                </div>
              </div>

              {/* Primary Reason */}
              <div className="p-3 rounded bg-bloomberg-orange/10 border border-bloomberg-orange/30">
                <div className="text-xs text-bloomberg-orange mb-1">PRIMARY REASON</div>
                <div className="font-medium">{selectedTrade.rationale.primary_reason}</div>
              </div>

              {/* Factors */}
              <div>
                <div className="text-xs text-muted-foreground mb-2">FACTOR SCORES</div>
                <div className="grid grid-cols-2 gap-2">
                  {Object.entries(selectedTrade.rationale.factors).map(([key, value]) => (
                    <div key={key} className="flex items-center gap-2 text-sm">
                      <span className="text-muted-foreground capitalize">
                        {key.replace(/_/g, " ")}:
                      </span>
                      <span
                        className={cn(
                          "font-mono",
                          value > 0 ? "text-positive" : value < 0 ? "text-negative" : ""
                        )}
                      >
                        {value > 0 ? "+" : ""}
                        {value.toFixed(3)}
                      </span>
                    </div>
                  ))}
                </div>
              </div>

              {/* Signal Summary */}
              <div className="p-2 rounded bg-secondary/30 text-sm">
                <div className="text-xs text-muted-foreground mb-1">SIGNALS</div>
                <div className="font-mono">{selectedTrade.rationale.signals_summary}</div>
              </div>

              {/* Risk */}
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div className="p-2 rounded bg-secondary/30">
                  <div className="text-xs text-muted-foreground mb-1">RISK ASSESSMENT</div>
                  <div>{selectedTrade.rationale.risk_assessment}</div>
                </div>
                <div className="p-2 rounded bg-secondary/30">
                  <div className="text-xs text-muted-foreground mb-1">EXPECTED</div>
                  <div>Return: {selectedTrade.rationale.expected_return}</div>
                  <div>Period: {selectedTrade.rationale.expected_holding_period}</div>
                </div>
              </div>

              {/* Confidence Bar */}
              <div>
                <div className="flex justify-between text-xs mb-1">
                  <span className="text-muted-foreground">CONFIDENCE</span>
                  <span className="font-mono">
                    {(selectedTrade.rationale.confidence * 100).toFixed(0)}%
                  </span>
                </div>
                <div className="w-full h-3 bg-secondary rounded overflow-hidden">
                  <div
                    className="h-full bg-gradient-to-r from-negative via-yellow-500 to-positive"
                    style={{ width: `${selectedTrade.rationale.confidence * 100}%` }}
                  />
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Footer */}
      <footer className="terminal-panel mt-2 px-4 py-2">
        <p className="text-xs text-muted-foreground text-center">
          AUTONOMOUS PAPER TRADING | Renaissance Technologies-Style Multi-Factor Signals | NOT
          FINANCIAL ADVICE
        </p>
      </footer>
    </div>
  );
}
