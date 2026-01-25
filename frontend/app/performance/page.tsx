"use client";

import { useState } from "react";
import { cn, formatPercent } from "@/lib/utils";
import { EquityChart } from "@/components/charts/equity-chart";

// Demo metrics
const demoMetrics = {
  total_return: 0.23,
  cagr: 0.18,
  volatility: 0.15,
  sharpe_ratio: 1.2,
  sortino_ratio: 1.8,
  calmar_ratio: 2.1,
  max_drawdown: -0.12,
  win_rate: 0.54,
  profit_factor: 1.4,
  alpha: 0.08,
  beta: 0.85,
  tracking_error: 0.06,
};

const tabs = [
  { id: "overview", name: "Overview" },
  { id: "returns", name: "Returns" },
  { id: "risk", name: "Risk" },
  { id: "attribution", name: "Attribution" },
];

export default function PerformancePage() {
  const [activeTab, setActiveTab] = useState("overview");

  return (
    <div className="p-8">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-2xl font-semibold">Performance Analysis</h1>
        <p className="text-muted-foreground mt-1">
          Track portfolio performance and risk metrics
        </p>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-6 p-1 bg-muted rounded-lg w-fit">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={cn(
              "px-4 py-2 rounded-md text-sm font-medium transition-colors",
              activeTab === tab.id
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            {tab.name}
          </button>
        ))}
      </div>

      {/* Content */}
      {activeTab === "overview" && (
        <div className="space-y-6">
          {/* Equity Chart */}
          <div className="bg-card rounded-xl border border-border p-6">
            <h2 className="text-lg font-medium mb-4">Equity Curve</h2>
            <EquityChart />
          </div>

          {/* Key Metrics */}
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4">
            <MetricCard
              label="Total Return"
              value={formatPercent(demoMetrics.total_return)}
              positive={demoMetrics.total_return > 0}
            />
            <MetricCard
              label="CAGR"
              value={formatPercent(demoMetrics.cagr)}
              positive={demoMetrics.cagr > 0}
            />
            <MetricCard
              label="Volatility"
              value={formatPercent(demoMetrics.volatility)}
            />
            <MetricCard
              label="Sharpe Ratio"
              value={demoMetrics.sharpe_ratio.toFixed(2)}
              positive={demoMetrics.sharpe_ratio > 0.5}
            />
            <MetricCard
              label="Max Drawdown"
              value={formatPercent(demoMetrics.max_drawdown)}
              positive={demoMetrics.max_drawdown > -0.2}
            />
            <MetricCard
              label="Win Rate"
              value={formatPercent(demoMetrics.win_rate)}
              positive={demoMetrics.win_rate > 0.5}
            />
          </div>
        </div>
      )}

      {activeTab === "returns" && (
        <div className="space-y-6">
          <div className="bg-card rounded-xl border border-border p-6">
            <h2 className="text-lg font-medium mb-4">Returns Analysis</h2>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-6">
              <div>
                <div className="text-sm text-muted-foreground mb-1">Total Return</div>
                <div className="text-2xl font-semibold text-positive">
                  {formatPercent(demoMetrics.total_return)}
                </div>
              </div>
              <div>
                <div className="text-sm text-muted-foreground mb-1">CAGR</div>
                <div className="text-2xl font-semibold text-positive">
                  {formatPercent(demoMetrics.cagr)}
                </div>
              </div>
              <div>
                <div className="text-sm text-muted-foreground mb-1">Best Month</div>
                <div className="text-2xl font-semibold text-positive">+8.2%</div>
              </div>
              <div>
                <div className="text-sm text-muted-foreground mb-1">Worst Month</div>
                <div className="text-2xl font-semibold text-negative">-5.3%</div>
              </div>
            </div>
          </div>

          <div className="bg-card rounded-xl border border-border p-6">
            <h2 className="text-lg font-medium mb-4">Monthly Returns</h2>
            <div className="h-64 flex items-center justify-center text-muted-foreground">
              Monthly returns heatmap would go here
            </div>
          </div>
        </div>
      )}

      {activeTab === "risk" && (
        <div className="space-y-6">
          <div className="bg-card rounded-xl border border-border p-6">
            <h2 className="text-lg font-medium mb-4">Risk Metrics</h2>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-6">
              <div>
                <div className="text-sm text-muted-foreground mb-1">Volatility</div>
                <div className="text-2xl font-semibold">
                  {formatPercent(demoMetrics.volatility)}
                </div>
              </div>
              <div>
                <div className="text-sm text-muted-foreground mb-1">Max Drawdown</div>
                <div className="text-2xl font-semibold text-negative">
                  {formatPercent(demoMetrics.max_drawdown)}
                </div>
              </div>
              <div>
                <div className="text-sm text-muted-foreground mb-1">Sharpe Ratio</div>
                <div className="text-2xl font-semibold">
                  {demoMetrics.sharpe_ratio.toFixed(2)}
                </div>
              </div>
              <div>
                <div className="text-sm text-muted-foreground mb-1">Sortino Ratio</div>
                <div className="text-2xl font-semibold">
                  {demoMetrics.sortino_ratio.toFixed(2)}
                </div>
              </div>
              <div>
                <div className="text-sm text-muted-foreground mb-1">Calmar Ratio</div>
                <div className="text-2xl font-semibold">
                  {demoMetrics.calmar_ratio.toFixed(2)}
                </div>
              </div>
              <div>
                <div className="text-sm text-muted-foreground mb-1">Beta</div>
                <div className="text-2xl font-semibold">
                  {demoMetrics.beta.toFixed(2)}
                </div>
              </div>
              <div>
                <div className="text-sm text-muted-foreground mb-1">VaR (95%)</div>
                <div className="text-2xl font-semibold text-negative">-2.1%</div>
              </div>
              <div>
                <div className="text-sm text-muted-foreground mb-1">VaR (99%)</div>
                <div className="text-2xl font-semibold text-negative">-3.2%</div>
              </div>
            </div>
          </div>

          <div className="bg-card rounded-xl border border-border p-6">
            <h2 className="text-lg font-medium mb-4">Drawdown Analysis</h2>
            <div className="h-48 flex items-center justify-center text-muted-foreground">
              Drawdown chart would go here
            </div>
          </div>
        </div>
      )}

      {activeTab === "attribution" && (
        <div className="space-y-6">
          <div className="bg-card rounded-xl border border-border p-6">
            <h2 className="text-lg font-medium mb-4">Return Attribution</h2>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-6">
              <div>
                <div className="text-sm text-muted-foreground mb-1">Alpha</div>
                <div className="text-2xl font-semibold text-positive">
                  {formatPercent(demoMetrics.alpha)}
                </div>
              </div>
              <div>
                <div className="text-sm text-muted-foreground mb-1">Market (Beta)</div>
                <div className="text-2xl font-semibold">+12.3%</div>
              </div>
              <div>
                <div className="text-sm text-muted-foreground mb-1">Momentum</div>
                <div className="text-2xl font-semibold text-positive">+3.2%</div>
              </div>
              <div>
                <div className="text-sm text-muted-foreground mb-1">Residual</div>
                <div className="text-2xl font-semibold">+1.8%</div>
              </div>
            </div>
          </div>

          <div className="bg-card rounded-xl border border-border p-6">
            <h2 className="text-lg font-medium mb-4">Information Ratio</h2>
            <div className="grid grid-cols-2 gap-6">
              <div>
                <div className="text-sm text-muted-foreground mb-1">Tracking Error</div>
                <div className="text-2xl font-semibold">
                  {formatPercent(demoMetrics.tracking_error)}
                </div>
              </div>
              <div>
                <div className="text-sm text-muted-foreground mb-1">Information Ratio</div>
                <div className="text-2xl font-semibold">
                  {(demoMetrics.alpha / demoMetrics.tracking_error).toFixed(2)}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Educational Note */}
      <div className="mt-8 p-4 rounded-lg bg-muted/50 border border-border">
        <h3 className="font-medium mb-2">Interpreting Metrics</h3>
        <ul className="text-sm text-muted-foreground space-y-1 list-disc list-inside">
          <li>Sharpe > 1 is generally considered good; > 2 is excellent (and rare)</li>
          <li>Max drawdown shows worst-case scenario - can you handle that emotionally?</li>
          <li>Alpha represents skill; Beta represents market exposure</li>
          <li>Information Ratio > 0.5 suggests genuine stock selection ability</li>
        </ul>
      </div>
    </div>
  );
}

function MetricCard({
  label,
  value,
  positive,
}: {
  label: string;
  value: string;
  positive?: boolean;
}) {
  return (
    <div className="bg-card rounded-xl border border-border p-4">
      <div className="text-xs text-muted-foreground mb-1">{label}</div>
      <div
        className={cn(
          "text-xl font-semibold tabular-nums",
          positive !== undefined && (positive ? "text-positive" : "text-negative")
        )}
      >
        {value}
      </div>
    </div>
  );
}
