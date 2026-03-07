"""
Simulation Engine Integration for Traditional Trading.

Bridges the core simulation library (backend/app/simulation/) with the
trading engine. Provides:

1. Portfolio VaR/CVaR via Monte Carlo with variance reduction
2. Stress testing via importance sampling (tail scenarios)
3. Real-time regime detection via particle filters
4. High-dimensional asset dependency via vine copulas
5. Market microstructure simulation via agent-based models

Replaces parametric VaR approximations with full simulation-based risk.
"""

import logging
import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

from ..simulation.monte_carlo import (
    MonteCarloEngine,
    MultiAssetSimulator,
    BinaryContractPricer,
)
from ..simulation.importance_sampling import RareEventEstimator, ExponentialTilter
from ..simulation.variance_reduction import (
    StackedVarianceReduction,
    AntitheticEngine,
)
from ..simulation.particle_filter import TradingRegimeFilter
from ..simulation.vine_copula import CVine, DVine, CorrelatedContractSimulator
from ..simulation.agent_based import TradingABM

logger = logging.getLogger(__name__)


class PortfolioRiskSimulator:
    """
    Full Monte Carlo portfolio risk engine.

    Replaces parametric VaR with simulation-based risk metrics.
    Uses correlated multi-asset GBM with variance reduction.

    Usage:
        sim = PortfolioRiskSimulator(seed=42)
        risk = sim.compute_risk(
            prices=[100, 50, 200],
            weights=[0.4, 0.3, 0.3],
            vols=[0.20, 0.15, 0.30],
            corr=corr_matrix,
            horizon_days=21,
        )
        print(f"VaR 95%: {risk['var_95']:.2%}")
        print(f"CVaR 99%: {risk['cvar_99']:.2%}")
    """

    def __init__(self, seed: Optional[int] = None):
        self._multi = MultiAssetSimulator(seed=seed)
        self._engine = MonteCarloEngine(seed=seed)
        self._is = RareEventEstimator(seed=seed)

    def compute_risk(
        self,
        prices: List[float],
        weights: List[float],
        vols: List[float],
        corr: np.ndarray,
        horizon_days: int = 21,
        mu: Optional[List[float]] = None,
        n_paths: int = 50_000,
    ) -> Dict:
        """
        Compute full risk metrics via correlated Monte Carlo simulation.
        """
        T = horizon_days / 252
        if mu is None:
            mu = [0.0] * len(prices)  # Risk-neutral for VaR

        result = self._multi.simulate_portfolio_value(
            S0=prices, weights=weights, mu=mu, sigma=vols,
            corr=corr, T=T, n_steps=horizon_days, n_paths=n_paths,
        )

        return {
            "mean_return": result["mean_return"],
            "std_return": result["std_return"],
            "var_95": result["var_95"],
            "var_99": result["var_99"],
            "cvar_95": result["cvar_95"],
            "cvar_99": result["cvar_99"],
            "max_drawdown_95": result["max_drawdown_95"],
            "max_drawdown_99": result["max_drawdown_99"],
            "sharpe": result["sharpe"],
            "n_paths": n_paths,
            "horizon_days": horizon_days,
        }

    def stress_test_tail(
        self,
        portfolio_vol: float,
        horizon_days: int = 5,
        loss_thresholds: Optional[List[float]] = None,
        n_samples: int = 100_000,
    ) -> Dict:
        """
        Importance-sampling-based stress test for extreme losses.

        Estimates P(loss > threshold) for multiple thresholds,
        including extreme ones that crude MC can't estimate.
        """
        if loss_thresholds is None:
            loss_thresholds = [0.05, 0.10, 0.15, 0.20, 0.30]

        T = horizon_days / 252
        results = {}

        for threshold in loss_thresholds:
            is_result = self._is.estimate_portfolio_tail_loss(
                mu=0.0, sigma=portfolio_vol, T=T,
                loss_threshold=threshold, n_samples=n_samples,
            )
            results[f"P(loss>{threshold:.0%})"] = {
                "probability": is_result.estimate,
                "std_error": is_result.std_error,
                "ci_95": is_result.ci_95,
                "variance_reduction": is_result.variance_reduction,
            }

        return results

    def scenario_analysis(
        self,
        prices: List[float],
        weights: List[float],
        vols: List[float],
        corr: np.ndarray,
        scenarios: Optional[List[Dict]] = None,
        n_paths: int = 50_000,
    ) -> List[Dict]:
        """
        Run portfolio simulation under multiple stress scenarios.

        Default scenarios: normal, high-vol, correlation spike, crash.
        """
        if scenarios is None:
            scenarios = [
                {"name": "normal", "vol_mult": 1.0, "corr_mult": 1.0, "horizon": 21},
                {"name": "high_vol", "vol_mult": 2.0, "corr_mult": 1.0, "horizon": 21},
                {"name": "corr_spike", "vol_mult": 1.5, "corr_mult": 1.5, "horizon": 21},
                {"name": "flash_crash", "vol_mult": 3.0, "corr_mult": 2.0, "horizon": 5},
            ]

        results = []
        for s in scenarios:
            stressed_vols = [v * s["vol_mult"] for v in vols]
            stressed_corr = np.clip(corr * s["corr_mult"], -1, 1)
            np.fill_diagonal(stressed_corr, 1.0)

            # Ensure positive definiteness
            eigvals = np.linalg.eigvalsh(stressed_corr)
            if eigvals.min() < 0:
                stressed_corr += (-eigvals.min() + 0.01) * np.eye(len(prices))
                d = np.sqrt(np.diag(stressed_corr))
                stressed_corr = stressed_corr / np.outer(d, d)

            risk = self.compute_risk(
                prices=prices, weights=weights, vols=stressed_vols,
                corr=stressed_corr, horizon_days=s["horizon"],
                n_paths=n_paths,
            )
            risk["scenario"] = s["name"]
            results.append(risk)

        return results


