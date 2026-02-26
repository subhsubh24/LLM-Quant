"""
Advanced Quantitative Models for Prediction Markets.

Implements the institutional-grade math from the RohOhChain roadmap:
1. Avellaneda-Stoikov optimal market making (reservation price + optimal spread)
2. VPIN (Volume-synchronized Probability of Informed Trading) toxicity detection
3. Monte Carlo Kelly with empirical return distributions
4. Logit transform for bounded price modeling
5. Bayesian probability updater with Beta priors

References:
- Avellaneda & Stoikov (2008): "High-frequency trading in a limit order book"
- Easley, López de Prado & O'Hara (2012): "Flow Toxicity and Liquidity"
- Kelly (1956): "A New Interpretation of Information Rate"
- Jaynes (2003): "Probability Theory: The Logic of Science"
"""

import logging
import math
import random
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ============================================================
# Logit Transform for Bounded Prices
# ============================================================

def logit(p: float, eps: float = 1e-6) -> float:
    """
    Transform bounded probability p ∈ (0,1) to unbounded real line.

    logit(p) = ln(p / (1 - p))

    This is essential for market making models: prediction market prices
    are bounded [0, 1], but diffusion models (Brownian motion, Ornstein-
    Uhlenbeck) assume unbounded state spaces. The logit transform maps
    prices to the real line, applies the model, then maps back via sigmoid.

    Same function as the sigmoid inverse used in neural networks.
    """
    p = max(eps, min(1.0 - eps, p))
    return math.log(p / (1.0 - p))


def sigmoid(x: float) -> float:
    """
    Inverse logit: map real line back to (0, 1).

    sigmoid(x) = 1 / (1 + exp(-x))
    """
    if x > 500:
        return 1.0
    if x < -500:
        return 0.0
    return 1.0 / (1.0 + math.exp(-x))


def logit_volatility(prices: List[float], window: int = 20) -> float:
    """
    Compute volatility in logit space (unbounded) rather than raw price space.

    Standard deviation of logit(prices) gives a more accurate volatility
    estimate for prices near 0 or 1 where raw price changes are compressed.
    """
    if len(prices) < max(2, window):
        return 0.0
    recent = prices[-window:]
    logit_prices = [logit(p) for p in recent]
    # Returns of logit prices
    returns = [logit_prices[i] - logit_prices[i - 1] for i in range(1, len(logit_prices))]
    if not returns:
        return 0.0
    mean_r = sum(returns) / len(returns)
    var = sum((r - mean_r) ** 2 for r in returns) / len(returns)
    return math.sqrt(var)


# ============================================================
# Avellaneda-Stoikov Market Making
# ============================================================

@dataclass
class AvellanedaStoikovConfig:
    """Configuration for the Avellaneda-Stoikov market making model."""
    gamma: float = 0.1          # Risk aversion parameter (higher = tighter quotes)
    kappa: float = 1.5          # Order arrival rate (fills/sec at best price)
    min_spread: float = 0.005   # Floor spread (0.5 cents)
    max_spread: float = 0.05    # Ceiling spread (5 cents)
    volatility_window: int = 30  # Ticks for volatility estimation


