"use client";

import { CheckCircle2, XCircle, AlertTriangle, HelpCircle } from "lucide-react";
import { cn } from "@/lib/utils";

export interface CalibrationData {
  status:
    | "insufficient_degenerate"
    | "no_data"
    | "insufficient_samples"
    | "fails"
    | "passes";
  n: number;
  passes: boolean;
  strategy_brier: number | null;
  baseline_brier: number | null;
  improvement: number | null;
  improvement_ci_low: number | null;
  improvement_ci_high: number | null;
  expected_calibration_error: number | null;
  note: string | null;
}

export interface DriftData {
  status: "insufficient_data" | "evaluated";
  drift_detected: boolean;
  num_predictions: number;
  severity?: string;
  baseline_brier?: number | null;
  recent_brier?: number | null;
  brier_delta?: number | null;
  de_rating?: number | null;
  recent_n?: number;
}

function fmt(v: number | null, decimals = 4): string {
  if (v === null || v === undefined) return "—";
  return v.toFixed(decimals);
}

function StatusBadge({ status, passes }: { status: CalibrationData["status"]; passes: boolean }) {
  if (status === "insufficient_degenerate" || status === "no_data") {
    return (
      <span className="flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full bg-amber-500/10 text-amber-400">
        <AlertTriangle className="w-3 h-3" />
        Insufficient data
      </span>
    );
  }
  if (status === "insufficient_samples") {
    return (
      <span className="flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full bg-amber-500/10 text-amber-400">
        <HelpCircle className="w-3 h-3" />
        Insufficient samples
      </span>
    );
  }
  if (passes) {
    return (
      <span className="flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full bg-green-500/10 text-green-500">
        <CheckCircle2 className="w-3 h-3" />
        Passes
      </span>
    );
  }
  return (
    <span className="flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full bg-red-500/10 text-red-500">
      <XCircle className="w-3 h-3" />
      Fails
    </span>
  );
}

export function CalibrationCard({
  calibration,
  drift,
}: {
  calibration: CalibrationData;
  drift: DriftData | null;
}) {
  const isDegenerate =
    calibration.status === "insufficient_degenerate" ||
    calibration.status === "no_data";

  const showImprovement =
    !isDegenerate &&
    calibration.status !== "insufficient_samples" &&
    calibration.improvement !== null;

  return (
    <div className="glass-card p-5">
      <div className="flex items-center justify-between mb-3">
        <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">
          Calibration
        </span>
        <StatusBadge status={calibration.status} passes={calibration.passes} />
      </div>

      {/* Backend note displayed verbatim when present */}
      {calibration.note && (
        <p className="text-[11px] text-amber-400/80 bg-amber-500/5 border border-amber-500/10 rounded-md px-2.5 py-1.5 mb-3 italic">
          {calibration.note}
        </p>
      )}

      <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-[11px]">
        <div>
          <span className="text-muted-foreground">Predictions (n)</span>
          <p className="font-bold tabular-nums text-foreground">{calibration.n}</p>
        </div>
        <div>
          <span className="text-muted-foreground">Strategy Brier</span>
          <p className="font-bold tabular-nums text-foreground">
            {isDegenerate ? "—" : fmt(calibration.strategy_brier)}
          </p>
        </div>
        <div>
          <span className="text-muted-foreground">Baseline Brier</span>
          <p className="font-bold tabular-nums text-foreground">
            {isDegenerate ? "—" : fmt(calibration.baseline_brier)}
          </p>
        </div>
        <div>
          <span className="text-muted-foreground">ECE</span>
          <p className="font-bold tabular-nums text-foreground">
            {isDegenerate ? "—" : fmt(calibration.expected_calibration_error)}
          </p>
        </div>

        {showImprovement ? (
          <>
            <div>
              <span className="text-muted-foreground">Improvement</span>
              <p className={cn(
                "font-bold tabular-nums",
                (calibration.improvement ?? 0) > 0 ? "text-green-500" : "text-red-500"
              )}>
                {fmt(calibration.improvement)}
              </p>
            </div>
            <div>
              <span className="text-muted-foreground">95% CI</span>
              <p className="font-bold tabular-nums text-foreground font-mono text-[10px]">
                [{fmt(calibration.improvement_ci_low, 4)}, {fmt(calibration.improvement_ci_high, 4)}]
              </p>
            </div>
          </>
        ) : (
          <div className="col-span-2">
            <span className="text-muted-foreground">Improvement vs baseline</span>
            <p className="font-bold text-muted-foreground italic">— no edge over crowd yet</p>
          </div>
        )}
      </div>

      {/* Drift section */}
      {drift && (
        <div className="mt-4 pt-4 border-t border-border/60">
          <div className="flex items-center justify-between mb-2">
            <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">
              Calibration Drift
            </span>
            {drift.status === "insufficient_data" ? (
              <span className="text-[10px] text-amber-400 bg-amber-500/10 px-2 py-0.5 rounded-full font-medium">
                Not enough data to evaluate drift
              </span>
            ) : drift.drift_detected ? (
              <span className="flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full bg-red-500/10 text-red-500">
                <AlertTriangle className="w-3 h-3" />
                Drift detected{drift.severity ? ` (${drift.severity})` : ""}
              </span>
            ) : (
              <span className="flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full bg-green-500/10 text-green-500">
                <CheckCircle2 className="w-3 h-3" />
                No drift
              </span>
            )}
          </div>

          {drift.status === "evaluated" && (
            <div className="grid grid-cols-3 gap-x-4 gap-y-1 text-[11px]">
              <div>
                <span className="text-muted-foreground">Predictions</span>
                <p className="font-bold tabular-nums text-foreground">{drift.num_predictions}</p>
              </div>
              <div>
                <span className="text-muted-foreground">Recent Brier</span>
                <p className="font-bold tabular-nums text-foreground">
                  {drift.recent_brier !== undefined && drift.recent_brier !== null
                    ? fmt(drift.recent_brier)
                    : "—"}
                </p>
              </div>
              <div>
                <span className="text-muted-foreground">Brier delta</span>
                <p className={cn(
                  "font-bold tabular-nums",
                  drift.brier_delta !== undefined && drift.brier_delta !== null
                    ? (drift.brier_delta > 0 ? "text-red-500" : "text-green-500")
                    : "text-muted-foreground"
                )}>
                  {drift.brier_delta !== undefined && drift.brier_delta !== null
                    ? fmt(drift.brier_delta)
                    : "—"}
                </p>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
