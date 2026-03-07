"""
Simulation Engine Integration for Prediction Markets.

Bridges the core simulation library (backend/app/simulation/) with the
prediction market trading system. Provides:

1. Enhanced Kelly sizing with variance-reduced Monte Carlo
2. Tail-risk contract pricing via importance sampling
3. Real-time probability tracking via particle filters
4. Correlated portfolio analysis via vine copulas
5. Market microstructure simulation via agent-based models
6. Hierarchical Bayesian pooling across related markets
7. Correlation stress testing for portfolio risk

This module replaces crude bootstrap MC with production-grade simulation.
"""

import logging
import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

from ..simulation.monte_carlo import BinaryContractPricer, MonteCarloEngine
from ..simulation.importance_sampling import RareEventEstimator
from ..simulation.variance_reduction import StackedVarianceReduction
from ..simulation.particle_filter import PredictionMarketFilter, MultiContractFilter
from ..simulation.vine_copula import CorrelatedContractSimulator
from ..simulation.agent_based import PredictionMarketABM
from ..simulation.hierarchical_bayesian import (
    HierarchicalBayesianModel, NationalSwingModel, CategoryPoolingModel,
)
from ..simulation.correlation_stress import CorrelationStressTester

logger = logging.getLogger(__name__)


class EnhancedContractPricer:
    """
    Production-grade binary contract pricer for prediction markets.

    Automatically selects the best simulation method based on the contract:
    - Near-50% contracts: stratified MC (highest precision where variance is maximal)
    - Extreme contracts (<5% or >95%): importance sampling
    - Path-dependent contracts: full path simulation
    - Standard contracts: stacked variance reduction (antithetic + stratified + CV)

    Usage:
        pricer = EnhancedContractPricer()
        result = pricer.price_contract(
            current_prob=0.62, vol=0.3, T=30/365, n_paths=50_000
        )
        print(f"Fair value: {result['probability']:.4f} +/- {result['std_error']:.4f}")
    """

    def __init__(self, seed: Optional[int] = None):
        self._engine = MonteCarloEngine(seed=seed)
        self._pricer = BinaryContractPricer(self._engine)
        self._is = RareEventEstimator(seed=seed)
        self._vr = StackedVarianceReduction(seed=seed)

    def price_contract(
        self,
        current_prob: float,
        vol: float,
        T: float,
        n_paths: int = 50_000,
    ) -> Dict:
        """
        Price a prediction market binary contract.

        Automatically selects the best method based on current_prob.
        """
        if current_prob < 0.05 or current_prob > 0.95:
            # Tail contract: use importance sampling
            result = self._is.estimate_prediction_market_tail(
                current_prob=current_prob, vol=vol, T=T, n_samples=n_paths,
            )
            return {
                "probability": result.estimate,
                "std_error": result.std_error,
                "ci_95": result.ci_95,
                "method": "importance_sampling",
                "variance_reduction": result.variance_reduction,
            }
        else:
            # Standard contract: use stacked variance reduction
            # Map to asset-binary framework for the VR engine
            eps = 1e-6
            S0 = 100.0
            # Convert prob to a strike via inverse CDF
            K = S0 * math.exp(
                (vol * math.sqrt(T)) * _norm_ppf(1.0 - current_prob)
            )
            sigma = vol

            result = self._vr.estimate_binary(
                S0=S0, K=K, mu=0.0, sigma=sigma, T=T,
                n_strata=10, n_total=n_paths,
            )
            return {
                "probability": result.estimate,
                "std_error": result.std_error,
                "ci_95": result.ci_95,
                "method": "stacked_variance_reduction",
                "variance_reduction": result.variance_reduction,
            }

    def price_crash_contract(
        self,
        asset_price: float,
        crash_pct: float,
        sigma: float,
        T: float,
        n_paths: int = 100_000,
    ) -> Dict:
        """
        Price a crash/tail-risk contract via importance sampling.

        Example: "Will S&P 500 drop 20% in one week?"
        """
        result = self._is.estimate_portfolio_tail_loss(
            mu=0.0, sigma=sigma, T=T,
            loss_threshold=crash_pct, n_samples=n_paths,
        )
        return {
            "probability": result.estimate,
            "std_error": result.std_error,
            "ci_95": result.ci_95,
            "method": "importance_sampling",
            "variance_reduction": result.variance_reduction,
            "crude_estimate": result.crude_estimate,
        }