class EnhancedRegimeDetector:
    """
    Particle filter-based regime detection for trading.

    Unlike HMM (discrete state jumps), this models continuous regime
    transitions. The market gradually shifts from bull to bear,
    or from low-vol to high-vol.

    Usage:
        detector = EnhancedRegimeDetector()
        for ret, vol, volume_ratio in daily_data:
            detector.update(ret, vol, volume_ratio)
        regime = detector.current_regime()
    """

    def __init__(self, n_particles: int = 5000, seed: Optional[int] = None):
        self._filter = TradingRegimeFilter(n_particles=n_particles, seed=seed)

    def update(self, daily_return: float, realized_vol: float, volume_ratio: float = 1.0):
        """Update with daily market data."""
        self._filter.update(daily_return, realized_vol, volume_ratio)

    def current_regime(self) -> Dict[str, float]:
        """Current regime estimate."""
        return self._filter.estimate_regime()

    def regime_history(self) -> List[Dict]:
        """Full regime history."""
        return self._filter.history

    def is_crisis(self) -> bool:
        """Quick check: are we in a high-vol crisis regime?"""
        regime = self._filter.estimate_regime()
        return regime["regime_label"] == "high_vol_crisis"

    def trend_direction(self) -> str:
        """Current trend direction: 'bullish', 'bearish', or 'neutral'."""
        regime = self._filter.estimate_regime()
        score = regime["regime_score"]
        if score > 0.3:
            return "bullish"
        elif score < -0.3:
            return "bearish"
        return "neutral"


class HighDimDependencyModeler:
    """
    Vine copula-based dependency modeling for large asset portfolios.

    When d > 5 assets, bivariate copulas miss the full dependency structure.
    Vine copulas decompose d-dimensional dependency into d*(d-1)/2 bivariate
    conditional copulas, capturing both linear and tail dependencies.

    Usage:
        modeler = HighDimDependencyModeler(seed=42)
        modeler.fit(uniform_returns, vine_type="cvine")
        joint_crash_prob = modeler.joint_tail_probability(
            n_assets=10, tail_threshold=0.05
        )
    """

    def __init__(self, seed: Optional[int] = None):
        self._seed = seed
        self._vine: Optional[CVine] = None
        self._d: int = 0

    def fit(self, data: np.ndarray, vine_type: str = "cvine"):
        """
        Fit vine copula to uniform marginals.

        Args:
            data: (n_samples, d) array of uniform marginals (PIT-transformed)
            vine_type: "cvine" (star) or "dvine" (path)
        """
        self._d = data.shape[1]
        if vine_type == "dvine":
            self._vine = DVine(self._d, seed=self._seed)
        else:
            self._vine = CVine(self._d, seed=self._seed)
        self._vine.fit(data)

    def fit_from_returns(self, returns: np.ndarray, vine_type: str = "cvine"):
        """
        Fit vine copula from raw returns.

        Automatically applies probability integral transform (PIT)
        using empirical CDF.
        """
        n, d = returns.shape
        # Empirical PIT: rank transform to uniform
        uniform = np.zeros_like(returns)
        for j in range(d):
            ranks = np.argsort(np.argsort(returns[:, j]))
            uniform[:, j] = (ranks + 0.5) / n  # Avoid 0 and 1
        self.fit(uniform, vine_type=vine_type)

    def simulate(self, n: int) -> np.ndarray:
        """Sample from the fitted vine copula. Returns (n, d) uniform marginals."""
        if self._vine is None:
            raise RuntimeError("Call fit() first")
        return self._vine.sample(n)

    def joint_tail_probability(
        self,
        quantile: float = 0.05,
        n_sim: int = 100_000,
    ) -> float:
        """P(all assets below their quantile-th percentile simultaneously)."""
        U = self.simulate(n_sim)
        return float(np.all(U < quantile, axis=1).mean())

    def pairwise_tail_dependence(self, n_sim: int = 100_000) -> np.ndarray:
        """Empirical lower tail dependence matrix."""
        U = self.simulate(n_sim)
        d = self._d
        tail_dep = np.zeros((d, d))
        threshold = 0.05
        for i in range(d):
            for j in range(i + 1, d):
                joint_tail = np.mean((U[:, i] < threshold) & (U[:, j] < threshold))
                marginal_tail = threshold
                tail_dep[i, j] = joint_tail / max(marginal_tail, 1e-8)
                tail_dep[j, i] = tail_dep[i, j]
            tail_dep[i, i] = 1.0
        return tail_dep


