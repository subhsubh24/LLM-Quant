"""
Portfolio optimization with constraints.

Implements mean-variance optimization with:
- Shrinkage covariance estimation (Ledoit-Wolf)
- Position limits
- Turnover constraints
- Volatility targeting
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import numpy as np
import pandas as pd
import logging
import json

logger = logging.getLogger(__name__)
from hashlib import sha256


@dataclass
class PortfolioConfig:
    """Configuration for portfolio construction."""

    # Position limits
    max_position_weight: float = 0.10  # Max 10% per stock
    min_position_weight: float = 0.0   # No shorting by default
    max_sector_weight: float = 0.30    # Max 30% per sector

    # Volatility targeting
    target_volatility: float = 0.15    # 15% annualized
    vol_lookback: int = 63             # Days for vol estimation

    # Turnover constraint
    max_turnover: float = 0.30         # Max 30% turnover per rebalance

    # Number of positions
    max_positions: int = 20
    min_positions: int = 10

    # Long only
    long_only: bool = True

    # Optimization method
    optimizer_type: str = "mean_variance"  # mean_variance, risk_parity

    def to_dict(self) -> dict:
        return {
            "max_position_weight": self.max_position_weight,
            "min_position_weight": self.min_position_weight,
            "max_sector_weight": self.max_sector_weight,
            "target_volatility": self.target_volatility,
            "vol_lookback": self.vol_lookback,
            "max_turnover": self.max_turnover,
            "max_positions": self.max_positions,
            "min_positions": self.min_positions,
            "long_only": self.long_only,
            "optimizer_type": self.optimizer_type,
        }

    def compute_hash(self) -> str:
        config_str = json.dumps(self.to_dict(), sort_keys=True)
        return sha256(config_str.encode()).hexdigest()[:16]


class PortfolioOptimizer(ABC):
    """Abstract base class for portfolio optimizers."""

    def __init__(self, config: PortfolioConfig):
        self.config = config

    @abstractmethod
    def optimize(
        self,
        expected_returns: pd.Series,
        covariance: pd.DataFrame,
        current_weights: Optional[pd.Series] = None,
        sector_map: Optional[Dict[str, str]] = None
    ) -> pd.Series:
        """
        Optimize portfolio weights.

        Args:
            expected_returns: Expected returns for each asset
            covariance: Covariance matrix
            current_weights: Current portfolio weights (for turnover constraint)
            sector_map: Ticker -> sector mapping (for sector constraints)

        Returns:
            Optimal weights as Series
        """
        pass


class MeanVarianceOptimizer(PortfolioOptimizer):
    """
    Mean-variance optimization with practical constraints.

    Uses cvxpy for convex optimization with:
    - Ledoit-Wolf shrinkage for covariance
    - Position limits
    - Turnover constraints
    - Volatility targeting
    """

    def optimize(
        self,
        expected_returns: pd.Series,
        covariance: pd.DataFrame,
        current_weights: Optional[pd.Series] = None,
        sector_map: Optional[Dict[str, str]] = None
    ) -> pd.Series:
        """Optimize using mean-variance with constraints."""
        import cvxpy as cp

        n_assets = len(expected_returns)
        tickers = expected_returns.index.tolist()

        # Decision variable: weights
        w = cp.Variable(n_assets)

        # Expected return
        mu = expected_returns.values
        Sigma = covariance.values

        # Objective: maximize expected return (we'll use constraints for risk)
        # Or: maximize Sharpe-like ratio with constraints
        portfolio_return = mu @ w
        portfolio_variance = cp.quad_form(w, Sigma)

        # Constraints
        constraints = []

        # Weights sum to 1
        constraints.append(cp.sum(w) == 1)

        # Long only (if configured)
        if self.config.long_only:
            constraints.append(w >= 0)
        else:
            constraints.append(w >= self.config.min_position_weight)

        # Max position
        constraints.append(w <= self.config.max_position_weight)

        # Volatility target (as inequality)
        target_var = self.config.target_volatility ** 2
        constraints.append(portfolio_variance <= target_var * 1.5)  # Allow some slack

        # Turnover constraint
        if current_weights is not None:
            # Align current weights with new tickers
            aligned_current = pd.Series(0.0, index=tickers)
            for ticker in current_weights.index:
                if ticker in aligned_current.index:
                    aligned_current[ticker] = current_weights[ticker]

            turnover = cp.sum(cp.abs(w - aligned_current.values))
            constraints.append(turnover <= self.config.max_turnover * 2)  # 2x since |buy| + |sell|

        # Sector constraints (if sector map provided)
        if sector_map:
            sectors = set(sector_map.values())
            for sector in sectors:
                sector_mask = np.array([
                    1.0 if sector_map.get(t) == sector else 0.0
                    for t in tickers
                ])
                if sector_mask.sum() > 0:
                    constraints.append(sector_mask @ w <= self.config.max_sector_weight)

        # Objective: maximize return - risk penalty
        # This is equivalent to maximizing Sharpe for a given risk aversion
        risk_aversion = 1.0
        objective = cp.Maximize(portfolio_return - risk_aversion * portfolio_variance)

        # Solve
        problem = cp.Problem(objective, constraints)

        try:
            problem.solve(solver=cp.OSQP, verbose=False)

            if problem.status not in ["optimal", "optimal_inaccurate"]:
                logger.warning(f"Optimization status: {problem.status}")
                return self._fallback_weights(expected_returns)

            weights = pd.Series(w.value, index=tickers)

            # Clean up small weights
            weights = weights.clip(lower=0)
            weights[weights < 0.01] = 0
            weights = weights / weights.sum()  # Renormalize

            # Limit number of positions
            if (weights > 0).sum() > self.config.max_positions:
                weights = self._limit_positions(weights, expected_returns)

            return weights

        except Exception as e:
            logger.error(f"Optimization failed: {e}")
            return self._fallback_weights(expected_returns)

    def _fallback_weights(self, expected_returns: pd.Series) -> pd.Series:
        """Simple fallback: equal weight top N by expected return."""
        n = min(self.config.max_positions, len(expected_returns))
        top_n = expected_returns.nlargest(n).index
        weights = pd.Series(0.0, index=expected_returns.index)
        weights[top_n] = 1.0 / n
        return weights

    def _limit_positions(
        self,
        weights: pd.Series,
        expected_returns: pd.Series
    ) -> pd.Series:
        """Reduce to max_positions by removing lowest weight positions."""
        # Keep top positions by weight
        nonzero = weights[weights > 0]
        if len(nonzero) <= self.config.max_positions:
            return weights

        # Sort by expected return * weight (conviction)
        conviction = nonzero * expected_returns.reindex(nonzero.index).fillna(0)
        top_positions = conviction.nlargest(self.config.max_positions).index

        result = pd.Series(0.0, index=weights.index)
        result[top_positions] = weights[top_positions]
        result = result / result.sum()

        return result


class RiskParityOptimizer(PortfolioOptimizer):
    """
    Risk parity portfolio optimization.

    Allocates to equalize risk contribution from each asset.
    This is a more defensive approach than mean-variance.
    """

    def optimize(
        self,
        expected_returns: pd.Series,
        covariance: pd.DataFrame,
        current_weights: Optional[pd.Series] = None,
        sector_map: Optional[Dict[str, str]] = None
    ) -> pd.Series:
        """Optimize for risk parity."""
        tickers = expected_returns.index.tolist()

        # Start with inverse volatility weights
        vols = np.sqrt(np.diag(covariance.values))
        inv_vol = 1.0 / np.clip(vols, 0.01, None)
        weights = inv_vol / inv_vol.sum()

        # Iterative refinement for true risk parity
        # (marginal risk contribution = equal)
        for _ in range(20):
            # Portfolio volatility
            port_var = weights @ covariance.values @ weights
            port_vol = np.sqrt(port_var)

            # Marginal risk contribution
            mrc = (covariance.values @ weights) / port_vol

            # Risk contribution
            rc = weights * mrc

            # Target: equal risk contribution
            target_rc = port_vol / len(weights)

            # Update weights
            adjustment = target_rc / np.clip(rc, 0.001, None)
            weights = weights * adjustment
            weights = weights / weights.sum()

        weights = pd.Series(weights, index=tickers)

        # Apply position limits
        weights = weights.clip(
            lower=self.config.min_position_weight if not self.config.long_only else 0,
            upper=self.config.max_position_weight
        )
        weights = weights / weights.sum()

        return weights


def estimate_covariance(
    returns: pd.DataFrame,
    method: str = "ledoit_wolf",
    min_periods: int = 63
) -> pd.DataFrame:
    """
    Estimate covariance matrix with shrinkage.

    Args:
        returns: Return DataFrame (dates x tickers)
        method: Estimation method (ledoit_wolf, sample, ewm)
        min_periods: Minimum periods required

    Returns:
        Covariance matrix
    """
    if len(returns) < min_periods:
        logger.warning(f"Only {len(returns)} observations for covariance estimation")

    if method == "ledoit_wolf":
        from sklearn.covariance import LedoitWolf
        lw = LedoitWolf()
        # Handle NaN by using pairwise complete observations
        clean_returns = returns.dropna()
        if len(clean_returns) < min_periods:
            clean_returns = returns.fillna(0)

        lw.fit(clean_returns.values)
        cov = pd.DataFrame(
            lw.covariance_ * 252,  # Annualize
            index=returns.columns,
            columns=returns.columns
        )

    elif method == "ewm":
        # Exponentially weighted covariance
        halflife = 63  # ~3 months
        cov = returns.ewm(halflife=halflife).cov().iloc[-len(returns.columns):]
        cov = cov.droplevel(0) * 252

    else:  # sample
        cov = returns.cov() * 252

    return cov


def estimate_expected_returns(
    model_scores: pd.Series,
    historical_returns: pd.DataFrame,
    blend_weight: float = 0.5
) -> pd.Series:
    """
    Estimate expected returns from model scores.

    Args:
        model_scores: Model ranking scores
        historical_returns: Historical return data
        blend_weight: Weight on model vs historical mean (0-1)

    Returns:
        Expected return estimates
    """
    # Historical mean
    hist_mean = historical_returns.mean() * 252  # Annualize

    # Normalize model scores to return-like scale
    # Map scores to realistic return expectations
    score_std = model_scores.std()
    if score_std > 0:
        normalized_scores = (model_scores - model_scores.mean()) / score_std
        # Scale to ~10% spread top to bottom
        scaled_scores = normalized_scores * 0.10
    else:
        scaled_scores = model_scores * 0

    # Blend
    expected = blend_weight * scaled_scores + (1 - blend_weight) * hist_mean.reindex(model_scores.index).fillna(0)

    return expected
