"""
Sequential Monte Carlo (Particle Filters) for Real-Time Bayesian Updating.

Maintains N "particles" - each a hypothesis about the true state - and
reweights them as new data arrives. Unlike conjugate Bayesian updates
(Beta-Bernoulli), particle filters handle:

1. Non-conjugate likelihoods (arbitrary observation models)
2. Multi-modal posteriors (multiple competing hypotheses)
3. Correlated state evolution (joint probability tracking)
4. Non-linear state dynamics

Applications:
- Prediction markets: real-time probability tracking during live events
- Trading: regime detection with smooth transitions
- Portfolio: dynamic correlation estimation

Algorithm: Bootstrap Particle Filter
    1. INITIALIZE: Draw x_0^{(i)} ~ Prior for i=1,...,N
    2. FOR each observation y_t:
       a. PROPAGATE: x_t^{(i)} ~ f(·|x_{t-1}^{(i)})
       b. REWEIGHT: w_t^{(i)} ∝ g(y_t|x_t^{(i)})
       c. NORMALIZE: w̃_t^{(i)} = w_t^{(i)} / Σ_j w_t^{(j)}
       d. RESAMPLE if ESS = 1/Σ(w̃^2) < N/2

References:
- Doucet, de Freitas & Gordon (2001): "Sequential Monte Carlo Methods in Practice"
- Gordon, Salmond & Smith (1993): "Novel approach to nonlinear/non-Gaussian Bayesian state estimation"
- Chopin (2002): "A sequential particle filter method for static models"
"""

import logging
import math
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


def _logit(p: float, eps: float = 1e-6) -> float:
    p = max(eps, min(1.0 - eps, p))
    return math.log(p / (1.0 - p))


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(x, -500, 500)))


@dataclass
class FilterState:
    """Snapshot of filter state at a given time."""
    estimate: float
    ci_lower: float
    ci_upper: float
    ess: float
    n_resamples: int
    observation: float


class ParticleFilter:
    """
    Generic bootstrap particle filter.

    Tracks a hidden state x_t given noisy observations y_t.
    User supplies the transition model and observation likelihood.

    Usage:
        pf = ParticleFilter(
            n_particles=5000,
            transition_fn=lambda x, rng: x + rng.normal(0, 0.1, len(x)),
            log_likelihood_fn=lambda y, x: -0.5 * ((y - x) / 0.05)**2,
        )
        pf.initialize(prior_mean=0.0, prior_std=1.0)
        pf.update(observation=0.5)
        print(pf.estimate())
    """

    def __init__(
        self,
        n_particles: int = 5000,
        transition_fn: Optional[Callable] = None,
        log_likelihood_fn: Optional[Callable] = None,
        seed: Optional[int] = None,
    ):
        self.N = n_particles
        self.transition_fn = transition_fn
        self.log_likelihood_fn = log_likelihood_fn
        self.rng = np.random.default_rng(seed)

        self.particles = np.zeros(n_particles)
        self.weights = np.ones(n_particles) / n_particles
        self.history: List[FilterState] = []
        self._n_resamples = 0

    def initialize(self, prior_mean: float = 0.0, prior_std: float = 1.0):
        """Initialize particles from a Gaussian prior."""
        self.particles = self.rng.normal(prior_mean, prior_std, self.N)
        self.weights = np.ones(self.N) / self.N
        self.history = []
        self._n_resamples = 0

    def update(self, observation: float):
        """Incorporate a new observation via propagate-reweight-resample."""
        # 1. Propagate
        if self.transition_fn is not None:
            self.particles = self.transition_fn(self.particles, self.rng)

        # 2. Reweight
        if self.log_likelihood_fn is not None:
            log_lk = self.log_likelihood_fn(observation, self.particles)
            log_weights = np.log(self.weights + 1e-300) + log_lk
            log_weights -= log_weights.max()  # Numerical stability
            self.weights = np.exp(log_weights)
            self.weights /= self.weights.sum()

        # 3. Check ESS and resample if needed
        ess = self._ess()
        if ess < self.N / 2:
            self._systematic_resample()
            self._n_resamples += 1

        # Record state
        est = self.estimate()
        ci = self.credible_interval()
        self.history.append(FilterState(
            estimate=est,
            ci_lower=ci[0],
            ci_upper=ci[1],
            ess=ess,
            n_resamples=self._n_resamples,
            observation=observation,
        ))

    def estimate(self) -> float:
        """Weighted mean of particles."""
        return float(np.average(self.particles, weights=self.weights))

    def credible_interval(self, alpha: float = 0.05) -> Tuple[float, float]:
        """Weighted quantile-based credible interval."""
        idx = np.argsort(self.particles)
        sorted_p = self.particles[idx]
        sorted_w = self.weights[idx]
        cumw = np.cumsum(sorted_w)
        lower = sorted_p[np.searchsorted(cumw, alpha / 2)]
        upper = sorted_p[np.searchsorted(cumw, 1.0 - alpha / 2)]
        return float(lower), float(upper)

    def _ess(self) -> float:
        """Effective sample size."""
        return float(1.0 / np.sum(self.weights ** 2))

    def _systematic_resample(self):
        """Systematic resampling - lower variance than multinomial."""
        cumsum = np.cumsum(self.weights)
        u = (np.arange(self.N) + self.rng.uniform()) / self.N
        indices = np.searchsorted(cumsum, u)
        indices = np.clip(indices, 0, self.N - 1)
        self.particles = self.particles[indices].copy()
        self.weights = np.ones(self.N) / self.N


