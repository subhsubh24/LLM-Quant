"""
Monte Carlo Simulation Engine.

The foundation of the simulation stack. Implements:
1. GBM (Geometric Brownian Motion) path simulation for asset prices
2. Binary contract pricing with confidence intervals
3. Multi-asset correlated path generation
4. Prediction market probability estimation
5. Path-dependent payoff evaluation

Convergence rate: O(N^{-1/2}) by CLT, with variance p(1-p)/N for binary events.

References:
- Glasserman (2003): "Monte Carlo Methods in Financial Engineering", Ch. 3-4
- Broadie & Glasserman (1996): "Estimating Security Price Derivatives Using Simulation"
"""

import logging
import math
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
from scipy.stats import norm

logger = logging.getLogger(__name__)


@dataclass
class PathResult:
    """Result of a Monte Carlo path simulation."""
    paths: np.ndarray           # Shape: (n_paths, n_steps+1)
    times: np.ndarray           # Shape: (n_steps+1,)
    terminal_values: np.ndarray  # Shape: (n_paths,)
    mean_terminal: float
    std_terminal: float
    percentiles: Dict[str, float]  # e.g., {"5%": ..., "50%": ..., "95%": ...}


@dataclass
class BinaryContractResult:
    """Result of binary contract Monte Carlo pricing."""
    probability: float
    std_error: float
    ci_95: Tuple[float, float]
    n_paths: int
    brier_bound: float  # Upper bound on Brier score given our precision


