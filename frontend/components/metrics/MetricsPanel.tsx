"use client";

import { useState, useEffect, useCallback } from "react";
import { RefreshCw, Loader2, AlertTriangle } from "lucide-react";
import { cn } from "@/lib/utils";

import { FloorStatusCard, FloorStatusData } from "./FloorStatusCard";
import { CalibrationCard, CalibrationData, DriftData } from "./CalibrationCard";
import { WeeklyMetricsCard, WeeklyMetricsData } from "./WeeklyMetricsCard";
import { PerStrategyTable, PerStrategyData } from "./PerStrategyTable";
import { EvaluationWindowsCard, EvaluationWindowsData } from "./EvaluationWindowsCard";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type FetchState<T> =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ok"; data: T }
  | { status: "error"; message: string };

function useFetch<T>(url: string, enabled: boolean) {
  const [state, setState] = useState<FetchState<T>>({ status: "idle" });

  const load = useCallback(async () => {
    setState({ status: "loading" });
    try {
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as T;
      setState({ status: "ok", data });
    } catch (e) {
      setState({ status: "error", message: e instanceof Error ? e.message : String(e) });
    }
  }, [url]);

  useEffect(() => {
    if (enabled) load();
  }, [enabled, load]);

  return { state, reload: load };
}

function LoadingCard() {
  return (
    <div className="glass-card p-5 space-y-3">
      <div className="skeleton h-3 w-28" />
      <div className="skeleton h-5 w-48" />
      <div className="grid grid-cols-2 gap-2">
        <div className="skeleton h-10 rounded-lg" />
        <div className="skeleton h-10 rounded-lg" />
      </div>
    </div>
  );
}

function ErrorCard({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="glass-card p-5">
      <div className="flex items-center gap-2 text-red-400">
        <AlertTriangle className="w-4 h-4 flex-shrink-0" />
        <span className="text-xs font-medium">Failed to load: {message}</span>
      </div>
      <button
        onClick={onRetry}
        className="mt-2 flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground transition-colors"
      >
        <RefreshCw className="w-3 h-3" /> Retry
      </button>
    </div>
  );
}

function Card<T>({ state, onRetry, render }: {
  state: FetchState<T>;
  onRetry: () => void;
  render: (data: T) => React.ReactNode;
}) {
  if (state.status === "idle" || state.status === "loading") return <LoadingCard />;
  if (state.status === "error") return <ErrorCard message={state.message} onRetry={onRetry} />;
  return <>{render(state.data)}</>;
}

export function MetricsPanel() {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  const weekly = useFetch<WeeklyMetricsData>(
    `${API_BASE}/prediction-markets/metrics/weekly`, mounted
  );
  const floor = useFetch<FloorStatusData>(
    `${API_BASE}/prediction-markets/metrics/floor-status`, mounted
  );
  const calibration = useFetch<CalibrationData>(
    `${API_BASE}/prediction-markets/metrics/calibration`, mounted
  );
  const perStrategy = useFetch<PerStrategyData>(
    `${API_BASE}/prediction-markets/metrics/per-strategy`, mounted
  );
  const evalWindows = useFetch<EvaluationWindowsData>(
    `${API_BASE}/prediction-markets/metrics/evaluation-windows`, mounted
  );
  const drift = useFetch<DriftData>(
    `${API_BASE}/prediction-markets/metrics/calibration-drift`, mounted
  );

  const allLoading = [weekly, floor, calibration, perStrategy, evalWindows, drift].every(
    (f) => f.state.status === "loading" || f.state.status === "idle"
  );

  const reloadAll = () => {
    weekly.reload();
    floor.reload();
    calibration.reload();
    perStrategy.reload();
    evalWindows.reload();
    drift.reload();
  };

  return (
    <div className="space-y-4 fade-in">
      {/* Header row */}
      <div className="flex items-center justify-between">
        <div>
          <p className="text-[10px] text-muted-foreground">
            Paper-trading metrics — real data, no simulation.
          </p>
        </div>
        <button
          onClick={reloadAll}
          disabled={allLoading}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-medium border border-border text-muted-foreground hover:text-foreground transition-colors disabled:opacity-50"
        >
          {allLoading
            ? <Loader2 className="w-3 h-3 animate-spin" />
            : <RefreshCw className="w-3 h-3" />
          }
          Refresh all
        </button>
      </div>

      {/* Honesty banner — shown when there are zero resolved trades */}
      {weekly.state.status === "ok" && weekly.state.data.total_trades === 0 && (
        <div className="glass-card px-4 py-3 flex items-start gap-2 border border-amber-500/20 bg-amber-500/5">
          <AlertTriangle className="w-4 h-4 text-amber-400 flex-shrink-0 mt-0.5" />
          <div>
            <p className="text-xs font-semibold text-amber-400">
              Insufficient data — 0 resolved trades
            </p>
            <p className="text-[11px] text-amber-400/70 mt-0.5">
              All metrics below reflect genuinely degenerate state. No edge, no P&L, and no
              calibration signal yet. Numbers will populate as paper trades resolve.
            </p>
          </div>
        </div>
      )}

      {/* Floor status + calibration side-by-side */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card
          state={floor.state}
          onRetry={floor.reload}
          render={(data) => <FloorStatusCard data={data} />}
        />
        <Card
          state={calibration.state}
          onRetry={calibration.reload}
          render={(calData) => (
            <CalibrationCard
              calibration={calData}
              drift={drift.state.status === "ok" ? drift.state.data : null}
            />
          )}
        />
      </div>

      {/* Weekly metrics */}
      <Card
        state={weekly.state}
        onRetry={weekly.reload}
        render={(data) => <WeeklyMetricsCard data={data} />}
      />

      {/* Per-strategy table */}
      <Card
        state={perStrategy.state}
        onRetry={perStrategy.reload}
        render={(data) => <PerStrategyTable data={data} />}
      />

      {/* Evaluation windows */}
      <Card
        state={evalWindows.state}
        onRetry={evalWindows.reload}
        render={(data) => <EvaluationWindowsCard data={data} />}
      />
    </div>
  );
}
