"""
Tests for prediction market module.

Covers:
- Kelly criterion sizing
- Strategy scanning (all 7 strategies)
- Execution engine (dry-run)
- Risk manager (circuit breaker, rate limiting, etc.)
- Orchestrator lifecycle
- Persistence (model field alignment)
- Whale copy exit logic
- Cross-market implication rules
"""

import asyncio
import json
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

# ============================================================
# Shared test fixtures
# ============================================================

from app.prediction_markets.polymarket_client import Market, Outcome, ScanResult


def _make_market(
    mid: str = "m1",
    question: str = "Will BTC exceed $100k?",
    yes_price: float = 0.60,
    volume: float = 100_000,
    liquidity: float = 50_000,
    category: str = "Crypto",
    end_hours: float = 48,
    active: bool = True,
    closed: bool = False,
    resolved: bool = False,
) -> Market:
    """Helper to build a Market for tests."""
    no_price = round(1.0 - yes_price, 4)
    end_date = datetime.now(timezone.utc) + timedelta(hours=end_hours) if end_hours else None
    return Market(
        id=mid,
        condition_id=mid,
        question=question,
        slug=mid,
        description="",
        category=category,
        end_date=end_date,
        outcomes=[
            Outcome(token_id=f"{mid}_yes", label="Yes", price=yes_price, midpoint=yes_price, volume=volume),
            Outcome(token_id=f"{mid}_no", label="No", price=no_price, midpoint=no_price, volume=volume),
        ],
        total_volume=volume,
        liquidity=liquidity,
        active=active,
        closed=closed,
        resolved=resolved,
        resolution_source="polymarket",
        tags=[],
        neg_risk=False,
    )


def _make_scan_result(
    market: Market = None,
    strategy: str = "test",
    edge: float = 0.10,
    confidence: float = 0.75,
    entry_price: float = 0.50,
) -> ScanResult:
    if market is None:
        market = _make_market()
    return ScanResult(
        market=market,
        strategy=strategy,
        outcome_idx=0,
        side="BUY",
        entry_price=entry_price,
        expected_value=entry_price + edge,
        edge=edge,
        confidence=confidence,
        reason="test signal",
    )


# ============================================================
# Kelly Criterion Tests
# ============================================================

class TestKellySizing:
    def test_positive_edge_returns_nonzero(self):
        from app.prediction_markets.orchestrator import kelly_size, KellyConfig
        config = KellyConfig()
        result = kelly_size(
            edge=0.10, confidence=0.80, win_probability=0.60,
            bankroll=1000.0, config=config,
        )
        assert result > 0

    def test_zero_edge_returns_zero(self):
        from app.prediction_markets.orchestrator import kelly_size, KellyConfig
        config = KellyConfig()
        result = kelly_size(
            edge=0.0, confidence=0.80, win_probability=0.50,
            bankroll=1000.0, config=config,
        )
        assert result == 0.0

    def test_below_min_edge_returns_zero(self):
        from app.prediction_markets.orchestrator import kelly_size, KellyConfig
        config = KellyConfig(min_edge=0.05)
        result = kelly_size(
            edge=0.02, confidence=0.80, win_probability=0.52,
            bankroll=1000.0, config=config,
        )
        assert result == 0.0

    def test_low_confidence_returns_zero(self):
        from app.prediction_markets.orchestrator import kelly_size, KellyConfig
        config = KellyConfig(min_confidence=0.70)
        result = kelly_size(
            edge=0.10, confidence=0.50, win_probability=0.60,
            bankroll=1000.0, config=config,
        )
        assert result == 0.0

    def test_zero_bankroll_returns_zero(self):
        from app.prediction_markets.orchestrator import kelly_size, KellyConfig
        result = kelly_size(
            edge=0.10, confidence=0.80, win_probability=0.60,
            bankroll=0.0, config=KellyConfig(),
        )
        assert result == 0.0

    def test_bet_capped_at_max(self):
        from app.prediction_markets.orchestrator import kelly_size, KellyConfig
        config = KellyConfig(max_bet_usd=10.0, fractional_kelly=1.0)
        result = kelly_size(
            edge=0.30, confidence=0.95, win_probability=0.80,
            bankroll=100_000, config=config,
        )
        assert result <= 10.0

    def test_non_finite_inputs_return_zero(self):
        """Every NaN/inf sizing input must return 0.0 (fail closed). NaN defeats the
        `x < threshold` pre-filters (NaN comparisons are always False). WITHOUT the guard,
        3 of these 6 cases LEAK on pre-fix code (verified): confidence=NaN BYPASSES the
        min-confidence gate and places a real $50 bet; bankroll=NaN returns a NaN-sized
        order; bankroll=inf returns a max bet. (The edge=NaN / win_probability=NaN / edge=inf
        cases already returned 0.0 via the market_price/`b>0` guards — pinned here as
        belt-and-suspenders.) Post-fix ALL six return 0.0."""
        import math

        from app.prediction_markets.orchestrator import kelly_size, KellyConfig
        config = KellyConfig()
        nan, inf = float("nan"), float("inf")
        cases = [
            dict(edge=nan, confidence=0.8, win_probability=0.6, bankroll=1000.0),
            dict(edge=0.1, confidence=nan, win_probability=0.6, bankroll=1000.0),
            dict(edge=0.1, confidence=0.8, win_probability=nan, bankroll=1000.0),
            dict(edge=0.1, confidence=0.8, win_probability=0.6, bankroll=nan),
            dict(edge=inf, confidence=0.8, win_probability=0.6, bankroll=1000.0),
            dict(edge=0.1, confidence=0.8, win_probability=0.6, bankroll=inf),
        ]
        for kwargs in cases:
            result = kelly_size(config=config, **kwargs)
            assert result == 0.0, f"expected 0.0, got {result} for {kwargs}"
            assert math.isfinite(result)

    def test_fractional_kelly_reduces_bet(self):
        from app.prediction_markets.orchestrator import kelly_size, KellyConfig
        full = kelly_size(
            edge=0.15, confidence=0.80, win_probability=0.65,
            bankroll=1000.0, config=KellyConfig(fractional_kelly=1.0, max_bet_usd=500),
        )
        quarter = kelly_size(
            edge=0.15, confidence=0.80, win_probability=0.65,
            bankroll=1000.0, config=KellyConfig(fractional_kelly=0.25, max_bet_usd=500),
        )
        if full > 0 and quarter > 0:
            assert quarter < full

    def test_size_from_scan_result(self):
        from app.prediction_markets.orchestrator import size_from_scan_result, KellyConfig
        result = _make_scan_result(edge=0.12, confidence=0.80, entry_price=0.50)
        bet_usd, contracts = size_from_scan_result(result, bankroll=500.0, config=KellyConfig())
        assert bet_usd >= 0
        assert contracts >= 0


