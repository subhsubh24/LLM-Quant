"""
Scan-to-Execute Orchestrator for Prediction Markets.

Closes the loop: Scanner → Kelly Sizing → Execution → Persistence → Mark-to-Market.

This is the "brain" that ties everything together:
1. Runs scanner on a configurable interval
2. Filters opportunities through risk controls
3. Sizes positions using Kelly criterion
4. Executes orders (dry-run by default)
5. Persists everything to DB
6. Updates positions with live prices from WebSocket feeds
7. Detects resolved markets and realizes P&L

Usage:
    orchestrator = PredictionMarketOrchestrator()
    await orchestrator.start()  # Runs in background
    ...
    await orchestrator.stop()
"""

import asyncio
import json
import logging
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from .polymarket_client import Market, PolymarketClient, ScanResult
from .data_quality import DataQualityValidator
from .execution import (
    Exchange,
    OrderRequest,
    OrderResult,
    OrderSide,
    OrderStatus,
    OrderType,
    PredictionMarketExecutor,
    Position,
    get_executor,
)
from .strategies import PredictionMarketScanner, StrategyConfig
from .risk_manager import RiskManager, RiskCheckResult
from .cost_model import DEFAULT_COST_MODEL
# NOTE: AuditLogger is imported lazily inside __init__ (see there) so the audit
# table's table=True registration is deferred to orchestrator construction,
# avoiding an eager dual-import-path collision in mixed test sessions.

try:
    from .simulation_integration import EnhancedContractPricer, LiveProbabilityTracker
except ImportError:
    EnhancedContractPricer = None
    LiveProbabilityTracker = None

logger = logging.getLogger(__name__)


# ============================================================
# Kelly Criterion Position Sizing
# ============================================================

@dataclass
class KellyConfig:
    """Configuration for Kelly criterion sizing."""
    fractional_kelly: float = 0.25   # Use quarter-Kelly (conservative)
    use_monte_carlo: bool = True     # Use Monte Carlo Kelly when historical data available
    min_bet_usd: float = 1.0        # Don't place orders smaller than this
    max_bet_usd: float = 50.0       # Hard cap per position
    min_edge: float = 0.01          # Don't trade edges below 1%
    min_confidence: float = 0.50    # Don't trade low-confidence signals
    max_kelly_fraction: float = 0.20  # Never bet more than 20% of bankroll


def kelly_size(
    edge: float,
    confidence: float,
    win_probability: float,
    bankroll: float,
    config: KellyConfig,
) -> float:
    """
    Calculate optimal bet size using Kelly criterion.

    Kelly formula: f* = (p * b - q) / b
    where:
        p = probability of winning
        q = 1 - p = probability of losing
        b = odds ratio (net payout per dollar risked)

    For prediction markets:
        - You buy at price P, receive $1 if correct
        - b = (1 - P) / P (net payout per dollar risked)
        - p = your estimated true probability (from strategy confidence)
        - Edge = p - P (your advantage over the market)

    We use fractional Kelly (e.g., quarter-Kelly) to reduce variance.

    Args:
        edge: Expected edge (strategy output, e.g., 0.15 = 15%)
        confidence: Strategy confidence in the signal (0-1)
        win_probability: Estimated true probability of the outcome
        bankroll: Available capital for betting
        config: Kelly sizing configuration

    Returns:
        Optimal bet size in USD (0 if no bet should be placed)
    """
    # Pre-filters
    if edge < config.min_edge:
        return 0.0
    if confidence < config.min_confidence:
        return 0.0
    if bankroll <= 0:
        return 0.0

    # Estimated market price (what we'd pay)
    market_price = win_probability - edge
    if market_price <= 0 or market_price >= 1:
        return 0.0

    # Odds ratio: how much we win per dollar risked
    b = (1.0 - market_price) / market_price

    # True probability (our estimate)
    p = win_probability
    q = 1.0 - p

    # Full Kelly fraction
    kelly_f = (p * b - q) / b if b > 0 else 0.0

    # Clamp to [0, max_kelly_fraction]
    kelly_f = max(0.0, min(kelly_f, config.max_kelly_fraction))

    # Apply fractional Kelly
    kelly_f *= config.fractional_kelly

    # Convert to USD
    bet_usd = kelly_f * bankroll

    # Apply min/max constraints
    if bet_usd < config.min_bet_usd:
        return 0.0
    bet_usd = min(bet_usd, config.max_bet_usd)

    return round(bet_usd, 2)


def size_from_scan_result(
    result: ScanResult,
    bankroll: float,
    config: KellyConfig,
    mc_kelly: Optional["MonteCarloKelly"] = None,
) -> Tuple[float, float]:
    """
    Calculate bet size from a scan result.

    Uses Monte Carlo Kelly when historical trade data is available,
    otherwise falls back to deterministic fractional Kelly.

    Returns:
        (bet_size_usd, num_contracts)
    """
    # Estimate win probability from entry price and edge
    market_price = result.entry_price
    win_probability = market_price + result.edge

    # COST-AWARE EDGE (ROADMAP C2): size on the edge NET of the slippage + fee the
    # executor will actually charge — NOT the gross edge. Sizing on gross edge both
    # over-bets (full-Kelly on inflated odds) and takes trades whose gross edge is
    # positive but whose net edge is <= 0 after costs. cost_model is the single source
    # of truth for those rates (kept consistent with execution.py's paper fills).
    net_edge = DEFAULT_COST_MODEL.net_edge(win_probability, market_price)

    # Deterministic Kelly first (always computed), on the cost-adjusted edge.
    naive_bet_usd = kelly_size(
        edge=net_edge,
        confidence=result.confidence,
        win_probability=win_probability,
        bankroll=bankroll,
        config=config,
    )

    if naive_bet_usd <= 0:
        return 0.0, 0.0

    # Simulation-enhanced pricing (stacked variance reduction)
    if EnhancedContractPricer is not None and config.use_monte_carlo:
        try:
            pricer = EnhancedContractPricer()
            sim_result = pricer.price_contract(
                current_prob=market_price,
                vol=0.3,  # Default prediction market vol
                T=30 / 365,  # Default 30-day horizon
                n_paths=10_000,
            )
            sim_prob = sim_result["probability"]
            # If simulation disagrees with market by > 2%, use sim estimate
            if abs(sim_prob - market_price) > 0.02:
                win_probability = sim_prob
                naive_bet_usd = kelly_size(
                    edge=DEFAULT_COST_MODEL.net_edge(win_probability, market_price),
                    confidence=result.confidence,
                    win_probability=win_probability,
                    bankroll=bankroll,
                    config=config,
                )
                logger.debug(
                    f"[SIM-KELLY] {result.strategy}: market={market_price:.3f} → "
                    f"sim={sim_prob:.3f} (method={sim_result['method']}, "
                    f"VR={sim_result.get('variance_reduction', 'N/A')})"
                )
        except Exception as e:
            logger.debug(f"[SIM-KELLY] Simulation pricing failed: {e}")

    # Monte Carlo Kelly adjustment (when enabled + historical data available)
    bet_usd = naive_bet_usd
    if config.use_monte_carlo and mc_kelly is not None:
        naive_fraction = naive_bet_usd / bankroll if bankroll > 0 else 0
        mc_bet, mc_diag = mc_kelly.compute_size(
            strategy=result.strategy,
            naive_kelly_fraction=naive_fraction,
            bankroll=bankroll,
        )
        if mc_bet > 0:
            bet_usd = mc_bet
            logger.debug(
                f"[MC-KELLY] {result.strategy}: naive=${naive_bet_usd:.2f} → "
                f"mc=${mc_bet:.2f} (method={mc_diag.get('method')})"
            )

    # Convert USD to contracts at the COST-INCLUSIVE price: bet_usd is the capital we
    # intend to deploy, and the executor charges slippage + fee on top, so the real
    # contract count is bet_usd / effective_cost — using the raw price would overstate
    # the position and deploy more cash than bet_usd (ROADMAP C2).
    price = market_price if market_price > 0 else 0.50
    num_contracts = DEFAULT_COST_MODEL.contracts_for_budget(bet_usd, price)

    return bet_usd, round(num_contracts, 1)