class MonteCarloEngine:
    """
    Core Monte Carlo path simulation engine.

    Supports GBM, mean-reverting (OU), and jump-diffusion dynamics.
    Works for both traditional assets and prediction market underlyings.

    Usage:
        engine = MonteCarloEngine(seed=42)
        paths = engine.simulate_gbm(S0=100, mu=0.08, sigma=0.2, T=1.0, n_steps=252)
        print(f"E[S_T] = {paths.mean_terminal:.2f}")
    """

    def __init__(self, seed: Optional[int] = None):
        self.rng = np.random.default_rng(seed)

    def simulate_gbm(
        self,
        S0: float,
        mu: float,
        sigma: float,
        T: float,
        n_steps: int = 252,
        n_paths: int = 100_000,
    ) -> PathResult:
        """
        Simulate Geometric Brownian Motion paths.

        dS/S = mu*dt + sigma*dW

        Exact solution: S_t = S_0 * exp((mu - sigma^2/2)*t + sigma*W_t)

        Args:
            S0: Initial price
            mu: Annual drift (risk-neutral: r - q)
            sigma: Annual volatility
            T: Time horizon in years
            n_steps: Number of time steps
            n_paths: Number of simulation paths
        """
        dt = T / n_steps
        sqrt_dt = math.sqrt(dt)

        # Pre-allocate
        paths = np.zeros((n_paths, n_steps + 1))
        paths[:, 0] = S0

        # Vectorized simulation
        Z = self.rng.standard_normal((n_paths, n_steps))
        drift = (mu - 0.5 * sigma ** 2) * dt
        diffusion = sigma * sqrt_dt * Z

        log_returns = drift + diffusion
        log_prices = np.cumsum(log_returns, axis=1)
        paths[:, 1:] = S0 * np.exp(log_prices)

        times = np.linspace(0, T, n_steps + 1)
        terminal = paths[:, -1]

        return PathResult(
            paths=paths,
            times=times,
            terminal_values=terminal,
            mean_terminal=float(terminal.mean()),
            std_terminal=float(terminal.std()),
            percentiles={
                "1%": float(np.percentile(terminal, 1)),
                "5%": float(np.percentile(terminal, 5)),
                "25%": float(np.percentile(terminal, 25)),
                "50%": float(np.percentile(terminal, 50)),
                "75%": float(np.percentile(terminal, 75)),
                "95%": float(np.percentile(terminal, 95)),
                "99%": float(np.percentile(terminal, 99)),
            },
        )

    def simulate_jump_diffusion(
        self,
        S0: float,
        mu: float,
        sigma: float,
        T: float,
        jump_intensity: float = 1.0,
        jump_mean: float = -0.05,
        jump_vol: float = 0.10,
        n_steps: int = 252,
        n_paths: int = 100_000,
    ) -> PathResult:
        """
        Merton jump-diffusion model.

        dS/S = (mu - lambda*k)*dt + sigma*dW + J*dN

        Where N is Poisson(lambda) and J ~ N(jump_mean, jump_vol^2).
        k = E[e^J - 1] is the compensator.

        Critical for prediction markets where news causes discontinuous
        price jumps (e.g., court ruling, election call).
        """
        dt = T / n_steps
        sqrt_dt = math.sqrt(dt)

        # Compensator: k = exp(jump_mean + jump_vol^2/2) - 1
        k = math.exp(jump_mean + 0.5 * jump_vol ** 2) - 1.0

        paths = np.zeros((n_paths, n_steps + 1))
        paths[:, 0] = S0

        for t in range(n_steps):
            Z = self.rng.standard_normal(n_paths)
            # Poisson jumps
            N_jumps = self.rng.poisson(jump_intensity * dt, n_paths)
            # Sum of jump sizes
            J = np.zeros(n_paths)
            for i in range(n_paths):
                if N_jumps[i] > 0:
                    J[i] = np.sum(
                        self.rng.normal(jump_mean, jump_vol, N_jumps[i])
                    )

            drift = (mu - jump_intensity * k - 0.5 * sigma ** 2) * dt
            diffusion = sigma * sqrt_dt * Z
            paths[:, t + 1] = paths[:, t] * np.exp(drift + diffusion + J)

        times = np.linspace(0, T, n_steps + 1)
        terminal = paths[:, -1]

        return PathResult(
            paths=paths,
            times=times,
            terminal_values=terminal,
            mean_terminal=float(terminal.mean()),
            std_terminal=float(terminal.std()),
            percentiles={
                "1%": float(np.percentile(terminal, 1)),
                "5%": float(np.percentile(terminal, 5)),
                "25%": float(np.percentile(terminal, 25)),
                "50%": float(np.percentile(terminal, 50)),
                "75%": float(np.percentile(terminal, 75)),
                "95%": float(np.percentile(terminal, 95)),
                "99%": float(np.percentile(terminal, 99)),
            },
        )

    def simulate_ou(
        self,
        X0: float,
        theta: float,
        mu: float,
        sigma: float,
        T: float,
        n_steps: int = 252,
        n_paths: int = 100_000,
    ) -> PathResult:
        """
        Ornstein-Uhlenbeck (mean-reverting) process.

        dX = theta*(mu - X)*dt + sigma*dW

        Used for: prediction market logit-prices, interest rate spreads,
        stat-arb spread modeling, volatility mean-reversion.

        Args:
            X0: Initial value
            theta: Mean-reversion speed
            mu: Long-run mean
            sigma: Volatility
        """
        dt = T / n_steps
        sqrt_dt = math.sqrt(dt)

        paths = np.zeros((n_paths, n_steps + 1))
        paths[:, 0] = X0

        Z = self.rng.standard_normal((n_paths, n_steps))

        # Exact discretization for OU
        exp_theta_dt = math.exp(-theta * dt)
        conditional_mean_coeff = 1.0 - exp_theta_dt
        conditional_var = (sigma ** 2 / (2.0 * theta)) * (1.0 - math.exp(-2.0 * theta * dt))
        conditional_std = math.sqrt(max(conditional_var, 1e-12))

        for t in range(n_steps):
            paths[:, t + 1] = (
                paths[:, t] * exp_theta_dt
                + mu * conditional_mean_coeff
                + conditional_std * Z[:, t]
            )

        times = np.linspace(0, T, n_steps + 1)
        terminal = paths[:, -1]

        return PathResult(
            paths=paths,
            times=times,
            terminal_values=terminal,
            mean_terminal=float(terminal.mean()),
            std_terminal=float(terminal.std()),
            percentiles={
                "1%": float(np.percentile(terminal, 1)),
                "5%": float(np.percentile(terminal, 5)),
                "50%": float(np.percentile(terminal, 50)),
                "95%": float(np.percentile(terminal, 95)),
                "99%": float(np.percentile(terminal, 99)),
            },
        )