# ============================================================
# Strategy Tests
# ============================================================

class TestNearCertaintyStrategy:
    def test_finds_95c_outcome(self):
        from app.prediction_markets.strategies import NearCertaintyStrategy, StrategyConfig
        from app.prediction_markets.polymarket_client import PolymarketClient
        client = PolymarketClient()
        strat = NearCertaintyStrategy(client, StrategyConfig(), min_volume=0)
        market = _make_market(yes_price=0.97, volume=100_000, end_hours=24)
        results = strat.scan([market])
        assert len(results) >= 1
        assert results[0].strategy == "near_certainty"

    def test_ignores_low_price(self):
        from app.prediction_markets.strategies import NearCertaintyStrategy, StrategyConfig
        from app.prediction_markets.polymarket_client import PolymarketClient
        client = PolymarketClient()
        strat = NearCertaintyStrategy(client, StrategyConfig(), min_volume=0)
        market = _make_market(yes_price=0.50, volume=100_000, end_hours=24)
        results = strat.scan([market])
        assert len(results) == 0

    @pytest.mark.xfail(
        reason="KNOWN INTEGRITY ITEM (ROADMAP F1): NearCertaintyStrategy docstring says "
        "'within 72h' but max_hours_to_resolution defaults to 720 (30 days). This stale "
        "test asserts the old 72h behavior. Resolve by deciding 72h vs 720h with the "
        "owner (a trading-behavior decision) before un-xfailing — do NOT silently change "
        "strategy behavior to satisfy the test.",
        strict=False,
    )
    def test_ignores_far_resolution(self):
        from app.prediction_markets.strategies import NearCertaintyStrategy, StrategyConfig
        from app.prediction_markets.polymarket_client import PolymarketClient
        client = PolymarketClient()
        strat = NearCertaintyStrategy(client, StrategyConfig(), min_volume=0)
        # Market resolves in 200 hours (beyond the docstring's 72h limit)
        market = _make_market(yes_price=0.97, volume=100_000, end_hours=200)
        results = strat.scan([market])
        assert len(results) == 0


class TestSameMarketArbStrategy:
    def test_finds_underpriced_pair(self):
        from app.prediction_markets.strategies import SameMarketArbitrageStrategy, StrategyConfig
        from app.prediction_markets.polymarket_client import PolymarketClient
        client = PolymarketClient()
        strat = SameMarketArbitrageStrategy(client, StrategyConfig(min_liquidity=0))
        # YES=0.47 + NO=0.48 = 0.95 → 5% discount, 3% after fees
        market = _make_market(yes_price=0.47)
        market.outcomes[1].price = 0.48
        results = strat.scan([market])
        assert len(results) >= 1
        assert results[0].strategy == "same_market_arb"

    def test_ignores_fair_pair(self):
        from app.prediction_markets.strategies import SameMarketArbitrageStrategy, StrategyConfig
        from app.prediction_markets.polymarket_client import PolymarketClient
        client = PolymarketClient()
        strat = SameMarketArbitrageStrategy(client, StrategyConfig(min_liquidity=0))
        market = _make_market(yes_price=0.50)  # YES=0.50 + NO=0.50 = 1.00
        results = strat.scan([market])
        assert len(results) == 0


class TestMarketMakingStrategy:
    def test_finds_wide_spread_market(self):
        from app.prediction_markets.strategies import MarketMakingStrategy, StrategyConfig
        from app.prediction_markets.polymarket_client import PolymarketClient
        client = PolymarketClient()
        strat = MarketMakingStrategy(client, StrategyConfig(), min_liquidity=0)
        # Spread = abs(1 - (0.47 + 0.49)) = 0.04
        market = _make_market(yes_price=0.47, liquidity=50_000)
        market.outcomes[1].price = 0.49
        assert market.spread > 0.02  # Confirm spread is wide enough
        results = strat.scan([market])
        assert len(results) >= 1
        assert results[0].strategy == "market_making"

    def test_skips_extreme_prices(self):
        from app.prediction_markets.strategies import MarketMakingStrategy, StrategyConfig
        from app.prediction_markets.polymarket_client import PolymarketClient
        client = PolymarketClient()
        strat = MarketMakingStrategy(client, StrategyConfig(), min_liquidity=0)
        # Extreme price (>0.90) should be skipped even with wide spread
        market = _make_market(yes_price=0.95, liquidity=50_000)
        market.outcomes[1].price = 0.01  # spread = abs(1 - 0.96) = 0.04
        results = strat.scan([market])
        assert len(results) == 0


class TestFlashCrashStrategy:
    def test_detects_crash(self):
        from app.prediction_markets.strategies import FlashCrashStrategy, StrategyConfig
        from app.prediction_markets.polymarket_client import PolymarketClient
        client = PolymarketClient()
        strat = FlashCrashStrategy(client, StrategyConfig(), min_volume=0)

        market = _make_market(
            question="Will BTC go up in next 15 min?",
            yes_price=0.20, volume=10_000, category="Crypto",
        )
        market.outcomes[1].price = 0.75  # Combined: 0.20 + 0.75 = 0.95

        # Seed price history with a crash
        token_id = market.outcomes[0].token_id
        for _ in range(10):
            strat.update_prices(token_id, 0.55)
        strat.update_prices(token_id, 0.20)

        results = strat.scan([market])
        assert len(results) >= 1
        assert "FLASH CRASH" in results[0].reason


