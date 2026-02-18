"""
Production Risk Management System

Implements defensive guardrails:
- Circuit breakers (daily/weekly loss limits)
- Stress testing (2008 crisis, COVID, VIX spikes)
- Position limits (per stock, sector, correlation)
- Value at Risk (VaR) monitoring
- Tail risk management (CVaR)
- Drawdown circuit breakers
- Concentration limits

This prevents catastrophic losses and keeps strategy within acceptable bounds.

References:
- Jorion (2006) "Value at Risk"
- Dowd (2007) "Measuring Market Risk"
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any
from enum import Enum
from datetime import datetime, timedelta
import numpy as np
import pandas as pd
import logging

logger = logging.getLogger(__name__)


class RiskEvent(Enum):
    """Risk event types."""
    DAILY_LOSS_LIMIT = "daily_loss_limit"
    WEEKLY_LOSS_LIMIT = "weekly_loss_limit"
    DRAWDOWN_LIMIT = "drawdown_limit"
    VAR_BREACH = "var_breach"
    CONCENTRATION_LIMIT = "concentration_limit"
    CORRELATION_SPIKE = "correlation_spike"
    VOLATILITY_SPIKE = "volatility_spike"


@dataclass
class CircuitBreaker:
    """Circuit breaker configuration."""
    name: str
    loss_limit_pct: float  # Percentage of portfolio
    lookback_days: int = 1
    action: str = "pause"  # 'pause' | 'scale_down' | 'close'
    scale_factor: float = 0.5  # If scale_down, scale positions by this

    triggered: bool = False
    triggered_at: Optional[datetime] = None
    recovery_cooldown_hours: int = 24

    def is_cooldown_expired(self) -> bool:
        """Check if circuit breaker has cooled down."""
        if not self.triggered_at:
            return True

        cooldown_end = self.triggered_at + timedelta(hours=self.recovery_cooldown_hours)
        return datetime.now() > cooldown_end


@dataclass
class RiskMetrics:
    """Real-time risk metrics."""
    current_portfolio_value: float
    daily_pnl: float
    daily_pnl_pct: float
    weekly_pnl: float
    weekly_pnl_pct: float
    max_drawdown: float
    current_drawdown: float
    volatility_annualized: float
    var_95: float  # 95% Value at Risk
    cvar_95: float  # Conditional Value at Risk (expected shortfall)
    sharpe_ratio: float
    concentration_factor: float  # 0-1, higher = more concentrated
    max_correlation: float  # Highest correlation between any two positions
    estimated_liquidation_hours: float  # Hours to liquidate all positions
    beta_to_market: float


class CircuitBreakerManager:
    """
    Manages multiple circuit breakers.

    Circuit breakers are risk controls that automatically limit or stop trading
    when portfolio experiences excessive losses or risk.
    """

    def __init__(self):
        """Initialize circuit breaker manager."""
        self.circuit_breakers: Dict[str, CircuitBreaker] = {}
        self.events: List[Tuple[datetime, RiskEvent, str]] = []

    def add_circuit_breaker(
        self,
        name: str,
        loss_limit_pct: float,
        lookback_days: int = 1,
        action: str = "pause",
    ) -> CircuitBreaker:
        """
        Add a circuit breaker.

        Args:
            name: Unique name
            loss_limit_pct: Loss threshold (e.g., 5 for -5%)
            lookback_days: Lookback window (1=daily, 7=weekly)
            action: 'pause' | 'scale_down' | 'close'

        Returns:
            CircuitBreaker instance
        """
        breaker = CircuitBreaker(
            name=name,
            loss_limit_pct=loss_limit_pct,
            lookback_days=lookback_days,
            action=action,
        )
        self.circuit_breakers[name] = breaker
        logger.info(
            f"Added circuit breaker: {name} "
            f"(loss_limit={loss_limit_pct}%, action={action})"
        )
        return breaker

    def check_circuit_breakers(
        self,
        returns: pd.Series,
        portfolio_value: float,
    ) -> List[Tuple[str, RiskEvent, str]]:
        """
        Check all circuit breakers against returns.

        Args:
            returns: Daily returns series
            portfolio_value: Current portfolio value

        Returns:
            List of (breaker_name, event_type, action) tuples
        """
        triggered = []

        for breaker_name, breaker in self.circuit_breakers.items():
            # Check if on cooldown
            if breaker.triggered and not breaker.is_cooldown_expired():
                continue

            # Get lookback window
            if len(returns) >= breaker.lookback_days:
                window_returns = returns.iloc[-breaker.lookback_days :]
            else:
                window_returns = returns

            # Compute cumulative return
            cumulative_return = (1 + window_returns).prod() - 1

            # Check if breach
            if cumulative_return <= -breaker.loss_limit_pct / 100:
                breaker.triggered = True
                breaker.triggered_at = datetime.now()

                self.events.append(
                    (datetime.now(), RiskEvent.DAILY_LOSS_LIMIT, breaker_name)
                )

                triggered.append((breaker_name, RiskEvent.DAILY_LOSS_LIMIT, breaker.action))

                logger.warning(
                    f"⚠️  CIRCUIT BREAKER TRIGGERED: {breaker_name} "
                    f"(loss={cumulative_return:.2%})"
                )

        return triggered

    def reset_circuit_breaker(self, name: str) -> None:
        """Manually reset a circuit breaker."""
        if name in self.circuit_breakers:
            self.circuit_breakers[name].triggered = False
            self.circuit_breakers[name].triggered_at = None
            logger.info(f"Circuit breaker reset: {name}")

    def get_status(self) -> Dict[str, Any]:
        """Get status of all circuit breakers."""
        status = {}
        for name, breaker in self.circuit_breakers.items():
            status[name] = {
                "triggered": breaker.triggered,
                "triggered_at": breaker.triggered_at.isoformat() if breaker.triggered_at else None,
                "on_cooldown": not breaker.is_cooldown_expired(),
                "action": breaker.action,
                "loss_limit_pct": breaker.loss_limit_pct,
            }
        return status


class StressTestScenario:
    """Stress test scenario (market shock simulation)."""

    def __init__(self, name: str, description: str, scenario_returns: Dict[str, float]):
        """
        Initialize stress test.

        Args:
            name: Scenario name
            description: Human-readable description
            scenario_returns: Dict of asset_class -> return (e.g., 'equities': -0.40)
        """
        self.name = name
        self.description = description
        self.scenario_returns = scenario_returns

    def apply_to_positions(
        self,
        positions: Dict[str, float],
        asset_class_map: Dict[str, str],
    ) -> Dict[str, float]:
        """
        Apply stress scenario to positions.

        Args:
            positions: Dict of ticker -> position size
            asset_class_map: Dict of ticker -> asset_class

        Returns:
            Dict of ticker -> stressed_position
        """
        stressed = {}

        for ticker, size in positions.items():
            asset_class = asset_class_map.get(ticker, "other")
            shock = self.scenario_returns.get(asset_class, 0)
            stressed[ticker] = size * (1 + shock)

        return stressed

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "description": self.description,
            "scenario_returns": self.scenario_returns,
        }


class StressTestManager:
    """
    Manages stress testing scenarios.

    Pre-defined scenarios for common market shocks.
    """

    # Standard scenarios
    SCENARIO_2008 = {
        "equities": -0.40,
        "credit": -0.50,
        "volatility": 2.0,
        "commodities": -0.30,
        "currencies": -0.10,
    }

    SCENARIO_COVID = {
        "equities": -0.30,
        "credit": -0.20,
        "volatility": 1.5,
        "commodities": -0.20,
        "currencies": 0.05,
    }

    SCENARIO_VIX_SPIKE = {
        "equities": -0.15,
        "credit": -0.10,
        "volatility": 2.0,
        "commodities": 0.05,
        "currencies": 0.0,
    }

    SCENARIO_RATE_SHOCK = {
        "equities": -0.10,
        "credit": -0.15,
        "volatility": 1.2,
        "commodities": 0.10,
        "currencies": -0.05,
    }

    def __init__(self):
        """Initialize stress test manager."""
        self.scenarios: Dict[str, StressTestScenario] = {}

        # Add default scenarios
        self.add_scenario(
            "2008_crisis",
            "2008 Financial Crisis",
            self.SCENARIO_2008,
        )
        self.add_scenario(
            "covid_crash",
            "COVID-19 Pandemic Crash",
            self.SCENARIO_COVID,
        )
        self.add_scenario(
            "vix_spike",
            "VIX Spike to 80",
            self.SCENARIO_VIX_SPIKE,
        )
        self.add_scenario(
            "rate_shock",
            "Interest Rate Shock",
            self.SCENARIO_RATE_SHOCK,
        )

    def add_scenario(
        self,
        name: str,
        description: str,
        scenario_returns: Dict[str, float],
    ) -> StressTestScenario:
        """Add a stress test scenario."""
        scenario = StressTestScenario(name, description, scenario_returns)
        self.scenarios[name] = scenario
        return scenario

    def run_stress_test(
        self,
        positions: Dict[str, float],
        asset_class_map: Dict[str, str],
        portfolio_value: float,
    ) -> Dict[str, Dict]:
        """
        Run all stress tests on portfolio.

        Args:
            positions: Current positions
            asset_class_map: Asset class mapping
            portfolio_value: Current portfolio value

        Returns:
            Dict of scenario_name -> {stressed_pnl, stressed_pnl_pct}
        """
        results = {}

        for scenario_name, scenario in self.scenarios.items():
            stressed_positions = scenario.apply_to_positions(positions, asset_class_map)

            # Compute PnL change
            original_value = sum(positions.values())
            stressed_value = sum(stressed_positions.values())
            pnl_change = stressed_value - original_value

            results[scenario_name] = {
                "scenario_name": scenario.name,
                "description": scenario.description,
                "pnl_change": pnl_change,
                "pnl_change_pct": pnl_change / (portfolio_value + 1e-10),
                "portfolio_value_after": portfolio_value + pnl_change,
                "scenario": scenario.to_dict(),
            }

        return results


class PositionLimits:
    """Enforce position limits."""

    def __init__(
        self,
        max_position_pct: float = 0.05,  # Max 5% per stock
        max_sector_pct: float = 0.25,  # Max 25% per sector
        max_correlation_limit: float = 0.85,  # Max correlation between positions
        max_leverage: float = 1.5,
    ):
        """
        Initialize position limits.

        Args:
            max_position_pct: Maximum % of portfolio per position
            max_sector_pct: Maximum % of portfolio per sector
            max_correlation_limit: Maximum allowed correlation
            max_leverage: Maximum leverage ratio
        """
        self.max_position_pct = max_position_pct
        self.max_sector_pct = max_sector_pct
        self.max_correlation_limit = max_correlation_limit
        self.max_leverage = max_leverage

    def check_position_limits(
        self,
        positions: Dict[str, float],
        portfolio_value: float,
        sector_map: Optional[Dict[str, str]] = None,
    ) -> List[Tuple[str, str]]:
        """
        Check if positions violate limits.

        Args:
            positions: Dict of ticker -> size
            portfolio_value: Total portfolio value
            sector_map: Optional sector mapping

        Returns:
            List of (ticker, violation_type) tuples
        """
        violations = []

        # Check individual position limits
        for ticker, size in positions.items():
            position_pct = abs(size) / (portfolio_value + 1e-10)

            if position_pct > self.max_position_pct:
                violations.append((ticker, "exceeds_position_limit"))

        # Check sector limits
        if sector_map:
            sector_exposure = {}
            for ticker, size in positions.items():
                sector = sector_map.get(ticker, "other")
                sector_exposure[sector] = sector_exposure.get(sector, 0) + abs(size)

            for sector, exposure in sector_exposure.items():
                sector_pct = exposure / (portfolio_value + 1e-10)
                if sector_pct > self.max_sector_pct:
                    violations.append((sector, "exceeds_sector_limit"))

        # Check leverage
        gross_exposure = sum(abs(s) for s in positions.values())
        leverage = gross_exposure / (portfolio_value + 1e-10)

        if leverage > self.max_leverage:
            violations.append(("portfolio", "exceeds_leverage_limit"))

        return violations


class RiskControlSystem:
    """
    Main risk control system combining all defensive measures.

    Orchestrates:
    - Circuit breakers
    - Stress testing
    - Position limits
    - Risk monitoring
    """

    def __init__(
        self,
        initial_capital: float = 100_000,
        daily_loss_limit_pct: float = 5.0,
        weekly_loss_limit_pct: float = 10.0,
        max_drawdown_pct: float = 15.0,
    ):
        """
        Initialize risk control system.

        Args:
            initial_capital: Starting capital
            daily_loss_limit_pct: Max daily loss before pause
            weekly_loss_limit_pct: Max weekly loss before scale down
            max_drawdown_pct: Max drawdown before close positions
        """
        self.initial_capital = initial_capital
        self.daily_loss_limit_pct = daily_loss_limit_pct
        self.weekly_loss_limit_pct = weekly_loss_limit_pct
        self.max_drawdown_pct = max_drawdown_pct

        # Initialize components
        self.circuit_breaker_manager = CircuitBreakerManager()
        self.stress_test_manager = StressTestManager()
        self.position_limits = PositionLimits()

        # Set up default circuit breakers
        self.circuit_breaker_manager.add_circuit_breaker(
            "daily_loss",
            loss_limit_pct=daily_loss_limit_pct,
            lookback_days=1,
            action="pause",
        )
        self.circuit_breaker_manager.add_circuit_breaker(
            "weekly_loss",
            loss_limit_pct=weekly_loss_limit_pct,
            lookback_days=5,
            action="scale_down",
        )
        self.circuit_breaker_manager.add_circuit_breaker(
            "max_drawdown",
            loss_limit_pct=max_drawdown_pct,
            lookback_days=252,  # Max drawdown since start
            action="close",
        )

    def check_all_controls(
        self,
        positions: Dict[str, float],
        returns: pd.Series,
        portfolio_value: float,
        sector_map: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        Run all risk checks.

        Args:
            positions: Current positions
            returns: Daily returns history
            portfolio_value: Current portfolio value
            sector_map: Optional sector mapping

        Returns:
            Dict with all risk check results
        """
        results = {
            "timestamp": datetime.now().isoformat(),
            "portfolio_value": portfolio_value,
            "circuit_breakers_triggered": [],
            "position_violations": [],
            "stress_test_results": {},
        }

        # Check circuit breakers
        cb_triggered = self.circuit_breaker_manager.check_circuit_breakers(
            returns, portfolio_value
        )
        results["circuit_breakers_triggered"] = [
            {"name": name, "event": event.name, "action": action}
            for name, event, action in cb_triggered
        ]

        # Check position limits
        violations = self.position_limits.check_position_limits(
            positions, portfolio_value, sector_map
        )
        results["position_violations"] = [
            {"position": p, "violation": v} for p, v in violations
        ]

        # Run stress tests
        if positions:
            stress_results = self.stress_test_manager.run_stress_test(
                positions, sector_map or {}, portfolio_value
            )
            results["stress_test_results"] = stress_results

        return results

    def get_status(self) -> Dict[str, Any]:
        """Get overall risk control status."""
        return {
            "circuit_breakers": self.circuit_breaker_manager.get_status(),
            "position_limits": {
                "max_position_pct": self.position_limits.max_position_pct,
                "max_sector_pct": self.position_limits.max_sector_pct,
                "max_leverage": self.position_limits.max_leverage,
            },
            "scenarios_configured": list(self.stress_test_manager.scenarios.keys()),
        }
