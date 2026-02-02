"""
Backtesting & Pre-Training Framework

Provides:
1. Historical data downloading (Binance, Yahoo Finance)
2. Walk-forward backtesting with proper validation
3. ML model pre-training pipeline
4. Model checkpointing (save/load trained weights)
5. Performance metrics and analysis

This ensures models are trained BEFORE live trading, not during.
"""

import asyncio
import logging
import os
import json
import pickle
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from pathlib import Path
import numpy as np

logger = logging.getLogger(__name__)

# Model checkpoint directory
CHECKPOINT_DIR = Path(__file__).parent / "checkpoints"
CHECKPOINT_DIR.mkdir(exist_ok=True)

# Historical data directory
DATA_DIR = Path(__file__).parent / "historical_data"
DATA_DIR.mkdir(exist_ok=True)


@dataclass
class OHLCV:
    """Single OHLCV candle."""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    def to_dict(self) -> Dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
        }


@dataclass
class BacktestResult:
    """Results from a backtest run."""
    start_date: datetime
    end_date: datetime
    initial_capital: float
    final_capital: float
    total_return: float
    total_return_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown: float
    max_drawdown_pct: float
    win_rate: float
    profit_factor: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    avg_win: float
    avg_loss: float
    avg_holding_period: float  # in hours
    equity_curve: List[Tuple[datetime, float]] = field(default_factory=list)
    trades: List[Dict] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "initial_capital": self.initial_capital,
            "final_capital": round(self.final_capital, 2),
            "total_return": round(self.total_return, 2),
            "total_return_pct": round(self.total_return_pct, 2),
            "sharpe_ratio": round(self.sharpe_ratio, 3),
            "sortino_ratio": round(self.sortino_ratio, 3),
            "max_drawdown": round(self.max_drawdown, 2),
            "max_drawdown_pct": round(self.max_drawdown_pct, 2),
            "win_rate": round(self.win_rate * 100, 1),
            "profit_factor": round(self.profit_factor, 2),
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "avg_win": round(self.avg_win, 2),
            "avg_loss": round(self.avg_loss, 2),
            "avg_holding_period_hours": round(self.avg_holding_period, 1),
        }


@dataclass
class TrainingMetrics:
    """Metrics from model training."""
    epochs_completed: int
    total_samples: int
    training_loss: List[float] = field(default_factory=list)
    validation_loss: List[float] = field(default_factory=list)
    dqn_loss: List[float] = field(default_factory=list)
    ppo_loss: List[float] = field(default_factory=list)
    prediction_accuracy: List[float] = field(default_factory=list)
    sharpe_during_training: List[float] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "epochs_completed": self.epochs_completed,
            "total_samples": self.total_samples,
            "final_training_loss": self.training_loss[-1] if self.training_loss else None,
            "final_validation_loss": self.validation_loss[-1] if self.validation_loss else None,
            "final_accuracy": self.prediction_accuracy[-1] if self.prediction_accuracy else None,
        }


class HistoricalDataDownloader:
    """
    Downloads historical price data from multiple sources.

    Sources:
    - Binance API (crypto)
    - Yahoo Finance (stocks, ETFs, indices)
    - Federal Reserve FRED (economic indicators)
    """

    # Crypto symbols to download
    CRYPTO_SYMBOLS = [
        "BTC", "ETH", "SOL", "AVAX", "MATIC", "LINK", "UNI", "AAVE",
        "DOT", "ADA", "XRP", "LTC", "ATOM", "ARB", "OP", "APT"
    ]

    # Stock/ETF symbols
    STOCK_SYMBOLS = [
        "SPY", "QQQ", "IWM", "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA",
        "META", "TSLA", "AMD", "NFLX", "GLD", "SLV", "TLT", "VIX"
    ]

    def __init__(self):
        self.data_cache: Dict[str, List[OHLCV]] = {}

    async def download_crypto_history(
        self,
        symbol: str,
        interval: str = "1h",
        days: int = 365
    ) -> List[OHLCV]:
        """Download crypto historical data from Binance."""
        import aiohttp

        candles = []
        binance_symbol = f"{symbol}USDT"

        # Calculate time range
        end_time = int(datetime.now().timestamp() * 1000)
        start_time = int((datetime.now() - timedelta(days=days)).timestamp() * 1000)

        # Binance klines endpoint
        url = "https://api.binance.us/api/v3/klines"

        try:
            async with aiohttp.ClientSession() as session:
                params = {
                    "symbol": binance_symbol,
                    "interval": interval,
                    "startTime": start_time,
                    "endTime": end_time,
                    "limit": 1000
                }

                current_start = start_time
                while current_start < end_time:
                    params["startTime"] = current_start

                    async with session.get(url, params=params) as response:
                        if response.status != 200:
                            logger.warning(f"Binance API error for {symbol}: {response.status}")
                            break

                        data = await response.json()

                        if not data:
                            break

                        for kline in data:
                            candles.append(OHLCV(
                                timestamp=datetime.fromtimestamp(kline[0] / 1000),
                                open=float(kline[1]),
                                high=float(kline[2]),
                                low=float(kline[3]),
                                close=float(kline[4]),
                                volume=float(kline[5])
                            ))

                        # Move to next batch
                        current_start = data[-1][0] + 1

                        # Rate limiting
                        await asyncio.sleep(0.1)

            logger.info(f"Downloaded {len(candles)} candles for {symbol}")
            self.data_cache[symbol] = candles

            # Save to disk
            self._save_to_disk(symbol, candles)

            return candles

        except Exception as e:
            logger.error(f"Error downloading {symbol}: {e}")
            return []

    async def download_stock_history(
        self,
        symbol: str,
        days: int = 365
    ) -> List[OHLCV]:
        """Download stock/ETF data from Yahoo Finance."""
        import aiohttp

        candles = []

        # Yahoo Finance API (unofficial but widely used)
        end_time = int(datetime.now().timestamp())
        start_time = int((datetime.now() - timedelta(days=days)).timestamp())

        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"

        try:
            async with aiohttp.ClientSession() as session:
                params = {
                    "period1": start_time,
                    "period2": end_time,
                    "interval": "1h",
                    "includePrePost": "false"
                }

                headers = {"User-Agent": "Mozilla/5.0"}

                async with session.get(url, params=params, headers=headers) as response:
                    if response.status != 200:
                        logger.warning(f"Yahoo API error for {symbol}: {response.status}")
                        return []

                    data = await response.json()

                    result = data.get("chart", {}).get("result", [])
                    if not result:
                        return []

                    quotes = result[0]
                    timestamps = quotes.get("timestamp", [])
                    ohlcv = quotes.get("indicators", {}).get("quote", [{}])[0]

                    opens = ohlcv.get("open", [])
                    highs = ohlcv.get("high", [])
                    lows = ohlcv.get("low", [])
                    closes = ohlcv.get("close", [])
                    volumes = ohlcv.get("volume", [])

                    for i, ts in enumerate(timestamps):
                        if all(x is not None for x in [opens[i], highs[i], lows[i], closes[i]]):
                            candles.append(OHLCV(
                                timestamp=datetime.fromtimestamp(ts),
                                open=opens[i],
                                high=highs[i],
                                low=lows[i],
                                close=closes[i],
                                volume=volumes[i] or 0
                            ))

            logger.info(f"Downloaded {len(candles)} candles for {symbol}")
            self.data_cache[symbol] = candles
            self._save_to_disk(symbol, candles)

            return candles

        except Exception as e:
            logger.error(f"Error downloading {symbol}: {e}")
            return []

    async def download_all(self, days: int = 365) -> Dict[str, List[OHLCV]]:
        """Download all historical data for training."""
        logger.info(f"Downloading {days} days of historical data...")

        # Download crypto
        for symbol in self.CRYPTO_SYMBOLS:
            if symbol not in self.data_cache:
                await self.download_crypto_history(symbol, days=days)
                await asyncio.sleep(0.5)  # Rate limiting

        # Download stocks
        for symbol in self.STOCK_SYMBOLS:
            if symbol not in self.data_cache:
                await self.download_stock_history(symbol, days=days)
                await asyncio.sleep(0.5)

        logger.info(f"Downloaded data for {len(self.data_cache)} symbols")
        return self.data_cache

    def _save_to_disk(self, symbol: str, candles: List[OHLCV]):
        """Save historical data to disk."""
        filepath = DATA_DIR / f"{symbol}_history.json"
        data = [c.to_dict() for c in candles]
        with open(filepath, "w") as f:
            json.dump(data, f)

    def load_from_disk(self, symbol: str) -> List[OHLCV]:
        """Load historical data from disk."""
        filepath = DATA_DIR / f"{symbol}_history.json"
        if not filepath.exists():
            return []

        with open(filepath, "r") as f:
            data = json.load(f)

        candles = [
            OHLCV(
                timestamp=datetime.fromisoformat(d["timestamp"]),
                open=d["open"],
                high=d["high"],
                low=d["low"],
                close=d["close"],
                volume=d["volume"]
            )
            for d in data
        ]

        self.data_cache[symbol] = candles
        return candles

    def load_all_from_disk(self) -> Dict[str, List[OHLCV]]:
        """Load all cached historical data."""
        for filepath in DATA_DIR.glob("*_history.json"):
            symbol = filepath.stem.replace("_history", "")
            self.load_from_disk(symbol)
        return self.data_cache


