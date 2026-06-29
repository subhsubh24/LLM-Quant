"""
Tests for strategy_registry.py — alpha lifecycle state machine (ROADMAP B3 / E4).

Pins the guards that make the lifecycle real: illegal transitions raise, the integrity
gate refuses to PROMOTE without recorded backtest+OOS+calibration evidence, retirement is
always reachable, and serialization round-trips deterministically.
"""

import os
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.prediction_markets.strategy_registry import (  # noqa: E402
    AlphaRecord,
    Evidence,
    IllegalTransition,
    LifecycleState,
    MissingEvidence,
    StrategyRegistry,
)


def _t(day: int) -> datetime:
    return datetime(2026, 6, day, 12, 0, 0, tzinfo=timezone.utc)


def _full_evidence() -> Evidence:
    return Evidence(
        backtest_passed=True,
        oos_validated=True,
        calibration_passed=True,
        metrics=(("oos_brier", 0.18), ("n", 120.0)),
    )


class TestProposeAndQuery:
    def test_propose_creates_proposed(self):
        reg = StrategyRegistry()
        reg.propose("alpha_x", _t(1), reason="hypothesis")
        assert "alpha_x" in reg
        assert reg.state_of("alpha_x") == LifecycleState.PROPOSED
        assert reg.in_state(LifecycleState.PROPOSED) == ["alpha_x"]

    def test_duplicate_propose_raises(self):
        reg = StrategyRegistry()
        reg.propose("alpha_x", _t(1))
        with pytest.raises(IllegalTransition):
            reg.propose("alpha_x", _t(2))

    def test_get_unknown_raises(self):
        reg = StrategyRegistry()
        with pytest.raises(KeyError):
            reg.get("nope")

    def test_names_sorted(self):
        reg = StrategyRegistry()
        reg.propose("b", _t(1))
        reg.propose("a", _t(1))
        assert reg.names() == ["a", "b"]


class TestLegalPath:
    def test_full_happy_path_to_promoted(self):
        reg = StrategyRegistry()
        reg.propose("a", _t(1))
        reg.transition("a", LifecycleState.BACKTESTING, _t(2), "start backtest")
        reg.transition(
            "a", LifecycleState.PAPER, _t(3), "backtest passed",
            evidence=Evidence(backtest_passed=True),
        )
        reg.transition(
            "a", LifecycleState.PROMOTED, _t(10), "paper validated",
            evidence=_full_evidence(),
        )
        rec = reg.get("a")
        assert rec.state == LifecycleState.PROMOTED
        assert [t.to_state for t in rec.history] == [
            LifecycleState.BACKTESTING,
            LifecycleState.PAPER,
            LifecycleState.PROMOTED,
        ]


class TestIllegalTransitions:
    def test_cannot_skip_to_promoted(self):
        reg = StrategyRegistry()
        reg.propose("a", _t(1))
        with pytest.raises(IllegalTransition):
            reg.transition("a", LifecycleState.PROMOTED, _t(2), evidence=_full_evidence())

    def test_cannot_skip_proposed_to_paper(self):
        reg = StrategyRegistry()
        reg.propose("a", _t(1))
        with pytest.raises(IllegalTransition):
            reg.transition(
                "a", LifecycleState.PAPER, _t(2),
                evidence=Evidence(backtest_passed=True),
            )

    def test_retired_is_terminal(self):
        reg = StrategyRegistry()
        reg.propose("a", _t(1))
        reg.transition("a", LifecycleState.RETIRED, _t(2), "abandoned")
        with pytest.raises(IllegalTransition):
            reg.transition("a", LifecycleState.BACKTESTING, _t(3))
        with pytest.raises(IllegalTransition):
            reg.transition("a", LifecycleState.RETIRED, _t(4))


