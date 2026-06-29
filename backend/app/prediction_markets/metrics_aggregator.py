"""
ROADMAP C5 + B2 — Metrics Aggregator
======================================
Pure, deterministic module that takes resolved-trade inputs and returns a
JSON-serializable dict with:

  - Weekly PnL series + MetricsSummary (hit_rate, weekly_sharpe, max_drawdown,
    avg_weekly_pnl, total_trades)
  - Floor status (floor_met against floor_usd=2000) with meets_floor bool
  - Calibration result (evaluate_calibration) with honest degenerate-path
    detection when model_prob == market_price (zero edge — current paper reality)

HONESTY CONTRACT
----------------
* Every number flows from real resolved TradePnL / ResolvedPrediction inputs.
* No fabricated values, no fake calibration passes.
* When model_prob == market_price for all predictions (current degenerate case:
  strategies seed model to crowd), calibration is reported as
  "insufficient_degenerate" — NOT a pass. The module NEVER invents a passing
  calibration.
* Empty inputs → zeros/nulls, meets_floor=False, no crash.

This module imports from weekly_metrics and calibration; it does NOT modify them.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Sequence

from .weekly_metrics import (
    TradePnL,
    MetricsSummary,
    floor_met,
    summarize,
)
from .calibration import (
    ResolvedPrediction,
    CalibrationResult,
    evaluate_calibration,
)
from .per_strategy_metrics import (
    StrategyTradePnL,
    StrategyAttribution,
    attribute_by_strategy,
    rank_by_total_pnl,
)


# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

FLOOR_USD: float = 2000.0          # ROADMAP C5 go-live gate
CALIBRATION_MIN_SAMPLES: int = 30  # Passed to evaluate_calibration


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _safe_float(v: float) -> Any:
    """Convert NaN/Inf to None for JSON safety."""
    if v is None:
        return None
    try:
        if math.isnan(v) or math.isinf(v):
            return None
        return v
    except TypeError:
        return None


def _summary_to_dict(summary: MetricsSummary) -> Dict[str, Any]:
    """Serialize MetricsSummary + weekly series to a JSON-safe dict."""
    weekly_series = [
        {
            "week_start": w.week_start.isoformat(),
            "realized_pnl_usd": _safe_float(w.realized_pnl_usd),
            "num_trades": w.num_trades,
            "num_wins": w.num_wins,
            "hit_rate": _safe_float(w.hit_rate),
            "cumulative_pnl_usd": _safe_float(w.cumulative_pnl_usd),
        }
        for w in summary.weeks
    ]
    return {
        "total_pnl_usd": _safe_float(summary.total_pnl_usd),
        "avg_weekly_pnl_usd": _safe_float(summary.avg_weekly_pnl_usd),
        "weekly_sharpe": _safe_float(summary.weekly_sharpe),
        "max_drawdown_usd": _safe_float(summary.max_drawdown_usd),
        "max_drawdown_pct": _safe_float(summary.max_drawdown_pct),
        "hit_rate": _safe_float(summary.hit_rate),
        "total_trades": summary.total_trades,
        "best_week_usd": _safe_float(summary.best_week_usd),
        "worst_week_usd": _safe_float(summary.worst_week_usd),
        "num_weeks": summary.num_weeks,
        "weekly_series": weekly_series,
    }


def _floor_status_to_dict(
    summary: MetricsSummary,
    floor_usd: float = FLOOR_USD,
) -> Dict[str, Any]:
    """Return floor-status dict from a pre-built MetricsSummary."""
    meets = floor_met(summary, floor_usd=floor_usd)
    return {
        "meets_floor": meets,
        "floor_usd": floor_usd,
        "avg_weekly_pnl_usd": _safe_float(summary.avg_weekly_pnl_usd),
        "weeks_counted": summary.num_weeks,
        "total_trades": summary.total_trades,
    }


def _is_degenerate(samples: Sequence[ResolvedPrediction]) -> bool:
    """Return True if every sample has model_prob == market_price (zero-edge case)."""
    if not samples:
        return False
    return all(
        math.isclose(s.predicted_prob, s.market_price, rel_tol=1e-9, abs_tol=1e-12)
        for s in samples
    )


def _calibration_to_dict(result: CalibrationResult, is_degenerate: bool) -> Dict[str, Any]:
    """Serialize CalibrationResult to a JSON-safe dict with honest status field."""
    # Determine honest status string
    if is_degenerate:
        status = "insufficient_degenerate"
    elif result.n == 0:
        status = "no_data"
    elif result.n < CALIBRATION_MIN_SAMPLES:
        status = "insufficient_samples"
    elif result.passes:
        status = "passes"
    else:
        status = "fails"

    return {
        "status": status,
        "n": result.n,
        "passes": result.passes,
        "strategy_brier": _safe_float(result.strategy_brier),
        "baseline_brier": _safe_float(result.baseline_brier),
        "improvement": _safe_float(result.improvement),
        "improvement_ci_low": _safe_float(result.improvement_ci_low),
        "improvement_ci_high": _safe_float(result.improvement_ci_high),
        "expected_calibration_error": _safe_float(result.expected_calibration_error),
        "note": (
            "model_prob == market_price for all samples: strategy has no edge "
            "over crowd baseline — calibration evaluation is degenerate (not a pass)."
            if is_degenerate else None
        ),
    }


# ---------------------------------------------------------------------------
# Primary entry-points (called by routes.py)
# ---------------------------------------------------------------------------

def compute_weekly_metrics(trades: Sequence[TradePnL]) -> Dict[str, Any]:
    """
    Compute weekly PnL series + portfolio-level MetricsSummary.

    Parameters
    ----------
    trades:
        Sequence of resolved TradePnL records. May be empty.

    Returns
    -------
    dict
        JSON-serializable dict with ``summary`` key (MetricsSummary fields)
        and ``weekly_series`` list.  All numbers flow from real inputs; no
        fabrication.
    """
    # Materialize once: `trades` is typed Sequence but a one-shot iterator would be
    # consumed by summarize(), leaving len() at 0 (reviewer MUST-FIX M1).
    trade_list = list(trades)
    summary = summarize(trade_list)
    return {
        "source": "resolved_trades",
        "num_input_trades": len(trade_list),
        **_summary_to_dict(summary),
    }


def compute_floor_status(trades: Sequence[TradePnL]) -> Dict[str, Any]:
    """
    Evaluate whether the ROADMAP C5 go-live floor has been met.

    Parameters
    ----------
    trades:
        Sequence of resolved TradePnL records.

    Returns
    -------
    dict
        ``meets_floor`` (bool), ``floor_usd``, ``avg_weekly_pnl_usd``,
        ``weeks_counted``, ``total_trades``.
    """
    summary = summarize(list(trades))
    return _floor_status_to_dict(summary, floor_usd=FLOOR_USD)


def compute_calibration(predictions: Sequence[ResolvedPrediction]) -> Dict[str, Any]:
    """
    Run the ROADMAP B2 calibration evaluation with honest degenerate-path detection.

    If ``model_prob == market_price`` for all predictions (the current paper-trading
    reality — strategies seed model to the crowd price, leaving zero edge), the
    evaluation is reported as ``"insufficient_degenerate"`` — NOT a pass.  The caller
    receives an honest status and a plain-language note explaining why.

    Parameters
    ----------
    predictions:
        Sequence of ResolvedPrediction records. May be empty.

    Returns
    -------
    dict
        JSON-serializable calibration result with an honest ``status`` field.
        Never fabricates a passing calibration.
    """
    sample_list = list(predictions)
    degenerate = _is_degenerate(sample_list)
    result = evaluate_calibration(sample_list, min_samples=CALIBRATION_MIN_SAMPLES)
    return _calibration_to_dict(result, is_degenerate=degenerate)


def _attribution_to_dict(a: StrategyAttribution) -> Dict[str, Any]:
    """Serialize a StrategyAttribution to a JSON-safe dict (NaN/Inf → None)."""
    return {
        "strategy": a.strategy,
        "num_trades": a.num_trades,
        "num_wins": a.num_wins,
        "total_pnl_usd": _safe_float(a.total_pnl_usd),
        "mean_pnl_usd": _safe_float(a.mean_pnl_usd),
        "hit_rate": _safe_float(a.hit_rate),
        "best_trade_usd": _safe_float(a.best_trade_usd),
        "worst_trade_usd": _safe_float(a.worst_trade_usd),
        # weekly_pnl is an immutable MappingProxyType keyed by ISO-Monday date.
        "weekly_pnl": {k: _safe_float(v) for k, v in a.weekly_pnl.items()},
    }


def compute_per_strategy_metrics(
    trades: Sequence[StrategyTradePnL],
) -> Dict[str, Any]:
    """
    ROADMAP E6 — per-strategy realized-PnL attribution over strategy-tagged trades.

    Pure + deterministic wrapper around ``per_strategy_metrics.attribute_by_strategy``:
    groups resolved, strategy-tagged trades by the alpha that opened them and reports
    each strategy's realized PnL / hit-rate / weekly series, plus a ranking by total
    realized PnL (the E4 A/B + decayed-alpha-retirement ordering input).

    HONESTY
    -------
    * Strategies with zero trades NEVER appear (no fabricated 0/0 rows) — inherited
      from ``attribute_by_strategy``.
    * Every number flows from the real resolved trades passed in; empty input →
      ``{"strategies": [], "ranking": [], "num_input_trades": 0}`` (no crash, no
      invented strategy).

    Returns
    -------
    dict
        ``strategies`` (list of per-strategy dicts, sorted by name),
        ``ranking`` (strategy names ranked by total realized PnL desc, ties by name),
        ``num_input_trades``.
    """
    trade_list = list(trades)
    attributions = attribute_by_strategy(trade_list)
    ranked = rank_by_total_pnl(attributions)
    return {
        "source": "resolved_trades_by_strategy",
        "num_input_trades": len(trade_list),
        # Sorted by name for a stable, deterministic listing.
        "strategies": [
            _attribution_to_dict(attributions[name]) for name in sorted(attributions)
        ],
        # Ranked by realized PnL (desc); the decision input for E4 promote/retire.
        "ranking": [a.strategy for a in ranked],
    }


def compute_all(
    trades: Sequence[TradePnL],
    predictions: Sequence[ResolvedPrediction],
) -> Dict[str, Any]:
    """
    Run all three metric groups in one call.

    Parameters
    ----------
    trades:
        Resolved TradePnL records for weekly/floor metrics.
    predictions:
        Resolved ResolvedPrediction records for calibration.

    Returns
    -------
    dict
        Keys: ``weekly_metrics``, ``floor_status``, ``calibration``.
    """
    trade_list = list(trades)
    pred_list = list(predictions)

    summary = summarize(trade_list)
    degenerate = _is_degenerate(pred_list)
    cal_result = evaluate_calibration(pred_list, min_samples=CALIBRATION_MIN_SAMPLES)

    return {
        "weekly_metrics": {
            "source": "resolved_trades",
            "num_input_trades": len(trade_list),
            **_summary_to_dict(summary),
        },
        "floor_status": _floor_status_to_dict(summary, floor_usd=FLOOR_USD),
        "calibration": _calibration_to_dict(cal_result, is_degenerate=degenerate),
    }


# ---------------------------------------------------------------------------
# Public API surface
# ---------------------------------------------------------------------------

__all__ = [
    "FLOOR_USD",
    "CALIBRATION_MIN_SAMPLES",
    "compute_weekly_metrics",
    "compute_floor_status",
    "compute_calibration",
    "compute_per_strategy_metrics",
    "compute_all",
]
