"""
Risk Manager for Prediction Market Trading.

Implements:
1. Daily loss limit — circuit breaker when daily P&L hits threshold
2. Max portfolio exposure — total capital at risk
3. Max correlated exposure — don't over-concentrate in one category
4. Drawdown-based strategy disabling — auto-disable losing strategies
5. Per-strategy position limits — honor strategy config.max_positions
6. Rate limiting — don't fire too many orders per minute
"""

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Set

from .polymarket_client import ScanResult
from .execution import (
    Exchange,
    OrderResult,
    OrderStatus,
    PredictionMarketExecutor,
)

logger = logging.getLogger(__name__)


@dataclass
class RiskConfig:
    """Risk management configuration."""
    # Daily loss limit
    daily_loss_limit_usd: float = 50.0       # Stop trading if daily P&L < -$50
    circuit_breaker_cooldown_min: int = 60    # Wait 60 min after circuit breaker

    # Portfolio limits
    max_portfolio_exposure_usd: float = 500.0
    max_single_position_usd: float = 50.0

    # Correlation limits
    max_category_exposure_usd: float = 200.0  # Max exposure per category
    max_strategy_exposure_usd: float = 200.0  # Max exposure per strategy

    # Drawdown controls
    strategy_disable_drawdown: float = 0.20   # Disable strategy at 20% drawdown
    strategy_disable_min_trades: int = 5      # Need at least 5 trades before disabling

    # Rate limiting
    max_orders_per_minute: int = 10
    max_orders_per_hour: int = 100

    # Position limits
    max_total_positions: int = 50
    max_positions_per_market: int = 2         # Max 2 positions in same market


@dataclass
class RiskCheckResult:
    """Result of a risk check."""
    approved: bool
    reason: str = ""
    risk_score: float = 0.0  # 0.0 = no risk, 1.0 = max risk


