"use client";

import { cn } from "@/lib/utils";

export interface StrategyRow {
  strategy: string;
  num_trades: number;
  num_wins: number;
  total_pnl_usd: number | null;
  mean_pnl_usd: number | null;
  hit_rate: number | null;
  best_trade_usd: number | null;
  worst_trade_usd: number | null;
  weekly_pnl: Record<string, number>;
}

export interface PerStrategyData {
  source: string;
  num_input_trades: number;
  strategies: StrategyRow[];
  ranking: string[];
}

function fmt(v: number | null, prefix = "$", decimals = 2): string {
  if (v === null || v === undefined) return "—";
  return `${prefix}${v.toFixed(decimals)}`;
}

function fmtPct(v: number | null): string {
  if (v === null || v === undefined) return "—";
  return `${(v * 100).toFixed(1)}%`;
}

export function PerStrategyTable({ data }: { data: PerStrategyData }) {
  const hasData = data.num_input_trades > 0 && data.strategies.length > 0;

  return (
    <div className="glass-card p-5">
      <div className="flex items-center justify-between mb-4">
        <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">
          Per-Strategy Breakdown
        </span>
        {!hasData && (
          <span className="text-[10px] text-amber-400 bg-amber-500/10 px-2 py-0.5 rounded-full font-medium">
            No resolved trades yet
          </span>
        )}
      </div>

      {hasData ? (
        <div className="overflow-x-auto">
          <table className="w-full text-[11px]">
            <thead>
              <tr className="border-b border-border/60">
                {["Rank", "Strategy", "Trades", "Wins", "Hit Rate", "Total P&L", "Mean P&L", "Best", "Worst"].map((h) => (
                  <th key={h} className="text-left text-[10px] text-muted-foreground font-semibold uppercase tracking-wider py-2 pr-4 whitespace-nowrap">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.ranking.map((stratId, rankIdx) => {
                const row = data.strategies.find((s) => s.strategy === stratId);
                if (!row) return null;
                const rankDisplay = `#${rankIdx + 1}`;
                return (
                  <tr key={stratId} className="border-b border-border/20 hover:bg-muted/20 transition-colors">
                    <td className="py-2.5 pr-4 text-muted-foreground font-mono font-semibold">{rankDisplay}</td>
                    <td className="py-2.5 pr-4 font-medium text-foreground whitespace-nowrap">{stratId}</td>
                    <td className="py-2.5 pr-4 tabular-nums text-foreground">{row.num_trades}</td>
                    <td className="py-2.5 pr-4 tabular-nums text-foreground">{row.num_wins}</td>
                    <td className="py-2.5 pr-4 tabular-nums text-foreground">{fmtPct(row.hit_rate)}</td>
                    <td className={cn(
                      "py-2.5 pr-4 tabular-nums font-semibold",
                      row.total_pnl_usd === null ? "text-muted-foreground" :
                        row.total_pnl_usd >= 0 ? "text-green-500" : "text-red-500"
                    )}>
                      {fmt(row.total_pnl_usd)}
                    </td>
                    <td className={cn(
                      "py-2.5 pr-4 tabular-nums",
                      row.mean_pnl_usd === null ? "text-muted-foreground" :
                        row.mean_pnl_usd >= 0 ? "text-green-500" : "text-red-500"
                    )}>
                      {fmt(row.mean_pnl_usd)}
                    </td>
                    <td className="py-2.5 pr-4 tabular-nums text-green-500">{fmt(row.best_trade_usd)}</td>
                    <td className="py-2.5 pr-4 tabular-nums text-red-400">{fmt(row.worst_trade_usd)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="py-10 text-center">
          <p className="text-sm text-foreground font-medium">No strategy data available</p>
          <p className="text-xs text-muted-foreground mt-1">
            Strategy rankings will appear once paper trades resolve.
          </p>
        </div>
      )}
    </div>
  );
}