# Type import for MC Kelly (avoids circular imports at module level)
try:
    from .quant_models import MonteCarloKelly
except ImportError:
    MonteCarloKelly = None


# ============================================================
# Mark-to-Market Engine
# ============================================================

class MarkToMarketEngine:
    """
    Updates positions with live prices and detects resolved markets.

    Called periodically by the orchestrator.
    """

    def __init__(
        self,
        executor: PredictionMarketExecutor,
        risk_manager: "Optional[RiskManager]" = None,
    ):
        self.executor = executor
        # Optional RiskManager so resolution-realized PnL feeds the per-strategy
        # drawdown circuit (ROADMAP D2). Market RESOLUTION is the PRIMARY way binary
        # positions take losses, but `check_resolutions` previously fed ONLY the
        # executor-level loss caps (D3/D4) and never `risk_manager.record_pnl` — so a
        # strategy could bleed out via resolutions without ever tripping its
        # drawdown-based auto-disable. Wiring the risk_manager here closes that bypass
        # (mirrors the earlier D3/D4 fix that closed the same resolution bypass for the
        # kill-switch counters). Optional/None-safe so the engine still works standalone.
        self.risk_manager = risk_manager
        self._resolution_cache: Dict[str, bool] = {}

    def update_prices(self):
        """Update all position prices from WebSocket feeds."""
        try:
            from .websocket_feeds import get_feed_manager
            feed = get_feed_manager()
        except Exception:
            return

        updated = 0
        for token_id, pos in list(self.executor.positions.items()):
            # Try to get live price
            price_data = feed.get_price(pos.exchange.value, token_id)
            if price_data and price_data.data_age_seconds < 300:
                old_price = pos.current_price
                pos.current_price = price_data.midpoint
                pos.unrealized_pnl = (pos.current_price - pos.avg_entry_price) * pos.size
                pos.updated_at = datetime.now(timezone.utc)
                updated += 1

        if updated > 0:
            logger.debug(f"[MTM] Updated {updated} position prices")

    def check_resolutions(self):
        """
        Check if any positions have resolved (market settled).

        For resolved markets:
        - If we held the winning outcome: realize profit
        - If we held the losing outcome: realize loss
        """
        try:
            from .polymarket_client import PolymarketClient
        except ImportError:
            return

        positions = list(self.executor.positions.items())
        if not positions:
            return

        # Reuse ONE client (and its requests.Session connection pool) across all
        # positions this cycle. The MTM loop runs every ~30s, so the old per-position
        # `PolymarketClient()` leaked a fresh Session per open position per cycle
        # (2880 cycles/day × N positions) — a deep-audit resource-churn finding. The
        # client's own get() carries timeout=15, so a hung venue cannot block forever.
        try:
            client = PolymarketClient()
        except Exception as e:  # never let client init break settlement
            logger.warning(f"[MTM] PolymarketClient init failed; skipping resolution check: {e}")
            return

        resolved = []
        for token_id, pos in positions:
            if token_id in self._resolution_cache:
                continue

            # Check if market has resolved
            try:
                # Check via Gamma API
                market = client.get_market_by_slug(pos.market_id)
                if market and market.resolved:
                    # Find the winning outcome
                    winning_price = 0.0
                    for outcome in market.outcomes:
                        if outcome.token_id == token_id:
                            winning_price = outcome.price  # 1.0 if won, 0.0 if lost
                            break
                    resolved.append((token_id, winning_price))
                    self._resolution_cache[token_id] = True

            except Exception as e:
                logger.debug(f"[MTM] Resolution check failed for {token_id}: {e}")

        # Realize P&L for resolved positions
        for token_id, settlement_price in resolved:
            if token_id in self.executor.positions:
                pos = self.executor.positions[token_id]
                pnl = (settlement_price - pos.avg_entry_price) * pos.size
                pos.realized_pnl += pnl
                pos.unrealized_pnl = 0.0
                pos.current_price = settlement_price

                # Feed the executor-level realized-PnL counters + AUTO-TRIP the kill
                # switch if this resolution loss breaches a hard cap (ROADMAP D3/D4).
                # Resolution is the PRIMARY way binary-market positions take losses, so
                # without this the loss caps would silently miss the dominant loss path
                # (the gate reads the same counters) — caught by the adversarial audit.
                self.executor.record_realized_pnl(pnl)

                # Feed the per-strategy DRAWDOWN circuit too (ROADMAP D2). Same bypass
                # as above but for `risk_manager.record_pnl`: without this, a strategy's
                # resolution losses never reach its drawdown-based auto-disable, so a
                # decayed alpha keeps trading. Best-effort + None-safe so a risk-manager
                # hiccup can never break the resolution/settlement path.
                # SCOPE (reviewer S2, honest): this closes the RESOLUTION path — the
                # dominant way binary positions realize PnL (held to settlement). The
                # SELL/partial-reduce path feeds the executor's caps but does not yet feed
                # risk_manager.record_pnl; wiring that is a named follow-up (positions are
                # usually held to resolution, so resolution is the right path to close first).
                if self.risk_manager is not None:
                    try:
                        strategy = (getattr(pos, "strategy", "") or "").strip()
                        if strategy:
                            self.risk_manager.record_pnl(strategy, pnl)
                    except Exception as e:  # pragma: no cover - defensive
                        logger.warning(
                            f"[MTM] risk_manager.record_pnl failed for {token_id}: {e}"
                        )

                logger.info(
                    f"[MTM] Position resolved: {token_id} | "
                    f"Settlement: ${settlement_price:.2f} | "
                    f"P&L: ${pnl:+.2f}"
                )

                # Remove closed position
                del self.executor.positions[token_id]

                # Persist resolution
                self._persist_resolution(pos, pnl, settlement_price)

    def _persist_resolution(self, pos: Position, pnl: float, settlement_price: float):
        """Persist a resolved position to DB."""
        try:
            from ..db.database import get_session
            from .models import PredictionPosition
            from sqlmodel import select

            with get_session() as session:
                stmt = select(PredictionPosition).where(
                    PredictionPosition.token_id == pos.token_id
                )
                db_pos = session.exec(stmt).first()
                if db_pos:
                    db_pos.is_active = False
                    db_pos.is_resolved = True
                    db_pos.resolution_value = settlement_price
                    db_pos.realized_pnl = pos.realized_pnl
                    db_pos.unrealized_pnl = 0.0
                    db_pos.closed_at = datetime.now(timezone.utc)
                    session.add(db_pos)
        except Exception as e:
            logger.error(f"[MTM] Failed to persist resolution: {e}")

    def get_summary(self) -> dict:
        """Get mark-to-market summary."""
        positions = list(self.executor.positions.values())
        return {
            "total_positions": len(positions),
            "total_market_value": sum(p.market_value for p in positions),
            "total_unrealized_pnl": sum(p.unrealized_pnl for p in positions),
            "total_realized_pnl": sum(p.realized_pnl for p in positions),
            "resolutions_cached": len(self._resolution_cache),
        }