class TestCrossMarketArbImplicationRules:
    def test_implication_violation_detected(self):
        from app.prediction_markets.strategies import (
            CrossMarketArbitrageStrategy, StrategyConfig, ImplicationRule,
        )
        from app.prediction_markets.polymarket_client import PolymarketClient
        client = PolymarketClient()
        rules = [ImplicationRule("win election", "win pennsylvania", "implies", "Politics")]
        strat = CrossMarketArbitrageStrategy(client, StrategyConfig(), custom_rules=rules)

        # Parent (election) at 70%, child (state) at 50% → violation
        parent = _make_market(
            mid="election", question="Will X win election?",
            yes_price=0.70, category="Politics",
        )
        child = _make_market(
            mid="pa", question="Will X win pennsylvania?",
            yes_price=0.50, category="Politics",
        )
        results = strat.scan([parent, child])
        assert any("IMPLICATION VIOLATION" in r.reason for r in results)

    def test_no_violation_when_consistent(self):
        from app.prediction_markets.strategies import (
            CrossMarketArbitrageStrategy, StrategyConfig, ImplicationRule,
        )
        from app.prediction_markets.polymarket_client import PolymarketClient
        client = PolymarketClient()
        rules = [ImplicationRule("win election", "win pennsylvania", "implies", "Politics")]
        strat = CrossMarketArbitrageStrategy(client, StrategyConfig(), custom_rules=rules)

        parent = _make_market(
            mid="election", question="Will X win election?",
            yes_price=0.50, category="Politics",
        )
        child = _make_market(
            mid="pa", question="Will X win pennsylvania?",
            yes_price=0.65, category="Politics",
        )
        results = strat.scan([parent, child])
        implication_results = [r for r in results if "IMPLICATION" in r.reason]
        assert len(implication_results) == 0


class TestWhaleCopyExits:
    def _make_strategy(self):
        from app.prediction_markets.strategies import WhaleCopyTradingStrategy, StrategyConfig
        from app.prediction_markets.polymarket_client import PolymarketClient
        client = PolymarketClient()
        return WhaleCopyTradingStrategy(
            client, StrategyConfig(),
            trailing_stop_pct=0.15,
            time_exit_hours=2.0,
            profit_target_pct=0.30,
        )

    def test_trailing_stop_fires(self):
        strat = self._make_strategy()
        market = _make_market(mid="m1", yes_price=0.40)
        token_id = market.outcomes[0].token_id

        strat._position_tracking[token_id] = {
            "peak_price": 0.60,
            "entry_time": datetime.now(timezone.utc) - timedelta(minutes=30),
            "entry_price": 0.50,
            "market_id": "m1",
        }
        # Current price 0.40 is a 33% drop from peak 0.60 → should trigger
        exits = strat.check_exits([market])
        assert len(exits) == 1
        assert "TRAILING STOP" in exits[0].reason

    def test_time_exit_fires(self):
        strat = self._make_strategy()
        market = _make_market(mid="m1", yes_price=0.52)
        token_id = market.outcomes[0].token_id

        strat._position_tracking[token_id] = {
            "peak_price": 0.52,
            "entry_time": datetime.now(timezone.utc) - timedelta(hours=3),
            "entry_price": 0.50,
            "market_id": "m1",
        }
        exits = strat.check_exits([market])
        assert len(exits) == 1
        assert "TIME EXIT" in exits[0].reason

    def test_profit_target_fires(self):
        strat = self._make_strategy()
        market = _make_market(mid="m1", yes_price=0.70)
        token_id = market.outcomes[0].token_id

        strat._position_tracking[token_id] = {
            "peak_price": 0.70,
            "entry_time": datetime.now(timezone.utc) - timedelta(minutes=10),
            "entry_price": 0.50,
            "market_id": "m1",
        }
        exits = strat.check_exits([market])
        assert len(exits) == 1
        assert "PROFIT TARGET" in exits[0].reason

    def test_no_exit_when_healthy(self):
        strat = self._make_strategy()
        market = _make_market(mid="m1", yes_price=0.55)
        token_id = market.outcomes[0].token_id

        strat._position_tracking[token_id] = {
            "peak_price": 0.56,
            "entry_time": datetime.now(timezone.utc) - timedelta(minutes=10),
            "entry_price": 0.50,
            "market_id": "m1",
        }
        exits = strat.check_exits([market])
        assert len(exits) == 0


# ============================================================
# Execution Engine Tests
# ============================================================

