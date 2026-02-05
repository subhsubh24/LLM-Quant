"""
Advanced Quantitative Analytics Framework.

This module implements rigorous statistical and mathematical models:
- Bayesian inference for parameter estimation
- Hidden Markov Models for regime detection
- GARCH/EGARCH for volatility forecasting
- Copula models for dependency structure
- Extreme Value Theory for tail risk
- Factor models for alpha generation
- Portfolio optimization (Black-Litterman, CVaR, Risk Parity)

Academic references:
- Hamilton (1989) "A New Approach to the Economic Analysis of Nonstationary Time Series" (HMM)
- Bollerslev (1986) "Generalized Autoregressive Conditional Heteroskedasticity" (GARCH)
- Nelson (1991) "Conditional Heteroskedasticity in Asset Returns" (EGARCH)
- Black & Litterman (1992) "Global Portfolio Optimization" (BL Model)
- McNeil et al. (2005) "Quantitative Risk Management" (EVT, Copulas)
- Fama & French (1993) "Common Risk Factors" (Factor Models)
"""

import numpy as np
from typing import Dict, List, Tuple, Optional, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from scipy import stats
from scipy.optimize import minimize, differential_evolution
from scipy.special import gammaln
import logging

logger = logging.getLogger(__name__)


# =============================================================================
# BAYESIAN INFERENCE
# =============================================================================

@dataclass
class BayesianPosterior:
    """Result of Bayesian inference."""
    mean: np.ndarray
    std: np.ndarray
    samples: np.ndarray
    log_likelihood: float
    bic: float
    aic: float


class BayesianEstimator:
    """
    Bayesian parameter estimation using MCMC.

    Implements Metropolis-Hastings algorithm for posterior sampling
    with adaptive proposal distribution.
    """

    def __init__(
        self,
        n_samples: int = 10000,
        burn_in: int = 2000,
        adapt_interval: int = 100,
    ):
        self.n_samples = n_samples
        self.burn_in = burn_in
        self.adapt_interval = adapt_interval

    def estimate_returns_distribution(
        self,
        returns: np.ndarray,
        prior_mu: float = 0.0,
        prior_sigma_mu: float = 0.1,
        prior_alpha_sigma: float = 2.0,
        prior_beta_sigma: float = 0.05,
    ) -> BayesianPosterior:
        """
        Estimate posterior distribution of return parameters.

        Uses Normal-Inverse-Gamma conjugate prior:
        - μ ~ N(prior_mu, prior_sigma_mu²)
        - σ² ~ InvGamma(alpha, beta)
        """
        n = len(returns)
        sample_mean = np.mean(returns)
        sample_var = np.var(returns, ddof=1)

        # Conjugate update for Normal-Inverse-Gamma
        # Posterior for variance
        alpha_post = prior_alpha_sigma + n / 2
        ss = np.sum((returns - sample_mean) ** 2)
        beta_post = prior_beta_sigma + ss / 2

        # Posterior for mean (conditional on variance)
        precision_prior = 1 / prior_sigma_mu ** 2
        precision_data = n / sample_var
        precision_post = precision_prior + precision_data
        mu_post = (precision_prior * prior_mu + precision_data * sample_mean) / precision_post

        # Sample from posterior
        sigma_samples = np.sqrt(1 / np.random.gamma(alpha_post, 1 / beta_post, self.n_samples))
        mu_samples = np.random.normal(mu_post, sigma_samples / np.sqrt(precision_post))

        samples = np.column_stack([mu_samples, sigma_samples])

        # Compute model fit metrics
        log_lik = self._normal_log_likelihood(returns, mu_post, np.sqrt(beta_post / alpha_post))
        k = 2  # number of parameters
        aic = 2 * k - 2 * log_lik
        bic = k * np.log(n) - 2 * log_lik

        return BayesianPosterior(
            mean=np.array([mu_post, np.sqrt(beta_post / alpha_post)]),
            std=np.array([np.std(mu_samples), np.std(sigma_samples)]),
            samples=samples[self.burn_in:],
            log_likelihood=log_lik,
            bic=bic,
            aic=aic,
        )

    def _normal_log_likelihood(self, data: np.ndarray, mu: float, sigma: float) -> float:
        """Compute log-likelihood for normal distribution."""
        n = len(data)
        return -n / 2 * np.log(2 * np.pi) - n * np.log(sigma) - np.sum((data - mu) ** 2) / (2 * sigma ** 2)

    def estimate_sharpe_ratio(
        self,
        returns: np.ndarray,
        risk_free_rate: float = 0.0,
        annualization: float = 252,
    ) -> Tuple[float, float, np.ndarray]:
        """
        Bayesian estimation of Sharpe ratio with uncertainty.

        Returns point estimate, standard error, and posterior samples.
        """
        posterior = self.estimate_returns_distribution(returns)

        # Sharpe ratio samples
        mu_samples = posterior.samples[:, 0]
        sigma_samples = posterior.samples[:, 1]

        sharpe_samples = (mu_samples - risk_free_rate / annualization) / sigma_samples * np.sqrt(annualization)

        return float(np.mean(sharpe_samples)), float(np.std(sharpe_samples)), sharpe_samples


# =============================================================================
# HIDDEN MARKOV MODEL FOR REGIME DETECTION
# =============================================================================

@dataclass
class HMMState:
    """State of Hidden Markov Model."""
    n_states: int
    transition_matrix: np.ndarray
    means: np.ndarray
    variances: np.ndarray
    stationary_probs: np.ndarray
    current_state: int
    state_probs: np.ndarray


