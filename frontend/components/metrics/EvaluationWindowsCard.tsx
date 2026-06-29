"use client";

import { ChevronDown } from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/utils";

export interface WindowMetrics {
  realized_pnl_usd: number | null;
  num_trades: number;
  num_wins: number;
  hit_rate: number | null;
  max_drawdown_usd: number | null;
  max_drawdown_pct: number | null;
  brier_score: number | null;
  brier_n: number;
}

export interface EvalWindow {
  window_start: string;
  window_end: string;
  configs: Record<string, unknown>;
  trades: unknown[];
  metrics: WindowMetrics;
}

export interface EvaluationWindowsData {
  source: string;
  num_input_trades: number;
  num_windows: number;
  windows: EvalWindow[];
}

function fmt(v: number | null, prefix = "$", decimals = 2): string {
  if (v === null || v === undefined) return "—";
  return `${prefix}${v.toFixed(decimals)}`;
}

function fmtPct(v: number | null): string {
  if (v === null || v === undefined) return "—";
  return `${(v * 100).toFixed(1)}%`;
}

function WindowRow({ win }: { win: EvalWindow }) {
  const [open, setOpen] = useState(false);
  const m = win.metrics;
  const noTrades = m.num_trades === 0;

  return (
    <div className="border-b border-border/20">
      <button
        onClick={() => setOpen(!open)}
        className="w-full px-4 py-3 flex items-center gap-3 hover:bg-muted/20 transition-colors text-left"
      >
        <ChevronDown className={cn("w-3.5 h-3.5 text-muted-foreground flex-shrink-0 transition-transform", open && "rotate-180")} />
        <div className="flex-1 grid grid-cols-2 lg:grid-cols-5 gap-3 text-[11px]">
          <div>
            <span className="font-mono text-muted-foreground">
              {win.window_start.slice(0, 10)} → {win.window_end.slice(0, 10)}
            </span>
          </div>
          <div>
            <span className="text-muted-foreground">Trades </span>
            <span className={cn("font-semibold", noTrades ? "text-muted-foreground italic" : "text-foreground")}>
              {noTrades ? "none" : m.num_trades}
            </span>
          </div>
          <div>
            <span className="text-muted-foreground">P&L </span>
            <span className={cn(
              "font-semibold tabular-nums",
              m.realized_pnl_usd === null || noTrades ? "text-muted-foreground" :
                m.realized_pnl_usd >= 0 ? "text-green-500" : "text-red-500"
            )}>
              {noTrades ? "—" : fmt(m.realized_pnl_usd)}
            </span>
          </div>
          <div>
            <span className="text-muted-foreground">Hit Rate </span>
            <span className="font-semibold text-foreground">{noTrades ? "—" : fmtPct(m.hit_rate)}</span>
          </div>
          <div>
            <span className="text-muted-foreground">Brier </span>
            <span className="font-semibold text-foreground">
              {m.brier_score !== null ? m.brier_score.toFixed(4) : "—"}
            </span>
          </div>
        </div>
      </button>

      {open && (
        <div className="px-4 pb-3 pt-0 bg-muted/10">
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 text-[11px] pl-6">
            <div>
              <span className="text-muted-foreground">Wins</span>
              <p className="font-bold text-foreground">{m.num_wins}</p>
            </div>
            <div>
              <span className="text-muted-foreground">Max drawdown</span>
              <p className="font-bold tabular-nums text-red-400">{fmt(m.max_drawdown_usd)}</p>
            </div>
            <div>
              <span className="text-muted-foreground">Max DD %</span>
              <p className="font-bold tabular-nums text-red-400">{fmtPct(m.max_drawdown_pct)}</p>
            </div>
            <div>
              <span className="text-muted-foreground">Brier n</span>
              <p className="font-bold tabular-nums text-foreground">{m.brier_n}</p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export function EvaluationWindowsCard({ data }: { data: EvaluationWindowsData }) {
  const hasWindows = data.windows.length > 0;
  const hasData = data.num_input_trades > 0;

  return (
    <div className="glass-card overflow-hidden">
      <div className="px-5 py-3 border-b border-border/60 flex items-center justify-between">
        <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">
          Evaluation Windows
        </span>
        <div className="flex items-center gap-2">
          {!hasData && (
            <span className="text-[10px] text-amber-400 bg-amber-500/10 px-2 py-0.5 rounded-full font-medium">
              No resolved trades yet
            </span>
          )}
          <span className="text-[10px] font-bold text-muted-foreground tabular-nums px-1.5 py-0.5 bg-muted rounded-md">
            {data.num_windows} window{data.num_windows !== 1 ? "s" : ""}
          </span>
        </div>
      </div>

      {hasWindows ? (
        <div className="max-h-[400px] overflow-y-auto">
          {data.windows.map((win, i) => (
            <WindowRow key={i} win={win} />
          ))}
        </div>
      ) : (
        <div className="py-12 text-center">
          <p className="text-sm text-foreground font-medium">No evaluation windows yet</p>
          <p className="text-xs text-muted-foreground mt-1">
            Windows appear once enough data accumulates (requires resolved trades).
          </p>
        </div>
      )}
    </div>
  );
}
