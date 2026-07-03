"""
Tests for the learning-loop WIRING (this run):

* ROADMAP E6 — per-strategy attribution serialized via metrics_aggregator +
  orchestrator.get_resolved_trades_by_strategy (untagged → "unattributed").
* ROADMAP B3 — strategy_registry_store durable round-trip + orchestrator
  record_strategy_transition enforcing the engine's integrity gate via the
  same code path the API uses.
* ROADMAP D2 (resolution risk fix) — a losing market RESOLUTION now feeds
  risk_manager.record_pnl so a decayed strategy's drawdown auto-disable can
  actually fire on the dominant binary-market loss path (previously bypassed).

Deterministic; no network. Uses in-memory SQLite for persistence.
"""

import pytest
from datetime import datetime, timezone

from app.prediction_markets.per_strategy_metrics import StrategyTradePnL
from app.prediction_markets.metrics_aggregator import (
    compute_per_strategy_metrics,
)
from app.prediction_markets.strategy_registry import (
    StrategyRegistry,
    LifecycleState,
    Evidence,
    IllegalTransition,
    MissingEvidence,
)


def _ts(day):
    return datetime(2024, 1, day, 12, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# E6 — per-strategy attribution serializer
# ---------------------------------------------------------------------------

def test_per_strategy_metrics_groups_and_ranks():
    trades = [
        StrategyTradePnL("alpha", _ts(1), 100.0, True),
        StrategyTradePnL("alpha", _ts(2), -40.0, False),
        StrategyTradePnL("beta", _ts(1), 10.0, True),
    ]
    out = compute_per_strategy_metrics(trades)
    assert out["num_input_trades"] == 3
    names = [s["strategy"] for s in out["strategies"]]
    assert names == ["alpha", "beta"]  # sorted by name
    alpha = next(s for s in out["strategies"] if s["strategy"] == "alpha")
    assert alpha["num_trades"] == 2
    assert alpha["num_wins"] == 1
    assert alpha["total_pnl_usd"] == pytest.approx(60.0)
    assert alpha["hit_rate"] == pytest.approx(0.5)
    # Ranking by total realized PnL desc: alpha (60) before beta (10).
    assert out["ranking"] == ["alpha", "beta"]


def test_per_strategy_metrics_no_fabricated_rows_and_empty():
    # Zero-trade strategies never appear; empty input → honest empty shape.
    assert compute_per_strategy_metrics([]) == {
        "source": "resolved_trades_by_strategy",
        "num_input_trades": 0,
        "strategies": [],
        "ranking": [],
    }


def test_per_strategy_metrics_total_reconciles_to_weekly():
    trades = [
        StrategyTradePnL("alpha", _ts(1), 30.0, True),
        StrategyTradePnL("alpha", _ts(9), -5.0, False),  # different ISO week
    ]
    out = compute_per_strategy_metrics(trades)
    alpha = out["strategies"][0]
    assert alpha["total_pnl_usd"] == pytest.approx(sum(alpha["weekly_pnl"].values()))


def test_per_strategy_metrics_deterministic():
    trades = [
        StrategyTradePnL("b", _ts(1), 5.0, True),
        StrategyTradePnL("a", _ts(1), -1.0, False),
    ]
    assert compute_per_strategy_metrics(trades) == compute_per_strategy_metrics(trades)


# ---------------------------------------------------------------------------
# B3 — durable registry store round-trip
# ---------------------------------------------------------------------------

def _mem_store():
    from sqlmodel import create_engine
    from app.prediction_markets.strategy_registry_store import (
        StrategyRegistryStore,
        init_db,
    )
    engine = create_engine("sqlite://")
    init_db(engine)
    return StrategyRegistryStore(engine=engine)


def test_registry_store_load_none_when_empty():
    store = _mem_store()
    assert store.load() is None  # nothing persisted yet


def test_registry_store_roundtrip_is_byte_stable():
    store = _mem_store()
    reg = StrategyRegistry()
    reg.propose("no_scanner", at=_ts(1), reason="seed")
    reg.transition("no_scanner", LifecycleState.BACKTESTING, at=_ts(2),
                   evidence=Evidence())
    assert store.save(reg) is True

    loaded = store.load()
    assert loaded is not None
    assert loaded.to_dict() == reg.to_dict()
    assert loaded.state_of("no_scanner") == LifecycleState.BACKTESTING


def test_registry_store_save_overwrites_singleton():
    store = _mem_store()
    reg1 = StrategyRegistry()
    reg1.propose("one", at=_ts(1))
    store.save(reg1)
    reg2 = StrategyRegistry()
    reg2.propose("two", at=_ts(1))
    store.save(reg2)
    loaded = store.load()
    assert loaded.names() == ["two"]  # singleton overwritten, not appended


# ---------------------------------------------------------------------------
# B3 — orchestrator transition path enforces the integrity gate
# ---------------------------------------------------------------------------

def _orchestrator():
    # scanner=None → no deployed strategies seeded; executor dry-run paper.
    from app.prediction_markets.orchestrator import PredictionMarketOrchestrator
    from app.prediction_markets.execution import get_executor
    return PredictionMarketOrchestrator(
        scanner=None, executor=get_executor(dry_run=True)
    )


def test_orchestrator_propose_then_legal_transition():
    orch = _orchestrator()
    orch.propose_strategy("exp_alpha", reason="hypothesis", at=_ts(1))
    rec = orch.record_strategy_transition(
        "exp_alpha", LifecycleState.BACKTESTING, reason="start", at=_ts(2),
        evidence=Evidence(),
    )
    assert rec.state == LifecycleState.BACKTESTING
    snap = orch.get_strategy_registry()
    assert any(a["name"] == "exp_alpha" for a in snap["alphas"])


def test_orchestrator_promotion_requires_full_evidence():
    orch = _orchestrator()
    orch.propose_strategy("exp_alpha", at=_ts(1))
    orch.record_strategy_transition("exp_alpha", LifecycleState.BACKTESTING, at=_ts(2),
                                    evidence=Evidence(backtest_passed=True))
    orch.record_strategy_transition("exp_alpha", LifecycleState.PAPER, at=_ts(3),
                                    evidence=Evidence(backtest_passed=True))
    # Promotion WITHOUT oos+calibration evidence must be refused (integrity gate).
    with pytest.raises(MissingEvidence):
        orch.record_strategy_transition(
            "exp_alpha", LifecycleState.PROMOTED, at=_ts(4),
            evidence=Evidence(backtest_passed=True),
        )
    # With full evidence it is allowed.
    rec = orch.record_strategy_transition(
        "exp_alpha", LifecycleState.PROMOTED, at=_ts(5),
        evidence=Evidence(backtest_passed=True, oos_validated=True,
                          calibration_passed=True),
    )
    assert rec.state == LifecycleState.PROMOTED


def test_orchestrator_illegal_jump_rejected():
    orch = _orchestrator()
    orch.propose_strategy("exp_alpha", at=_ts(1))
    # PROPOSED → PROMOTED is structurally impossible.
    with pytest.raises(IllegalTransition):
        orch.record_strategy_transition(
            "exp_alpha", LifecycleState.PROMOTED, at=_ts(2),
            evidence=Evidence(backtest_passed=True, oos_validated=True,
                              calibration_passed=True),
        )


def test_orchestrator_seeds_deployed_strategies_as_proposed():
    # A scanner with named strategies → each seeded PROPOSED (honest: no evidence yet).
    from app.prediction_markets.orchestrator import PredictionMarketOrchestrator
    from app.prediction_markets.execution import get_executor

    class _S:
        def __init__(self, n):
            self._n = n
        @property
        def name(self):
            return self._n

    class _Scanner:
        strategies = [_S("alpha_x"), _S("beta_y")]

    orch = PredictionMarketOrchestrator(
        scanner=_Scanner(), executor=get_executor(dry_run=True)
    )
    snap = orch.get_strategy_registry()
    states = {a["name"]: a["state"] for a in snap["alphas"]}
    assert states.get("alpha_x") == "proposed"
    assert states.get("beta_y") == "proposed"


# ---------------------------------------------------------------------------
# D2 resolution risk fix — resolution loss feeds the strategy drawdown circuit
# ---------------------------------------------------------------------------

def test_resolution_loss_feeds_strategy_drawdown_disable():
    """A losing market RESOLUTION must feed risk_manager.record_pnl so the
    per-strategy drawdown auto-disable can fire on the dominant binary loss path.
    Previously check_resolutions fed ONLY the executor loss caps, never the risk
    manager — a strategy could decay via resolutions and keep trading.
    """
    from app.prediction_markets.orchestrator import MarkToMarketEngine
    from app.prediction_markets import polymarket_client as pmc
    from app.prediction_markets.execution import (
        PredictionMarketExecutor, OrderRequest, OrderSide, OrderType, Exchange,
    )
    from app.prediction_markets.risk_manager import RiskManager, RiskConfig

    ex = PredictionMarketExecutor(
        dry_run=True, max_position_usd=60.0, max_portfolio_usd=500.0,
        max_daily_loss_usd=10_000.0, max_total_loss_usd=10_000.0,  # caps wide so
    )                                                              # kill switch stays off
    ex.execute(OrderRequest(
        exchange=Exchange.POLYMARKET, market_id="m1", token_id="t1",
        side=OrderSide.BUY, order_type=OrderType.LIMIT, size=100, price=0.50,
        strategy="decayed", market_question="Q?", outcome_label="Yes",
    ))
    token_id = next(iter(ex.positions))

    rm = RiskManager(config=RiskConfig(
        strategy_disable_drawdown=0.20, strategy_disable_min_trades=1,
    ))
    # Establish a prior peak for the strategy, and enough trades to clear min_trades.
    rm.record_pnl("decayed", 100.0)
    rm._strategy_trades["decayed"] = 5
    assert "decayed" not in rm._disabled_strategies

    lost = pmc.Market(
        id="m", condition_id="c", question="Q?", slug="q", description="",
        category="", end_date=None,
        outcomes=[pmc.Outcome(token_id=token_id, label="Yes", price=0.0,
                              midpoint=0.0, volume=0.0)],
        total_volume=0.0, liquidity=0.0, active=False, closed=True, resolved=True,
    )

    class _FakeClient:
        def __init__(self, *a, **k):
            pass
        def get_market_by_id(self, _market_id):
            return lost

    orig = pmc.PolymarketClient
    pmc.PolymarketClient = _FakeClient
    try:
        engine = MarkToMarketEngine(ex, risk_manager=rm)
        engine.check_resolutions()
    finally:
        pmc.PolymarketClient = orig

    # current_value: 100 (peak) + (-50 resolution) = 50 → 50% drawdown ≥ 20% → disabled.
    assert "decayed" in rm._disabled_strategies
    assert token_id not in ex.positions


def test_resolution_without_risk_manager_still_works():
    """The risk_manager wiring is optional/None-safe — resolution accounting must
    still work (and feed the executor caps) when no risk_manager is attached."""
    from app.prediction_markets.orchestrator import MarkToMarketEngine
    from app.prediction_markets import polymarket_client as pmc
    from app.prediction_markets.execution import (
        PredictionMarketExecutor, OrderRequest, OrderSide, OrderType, Exchange,
    )

    ex = PredictionMarketExecutor(
        dry_run=True, max_position_usd=60.0, max_portfolio_usd=500.0,
        max_daily_loss_usd=10_000.0, max_total_loss_usd=10_000.0,
    )
    ex.execute(OrderRequest(
        exchange=Exchange.POLYMARKET, market_id="m1", token_id="t1",
        side=OrderSide.BUY, order_type=OrderType.LIMIT, size=100, price=0.50,
        strategy="s", market_question="Q?", outcome_label="Yes",
    ))
    token_id = next(iter(ex.positions))
    win = pmc.Market(
        id="m", condition_id="c", question="Q?", slug="q", description="",
        category="", end_date=None,
        outcomes=[pmc.Outcome(token_id=token_id, label="Yes", price=1.0,
                              midpoint=1.0, volume=0.0)],
        total_volume=0.0, liquidity=0.0, active=False, closed=True, resolved=True,
    )

    class _FakeClient:
        def __init__(self, *a, **k):
            pass
        def get_market_by_id(self, _market_id):
            return win

    orig = pmc.PolymarketClient
    pmc.PolymarketClient = _FakeClient
    try:
        engine = MarkToMarketEngine(ex)  # no risk_manager
        engine.check_resolutions()
    finally:
        pmc.PolymarketClient = orig
    assert token_id not in ex.positions  # resolved + closed, no crash


# ---------------------------------------------------------------------------
# E5 — evaluation-window metrics serializer (wired via metrics_aggregator)
# ---------------------------------------------------------------------------

def test_evaluation_windows_buckets_by_iso_week_and_honest_empty():
    from app.prediction_markets.metrics_aggregator import (
        compute_evaluation_windows,
    )
    from app.prediction_markets.evaluation_window import ResolvedTrade

    # Two trades in the same ISO week, one in a later week.
    trades = [
        ResolvedTrade("alpha", _ts(1), 100.0, True),   # 2024-01-01 (Mon)
        ResolvedTrade("alpha", _ts(3), -40.0, False),  # same week
        ResolvedTrade("beta", _ts(9), 10.0, True),     # following week
    ]
    out = compute_evaluation_windows(trades)
    assert out["num_input_trades"] == 3
    assert out["num_windows"] == 2
    w0 = out["windows"][0]
    assert w0["metrics"]["num_trades"] == 2
    assert w0["metrics"]["realized_pnl_usd"] == pytest.approx(60.0)
    # Brier omitted honestly (no per-trade calibration signal supplied).
    assert w0["metrics"]["brier_score"] is None

    # Empty input → honest empty shape, no fabricated window.
    empty = compute_evaluation_windows([])
    assert empty["num_windows"] == 0 and empty["windows"] == []


# ---------------------------------------------------------------------------
# E2 — calibration-drift signal serializer (wired via metrics_aggregator)
# ---------------------------------------------------------------------------

def _pred(prob, outcome):
    from app.prediction_markets.calibration import ResolvedPrediction
    return ResolvedPrediction(
        market_id="m", predicted_prob=prob, market_price=0.5, outcome=outcome
    )


def test_calibration_drift_insufficient_data_no_false_alarm():
    from app.prediction_markets.metrics_aggregator import (
        compute_calibration_drift,
    )
    # Far fewer than min_baseline + recent_window → honest insufficient_data.
    out = compute_calibration_drift([_pred(0.6, 1) for _ in range(5)])
    assert out["status"] == "insufficient_data"
    assert out["drift_detected"] is False
    # The degenerate current reality (no non-degenerate predictions) lands here too.
    assert compute_calibration_drift([])["status"] == "insufficient_data"


def test_calibration_drift_flags_real_degradation():
    from app.prediction_markets.metrics_aggregator import (
        compute_calibration_drift,
    )
    # Baseline: well-calibrated (prob 0.9 → outcome 1 ~90% of the time, low Brier).
    # Recent: badly miscalibrated (prob 0.9 → outcome 0 every time, high Brier).
    baseline = []
    for i in range(60):
        baseline.append(_pred(0.9, 1 if i % 10 != 0 else 0))  # ~90% YES, sharp
    recent = [_pred(0.9, 0) for _ in range(30)]               # confidently WRONG
    out = compute_calibration_drift(baseline + recent, recent_window=30, min_baseline=30)
    assert out["status"] == "evaluated"
    assert out["drift_detected"] is True
    assert out["recent_n"] == 30
    # de-rating must cut Kelly size under detected drift (<= 1.0, strictly < here).
    assert out["de_rating"] < 1.0


def test_calibration_drift_stable_calibration_no_drift():
    from app.prediction_markets.metrics_aggregator import (
        compute_calibration_drift,
    )
    # Baseline and recent both well-calibrated and identical in distribution → no drift.
    preds = []
    for i in range(90):
        preds.append(_pred(0.7, 1 if i % 10 < 7 else 0))  # 70% YES throughout
    out = compute_calibration_drift(preds, recent_window=30, min_baseline=30)
    assert out["status"] == "evaluated"
    assert out["drift_detected"] is False


def test_calibration_drift_is_deterministic():
    from app.prediction_markets.metrics_aggregator import (
        compute_calibration_drift,
    )
    preds = [_pred(0.8, 1 if i % 5 != 0 else 0) for i in range(90)]
    a = compute_calibration_drift(preds)
    b = compute_calibration_drift(preds)
    assert a == b


def test_resolution_absent_token_not_fabricated_as_loss():
    """SIDE-EFFECT INTEGRITY (ROADMAP F4.1): a resolved market whose outcomes do
    NOT contain the held token_id must NOT be settled as a phantom 0.0 total loss.
    Inventing that settlement would realize a loss the position never took, could
    AUTO-TRIP the kill switch on the invented loss (D3/D4 read the same realized-PnL
    counters), and would cache the position resolved so it never reconciles. The fix:
    skip + leave UNCACHED so the next cycle retries once the venue data is consistent.
    """
    from app.prediction_markets.orchestrator import MarkToMarketEngine
    from app.prediction_markets import polymarket_client as pmc
    from app.prediction_markets.execution import (
        PredictionMarketExecutor, OrderRequest, OrderSide, OrderType, Exchange,
    )

    # Tight loss caps so ANY fabricated loss would trip the kill switch loudly.
    ex = PredictionMarketExecutor(
        dry_run=True, max_position_usd=60.0, max_portfolio_usd=500.0,
        max_daily_loss_usd=5.0, max_total_loss_usd=5.0,
    )
    ex.execute(OrderRequest(
        exchange=Exchange.POLYMARKET, market_id="m1", token_id="t1",
        side=OrderSide.BUY, order_type=OrderType.LIMIT, size=100, price=0.50,
        strategy="s", market_question="Q?", outcome_label="Yes",
    ))
    token_id = next(iter(ex.positions))

    # A resolved market whose ONLY outcome is a DIFFERENT token than the one held
    # (the data-inconsistency case: re-resolved/stale market or malformed outcomes).
    mismatched = pmc.Market(
        id="m", condition_id="c", question="Q?", slug="q", description="",
        category="", end_date=None,
        outcomes=[pmc.Outcome(token_id="OTHER", label="Yes", price=1.0,
                              midpoint=1.0, volume=0.0)],
        total_volume=0.0, liquidity=0.0, active=False, closed=True, resolved=True,
    )

    class _FakeClientMismatch:
        def __init__(self, *a, **k):
            pass
        def get_market_by_id(self, _market_id):
            return mismatched

    orig = pmc.PolymarketClient
    pmc.PolymarketClient = _FakeClientMismatch
    try:
        engine = MarkToMarketEngine(ex)
        engine.check_resolutions()
        # No fabricated settlement: position still open, NO realized loss fed,
        # kill switch NOT tripped, and NOT cached resolved (so it retries).
        assert token_id in ex.positions, "position must NOT be deleted on absent token"
        assert ex._realized_pnl_total == 0.0, "no phantom loss may be realized"
        assert ex.kill_switch_active is False, "kill switch must not trip on invented loss"
        assert token_id not in engine._resolution_cache, "must stay uncached to retry"

        # RETRY: once the venue returns consistent outcomes (held token present and
        # lost → price 0.0), the SAME engine settles it on the next cycle — a real loss.
        consistent = pmc.Market(
            id="m", condition_id="c", question="Q?", slug="q", description="",
            category="", end_date=None,
            outcomes=[pmc.Outcome(token_id=token_id, label="Yes", price=0.0,
                                  midpoint=0.0, volume=0.0)],
            total_volume=0.0, liquidity=0.0, active=False, closed=True, resolved=True,
        )

        class _FakeClientConsistent:
            def __init__(self, *a, **k):
                pass
            def get_market_by_id(self, _market_id):
                return consistent

        pmc.PolymarketClient = _FakeClientConsistent
        engine.check_resolutions()
        assert token_id not in ex.positions, "consistent data must now settle the loss"
        assert ex._realized_pnl_total < 0.0, "the REAL resolution loss is realized on retry"
    finally:
        pmc.PolymarketClient = orig


def test_resolution_looks_up_market_by_id_not_slug():
    """BUILDS≠WORKS regression: positions store the Gamma numeric ``id``
    (``market_id=opp.market.id``), NOT the URL slug — DISTINCT fields. The old
    ``check_resolutions`` called ``get_market_by_slug(pos.market_id)``, querying Gamma's
    ``slug`` filter with a numeric id, which matches NOTHING in production — so positions
    NEVER settled and the dominant binary-market loss path (feeding the loss caps + kill
    switch) was silently dead. The prior tests missed it because their fakes ignore the
    argument. This fake reproduces prod: ``get_market_by_slug`` returns None (a numeric id
    never matches a slug), while ``get_market_by_id`` returns the resolved market. It FAILS
    on the pre-fix code (no settlement -> no realized loss) and passes once resolution looks
    the market up by id.
    """
    from app.prediction_markets.orchestrator import MarkToMarketEngine
    from app.prediction_markets import polymarket_client as pmc
    from app.prediction_markets.execution import (
        PredictionMarketExecutor, OrderRequest, OrderSide, OrderType, Exchange,
    )

    ex = PredictionMarketExecutor(
        dry_run=True, max_position_usd=60.0, max_portfolio_usd=500.0,
        max_daily_loss_usd=10_000.0, max_total_loss_usd=10_000.0,
    )
    ex.execute(OrderRequest(
        exchange=Exchange.POLYMARKET, market_id="253591", token_id="t1",
        side=OrderSide.BUY, order_type=OrderType.LIMIT, size=100, price=0.50,
        strategy="s", market_question="Q?", outcome_label="Yes",
    ))
    token_id = next(iter(ex.positions))
    assert ex.positions[token_id].market_id == "253591"  # a numeric Gamma id, not a slug

    lost = pmc.Market(
        id="253591", condition_id="c", question="Q?", slug="will-x-happen",
        description="", category="", end_date=None,
        outcomes=[pmc.Outcome(token_id=token_id, label="Yes", price=0.0,
                              midpoint=0.0, volume=0.0)],
        total_volume=0.0, liquidity=0.0, active=False, closed=True, resolved=True,
    )

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        def get_market_by_slug(self, slug):
            # Prod reality: querying the slug filter with a numeric id matches nothing.
            return None

        def get_market_by_id(self, market_id):
            assert market_id == "253591"
            return lost

    orig = pmc.PolymarketClient
    pmc.PolymarketClient = _FakeClient
    try:
        engine = MarkToMarketEngine(ex)
        engine.check_resolutions()
    finally:
        pmc.PolymarketClient = orig

    # Settlement actually fired: the losing position is closed and the loss realized.
    # Gross -$50 ((0-0.50)*100), NET of the entry fee the loss caps now subtract (2% of
    # the $50 cost basis = $1.00) = -$51.00.
    assert token_id not in ex.positions, "position must settle when looked up by id"
    assert ex._realized_pnl_total == pytest.approx(-51.0), \
        "the real resolution loss must be booked (dead on the pre-fix slug lookup)"