# ============================================================
# Orchestrator
# ============================================================

class PredictionMarketOrchestrator:
    """
    The main loop that ties Scanner → Kelly → Execution → Persistence → MTM.

    Lifecycle:
    1. start() — launches background tasks
    2. Background tasks run continuously:
       a. scan_and_execute() — every scan_interval_sec
       b. mark_to_market() — every mtm_interval_sec
       c. snapshot_portfolio() — every snapshot_interval_sec
    3. stop() — cancels all tasks
    """

    def __init__(
        self,
        scanner: Optional[PredictionMarketScanner] = None,
        executor: Optional[PredictionMarketExecutor] = None,
        risk_manager: Optional[RiskManager] = None,
        kelly_config: Optional[KellyConfig] = None,
        scan_interval_sec: int = 120,
        mtm_interval_sec: int = 30,
        snapshot_interval_sec: int = 300,
    ):
        self.scanner = scanner
        self.executor = executor or get_executor(dry_run=True)
        self.risk_manager = risk_manager or RiskManager()
        self.kelly_config = kelly_config or KellyConfig()
        self.mtm_engine = MarkToMarketEngine(self.executor, risk_manager=self.risk_manager)

        # Simulation-enhanced pricing and probability tracking
        self.simulation_pricer = EnhancedContractPricer() if EnhancedContractPricer else None
        self.probability_trackers: Dict[str, "LiveProbabilityTracker"] = {}

        # Data-quality gate (ROADMAP A5): rejects stale/incomplete/insane markets
        # before any sizing or order placement.
        self._dq_validator = DataQualityValidator()

        self.scan_interval_sec = scan_interval_sec
        self.mtm_interval_sec = mtm_interval_sec
        self.snapshot_interval_sec = snapshot_interval_sec

        # State
        self._running = False
        self._tasks: List[asyncio.Task] = []
        self.total_scans = 0
        self.total_executions = 0
        self.total_skipped = 0
        self.last_scan_at: Optional[datetime] = None
        self.last_scan_opportunities: int = 0
        self.activity_log: List[dict] = []  # Recent activity entries for frontend
        self.last_scan_result: Optional[dict] = None  # Last scan summary
        self.last_scan_opportunities_raw: List[dict] = []  # Raw opportunities for frontend scanner

        # Durable audit log (ROADMAP G3 / OA-10): persists every decision and
        # would-be order so the history survives restarts (unlike activity_log).
        # Construction is best-effort — fall back to a no-op so a bad audit
        # setup can never break the orchestrator.
        try:
            # Imported lazily here (not at module top) so the audit table's
            # ``table=True`` registration happens only when an orchestrator is
            # actually constructed — mirroring the lazy ``from .models import``
            # pattern used elsewhere in this file and avoiding an eager dual-path
            # import collision in mixed test sessions.
            from .audit_log import AuditLogger, _NoOpAuditLogger
            self._audit = AuditLogger()
        except Exception as e:  # pragma: no cover - defensive
            logger.warning(f"[ORCHESTRATOR] AuditLogger init failed, using no-op: {e}")
            try:
                from .audit_log import _NoOpAuditLogger
                self._audit = _NoOpAuditLogger()
            except Exception:
                # Even the no-op import failed (package badly broken) — use an inline
                # shim so the hook call sites never hit an AttributeError on None.
                import types
                self._audit = types.SimpleNamespace(
                    record_decision=lambda *a, **k: None,
                    record_would_be_order=lambda *a, **k: None,
                    recent=lambda *a, **k: [],
                )

        # Alpha-lifecycle registry (ROADMAP B3): a durable record of each alpha's
        # lifecycle state (proposed → backtest → paper → promote → retire) with the
        # engine's fail-loud integrity gate. Best-effort + lazy (same dual-import
        # discipline as the audit log) so a persistence problem can never break init.
        self._registry_store = None
        self._strategy_registry = None
        self._init_strategy_registry()

    def _init_strategy_registry(self):
        """Load the persisted alpha-lifecycle registry, then sync it with deployed strategies.

        Best-effort: any failure leaves an in-memory registry so the recording API still
        works; only DURABILITY (not correctness) depends on the DB.
        """
        from .strategy_registry import StrategyRegistry
        try:
            from .strategy_registry_store import StrategyRegistryStore, _NoOpStrategyRegistryStore
            try:
                self._registry_store = StrategyRegistryStore()
            except Exception as e:  # pragma: no cover - defensive
                logger.warning(f"[ORCHESTRATOR] registry store init failed, no-op: {e}")
                self._registry_store = _NoOpStrategyRegistryStore()

            loaded = self._registry_store.load()
            self._strategy_registry = loaded if loaded is not None else StrategyRegistry()
        except Exception as e:  # pragma: no cover - defensive
            logger.warning(f"[ORCHESTRATOR] registry load failed: {e}")
            self._strategy_registry = StrategyRegistry()

        # Seed any deployed strategy not already tracked. Idempotent + re-callable (the
        # primary get_orchestrator() path attaches the scanner AFTER construction, so this
        # also runs again via sync_registry_with_scanner() once strategies are present —
        # otherwise the registry would be empty forever in production, reviewer S1).
        self.sync_registry_with_scanner()

    def sync_registry_with_scanner(self) -> int:
        """Propose any DEPLOYED scanner strategy not yet in the registry; persist if changed.

        Returns the number of newly-seeded strategies. Seeding state is PROPOSED — the
        HONEST state: every deployed strategy is a heuristic running in paper WITHOUT
        recorded backtest/OOS/calibration evidence, so none can legally reach
        PAPER/PROMOTED in the engine. The registry therefore truthfully shows that NO
        alpha has yet passed the integrity gate (rather than implying success). Safe to
        call repeatedly (e.g. after the scanner is attached); only persists on a real change.
        """
        if self._strategy_registry is None:
            from .strategy_registry import StrategyRegistry
            self._strategy_registry = StrategyRegistry()
        now = datetime.now(timezone.utc)
        seed_reason = "deployed heuristic; no backtest/OOS/calibration evidence recorded yet"
        added = 0
        for name in self._deployed_strategy_names():
            try:
                if name not in self._strategy_registry:
                    self._strategy_registry.propose(name, at=now, reason=seed_reason)
                    added += 1
            except Exception as e:  # pragma: no cover - defensive
                logger.debug(f"[ORCHESTRATOR] could not seed strategy {name!r}: {e}")
        # Persist ONLY when we actually added something — never overwrite a persisted
        # registry with an empty seed (which would wedge seeding on the next boot).
        if added and self._registry_store is not None:
            self._registry_store.save(self._strategy_registry)
        return added

    def _deployed_strategy_names(self) -> List[str]:
        """Names of the strategies currently registered on the scanner (sorted, unique)."""
        names = set()
        scanner = getattr(self, "scanner", None)
        for s in getattr(scanner, "strategies", []) or []:
            try:
                nm = getattr(s, "name", None)
                if nm:
                    names.add(str(nm))
            except Exception:  # pragma: no cover - defensive
                continue
        return sorted(names)

    def record_strategy_transition(
        self,
        name: str,
        to_state,
        reason: str = "",
        evidence=None,
        at=None,
    ):
        """Record + PERSIST a real alpha lifecycle transition (ROADMAP B3).

        Delegates to the pure engine, which enforces the legal-transition map AND the
        fail-loud integrity gate (e.g. a promotion REQUIRES recorded backtest+OOS+
        calibration evidence). Raises ``IllegalTransition`` / ``MissingEvidence`` exactly
        as the engine does. On success the whole registry snapshot is persisted (best-effort).

        HONESTY: the gate checks the PRESENCE of the supplied ``evidence`` booleans — it is
        an audit trail, NOT an authenticity verifier (a caller that hand-sets
        ``calibration_passed=True`` without a real passing eval is lying to itself). This is
        why this method is NOT exposed over an unauthenticated HTTP body: a trusted in-process
        caller must DERIVE the evidence from the actual E5/E2 gate results before promoting.
        Wiring that derivation is the named B3 follow-up.

        ``to_state`` may be a ``LifecycleState`` or its string value; ``at`` defaults to
        wall-clock UTC (live operation, not a reproducible backtest fingerprint).
        """
        from .strategy_registry import LifecycleState
        if self._strategy_registry is None:
            from .strategy_registry import StrategyRegistry
            self._strategy_registry = StrategyRegistry()
        target = to_state if isinstance(to_state, LifecycleState) else LifecycleState(to_state)
        when = at or datetime.now(timezone.utc)
        record = self._strategy_registry.transition(
            name, target, at=when, reason=reason, evidence=evidence
        )
        if self._registry_store is not None:
            self._registry_store.save(self._strategy_registry)
        return record

    def propose_strategy(self, name: str, reason: str = "", at=None):
        """Register a NEW alpha in PROPOSED state + persist (ROADMAP B3)."""
        if self._strategy_registry is None:
            from .strategy_registry import StrategyRegistry
            self._strategy_registry = StrategyRegistry()
        when = at or datetime.now(timezone.utc)
        record = self._strategy_registry.propose(name, at=when, reason=reason)
        if self._registry_store is not None:
            self._registry_store.save(self._strategy_registry)
        return record

    def get_strategy_registry(self) -> dict:
        """Deterministic, JSON-serializable snapshot of the alpha-lifecycle registry."""
        if self._strategy_registry is None:
            return {"alphas": []}
        return self._strategy_registry.to_dict()

    def _add_activity(self, type: str, message: str, strategy: str = None):
        """Add an entry to the activity log (kept in memory, max 200)."""
        entry = {
            "id": f"{int(datetime.now(timezone.utc).timestamp()*1000)}-{id(message) % 10000}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": type,
            "strategy": strategy,
            "message": message,
        }
        self.activity_log.insert(0, entry)
        if len(self.activity_log) > 200:
            self.activity_log = self.activity_log[:200]

    async def start(self):
        """Start all background loops."""
        if self._running:
            return
        self._running = True

        self._tasks = [
            asyncio.create_task(self._scan_loop()),
            asyncio.create_task(self._mtm_loop()),
            asyncio.create_task(self._snapshot_loop()),
        ]
        logger.info(
            f"[ORCHESTRATOR] Started | scan={self.scan_interval_sec}s | "
            f"mtm={self.mtm_interval_sec}s | snapshot={self.snapshot_interval_sec}s"
        )

    async def stop(self):
        """Stop all background loops."""
        self._running = False
        for task in self._tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks.clear()
        logger.info("[ORCHESTRATOR] Stopped")

    # ================================================================
    # Scan Loop
    # ================================================================

    async def _scan_loop(self):
        """Periodically scan for opportunities and execute."""
        while self._running:
            try:
                await self.scan_and_execute()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[ORCHESTRATOR] Scan loop error: {e}")
            await asyncio.sleep(self.scan_interval_sec)

    async def scan_and_execute(self) -> dict:
        """
        Run one scan cycle: scan → filter → size → execute → persist.

        Returns summary of what happened.
        """
        if not self.scanner:
            return {"error": "No scanner configured"}

        self.total_scans += 1
        self.last_scan_at = datetime.now(timezone.utc)

        # 1. Scan
        logger.info(f"[ORCHESTRATOR] Scan #{self.total_scans} starting...")
        self._add_activity("scan", f"Scan #{self.total_scans} starting across all strategies...")
        opportunities = self.scanner.scan(market_limit=200)
        self.last_scan_opportunities = len(opportunities)

        # Store raw opportunities for frontend scanner tab
        self.last_scan_opportunities_raw = [
            {
                "id": f"{opp.strategy}-{self.total_scans}-{i}",
                "strategy": opp.strategy,
                "market": opp.market.question,
                "market_id": opp.market.id,
                "outcome": (
                    opp.market.outcomes[opp.outcome_idx].label
                    if 0 <= opp.outcome_idx < len(opp.market.outcomes)
                    else "Both"
                ),
                "side": opp.side,
                "entry_price": opp.entry_price,
                "edge": opp.edge,
                "confidence": opp.confidence,
                "reason": opp.reason,
                "timestamp": opp.timestamp.isoformat() if hasattr(opp, 'timestamp') and opp.timestamp else datetime.now(timezone.utc).isoformat(),
            }
            for i, opp in enumerate(opportunities)
        ]

        if not opportunities:
            self._add_activity("scan", f"Scan #{self.total_scans} complete: 0 opportunities found")
            no_result = {"scan": self.total_scans, "opportunities": 0, "executed": 0}
            self.last_scan_result = no_result
            return no_result

        # 2. Filter + Size + Execute
        executed = []
        skipped = []
        bankroll = self.executor.max_portfolio_usd - self.executor.total_exposure

        for opp in opportunities:
            # Data-quality gate (ROADMAP A5): skip markets with stale, incomplete,
            # or price-insane data before any order is sized or placed.
            dq_result = self._dq_validator.check_market(opp.market)
            if not dq_result.ok:
                reason = f"data-quality: {dq_result.reason}"
                logger.warning(
                    f"[ORCHESTRATOR] Skipping {opp.market.question[:60]!r} — {reason}"
                )
                skipped.append({"market": opp.market.question[:60], "reason": reason})
                self.total_skipped += 1
                try:
                    self._audit.record_decision(
                        "dq_reject",
                        strategy=opp.strategy,
                        market_id=opp.market.id,
                        market_question=opp.market.question[:200],
                        side=opp.side,
                        edge=opp.edge,
                        confidence=opp.confidence,
                        reason=dq_result.reason,
                    )
                except Exception:
                    pass
                continue

            # Risk check
            risk_result = self.risk_manager.check_opportunity(
                opp, self.executor, self.scanner
            )
            if not risk_result.approved:
                skipped.append({"market": opp.market.question[:60], "reason": risk_result.reason})
                self.total_skipped += 1
                try:
                    self._audit.record_decision(
                        "risk_reject",
                        strategy=opp.strategy,
                        market_id=opp.market.id,
                        market_question=opp.market.question[:200],
                        side=opp.side,
                        edge=opp.edge,
                        confidence=opp.confidence,
                        reason=risk_result.reason,
                    )
                except Exception:
                    pass
                continue

            # Kelly sizing
            bet_usd, num_contracts = size_from_scan_result(
                opp, bankroll, self.kelly_config
            )
            if num_contracts <= 0:
                skipped.append({"market": opp.market.question[:60], "reason": "Kelly size = 0"})
                try:
                    self._audit.record_decision(
                        "kelly_skip",
                        strategy=opp.strategy,
                        market_id=opp.market.id,
                        market_question=opp.market.question[:200],
                        side=opp.side,
                        edge=opp.edge,
                        confidence=opp.confidence,
                        reason="Kelly size = 0",
                    )
                except Exception:
                    pass
                continue

            # Determine token and labels
            exchange = Exchange.POLYMARKET
            outcome = opp.market.outcomes[opp.outcome_idx] if opp.outcome_idx >= 0 else None
            token_id = outcome.token_id if outcome else ""
            outcome_label = outcome.label if outcome else ""

            # Build order
            order = OrderRequest(
                exchange=exchange,
                market_id=opp.market.id,
                token_id=token_id,
                side=OrderSide.BUY if opp.side == "BUY" else OrderSide.SELL,
                order_type=OrderType.LIMIT,
                size=num_contracts,
                price=opp.entry_price,
                strategy=opp.strategy,
                market_question=opp.market.question,
                outcome_label=outcome_label,
            )

            # Execute
            result = self.executor.execute(order)

            # Durable audit of the REAL would-be order (filled/rejected/gated).
            # Reflects the actual OrderResult — never fabricates a success.
            try:
                self._audit.record_would_be_order(
                    result,
                    strategy=opp.strategy,
                    market_question=opp.market.question[:200],
                    edge=opp.edge,
                    confidence=opp.confidence,
                    is_dry_run=getattr(self.executor, "dry_run", None),
                    live_enabled=getattr(self.executor, "live_enabled", None),
                )
            except Exception:
                pass

            if result.is_success:
                self.total_executions += 1
                bankroll -= bet_usd  # Reduce available bankroll

                executed.append({
                    "order_id": result.order_id,
                    "market": opp.market.question[:60],
                    "strategy": opp.strategy,
                    "side": opp.side,
                    "size": num_contracts,
                    "price": opp.entry_price,
                    "edge": opp.edge,
                    "kelly_bet_usd": bet_usd,
                })

                self._add_activity(
                    "execute",
                    f"Executed {opp.side} {num_contracts} @ ${opp.entry_price:.2f} — {opp.market.question[:60]} (edge: {opp.edge*100:.1f}%, Kelly: ${bet_usd:.2f})",
                    opp.strategy,
                )

                # Persist order to DB
                self._persist_order(result, opp)

                # Update strategy tracking
                for s in self.scanner.strategies:
                    if s.name == opp.strategy:
                        s.trades_executed += 1
                        break

                # Record execution in risk manager
                self.risk_manager.record_execution(result)

            else:
                skipped.append({
                    "market": opp.market.question[:60],
                    "reason": result.error or result.status.value,
                })

        # Log signals for top opportunities
        for opp in opportunities[:5]:
            self._add_activity(
                "signal",
                f"{opp.reason[:80]} — edge: {opp.edge*100:.1f}%, confidence: {opp.confidence*100:.0f}%",
                opp.strategy,
            )

        summary = {
            "scan": self.total_scans,
            "opportunities": len(opportunities),
            "executed": len(executed),
            "skipped": len(skipped),
            "bankroll_remaining": bankroll,
            "executions": executed[:10],
            "skip_reasons": skipped[:10],
        }

        # Log execution summary with skip reason breakdown
        if skipped:
            from collections import Counter
            reason_counts = Counter(s["reason"].split(":")[0].strip() for s in skipped)
            reason_summary = ", ".join(f"{r}: {c}" for r, c in reason_counts.most_common(5))
            summary_msg = (
                f"Scan #{self.total_scans} complete: "
                f"{len(opportunities)} opps → {len(executed)} executed, {len(skipped)} skipped "
                f"({reason_summary})"
            )
            logger.info(f"[ORCHESTRATOR] {summary_msg}")
        else:
            summary_msg = (
                f"Scan #{self.total_scans} complete: "
                f"{len(opportunities)} opps → {len(executed)} executed, {len(skipped)} skipped"
            )
            logger.info(f"[ORCHESTRATOR] {summary_msg}")

        self._add_activity("scan", summary_msg)
        self.last_scan_result = summary
        return summary

    def _persist_order(self, result: OrderResult, opp: ScanResult):
        """Persist an executed order to the database."""
        try:
            from ..db.database import get_session
            from .models import PredictionOrder, PredictionPosition

            with get_session() as session:
                # Save order
                db_order = PredictionOrder(
                    portfolio_id=1,
                    order_id=result.order_id,
                    exchange=result.exchange.value,
                    market_id=result.market_id,
                    token_id=result.token_id,
                    side=result.side.value,
                    order_type=result.order_type.value,
                    size=result.size,
                    limit_price=result.price,
                    status=result.status.value,
                    filled_size=result.filled_size,
                    filled_price=result.filled_price,
                    fees=result.fees,
                    strategy=opp.strategy,
                    is_dry_run=self.executor.dry_run,
                    raw_response_json=json.dumps(result.raw_response) if result.raw_response else None,
                )
                session.add(db_order)

                # Upsert position
                if result.is_success and result.token_id in self.executor.positions:
                    pos = self.executor.positions[result.token_id]
                    from sqlmodel import select
                    stmt = select(PredictionPosition).where(
                        PredictionPosition.token_id == result.token_id
                    )
                    db_pos = session.exec(stmt).first()

                    if db_pos:
                        db_pos.size = pos.size
                        db_pos.avg_entry_price = pos.avg_entry_price
                        db_pos.current_price = pos.current_price
                        db_pos.market_value = pos.market_value
                        db_pos.unrealized_pnl = pos.unrealized_pnl
                        db_pos.updated_at = datetime.utcnow()
                        session.add(db_pos)
                    else:
                        outcome_label = ""
                        if 0 <= opp.outcome_idx < len(opp.market.outcomes):
                            outcome_label = opp.market.outcomes[opp.outcome_idx].label

                        db_pos = PredictionPosition(
                            portfolio_id=1,
                            exchange=result.exchange.value,
                            market_id=result.market_id,
                            token_id=result.token_id,
                            market_question=opp.market.question[:200],
                            outcome_label=outcome_label,
                            category=opp.market.category,
                            side="long" if result.side == OrderSide.BUY else "short",
                            size=result.filled_size,
                            avg_entry_price=result.filled_price,
                            current_price=result.filled_price,
                            market_value=result.filled_size * result.filled_price,
                            strategy=opp.strategy,
                            confidence=opp.confidence,
                            edge_at_entry=opp.edge,
                        )
                        session.add(db_pos)

        except Exception as e:
            logger.error(f"[ORCHESTRATOR] Failed to persist order: {e}")

    # ================================================================
    # Mark-to-Market Loop
    # ================================================================

    async def _mtm_loop(self):
        """Periodically update positions with live prices."""
        while self._running:
            try:
                self.mtm_engine.update_prices()

                # Update simulation probability trackers
                if LiveProbabilityTracker is not None:
                    for token_id, pos in list(self.executor.positions.items()):
                        if token_id not in self.probability_trackers:
                            self.probability_trackers[token_id] = LiveProbabilityTracker(
                                prior_prob=pos.avg_entry_price
                            )
                        if pos.current_price > 0:
                            self.probability_trackers[token_id].update(pos.current_price)

                self.mtm_engine.check_resolutions()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[ORCHESTRATOR] MTM error: {e}")
            await asyncio.sleep(self.mtm_interval_sec)

    # ================================================================
    # Snapshot Loop
    # ================================================================

    async def _snapshot_loop(self):
        """Periodically take portfolio snapshots for equity curve."""
        while self._running:
            try:
                await asyncio.sleep(self.snapshot_interval_sec)
                self._take_snapshot()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[ORCHESTRATOR] Snapshot error: {e}")

    def _take_snapshot(self):
        """Take a portfolio P&L snapshot."""
        try:
            from ..db.database import get_session
            from .models import PredictionPnLSnapshot

            positions = list(self.executor.positions.values())
            poly_value = sum(
                p.market_value for p in positions if p.exchange == Exchange.POLYMARKET
            )
            kalshi_value = 0.0  # Kalshi not yet integrated
            total_exposure = sum(p.market_value for p in positions)
            total_unrealized = sum(p.unrealized_pnl for p in positions)
            total_realized = sum(p.realized_pnl for p in positions)
            cash = self.executor.max_portfolio_usd - total_exposure

            # Strategy breakdown
            strategy_values: Dict[str, float] = {}
            for pos in positions:
                strategy_values[pos.strategy] = (
                    strategy_values.get(pos.strategy, 0.0) + pos.market_value
                )

            with get_session() as session:
                snapshot = PredictionPnLSnapshot(
                    portfolio_id=1,
                    total_value_usd=cash + total_exposure + total_unrealized,
                    cash_usd=cash,
                    positions_value_usd=total_exposure,
                    realized_pnl=total_realized,
                    unrealized_pnl=total_unrealized,
                    total_fees=self.executor.total_fees,
                    num_positions=len(positions),
                    polymarket_value=poly_value,
                    kalshi_value=kalshi_value,
                    strategy_breakdown_json=json.dumps(strategy_values),
                )
                session.add(snapshot)

            logger.debug(
                f"[ORCHESTRATOR] Snapshot: ${cash + total_exposure:,.2f} total | "
                f"{len(positions)} positions | P&L ${total_unrealized + total_realized:+,.2f}"
            )
        except Exception as e:
            logger.error(f"[ORCHESTRATOR] Snapshot error: {e}")

    # ================================================================
    # Metrics helpers (read-only)
    # ================================================================

    def get_resolved_trades(self):
        """Return a list of TradePnL built ONLY from genuinely resolved positions.

        READ-ONLY: does not alter resolution accounting, positions, or any executor
        state.  Maps from the DB-persisted resolved PredictionPosition records
        (is_resolved=True) so data survives orchestrator restarts.

        Fields derived honestly:
        - timestamp: closed_at when available, else opened_at (position-close event)
        - pnl_usd: realized_pnl column from the DB record (set by _persist_resolution)
        - is_win: pnl_usd > 0

        Positions with no closed_at AND no opened_at are omitted rather than
        inventing a timestamp.  Positions whose realized_pnl is 0.0 AND
        resolution_value is None are omitted (no honest PnL to record).
        """
        from .weekly_metrics import TradePnL

        trades = []

        # Primary source: DB-persisted resolved positions (survive restarts).
        try:
            from ..db.database import get_session
            from .models import PredictionPosition
            from sqlmodel import select

            with get_session() as session:
                stmt = select(PredictionPosition).where(
                    PredictionPosition.is_resolved == True  # noqa: E712
                )
                db_positions = session.exec(stmt).all()

                for pos in db_positions:
                    # We need a timestamp to bucket by week. Prefer the resolution
                    # time (closed_at); fall back to opened_at only if missing.
                    ts = pos.closed_at
                    if ts is None:
                        ts = pos.opened_at
                        if ts is not None:
                            logger.warning(
                                "[METRICS] resolved position %s has no closed_at; "
                                "bucketing by opened_at (week may be slightly off).",
                                getattr(pos, "market_id", "?"),
                            )
                    if ts is None:
                        continue  # cannot place this trade on the timeline

                    # resolution_value is None means the resolution was never
                    # persisted properly — skip rather than invent pnl.
                    if pos.resolution_value is None and pos.realized_pnl == 0.0:
                        continue

                    trades.append(
                        TradePnL(
                            timestamp=ts,
                            pnl_usd=pos.realized_pnl,
                            is_win=pos.realized_pnl > 0.0,
                        )
                    )

        except Exception as e:
            logger.debug(f"[METRICS] DB resolved-position fetch failed: {e}")

        return trades

    def get_resolved_trades_by_strategy(self):
        """Return resolved trades TAGGED with the strategy that opened them (ROADMAP E6).

        READ-ONLY, like ``get_resolved_trades`` — does not alter resolution accounting,
        positions, or executor state.  Maps from DB-persisted resolved
        ``PredictionPosition`` rows (``is_resolved=True``), which carry a ``strategy``
        column, into ``StrategyTradePnL`` records the per-strategy attribution engine
        consumes.

        Honest by construction:
        * A position whose ``strategy`` tag is empty/None is bucketed under the
          sentinel ``"unattributed"`` rather than dropped (so portfolio totals still
          reconcile) — the attribution engine never fabricates a strategy.
        * Same timestamp/skip rules as ``get_resolved_trades`` (no invented timeline,
          no invented PnL).
        """
        from .per_strategy_metrics import StrategyTradePnL

        trades = []
        try:
            from ..db.database import get_session
            from .models import PredictionPosition
            from sqlmodel import select

            with get_session() as session:
                stmt = select(PredictionPosition).where(
                    PredictionPosition.is_resolved == True  # noqa: E712
                )
                db_positions = session.exec(stmt).all()

                for pos in db_positions:
                    ts = pos.closed_at
                    if ts is None:
                        ts = pos.opened_at
                        if ts is not None:
                            # Consistent with get_resolved_trades: warn (don't silently
                            # bucket) when falling back to opened_at (reviewer F2).
                            logger.warning(
                                "[METRICS] resolved position %s has no closed_at; "
                                "bucketing by opened_at (week may be slightly off).",
                                getattr(pos, "market_id", "?"),
                            )
                    if ts is None:
                        continue  # cannot place this trade on the timeline
                    # No honest PnL to record (resolution never persisted properly).
                    if pos.resolution_value is None and pos.realized_pnl == 0.0:
                        continue

                    strategy = (getattr(pos, "strategy", "") or "").strip() or "unattributed"
                    trades.append(
                        StrategyTradePnL(
                            strategy=strategy,
                            timestamp=ts,
                            pnl_usd=pos.realized_pnl,
                            is_win=pos.realized_pnl > 0.0,
                        )
                    )
        except Exception as e:
            logger.debug(f"[METRICS] DB by-strategy resolved-position fetch failed: {e}")

        return trades

    def get_resolved_evaluation_trades(self):
        """Return ``ResolvedTrade`` records for the E5 evaluation-window engine.

        READ-ONLY. Composes on ``get_resolved_trades_by_strategy`` (same DB-persisted
        resolved positions) and adapts each into an ``evaluation_window.ResolvedTrade``.
        ``predicted_prob``/``actual_outcome`` are left ``None`` — no per-trade calibration
        signal is persisted yet, so the window engine reports realized PnL / hit-rate /
        drawdown honestly and leaves Brier ``None`` (never fabricated).
        """
        from .evaluation_window import ResolvedTrade

        return [
            ResolvedTrade(
                strategy=t.strategy,
                timestamp=t.timestamp,
                pnl_usd=t.pnl_usd,
                is_win=t.is_win,
            )
            for t in self.get_resolved_trades_by_strategy()
        ]

    def get_resolved_predictions(self):
        """Return time-ordered ``ResolvedPrediction`` records for the E2 drift detector.

        READ-ONLY. Built from DB-persisted resolved positions that carry a NON-degenerate
        model edge (``edge_at_entry != 0``), ordered by resolution time (``closed_at``)
        so a chronological baseline/recent split is possible. Mirrors the calibration
        endpoint's honest construction: a position whose recorded model edge is exactly 0
        carries ``predicted_prob == market_price`` and cannot inform a calibration test,
        so it is SKIPPED rather than imputed — which makes "no non-degenerate predictions"
        the honest default for the current paper reality (strategies seed model to crowd).

        Keep the degenerate-skip filter (resolution_value None, price at the {0,1} boundary,
        edge_at_entry == 0) IN SYNC with the ``/prediction-markets/metrics/calibration``
        route, which reconstructs ResolvedPrediction the same way — a drift between the two
        would be a silent honesty bug.
        """
        from .calibration import ResolvedPrediction

        rows = []
        try:
            from ..db.database import get_session
            from .models import PredictionPosition
            from sqlmodel import select

            with get_session() as session:
                stmt = select(PredictionPosition).where(
                    PredictionPosition.is_resolved == True  # noqa: E712
                )
                db_positions = session.exec(stmt).all()

                for pos in db_positions:
                    if pos.resolution_value is None:
                        continue
                    if pos.avg_entry_price <= 0.0 or pos.avg_entry_price >= 1.0:
                        continue
                    if pos.edge_at_entry == 0.0:
                        continue  # degenerate (model == crowd) — never impute
                    ts = pos.closed_at or pos.opened_at
                    if ts is None:
                        continue
                    market_price = pos.avg_entry_price
                    predicted_prob = max(0.0, min(1.0, market_price + pos.edge_at_entry))
                    outcome = 1 if pos.resolution_value >= 0.5 else 0
                    rows.append(
                        (
                            ts,
                            ResolvedPrediction(
                                market_id=pos.market_id,
                                predicted_prob=predicted_prob,
                                market_price=market_price,
                                outcome=outcome,
                            ),
                        )
                    )
                # Sort INSIDE the guarded block: a mix of naive/aware closed_at values
                # would raise TypeError here, and we want that to degrade to the honest
                # empty result (insufficient_data) rather than propagate.
                rows.sort(key=lambda r: r[0])
        except Exception as e:
            logger.debug(f"[METRICS] resolved-prediction load failed: {e}")
            return []

        return [r[1] for r in rows]

    # ================================================================
    # Status
    # ================================================================

    def get_status(self) -> dict:
        """Get orchestrator status."""
        return {
            "running": self._running,
            "total_scans": self.total_scans,
            "total_executions": self.total_executions,
            "total_skipped": self.total_skipped,
            "last_scan_at": self.last_scan_at.isoformat() if self.last_scan_at else None,
            "last_scan_opportunities": self.last_scan_opportunities,
            "scan_interval_sec": self.scan_interval_sec,
            "mtm_interval_sec": self.mtm_interval_sec,
            "snapshot_interval_sec": self.snapshot_interval_sec,
            "kelly_config": {
                "fractional_kelly": self.kelly_config.fractional_kelly,
                "min_bet_usd": self.kelly_config.min_bet_usd,
                "max_bet_usd": self.kelly_config.max_bet_usd,
                "min_edge": self.kelly_config.min_edge,
                "min_confidence": self.kelly_config.min_confidence,
            },
            "simulation": {
                "pricer_available": self.simulation_pricer is not None,
                "tracked_contracts": len(self.probability_trackers),
                "tracker_divergences": {
                    tid: t.divergence_from_market()
                    for tid, t in list(self.probability_trackers.items())[:10]
                },
            },
            "risk_manager": self.risk_manager.get_status(),
            "mtm": self.mtm_engine.get_summary(),
            "portfolio": self.executor.get_portfolio_summary(),
            "activity_log": self.activity_log[:50],
            "last_scan_result": self.last_scan_result,
        }