class PredictionMarketFilter:
    """
    Particle filter specialized for prediction market probability tracking.

    State: logit(true_probability) - unbounded, supports diffusion models.
    Observation: market price (noisy reading of true probability).

    The filter smooths market noise and propagates uncertainty.
    When the market spikes from $0.58 to $0.65 on a single trade,
    the filter recognizes the true probability may not have changed that much.

    Usage (election night tracker):
        pf = PredictionMarketFilter(prior_prob=0.50, process_vol=0.03)
        pf.update(observed_price=0.55)
        pf.update(observed_price=0.62)
        print(f"Filtered: {pf.estimate():.3f}")
        print(f"95% CI: {pf.credible_interval()}")
    """

    def __init__(
        self,
        n_particles: int = 5000,
        prior_prob: float = 0.5,
        process_vol: float = 0.05,
        obs_noise: float = 0.03,
        seed: Optional[int] = None,
    ):
        self.N = n_particles
        self.process_vol = process_vol
        self.obs_noise = obs_noise
        self.rng = np.random.default_rng(seed)

        # Initialize in logit space
        logit_prior = _logit(prior_prob)
        self.logit_particles = self.rng.normal(logit_prior, 0.5, n_particles)
        self.weights = np.ones(n_particles) / n_particles
        self.history: List[FilterState] = []
        self._n_resamples = 0

    def update(self, observed_price: float):
        """Incorporate a new observation (market price, poll, vote count)."""
        # 1. Propagate: random walk in logit space
        self.logit_particles += self.rng.normal(0, self.process_vol, self.N)

        # 2. Convert to probability space
        prob_particles = _sigmoid(self.logit_particles)

        # 3. Reweight: Gaussian likelihood
        log_lk = -0.5 * ((observed_price - prob_particles) / self.obs_noise) ** 2
        log_weights = np.log(self.weights + 1e-300) + log_lk
        log_weights -= log_weights.max()
        self.weights = np.exp(log_weights)
        self.weights /= self.weights.sum()

        # 4. Resample if ESS low
        ess = 1.0 / np.sum(self.weights ** 2)
        if ess < self.N / 2:
            self._systematic_resample()
            self._n_resamples += 1

        est = self.estimate()
        ci = self.credible_interval()
        self.history.append(FilterState(
            estimate=est,
            ci_lower=ci[0],
            ci_upper=ci[1],
            ess=ess,
            n_resamples=self._n_resamples,
            observation=observed_price,
        ))

    def estimate(self) -> float:
        """Weighted mean probability estimate."""
        probs = _sigmoid(self.logit_particles)
        return float(np.average(probs, weights=self.weights))

    def credible_interval(self, alpha: float = 0.05) -> Tuple[float, float]:
        """Weighted credible interval in probability space."""
        probs = _sigmoid(self.logit_particles)
        idx = np.argsort(probs)
        sorted_p = probs[idx]
        sorted_w = self.weights[idx]
        cumw = np.cumsum(sorted_w)
        lower = sorted_p[np.searchsorted(cumw, alpha / 2)]
        upper = sorted_p[min(np.searchsorted(cumw, 1.0 - alpha / 2), len(sorted_p) - 1)]
        return float(lower), float(upper)

    def _systematic_resample(self):
        cumsum = np.cumsum(self.weights)
        u = (np.arange(self.N) + self.rng.uniform()) / self.N
        indices = np.searchsorted(cumsum, u)
        indices = np.clip(indices, 0, self.N - 1)
        self.logit_particles = self.logit_particles[indices].copy()
        self.weights = np.ones(self.N) / self.N