class BinaryContractPricer:
    """
    Monte Carlo pricing for binary (digital) contracts.

    Covers both traditional digital options and prediction market outcomes.

    For prediction markets, the "underlying" can be:
    - An asset price (e.g., "Will AAPL close above $200?")
    - A logit-transformed probability (e.g., "Will the Fed cut rates?")
    - A directly simulated event indicator

    The Brier Score bound tells you how calibrated your simulation can be
    given the number of paths: Brier <= p*(1-p)/N at the 95% level.
    """

    def __init__(self, engine: Optional[MonteCarloEngine] = None):
        self.engine = engine or MonteCarloEngine()

    def price_asset_binary(
        self,
        S0: float,
        K: float,
        mu: float,
        sigma: float,
        T: float,
        n_paths: int = 100_000,
        above: bool = True,
    ) -> BinaryContractResult:
        """
        Price a binary contract on an asset: pays $1 if S_T > K (or < K).

        Example: "Will AAPL close above $200 by March 15?"
        """
        result = self.engine.simulate_gbm(
            S0=S0, mu=mu, sigma=sigma, T=T, n_steps=1, n_paths=n_paths,
        )

        if above:
            payoffs = (result.terminal_values > K).astype(float)
        else:
            payoffs = (result.terminal_values < K).astype(float)

        p_hat = float(payoffs.mean())
        se = math.sqrt(p_hat * (1.0 - p_hat) / n_paths) if n_paths > 0 else 0.0

        return BinaryContractResult(
            probability=p_hat,
            std_error=se,
            ci_95=(max(0.0, p_hat - 1.96 * se), min(1.0, p_hat + 1.96 * se)),
            n_paths=n_paths,
            brier_bound=p_hat * (1.0 - p_hat) / n_paths,
        )

    def price_jump_binary(
        self,
        S0: float,
        K: float,
        mu: float,
        sigma: float,
        T: float,
        jump_intensity: float = 2.0,
        jump_mean: float = -0.03,
        jump_vol: float = 0.08,
        n_paths: int = 100_000,
        above: bool = True,
    ) -> BinaryContractResult:
        """
        Binary contract pricing under jump-diffusion dynamics.

        More realistic for prediction markets where news causes jumps.
        """
        result = self.engine.simulate_jump_diffusion(
            S0=S0, mu=mu, sigma=sigma, T=T,
            jump_intensity=jump_intensity,
            jump_mean=jump_mean,
            jump_vol=jump_vol,
            n_steps=max(1, int(T * 252)),
            n_paths=n_paths,
        )

        if above:
            payoffs = (result.terminal_values > K).astype(float)
        else:
            payoffs = (result.terminal_values < K).astype(float)

        p_hat = float(payoffs.mean())
        se = math.sqrt(p_hat * (1.0 - p_hat) / n_paths) if n_paths > 0 else 0.0

        return BinaryContractResult(
            probability=p_hat,
            std_error=se,
            ci_95=(max(0.0, p_hat - 1.96 * se), min(1.0, p_hat + 1.96 * se)),
            n_paths=n_paths,
            brier_bound=p_hat * (1.0 - p_hat) / n_paths,
        )

    def price_prediction_market_binary(
        self,
        current_prob: float,
        prob_volatility: float,
        T: float,
        threshold: float = 0.5,
        n_paths: int = 100_000,
    ) -> BinaryContractResult:
        """
        Price a prediction market binary by simulating probability paths.

        Models the probability itself as a mean-reverting process in logit space:
            d(logit(p)) = theta*(logit(p_fair) - logit(p))*dt + sigma*dW

        Then checks: P(p_T > threshold) = probability of resolution YES.

        This is for contracts like "Will event X happen?" where the underlying
        is a probability, not an asset price.

        Args:
            current_prob: Current market probability (0-1)
            prob_volatility: Volatility of the probability in logit space
            T: Time to resolution in years
            threshold: Resolution threshold (0.5 for standard binary)
        """
        eps = 1e-6
        X0 = math.log(max(eps, current_prob) / max(eps, 1.0 - current_prob))
        K_logit = math.log(max(eps, threshold) / max(eps, 1.0 - threshold))

        # Simulate logit-space paths (OU for mean reversion, or GBM-like drift)
        result = self.engine.simulate_ou(
            X0=X0, theta=0.5, mu=X0, sigma=prob_volatility,
            T=T, n_steps=max(1, int(T * 252)), n_paths=n_paths,
        )

        # Transform terminal values back to probability space
        terminal_probs = 1.0 / (1.0 + np.exp(-result.terminal_values))
        payoffs = (terminal_probs > threshold).astype(float)

        p_hat = float(payoffs.mean())
        se = math.sqrt(p_hat * (1.0 - p_hat) / n_paths) if n_paths > 0 else 0.0

        return BinaryContractResult(
            probability=p_hat,
            std_error=se,
            ci_95=(max(0.0, p_hat - 1.96 * se), min(1.0, p_hat + 1.96 * se)),
            n_paths=n_paths,
            brier_bound=p_hat * (1.0 - p_hat) / n_paths,
        )

    def price_barrier_binary(
        self,
        S0: float,
        K: float,
        barrier: float,
        mu: float,
        sigma: float,
        T: float,
        n_steps: int = 252,
        n_paths: int = 100_000,
        knock_in: bool = True,
        barrier_up: bool = True,
    ) -> BinaryContractResult:
        """
        Barrier binary contract: pays $1 if barrier is hit AND terminal condition met.

        Relevant for prediction markets with path-dependent resolution
        (e.g., "Will BTC touch $100k before June AND close above $90k?").
        """
        result = self.engine.simulate_gbm(
            S0=S0, mu=mu, sigma=sigma, T=T, n_steps=n_steps, n_paths=n_paths,
        )

        if barrier_up:
            barrier_hit = np.max(result.paths, axis=1) >= barrier
        else:
            barrier_hit = np.min(result.paths, axis=1) <= barrier

        terminal_condition = result.terminal_values > K

        if knock_in:
            payoffs = (barrier_hit & terminal_condition).astype(float)
        else:
            payoffs = (~barrier_hit & terminal_condition).astype(float)

        p_hat = float(payoffs.mean())
        se = math.sqrt(p_hat * (1.0 - p_hat) / n_paths) if n_paths > 0 else 0.0

        return BinaryContractResult(
            probability=p_hat,
            std_error=se,
            ci_95=(max(0.0, p_hat - 1.96 * se), min(1.0, p_hat + 1.96 * se)),
            n_paths=n_paths,
            brier_bound=p_hat * (1.0 - p_hat) / n_paths,
        )


