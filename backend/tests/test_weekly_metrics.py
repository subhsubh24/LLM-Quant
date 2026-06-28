"""
Tests for ROADMAP C5 — prediction_markets/weekly_metrics.py
===========================================================
All tests are deterministic (no randomness, no I/O, no network).

The module lives in the CI-clean ``prediction_markets`` package (not
``backend.app.backtest``, whose ``__init__`` pulls heavy ML deps absent from the
lightweight CI gate), so it imports directly with no shim.

Coverage
--------
* week_start_of  — correct Monday for several known dates
* aggregate_weekly — multi-week grouping, cumulative running sum, hit_rate
* weekly_sharpe  — hand-checked series, degenerate cases
* max_drawdown   — explicit equity curve, USD + pct
* summarize      — end-to-end on a small fixture
* floor_met      — True / False branches
* determinism    — same input → identical summary twice
"""

from __future__ import annotations

import statistics
from datetime import date, datetime

import pytest

from backend.app.prediction_markets.weekly_metrics import (
    MetricsSummary,
    TradePnL,
    WeeklyMetrics,
    aggregate_weekly,
    floor_met,
    max_drawdown,
    summarize,
    week_start_of,
    weekly_sharpe,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _trade(year: int, month: int, day: int, pnl: float, win: bool) -> TradePnL:
    """Convenience constructor for test trades."""
    return TradePnL(timestamp=datetime(year, month, day, 12, 0), pnl_usd=pnl, is_win=win)


# Three calendar weeks (all in 2024):
# Week A: Mon 2024-01-15 … Sun 2024-01-21
# Week B: Mon 2024-01-22 … Sun 2024-01-28
# Week C: Mon 2024-01-29 … Sun 2024-02-04

WEEK_A_TRADES = [
    _trade(2024, 1, 16, 500.0, True),   # Tuesday
    _trade(2024, 1, 18, -100.0, False),  # Thursday
    _trade(2024, 1, 20, 300.0, True),   # Saturday
]

WEEK_B_TRADES = [
    _trade(2024, 1, 22, 800.0, True),   # Monday
    _trade(2024, 1, 25, -200.0, False),  # Thursday
]

WEEK_C_TRADES = [
    _trade(2024, 1, 31, 1200.0, True),  # Wednesday
    _trade(2024, 2, 1, 600.0, True),    # Thursday
    _trade(2024, 2, 3, -400.0, False),   # Saturday
]

ALL_TRADES = WEEK_A_TRADES + WEEK_B_TRADES + WEEK_C_TRADES


# ---------------------------------------------------------------------------
# week_start_of
# ---------------------------------------------------------------------------

class TestWeekStartOf:
    def test_wednesday_returns_preceding_monday(self):
        d = date(2024, 1, 17)  # Wednesday
        assert week_start_of(d) == date(2024, 1, 15)

    def test_monday_returns_itself(self):
        d = date(2024, 1, 15)  # Monday
        assert week_start_of(d) == date(2024, 1, 15)

    def test_sunday_returns_preceding_monday(self):
        d = date(2024, 1, 21)  # Sunday
        assert week_start_of(d) == date(2024, 1, 15)

    def test_friday_returns_preceding_monday(self):
        d = date(2024, 1, 19)  # Friday
        assert week_start_of(d) == date(2024, 1, 15)

    def test_saturday_week_b(self):
        # 2024-01-27 is a Saturday in week B
        d = date(2024, 1, 27)
        assert week_start_of(d) == date(2024, 1, 22)

    def test_datetime_input(self):
        dt = datetime(2024, 1, 17, 9, 30)  # Wednesday
        assert week_start_of(dt) == date(2024, 1, 15)

    def test_new_year_boundary(self):
        # 2023-01-01 is a Sunday; its week starts Mon 2022-12-26
        d = date(2023, 1, 1)
        assert week_start_of(d) == date(2022, 12, 26)

    def test_tuesday_different_month(self):
        d = date(2024, 2, 6)  # Tuesday
        assert week_start_of(d) == date(2024, 2, 5)  # Monday Feb 5


# ---------------------------------------------------------------------------
# aggregate_weekly
# ---------------------------------------------------------------------------

class TestAggregateWeekly:
    def test_empty_input_returns_empty(self):
        assert aggregate_weekly([]) == []

    def test_groups_into_three_weeks(self):
        weeks = aggregate_weekly(ALL_TRADES)
        assert len(weeks) == 3

    def test_week_starts_are_correct_mondays(self):
        weeks = aggregate_weekly(ALL_TRADES)
        assert weeks[0].week_start == date(2024, 1, 15)
        assert weeks[1].week_start == date(2024, 1, 22)
        assert weeks[2].week_start == date(2024, 1, 29)

    def test_week_a_realized_pnl(self):
        weeks = aggregate_weekly(ALL_TRADES)
        # 500 - 100 + 300 = 700
        assert weeks[0].realized_pnl_usd == pytest.approx(700.0)

    def test_week_b_realized_pnl(self):
        weeks = aggregate_weekly(ALL_TRADES)
        # 800 - 200 = 600
        assert weeks[1].realized_pnl_usd == pytest.approx(600.0)

    def test_week_c_realized_pnl(self):
        weeks = aggregate_weekly(ALL_TRADES)
        # 1200 + 600 - 400 = 1400
        assert weeks[2].realized_pnl_usd == pytest.approx(1400.0)

    def test_cumulative_is_running_sum(self):
        weeks = aggregate_weekly(ALL_TRADES)
        assert weeks[0].cumulative_pnl_usd == pytest.approx(700.0)
        assert weeks[1].cumulative_pnl_usd == pytest.approx(1300.0)   # 700+600
        assert weeks[2].cumulative_pnl_usd == pytest.approx(2700.0)   # 1300+1400

    def test_num_trades_per_week(self):
        weeks = aggregate_weekly(ALL_TRADES)
        assert weeks[0].num_trades == 3
        assert weeks[1].num_trades == 2
        assert weeks[2].num_trades == 3

    def test_num_wins_per_week(self):
        weeks = aggregate_weekly(ALL_TRADES)
        assert weeks[0].num_wins == 2   # 500 win, -100 loss, 300 win
        assert weeks[1].num_wins == 1   # 800 win, -200 loss
        assert weeks[2].num_wins == 2   # 1200 win, 600 win, -400 loss

    def test_hit_rate_per_week(self):
        weeks = aggregate_weekly(ALL_TRADES)
        assert weeks[0].hit_rate == pytest.approx(2 / 3)
        assert weeks[1].hit_rate == pytest.approx(1 / 2)
        assert weeks[2].hit_rate == pytest.approx(2 / 3)

    def test_sorted_ascending(self):
        import random
        shuffled = list(ALL_TRADES)
        random.shuffle(shuffled)
        weeks = aggregate_weekly(shuffled)
        starts = [w.week_start for w in weeks]
        assert starts == sorted(starts)

    def test_single_trade(self):
        t = _trade(2024, 3, 13, 999.0, True)  # Wednesday
        weeks = aggregate_weekly([t])
        assert len(weeks) == 1
        assert weeks[0].week_start == date(2024, 3, 11)  # Monday
        assert weeks[0].realized_pnl_usd == pytest.approx(999.0)
        assert weeks[0].cumulative_pnl_usd == pytest.approx(999.0)
        assert weeks[0].hit_rate == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# weekly_sharpe
# ---------------------------------------------------------------------------

class TestWeeklySharpe:
    def test_fewer_than_two_weeks_returns_zero(self):
        assert weekly_sharpe([]) == 0.0
        assert weekly_sharpe([500.0]) == 0.0

    def test_constant_series_returns_zero(self):
        assert weekly_sharpe([100.0, 100.0, 100.0]) == 0.0

    def test_known_series_hand_checked(self):
        # Series: [100, 200, 300]
        # mean = 200, stdev(ddof=1) = 100, sharpe = 200/100 = 2.0
        pnls = [100.0, 200.0, 300.0]
        expected_mean = statistics.mean(pnls)      # 200.0
        expected_stdev = statistics.stdev(pnls)    # 100.0
        expected = expected_mean / expected_stdev   # 2.0
        assert weekly_sharpe(pnls) == pytest.approx(expected)

    def test_mixed_sign_series(self):
        # Series: [-100, 300, -50, 400]
        pnls = [-100.0, 300.0, -50.0, 400.0]
        mean = statistics.mean(pnls)
        stdev = statistics.stdev(pnls)
        expected = mean / stdev
        assert weekly_sharpe(pnls) == pytest.approx(expected)

    def test_two_identical_values_returns_zero(self):
        assert weekly_sharpe([250.0, 250.0]) == 0.0

    def test_two_different_values(self):
        pnls = [0.0, 200.0]
        mean = statistics.mean(pnls)
        stdev = statistics.stdev(pnls)
        expected = mean / stdev
        assert weekly_sharpe(pnls) == pytest.approx(expected)


# ---------------------------------------------------------------------------
# max_drawdown
# ---------------------------------------------------------------------------

class TestMaxDrawdown:
    def test_empty_curve_returns_zeros(self):
        dd_usd, dd_pct = max_drawdown([])
        assert dd_usd == 0.0
        assert dd_pct == 0.0

    def test_monotonically_rising_has_no_drawdown(self):
        dd_usd, dd_pct = max_drawdown([100.0, 150.0, 200.0])
        assert dd_usd == 0.0
        assert dd_pct == 0.0

    def test_target_curve(self):
        # [100, 120, 90, 150, 80]
        # Peak sequence:  100, 120, 120, 150, 150
        # Drawdowns:        0,   0,  30,   0,  70
        # max dd_usd = 70 (peak 150 → trough 80)
        # dd_pct = 70 / 150 ≈ 0.4667
        curve = [100.0, 120.0, 90.0, 150.0, 80.0]
        dd_usd, dd_pct = max_drawdown(curve)
        assert dd_usd == pytest.approx(70.0)
        assert dd_pct == pytest.approx(70.0 / 150.0)

    def test_intermediate_drawdown_not_chosen_if_smaller(self):
        # [100, 120, 90, ...] → 120→90 = 30, which is < 70 in full curve
        curve = [100.0, 120.0, 90.0, 150.0, 80.0]
        dd_usd, _ = max_drawdown(curve)
        assert dd_usd == pytest.approx(70.0)  # not 30

    def test_single_value(self):
        dd_usd, dd_pct = max_drawdown([500.0])
        assert dd_usd == 0.0
        assert dd_pct == 0.0

    def test_negative_starting_peak_guard(self):
        # If all values are negative the peak can be negative; guard pct=0
        curve = [-50.0, -30.0, -80.0]
        dd_usd, dd_pct = max_drawdown(curve)
        # peak at index 1 = -30; trough at index 2 = -80; dd_usd = -30-(-80)=50
        assert dd_usd == pytest.approx(50.0)
        # peak <= 0 → pct should be 0.0
        assert dd_pct == 0.0

    def test_monotonically_declining(self):
        curve = [200.0, 150.0, 100.0, 50.0]
        dd_usd, dd_pct = max_drawdown(curve)
        assert dd_usd == pytest.approx(150.0)
        assert dd_pct == pytest.approx(150.0 / 200.0)


# ---------------------------------------------------------------------------
# summarize (end-to-end)
# ---------------------------------------------------------------------------

class TestSummarize:
    def test_empty_input(self):
        s = summarize([])
        assert s.num_weeks == 0
        assert s.total_pnl_usd == 0.0
        assert s.avg_weekly_pnl_usd == 0.0
        assert s.weekly_sharpe == 0.0
        assert s.max_drawdown_usd == 0.0
        assert s.max_drawdown_pct == 0.0
        assert s.hit_rate == 0.0
        assert s.total_trades == 0
        assert s.best_week_usd == 0.0
        assert s.worst_week_usd == 0.0

    def test_three_week_fixture(self):
        s = summarize(ALL_TRADES)
        # Weeks: 700, 600, 1400
        assert s.num_weeks == 3
        assert s.total_pnl_usd == pytest.approx(2700.0)
        assert s.avg_weekly_pnl_usd == pytest.approx(900.0)  # 2700/3
        assert s.total_trades == 8   # 3+2+3
        # Wins: 2+1+2 = 5
        assert s.hit_rate == pytest.approx(5 / 8)

    def test_best_and_worst_week(self):
        s = summarize(ALL_TRADES)
        assert s.best_week_usd == pytest.approx(1400.0)
        assert s.worst_week_usd == pytest.approx(600.0)

    def test_weekly_sharpe_in_summary(self):
        s = summarize(ALL_TRADES)
        expected = weekly_sharpe([700.0, 600.0, 1400.0])
        assert s.weekly_sharpe == pytest.approx(expected)

    def test_max_drawdown_in_summary(self):
        s = summarize(ALL_TRADES)
        # Cumulative curve: [700, 1300, 2700] — monotonically rising
        dd_usd, dd_pct = max_drawdown([700.0, 1300.0, 2700.0])
        assert s.max_drawdown_usd == pytest.approx(dd_usd)
        assert s.max_drawdown_pct == pytest.approx(dd_pct)

    def test_drawdown_on_declining_curve(self):
        # One losing week makes the cumulative dip
        trades = [
            _trade(2024, 1, 15, 1000.0, True),   # Week A: +1000
            _trade(2024, 1, 22, -400.0, False),   # Week B: -400  → cumul 600
            _trade(2024, 1, 29, 200.0, True),     # Week C: +200  → cumul 800
        ]
        s = summarize(trades)
        # cumulative curve: [1000, 600, 800]
        # peak=1000, trough=600 → dd_usd=400, dd_pct=0.4
        assert s.max_drawdown_usd == pytest.approx(400.0)
        assert s.max_drawdown_pct == pytest.approx(0.4)

    def test_weeks_field_matches_aggregate_weekly(self):
        s = summarize(ALL_TRADES)
        expected_weeks = aggregate_weekly(ALL_TRADES)
        assert s.weeks == expected_weeks

    def test_single_trade_summary(self):
        t = _trade(2024, 6, 5, 3000.0, True)  # Wednesday
        s = summarize([t])
        assert s.num_weeks == 1
        assert s.total_pnl_usd == pytest.approx(3000.0)
        assert s.avg_weekly_pnl_usd == pytest.approx(3000.0)
        assert s.hit_rate == pytest.approx(1.0)
        assert s.total_trades == 1
        assert s.weekly_sharpe == 0.0   # < 2 weeks


# ---------------------------------------------------------------------------
# floor_met
# ---------------------------------------------------------------------------

class TestFloorMet:
    def _summary_with(self, avg_weekly: float, num_weeks: int) -> MetricsSummary:
        """Build a minimal MetricsSummary for floor_met testing."""
        # We construct weeks artificially to avoid needing real trades
        weeks_list: list[WeeklyMetrics] = []
        running = 0.0
        for i in range(num_weeks):
            ws = date(2024, 1, 1 + i * 7)
            running += avg_weekly
            weeks_list.append(
                WeeklyMetrics(
                    week_start=ws,
                    realized_pnl_usd=avg_weekly,
                    num_trades=1,
                    num_wins=1,
                    hit_rate=1.0,
                    cumulative_pnl_usd=running,
                )
            )
        return MetricsSummary(
            weeks=weeks_list,
            total_pnl_usd=avg_weekly * num_weeks,
            avg_weekly_pnl_usd=avg_weekly,
            weekly_sharpe=0.0,
            max_drawdown_usd=0.0,
            max_drawdown_pct=0.0,
            hit_rate=1.0,
            total_trades=num_weeks,
            best_week_usd=avg_weekly,
            worst_week_usd=avg_weekly,
            num_weeks=num_weeks,
        )

    def test_above_floor_and_enough_weeks(self):
        s = self._summary_with(avg_weekly=2500.0, num_weeks=4)
        assert floor_met(s) is True

    def test_exactly_at_floor(self):
        s = self._summary_with(avg_weekly=2000.0, num_weeks=1)
        assert floor_met(s) is True

    def test_below_floor(self):
        s = self._summary_with(avg_weekly=1999.99, num_weeks=4)
        assert floor_met(s) is False

    def test_zero_weeks(self):
        s = self._summary_with(avg_weekly=5000.0, num_weeks=0)
        assert floor_met(s) is False

    def test_min_weeks_not_met(self):
        s = self._summary_with(avg_weekly=3000.0, num_weeks=2)
        assert floor_met(s, floor_usd=2000.0, min_weeks=4) is False

    def test_custom_floor_usd(self):
        s = self._summary_with(avg_weekly=500.0, num_weeks=3)
        assert floor_met(s, floor_usd=400.0, min_weeks=1) is True
        assert floor_met(s, floor_usd=600.0, min_weeks=1) is False

    def test_from_real_trades(self):
        # The three-week fixture averages 900 USD/week — below the $2k floor
        s = summarize(ALL_TRADES)
        assert floor_met(s) is False

    def test_from_real_trades_above_floor(self):
        trades = [
            _trade(2024, 1, 15, 3000.0, True),
            _trade(2024, 1, 22, 2500.0, True),
        ]
        s = summarize(trades)
        assert s.avg_weekly_pnl_usd == pytest.approx(2750.0)
        assert floor_met(s) is True


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

class TestDeterminism:
    def test_same_input_twice_identical_output(self):
        s1 = summarize(ALL_TRADES)
        s2 = summarize(ALL_TRADES)
        assert s1 == s2

    def test_shuffled_trades_same_summary(self):
        import random
        shuffled = list(ALL_TRADES)
        random.shuffle(shuffled)
        s_original = summarize(ALL_TRADES)
        s_shuffled = summarize(shuffled)
        # Order of trades within a week should not affect per-week totals
        assert s_original.total_pnl_usd == pytest.approx(s_shuffled.total_pnl_usd)
        assert s_original.num_weeks == s_shuffled.num_weeks
        assert s_original.total_trades == s_shuffled.total_trades
        assert s_original.hit_rate == pytest.approx(s_shuffled.hit_rate)

    def test_week_start_of_is_pure(self):
        d = date(2024, 3, 20)
        assert week_start_of(d) == week_start_of(d)

    def test_max_drawdown_is_pure(self):
        curve = [100.0, 120.0, 90.0, 150.0, 80.0]
        assert max_drawdown(curve) == max_drawdown(curve)

    def test_weekly_sharpe_is_pure(self):
        pnls = [100.0, 200.0, 300.0]
        assert weekly_sharpe(pnls) == weekly_sharpe(pnls)