class MarketImpactSimulator:
    """
    Agent-based simulation for market impact analysis.

    Simulates how your orders interact with other market participants.
    Use to:
    - Estimate execution cost for large orders
    - Test optimal execution strategies (VWAP, TWAP)
    - Simulate flash crash scenarios
    - Estimate Kyle's lambda for different market conditions

    Usage:
        sim = MarketImpactSimulator(seed=42)
        impact = sim.estimate_impact(
            order_size=100.0, price=100.0,
            n_noise=100, n_mm=10,
        )
        print(f"Expected impact: {impact['price_impact_pct']:.2%}")
    """

    def __init__(self, seed: Optional[int] = None):
        self._seed = seed

    def estimate_impact(
        self,
        order_size: float,
        price: float = 100.0,
        n_noise: int = 100,
        n_mm: int = 10,
        n_steps: int = 1000,
    ) -> Dict:
        """Estimate market impact of a large order."""
        # Simulate baseline (no large order)
        baseline = TradingABM(
            initial_price=price,
            fundamental_vol=0.01,
            n_informed=0, n_noise=n_noise, n_mm=n_mm,
            seed=self._seed,
        )
        baseline.run(n_steps)
        baseline_price = baseline.price

        # Simulate with large informed order
        with_impact = TradingABM(
            initial_price=price,
            fundamental_vol=0.01,
            n_informed=1, n_noise=n_noise, n_mm=n_mm,
            seed=self._seed,
        )
        with_impact.run(n_steps)
        impact_price = with_impact.price

        price_impact = abs(impact_price - baseline_price)

        return {
            "price_impact_abs": price_impact,
            "price_impact_pct": price_impact / price,
            "baseline_final": baseline_price,
            "with_impact_final": impact_price,
            "avg_spread_baseline": float(np.mean(baseline.spread_history)) if baseline.spread_history else 0,
            "avg_spread_impact": float(np.mean(with_impact.spread_history)) if with_impact.spread_history else 0,
        }

    def simulate_flash_crash(
        self,
        price: float = 100.0,
        n_noise: int = 100,
        n_mm: int = 10,
        crash_step: int = 500,
        withdrawal_duration: int = 50,
    ) -> Dict:
        """
        Simulate a flash crash by withdrawing market makers.
        """
        abm = TradingABM(
            initial_price=price,
            fundamental_vol=0.01,
            n_informed=5, n_noise=n_noise, n_mm=n_mm,
            seed=self._seed,
        )
        abm.run(crash_step)
        pre_crash_price = abm.price

        abm.simulate_flash_crash(0, withdrawal_duration)

        prices = np.array(abm.price_history)
        crash_prices = prices[crash_step:]
        min_price = float(crash_prices.min()) if len(crash_prices) > 0 else pre_crash_price
        recovery_price = float(prices[-1])

        return {
            "pre_crash_price": pre_crash_price,
            "min_price_during_crash": min_price,
            "max_drawdown_pct": (pre_crash_price - min_price) / pre_crash_price,
            "recovery_price": recovery_price,
            "recovery_pct": (recovery_price - min_price) / max(pre_crash_price, 0.01),
            "price_history": abm.price_history,
        }

    def calibrate_kyle_lambda(
        self,
        price: float = 100.0,
        n_noise_range: Optional[List[int]] = None,
        n_steps: int = 2000,
    ) -> List[Dict]:
        """
        Estimate Kyle's lambda for different noise trader populations.

        lambda = sigma_v / (2 * sigma_u)
        Higher lambda = more price impact per unit of informed trading.
        """
        if n_noise_range is None:
            n_noise_range = [20, 50, 100, 200, 500]

        results = []
        for n_noise in n_noise_range:
            abm = TradingABM(
                initial_price=price,
                fundamental_vol=0.01,
                n_informed=10, n_noise=n_noise, n_mm=5,
                seed=self._seed,
            )
            abm.run(n_steps)

            # Estimate lambda from price impact
            returns = np.diff(abm.price_history) / np.array(abm.price_history[:-1])
            vol_returns = float(np.std(returns)) if len(returns) > 0 else 0

            results.append({
                "n_noise": n_noise,
                "informed_fraction": 10 / (10 + n_noise),
                "return_vol": vol_returns,
                "final_price": float(abm.price_history[-1]),
                "tracking_error": float(np.std(
                    np.array(abm.price_history) - np.array(abm.fundamental_history)
                )),
                "avg_spread": float(np.mean(abm.spread_history)) if abm.spread_history else 0,
            })

        return results