class LiveProbabilityTracker:
    """
    Real-time probability tracking for active prediction markets.

    Wraps the particle filter to provide smooth, noise-filtered probability
    estimates during live events (elections, Fed meetings, etc).

    The filter tempers market spikes - when price jumps from 0.58 to 0.65
    on a single trade, the filter recognizes the true probability may not
    have moved that much.

    Usage:
        tracker = LiveProbabilityTracker(prior_prob=0.50)

        # As market prices arrive:
        tracker.update(0.52)
        tracker.update(0.55)
        tracker.update(0.58)

        print(f"Filtered: {tracker.estimate():.3f}")
        print(f"CI: {tracker.credible_interval()}")
    """

    def __init__(
        self,
        prior_prob: float = 0.5,
        process_vol: float = 0.03,
        obs_noise: float = 0.03,
        n_particles: int = 5000,
        seed: Optional[int] = None,
    ):
        self._filter = PredictionMarketFilter(
            n_particles=n_particles,
            prior_prob=prior_prob,
            process_vol=process_vol,
            obs_noise=obs_noise,
            seed=seed,
        )

    def update(self, observed_price: float):
        """Incorporate new market price observation."""
        self._filter.update(observed_price)

    def estimate(self) -> float:
        """Current filtered probability estimate."""
        return self._filter.estimate()

    def credible_interval(self, alpha: float = 0.05) -> Tuple[float, float]:
        """95% credible interval."""
        return self._filter.credible_interval(alpha)

    def history(self) -> List[Dict]:
        """Full filter history for plotting/analysis."""
        return [
            {
                "estimate": s.estimate,
                "ci_lower": s.ci_lower,
                "ci_upper": s.ci_upper,
                "observation": s.observation,
                "ess": s.ess,
            }
            for s in self._filter.history
        ]

    def divergence_from_market(self) -> Optional[float]:
        """How much the filter disagrees with the raw market price."""
        if not self._filter.history:
            return None
        last = self._filter.history[-1]
        return last.estimate - last.observation


class CorrelatedPortfolioAnalyzer:
    """
    Correlation-aware analysis for prediction market portfolios.

    Uses vine copulas to model dependencies between contracts,
    enabling proper joint probability estimation.

    This replaces the naive assumption of independence that makes
    Kelly criterion over-bet on correlated contracts.

    Usage:
        analyzer = CorrelatedPortfolioAnalyzer()
        analyzer.fit_from_correlation(
            n_contracts=5,
            corr_matrix=state_correlations,
        )
        sweep = analyzer.sweep_probability([0.52, 0.53, 0.51, 0.48, 0.50])
        portfolio_var = analyzer.portfolio_var([0.52, 0.53, 0.51, 0.48, 0.50])
    """

    def __init__(self, seed: Optional[int] = None):
        self._sim = CorrelatedContractSimulator(seed=seed)
        self._fitted = False

    def fit_from_data(self, data: np.ndarray, vine_type: str = "cvine"):
        """Fit from historical uniform data (apply PIT first)."""
        self._sim.fit(data, vine_type=vine_type)
        self._fitted = True

    def fit_from_correlation(
        self, n_contracts: int, corr_matrix: np.ndarray,
        vine_type: str = "cvine",
    ):
        """Fit from a correlation matrix (no historical data needed)."""
        self._sim.fit_from_correlations(
            d=n_contracts, corr=corr_matrix, vine_type=vine_type,
        )
        self._fitted = True

    def sweep_probability(
        self, marginal_probs: List[float], n_sim: int = 100_000
    ) -> float:
        """P(all contracts resolve YES)."""
        outcomes = self._sim.simulate_outcomes(marginal_probs, n_sim)
        return self._sim.sweep_probability(outcomes)

    def loss_probability(
        self, marginal_probs: List[float], n_sim: int = 100_000
    ) -> float:
        """P(all contracts resolve NO)."""
        outcomes = self._sim.simulate_outcomes(marginal_probs, n_sim)
        return self._sim.loss_probability(outcomes)

    def portfolio_var(
        self, marginal_probs: List[float], bet_sizes: Optional[List[float]] = None,
        n_sim: int = 100_000, confidence: float = 0.95,
    ) -> Dict:
        """
        Portfolio VaR/CVaR for a basket of prediction market contracts.
        """
        if bet_sizes is None:
            bet_sizes = [1.0] * len(marginal_probs)

        outcomes = self._sim.simulate_outcomes(marginal_probs, n_sim)
        bets = np.array(bet_sizes)
        prices = np.array(marginal_probs)

        # P&L: for each sim, compute portfolio return
        # Buy at price p, receive 1 if outcome=1, else 0
        payoffs = outcomes.astype(float) - prices
        portfolio_pnl = np.sum(payoffs * bets, axis=1)

        sorted_pnl = np.sort(portfolio_pnl)
        n = len(sorted_pnl)
        var_idx = int((1 - confidence) * n)

        return {
            "mean_pnl": float(portfolio_pnl.mean()),
            "std_pnl": float(portfolio_pnl.std()),
            "var": float(sorted_pnl[var_idx]),
            "cvar": float(sorted_pnl[:var_idx].mean()) if var_idx > 0 else float(sorted_pnl[0]),
            "max_loss": float(sorted_pnl[0]),
            "max_gain": float(sorted_pnl[-1]),
            "prob_positive": float((portfolio_pnl > 0).mean()),
        }

    def conditional_probability(
        self,
        marginal_probs: List[float],
        target_idx: int,
        condition_indices: List[int],
        condition_values: List[int],
        n_sim: int = 100_000,
    ) -> Optional[float]:
        """P(contract[target]=1 | conditions)."""
        outcomes = self._sim.simulate_outcomes(marginal_probs, n_sim)
        return self._sim.conditional_probability(
            outcomes, target_idx, condition_indices, condition_values,
        )