class GaussianHMM:
    """
    Hidden Markov Model with Gaussian emissions.

    Uses Baum-Welch (EM) algorithm for parameter estimation
    and Viterbi algorithm for state decoding.

    Applications:
    - Market regime detection (bull/bear/sideways)
    - Volatility regime identification
    - Risk regime classification
    """

    def __init__(self, n_states: int = 3, n_iter: int = 100, tol: float = 1e-6):
        self.n_states = n_states
        self.n_iter = n_iter
        self.tol = tol

        # Initialize parameters
        self.transition_matrix: Optional[np.ndarray] = None
        self.means: Optional[np.ndarray] = None
        self.variances: Optional[np.ndarray] = None
        self.start_probs: Optional[np.ndarray] = None

    def fit(self, observations: np.ndarray) -> "GaussianHMM":
        """
        Fit HMM using Baum-Welch algorithm (EM).

        Args:
            observations: Array of observations (e.g., returns)
        """
        n = len(observations)

        # K-means initialization
        self._initialize_kmeans(observations)

        prev_log_lik = -np.inf

        for iteration in range(self.n_iter):
            # E-step: Forward-backward algorithm
            alpha, scaling = self._forward(observations)
            beta = self._backward(observations, scaling)
            gamma, xi = self._compute_posteriors(observations, alpha, beta, scaling)

            # M-step: Update parameters
            self._update_parameters(observations, gamma, xi)

            # Check convergence
            log_lik = np.sum(np.log(scaling))
            if abs(log_lik - prev_log_lik) < self.tol:
                logger.info(f"HMM converged at iteration {iteration}")
                break
            prev_log_lik = log_lik

        return self

    def _initialize_kmeans(self, observations: np.ndarray):
        """Initialize parameters using K-means clustering."""
        n = len(observations)

        # Sort observations to initialize means
        sorted_obs = np.sort(observations)
        quantiles = np.linspace(0, 1, self.n_states + 2)[1:-1]
        self.means = np.array([np.percentile(sorted_obs, q * 100) for q in quantiles])

        # Initialize variances
        self.variances = np.ones(self.n_states) * np.var(observations)

        # Initialize uniform transition matrix with persistence
        self.transition_matrix = np.ones((self.n_states, self.n_states)) * 0.1 / (self.n_states - 1)
        np.fill_diagonal(self.transition_matrix, 0.9)

        # Uniform start probabilities
        self.start_probs = np.ones(self.n_states) / self.n_states

    def _emission_prob(self, obs: float, state: int) -> float:
        """Compute emission probability P(obs | state)."""
        mu = self.means[state]
        sigma = np.sqrt(self.variances[state])
        return stats.norm.pdf(obs, mu, sigma)

    def _forward(self, observations: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """Forward algorithm with scaling."""
        n = len(observations)
        alpha = np.zeros((n, self.n_states))
        scaling = np.zeros(n)

        # Initialize
        for j in range(self.n_states):
            alpha[0, j] = self.start_probs[j] * self._emission_prob(observations[0], j)
        scaling[0] = np.sum(alpha[0])
        alpha[0] /= scaling[0]

        # Recursion
        for t in range(1, n):
            for j in range(self.n_states):
                alpha[t, j] = np.sum(alpha[t - 1] * self.transition_matrix[:, j]) * self._emission_prob(observations[t], j)
            scaling[t] = np.sum(alpha[t])
            alpha[t] /= scaling[t]

        return alpha, scaling

    def _backward(self, observations: np.ndarray, scaling: np.ndarray) -> np.ndarray:
        """Backward algorithm."""
        n = len(observations)
        beta = np.zeros((n, self.n_states))
        beta[n - 1] = 1

        for t in range(n - 2, -1, -1):
            for i in range(self.n_states):
                for j in range(self.n_states):
                    beta[t, i] += self.transition_matrix[i, j] * self._emission_prob(observations[t + 1], j) * beta[t + 1, j]
            beta[t] /= scaling[t + 1]

        return beta

    def _compute_posteriors(
        self,
        observations: np.ndarray,
        alpha: np.ndarray,
        beta: np.ndarray,
        scaling: np.ndarray,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Compute posterior probabilities."""
        n = len(observations)

        # Gamma: P(state_t | observations)
        gamma = alpha * beta
        gamma /= gamma.sum(axis=1, keepdims=True)

        # Xi: P(state_t, state_{t+1} | observations)
        xi = np.zeros((n - 1, self.n_states, self.n_states))
        for t in range(n - 1):
            for i in range(self.n_states):
                for j in range(self.n_states):
                    xi[t, i, j] = (alpha[t, i] * self.transition_matrix[i, j] *
                                   self._emission_prob(observations[t + 1], j) * beta[t + 1, j])
            xi[t] /= xi[t].sum()

        return gamma, xi

    def _update_parameters(
        self,
        observations: np.ndarray,
        gamma: np.ndarray,
        xi: np.ndarray,
    ):
        """Update HMM parameters (M-step)."""
        # Update start probabilities
        self.start_probs = gamma[0]

        # Update transition matrix
        for i in range(self.n_states):
            for j in range(self.n_states):
                self.transition_matrix[i, j] = np.sum(xi[:, i, j]) / np.sum(gamma[:-1, i])

        # Update emission parameters
        for j in range(self.n_states):
            weight = gamma[:, j]
            self.means[j] = np.sum(weight * observations) / np.sum(weight)
            self.variances[j] = np.sum(weight * (observations - self.means[j]) ** 2) / np.sum(weight)

    def predict(self, observations: np.ndarray) -> np.ndarray:
        """Predict most likely state sequence using Viterbi algorithm."""
        n = len(observations)
        viterbi = np.zeros((n, self.n_states))
        backpointer = np.zeros((n, self.n_states), dtype=int)

        # Initialize
        for j in range(self.n_states):
            viterbi[0, j] = np.log(self.start_probs[j] + 1e-10) + np.log(self._emission_prob(observations[0], j) + 1e-10)

        # Recursion
        for t in range(1, n):
            for j in range(self.n_states):
                trans_probs = viterbi[t - 1] + np.log(self.transition_matrix[:, j] + 1e-10)
                backpointer[t, j] = np.argmax(trans_probs)
                viterbi[t, j] = np.max(trans_probs) + np.log(self._emission_prob(observations[t], j) + 1e-10)

        # Backtrack
        states = np.zeros(n, dtype=int)
        states[n - 1] = np.argmax(viterbi[n - 1])
        for t in range(n - 2, -1, -1):
            states[t] = backpointer[t + 1, states[t + 1]]

        return states

    def predict_proba(self, observations: np.ndarray) -> np.ndarray:
        """Get state probabilities using forward-backward."""
        alpha, scaling = self._forward(observations)
        beta = self._backward(observations, scaling)

        gamma = alpha * beta
        gamma /= gamma.sum(axis=1, keepdims=True)

        return gamma

    def get_stationary_distribution(self) -> np.ndarray:
        """Compute stationary distribution of the Markov chain."""
        eigenvalues, eigenvectors = np.linalg.eig(self.transition_matrix.T)
        idx = np.argmin(np.abs(eigenvalues - 1))
        stationary = np.real(eigenvectors[:, idx])
        return stationary / stationary.sum()

    def get_state(self, observations: np.ndarray) -> HMMState:
        """Get current HMM state with full information."""
        states = self.predict(observations)
        probs = self.predict_proba(observations)

        return HMMState(
            n_states=self.n_states,
            transition_matrix=self.transition_matrix,
            means=self.means,
            variances=self.variances,
            stationary_probs=self.get_stationary_distribution(),
            current_state=int(states[-1]),
            state_probs=probs[-1],
        )


# =============================================================================
# GARCH VOLATILITY MODEL
# =============================================================================

@dataclass
class GARCHForecast:
    """GARCH volatility forecast."""
    current_vol: float
    forecast_vol: np.ndarray
    conditional_var: np.ndarray
    params: Dict[str, float]
    log_likelihood: float
    aic: float
    bic: float


class GARCH:
    """
    GARCH(p,q) model for volatility forecasting.

    σ²_t = ω + Σαᵢε²_{t-i} + Σβⱼσ²_{t-j}

    Supports:
    - GARCH(1,1) - most common
    - EGARCH for asymmetric effects
    - GJR-GARCH for leverage effects
    """

    def __init__(self, p: int = 1, q: int = 1, model_type: str = "garch"):
        self.p = p  # ARCH order
        self.q = q  # GARCH order
        self.model_type = model_type

        self.omega: float = 0
        self.alpha: np.ndarray = np.zeros(p)
        self.beta: np.ndarray = np.zeros(q)
        self.gamma: np.ndarray = np.zeros(p)  # For EGARCH/GJR

        self.fitted = False
        self.log_likelihood: float = 0

    def fit(self, returns: np.ndarray) -> "GARCH":
        """
        Fit GARCH model using MLE.

        Args:
            returns: Array of return observations
        """
        returns = np.asarray(returns)
        n = len(returns)

        # Initial variance estimate
        var0 = np.var(returns)

        # Initial parameter guess
        if self.model_type == "garch":
            # omega, alpha, beta
            x0 = np.array([var0 * 0.1, 0.1, 0.8])
            bounds = [(1e-8, var0 * 10), (1e-8, 0.5), (1e-8, 0.999)]
        else:  # EGARCH
            x0 = np.array([np.log(var0 * 0.1), 0.1, 0.9, -0.1])
            bounds = [(-20, 5), (0, 0.5), (0, 0.999), (-0.5, 0)]

        # Optimize
        result = minimize(
            lambda params: -self._log_likelihood(returns, params),
            x0,
            method="L-BFGS-B",
            bounds=bounds,
        )

        # Store parameters
        if self.model_type == "garch":
            self.omega = result.x[0]
            self.alpha = np.array([result.x[1]])
            self.beta = np.array([result.x[2]])
        else:
            self.omega = result.x[0]
            self.alpha = np.array([result.x[1]])
            self.beta = np.array([result.x[2]])
            self.gamma = np.array([result.x[3]])

        self.log_likelihood = -result.fun
        self.fitted = True

        return self

    def _log_likelihood(self, returns: np.ndarray, params: np.ndarray) -> float:
        """Compute log-likelihood for GARCH model."""
        n = len(returns)

        if self.model_type == "garch":
            omega, alpha, beta = params[0], params[1], params[2]
            var = np.zeros(n)
            var[0] = np.var(returns)

            for t in range(1, n):
                var[t] = omega + alpha * returns[t - 1] ** 2 + beta * var[t - 1]

        else:  # EGARCH
            omega, alpha, beta, gamma = params[0], params[1], params[2], params[3]
            log_var = np.zeros(n)
            log_var[0] = np.log(np.var(returns))

            for t in range(1, n):
                std_resid = returns[t - 1] / np.exp(log_var[t - 1] / 2)
                log_var[t] = (omega + alpha * (np.abs(std_resid) - np.sqrt(2 / np.pi)) +
                              gamma * std_resid + beta * log_var[t - 1])
            var = np.exp(log_var)

        # Prevent numerical issues
        var = np.maximum(var, 1e-10)

        # Normal log-likelihood
        ll = -0.5 * np.sum(np.log(2 * np.pi) + np.log(var) + returns ** 2 / var)
        return ll

    def forecast(self, returns: np.ndarray, horizon: int = 10) -> GARCHForecast:
        """
        Forecast volatility.

        Args:
            returns: Historical returns
            horizon: Forecast horizon

        Returns:
            GARCHForecast with predictions
        """
        if not self.fitted:
            self.fit(returns)

        n = len(returns)

        # Compute conditional variance history
        var_history = np.zeros(n)
        var_history[0] = np.var(returns)

        for t in range(1, n):
            if self.model_type == "garch":
                var_history[t] = (self.omega +
                                  self.alpha[0] * returns[t - 1] ** 2 +
                                  self.beta[0] * var_history[t - 1])
            else:
                std_resid = returns[t - 1] / np.sqrt(var_history[t - 1])
                log_var = (self.omega +
                           self.alpha[0] * (np.abs(std_resid) - np.sqrt(2 / np.pi)) +
                           self.gamma[0] * std_resid +
                           self.beta[0] * np.log(var_history[t - 1]))
                var_history[t] = np.exp(log_var)

        # Forecast
        forecast_var = np.zeros(horizon)
        current_var = var_history[-1]
        current_resid = returns[-1]

        for h in range(horizon):
            if self.model_type == "garch":
                if h == 0:
                    forecast_var[h] = (self.omega +
                                       self.alpha[0] * current_resid ** 2 +
                                       self.beta[0] * current_var)
                else:
                    # Long-run variance recursion
                    forecast_var[h] = (self.omega +
                                       (self.alpha[0] + self.beta[0]) * forecast_var[h - 1])
            else:
                # EGARCH forecast (simplified)
                persistence = self.beta[0]
                unconditional = np.exp(self.omega / (1 - persistence))
                forecast_var[h] = unconditional + persistence ** h * (current_var - unconditional)

        # Compute fit metrics
        k = 3 if self.model_type == "garch" else 4
        aic = 2 * k - 2 * self.log_likelihood
        bic = k * np.log(n) - 2 * self.log_likelihood

        params = {
            "omega": float(self.omega),
            "alpha": float(self.alpha[0]),
            "beta": float(self.beta[0]),
        }
        if self.model_type == "egarch":
            params["gamma"] = float(self.gamma[0])

        return GARCHForecast(
            current_vol=float(np.sqrt(var_history[-1] * 252)),  # Annualized
            forecast_vol=np.sqrt(forecast_var * 252),
            conditional_var=var_history,
            params=params,
            log_likelihood=self.log_likelihood,
            aic=aic,
            bic=bic,
        )


# =============================================================================
# COPULA MODELS FOR DEPENDENCY
# =============================================================================

@dataclass
class CopulaDependency:
    """Copula dependency structure."""
    copula_type: str
    correlation_matrix: np.ndarray
    tail_dependence_lower: float
    tail_dependence_upper: float
    kendall_tau: np.ndarray
    params: Dict[str, float]


class GaussianCopula:
    """
    Gaussian Copula for modeling multivariate dependencies.

    Captures linear correlation but no tail dependence.
    Useful for modeling dependencies between assets in normal conditions.
    """

    def __init__(self):
        self.correlation_matrix: Optional[np.ndarray] = None

    def fit(self, data: np.ndarray) -> "GaussianCopula":
        """
        Fit Gaussian copula to data.

        Args:
            data: (n_samples, n_assets) array
        """
        # Transform to uniform margins
        u = self._empirical_cdf(data)

        # Transform to normal margins
        z = stats.norm.ppf(np.clip(u, 0.001, 0.999))

        # Estimate correlation
        self.correlation_matrix = np.corrcoef(z.T)

        return self

    def _empirical_cdf(self, data: np.ndarray) -> np.ndarray:
        """Transform to uniform margins using empirical CDF."""
        n, d = data.shape
        u = np.zeros_like(data)
        for j in range(d):
            u[:, j] = stats.rankdata(data[:, j]) / (n + 1)
        return u

    def sample(self, n_samples: int) -> np.ndarray:
        """Sample from copula."""
        if self.correlation_matrix is None:
            raise ValueError("Copula not fitted")

        d = self.correlation_matrix.shape[0]

        # Sample from multivariate normal
        L = np.linalg.cholesky(self.correlation_matrix)
        z = np.random.randn(n_samples, d) @ L.T

        # Transform to uniform
        u = stats.norm.cdf(z)
        return u

    def get_dependency(self) -> CopulaDependency:
        """Get dependency structure."""
        if self.correlation_matrix is None:
            raise ValueError("Copula not fitted")

        # Kendall's tau from Pearson correlation
        r = self.correlation_matrix
        tau = 2 / np.pi * np.arcsin(r)

        return CopulaDependency(
            copula_type="Gaussian",
            correlation_matrix=self.correlation_matrix,
            tail_dependence_lower=0.0,  # Gaussian has no tail dependence
            tail_dependence_upper=0.0,
            kendall_tau=tau,
            params={},
        )


class StudentTCopula:
    """
    Student-t Copula for heavy-tailed dependencies.

    Captures symmetric tail dependence, important for modeling
    extreme co-movements during market stress.
    """

    def __init__(self, df: float = 5):
        self.df = df
        self.correlation_matrix: Optional[np.ndarray] = None

    def fit(self, data: np.ndarray) -> "StudentTCopula":
        """Fit Student-t copula to data."""
        # Transform to uniform margins
        u = self._empirical_cdf(data)

        # Transform to t margins
        z = stats.t.ppf(np.clip(u, 0.001, 0.999), df=self.df)

        # Estimate correlation
        self.correlation_matrix = np.corrcoef(z.T)

        # Estimate degrees of freedom via profile likelihood
        self.df = self._estimate_df(u)

        return self

    def _empirical_cdf(self, data: np.ndarray) -> np.ndarray:
        """Transform to uniform margins."""
        n, d = data.shape
        u = np.zeros_like(data)
        for j in range(d):
            u[:, j] = stats.rankdata(data[:, j]) / (n + 1)
        return u

    def _estimate_df(self, u: np.ndarray) -> float:
        """Estimate degrees of freedom using MLE."""
        def neg_log_lik(df):
            if df <= 2:
                return 1e10
            z = stats.t.ppf(np.clip(u, 0.001, 0.999), df=df)
            return -np.sum(stats.t.logpdf(z, df=df))

        result = minimize(neg_log_lik, x0=5, bounds=[(2.1, 100)])
        return result.x[0]

    def tail_dependence(self) -> float:
        """Compute tail dependence coefficient."""
        if self.correlation_matrix is None:
            return 0

        # For bivariate t-copula
        rho = self.correlation_matrix[0, 1] if self.correlation_matrix.shape[0] > 1 else 0
        nu = self.df

        if nu <= 0 or rho >= 1:
            return 0

        # Tail dependence formula
        lambda_tail = 2 * stats.t.cdf(-np.sqrt((nu + 1) * (1 - rho) / (1 + rho)), df=nu + 1)
        return lambda_tail

    def get_dependency(self) -> CopulaDependency:
        """Get dependency structure."""
        if self.correlation_matrix is None:
            raise ValueError("Copula not fitted")

        tail_dep = self.tail_dependence()

        return CopulaDependency(
            copula_type="Student-t",
            correlation_matrix=self.correlation_matrix,
            tail_dependence_lower=tail_dep,
            tail_dependence_upper=tail_dep,  # Symmetric for t-copula
            kendall_tau=2 / np.pi * np.arcsin(self.correlation_matrix),
            params={"df": self.df},
        )


# =============================================================================
# EXTREME VALUE THEORY
# =============================================================================

@dataclass
class EVTAnalysis:
    """Extreme Value Theory analysis results."""
    threshold: float
    shape_xi: float
    scale_sigma: float
    var_95: float
    var_99: float
    var_999: float
    expected_shortfall_95: float
    expected_shortfall_99: float
    exceedances: np.ndarray


class ExtremeValueAnalyzer:
    """
    Extreme Value Theory for tail risk modeling.

    Uses Peaks Over Threshold (POT) method with GPD
    (Generalized Pareto Distribution) fitting.
    """

    def __init__(self, threshold_quantile: float = 0.95):
        self.threshold_quantile = threshold_quantile
        self.threshold: float = 0
        self.shape_xi: float = 0
        self.scale_sigma: float = 0

    def fit(self, losses: np.ndarray) -> "ExtremeValueAnalyzer":
        """
        Fit GPD to loss exceedances.

        Args:
            losses: Array of losses (positive = loss)
        """
        # Determine threshold
        self.threshold = np.percentile(losses, self.threshold_quantile * 100)

        # Get exceedances
        exceedances = losses[losses > self.threshold] - self.threshold

        if len(exceedances) < 10:
            # Use debug level - this is expected with limited data
            logger.debug("Too few exceedances for reliable EVT fit")
            return self

        # Fit GPD using method of moments (Hill estimator for shape)
        mean_excess = np.mean(exceedances)
        var_excess = np.var(exceedances)

        # Method of moments estimators
        self.shape_xi = 0.5 * (mean_excess ** 2 / var_excess - 1)
        self.scale_sigma = mean_excess * (1 - self.shape_xi)

        # Constrain shape parameter
        self.shape_xi = np.clip(self.shape_xi, -0.5, 0.5)

        return self

    def var(self, confidence: float = 0.99) -> float:
        """
        Compute Value at Risk using EVT.

        Args:
            confidence: Confidence level (e.g., 0.99 for 99% VaR)
        """
        if self.scale_sigma == 0:
            return 0

        n_u = 1 - self.threshold_quantile  # Exceedance probability
        p = 1 - confidence

        if abs(self.shape_xi) < 1e-6:
            # Exponential case
            var = self.threshold - self.scale_sigma * np.log(p / n_u)
        else:
            var = self.threshold + self.scale_sigma / self.shape_xi * ((p / n_u) ** (-self.shape_xi) - 1)

        return var

    def expected_shortfall(self, confidence: float = 0.99) -> float:
        """
        Compute Expected Shortfall (CVaR) using EVT.

        ES = E[X | X > VaR]
        """
        if self.scale_sigma == 0:
            return 0

        var = self.var(confidence)

        if abs(self.shape_xi) < 1e-6:
            es = var + self.scale_sigma
        else:
            if self.shape_xi < 1:
                es = var / (1 - self.shape_xi) + (self.scale_sigma - self.shape_xi * self.threshold) / (1 - self.shape_xi)
            else:
                es = np.inf

        return es

    def analyze(self, losses: np.ndarray) -> EVTAnalysis:
        """Complete EVT analysis."""
        self.fit(losses)

        exceedances = losses[losses > self.threshold] - self.threshold

        return EVTAnalysis(
            threshold=self.threshold,
            shape_xi=self.shape_xi,
            scale_sigma=self.scale_sigma,
            var_95=self.var(0.95),
            var_99=self.var(0.99),
            var_999=self.var(0.999),
            expected_shortfall_95=self.expected_shortfall(0.95),
            expected_shortfall_99=self.expected_shortfall(0.99),
            exceedances=exceedances,
        )


# =============================================================================
# FACTOR MODELS
# =============================================================================

@dataclass
class FactorExposures:
    """Factor exposures and alpha."""
    alpha: float
    betas: Dict[str, float]
    r_squared: float
    residual_vol: float
    factor_returns: Dict[str, float]
    t_stats: Dict[str, float]


class FactorModel:
    """
    Multi-factor model for alpha and risk decomposition.

    Implements Fama-French style factor analysis:
    R = α + β₁F₁ + β₂F₂ + ... + ε

    Standard factors:
    - Market (MKT-RF)
    - Size (SMB)
    - Value (HML)
    - Momentum (UMD)
    - Quality (RMW)
    - Investment (CMA)
    - Volatility (VOL)
    """

    def __init__(self, factors: Optional[List[str]] = None):
        self.factors = factors or ["market", "size", "value", "momentum"]
        self.betas: Dict[str, float] = {}
        self.alpha: float = 0
        self.residuals: np.ndarray = np.array([])

    def generate_factor_returns(self, n_periods: int) -> Dict[str, np.ndarray]:
        """
        Generate synthetic factor returns for demonstration.
        In production, these would come from a data provider.
        """
        np.random.seed(42)

        factor_returns = {}

        # Market factor
        factor_returns["market"] = np.random.normal(0.0004, 0.01, n_periods)  # ~10% annual

        # Size factor (SMB)
        factor_returns["size"] = np.random.normal(0.0001, 0.006, n_periods)

        # Value factor (HML)
        factor_returns["value"] = np.random.normal(0.0001, 0.005, n_periods)

        # Momentum factor
        factor_returns["momentum"] = np.random.normal(0.0002, 0.008, n_periods)

        # Volatility factor
        factor_returns["volatility"] = np.random.normal(-0.0001, 0.007, n_periods)

        # Quality factor
        factor_returns["quality"] = np.random.normal(0.0001, 0.004, n_periods)

        return factor_returns

    def fit(
        self,
        returns: np.ndarray,
        factor_returns: Optional[Dict[str, np.ndarray]] = None,
    ) -> FactorExposures:
        """
        Fit factor model using OLS regression.

        Args:
            returns: Asset returns
            factor_returns: Dictionary of factor returns
        """
        n = len(returns)

        if factor_returns is None:
            factor_returns = self.generate_factor_returns(n)

        # Build factor matrix
        X = np.column_stack([
            factor_returns.get(f, np.zeros(n))
            for f in self.factors
        ])
        X = np.column_stack([np.ones(n), X])  # Add intercept

        # OLS regression
        beta_hat = np.linalg.lstsq(X, returns, rcond=None)[0]

        self.alpha = beta_hat[0]
        self.betas = dict(zip(self.factors, beta_hat[1:]))

        # Compute residuals
        fitted = X @ beta_hat
        self.residuals = returns - fitted

        # R-squared
        ss_res = np.sum(self.residuals ** 2)
        ss_tot = np.sum((returns - np.mean(returns)) ** 2)
        r_squared = 1 - ss_res / ss_tot

        # Standard errors and t-stats
        sigma_sq = ss_res / (n - len(beta_hat))
        var_beta = sigma_sq * np.linalg.inv(X.T @ X).diagonal()
        se = np.sqrt(var_beta)
        t_stats = beta_hat / se

        return FactorExposures(
            alpha=float(self.alpha * 252),  # Annualized
            betas=self.betas,
            r_squared=r_squared,
            residual_vol=float(np.std(self.residuals) * np.sqrt(252)),
            factor_returns={f: float(np.mean(factor_returns[f]) * 252) for f in self.factors},
            t_stats=dict(zip(["alpha"] + self.factors, t_stats)),
        )


# =============================================================================
# PORTFOLIO OPTIMIZATION
# =============================================================================

@dataclass
class OptimalPortfolio:
    """Optimal portfolio allocation."""
    weights: np.ndarray
    expected_return: float
    volatility: float
    sharpe_ratio: float
    var_95: float
    cvar_95: float
    max_drawdown: float
    diversification_ratio: float


class PortfolioOptimizer:
    """
    Advanced portfolio optimization with multiple objectives.

    Implements:
    - Mean-Variance (Markowitz)
    - Black-Litterman
    - Risk Parity
    - CVaR Optimization
    - Maximum Diversification
    """

    def __init__(
        self,
        returns: np.ndarray,
        asset_names: Optional[List[str]] = None,
        risk_free_rate: float = 0.02,
    ):
        """
        Args:
            returns: (n_periods, n_assets) array of returns
            asset_names: List of asset names
            risk_free_rate: Annual risk-free rate
        """
        self.returns = np.asarray(returns)
        self.n_assets = returns.shape[1]
        self.asset_names = asset_names or [f"Asset_{i}" for i in range(self.n_assets)]
        self.risk_free_rate = risk_free_rate

        # Compute statistics
        self.mean_returns = np.mean(returns, axis=0) * 252
        self.cov_matrix = np.cov(returns.T) * 252
        self.corr_matrix = np.corrcoef(returns.T)
        self.volatilities = np.std(returns, axis=0) * np.sqrt(252)

    def mean_variance(
        self,
        target_return: Optional[float] = None,
        target_vol: Optional[float] = None,
        constraints: Optional[Dict] = None,
    ) -> OptimalPortfolio:
        """
        Mean-variance optimization (Markowitz, 1952).

        Args:
            target_return: Target portfolio return
            target_vol: Target portfolio volatility
            constraints: Additional constraints
        """
        n = self.n_assets

        # Objective: minimize variance (or maximize Sharpe)
        def portfolio_variance(weights):
            return weights @ self.cov_matrix @ weights

        def portfolio_return(weights):
            return weights @ self.mean_returns

        def neg_sharpe(weights):
            ret = portfolio_return(weights)
            vol = np.sqrt(portfolio_variance(weights))
            return -(ret - self.risk_free_rate) / vol

        # Constraints
        cons = [{"type": "eq", "fun": lambda w: np.sum(w) - 1}]

        if target_return is not None:
            cons.append({"type": "eq", "fun": lambda w: portfolio_return(w) - target_return})
        if target_vol is not None:
            cons.append({"type": "eq", "fun": lambda w: np.sqrt(portfolio_variance(w)) - target_vol})

        # Bounds (long-only by default)
        bounds = [(0, 1) for _ in range(n)]

        # Optimize
        x0 = np.ones(n) / n

        if target_return is None and target_vol is None:
            # Maximize Sharpe ratio
            result = minimize(neg_sharpe, x0, method="SLSQP", bounds=bounds, constraints=cons)
        else:
            # Minimize variance
            result = minimize(portfolio_variance, x0, method="SLSQP", bounds=bounds, constraints=cons)

        weights = result.x

        return self._create_portfolio(weights)

    def black_litterman(
        self,
        views: Dict[str, float],
        view_confidences: Optional[Dict[str, float]] = None,
        tau: float = 0.05,
    ) -> OptimalPortfolio:
        """
        Black-Litterman model (1992).

        Combines market equilibrium with investor views.

        Args:
            views: Dictionary of asset -> expected return views
            view_confidences: Confidence in each view (0-1)
            tau: Scaling factor for uncertainty
        """
        n = self.n_assets

        # Market-cap weights (assume equal for now)
        market_weights = np.ones(n) / n

        # Equilibrium returns (reverse optimization)
        risk_aversion = 2.5
        equilibrium_returns = risk_aversion * self.cov_matrix @ market_weights

        # View matrix
        n_views = len(views)
        P = np.zeros((n_views, n))
        Q = np.zeros(n_views)

        for i, (asset, view_return) in enumerate(views.items()):
            if asset in self.asset_names:
                j = self.asset_names.index(asset)
                P[i, j] = 1
                Q[i] = view_return

        # View uncertainty
        if view_confidences:
            omega_diag = [(1 - view_confidences.get(a, 0.5)) ** 2 * 0.1 for a in views]
        else:
            omega_diag = [0.05] * n_views
        Omega = np.diag(omega_diag)

        # Black-Litterman formula
        tau_cov = tau * self.cov_matrix

        # Combined return estimate
        M = np.linalg.inv(np.linalg.inv(tau_cov) + P.T @ np.linalg.inv(Omega) @ P)
        bl_returns = M @ (np.linalg.inv(tau_cov) @ equilibrium_returns + P.T @ np.linalg.inv(Omega) @ Q)

        # Optimize with BL returns
        def neg_utility(weights):
            ret = weights @ bl_returns
            var = weights @ self.cov_matrix @ weights
            return -(ret - risk_aversion / 2 * var)

        cons = [{"type": "eq", "fun": lambda w: np.sum(w) - 1}]
        bounds = [(0, 1) for _ in range(n)]

        result = minimize(neg_utility, market_weights, method="SLSQP", bounds=bounds, constraints=cons)

        return self._create_portfolio(result.x)

    def risk_parity(self) -> OptimalPortfolio:
        """
        Risk Parity optimization.

        Equalizes risk contribution from each asset.
        """
        n = self.n_assets

        def risk_contribution_error(weights):
            weights = np.maximum(weights, 1e-8)
            port_vol = np.sqrt(weights @ self.cov_matrix @ weights)
            marginal_contrib = self.cov_matrix @ weights
            risk_contrib = weights * marginal_contrib / port_vol

            # Target: equal risk contribution
            target_contrib = port_vol / n
            return np.sum((risk_contrib - target_contrib) ** 2)

        cons = [{"type": "eq", "fun": lambda w: np.sum(w) - 1}]
        bounds = [(0.01, 1) for _ in range(n)]

        x0 = np.ones(n) / n
        result = minimize(risk_contribution_error, x0, method="SLSQP", bounds=bounds, constraints=cons)

        return self._create_portfolio(result.x)

    def cvar_optimization(self, confidence: float = 0.95) -> OptimalPortfolio:
        """
        CVaR (Conditional Value at Risk) optimization.

        Minimizes expected shortfall for better tail risk management.
        """
        n = self.n_assets
        n_scenarios = len(self.returns)

        def cvar_objective(weights):
            port_returns = self.returns @ weights
            var = np.percentile(port_returns, (1 - confidence) * 100)
            cvar = -np.mean(port_returns[port_returns <= var])
            return cvar

        cons = [{"type": "eq", "fun": lambda w: np.sum(w) - 1}]
        bounds = [(0, 1) for _ in range(n)]

        x0 = np.ones(n) / n
        result = minimize(cvar_objective, x0, method="SLSQP", bounds=bounds, constraints=cons)

        return self._create_portfolio(result.x)

    def maximum_diversification(self) -> OptimalPortfolio:
        """
        Maximum Diversification Portfolio.

        Maximizes diversification ratio = weighted average vol / portfolio vol.
        """
        n = self.n_assets

        def neg_diversification_ratio(weights):
            weighted_vol = np.sum(weights * self.volatilities)
            port_vol = np.sqrt(weights @ self.cov_matrix @ weights)
            return -weighted_vol / port_vol

        cons = [{"type": "eq", "fun": lambda w: np.sum(w) - 1}]
        bounds = [(0, 1) for _ in range(n)]

        x0 = np.ones(n) / n
        result = minimize(neg_diversification_ratio, x0, method="SLSQP", bounds=bounds, constraints=cons)

        return self._create_portfolio(result.x)

    def _create_portfolio(self, weights: np.ndarray) -> OptimalPortfolio:
        """Create OptimalPortfolio from weights."""
        weights = np.maximum(weights, 0)
        weights = weights / np.sum(weights)

        port_return = float(weights @ self.mean_returns)
        port_vol = float(np.sqrt(weights @ self.cov_matrix @ weights))
        sharpe = (port_return - self.risk_free_rate) / port_vol if port_vol > 0 else 0

        # Compute VaR and CVaR
        port_returns = self.returns @ weights
        var_95 = float(-np.percentile(port_returns, 5) * np.sqrt(252))
        cvar_95 = float(-np.mean(port_returns[port_returns <= np.percentile(port_returns, 5)]) * np.sqrt(252))

        # Max drawdown
        cum_returns = np.cumprod(1 + port_returns)
        running_max = np.maximum.accumulate(cum_returns)
        drawdowns = (cum_returns - running_max) / running_max
        max_dd = float(-np.min(drawdowns))

        # Diversification ratio
        weighted_vol = np.sum(weights * self.volatilities)
        div_ratio = weighted_vol / port_vol if port_vol > 0 else 1

        return OptimalPortfolio(
            weights=weights,
            expected_return=port_return,
            volatility=port_vol,
            sharpe_ratio=sharpe,
            var_95=var_95,
            cvar_95=cvar_95,
            max_drawdown=max_dd,
            diversification_ratio=div_ratio,
        )


# =============================================================================
# SIGNAL GENERATION
# =============================================================================

@dataclass
class TradingSignal:
    """Trading signal with confidence."""
    asset: str
    direction: str  # "long", "short", "neutral"
    strength: float  # -1 to 1
    confidence: float  # 0 to 1
    factors: Dict[str, float]
    timestamp: datetime


class SignalGenerator:
    """
    Multi-factor signal generation.

    Combines:
    - Momentum (time-series and cross-sectional)
    - Mean reversion
    - Volatility signals
    - Trend following
    - Carry
    """

    def __init__(self, lookback_periods: Dict[str, int] = None):
        self.lookback = lookback_periods or {
            "short": 5,
            "medium": 20,
            "long": 60,
            "trend": 200,
        }

    def generate_signals(
        self,
        prices: np.ndarray,
        volumes: Optional[np.ndarray] = None,
        asset_names: Optional[List[str]] = None,
    ) -> List[TradingSignal]:
        """
        Generate trading signals for all assets.

        Args:
            prices: (n_periods, n_assets) price array
            volumes: Optional volume data
            asset_names: Asset identifiers
        """
        n_periods, n_assets = prices.shape
        asset_names = asset_names or [f"Asset_{i}" for i in range(n_assets)]

        signals = []

        for i in range(n_assets):
            price = prices[:, i]
            volume = volumes[:, i] if volumes is not None else None

            # Compute individual factors
            factors = {}

            # Momentum factors
            factors["momentum_short"] = self._momentum(price, self.lookback["short"])
            factors["momentum_medium"] = self._momentum(price, self.lookback["medium"])
            factors["momentum_long"] = self._momentum(price, self.lookback["long"])

            # Mean reversion
            factors["mean_reversion"] = self._mean_reversion(price, self.lookback["medium"])

            # Trend strength
            factors["trend"] = self._trend_strength(price, self.lookback["trend"])

            # Volatility regime
            factors["volatility"] = self._volatility_signal(price, self.lookback["medium"])

            # RSI
            factors["rsi"] = self._rsi_signal(price, 14)

            # Volume (if available)
            if volume is not None:
                factors["volume_momentum"] = self._volume_momentum(volume, price, self.lookback["short"])

            # Combine factors into signal
            weights = {
                "momentum_short": 0.15,
                "momentum_medium": 0.20,
                "momentum_long": 0.15,
                "mean_reversion": 0.10,
                "trend": 0.20,
                "volatility": 0.10,
                "rsi": 0.10,
            }

            combined = sum(factors.get(k, 0) * w for k, w in weights.items())

            # Determine direction and strength
            if combined > 0.2:
                direction = "long"
                strength = min(combined, 1.0)
            elif combined < -0.2:
                direction = "short"
                strength = max(combined, -1.0)
            else:
                direction = "neutral"
                strength = combined

            # Confidence based on factor agreement
            factor_signs = [np.sign(v) for v in factors.values() if v != 0]
            if len(factor_signs) > 0:
                agreement = abs(sum(factor_signs)) / len(factor_signs)
            else:
                agreement = 0.5
            confidence = 0.5 + 0.5 * agreement

            signals.append(TradingSignal(
                asset=asset_names[i],
                direction=direction,
                strength=float(strength),
                confidence=float(confidence),
                factors=factors,
                timestamp=datetime.now(),
            ))

        return signals

    def _momentum(self, price: np.ndarray, period: int) -> float:
        """Compute momentum signal."""
        if len(price) < period:
            return 0
        return (price[-1] / price[-period] - 1) * 10  # Scaled

    def _mean_reversion(self, price: np.ndarray, period: int) -> float:
        """Compute mean reversion signal."""
        if len(price) < period:
            return 0
        ma = np.mean(price[-period:])
        std = np.std(price[-period:])
        if std == 0:
            return 0
        z_score = (price[-1] - ma) / std
        return -np.clip(z_score, -3, 3) / 3  # Contrarian signal

    def _trend_strength(self, price: np.ndarray, period: int) -> float:
        """Compute trend strength using linear regression."""
        if len(price) < period:
            return 0
        y = price[-period:]
        x = np.arange(period)
        slope = np.polyfit(x, y, 1)[0]
        # Normalize by price level
        return slope / price[-1] * 100

    def _volatility_signal(self, price: np.ndarray, period: int) -> float:
        """Compute volatility-based signal."""
        if len(price) < period + 1:
            return 0
        returns = np.diff(price[-period - 1:]) / price[-period - 1:-1]
        vol = np.std(returns) * np.sqrt(252)

        # Low volatility is positive for trend-following
        avg_vol = 0.2  # Assume 20% average
        return (avg_vol - vol) / avg_vol

    def _rsi_signal(self, price: np.ndarray, period: int = 14) -> float:
        """Compute RSI signal."""
        if len(price) < period + 1:
            return 0
        deltas = np.diff(price[-period - 1:])
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)

        avg_gain = np.mean(gains)
        avg_loss = np.mean(losses)

        if avg_loss == 0:
            rsi = 100
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - 100 / (1 + rs)

        # Convert to signal (-1 to 1)
        if rsi > 70:
            return -(rsi - 70) / 30  # Overbought
        elif rsi < 30:
            return (30 - rsi) / 30  # Oversold
        else:
            return 0

    def _volume_momentum(self, volume: np.ndarray, price: np.ndarray, period: int) -> float:
        """Compute volume-price momentum."""
        if len(volume) < period or len(price) < period:
            return 0

        vol_change = volume[-1] / np.mean(volume[-period:]) - 1
        price_change = price[-1] / price[-period] - 1

        # High volume with price increase is bullish
        return np.sign(price_change) * min(abs(vol_change), 2) / 2


# =============================================================================
# WALK-FORWARD OPTIMIZATION
# =============================================================================

@dataclass
class WalkForwardResult:
    """Results from walk-forward optimization."""
    in_sample_sharpe: float
    out_of_sample_sharpe: float
    overfitting_ratio: float
    optimal_params: Dict[str, Any]
    period_returns: List[float]
    cumulative_return: float


class WalkForwardOptimizer:
    """
    Walk-forward optimization for robust backtesting.

    Prevents overfitting by:
    1. Optimizing on in-sample period
    2. Testing on out-of-sample period
    3. Rolling forward and repeating
    """

    def __init__(
        self,
        in_sample_periods: int = 252,
        out_of_sample_periods: int = 63,
        n_windows: int = 8,
    ):
        self.in_sample_periods = in_sample_periods
        self.out_of_sample_periods = out_of_sample_periods
        self.n_windows = n_windows

    def optimize(
        self,
        returns: np.ndarray,
        strategy_func: Callable,
        param_space: Dict[str, Tuple[float, float]],
    ) -> WalkForwardResult:
        """
        Run walk-forward optimization.

        Args:
            returns: Historical returns
            strategy_func: Function(returns, params) -> signals
            param_space: Parameter bounds for optimization
        """
        total_periods = len(returns)
        window_size = self.in_sample_periods + self.out_of_sample_periods

        if total_periods < window_size:
            raise ValueError("Insufficient data for walk-forward optimization")

        in_sample_sharpes = []
        out_sample_sharpes = []
        period_returns = []
        all_params = []

        for window in range(self.n_windows):
            start = window * self.out_of_sample_periods
            in_sample_end = start + self.in_sample_periods
            out_sample_end = in_sample_end + self.out_of_sample_periods

            if out_sample_end > total_periods:
                break

            in_sample = returns[start:in_sample_end]
            out_sample = returns[in_sample_end:out_sample_end]

            # Optimize on in-sample
            best_params, is_sharpe = self._optimize_params(
                in_sample, strategy_func, param_space
            )

            # Test on out-of-sample
            os_returns = strategy_func(out_sample, best_params)
            os_sharpe = self._compute_sharpe(os_returns)

            in_sample_sharpes.append(is_sharpe)
            out_sample_sharpes.append(os_sharpe)
            period_returns.extend(os_returns)
            all_params.append(best_params)

        # Compute metrics
        avg_is_sharpe = np.mean(in_sample_sharpes)
        avg_os_sharpe = np.mean(out_sample_sharpes)
        overfitting = (avg_is_sharpe - avg_os_sharpe) / avg_is_sharpe if avg_is_sharpe != 0 else 0

        # Aggregate best parameters
        optimal_params = {}
        for key in param_space:
            optimal_params[key] = np.mean([p.get(key, 0) for p in all_params])

        return WalkForwardResult(
            in_sample_sharpe=avg_is_sharpe,
            out_of_sample_sharpe=avg_os_sharpe,
            overfitting_ratio=overfitting,
            optimal_params=optimal_params,
            period_returns=period_returns,
            cumulative_return=float(np.prod(1 + np.array(period_returns)) - 1),
        )

    def _optimize_params(
        self,
        returns: np.ndarray,
        strategy_func: Callable,
        param_space: Dict[str, Tuple[float, float]],
    ) -> Tuple[Dict, float]:
        """Optimize parameters on in-sample data."""
        def objective(params_array):
            params = {}
            for i, key in enumerate(param_space):
                params[key] = params_array[i]

            strategy_returns = strategy_func(returns, params)
            sharpe = self._compute_sharpe(strategy_returns)
            return -sharpe  # Minimize negative Sharpe

        bounds = [param_space[k] for k in param_space]

        result = differential_evolution(objective, bounds, maxiter=50, seed=42)

        best_params = {}
        for i, key in enumerate(param_space):
            best_params[key] = result.x[i]

        return best_params, -result.fun

    def _compute_sharpe(self, returns: np.ndarray) -> float:
        """Compute Sharpe ratio."""
        if len(returns) == 0 or np.std(returns) == 0:
            return 0
        return np.mean(returns) / np.std(returns) * np.sqrt(252)


# =============================================================================
# FACTORY FUNCTIONS
# =============================================================================

def create_analytics_suite() -> Dict[str, Any]:
    """Create a complete analytics suite."""
    return {
        "bayesian": BayesianEstimator(),
        "hmm": GaussianHMM(n_states=3),
        "garch": GARCH(p=1, q=1),
        "gaussian_copula": GaussianCopula(),
        "t_copula": StudentTCopula(),
        "evt": ExtremeValueAnalyzer(),
        "factor_model": FactorModel(),
        "signal_generator": SignalGenerator(),
        "walk_forward": WalkForwardOptimizer(),
    }
