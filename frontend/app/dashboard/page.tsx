"use client";

import { useEffect, useState } from "react";
import {
  TrendingUp,
  TrendingDown,
  DollarSign,
  Percent,
  AlertTriangle,
  RefreshCw,
} from "lucide-react";
import { cn, formatCurrency, formatPercent, getReturnColor } from "@/lib/utils";
import { EquityChart } from "@/components/charts/equity-chart";

interface PortfolioData {
  total_value: number;
  total_pnl: number;
  total_pnl_pct: number;
  current_cash: number;
  positions_count: number;
}

interface Recommendation {
  ticker: string;
  signal: number;
  action: string;
}

export default function DashboardPage() {
  const [portfolio, setPortfolio] = useState<PortfolioData | null>(null);
  const [recommendations, setRecommendations] = useState<{
    buy: Recommendation[];
    sell: Recommendation[];
  } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchData();
  }, []);

  async function fetchData() {
    setLoading(true);
    setError(null);

    try {
      // Fetch portfolio
      const portfolioRes = await fetch("/api/paper/portfolios");
      if (portfolioRes.ok) {
        const portfolios = await portfolioRes.json();
        if (portfolios.length > 0) {
          setPortfolio(portfolios[0]);
        }
      }

      // Fetch recommendations
      const recsRes = await fetch("/api/paper/recommendations", {
        method: "POST",
      });
      if (recsRes.ok) {
        const data = await recsRes.json();
        setRecommendations(data.recommendations);
      }
    } catch (err) {
      setError("Failed to load data. Is the backend running?");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="p-8">
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-semibold">Dashboard</h1>
          <p className="text-muted-foreground mt-1">
            Paper trading portfolio overview
          </p>
        </div>
        <button
          onClick={fetchData}
          className="flex items-center gap-2 px-4 py-2 rounded-lg bg-secondary hover:bg-secondary/80 transition-colors"
        >
          <RefreshCw className={cn("w-4 h-4", loading && "animate-spin")} />
          Refresh
        </button>
      </div>

      {/* Error State */}
      {error && (
        <div className="mb-6 p-4 rounded-lg bg-destructive/10 border border-destructive/20 flex items-center gap-3">
          <AlertTriangle className="w-5 h-5 text-destructive" />
          <p className="text-sm text-destructive">{error}</p>
        </div>
      )}

      {/* Metrics Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
        <MetricCard
          title="Portfolio Value"
          value={formatCurrency(portfolio?.total_value || 100000)}
          icon={DollarSign}
          loading={loading}
        />
        <MetricCard
          title="Total P&L"
          value={formatCurrency(portfolio?.total_pnl || 0)}
          subValue={formatPercent(portfolio?.total_pnl_pct || 0)}
          icon={portfolio?.total_pnl && portfolio.total_pnl > 0 ? TrendingUp : TrendingDown}
          valueClassName={getReturnColor(portfolio?.total_pnl || 0)}
          loading={loading}
        />
        <MetricCard
          title="Available Cash"
          value={formatCurrency(portfolio?.current_cash || 100000)}
          icon={DollarSign}
          loading={loading}
        />
        <MetricCard
          title="Positions"
          value={String(portfolio?.positions_count || 0)}
          icon={Percent}
          loading={loading}
        />
      </div>

      {/* Main Content Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Equity Chart */}
        <div className="lg:col-span-2 bg-card rounded-xl border border-border p-6">
          <h2 className="text-lg font-medium mb-4">Portfolio Performance</h2>
          <EquityChart />
        </div>

        {/* Recommendations */}
        <div className="bg-card rounded-xl border border-border p-6">
          <h2 className="text-lg font-medium mb-4">Today's Signals</h2>

          {loading ? (
            <div className="animate-pulse space-y-3">
              {[1, 2, 3, 4, 5].map((i) => (
                <div key={i} className="h-10 bg-muted rounded" />
              ))}
            </div>
          ) : recommendations ? (
            <div className="space-y-4">
              <div>
                <h3 className="text-sm font-medium text-positive mb-2">Buy Signals</h3>
                <div className="space-y-2">
                  {recommendations.buy.slice(0, 5).map((rec) => (
                    <div
                      key={rec.ticker}
                      className="flex items-center justify-between p-2 rounded-lg bg-muted/50"
                    >
                      <span className="font-medium">{rec.ticker}</span>
                      <span className="text-sm text-muted-foreground tabular-nums">
                        {(rec.signal * 100).toFixed(0)}
                      </span>
                    </div>
                  ))}
                </div>
              </div>

              <div>
                <h3 className="text-sm font-medium text-negative mb-2">Sell Signals</h3>
                <div className="space-y-2">
                  {recommendations.sell.slice(0, 3).map((rec) => (
                    <div
                      key={rec.ticker}
                      className="flex items-center justify-between p-2 rounded-lg bg-muted/50"
                    >
                      <span className="font-medium">{rec.ticker}</span>
                      <span className="text-sm text-muted-foreground tabular-nums">
                        {(rec.signal * 100).toFixed(0)}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">No recommendations available</p>
          )}

          <p className="mt-4 text-xs text-muted-foreground">
            Signals from momentum model. For educational purposes only.
          </p>
        </div>
      </div>

      {/* Disclaimer */}
      <div className="mt-8 p-4 rounded-lg bg-muted/50 border border-border">
        <p className="text-xs text-muted-foreground">
          <strong>Disclaimer:</strong> This is a paper trading simulation for educational
          purposes only. All trades are simulated with no real money involved. Past
          performance does not indicate future results. This is not financial advice.
        </p>
      </div>
    </div>
  );
}

interface MetricCardProps {
  title: string;
  value: string;
  subValue?: string;
  icon: React.ComponentType<{ className?: string }>;
  valueClassName?: string;
  loading?: boolean;
}

function MetricCard({
  title,
  value,
  subValue,
  icon: Icon,
  valueClassName,
  loading,
}: MetricCardProps) {
  return (
    <div className="bg-card rounded-xl border border-border p-6 card-hover">
      <div className="flex items-center justify-between mb-4">
        <span className="text-sm text-muted-foreground">{title}</span>
        <Icon className="w-5 h-5 text-muted-foreground" />
      </div>
      {loading ? (
        <div className="animate-pulse">
          <div className="h-8 bg-muted rounded w-2/3" />
        </div>
      ) : (
        <div>
          <span className={cn("text-2xl font-semibold tabular-nums", valueClassName)}>
            {value}
          </span>
          {subValue && (
            <span className={cn("ml-2 text-sm", valueClassName)}>{subValue}</span>
          )}
        </div>
      )}
    </div>
  );
}