class MultiContractFilter:
    """
    Joint particle filter for multiple correlated prediction market contracts.

    State: vector of logit(probabilities) for d contracts.
    Handles correlated state evolution (e.g., swing states in an election).

    This is what you need when "Biden wins PA" affects "Biden wins MI" and
    you want to track all probabilities jointly as results come in.

    Usage:
        mcf = MultiContractFilter(
            n_contracts=5,
            prior_probs=[0.52, 0.53, 0.51, 0.48, 0.50],
            correlation=corr_matrix,
        )
        mcf.update(contract_idx=0, observed_price=0.58)  # PA update
        joint_probs = mcf.estimate_all()
        sweep_prob = mcf.estimate_joint_event(lambda p: all(x > 0.5 for x in p))
    """

    def __init__(
        self,
        n_contracts: int,
        prior_probs: List[float],
        correlation: Optional[np.ndarray] = None,
        n_particles: int = 10_000,
        process_vol: float = 0.03,
        obs_noise: float = 0.03,
        seed: Optional[int] = None,
    ):
        self.d = n_contracts
        self.N = n_particles
        self.process_vol = process_vol
        self.obs_noise = obs_noise
        self.rng = np.random.default_rng(seed)

        # Correlation structure for state evolution
        if correlation is not None:
            self.L = np.linalg.cholesky(np.array(correlation))
        else:
            self.L = np.eye(n_contracts)

        # Initialize particles: (N, d) in logit space
        logit_priors = np.array([_logit(p) for p in prior_probs])
        self.particles = self.rng.normal(0, 0.5, (n_particles, n_contracts))
        self.particles += logit_priors
        self.weights = np.ones(n_particles) / n_particles
        self._n_resamples = 0

    def update(self, contract_idx: int, observed_price: float):
        """Update after observing a price for one contract."""
        # 1. Propagate ALL contracts with correlated noise
        Z = self.rng.standard_normal((self.N, self.d))
        correlated_noise = self.process_vol * (Z @ self.L.T)
        self.particles += correlated_noise

        # 2. Reweight based on the observed contract
        prob_particles = _sigmoid(self.particles[:, contract_idx])
        log_lk = -0.5 * ((observed_price - prob_particles) / self.obs_noise) ** 2
        log_weights = np.log(self.weights + 1e-300) + log_lk
        log_weights -= log_weights.max()
        self.weights = np.exp(log_weights)
        self.weights /= self.weights.sum()

        # 3. Resample if needed
        ess = 1.0 / np.sum(self.weights ** 2)
        if ess < self.N / 2:
            self._systematic_resample()
            self._n_resamples += 1

    def update_multiple(self, observations: Dict[int, float]):
        """Update with simultaneous observations for multiple contracts."""
        # Propagate once
        Z = self.rng.standard_normal((self.N, self.d))
        correlated_noise = self.process_vol * (Z @ self.L.T)
        self.particles += correlated_noise

        # Accumulate log-likelihoods from all observations
        log_lk_total = np.zeros(self.N)
        for idx, price in observations.items():
            prob_particles = _sigmoid(self.particles[:, idx])
            log_lk_total += -0.5 * ((price - prob_particles) / self.obs_noise) ** 2

        log_weights = np.log(self.weights + 1e-300) + log_lk_total
        log_weights -= log_weights.max()
        self.weights = np.exp(log_weights)
        self.weights /= self.weights.sum()

        ess = 1.0 / np.sum(self.weights ** 2)
        if ess < self.N / 2:
            self._systematic_resample()
            self._n_resamples += 1

    def estimate_all(self) -> List[float]:
        """Weighted mean probability for each contract."""
        probs = _sigmoid(self.particles)
        return [float(np.average(probs[:, i], weights=self.weights)) for i in range(self.d)]

    def estimate_joint_event(self, event_fn: Callable) -> float:
        """
        Estimate P(joint event) over the particle population.

        event_fn takes a list of d probabilities and returns bool.
        Example: lambda p: all(x > 0.5 for x in p)  # sweep probability
        """
        probs = _sigmoid(self.particles)
        indicators = np.array([
            float(event_fn(probs[i, :].tolist())) for i in range(self.N)
        ])
        return float(np.average(indicators, weights=self.weights))

    def estimate_conditional(
        self, target_idx: int, condition_fn: Callable
    ) -> Optional[float]:
        """
        Estimate P(contract[target_idx] > 0.5 | condition).

        condition_fn takes a list of d probabilities and returns bool.
        """
        probs = _sigmoid(self.particles)
        mask = np.array([
            condition_fn(probs[i, :].tolist()) for i in range(self.N)
        ])
        cond_weights = self.weights * mask
        total_w = cond_weights.sum()
        if total_w < 1e-12:
            return None
        cond_weights /= total_w
        return float(np.average(probs[:, target_idx] > 0.5, weights=cond_weights))

    def _systematic_resample(self):
        cumsum = np.cumsum(self.weights)
        u = (np.arange(self.N) + self.rng.uniform()) / self.N
        indices = np.searchsorted(cumsum, u)
        indices = np.clip(indices, 0, self.N - 1)
        self.particles = self.particles[indices].copy()
        self.weights = np.ones(self.N) / self.N