class TestExecutor:
    def test_dry_run_fills(self):
        from app.prediction_markets.execution import (
            PredictionMarketExecutor, OrderRequest, OrderSide, OrderType,
            OrderStatus, Exchange,
        )
        executor = PredictionMarketExecutor(dry_run=True)
        req = OrderRequest(
            exchange=Exchange.POLYMARKET,
            market_id="test_market",
            token_id="test_token",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            size=10.0,
            price=0.50,
            strategy="test",
        )
        result = executor.execute(req)
        assert result.is_success
        assert result.status == OrderStatus.FILLED
        assert result.filled_size == 10.0
        assert "test_token" in executor.positions

    def test_risk_check_blocks_oversized_order(self):
        from app.prediction_markets.execution import (
            PredictionMarketExecutor, OrderRequest, OrderSide, OrderType,
            OrderStatus, Exchange,
        )
        executor = PredictionMarketExecutor(dry_run=True, max_position_usd=5.0)
        req = OrderRequest(
            exchange=Exchange.POLYMARKET,
            market_id="test_market",
            token_id="test_token",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            size=100.0,
            price=0.50,
            strategy="test",
        )
        result = executor.execute(req)
        assert result.status == OrderStatus.REJECTED
        assert "Risk check" in result.error

    def test_portfolio_summary(self):
        from app.prediction_markets.execution import (
            PredictionMarketExecutor, OrderRequest, OrderSide, OrderType, Exchange,
        )
        executor = PredictionMarketExecutor(dry_run=True)
        req = OrderRequest(
            exchange=Exchange.POLYMARKET,
            market_id="test_market",
            token_id="test_token",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            size=5.0,
            price=0.40,
            strategy="near_certainty",
        )
        executor.execute(req)
        summary = executor.get_portfolio_summary()
        assert summary["total_positions"] == 1
        assert summary["dry_run"] is True
        assert summary["total_exposure"] > 0

    def test_sell_closes_position(self):
        from app.prediction_markets.execution import (
            PredictionMarketExecutor, OrderRequest, OrderSide, OrderType, Exchange,
        )
        executor = PredictionMarketExecutor(dry_run=True, max_position_usd=100)
        # Buy
        buy = OrderRequest(
            exchange=Exchange.POLYMARKET, market_id="m1", token_id="t1",
            side=OrderSide.BUY, order_type=OrderType.LIMIT, size=10.0, price=0.50,
        )
        executor.execute(buy)
        assert "t1" in executor.positions
        # Sell full
        sell = OrderRequest(
            exchange=Exchange.POLYMARKET, market_id="m1", token_id="t1",
            side=OrderSide.SELL, order_type=OrderType.LIMIT, size=10.0, price=0.60,
        )
        executor.execute(sell)
        assert "t1" not in executor.positions

    def test_market_order_without_price_rejected(self):
        # run-risk-readiness top_gaps: a MARKET order with price=None used to be submitted
        # as a FABRICATED $0.50 limit (`req.price or 0.50`, shared by the risk-gate
        # notional, the venue-submitted limit, and the paper fill). It must instead REJECT
        # — no position created, no exposure change, nothing recorded as filled.
        # PROVEN to FAIL pre-fix: pre-fix this order fills at the invented 0.50 (status
        # FILLED, "test_token" in executor.positions).
        from app.prediction_markets.execution import (
            PredictionMarketExecutor, OrderRequest, OrderSide, OrderType,
            OrderStatus, Exchange,
        )
        executor = PredictionMarketExecutor(dry_run=True)
        req = OrderRequest(
            exchange=Exchange.POLYMARKET,
            market_id="test_market",
            token_id="test_token",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            size=10.0,
            price=None,
            strategy="test",
        )
        result = executor.execute(req)
        assert result.status == OrderStatus.REJECTED
        assert "MARKET order" in (result.error or "")
        assert result.filled_size == 0.0
        assert result.filled_price == 0.0
        # No state mutation of any kind — the rejection happens before the paper fill /
        # venue call and before any position or exposure bookkeeping runs.
        assert executor.positions == {}
        assert executor.total_exposure == 0.0
        assert executor.total_fees == 0.0

    def test_market_order_without_price_rejected_on_gated_live_path_too(self):
        # The guard lives in _check_risk, which execute() calls BEFORE branching on
        # dry_run/live_enabled — so the same rejection applies whether the executor is in
        # paper mode or the (still gated-off) live branch. dry_run=False + live_enabled=False
        # here only proves the order never even reaches the live-gate check; it does NOT
        # flip LIVE_TRADING_ENABLED or place any real order.
        from app.prediction_markets.execution import (
            PredictionMarketExecutor, OrderRequest, OrderSide, OrderType,
            OrderStatus, Exchange,
        )
        executor = PredictionMarketExecutor(dry_run=False, live_enabled=False)
        req = OrderRequest(
            exchange=Exchange.POLYMARKET,
            market_id="test_market",
            token_id="test_token",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            size=10.0,
            price=None,
            strategy="test",
        )
        result = executor.execute(req)
        assert result.status == OrderStatus.REJECTED
        assert "MARKET order" in (result.error or "")
        assert executor.positions == {}

    def test_market_order_with_real_price_still_fills(self):
        # A MARKET order that DOES carry a real price must behave exactly as before — the
        # price=None guard must never touch an order that already has a usable price.
        from app.prediction_markets.execution import (
            PredictionMarketExecutor, OrderRequest, OrderSide, OrderType,
            OrderStatus, Exchange,
        )
        executor = PredictionMarketExecutor(dry_run=True)
        req = OrderRequest(
            exchange=Exchange.POLYMARKET,
            market_id="test_market",
            token_id="test_token",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            size=10.0,
            price=0.42,
            strategy="test",
        )
        result = executor.execute(req)
        assert result.status == OrderStatus.FILLED
        assert result.filled_size == 10.0
        assert "test_token" in executor.positions

    def test_priceless_order_rejected_for_every_order_type(self):
        # The guard is keyed on the MISSING PRICE, not the order type. A first cut checked
        # MARKET only; a reviewer showed the DEFAULT body POSTed to /prediction-markets/execute
        # (`order_type` defaults to "LIMIT", `price` defaults to None in PlaceOrderRequest)
        # reproduced the identical fabricated $0.50 FILL and a real position — i.e. the narrow
        # guard closed the variant the orchestrator never emits and left open the one the app's
        # own HTTP surface emits by default. Every order type must reject.
        from app.prediction_markets.execution import (
            PredictionMarketExecutor, OrderRequest, OrderSide, OrderType,
            OrderStatus, Exchange,
        )
        for order_type in (OrderType.MARKET, OrderType.LIMIT, OrderType.GTC, OrderType.FOK):
            executor = PredictionMarketExecutor(dry_run=True)
            req = OrderRequest(
                exchange=Exchange.POLYMARKET,
                market_id="test_market",
                token_id="test_token",
                side=OrderSide.BUY,
                order_type=order_type,
                size=10.0,
                price=None,
                strategy="test",
            )
            result = executor.execute(req)
            assert result.status == OrderStatus.REJECTED, order_type
            assert "no usable price" in (result.error or ""), (order_type, result.error)
            # Nothing was fabricated on the way out: no position, no exposure, no fee.
            assert executor.positions == {}, order_type
            assert executor.total_exposure == 0.0, order_type
            assert executor.total_fees == 0.0, order_type

    def test_zero_price_is_rejected_not_treated_as_a_real_price(self):
        # 0.0 is not a tradeable prediction-market price, and all seven `or 0.50` fallback
        # sites already tested falsiness rather than `is None` — so rejecting it is the
        # pre-existing semantics made explicit, not a new rule.
        from app.prediction_markets.execution import (
            PredictionMarketExecutor, OrderRequest, OrderSide, OrderType,
            OrderStatus, Exchange,
        )
        executor = PredictionMarketExecutor(dry_run=True)
        req = OrderRequest(
            exchange=Exchange.POLYMARKET,
            market_id="test_market",
            token_id="test_token",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            size=10.0,
            price=0.0,
            strategy="test",
        )
        result = executor.execute(req)
        assert result.status == OrderStatus.REJECTED
        assert executor.positions == {}

    def test_priced_limit_order_still_fills_exactly_as_before(self):
        from app.prediction_markets.execution import (
            PredictionMarketExecutor, OrderRequest, OrderSide, OrderType,
            OrderStatus, Exchange,
        )
        executor = PredictionMarketExecutor(dry_run=True)
        req = OrderRequest(
            exchange=Exchange.POLYMARKET,
            market_id="test_market",
            token_id="test_token",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            size=10.0,
            price=0.42,
            strategy="test",
        )
        result = executor.execute(req)
        assert result.status == OrderStatus.FILLED
        assert result.filled_size == 10.0
        assert "test_token" in executor.positions


# ============================================================
# Risk Manager Tests
# ============================================================