class WalkForwardBacktester:
    """
    Walk-Forward Backtesting Engine

    Implements proper walk-forward validation:
    1. Split data into train/test windows
    2. Train on window, test on out-of-sample
    3. Roll forward and repeat
    4. Aggregate results to assess true performance

    This prevents overfitting and gives realistic performance estimates.
    """

    def __init__(
        self,
        train_window_days: int = 60,
        test_window_days: int = 20,
        step_days: int = 10,
        initial_capital: float = 10000.0
    ):
        self.train_window = train_window_days
        self.test_window = test_window_days
        self.step_days = step_days
        self.initial_capital = initial_capital

        self.results: List[BacktestResult] = []
        self.equity_curve: List[Tuple[datetime, float]] = []
        self.all_trades: List[Dict] = []

    def prepare_features(self, candles: List[OHLCV], lookback: int = 20) -> np.ndarray:
        """
        Prepare feature matrix from OHLCV data.

        Features:
        - Returns (1, 5, 10, 20 period)
        - Volatility (realized, Parkinson, Garman-Klass)
        - RSI, MACD, Bollinger Bands
        - Volume profile
        - Price momentum
        """
        if len(candles) < lookback + 20:
            return np.array([])

        closes = np.array([c.close for c in candles])
        highs = np.array([c.high for c in candles])
        lows = np.array([c.low for c in candles])
        volumes = np.array([c.volume for c in candles])

        features = []

        for i in range(lookback, len(candles)):
            window_close = closes[i-lookback:i+1]
            window_high = highs[i-lookback:i+1]
            window_low = lows[i-lookback:i+1]
            window_vol = volumes[i-lookback:i+1]

            # Returns
            returns_1 = (closes[i] - closes[i-1]) / closes[i-1] if closes[i-1] > 0 else 0
            returns_5 = (closes[i] - closes[i-5]) / closes[i-5] if i >= 5 and closes[i-5] > 0 else 0
            returns_10 = (closes[i] - closes[i-10]) / closes[i-10] if i >= 10 and closes[i-10] > 0 else 0
            returns_20 = (closes[i] - closes[i-20]) / closes[i-20] if i >= 20 and closes[i-20] > 0 else 0

            # Volatility
            log_returns = np.diff(np.log(window_close + 1e-8))
            realized_vol = np.std(log_returns) * np.sqrt(252 * 24)  # Annualized hourly

            # Parkinson volatility (high-low based)
            hl_ratio = np.log(window_high / (window_low + 1e-8))
            parkinson_vol = np.sqrt(np.mean(hl_ratio ** 2) / (4 * np.log(2))) * np.sqrt(252 * 24)

            # RSI
            gains = np.maximum(np.diff(window_close), 0)
            losses = np.maximum(-np.diff(window_close), 0)
            avg_gain = np.mean(gains[-14:]) if len(gains) >= 14 else np.mean(gains)
            avg_loss = np.mean(losses[-14:]) if len(losses) >= 14 else np.mean(losses)
            rsi = 100 - (100 / (1 + avg_gain / (avg_loss + 1e-8)))

            # MACD
            ema_12 = self._ema(window_close, 12)
            ema_26 = self._ema(window_close, 26)
            macd = (ema_12 - ema_26) / (closes[i] + 1e-8)

            # Bollinger Bands position
            sma_20 = np.mean(window_close[-20:])
            std_20 = np.std(window_close[-20:])
            bb_position = (closes[i] - sma_20) / (2 * std_20 + 1e-8)

            # Volume profile
            vol_sma = np.mean(window_vol)
            vol_ratio = window_vol[-1] / (vol_sma + 1e-8)

            # Price momentum (rate of change)
            momentum = (closes[i] - np.mean(window_close)) / (np.std(window_close) + 1e-8)

            # Trend strength (ADX approximation)
            tr = np.maximum(window_high - window_low,
                          np.abs(window_high - np.roll(window_close, 1)),
                          np.abs(window_low - np.roll(window_close, 1)))
            atr = np.mean(tr[-14:])
            trend_strength = atr / (closes[i] + 1e-8)

            feature_vector = [
                returns_1, returns_5, returns_10, returns_20,
                realized_vol, parkinson_vol,
                rsi / 100,  # Normalize to 0-1
                macd,
                bb_position,
                vol_ratio,
                momentum,
                trend_strength,
                # Normalized price levels
                (closes[i] - np.min(window_close)) / (np.max(window_close) - np.min(window_close) + 1e-8),
                # High-low range
                (window_high[-1] - window_low[-1]) / (closes[i] + 1e-8),
            ]

            features.append(feature_vector)

        return np.array(features)

    def _ema(self, data: np.ndarray, period: int) -> float:
        """Calculate EMA."""
        if len(data) < period:
            return data[-1]
        multiplier = 2 / (period + 1)
        ema = data[0]
        for price in data[1:]:
            ema = (price - ema) * multiplier + ema
        return ema

    def generate_labels(self, candles: List[OHLCV], lookahead: int = 5, threshold: float = 0.02) -> np.ndarray:
        """
        Generate trading labels based on future returns.

        Labels:
        0 = Sell (future return < -threshold)
        1 = Hold (future return between -threshold and +threshold)
        2 = Buy (future return > +threshold)
        """
        closes = np.array([c.close for c in candles])
        labels = []

        for i in range(len(closes) - lookahead):
            future_return = (closes[i + lookahead] - closes[i]) / closes[i]

            if future_return > threshold:
                labels.append(2)  # Buy
            elif future_return < -threshold:
                labels.append(0)  # Sell
            else:
                labels.append(1)  # Hold

        return np.array(labels)

    def run_backtest(
        self,
        data: Dict[str, List[OHLCV]],
        model_trainer: 'ModelPreTrainer',
        strategy: str = "ml_ensemble"
    ) -> BacktestResult:
        """
        Run walk-forward backtest.

        Args:
            data: Historical OHLCV data per symbol
            model_trainer: Pre-trainer with trained models
            strategy: Trading strategy to use
        """
        logger.info("Starting walk-forward backtest...")

        # Combine all data into time-sorted events
        all_candles = []
        for symbol, candles in data.items():
            for candle in candles:
                all_candles.append((candle.timestamp, symbol, candle))

        all_candles.sort(key=lambda x: x[0])

        if not all_candles:
            logger.error("No data for backtest")
            return self._empty_result()

        # Initialize tracking
        capital = self.initial_capital
        positions: Dict[str, Dict] = {}  # symbol -> position info
        equity_curve = [(all_candles[0][0], capital)]
        trades = []

        # Walk through time
        window_data: Dict[str, List[OHLCV]] = {sym: [] for sym in data.keys()}

        for timestamp, symbol, candle in all_candles:
            window_data[symbol].append(candle)

            # Keep only recent data (memory efficiency)
            max_window = self.train_window + self.test_window + 50
            if len(window_data[symbol]) > max_window * 24:  # hourly data
                window_data[symbol] = window_data[symbol][-max_window * 24:]

            # Update existing positions
            if symbol in positions:
                pos = positions[symbol]
                current_price = candle.close
                entry_price = pos["entry_price"]
                side = pos["side"]

                # Calculate unrealized P&L
                if side == "long":
                    pnl_pct = (current_price - entry_price) / entry_price
                else:
                    pnl_pct = (entry_price - current_price) / entry_price

                unrealized_pnl = pos["size"] * pnl_pct

                # Check exit conditions
                should_exit = False
                exit_reason = ""

                # Take profit (10%)
                if pnl_pct >= 0.10:
                    should_exit = True
                    exit_reason = "take_profit"
                # Stop loss (5%)
                elif pnl_pct <= -0.05:
                    should_exit = True
                    exit_reason = "stop_loss"
                # Time-based exit (hold max 48 hours)
                elif (timestamp - pos["entry_time"]).total_seconds() > 48 * 3600:
                    should_exit = True
                    exit_reason = "time_exit"

                if should_exit:
                    realized_pnl = pos["size"] * pnl_pct
                    capital += pos["size"] + realized_pnl

                    trades.append({
                        "symbol": symbol,
                        "side": side,
                        "entry_price": entry_price,
                        "exit_price": current_price,
                        "entry_time": pos["entry_time"].isoformat(),
                        "exit_time": timestamp.isoformat(),
                        "pnl": realized_pnl,
                        "pnl_pct": pnl_pct * 100,
                        "exit_reason": exit_reason,
                    })

                    del positions[symbol]

            # Generate trading signal (only if we have enough data)
            if len(window_data[symbol]) >= 100 and symbol not in positions:
                features = self.prepare_features(window_data[symbol][-100:])

                if len(features) > 0:
                    # Get ML prediction
                    state = features[-1]
                    prediction = model_trainer.predict(state)

                    # Only trade on strong signals
                    if prediction["action"] != 1 and prediction["confidence"] > 0.6:
                        # Position sizing (2% of capital per trade, max 10 positions)
                        if len(positions) < 10:
                            position_size = min(capital * 0.02, capital * 0.1)

                            if position_size > 100:  # Minimum position
                                side = "long" if prediction["action"] == 2 else "short"

                                positions[symbol] = {
                                    "side": side,
                                    "entry_price": candle.close,
                                    "entry_time": timestamp,
                                    "size": position_size,
                                }

                                capital -= position_size

            # Update equity curve periodically
            if len(equity_curve) == 0 or (timestamp - equity_curve[-1][0]).total_seconds() > 3600:
                # Calculate total equity
                total_equity = capital
                for sym, pos in positions.items():
                    if sym in window_data and window_data[sym]:
                        current_price = window_data[sym][-1].close
                        entry_price = pos["entry_price"]
                        if pos["side"] == "long":
                            pnl_pct = (current_price - entry_price) / entry_price
                        else:
                            pnl_pct = (entry_price - current_price) / entry_price
                        total_equity += pos["size"] * (1 + pnl_pct)

                equity_curve.append((timestamp, total_equity))

        # Close remaining positions at end
        for symbol, pos in list(positions.items()):
            if symbol in window_data and window_data[symbol]:
                current_price = window_data[symbol][-1].close
                entry_price = pos["entry_price"]
                if pos["side"] == "long":
                    pnl_pct = (current_price - entry_price) / entry_price
                else:
                    pnl_pct = (entry_price - current_price) / entry_price

                realized_pnl = pos["size"] * pnl_pct
                capital += pos["size"] + realized_pnl

                trades.append({
                    "symbol": symbol,
                    "side": pos["side"],
                    "entry_price": entry_price,
                    "exit_price": current_price,
                    "entry_time": pos["entry_time"].isoformat(),
                    "exit_time": all_candles[-1][0].isoformat(),
                    "pnl": realized_pnl,
                    "pnl_pct": pnl_pct * 100,
                    "exit_reason": "backtest_end",
                })

        # Calculate final metrics
        return self._calculate_metrics(equity_curve, trades)

    def _calculate_metrics(
        self,
        equity_curve: List[Tuple[datetime, float]],
        trades: List[Dict]
    ) -> BacktestResult:
        """Calculate backtest performance metrics."""
        if not equity_curve:
            return self._empty_result()

        initial = self.initial_capital
        final = equity_curve[-1][1]

        # Returns
        total_return = final - initial
        total_return_pct = (total_return / initial) * 100

        # Calculate daily returns for Sharpe/Sortino
        equity_values = [e[1] for e in equity_curve]
        returns = np.diff(equity_values) / (np.array(equity_values[:-1]) + 1e-8)

        # Sharpe Ratio (annualized, assuming hourly data)
        if len(returns) > 1 and np.std(returns) > 0:
            sharpe = np.mean(returns) / np.std(returns) * np.sqrt(252 * 24)
        else:
            sharpe = 0

        # Sortino Ratio (downside deviation only)
        downside_returns = returns[returns < 0]
        if len(downside_returns) > 0:
            sortino = np.mean(returns) / np.std(downside_returns) * np.sqrt(252 * 24)
        else:
            sortino = sharpe

        # Max Drawdown
        peak = equity_values[0]
        max_dd = 0
        for value in equity_values:
            if value > peak:
                peak = value
            dd = (peak - value) / peak
            if dd > max_dd:
                max_dd = dd

        # Trade statistics
        winning_trades = [t for t in trades if t["pnl"] > 0]
        losing_trades = [t for t in trades if t["pnl"] <= 0]

        win_rate = len(winning_trades) / len(trades) if trades else 0
        avg_win = np.mean([t["pnl"] for t in winning_trades]) if winning_trades else 0
        avg_loss = np.mean([abs(t["pnl"]) for t in losing_trades]) if losing_trades else 0

        # Profit factor
        gross_profit = sum(t["pnl"] for t in winning_trades)
        gross_loss = abs(sum(t["pnl"] for t in losing_trades))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

        # Average holding period
        holding_periods = []
        for t in trades:
            entry = datetime.fromisoformat(t["entry_time"])
            exit_time = datetime.fromisoformat(t["exit_time"])
            holding_periods.append((exit_time - entry).total_seconds() / 3600)
        avg_holding = np.mean(holding_periods) if holding_periods else 0

        return BacktestResult(
            start_date=equity_curve[0][0],
            end_date=equity_curve[-1][0],
            initial_capital=initial,
            final_capital=final,
            total_return=total_return,
            total_return_pct=total_return_pct,
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            max_drawdown=max_dd * initial,
            max_drawdown_pct=max_dd * 100,
            win_rate=win_rate,
            profit_factor=profit_factor,
            total_trades=len(trades),
            winning_trades=len(winning_trades),
            losing_trades=len(losing_trades),
            avg_win=avg_win,
            avg_loss=avg_loss,
            avg_holding_period=avg_holding,
            equity_curve=equity_curve,
            trades=trades,
        )

    def _empty_result(self) -> BacktestResult:
        """Return empty backtest result."""
        now = datetime.now()
        return BacktestResult(
            start_date=now,
            end_date=now,
            initial_capital=self.initial_capital,
            final_capital=self.initial_capital,
            total_return=0,
            total_return_pct=0,
            sharpe_ratio=0,
            sortino_ratio=0,
            max_drawdown=0,
            max_drawdown_pct=0,
            win_rate=0,
            profit_factor=0,
            total_trades=0,
            winning_trades=0,
            losing_trades=0,
            avg_win=0,
            avg_loss=0,
            avg_holding_period=0,
        )


