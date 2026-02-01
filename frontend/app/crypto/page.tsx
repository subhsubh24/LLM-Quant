"use client";

import { useEffect, useState, useCallback } from "react";
import {
  TrendingUp,
  TrendingDown,
  Activity,
  RefreshCw,
  DollarSign,
  BarChart3,
  Zap,
  Globe,
  ArrowUpRight,
  ArrowDownRight,
} from "lucide-react";
import { cn } from "@/lib/utils";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface CryptoQuote {
  symbol: string;
  name: string;
  price: number;
  change_24h: number;
  change_percent_24h: number;
  high_24h: number;
  low_24h: number;
  volume_24h: number;
  market_cap: number;
  market_cap_rank: number;
  ath: number;
  ath_change_percent: number;
}

interface CryptoSignal {
  symbol: string;
  name: string;
  price: number;
  change_24h: number;
  action: string;
  signal_score: number;
  volume_24h: number;
  market_cap: number;
}

interface MarketOverview {
  top_cryptos: CryptoQuote[];
  total_market_cap: number;
  btc_dominance: number;
  top_gainers: CryptoQuote[];
  top_losers: CryptoQuote[];
  timestamp: string;
}

export default function CryptoPage() {
  const [overview, setOverview] = useState<MarketOverview | null>(null);
  const [signals, setSignals] = useState<CryptoSignal[]>([]);
  const [selectedCrypto, setSelectedCrypto] = useState<CryptoQuote | null>(null);
  const [loading, setLoading] = useState(true);
  const [orderSymbol, setOrderSymbol] = useState("BTC");
  const [orderSide, setOrderSide] = useState<"buy" | "sell">("buy");
  const [orderQuantity, setOrderQuantity] = useState("0.01");

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [overviewRes, signalsRes] = await Promise.all([
        fetch(`${API_BASE}/api/crypto/overview`),
        fetch(`${API_BASE}/api/crypto/signals`),
      ]);

      if (overviewRes.ok) {
        const data = await overviewRes.json();
        setOverview(data);
        if (data.top_cryptos?.length > 0) {
          setSelectedCrypto(data.top_cryptos[0]);
        }
      }

      if (signalsRes.ok) {
        const data = await signalsRes.json();
        setSignals(data.signals || []);
      }
    } catch (err) {
      console.error("Failed to fetch crypto data:", err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 30000); // Refresh every 30s
    return () => clearInterval(interval);
  }, [fetchData]);

  const placeOrder = async () => {
    try {
      const res = await fetch(
        `${API_BASE}/api/crypto/order?symbol=${orderSymbol}&side=${orderSide}&quantity=${orderQuantity}&order_type=market`,
        { method: "POST" }
      );
      if (res.ok) {
        const data = await res.json();
        alert(`Order placed! ${orderSide.toUpperCase()} ${orderQuantity} ${orderSymbol} @ $${data.current_price}`);
      }
    } catch (err) {
      console.error("Order failed:", err);
    }
  };

  const formatNumber = (num: number, decimals: number = 2) => {
    if (num >= 1e12) return `$${(num / 1e12).toFixed(2)}T`;
    if (num >= 1e9) return `$${(num / 1e9).toFixed(2)}B`;
    if (num >= 1e6) return `$${(num / 1e6).toFixed(2)}M`;
    return `$${num.toFixed(decimals)}`;
  };

  const formatPrice = (price: number) => {
    if (price >= 1000) return `$${price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    if (price >= 1) return `$${price.toFixed(2)}`;
    if (price >= 0.01) return `$${price.toFixed(4)}`;
    return `$${price.toFixed(6)}`;
  };

  return (
    <div className="min-h-screen bg-background p-2">
      {/* Header */}
      <header className="terminal-panel mb-2 px-4 py-2 flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Globe className="w-5 h-5 text-yellow-500" />
          <h1 className="text-lg font-bold text-yellow-500 font-mono">CRYPTO TERMINAL</h1>
          <span className="status-live text-xs px-2 py-0.5 rounded">LIVE</span>
        </div>
        <div className="flex items-center gap-4 text-xs">
          <div>
            <span className="text-muted-foreground">Total MCap: </span>
            <span className="font-mono">{overview ? formatNumber(overview.total_market_cap) : "--"}</span>
          </div>
          <div>
            <span className="text-muted-foreground">BTC Dom: </span>
            <span className="font-mono text-yellow-500">{overview?.btc_dominance || "--"}%</span>
          </div>
          <button
            onClick={fetchData}
            disabled={loading}
            className="p-1.5 rounded hover:bg-secondary"
          >
            <RefreshCw className={cn("w-4 h-4", loading && "animate-spin")} />
          </button>
        </div>
      </header>

      <div className="grid grid-cols-12 gap-2">
        {/* Main Watchlist */}
        <div className="col-span-12 lg:col-span-8 terminal-panel">
          <div className="px-3 py-2 border-b border-border flex items-center justify-between">
            <h2 className="text-sm font-semibold text-yellow-500 font-mono">TOP CRYPTOCURRENCIES</h2>
          </div>
          <div className="overflow-x-auto">
            <table className="data-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Name</th>
                  <th className="text-right">Price</th>
                  <th className="text-right">24h %</th>
                  <th className="text-right">24h High</th>
                  <th className="text-right">24h Low</th>
                  <th className="text-right">Volume (24h)</th>
                  <th className="text-right">Market Cap</th>
                </tr>
              </thead>
              <tbody>
                {overview?.top_cryptos?.map((crypto) => (
                  <tr
                    key={crypto.symbol}
                    className={cn(
                      "cursor-pointer hover:bg-secondary/50",
                      selectedCrypto?.symbol === crypto.symbol && "bg-secondary"
                    )}
                    onClick={() => setSelectedCrypto(crypto)}
                  >
                    <td className="text-muted-foreground">{crypto.market_cap_rank}</td>
                    <td>
                      <div className="flex items-center gap-2">
                        <span className="font-semibold">{crypto.symbol}</span>
                        <span className="text-muted-foreground text-xs">{crypto.name}</span>
                      </div>
                    </td>
                    <td className="text-right font-mono">{formatPrice(crypto.price)}</td>
                    <td className={cn(
                      "text-right font-mono",
                      crypto.change_percent_24h >= 0 ? "text-positive" : "text-negative"
                    )}>
                      <span className="flex items-center justify-end gap-1">
                        {crypto.change_percent_24h >= 0 ? (
                          <ArrowUpRight className="w-3 h-3" />
                        ) : (
                          <ArrowDownRight className="w-3 h-3" />
                        )}
                        {Math.abs(crypto.change_percent_24h).toFixed(2)}%
                      </span>
                    </td>
                    <td className="text-right font-mono text-muted-foreground">{formatPrice(crypto.high_24h)}</td>
                    <td className="text-right font-mono text-muted-foreground">{formatPrice(crypto.low_24h)}</td>
                    <td className="text-right font-mono">{formatNumber(crypto.volume_24h)}</td>
                    <td className="text-right font-mono">{formatNumber(crypto.market_cap)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Right Sidebar */}
        <div className="col-span-12 lg:col-span-4 space-y-2">
          {/* Selected Crypto Detail */}
          {selectedCrypto && (
            <div className="terminal-panel p-3">
              <div className="flex items-center justify-between mb-3">
                <div>
                  <h2 className="text-lg font-bold text-yellow-500">{selectedCrypto.symbol}</h2>
                  <p className="text-xs text-muted-foreground">{selectedCrypto.name}</p>
                </div>
                <div className="text-right">
                  <div className="text-xl font-mono">{formatPrice(selectedCrypto.price)}</div>
                  <div className={cn(
                    "text-sm font-mono",
                    selectedCrypto.change_percent_24h >= 0 ? "text-positive" : "text-negative"
                  )}>
                    {selectedCrypto.change_percent_24h >= 0 ? "+" : ""}
                    {selectedCrypto.change_percent_24h.toFixed(2)}%
                  </div>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-2 text-xs">
                <div className="p-2 rounded bg-secondary/30">
                  <div className="text-muted-foreground">24h High</div>
                  <div className="font-mono">{formatPrice(selectedCrypto.high_24h)}</div>
                </div>
                <div className="p-2 rounded bg-secondary/30">
                  <div className="text-muted-foreground">24h Low</div>
                  <div className="font-mono">{formatPrice(selectedCrypto.low_24h)}</div>
                </div>
                <div className="p-2 rounded bg-secondary/30">
                  <div className="text-muted-foreground">All-Time High</div>
                  <div className="font-mono">{formatPrice(selectedCrypto.ath)}</div>
                </div>
                <div className="p-2 rounded bg-secondary/30">
                  <div className="text-muted-foreground">From ATH</div>
                  <div className="font-mono text-negative">{selectedCrypto.ath_change_percent.toFixed(1)}%</div>
                </div>
              </div>
            </div>
          )}

          {/* Quick Order */}
          <div className="terminal-panel p-3">
            <h2 className="text-sm font-semibold text-yellow-500 font-mono mb-3">QUICK ORDER</h2>
            <div className="space-y-2">
              <div className="grid grid-cols-2 gap-2">
                <button
                  onClick={() => setOrderSide("buy")}
                  className={cn(
                    "py-2 rounded font-mono text-sm",
                    orderSide === "buy"
                      ? "bg-positive text-white"
                      : "bg-secondary text-muted-foreground"
                  )}
                >
                  BUY
                </button>
                <button
                  onClick={() => setOrderSide("sell")}
                  className={cn(
                    "py-2 rounded font-mono text-sm",
                    orderSide === "sell"
                      ? "bg-negative text-white"
                      : "bg-secondary text-muted-foreground"
                  )}
                >
                  SELL
                </button>
              </div>
              <select
                value={orderSymbol}
                onChange={(e) => setOrderSymbol(e.target.value)}
                className="command-input w-full"
              >
                {overview?.top_cryptos?.map((c) => (
                  <option key={c.symbol} value={c.symbol}>
                    {c.symbol} - {c.name}
                  </option>
                ))}
              </select>
              <input
                type="number"
                value={orderQuantity}
                onChange={(e) => setOrderQuantity(e.target.value)}
                className="command-input w-full"
                placeholder="Quantity"
                step="0.001"
              />
              <button
                onClick={placeOrder}
                className={cn(
                  "w-full py-2 rounded font-mono text-sm text-white",
                  orderSide === "buy" ? "bg-positive" : "bg-negative"
                )}
              >
                {orderSide === "buy" ? "BUY" : "SELL"} {orderSymbol}
              </button>
            </div>
            <p className="text-xs text-muted-foreground mt-2 text-center">Paper trading only</p>
          </div>

          {/* Trading Signals */}
          <div className="terminal-panel p-3">
            <h2 className="text-sm font-semibold text-yellow-500 font-mono mb-3">
              <Zap className="w-4 h-4 inline mr-1" />
              SIGNALS
            </h2>
            <div className="space-y-1 max-h-[200px] overflow-y-auto">
              {signals.slice(0, 8).map((signal) => (
                <div
                  key={signal.symbol}
                  className="flex items-center justify-between p-2 rounded bg-secondary/30 text-xs"
                >
                  <div>
                    <span className="font-semibold">{signal.symbol}</span>
                    <span className={cn(
                      "ml-2",
                      signal.change_24h >= 0 ? "text-positive" : "text-negative"
                    )}>
                      {signal.change_24h >= 0 ? "+" : ""}{signal.change_24h.toFixed(1)}%
                    </span>
                  </div>
                  <span className={cn(
                    "px-2 py-0.5 rounded text-xs font-mono",
                    signal.action.includes("BUY") && "bg-positive/20 text-positive",
                    signal.action.includes("SELL") && "bg-negative/20 text-negative",
                    signal.action === "HOLD" && "bg-secondary text-muted-foreground"
                  )}>
                    {signal.action}
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* Gainers & Losers */}
          <div className="terminal-panel p-3">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <h3 className="text-xs font-semibold text-positive mb-2">TOP GAINERS</h3>
                {overview?.top_gainers?.slice(0, 3).map((c) => (
                  <div key={c.symbol} className="flex justify-between text-xs py-1">
                    <span>{c.symbol}</span>
                    <span className="text-positive font-mono">+{c.change_percent_24h.toFixed(1)}%</span>
                  </div>
                ))}
              </div>
              <div>
                <h3 className="text-xs font-semibold text-negative mb-2">TOP LOSERS</h3>
                {overview?.top_losers?.slice(0, 3).map((c) => (
                  <div key={c.symbol} className="flex justify-between text-xs py-1">
                    <span>{c.symbol}</span>
                    <span className="text-negative font-mono">{c.change_percent_24h.toFixed(1)}%</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Footer */}
      <footer className="terminal-panel mt-2 px-4 py-2">
        <p className="text-xs text-muted-foreground text-center">
          PAPER TRADING ONLY | Cryptocurrency is highly volatile | Data from CoinGecko
        </p>
      </footer>
    </div>
  );
}
