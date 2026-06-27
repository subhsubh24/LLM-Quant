"""
Correlation Stress Testing for Prediction Market Portfolios.

Implements what-if scenarios for correlation regime changes:

1. **Correlation spike**: What happens when correlations jump to 0.8+ during a crisis?
2. **Decorrelation**: What if historically correlated markets decouple?
3. **Contagion cascade**: If market A moves, how much does portfolio VaR change?
4. **Stressed VaR**: Regulatory-style stressed risk metrics under tail correlations

Key insight: Normal-time correlations understate tail risk. During crises,
all correlations go to 1. This module quantifies the gap between normal
and stressed portfolio risk, enabling proper position sizing.

References:
- Embrechts, McNeil & Straumann (2002): "Correlation and Dependence in Risk Management"
- Rebonato & Jackel (1999): "The Most General Methodology to Create a Valid Correlation Matrix"
"""

import logging
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class StressScenarioResult:
    """Result from a single correlation stress scenario."""
    scenario_name: str
    base_var: float
    stressed_var: float
    var_ratio: float
    base_cvar: float
    stressed_cvar: float
    cvar_ratio: float
    base_mean_pnl: float
    stressed_mean_pnl: float
    correlation_matrix: np.ndarray
    max_loss_increase: float


@dataclass
class ContagionResult:
    """Result from contagion analysis."""
    source_market: int
    source_shock: float
    impact_on_others: np.ndarray
    portfolio_impact: float
    propagation_matrix: np.ndarray


@dataclass
class StressTestReport:
    """Full stress test report across multiple scenarios."""
    scenarios: List[StressScenarioResult]
    worst_case_var: float
    worst_case_scenario: str
    normal_var: float
    stress_multiplier: float
    recommendation: str


def _nearest_positive_semidefinite(A: np.ndarray) -> np.ndarray:
    """
    Find the nearest positive semi-definite matrix (Higham 2002).

    Stressed correlation matrices may not be valid. This projects
    to the nearest valid correlation matrix via eigenvalue clipping.
    """
    B = (A + A.T) / 2
    eigvals, eigvecs = np.linalg.eigh(B)
    eigvals = np.maximum(eigvals, 1e-8)
    result = eigvecs @ np.diag(eigvals) @ eigvecs.T
    d = np.sqrt(np.diag(result))
    result = result / np.outer(d, d)
    np.fill_diagonal(result, 1.0)
    return result