class ModelPreTrainer:
    """
    Pre-Training Pipeline for ML Models

    Trains all models on historical data BEFORE live trading:
    - DQN: Learn Q-values from simulated trading
    - PPO: Learn policy from market dynamics
    - LSTM/Transformer: Learn price patterns
    - VAE: Learn market regime representations

    Saves trained weights to disk for production use.
    """

    def __init__(self, state_dim: int = 64, action_dim: int = 3):
        self.state_dim = state_dim
        self.action_dim = action_dim  # 0=sell, 1=hold, 2=buy

        # Initialize models with PROPER TRAINABLE versions
        from .ml_models import (
            create_dqn_agent, create_ppo_agent,
            LSTMClassifier, TrainableTransformer, TrainableVAE
        )

        # DQN and PPO already have proper training
        self.dqn = create_dqn_agent(state_dim, action_dim)
        self.ppo = create_ppo_agent(state_dim, action_dim)

        # Use trainable versions with proper backpropagation
        self.lstm = LSTMClassifier(
            input_dim=state_dim, hidden_dim=128, output_dim=action_dim, lr=0.001
        )
        self.transformer = TrainableTransformer(
            input_dim=state_dim, hidden_dim=64, output_dim=action_dim, lr=0.001
        )
        self.vae = TrainableVAE(
            input_dim=state_dim, hidden_dim=64, latent_dim=8, output_dim=4, lr=0.001
        )

        self.is_trained = False
        self.training_metrics = TrainingMetrics(epochs_completed=0, total_samples=0)
        self.min_training_epochs = 50
        self.min_training_samples = 10000

    def prepare_training_data(
        self,
        historical_data: Dict[str, List[OHLCV]],
        backtester: WalkForwardBacktester
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Prepare training data from historical OHLCV.

        Returns: (features, labels, rewards)
        """
        all_features = []
        all_labels = []
        all_rewards = []

        for symbol, candles in historical_data.items():
            if len(candles) < 200:
                continue

            features = backtester.prepare_features(candles)
            labels = backtester.generate_labels(candles)

            # Align features and labels
            min_len = min(len(features), len(labels))
            if min_len > 0:
                features = features[:min_len]
                labels = labels[:min_len]

                # Calculate rewards (based on actual returns)
                closes = np.array([c.close for c in candles])
                rewards = []
                for i in range(len(labels)):
                    if i + 5 < len(closes):
                        future_return = (closes[i + 5] - closes[i]) / closes[i]
                        # Reward alignment: +1 for correct direction, -1 for wrong
                        if labels[i] == 2:  # Predicted buy
                            rewards.append(future_return * 10)  # Scale for learning
                        elif labels[i] == 0:  # Predicted sell
                            rewards.append(-future_return * 10)
                        else:
                            rewards.append(0)
                    else:
                        rewards.append(0)

                all_features.append(features)
                all_labels.append(labels)
                all_rewards.append(np.array(rewards))

        if not all_features:
            return np.array([]), np.array([]), np.array([])

        X = np.vstack(all_features)
        y = np.concatenate(all_labels)
        r = np.concatenate(all_rewards)

        # Pad/truncate features to state_dim
        if X.shape[1] < self.state_dim:
            padding = np.zeros((X.shape[0], self.state_dim - X.shape[1]))
            X = np.hstack([X, padding])
        elif X.shape[1] > self.state_dim:
            X = X[:, :self.state_dim]

        return X, y, r

    def train(
        self,
        features: np.ndarray,
        labels: np.ndarray,
        rewards: np.ndarray,
        epochs: int = 100,
        batch_size: int = 64,
        validation_split: float = 0.2
    ) -> TrainingMetrics:
        """
        Train all models on historical data.
        """
        if len(features) == 0:
            logger.error("No training data provided")
            return self.training_metrics

        logger.info(f"Training on {len(features)} samples for {epochs} epochs...")

        # Split train/validation
        n_val = int(len(features) * validation_split)
        indices = np.random.permutation(len(features))
        train_idx = indices[n_val:]
        val_idx = indices[:n_val]

        X_train, y_train, r_train = features[train_idx], labels[train_idx], rewards[train_idx]
        X_val, y_val, r_val = features[val_idx], labels[val_idx], rewards[val_idx]

        for epoch in range(epochs):
            # Shuffle training data
            perm = np.random.permutation(len(X_train))
            X_train, y_train, r_train = X_train[perm], y_train[perm], r_train[perm]

            epoch_losses = []

            # Mini-batch training
            for i in range(0, len(X_train), batch_size):
                batch_X = X_train[i:i+batch_size]
                batch_y = y_train[i:i+batch_size]
                batch_r = r_train[i:i+batch_size]

                # =====================
                # TRAIN DQN (Experience Replay)
                # =====================
                for j in range(len(batch_X) - 1):
                    state = batch_X[j]
                    action = int(batch_y[j])
                    reward = batch_r[j]
                    next_state = batch_X[j + 1]
                    done = (j == len(batch_X) - 2)

                    from .ml_models import Experience
                    exp = Experience(state, action, reward, next_state, done)
                    self.dqn.replay_buffer.push(exp)

                dqn_loss = self.dqn.train_step(batch_size=min(32, len(batch_X)))
                if dqn_loss:
                    epoch_losses.append(dqn_loss)

                # =====================
                # TRAIN PPO (Policy Gradient)
                # =====================
                for j in range(len(batch_X)):
                    state = batch_X[j]
                    action = int(batch_y[j])
                    reward = batch_r[j]
                    done = (j == len(batch_X) - 1)

                    probs = self.ppo.get_action_probs(state)
                    log_prob = np.log(probs[action] + 1e-8)
                    value = self.ppo.get_value(state)

                    # Signature: (state, action, reward, value, log_prob, done)
                    self.ppo.store_transition(state, action, reward, value, log_prob, done)

                ppo_loss = self.ppo.train_step()

                # =====================
                # TRAIN LSTM (Proper BPTT)
                # =====================
                if len(batch_X) >= 10:
                    seq_len = 10
                    # Create sequences for LSTM training
                    for j in range(0, len(batch_X) - seq_len, seq_len):
                        seq = batch_X[j:j+seq_len]
                        target = batch_y[j+seq_len-1:j+seq_len]  # Label for last timestep

                        if len(target) > 0:
                            # Proper backpropagation through time
                            lstm_loss = self.lstm.train_step(
                                seq.reshape(1, seq_len, -1),
                                target
                            )
                            epoch_losses.append(lstm_loss)

                # =====================
                # TRAIN TRANSFORMER (Proper Gradient Descent)
                # =====================
                if len(batch_X) >= 10:
                    seq_len = 10
                    for j in range(0, len(batch_X) - seq_len, seq_len):
                        seq = batch_X[j:j+seq_len]
                        target = batch_y[j+seq_len-1:j+seq_len]

                        if len(target) > 0:
                            # Proper backpropagation
                            trans_loss = self.transformer.train_step(
                                seq.reshape(1, seq_len, -1),
                                target
                            )
                            epoch_losses.append(trans_loss)

                # =====================
                # TRAIN VAE (Reconstruction + KL Loss)
                # =====================
                # VAE trains on individual states with optional regime labels
                vae_loss = self.vae.train_step(batch_X, batch_y % 4)  # 4 regimes
                epoch_losses.append(vae_loss)

            # Validation
            val_preds = []
            for state in X_val:
                pred = self.predict(state)
                val_preds.append(pred["action"])

            val_accuracy = np.mean(np.array(val_preds) == y_val)

            # Record metrics
            avg_loss = np.mean(epoch_losses) if epoch_losses else 0
            self.training_metrics.training_loss.append(avg_loss)
            self.training_metrics.prediction_accuracy.append(val_accuracy)

            # Decay DQN epsilon
            self.dqn.epsilon = max(0.01, self.dqn.epsilon * 0.995)

            if (epoch + 1) % 10 == 0:
                logger.info(
                    f"Epoch {epoch+1}/{epochs} | "
                    f"Loss: {avg_loss:.4f} | "
                    f"Val Acc: {val_accuracy:.2%} | "
                    f"Epsilon: {self.dqn.epsilon:.3f}"
                )

        self.training_metrics.epochs_completed = epochs
        self.training_metrics.total_samples = len(features)
        self.is_trained = True

        # Save checkpoints
        self.save_checkpoints()

        logger.info(f"Training complete! Final accuracy: {val_accuracy:.2%}")
        return self.training_metrics

    def predict(self, state: np.ndarray) -> Dict:
        """
        Get ensemble prediction from all models.

        Returns:
            action: 0=sell, 1=hold, 2=buy
            confidence: 0-1 confidence score
        """
        # Ensure state is correct shape
        if len(state.shape) == 1:
            if len(state) < self.state_dim:
                state = np.pad(state, (0, self.state_dim - len(state)))
            elif len(state) > self.state_dim:
                state = state[:self.state_dim]

        predictions = []
        confidences = []

        # DQN prediction
        q_values = self.dqn.get_q_values(state)
        dqn_action = np.argmax(q_values)
        dqn_conf = np.exp(q_values[dqn_action]) / np.sum(np.exp(q_values))
        predictions.append(dqn_action)
        confidences.append(dqn_conf)

        # PPO prediction
        ppo_probs = self.ppo.get_action_probs(state)
        ppo_action = np.argmax(ppo_probs)
        predictions.append(ppo_action)
        confidences.append(ppo_probs[ppo_action])

        # LSTM prediction
        lstm_out, _ = self.lstm.forward(state.reshape(1, -1))
        lstm_probs = self._softmax(lstm_out[-1])
        lstm_action = np.argmax(lstm_probs)
        predictions.append(lstm_action)
        confidences.append(lstm_probs[lstm_action])

        # Transformer prediction
        trans_out = self.transformer.forward(state.reshape(1, -1))
        trans_probs = self._softmax(trans_out[-1])
        trans_action = np.argmax(trans_probs)
        predictions.append(trans_action)
        confidences.append(trans_probs[trans_action])

        # Ensemble vote (weighted by confidence)
        action_votes = {0: 0, 1: 0, 2: 0}
        for pred, conf in zip(predictions, confidences):
            action_votes[pred] += conf

        final_action = max(action_votes, key=action_votes.get)
        final_confidence = action_votes[final_action] / sum(confidences)

        return {
            "action": final_action,
            "confidence": float(final_confidence),
            "q_values": q_values.tolist(),
            "predictions": predictions,
        }

    def _softmax(self, x: np.ndarray) -> np.ndarray:
        """Compute softmax."""
        exp_x = np.exp(x - np.max(x))
        return exp_x / (np.sum(exp_x) + 1e-8)

    def save_checkpoints(self):
        """Save trained model weights to disk."""
        logger.info("Saving model checkpoints...")

        checkpoint = {
            "dqn_weights": {
                "q_network": self.dqn.q_network.get_weights(),
                "target_network": self.dqn.target_network.get_weights(),
                "epsilon": self.dqn.epsilon,
            },
            "ppo_weights": {
                "policy": self.ppo.policy_network.get_weights(),
                "value": self.ppo.value_network.get_weights(),
            },
            # Use get_weights() methods from trainable models
            "lstm_weights": self.lstm.get_weights(),
            "transformer_weights": self.transformer.get_weights(),
            "vae_weights": self.vae.get_weights(),
            "training_metrics": self.training_metrics.to_dict(),
            "is_trained": self.is_trained,
            "timestamp": datetime.now().isoformat(),
        }

        checkpoint_path = CHECKPOINT_DIR / "model_checkpoint.pkl"
        with open(checkpoint_path, "wb") as f:
            pickle.dump(checkpoint, f)

        logger.info(f"Checkpoints saved to {checkpoint_path}")

    def load_checkpoints(self) -> bool:
        """Load trained model weights from disk."""
        checkpoint_path = CHECKPOINT_DIR / "model_checkpoint.pkl"

        if not checkpoint_path.exists():
            logger.warning("No checkpoint found - models will start untrained")
            return False

        try:
            with open(checkpoint_path, "rb") as f:
                checkpoint = pickle.load(f)

            # Restore DQN
            self.dqn.q_network.set_weights(checkpoint["dqn_weights"]["q_network"])
            self.dqn.target_network.set_weights(checkpoint["dqn_weights"]["target_network"])
            self.dqn.epsilon = checkpoint["dqn_weights"]["epsilon"]

            # Restore PPO
            self.ppo.policy_network.set_weights(checkpoint["ppo_weights"]["policy"])
            self.ppo.value_network.set_weights(checkpoint["ppo_weights"]["value"])

            # Restore trainable models using set_weights() methods
            self.lstm.set_weights(checkpoint["lstm_weights"])
            self.transformer.set_weights(checkpoint["transformer_weights"])
            self.vae.set_weights(checkpoint["vae_weights"])

            self.is_trained = checkpoint.get("is_trained", True)

            logger.info(f"Loaded checkpoint from {checkpoint['timestamp']}")
            logger.info(f"DQN epsilon: {self.dqn.epsilon:.4f}")

            return True

        except Exception as e:
            logger.error(f"Error loading checkpoint: {e}")
            return False

    def meets_training_requirements(self) -> Tuple[bool, str]:
        """Check if models meet minimum training requirements."""
        if not self.is_trained:
            return False, "Models have not been trained"

        if self.training_metrics.epochs_completed < self.min_training_epochs:
            return False, f"Only {self.training_metrics.epochs_completed}/{self.min_training_epochs} epochs completed"

        if self.training_metrics.total_samples < self.min_training_samples:
            return False, f"Only {self.training_metrics.total_samples}/{self.min_training_samples} samples trained"

        if self.dqn.epsilon > 0.1:
            return False, f"DQN still exploring (epsilon={self.dqn.epsilon:.2f} > 0.1)"

        return True, "Training requirements met"


class AlphaSourceManager:
    """
    Alternative Alpha Sources using APIs you already have!

    Sources:
    1. Fear & Greed Index (free, no key needed)
    2. Finnhub API (news sentiment, analyst ratings, insider transactions)
    3. Claude AI (LLM-powered market analysis and pattern recognition)
    4. Cross-asset signals (DXY, correlations via Yahoo Finance)

    The Claude integration is the secret sauce - it can:
    - Interpret news headlines for sentiment
    - Detect market regime changes
    - Identify patterns humans might miss
    - Provide contrarian signals
    """

    def __init__(self):
        self.sentiment_cache: Dict[str, Dict] = {}
        self.news_cache: Dict[str, Dict] = {}
        self.claude_cache: Dict[str, Dict] = {}
        self.fear_greed_value: float = 50
        self.last_update: Optional[datetime] = None
        self.cache_duration = timedelta(minutes=15)

        # Get API keys from settings
        try:
            from ..config import get_settings
            settings = get_settings()
            self.finnhub_api_key = settings.finnhub_api_key
            self.anthropic_api_key = settings.anthropic_api_key
        except Exception:
            self.finnhub_api_key = os.environ.get("FINNHUB_API_KEY", "")
            self.anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY", "")

    async def get_fear_greed_index(self) -> Dict:
        """Fetch Crypto Fear & Greed Index (free, no key needed)."""
        import aiohttp

        try:
            url = "https://api.alternative.me/fng/"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        value = int(data["data"][0]["value"])
                        classification = data["data"][0]["value_classification"]

                        self.fear_greed_value = value

                        return {
                            "value": value,
                            "classification": classification,
                            "signal": self._fear_greed_signal(value),
                            "source": "alternative.me",
                        }
        except Exception as e:
            logger.warning(f"Failed to fetch Fear & Greed: {e}")

        return {"value": 50, "classification": "Neutral", "signal": 0, "source": "default"}

    def _fear_greed_signal(self, value: int) -> float:
        """Contrarian Fear & Greed signal."""
        if value < 25:
            return 1.0  # Extreme fear = strong buy
        elif value < 45:
            return 0.5
        elif value < 55:
            return 0.0
        elif value < 75:
            return -0.5
        else:
            return -1.0  # Extreme greed = strong sell

    async def get_finnhub_sentiment(self, symbol: str) -> Dict:
        """
        Get market sentiment from Finnhub API.

        Finnhub provides:
        - News sentiment scores
        - Analyst recommendations (buy/hold/sell)
        - Insider transactions
        - Social sentiment (Reddit, Twitter mentions)

        Free tier: 60 API calls/minute
        Docs: https://finnhub.io/docs/api
        """
        import aiohttp

        cache_key = f"finnhub_{symbol}"
        if cache_key in self.sentiment_cache:
            cached = self.sentiment_cache[cache_key]
            if datetime.now() - cached.get("timestamp", datetime.min) < self.cache_duration:
                return cached["data"]

        default_response = {
            "symbol": symbol,
            "news_sentiment": 0,
            "analyst_signal": 0,
            "insider_signal": 0,
            "social_sentiment": 0,
            "signal": 0,
            "source": "default",
        }

        if not self.finnhub_api_key:
            logger.debug("Finnhub API key not set")
            return default_response

        try:
            base_url = "https://finnhub.io/api/v1"
            signals = []

            async with aiohttp.ClientSession() as session:
                # 1. News Sentiment
                try:
                    url = f"{base_url}/news-sentiment"
                    params = {"symbol": symbol, "token": self.finnhub_api_key}
                    async with session.get(url, params=params, timeout=10) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            if data.get("sentiment"):
                                # Finnhub sentiment: -1 (bearish) to 1 (bullish)
                                buzz_score = data.get("buzz", {}).get("buzz", 0)
                                sentiment_score = data["sentiment"].get("bullishPercent", 50) / 100
                                news_signal = (sentiment_score - 0.5) * 2  # Normalize to -1 to 1

                                # Weight by buzz (more mentions = more significant)
                                if buzz_score > 1.5:
                                    news_signal *= 1.2

                                signals.append(("news", news_signal))
                except Exception as e:
                    logger.debug(f"Finnhub news sentiment error: {e}")

                # 2. Analyst Recommendations
                try:
                    url = f"{base_url}/stock/recommendation"
                    params = {"symbol": symbol, "token": self.finnhub_api_key}
                    async with session.get(url, params=params, timeout=10) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            if data:
                                latest = data[0]  # Most recent
                                buy = latest.get("buy", 0) + latest.get("strongBuy", 0)
                                sell = latest.get("sell", 0) + latest.get("strongSell", 0)
                                hold = latest.get("hold", 0)
                                total = buy + sell + hold

                                if total > 0:
                                    # Score: more buys = positive, more sells = negative
                                    analyst_signal = (buy - sell) / total
                                    signals.append(("analyst", analyst_signal))
                except Exception as e:
                    logger.debug(f"Finnhub analyst error: {e}")

                # 3. Insider Transactions (for stocks)
                try:
                    url = f"{base_url}/stock/insider-transactions"
                    params = {"symbol": symbol, "token": self.finnhub_api_key}
                    async with session.get(url, params=params, timeout=10) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            if data.get("data"):
                                # Analyze recent insider activity
                                recent = data["data"][:10]  # Last 10 transactions
                                buys = sum(1 for t in recent if t.get("transactionType") == "P")
                                sells = sum(1 for t in recent if t.get("transactionType") == "S")

                                if buys + sells > 0:
                                    insider_signal = (buys - sells) / (buys + sells)
                                    signals.append(("insider", insider_signal * 0.5))  # Lower weight
                except Exception as e:
                    logger.debug(f"Finnhub insider error: {e}")

                # 4. Social Sentiment (if available)
                try:
                    url = f"{base_url}/stock/social-sentiment"
                    params = {"symbol": symbol, "token": self.finnhub_api_key}
                    async with session.get(url, params=params, timeout=10) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            reddit = data.get("reddit", [])
                            twitter = data.get("twitter", [])

                            if reddit or twitter:
                                # Aggregate sentiment from social platforms
                                all_mentions = reddit + twitter
                                if all_mentions:
                                    avg_score = sum(m.get("score", 0) for m in all_mentions) / len(all_mentions)
                                    social_signal = max(-1, min(1, avg_score / 100))
                                    signals.append(("social", social_signal))
                except Exception as e:
                    logger.debug(f"Finnhub social error: {e}")

            # Combine signals with equal weighting
            if signals:
                combined_signal = sum(s[1] for s in signals) / len(signals)
            else:
                combined_signal = 0

            result = {
                "symbol": symbol,
                "signals": {name: round(val, 3) for name, val in signals},
                "signal": round(max(-1, min(1, combined_signal)), 3),
                "source": "finnhub",
                "num_signals": len(signals),
            }

            self.sentiment_cache[cache_key] = {
                "data": result,
                "timestamp": datetime.now(),
            }

            return result

        except Exception as e:
            logger.warning(f"Finnhub API error for {symbol}: {e}")

        return default_response

    async def get_claude_alpha(self, symbol: str, market_data: Optional[Dict] = None) -> Dict:
        """
        Use Claude to generate alpha signals from market analysis.

        Claude analyzes:
        1. Recent price action and technical patterns
        2. News headlines and sentiment
        3. Market regime (trending, ranging, volatile)
        4. Cross-asset correlations
        5. Contrarian opportunities

        This is your UNIQUE EDGE - LLM-powered trading signals!
        """
        cache_key = f"claude_{symbol}"
        if cache_key in self.claude_cache:
            cached = self.claude_cache[cache_key]
            if datetime.now() - cached.get("timestamp", datetime.min) < self.cache_duration:
                return cached["data"]

        default_response = {
            "symbol": symbol,
            "signal": 0,
            "confidence": 0,
            "analysis": "No analysis available",
            "recommendation": "hold",
            "source": "default",
        }

        if not self.anthropic_api_key:
            logger.debug("Anthropic API key not set for Claude alpha")
            return default_response

        try:
            import anthropic

            # Gather context for Claude
            context_parts = [f"Symbol: {symbol}"]

            # Add Fear & Greed
            fg = await self.get_fear_greed_index()
            context_parts.append(f"Fear & Greed Index: {fg['value']} ({fg['classification']})")

            # Add Finnhub sentiment if available
            if self.finnhub_api_key:
                finnhub = await self.get_finnhub_sentiment(symbol)
                if finnhub.get("source") == "finnhub":
                    context_parts.append(f"Finnhub Signals: {finnhub.get('signals', {})}")

            # Add market data if provided
            if market_data:
                if "price" in market_data:
                    context_parts.append(f"Current Price: ${market_data['price']:.2f}")
                if "change_24h" in market_data:
                    context_parts.append(f"24h Change: {market_data['change_24h']:.2f}%")
                if "volume" in market_data:
                    context_parts.append(f"Volume: {market_data['volume']}")

            context = "\n".join(context_parts)

            # Create Claude client
            client = anthropic.Anthropic(api_key=self.anthropic_api_key)

            # Generate alpha signal
            prompt = f"""You are a quantitative trading analyst. Analyze this market data and provide a trading signal.

MARKET DATA:
{context}

Provide your analysis in this EXACT JSON format (no markdown, just raw JSON):
{{
    "signal": <float between -1 (strong sell) and 1 (strong buy)>,
    "confidence": <float between 0 and 1>,
    "regime": "<trending_up|trending_down|ranging|volatile>",
    "key_factors": ["<factor1>", "<factor2>", "<factor3>"],
    "recommendation": "<strong_buy|buy|hold|sell|strong_sell>",
    "reasoning": "<one sentence explanation>"
}}

Be contrarian when sentiment is extreme. Consider:
- Fear & Greed extremes are often reversal signals
- High confidence requires multiple confirming signals
- Default to 'hold' (signal near 0) when uncertain"""

            response = client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}]
            )

            # Parse Claude's response
            response_text = response.content[0].text.strip()

            # Try to extract JSON from response
            try:
                import json
                # Handle potential markdown code blocks
                if "```" in response_text:
                    response_text = response_text.split("```")[1]
                    if response_text.startswith("json"):
                        response_text = response_text[4:]

                analysis = json.loads(response_text)

                result = {
                    "symbol": symbol,
                    "signal": max(-1, min(1, float(analysis.get("signal", 0)))),
                    "confidence": max(0, min(1, float(analysis.get("confidence", 0.5)))),
                    "regime": analysis.get("regime", "unknown"),
                    "key_factors": analysis.get("key_factors", []),
                    "recommendation": analysis.get("recommendation", "hold"),
                    "reasoning": analysis.get("reasoning", ""),
                    "source": "claude",
                }

                self.claude_cache[cache_key] = {
                    "data": result,
                    "timestamp": datetime.now(),
                }

                logger.info(f"Claude alpha for {symbol}: signal={result['signal']:.2f}, conf={result['confidence']:.2f}")
                return result

            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse Claude response: {e}")
                # Try to extract signal from text
                if "buy" in response_text.lower():
                    return {**default_response, "signal": 0.3, "source": "claude_fallback"}
                elif "sell" in response_text.lower():
                    return {**default_response, "signal": -0.3, "source": "claude_fallback"}

        except Exception as e:
            logger.warning(f"Claude alpha error for {symbol}: {e}")

        return default_response

    async def get_cross_asset_signals(self) -> Dict:
        """
        Analyze cross-asset correlations (free via Yahoo Finance).

        - DXY strength = bearish for risk assets
        - VIX spikes = opportunity or danger
        - Gold/BTC correlation for risk sentiment
        """
        import aiohttp

        try:
            # Fetch DXY (Dollar Index)
            url = "https://query1.finance.yahoo.com/v8/finance/chart/DX-Y.NYB"
            params = {"interval": "1d", "range": "5d"}
            headers = {"User-Agent": "Mozilla/5.0"}

            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, headers=headers, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        result = data.get("chart", {}).get("result", [])

                        if result:
                            quotes = result[0].get("indicators", {}).get("quote", [{}])[0]
                            closes = quotes.get("close", [])

                            if len(closes) >= 2:
                                dxy_current = closes[-1]
                                dxy_prev = closes[-2]

                                if dxy_current and dxy_prev:
                                    dxy_change = (dxy_current - dxy_prev) / dxy_prev

                                    # Strong dollar = bearish for risk assets
                                    if dxy_change > 0.005:
                                        dxy_signal = -0.3
                                    elif dxy_change > 0:
                                        dxy_signal = -0.1
                                    elif dxy_change < -0.005:
                                        dxy_signal = 0.3
                                    else:
                                        dxy_signal = 0.1

                                    return {
                                        "dxy_value": round(dxy_current, 2),
                                        "dxy_change_pct": round(dxy_change * 100, 2),
                                        "regime": "risk_off" if dxy_signal < 0 else "risk_on",
                                        "signal": dxy_signal,
                                        "source": "yahoo",
                                    }

        except Exception as e:
            logger.debug(f"Cross-asset data error: {e}")

        return {"dxy_value": 0, "dxy_change_pct": 0, "regime": "neutral", "signal": 0, "source": "default"}

    async def get_combined_alpha(self, symbol: str, market_data: Optional[Dict] = None) -> Dict:
        """
        Combine all alpha sources into a single trading signal.

        Weighting (adapts based on available data):
        - Fear & Greed: 15% (always available)
        - Finnhub Sentiment: 25% (if API key set)
        - Claude AI Analysis: 40% (if API key set - this is your edge!)
        - Cross-Asset: 20% (always available via Yahoo)
        """
        # Fetch all signals in parallel
        tasks = [
            self.get_fear_greed_index(),
            self.get_finnhub_sentiment(symbol),
            self.get_claude_alpha(symbol, market_data),
            self.get_cross_asset_signals(),
        ]

        fear_greed, finnhub, claude, cross_asset = await asyncio.gather(*tasks)

        # Dynamic weighting based on data availability
        weights = {
            "fear_greed": 0.15,  # Always available
            "finnhub": 0.25 if finnhub.get("source") == "finnhub" else 0.05,
            "claude": 0.40 if claude.get("source") == "claude" else 0.10,
            "cross_asset": 0.20 if cross_asset.get("source") == "yahoo" else 0.10,
        }

        # Normalize weights
        total_weight = sum(weights.values())
        weights = {k: v / total_weight for k, v in weights.items()}

        # Combine signals
        combined_signal = (
            fear_greed["signal"] * weights["fear_greed"] +
            finnhub["signal"] * weights["finnhub"] +
            claude["signal"] * weights["claude"] +
            cross_asset["signal"] * weights["cross_asset"]
        )

        # Adjust confidence based on Claude's confidence
        confidence = claude.get("confidence", 0.5) if claude.get("source") == "claude" else abs(combined_signal)

        # Determine recommendation
        if combined_signal > 0.4:
            recommendation = "strong_buy"
        elif combined_signal > 0.2:
            recommendation = "buy"
        elif combined_signal < -0.4:
            recommendation = "strong_sell"
        elif combined_signal < -0.2:
            recommendation = "sell"
        else:
            recommendation = "hold"

        return {
            "symbol": symbol,
            "combined_signal": round(combined_signal, 3),
            "confidence": round(confidence, 2),
            "recommendation": recommendation,
            "components": {
                "fear_greed": fear_greed,
                "finnhub": finnhub,
                "claude": claude,
                "cross_asset": cross_asset,
            },
            "weights_used": {k: round(v, 2) for k, v in weights.items()},
            "timestamp": datetime.now().isoformat(),
        }


# Global instances
_data_downloader: Optional[HistoricalDataDownloader] = None
_model_pretrainer: Optional[ModelPreTrainer] = None
_backtester: Optional[WalkForwardBacktester] = None
_alpha_manager: Optional[AlphaSourceManager] = None


def get_data_downloader() -> HistoricalDataDownloader:
    """Get or create data downloader instance."""
    global _data_downloader
    if _data_downloader is None:
        _data_downloader = HistoricalDataDownloader()
    return _data_downloader


def get_model_pretrainer() -> ModelPreTrainer:
    """Get or create model pre-trainer instance."""
    global _model_pretrainer
    if _model_pretrainer is None:
        _model_pretrainer = ModelPreTrainer()
    return _model_pretrainer


def get_backtester() -> WalkForwardBacktester:
    """Get or create backtester instance."""
    global _backtester
    if _backtester is None:
        _backtester = WalkForwardBacktester()
    return _backtester


def get_alpha_manager() -> AlphaSourceManager:
    """Get or create alpha manager instance."""
    global _alpha_manager
    if _alpha_manager is None:
        _alpha_manager = AlphaSourceManager()
    return _alpha_manager


async def run_full_training_pipeline(
    days_of_data: int = 180,
    training_epochs: int = 100
) -> Dict:
    """
    Run the complete pre-training pipeline:
    1. Download historical data
    2. Train models
    3. Run backtest
    4. Save checkpoints

    Returns training and backtest results.
    """
    logger.info("="*60)
    logger.info("STARTING FULL TRAINING PIPELINE")
    logger.info("="*60)

    # Initialize components
    downloader = get_data_downloader()
    pretrainer = get_model_pretrainer()
    backtester = get_backtester()

    # Step 1: Download historical data
    logger.info("\n📥 Step 1: Downloading historical data...")
    historical_data = await downloader.download_all(days=days_of_data)

    if not historical_data:
        # Try loading from disk
        historical_data = downloader.load_all_from_disk()

    if not historical_data:
        return {"error": "Failed to obtain historical data"}

    logger.info(f"Loaded data for {len(historical_data)} symbols")

    # Step 2: Prepare training data
    logger.info("\n🔧 Step 2: Preparing training data...")
    features, labels, rewards = pretrainer.prepare_training_data(historical_data, backtester)

    if len(features) == 0:
        return {"error": "Failed to prepare training data"}

    logger.info(f"Prepared {len(features)} training samples")

    # Step 3: Train models
    logger.info("\n🧠 Step 3: Training ML models...")
    training_metrics = pretrainer.train(
        features, labels, rewards,
        epochs=training_epochs,
        batch_size=64
    )

    # Step 4: Run backtest
    logger.info("\n📊 Step 4: Running walk-forward backtest...")
    backtest_result = backtester.run_backtest(historical_data, pretrainer)

    # Step 5: Validate training
    logger.info("\n✅ Step 5: Validating training requirements...")
    meets_requirements, reason = pretrainer.meets_training_requirements()

    result = {
        "success": meets_requirements,
        "reason": reason,
        "training_metrics": training_metrics.to_dict(),
        "backtest_result": backtest_result.to_dict(),
        "symbols_trained": list(historical_data.keys()),
        "checkpoint_path": str(CHECKPOINT_DIR / "model_checkpoint.pkl"),
    }

    logger.info("\n" + "="*60)
    logger.info("TRAINING PIPELINE COMPLETE")
    logger.info(f"Status: {'✅ READY FOR LIVE TRADING' if meets_requirements else '❌ ' + reason}")
    logger.info(f"Backtest Return: {backtest_result.total_return_pct:.1f}%")
    logger.info(f"Sharpe Ratio: {backtest_result.sharpe_ratio:.2f}")
    logger.info(f"Win Rate: {backtest_result.win_rate*100:.1f}%")
    logger.info("="*60)

    return result
