"""
Strategy Component Backtester - Tests individual trading strategies on historical data.

This module allows backtesting of each strategy component used by the Quant Bot:
- Technical indicators (RSI, MACD, Bollinger Bands)
- Statistical signals (Z-score, Hurst exponent)
- Momentum strategies
- Mean reversion strategies
- Factor combinations

All strategies are tested on real historical data to validate their effectiveness.
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta
from enum import Enum
import logging
import yfinance as yf

logger = logging.getLogger(__name__)


class StrategyType(Enum):
    """Types of strategies that can be backtested."""
    RSI_OVERSOLD = "rsi_oversold"
    RSI_OVERBOUGHT = "rsi_overbought"
    MACD_CROSSOVER = "macd_crossover"
    BOLLINGER_BANDS = "bollinger_bands"
    MOMENTUM = "momentum"
    MEAN_REVERSION = "mean_reversion"
    ZSCORE = "zscore"
    COMBINED_MULTI_FACTOR = "combined_multi_factor"


@dataclass
class StrategyConfig:
    """Configuration for a strategy backtest."""
    strategy_type: StrategyType

    # RSI parameters
    rsi_period: int = 14
    rsi_oversold: float = 30
    rsi_overbought: float = 70

    # MACD parameters
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9

    # Bollinger parameters
    bb_period: int = 20
    bb_std: float = 2.0

    # Momentum parameters
    momentum_lookback: int = 20
    momentum_threshold: float = 0.05

    # Mean reversion parameters
    zscore_lookback: int = 20
    zscore_entry: float = -2.0
    zscore_exit: float = 0.0

    # Risk management
    stop_loss_pct: float = 0.05
    take_profit_pct: float = 0.10
    max_holding_days: int = 10

    # Position sizing
    position_size_pct: float = 0.10

    def to_dict(self) -> dict:
        return {
            "strategy_type": self.strategy_type.value,
            "rsi_period": self.rsi_period,
            "rsi_oversold": self.rsi_oversold,
            "rsi_overbought": self.rsi_overbought,
            "macd_fast": self.macd_fast,
            "macd_slow": self.macd_slow,
            "macd_signal": self.macd_signal,
            "bb_period": self.bb_period,
            "bb_std": self.bb_std,
            "momentum_lookback": self.momentum_lookback,
            "momentum_threshold": self.momentum_threshold,
            "zscore_lookback": self.zscore_lookback,
            "zscore_entry": self.zscore_entry,
            "zscore_exit": self.zscore_exit,
            "stop_loss_pct": self.stop_loss_pct,
            "take_profit_pct": self.take_profit_pct,
            "max_holding_days": self.max_holding_days,
            "position_size_pct": self.position_size_pct,
        }


@dataclass
class BacktestTrade:
    """Record of a single trade in the backtest."""
    entry_date: datetime
    exit_date: datetime
    entry_price: float
    exit_price: float
    side: str  # "long" or "short"
    pnl: float
    pnl_pct: float
    holding_days: int
    exit_reason: str  # "signal", "stop_loss", "take_profit", "max_holding"


@dataclass
class StrategyBacktestResult:
    """Complete results from a strategy backtest."""
    config: StrategyConfig
    symbol: str
    start_date: datetime
    end_date: datetime

    # Performance metrics
    total_return: float
    annualized_return: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown: float
    win_rate: float
    profit_factor: float
    avg_trade_pnl: float
    avg_win: float
    avg_loss: float

    # Trade statistics
    total_trades: int
    winning_trades: int
    losing_trades: int
    avg_holding_days: float

    # Risk metrics
    volatility: float
    calmar_ratio: float
    var_95: float

    # Time series
    equity_curve: List[Tuple[datetime, float]]
    drawdown_curve: List[Tuple[datetime, float]]
    trades: List[BacktestTrade]

    # Benchmark comparison
    benchmark_return: float
    alpha: float
    beta: float

    def to_dict(self) -> dict:
        return {
            "config": self.config.to_dict(),
            "symbol": self.symbol,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "metrics": {
                "total_return": round(self.total_return * 100, 2),
                "annualized_return": round(self.annualized_return * 100, 2),
                "sharpe_ratio": round(self.sharpe_ratio, 2),
                "sortino_ratio": round(self.sortino_ratio, 2),
                "max_drawdown": round(self.max_drawdown * 100, 2),
                "win_rate": round(self.win_rate * 100, 1),
                "profit_factor": round(self.profit_factor, 2),
                "avg_trade_pnl": round(self.avg_trade_pnl * 100, 2),
                "avg_win": round(self.avg_win * 100, 2),
                "avg_loss": round(self.avg_loss * 100, 2),
            },
            "trade_stats": {
                "total_trades": self.total_trades,
                "winning_trades": self.winning_trades,
                "losing_trades": self.losing_trades,
                "avg_holding_days": round(self.avg_holding_days, 1),
            },
            "risk_metrics": {
                "volatility": round(self.volatility * 100, 2),
                "calmar_ratio": round(self.calmar_ratio, 2),
                "var_95": round(self.var_95 * 100, 2),
            },
            "benchmark": {
                "benchmark_return": round(self.benchmark_return * 100, 2),
                "alpha": round(self.alpha * 100, 2),
                "beta": round(self.beta, 2),
            },
            "equity_curve": [
                {"date": d.isoformat() if hasattr(d, 'isoformat') else str(d), "value": round(v, 2)}
                for d, v in self.equity_curve[-100:]  # Last 100 points
            ],
            "trades_summary": [
                {
                    "entry": t.entry_date.isoformat() if hasattr(t.entry_date, 'isoformat') else str(t.entry_date),
                    "exit": t.exit_date.isoformat() if hasattr(t.exit_date, 'isoformat') else str(t.exit_date),
                    "pnl_pct": round(t.pnl_pct * 100, 2),
                    "exit_reason": t.exit_reason,
                }
                for t in self.trades[-20:]  # Last 20 trades
            ],
        }


class StrategyBacktester:
    """
    Backtests individual trading strategies on historical data.

    This class implements vectorized backtesting for each strategy component
    used by the Quant Bot, allowing users to validate strategies before
    deploying them in paper trading.
    """

    def __init__(self, initial_capital: float = 100000.0):
        self.initial_capital = initial_capital

    def fetch_historical_data(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
    ) -> Optional[pd.DataFrame]:
        """Fetch historical OHLCV data from yfinance."""
        try:
            # Map crypto symbols to yfinance format
            yf_symbol = symbol
            if symbol in ["BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "AVAX", "LINK", "DOT"]:
                yf_symbol = f"{symbol}-USD"

            ticker = yf.Ticker(yf_symbol)
            df = ticker.history(start=start_date, end=end_date)

            if df.empty:
                logger.warning(f"No data for {symbol}")
                return None

            df.columns = [c.lower() for c in df.columns]
            return df

        except Exception as e:
            logger.error(f"Failed to fetch data for {symbol}: {e}")
            return None

    def calculate_rsi(self, prices: pd.Series, period: int = 14) -> pd.Series:
        """Calculate RSI indicator."""
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()

        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def calculate_macd(
        self,
        prices: pd.Series,
        fast: int = 12,
        slow: int = 26,
        signal: int = 9,
    ) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """Calculate MACD indicator."""
        ema_fast = prices.ewm(span=fast, adjust=False).mean()
        ema_slow = prices.ewm(span=slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        histogram = macd_line - signal_line
        return macd_line, signal_line, histogram

    def calculate_bollinger_bands(
        self,
        prices: pd.Series,
        period: int = 20,
        std_dev: float = 2.0,
    ) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """Calculate Bollinger Bands."""
        middle = prices.rolling(window=period).mean()
        std = prices.rolling(window=period).std()
        upper = middle + (std_dev * std)
        lower = middle - (std_dev * std)
        return middle, upper, lower

    def calculate_zscore(self, prices: pd.Series, lookback: int = 20) -> pd.Series:
        """Calculate Z-score for mean reversion."""
        mean = prices.rolling(window=lookback).mean()
        std = prices.rolling(window=lookback).std()
        zscore = (prices - mean) / std
        return zscore

    def generate_signals(
        self,
        df: pd.DataFrame,
        config: StrategyConfig,
    ) -> pd.Series:
        """
        Generate trading signals based on strategy configuration.
        Returns: Series with 1 (buy), -1 (sell), 0 (hold)
        """
        prices = df['close']
        signals = pd.Series(0, index=df.index)

        if config.strategy_type == StrategyType.RSI_OVERSOLD:
            rsi = self.calculate_rsi(prices, config.rsi_period)
            signals = signals.where(rsi >= config.rsi_oversold, 1)  # Buy when oversold
            signals = signals.where(rsi <= config.rsi_overbought, -1)  # Sell when overbought

        elif config.strategy_type == StrategyType.RSI_OVERBOUGHT:
            rsi = self.calculate_rsi(prices, config.rsi_period)
            signals = signals.where(rsi <= config.rsi_overbought, -1)  # Short when overbought

        elif config.strategy_type == StrategyType.MACD_CROSSOVER:
            macd_line, signal_line, histogram = self.calculate_macd(
                prices, config.macd_fast, config.macd_slow, config.macd_signal
            )
            # Buy when MACD crosses above signal
            signals = ((macd_line > signal_line) & (macd_line.shift(1) <= signal_line.shift(1))).astype(int)
            # Sell when MACD crosses below signal
            signals = signals - ((macd_line < signal_line) & (macd_line.shift(1) >= signal_line.shift(1))).astype(int)

        elif config.strategy_type == StrategyType.BOLLINGER_BANDS:
            middle, upper, lower = self.calculate_bollinger_bands(
                prices, config.bb_period, config.bb_std
            )
            # Buy when price touches lower band
            signals = (prices < lower).astype(int)
            # Sell when price touches upper band
            signals = signals - (prices > upper).astype(int)

        elif config.strategy_type == StrategyType.MOMENTUM:
            returns = prices.pct_change(config.momentum_lookback)
            signals = (returns > config.momentum_threshold).astype(int)
            signals = signals - (returns < -config.momentum_threshold).astype(int)

        elif config.strategy_type == StrategyType.MEAN_REVERSION:
            zscore = self.calculate_zscore(prices, config.zscore_lookback)
            signals = (zscore < config.zscore_entry).astype(int)  # Buy when very negative
            signals = signals.where(zscore < config.zscore_exit, -1)  # Exit at mean

        elif config.strategy_type == StrategyType.ZSCORE:
            zscore = self.calculate_zscore(prices, config.zscore_lookback)
            # Buy when z-score < -2 (oversold)
            signals = (zscore < -2).astype(int)
            # Sell when z-score > 2 (overbought)
            signals = signals - (zscore > 2).astype(int)

        elif config.strategy_type == StrategyType.COMBINED_MULTI_FACTOR:
            # Multi-factor combination
            rsi = self.calculate_rsi(prices, config.rsi_period)
            macd_line, signal_line, _ = self.calculate_macd(
                prices, config.macd_fast, config.macd_slow, config.macd_signal
            )
            middle, upper, lower = self.calculate_bollinger_bands(
                prices, config.bb_period, config.bb_std
            )
            zscore = self.calculate_zscore(prices, config.zscore_lookback)

            # Score each factor
            rsi_score = ((rsi < config.rsi_oversold).astype(float) -
                        (rsi > config.rsi_overbought).astype(float))
            macd_score = (macd_line > signal_line).astype(float) - 0.5
            bb_score = ((prices < lower).astype(float) -
                       (prices > upper).astype(float))
            zscore_score = (-zscore / 3).clip(-1, 1)

            # Combine scores
            composite = (rsi_score * 0.25 + macd_score * 0.25 +
                        bb_score * 0.25 + zscore_score * 0.25)

            signals = (composite > 0.3).astype(int) - (composite < -0.3).astype(int)

        return signals

    def run_backtest(
        self,
        symbol: str,
        config: StrategyConfig,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Optional[StrategyBacktestResult]:
        """
        Run a complete backtest for a strategy configuration.
        """
        # Default dates
        if end_date is None:
            end_date = datetime.now()
        if start_date is None:
            start_date = end_date - timedelta(days=365)

        # Fetch data
        df = self.fetch_historical_data(symbol, start_date, end_date)
        if df is None or len(df) < 50:
            logger.warning(f"Insufficient data for {symbol}")
            return None

        # Generate signals
        signals = self.generate_signals(df, config)

        # Run vectorized backtest
        trades = []
        equity = [self.initial_capital]
        drawdown = [0.0]
        equity_dates = [df.index[0]]

        cash = self.initial_capital
        position = 0
        entry_price = 0
        entry_date = None

        prices = df['close'].values
        dates = df.index

        for i in range(1, len(df)):
            current_price = prices[i]
            current_date = dates[i]
            signal = signals.iloc[i]

            # Check existing position for exits
            if position != 0:
                days_held = (current_date - entry_date).days if entry_date else 0
                pnl_pct = (current_price - entry_price) / entry_price if position > 0 else (entry_price - current_price) / entry_price

                exit_reason = None

                # Check stop loss
                if pnl_pct < -config.stop_loss_pct:
                    exit_reason = "stop_loss"
                # Check take profit
                elif pnl_pct > config.take_profit_pct:
                    exit_reason = "take_profit"
                # Check max holding
                elif days_held >= config.max_holding_days:
                    exit_reason = "max_holding"
                # Check signal reversal
                elif (position > 0 and signal < 0) or (position < 0 and signal > 0):
                    exit_reason = "signal"

                if exit_reason:
                    # Close position
                    pnl = position * (current_price - entry_price)
                    cash += position * current_price

                    trades.append(BacktestTrade(
                        entry_date=entry_date,
                        exit_date=current_date,
                        entry_price=entry_price,
                        exit_price=current_price,
                        side="long" if position > 0 else "short",
                        pnl=pnl,
                        pnl_pct=pnl_pct,
                        holding_days=days_held,
                        exit_reason=exit_reason,
                    ))

                    position = 0
                    entry_price = 0
                    entry_date = None

            # Check for new entry
            if position == 0 and signal != 0:
                position_value = cash * config.position_size_pct
                if signal > 0:  # Buy
                    shares = position_value / current_price
                    position = shares
                    cash -= position_value
                    entry_price = current_price
                    entry_date = current_date

            # Track equity
            portfolio_value = cash + (position * current_price if position > 0 else 0)
            equity.append(portfolio_value)
            equity_dates.append(current_date)

            # Track drawdown
            peak = max(equity)
            dd = (portfolio_value - peak) / peak if peak > 0 else 0
            drawdown.append(dd)

        # Calculate metrics
        if not trades:
            # No trades executed
            return StrategyBacktestResult(
                config=config,
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                total_return=0,
                annualized_return=0,
                sharpe_ratio=0,
                sortino_ratio=0,
                max_drawdown=0,
                win_rate=0,
                profit_factor=0,
                avg_trade_pnl=0,
                avg_win=0,
                avg_loss=0,
                total_trades=0,
                winning_trades=0,
                losing_trades=0,
                avg_holding_days=0,
                volatility=0,
                calmar_ratio=0,
                var_95=0,
                equity_curve=list(zip(equity_dates, equity)),
                drawdown_curve=list(zip(equity_dates, drawdown)),
                trades=[],
                benchmark_return=0,
                alpha=0,
                beta=1,
            )

        # Performance metrics
        final_equity = equity[-1]
        total_return = (final_equity - self.initial_capital) / self.initial_capital

        days = (end_date - start_date).days
        years = days / 365.25
        annualized_return = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0

        # Returns series for risk metrics
        equity_series = pd.Series(equity)
        returns = equity_series.pct_change().dropna()

        volatility = returns.std() * np.sqrt(252) if len(returns) > 0 else 0
        sharpe_ratio = (annualized_return - 0.02) / volatility if volatility > 0 else 0

        # Sortino (downside only)
        downside_returns = returns[returns < 0]
        downside_vol = downside_returns.std() * np.sqrt(252) if len(downside_returns) > 0 else 0
        sortino_ratio = (annualized_return - 0.02) / downside_vol if downside_vol > 0 else 0

        # Max drawdown
        max_drawdown = min(drawdown)

        # Win rate and profit factor
        winning = [t for t in trades if t.pnl > 0]
        losing = [t for t in trades if t.pnl <= 0]

        win_rate = len(winning) / len(trades) if trades else 0

        total_wins = sum(t.pnl for t in winning)
        total_losses = abs(sum(t.pnl for t in losing))
        profit_factor = total_wins / total_losses if total_losses > 0 else float('inf')

        avg_trade_pnl = np.mean([t.pnl_pct for t in trades]) if trades else 0
        avg_win = np.mean([t.pnl_pct for t in winning]) if winning else 0
        avg_loss = np.mean([t.pnl_pct for t in losing]) if losing else 0

        avg_holding_days = np.mean([t.holding_days for t in trades]) if trades else 0

        # Calmar ratio
        calmar_ratio = annualized_return / abs(max_drawdown) if max_drawdown != 0 else 0

        # VaR 95%
        var_95 = np.percentile(returns, 5) if len(returns) > 0 else 0

        # Benchmark comparison (buy and hold)
        benchmark_return = (prices[-1] - prices[0]) / prices[0]
        alpha = total_return - benchmark_return

        # Beta calculation
        if len(returns) > 10:
            benchmark_returns = pd.Series(prices).pct_change().dropna()
            if len(benchmark_returns) == len(returns):
                cov = np.cov(returns, benchmark_returns[:len(returns)])[0, 1]
                var = np.var(benchmark_returns[:len(returns)])
                beta = cov / var if var > 0 else 1
            else:
                beta = 1
        else:
            beta = 1

        return StrategyBacktestResult(
            config=config,
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            total_return=total_return,
            annualized_return=annualized_return,
            sharpe_ratio=sharpe_ratio,
            sortino_ratio=sortino_ratio,
            max_drawdown=max_drawdown,
            win_rate=win_rate,
            profit_factor=profit_factor,
            avg_trade_pnl=avg_trade_pnl,
            avg_win=avg_win,
            avg_loss=avg_loss,
            total_trades=len(trades),
            winning_trades=len(winning),
            losing_trades=len(losing),
            avg_holding_days=avg_holding_days,
            volatility=volatility,
            calmar_ratio=calmar_ratio,
            var_95=var_95,
            equity_curve=list(zip(equity_dates, equity)),
            drawdown_curve=list(zip(equity_dates, drawdown)),
            trades=trades,
            benchmark_return=benchmark_return,
            alpha=alpha,
            beta=beta,
        )

    def run_multi_symbol_backtest(
        self,
        symbols: List[str],
        config: StrategyConfig,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Dict[str, StrategyBacktestResult]:
        """Run backtest across multiple symbols."""
        results = {}
        for symbol in symbols:
            result = self.run_backtest(symbol, config, start_date, end_date)
            if result:
                results[symbol] = result
        return results

    def compare_strategies(
        self,
        symbol: str,
        configs: List[StrategyConfig],
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> List[StrategyBacktestResult]:
        """Compare multiple strategy configurations on the same symbol."""
        results = []
        for config in configs:
            result = self.run_backtest(symbol, config, start_date, end_date)
            if result:
                results.append(result)
        return results


# Singleton instance
_strategy_backtester: Optional[StrategyBacktester] = None

def get_strategy_backtester() -> StrategyBacktester:
    """Get the singleton StrategyBacktester instance."""
    global _strategy_backtester
    if _strategy_backtester is None:
        _strategy_backtester = StrategyBacktester()
    return _strategy_backtester
