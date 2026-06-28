"""
Backtesting engine for strategy evaluation.

This module implements a vectorized backtest with:
- Walk-forward simulation
- Transaction costs and slippage
- Risk controls
- Comprehensive performance tracking
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any, Protocol, runtime_checkable
from datetime import date, timedelta
import numpy as np
import pandas as pd
import logging
import json

logger = logging.getLogger(__name__)
from hashlib import sha256


@runtime_checkable
class BaseRanker(Protocol):
    """Structural interface for a ranking model used by the backtest engine.

    Previously imported from the (now-retired) stock ML stack (``..models.estimators``);
    kept here as a lightweight structural type so the asset-agnostic backtest engine
    stays import-clean without the heavy ML dependencies (ROADMAP A1).
    """

    def fit(self, X, y) -> "BaseRanker": ...
    def predict(self, X): ...
    def get_feature_importance(self) -> Dict[str, float]: ...


from ..portfolio.optimizer import (
    PortfolioConfig,
    PortfolioOptimizer,
    MeanVarianceOptimizer,
    estimate_covariance,
    estimate_expected_returns,
)
from ..portfolio.risk import RiskManager
from ..portfolio.execution import ExecutionModel, TransactionCostModel
from .metrics import PerformanceMetrics, compute_metrics


@dataclass
class BacktestConfig:
    """Configuration for backtesting."""

    # Time period
    start_date: Optional[date] = None
    end_date: Optional[date] = None

    # Rebalancing
    rebalance_frequency: str = "weekly"  # daily, weekly, monthly
    rebalance_day: int = 0  # 0=Monday for weekly, 1-31 for monthly

    # Initial capital
    initial_cash: float = 100_000.0

    # Costs
    transaction_cost_bps: float = 10.0
    slippage_bps: float = 5.0

    # Portfolio construction
    portfolio_config: PortfolioConfig = field(default_factory=PortfolioConfig)

    # Risk settings
    target_volatility: float = 0.15
    max_drawdown_limit: float = 0.20

    # Benchmark
    benchmark_ticker: str = "SPY"

    # Reproducibility
    random_seed: int = 42

    def to_dict(self) -> dict:
        return {
            "start_date": str(self.start_date) if self.start_date else None,
            "end_date": str(self.end_date) if self.end_date else None,
            "rebalance_frequency": self.rebalance_frequency,
            "rebalance_day": self.rebalance_day,
            "initial_cash": self.initial_cash,
            "transaction_cost_bps": self.transaction_cost_bps,
            "slippage_bps": self.slippage_bps,
            "portfolio_config": self.portfolio_config.to_dict(),
            "target_volatility": self.target_volatility,
            "max_drawdown_limit": self.max_drawdown_limit,
            "benchmark_ticker": self.benchmark_ticker,
            "random_seed": self.random_seed,
        }

    def compute_hash(self) -> str:
        config_str = json.dumps(self.to_dict(), sort_keys=True)
        return sha256(config_str.encode()).hexdigest()[:16]


@dataclass
class BacktestResult:
    """Complete backtest results."""

    config: BacktestConfig

    # Time series
    equity_curve: pd.Series  # Portfolio value over time
    returns: pd.Series  # Daily returns
    weights_history: pd.DataFrame  # Daily weights (dates x tickers)
    holdings_history: pd.DataFrame  # Daily shares (dates x tickers)

    # Trades
    trades: List[Dict]

    # Benchmark
    benchmark_curve: pd.Series
    benchmark_returns: pd.Series

    # Metrics
    metrics: PerformanceMetrics

    # Diagnostics
    turnover_series: pd.Series
    cost_series: pd.Series
    drawdown_series: pd.Series

    # Regime-stratified metrics (optional, populated by analyze_by_regime)
    regime_metrics: Optional[Dict[str, Dict[str, float]]] = None

    def to_dict(self) -> dict:
        """Serialize for storage."""
        result = {
            "config": self.config.to_dict(),
            "equity_curve": self.equity_curve.to_dict(),
            "returns": self.returns.to_dict(),
            "metrics": self.metrics.to_dict(),
            "n_trades": len(self.trades),
        }
        if self.regime_metrics:
            result["regime_metrics"] = self.regime_metrics
        return result


class BacktestEngine:
    """
    Main backtesting engine.

    Simulates strategy execution with:
    - Walk-forward prediction and rebalancing
    - Realistic transaction costs
    - Risk overlays
    - Performance tracking
    """

    def __init__(self, config: BacktestConfig):
        self.config = config
        self.execution_model = ExecutionModel(
            TransactionCostModel(
                commission_bps=config.transaction_cost_bps,
                spread_bps=config.slippage_bps / 2
            ),
            slippage_bps=config.slippage_bps / 2
        )
        self.risk_manager = RiskManager(
            target_volatility=config.target_volatility,
            max_drawdown_limit=config.max_drawdown_limit
        )
        self.portfolio_optimizer = MeanVarianceOptimizer(config.portfolio_config)

    def run(
        self,
        prices: pd.DataFrame,
        model: BaseRanker,
        features: pd.DataFrame,
        volumes: Optional[pd.DataFrame] = None,
        sector_map: Optional[Dict[str, str]] = None
    ) -> BacktestResult:
        """
        Run backtest simulation.

        Args:
            prices: Price DataFrame (dates x tickers)
            model: Trained ranking model
            features: Feature DataFrame for making predictions
            volumes: Optional volume data
            sector_map: Optional ticker -> sector mapping

        Returns:
            BacktestResult with all performance data
        """
        np.random.seed(self.config.random_seed)

        # Setup
        dates = prices.index.tolist()
        tickers = prices.columns.tolist()

        # Determine backtest period
        start_idx = 0
        if self.config.start_date:
            start_idx = next(
                (i for i, d in enumerate(dates) if d >= self.config.start_date),
                0
            )

        end_idx = len(dates)
        if self.config.end_date:
            end_idx = next(
                (i for i, d in enumerate(dates) if d > self.config.end_date),
                len(dates)
            )

        # Skip early dates for feature warmup
        start_idx = max(start_idx, 252)  # Need 1 year for features

        # Get rebalance dates
        rebalance_dates = self._get_rebalance_dates(
            dates[start_idx:end_idx]
        )

        # Initialize tracking
        cash = self.config.initial_cash
        holdings = pd.Series(0.0, index=tickers)  # Shares held
        weights = pd.Series(0.0, index=tickers)

        equity_history = []
        returns_history = []
        weights_history = []
        holdings_history = []
        trades_history = []
        turnover_history = []
        cost_history = []
        drawdown_history = []

        prev_equity = cash

        # Main simulation loop
        for i, current_date in enumerate(dates[start_idx:end_idx]):
            # Get current prices
            current_prices = prices.loc[current_date]

            # Compute current portfolio value
            portfolio_value = cash + (holdings * current_prices).sum()

            # Compute return
            daily_return = (portfolio_value / prev_equity) - 1 if prev_equity > 0 else 0
            prev_equity = portfolio_value

            # Update weights
            if portfolio_value > 0:
                weights = (holdings * current_prices) / portfolio_value
            else:
                weights = pd.Series(0.0, index=tickers)

            # Track
            equity_history.append((current_date, portfolio_value))
            returns_history.append((current_date, daily_return))
            weights_history.append((current_date, weights.to_dict()))
            holdings_history.append((current_date, holdings.to_dict()))

            # Check for rebalance
            if current_date in rebalance_dates:
                # Generate predictions
                if current_date in features.index:
                    current_features = features.loc[[current_date]]

                    # Filter to features for available tickers
                    available_tickers = [
                        t for t in tickers
                        if any(col.startswith(f"{t}_") for col in current_features.columns)
                    ]

                    if available_tickers:
                        # Get model scores
                        try:
                            scores = self._get_scores(
                                model, current_features, available_tickers
                            )

                            # Estimate covariance
                            lookback_start = max(0, start_idx + i - 252)
                            historical_prices = prices.iloc[lookback_start:start_idx + i]
                            returns = historical_prices.pct_change().dropna()

                            if len(returns) > 63:
                                cov = estimate_covariance(returns)

                                # Estimate expected returns
                                expected_rets = estimate_expected_returns(
                                    scores, returns, blend_weight=0.7
                                )

                                # Optimize portfolio
                                target_weights = self.portfolio_optimizer.optimize(
                                    expected_rets,
                                    cov,
                                    current_weights=weights,
                                    sector_map=sector_map
                                )

                                # Apply risk overlay
                                if len(equity_history) > 21:
                                    equity_series = pd.Series(
                                        [e[1] for e in equity_history],
                                        index=[e[0] for e in equity_history]
                                    )
                                    return_series = pd.Series(
                                        [r[1] for r in returns_history],
                                        index=[r[0] for r in returns_history]
                                    )
                                    target_weights = self.risk_manager.apply_risk_overlay(
                                        target_weights, equity_series, return_series
                                    )

                                # Execute trades
                                trades, cost, new_holdings, new_cash = self._execute_rebalance(
                                    holdings, cash, target_weights,
                                    portfolio_value, current_prices, volumes
                                )

                                # Update state
                                holdings = new_holdings
                                cash = new_cash

                                # Track
                                turnover = sum(abs(t["weight_change"]) for t in trades) / 2
                                turnover_history.append((current_date, turnover))
                                cost_history.append((current_date, cost))
                                trades_history.extend(trades)

                        except Exception as e:
                            logger.warning(f"Rebalance failed on {current_date}: {e}")

            # Compute drawdown
            if equity_history:
                peak = max(e[1] for e in equity_history)
                dd = (portfolio_value - peak) / peak if peak > 0 else 0
                drawdown_history.append((current_date, dd))

        # Build result DataFrames
        equity_curve = pd.Series(
            [e[1] for e in equity_history],
            index=pd.DatetimeIndex([e[0] for e in equity_history])
        )
        returns = pd.Series(
            [r[1] for r in returns_history],
            index=pd.DatetimeIndex([r[0] for r in returns_history])
        )

        weights_df = pd.DataFrame(
            [w[1] for w in weights_history],
            index=pd.DatetimeIndex([w[0] for w in weights_history])
        )
        holdings_df = pd.DataFrame(
            [h[1] for h in holdings_history],
            index=pd.DatetimeIndex([h[0] for h in holdings_history])
        )

        # Get benchmark
        benchmark_curve, benchmark_returns = self._get_benchmark(
            prices, dates[start_idx:end_idx]
        )

        # Compute metrics
        metrics = compute_metrics(
            returns, benchmark_returns, self.config.initial_cash
        )

        # Build timeseries for diagnostics
        turnover_series = pd.Series(
            [t[1] for t in turnover_history] if turnover_history else [0],
            index=pd.DatetimeIndex([t[0] for t in turnover_history]) if turnover_history else [dates[start_idx]]
        )
        cost_series = pd.Series(
            [c[1] for c in cost_history] if cost_history else [0],
            index=pd.DatetimeIndex([c[0] for c in cost_history]) if cost_history else [dates[start_idx]]
        )
        drawdown_series = pd.Series(
            [d[1] for d in drawdown_history] if drawdown_history else [0],
            index=pd.DatetimeIndex([d[0] for d in drawdown_history]) if drawdown_history else [dates[start_idx]]
        )

        return BacktestResult(
            config=self.config,
            equity_curve=equity_curve,
            returns=returns,
            weights_history=weights_df,
            holdings_history=holdings_df,
            trades=trades_history,
            benchmark_curve=benchmark_curve,
            benchmark_returns=benchmark_returns,
            metrics=metrics,
            turnover_series=turnover_series,
            cost_series=cost_series,
            drawdown_series=drawdown_series
        )

    def _get_rebalance_dates(self, dates: List) -> set:
        """Get set of dates when rebalancing should occur."""
        rebalance_dates = set()

        for d in dates:
            if isinstance(d, pd.Timestamp):
                d = d.date()

            if self.config.rebalance_frequency == "daily":
                rebalance_dates.add(d)

            elif self.config.rebalance_frequency == "weekly":
                # Rebalance on specified weekday (0=Monday)
                if d.weekday() == self.config.rebalance_day:
                    rebalance_dates.add(d)

            elif self.config.rebalance_frequency == "monthly":
                # Rebalance on first trading day of month or specified day
                if d.day <= 5:  # Within first week
                    rebalance_dates.add(d)

        return rebalance_dates

    def _get_scores(
        self,
        model: BaseRanker,
        features: pd.DataFrame,
        tickers: List[str]
    ) -> pd.Series:
        """Get model scores for available tickers."""
        # Reshape features for prediction
        # Features are named like "AAPL_ret_1d", need to create feature matrix

        scores = {}
        for ticker in tickers:
            # Extract features for this ticker
            ticker_cols = [c for c in features.columns if c.startswith(f"{ticker}_")]
            if not ticker_cols:
                continue

            ticker_features = features[ticker_cols]

            # Rename columns to remove ticker prefix (for model compatibility)
            rename_map = {c: c.replace(f"{ticker}_", "") for c in ticker_cols}
            ticker_features = ticker_features.rename(columns=rename_map)

            # Check for NaN
            if ticker_features.isna().any().any():
                continue

            try:
                # Model expects DataFrame, returns Series
                pred = model.predict(ticker_features)
                scores[ticker] = pred.iloc[0] if len(pred) > 0 else 0
            except Exception:
                scores[ticker] = 0

        return pd.Series(scores)

    def _execute_rebalance(
        self,
        holdings: pd.Series,
        cash: float,
        target_weights: pd.Series,
        portfolio_value: float,
        prices: pd.Series,
        volumes: Optional[pd.DataFrame]
    ) -> Tuple[List[Dict], float, pd.Series, float]:
        """Execute rebalancing trades."""
        # Current weights
        current_weights = (holdings * prices) / portfolio_value if portfolio_value > 0 else holdings * 0

        # Compute trades
        trade_orders = self.execution_model.compute_trades(
            current_weights, target_weights, portfolio_value, prices
        )

        if not trade_orders:
            return [], 0, holdings, cash

        # Execute with costs
        vol_series = None
        if volumes is not None:
            vol_series = volumes.iloc[-21:].mean() if len(volumes) > 21 else None

        executed, total_cost = self.execution_model.execute_trades(
            trade_orders,
            volumes=vol_series,
            random_seed=None  # Let the engine random seed control
        )

        # Update holdings and cash
        new_holdings = holdings.copy()
        new_cash = cash - total_cost

        trades = []
        for trade in executed:
            if trade.side == "buy":
                new_holdings[trade.ticker] += trade.shares
                new_cash -= trade.notional
            else:
                new_holdings[trade.ticker] -= trade.shares
                new_cash += trade.notional

            trades.append({
                "ticker": trade.ticker,
                "side": trade.side,
                "shares": trade.shares,
                "price": trade.price,
                "notional": trade.notional,
                "cost": trade.total_cost,
                "weight_change": next(
                    (o.weight_change for o in trade_orders if o.ticker == trade.ticker),
                    0
                )
            })

        return trades, total_cost, new_holdings, new_cash

    def _get_benchmark(
        self,
        prices: pd.DataFrame,
        dates: List
    ) -> Tuple[pd.Series, pd.Series]:
        """Get benchmark equity curve and returns."""
        benchmark_ticker = self.config.benchmark_ticker

        if benchmark_ticker in prices.columns:
            benchmark_prices = prices[benchmark_ticker].loc[dates]
            benchmark_returns = benchmark_prices.pct_change().fillna(0)
            benchmark_curve = (1 + benchmark_returns).cumprod() * self.config.initial_cash
            return benchmark_curve, benchmark_returns

        # Fallback: equal weight universe
        avg_returns = prices.loc[dates].pct_change().mean(axis=1).fillna(0)
        benchmark_curve = (1 + avg_returns).cumprod() * self.config.initial_cash
        return benchmark_curve, avg_returns
