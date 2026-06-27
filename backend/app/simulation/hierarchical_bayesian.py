"""
Hierarchical Bayesian Models for Prediction Markets.

Implements hierarchical (multi-level) Bayesian models that pool information
across related prediction markets. Key use cases:

1. **National swing model**: Multiple state-level election markets share
   a latent national swing parameter. Observing one state moves all others.

2. **Category pooling**: Weather markets in nearby cities share a spatial
   hyperparameter. Crypto markets share a common sentiment factor.

3. **Volatility shrinkage**: Market-specific volatilities are shrunk toward
   a category-level mean, preventing overfitting on thin markets.

Uses pure NumPy MCMC (Gibbs sampling + Metropolis-Hastings) — no Stan/PyMC
dependency required. This is deliberately lightweight for production use.

References:
- Gelman et al. (2013): "Bayesian Data Analysis" Ch. 5 (Hierarchical Models)
- Efron & Morris (1975): "Data Analysis Using Stein's Estimator"
- Lock & Gelman (2010): "Bayesian Combination of State Polls and Election Forecasts"
"""

import logging
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class HierarchicalEstimate:
    """Result from hierarchical Bayesian estimation."""
    group_estimates: np.ndarray       # Shrunk estimates per market
    group_ci_lower: np.ndarray        # 95% CI lower per market
    group_ci_upper: np.ndarray        # 95% CI upper per market
    raw_estimates: np.ndarray         # Raw (unpooled) estimates
    global_mean: float                # Estimated population mean
    global_std: float                 # Estimated population spread
    shrinkage_factors: np.ndarray     # How much each market was shrunk (0=full, 1=none)
    posterior_samples: np.ndarray     # (n_samples, n_groups) posterior draws
    n_iter: int
    acceptance_rate: float


@dataclass
class SwingModelResult:
    """Result from a national/category swing model."""
    base_probs: np.ndarray            # Pre-swing probabilities per market
    swing_estimate: float             # Estimated common swing in logit space
    swing_std: float                  # Uncertainty on the swing
    adjusted_probs: np.ndarray        # Post-swing adjusted probabilities
    adjusted_ci_lower: np.ndarray
    adjusted_ci_upper: np.ndarray
    correlation_matrix: np.ndarray    # Implied correlation from shared swing
    posterior_swing_samples: np.ndarray


