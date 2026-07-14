"""Journey test (ROADMAP B6): the per-strategy enable/disable control actually changes
WHICH strategies the scan loop runs — verifying the EFFECT, not the message (FACTORY_STANDARD
§6). The old panel toggle was a FAKE control (flipped local UI state only; the orchestrator
ran every strategy regardless). This proves the real backend loop:

  1. A disabled strategy produces NO results from a real ``scanner.scan()`` (top-level).
  2. A disabled strategy bundled inside the adaptive wrapper is skipped on the trading path
     (not just top-level ones) — otherwise disabling a wrapped strategy would be a fake
     control that never changes what the bot runs.
  3. The disabled set persists + rehydrates via StrategyEnableStore (survives restart).
  4. ``apply_persisted_strategy_states`` reads the store and disables the right strategies.

Fully offline + deterministic: a fake client returns fixed markets; the scan path never
touches the network (use_clob=False, use_whale_feed=False).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List

from sqlmodel import create_engine

from app.prediction_markets.polymarket_client import Market, Outcome, ScanResult
from app.prediction_markets.strategies import (
    BaseStrategy,
    PredictionMarketScanner,
    StrategyConfig,
)
from app.prediction_markets.advanced_strategies import AdaptiveBuySignalThreshold
from app.prediction_markets.strategy_enable_store import StrategyEnableStore, init_db
from app.prediction_markets.orchestrator import apply_persisted_strategy_states


def _market(mid: str = "m1") -> Market:
    end = datetime.now(timezone.utc) + timedelta(days=30)
    return Market(
        id=mid,
        condition_id=f"c_{mid}",
        question="Will it resolve YES?",
        slug=mid,
        description="",
        category="Test",
        end_date=end,
        outcomes=[
            Outcome(token_id=f"{mid}_yes", label="Yes", price=0.50, midpoint=0.50, volume=50_000.0),
            Outcome(token_id=f"{mid}_no", label="No", price=0.50, midpoint=0.50, volume=50_000.0),
        ],
        total_volume=50_000.0,
        liquidity=50_000.0,
        active=True,
        closed=False,
        resolved=False,
    )


class _FakeClient:
    """Returns a fixed market on the first page, empty afterwards (stops pagination)."""

    def get_markets(self, limit: int = 100, offset: int = 0) -> List[Market]:
        return [_market()] if offset == 0 else []


class _MarkerStrategy(BaseStrategy):
    """A strategy that always emits one ScanResult tagged with its own name."""

    def __init__(self, client, config, tag: str):
        super().__init__(client, config)
        self._tag = tag

    @property
    def name(self) -> str:
        return self._tag

    def scan(self, markets: List[Market]) -> List[ScanResult]:
        return [
            ScanResult(
                market=markets[0],
                strategy=self._tag,
                outcome_idx=0,
                side="BUY",
                entry_price=0.50,
                expected_value=0.55,
                edge=0.05,
                confidence=0.55,
                reason=f"marker:{self._tag}",
            )
        ]


def _new_scanner() -> PredictionMarketScanner:
    scanner = PredictionMarketScanner(_FakeClient(), use_clob=False)
    scanner.use_whale_feed = False
    return scanner


def _strategies_in(results: List[ScanResult]) -> set:
    return {r.strategy for r in results}


def test_disabling_top_level_strategy_removes_its_results_from_scan():
    cfg = StrategyConfig(dry_run=True)
    scanner = _new_scanner()
    scanner.add_strategy(_MarkerStrategy(scanner.client, cfg, "alpha"))
    scanner.add_strategy(_MarkerStrategy(scanner.client, cfg, "beta"))

    # Baseline: both run.
    assert _strategies_in(scanner.scan(market_limit=100)) == {"alpha", "beta"}

    # Disable one → its results disappear; the other is untouched (NOT the shared-config trap
    # that would disable both).
    assert scanner.set_strategy_enabled("alpha", False) is True
    assert _strategies_in(scanner.scan(market_limit=100)) == {"beta"}
    assert scanner.is_strategy_enabled("alpha") is False
    assert scanner.is_strategy_enabled("beta") is True

    # Re-enable → both return.
    assert scanner.set_strategy_enabled("alpha", True) is True
    assert _strategies_in(scanner.scan(market_limit=100)) == {"alpha", "beta"}


def test_disabling_unknown_strategy_is_a_noop_and_reports_false():
    scanner = _new_scanner()
    scanner.add_strategy(_MarkerStrategy(scanner.client, StrategyConfig(), "alpha"))
    assert scanner.set_strategy_enabled("does_not_exist", False) is False
    # The typo did NOT get recorded (can't shadow a future strategy of that name).
    assert _strategies_in(scanner.scan(market_limit=100)) == {"alpha"}


def test_disabling_a_wrapped_inner_strategy_is_respected_on_the_trading_path():
    cfg = StrategyConfig(dry_run=True)
    scanner = _new_scanner()
    adaptive = AdaptiveBuySignalThreshold(scanner.client, cfg)
    adaptive.add_inner_strategy(_MarkerStrategy(scanner.client, cfg, "inner_a"))
    adaptive.add_inner_strategy(_MarkerStrategy(scanner.client, cfg, "inner_b"))
    scanner.add_strategy(adaptive)

    # The control targets inner strategies by name (not just the wrapper).
    assert "inner_a" in scanner.registered_strategy_names()
    assert "inner_b" in scanner.registered_strategy_names()

    # Baseline: both inners' candidates pass through the wrapper (edge 0.05 clears the
    # adaptive threshold; results are tagged "adaptive_threshold" after filtering).
    base = scanner.scan(market_limit=100)
    assert base, "expected the adaptive wrapper to emit at least one result"

    # Disable one inner → the wrapper skips it. Prove the EFFECT by counting: with both inners
    # enabled the wrapper sees 2 candidates (same market), with one disabled it sees 1.
    two_inner_count = len(scanner.scan(market_limit=100))
    assert scanner.set_strategy_enabled("inner_a", False) is True
    assert scanner.is_strategy_enabled("inner_a") is False
    one_inner_count = len(scanner.scan(market_limit=100))
    assert one_inner_count < two_inner_count, (
        f"disabling a wrapped inner must reduce results ({two_inner_count} -> {one_inner_count})"
    )

    # Re-enable restores the original count.
    assert scanner.set_strategy_enabled("inner_a", True) is True
    assert len(scanner.scan(market_limit=100)) == two_inner_count


def test_enable_store_persists_and_rehydrates_disabled_set():
    engine = create_engine("sqlite://")
    init_db(engine)
    store = StrategyEnableStore(engine=engine)

    # Absent row → empty (fail-open, all enabled).
    assert store.load_disabled() == set()

    assert store.save_disabled({"alpha", "gamma"}) is True
    # A FRESH store on the same engine (simulating a restart) rehydrates the same set.
    assert StrategyEnableStore(engine=engine).load_disabled() == {"alpha", "gamma"}

    # Clearing persists too.
    assert store.save_disabled(set()) is True
    assert StrategyEnableStore(engine=engine).load_disabled() == set()


def test_apply_persisted_strategy_states_disables_from_the_store(monkeypatch):
    engine = create_engine("sqlite://")
    init_db(engine)
    StrategyEnableStore(engine=engine).save_disabled({"beta"})

    # apply_persisted_strategy_states does `from .strategy_enable_store import StrategyEnableStore`
    # at call time, so patching the name in that module points it at our in-memory engine.
    import app.prediction_markets.strategy_enable_store as store_mod
    monkeypatch.setattr(
        store_mod, "StrategyEnableStore", lambda *a, **k: StrategyEnableStore(engine=engine)
    )

    cfg = StrategyConfig(dry_run=True)
    scanner = _new_scanner()
    scanner.add_strategy(_MarkerStrategy(scanner.client, cfg, "alpha"))
    scanner.add_strategy(_MarkerStrategy(scanner.client, cfg, "beta"))

    apply_persisted_strategy_states(scanner)

    assert scanner.is_strategy_enabled("beta") is False
    assert scanner.is_strategy_enabled("alpha") is True
    assert _strategies_in(scanner.scan(market_limit=100)) == {"alpha"}
