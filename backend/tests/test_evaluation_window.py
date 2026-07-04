"""
Tests for evaluation_window.py — evaluation-window engine + realized-vs-backtest
reconciliation (ROADMAP E5/E6).

Pins:
  * ISO-week window assignment (Monday bucketing, UTC normalization of naive datetimes).
  * config-change-at-boundary discipline (a mid-window change never rewrites a closed
    window; it lands at the next boundary).
  * per-window PnL / hit-rate / drawdown / Brier correctness on hand-computed fixtures.
  * reconciliation tri-state overfit_flag (fires past threshold; None with no expectation),
    absolute + relative thresholds, and reconcile-to-total (no rounding drift).
  * determinism: same input -> byte-identical to_dict twice.
"""

import os
import sys
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.prediction_markets.evaluation_window import (  # noqa: E402
    EvaluationWindow,
    ReconciliationReport,
    ResolvedTrade,
    StrategyConfigSnapshot,
    WindowManager,
    WindowMetrics,
    build_windows,
    compute_window_metrics,
    config_hash_of,
    reconcile,
    window_start_of,
)


def _trade(strategy, dt, pnl, predicted=None, actual=None):
    return ResolvedTrade(
        strategy=strategy,
        timestamp=dt,
        pnl_usd=pnl,
        is_win=pnl > 0,
        predicted_prob=predicted,
        actual_outcome=actual,
    )