class CorrelationStressTester:
    """
    Stress tests a prediction market portfolio under various correlation regimes.

    Usage:
        tester = CorrelationStressTester(seed=42)
        report = tester.full_stress_test(
            marginal_probs=[0.55, 0.60, 0.45, 0.70, 0.50],
            base_correlation=base_corr,
            bet_sizes=[100, 200, 150, 100, 250],
        )
        print(f"Normal VaR: ${report.normal_var:.2f}")
        print(f"Stressed VaR: ${report.worst_case_var:.2f}")
        print(f"Stress multiplier: {report.stress_multiplier:.1f}x")
        print(report.recommendation)
    """

    def __init__(self, seed: Optional[int] = None):
        self._rng = np.random.default_rng(seed)

    def _simulate_portfolio_pnl(
        self,
        marginal_probs: np.ndarray,
        corr: np.ndarray,
        bet_sizes: np.ndarray,
        n_sim: int = 100_000,
    ) -> np.ndarray:
        """Simulate portfolio P&L using Gaussian copula with given correlation."""
        d = len(marginal_probs)

        try:
            L = np.linalg.cholesky(corr)
        except np.linalg.LinAlgError:
            corr = _nearest_positive_semidefinite(corr)
            L = np.linalg.cholesky(corr)

        Z = self._rng.standard_normal((n_sim, d))
        corr_normals = Z @ L.T

        from scipy.stats import norm
        U = norm.cdf(corr_normals)

        outcomes = (U < marginal_probs[None, :]).astype(float)
        payoffs = outcomes - marginal_probs[None, :]
        portfolio_pnl = np.sum(payoffs * bet_sizes[None, :], axis=1)

        return portfolio_pnl

    def _compute_risk_metrics(
        self, pnl: np.ndarray, confidence: float = 0.95
    ) -> Dict[str, float]:
        """Compute VaR, CVaR, and other risk metrics from P&L array."""
        sorted_pnl = np.sort(pnl)
        n = len(sorted_pnl)
        var_idx = int((1 - confidence) * n)

        return {
            "var": float(sorted_pnl[var_idx]),
            "cvar": float(sorted_pnl[:max(var_idx, 1)].mean()),
            "mean_pnl": float(pnl.mean()),
            "std_pnl": float(pnl.std()),
            "max_loss": float(sorted_pnl[0]),
            "max_gain": float(sorted_pnl[-1]),
            "prob_positive": float((pnl > 0).mean()),
        }

    def stress_uniform_correlation(
        self,
        marginal_probs: np.ndarray,
        base_corr: np.ndarray,
        bet_sizes: np.ndarray,
        stress_rho: float = 0.8,
        n_sim: int = 100_000,
        confidence: float = 0.95,
    ) -> StressScenarioResult:
        """
        Stress test: What if all correlations jump to stress_rho?

        This is the classic crisis scenario where diversification disappears.
        """
        d = len(marginal_probs)
        marginal_probs = np.asarray(marginal_probs)
        bet_sizes = np.asarray(bet_sizes, dtype=float)

        stressed_corr = np.full((d, d), stress_rho)
        np.fill_diagonal(stressed_corr, 1.0)
        stressed_corr = _nearest_positive_semidefinite(stressed_corr)

        base_pnl = self._simulate_portfolio_pnl(marginal_probs, base_corr, bet_sizes, n_sim)
        stressed_pnl = self._simulate_portfolio_pnl(marginal_probs, stressed_corr, bet_sizes, n_sim)

        base_metrics = self._compute_risk_metrics(base_pnl, confidence)
        stressed_metrics = self._compute_risk_metrics(stressed_pnl, confidence)

        base_var = abs(base_metrics["var"])
        stressed_var = abs(stressed_metrics["var"])

        return StressScenarioResult(
            scenario_name=f"uniform_correlation_{stress_rho}",
            base_var=base_metrics["var"],
            stressed_var=stressed_metrics["var"],
            var_ratio=stressed_var / max(base_var, 1e-10),
            base_cvar=base_metrics["cvar"],
            stressed_cvar=stressed_metrics["cvar"],
            cvar_ratio=abs(stressed_metrics["cvar"]) / max(abs(base_metrics["cvar"]), 1e-10),
            base_mean_pnl=base_metrics["mean_pnl"],
            stressed_mean_pnl=stressed_metrics["mean_pnl"],
            correlation_matrix=stressed_corr,
            max_loss_increase=(stressed_metrics["max_loss"] - base_metrics["max_loss"])
            / max(abs(base_metrics["max_loss"]), 1e-10),
        )

    def stress_scaled_correlation(
        self,
        marginal_probs: np.ndarray,
        base_corr: np.ndarray,
        bet_sizes: np.ndarray,
        scale_factor: float = 2.0,
        n_sim: int = 100_000,
        confidence: float = 0.95,
    ) -> StressScenarioResult:
        """
        Stress test: Scale existing correlations by a factor (preserving structure).

        scale_factor=2.0 doubles all correlations (capped at +/-1).
        """
        d = len(marginal_probs)
        marginal_probs = np.asarray(marginal_probs)
        bet_sizes = np.asarray(bet_sizes, dtype=float)

        stressed_corr = base_corr.copy()
        mask = ~np.eye(d, dtype=bool)
        stressed_corr[mask] = np.clip(stressed_corr[mask] * scale_factor, -0.99, 0.99)
        stressed_corr = _nearest_positive_semidefinite(stressed_corr)

        base_pnl = self._simulate_portfolio_pnl(marginal_probs, base_corr, bet_sizes, n_sim)
        stressed_pnl = self._simulate_portfolio_pnl(marginal_probs, stressed_corr, bet_sizes, n_sim)

        base_metrics = self._compute_risk_metrics(base_pnl, confidence)
        stressed_metrics = self._compute_risk_metrics(stressed_pnl, confidence)

        return StressScenarioResult(
            scenario_name=f"scaled_correlation_{scale_factor}x",
            base_var=base_metrics["var"],
            stressed_var=stressed_metrics["var"],
            var_ratio=abs(stressed_metrics["var"]) / max(abs(base_metrics["var"]), 1e-10),
            base_cvar=base_metrics["cvar"],
            stressed_cvar=stressed_metrics["cvar"],
            cvar_ratio=abs(stressed_metrics["cvar"]) / max(abs(base_metrics["cvar"]), 1e-10),
            base_mean_pnl=base_metrics["mean_pnl"],
            stressed_mean_pnl=stressed_metrics["mean_pnl"],
            correlation_matrix=stressed_corr,
            max_loss_increase=(stressed_metrics["max_loss"] - base_metrics["max_loss"])
            / max(abs(base_metrics["max_loss"]), 1e-10),
        )

    def stress_block_correlation(
        self,
        marginal_probs: np.ndarray,
        base_corr: np.ndarray,
        bet_sizes: np.ndarray,
        blocks: List[List[int]],
        within_block_rho: float = 0.9,
        between_block_rho: float = 0.3,
        n_sim: int = 100_000,
        confidence: float = 0.95,
    ) -> StressScenarioResult:
        """
        Stress test: Markets cluster into blocks with high within-block correlation.

        Example: Election markets cluster by party, weather markets by region.
        """
        d = len(marginal_probs)
        marginal_probs = np.asarray(marginal_probs)
        bet_sizes = np.asarray(bet_sizes, dtype=float)

        stressed_corr = np.full((d, d), between_block_rho)
        for block in blocks:
            for i in block:
                for j in block:
                    if i != j:
                        stressed_corr[i, j] = within_block_rho
        np.fill_diagonal(stressed_corr, 1.0)
        stressed_corr = _nearest_positive_semidefinite(stressed_corr)

        base_pnl = self._simulate_portfolio_pnl(marginal_probs, base_corr, bet_sizes, n_sim)
        stressed_pnl = self._simulate_portfolio_pnl(marginal_probs, stressed_corr, bet_sizes, n_sim)

        base_metrics = self._compute_risk_metrics(base_pnl, confidence)
        stressed_metrics = self._compute_risk_metrics(stressed_pnl, confidence)

        return StressScenarioResult(
            scenario_name="block_correlation",
            base_var=base_metrics["var"],
            stressed_var=stressed_metrics["var"],
            var_ratio=abs(stressed_metrics["var"]) / max(abs(base_metrics["var"]), 1e-10),
            base_cvar=base_metrics["cvar"],
            stressed_cvar=stressed_metrics["cvar"],
            cvar_ratio=abs(stressed_metrics["cvar"]) / max(abs(base_metrics["cvar"]), 1e-10),
            base_mean_pnl=base_metrics["mean_pnl"],
            stressed_mean_pnl=stressed_metrics["mean_pnl"],
            correlation_matrix=stressed_corr,
            max_loss_increase=(stressed_metrics["max_loss"] - base_metrics["max_loss"])
            / max(abs(base_metrics["max_loss"]), 1e-10),
        )

    def contagion_analysis(
        self,
        marginal_probs: np.ndarray,
        corr: np.ndarray,
        bet_sizes: np.ndarray,
        source_idx: int,
        shock_size: float = -0.20,
    ) -> ContagionResult:
        """
        Analyze contagion: if market[source_idx] drops by shock_size,
        what happens to the rest of the portfolio?

        Uses conditional multivariate normal to propagate the shock.
        """
        d = len(marginal_probs)
        marginal_probs = np.asarray(marginal_probs, dtype=float)
        bet_sizes = np.asarray(bet_sizes, dtype=float)

        logit_p = np.log(np.clip(marginal_probs, 1e-6, 1 - 1e-6)
                         / (1 - np.clip(marginal_probs, 1e-6, 1 - 1e-6)))

        shocked_prob = np.clip(marginal_probs[source_idx] + shock_size, 0.01, 0.99)
        shocked_logit = math.log(shocked_prob / (1 - shocked_prob))
        logit_shock = shocked_logit - logit_p[source_idx]

        # Conditional mean shift: E[X_j | X_i = x] = mu_j + corr[j,i] * (x - mu_i)
        impact = np.zeros(d)
        for j in range(d):
            if j != source_idx:
                impact[j] = corr[j, source_idx] * logit_shock

        adjusted_logit = logit_p + impact
        adjusted_probs = 1.0 / (1.0 + np.exp(-np.clip(adjusted_logit, -20, 20)))
        prob_impact = adjusted_probs - marginal_probs

        portfolio_impact = float(np.sum(prob_impact * bet_sizes))

        return ContagionResult(
            source_market=source_idx,
            source_shock=shock_size,
            impact_on_others=prob_impact,
            portfolio_impact=portfolio_impact,
            propagation_matrix=corr.copy(),
        )

    def full_stress_test(
        self,
        marginal_probs: List[float],
        base_correlation: np.ndarray,
        bet_sizes: List[float],
        n_sim: int = 100_000,
        confidence: float = 0.95,
    ) -> StressTestReport:
        """
        Run a comprehensive stress test across multiple scenarios.

        Returns a report with worst-case VaR and position sizing recommendation.
        """
        probs = np.asarray(marginal_probs)
        corr = np.asarray(base_correlation)
        bets = np.asarray(bet_sizes, dtype=float)

        scenarios = []

        # Scenario 1: Uniform high correlation (crisis)
        scenarios.append(self.stress_uniform_correlation(
            probs, corr, bets, stress_rho=0.8, n_sim=n_sim, confidence=confidence,
        ))

        # Scenario 2: Extreme correlation (panic)
        scenarios.append(self.stress_uniform_correlation(
            probs, corr, bets, stress_rho=0.95, n_sim=n_sim, confidence=confidence,
        ))

        # Scenario 3: Double existing correlations
        scenarios.append(self.stress_scaled_correlation(
            probs, corr, bets, scale_factor=2.0, n_sim=n_sim, confidence=confidence,
        ))

        # Scenario 4: Decorrelation (diversification increases)
        scenarios.append(self.stress_scaled_correlation(
            probs, corr, bets, scale_factor=0.0, n_sim=n_sim, confidence=confidence,
        ))

        worst = min(scenarios, key=lambda s: s.stressed_var)
        normal_var = scenarios[0].base_var

        stress_multiplier = abs(worst.stressed_var) / max(abs(normal_var), 1e-10)

        if stress_multiplier > 3.0:
            rec = f"CRITICAL: Reduce position sizes by {int((1 - 1/stress_multiplier) * 100)}%. Portfolio is extremely vulnerable to correlation spikes."
        elif stress_multiplier > 2.0:
            rec = f"WARNING: Consider reducing positions by {int((1 - 1/stress_multiplier) * 100)}%. Moderate correlation risk."
        elif stress_multiplier > 1.5:
            rec = "CAUTION: Portfolio has some correlation concentration. Monitor closely."
        else:
            rec = "OK: Portfolio is well-diversified. Correlation stress impact is manageable."

        return StressTestReport(
            scenarios=scenarios,
            worst_case_var=worst.stressed_var,
            worst_case_scenario=worst.scenario_name,
            normal_var=normal_var,
            stress_multiplier=stress_multiplier,
            recommendation=rec,
        )
