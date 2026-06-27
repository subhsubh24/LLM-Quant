"""
Paper Trading Simulator for Prediction Markets.

Connects to live Polymarket data feeds (read-only) and simulates
trading with virtual money. Uses the simulation engine for enhanced
pricing, probability tracking, and risk analysis.

Usage:
    sim = PaperTradingSimulator(bankroll=10_000)

    # Manual trading
    sim.buy("market-slug", outcome_idx=0, size=100)
    sim.refresh_prices()
    sim.mark_to_market()
    print(sim.get_portfolio())

    # Automated scanning
    from .strategies import PredictionMarketScanner
    scanner = PredictionMarketScanner(PolymarketClient())
    sim.run_scan_cycle(scanner)

    # Full simulation analysis on a contract
    analysis = sim.simulate_contract("market-slug", outcome_idx=0)
    print(f"Fair value: {analysis['sim_price']:.4f}")
    print(f"MC paths: {analysis['n_paths']}")
"""

import logging
import math
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .polymarket_client import Market, Outcome, PolymarketClient, ScanResult

# Graceful imports for simulation modules
try:
    from .simulation_integration import EnhancedContractPricer, LiveProbabilityTracker
except ImportError:
    EnhancedContractPricer = None  # type: ignore[assignment,misc]
    LiveProbabilityTracker = None  # type: ignore[assignment,misc]

try:
    from .orchestrator import kelly_size, KellyConfig, size_from_scan_result
except ImportError:
    kelly_size = None  # type: ignore[assignment,misc]
    KellyConfig = None  # type: ignore[assignment,misc]
    size_from_scan_result = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)

# Default simulation parameters
DEFAULT_VOL = 0.30  # Annualized volatility for prediction market contracts
DEFAULT_HORIZON_DAYS = 30  # Default time-to-expiry assumption
DEFAULT_MC_PATHS = 50_000  # Monte Carlo paths for simulation pricing


# ============================================================
# Data Classes
# ============================================================

