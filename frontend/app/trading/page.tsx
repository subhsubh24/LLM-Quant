"use client";

import { useEffect, useState, useCallback } from "react";
import {
  Play,
  Pause,
  RefreshCw,
  TrendingUp,
  TrendingDown,
  AlertTriangle,
  Target,
  Shield,
  Zap,
  DollarSign,
  BarChart3,
  Clock,
  CheckCircle,
  XCircle,
} from "lucide-react";
import { cn } from "@/lib/utils";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface Signal {
  symbol: string;
  composite_score: number;
  signal_strength: string;
  action: string;
  target_weight: number;
  stop_loss_pct: number;
  take_profit_pct: number;
  momentum_score: number;
  value_score: number;
  quality_score: number;
  expected_return: number;
  confidence: number;
}

interface Position {
  symbol: string;
  quantity: number;
  avg_cost: number;
  current_price: number;
  market_value: number;
  unrealized_pnl: number;
  unrealized_pnl_pct: number;
  weight: number;
}

interface Order {
  id: string;
  symbol: string;
  side: string;
  order_type: string;
  quantity: number;
  status: string;
  limit_price?: number;
  stop_price?: number;
  filled_price?: number;
  created_at: string;
}

interface TradingStatus {
  auto_trading_enabled: boolean;
  portfolio: {
    cash: number;
    total_value: number;
    total_pnl: number;
    total_pnl_pct: number;
    positions: Record<string, Position>;
  };
  performance: {
    total_return: number;
    sharpe_ratio: number;
    max_drawdown: number;
    n_trades: number;
  };
  market_regime: string;
}