class MultiAssetSimulator:
    """
    Correlated multi-asset Monte Carlo simulation.

    Uses Cholesky decomposition to generate correlated Brownian motions.
    Essential for portfolio simulation and correlated prediction market analysis.

    Usage:
        sim = MultiAssetSimulator(seed=42)
        paths = sim.simulate_correlated_gbm(
            S0=[100, 50, 200],
            mu=[0.08, 0.05, 0.12],
            sigma=[0.20, 0.15, 0.30],
            corr=[[1, 0.5, 0.3], [0.5, 1, 0.4], [0.3, 0.4, 1]],
            T=1.0,
        )
    """

    def __init__(self, seed: Optional[int] = None):
        self.rng = np.random.default_rng(seed)

    def simulate_correlated_gbm(
        self,
        S0: List[float],
        mu: List[float],
        sigma: List[float],
        corr: np.ndarray,
        T: float,
        n_steps: int = 252,
        n_paths: int = 50_000,
    ) -> Dict[str, np.ndarray]:
        """
        Simulate correlated GBM paths for multiple assets.

        Returns dict with 'paths' (n_paths, n_assets, n_steps+1),
        'terminal' (n_paths, n_assets), and asset-level stats.
        """
        n_assets = len(S0)
        dt = T / n_steps
        sqrt_dt = math.sqrt(dt)

        S0_arr = np.array(S0)
        mu_arr = np.array(mu)
        sigma_arr = np.array(sigma)
        corr_arr = np.array(corr)

        # Cholesky decomposition for correlation
        L = np.linalg.cholesky(corr_arr)

        paths = np.zeros((n_paths, n_assets, n_steps + 1))
        paths[:, :, 0] = S0_arr

        for t in range(n_steps):
            Z_indep = self.rng.standard_normal((n_paths, n_assets))
            Z_corr = Z_indep @ L.T  # Correlated normals

            drift = (mu_arr - 0.5 * sigma_arr ** 2) * dt
            diffusion = sigma_arr * sqrt_dt * Z_corr

            paths[:, :, t + 1] = paths[:, :, t] * np.exp(drift + diffusion)

        terminal = paths[:, :, -1]

        return {
            "paths": paths,
            "terminal": terminal,
            "times": np.linspace(0, T, n_steps + 1),
            "mean_terminal": terminal.mean(axis=0).tolist(),
            "correlation_realized": np.corrcoef(
                np.log(terminal / S0_arr), rowvar=False
            ).tolist(),
        }

    def simulate_portfolio_value(
        self,
        S0: List[float],
        weights: List[float],
        mu: List[float],
        sigma: List[float],
        corr: np.ndarray,
        T: float,
        n_steps: int = 252,
        n_paths: int = 50_000,
    ) -> Dict[str, np.ndarray]:
        """
        Simulate portfolio value paths for VaR/CVaR computation.
        """
        result = self.simulate_correlated_gbm(
            S0=S0, mu=mu, sigma=sigma, corr=corr,
            T=T, n_steps=n_steps, n_paths=n_paths,
        )

        weights_arr = np.array(weights)
        initial_value = np.dot(S0, weights_arr)

        # Portfolio value at each time step
        # paths shape: (n_paths, n_assets, n_steps+1)
        portfolio_paths = np.sum(
            result["paths"] * weights_arr[np.newaxis, :, np.newaxis],
            axis=1,
        )

        terminal_values = portfolio_paths[:, -1]
        returns = (terminal_values - initial_value) / initial_value

        # Compute max drawdown per path
        running_max = np.maximum.accumulate(portfolio_paths, axis=1)
        drawdowns = (running_max - portfolio_paths) / np.maximum(running_max, 1e-8)
        max_drawdowns = np.max(drawdowns, axis=1)

        sorted_returns = np.sort(returns)
        n = len(sorted_returns)

        return {
            "portfolio_paths": portfolio_paths,
            "terminal_values": terminal_values,
            "returns": returns,
            "mean_return": float(returns.mean()),
            "std_return": float(returns.std()),
            "var_95": float(sorted_returns[int(0.05 * n)]),
            "var_99": float(sorted_returns[int(0.01 * n)]),
            "cvar_95": float(sorted_returns[: int(0.05 * n)].mean()),
            "cvar_99": float(sorted_returns[: int(0.01 * n)].mean()),
            "max_drawdown_95": float(np.percentile(max_drawdowns, 95)),
            "max_drawdown_99": float(np.percentile(max_drawdowns, 99)),
            "sharpe": float(returns.mean() / max(returns.std(), 1e-8)),
        }