class TestRiskManager:
    def test_approves_normal_opportunity(self):
        from app.prediction_markets.risk_manager import RiskManager
        from app.prediction_markets.execution import PredictionMarketExecutor
        rm = RiskManager()
        executor = PredictionMarketExecutor(dry_run=True)
        opp = _make_scan_result()
        result = rm.check_opportunity(opp, executor)
        assert result.approved

    def test_blocks_after_daily_loss(self):
        from app.prediction_markets.risk_manager import RiskManager, RiskConfig
        from app.prediction_markets.execution import PredictionMarketExecutor
        rm = RiskManager(config=RiskConfig(daily_loss_limit_usd=10.0))
        executor = PredictionMarketExecutor(dry_run=True)
        rm._daily_pnl = -15.0
        rm._daily_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        opp = _make_scan_result()
        result = rm.check_opportunity(opp, executor)
        assert not result.approved
        assert "Daily loss limit" in result.reason

    def test_rate_limit(self):
        from app.prediction_markets.risk_manager import RiskManager, RiskConfig
        from app.prediction_markets.execution import PredictionMarketExecutor
        rm = RiskManager(config=RiskConfig(max_orders_per_minute=2))
        executor = PredictionMarketExecutor(dry_run=True)
        now = time.time()
        rm._order_timestamps = [now - 10, now - 5]  # 2 orders in last minute
        rm._daily_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        opp = _make_scan_result()
        result = rm.check_opportunity(opp, executor)
        assert not result.approved
        assert "rate limit" in result.reason.lower()

    def test_blocks_disabled_strategy(self):
        from app.prediction_markets.risk_manager import RiskManager
        from app.prediction_markets.execution import PredictionMarketExecutor
        rm = RiskManager()
        executor = PredictionMarketExecutor(dry_run=True)
        rm._disabled_strategies.add("test")
        rm._daily_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        opp = _make_scan_result(strategy="test")
        result = rm.check_opportunity(opp, executor)
        assert not result.approved
        assert "disabled" in result.reason.lower()

    def test_enable_strategy(self):
        from app.prediction_markets.risk_manager import RiskManager
        rm = RiskManager()
        rm._disabled_strategies.add("test")
        rm.enable_strategy("test")
        assert "test" not in rm._disabled_strategies


