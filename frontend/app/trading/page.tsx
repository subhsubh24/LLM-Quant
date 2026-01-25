"use client";

import { useState, useEffect } from "react";
import {
  ArrowUpRight,
  ArrowDownRight,
  RefreshCw,
  CheckCircle,
  XCircle,
} from "lucide-react";
import { cn, formatCurrency } from "@/lib/utils";

interface Position {
  ticker: string;
  shares: number;
  avg_cost: number;
  current_price: number;
  market_value: number;
  unrealized_pnl: number;
  weight: number;
}

interface Recommendation {
  ticker: string;
  signal: number;
  action: string;
}

export default function TradingPage() {
  const [portfolio, setPortfolio] = useState<any>(null);
  const [recommendations, setRecommendations] = useState<{
    buy: Recommendation[];
    sell: Recommendation[];
  } | null>(null);
  const [loading, setLoading] = useState(true);
  const [executing, setExecuting] = useState<string | null>(null);

  useEffect(() => {
    fetchData();
  }, []);

  async function fetchData() {
    setLoading(true);
    try {
      // Fetch portfolio
      const portfolioRes = await fetch("/api/paper/portfolio/default");
      if (portfolioRes.ok) {
        setPortfolio(await portfolioRes.json());
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
      console.error("Failed to fetch data:", err);
    } finally {
      setLoading(false);
    }
  }

  function simulateTrade(ticker: string, action: string) {
    setExecuting(ticker);
    // Simulate execution delay
    setTimeout(() => {
      setExecuting(null);
      // In a real app, this would call the API and refresh data
    }, 1000);
  }

  return (
    <div className="p-8">
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-semibold">Paper Trading</h1>
          <p className="text-muted-foreground mt-1">
            Execute simulated trades based on model signals
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

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Recommendations */}
        <div className="bg-card rounded-xl border border-border p-6">
          <h2 className="text-lg font-medium mb-4">Recommended Trades</h2>

          {loading ? (
            <div className="animate-pulse space-y-3">
              {[1, 2, 3, 4, 5].map((i) => (
                <div key={i} className="h-16 bg-muted rounded" />
              ))}
            </div>
          ) : recommendations ? (
            <div className="space-y-6">
              {/* Buy Recommendations */}
              <div>
                <h3 className="text-sm font-medium text-positive mb-3 flex items-center gap-2">
                  <ArrowUpRight className="w-4 h-4" />
                  Buy Signals
                </h3>
                <div className="space-y-2">
                  {recommendations.buy.slice(0, 5).map((rec) => (
                    <div
                      key={rec.ticker}
                      className="flex items-center justify-between p-3 rounded-lg bg-muted/50 border border-border"
                    >
                      <div>
                        <span className="font-medium">{rec.ticker}</span>
                        <span className="ml-2 text-sm text-muted-foreground">
                          Score: {(rec.signal * 100).toFixed(0)}
                        </span>
                      </div>
                      <button
                        onClick={() => simulateTrade(rec.ticker, "buy")}
                        disabled={executing === rec.ticker}
                        className={cn(
                          "px-3 py-1.5 rounded-lg text-sm font-medium transition-colors",
                          executing === rec.ticker
                            ? "bg-muted text-muted-foreground"
                            : "bg-primary text-primary-foreground hover:bg-primary/90"
                        )}
                      >
                        {executing === rec.ticker ? "..." : "Buy"}
                      </button>
                    </div>
                  ))}
                </div>
              </div>

              {/* Sell Recommendations */}
              <div>
                <h3 className="text-sm font-medium text-negative mb-3 flex items-center gap-2">
                  <ArrowDownRight className="w-4 h-4" />
                  Sell Signals
                </h3>
                <div className="space-y-2">
                  {recommendations.sell.slice(0, 3).map((rec) => (
                    <div
                      key={rec.ticker}
                      className="flex items-center justify-between p-3 rounded-lg bg-muted/50 border border-border"
                    >
                      <div>
                        <span className="font-medium">{rec.ticker}</span>
                        <span className="ml-2 text-sm text-muted-foreground">
                          Score: {(rec.signal * 100).toFixed(0)}
                        </span>
                      </div>
                      <button
                        onClick={() => simulateTrade(rec.ticker, "sell")}
                        disabled={executing === rec.ticker}
                        className={cn(
                          "px-3 py-1.5 rounded-lg text-sm font-medium transition-colors",
                          executing === rec.ticker
                            ? "bg-muted text-muted-foreground"
                            : "bg-destructive text-destructive-foreground hover:bg-destructive/90"
                        )}
                      >
                        {executing === rec.ticker ? "..." : "Sell"}
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          ) : (
            <p className="text-muted-foreground">No recommendations available</p>
          )}
        </div>

        {/* Current Positions */}
        <div className="bg-card rounded-xl border border-border p-6">
          <h2 className="text-lg font-medium mb-4">Current Positions</h2>

          {loading ? (
            <div className="animate-pulse space-y-3">
              {[1, 2, 3, 4].map((i) => (
                <div key={i} className="h-16 bg-muted rounded" />
              ))}
            </div>
          ) : portfolio?.positions?.length > 0 ? (
            <div className="space-y-2">
              {portfolio.positions.map((pos: Position) => (
                <div
                  key={pos.ticker}
                  className="flex items-center justify-between p-3 rounded-lg bg-muted/50"
                >
                  <div>
                    <span className="font-medium">{pos.ticker}</span>
                    <span className="ml-2 text-sm text-muted-foreground">
                      {pos.shares.toFixed(0)} shares
                    </span>
                  </div>
                  <div className="text-right">
                    <div className="font-medium tabular-nums">
                      {formatCurrency(pos.market_value)}
                    </div>
                    <div
                      className={cn(
                        "text-sm tabular-nums",
                        pos.unrealized_pnl >= 0 ? "text-positive" : "text-negative"
                      )}
                    >
                      {pos.unrealized_pnl >= 0 ? "+" : ""}
                      {formatCurrency(pos.unrealized_pnl)}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="h-48 flex items-center justify-center text-muted-foreground">
              <p>No positions yet. Execute trades to build your portfolio.</p>
            </div>
          )}

          {portfolio && (
            <div className="mt-4 pt-4 border-t border-border">
              <div className="flex justify-between text-sm">
                <span className="text-muted-foreground">Available Cash</span>
                <span className="font-medium tabular-nums">
                  {formatCurrency(portfolio.current_cash)}
                </span>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Trade Execution Note */}
      <div className="mt-8 p-4 rounded-lg bg-muted/50 border border-border">
        <h3 className="font-medium mb-2">Paper Trading Notes</h3>
        <ul className="text-sm text-muted-foreground space-y-1 list-disc list-inside">
          <li>All trades are simulated - no real money is used</li>
          <li>Execution assumes end-of-day prices with 10bps costs</li>
          <li>Signals are generated by a momentum-based model</li>
          <li>This is for educational purposes only, not trading advice</li>
        </ul>
      </div>
    </div>
  );
}
