"""
Tests for per_strategy_metrics.py — per-strategy realized-PnL attribution (ROADMAP E6).

Pins the math (totals, hit-rate, weekly bucketing), determinism (sorted output), and the
honesty property (zero-trade strategies never appear; no fabricated 0/0).
"""

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.prediction_markets.per_strategy_metrics import (  # noqa: E402
    StrategyTradePnL,
    attribute_by_strategy,
    rank_by_total_pnl,
)


def _trade(strategy: str, day: int, pnl: float) -> StrategyTradePnL:
    return StrategyTradePnL(
        strategy=strategy,
        timestamp=datetime(2026, 6, day, 12, 0, 0, tzinfo=timezone.utc),
        pnl_usd=pnl,
        is_win=pnl > 0,
    )


class TestAttribution:
    def test_basic_totals_and_hit_rate(self):
        trades = [
            _trade("alpha", 1, 100.0),
            _trade("alpha", 2, -40.0),
            _trade("alpha", 3, 60.0),
            _trade("beta", 1, -10.0),
        ]
        attr = attribute_by_strategy(trades)
        assert set(attr) == {"alpha", "beta"}

        a = attr["alpha"]
        assert a.num_trades == 3
        assert a.num_wins == 2
        assert a.total_pnl_usd == 120.0
        assert abs(a.mean_pnl_usd - 40.0) < 1e-9
        assert abs(a.hit_rate - (2 / 3)) < 1e-9
        assert a.best_trade_usd == 100.0
        assert a.worst_trade_usd == -40.0

        b = attr["beta"]
        assert b.num_trades == 1
        assert b.hit_rate == 0.0
        assert b.total_pnl_usd == -10.0

    def test_zero_trade_strategy_absent(self):
        # A strategy with no trades simply never appears — no fabricated 0/0 row.
        attr = attribute_by_strategy([_trade("alpha", 1, 10.0)])
        assert "ghost" not in attr
        assert list(attr) == ["alpha"]

    def test_empty_input(self):
        assert attribute_by_strategy([]) == {}

    def test_weekly_bucketing(self):
        # 2026-06-01 is a Monday. Days 1-3 share week 2026-06-01; day 8 is the next week.
        trades = [
            _trade("alpha", 1, 10.0),
            _trade("alpha", 3, 5.0),
            _trade("alpha", 8, 20.0),
        ]
        a = attribute_by_strategy(trades)["alpha"]
        assert a.weekly_pnl == {"2026-06-01": 15.0, "2026-06-08": 20.0}
        # weeks are in sorted order
        assert list(a.weekly_pnl) == sorted(a.weekly_pnl)

    def test_weekly_reconciles_to_total_exactly(self):
        # Float-noisy values that would not reconcile under inconsistent rounding.
        trades = [
            _trade("a", 1, 0.1),
            _trade("a", 2, 0.2),
            _trade("a", 9, 0.1),  # next week
        ]
        a = attribute_by_strategy(trades)["a"]
        assert sum(a.weekly_pnl.values()) == a.total_pnl_usd

    def test_weekly_pnl_is_immutable(self):
        import pytest

        a = attribute_by_strategy([_trade("a", 1, 10.0)])["a"]
        with pytest.raises(TypeError):
            a.weekly_pnl["2026-06-01"] = 999.0  # type: ignore[index]

    def test_naive_timestamp_treated_as_utc(self):
        t = StrategyTradePnL(
            strategy="a",
            timestamp=datetime(2026, 6, 1, 12, 0, 0),  # naive
            pnl_usd=5.0,
            is_win=True,
        )
        a = attribute_by_strategy([t])["a"]
        assert "2026-06-01" in a.weekly_pnl


class TestRanking:
    def test_rank_by_total_pnl_desc_with_name_tiebreak(self):
        trades = [
            _trade("low", 1, -50.0),
            _trade("high", 1, 200.0),
            _trade("mid_b", 1, 10.0),
            _trade("mid_a", 1, 10.0),  # tie with mid_b → name asc
        ]
        ranked = rank_by_total_pnl(attribute_by_strategy(trades))
        assert [r.strategy for r in ranked] == ["high", "mid_a", "mid_b", "low"]

    def test_rank_empty(self):
        assert rank_by_total_pnl({}) == []