class TestRiskManagerHardening:
    """Deep-audit hardening: the category cap must not be under-counted, and the risk
    score must never crash on a zero/unset config limit."""

    def _today(self):
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def test_category_estimate_uses_conservative_single_position_bound(self):
        """A full-size Kelly trade must not slip past the category cap.

        The old `entry_price * 10` estimate (~$5 at a $0.50 price) under-counted the add,
        so a real max_single_position_usd ($50) trade could breach the category cap. With
        the cap at $40 and an empty category, the conservative estimate ($50) BLOCKS it —
        the old estimate ($5) would have wrongly approved it.
        """
        from app.prediction_markets.risk_manager import RiskManager, RiskConfig
        from app.prediction_markets.execution import PredictionMarketExecutor
        rm = RiskManager(config=RiskConfig(
            max_category_exposure_usd=40.0, max_single_position_usd=50.0))
        rm._daily_date = self._today()
        executor = PredictionMarketExecutor(dry_run=True)
        opp = _make_scan_result(entry_price=0.50)  # old estimate would be $5
        result = rm.check_opportunity(opp, executor)
        assert not result.approved
        assert "Category" in result.reason

    def test_category_cap_with_headroom_still_approves(self):
        """The conservative estimate is not absurdly strict: one full position fits a
        cap with headroom (no over-blocking of legitimate trades)."""
        from app.prediction_markets.risk_manager import RiskManager, RiskConfig
        from app.prediction_markets.execution import PredictionMarketExecutor
        rm = RiskManager(config=RiskConfig(
            max_category_exposure_usd=60.0, max_single_position_usd=50.0))
        rm._daily_date = self._today()
        executor = PredictionMarketExecutor(dry_run=True)
        opp = _make_scan_result(entry_price=0.50)
        result = rm.check_opportunity(opp, executor)
        assert result.approved

    def test_risk_score_does_not_crash_on_zero_config_limits(self):
        """A risk-config route that sets a limit to 0 must not raise ZeroDivisionError
        into the scan loop — `_calculate_risk_score` guards the divisions."""
        from app.prediction_markets.risk_manager import RiskManager, RiskConfig
        from app.prediction_markets.execution import PredictionMarketExecutor
        rm = RiskManager(config=RiskConfig(
            max_portfolio_exposure_usd=0.0,
            daily_loss_limit_usd=0.0,
            max_total_positions=0,
        ))
        executor = PredictionMarketExecutor(dry_run=True)
        opp = _make_scan_result()
        score = rm._calculate_risk_score(opp, executor)  # must NOT raise
        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0

    def _yesterday(self):
        return (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")

    def test_circuit_breaker_cooldown_survives_utc_day_roll(self):
        """The wall-clock cooldown must NOT be truncated by the midnight daily reset.

        A breach shortly before midnight arms a cooldown that extends into the next UTC
        day. When ``check_opportunity`` runs after midnight, ``_reset_daily_if_needed``
        detects the day change — but it must reset ONLY the daily budget, NOT wipe the
        still-active breaker. Pre-fix (the day-roll cleared the breaker) the bot resumed
        trading immediately after midnight; this test would FAIL there (result.approved is
        True). Post-fix the breaker holds until its configured ``_circuit_breaker_until``.
        """
        from app.prediction_markets.risk_manager import RiskManager, RiskConfig
        from app.prediction_markets.execution import PredictionMarketExecutor
        rm = RiskManager(config=RiskConfig(circuit_breaker_cooldown_min=60))
        executor = PredictionMarketExecutor(dry_run=True)
        # Arm the breaker with a cooldown 30 min in the FUTURE, and stamp the last-seen day
        # as YESTERDAY so the next check triggers the day-roll reset.
        rm._circuit_breaker_active = True
        rm._circuit_breaker_until = datetime.now(timezone.utc) + timedelta(minutes=30)
        rm._daily_pnl = -999.0
        rm._daily_date = self._yesterday()

        result = rm.check_opportunity(_make_scan_result(), executor)

        # The breaker STILL blocks (its wall-clock cooldown has not elapsed)...
        assert not result.approved
        assert "Circuit breaker" in result.reason
        assert rm._circuit_breaker_active is True
        # ...while the daily budget WAS still reset by the day-roll (0.0, not -999.0).
        assert rm._daily_pnl == 0.0
        assert rm._daily_date == datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def test_circuit_breaker_clears_once_wall_clock_cooldown_expires(self):
        """The fix must not strand a breaker: once the wall-clock cooldown has elapsed, the
        next ``check_opportunity`` clears it and trading resumes (with a fresh daily budget).
        """
        from app.prediction_markets.risk_manager import RiskManager, RiskConfig
        from app.prediction_markets.execution import PredictionMarketExecutor
        rm = RiskManager(config=RiskConfig(circuit_breaker_cooldown_min=60))
        executor = PredictionMarketExecutor(dry_run=True)
        # Breaker armed but its cooldown already EXPIRED (until-time in the past).
        rm._circuit_breaker_active = True
        rm._circuit_breaker_until = datetime.now(timezone.utc) - timedelta(minutes=1)
        rm._daily_date = self._today()

        result = rm.check_opportunity(_make_scan_result(), executor)

        assert result.approved
        assert rm._circuit_breaker_active is False


# ============================================================
# Orchestrator Tests
# ============================================================

class TestOrchestrator:
    def test_get_orchestrator_singleton(self):
        from app.prediction_markets.orchestrator import get_orchestrator
        o1 = get_orchestrator()
        o2 = get_orchestrator()
        assert o1 is o2

    def test_scan_without_scanner_returns_error(self):
        from app.prediction_markets.orchestrator import PredictionMarketOrchestrator
        orch = PredictionMarketOrchestrator(scanner=None)
        result = asyncio.get_event_loop().run_until_complete(orch.scan_and_execute())
        assert "error" in result

    def test_status(self):
        from app.prediction_markets.orchestrator import PredictionMarketOrchestrator
        orch = PredictionMarketOrchestrator()
        status = orch.get_status()
        assert "running" in status
        assert "total_scans" in status
        assert "kelly_config" in status
        assert "risk_manager" in status

    def test_multi_leg_opportunity_is_skipped_not_phantom_filled(self):
        # SIDE-EFFECT INTEGRITY (ROADMAP B1): an outcome_idx == -1 basket opportunity
        # (e.g. a same-market dutch-book that must BUY several outcomes) has no single
        # token to trade. It must be recorded as SKIPPED — never executed via the
        # single-order path, which would send an order with an EMPTY token_id that the
        # paper executor still "fills", booking a phantom position that never traversed a
        # real per-leg order path.
        from app.prediction_markets.orchestrator import (
            PredictionMarketOrchestrator, KellyConfig,
        )
        from app.prediction_markets.execution import PredictionMarketExecutor
        from app.prediction_markets.risk_manager import RiskManager, RiskConfig

        market = _make_market(mid="arb1", yes_price=0.45, end_hours=48)
        opp = ScanResult(
            market=market, strategy="SameMarketArbitrage", outcome_idx=-1, side="BUY",
            entry_price=0.45, expected_value=0.57, edge=0.12, confidence=0.9,
            reason="dutch-book basket",
        )

        class _FakeScanner:
            strategies: list = []

            def scan(self, market_limit=200):
                return [opp]

        # Modest per-position cap + permissive risk caps so the opp clears data-quality
        # AND risk and reaches the EXECUTION step — where the multi-leg branch must skip
        # it. (Without permissive risk it would be category-capped upstream and we'd not be
        # exercising the B1 branch at all.)
        ex = PredictionMarketExecutor(
            dry_run=True, max_position_usd=50.0, max_portfolio_usd=10000.0
        )
        permissive_risk = RiskManager(RiskConfig(
            daily_loss_limit_usd=100_000.0,
            max_portfolio_exposure_usd=100_000.0,
            max_single_position_usd=100_000.0,
            max_category_exposure_usd=100_000.0,
            max_strategy_exposure_usd=100_000.0,
            max_total_positions=1000,
        ))
        orch = PredictionMarketOrchestrator(
            scanner=_FakeScanner(), executor=ex, risk_manager=permissive_risk,
            kelly_config=KellyConfig(max_bet_usd=20.0),
        )
        summary = asyncio.get_event_loop().run_until_complete(orch.scan_and_execute())

        # No execution, no phantom fill.
        assert summary["executed"] == 0
        assert orch.total_executions == 0
        # The skip is SPECIFICALLY the multi-leg reason — proves it reached the B1 branch
        # (not a data-quality / risk reject upstream that would also yield 0 executions).
        assert any("multi-leg" in s["reason"] for s in summary["skip_reasons"]), summary["skip_reasons"]
        # And NO empty-token (phantom) position was booked.
        assert "" not in ex.positions
        assert ex.positions == {}


# ============================================================
# Model Tests
# ============================================================

class TestModels:
    def test_portfolio_model_fields(self):
        from app.prediction_markets.models import PredictionPortfolio
        p = PredictionPortfolio(name="test", exchange="all")
        assert p.total_pnl == 0.0
        assert p.win_rate == 0.0

    def test_position_model_computed_fields(self):
        from app.prediction_markets.models import PredictionPosition
        pos = PredictionPosition(
            portfolio_id=1, exchange="polymarket", market_id="m1",
            token_id="t1", size=10.0, avg_entry_price=0.50, current_price=0.60,
        )
        assert pos.cost_basis == 5.0
        assert pos.total_pnl == 0.0  # unrealized + realized = 0 + 0

    def test_snapshot_model_exists(self):
        from app.prediction_markets.models import PredictionPortfolioSnapshot
        snap = PredictionPortfolioSnapshot(
            total_positions=5, total_exposure=100.0, cash_balance=400.0,
            total_value=500.0, unrealized_pnl=10.0, realized_pnl=5.0,
            total_pnl=15.0, total_fees=2.0,
        )
        assert snap.total_value == 500.0

    def test_strategy_performance_model_exists(self):
        from app.prediction_markets.models import PredictionStrategyPerformance
        perf = PredictionStrategyPerformance(strategy="test")
        assert perf.total_trades == 0
        assert perf.win_rate == 0.0

    def test_price_history_model(self):
        from app.prediction_markets.models import PredictionPriceHistory
        ph = PredictionPriceHistory(
            exchange="polymarket", market_id="m1", token_id="t1", price=0.55,
        )
        assert ph.price == 0.55


# ============================================================
# Weather Strategy Tests
# ============================================================

class TestWeatherStrategy:
    def test_finds_mispriced_bucket(self):
        from app.prediction_markets.strategies import (
            WeatherArbitrageStrategy, StrategyConfig, WeatherForecast,
        )
        from app.prediction_markets.polymarket_client import PolymarketClient
        client = PolymarketClient()
        strat = WeatherArbitrageStrategy(client, StrategyConfig(), entry_threshold=0.20)

        forecast = WeatherForecast(
            location="NYC", date=datetime.now(timezone.utc),
            temp_high_f=75, temp_low_f=65, temp_mean_f=70,
            precipitation_pct=10, wind_mph=5, confidence=0.92,
        )
        strat.update_forecasts({"NYC": forecast})

        market = _make_market(
            question="What will NYC temperature be tomorrow?",
            yes_price=0.10, category="Weather",
        )
        market.outcomes[0] = Outcome(
            token_id="nyc_65_75", label="65-75°F", price=0.10, midpoint=0.10, volume=5000,
        )
        results = strat.scan([market])
        assert len(results) >= 1
        assert results[0].strategy == "weather_arb"

    def test_parse_temp_range(self):
        from app.prediction_markets.strategies import WeatherArbitrageStrategy, StrategyConfig
        from app.prediction_markets.polymarket_client import PolymarketClient
        client = PolymarketClient()
        strat = WeatherArbitrageStrategy(client, StrategyConfig())

        assert strat._parse_temp_range("65-75°F") == (65.0, 75.0)
        assert strat._parse_temp_range("Above 80°F") == (80.0, 200.0)
        assert strat._parse_temp_range("Below 32°F") == (-50.0, 32.0)
        assert strat._parse_temp_range("No temp info") is None


# ============================================================
# Quant Models Tests (Avellaneda-Stoikov, VPIN, MC Kelly, Bayes)
# ============================================================

class TestLogitTransform:
    def test_logit_sigmoid_inverse(self):
        from app.prediction_markets.quant_models import logit, sigmoid
        for p in [0.1, 0.25, 0.5, 0.75, 0.9]:
            assert abs(sigmoid(logit(p)) - p) < 1e-6

    def test_logit_midpoint_is_zero(self):
        from app.prediction_markets.quant_models import logit
        assert abs(logit(0.5)) < 1e-6

    def test_logit_monotonic(self):
        from app.prediction_markets.quant_models import logit
        assert logit(0.3) < logit(0.5) < logit(0.7)

    def test_logit_volatility(self):
        from app.prediction_markets.quant_models import logit_volatility
        prices = [0.50 + 0.01 * (i % 5 - 2) for i in range(30)]
        vol = logit_volatility(prices)
        assert vol > 0


class TestAvellanedaStoikov:
    def test_quotes_around_midpoint(self):
        from app.prediction_markets.quant_models import AvellanedaStoikovModel
        model = AvellanedaStoikovModel()
        bid, ask, diag = model.compute_quotes("t1", 0.50, 0.0, 168.0)
        assert bid < 0.50
        assert ask > 0.50
        assert ask > bid

    def test_inventory_shifts_reservation(self):
        from app.prediction_markets.quant_models import AvellanedaStoikovModel
        model = AvellanedaStoikovModel()
        # Long inventory → reservation price drops (wants to sell)
        _, _, diag_long = model.compute_quotes("t1", 0.50, 10.0, 168.0)
        _, _, diag_zero = model.compute_quotes("t1", 0.50, 0.0, 168.0)
        _, _, diag_short = model.compute_quotes("t1", 0.50, -10.0, 168.0)
        assert diag_long["reservation_price"] < diag_zero["reservation_price"]
        assert diag_short["reservation_price"] > diag_zero["reservation_price"]

    def test_extreme_prices_bounded(self):
        from app.prediction_markets.quant_models import AvellanedaStoikovModel
        model = AvellanedaStoikovModel()
        bid, ask, _ = model.compute_quotes("t1", 0.95, 0.0, 24.0)
        assert 0.01 <= bid < ask <= 0.99


class TestVPIN:
    def test_balanced_flow_low_vpin(self):
        from app.prediction_markets.quant_models import VPINTracker, VPINConfig
        vpin = VPINTracker(VPINConfig(bucket_size=10, n_buckets=5))
        # Alternating buy/sell flow (balanced)
        for i in range(100):
            price = 0.50 + (0.01 if i % 2 == 0 else -0.01)
            vpin.record_trade("t1", price, 5.0)
        val = vpin.get_vpin("t1")
        assert val is not None
        assert val < 0.30  # Balanced → low VPIN

    def test_onesided_flow_high_vpin(self):
        from app.prediction_markets.quant_models import VPINTracker, VPINConfig
        vpin = VPINTracker(VPINConfig(bucket_size=10, n_buckets=5))
        # All buys (monotonically increasing price)
        for i in range(100):
            vpin.record_trade("t1", 0.50 + i * 0.001, 5.0)
        val = vpin.get_vpin("t1")
        assert val is not None
        assert val > 0.70  # One-sided → high VPIN

    def test_toxicity_detection(self):
        from app.prediction_markets.quant_models import VPINTracker, VPINConfig
        vpin = VPINTracker(VPINConfig(bucket_size=10, n_buckets=5, alert_threshold=0.60))
        for i in range(100):
            vpin.record_trade("t1", 0.50 + i * 0.001, 5.0)
        toxic, val = vpin.is_toxic("t1")
        assert toxic


class TestMonteCarloKelly:
    def test_reduces_bet_with_uncertain_edge(self):
        from app.prediction_markets.quant_models import MonteCarloKelly, MonteCarloKellyConfig
        mc = MonteCarloKelly(MonteCarloKellyConfig(
            n_simulations=500, n_trades_per_path=50, min_historical_trades=5,
        ))
        # Record noisy returns (high variance)
        import random
        random.seed(42)
        for _ in range(20):
            mc.record_return("noisy", random.gauss(0.05, 0.30))

        naive_fraction = 0.10  # 10% Kelly
        bet, diag = mc.compute_size("noisy", naive_fraction, 1000.0)
        assert diag["method"] == "monte_carlo_kelly"
        # MC should reduce bet due to high variance
        assert bet < naive_fraction * 1000.0

    def test_fallback_with_no_data(self):
        from app.prediction_markets.quant_models import MonteCarloKelly
        mc = MonteCarloKelly()
        bet, diag = mc.compute_size("unknown", 0.10, 1000.0)
        assert diag["method"] == "naive_kelly_with_haircut"
        assert bet > 0


class TestBayesianUpdater:
    def test_prior_from_market_price(self):
        from app.prediction_markets.quant_models import BayesianUpdater
        bu = BayesianUpdater()
        bu.set_prior("test", market_price=0.60, confidence=20)
        est = bu.get_estimate("test")
        assert abs(est.mean - 0.60) < 0.05

    def test_update_shifts_posterior(self):
        from app.prediction_markets.quant_models import BayesianUpdater
        bu = BayesianUpdater()
        bu.set_prior("test", market_price=0.50, confidence=10)
        # Observe 5 positive signals
        for _ in range(5):
            bu.update_with_outcome("test", True)
        est = bu.get_estimate("test")
        assert est.mean > 0.55  # Should shift upward

    def test_signal_update(self):
        from app.prediction_markets.quant_models import BayesianUpdater
        bu = BayesianUpdater()
        bu.set_prior("test", market_price=0.50, confidence=10)
        bu.update_with_signal("test", signal_mean=0.80, signal_weight=10)
        est = bu.get_estimate("test")
        assert est.mean > 0.60  # Shifted toward 0.80

    def test_edge_vs_market(self):
        from app.prediction_markets.quant_models import BayesianUpdater
        bu = BayesianUpdater()
        bu.set_prior("test", market_price=0.40, confidence=5)
        bu.update_with_signal("test", signal_mean=0.70, signal_weight=10)
        edge = bu.get_edge_vs_market("test", market_price=0.40)
        assert edge > 0.10  # Model says higher than market

    def test_confidence_interval(self):
        from app.prediction_markets.quant_models import BayesianUpdater
        bu = BayesianUpdater()
        bu.set_prior("test", market_price=0.50, confidence=100)
        est = bu.get_estimate("test")
        lo, hi = est.confidence_interval_95
        assert lo < 0.50 < hi
        assert hi - lo < 0.20  # High confidence → narrow CI


class TestKillSwitch:
    def test_blocks_orders_when_active(self):
        from app.prediction_markets.execution import (
            PredictionMarketExecutor, OrderRequest, OrderSide, OrderType,
            OrderStatus, Exchange,
        )
        executor = PredictionMarketExecutor(dry_run=True)
        executor.activate_kill_switch("test_emergency")
        req = OrderRequest(
            exchange=Exchange.POLYMARKET, market_id="m1", token_id="t1",
            side=OrderSide.BUY, order_type=OrderType.LIMIT, size=5.0, price=0.50,
        )
        result = executor.execute(req)
        assert result.status == OrderStatus.REJECTED
        assert "KILL SWITCH" in result.error

    def test_allows_orders_after_deactivation(self):
        from app.prediction_markets.execution import (
            PredictionMarketExecutor, OrderRequest, OrderSide, OrderType,
            OrderStatus, Exchange,
        )
        executor = PredictionMarketExecutor(dry_run=True)
        executor.activate_kill_switch("test")
        executor.deactivate_kill_switch()
        req = OrderRequest(
            exchange=Exchange.POLYMARKET, market_id="m1", token_id="t1",
            side=OrderSide.BUY, order_type=OrderType.LIMIT, size=5.0, price=0.50,
        )
        result = executor.execute(req)
        assert result.status == OrderStatus.FILLED


class TestRiskManagerRecordExecution:
    """Verify record_execution handles missing/empty raw_response."""

    def test_record_execution_no_strategy_in_raw_response(self):
        from app.prediction_markets.risk_manager import RiskManager
        from app.prediction_markets.execution import (
            OrderResult, Exchange, OrderSide, OrderType, OrderStatus,
        )
        rm = RiskManager()
        result = OrderResult(
            order_id="dry-001", exchange=Exchange.POLYMARKET,
            market_id="m1", token_id="t1", side=OrderSide.BUY,
            order_type=OrderType.LIMIT, size=5.0, price=0.50,
            status=OrderStatus.FILLED, filled_size=5.0, filled_price=0.50,
            fees=0.01, raw_response={},
        )
        # Should not raise even with empty raw_response
        rm.record_execution(result)
        assert rm._daily_pnl == -0.01

    def test_record_execution_does_not_track_strategy_trades(self):
        # record_execution does NOT count per-strategy trades: the venue OrderResult has no
        # `strategy` field (only OrderRequest/Position do), so the old
        # `raw_response.get("strategy")` increment was structurally dead. The per-strategy
        # trade counter is advanced in record_pnl (position close), which receives the real
        # strategy name — see test_strategy_drawdown_disable.py.
        from app.prediction_markets.risk_manager import RiskManager
        from app.prediction_markets.execution import (
            OrderResult, Exchange, OrderSide, OrderType, OrderStatus,
        )
        rm = RiskManager()
        result = OrderResult(
            order_id="dry-002", exchange=Exchange.POLYMARKET,
            market_id="m1", token_id="t1", side=OrderSide.BUY,
            order_type=OrderType.LIMIT, size=5.0, price=0.50,
            status=OrderStatus.FILLED, filled_size=5.0, filled_price=0.50,
            fees=0.02, raw_response={"strategy": "near_certainty"},
        )
        rm.record_execution(result)
        # No strategy is counted from the venue response (would break the drawdown gate).
        assert rm._strategy_trades["near_certainty"] == 0
        # record_pnl is the real per-strategy trade counter:
        rm.record_pnl("near_certainty", -1.0)
        assert rm._strategy_trades["near_certainty"] == 1

    def test_record_execution_rejected_no_tracking(self):
        from app.prediction_markets.risk_manager import RiskManager
        from app.prediction_markets.execution import (
            OrderResult, Exchange, OrderSide, OrderType, OrderStatus,
        )
        rm = RiskManager()
        result = OrderResult(
            order_id="dry-003", exchange=Exchange.POLYMARKET,
            market_id="m1", token_id="t1", side=OrderSide.BUY,
            order_type=OrderType.LIMIT, size=5.0, price=0.50,
            status=OrderStatus.REJECTED, error="test rejection",
        )
        rm.record_execution(result)
        # Rejected orders shouldn't affect P&L or strategy counts
        assert rm._daily_pnl == 0.0
        assert sum(rm._strategy_trades.values()) == 0