class AvellanedaStoikovModel:
    """
    Optimal market making using the Avellaneda-Stoikov (2008) framework.

    Core idea: the market maker sets quotes around a "reservation price"
    that adjusts away from mid based on inventory risk. The spread
    compensates for adverse selection and inventory risk.

    Reservation price:
        r = s - q * γ * σ² * (T - t)
        - s: mid-price (in logit space for bounded prices)
        - q: inventory (positive = long, negative = short)
        - γ: risk aversion
        - σ²: variance (estimated from recent ticks)
        - (T - t): time to resolution

    Optimal spread:
        δ = γσ²(T - t) + (2/γ) * ln(1 + γ/κ)
        - First term: inventory risk compensation
        - Second term: pure liquidity provision profit

    For prediction markets, we work in logit space:
        logit(p) = ln(p / (1-p))
    Then transform back to [0,1] via sigmoid for actual quote prices.
    """

    def __init__(self, config: Optional[AvellanedaStoikovConfig] = None):
        self.config = config or AvellanedaStoikovConfig()
        self._price_history: Dict[str, List[float]] = {}

    def record_price(self, token_id: str, price: float):
        """Record a price tick for volatility estimation."""
        if token_id not in self._price_history:
            self._price_history[token_id] = []
        self._price_history[token_id].append(price)
        # Keep last 200 ticks
        if len(self._price_history[token_id]) > 200:
            self._price_history[token_id] = self._price_history[token_id][-200:]

    def compute_quotes(
        self,
        token_id: str,
        mid_price: float,
        inventory: float,
        time_to_resolution_hours: float,
    ) -> Tuple[float, float, dict]:
        """
        Compute optimal bid and ask prices.

        Args:
            token_id: Token to quote
            mid_price: Current midpoint price (0-1)
            inventory: Current inventory (positive = long, negative = short)
            time_to_resolution_hours: Hours until market resolves

        Returns:
            (bid_price, ask_price, diagnostics_dict)
        """
        cfg = self.config

        # Estimate volatility in logit space
        prices = self._price_history.get(token_id, [])
        sigma = logit_volatility(prices, cfg.volatility_window)
        if sigma < 0.001:
            sigma = 0.05  # Default volatility when insufficient data

        sigma_sq = sigma ** 2

        # Time remaining as fraction (normalize to 0-1 range)
        # Use hours / 168 (one week) as the natural timescale
        T_minus_t = max(time_to_resolution_hours / 168.0, 0.001)

        # Work in logit space
        s = logit(mid_price)

        # Reservation price (shifted by inventory risk)
        r = s - inventory * cfg.gamma * sigma_sq * T_minus_t

        # Optimal spread
        spread_logit = (
            cfg.gamma * sigma_sq * T_minus_t
            + (2.0 / cfg.gamma) * math.log(1.0 + cfg.gamma / cfg.kappa)
        )

        # Convert back to probability space
        reservation_price = sigmoid(r)
        half_spread_logit = spread_logit / 2.0

        bid_logit = r - half_spread_logit
        ask_logit = r + half_spread_logit

        bid_price = sigmoid(bid_logit)
        ask_price = sigmoid(ask_logit)

        # Apply floor/ceiling
        actual_spread = ask_price - bid_price
        if actual_spread < cfg.min_spread:
            adjustment = (cfg.min_spread - actual_spread) / 2
            bid_price -= adjustment
            ask_price += adjustment
        elif actual_spread > cfg.max_spread:
            adjustment = (actual_spread - cfg.max_spread) / 2
            bid_price += adjustment
            ask_price -= adjustment

        # Clamp to valid range
        bid_price = max(0.01, min(0.98, bid_price))
        ask_price = max(0.02, min(0.99, ask_price))
        if ask_price <= bid_price:
            ask_price = bid_price + cfg.min_spread

        diagnostics = {
            "reservation_price": round(reservation_price, 4),
            "sigma": round(sigma, 4),
            "spread_logit": round(spread_logit, 4),
            "spread_actual": round(ask_price - bid_price, 4),
            "inventory_adjustment": round(mid_price - reservation_price, 4),
            "time_remaining_frac": round(T_minus_t, 4),
        }

        return round(bid_price, 4), round(ask_price, 4), diagnostics


# ============================================================
# VPIN: Volume-synchronized Probability of Informed Trading
# ============================================================

@dataclass
class VPINConfig:
    """Configuration for VPIN calculation."""
    bucket_size: float = 50.0     # Volume per bucket (in contracts)
    n_buckets: int = 50           # Rolling window of buckets
    alert_threshold: float = 0.70  # VPIN > 0.70 = high toxicity, widen/withdraw
    danger_threshold: float = 0.85  # VPIN > 0.85 = withdraw all quotes