class HierarchicalBayesianModel:
    """
    Hierarchical Bayesian model for pooling information across
    related prediction markets.

    The key insight: when you have K correlated markets (e.g., state
    election outcomes), each market's estimate should be *shrunk* toward
    the group mean. Markets with less data get shrunk more. This is
    the James-Stein / empirical Bayes approach, done properly with MCMC.

    Model:
        theta_k ~ N(mu, tau^2)          # Market-level true probs (logit space)
        y_k | theta_k ~ N(theta_k, sigma^2_k)  # Observed market prices

    Where:
        mu = population mean (estimated)
        tau^2 = between-market variance (estimated)
        sigma^2_k = within-market noise (from order book / volume)
    """

    def __init__(self, seed: Optional[int] = None):
        self._rng = np.random.default_rng(seed)

    @staticmethod
    def _logit(p: np.ndarray) -> np.ndarray:
        p = np.clip(p, 1e-6, 1 - 1e-6)
        return np.log(p / (1 - p))

    @staticmethod
    def _sigmoid(x: np.ndarray) -> np.ndarray:
        return 1.0 / (1.0 + np.exp(-np.clip(x, -20, 20)))

    def fit(
        self,
        observed_probs: np.ndarray,
        observation_noise: Optional[np.ndarray] = None,
        n_iter: int = 5000,
        burn_in: int = 1000,
        thin: int = 2,
    ) -> HierarchicalEstimate:
        """
        Fit hierarchical model to observed market probabilities.

        Args:
            observed_probs: Array of K market probabilities (0 to 1)
            observation_noise: Per-market noise std (in logit space).
                If None, estimated from data spread.
            n_iter: Total MCMC iterations
            burn_in: Iterations to discard
            thin: Keep every thin-th sample

        Returns:
            HierarchicalEstimate with shrunk group estimates and posteriors
        """
        K = len(observed_probs)
        y = self._logit(np.asarray(observed_probs, dtype=float))

        # Observation noise: use provided or estimate from spread
        if observation_noise is not None:
            sigma2 = np.asarray(observation_noise, dtype=float) ** 2
        else:
            sigma2 = np.full(K, max(np.var(y) * 0.5, 0.01))

        # Initialize
        mu = np.mean(y)
        tau2 = max(np.var(y), 0.01)
        theta = y.copy()

        # Storage
        n_keep = (n_iter - burn_in) // thin
        theta_samples = np.zeros((n_keep, K))
        mu_samples = np.zeros(n_keep)
        tau2_samples = np.zeros(n_keep)
        sample_idx = 0
        n_accepted = 0
        n_proposed = 0

        for it in range(n_iter):
            # --- Gibbs step: sample theta_k | mu, tau^2, y ---
            precision = 1.0 / sigma2 + 1.0 / tau2
            V = 1.0 / precision
            theta_hat = V * (y / sigma2 + mu / tau2)
            theta = theta_hat + np.sqrt(V) * self._rng.standard_normal(K)

            # --- Gibbs step: sample mu | theta, tau^2 ---
            prior_var = 100.0
            mu_var = 1.0 / (K / tau2 + 1.0 / prior_var)
            mu_mean = mu_var * (np.sum(theta) / tau2)
            mu = mu_mean + math.sqrt(mu_var) * self._rng.standard_normal()

            # --- Metropolis step: sample tau^2 | theta, mu ---
            n_proposed += 1
            log_tau2 = math.log(tau2)
            proposal_log_tau2 = log_tau2 + 0.3 * self._rng.standard_normal()
            proposal_tau2 = math.exp(proposal_log_tau2)

            def _log_post(t2):
                if t2 <= 0:
                    return -np.inf
                ll = -0.5 * K * math.log(t2) - 0.5 * np.sum((theta - mu) ** 2) / t2
                ll += -2.0 * math.log(t2) - 1.0 / t2  # Inv-Gamma(1,1) prior
                ll += math.log(t2)  # Jacobian for log transform
                return ll

            log_alpha = _log_post(proposal_tau2) - _log_post(tau2)
            if math.log(self._rng.random()) < log_alpha:
                tau2 = proposal_tau2
                n_accepted += 1

            # Store
            if it >= burn_in and (it - burn_in) % thin == 0 and sample_idx < n_keep:
                theta_samples[sample_idx] = theta
                mu_samples[sample_idx] = mu
                tau2_samples[sample_idx] = tau2
                sample_idx += 1

        # Posterior summaries
        theta_mean = np.mean(theta_samples[:sample_idx], axis=0)
        theta_ci_lower = np.percentile(theta_samples[:sample_idx], 2.5, axis=0)
        theta_ci_upper = np.percentile(theta_samples[:sample_idx], 97.5, axis=0)

        group_estimates = self._sigmoid(theta_mean)
        ci_lower = self._sigmoid(theta_ci_lower)
        ci_upper = self._sigmoid(theta_ci_upper)

        # Shrinkage factors
        raw_probs = np.asarray(observed_probs)
        global_mean_prob = self._sigmoid(np.mean(mu_samples[:sample_idx]))
        denom = np.abs(raw_probs - global_mean_prob) + 1e-10
        shrinkage = np.abs(group_estimates - global_mean_prob) / denom
        shrinkage = np.clip(shrinkage, 0, 1)

        return HierarchicalEstimate(
            group_estimates=group_estimates,
            group_ci_lower=ci_lower,
            group_ci_upper=ci_upper,
            raw_estimates=raw_probs,
            global_mean=global_mean_prob,
            global_std=float(np.sqrt(np.mean(tau2_samples[:sample_idx]))),
            shrinkage_factors=shrinkage,
            posterior_samples=self._sigmoid(theta_samples[:sample_idx]),
            n_iter=n_iter,
            acceptance_rate=n_accepted / max(n_proposed, 1),
        )


