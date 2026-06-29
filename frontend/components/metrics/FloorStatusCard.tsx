"use client";

import { TrendingUp, TrendingDown, AlertTriangle } from "lucide-react";
import { cn } from "@/lib/utils";

export interface FloorStatusData {
  meets_floor: boolean;
  floor_usd: number;
  avg_weekly_pnl_usd: number | null;
  weeks_counted: number;
  total_trades: number;
}

function fmt(v: number | null, prefix = "$"): string {
  if (v === null || v === undefined) return "—";
  return `${prefix}${v.toFixed(2)}`;
}

export function FloorStatusCard({ data }: { data: FloorStatusData }) {
  const met = data.meets_floor;
  const avg = data.avg_weekly_pnl_usd;
  const floorUsd = data.floor_usd ?? 2000;

  return (
    <div className={cn(
      "glass-card p-5 border-l-4",
      met ? "border-l-green-500" : "border-l-red-500"
    )}>
      <div className="flex items-start justify-between mb-3">
        <div>
          <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">
            Go-Live Floor
          </span>
          <p className={cn(
            "text-sm font-bold mt-0.5",
            met ? "text-green-500" : "text-red-500"
          )}>
            {met ? "FLOOR MET" : "Floor NOT MET"}
          </p>
        </div>
        {met
          ? <TrendingUp className="w-5 h-5 text-green-500 flex-shrink-0" />
          : <AlertTriangle className="w-5 h-5 text-red-500 flex-shrink-0" />
        }
      </div>

      <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-[11px]">
        <div>
          <span className="text-muted-foreground">Avg weekly P&L</span>
          <p className={cn(
            "font-bold tabular-nums",
            avg === null ? "text-muted-foreground" :
              avg >= floorUsd ? "text-green-500" : "text-red-500"
          )}>
            {avg !== null ? fmt(avg) : "—"}
          </p>
        </div>
        <div>
          <span className="text-muted-foreground">Required floor</span>
          <p className="font-bold tabular-nums text-foreground">{fmt(floorUsd)}/wk</p>
        </div>
        <div>
          <span className="text-muted-foreground">Weeks counted</span>
          <p className="font-bold tabular-nums text-foreground">{data.weeks_counted}</p>
        </div>
        <div>
          <span className="text-muted-foreground">Total trades</span>
          <p className={cn(
            "font-bold tabular-nums",
            data.total_trades === 0 ? "text-muted-foreground italic" : "text-foreground"
          )}>
            {data.total_trades === 0 ? "No resolved trades" : data.total_trades}
          </p>
        </div>
      </div>

      {!met && (
        <p className="mt-3 text-[10px] text-red-400/80 bg-red-500/5 border border-red-500/10 rounded-md px-2.5 py-1.5">
          Not eligible for go-live. Avg weekly P&L ({avg !== null ? fmt(avg) : "—"}) is below the
          required floor of {fmt(floorUsd)}/week.
        </p>
      )}
    </div>
  );
}
