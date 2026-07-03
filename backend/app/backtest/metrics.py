"""
Performance metrics computation for backtesting.

Computes standard quant performance metrics:
- Returns metrics (CAGR, volatility)
- Risk-adjusted (Sharpe, Sortino, Calmar)
- Drawdown analysis
- Win/loss statistics
"""

from dataclasses import dataclass
from typing import Dict, Optional
import numpy as np
import pandas as pd


@dataclass
class PerformanceMetrics:
    """Comprehensive performance metrics."""

    # Return metrics
    total_return: float  # Total percentage return
    cagr: float  # Compound annual growth rate
    volatility: float  # Annualized volatility
    skewness: float  # Return distribution skewness
    kurtosis: float  # Return distribution kurtosis

    # Risk-adjusted metrics
    sharpe_ratio: float  # Annualized Sharpe
    sortino_ratio: float  # Sortino (downside risk)
    calmar_ratio: float  # CAGR / Max Drawdown

    # Drawdown metrics
    max_drawdown: float  # Maximum drawdown
    avg_drawdown: float  # Average drawdown
    max_drawdown_duration: int  # Days in max drawdown

    # Win/loss statistics
    win_rate: float  # Percentage of positive days
    profit_factor: float  # Gross profits / Gross losses
    avg_win: float  # Average winning day return
    avg_loss: float  # Average losing day return
    best_day: float  # Best single day return
    worst_day: float  # Worst single day return

    # Benchmark comparison
    alpha: float  # Jensen's alpha
    beta: float  # Market beta
    information_ratio: float  # Active return / tracking error
    tracking_error: float  # Std of active returns

    # Trading statistics
    num_trades: int
    avg_turnover: float  # Average portfolio turnover
    total_costs: float  # Total transaction costs

    def to_dict(self) -> dict:
        return {
            "total_return": self.total_return,
            "cagr": self.cagr,
            "volatility": self.volatility,
            "skewness": self.skewness,
            "kurtosis": self.kurtosis,
            "sharpe_ratio": self.sharpe_ratio,
            "sortino_ratio": self.sortino_ratio,
            "calmar_ratio": self.calmar_ratio,
            "max_drawdown": self.max_drawdown,
            "avg_drawdown": self.avg_drawdown,
            "max_drawdown_duration": self.max_drawdown_duration,
            "win_rate": self.win_rate,
            "profit_factor": self.profit_factor,
            "avg_win": self.avg_win,
            "avg_loss": self.avg_loss,
            "best_day": self.best_day,
            "worst_day": self.worst_day,
            "alpha": self.alpha,
            "beta": self.beta,
            "information_ratio": self.information_ratio,
            "tracking_error": self.tracking_error,
            "num_trades": self.num_trades,
            "avg_turnover": self.avg_turnover,
            "total_costs": self.total_costs,
        }

    def format_summary(self) -> str:
        """Format metrics as readable summary."""
        return f"""
Performance Summary
==================
Total Return: {self.total_return:.1%}
CAGR: {self.cagr:.1%}
Volatility: {self.volatility:.1%}

Risk-Adjusted Returns
--------------------
Sharpe Ratio: {self.sharpe_ratio:.2f}
Sortino Ratio: {self.sortino_ratio:.2f}
Calmar Ratio: {self.calmar_ratio:.2f}

Drawdown Analysis
-----------------
Max Drawdown: {self.max_drawdown:.1%}
Avg Drawdown: {self.avg_drawdown:.1%}
Max DD Duration: {self.max_drawdown_duration} days

Win/Loss Statistics
------------------
Win Rate: {self.win_rate:.1%}
Profit Factor: {self.profit_factor:.2f}
Best Day: {self.best_day:.1%}
Worst Day: {self.worst_day:.1%}

Benchmark Comparison
-------------------
Alpha: {self.alpha:.1%}
Beta: {self.beta:.2f}
Information Ratio: {self.information_ratio:.2f}
Tracking Error: {self.tracking_error:.1%}
""".strip()


