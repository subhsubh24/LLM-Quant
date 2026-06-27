"use client";

import { useEffect, useState, useCallback } from "react";
import {
  TrendingUp,
  TrendingDown,
  RefreshCw,
  Clock,
  Search,
  ArrowUpRight,
  ArrowDownRight,
  Activity,
  BarChart3,
  Newspaper,
  Loader2,
  AlertCircle,
  Zap,
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

function MiniBar({ value, max }: { value: number; max: number }) {
  const pct = Math.min(Math.abs(value / max) * 100, 100);
  const positive = value >= 0;
  return (
    <div className="w-16 h-1.5 rounded-full bg-muted overflow-hidden">
      <div
        className={cn("h-full rounded-full transition-all duration-700", positive ? "bg-green-500" : "bg-red-500")}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

function LoadingCard() {
  return (
    <div className="glass-card p-5 space-y-3">
      <div className="skeleton h-3 w-20" />
      <div className="skeleton h-7 w-28" />
      <div className="skeleton h-3 w-16" />
    </div>
  );
}

function EmptyState({ icon: Icon, title, subtitle }: { icon: any; title: string; subtitle: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-12 text-center">
      <div className="w-12 h-12 rounded-2xl bg-muted flex items-center justify-center mb-3">
        <Icon className="w-6 h-6 text-muted-foreground" />
      </div>
      <p className="text-sm font-medium text-foreground mb-1">{title}</p>
      <p className="text-xs text-muted-foreground max-w-[200px]">{subtitle}</p>
    </div>
  );
}

export default function DashboardPage() {
  const [marketOverview, setMarketOverview] = useState<MarketOverview | null>(null);
  const [watchlist, setWatchlist] = useState<Quote[]>([]);
  const [news, setNews] = useState<NewsItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);
  const [searchSymbol, setSearchSymbol] = useState("");
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true);
    setError(null);
    try {
      const [overviewRes, watchlistRes, newsRes] = await Promise.all([
        fetch(`${API_BASE}/api/market/overview`).catch(() => null),
        fetch(`${API_BASE}/api/market/watchlist`).catch(() => null),
        fetch(`${API_BASE}/api/market/news?limit=10`).catch(() => null),
      ]);

      if (overviewRes?.ok) setMarketOverview(await overviewRes.json());
      if (watchlistRes?.ok) {
        const data = await watchlistRes.json();
        setWatchlist(data.watchlist.filter((q: any) => !q.error));
      }
      if (newsRes?.ok) {
        const data = await newsRes.json();
        setNews(data.news || []);
      }

      if (!overviewRes?.ok && !watchlistRes?.ok && !newsRes?.ok) {
        setError("Could not connect to API. Make sure the backend is running.");
      }

      setLastUpdate(new Date());
    } catch (err) {
      setError("Failed to fetch market data");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(() => fetchData(), 30000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!searchSymbol.trim()) return;
    try {
      const res = await fetch(`${API_BASE}/api/market/quote/${searchSymbol.toUpperCase()}`);
      if (res.ok) {
        const quote = await res.json();
        if (!watchlist.find((q) => q.symbol === quote.symbol)) {
          setWatchlist((prev) => [quote, ...prev]);
        }
      }
    } catch {}
    setSearchSymbol("");
  };

  const formatPrice = (price: number) =>
    price?.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) || "—";

  const formatTime = (date: Date) =>
    date.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", second: "2-digit" });

  const formatNewsTime = (isoString: string) => {
    if (!isoString) return "Recent";
    const date = new Date(isoString);
    if (isNaN(date.getTime())) return "Recent";
    const diffMs = Date.now() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    if (diffMins < 0) return "Just now";
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffMins < 1440) return `${Math.floor(diffMins / 60)}h ago`;
    return date.toLocaleDateString();
  };

  const advancingCount = watchlist.filter((q) => q.change >= 0).length;
  const decliningCount = watchlist.filter((q) => q.change < 0).length;
  const maxChange = Math.max(...watchlist.map((q) => Math.abs(q.change_percent)), 1);

  return (
    <div className="min-h-screen p-6 lg:p-8">
      {/* Header */}
      <div className="flex items-center justify-between mb-6 fade-in">
        <div>
          <h1 className="text-2xl font-bold text-foreground tracking-tight">Dashboard</h1>
          <p className="text-sm text-muted-foreground mt-0.5">Real-time market overview</p>
        </div>
        <div className="flex items-center gap-3">
          <form onSubmit={handleSearch} className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <input
              type="text"
              value={searchSymbol}
              onChange={(e) => setSearchSymbol(e.target.value.toUpperCase())}
              placeholder="Add symbol..."
              className="pl-10 pr-4 py-2 bg-muted/50 rounded-xl border border-border text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary/40 w-44"
            />
          </form>
          <div className="flex items-center gap-2 text-xs text-muted-foreground bg-muted/50 px-3 py-2 rounded-xl border border-border">
            <Clock className="w-3.5 h-3.5" />
            <span className="font-mono tabular-nums">{lastUpdate ? formatTime(lastUpdate) : "—"}</span>
          </div>
          <button
            onClick={() => fetchData(true)}
            disabled={refreshing}
            className="p-2 rounded-xl bg-muted/50 hover:bg-muted border border-border text-muted-foreground hover:text-foreground disabled:opacity-50"
          >
            <RefreshCw className={cn("w-4 h-4", refreshing && "animate-spin")} />
          </button>
        </div>
      </div>

      {/* Error Banner */}
      {error && (
        <div className="mb-6 p-4 rounded-xl bg-destructive/10 border border-destructive/20 flex items-center gap-3 fade-in">
          <AlertCircle className="w-4 h-4 text-destructive flex-shrink-0" />
          <span className="text-sm text-destructive">{error}</span>
        </div>
      )}

      {/* Market Status Banner */}
      <div
        className={cn(
          "mb-6 p-3 rounded-xl flex items-center justify-between border fade-in",
          marketOverview?.market_status === "open"
            ? "bg-green-500/5 border-green-500/20"
            : "bg-amber-500/5 border-amber-500/20"
        )}
      >
        <div className="flex items-center gap-3">
          <div
            className={cn(
              "status-dot",
              marketOverview?.market_status === "open" ? "live" : "warning"
            )}
          />
          <span
            className={cn(
              "text-sm font-semibold",
              marketOverview?.market_status === "open" ? "text-green-500" : "text-amber-500"
            )}
          >
            Market {marketOverview?.market_status === "open" ? "Open" : "Closed"}
          </span>
        </div>
        <span className="text-xs text-muted-foreground">NYSE / NASDAQ Regular Hours</span>
      </div>

      {/* Market Indices */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3 mb-6 stagger-children">
        {loading
          ? Array.from({ length: 5 }).map((_, i) => <LoadingCard key={i} />)
          : marketOverview?.indices.slice(0, 5).map((index) => (
              <div key={index.symbol} className="glass-card p-4 group hover:border-primary/20 transition-colors">
                <div className="text-xs text-muted-foreground font-medium mb-1">{index.name}</div>
                <div className="text-xl font-bold text-foreground tracking-tight tabular-nums">
                  {formatPrice(index.price)}
                </div>
                <div className="flex items-center gap-2 mt-1.5">
                  <span
                    className={cn(
                      "inline-flex items-center gap-0.5 text-xs font-semibold tabular-nums",
                      index.change >= 0 ? "text-green-500" : "text-red-500"
                    )}
                  >
                    {index.change >= 0 ? <ArrowUpRight className="w-3 h-3" /> : <ArrowDownRight className="w-3 h-3" />}
                    {index.change >= 0 ? "+" : ""}
                    {index.change_percent?.toFixed(2)}%
                  </span>
                  <MiniBar value={index.change_percent} max={3} />
                </div>
              </div>
            ))}
      </div>

      <div className="grid grid-cols-12 gap-4">
        {/* Watchlist */}
        <div className="col-span-12 lg:col-span-6 glass-card overflow-hidden">
          <div className="p-4 border-b border-border/60 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-foreground flex items-center gap-2">
              <Activity className="w-4 h-4 text-primary" />
              Watchlist
              <span className="ml-1 px-1.5 py-0.5 bg-muted text-muted-foreground text-[10px] font-bold rounded-md tabular-nums">
                {watchlist.length}
              </span>
            </h2>
            <div className="flex items-center gap-3 text-[10px] font-medium text-muted-foreground">
              <span className="flex items-center gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-green-500" />
                {advancingCount} up
              </span>
              <span className="flex items-center gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-red-500" />
                {decliningCount} down
              </span>
            </div>
          </div>

          {/* Breadth bar */}
          {watchlist.length > 0 && (
            <div className="h-1 flex">
              <div
                className="bg-green-500/60 transition-all duration-500"
                style={{ width: `${(advancingCount / watchlist.length) * 100}%` }}
              />
              <div
                className="bg-red-500/60 transition-all duration-500"
                style={{ width: `${(decliningCount / watchlist.length) * 100}%` }}
              />
            </div>
          )}

          <div className="max-h-[420px] overflow-y-auto">
            <table className="w-full">
              <thead className="sticky top-0 bg-card/95 backdrop-blur-sm">
                <tr className="border-b border-border/40">
                  <th className="text-left text-[10px] font-semibold text-muted-foreground uppercase tracking-wider py-2.5 px-4">
                    Symbol
                  </th>
                  <th className="text-right text-[10px] font-semibold text-muted-foreground uppercase tracking-wider py-2.5 px-4">
                    Price
                  </th>
                  <th className="text-right text-[10px] font-semibold text-muted-foreground uppercase tracking-wider py-2.5 px-4">
                    Change
                  </th>
                  <th className="text-right text-[10px] font-semibold text-muted-foreground uppercase tracking-wider py-2.5 px-4 hidden md:table-cell">
                    Strength
                  </th>
                </tr>
              </thead>
              <tbody>
                {watchlist.map((quote, i) => (
                  <tr
                    key={quote.symbol}
                    className="border-b border-border/20 hover:bg-muted/30 transition-colors"
                    style={{ animationDelay: `${i * 30}ms` }}
                  >
                    <td className="py-3 px-4">
                      <span className="font-semibold text-sm text-foreground">{quote.symbol}</span>
                    </td>
                    <td className="py-3 px-4 text-right">
                      <span className="font-mono text-sm text-foreground tabular-nums">${formatPrice(quote.price)}</span>
                    </td>
                    <td className="py-3 px-4 text-right">
                      <span
                        className={cn(
                          "inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-semibold tabular-nums",
                          quote.change >= 0 ? "bg-green-500/10 text-green-500" : "bg-red-500/10 text-red-500"
                        )}
                      >
                        {quote.change >= 0 ? <ArrowUpRight className="w-3 h-3" /> : <ArrowDownRight className="w-3 h-3" />}
                        {quote.change >= 0 ? "+" : ""}
                        {quote.change_percent?.toFixed(2)}%
                      </span>
                    </td>
                    <td className="py-3 px-4 text-right hidden md:table-cell">
                      <MiniBar value={quote.change_percent} max={maxChange} />
                    </td>
                  </tr>
                ))}
                {!loading && watchlist.length === 0 && (
                  <tr>
                    <td colSpan={4}>
                      <EmptyState icon={Activity} title="No stocks yet" subtitle="Search to add symbols to your watchlist" />
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* Sector Performance */}
        <div className="col-span-12 md:col-span-6 lg:col-span-3 glass-card overflow-hidden">
          <div className="p-4 border-b border-border/60">
            <h2 className="text-sm font-semibold text-foreground flex items-center gap-2">
              <BarChart3 className="w-4 h-4 text-primary" />
              Sectors
            </h2>
          </div>
          <div className="p-3 space-y-1 max-h-[420px] overflow-y-auto">
            {marketOverview?.sectors.map((sector) => (
              <div
                key={sector.symbol}
                className="flex items-center justify-between p-2.5 rounded-lg hover:bg-muted/40 transition-colors group"
              >
                <span className="text-xs text-muted-foreground group-hover:text-foreground transition-colors">
                  {sector.name}
                </span>
                <div className="flex items-center gap-2">
                  <MiniBar value={sector.change_percent} max={3} />
                  <span
                    className={cn(
                      "font-mono text-xs font-semibold tabular-nums w-14 text-right",
                      sector.change_percent >= 0 ? "text-green-500" : "text-red-500"
                    )}
                  >
                    {sector.change_percent >= 0 ? "+" : ""}
                    {sector.change_percent?.toFixed(2)}%
                  </span>
                </div>
              </div>
            ))}
            {!marketOverview?.sectors?.length && !loading && (
              <EmptyState icon={BarChart3} title="No sector data" subtitle="Market data unavailable" />
            )}
          </div>
        </div>

        {/* News Feed */}
        <div className="col-span-12 md:col-span-6 lg:col-span-3 glass-card overflow-hidden">
          <div className="p-4 border-b border-border/60">
            <h2 className="text-sm font-semibold text-foreground flex items-center gap-2">
              <Newspaper className="w-4 h-4 text-primary" />
              Market News
            </h2>
          </div>
          <div className="max-h-[420px] overflow-y-auto">
            {news.map((item) => (
              <a
                key={item.id}
                href={item.url}
                target="_blank"
                rel="noopener noreferrer"
                className="block p-3 hover:bg-muted/30 border-b border-border/20 transition-colors group"
              >
                <p className="text-xs font-medium text-foreground line-clamp-2 group-hover:text-primary transition-colors leading-relaxed">
                  {item.headline || item.summary || "News article"}
                </p>
                <div className="flex items-center gap-2 mt-1.5 text-[10px] text-muted-foreground">
                  <span className="font-semibold">{item.source}</span>
                  <span className="opacity-40">·</span>
                  <span>{formatNewsTime(item.published)}</span>
                </div>
              </a>
            ))}
            {news.length === 0 && !loading && (
              <EmptyState icon={Newspaper} title="No news" subtitle="Add Finnhub API key for live news feed" />
            )}
          </div>
        </div>
      </div>

      {/* Quick Stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mt-4 stagger-children">
        <div className="glass-card p-4">
          <div className="flex items-center justify-between mb-3">
            <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">Top Gainer</span>
            <div className="w-8 h-8 rounded-lg bg-green-500/10 flex items-center justify-center">
              <TrendingUp className="w-4 h-4 text-green-500" />
            </div>
          </div>
          <div className="text-lg font-bold text-foreground tabular-nums">
            {watchlist.length > 0
              ? [...watchlist].sort((a, b) => b.change_percent - a.change_percent)[0]?.symbol
              : "—"}
          </div>
          <div className="text-xs text-green-500 font-semibold mt-0.5 tabular-nums">
            {watchlist.length > 0 &&
              `+${[...watchlist].sort((a, b) => b.change_percent - a.change_percent)[0]?.change_percent?.toFixed(2)}%`}
          </div>
        </div>

        <div className="glass-card p-4">
          <div className="flex items-center justify-between mb-3">
            <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">Top Loser</span>
            <div className="w-8 h-8 rounded-lg bg-red-500/10 flex items-center justify-center">
              <TrendingDown className="w-4 h-4 text-red-500" />
            </div>
          </div>
          <div className="text-lg font-bold text-foreground tabular-nums">
            {watchlist.length > 0
              ? [...watchlist].sort((a, b) => a.change_percent - b.change_percent)[0]?.symbol
              : "—"}
          </div>
          <div className="text-xs text-red-500 font-semibold mt-0.5 tabular-nums">
            {watchlist.length > 0 &&
              `${[...watchlist].sort((a, b) => a.change_percent - b.change_percent)[0]?.change_percent?.toFixed(2)}%`}
          </div>
        </div>

        <div className="glass-card p-4">
          <div className="flex items-center justify-between mb-3">
            <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">Advancing</span>
            <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center">
              <ArrowUpRight className="w-4 h-4 text-primary" />
            </div>
          </div>
          <div className="text-lg font-bold text-foreground tabular-nums">{advancingCount}</div>
          <div className="text-xs text-muted-foreground mt-0.5">of {watchlist.length} stocks</div>
        </div>

        <div className="glass-card p-4">
          <div className="flex items-center justify-between mb-3">
            <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">Declining</span>
            <div className="w-8 h-8 rounded-lg bg-amber-500/10 flex items-center justify-center">
              <ArrowDownRight className="w-4 h-4 text-amber-500" />
            </div>
          </div>
          <div className="text-lg font-bold text-foreground tabular-nums">{decliningCount}</div>
          <div className="text-xs text-muted-foreground mt-0.5">of {watchlist.length} stocks</div>
        </div>
      </div>

      {/* Footer */}
      <div className="mt-8 text-center text-[10px] text-muted-foreground/60">
        Data delayed 15 min · For educational purposes only · Not financial advice
      </div>
    </div>
  );
}