@dataclass
class SimulatedPosition:
    """
    A simulated position in a prediction market contract.

    Tracks live prices alongside simulation engine estimates so the
    trader can see where the model disagrees with the market.
    """

    market_id: str
    token_id: str
    question: str
    outcome_label: str

    side: str  # "long" or "short"
    size: float  # Number of contracts
    entry_price: float  # Price at entry (0.00-1.00)
    current_price: float  # Latest market price

    entry_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    sim_fair_value: float = 0.0  # Fair value from simulation engine

    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0

    tracker: Any = field(default=None, repr=False)  # Optional LiveProbabilityTracker

    # Internal bookkeeping
    position_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    exchange: str = "polymarket"
    is_closed: bool = False
    close_time: Optional[datetime] = None
    close_price: Optional[float] = None

    @property
    def cost_basis(self) -> float:
        """Total cost to enter the position."""
        return self.size * self.entry_price

    @property
    def market_value(self) -> float:
        """Current market value of the position."""
        if self.is_closed:
            return 0.0
        return self.size * self.current_price

    @property
    def hold_time_hours(self) -> float:
        """Hours since position was opened."""
        end = self.close_time or datetime.now(timezone.utc)
        return (end - self.entry_time).total_seconds() / 3600.0

    @property
    def sim_edge(self) -> float:
        """Edge implied by simulation vs market price (positive = underpriced)."""
        if self.sim_fair_value > 0:
            return self.sim_fair_value - self.current_price
        return 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary for reporting."""
        return {
            "position_id": self.position_id,
            "market_id": self.market_id,
            "token_id": self.token_id,
            "question": self.question[:80],
            "outcome_label": self.outcome_label,
            "exchange": self.exchange,
            "side": self.side,
            "size": self.size,
            "entry_price": round(self.entry_price, 4),
            "current_price": round(self.current_price, 4),
            "sim_fair_value": round(self.sim_fair_value, 4),
            "sim_edge": round(self.sim_edge, 4),
            "unrealized_pnl": round(self.unrealized_pnl, 2),
            "realized_pnl": round(self.realized_pnl, 2),
            "hold_time_hours": round(self.hold_time_hours, 1),
            "is_closed": self.is_closed,
        }


@dataclass
class SimulationReport:
    """
    Performance report for the paper trading simulator.

    Includes both standard trading metrics and simulation-specific
    diagnostics (Brier score, simulation value-added).
    """

    total_pnl: float = 0.0
    win_rate: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0

    n_trades: int = 0
    avg_hold_time: float = 0.0  # Hours

    brier_score: float = 0.0  # Calibration of sim prices vs outcomes
    simulation_value_added: float = 0.0  # Return improvement from sim pricing

    # Breakdown
    n_open: int = 0
    n_closed: int = 0
    n_wins: int = 0
    n_losses: int = 0
    total_volume: float = 0.0
    best_trade_pnl: float = 0.0
    worst_trade_pnl: float = 0.0
    avg_sim_edge_at_entry: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "total_pnl": round(self.total_pnl, 2),
            "win_rate": round(self.win_rate, 4),
            "sharpe_ratio": round(self.sharpe_ratio, 4),
            "max_drawdown": round(self.max_drawdown, 4),
            "n_trades": self.n_trades,
            "n_open": self.n_open,
            "n_closed": self.n_closed,
            "n_wins": self.n_wins,
            "n_losses": self.n_losses,
            "avg_hold_time_hours": round(self.avg_hold_time, 1),
            "brier_score": round(self.brier_score, 6),
            "simulation_value_added": round(self.simulation_value_added, 4),
            "total_volume": round(self.total_volume, 2),
            "best_trade_pnl": round(self.best_trade_pnl, 2),
            "worst_trade_pnl": round(self.worst_trade_pnl, 2),
            "avg_sim_edge_at_entry": round(self.avg_sim_edge_at_entry, 4),
        }


# ============================================================
# Trade Log Entry
# ============================================================

@dataclass
class TradeLogEntry:
    """Internal record of every simulated trade for audit trail."""

    trade_id: str
    timestamp: datetime
    market_id: str
    token_id: str
    question: str
    outcome_label: str
    exchange: str
    action: str  # "buy" or "sell"
    side: str  # "long" or "short"
    size: float
    price: float
    sim_fair_value: float
    sim_edge: float
    sim_method: str
    bankroll_before: float
    bankroll_after: float
    position_id: str
    notes: str = ""


# ============================================================
# Paper Trading Simulator
# ============================================================

class PaperTradingSimulator:
    """
    Paper-trading simulation environment for prediction markets.

    Connects to live Polymarket market data (read-only,
    no authentication required) and simulates trading with virtual money.
    Uses the simulation engine (EnhancedContractPricer) for fair-value
    estimates and LiveProbabilityTracker for noise-filtered probability
    tracking on open positions.

    Features:
        - Virtual bankroll with full P&L accounting
        - Live price feeds from Polymarket Gamma/CLOB API
        - Simulation-enhanced pricing on every trade
        - Per-position particle filter probability tracking
        - Automated scan-and-execute via the orchestrator scanner
        - Full trade log with simulation diagnostics
        - Performance reporting with Brier scores and Sharpe ratio

    Thread Safety:
        This class is NOT thread-safe. Use one instance per thread/coroutine,
        or add external locking if sharing across threads.
    """

    def __init__(
        self,
        bankroll: float = 10_000.0,
        polymarket_client: Optional[PolymarketClient] = None,
        pricer: Any = None,
        mc_paths: int = DEFAULT_MC_PATHS,
        vol: float = DEFAULT_VOL,
        horizon_days: int = DEFAULT_HORIZON_DAYS,
        kelly_fraction: float = 0.25,
        max_position_pct: float = 0.10,
        seed: Optional[int] = None,
    ):
        """
        Initialize the paper trading simulator.

        Args:
            bankroll: Starting virtual capital in USD.
            polymarket_client: Client for Polymarket data. Created lazily if None.
            pricer: EnhancedContractPricer instance. Created if sim modules available.
            mc_paths: Number of Monte Carlo paths for contract pricing.
            vol: Annualized volatility assumption for simulation pricing.
            horizon_days: Default time-to-expiry for simulation pricing.
            kelly_fraction: Fractional Kelly multiplier (0.25 = quarter-Kelly).
            max_position_pct: Maximum position size as fraction of bankroll.
            seed: Random seed for reproducibility.
        """
        # Bankroll
        self.initial_bankroll = bankroll
        self.bankroll = bankroll
        self._high_watermark = bankroll

        # Clients (lazy initialization)
        self._poly_client = polymarket_client

        # Simulation engine
        self._pricer = pricer
        if self._pricer is None and EnhancedContractPricer is not None:
            try:
                self._pricer = EnhancedContractPricer(seed=seed)
            except Exception as e:
                logger.warning(f"[PAPER-SIM] Could not initialize pricer: {e}")
                self._pricer = None

        self._mc_paths = mc_paths
        self._vol = vol
        self._horizon_days = horizon_days
        self._seed = seed

        # Risk parameters
        self._kelly_fraction = kelly_fraction
        self._max_position_pct = max_position_pct

        # State
        self.positions: Dict[str, SimulatedPosition] = {}  # position_id -> position
        self.closed_positions: List[SimulatedPosition] = []
        self.trade_log: List[TradeLogEntry] = []
        self._market_cache: Dict[str, Market] = {}  # market_id/slug -> Market
        self._equity_curve: List[Tuple[datetime, float]] = [
            (datetime.now(timezone.utc), bankroll)
        ]

        # Counters
        self._total_trades = 0
        self._total_volume = 0.0

        logger.info(
            f"[PAPER-SIM] Initialized | bankroll=${bankroll:,.2f} | "
            f"pricer={'available' if self._pricer else 'unavailable'} | "
            f"mc_paths={mc_paths} | vol={vol}"
        )

    # ================================================================
    # Client Accessors (lazy init)
    # ================================================================

    @property
    def poly_client(self) -> PolymarketClient:
        """Polymarket API client, lazily initialized."""
        if self._poly_client is None:
            self._poly_client = PolymarketClient()
        return self._poly_client

    def reset(self):
        """Reset all paper trading state back to initial bankroll."""
        self.bankroll = self.initial_bankroll
        self._high_watermark = self.initial_bankroll
        self.positions.clear()
        self.closed_positions.clear()
        self.trade_log.clear()
        self._market_cache.clear()
        self._equity_curve = [(datetime.now(timezone.utc), self.initial_bankroll)]
        self._total_trades = 0
        self._total_volume = 0.0
        logger.info(f"[PAPER-SIM] Reset | bankroll=${self.initial_bankroll:,.2f}")

    # ================================================================
    # Market Data
    # ================================================================

    def _resolve_market(
        self, market_id: str, exchange: str = "polymarket"
    ) -> Optional[Market]:
        """
        Fetch and cache a market by ID or slug.

        Fetches from Polymarket by slug.
        """
        if market_id in self._market_cache:
            return self._market_cache[market_id]

        market = None
        market = self.poly_client.get_market_by_slug(market_id)
        if market is None:
            # Try as condition_id via market listing
            markets = self.poly_client.get_markets(limit=100)
            for m in markets:
                if m.id == market_id or m.condition_id == market_id:
                    market = m
                    break

        if market is not None:
            self._market_cache[market_id] = market
            # Also cache by slug and condition_id for cross-lookup
            if market.slug:
                self._market_cache[market.slug] = market
            if market.condition_id:
                self._market_cache[market.condition_id] = market

        return market

    def _get_live_price(
        self, market: Market, outcome_idx: int
    ) -> Optional[float]:
        """Fetch the latest midpoint price for an outcome."""
        if outcome_idx < 0 or outcome_idx >= len(market.outcomes):
            return None
        outcome = market.outcomes[outcome_idx]
        if not outcome.token_id:
            return outcome.price  # Fall back to cached price

        return self.poly_client.get_midpoint(outcome.token_id)

    def _get_sim_price(
        self, current_price: float, market: Optional[Market] = None
    ) -> Dict[str, Any]:
        """
        Run the simulation engine to get a fair-value estimate.

        Returns a dict with keys: sim_price, std_error, method, n_paths.
        Falls back to the market price if simulation is unavailable.
        """
        if self._pricer is None or current_price <= 0 or current_price >= 1:
            return {
                "sim_price": current_price,
                "std_error": 0.0,
                "method": "passthrough",
                "n_paths": 0,
                "variance_reduction": None,
            }

        # Compute time-to-expiry from market end_date if available
        T = self._horizon_days / 365.0
        if market and market.end_date:
            now = datetime.now(timezone.utc)
            remaining = (market.end_date - now).total_seconds()
            if remaining > 0:
                T = remaining / (365.25 * 86400)
            else:
                # Market expired, price is essentially the settlement
                T = 1.0 / 365.0  # 1-day minimum

        try:
            result = self._pricer.price_contract(
                current_prob=current_price,
                vol=self._vol,
                T=T,
                n_paths=self._mc_paths,
            )
            return {
                "sim_price": result["probability"],
                "std_error": result["std_error"],
                "method": result["method"],
                "n_paths": self._mc_paths,
                "variance_reduction": result.get("variance_reduction"),
            }
        except Exception as e:
            logger.warning(f"[PAPER-SIM] Simulation pricing failed: {e}")
            return {
                "sim_price": current_price,
                "std_error": 0.0,
                "method": "fallback",
                "n_paths": 0,
                "variance_reduction": None,
            }

    # ================================================================
    # Trading: Buy / Sell
    # ================================================================

    def buy(
        self,
        market_id: str,
        outcome_idx: int = 0,
        size: float = 10.0,
        price: Optional[float] = None,
        exchange: str = "polymarket",
    ) -> Optional[SimulatedPosition]:
        """
        Buy contracts on a prediction market outcome.

        Simulates a fill at the current midpoint (or the specified price).
        Deducts cost from the virtual bankroll, runs the simulation engine
        for a fair-value estimate, and attaches a probability tracker.

        Args:
            market_id: Market slug (Polymarket).
            outcome_idx: Index of the outcome to buy (0=Yes, 1=No for binary).
            size: Number of contracts to buy.
            price: Limit price override. If None, uses live midpoint.
            exchange: "polymarket".

        Returns:
            SimulatedPosition if trade succeeds, None otherwise.
        """
        market = self._resolve_market(market_id, exchange=exchange)
        if market is None:
            logger.error(f"[PAPER-SIM] Market not found: {market_id}")
            return None

        if outcome_idx < 0 or outcome_idx >= len(market.outcomes):
            logger.error(
                f"[PAPER-SIM] Invalid outcome_idx={outcome_idx} for market "
                f"with {len(market.outcomes)} outcomes"
            )
            return None

        outcome = market.outcomes[outcome_idx]

        # Determine fill price
        if price is not None:
            fill_price = price
        else:
            live_price = self._get_live_price(market, outcome_idx)
            fill_price = live_price if live_price is not None else outcome.price

        if fill_price <= 0 or fill_price >= 1:
            logger.error(f"[PAPER-SIM] Invalid price {fill_price} for {market_id}")
            return None

        # Check bankroll
        cost = size * fill_price
        if cost > self.bankroll:
            logger.warning(
                f"[PAPER-SIM] Insufficient bankroll: need ${cost:.2f}, "
                f"have ${self.bankroll:.2f}"
            )
            return None

        # Check position size limit
        max_cost = self.initial_bankroll * self._max_position_pct
        if cost > max_cost:
            logger.warning(
                f"[PAPER-SIM] Position too large: ${cost:.2f} > "
                f"max ${max_cost:.2f} ({self._max_position_pct:.0%} of bankroll)"
            )
            return None

        # Run simulation pricing
        sim_result = self._get_sim_price(fill_price, market)

        # Create probability tracker for the position
        tracker = None
        if LiveProbabilityTracker is not None:
            try:
                tracker = LiveProbabilityTracker(
                    prior_prob=fill_price,
                    seed=self._seed,
                )
                tracker.update(fill_price)
            except Exception as e:
                logger.debug(f"[PAPER-SIM] Tracker init failed: {e}")

        # Create position
        bankroll_before = self.bankroll
        self.bankroll -= cost

        position = SimulatedPosition(
            market_id=market.id,
            token_id=outcome.token_id,
            question=market.question,
            outcome_label=outcome.label,
            side="long",
            size=size,
            entry_price=fill_price,
            current_price=fill_price,
            sim_fair_value=sim_result["sim_price"],
            tracker=tracker,
            exchange="polymarket",
        )

        self.positions[position.position_id] = position
        self._total_trades += 1
        self._total_volume += cost

        # Log the trade
        log_entry = TradeLogEntry(
            trade_id=uuid.uuid4().hex[:12],
            timestamp=datetime.now(timezone.utc),
            market_id=market.id,
            token_id=outcome.token_id,
            question=market.question,
            outcome_label=outcome.label,
            exchange=position.exchange,
            action="buy",
            side="long",
            size=size,
            price=fill_price,
            sim_fair_value=sim_result["sim_price"],
            sim_edge=sim_result["sim_price"] - fill_price,
            sim_method=sim_result["method"],
            bankroll_before=bankroll_before,
            bankroll_after=self.bankroll,
            position_id=position.position_id,
            notes=(
                f"MC paths={sim_result['n_paths']}, "
                f"SE={sim_result['std_error']:.6f}, "
                f"VR={sim_result.get('variance_reduction', 'N/A')}"
            ),
        )
        self.trade_log.append(log_entry)

        logger.info(
            f"[PAPER-SIM] BUY {size:.1f} contracts @ ${fill_price:.4f} | "
            f"cost=${cost:.2f} | sim_fv={sim_result['sim_price']:.4f} "
            f"({sim_result['method']}) | "
            f"bankroll=${self.bankroll:,.2f} | {market.question[:50]}"
        )

        return position

    def sell(
        self,
        market_id: str,
        outcome_idx: int = 0,
        size: Optional[float] = None,
        price: Optional[float] = None,
        position_id: Optional[str] = None,
        exchange: str = "polymarket",
    ) -> Optional[float]:
        """
        Sell (close) contracts on a prediction market outcome.

        If position_id is provided, closes that specific position.
        Otherwise, finds a matching open position by market_id and outcome_idx.

        Args:
            market_id: Market slug or ticker.
            outcome_idx: Index of the outcome to sell.
            size: Number of contracts to sell. None = sell entire position.
            price: Limit price override. None = use live midpoint.
            position_id: Specific position to close.
            exchange: "polymarket".

        Returns:
            Realized P&L from the sale, or None if no matching position found.
        """
        # Find the position to close
        target_pos = None

        if position_id and position_id in self.positions:
            target_pos = self.positions[position_id]
        else:
            market = self._resolve_market(market_id, exchange=exchange)
            if market is None:
                logger.error(f"[PAPER-SIM] Market not found: {market_id}")
                return None

            outcome = market.outcomes[outcome_idx] if outcome_idx < len(market.outcomes) else None
            if outcome is None:
                logger.error(f"[PAPER-SIM] Invalid outcome_idx={outcome_idx}")
                return None

            # Find matching open position
            for pos in self.positions.values():
                if (
                    pos.market_id == market.id
                    and pos.token_id == outcome.token_id
                    and pos.side == "long"
                    and not pos.is_closed
                ):
                    target_pos = pos
                    break

        if target_pos is None:
            logger.warning(f"[PAPER-SIM] No open position found for {market_id}")
            return None

        # Determine sell size
        sell_size = size if size is not None else target_pos.size
        sell_size = min(sell_size, target_pos.size)

        # Determine sell price
        if price is not None:
            sell_price = price
        else:
            market = self._resolve_market(target_pos.market_id, exchange=target_pos.exchange)
            if market is not None:
                # Find the outcome index for this position
                oidx = None
                for i, o in enumerate(market.outcomes):
                    if o.token_id == target_pos.token_id:
                        oidx = i
                        break
                if oidx is not None:
                    live = self._get_live_price(market, oidx)
                    sell_price = live if live is not None else target_pos.current_price
                else:
                    sell_price = target_pos.current_price
            else:
                sell_price = target_pos.current_price

        # Calculate P&L
        pnl = (sell_price - target_pos.entry_price) * sell_size
        proceeds = sell_size * sell_price

        # Update bankroll
        bankroll_before = self.bankroll
        self.bankroll += proceeds

        # Run sim pricing for the trade log
        sim_result = self._get_sim_price(sell_price)

        # Update or close the position
        if sell_size >= target_pos.size:
            # Full close
            target_pos.realized_pnl += pnl
            target_pos.unrealized_pnl = 0.0
            target_pos.is_closed = True
            target_pos.close_time = datetime.now(timezone.utc)
            target_pos.close_price = sell_price

            self.closed_positions.append(target_pos)
            del self.positions[target_pos.position_id]
        else:
            # Partial close
            target_pos.realized_pnl += pnl
            target_pos.size -= sell_size

        self._total_trades += 1
        self._total_volume += proceeds

        # Log the trade
        log_entry = TradeLogEntry(
            trade_id=uuid.uuid4().hex[:12],
            timestamp=datetime.now(timezone.utc),
            market_id=target_pos.market_id,
            token_id=target_pos.token_id,
            question=target_pos.question,
            outcome_label=target_pos.outcome_label,
            exchange=target_pos.exchange,
            action="sell",
            side="long",
            size=sell_size,
            price=sell_price,
            sim_fair_value=sim_result["sim_price"],
            sim_edge=sim_result["sim_price"] - sell_price,
            sim_method=sim_result["method"],
            bankroll_before=bankroll_before,
            bankroll_after=self.bankroll,
            position_id=target_pos.position_id,
            notes=f"realized_pnl=${pnl:+.2f}",
        )
        self.trade_log.append(log_entry)

        logger.info(
            f"[PAPER-SIM] SELL {sell_size:.1f} contracts @ ${sell_price:.4f} | "
            f"P&L=${pnl:+.2f} | bankroll=${self.bankroll:,.2f} | "
            f"{target_pos.question[:50]}"
        )

        return pnl

    # ================================================================
    # Price Refresh & Mark-to-Market
    # ================================================================

    def refresh_prices(self) -> int:
        """
        Pull latest prices from Polymarket API for all open positions.

        Returns the number of positions successfully updated.
        """
        updated = 0
        for pos in self.positions.values():
            if pos.is_closed:
                continue

            market = self._resolve_market(pos.market_id, exchange=pos.exchange)
            if market is None:
                continue

            # Find the outcome index for this token
            for i, outcome in enumerate(market.outcomes):
                if outcome.token_id == pos.token_id:
                    live_price = self._get_live_price(market, i)
                    if live_price is not None and live_price > 0:
                        pos.current_price = live_price
                        updated += 1
                    break

        if updated > 0:
            logger.info(f"[PAPER-SIM] Refreshed prices for {updated} positions")
        return updated

    def mark_to_market(self) -> Dict[str, Any]:
        """
        Update all open positions with live prices and simulation estimates.

        For each position:
        1. Updates current_price from the exchange
        2. Runs the simulation engine for a fresh fair-value estimate
        3. Updates the particle filter probability tracker
        4. Computes unrealized P&L

        Returns a summary of the mark-to-market results.
        """
        self.refresh_prices()

        total_unrealized = 0.0
        total_sim_divergence = 0.0
        n_divergent = 0

        for pos in self.positions.values():
            if pos.is_closed:
                continue

            # Compute unrealized P&L
            if pos.side == "long":
                pos.unrealized_pnl = (pos.current_price - pos.entry_price) * pos.size
            else:
                pos.unrealized_pnl = (pos.entry_price - pos.current_price) * pos.size

            total_unrealized += pos.unrealized_pnl

            # Update simulation fair value
            market = self._market_cache.get(pos.market_id)
            sim_result = self._get_sim_price(pos.current_price, market)
            pos.sim_fair_value = sim_result["sim_price"]

            # Update probability tracker
            if pos.tracker is not None and pos.current_price > 0:
                try:
                    pos.tracker.update(pos.current_price)
                except Exception:
                    pass

            # Track divergence
            divergence = abs(pos.sim_fair_value - pos.current_price)
            if divergence > 0.02:
                n_divergent += 1
                total_sim_divergence += divergence

        # Update equity curve and high watermark
        total_value = self._compute_total_value()
        self._equity_curve.append((datetime.now(timezone.utc), total_value))
        if total_value > self._high_watermark:
            self._high_watermark = total_value

        summary = {
            "total_value": round(total_value, 2),
            "bankroll": round(self.bankroll, 2),
            "positions_value": round(total_value - self.bankroll, 2),
            "unrealized_pnl": round(total_unrealized, 2),
            "n_positions": len(self.positions),
            "n_sim_divergent": n_divergent,
            "avg_sim_divergence": (
                round(total_sim_divergence / n_divergent, 4) if n_divergent > 0 else 0.0
            ),
            "high_watermark": round(self._high_watermark, 2),
            "drawdown": round(self._compute_drawdown(), 4),
        }

        logger.info(
            f"[PAPER-SIM] MTM: value=${total_value:,.2f} | "
            f"unrealized=${total_unrealized:+,.2f} | "
            f"{len(self.positions)} positions | "
            f"{n_divergent} sim-divergent"
        )

        return summary

    # ================================================================
    # Portfolio & Reporting
    # ================================================================

    def get_portfolio(self) -> Dict[str, Any]:
        """
        Get the current portfolio state.

        Returns a dict with bankroll, positions, aggregate P&L,
        and simulation diagnostics.
        """
        total_value = self._compute_total_value()
        total_unrealized = sum(p.unrealized_pnl for p in self.positions.values())
        total_realized = sum(p.realized_pnl for p in self.closed_positions)
        total_realized += sum(p.realized_pnl for p in self.positions.values())

        positions_list = sorted(
            [p.to_dict() for p in self.positions.values()],
            key=lambda x: abs(x["unrealized_pnl"]),
            reverse=True,
        )

        # Simulation diagnostics
        sim_diagnostics = {}
        for pos in self.positions.values():
            if pos.tracker is not None:
                try:
                    divergence = pos.tracker.divergence_from_market()
                    sim_diagnostics[pos.position_id] = {
                        "filtered_prob": round(pos.tracker.estimate(), 4),
                        "market_price": round(pos.current_price, 4),
                        "divergence": round(divergence, 4) if divergence else 0.0,
                        "sim_fair_value": round(pos.sim_fair_value, 4),
                    }
                except Exception:
                    pass

        return {
            "bankroll": round(self.bankroll, 2),
            "initial_bankroll": round(self.initial_bankroll, 2),
            "total_value": round(total_value, 2),
            "total_pnl": round(total_value - self.initial_bankroll, 2),
            "return_pct": round(
                (total_value - self.initial_bankroll) / self.initial_bankroll, 4
            ),
            "unrealized_pnl": round(total_unrealized, 2),
            "realized_pnl": round(total_realized, 2),
            "n_open_positions": len(self.positions),
            "n_closed_positions": len(self.closed_positions),
            "total_trades": self._total_trades,
            "total_volume": round(self._total_volume, 2),
            "high_watermark": round(self._high_watermark, 2),
            "drawdown": round(self._compute_drawdown(), 4),
            "positions": positions_list,
            "simulation_diagnostics": sim_diagnostics,
            "pricer_available": self._pricer is not None,
        }

    def get_report(self) -> SimulationReport:
        """
        Generate a comprehensive performance report.

        Computes standard trading metrics (Sharpe, drawdown, win rate)
        plus simulation-specific metrics (Brier score, simulation value-added).
        """
        all_positions = list(self.positions.values()) + self.closed_positions
        closed = [p for p in all_positions if p.is_closed]

        report = SimulationReport()
        report.n_trades = self._total_trades
        report.n_open = len(self.positions)
        report.n_closed = len(closed)
        report.total_volume = self._total_volume

        # P&L
        total_value = self._compute_total_value()
        report.total_pnl = total_value - self.initial_bankroll

        # Win/loss counts from closed positions
        pnl_values = []
        hold_times = []
        sim_edges_at_entry = []

        for pos in closed:
            trade_pnl = pos.realized_pnl
            pnl_values.append(trade_pnl)

            if trade_pnl > 0:
                report.n_wins += 1
            elif trade_pnl < 0:
                report.n_losses += 1

            hold_times.append(pos.hold_time_hours)
            sim_edges_at_entry.append(pos.sim_fair_value - pos.entry_price)

        if report.n_wins + report.n_losses > 0:
            report.win_rate = report.n_wins / (report.n_wins + report.n_losses)

        if hold_times:
            report.avg_hold_time = sum(hold_times) / len(hold_times)

        if pnl_values:
            report.best_trade_pnl = max(pnl_values)
            report.worst_trade_pnl = min(pnl_values)

        if sim_edges_at_entry:
            report.avg_sim_edge_at_entry = sum(sim_edges_at_entry) / len(sim_edges_at_entry)

        # Sharpe ratio from equity curve
        report.sharpe_ratio = self._compute_sharpe()

        # Max drawdown
        report.max_drawdown = self._compute_max_drawdown()

        # Brier score: measures calibration of sim fair values vs outcomes
        report.brier_score = self._compute_brier_score()

        # Simulation value-added: difference in returns between
        # sim-informed trades and naive (market-price) Kelly returns
        report.simulation_value_added = self._compute_sim_value_added()

        return report

    # ================================================================
    # Automated Scanning
    # ================================================================

    def run_scan_cycle(self, scanner: Any) -> Dict[str, Any]:
        """
        Run one automated scan-and-execute cycle.

        Uses the provided PredictionMarketScanner to find opportunities,
        then executes paper trades based on Kelly sizing.

        Args:
            scanner: A PredictionMarketScanner instance.

        Returns:
            Summary dict with opportunities found and trades executed.
        """
        if scanner is None:
            return {"error": "No scanner provided"}

        logger.info("[PAPER-SIM] Starting scan cycle...")

        # Scan for opportunities
        try:
            opportunities = scanner.scan(market_limit=200)
        except Exception as e:
            logger.error(f"[PAPER-SIM] Scan failed: {e}")
            return {"error": str(e), "opportunities": 0, "executed": 0}

        if not opportunities:
            return {"opportunities": 0, "executed": 0, "skipped": 0}

        executed = []
        skipped = []

        for opp in opportunities:
            # Kelly sizing
            bet_usd, num_contracts = self._compute_kelly_size(opp)

            if num_contracts <= 0:
                skipped.append({
                    "market": opp.market.question[:60],
                    "reason": "Kelly size = 0",
                    "edge": round(opp.edge, 4),
                })
                continue

            # Determine exchange
            exchange = (
                "polymarket"
            )

            # Execute paper trade
            position = self.buy(
                market_id=opp.market.slug or opp.market.id,
                outcome_idx=opp.outcome_idx,
                size=num_contracts,
                price=opp.entry_price,
                exchange=exchange,
            )

            if position is not None:
                executed.append({
                    "position_id": position.position_id,
                    "market": opp.market.question[:60],
                    "strategy": opp.strategy,
                    "side": opp.side,
                    "size": num_contracts,
                    "price": opp.entry_price,
                    "edge": round(opp.edge, 4),
                    "sim_fair_value": round(position.sim_fair_value, 4),
                    "kelly_bet_usd": round(bet_usd, 2),
                })
            else:
                skipped.append({
                    "market": opp.market.question[:60],
                    "reason": "Buy rejected",
                    "edge": round(opp.edge, 4),
                })

        summary = {
            "opportunities": len(opportunities),
            "executed": len(executed),
            "skipped": len(skipped),
            "bankroll": round(self.bankroll, 2),
            "executions": executed[:20],
            "skip_reasons": skipped[:10],
        }

        logger.info(
            f"[PAPER-SIM] Scan cycle complete: {len(opportunities)} opps -> "
            f"{len(executed)} executed, {len(skipped)} skipped"
        )

        return summary

    # ================================================================
    # Simulation Analysis
    # ================================================================

    def simulate_contract(
        self,
        market_id: str,
        outcome_idx: int = 0,
        exchange: str = "polymarket",
        n_paths: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Run a full simulation analysis on a specific contract.

        Fetches the live price, runs Monte Carlo pricing, and returns
        a comprehensive analysis including fair value, confidence intervals,
        edge estimate, and recommended Kelly size.

        Args:
            market_id: Market slug (Polymarket).
            outcome_idx: Which outcome to analyze (0=Yes, 1=No for binary).
            exchange: "polymarket".
            n_paths: Override number of MC paths.

        Returns:
            Dict with full simulation analysis results.
        """
        market = self._resolve_market(market_id, exchange=exchange)
        if market is None:
            return {"error": f"Market not found: {market_id}"}

        if outcome_idx < 0 or outcome_idx >= len(market.outcomes):
            return {"error": f"Invalid outcome_idx={outcome_idx}"}

        outcome = market.outcomes[outcome_idx]
        live_price = self._get_live_price(market, outcome_idx)
        market_price = live_price if live_price is not None else outcome.price

        # Run simulation pricing
        paths = n_paths or self._mc_paths
        old_paths = self._mc_paths
        self._mc_paths = paths
        sim_result = self._get_sim_price(market_price, market)
        self._mc_paths = old_paths

        sim_price = sim_result["sim_price"]
        edge = sim_price - market_price

        # Time to expiry
        T = self._horizon_days / 365.0
        if market.end_date:
            now = datetime.now(timezone.utc)
            remaining = (market.end_date - now).total_seconds()
            if remaining > 0:
                T = remaining / (365.25 * 86400)

        # Kelly sizing recommendation
        kelly_bet = 0.0
        kelly_frac = 0.0
        if edge > 0.02 and KellyConfig is not None and kelly_size is not None:
            config = KellyConfig(fractional_kelly=self._kelly_fraction)
            kelly_bet = kelly_size(
                edge=edge,
                confidence=min(0.9, 0.5 + edge * 5),  # Heuristic confidence
                win_probability=sim_price,
                bankroll=self.bankroll,
                config=config,
            )
            kelly_frac = kelly_bet / self.bankroll if self.bankroll > 0 else 0.0

        analysis = {
            "market_id": market.id,
            "question": market.question,
            "outcome": outcome.label,
            "exchange": exchange,
            "market_price": round(market_price, 4),
            "sim_price": round(sim_price, 4),
            "std_error": round(sim_result["std_error"], 6),
            "ci_95": (
                round(sim_price - 1.96 * sim_result["std_error"], 4),
                round(sim_price + 1.96 * sim_result["std_error"], 4),
            ),
            "edge": round(edge, 4),
            "edge_pct": f"{edge:.2%}",
            "method": sim_result["method"],
            "n_paths": paths,
            "variance_reduction": sim_result.get("variance_reduction"),
            "time_to_expiry_days": round(T * 365, 1),
            "vol_assumption": self._vol,
            "kelly_bet_usd": round(kelly_bet, 2),
            "kelly_fraction": round(kelly_frac, 4),
            "signal": (
                "STRONG_BUY" if edge > 0.05
                else "BUY" if edge > 0.02
                else "SELL" if edge < -0.05
                else "WEAK_SELL" if edge < -0.02
                else "HOLD"
            ),
            "total_volume": market.total_volume,
            "liquidity": market.liquidity,
        }

        logger.info(
            f"[PAPER-SIM] Contract analysis: {market.question[:50]} | "
            f"market={market_price:.4f} sim={sim_price:.4f} "
            f"edge={edge:+.4f} signal={analysis['signal']}"
        )

        return analysis

    # ================================================================
    # Internal Helpers
    # ================================================================

    def _compute_total_value(self) -> float:
        """Total portfolio value = cash + positions market value."""
        positions_value = sum(
            p.size * p.current_price
            for p in self.positions.values()
            if not p.is_closed
        )
        return self.bankroll + positions_value

    def _compute_drawdown(self) -> float:
        """Current drawdown from high watermark."""
        total_value = self._compute_total_value()
        if self._high_watermark <= 0:
            return 0.0
        return (self._high_watermark - total_value) / self._high_watermark

    def _compute_max_drawdown(self) -> float:
        """Maximum drawdown from the equity curve."""
        if len(self._equity_curve) < 2:
            return 0.0

        values = [v for _, v in self._equity_curve]
        peak = values[0]
        max_dd = 0.0

        for v in values:
            if v > peak:
                peak = v
            dd = (peak - v) / peak if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd

        return max_dd

    def _compute_sharpe(self, risk_free_rate: float = 0.05) -> float:
        """
        Compute annualized Sharpe ratio from the equity curve.

        Uses daily returns derived from the equity snapshots.
        """
        if len(self._equity_curve) < 3:
            return 0.0

        values = [v for _, v in self._equity_curve]
        returns = []
        for i in range(1, len(values)):
            if values[i - 1] > 0:
                returns.append(values[i] / values[i - 1] - 1.0)

        if not returns or len(returns) < 2:
            return 0.0

        arr = np.array(returns)
        mean_ret = float(np.mean(arr))
        std_ret = float(np.std(arr, ddof=1))

        if std_ret < 1e-10:
            return 0.0

        # Annualize (assume ~252 trading days worth of snapshots)
        # Scale factor depends on how frequently mark_to_market is called
        n_snapshots = len(returns)
        if n_snapshots > 0:
            time_span = (
                self._equity_curve[-1][0] - self._equity_curve[0][0]
            ).total_seconds()
            if time_span > 0:
                periods_per_year = n_snapshots / (time_span / (365.25 * 86400))
            else:
                periods_per_year = 252.0
        else:
            periods_per_year = 252.0

        annualized_return = mean_ret * periods_per_year
        annualized_vol = std_ret * math.sqrt(periods_per_year)

        return (annualized_return - risk_free_rate) / annualized_vol if annualized_vol > 0 else 0.0

    def _compute_brier_score(self) -> float:
        """
        Compute Brier score for simulation fair-value estimates vs outcomes.

        Only meaningful for closed positions where we know the outcome.
        Lower is better (0 = perfect calibration).
        """
        if not self.closed_positions:
            return 0.0

        brier_sum = 0.0
        n = 0

        for pos in self.closed_positions:
            if pos.close_price is None or pos.sim_fair_value <= 0:
                continue

            # Infer the outcome: if close_price >= 0.5, outcome was likely YES
            # This is a proxy; real Brier needs the binary resolution
            outcome = 1.0 if pos.close_price >= 0.90 else 0.0
            forecast = pos.sim_fair_value

            brier_sum += (forecast - outcome) ** 2
            n += 1

        return brier_sum / n if n > 0 else 0.0

    def _compute_sim_value_added(self) -> float:
        """
        Compute the value added by simulation-informed trading.

        Measures the difference between:
        - Actual returns (trading with sim fair values)
        - Hypothetical returns if we had ignored simulation and used market prices

        A positive value means the simulation engine improved our returns.
        """
        if not self.closed_positions:
            return 0.0

        sim_pnl = 0.0
        naive_pnl = 0.0

        for pos in self.closed_positions:
            if pos.close_price is None:
                continue

            # Actual P&L
            sim_pnl += pos.realized_pnl

            # Naive P&L: what if we had sized without simulation?
            # The sim edge might have made us trade (or skip) differently,
            # so we approximate by looking at edge contribution
            sim_edge = pos.sim_fair_value - pos.entry_price
            if sim_edge > 0.02:
                # Sim said buy -- actual trade happened
                naive_pnl += (pos.close_price - pos.entry_price) * pos.size * 0.5
            else:
                # Sim might not have recommended this trade
                naive_pnl += pos.realized_pnl

        return sim_pnl - naive_pnl

    def _compute_kelly_size(self, opp: ScanResult) -> Tuple[float, float]:
        """
        Compute Kelly-optimal position size for a scan opportunity.

        Uses the simulation engine when available to refine the
        probability estimate before sizing.

        Returns:
            (bet_usd, num_contracts)
        """
        if size_from_scan_result is not None and KellyConfig is not None:
            config = KellyConfig(
                fractional_kelly=self._kelly_fraction,
                max_bet_usd=self.initial_bankroll * self._max_position_pct,
                max_kelly_fraction=self._max_position_pct,
            )
            try:
                return size_from_scan_result(opp, self.bankroll, config)
            except Exception as e:
                logger.debug(f"[PAPER-SIM] Kelly sizing via orchestrator failed: {e}")

        # Fallback: simple proportional sizing
        if opp.edge <= 0.02 or opp.confidence < 0.5:
            return 0.0, 0.0

        bet_pct = min(opp.edge * self._kelly_fraction, self._max_position_pct)
        bet_usd = bet_pct * self.bankroll
        bet_usd = max(1.0, min(bet_usd, self.initial_bankroll * self._max_position_pct))

        price = opp.entry_price if opp.entry_price > 0 else 0.50
        num_contracts = bet_usd / price

        return bet_usd, round(num_contracts, 1)

    # ================================================================
    # Convenience
    # ================================================================

    def reset(self, bankroll: Optional[float] = None):
        """
        Reset the simulator to initial state.

        Clears all positions, trade logs, and equity curve.
        Optionally sets a new starting bankroll.
        """
        self.bankroll = bankroll if bankroll is not None else self.initial_bankroll
        self.initial_bankroll = self.bankroll
        self._high_watermark = self.bankroll

        self.positions.clear()
        self.closed_positions.clear()
        self.trade_log.clear()
        self._market_cache.clear()
        self._equity_curve = [(datetime.now(timezone.utc), self.bankroll)]
        self._total_trades = 0
        self._total_volume = 0.0

        logger.info(f"[PAPER-SIM] Reset | bankroll=${self.bankroll:,.2f}")

    def get_trade_log(self, last_n: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Get the trade log as a list of dicts.

        Args:
            last_n: Return only the most recent N trades. None = all.
        """
        entries = self.trade_log if last_n is None else self.trade_log[-last_n:]
        return [
            {
                "trade_id": e.trade_id,
                "timestamp": e.timestamp.isoformat(),
                "action": e.action,
                "market_id": e.market_id,
                "outcome": e.outcome_label,
                "exchange": e.exchange,
                "size": e.size,
                "price": round(e.price, 4),
                "sim_fair_value": round(e.sim_fair_value, 4),
                "sim_edge": round(e.sim_edge, 4),
                "sim_method": e.sim_method,
                "bankroll_after": round(e.bankroll_after, 2),
                "notes": e.notes,
            }
            for e in entries
        ]

    def get_equity_curve(self) -> List[Dict[str, Any]]:
        """Get the equity curve as a list of {timestamp, value} dicts."""
        return [
            {"timestamp": ts.isoformat(), "value": round(val, 2)}
            for ts, val in self._equity_curve
        ]

    def __repr__(self) -> str:
        total_value = self._compute_total_value()
        pnl = total_value - self.initial_bankroll
        return (
            f"PaperTradingSimulator("
            f"value=${total_value:,.2f}, "
            f"pnl=${pnl:+,.2f}, "
            f"positions={len(self.positions)}, "
            f"trades={self._total_trades}, "
            f"pricer={'yes' if self._pricer else 'no'}"
            f")"
        )