class TradingRegimeFilter:
    """
    Particle filter for trading regime detection with smooth transitions.

    State: (regime_logit, volatility, trend_strength)
    Observation: (returns, realized_vol, volume)

    Unlike HMM (which assumes discrete jumps), this filter models
    continuous regime transitions - the market gradually shifts from
    bull to bear, or from low-vol to high-vol.

    Usage:
        rf = TradingRegimeFilter(seed=42)
        for ret, vol, volume in daily_data:
            rf.update(ret, vol, volume)
        regime = rf.estimate_regime()
        # regime in {0: low-vol trending, 1: high-vol trending, 2: mean-reverting}
    """

    def __init__(
        self,
        n_particles: int = 5000,
        seed: Optional[int] = None,
    ):
        self.N = n_particles
        self.rng = np.random.default_rng(seed)

        # State: [regime_score, vol_state, trend_state]
        # regime_score: -1 (bear) to +1 (bull)
        # vol_state: log(vol), mean-reverting
        # trend_state: momentum score
        self.particles = np.zeros((n_particles, 3))
        self.particles[:, 0] = self.rng.normal(0, 0.5, n_particles)       # regime
        self.particles[:, 1] = self.rng.normal(-3.0, 0.5, n_particles)    # log-vol (~5%)
        self.particles[:, 2] = self.rng.normal(0, 0.3, n_particles)       # trend

        self.weights = np.ones(n_particles) / n_particles
        self.history: List[Dict] = []
        self._n_resamples = 0

    def update(self, daily_return: float, realized_vol: float, volume_ratio: float = 1.0):
        """
        Update regime estimate with daily market data.

        Args:
            daily_return: Daily log return
            realized_vol: Realized volatility (e.g., 5-day)
            volume_ratio: Volume / average volume (1.0 = normal)
        """
        # 1. Propagate
        # Regime: random walk with slight mean reversion
        self.particles[:, 0] += self.rng.normal(0, 0.05, self.N)
        self.particles[:, 0] *= 0.98  # Slight mean reversion to 0

        # Vol state: OU process toward long-run vol
        long_run_log_vol = -3.0  # ~5% annual
        self.particles[:, 1] += 0.1 * (long_run_log_vol - self.particles[:, 1])
        self.particles[:, 1] += self.rng.normal(0, 0.1, self.N)

        # Trend: momentum with decay
        self.particles[:, 2] *= 0.95
        self.particles[:, 2] += self.rng.normal(0, 0.05, self.N)

        # 2. Reweight
        log_lk = np.zeros(self.N)

        # Return likelihood: conditioned on regime and vol
        expected_return = 0.0003 * self.particles[:, 0]  # ~7.5% annual if regime=1
        vol_particles = np.exp(self.particles[:, 1])
        log_lk += -0.5 * ((daily_return - expected_return) / np.maximum(vol_particles, 1e-6)) ** 2

        # Vol likelihood: realized vol should match vol state
        if realized_vol > 0:
            log_rv = math.log(max(realized_vol, 1e-6))
            log_lk += -0.5 * ((log_rv - self.particles[:, 1]) / 0.3) ** 2

        # Volume: high volume during regime transitions
        if volume_ratio > 1.5:
            # High volume increases weight of particles with extreme regime values
            log_lk += 0.1 * np.abs(self.particles[:, 0])

        log_weights = np.log(self.weights + 1e-300) + log_lk
        log_weights -= log_weights.max()
        self.weights = np.exp(log_weights)
        self.weights /= self.weights.sum()

        # 3. Resample
        ess = 1.0 / np.sum(self.weights ** 2)
        if ess < self.N / 2:
            cumsum = np.cumsum(self.weights)
            u = (np.arange(self.N) + self.rng.uniform()) / self.N
            indices = np.searchsorted(cumsum, u)
            indices = np.clip(indices, 0, self.N - 1)
            self.particles = self.particles[indices].copy()
            self.weights = np.ones(self.N) / self.N
            self._n_resamples += 1

        self.history.append(self.estimate_regime())

    def estimate_regime(self) -> Dict[str, float]:
        """Estimate current regime state."""
        regime = float(np.average(self.particles[:, 0], weights=self.weights))
        vol = float(np.exp(np.average(self.particles[:, 1], weights=self.weights)))
        trend = float(np.average(self.particles[:, 2], weights=self.weights))

        # Classify
        if abs(regime) < 0.3 and vol < 0.15:
            regime_label = "low_vol_ranging"
        elif regime > 0.3:
            regime_label = "bullish_trending"
        elif regime < -0.3:
            regime_label = "bearish_trending"
        elif vol > 0.25:
            regime_label = "high_vol_crisis"
        else:
            regime_label = "transitional"

        return {
            "regime_score": round(regime, 4),
            "volatility": round(vol, 4),
            "trend_strength": round(trend, 4),
            "regime_label": regime_label,
            "ess": round(1.0 / np.sum(self.weights ** 2), 1),
        }