class NationalSwingModel:
    """
    Models a shared latent swing factor across correlated prediction markets.

    Classic use case: US election state markets. If the national mood
    shifts +2% Democratic, all state probabilities shift — but by different
    amounts depending on each state's elasticity.

    Model:
        delta ~ N(0, sigma_swing^2)               # National swing
        p_k = sigmoid(logit(p0_k) + beta_k * delta)  # Adjusted probability
        y_k ~ N(logit(p_k), sigma_obs^2)           # Observed market price
    """

    def __init__(self, seed: Optional[int] = None):
        self._rng = np.random.default_rng(seed)

    @staticmethod
    def _logit(p):
        p = np.clip(p, 1e-6, 1 - 1e-6)
        return np.log(p / (1 - p))

    @staticmethod
    def _sigmoid(x):
        return 1.0 / (1.0 + np.exp(-np.clip(x, -20, 20)))

    def estimate_swing(
        self,
        base_probs: np.ndarray,
        observed_probs: np.ndarray,
        elasticities: Optional[np.ndarray] = None,
        obs_noise: float = 0.05,
        swing_prior_std: float = 0.3,
        n_iter: int = 5000,
        burn_in: int = 1000,
    ) -> SwingModelResult:
        """
        Estimate the common swing factor from observed market prices.

        Args:
            base_probs: Prior/baseline probabilities per market
            observed_probs: Current market prices
            elasticities: Per-market swing sensitivities (default: all 1.0)
            obs_noise: Observation noise std in logit space
            swing_prior_std: Prior std on the swing parameter
        """
        K = len(base_probs)
        base_logit = self._logit(np.asarray(base_probs, dtype=float))
        obs_logit = self._logit(np.asarray(observed_probs, dtype=float))

        if elasticities is None:
            elasticities = np.ones(K)
        else:
            elasticities = np.asarray(elasticities, dtype=float)

        sigma2_obs = obs_noise ** 2
        sigma2_swing = swing_prior_std ** 2

        swing_samples = np.zeros(n_iter - burn_in)
        residuals = obs_logit - base_logit

        for it in range(n_iter):
            precision = np.sum(elasticities ** 2) / sigma2_obs + 1.0 / sigma2_swing
            V_delta = 1.0 / precision
            delta_hat = V_delta * np.sum(elasticities * residuals) / sigma2_obs
            delta = delta_hat + math.sqrt(V_delta) * self._rng.standard_normal()

            if it >= burn_in:
                swing_samples[it - burn_in] = delta

        swing_mean = float(np.mean(swing_samples))
        swing_std = float(np.std(swing_samples))

        adjusted_logit = base_logit + elasticities * swing_mean
        adjusted_probs = self._sigmoid(adjusted_logit)

        adj_logit_samples = base_logit[None, :] + elasticities[None, :] * swing_samples[:, None]
        adj_prob_samples = self._sigmoid(adj_logit_samples)
        ci_lower = np.percentile(adj_prob_samples, 2.5, axis=0)
        ci_upper = np.percentile(adj_prob_samples, 97.5, axis=0)

        # Implied correlation from shared swing factor
        var_total = elasticities ** 2 * sigma2_swing + sigma2_obs
        corr = np.outer(elasticities, elasticities) * sigma2_swing / np.sqrt(np.outer(var_total, var_total))
        np.fill_diagonal(corr, 1.0)

        return SwingModelResult(
            base_probs=np.asarray(base_probs),
            swing_estimate=swing_mean,
            swing_std=swing_std,
            adjusted_probs=adjusted_probs,
            adjusted_ci_lower=ci_lower,
            adjusted_ci_upper=ci_upper,
            correlation_matrix=corr,
            posterior_swing_samples=swing_samples,
        )


class CategoryPoolingModel:
    """
    Pools volatility and probability estimates across markets in the same category.

    Example: 10 weather temperature markets for different cities. Each has
    few trades, but they share a common weather system. The hierarchical
    model borrows strength across cities.
    """

    def __init__(self, seed: Optional[int] = None):
        self._hierarchical = HierarchicalBayesianModel(seed=seed)
        self._rng = np.random.default_rng(seed)

    def pool_probabilities(
        self,
        market_probs: Dict[str, float],
        market_volumes: Optional[Dict[str, float]] = None,
        n_iter: int = 5000,
    ) -> Dict[str, Dict]:
        """
        Pool probability estimates across markets in a category.

        Args:
            market_probs: {market_id: observed_probability}
            market_volumes: {market_id: total_volume} (higher volume = less noise)

        Returns:
            {market_id: {"pooled_prob", "raw_prob", "ci_lower", "ci_upper", "shrinkage"}}
        """
        ids = list(market_probs.keys())
        probs = np.array([market_probs[k] for k in ids])

        if market_volumes:
            volumes = np.array([market_volumes.get(k, 1000) for k in ids])
            noise = 0.5 / np.sqrt(np.maximum(volumes, 1))
        else:
            noise = None

        result = self._hierarchical.fit(probs, observation_noise=noise, n_iter=n_iter)

        return {
            ids[i]: {
                "pooled_prob": float(result.group_estimates[i]),
                "raw_prob": float(result.raw_estimates[i]),
                "ci_lower": float(result.group_ci_lower[i]),
                "ci_upper": float(result.group_ci_upper[i]),
                "shrinkage": float(result.shrinkage_factors[i]),
            }
            for i in range(len(ids))
        }

    def pool_volatilities(
        self,
        market_vols: Dict[str, float],
        market_n_obs: Optional[Dict[str, int]] = None,
        n_iter: int = 5000,
    ) -> Dict[str, Dict]:
        """
        Pool volatility estimates (useful for Kelly sizing and pricing).

        Thin markets get their vol estimate shrunk toward the category mean.
        """
        ids = list(market_vols.keys())
        vols = np.array([market_vols[k] for k in ids])

        log_vols = np.log(np.maximum(vols, 1e-6))

        if market_n_obs:
            n_obs = np.array([market_n_obs.get(k, 10) for k in ids])
            noise = 1.0 / np.sqrt(np.maximum(n_obs, 1))
        else:
            noise = None

        # Map log-vols to (0,1) via sigmoid for the hierarchical model
        result = self._hierarchical.fit(
            observed_probs=1.0 / (1.0 + np.exp(-log_vols)),
            observation_noise=noise,
            n_iter=n_iter,
        )

        pooled_log_vols = np.log(result.group_estimates / (1 - result.group_estimates + 1e-10))
        pooled_vols = np.exp(pooled_log_vols)

        return {
            ids[i]: {
                "pooled_vol": float(pooled_vols[i]),
                "raw_vol": float(vols[i]),
                "shrinkage": float(result.shrinkage_factors[i]),
            }
            for i in range(len(ids))
        }
