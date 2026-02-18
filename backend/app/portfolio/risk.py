"""
Risk management for portfolio construction and monitoring.

Implements:
- Volatility estimation and targeting
- Drawdown monitoring
- Risk metrics calculation
- Position sizing with risk controls
"""

from dataclasses import dataclass
from typing import Dict, Optional, Tuple, List
import numpy as np
import pandas as pd
import logging

logger = logging.getLogger(__name__)


@dataclass
class RiskMetrics:
    """Portfolio risk metrics."""
    volatility: float  # Annualized volatility
    beta: float  # Market beta
    max_drawdown: float  # Maximum drawdown
    current_drawdown: float  # Current drawdown from peak
    var_95: float  # 95% Value at Risk (daily)
    var_99: float  # 99% Value at Risk (daily)
    sharpe_ratio: float  # Annualized Sharpe ratio
    sortino_ratio: float  # Sortino ratio (downside risk)
    calmar_ratio: float  # Return / MaxDD

    def to_dict(self) -> dict:
        return {
            "volatility": self.volatility,
            "beta": self.beta,
            "max_drawdown": self.max_drawdown,
            "current_drawdown": self.current_drawdown,
            "var_95": self.var_95,
            "var_99": self.var_99,
            "sharpe_ratio": self.sharpe_ratio,
            "sortino_ratio": self.sortino_ratio,
            "calmar_ratio": self.calmar_ratio,
        }