class VPINTracker:
    """
    Volume-synchronized Probability of Informed Trading.

    Measures order flow toxicity: when buy/sell volume becomes heavily
    imbalanced, it signals that informed traders (who know the outcome)
    are aggressively taking liquidity. A market maker should widen
    spreads or withdraw quotes entirely.

    VPIN = |V_buy - V_sell| / (V_buy + V_sell)

    Volume is accumulated into fixed-size "buckets" (volume bars).
    Each bucket records the buy/sell split. VPIN is computed over
    a rolling window of the last N buckets.

    A VPIN of 0.0 = perfectly balanced flow (noise traders).
    A VPIN of 1.0 = 100% one-directional flow (fully informed).

    References:
    - Easley, López de Prado & O'Hara (2012)
    - The original paper used CDF of normal distribution to classify
      trades; we use a simpler tick-rule approach for prediction markets.
    """

    def __init__(self, config: Optional[VPINConfig] = None):
        self.config = config or VPINConfig()
        # Per-token tracking
        self._buckets: Dict[str, deque] = {}  # token_id -> deque of (buy_vol, sell_vol)
        self._current_bucket: Dict[str, Dict[str, float]] = {}  # token_id -> {buy, sell}
        self._last_price: Dict[str, float] = {}

    def record_trade(self, token_id: str, price: float, size: float):
        """
        Record a trade and classify it as buy or sell using the tick rule.

        Tick rule: if price > last price → buy-initiated.
                   if price < last price → sell-initiated.
                   if price == last price → split 50/50.
        """
        if token_id not in self._buckets:
            self._buckets[token_id] = deque(maxlen=self.config.n_buckets)
            self._current_bucket[token_id] = {"buy": 0.0, "sell": 0.0}

        last = self._last_price.get(token_id)
        self._last_price[token_id] = price

        bucket = self._current_bucket[token_id]

        if last is None:
            # First trade — split 50/50
            bucket["buy"] += size / 2
            bucket["sell"] += size / 2
        elif price > last:
            bucket["buy"] += size
        elif price < last:
            bucket["sell"] += size
        else:
            # Same price — split
            bucket["buy"] += size / 2
            bucket["sell"] += size / 2

        # Check if bucket is full
        total = bucket["buy"] + bucket["sell"]
        if total >= self.config.bucket_size:
            self._buckets[token_id].append((bucket["buy"], bucket["sell"]))
            self._current_bucket[token_id] = {"buy": 0.0, "sell": 0.0}

    def get_vpin(self, token_id: str) -> Optional[float]:
        """
        Compute VPIN for a token.

        Returns None if insufficient data (need at least n_buckets/2 buckets).
        """
        buckets = self._buckets.get(token_id)
        if not buckets or len(buckets) < self.config.n_buckets // 2:
            return None

        total_buy = sum(b for b, _ in buckets)
        total_sell = sum(s for _, s in buckets)
        total = total_buy + total_sell

        if total == 0:
            return 0.0

        return abs(total_buy - total_sell) / total

    def is_toxic(self, token_id: str) -> Tuple[bool, float]:
        """
        Check if order flow is toxic (informed traders present).

        Returns (is_toxic, vpin_value).
        """
        vpin = self.get_vpin(token_id)
        if vpin is None:
            return False, 0.0
        return vpin >= self.config.alert_threshold, vpin

    def should_withdraw(self, token_id: str) -> bool:
        """Check if quotes should be withdrawn entirely (extreme toxicity)."""
        vpin = self.get_vpin(token_id)
        if vpin is None:
            return False
        return vpin >= self.config.danger_threshold

    def get_all_vpins(self) -> Dict[str, float]:
        """Get VPIN for all tracked tokens."""
        result = {}
        for token_id in self._buckets:
            vpin = self.get_vpin(token_id)
            if vpin is not None:
                result[token_id] = round(vpin, 4)
        return result


# ============================================================
# Monte Carlo Kelly
# ============================================================

@dataclass
class MonteCarloKellyConfig:
    """Configuration for Monte Carlo Kelly sizing."""
    n_simulations: int = 5000       # Number of Monte Carlo paths
    n_trades_per_path: int = 100    # Trades per simulated path
    max_drawdown_pct: float = 0.15  # Target max drawdown (95th percentile)
    confidence_level: float = 0.95  # Percentile for drawdown targeting
    min_historical_trades: int = 10  # Need this many trades before MC kicks in


