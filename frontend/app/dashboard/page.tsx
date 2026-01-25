"use client";

import { useEffect, useState, useCallback } from "react";
import {
  TrendingUp,
  TrendingDown,
  RefreshCw,
  Clock,
  Zap,
  Search,
  ExternalLink,
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

export default function TerminalDashboard() {
  const [marketOverview, setMarketOverview] = useState<MarketOverview | null>(null);
  const [watchlist, setWatchlist] = useState<Quote[]>([]);
  const [news, setNews] = useState<NewsItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdate, setLastUpdate] = useState<Date>(new Date());
  const [searchSymbol, setSearchSymbol] = useState("");

  const fetchData = useCallback(async () => {
    try {
      const [overviewRes, watchlistRes, newsRes] = await Promise.all([
        fetch(`${API_BASE}/api/market/overview`),
        fetch(`${API_BASE}/api/market/watchlist`),
        fetch(`${API_BASE}/api/market/news?limit=15`),
      ]);

      if (overviewRes.ok) {
        const data = await overviewRes.json();
        setMarketOverview(data);
      }

      if (watchlistRes.ok) {
        const data = await watchlistRes.json();
        setWatchlist(data.watchlist.filter((q: any) => !q.error));
      }

      if (newsRes.ok) {
        const data = await newsRes.json();
        setNews(data.news || []);
      }

      setLastUpdate(new Date());
      setError(null);
    } catch (err) {
      setError("Failed to connect to market data service");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    // Auto-refresh every 30 seconds
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
        // Add to watchlist if not already there
        if (!watchlist.find(q => q.symbol === quote.symbol)) {
          setWatchlist(prev => [quote, ...prev]);
        }
      }
    } catch (err) {
      console.error("Search failed:", err);
    }
    setSearchSymbol("");
  };

  const formatPrice = (price: number) => {
    return price?.toLocaleString("en-US", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }) || "—";
  };

  const formatChange = (change: number, percent: number) => {
    const sign = change >= 0 ? "+" : "";
    return `${sign}${change?.toFixed(2)} (${sign}${percent?.toFixed(2)}%)`;
  };

  const formatTime = (date: Date) => {
    return date.toLocaleTimeString("en-US", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  };

  const formatNewsTime = (isoString: string) => {
    const date = new Date(isoString);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMins / 60);

    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    return date.toLocaleDateString();
  };

  return (
    <div className="min-h-screen bg-background p-2">
      {/* Header Bar */}
      <header className="terminal-panel mb-2 px-4 py-2 flex items-center justify-between">
        <div className="flex items-center gap-4">
          <h1 className="text-lg font-bold text-bloomberg-orange font-mono">QUANTLAB TERMINAL</h1>
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <div className={cn(
              "status-dot",
              marketOverview?.market_status === "open" ? "status-live bg-positive" : "bg-muted-foreground"
            )} />
            <span className="uppercase">
              {marketOverview?.market_status || "CONNECTING..."}
            </span>
          </div>
        </div>

        <div className="flex items-center gap-4">
          <form onSubmit={handleSearch} className="flex items-center gap-2">
            <Search className="w-4 h-4 text-muted-foreground" />
            <input
              type="text"
              value={searchSymbol}
              onChange={(e) => setSearchSymbol(e.target.value.toUpperCase())}
              placeholder="SYMBOL"
              className="command-input w-24 text-xs"
            />
          </form>

          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Clock className="w-3 h-3" />
            <span className="font-mono">{formatTime(lastUpdate)}</span>
          </div>

          <button
            onClick={fetchData}
            className="p-1.5 rounded hover:bg-secondary transition-colors"
            title="Refresh"
          >
            <RefreshCw className={cn("w-4 h-4", loading && "animate-spin")} />
          </button>
        </div>
      </header>

      {error && (
        <div className="terminal-panel mb-2 px-4 py-2 border-destructive bg-destructive/10">
          <p className="text-sm text-destructive">{error}</p>
        </div>
      )}

      {/* Main Grid */}
      <div className="grid grid-cols-12 gap-2">
        {/* Market Indices */}
        <div className="col-span-12 terminal-panel p-3">
          <div className="flex items-center gap-6 overflow-x-auto">
            {marketOverview?.indices.map((index) => (
              <div key={index.symbol} className="flex-shrink-0 index-box min-w-[140px]">
                <div className="text-xs text-muted-foreground mb-1">{index.name}</div>
                <div className="font-mono font-semibold">{formatPrice(index.price)}</div>
                <div className={cn(
                  "text-xs font-mono",
                  index.change >= 0 ? "text-positive" : "text-negative"
                )}>
                  {formatChange(index.change, index.change_percent)}
                </div>
              </div>
            ))}
            {!marketOverview && loading && (
              <div className="text-sm text-muted-foreground">Loading market data...</div>
            )}
          </div>
        </div>

        {/* Watchlist */}
        <div className="col-span-12 lg:col-span-5 terminal-panel">
          <div className="px-3 py-2 border-b border-border flex items-center justify-between">
            <h2 className="text-sm font-semibold text-bloomberg-orange">WATCHLIST</h2>
            <span className="text-xs text-muted-foreground">{watchlist.length} symbols</span>
          </div>
          <div className="max-h-[400px] overflow-y-auto">
            <table className="data-table">
              <thead>
                <tr>
                  <th>SYMBOL</th>
                  <th className="text-right">LAST</th>
                  <th className="text-right">CHG</th>
                  <th className="text-right">CHG%</th>
                </tr>
              </thead>
              <tbody>
                {watchlist.map((quote) => (
                  <tr key={quote.symbol}>
                    <td className="font-semibold">{quote.symbol}</td>
                    <td className="text-right tabular-nums">{formatPrice(quote.price)}</td>
                    <td className={cn(
                      "text-right tabular-nums",
                      quote.change >= 0 ? "text-positive" : "text-negative"
                    )}>
                      {quote.change >= 0 ? "+" : ""}{quote.change?.toFixed(2)}
                    </td>
                    <td className={cn(
                      "text-right tabular-nums",
                      quote.change_percent >= 0 ? "text-positive" : "text-negative"
                    )}>
                      {quote.change_percent >= 0 ? "+" : ""}{quote.change_percent?.toFixed(2)}%
                    </td>
                  </tr>
                ))}
                {watchlist.length === 0 && !loading && (
                  <tr>
                    <td colSpan={4} className="text-center text-muted-foreground py-4">
                      No data available
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* Sector Performance */}
        <div className="col-span-12 lg:col-span-3 terminal-panel">
          <div className="px-3 py-2 border-b border-border">
            <h2 className="text-sm font-semibold text-bloomberg-orange">SECTORS</h2>
          </div>
          <div className="p-2 space-y-1 max-h-[400px] overflow-y-auto">
            {marketOverview?.sectors.map((sector) => (
              <div
                key={sector.symbol}
                className={cn(
                  "flex items-center justify-between px-2 py-1.5 rounded text-sm",
                  sector.change_percent >= 0 ? "sector-positive-1" : "sector-negative-1"
                )}
              >
                <span className="truncate">{sector.name}</span>
                <span className={cn(
                  "font-mono font-medium tabular-nums",
                  sector.change_percent >= 0 ? "text-positive" : "text-negative"
                )}>
                  {sector.change_percent >= 0 ? "+" : ""}{sector.change_percent?.toFixed(2)}%
                </span>
              </div>
            ))}
            {!marketOverview && loading && (
              <div className="text-sm text-muted-foreground text-center py-4">Loading...</div>
            )}
          </div>
        </div>

        {/* News Feed */}
        <div className="col-span-12 lg:col-span-4 terminal-panel">
          <div className="px-3 py-2 border-b border-border flex items-center gap-2">
            <Zap className="w-4 h-4 text-bloomberg-orange" />
            <h2 className="text-sm font-semibold text-bloomberg-orange">MARKET NEWS</h2>
          </div>
          <div className="max-h-[400px] overflow-y-auto divide-y divide-border/50">
            {news.map((item) => (
              <a
                key={item.id}
                href={item.url}
                target="_blank"
                rel="noopener noreferrer"
                className="block px-3 py-2 hover:bg-secondary/30 transition-colors group"
              >
                <div className="flex items-start justify-between gap-2">
                  <p className="news-headline group-hover:text-primary">
                    {item.headline}
                  </p>
                  <ExternalLink className="w-3 h-3 flex-shrink-0 text-muted-foreground opacity-0 group-hover:opacity-100" />
                </div>
                <div className="flex items-center gap-2 mt-1 text-xs text-muted-foreground">
                  <span>{item.source}</span>
                  <span>|</span>
                  <span>{formatNewsTime(item.published)}</span>
                  {item.related_symbols.length > 0 && (
                    <>
                      <span>|</span>
                      <span className="text-bloomberg-blue">
                        {item.related_symbols.slice(0, 3).join(", ")}
                      </span>
                    </>
                  )}
                </div>
              </a>
            ))}
            {news.length === 0 && !loading && (
              <div className="px-3 py-4 text-sm text-muted-foreground text-center">
                No news available. Add a Finnhub API key for live news.
              </div>
            )}
          </div>
        </div>

        {/* Quick Stats */}
        <div className="col-span-12 terminal-panel p-3">
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4">
            <QuickStat
              label="Top Gainer"
              value={watchlist.length > 0 ?
                [...watchlist].sort((a, b) => b.change_percent - a.change_percent)[0]?.symbol : "—"}
              subValue={watchlist.length > 0 ?
                `+${[...watchlist].sort((a, b) => b.change_percent - a.change_percent)[0]?.change_percent?.toFixed(2)}%` : ""}
              positive
            />
            <QuickStat
              label="Top Loser"
              value={watchlist.length > 0 ?
                [...watchlist].sort((a, b) => a.change_percent - b.change_percent)[0]?.symbol : "—"}
              subValue={watchlist.length > 0 ?
                `${[...watchlist].sort((a, b) => a.change_percent - b.change_percent)[0]?.change_percent?.toFixed(2)}%` : ""}
            />
            <QuickStat
              label="VIX"
              value={marketOverview?.indices.find(i => i.symbol === "^VIX")?.price?.toFixed(2) || "—"}
              subValue={marketOverview?.indices.find(i => i.symbol === "^VIX")?.change_percent?.toFixed(2) + "%" || ""}
            />
            <QuickStat
              label="Market Status"
              value={marketOverview?.market_status?.toUpperCase() || "—"}
              subValue=""
            />
            <QuickStat
              label="Advancing"
              value={watchlist.filter(q => q.change >= 0).length.toString()}
              subValue={`of ${watchlist.length}`}
              positive
            />
            <QuickStat
              label="Declining"
              value={watchlist.filter(q => q.change < 0).length.toString()}
              subValue={`of ${watchlist.length}`}
            />
          </div>
        </div>
      </div>

      {/* Footer */}
      <footer className="terminal-panel mt-2 px-4 py-2">
        <p className="text-xs text-muted-foreground text-center">
          QUANTLAB TERMINAL | Data delayed 15 min | For educational purposes only | Not financial advice
        </p>
      </footer>
    </div>
  );
}

function QuickStat({
  label,
  value,
  subValue,
  positive,
}: {
  label: string;
  value: string;
  subValue: string;
  positive?: boolean;
}) {
  return (
    <div className="text-center">
      <div className="text-xs text-muted-foreground mb-1">{label}</div>
      <div className={cn(
        "font-mono font-semibold",
        positive ? "text-positive" : subValue.startsWith("-") ? "text-negative" : ""
      )}>
        {value}
      </div>
      {subValue && (
        <div className={cn(
          "text-xs font-mono",
          positive ? "text-positive" : subValue.startsWith("-") ? "text-negative" : "text-muted-foreground"
        )}>
          {subValue}
        </div>
      )}
    </div>
  );
}