class RiskManager:
    """
    Portfolio risk management.

    Handles:
    - Risk metric computation
    - Volatility targeting
    - Drawdown monitoring and guardrails
    - Position sizing
    """

    def __init__(
        self,
        target_volatility: float = 0.15,
        max_drawdown_limit: float = 0.20,
        risk_free_rate: float = 0.04
    ):
        self.target_volatility = target_volatility
        self.max_drawdown_limit = max_drawdown_limit
        self.risk_free_rate = risk_free_rate

    def compute_metrics(
        self,
        returns: pd.Series,
        market_returns: Optional[pd.Series] = None
    ) -> RiskMetrics:
        """
        Compute comprehensive risk metrics.

        Args:
            returns: Portfolio return series (daily)
            market_returns: Optional market benchmark returns

        Returns:
            RiskMetrics object
        """
        if len(returns) < 21:
            logger.warning("Insufficient data for risk metrics")
            return self._empty_metrics()

        # Annualized volatility
        vol = returns.std() * np.sqrt(252)

        # Beta
        if market_returns is not None and len(market_returns) > 0:
            aligned = pd.concat([returns, market_returns], axis=1).dropna()
            if len(aligned) > 21:
                cov = aligned.cov().iloc[0, 1]
                var = aligned.iloc[:, 1].var()
                beta = cov / var if var > 0 else 1.0
            else:
                beta = 1.0
        else:
            beta = 1.0

        # Drawdown - FIX #2: Add epsilon guard to prevent division by zero
        cumulative = (1 + returns).cumprod()
        running_max = cumulative.expanding().max()
        drawdown = (cumulative - running_max) / (running_max + 1e-8)
        max_dd = drawdown.min()
        current_dd = drawdown.iloc[-1]

        # VaR (historical)
        var_95 = returns.quantile(0.05)
        var_99 = returns.quantile(0.01)

        # Sharpe ratio
        excess_return = returns.mean() * 252 - self.risk_free_rate
        sharpe = excess_return / vol if vol > 0 else 0.0

        # Sortino ratio (downside deviation)
        downside_returns = returns[returns < 0]
        if len(downside_returns) > 0:
            downside_dev = downside_returns.std() * np.sqrt(252)
            sortino = excess_return / downside_dev if downside_dev > 0 else 0.0
        else:
            sortino = sharpe  # No downside

        # Calmar ratio
        calmar = excess_return / abs(max_dd) if max_dd < 0 else 0.0

        return RiskMetrics(
            volatility=vol,
            beta=beta,
            max_drawdown=max_dd,
            current_drawdown=current_dd,
            var_95=var_95,
            var_99=var_99,
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            calmar_ratio=calmar
        )

    def _empty_metrics(self) -> RiskMetrics:
        """Return empty metrics for insufficient data."""
        return RiskMetrics(
            volatility=0.0,
            beta=1.0,
            max_drawdown=0.0,
            current_drawdown=0.0,
            var_95=0.0,
            var_99=0.0,
            sharpe_ratio=0.0,
            sortino_ratio=0.0,
            calmar_ratio=0.0
        )

    def compute_volatility_scalar(
        self,
        recent_returns: pd.Series,
        lookback: int = 21
    ) -> float:
        """
        Compute volatility scaling factor for position sizing.

        If recent vol > target, scale down positions.
        If recent vol < target, scale up positions.

        Returns scalar to multiply weights by.
        """
        if len(recent_returns) < lookback:
            return 1.0

        recent_vol = recent_returns.iloc[-lookback:].std() * np.sqrt(252)

        if recent_vol <= 0:
            return 1.0

        scalar = self.target_volatility / recent_vol

        # Clamp to reasonable range
        scalar = np.clip(scalar, 0.5, 2.0)

        return scalar

    def check_drawdown_limit(
        self,
        equity_curve: pd.Series
    ) -> Tuple[bool, float]:
        """
        Check if drawdown limit has been breached.

        Returns:
            Tuple of (is_breached, current_drawdown)
        """
        if len(equity_curve) < 2:
            return False, 0.0

        running_max = equity_curve.expanding().max()
        drawdown = (equity_curve - running_max) / running_max
        current_dd = drawdown.iloc[-1]

        is_breached = current_dd <= -self.max_drawdown_limit

        if is_breached:
            logger.warning(
                f"Drawdown limit breached: {current_dd:.1%} "
                f"(limit: {-self.max_drawdown_limit:.1%})"
            )

        return is_breached, current_dd

    def apply_risk_overlay(
        self,
        target_weights: pd.Series,
        equity_curve: pd.Series,
        portfolio_returns: pd.Series
    ) -> pd.Series:
        """
        Apply risk overlay to target weights.

        This reduces exposure when:
        - Volatility is elevated
        - Drawdown is approaching limit

        Args:
            target_weights: Target portfolio weights
            equity_curve: Portfolio value time series
            portfolio_returns: Portfolio return series

        Returns:
            Adjusted weights after risk overlay
        """
        adjusted = target_weights.copy()

        # 1. Volatility adjustment
        if len(portfolio_returns) >= 21:
            vol_scalar = self.compute_volatility_scalar(portfolio_returns)
            adjusted = adjusted * vol_scalar
            logger.debug(f"Vol scalar: {vol_scalar:.2f}")

        # 2. Drawdown adjustment
        if len(equity_curve) >= 2:
            is_breached, current_dd = self.check_drawdown_limit(equity_curve)

            if is_breached:
                # Severely reduce exposure
                adjusted = adjusted * 0.3
                logger.warning("Drawdown limit reached - reducing exposure to 30%")
            elif current_dd <= -self.max_drawdown_limit * 0.7:
                # Approaching limit - start reducing
                reduction = 1 - (abs(current_dd) / self.max_drawdown_limit - 0.7) / 0.3
                adjusted = adjusted * max(reduction, 0.5)
                logger.info(f"Near drawdown limit - reducing exposure to {reduction:.0%}")

        # Ensure weights sum to <= 1
        total = adjusted.sum()
        if total > 1:
            adjusted = adjusted / total

        return adjusted

    def compute_position_risk(
        self,
        weights: pd.Series,
        covariance: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Compute risk contribution by position.

        Returns DataFrame with columns:
        - weight: Position weight
        - marginal_risk: Marginal contribution to risk
        - risk_contribution: Total risk contribution
        - pct_of_risk: Percentage of portfolio risk
        """
        aligned_weights = weights.reindex(covariance.index).fillna(0)
        w = aligned_weights.values

        # Portfolio variance
        port_var = w @ covariance.values @ w
        port_vol = np.sqrt(port_var)

        # Marginal risk contribution
        mrc = (covariance.values @ w) / port_vol

        # Risk contribution
        rc = w * mrc

        # Percentage of risk
        pct_risk = rc / port_vol if port_vol > 0 else rc * 0

        return pd.DataFrame({
            "weight": weights,
            "marginal_risk": mrc,
            "risk_contribution": rc,
            "pct_of_risk": pct_risk
        }, index=weights.index)