class TestIntegrityGate:
    def test_paper_requires_backtest_evidence(self):
        reg = StrategyRegistry()
        reg.propose("a", _t(1))
        reg.transition("a", LifecycleState.BACKTESTING, _t(2))
        with pytest.raises(MissingEvidence):
            reg.transition("a", LifecycleState.PAPER, _t(3))  # no evidence

    def test_promote_requires_all_three_evidences(self):
        reg = StrategyRegistry()
        reg.propose("a", _t(1))
        reg.transition("a", LifecycleState.BACKTESTING, _t(2))
        reg.transition(
            "a", LifecycleState.PAPER, _t(3), evidence=Evidence(backtest_passed=True)
        )
        # Missing oos_validated + calibration_passed → refused.
        with pytest.raises(MissingEvidence):
            reg.transition(
                "a", LifecycleState.PROMOTED, _t(4),
                evidence=Evidence(backtest_passed=True),
            )
        # Still in PAPER (no partial state change).
        assert reg.state_of("a") == LifecycleState.PAPER

    def test_retirement_from_any_state_never_needs_evidence(self):
        for start_to in (
            [LifecycleState.BACKTESTING],
            [LifecycleState.BACKTESTING, LifecycleState.PAPER],
        ):
            reg = StrategyRegistry()
            reg.propose("a", _t(1))
            day = 2
            for st in start_to:
                ev = Evidence(backtest_passed=True) if st == LifecycleState.PAPER else None
                reg.transition("a", st, _t(day), evidence=ev)
                day += 1
            reg.transition("a", LifecycleState.RETIRED, _t(day), "decayed")
            assert reg.state_of("a") == LifecycleState.RETIRED


class TestSerialization:
    def test_round_trip_deterministic(self):
        reg = StrategyRegistry()
        reg.propose("a", _t(1))
        reg.transition("a", LifecycleState.BACKTESTING, _t(2), "start")
        reg.transition(
            "a", LifecycleState.PAPER, _t(3), "ok", evidence=Evidence(backtest_passed=True)
        )
        reg.propose("b", _t(1))

        d1 = reg.to_dict()
        reg2 = StrategyRegistry.from_dict(d1)
        d2 = reg2.to_dict()
        assert d1 == d2  # byte-stable round trip
        assert reg2.state_of("a") == LifecycleState.PAPER
        assert reg2.state_of("b") == LifecycleState.PROPOSED

    def test_from_dict_normalizes_naive_timestamps(self):
        # Externally-authored JSON with NAIVE ISO timestamps must be normalized to UTC so
        # a later to_dict() is host-timezone-independent (determinism guard).
        blob = {
            "alphas": [
                {
                    "name": "a",
                    "state": "backtesting",
                    "created_at": "2026-06-01T12:00:00",  # naive
                    "history": [
                        {
                            "at": "2026-06-02T09:00:00",  # naive
                            "from_state": "proposed",
                            "to_state": "backtesting",
                            "reason": "start",
                            "evidence": {},
                        }
                    ],
                }
            ]
        }
        reg = StrategyRegistry.from_dict(blob)
        assert reg.get("a").created_at.tzinfo is not None
        assert reg.get("a").history[0].at.tzinfo is not None
        # round-trips to explicit +00:00 form, and is stable on a second pass
        d1 = reg.to_dict()
        assert d1["alphas"][0]["created_at"] == "2026-06-01T12:00:00+00:00"
        assert StrategyRegistry.from_dict(d1).to_dict() == d1

    def test_evidence_metrics_preserved(self):
        reg = StrategyRegistry()
        reg.propose("a", _t(1))
        reg.transition("a", LifecycleState.BACKTESTING, _t(2))
        reg.transition(
            "a", LifecycleState.PAPER, _t(3),
            evidence=Evidence(backtest_passed=True, metrics=(("sharpe", 1.4),)),
        )
        d = reg.to_dict()
        ev = d["alphas"][0]["history"][-1]["evidence"]
        assert ev["metrics"]["sharpe"] == 1.4

    def test_to_dict_is_json_serializable(self):
        import json

        reg = StrategyRegistry()
        reg.propose("a", _t(1))
        reg.transition("a", LifecycleState.RETIRED, _t(2), "abandoned")
        json.dumps(reg.to_dict())  # must not raise


class TestTimestampValidation:
    def test_non_datetime_raises(self):
        reg = StrategyRegistry()
        reg.propose("a", _t(1))
        with pytest.raises(TypeError):
            reg.transition("a", LifecycleState.BACKTESTING, "2026-06-02")  # type: ignore[arg-type]

    def test_naive_datetime_normalized_to_utc(self):
        reg = StrategyRegistry()
        reg.propose("a", datetime(2026, 6, 1, 12, 0, 0))  # naive
        assert reg.get("a").created_at.tzinfo is not None