class MonteCarloKelly:
    """
    Monte Carlo Kelly position sizing with empirical return distributions.

    The textbook Kelly formula assumes you know your edge with certainty.
    In practice, your edge estimate has uncertainty. Naive Kelly overbets
    when edge is uncertain, leading to ruin even with a genuine edge.

    This implementation:
    1. Collects historical trade returns
    2. Resamples returns (bootstrap) to create N simulated paths
    3. For each path, computes the max drawdown
    4. Finds the position size where the 95th-percentile drawdown
       equals the target (e.g., 15%)
    5. This is the "empirical Kelly" — automatically haircuts for uncertainty

    f_empirical = f_kelly × (1 - CV_edge)
    Where CV_edge = coefficient of variation of edge estimates across sims.
    """

    def __init__(self, config: Optional[MonteCarloKellyConfig] = None):
        self.config = config or MonteCarloKellyConfig()
        self._trade_returns: Dict[str, List[float]] = {}  # strategy -> [returns]

    def record_return(self, strategy: str, return_pct: float):
        """Record a realized trade return for a strategy."""
        if strategy not in self._trade_returns:
            self._trade_returns[strategy] = []
        self._trade_returns[strategy].append(return_pct)

    def compute_size(
        self,
        strategy: str,
        naive_kelly_fraction: float,
        bankroll: float,
    ) -> Tuple[float, dict]:
        """
        Compute Monte Carlo-adjusted Kelly size.

        Args:
            strategy: Strategy name (to look up historical returns)
            naive_kelly_fraction: The standard Kelly fraction (f*)
            bankroll: Current bankroll

        Returns:
            (adjusted_bet_usd, diagnostics)
        """
        returns = self._trade_returns.get(strategy, [])
        cfg = self.config

        # Fall back to naive Kelly with a conservative haircut if not enough data
        if len(returns) < cfg.min_historical_trades:
            haircut = 0.5  # 50% haircut when no data
            return round(naive_kelly_fraction * haircut * bankroll, 2), {
                "method": "naive_kelly_with_haircut",
                "haircut": haircut,
                "reason": f"insufficient data ({len(returns)}/{cfg.min_historical_trades})",
            }

        # Run Monte Carlo simulation
        drawdowns = []
        edge_estimates = []

        for _ in range(cfg.n_simulations):
            # Bootstrap: resample returns with replacement
            path = random.choices(returns, k=cfg.n_trades_per_path)

            # Simulate equity curve
            equity = 1.0
            peak = 1.0
            max_dd = 0.0

            for r in path:
                equity *= (1.0 + naive_kelly_fraction * r)
                if equity > peak:
                    peak = equity
                dd = (peak - equity) / peak if peak > 0 else 0
                if dd > max_dd:
                    max_dd = dd

            drawdowns.append(max_dd)
            # Track the edge (mean return of this path)
            path_mean = sum(path) / len(path) if path else 0
            edge_estimates.append(path_mean)

        # Sort drawdowns and find the confidence-level percentile
        drawdowns.sort()
        idx = int(cfg.confidence_level * len(drawdowns))
        percentile_dd = drawdowns[min(idx, len(drawdowns) - 1)]

        # Coefficient of variation of edge
        mean_edge = sum(edge_estimates) / len(edge_estimates) if edge_estimates else 0
        var_edge = sum((e - mean_edge) ** 2 for e in edge_estimates) / len(edge_estimates) if edge_estimates else 0
        std_edge = math.sqrt(var_edge)
        cv_edge = std_edge / abs(mean_edge) if abs(mean_edge) > 1e-8 else 1.0

        # Scale factor: reduce Kelly by the ratio of target drawdown to simulated drawdown
        if percentile_dd > 0:
            scale = min(1.0, cfg.max_drawdown_pct / percentile_dd)
        else:
            scale = 1.0

        # Also apply CV haircut
        cv_haircut = max(0.1, 1.0 - cv_edge)
        adjusted_fraction = naive_kelly_fraction * scale * cv_haircut

        bet_usd = round(adjusted_fraction * bankroll, 2)

        diagnostics = {
            "method": "monte_carlo_kelly",
            "n_simulations": cfg.n_simulations,
            "historical_trades": len(returns),
            "naive_kelly_fraction": round(naive_kelly_fraction, 4),
            "adjusted_fraction": round(adjusted_fraction, 4),
            "scale_factor": round(scale, 4),
            "cv_haircut": round(cv_haircut, 4),
            "cv_edge": round(cv_edge, 4),
            "percentile_drawdown": round(percentile_dd, 4),
            "target_drawdown": cfg.max_drawdown_pct,
            "mean_edge": round(mean_edge, 4),
            "median_drawdown": round(drawdowns[len(drawdowns) // 2], 4),
        }

        return max(0.0, bet_usd), diagnostics


# ============================================================
# Bayesian Probability Updater (Beta-Bernoulli)
# ============================================================

@dataclass
class BayesianEstimate:
    """A Bayesian probability estimate with uncertainty."""
    alpha: float        # Beta distribution alpha (pseudo-wins)
    beta: float         # Beta distribution beta (pseudo-losses)

    @property
    def mean(self) -> float:
        """Posterior mean: E[p] = α / (α + β)"""
        return self.alpha / (self.alpha + self.beta) if (self.alpha + self.beta) > 0 else 0.5

    @property
    def variance(self) -> float:
        """Posterior variance."""
        a, b = self.alpha, self.beta
        n = a + b
        if n <= 0:
            return 0.25
        return (a * b) / (n * n * (n + 1))

    @property
    def std(self) -> float:
        return math.sqrt(self.variance)

    @property
    def confidence_interval_95(self) -> Tuple[float, float]:
        """Approximate 95% credible interval using normal approximation."""
        m = self.mean
        s = self.std
        return (max(0.0, m - 1.96 * s), min(1.0, m + 1.96 * s))

    @property
    def sample_size(self) -> float:
        """Effective sample size (total pseudo-observations)."""
        return self.alpha + self.beta


class BayesianUpdater:
    """
    Beta-Bernoulli Bayesian updater for prediction market probabilities.

    Instead of using a fixed probability estimate, this maintains a
    Beta(α, β) posterior distribution. Start with a prior (e.g., the
    market price), then update as new evidence arrives (polls, news,
    historical resolution data).

    The Beta distribution is the conjugate prior for Bernoulli outcomes,
    which is exactly what binary prediction markets are.

    Usage:
        updater = BayesianUpdater()
        # Start with market price as prior (concentrated)
        updater.set_prior("election_yes", market_price=0.60, confidence=20)
        # New poll: 55% favorable → update
        updater.update_with_signal("election_yes", signal_mean=0.55, signal_weight=5)
        # Get posterior
        est = updater.get_estimate("election_yes")
        print(f"P(yes) = {est.mean:.2%} ± {est.std:.2%}")
    """

    def __init__(self):
        self._estimates: Dict[str, BayesianEstimate] = {}

    def set_prior(self, key: str, market_price: float, confidence: float = 10.0):
        """
        Set a prior from the market price.

        Args:
            key: Identifier (e.g., token_id or market_id)
            market_price: Current market price (used as prior mean)
            confidence: How many pseudo-observations the prior is worth.
                        Higher = more resistant to updates. Market prices
                        with high volume deserve higher confidence.
        """
        p = max(0.01, min(0.99, market_price))
        alpha = p * confidence
        beta = (1.0 - p) * confidence
        self._estimates[key] = BayesianEstimate(alpha=alpha, beta=beta)

    def update_with_outcome(self, key: str, success: bool):
        """
        Update after observing a binary outcome.

        This is the purest Bayesian update: observe YES → alpha += 1,
        observe NO → beta += 1.
        """
        est = self._estimates.get(key)
        if est is None:
            est = BayesianEstimate(alpha=1.0, beta=1.0)  # Uniform prior
            self._estimates[key] = est

        if success:
            est.alpha += 1.0
        else:
            est.beta += 1.0

    def update_with_signal(self, key: str, signal_mean: float, signal_weight: float = 1.0):
        """
        Update with a soft signal (e.g., a poll result, model prediction).

        Treats the signal as equivalent to observing `signal_weight` outcomes
        with a success rate of `signal_mean`.

        Args:
            key: Identifier
            signal_mean: Signal value (0-1), e.g., poll says 55% → 0.55
            signal_weight: How many pseudo-observations this signal is worth
        """
        est = self._estimates.get(key)
        if est is None:
            est = BayesianEstimate(alpha=1.0, beta=1.0)
            self._estimates[key] = est

        signal_mean = max(0.01, min(0.99, signal_mean))
        est.alpha += signal_mean * signal_weight
        est.beta += (1.0 - signal_mean) * signal_weight

    def get_estimate(self, key: str) -> Optional[BayesianEstimate]:
        """Get the current posterior estimate."""
        return self._estimates.get(key)

    def get_edge_vs_market(self, key: str, market_price: float) -> Optional[float]:
        """
        Compute edge: difference between Bayesian posterior and market price.

        Positive = our model thinks the event is more likely than the market.
        """
        est = self._estimates.get(key)
        if est is None:
            return None
        return est.mean - market_price

    def get_all_estimates(self) -> Dict[str, dict]:
        """Get all estimates as a serializable dict."""
        return {
            key: {
                "mean": round(est.mean, 4),
                "std": round(est.std, 4),
                "ci_95": [round(c, 4) for c in est.confidence_interval_95],
                "alpha": round(est.alpha, 2),
                "beta": round(est.beta, 2),
                "sample_size": round(est.sample_size, 1),
            }
            for key, est in self._estimates.items()
        }