export default function TradingPage() {
  const [status, setStatus] = useState<TradingStatus | null>(null);
  const [signals, setSignals] = useState<Signal[]>([]);
  const [orders, setOrders] = useState<Order[]>([]);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [rebalancing, setRebalancing] = useState(false);

  // Order form state
  const [orderSymbol, setOrderSymbol] = useState("");
  const [orderSide, setOrderSide] = useState<"buy" | "sell">("buy");
  const [orderType, setOrderType] = useState<"market" | "limit" | "bracket">("market");
  const [orderQuantity, setOrderQuantity] = useState("");
  const [orderPrice, setOrderPrice] = useState("");
  const [stopLossPct, setStopLossPct] = useState("5");
  const [takeProfitPct, setTakeProfitPct] = useState("10");

  const fetchData = useCallback(async () => {
    try {
      const [statusRes, ordersRes] = await Promise.all([
        fetch(`${API_BASE}/api/trading/status`),
        fetch(`${API_BASE}/api/trading/orders?status=all`),
      ]);

      if (statusRes.ok) {
        const data = await statusRes.json();
        setStatus(data);
      }

      if (ordersRes.ok) {
        const data = await ordersRes.json();
        setOrders(data.orders || []);
      }
    } catch (err) {
      console.error("Failed to fetch trading data:", err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 10000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const generateSignals = async () => {
    setGenerating(true);
    try {
      const res = await fetch(`${API_BASE}/api/signals/generate`);
      if (res.ok) {
        const data = await res.json();
        setSignals(data.top_buys || []);
      }
    } catch (err) {
      console.error("Failed to generate signals:", err);
    } finally {
      setGenerating(false);
    }
  };

  const toggleAutoTrading = async () => {
    const endpoint = status?.auto_trading_enabled ? "disable" : "enable";
    try {
      await fetch(`${API_BASE}/api/trading/${endpoint}`, { method: "POST" });
      fetchData();
    } catch (err) {
      console.error("Failed to toggle auto-trading:", err);
    }
  };

  const triggerRebalance = async () => {
    setRebalancing(true);
    try {
      const res = await fetch(`${API_BASE}/api/trading/rebalance`, { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        alert(`Rebalance complete! ${data.orders_created} orders created.`);
        fetchData();
      }
    } catch (err) {
      console.error("Failed to rebalance:", err);
    } finally {
      setRebalancing(false);
    }
  };

  const submitOrder = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!orderSymbol || !orderQuantity) return;

    try {
      let endpoint = `/api/trading/order/${orderType}`;
      let body: any = {
        symbol: orderSymbol.toUpperCase(),
        side: orderSide,
        quantity: parseFloat(orderQuantity),
      };

      if (orderType === "limit" && orderPrice) {
        body.limit_price = parseFloat(orderPrice);
      }

      if (orderType === "bracket") {
        body.stop_loss_pct = parseFloat(stopLossPct) / 100;
        body.take_profit_pct = parseFloat(takeProfitPct) / 100;
      }

      const res = await fetch(`${API_BASE}${endpoint}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      if (res.ok) {
        setOrderSymbol("");
        setOrderQuantity("");
        setOrderPrice("");
        fetchData();
      }
    } catch (err) {
      console.error("Failed to submit order:", err);
    }
  };

  const executeSignal = async (symbol: string) => {
    try {
      const res = await fetch(`${API_BASE}/api/trading/execute-signal?symbol=${symbol}`, {
        method: "POST",
      });
      if (res.ok) {
        fetchData();
      }
    } catch (err) {
      console.error("Failed to execute signal:", err);
    }
  };

  const cancelOrder = async (orderId: string) => {
    try {
      await fetch(`${API_BASE}/api/trading/order/${orderId}`, { method: "DELETE" });
      fetchData();
    } catch (err) {
      console.error("Failed to cancel order:", err);
    }
  };

  const positions = status?.portfolio?.positions ? Object.values(status.portfolio.positions) : [];

  return (
    <div className="min-h-screen bg-background p-2">
      {/* Header */}
      <header className="terminal-panel mb-2 px-4 py-2 flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Zap className="w-5 h-5 text-bloomberg-orange" />
          <h1 className="text-lg font-bold text-bloomberg-orange font-mono">AUTO TRADER</h1>
          <div className={cn(
            "flex items-center gap-2 px-2 py-0.5 rounded text-xs font-mono",
            status?.auto_trading_enabled ? "bg-positive/20 text-positive" : "bg-muted text-muted-foreground"
          )}>
            {status?.auto_trading_enabled ? <Play className="w-3 h-3" /> : <Pause className="w-3 h-3" />}
            {status?.auto_trading_enabled ? "ACTIVE" : "PAUSED"}
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={toggleAutoTrading}
            className={cn(
              "px-3 py-1.5 rounded text-xs font-mono font-medium",
              status?.auto_trading_enabled
                ? "bg-destructive text-destructive-foreground"
                : "bg-positive text-background"
            )}
          >
            {status?.auto_trading_enabled ? "STOP" : "START"} AUTO-TRADE
          </button>
          <button
            onClick={triggerRebalance}
            disabled={rebalancing}
            className="px-3 py-1.5 rounded bg-primary text-primary-foreground text-xs font-mono"
          >
            {rebalancing ? "REBALANCING..." : "REBALANCE NOW"}
          </button>
        </div>
      </header>

      <div className="grid grid-cols-12 gap-2">
        {/* Portfolio Summary */}
        <div className="col-span-12 lg:col-span-4 terminal-panel p-3">
          <h2 className="text-sm font-semibold text-bloomberg-orange font-mono mb-3">PORTFOLIO</h2>
          <div className="grid grid-cols-2 gap-3">
            <StatBox
              label="Total Value"
              value={`$${(status?.portfolio?.total_value || 100000).toLocaleString()}`}
            />
            <StatBox
              label="Cash"
              value={`$${(status?.portfolio?.cash || 100000).toLocaleString()}`}
            />
            <StatBox
              label="Total P&L"
              value={`$${(status?.portfolio?.total_pnl || 0).toLocaleString()}`}
              positive={(status?.portfolio?.total_pnl || 0) >= 0}
            />
            <StatBox
              label="Return"
              value={`${((status?.portfolio?.total_pnl_pct || 0) * 100).toFixed(2)}%`}
              positive={(status?.portfolio?.total_pnl_pct || 0) >= 0}
            />
          </div>

          <div className="mt-4 pt-3 border-t border-border">
            <h3 className="text-xs text-muted-foreground mb-2">PERFORMANCE</h3>
            <div className="grid grid-cols-2 gap-2 text-xs">
              <div>
                <span className="text-muted-foreground">Sharpe: </span>
                <span className="font-mono">{status?.performance?.sharpe_ratio?.toFixed(2) || "—"}</span>
              </div>
              <div>
                <span className="text-muted-foreground">Max DD: </span>
                <span className="font-mono text-negative">
                  {((status?.performance?.max_drawdown || 0) * 100).toFixed(1)}%
                </span>
              </div>
              <div>
                <span className="text-muted-foreground">Trades: </span>
                <span className="font-mono">{status?.performance?.n_trades || 0}</span>
              </div>
              <div>
                <span className="text-muted-foreground">Regime: </span>
                <span className="font-mono uppercase">{status?.market_regime || "—"}</span>
              </div>
            </div>
          </div>
        </div>

        {/* Order Entry */}
        <div className="col-span-12 lg:col-span-4 terminal-panel p-3">
          <h2 className="text-sm font-semibold text-bloomberg-orange font-mono mb-3">NEW ORDER</h2>
          <form onSubmit={submitOrder} className="space-y-3">
            <div className="flex gap-2">
              <input
                type="text"
                value={orderSymbol}
                onChange={(e) => setOrderSymbol(e.target.value.toUpperCase())}
                placeholder="SYMBOL"
                className="command-input flex-1 text-xs"
              />
              <select
                value={orderSide}
                onChange={(e) => setOrderSide(e.target.value as "buy" | "sell")}
                className="command-input text-xs"
              >
                <option value="buy">BUY</option>
                <option value="sell">SELL</option>
              </select>
            </div>

            <div className="flex gap-2">
              <select
                value={orderType}
                onChange={(e) => setOrderType(e.target.value as any)}
                className="command-input text-xs"
              >
                <option value="market">MARKET</option>
                <option value="limit">LIMIT</option>
                <option value="bracket">BRACKET</option>
              </select>
              <input
                type="number"
                value={orderQuantity}
                onChange={(e) => setOrderQuantity(e.target.value)}
                placeholder="QTY"
                className="command-input flex-1 text-xs"
              />
            </div>

            {orderType === "limit" && (
              <input
                type="number"
                value={orderPrice}
                onChange={(e) => setOrderPrice(e.target.value)}
                placeholder="LIMIT PRICE"
                className="command-input w-full text-xs"
                step="0.01"
              />
            )}

            {orderType === "bracket" && (
              <div className="flex gap-2">
                <input
                  type="number"
                  value={stopLossPct}
                  onChange={(e) => setStopLossPct(e.target.value)}
                  placeholder="SL %"
                  className="command-input flex-1 text-xs"
                />
                <input
                  type="number"
                  value={takeProfitPct}
                  onChange={(e) => setTakeProfitPct(e.target.value)}
                  placeholder="TP %"
                  className="command-input flex-1 text-xs"
                />
              </div>
            )}

            <button
              type="submit"
              className={cn(
                "w-full py-2 rounded text-xs font-mono font-medium",
                orderSide === "buy"
                  ? "bg-positive text-background"
                  : "bg-negative text-white"
              )}
            >
              {orderSide.toUpperCase()} {orderSymbol || "..."}
            </button>
          </form>
        </div>

        {/* Signals */}
        <div className="col-span-12 lg:col-span-4 terminal-panel p-3">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-bloomberg-orange font-mono">SIGNALS</h2>
            <button
              onClick={generateSignals}
              disabled={generating}
              className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
            >
              <RefreshCw className={cn("w-3 h-3", generating && "animate-spin")} />
              Generate
            </button>
          </div>

          <div className="max-h-[250px] overflow-y-auto space-y-1">
            {signals.map((signal) => (
              <div
                key={signal.symbol}
                className="flex items-center justify-between p-2 rounded bg-secondary/30 text-xs"
              >
                <div>
                  <span className="font-mono font-semibold">{signal.symbol}</span>
                  <span className={cn(
                    "ml-2 px-1.5 py-0.5 rounded text-[10px]",
                    signal.action === "BUY" ? "bg-positive/20 text-positive" : "bg-negative/20 text-negative"
                  )}>
                    {signal.action}
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="font-mono">{(signal.composite_score * 100).toFixed(0)}</span>
                  <button
                    onClick={() => executeSignal(signal.symbol)}
                    className="px-2 py-0.5 rounded bg-primary text-primary-foreground text-[10px]"
                  >
                    EXEC
                  </button>
                </div>
              </div>
            ))}
            {signals.length === 0 && (
              <p className="text-xs text-muted-foreground text-center py-4">
                Click Generate to get signals
              </p>
            )}
          </div>
        </div>

        {/* Positions */}
        <div className="col-span-12 lg:col-span-6 terminal-panel">
          <div className="px-3 py-2 border-b border-border">
            <h2 className="text-sm font-semibold text-bloomberg-orange font-mono">POSITIONS</h2>
          </div>
          <div className="max-h-[300px] overflow-y-auto">
            <table className="data-table">
              <thead>
                <tr>
                  <th>SYMBOL</th>
                  <th className="text-right">QTY</th>
                  <th className="text-right">PRICE</th>
                  <th className="text-right">VALUE</th>
                  <th className="text-right">P&L</th>
                  <th className="text-right">%</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((pos) => (
                  <tr key={pos.symbol}>
                    <td className="font-semibold">{pos.symbol}</td>
                    <td className="text-right tabular-nums">{pos.quantity?.toFixed(0)}</td>
                    <td className="text-right tabular-nums">${pos.current_price?.toFixed(2)}</td>
                    <td className="text-right tabular-nums">${pos.market_value?.toFixed(0)}</td>
                    <td className={cn(
                      "text-right tabular-nums",
                      pos.unrealized_pnl >= 0 ? "text-positive" : "text-negative"
                    )}>
                      ${pos.unrealized_pnl?.toFixed(0)}
                    </td>
                    <td className={cn(
                      "text-right tabular-nums",
                      pos.unrealized_pnl_pct >= 0 ? "text-positive" : "text-negative"
                    )}>
                      {(pos.unrealized_pnl_pct * 100)?.toFixed(1)}%
                    </td>
                  </tr>
                ))}
                {positions.length === 0 && (
                  <tr>
                    <td colSpan={6} className="text-center text-muted-foreground py-4">
                      No positions - use Generate Signals then Rebalance
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* Open Orders */}
        <div className="col-span-12 lg:col-span-6 terminal-panel">
          <div className="px-3 py-2 border-b border-border">
            <h2 className="text-sm font-semibold text-bloomberg-orange font-mono">ORDERS</h2>
          </div>
          <div className="max-h-[300px] overflow-y-auto">
            <table className="data-table">
              <thead>
                <tr>
                  <th>SYMBOL</th>
                  <th>SIDE</th>
                  <th>TYPE</th>
                  <th className="text-right">QTY</th>
                  <th>STATUS</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {orders.slice(0, 20).map((order) => (
                  <tr key={order.id}>
                    <td className="font-semibold">{order.symbol}</td>
                    <td className={order.side === "buy" ? "text-positive" : "text-negative"}>
                      {order.side.toUpperCase()}
                    </td>
                    <td>{order.order_type}</td>
                    <td className="text-right tabular-nums">{order.quantity}</td>
                    <td>
                      <span className={cn(
                        "px-1.5 py-0.5 rounded text-[10px]",
                        order.status === "filled" && "bg-positive/20 text-positive",
                        order.status === "open" && "bg-bloomberg-orange/20 text-bloomberg-orange",
                        order.status === "cancelled" && "bg-muted text-muted-foreground"
                      )}>
                        {order.status.toUpperCase()}
                      </span>
                    </td>
                    <td>
                      {(order.status === "open" || order.status === "pending") && (
                        <button
                          onClick={() => cancelOrder(order.id)}
                          className="text-negative hover:text-negative/80"
                        >
                          <XCircle className="w-3 h-3" />
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
                {orders.length === 0 && (
                  <tr>
                    <td colSpan={6} className="text-center text-muted-foreground py-4">
                      No orders yet
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* Footer */}
      <footer className="terminal-panel mt-2 px-4 py-2">
        <p className="text-xs text-muted-foreground text-center">
          PAPER TRADING ONLY | All trades are simulated | Not financial advice
        </p>
      </footer>
    </div>
  );
}

function StatBox({
  label,
  value,
  positive,
}: {
  label: string;
  value: string;
  positive?: boolean;
}) {
  return (
    <div className="p-2 rounded bg-secondary/50">
      <div className="text-[10px] text-muted-foreground">{label}</div>
      <div className={cn(
        "font-mono font-semibold",
        positive === true && "text-positive",
        positive === false && "text-negative"
      )}>
        {value}
      </div>
    </div>
  );
}