# ============================================================
# Singleton
# ============================================================

_orchestrator: Optional[PredictionMarketOrchestrator] = None


def get_orchestrator() -> PredictionMarketOrchestrator:
    """Get or create the global orchestrator."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = PredictionMarketOrchestrator()
    return _orchestrator


def init_orchestrator(
    scanner: Optional[PredictionMarketScanner] = None,
    scan_interval_sec: int = 120,
):
    """Initialize the orchestrator without starting scan loops.

    The user can start scanning from the UI via bot/start or bot/scan-now.
    """
    global _orchestrator
    if scanner is None:
        try:
            scanner = _build_default_scanner()
        except Exception as e:
            logger.warning(f"[ORCHESTRATOR] Scanner auto-config failed: {e}")

    _orchestrator = PredictionMarketOrchestrator(
        scanner=scanner,
        scan_interval_sec=scan_interval_sec,
    )
    return _orchestrator


async def start_orchestrator(
    scanner: Optional[PredictionMarketScanner] = None,
    scan_interval_sec: int = 120,
):
    """Start the orchestrator with scan loops (called from bot/start).

    If no scanner is provided, auto-configures one with all strategies.
    """
    global _orchestrator
    if _orchestrator is None:
        init_orchestrator(scanner, scan_interval_sec)
    await _orchestrator.start()


def _build_default_scanner() -> PredictionMarketScanner:
    """Build a scanner with all strategies enabled."""
    import os
    from .polymarket_client import PolymarketClient
    from .strategies import (
        StrategyConfig,
        NearCertaintyStrategy,
        SameMarketArbitrageStrategy,
        CrossMarketArbitrageStrategy,
        MarketMakingStrategy,
        FlashCrashStrategy,
        WhaleCopyTradingStrategy,
    )
    from .advanced_strategies import (
        NOPositionScanner,
        LogicalImplicationDetector,
        WalletBehaviorDivergence,
        AdaptiveBuySignalThreshold,
    )

    client = PolymarketClient()
    config = StrategyConfig(dry_run=True)
    scanner = PredictionMarketScanner(client)

    # Register standalone strategies (not wrapped by adaptive)
    scanner.add_strategy(SameMarketArbitrageStrategy(client, config))
    scanner.add_strategy(MarketMakingStrategy(client, config))
    scanner.add_strategy(FlashCrashStrategy(client, config))
    scanner.add_strategy(WhaleCopyTradingStrategy(client, config))

    # Advanced standalone strategies
    scanner.add_strategy(LogicalImplicationDetector(client, config))
    scanner.add_strategy(WalletBehaviorDivergence(client, config))

    # Adaptive threshold wraps edge-based strategies for per-horizon filtering.
    # These are NOT registered directly to avoid duplicate signals.
    adaptive = AdaptiveBuySignalThreshold(client, config)
    adaptive.add_inner_strategy(NearCertaintyStrategy(client, config))
    adaptive.add_inner_strategy(CrossMarketArbitrageStrategy(client, config))
    adaptive.add_inner_strategy(NOPositionScanner(client, config))
    scanner.add_strategy(adaptive)

    # Wire weather strategy if NOAA data available
    try:
        from .noaa_weather import NOAAWeatherClient
        from .strategies import WeatherArbitrageStrategy
        noaa = NOAAWeatherClient()
        weather = WeatherArbitrageStrategy(client, config)
        scanner.add_strategy(weather)
    except Exception as e:
        logger.warning(f"[ORCHESTRATOR] Weather strategy not loaded: {e}")

    logger.info(f"[ORCHESTRATOR] Auto-configured scanner with {len(scanner.strategies)} strategies")
    return scanner


async def stop_orchestrator():
    """Stop the orchestrator."""
    global _orchestrator
    if _orchestrator:
        await _orchestrator.stop()