class MarketMicrostructureSimulator:
    """
    Agent-based simulation for prediction market microstructure analysis.

    Test scenarios:
    - How fast does the market converge to true probability?
    - What's the expected P&L for informed vs noise traders?
    - How does spread change as informed trader fraction increases?
    - What happens during information cascades?

    Usage:
        sim = MarketMicrostructureSimulator()
        result = sim.simulate_price_discovery(
            true_prob=0.65, initial_price=0.50,
            n_informed=10, n_noise=50,
        )
        print(f"Convergence: {result['convergence_steps']} steps")
        print(f"Brier: {result['brier_score']:.4f}")
    """

    def __init__(self, seed: Optional[int] = None):
        self._seed = seed

    def simulate_price_discovery(
        self,
        true_prob: float,
        initial_price: float = 0.50,
        n_informed: int = 10,
        n_noise: int = 50,
        n_mm: int = 5,
        n_steps: int = 2000,
    ) -> Dict:
        """Simulate how fast the market discovers the true probability."""
        abm = PredictionMarketABM(
            initial_price=initial_price,
            true_prob=true_prob,
            n_informed=n_informed,
            n_noise=n_noise,
            n_mm=n_mm,
            seed=self._seed,
        )
        abm.run(n_steps)

        return {
            **abm.summary(),
            "brier_score": abm.brier_score(),
            "convergence_steps": abm.convergence_speed(),
            "information_efficiency": abm.information_efficiency(),
            "price_history": [s.price for s in abm.history],
        }

    def compare_agent_ratios(
        self,
        true_prob: float = 0.65,
        scenarios: Optional[List[Dict]] = None,
        n_steps: int = 2000,
    ) -> List[Dict]:
        """
        Compare market quality under different agent population mixes.

        Default scenarios test how informed trader fraction affects efficiency.
        """
        if scenarios is None:
            scenarios = [
                {"n_informed": 1, "n_noise": 100, "n_mm": 5, "label": "1% informed"},
                {"n_informed": 5, "n_noise": 100, "n_mm": 5, "label": "5% informed"},
                {"n_informed": 10, "n_noise": 100, "n_mm": 5, "label": "9% informed"},
                {"n_informed": 25, "n_noise": 100, "n_mm": 5, "label": "20% informed"},
                {"n_informed": 50, "n_noise": 100, "n_mm": 5, "label": "33% informed"},
            ]

        results = []
        for s in scenarios:
            result = self.simulate_price_discovery(
                true_prob=true_prob,
                n_informed=s["n_informed"],
                n_noise=s["n_noise"],
                n_mm=s["n_mm"],
                n_steps=n_steps,
            )
            result["label"] = s.get("label", "")
            results.append(result)

        return results