def compute_metrics(
    returns: pd.Series,
    benchmark_returns: Optional[pd.Series] = None,
    initial_value: float = 100000,
    risk_free_rate: float = 0.04,
    trading_days: int = 252,
    num_trades: int = 0,
    total_turnover: float = 0,
    total_costs: float = 0
) -> PerformanceMetrics:
    """
    Compute comprehensive performance metrics.

    Args:
        returns: Daily return series
        benchmark_returns: Optional benchmark returns
        initial_value: Initial portfolio value
        risk_free_rate: Annual risk-free rate
        trading_days: Trading days per year
        num_trades: Total number of trades
        total_turnover: Cumulative turnover
        total_costs: Total transaction costs

    Returns:
        PerformanceMetrics object
    """
    # Handle edge cases
    if len(returns) < 2:
        return _empty_metrics()

    returns = returns.replace([np.inf, -np.inf], np.nan).dropna()
    if len(returns) < 2:
        return _empty_metrics()

    # Total and compound return
    cumulative = (1 + returns).cumprod()
    total_return = cumulative.iloc[-1] - 1

    # CAGR
    n_years = len(returns) / trading_days
    if n_years > 0 and total_return > -1:
        cagr = (1 + total_return) ** (1 / n_years) - 1
    else:
        cagr = 0

    # Volatility
    volatility = returns.std() * np.sqrt(trading_days)

    # Distribution stats
    skewness = returns.skew() if len(returns) > 3 else 0
    kurtosis = returns.kurtosis() if len(returns) > 4 else 0

    # Risk-adjusted returns
    daily_rf = risk_free_rate / trading_days
    excess_returns = returns - daily_rf

    sharpe = (excess_returns.mean() * trading_days) / volatility if volatility > 0 else 0

    # Sortino (downside deviation)
    downside_returns = returns[returns < 0]
    if len(downside_returns) > 0:
        downside_dev = downside_returns.std() * np.sqrt(trading_days)
        sortino = (excess_returns.mean() * trading_days) / downside_dev if downside_dev > 0 else 0
    else:
        sortino = sharpe

    # Drawdown analysis
    running_max = cumulative.expanding().max()
    drawdown = (cumulative - running_max) / running_max
    max_dd = drawdown.min()
    avg_dd = drawdown[drawdown < 0].mean() if (drawdown < 0).any() else 0

    # Max drawdown duration
    in_drawdown = drawdown < 0
    if in_drawdown.any():
        dd_groups = (~in_drawdown).cumsum()
        dd_lengths = in_drawdown.groupby(dd_groups).sum()
        max_dd_duration = int(dd_lengths.max()) if len(dd_lengths) > 0 else 0
    else:
        max_dd_duration = 0

    # Calmar
    calmar = cagr / abs(max_dd) if max_dd < 0 else 0

    # Win/loss stats
    winning = returns[returns > 0]
    losing = returns[returns < 0]

    win_rate = len(winning) / len(returns) if len(returns) > 0 else 0
    avg_win = winning.mean() if len(winning) > 0 else 0
    avg_loss = losing.mean() if len(losing) > 0 else 0

    gross_profits = winning.sum() if len(winning) > 0 else 0
    gross_losses = abs(losing.sum()) if len(losing) > 0 else 1e-10
    profit_factor = gross_profits / gross_losses

    best_day = returns.max()
    worst_day = returns.min()

    # Benchmark comparison
    if benchmark_returns is not None and len(benchmark_returns) > 0:
        # Align
        aligned = pd.concat([returns, benchmark_returns], axis=1).dropna()
        if len(aligned) > 21:
            port_ret = aligned.iloc[:, 0]
            bench_ret = aligned.iloc[:, 1]

            # Beta
            cov = port_ret.cov(bench_ret)
            var = bench_ret.var()
            beta = cov / var if var > 0 else 1

            # Alpha (annualized)
            bench_excess = (bench_ret.mean() * trading_days) - risk_free_rate
            alpha = (port_ret.mean() * trading_days) - risk_free_rate - beta * bench_excess

            # Tracking error and information ratio
            active_returns = port_ret - bench_ret
            tracking_error = active_returns.std() * np.sqrt(trading_days)
            info_ratio = (active_returns.mean() * trading_days) / tracking_error if tracking_error > 0 else 0
        else:
            alpha, beta = 0, 1
            tracking_error, info_ratio = 0, 0
    else:
        alpha, beta = 0, 1
        tracking_error, info_ratio = 0, 0

    # Average turnover
    n_rebalances = max(num_trades / 10, 1)  # Rough estimate
    avg_turnover = total_turnover / n_rebalances if n_rebalances > 0 else 0

    return PerformanceMetrics(
        total_return=total_return,
        cagr=cagr,
        volatility=volatility,
        skewness=skewness,
        kurtosis=kurtosis,
        sharpe_ratio=sharpe,
        sortino_ratio=sortino,
        calmar_ratio=calmar,
        max_drawdown=max_dd,
        avg_drawdown=avg_dd,
        max_drawdown_duration=max_dd_duration,
        win_rate=win_rate,
        profit_factor=profit_factor,
        avg_win=avg_win,
        avg_loss=avg_loss,
        best_day=best_day,
        worst_day=worst_day,
        alpha=alpha,
        beta=beta,
        information_ratio=info_ratio,
        tracking_error=tracking_error,
        num_trades=num_trades,
        avg_turnover=avg_turnover,
        total_costs=total_costs
    )