def _utc(y, m, d, h=12):
    return datetime(y, m, d, h, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# window_start_of / ISO-week bucketing
# ---------------------------------------------------------------------------

class TestWindowStart:
    def test_monday_is_its_own_start(self):
        # 2026-06-29 is a Monday.
        assert window_start_of(date(2026, 6, 29)) == date(2026, 6, 29)

    def test_wednesday_maps_back_to_monday(self):
        assert window_start_of(date(2026, 7, 1)) == date(2026, 6, 29)

    def test_sunday_maps_back_to_same_week_monday(self):
        # 2026-07-05 is a Sunday; its ISO week opened Monday 2026-06-29.
        assert window_start_of(date(2026, 7, 5)) == date(2026, 6, 29)

    def test_next_monday_is_new_window(self):
        assert window_start_of(date(2026, 7, 6)) == date(2026, 7, 6)

    def test_naive_datetime_treated_as_utc(self):
        naive = datetime(2026, 6, 30, 23, 59)
        assert window_start_of(naive) == date(2026, 6, 29)

    def test_tzaware_converted_to_utc_date(self):
        # 2026-06-29 01:00 UTC-2 == 2026-06-29 03:00 UTC -> Monday 2026-06-29.
        from datetime import timedelta, timezone as tz
        aware = datetime(2026, 6, 29, 1, 0, tzinfo=tz(timedelta(hours=-2)))
        assert window_start_of(aware) == date(2026, 6, 29)


# ---------------------------------------------------------------------------
# build_windows: assignment
# ---------------------------------------------------------------------------

class TestBuildWindows:
    def test_groups_into_iso_weeks(self):
        trades = [
            _trade("a", _utc(2026, 6, 29), 10.0),  # week of 06-29
            _trade("a", _utc(2026, 7, 1), 5.0),    # same week
            _trade("a", _utc(2026, 7, 6), -3.0),   # next week 07-06
        ]
        windows = build_windows(trades)
        assert [w.window_start for w in windows] == [date(2026, 6, 29), date(2026, 7, 6)]
        assert windows[0].window_end == date(2026, 7, 6)
        assert len(windows[0].trades) == 2
        assert len(windows[1].trades) == 1

    def test_windows_sorted_ascending(self):
        trades = [
            _trade("a", _utc(2026, 7, 20), 1.0),
            _trade("a", _utc(2026, 6, 29), 1.0),
            _trade("a", _utc(2026, 7, 6), 1.0),
        ]
        windows = build_windows(trades)
        starts = [w.window_start for w in windows]
        assert starts == sorted(starts)

    def test_zero_trade_windows_not_emitted(self):
        # A gap week (06-29 then 07-13) must NOT produce a fabricated empty window.
        trades = [
            _trade("a", _utc(2026, 6, 29), 1.0),
            _trade("a", _utc(2026, 7, 13), 1.0),
        ]
        windows = build_windows(trades)
        assert [w.window_start for w in windows] == [date(2026, 6, 29), date(2026, 7, 13)]
        # The skipped 07-06 week is absent.
        assert date(2026, 7, 6) not in [w.window_start for w in windows]

    def test_empty_input_yields_no_windows(self):
        assert build_windows([]) == []

    def test_trades_ordered_by_date_then_input_index(self):
        # Two same-day trades keep input order; later day comes after.
        t_late = _trade("a", _utc(2026, 7, 6), 1.0)
        t_early1 = _trade("a", _utc(2026, 6, 29, 9), 2.0)
        t_early2 = _trade("a", _utc(2026, 6, 29, 9), 3.0)
        windows = build_windows([t_late, t_early1, t_early2])
        w0 = windows[0]
        assert [t.pnl_usd for t in w0.trades] == [2.0, 3.0]  # input order preserved

    def test_window_carries_only_present_strategy_configs(self):
        cfgs = {
            "a": StrategyConfigSnapshot.create("a", {"x": 1}),
            "b": StrategyConfigSnapshot.create("b", {"y": 2}),
        }
        trades = [_trade("a", _utc(2026, 6, 29), 1.0)]
        windows = build_windows(trades, cfgs)
        assert set(windows[0].configs) == {"a"}


# ---------------------------------------------------------------------------
# StrategyConfigSnapshot / config_hash
# ---------------------------------------------------------------------------

class TestConfigSnapshot:
    def test_hash_is_deterministic(self):
        assert config_hash_of({"a": 1, "b": 2}) == config_hash_of({"a": 1, "b": 2})

    def test_hash_insensitive_to_key_order(self):
        assert config_hash_of({"a": 1, "b": 2}) == config_hash_of({"b": 2, "a": 1})

    def test_hash_changes_when_value_changes(self):
        assert config_hash_of({"a": 1}) != config_hash_of({"a": 2})

    def test_hash_changes_when_param_added(self):
        assert config_hash_of({"a": 1}) != config_hash_of({"a": 1, "b": 2})

    def test_int_and_float_value_hash_equal(self):
        # 5 and 5.0 are the same config.
        assert config_hash_of({"a": 5}) == config_hash_of({"a": 5.0})

    def test_params_are_immutable(self):
        snap = StrategyConfigSnapshot.create("a", {"x": 1})
        import types as _t
        assert isinstance(snap.params, _t.MappingProxyType)
        try:
            snap.params["x"] = 9  # type: ignore[index]
            assert False, "params should be immutable"
        except TypeError:
            pass

    def test_same_config_as(self):
        s1 = StrategyConfigSnapshot.create("a", {"x": 1})
        s2 = StrategyConfigSnapshot.create("a", {"x": 1})
        s3 = StrategyConfigSnapshot.create("a", {"x": 2})
        s4 = StrategyConfigSnapshot.create("b", {"x": 1})
        assert s1.same_config_as(s2)
        assert not s1.same_config_as(s3)
        assert not s1.same_config_as(s4)

    def test_create_derives_hash_from_params(self):
        snap = StrategyConfigSnapshot.create("a", {"x": 1, "y": 2})
        assert snap.config_hash == config_hash_of({"x": 1, "y": 2})

    def test_frozen_dataclass(self):
        snap = StrategyConfigSnapshot.create("a", {"x": 1})
        try:
            snap.name = "b"  # type: ignore[misc]
            assert False, "should be frozen"
        except Exception:
            pass


# ---------------------------------------------------------------------------
# compute_window_metrics
# ---------------------------------------------------------------------------

class TestWindowMetrics:
    def test_basic_pnl_and_hit_rate(self):
        trades = [
            _trade("a", _utc(2026, 6, 29), 100.0),
            _trade("a", _utc(2026, 6, 30), -40.0),
            _trade("a", _utc(2026, 7, 1), 60.0),
        ]
        m = compute_window_metrics(trades)
        assert m.realized_pnl_usd == 120.0
        assert m.num_trades == 3
        assert m.num_wins == 2
        assert m.hit_rate == 2 / 3

    def test_drawdown_hand_computed(self):
        # cumulative: 100, 220, 180, 280, 80 -> peak 280 trough 80 -> dd 200, pct 200/280
        trades = [
            _trade("a", _utc(2026, 6, 29), 100.0),
            _trade("a", _utc(2026, 6, 30), 120.0),
            _trade("a", _utc(2026, 7, 1), -40.0),
            _trade("a", _utc(2026, 7, 2), 100.0),
            _trade("a", _utc(2026, 7, 3), -200.0),
        ]
        m = compute_window_metrics(trades)
        assert m.max_drawdown_usd == 200.0
        assert abs(m.max_drawdown_pct - (200.0 / 280.0)) < 1e-12

    def test_no_drawdown_when_monotonic(self):
        trades = [
            _trade("a", _utc(2026, 6, 29), 10.0),
            _trade("a", _utc(2026, 6, 30), 20.0),
        ]
        m = compute_window_metrics(trades)
        assert m.max_drawdown_usd == 0.0
        assert m.max_drawdown_pct == 0.0

    def test_same_day_trades_order_by_time_not_just_date(self):
        """Two trades on the SAME calendar day at different times, listed in
        NON-chronological input order: a 3pm LOSS (−50) first, a 9am WIN (+100) second.
        Ordering by the FULL timestamp sequences them 9am-win → 3pm-loss → cumulative
        [100, 50] → a real intra-day drawdown of 50. A date-only sort (the pre-fix bug)
        preserves the input order → cumulative [−50, 50] → drawdown 0, HIDING it.
        Proven-fail pre-fix (asserts 50.0; the date-only path yields 0.0)."""
        trades = [
            _trade("a", _utc(2026, 6, 29, 15), -50.0),   # 3pm loss, listed FIRST
            _trade("a", _utc(2026, 6, 29, 9), 100.0),    # 9am win, listed SECOND
        ]
        m = compute_window_metrics(trades)
        assert m.realized_pnl_usd == 50.0       # order-invariant total
        assert m.max_drawdown_usd == 50.0       # order-DEPENDENT; date-only ordering → 0.0

    def test_same_instant_ties_follow_input_order(self):
        """Trades at the EXACT same timestamp keep their INPUT order (the index tiebreak),
        so the order-dependent drawdown is determined by input order. The two orderings
        below yield DIFFERENT drawdowns, proving the tiebreak is load-bearing (not a
        vacuous determinism check)."""
        t = _utc(2026, 6, 29, 12)
        win_first = compute_window_metrics([_trade("a", t, 100.0), _trade("a", t, -50.0)])
        loss_first = compute_window_metrics([_trade("a", t, -50.0), _trade("a", t, 100.0)])
        assert win_first.max_drawdown_usd == 50.0   # curve [100, 50] → peak 100, trough 50
        assert loss_first.max_drawdown_usd == 0.0    # curve [-50, 50] → monotone up, no dd

    def test_brier_score_hand_computed(self):
        # predicted 0.8 actual 1 -> 0.04 ; predicted 0.3 actual 0 -> 0.09 ; mean 0.065
        trades = [
            _trade("a", _utc(2026, 6, 29), 5.0, predicted=0.8, actual=1.0),
            _trade("a", _utc(2026, 6, 30), -5.0, predicted=0.3, actual=0.0),
        ]
        m = compute_window_metrics(trades)
        assert abs(m.brier_score - 0.065) < 1e-12
        assert m.brier_n == 2

    def test_brier_none_when_no_probs(self):
        trades = [_trade("a", _utc(2026, 6, 29), 5.0)]
        m = compute_window_metrics(trades)
        assert m.brier_score is None
        assert m.brier_n == 0

    def test_brier_excludes_partial_trades(self):
        # Only one trade carries BOTH prob and outcome.
        trades = [
            _trade("a", _utc(2026, 6, 29), 5.0, predicted=0.9, actual=1.0),
            _trade("a", _utc(2026, 6, 30), 5.0, predicted=0.5, actual=None),
            _trade("a", _utc(2026, 7, 1), 5.0, predicted=None, actual=1.0),
        ]
        m = compute_window_metrics(trades)
        assert m.brier_n == 1
        assert abs(m.brier_score - 0.01) < 1e-12

    def test_empty_raises(self):
        try:
            compute_window_metrics([])
            assert False, "should refuse empty"
        except ValueError:
            pass

    def test_total_reconciles_to_parts(self):
        pnls = [12.34, -5.67, 8.9, -1.1, 0.03]
        trades = [_trade("a", _utc(2026, 7, 1 + i), p) for i, p in enumerate(pnls)]
        m = compute_window_metrics(trades)
        assert m.realized_pnl_usd == sum(pnls)


# ---------------------------------------------------------------------------
# reconcile: tri-state overfit_flag
# ---------------------------------------------------------------------------

class TestReconcile:
    def test_none_expectation_gives_unknown_flag(self):
        r = reconcile(realized_pnl_usd=100.0, expected_pnl_usd=None, threshold=10.0)
        assert r.overfit_flag is None
        assert r.divergence_usd is None
        assert r.divergence_pct is None
        assert r.expected_pnl_usd is None

    def test_flag_false_within_absolute_threshold(self):
        r = reconcile(105.0, 100.0, threshold=10.0, threshold_kind="absolute")
        assert r.overfit_flag is False
        assert r.divergence_usd == 5.0

    def test_flag_true_past_absolute_threshold(self):
        r = reconcile(130.0, 100.0, threshold=10.0, threshold_kind="absolute")
        assert r.overfit_flag is True
        assert r.divergence_usd == 30.0

    def test_flag_negative_divergence_uses_abs(self):
        r = reconcile(60.0, 100.0, threshold=10.0, threshold_kind="absolute")
        assert r.overfit_flag is True
        assert r.divergence_usd == -40.0

    def test_relative_threshold_within(self):
        # divergence 5 / |100| = 0.05 ; threshold 0.10 -> within
        r = reconcile(105.0, 100.0, threshold=0.10, threshold_kind="relative")
        assert r.overfit_flag is False
        assert abs(r.divergence_pct - 0.05) < 1e-12

    def test_relative_threshold_exceeded(self):
        # divergence 30 / 100 = 0.30 > 0.10
        r = reconcile(130.0, 100.0, threshold=0.10, threshold_kind="relative")
        assert r.overfit_flag is True

    def test_relative_against_zero_expectation_is_unknown(self):
        r = reconcile(50.0, 0.0, threshold=0.10, threshold_kind="relative")
        assert r.overfit_flag is None
        assert r.divergence_usd == 50.0
        assert r.divergence_pct is None

    def test_absolute_against_zero_expectation_still_decides(self):
        r = reconcile(50.0, 0.0, threshold=10.0, threshold_kind="absolute")
        assert r.overfit_flag is True
        assert r.divergence_usd == 50.0

    def test_no_threshold_is_unknown_even_with_expectation(self):
        r = reconcile(130.0, 100.0, threshold=None)
        assert r.overfit_flag is None
        assert r.divergence_usd == 30.0  # divergence still reported

    def test_boundary_equal_is_within(self):
        # |divergence| == threshold is NOT > threshold -> not flagged.
        r = reconcile(110.0, 100.0, threshold=10.0, threshold_kind="absolute")
        assert r.overfit_flag is False

    def test_invalid_threshold_kind_raises(self):
        try:
            reconcile(1.0, 1.0, threshold=1.0, threshold_kind="bogus")
            assert False
        except ValueError:
            pass

    def test_threshold_echoed_for_auditability(self):
        # The caller's threshold/threshold_kind are echoed back for auditability even
        # when there is no expectation to test against (overfit_flag stays None) —
        # reviewer F4: the report should reflect what the caller intended to test.
        r_used = reconcile(130.0, 100.0, threshold=10.0)
        assert r_used.threshold == 10.0 and r_used.threshold_kind == "absolute"
        r_unknown = reconcile(130.0, None, threshold=10.0, threshold_kind="relative")
        assert r_unknown.overfit_flag is None        # verdict still UNKNOWN
        assert r_unknown.expected_pnl_usd is None
        assert r_unknown.threshold == 10.0           # but the intended test is preserved
        assert r_unknown.threshold_kind == "relative"


# ---------------------------------------------------------------------------
# WindowManager: config-change-at-boundary discipline
# ---------------------------------------------------------------------------

class TestWindowManagerBoundaryDiscipline:
    def _trades_two_weeks(self):
        return [
            _trade("a", _utc(2026, 6, 29), 1.0),   # window 06-29
            _trade("a", _utc(2026, 7, 1), 1.0),    # window 06-29 (same week)
            _trade("a", _utc(2026, 7, 6), 1.0),    # window 07-06
            _trade("a", _utc(2026, 7, 8), 1.0),    # window 07-06
        ]

    def test_initial_config_applies_to_first_window(self):
        mgr = WindowManager()
        v1 = StrategyConfigSnapshot.create("a", {"size": 1})
        mgr.set_config(v1)
        windows = mgr.build(self._trades_two_weeks())
        assert windows[0].configs["a"].config_hash == v1.config_hash

    def test_mid_window_change_does_not_rewrite_closed_window(self):
        mgr = WindowManager()
        v1 = StrategyConfigSnapshot.create("a", {"size": 1})
        v2 = StrategyConfigSnapshot.create("a", {"size": 2})
        mgr.set_config(v1)
        # Change requested during the first window (06-29) -> applies at NEXT boundary.
        mgr.request_config_change(v2, effective_after=date(2026, 6, 29))
        windows = mgr.build(self._trades_two_weeks())
        # First window keeps v1 (not retroactively rewritten)...
        assert windows[0].configs["a"].config_hash == v1.config_hash
        # ...second window picks up v2 at the boundary.
        assert windows[1].configs["a"].config_hash == v2.config_hash

    def test_change_effective_before_all_windows_applies_from_first(self):
        mgr = WindowManager()
        v1 = StrategyConfigSnapshot.create("a", {"size": 1})
        v2 = StrategyConfigSnapshot.create("a", {"size": 2})
        mgr.set_config(v1)
        # effective_after a week BEFORE the first window -> v2 active from window 1.
        mgr.request_config_change(v2, effective_after=date(2026, 6, 22))
        windows = mgr.build(self._trades_two_weeks())
        assert windows[0].configs["a"].config_hash == v2.config_hash
        assert windows[1].configs["a"].config_hash == v2.config_hash

    def test_change_at_same_week_boundary_not_applied_that_window(self):
        # A change whose boundary == a window's start lands at the NEXT boundary, never
        # mid-window. effective_after 07-06 must not affect window 07-06.
        mgr = WindowManager()
        v1 = StrategyConfigSnapshot.create("a", {"size": 1})
        v2 = StrategyConfigSnapshot.create("a", {"size": 2})
        mgr.set_config(v1)
        mgr.request_config_change(v2, effective_after=date(2026, 7, 6))
        windows = mgr.build(self._trades_two_weeks())
        assert windows[1].configs["a"].config_hash == v1.config_hash  # unchanged

    def test_config_held_stable_within_window(self):
        # Even with many trades on different days inside one window, the config is one
        # snapshot for the whole window.
        mgr = WindowManager()
        v1 = StrategyConfigSnapshot.create("a", {"size": 1})
        mgr.set_config(v1)
        windows = mgr.build([
            _trade("a", _utc(2026, 6, 29), 1.0),
            _trade("a", _utc(2026, 7, 2), 1.0),
            _trade("a", _utc(2026, 7, 5), 1.0),
        ])
        assert len(windows) == 1
        assert windows[0].configs["a"].config_hash == v1.config_hash

    def test_multiple_strategies_independent_configs(self):
        mgr = WindowManager()
        a1 = StrategyConfigSnapshot.create("a", {"x": 1})
        b1 = StrategyConfigSnapshot.create("b", {"y": 1})
        b2 = StrategyConfigSnapshot.create("b", {"y": 2})
        mgr.set_config(a1)
        mgr.set_config(b1)
        mgr.request_config_change(b2, effective_after=date(2026, 6, 29))
        trades = [
            _trade("a", _utc(2026, 6, 29), 1.0),
            _trade("b", _utc(2026, 6, 29), 1.0),
            _trade("a", _utc(2026, 7, 6), 1.0),
            _trade("b", _utc(2026, 7, 6), 1.0),
        ]
        windows = mgr.build(trades)
        # a unchanged across both windows; b changes at the second.
        assert windows[0].configs["a"].config_hash == a1.config_hash
        assert windows[1].configs["a"].config_hash == a1.config_hash
        assert windows[0].configs["b"].config_hash == b1.config_hash
        assert windows[1].configs["b"].config_hash == b2.config_hash


# ---------------------------------------------------------------------------
# Determinism / serialization
# ---------------------------------------------------------------------------

class TestDeterminism:
    def _trades(self):
        return [
            _trade("b", _utc(2026, 6, 29), 10.0, predicted=0.7, actual=1.0),
            _trade("a", _utc(2026, 6, 30), -4.0, predicted=0.6, actual=0.0),
            _trade("a", _utc(2026, 7, 6), 8.0),
        ]

    def test_window_to_dict_byte_identical_twice(self):
        import json
        cfgs = {
            "a": StrategyConfigSnapshot.create("a", {"k": 1}),
            "b": StrategyConfigSnapshot.create("b", {"k": 2}),
        }
        w1 = build_windows(self._trades(), cfgs)
        w2 = build_windows(self._trades(), cfgs)
        d1 = json.dumps([w.to_dict() for w in w1], sort_keys=True)
        d2 = json.dumps([w.to_dict() for w in w2], sort_keys=True)
        assert d1 == d2

    def test_reconcile_to_dict_byte_identical(self):
        import json
        r1 = reconcile(130.0, 100.0, threshold=10.0)
        r2 = reconcile(130.0, 100.0, threshold=10.0)
        assert json.dumps(r1.to_dict(), sort_keys=True) == json.dumps(
            r2.to_dict(), sort_keys=True
        )

    def test_metrics_to_dict_byte_identical(self):
        import json
        m1 = compute_window_metrics(self._trades()[:2])
        m2 = compute_window_metrics(self._trades()[:2])
        assert json.dumps(m1.to_dict(), sort_keys=True) == json.dumps(
            m2.to_dict(), sort_keys=True
        )

    def test_config_keys_sorted_in_dict(self):
        snap = StrategyConfigSnapshot.create("a", {"z": 1, "a": 2, "m": 3})
        keys = list(snap.to_dict()["params"].keys())
        assert keys == sorted(keys)

    def test_naive_and_utc_same_window_bucket(self):
        naive = build_windows([_trade("a", datetime(2026, 6, 29, 12), 1.0)])
        aware = build_windows([_trade("a", _utc(2026, 6, 29), 1.0)])
        assert naive[0].window_start == aware[0].window_start

    def test_window_metrics_returns_windowmetrics_type(self):
        w = build_windows(self._trades())
        assert isinstance(w[0].metrics(), WindowMetrics)


# ---------------------------------------------------------------------------
# Frozen / immutability sanity
# ---------------------------------------------------------------------------

class TestImmutability:
    def test_window_is_frozen(self):
        w = build_windows([_trade("a", _utc(2026, 6, 29), 1.0)])[0]
        try:
            w.window_start = date(2020, 1, 1)  # type: ignore[misc]
            assert False
        except Exception:
            pass

    def test_window_configs_immutable(self):
        import types as _t
        cfgs = {"a": StrategyConfigSnapshot.create("a", {"x": 1})}
        w = build_windows([_trade("a", _utc(2026, 6, 29), 1.0)], cfgs)[0]
        assert isinstance(w.configs, _t.MappingProxyType)

    def test_reconciliation_report_frozen(self):
        r = reconcile(1.0, 1.0, threshold=1.0)
        assert isinstance(r, ReconciliationReport)
        try:
            r.overfit_flag = True  # type: ignore[misc]
            assert False
        except Exception:
            pass

    def test_trades_stored_as_tuple(self):
        w = build_windows([_trade("a", _utc(2026, 6, 29), 1.0)])[0]
        assert isinstance(w.trades, tuple)

    def test_evaluation_window_type(self):
        w = build_windows([_trade("a", _utc(2026, 6, 29), 1.0)])[0]
        assert isinstance(w, EvaluationWindow)


# ---------------------------------------------------------------------------
# Integration: build windows + metrics + reconcile end to end
# ---------------------------------------------------------------------------

class TestEndToEnd:
    def test_full_loop_window_close_reconcile(self):
        mgr = WindowManager()
        mgr.set_config(StrategyConfigSnapshot.create("a", {"edge": 0.05}))
        trades = [
            _trade("a", _utc(2026, 6, 29), 50.0),
            _trade("a", _utc(2026, 6, 30), -10.0),
            _trade("a", _utc(2026, 7, 6), 200.0),
        ]
        windows = mgr.build(trades)
        assert len(windows) == 2

        m0 = windows[0].metrics()
        assert m0.realized_pnl_usd == 40.0
        # Backtest said this window should make 38; threshold 5 absolute -> within.
        r0 = reconcile(m0.realized_pnl_usd, 38.0, threshold=5.0)
        assert r0.overfit_flag is False

        m1 = windows[1].metrics()
        assert m1.realized_pnl_usd == 200.0
        # Backtest said 50; realized 200 -> big divergence -> overfit flagged.
        r1 = reconcile(m1.realized_pnl_usd, 50.0, threshold=5.0)
        assert r1.overfit_flag is True

        # No backtest expectation for a hypothetical window -> unknown, not False.
        r_unknown = reconcile(m1.realized_pnl_usd, None, threshold=5.0)
        assert r_unknown.overfit_flag is None
