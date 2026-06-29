"use client";

import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from "recharts";
import { TrendingUp } from "lucide-react";
import { cn } from "@/lib/utils";

export interface WeeklySeriesEntry {
  week_start: string;
  realized_pnl_usd: number | null;
  num_trades: number;
  num_wins: number;
  hit_rate: number | null;
  cumulative_pnl_usd: number | null;
}

export interface WeeklyMetricsData {
  source: string;
  num_input_trades: number;
  total_pnl_usd: number | null;
  avg_weekly_pnl_usd: number | null;
  weekly_sharpe: number | null;
  max_drawdown_usd: number | null;
  max_drawdown_pct: number | null;
  hit_rate: number | null;
  total_trades: number;
  best_week_usd: number | null;
  worst_week_usd: number | null;
  num_weeks: number;
  weekly_series: WeeklySeriesEntry[];
}

function fmt(v: number | null, prefix = "$", decimals = 2): string {
  if (v === null || v === undefined) return "—";
  return `${prefix}${v.toFixed(decimals)}`;
}

function fmtPct(v: number | null): string {
  if (v === null || v === undefined) return "—";
  return `${(v * 100).toFixed(1)}%`;
}

export function WeeklyMetricsCard({ data }: { data: WeeklyMetricsData }) {
  const hasData = data.total_trades > 0;
  const hasSeries = data.weekly_series.length > 0;

  const chartData = data.weekly_series.map((w) => ({
    week: w.week_start.slice(5), // MM-DD
    pnl: w.realized_pnl_usd,
    cumPnl: w.cumulative_pnl_usd,
  }));

  return (
    <div className="glass-card p-5">
      <div className="flex items-center justify-between mb-4">
        <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">
          Weekly Performance
        </span>
        {!hasData && (
          <span className="text-[10px] text-amber-400 bg-amber-500/10 px-2 py-0.5 rounded-full font-medium">
            No resolved trades yet
          </span>
        )}
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-3 lg:grid-cols-6 gap-3 mb-5">
        {[
          { label: "Total P&L", value: hasData ? fmt(data.total_pnl_usd) : "—", color: data.total_pnl_usd !== null && data.total_pnl_usd >= 0 ? "text-green-500" : "text-red-500" },
          { label: "Avg Weekly", value: hasData ? fmt(data.avg_weekly_pnl_usd) : "—", color: "text-foreground" },
          { label: "Sharpe (wkly)", value: hasData ? fmt(data.weekly_sharpe, "", 3) : "—", color: "text-foreground" },
          { label: "Hit Rate", value: hasData ? fmtPct(data.hit_rate) : "—", color: "text-foreground" },
          { label: "Max Drawdown", value: hasData ? fmt(data.max_drawdown_usd) : "—", color: hasData ? "text-red-400" : "text-muted-foreground" },
          { label: "Weeks", value: String(data.num_weeks), color: "text-foreground" },
        ].map((stat) => (
          <div key={stat.label} className="bg-muted/40 rounded-lg px-3 py-2">
            <span className="text-[10px] text-muted-foreground block mb-0.5">{stat.label}</span>
            <span className={cn("text-sm font-bold tabular-nums", !hasData ? "text-muted-foreground" : stat.color)}>
              {stat.value}
            </span>
          </div>
        ))}
      </div>

      {/* Chart */}
      {hasSeries ? (
        <div className="h-40">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
              <XAxis
                dataKey="week"
                tick={{ fontSize: 10 }}
                className="text-muted-foreground"
              />
              <YAxis
                // Always include $0 in the domain so the zero reference line is visible
                // and gains/losses are not visually exaggerated by a series-min baseline
                // (a P&L axis floated off zero misreads a small loss as a large one).
                domain={[
                  (dataMin: number) => Math.min(0, Number.isFinite(dataMin) ? dataMin : 0),
                  (dataMax: number) => Math.max(0, Number.isFinite(dataMax) ? dataMax : 0),
                ]}
                tick={{ fontSize: 10 }}
                tickFormatter={(v) => `$${v}`}
                width={56}
                label={{
                  value: "P&L ($)",
                  angle: -90,
                  position: "insideLeft",
                  style: { fontSize: 10, textAnchor: "middle", fill: "hsl(var(--muted-foreground))" },
                }}
                className="text-muted-foreground"
              />
              <ReferenceLine y={0} stroke="hsl(var(--border))" strokeDasharray="4 2" />
              <Tooltip
                contentStyle={{
                  backgroundColor: "hsl(var(--card))",
                  border: "1px solid hsl(var(--border))",
                  borderRadius: "8px",
                  fontSize: "11px",
                }}
                formatter={(value, name) => [
                  typeof value === "number" ? `$${value.toFixed(2)}` : "—",
                  name === "pnl" ? "Weekly P&L" : "Cumulative P&L",
                ]}
              />
              <Line
                type="monotone"
                dataKey="pnl"
                stroke="hsl(var(--primary))"
                strokeWidth={1.5}
                dot={{ r: 2.5 }}
                name="pnl"
              />
              <Line
                type="monotone"
                dataKey="cumPnl"
                stroke="hsl(var(--muted-foreground))"
                strokeWidth={1}
                dot={false}
                strokeDasharray="5 3"
                name="cumPnl"
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <div className="h-40 flex items-center justify-center rounded-lg bg-muted/20 border border-dashed border-border/60">
          <div className="text-center">
            <TrendingUp className="w-6 h-6 text-muted-foreground mx-auto mb-1.5" />
            <p className="text-xs text-muted-foreground">
              {hasData ? "Insufficient weekly data for chart" : "No resolved trades — chart will populate once trades resolve"}
            </p>
          </div>
        </div>
      )}

      {hasSeries && (
        <div className="mt-4">
          <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider mb-2">
            Weekly Breakdown
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-[11px]">
              <thead>
                <tr className="border-b border-border/40">
                  {["Week", "Trades", "Wins", "Hit Rate", "P&L", "Cumulative"].map((h) => (
                    <th key={h} className="text-left text-[10px] text-muted-foreground font-semibold uppercase tracking-wider py-1.5 pr-3 whitespace-nowrap">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.weekly_series.map((w) => (
                  <tr key={w.week_start} className="border-b border-border/20 hover:bg-muted/20">
                    <td className="py-1.5 pr-3 font-mono text-muted-foreground">{w.week_start}</td>
                    <td className="py-1.5 pr-3 tabular-nums text-foreground">{w.num_trades}</td>
                    <td className="py-1.5 pr-3 tabular-nums text-foreground">{w.num_wins}</td>
                    <td className="py-1.5 pr-3 tabular-nums text-foreground">{fmtPct(w.hit_rate)}</td>
                    <td className={cn(
                      "py-1.5 pr-3 tabular-nums font-semibold",
                      w.realized_pnl_usd === null ? "text-muted-foreground" :
                        w.realized_pnl_usd >= 0 ? "text-green-500" : "text-red-500"
                    )}>
                      {fmt(w.realized_pnl_usd)}
                    </td>
                    <td className="py-1.5 pr-3 tabular-nums text-foreground">{fmt(w.cumulative_pnl_usd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
