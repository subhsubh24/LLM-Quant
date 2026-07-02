"""
Tests for ROADMAP C5 + B2 — metrics_aggregator.py
===================================================
All tests are deterministic: no I/O, no network, no randomness in fixtures.

Coverage:
  1. Empty-trade input → zeros/nulls, meets_floor=False (no crash)
  2. Single trade → correct aggregation + floor=False (below $2 k)
  3. Multi-week weekly_series → correct buckets, cumulative PnL, hit_rate
  4. Floor met when avg_weekly_pnl >= 2000
  5. Floor not met when avg_weekly_pnl < 2000
  6. Degenerate calibration (model_prob == market_price) → status "insufficient_degenerate"
  7. Empty predictions → status "no_data", passes=False
  8. Insufficient samples (< 30) → status "insufficient_samples"
  9. compute_all returns all three keys and consistent numbers
  10. NaN/Inf safety: _safe_float converts them to None
"""

from __future__ import annotations

import math
from datetime import datetime

import pytest

from app.prediction_markets.weekly_metrics import TradePnL
from app.prediction_markets.calibration import ResolvedPrediction
from app.prediction_markets.metrics_aggregator import (
    FLOOR_USD,
    compute_weekly_metrics,
    compute_floor_status,
    compute_calibration,
    compute_all,
    _safe_float,
    _is_degenerate,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _trade(year: int, month: int, day: int, pnl: float, win: bool) -> TradePnL:
    return TradePnL(timestamp=datetime(year, month, day, 12, 0), pnl_usd=pnl, is_win=win)


def _pred(predicted_prob: float, market_price: float, outcome: int, mid: str = "m") -> ResolvedPrediction:
    return ResolvedPrediction(
        market_id=mid,
        predicted_prob=predicted_prob,
        market_price=market_price,
        outcome=outcome,
    )


# Three ISO weeks in January 2024:
#   Week A: 2024-01-15 (Mon) – 2024-01-21 (Sun)
#   Week B: 2024-01-22 (Mon) – 2024-01-28 (Sun)
#   Week C: 2024-01-29 (Mon) – 2024-02-04 (Sun)

WEEK_A_TRADES = [
    _trade(2024, 1, 15, 300.0, True),
    _trade(2024, 1, 17, -100.0, False),
]  # net = +200

WEEK_B_TRADES = [
    _trade(2024, 1, 22, 2500.0, True),
    _trade(2024, 1, 25, 500.0, True),
]  # net = +3000

WEEK_C_TRADES = [
    _trade(2024, 1, 29, -400.0, False),
]  # net = -400

ALL_TRADES = WEEK_A_TRADES + WEEK_B_TRADES + WEEK_C_TRADES
# 3 weeks: [+200, +3000, -400] → avg = 933.33, Sharpe = non-trivial


# ---------------------------------------------------------------------------
# 1. Empty input — zeros / nulls, meets_floor=False, no crash
# ---------------------------------------------------------------------------

class TestEmptyInput:
    def test_weekly_empty(self):
        result = compute_weekly_metrics([])
        assert result["total_trades"] == 0
        assert result["num_weeks"] == 0
        assert result["total_pnl_usd"] == 0.0
        assert result["avg_weekly_pnl_usd"] == 0.0
        assert result["weekly_series"] == []
        assert result["hit_rate"] == 0.0

    def test_floor_empty(self):
        result = compute_floor_status([])
        assert result["meets_floor"] is False
        assert result["avg_weekly_pnl_usd"] == 0.0
        assert result["weeks_counted"] == 0
        assert result["total_trades"] == 0
        assert result["floor_usd"] == FLOOR_USD

    def test_calibration_empty(self):
        result = compute_calibration([])
        assert result["status"] == "no_data"
        assert result["passes"] is False
        assert result["n"] == 0


# ---------------------------------------------------------------------------
# 2. Single trade — basic aggregation
# ---------------------------------------------------------------------------

class TestSingleTrade:
    def test_single_trade_counts(self):
        trades = [_trade(2024, 3, 4, 150.0, True)]
        result = compute_weekly_metrics(trades)
        assert result["total_trades"] == 1
        assert result["num_weeks"] == 1
        assert result["total_pnl_usd"] == pytest.approx(150.0)
        assert result["avg_weekly_pnl_usd"] == pytest.approx(150.0)
        assert result["hit_rate"] == pytest.approx(1.0)
        assert len(result["weekly_series"]) == 1

    def test_single_trade_floor_false(self):
        trades = [_trade(2024, 3, 4, 150.0, True)]
        result = compute_floor_status(trades)
        # 150 < 2000
        assert result["meets_floor"] is False

    def test_num_input_trades_field(self):
        trades = [_trade(2024, 3, 4, 150.0, True)]
        result = compute_weekly_metrics(trades)
        assert result["num_input_trades"] == 1


# ---------------------------------------------------------------------------
# 3. Multi-week bucketing — correct weekly_series
# ---------------------------------------------------------------------------

class TestMultiWeek:
    def test_three_weeks_produced(self):
        result = compute_weekly_metrics(ALL_TRADES)
        assert result["num_weeks"] == 3
        assert len(result["weekly_series"]) == 3

    def test_week_starts_ascending(self):
        result = compute_weekly_metrics(ALL_TRADES)
        starts = [w["week_start"] for w in result["weekly_series"]]
        assert starts == sorted(starts)

    def test_cumulative_pnl(self):
        result = compute_weekly_metrics(ALL_TRADES)
        series = result["weekly_series"]
        # Week A: +200, Week B: +3000, Week C: -400
        assert series[0]["realized_pnl_usd"] == pytest.approx(200.0)
        assert series[1]["realized_pnl_usd"] == pytest.approx(3000.0)
        assert series[2]["realized_pnl_usd"] == pytest.approx(-400.0)
        # Cumulative: 200, 3200, 2800
        assert series[0]["cumulative_pnl_usd"] == pytest.approx(200.0)
        assert series[1]["cumulative_pnl_usd"] == pytest.approx(3200.0)
        assert series[2]["cumulative_pnl_usd"] == pytest.approx(2800.0)

    def test_hit_rates(self):
        result = compute_weekly_metrics(ALL_TRADES)
        series = result["weekly_series"]
        # Week A: 1 win out of 2
        assert series[0]["hit_rate"] == pytest.approx(0.5)
        # Week B: 2 wins out of 2
        assert series[1]["hit_rate"] == pytest.approx(1.0)
        # Week C: 0 wins out of 1
        assert series[2]["hit_rate"] == pytest.approx(0.0)

    def test_total_trades_and_pnl(self):
        result = compute_weekly_metrics(ALL_TRADES)
        assert result["total_trades"] == 5
        assert result["total_pnl_usd"] == pytest.approx(2800.0)

    def test_source_field(self):
        result = compute_weekly_metrics(ALL_TRADES)
        assert result["source"] == "resolved_trades"


# ---------------------------------------------------------------------------
# 4. Floor met
# ---------------------------------------------------------------------------

class TestFloorMet:
    def test_floor_met_above(self):
        # Two weeks each averaging >= 2000
        trades = [
            _trade(2024, 1, 15, 2000.0, True),
            _trade(2024, 1, 22, 3000.0, True),
        ]
        result = compute_floor_status(trades)
        assert result["meets_floor"] is True

    def test_floor_met_exactly(self):
        # Exactly 2000 avg
        trades = [
            _trade(2024, 1, 15, 2000.0, True),
        ]
        result = compute_floor_status(trades)
        assert result["meets_floor"] is True


# ---------------------------------------------------------------------------
# 5. Floor not met
# ---------------------------------------------------------------------------

class TestFloorNotMet:
    def test_all_trades_below_floor(self):
        result = compute_floor_status(ALL_TRADES)
        # avg = (200 + 3000 - 400) / 3 = 933.33 < 2000
        assert result["meets_floor"] is False
        assert result["avg_weekly_pnl_usd"] == pytest.approx(2800.0 / 3, rel=1e-4)

    def test_loss_trades_below_floor(self):
        trades = [_trade(2024, 1, 15, -500.0, False)]
        result = compute_floor_status(trades)
        assert result["meets_floor"] is False


# ---------------------------------------------------------------------------
# 6. Degenerate calibration (model_prob == market_price)
# ---------------------------------------------------------------------------

class TestDegenerateCalibration:
    def _make_degenerate_samples(self, n: int) -> list:
        """n samples where predicted_prob == market_price (zero edge)."""
        samples = []
        for i in range(n):
            p = 0.4 + (i % 3) * 0.1  # 0.4, 0.5, 0.6 cycling
            outcome = i % 2
            samples.append(_pred(p, p, outcome, f"m{i}"))
        return samples

    def test_degenerate_status_string(self):
        samples = self._make_degenerate_samples(40)
        result = compute_calibration(samples)
        assert result["status"] == "insufficient_degenerate"

    def test_degenerate_passes_false(self):
        samples = self._make_degenerate_samples(40)
        result = compute_calibration(samples)
        # NEVER fabricate a passing calibration
        assert result["passes"] is False

    def test_degenerate_note_present(self):
        samples = self._make_degenerate_samples(40)
        result = compute_calibration(samples)
        assert result["note"] is not None
        assert "degenerate" in result["note"].lower()

    def test_is_degenerate_helper(self):
        samples = self._make_degenerate_samples(5)
        assert _is_degenerate(samples) is True

    def test_is_degenerate_false_when_distinct(self):
        samples = [_pred(0.6, 0.4, 1)]  # predicted != market
        assert _is_degenerate(samples) is False


# ---------------------------------------------------------------------------
# 7. Empty predictions → no_data
# ---------------------------------------------------------------------------

class TestEmptyPredictions:
    def test_status_no_data(self):
        result = compute_calibration([])
        assert result["status"] == "no_data"

    def test_n_zero(self):
        result = compute_calibration([])
        assert result["n"] == 0

    def test_passes_false(self):
        result = compute_calibration([])
        assert result["passes"] is False


# ---------------------------------------------------------------------------
# 8. Insufficient samples (< 30)
# ---------------------------------------------------------------------------

class TestInsufficientSamples:
    def test_insufficient_status(self):
        # 5 samples with non-degenerate predictions
        samples = [_pred(0.7, 0.5, 1, f"m{i}") for i in range(5)]
        result = compute_calibration(samples)
        assert result["status"] == "insufficient_samples"

    def test_insufficient_passes_false(self):
        samples = [_pred(0.7, 0.5, 1, f"m{i}") for i in range(5)]
        result = compute_calibration(samples)
        assert result["passes"] is False


# ---------------------------------------------------------------------------
# 9. compute_all — all three keys, consistent numbers
# ---------------------------------------------------------------------------

class TestComputeAll:
    def test_keys_present(self):
        result = compute_all(ALL_TRADES, [])
        assert "weekly_metrics" in result
        assert "floor_status" in result
        assert "calibration" in result

    def test_consistent_total_trades(self):
        result = compute_all(ALL_TRADES, [])
        wm = result["weekly_metrics"]
        fs = result["floor_status"]
        assert wm["total_trades"] == fs["total_trades"]

    def test_consistent_avg_weekly_pnl(self):
        result = compute_all(ALL_TRADES, [])
        wm = result["weekly_metrics"]
        fs = result["floor_status"]
        assert wm["avg_weekly_pnl_usd"] == pytest.approx(fs["avg_weekly_pnl_usd"])

    def test_empty_both(self):
        result = compute_all([], [])
        assert result["weekly_metrics"]["total_trades"] == 0
        assert result["floor_status"]["meets_floor"] is False
        assert result["calibration"]["status"] == "no_data"


# ---------------------------------------------------------------------------
# 10. NaN/Inf safety via _safe_float
# ---------------------------------------------------------------------------

class TestSafeFloat:
    def test_nan_becomes_none(self):
        assert _safe_float(float("nan")) is None

    def test_inf_becomes_none(self):
        assert _safe_float(float("inf")) is None
        assert _safe_float(float("-inf")) is None

    def test_normal_float_passthrough(self):
        assert _safe_float(3.14) == pytest.approx(3.14)

    def test_zero_passthrough(self):
        assert _safe_float(0.0) == 0.0

    def test_none_passthrough(self):
        assert _safe_float(None) is None