def _empty_metrics() -> PerformanceMetrics:
    """Return empty metrics for edge cases."""
    return PerformanceMetrics(
        total_return=0, cagr=0, volatility=0, skewness=0, kurtosis=0,
        sharpe_ratio=0, sortino_ratio=0, calmar_ratio=0,
        max_drawdown=0, avg_drawdown=0, max_drawdown_duration=0,
        win_rate=0, profit_factor=0, avg_win=0, avg_loss=0,
        best_day=0, worst_day=0,
        alpha=0, beta=1, information_ratio=0, tracking_error=0,
        num_trades=0, avg_turnover=0, total_costs=0
    )


def compute_regime_metrics(
    returns: pd.Series,
    benchmark_returns: Optional[pd.Series] = None,
    risk_free_rate: float = 0.04,
    trading_days: int = 252,
) -> Dict[str, Dict[str, float]]:
    """
    Compute performance metrics stratified by market regime.

    Classifies each day into a directional regime using 63-day trailing
    cumulative benchmark returns, then computes Sharpe, return, volatility,
    drawdown, and win rate within each regime.

    Regimes:
    - bull: Top tercile of 63-day trailing benchmark returns
    - bear: Bottom tercile
    - sideways: Middle tercile
    - high_volatility: Rolling 21-day vol above median
    - low_volatility: Rolling 21-day vol at or below median

    Args:
        returns: Strategy daily return series
        benchmark_returns: Market benchmark returns (for regime classification).
            If None, strategy returns are used as the market proxy.
        risk_free_rate: Annual risk-free rate
        trading_days: Trading days per year

    Returns:
        Dict of {regime_name: {sharpe, annualized_return, volatility, max_drawdown,
                                win_rate, n_days, pct_of_total}}
    """
    if len(returns) < 126:
        return {}

    # Use benchmark for regime detection, fall back to strategy returns
    market = benchmark_returns if benchmark_returns is not None else returns
    market = market.reindex(returns.index).fillna(0)

    result = {}

    # ── Directional regimes ─────────────────────────────────
    rolling_ret = market.rolling(63).sum()
    valid = rolling_ret.dropna()

    if len(valid) >= 63:
        ret_33 = valid.quantile(0.33)
        ret_67 = valid.quantile(0.67)

        regime_masks = {
            "bull": rolling_ret >= ret_67,
            "bear": rolling_ret <= ret_33,
            "sideways": (rolling_ret > ret_33) & (rolling_ret < ret_67),
        }

        for name, mask in regime_masks.items():
            mask = mask.reindex(returns.index, fill_value=False)
            regime_ret = returns[mask].dropna()
            if len(regime_ret) >= 21:
                result[name] = _regime_stats(regime_ret, risk_free_rate, trading_days, len(returns))

    # ── Volatility regimes ──────────────────────────────────
    rolling_vol = returns.rolling(21).std()
    vol_median = rolling_vol.median()

    vol_masks = {
        "high_volatility": rolling_vol > vol_median,
        "low_volatility": rolling_vol <= vol_median,
    }

    for name, mask in vol_masks.items():
        mask = mask.reindex(returns.index, fill_value=False)
        regime_ret = returns[mask].dropna()
        if len(regime_ret) >= 21:
            result[name] = _regime_stats(regime_ret, risk_free_rate, trading_days, len(returns))

    return result


def _regime_stats(
    returns: pd.Series,
    risk_free_rate: float,
    trading_days: int,
    total_days: int,
) -> Dict[str, float]:
    """Compute summary stats for a single regime slice."""
    daily_rf = risk_free_rate / trading_days
    excess = returns - daily_rf
    vol = returns.std() * np.sqrt(trading_days)
    sharpe = (excess.mean() * trading_days) / vol if vol > 1e-8 else 0.0

    cumulative = (1 + returns).cumprod()
    running_max = cumulative.expanding().max()
    drawdown = (cumulative - running_max) / running_max
    max_dd = float(drawdown.min()) if len(drawdown) > 0 else 0.0

    return {
        "sharpe": round(float(sharpe), 3),
        "annualized_return": round(float(returns.mean() * trading_days), 4),
        "volatility": round(float(vol), 4),
        "max_drawdown": round(max_dd, 4),
        "win_rate": round(float((returns > 0).mean()), 4),
        "n_days": len(returns),
        "pct_of_total": round(len(returns) / total_days, 4),
    }
