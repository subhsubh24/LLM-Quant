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
    min_edge: float = 0.03          # Don't trade edges below 3%
    min_confidence: float = 0.60    # Don't trade low-confidence signals
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

    # Deterministic Kelly first (always computed)
    naive_bet_usd = kelly_size(
        edge=result.edge,
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
                    edge=win_probability - market_price,
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

    # Convert USD to contracts
    price = market_price if market_price > 0 else 0.50
    num_contracts = bet_usd / price

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

    def __init__(self, executor: PredictionMarketExecutor):
        self.executor = executor
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
            from .kalshi_client import KalshiClient
        except ImportError:
            return

        resolved = []
        for token_id, pos in list(self.executor.positions.items()):
            if token_id in self._resolution_cache:
                continue

            # Check if market has resolved
            try:
                if pos.exchange == Exchange.POLYMARKET:
                    # Check via Gamma API
                    client = PolymarketClient()
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

                elif pos.exchange == Exchange.KALSHI:
                    client = KalshiClient()
                    market = client.get_market_by_ticker(pos.market_id)
                    if market and market.resolved:
                        winning_price = 1.0 if market.outcomes[0].price > 0.5 else 0.0
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
                    db_pos.closed_at = datetime.utcnow()
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
        self.mtm_engine = MarkToMarketEngine(self.executor)

        # Simulation-enhanced pricing and probability tracking
        self.simulation_pricer = EnhancedContractPricer() if EnhancedContractPricer else None
        self.probability_trackers: Dict[str, "LiveProbabilityTracker"] = {}

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
        opportunities = self.scanner.scan(market_limit=200)
        self.last_scan_opportunities = len(opportunities)

        if not opportunities:
            return {"scan": self.total_scans, "opportunities": 0, "executed": 0}

        # 2. Filter + Size + Execute
        executed = []
        skipped = []
        bankroll = self.executor.max_portfolio_usd - self.executor.total_exposure

        for opp in opportunities:
            # Risk check
            risk_result = self.risk_manager.check_opportunity(
                opp, self.executor, self.scanner
            )
            if not risk_result.approved:
                skipped.append({"market": opp.market.question[:60], "reason": risk_result.reason})
                self.total_skipped += 1
                continue

            # Kelly sizing
            bet_usd, num_contracts = size_from_scan_result(
                opp, bankroll, self.kelly_config
            )
            if num_contracts <= 0:
                skipped.append({"market": opp.market.question[:60], "reason": "Kelly size = 0"})
                continue

            # Determine exchange
            exchange = Exchange.POLYMARKET
            token_id = opp.market.outcomes[opp.outcome_idx].token_id if opp.outcome_idx >= 0 else ""
            if opp.market.resolution_source == "kalshi":
                exchange = Exchange.KALSHI
                token_id = opp.market.id

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
            )

            # Execute
            result = self.executor.execute(order)
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

        summary = {
            "scan": self.total_scans,
            "opportunities": len(opportunities),
            "executed": len(executed),
            "skipped": len(skipped),
            "bankroll_remaining": bankroll,
            "executions": executed[:10],
            "skip_reasons": skipped[:10],
        }

        logger.info(
            f"[ORCHESTRATOR] Scan #{self.total_scans} complete: "
            f"{len(opportunities)} opps → {len(executed)} executed, {len(skipped)} skipped"
        )

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
            kalshi_value = sum(
                p.market_value for p in positions if p.exchange == Exchange.KALSHI
            )
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


async def start_orchestrator(
    scanner: Optional[PredictionMarketScanner] = None,
    scan_interval_sec: int = 120,
):
    """Start the orchestrator (called from routes or app lifespan).

    If no scanner is provided, auto-configures one with all strategies
    and wires up Kalshi auth from environment variables.
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
    await _orchestrator.start()


def _build_default_scanner() -> PredictionMarketScanner:
    """Build a scanner with all strategies enabled."""
    import os
    from .polymarket_client import PolymarketClient
    from .kalshi_client import KalshiClient
    from .strategies import (
        StrategyConfig,
        NearCertaintyStrategy,
        SameMarketArbitrageStrategy,
        CrossMarketArbitrageStrategy,
        MarketMakingStrategy,
        FlashCrashStrategy,
        WhaleCopyTradingStrategy,
        CrossExchangeArbitrageStrategy,
    )

    client = PolymarketClient()
    config = StrategyConfig(dry_run=True)
    scanner = PredictionMarketScanner(client)

    # Register all strategies
    scanner.add_strategy(NearCertaintyStrategy(client, config))
    scanner.add_strategy(SameMarketArbitrageStrategy(client, config))
    scanner.add_strategy(CrossMarketArbitrageStrategy(client, config))
    scanner.add_strategy(MarketMakingStrategy(client, config))
    scanner.add_strategy(FlashCrashStrategy(client, config))
    scanner.add_strategy(WhaleCopyTradingStrategy(client, config))

    # Wire cross-exchange arb with Kalshi client if credentials available
    kalshi_client = KalshiClient()
    cross_exchange = CrossExchangeArbitrageStrategy(
        client, config, kalshi_client=kalshi_client
    )
    scanner.add_strategy(cross_exchange)

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