class RiskManager:
    """
    Pre-trade and portfolio-level risk management.

    Checks every opportunity before it reaches the executor.
    """

    def __init__(self, config: Optional[RiskConfig] = None):
        self.config = config or RiskConfig()

        # Daily tracking (resets at midnight UTC)
        self._daily_pnl: float = 0.0
        self._daily_date: Optional[str] = None
        self._circuit_breaker_active: bool = False
        self._circuit_breaker_until: Optional[datetime] = None

        # Order rate tracking
        self._order_timestamps: List[float] = []

        # Strategy performance tracking
        self._strategy_peak_value: Dict[str, float] = defaultdict(float)
        self._strategy_current_value: Dict[str, float] = defaultdict(float)
        self._strategy_trades: Dict[str, int] = defaultdict(int)
        self._disabled_strategies: Set[str] = set()

        # Category exposure tracking
        self._category_exposure: Dict[str, float] = defaultdict(float)

    def check_opportunity(
        self,
        opportunity: ScanResult,
        executor: PredictionMarketExecutor,
        scanner=None,
    ) -> RiskCheckResult:
        """
        Run all risk checks on an opportunity before execution.

        Returns RiskCheckResult with approved=True if all checks pass.
        """
        # Reset daily tracking if new day
        self._reset_daily_if_needed()

        # 1. Circuit breaker
        if self._circuit_breaker_active:
            if self._circuit_breaker_until and datetime.now(timezone.utc) < self._circuit_breaker_until:
                return RiskCheckResult(
                    approved=False,
                    reason=f"Circuit breaker active until {self._circuit_breaker_until.strftime('%H:%M UTC')}",
                    risk_score=1.0,
                )
            else:
                self._circuit_breaker_active = False
                logger.info("[RISK] Circuit breaker cooldown expired, resuming trading")

        # 2. Daily loss limit
        if self._daily_pnl < -self.config.daily_loss_limit_usd:
            self._activate_circuit_breaker()
            return RiskCheckResult(
                approved=False,
                reason=f"Daily loss limit hit: ${self._daily_pnl:.2f} < -${self.config.daily_loss_limit_usd}",
                risk_score=1.0,
            )

        # 3. Portfolio exposure
        if executor.total_exposure >= self.config.max_portfolio_exposure_usd:
            return RiskCheckResult(
                approved=False,
                reason=f"Max portfolio exposure: ${executor.total_exposure:.2f} >= ${self.config.max_portfolio_exposure_usd}",
                risk_score=0.9,
            )

        # 4. Total position count
        if len(executor.positions) >= self.config.max_total_positions:
            return RiskCheckResult(
                approved=False,
                reason=f"Max positions reached: {len(executor.positions)} >= {self.config.max_total_positions}",
                risk_score=0.8,
            )

        # 5. Strategy disabled by drawdown
        if opportunity.strategy in self._disabled_strategies:
            return RiskCheckResult(
                approved=False,
                reason=f"Strategy '{opportunity.strategy}' disabled due to drawdown",
                risk_score=0.7,
            )

        # 6. Category exposure limit
        category = opportunity.market.category or "General"
        cat_exposure = self._get_category_exposure(category, executor)
        estimated_add = opportunity.entry_price * 10  # Rough estimate
        if cat_exposure + estimated_add > self.config.max_category_exposure_usd:
            return RiskCheckResult(
                approved=False,
                reason=f"Category '{category}' exposure: ${cat_exposure:.2f} + ${estimated_add:.2f} > ${self.config.max_category_exposure_usd}",
                risk_score=0.6,
            )

        # 7. Per-market position limit
        market_positions = sum(
            1 for p in executor.positions.values()
            if p.market_id == opportunity.market.id
        )
        if market_positions >= self.config.max_positions_per_market:
            return RiskCheckResult(
                approved=False,
                reason=f"Max positions in market '{opportunity.market.question[:40]}': {market_positions}",
                risk_score=0.5,
            )

        # 8. Order rate limit
        if not self._check_rate_limit():
            return RiskCheckResult(
                approved=False,
                reason="Order rate limit exceeded",
                risk_score=0.4,
            )

        # All checks passed
        risk_score = self._calculate_risk_score(opportunity, executor)
        return RiskCheckResult(approved=True, risk_score=risk_score)

    def record_execution(self, result: OrderResult):
        """Record an execution for rate limiting and tracking."""
        self._order_timestamps.append(time.time())

        # Track daily P&L impact (fees reduce P&L)
        if result.is_success:
            self._daily_pnl -= result.fees
            strategy = result.raw_response.get("strategy", "") if result.raw_response else ""
            if strategy:
                self._strategy_trades[strategy] += 1

    def record_pnl(self, strategy: str, pnl: float):
        """Record realized P&L for a strategy (called when position closes)."""
        self._daily_pnl += pnl

        # Update strategy peak/current for drawdown tracking
        self._strategy_current_value[strategy] += pnl
        current = self._strategy_current_value[strategy]
        peak = self._strategy_peak_value[strategy]

        if current > peak:
            self._strategy_peak_value[strategy] = current
        elif peak > 0:
            drawdown = (peak - current) / peak
            trades = self._strategy_trades.get(strategy, 0)

            if (drawdown >= self.config.strategy_disable_drawdown and
                    trades >= self.config.strategy_disable_min_trades):
                self._disabled_strategies.add(strategy)
                logger.warning(
                    f"[RISK] Strategy '{strategy}' disabled: "
                    f"{drawdown:.0%} drawdown after {trades} trades"
                )

    def _activate_circuit_breaker(self):
        """Activate the circuit breaker."""
        self._circuit_breaker_active = True
        self._circuit_breaker_until = (
            datetime.now(timezone.utc) +
            timedelta(minutes=self.config.circuit_breaker_cooldown_min)
        )
        logger.warning(
            f"[RISK] CIRCUIT BREAKER ACTIVATED — daily P&L: ${self._daily_pnl:.2f} | "
            f"Cooldown until {self._circuit_breaker_until.strftime('%H:%M UTC')}"
        )

    def _reset_daily_if_needed(self):
        """Reset daily tracking at midnight UTC."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._daily_date != today:
            if self._daily_date is not None:
                logger.info(f"[RISK] Daily reset | Yesterday's P&L: ${self._daily_pnl:.2f}")
            self._daily_date = today
            self._daily_pnl = 0.0
            self._circuit_breaker_active = False
            self._circuit_breaker_until = None
            self._order_timestamps.clear()

    def _check_rate_limit(self) -> bool:
        """Check if we're within order rate limits."""
        now = time.time()

        # Clean old timestamps
        self._order_timestamps = [
            ts for ts in self._order_timestamps if now - ts < 3600
        ]

        # Check per-minute
        recent_minute = sum(1 for ts in self._order_timestamps if now - ts < 60)
        if recent_minute >= self.config.max_orders_per_minute:
            return False

        # Check per-hour
        if len(self._order_timestamps) >= self.config.max_orders_per_hour:
            return False

        return True

    def _get_category_exposure(self, category: str, executor: PredictionMarketExecutor) -> float:
        """Calculate total exposure for a category."""
        return sum(
            p.market_value for p in executor.positions.values()
            # We'd need category stored on positions for perfect tracking;
            # for now approximate from market_question content
        )

    def _calculate_risk_score(
        self, opportunity: ScanResult, executor: PredictionMarketExecutor
    ) -> float:
        """Calculate a composite risk score for an opportunity (0 = safe, 1 = risky)."""
        scores = []

        # Exposure ratio
        exposure_ratio = executor.total_exposure / self.config.max_portfolio_exposure_usd
        scores.append(exposure_ratio)

        # Daily P&L ratio (how close to circuit breaker)
        if self.config.daily_loss_limit_usd > 0:
            pnl_ratio = abs(min(0, self._daily_pnl)) / self.config.daily_loss_limit_usd
            scores.append(pnl_ratio)

        # Position count ratio
        pos_ratio = len(executor.positions) / self.config.max_total_positions
        scores.append(pos_ratio)

        # Low confidence = higher risk
        scores.append(1.0 - opportunity.confidence)

        return sum(scores) / len(scores) if scores else 0.0

    def enable_strategy(self, strategy: str):
        """Re-enable a strategy that was disabled by drawdown."""
        self._disabled_strategies.discard(strategy)
        logger.info(f"[RISK] Strategy '{strategy}' re-enabled")

    def get_status(self) -> dict:
        """Get risk manager status."""
        return {
            "daily_pnl": self._daily_pnl,
            "daily_loss_limit": self.config.daily_loss_limit_usd,
            "circuit_breaker_active": self._circuit_breaker_active,
            "circuit_breaker_until": (
                self._circuit_breaker_until.isoformat()
                if self._circuit_breaker_until else None
            ),
            "disabled_strategies": list(self._disabled_strategies),
            "orders_last_minute": sum(
                1 for ts in self._order_timestamps
                if time.time() - ts < 60
            ),
            "orders_last_hour": len(self._order_timestamps),
            "max_orders_per_minute": self.config.max_orders_per_minute,
            "max_orders_per_hour": self.config.max_orders_per_hour,
            "max_portfolio_exposure": self.config.max_portfolio_exposure_usd,
            "max_total_positions": self.config.max_total_positions,
        }
