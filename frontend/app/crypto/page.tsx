"use client";

import { useEffect, useState, useCallback } from "react";
import {
  TrendingUp,
  TrendingDown,
  Activity,
  RefreshCw,
  Zap,
  Globe,
  ArrowUpRight,
  ArrowDownRight,
  Bitcoin,
  Sparkles,
  ShoppingCart,
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
        if (data.top_cryptos?.length > 0 && !selectedCrypto) {
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
  }, [selectedCrypto]);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 30000);
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

  const formatNumber = (num: number) => {
    if (num >= 1e12) return `$${(num / 1e12).toFixed(2)}T`;
    if (num >= 1e9) return `$${(num / 1e9).toFixed(2)}B`;
    if (num >= 1e6) return `$${(num / 1e6).toFixed(2)}M`;
    return `$${num.toFixed(2)}`;
  };

  const formatPrice = (price: number) => {
    if (price >= 1000) return `$${price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    if (price >= 1) return `$${price.toFixed(2)}`;
    if (price >= 0.01) return `$${price.toFixed(4)}`;
    return `$${price.toFixed(6)}`;
  };

  return (
    <div className="min-h-screen bg-gray-50/50 p-8">
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-3xl font-bold text-gray-900 tracking-tight">Cryptocurrency</h1>
          <p className="text-gray-500 mt-1">24/7 real-time crypto market data and trading</p>
        </div>
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-3 bg-white px-4 py-2.5 rounded-xl border border-gray-200">
            <div className="flex items-center gap-2">
              <Globe className="w-4 h-4 text-gray-400" />
              <span className="text-sm text-gray-600">Total MCap:</span>
              <span className="font-semibold text-gray-900">{overview ? formatNumber(overview.total_market_cap) : "--"}</span>
            </div>
            <div className="w-px h-4 bg-gray-200" />
            <div className="flex items-center gap-2">
              <Bitcoin className="w-4 h-4 text-orange-500" />
              <span className="text-sm text-gray-600">BTC:</span>
              <span className="font-semibold text-orange-600">{overview?.btc_dominance || "--"}%</span>
            </div>
          </div>
          <button
            onClick={fetchData}
            className="p-2.5 bg-white rounded-xl hover:bg-gray-50 border border-gray-200"
          >
            <RefreshCw className={cn("w-5 h-5 text-gray-500", loading && "animate-spin")} />
          </button>
        </div>
      </div>

      {/* 24/7 Trading Banner */}
      <div className="mb-6 p-4 rounded-2xl bg-gradient-to-r from-orange-50 to-yellow-50 border border-orange-100 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-orange-100 flex items-center justify-center">
            <Bitcoin className="w-5 h-5 text-orange-600" />
          </div>
          <div>
            <span className="font-semibold text-orange-700">Crypto Markets</span>
            <div className="flex items-center gap-2 text-sm text-orange-600">
              <span className="flex items-center gap-1">
                <span className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
                LIVE
              </span>
              <span>•</span>
              <span>24/7 Trading Available</span>
            </div>
          </div>
        </div>
        <span className="px-3 py-1.5 bg-orange-100 text-orange-700 text-sm font-medium rounded-full">
          Paper Trading
        </span>
      </div>

      <div className="grid grid-cols-12 gap-6">
        {/* Main Crypto List */}
        <div className="col-span-8 bg-white rounded-2xl shadow-sm overflow-hidden">
          <div className="p-6 border-b border-gray-100 flex items-center justify-between">
            <h2 className="font-semibold text-gray-900 flex items-center gap-2">
              <Activity className="w-5 h-5 text-gray-400" />
              Top Cryptocurrencies
            </h2>
            <span className="text-sm text-gray-500">{overview?.top_cryptos?.length || 0} coins</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="bg-gray-50">
                <tr>
                  <th className="text-left text-xs font-medium text-gray-500 uppercase tracking-wider py-3 px-6">#</th>
                  <th className="text-left text-xs font-medium text-gray-500 uppercase tracking-wider py-3 px-6">Name</th>
                  <th className="text-right text-xs font-medium text-gray-500 uppercase tracking-wider py-3 px-6">Price</th>
                  <th className="text-right text-xs font-medium text-gray-500 uppercase tracking-wider py-3 px-6">24h Change</th>
                  <th className="text-right text-xs font-medium text-gray-500 uppercase tracking-wider py-3 px-6">24h High</th>
                  <th className="text-right text-xs font-medium text-gray-500 uppercase tracking-wider py-3 px-6">24h Low</th>
                  <th className="text-right text-xs font-medium text-gray-500 uppercase tracking-wider py-3 px-6">Market Cap</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {overview?.top_cryptos?.map((crypto) => (
                  <tr
                    key={crypto.symbol}
                    className={cn(
                      "hover:bg-gray-50 cursor-pointer transition-colors",
                      selectedCrypto?.symbol === crypto.symbol && "bg-blue-50"
                    )}
                    onClick={() => setSelectedCrypto(crypto)}
                  >
                    <td className="py-4 px-6 text-gray-500 text-sm">{crypto.market_cap_rank}</td>
                    <td className="py-4 px-6">
                      <div className="flex items-center gap-3">
                        <div className="w-10 h-10 rounded-xl bg-orange-100 flex items-center justify-center">
                          <Bitcoin className="w-5 h-5 text-orange-600" />
                        </div>
                        <div>
                          <div className="font-semibold text-gray-900">{crypto.symbol}</div>
                          <div className="text-xs text-gray-500">{crypto.name}</div>
                        </div>
                      </div>
                    </td>
                    <td className="py-4 px-6 text-right font-mono text-gray-900 font-medium">
                      {formatPrice(crypto.price)}
                    </td>
                    <td className="py-4 px-6 text-right">
                      <span className={cn(
                        "inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-sm font-medium",
                        crypto.change_percent_24h >= 0 ? "bg-green-50 text-green-700" : "bg-red-50 text-red-700"
                      )}>
                        {crypto.change_percent_24h >= 0 ? (
                          <ArrowUpRight className="w-3 h-3" />
                        ) : (
                          <ArrowDownRight className="w-3 h-3" />
                        )}
                        {Math.abs(crypto.change_percent_24h).toFixed(2)}%
                      </span>
                    </td>
                    <td className="py-4 px-6 text-right font-mono text-gray-500 text-sm">
                      {formatPrice(crypto.high_24h)}
                    </td>
                    <td className="py-4 px-6 text-right font-mono text-gray-500 text-sm">
                      {formatPrice(crypto.low_24h)}
                    </td>
                    <td className="py-4 px-6 text-right font-mono text-gray-900">
                      {formatNumber(crypto.market_cap)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Right Sidebar */}
        <div className="col-span-4 space-y-6">
          {/* Selected Crypto Detail */}
          {selectedCrypto && (
            <div className="bg-white rounded-2xl shadow-sm overflow-hidden">
              <div className="p-6 bg-gradient-to-br from-orange-50 to-yellow-50">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className="w-14 h-14 rounded-2xl bg-orange-100 flex items-center justify-center shadow-lg shadow-orange-200/50">
                      <Bitcoin className="w-7 h-7 text-orange-600" />
                    </div>
                    <div>
                      <h3 className="text-xl font-bold text-gray-900">{selectedCrypto.symbol}</h3>
                      <p className="text-sm text-gray-500">{selectedCrypto.name}</p>
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="text-2xl font-bold text-gray-900">{formatPrice(selectedCrypto.price)}</div>
                    <div className={cn(
                      "flex items-center justify-end gap-1 text-sm font-medium",
                      selectedCrypto.change_percent_24h >= 0 ? "text-green-600" : "text-red-600"
                    )}>
                      {selectedCrypto.change_percent_24h >= 0 ? (
                        <ArrowUpRight className="w-4 h-4" />
                      ) : (
                        <ArrowDownRight className="w-4 h-4" />
                      )}
                      {selectedCrypto.change_percent_24h >= 0 ? "+" : ""}
                      {selectedCrypto.change_percent_24h.toFixed(2)}%
                    </div>
                  </div>
                </div>
              </div>
              <div className="p-6">
                <div className="grid grid-cols-2 gap-4">
                  <div className="p-4 rounded-xl bg-gray-50">
                    <div className="text-sm text-gray-500 mb-1">24h High</div>
                    <div className="font-semibold text-gray-900">{formatPrice(selectedCrypto.high_24h)}</div>
                  </div>
                  <div className="p-4 rounded-xl bg-gray-50">
                    <div className="text-sm text-gray-500 mb-1">24h Low</div>
                    <div className="font-semibold text-gray-900">{formatPrice(selectedCrypto.low_24h)}</div>
                  </div>
                  <div className="p-4 rounded-xl bg-gray-50">
                    <div className="text-sm text-gray-500 mb-1">All-Time High</div>
                    <div className="font-semibold text-gray-900">{formatPrice(selectedCrypto.ath)}</div>
                  </div>
                  <div className="p-4 rounded-xl bg-gray-50">
                    <div className="text-sm text-gray-500 mb-1">From ATH</div>
                    <div className="font-semibold text-red-600">{selectedCrypto.ath_change_percent.toFixed(1)}%</div>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Quick Order */}
          <div className="bg-white rounded-2xl shadow-sm overflow-hidden">
            <div className="p-6 border-b border-gray-100">
              <h3 className="font-semibold text-gray-900 flex items-center gap-2">
                <ShoppingCart className="w-5 h-5 text-gray-400" />
                Quick Order
              </h3>
            </div>
            <div className="p-6 space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <button
                  onClick={() => setOrderSide("buy")}
                  className={cn(
                    "py-3 rounded-xl font-semibold transition-all",
                    orderSide === "buy"
                      ? "bg-green-500 text-white shadow-lg shadow-green-500/30"
                      : "bg-gray-100 text-gray-600 hover:bg-gray-200"
                  )}
                >
                  Buy
                </button>
                <button
                  onClick={() => setOrderSide("sell")}
                  className={cn(
                    "py-3 rounded-xl font-semibold transition-all",
                    orderSide === "sell"
                      ? "bg-red-500 text-white shadow-lg shadow-red-500/30"
                      : "bg-gray-100 text-gray-600 hover:bg-gray-200"
                  )}
                >
                  Sell
                </button>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">Asset</label>
                <select
                  value={orderSymbol}
                  onChange={(e) => setOrderSymbol(e.target.value)}
                  className="w-full px-4 py-3 bg-gray-50 rounded-xl text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500/20"
                >
                  {overview?.top_cryptos?.map((c) => (
                    <option key={c.symbol} value={c.symbol}>
                      {c.symbol} - {c.name}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">Quantity</label>
                <input
                  type="number"
                  value={orderQuantity}
                  onChange={(e) => setOrderQuantity(e.target.value)}
                  className="w-full px-4 py-3 bg-gray-50 rounded-xl text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500/20"
                  placeholder="0.01"
                  step="0.001"
                />
              </div>
              <button
                onClick={placeOrder}
                className={cn(
                  "w-full py-4 rounded-xl font-semibold text-white shadow-lg transition-all",
                  orderSide === "buy"
                    ? "bg-green-500 hover:bg-green-600 shadow-green-500/30"
                    : "bg-red-500 hover:bg-red-600 shadow-red-500/30"
                )}
              >
                {orderSide === "buy" ? "Buy" : "Sell"} {orderSymbol}
              </button>
              <p className="text-xs text-gray-400 text-center">Paper trading only • No real money</p>
            </div>
          </div>

          {/* Trading Signals */}
          <div className="bg-white rounded-2xl shadow-sm overflow-hidden">
            <div className="p-6 border-b border-gray-100">
              <h3 className="font-semibold text-gray-900 flex items-center gap-2">
                <Zap className="w-5 h-5 text-yellow-500" />
                AI Signals
              </h3>
            </div>
            <div className="p-4 space-y-2 max-h-64 overflow-y-auto">
              {signals.slice(0, 8).map((signal) => (
                <div
                  key={signal.symbol}
                  className="flex items-center justify-between p-3 rounded-xl bg-gray-50 hover:bg-gray-100 transition-colors"
                >
                  <div className="flex items-center gap-3">
                    <div className="w-8 h-8 rounded-lg bg-orange-100 flex items-center justify-center">
                      <Bitcoin className="w-4 h-4 text-orange-600" />
                    </div>
                    <div>
                      <div className="font-semibold text-gray-900 text-sm">{signal.symbol}</div>
                      <div className={cn(
                        "text-xs",
                        signal.change_24h >= 0 ? "text-green-600" : "text-red-600"
                      )}>
                        {signal.change_24h >= 0 ? "+" : ""}{signal.change_24h.toFixed(1)}%
                      </div>
                    </div>
                  </div>
                  <span className={cn(
                    "px-3 py-1.5 rounded-full text-xs font-semibold",
                    signal.action.includes("BUY") && "bg-green-100 text-green-700",
                    signal.action.includes("SELL") && "bg-red-100 text-red-700",
                    signal.action === "HOLD" && "bg-gray-100 text-gray-600"
                  )}>
                    {signal.action}
                  </span>
                </div>
              ))}
              {signals.length === 0 && (
                <div className="py-8 text-center text-gray-500 text-sm">
                  Loading signals...
                </div>
              )}
            </div>
          </div>

          {/* Top Movers */}
          <div className="bg-white rounded-2xl shadow-sm overflow-hidden">
            <div className="p-6 border-b border-gray-100">
              <h3 className="font-semibold text-gray-900">Top Movers</h3>
            </div>
            <div className="p-6">
              <div className="grid grid-cols-2 gap-6">
                <div>
                  <h4 className="text-sm font-medium text-green-600 mb-3 flex items-center gap-2">
                    <TrendingUp className="w-4 h-4" />
                    Gainers
                  </h4>
                  <div className="space-y-2">
                    {overview?.top_gainers?.slice(0, 3).map((c) => (
                      <div key={c.symbol} className="flex justify-between items-center">
                        <span className="text-sm font-medium text-gray-900">{c.symbol}</span>
                        <span className="text-sm font-mono text-green-600">
                          +{c.change_percent_24h.toFixed(1)}%
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
                <div>
                  <h4 className="text-sm font-medium text-red-600 mb-3 flex items-center gap-2">
                    <TrendingDown className="w-4 h-4" />
                    Losers
                  </h4>
                  <div className="space-y-2">
                    {overview?.top_losers?.slice(0, 3).map((c) => (
                      <div key={c.symbol} className="flex justify-between items-center">
                        <span className="text-sm font-medium text-gray-900">{c.symbol}</span>
                        <span className="text-sm font-mono text-red-600">
                          {c.change_percent_24h.toFixed(1)}%
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Footer */}
      <div className="mt-8 text-center text-sm text-gray-400">
        Paper trading only • Cryptocurrency is highly volatile • Data from CoinGecko
      </div>
    </div>
  );
}
