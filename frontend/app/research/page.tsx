"use client";

import { useState } from "react";
import {
  Play,
  Settings,
  FileText,
  AlertCircle,
  CheckCircle,
  Loader2,
} from "lucide-react";
import { cn } from "@/lib/utils";

export default function ResearchPage() {
  const [running, setRunning] = useState(false);
  const [results, setResults] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  const [config, setConfig] = useState({
    universe: "liquid_50",
    rebalanceFrequency: "weekly",
    maxPosition: 10,
    targetVol: 15,
    costBps: 10,
  });

  async function runBacktest() {
    setRunning(true);
    setError(null);
    setResults(null);

    try {
      const response = await fetch("/api/backtest/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          universe_name: config.universe,
          rebalance_frequency: config.rebalanceFrequency,
          max_position_weight: config.maxPosition / 100,
          target_volatility: config.targetVol / 100,
          transaction_cost_bps: config.costBps,
        }),
      });

      if (!response.ok) {
        throw new Error("Backtest failed");
      }

      const data = await response.json();
      setResults(data);
    } catch (err) {
      setError("Failed to run backtest. Is the backend running?");
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="p-8">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-2xl font-semibold">Research Lab</h1>
        <p className="text-muted-foreground mt-1">
          Configure and run backtests to evaluate strategies
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Configuration Panel */}
        <div className="bg-card rounded-xl border border-border p-6">
          <div className="flex items-center gap-2 mb-6">
            <Settings className="w-5 h-5" />
            <h2 className="text-lg font-medium">Configuration</h2>
          </div>

          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium mb-2">Universe</label>
              <select
                value={config.universe}
                onChange={(e) => setConfig({ ...config, universe: e.target.value })}
                className="w-full p-2 rounded-lg border border-border bg-background"
              >
                <option value="liquid_50">Liquid 50 (Default)</option>
              </select>
            </div>

            <div>
              <label className="block text-sm font-medium mb-2">
                Rebalance Frequency
              </label>
              <select
                value={config.rebalanceFrequency}
                onChange={(e) =>
                  setConfig({ ...config, rebalanceFrequency: e.target.value })
                }
                className="w-full p-2 rounded-lg border border-border bg-background"
              >
                <option value="daily">Daily</option>
                <option value="weekly">Weekly</option>
                <option value="monthly">Monthly</option>
              </select>
            </div>

            <div>
              <label className="block text-sm font-medium mb-2">
                Max Position (%)
              </label>
              <input
                type="number"
                value={config.maxPosition}
                onChange={(e) =>
                  setConfig({ ...config, maxPosition: parseInt(e.target.value) })
                }
                className="w-full p-2 rounded-lg border border-border bg-background"
              />
            </div>

            <div>
              <label className="block text-sm font-medium mb-2">
                Target Volatility (%)
              </label>
              <input
                type="number"
                value={config.targetVol}
                onChange={(e) =>
                  setConfig({ ...config, targetVol: parseInt(e.target.value) })
                }
                className="w-full p-2 rounded-lg border border-border bg-background"
              />
            </div>

            <div>
              <label className="block text-sm font-medium mb-2">
                Transaction Cost (bps)
              </label>
              <input
                type="number"
                value={config.costBps}
                onChange={(e) =>
                  setConfig({ ...config, costBps: parseInt(e.target.value) })
                }
                className="w-full p-2 rounded-lg border border-border bg-background"
              />
            </div>

            <button
              onClick={runBacktest}
              disabled={running}
              className={cn(
                "w-full flex items-center justify-center gap-2 px-4 py-3 rounded-lg font-medium transition-colors",
                running
                  ? "bg-muted text-muted-foreground cursor-not-allowed"
                  : "bg-primary text-primary-foreground hover:bg-primary/90"
              )}
            >
              {running ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Running...
                </>
              ) : (
                <>
                  <Play className="w-4 h-4" />
                  Run Backtest
                </>
              )}
            </button>
          </div>
        </div>

        {/* Results Panel */}
        <div className="lg:col-span-2 bg-card rounded-xl border border-border p-6">
          <div className="flex items-center gap-2 mb-6">
            <FileText className="w-5 h-5" />
            <h2 className="text-lg font-medium">Results</h2>
          </div>

          {error && (
            <div className="p-4 rounded-lg bg-destructive/10 border border-destructive/20 flex items-center gap-3">
              <AlertCircle className="w-5 h-5 text-destructive" />
              <p className="text-sm text-destructive">{error}</p>
            </div>
          )}

          {!results && !error && !running && (
            <div className="h-64 flex items-center justify-center text-muted-foreground">
              <p>Configure parameters and run a backtest to see results</p>
            </div>
          )}

          {running && (
            <div className="h-64 flex flex-col items-center justify-center gap-4">
              <Loader2 className="w-8 h-8 animate-spin text-primary" />
              <p className="text-muted-foreground">
                Running backtest... This may take a minute.
              </p>
            </div>
          )}

          {results && (
            <div className="space-y-6">
              {/* Metrics Grid */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <MetricBox
                  label="Total Return"
                  value={`${(results.metrics.total_return * 100).toFixed(1)}%`}
                  positive={results.metrics.total_return > 0}
                />
                <MetricBox
                  label="CAGR"
                  value={`${(results.metrics.cagr * 100).toFixed(1)}%`}
                  positive={results.metrics.cagr > 0}
                />
                <MetricBox
                  label="Sharpe Ratio"
                  value={results.metrics.sharpe_ratio.toFixed(2)}
                  positive={results.metrics.sharpe_ratio > 0.5}
                />
                <MetricBox
                  label="Max Drawdown"
                  value={`${(results.metrics.max_drawdown * 100).toFixed(1)}%`}
                  positive={results.metrics.max_drawdown > -0.2}
                />
              </div>

              {/* Validation */}
              <div className="p-4 rounded-lg bg-muted/50">
                <h3 className="font-medium mb-2">Model Validation</h3>
                <div className="grid grid-cols-3 gap-4 text-sm">
                  <div>
                    <span className="text-muted-foreground">Mean Score: </span>
                    <span className="font-medium">
                      {results.validation.mean_score.toFixed(4)}
                    </span>
                  </div>
                  <div>
                    <span className="text-muted-foreground">Std: </span>
                    <span className="font-medium">
                      {results.validation.std_score.toFixed(4)}
                    </span>
                  </div>
                  <div>
                    <span className="text-muted-foreground">Folds: </span>
                    <span className="font-medium">{results.validation.n_folds}</span>
                  </div>
                </div>
              </div>

              {/* Success Indicator */}
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <CheckCircle className="w-4 h-4 text-positive" />
                Backtest completed with {results.n_trades} trades
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Educational Note */}
      <div className="mt-8 p-4 rounded-lg bg-muted/50 border border-border">
        <h3 className="font-medium mb-2">Research Best Practices</h3>
        <ul className="text-sm text-muted-foreground space-y-1 list-disc list-inside">
          <li>Always use walk-forward validation, not random train/test splits</li>
          <li>Expect 30-50% performance degradation in live trading vs backtest</li>
          <li>High Sharpe ratios (>2) should be scrutinized for data issues</li>
          <li>Transaction costs of 10+ bps are realistic for retail traders</li>
        </ul>
      </div>
    </div>
  );
}

function MetricBox({
  label,
  value,
  positive,
}: {
  label: string;
  value: string;
  positive: boolean;
}) {
  return (
    <div className="p-4 rounded-lg bg-muted/50">
      <div className="text-xs text-muted-foreground mb-1">{label}</div>
      <div
        className={cn(
          "text-xl font-semibold tabular-nums",
          positive ? "text-positive" : "text-negative"
        )}
      >
        {value}
      </div>
    </div>
  );
}