class CrossMarketPooler:
    """
    Pools probability and volatility estimates across related prediction markets.

    Uses hierarchical Bayesian models to borrow strength across thin markets
    in the same category. Low-volume markets get shrunk toward the category
    mean, producing more stable estimates for Kelly sizing.

    Usage:
        pooler = CrossMarketPooler()
        result = pooler.pool_category(
            market_probs={"market_a": 0.55, "market_b": 0.60, "market_c": 0.45},
            market_volumes={"market_a": 50000, "market_b": 1000, "market_c": 500},
        )
        # market_b and market_c get shrunk toward the group mean
    """

    def __init__(self, seed: Optional[int] = None):
        self._pooler = CategoryPoolingModel(seed=seed)
        self._swing = NationalSwingModel(seed=seed)

    def pool_category(
        self,
        market_probs: Dict[str, float],
        market_volumes: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Dict]:
        """Pool probability estimates across markets in a category."""
        return self._pooler.pool_probabilities(market_probs, market_volumes)

    def estimate_swing(
        self,
        base_probs: List[float],
        current_probs: List[float],
        elasticities: Optional[List[float]] = None,
    ) -> Dict:
        """Estimate a shared swing factor across related markets."""
        result = self._swing.estimate_swing(
            base_probs=np.array(base_probs),
            observed_probs=np.array(current_probs),
            elasticities=np.array(elasticities) if elasticities else None,
        )
        return {
            "swing": result.swing_estimate,
            "swing_std": result.swing_std,
            "adjusted_probs": result.adjusted_probs.tolist(),
            "ci_lower": result.adjusted_ci_lower.tolist(),
            "ci_upper": result.adjusted_ci_upper.tolist(),
            "correlation_matrix": result.correlation_matrix.tolist(),
        }


class PortfolioStressTester:
    """
    Correlation stress testing for prediction market portfolios.

    Wraps the CorrelationStressTester to provide portfolio-level risk
    assessment under various correlation regimes.

    Usage:
        tester = PortfolioStressTester()
        report = tester.run_stress_test(
            probs=[0.55, 0.60, 0.45],
            bet_sizes=[100, 200, 150],
            base_corr=np.eye(3) * 0.7 + np.eye(3) * 0.3,
        )
        print(report["recommendation"])
    """

    def __init__(self, seed: Optional[int] = None):
        self._tester = CorrelationStressTester(seed=seed)

    def run_stress_test(
        self,
        probs: List[float],
        bet_sizes: List[float],
        base_corr: Optional[np.ndarray] = None,
        n_sim: int = 50_000,
    ) -> Dict:
        """Run full stress test. If no correlation given, assumes low correlation."""
        d = len(probs)
        if base_corr is None:
            base_corr = np.eye(d) * 0.8 + np.full((d, d), 0.2)

        report = self._tester.full_stress_test(
            marginal_probs=probs,
            base_correlation=base_corr,
            bet_sizes=bet_sizes,
            n_sim=n_sim,
        )
        return {
            "normal_var": report.normal_var,
            "worst_case_var": report.worst_case_var,
            "stress_multiplier": report.stress_multiplier,
            "worst_case_scenario": report.worst_case_scenario,
            "recommendation": report.recommendation,
            "n_scenarios": len(report.scenarios),
        }

    def contagion_check(
        self,
        probs: List[float],
        bet_sizes: List[float],
        corr: np.ndarray,
        shock_size: float = -0.20,
    ) -> List[Dict]:
        """Check contagion from each market to the portfolio."""
        results = []
        for i in range(len(probs)):
            c = self._tester.contagion_analysis(
                marginal_probs=np.array(probs),
                corr=corr,
                bet_sizes=np.array(bet_sizes, dtype=float),
                source_idx=i,
                shock_size=shock_size,
            )
            results.append({
                "source_market": i,
                "portfolio_impact": c.portfolio_impact,
                "impact_on_others": c.impact_on_others.tolist(),
            })
        return results


def _norm_ppf(p: float) -> float:
    """Quick normal inverse CDF approximation (Beasley-Springer-Moro)."""
    from scipy.stats import norm
    return float(norm.ppf(max(1e-6, min(1 - 1e-6, p))))
