"use client";

import { useEffect, useState, useCallback } from "react";
import {
  TrendingUp,
  TrendingDown,
  RefreshCw,
  Clock,
  Search,
  ExternalLink,
  ArrowUpRight,
  ArrowDownRight,
  Activity,
  Globe,
  BarChart3,
  Newspaper,
  Sparkles,
} from "lucide-react";
import { cn } from "@/lib/utils";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface Quote {
  symbol: string;
  price: number;
  change: number;
  change_percent: number;
  high: number;
  low: number;
  volume: number;
  timestamp: string;
}

interface NewsItem {
  id: string;
  headline: string;
  summary: string;
  source: string;
  url: string;
  published: string;
  related_symbols: string[];
}

interface MarketOverview {
  indices: Array<{
    symbol: string;
    name: string;
    price: number;
    change: number;
    change_percent: number;
  }>;
  sectors: Array<{
    symbol: string;
    name: string;
    change_percent: number;
  }>;
  market_status: string;
  timestamp: string;
}

export default function DashboardPage() {
  const [marketOverview, setMarketOverview] = useState<MarketOverview | null>(null);
  const [watchlist, setWatchlist] = useState<Quote[]>([]);
  const [news, setNews] = useState<NewsItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [lastUpdate, setLastUpdate] = useState<Date>(new Date());
  const [searchSymbol, setSearchSymbol] = useState("");

  const fetchData = useCallback(async () => {
    try {
      const [overviewRes, watchlistRes, newsRes] = await Promise.all([
        fetch(`${API_BASE}/api/market/overview`),
        fetch(`${API_BASE}/api/market/watchlist`),
        fetch(`${API_BASE}/api/market/news?limit=10`),
      ]);

      if (overviewRes.ok) setMarketOverview(await overviewRes.json());
      if (watchlistRes.ok) {
        const data = await watchlistRes.json();
        setWatchlist(data.watchlist.filter((q: any) => !q.error));
      }
      if (newsRes.ok) {
        const data = await newsRes.json();
        setNews(data.news || []);
      }

      setLastUpdate(new Date());
    } catch (err) {
      console.error("Failed to fetch data:", err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 30000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!searchSymbol.trim()) return;
    try {
      const res = await fetch(`${API_BASE}/api/market/quote/${searchSymbol.toUpperCase()}`);
      if (res.ok) {
        const quote = await res.json();
        if (!watchlist.find(q => q.symbol === quote.symbol)) {
          setWatchlist(prev => [quote, ...prev]);
        }
      }
    } catch (err) {
      console.error("Search failed:", err);
    }
    setSearchSymbol("");
  };

  const formatPrice = (price: number) =>
    price?.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) || "—";

  const formatTime = (date: Date) =>
    date.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" });

  const formatNewsTime = (isoString: string) => {
    const diffMs = Date.now() - new Date(isoString).getTime();
    const diffMins = Math.floor(diffMs / 60000);
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffMins < 1440) return `${Math.floor(diffMins / 60)}h ago`;
    return new Date(isoString).toLocaleDateString();
  };

  return (
    <div className="ml-64 min-h-screen bg-gray-50/50 p-8">
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-3xl font-bold text-gray-900 tracking-tight">Dashboard</h1>
          <p className="text-gray-500 mt-1">Real-time market overview and analytics</p>
        </div>
        <div className="flex items-center gap-4">
          <form onSubmit={handleSearch} className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
            <input
              type="text"
              value={searchSymbol}
              onChange={(e) => setSearchSymbol(e.target.value.toUpperCase())}
              placeholder="Search symbol..."
              className="pl-10 pr-4 py-2.5 bg-white rounded-xl border border-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20 w-48"
            />
          </form>
          <div className="flex items-center gap-2 text-sm text-gray-500 bg-white px-4 py-2.5 rounded-xl border border-gray-200">
            <Clock className="w-4 h-4" />
            <span>{formatTime(lastUpdate)}</span>
          </div>
          <button
            onClick={fetchData}
            className="p-2.5 bg-white rounded-xl hover:bg-gray-50 border border-gray-200"
          >
            <RefreshCw className={cn("w-5 h-5 text-gray-500", loading && "animate-spin")} />
          </button>
        </div>
      </div>

      {/* Market Status */}
      <div className={cn(
        "mb-6 p-4 rounded-2xl flex items-center justify-between",
        marketOverview?.market_status === "open"
          ? "bg-green-50 border border-green-100"
          : "bg-orange-50 border border-orange-100"
      )}>
        <div className="flex items-center gap-3">
          <div className={cn(
            "w-3 h-3 rounded-full",
            marketOverview?.market_status === "open" ? "bg-green-500 animate-pulse" : "bg-orange-500"
          )} />
          <span className={cn(
            "font-semibold",
            marketOverview?.market_status === "open" ? "text-green-700" : "text-orange-700"
          )}>
            Market {marketOverview?.market_status === "open" ? "Open" : "Closed"}
          </span>
        </div>
        <span className="text-sm text-gray-600">NYSE/NASDAQ Regular Hours</span>
      </div>

      {/* Market Indices */}
      <div className="grid grid-cols-5 gap-4 mb-6">
        {marketOverview?.indices.slice(0, 5).map((index) => (
          <div key={index.symbol} className="bg-white rounded-2xl p-5 shadow-sm">
            <div className="text-sm text-gray-500 mb-1">{index.name}</div>
            <div className="text-2xl font-bold text-gray-900 tracking-tight">
              {formatPrice(index.price)}
            </div>
            <div className={cn(
              "flex items-center gap-1 text-sm mt-1",
              index.change >= 0 ? "text-green-600" : "text-red-600"
            )}>
              {index.change >= 0 ? (
                <ArrowUpRight className="w-4 h-4" />
              ) : (
                <ArrowDownRight className="w-4 h-4" />
              )}
              {index.change >= 0 ? "+" : ""}{index.change_percent?.toFixed(2)}%
            </div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-12 gap-6">
        {/* Watchlist */}
        <div className="col-span-6 bg-white rounded-2xl shadow-sm overflow-hidden">
          <div className="p-6 border-b border-gray-100 flex items-center justify-between">
            <h2 className="font-semibold text-gray-900 flex items-center gap-2">
              <Activity className="w-5 h-5 text-gray-400" />
              Watchlist
              <span className="ml-2 px-2 py-0.5 bg-gray-100 text-gray-600 text-sm rounded-full">
                {watchlist.length}
              </span>
            </h2>
          </div>
          <div className="max-h-[400px] overflow-y-auto">
            <table className="w-full">
              <thead className="bg-gray-50 sticky top-0">
                <tr>
                  <th className="text-left text-xs font-medium text-gray-500 uppercase tracking-wider py-3 px-6">Symbol</th>
                  <th className="text-right text-xs font-medium text-gray-500 uppercase tracking-wider py-3 px-6">Price</th>
                  <th className="text-right text-xs font-medium text-gray-500 uppercase tracking-wider py-3 px-6">Change</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {watchlist.map((quote) => (
                  <tr key={quote.symbol} className="hover:bg-gray-50">
                    <td className="py-4 px-6">
                      <span className="font-semibold text-gray-900">{quote.symbol}</span>
                    </td>
                    <td className="py-4 px-6 text-right font-mono text-gray-900">
                      ${formatPrice(quote.price)}
                    </td>
                    <td className="py-4 px-6 text-right">
                      <span className={cn(
                        "inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-sm font-medium",
                        quote.change >= 0 ? "bg-green-50 text-green-700" : "bg-red-50 text-red-700"
                      )}>
                        {quote.change >= 0 ? (
                          <ArrowUpRight className="w-3 h-3" />
                        ) : (
                          <ArrowDownRight className="w-3 h-3" />
                        )}
                        {quote.change >= 0 ? "+" : ""}{quote.change_percent?.toFixed(2)}%
                      </span>
                    </td>
                  </tr>
                ))}
                {watchlist.length === 0 && (
                  <tr>
                    <td colSpan={3} className="py-12 text-center text-gray-500">
                      No stocks in watchlist
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* Sector Performance */}
        <div className="col-span-3 bg-white rounded-2xl shadow-sm overflow-hidden">
          <div className="p-6 border-b border-gray-100">
            <h2 className="font-semibold text-gray-900 flex items-center gap-2">
              <BarChart3 className="w-5 h-5 text-gray-400" />
              Sectors
            </h2>
          </div>
          <div className="p-4 space-y-2 max-h-[400px] overflow-y-auto">
            {marketOverview?.sectors.map((sector) => (
              <div
                key={sector.symbol}
                className={cn(
                  "flex items-center justify-between p-3 rounded-xl",
                  sector.change_percent >= 0 ? "bg-green-50" : "bg-red-50"
                )}
              >
                <span className="text-sm text-gray-700">{sector.name}</span>
                <span className={cn(
                  "font-mono text-sm font-medium",
                  sector.change_percent >= 0 ? "text-green-600" : "text-red-600"
                )}>
                  {sector.change_percent >= 0 ? "+" : ""}{sector.change_percent?.toFixed(2)}%
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* News Feed */}
        <div className="col-span-3 bg-white rounded-2xl shadow-sm overflow-hidden">
          <div className="p-6 border-b border-gray-100">
            <h2 className="font-semibold text-gray-900 flex items-center gap-2">
              <Newspaper className="w-5 h-5 text-gray-400" />
              Market News
            </h2>
          </div>
          <div className="max-h-[400px] overflow-y-auto divide-y divide-gray-100">
            {news.map((item) => (
              <a
                key={item.id}
                href={item.url}
                target="_blank"
                rel="noopener noreferrer"
                className="block p-4 hover:bg-gray-50 group"
              >
                <p className="text-sm font-medium text-gray-900 line-clamp-2 group-hover:text-blue-600">
                  {item.headline}
                </p>
                <div className="flex items-center gap-2 mt-2 text-xs text-gray-500">
                  <span>{item.source}</span>
                  <span>•</span>
                  <span>{formatNewsTime(item.published)}</span>
                </div>
              </a>
            ))}
            {news.length === 0 && (
              <div className="p-12 text-center">
                <Newspaper className="w-12 h-12 text-gray-300 mx-auto mb-3" />
                <p className="text-gray-500 text-sm">No news available</p>
                <p className="text-gray-400 text-xs mt-1">Add Finnhub API key for live news</p>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Quick Stats */}
      <div className="grid grid-cols-4 gap-4 mt-6">
        <div className="bg-white rounded-2xl p-6 shadow-sm">
          <div className="flex items-center justify-between mb-4">
            <span className="text-sm font-medium text-gray-500">Top Gainer</span>
            <div className="w-10 h-10 rounded-xl bg-green-50 flex items-center justify-center">
              <TrendingUp className="w-5 h-5 text-green-600" />
            </div>
          </div>
          <div className="text-2xl font-bold text-gray-900">
            {watchlist.length > 0 ?
              [...watchlist].sort((a, b) => b.change_percent - a.change_percent)[0]?.symbol : "—"}
          </div>
          <div className="text-sm text-green-600 mt-1">
            {watchlist.length > 0 &&
              `+${[...watchlist].sort((a, b) => b.change_percent - a.change_percent)[0]?.change_percent?.toFixed(2)}%`}
          </div>
        </div>

        <div className="bg-white rounded-2xl p-6 shadow-sm">
          <div className="flex items-center justify-between mb-4">
            <span className="text-sm font-medium text-gray-500">Top Loser</span>
            <div className="w-10 h-10 rounded-xl bg-red-50 flex items-center justify-center">
              <TrendingDown className="w-5 h-5 text-red-600" />
            </div>
          </div>
          <div className="text-2xl font-bold text-gray-900">
            {watchlist.length > 0 ?
              [...watchlist].sort((a, b) => a.change_percent - b.change_percent)[0]?.symbol : "—"}
          </div>
          <div className="text-sm text-red-600 mt-1">
            {watchlist.length > 0 &&
              `${[...watchlist].sort((a, b) => a.change_percent - b.change_percent)[0]?.change_percent?.toFixed(2)}%`}
          </div>
        </div>

        <div className="bg-white rounded-2xl p-6 shadow-sm">
          <div className="flex items-center justify-between mb-4">
            <span className="text-sm font-medium text-gray-500">Advancing</span>
            <div className="w-10 h-10 rounded-xl bg-blue-50 flex items-center justify-center">
              <ArrowUpRight className="w-5 h-5 text-blue-600" />
            </div>
          </div>
          <div className="text-2xl font-bold text-gray-900">
            {watchlist.filter(q => q.change >= 0).length}
          </div>
          <div className="text-sm text-gray-500 mt-1">of {watchlist.length} stocks</div>
        </div>

        <div className="bg-white rounded-2xl p-6 shadow-sm">
          <div className="flex items-center justify-between mb-4">
            <span className="text-sm font-medium text-gray-500">Declining</span>
            <div className="w-10 h-10 rounded-xl bg-orange-50 flex items-center justify-center">
              <ArrowDownRight className="w-5 h-5 text-orange-600" />
            </div>
          </div>
          <div className="text-2xl font-bold text-gray-900">
            {watchlist.filter(q => q.change < 0).length}
          </div>
          <div className="text-sm text-gray-500 mt-1">of {watchlist.length} stocks</div>
        </div>
      </div>

      {/* Footer */}
      <div className="mt-8 text-center text-sm text-gray-400">
        Data delayed 15 min • For educational purposes only • Not financial advice
      </div>
    </div>
  );
}
