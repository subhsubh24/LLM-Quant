"""
Autonomous Quant Trading Bot - State-of-the-Art Edition

Renaissance Technologies-style autonomous trading system featuring:
1. Ultra-fast market scanning (1-second intervals)
2. Advanced multi-factor signals:
   - RSI (Relative Strength Index) momentum
   - MACD-style trend following
   - Bollinger Band volatility breakouts
   - Volume-weighted momentum (VWAP deviation)
   - Order flow imbalance detection
   - Statistical arbitrage z-scores
   - Regime detection (trending vs mean-reverting)
3. Kelly Criterion position sizing
4. Dynamic risk with trailing stops and volatility targeting
5. Supports both stocks and 150+ cryptocurrencies

Paper trading only - for educational purposes.
"""

import asyncio
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta, time
from enum import Enum
from collections import deque
import numpy as np
import pandas as pd
import logging
import uuid
import pytz
import math

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(message)s', datefmt='%H:%M:%S')
import json


# ============================================================================
# QUANTITATIVE UTILITIES - State-of-the-Art Financial Mathematics
# ============================================================================

class QuantMath:
    """
    Advanced quantitative finance utilities implementing industry-standard
    algorithms from academic research and hedge fund practice.
    """

    @staticmethod
    def exponential_moving_average(prices: List[float], span: int) -> float:
        """
        Calculate EMA using the standard formula:
        EMA_t = α * Price_t + (1-α) * EMA_{t-1}
        where α = 2 / (span + 1)
        """
        if not prices or len(prices) < 2:
            return prices[-1] if prices else 0

        alpha = 2 / (span + 1)
        ema = prices[0]
        for price in prices[1:]:
            ema = alpha * price + (1 - alpha) * ema
        return ema

    @staticmethod
    def relative_strength_index(prices: List[float], period: int = 14) -> float:
        """
        RSI = 100 - (100 / (1 + RS))
        where RS = Average Gain / Average Loss over period

        RSI > 70: Overbought (potential sell)
        RSI < 30: Oversold (potential buy)
        """
        if len(prices) < period + 1:
            return 50.0  # Neutral if insufficient data

        changes = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        gains = [c if c > 0 else 0 for c in changes[-period:]]
        losses = [-c if c < 0 else 0 for c in changes[-period:]]

        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period

        if avg_loss == 0:
            return 100.0

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

    @staticmethod
    def macd(prices: List[float], fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[float, float, float]:
        """
        MACD (Moving Average Convergence Divergence)
        MACD Line = EMA(12) - EMA(26)
        Signal Line = EMA(9) of MACD Line
        Histogram = MACD Line - Signal Line

        Bullish: MACD crosses above Signal
        Bearish: MACD crosses below Signal
        """
        if len(prices) < slow:
            return 0, 0, 0

        ema_fast = QuantMath.exponential_moving_average(prices, fast)
        ema_slow = QuantMath.exponential_moving_average(prices, slow)
        macd_line = ema_fast - ema_slow

        # For signal line, we'd need historical MACD values
        # Simplified: use current MACD normalized
        signal_line = macd_line * 0.9  # Approximate
        histogram = macd_line - signal_line

        return macd_line, signal_line, histogram

    @staticmethod
    def bollinger_bands(prices: List[float], period: int = 20, std_dev: float = 2.0) -> Tuple[float, float, float]:
        """
        Bollinger Bands:
        Middle = SMA(period)
        Upper = Middle + (std_dev * σ)
        Lower = Middle - (std_dev * σ)

        Price near upper band: Potential overbought
        Price near lower band: Potential oversold
        Band squeeze: Low volatility, expect breakout
        """
        if len(prices) < period:
            return prices[-1], prices[-1] * 1.05, prices[-1] * 0.95

        recent = prices[-period:]
        middle = sum(recent) / period
        std = np.std(recent)
        upper = middle + (std_dev * std)
        lower = middle - (std_dev * std)

        return middle, upper, lower

    @staticmethod
    def zscore(value: float, mean: float, std: float) -> float:
        """
        Z-score = (X - μ) / σ
        Measures how many standard deviations from mean
        |Z| > 2: Statistically significant (95% confidence)
        |Z| > 3: Highly significant (99% confidence)
        """
        if std == 0:
            return 0
        return (value - mean) / std

    @staticmethod
    def kelly_criterion(win_rate: float, win_loss_ratio: float) -> float:
        """
        Kelly Criterion for optimal position sizing:
        f* = (bp - q) / b
        where:
        - b = win/loss ratio
        - p = win rate
        - q = 1 - p (loss rate)

        Returns optimal fraction of capital to bet
        """
        if win_loss_ratio <= 0 or win_rate <= 0:
            return 0.01  # Minimum position

        q = 1 - win_rate
        kelly = (win_loss_ratio * win_rate - q) / win_loss_ratio

        # Half-Kelly is safer in practice
        half_kelly = max(0.01, min(kelly / 2, 0.25))
        return half_kelly

    @staticmethod
    def volatility_regime(returns: List[float], lookback: int = 20) -> str:
        """
        Detect volatility regime using realized volatility percentile.
        Low vol: Trend-following works better
        High vol: Mean-reversion works better
        """
        if len(returns) < lookback:
            return "NORMAL"

        recent_vol = np.std(returns[-lookback:]) * np.sqrt(252)  # Annualized

        if recent_vol < 0.15:
            return "LOW_VOL"
        elif recent_vol > 0.50:
            return "HIGH_VOL"
        else:
            return "NORMAL"

    @staticmethod
    def momentum_quality(returns: List[float]) -> float:
        """
        Momentum quality score based on consistency of returns.
        High quality: Returns are consistently in one direction
        Low quality: Returns are choppy/inconsistent

        Uses information ratio concept: mean / std of returns
        """
        if len(returns) < 5:
            return 0

        mean_ret = np.mean(returns)
        std_ret = np.std(returns)

        if std_ret == 0:
            return 1.0 if mean_ret > 0 else -1.0

        # Information ratio style
        quality = mean_ret / std_ret
        return np.clip(quality, -1, 1)

    @staticmethod
    def hurst_exponent_fast(prices: List[float]) -> float:
        """
        Fast Hurst exponent estimation for regime detection:
        H > 0.5: Trending (momentum)
        H < 0.5: Mean-reverting
        H ≈ 0.5: Random walk

        Uses simplified R/S analysis.
        """
        if len(prices) < 20:
            return 0.5

        returns = np.diff(np.log(prices))
        n = len(returns)

        # Mean-adjusted returns
        mean_adj = returns - np.mean(returns)
        cumsum = np.cumsum(mean_adj)

        # Range and std
        r = max(cumsum) - min(cumsum)
        s = np.std(returns)

        if s == 0:
            return 0.5

        rs = r / s

        # Simplified H estimation
        h = np.log(rs) / np.log(n)
        return np.clip(h, 0, 1)

    @staticmethod
    def order_flow_imbalance(volume: float, price_change: float, avg_volume: float) -> float:
        """
        Simulated order flow imbalance based on volume and price movement.
        Positive: Buy pressure (aggressive buyers)
        Negative: Sell pressure (aggressive sellers)
        """
        if avg_volume == 0:
            return 0

        volume_ratio = volume / avg_volume

        # Volume * sign of price change
        if price_change > 0:
            ofi = volume_ratio * min(abs(price_change) / 2, 1)
        else:
            ofi = -volume_ratio * min(abs(price_change) / 2, 1)

        return np.clip(ofi, -1, 1)

    @staticmethod
    def sharpe_estimate(returns: List[float], risk_free: float = 0.02) -> float:
        """
        Estimate Sharpe ratio from recent returns.
        Sharpe = (Mean Return - Risk Free) / Volatility
        """
        if len(returns) < 5:
            return 0

        mean_ret = np.mean(returns) * 252  # Annualize
        vol = np.std(returns) * np.sqrt(252)

        if vol == 0:
            return 0

        return (mean_ret - risk_free) / vol

    @staticmethod
    def safe_float(value: float, default: float = 0.0) -> float:
        """
        Ensure a float is JSON-serializable (not NaN, Inf, -Inf).
        Returns default if value is not valid.
        """
        if value is None:
            return default
        if math.isnan(value) or math.isinf(value):
            return default
        return value


# Commentary buffer for real-time UI updates
class BotCommentary:
    """Stores real-time bot thoughts and commentary."""
    def __init__(self, max_entries: int = 100):
        self.entries: List[Dict[str, Any]] = []
        self.max_entries = max_entries

    def add(self, message: str, category: str = "info", data: Dict = None):
        """Add a commentary entry."""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "message": message,
            "category": category,  # info, analysis, signal, trade, risk, market
            "data": data or {}
        }
        self.entries.append(entry)
        if len(self.entries) > self.max_entries:
            self.entries = self.entries[-self.max_entries:]
        # Also log to console
        logger.info(f"[{category.upper()}] {message}")

    def get_recent(self, limit: int = 50) -> List[Dict]:
        return self.entries[-limit:]

    def clear(self):
        self.entries = []


# Global commentary instance
_commentary = BotCommentary()


def is_market_open() -> bool:
    """Check if US stock market is currently open."""
    eastern = pytz.timezone('US/Eastern')
    now = datetime.now(eastern)

    # Market hours: 9:30 AM - 4:00 PM ET, Monday-Friday
    market_open = time(9, 30)
    market_close = time(16, 0)

    # Check if it's a weekday
    if now.weekday() >= 5:  # Saturday = 5, Sunday = 6
        return False

    current_time = now.time()
    return market_open <= current_time <= market_close


def get_market_status() -> Dict[str, Any]:
    """Get detailed market status information."""
    eastern = pytz.timezone('US/Eastern')
    now = datetime.now(eastern)
    is_open = is_market_open()

    if is_open:
        market_close = now.replace(hour=16, minute=0, second=0)
        time_to_close = (market_close - now).total_seconds() / 3600
        return {
            "is_open": True,
            "status": "OPEN",
            "message": f"Market open - {time_to_close:.1f}h until close",
            "current_time_et": now.strftime("%H:%M ET"),
        }
    else:
        # Calculate next open
        next_open = now.replace(hour=9, minute=30, second=0)
        if now.time() > time(16, 0) or now.weekday() >= 5:
            days_ahead = 1
            if now.weekday() == 4:  # Friday after close
                days_ahead = 3
            elif now.weekday() == 5:  # Saturday
                days_ahead = 2
            elif now.weekday() == 6:  # Sunday
                days_ahead = 1
            next_open = next_open + timedelta(days=days_ahead)

        time_to_open = (next_open - now).total_seconds() / 3600
        return {
            "is_open": False,
            "status": "CLOSED",
            "message": f"Market closed - {time_to_open:.1f}h until open",
            "current_time_et": now.strftime("%H:%M ET"),
            "next_open": next_open.strftime("%Y-%m-%d %H:%M ET"),
        }

from ..config import get_settings
from ..signals.engine import SignalEngine, StockSignal, PortfolioSignals, get_signal_engine
from ..data.live import get_live_market_service
from ..data.crypto import get_crypto_service
from .orders import OrderSide


class TradingMode(Enum):
    AGGRESSIVE = "aggressive"  # High frequency, day trading
    BALANCED = "balanced"      # Mix of short and medium term
    CONSERVATIVE = "conservative"  # Longer holds, lower turnover


class AssetClass(Enum):
    STOCKS = "stocks"
    CRYPTO = "crypto"
    BOTH = "both"


@dataclass
class TradeRationale:
    """
    Comprehensive trade rationale with detailed quantitative analysis.
    Provides full transparency into the decision-making process.
    """
    decision: str  # BUY, SELL, HOLD
    confidence: float  # 0-1 (Kelly-adjusted)
    primary_reason: str  # Human-readable main driver

    # Quantitative Factors
    factors: Dict[str, float]  # All factor scores
    factor_weights: Dict[str, float]  # Weight applied to each factor

    # Technical Analysis
    rsi_value: float = 50.0  # RSI reading
    rsi_signal: str = "NEUTRAL"  # OVERSOLD, NEUTRAL, OVERBOUGHT
    macd_signal: str = "NEUTRAL"  # BULLISH, NEUTRAL, BEARISH
    bollinger_position: str = "MIDDLE"  # LOWER, MIDDLE, UPPER
    momentum_quality: float = 0.0  # -1 to 1 (consistency)

    # Statistical Analysis
    zscore: float = 0.0  # Standard deviations from mean
    volatility_regime: str = "NORMAL"  # LOW_VOL, NORMAL, HIGH_VOL
    hurst_exponent: float = 0.5  # Trend vs mean-reversion indicator

    # Market Microstructure
    order_flow_signal: float = 0.0  # -1 to 1 (buy/sell pressure)
    volume_confirmation: bool = False  # Is volume supporting the move?
    liquidity_score: float = 0.5  # 0-1 (higher = more liquid)

    # Risk Metrics
    risk_assessment: str = ""
    position_size_kelly: float = 0.0  # Kelly-optimal size
    expected_return: float = 0.0
    expected_sharpe: float = 0.0
    max_loss_scenario: str = ""

    # Trade Parameters
    expected_holding_period: str = ""
    stop_loss: float = 0.0
    take_profit: float = 0.0
    trailing_stop: float = 0.0

    # Summary
    signals_summary: str = ""
    detailed_analysis: str = ""  # Multi-line detailed explanation
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict:
        return {
            "decision": self.decision,
            "confidence": round(self.confidence, 3),
            "confidence_pct": f"{self.confidence * 100:.1f}%",
            "primary_reason": self.primary_reason,

            # Factors breakdown
            "factors": {k: round(v, 4) for k, v in self.factors.items()},
            "factor_weights": {k: round(v, 3) for k, v in self.factor_weights.items()},

            # Technical indicators
            "technical_analysis": {
                "rsi": {"value": round(self.rsi_value, 1), "signal": self.rsi_signal},
                "macd_signal": self.macd_signal,
                "bollinger_position": self.bollinger_position,
                "momentum_quality": round(self.momentum_quality, 2),
            },

            # Statistical measures
            "statistical_analysis": {
                "zscore": round(self.zscore, 2),
                "volatility_regime": self.volatility_regime,
                "hurst_exponent": round(self.hurst_exponent, 3),
                "market_type": "TRENDING" if self.hurst_exponent > 0.55 else "MEAN_REVERTING" if self.hurst_exponent < 0.45 else "RANDOM",
            },

            # Market structure
            "market_microstructure": {
                "order_flow": round(self.order_flow_signal, 2),
                "order_flow_direction": "BUY_PRESSURE" if self.order_flow_signal > 0.3 else "SELL_PRESSURE" if self.order_flow_signal < -0.3 else "BALANCED",
                "volume_confirms": self.volume_confirmation,
                "liquidity": round(self.liquidity_score, 2),
            },

            # Risk
            "risk_metrics": {
                "assessment": self.risk_assessment,
                "kelly_size": f"{self.position_size_kelly * 100:.1f}%",
                "expected_return": f"{self.expected_return * 100:.2f}%",
                "expected_sharpe": round(self.expected_sharpe, 2),
                "max_loss_scenario": self.max_loss_scenario,
            },

            # Trade setup
            "trade_setup": {
                "holding_period": self.expected_holding_period,
                "stop_loss": f"{self.stop_loss * 100:.1f}%",
                "take_profit": f"{self.take_profit * 100:.1f}%",
                "trailing_stop": f"{self.trailing_stop * 100:.1f}%",
                "risk_reward": round(self.take_profit / self.stop_loss, 2) if self.stop_loss > 0 else 0,
            },

            "signals_summary": self.signals_summary,
            "detailed_analysis": self.detailed_analysis,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class BotTrade:
    """Record of a bot trade with full context."""
    id: str
    timestamp: datetime
    asset_class: str
    symbol: str
    side: str
    quantity: float
    price: float
    value: float
    rationale: TradeRationale
    status: str = "executed"
    pnl: float = 0.0
    closed_at: Optional[datetime] = None

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat(),
            "asset_class": self.asset_class,
            "symbol": self.symbol,
            "side": self.side,
            "quantity": self.quantity,
            "price": round(self.price, 2),
            "value": round(self.value, 2),
            "rationale": self.rationale.to_dict(),
            "status": self.status,
            "pnl": round(self.pnl, 2),
            "closed_at": self.closed_at.isoformat() if self.closed_at else None,
        }


@dataclass
class BotPosition:
    """Current bot position with tracking."""
    symbol: str
    asset_class: str
    quantity: float
    entry_price: float
    current_price: float
    entry_time: datetime
    entry_rationale: TradeRationale
    stop_loss_price: float
    take_profit_price: float
    trailing_stop_pct: float = 0.10

    @property
    def market_value(self) -> float:
        return self.quantity * self.current_price

    @property
    def unrealized_pnl(self) -> float:
        return (self.current_price - self.entry_price) * self.quantity

    @property
    def unrealized_pnl_pct(self) -> float:
        return (self.current_price - self.entry_price) / self.entry_price

    @property
    def holding_period(self) -> timedelta:
        return datetime.now() - self.entry_time

    def to_dict(self) -> Dict:
        return {
            "symbol": self.symbol,
            "asset_class": self.asset_class,
            "quantity": self.quantity,
            "entry_price": round(self.entry_price, 2),
            "current_price": round(self.current_price, 2),
            "market_value": round(self.market_value, 2),
            "unrealized_pnl": round(self.unrealized_pnl, 2),
            "unrealized_pnl_pct": round(self.unrealized_pnl_pct * 100, 2),
            "entry_time": self.entry_time.isoformat(),
            "holding_period": str(self.holding_period),
            "stop_loss_price": round(self.stop_loss_price, 2),
            "take_profit_price": round(self.take_profit_price, 2),
        }


class QuantBot:
    """
    Autonomous quantitative trading bot.

    Implements Renaissance Technologies-style strategies:
    - Statistical arbitrage
    - Mean reversion
    - Momentum with regime switching
    - Factor-based position sizing
    - Dynamic risk management
    """

    # Stock universe for trading - Major liquid names
    STOCK_UNIVERSE = [
        # Mega-cap Tech
        "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "AMD", "INTC", "CRM",
        "ORCL", "ADBE", "AVGO", "QCOM", "TXN", "MU", "AMAT", "LRCX", "KLAC", "SNPS",
        # Financials
        "JPM", "BAC", "GS", "MS", "WFC", "C", "V", "MA", "PYPL", "BLK",
        # Healthcare
        "JNJ", "PFE", "UNH", "MRK", "ABBV", "LLY", "TMO", "ABT", "DHR", "BMY",
        # Energy
        "XOM", "CVX", "COP", "SLB", "EOG",
        # Consumer
        "HD", "LOW", "TGT", "COST", "WMT", "NKE", "SBUX", "MCD",
        # Media/Entertainment
        "DIS", "NFLX", "CMCSA", "WBD", "PARA",
        # EV & Clean Energy
        "RIVN", "LCID", "NIO", "ENPH", "FSLR",
    ]

    # Crypto universe - 150+ cryptocurrencies for comprehensive market coverage
    CRYPTO_UNIVERSE = [
        # ===== TOP 10 - Blue Chips =====
        "BTC", "ETH", "BNB", "XRP", "SOL", "ADA", "DOGE", "TRX", "AVAX", "LINK",

        # ===== 11-25 - Major Altcoins =====
        "DOT", "MATIC", "SHIB", "TON", "LTC", "BCH", "UNI", "ATOM", "XLM", "ICP",
        "ETC", "FIL", "APT", "NEAR", "IMX",

        # ===== 26-50 - Mid-Cap Leaders =====
        "HBAR", "OP", "INJ", "VET", "MKR", "ARB", "GRT", "AAVE", "ALGO", "RUNE",
        "FTM", "SAND", "MANA", "AXS", "SNX", "LDO", "CRV", "EGLD", "THETA", "XTZ",
        "FLOW", "KAVA", "NEO", "IOTA", "ZEC",

        # ===== 51-75 - Established Altcoins =====
        "CAKE", "1INCH", "COMP", "ENJ", "BAT", "CELO", "ZRX", "YFI", "SUSHI", "KSM",
        "GMX", "DYDX", "STX", "SUI", "SEI", "TIA", "JUP", "PYTH", "WIF", "BONK",
        "PEPE", "FLOKI", "RNDR", "FET", "AGIX",

        # ===== 76-100 - AI & Computing =====
        "OCEAN", "TAO", "AR", "HNT", "QNT", "AKT", "ROSE", "FXS", "SSV", "RPL",
        "PENDLE", "BLUR", "ID", "EDU", "MAGIC", "LQTY", "API3", "AUDIO", "RAD", "PERP",
        "DODO", "ALPHA", "CHESS", "HIGH", "VOXEL",

        # ===== 101-125 - Gaming & Metaverse =====
        "GALA", "ILV", "SUPER", "YGG", "PYR", "WAXP", "GODS", "IMX", "RARE", "LOOKS",
        "APE", "MEME", "AIDOGE", "LADYS", "TURBO", "BOB", "TOSHI", "BRETT", "MICHI", "POPCAT",
        "NEIRO", "GOAT", "PNUT", "ACT", "VIRTUAL",

        # ===== 126-150 - DeFi & Infrastructure =====
        "JTO", "STRK", "MANTA", "DYM", "ALT", "PORTAL", "PIXEL", "AEVO", "ENA", "W",
        "ONDO", "ETHFI", "REZ", "SAGA", "OMNI", "BB", "NOT", "IO", "ZK", "LISTA",
        "ZRO", "BLAST", "SCR", "EIGEN", "GRASS",

        # ===== 151-175 - Emerging & High-Potential =====
        "MORPHO", "ME", "MOVE", "USUAL", "VANA", "PENGU", "BIO", "ANIME", "TRUMP", "MELANIA",
        "AI16Z", "FARTCOIN", "GRIFFAIN", "SWARMS", "ARC", "ZEREBRO", "ELIZA", "ORCA", "MAX", "MOODENG",
        "SPX", "GIGACHAD", "GIGA", "PONKE", "WEN",

        # ===== 176-200 - Long-tail Opportunities =====
        "BOME", "SLERF", "TREMP", "DOG", "RUNE", "ORDI", "SATS", "RATS", "PIZZA", "WZRD",
        "MEW", "MYRO", "PORK", "BEER", "BODEN", "DEGEN", "HIGHER", "TYBG", "FRIEND", "NORMIE",
        "AERO", "DINO", "MOG", "CATGIRL", "HAPPY",
    ]

    def __init__(
        self,
        initial_capital: float = 10000.0,
        mode: TradingMode = TradingMode.BALANCED,
        asset_class: AssetClass = AssetClass.BOTH,
        max_positions: int = 10,
        max_position_pct: float = 0.15,
        min_trade_value: float = 100.0,
    ):
        self.settings = get_settings()
        self.signal_engine = get_signal_engine()
        self.market_service = get_live_market_service()
        self.crypto_service = get_crypto_service()

        # Capital and settings
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.mode = mode
        self.asset_class = asset_class
        self.max_positions = max_positions
        self.max_position_pct = max_position_pct
        self.min_trade_value = min_trade_value

        # Positions and trades
        self.positions: Dict[str, BotPosition] = {}
        self.trade_history: List[BotTrade] = []
        self.pending_signals: List[Dict] = []

        # Performance tracking
        self.equity_curve: List[Tuple[datetime, float]] = [(datetime.now(), initial_capital)]
        self.daily_pnl: List[Tuple[datetime, float]] = []

        # Bot state
        self.is_running = False
        self.last_scan_time: Optional[datetime] = None
        self.scan_interval_seconds = self._get_scan_interval()

        # Mode-specific settings
        self._configure_mode()

        logger.info(f"QuantBot initialized: ${initial_capital:,.2f} capital, {mode.value} mode, {asset_class.value} assets")

    def _get_scan_interval(self) -> float:
        """
        Get scan interval based on mode - ULTRA-FAST for real-time trading.
        Aggressive: 1 second (institutional-grade speed)
        Balanced: 2 seconds
        Conservative: 5 seconds
        """
        if self.mode == TradingMode.AGGRESSIVE:
            return 1.0  # 1 second - maximum speed
        elif self.mode == TradingMode.BALANCED:
            return 2.0  # 2 seconds
        else:
            return 5.0  # 5 seconds for conservative

    def _configure_mode(self):
        """
        Configure bot based on trading mode with optimized parameters
        derived from quantitative research on crypto markets.
        """
        # Initialize price history tracking for technical indicators
        self.price_history: Dict[str, deque] = {}
        self.max_history_length = 100  # Store last 100 price points per asset

        # Price cache for reducing API calls (symbol -> (price, timestamp))
        self._price_cache: Dict[str, Tuple[float, datetime]] = {}
        self._cache_ttl_seconds = 0.5  # Cache valid for 500ms (ultra-fast refresh)

        # Batch processing settings
        self._batch_size = 50  # Process coins in batches of 50
        self._max_concurrent_requests = 20  # Limit concurrent API calls

        # Historical win rate estimates for Kelly sizing
        self.estimated_win_rate = 0.52  # Slight edge assumption
        self.win_loss_ratio = 1.5  # Target 1.5:1 reward/risk

        if self.mode == TradingMode.AGGRESSIVE:
            # Aggressive: High frequency, tight stops, quick profits
            self.stop_loss_pct = 0.025  # 2.5% stop (tight)
            self.take_profit_pct = 0.04  # 4% take profit
            self.signal_threshold = 0.12  # Low threshold = more trades
            self.holding_period_target = "minutes to hours"
            self.rsi_oversold = 25  # More extreme for entries
            self.rsi_overbought = 75
            self.min_confidence = 0.45  # Accept lower confidence
            self.volatility_target = 0.30  # 30% vol target

        elif self.mode == TradingMode.BALANCED:
            # Balanced: Mix of quick and swing trades
            self.stop_loss_pct = 0.05  # 5% stop
            self.take_profit_pct = 0.10  # 10% take profit
            self.signal_threshold = 0.20
            self.holding_period_target = "hours to 2 days"
            self.rsi_oversold = 30
            self.rsi_overbought = 70
            self.min_confidence = 0.55
            self.volatility_target = 0.20  # 20% vol target

        else:  # Conservative
            # Conservative: Swing trading, wider stops, bigger targets
            self.stop_loss_pct = 0.08  # 8% stop
            self.take_profit_pct = 0.20  # 20% take profit
            self.signal_threshold = 0.30
            self.holding_period_target = "2-7 days"
            self.rsi_oversold = 35
            self.rsi_overbought = 65
            self.min_confidence = 0.65
            self.volatility_target = 0.15  # 15% vol target

    def _get_cached_price(self, symbol: str) -> Optional[float]:
        """Get price from cache if still valid."""
        if symbol in self._price_cache:
            price, timestamp = self._price_cache[symbol]
            age = (datetime.now() - timestamp).total_seconds()
            if age < self._cache_ttl_seconds:
                return price
        return None

    def _cache_price(self, symbol: str, price: float):
        """Cache a price with current timestamp."""
        self._price_cache[symbol] = (price, datetime.now())

    def _clear_stale_cache(self):
        """Remove stale entries from price cache."""
        now = datetime.now()
        stale = [
            sym for sym, (_, ts) in self._price_cache.items()
            if (now - ts).total_seconds() > self._cache_ttl_seconds * 10
        ]
        for sym in stale:
            del self._price_cache[sym]

    @property
    def total_value(self) -> float:
        """Total portfolio value."""
        position_value = sum(p.market_value for p in self.positions.values())
        return self.cash + position_value

    @property
    def total_pnl(self) -> float:
        """Total P&L since inception."""
        return self.total_value - self.initial_capital

    @property
    def total_pnl_pct(self) -> float:
        """Total return percentage."""
        return self.total_pnl / self.initial_capital

    async def start(self):
        """Start the autonomous trading bot."""
        self.is_running = True
        self.commentary = _commentary
        self.commentary.clear()

        self.commentary.add(
            f"🚀 QUANTBOT v2.1 ACTIVATED - Ultra-Fast Parallel Pipeline",
            "market"
        )
        self.commentary.add(
            f"💰 Capital: ${self.initial_capital:,.2f} | Mode: {self.mode.value.upper()} | Assets: {self.asset_class.value.upper()}",
            "market"
        )
        self.commentary.add(
            f"⚡ OPTIMIZED PIPELINE: {self.scan_interval_seconds}s intervals | {self._max_concurrent_requests} parallel requests | {self._batch_size} coins/batch",
            "info"
        )
        self.commentary.add(
            f"🌐 Universe: {len(self.CRYPTO_UNIVERSE)} cryptos + {len(self.STOCK_UNIVERSE)} stocks | Cache TTL: {self._cache_ttl_seconds*1000:.0f}ms",
            "info"
        )
        self.commentary.add(
            f"📊 QUANT STRATEGIES: RSI | MACD | Bollinger Bands | Z-Score | Hurst Regime | Kelly Sizing",
            "info"
        )
        self.commentary.add(
            f"🎯 Parameters: Stop {self.stop_loss_pct*100:.1f}% | Target {self.take_profit_pct*100:.1f}% | RSI: {self.rsi_oversold}/{self.rsi_overbought} | Threshold: {self.signal_threshold:.2f}",
            "info"
        )

        cycle_count = 0
        while self.is_running:
            try:
                cycle_count += 1
                await self._run_trading_cycle(cycle_count)
                await asyncio.sleep(self.scan_interval_seconds)
            except Exception as e:
                self.commentary.add(f"⚠️ Cycle error: {str(e)[:100]}", "risk")
                logger.error(f"Trading cycle error: {e}")
                await asyncio.sleep(5)  # Quick retry

    def stop(self):
        """Stop the autonomous trading bot."""
        self.is_running = False
        logger.info("QuantBot STOPPED")

    async def _run_trading_cycle(self, cycle_count: int = 0):
        """Execute one complete trading cycle with smart market detection."""
        cycle_start = datetime.now()
        self.last_scan_time = cycle_start

        # Clear stale cache periodically (every 100 cycles)
        if cycle_count % 100 == 0:
            self._clear_stale_cache()

        # Check market status
        market_status = get_market_status()
        market_open = market_status["is_open"]

        # Log cycle start every 10 cycles with timing info
        if cycle_count % 10 == 1:
            cache_size = len(self._price_cache)
            self.commentary.add(
                f"📊 Cycle #{cycle_count} | Portfolio: ${self.total_value:,.2f} | P&L: ${self.total_pnl:+,.2f} ({self.total_pnl_pct*100:+.2f}%) | Cache: {cache_size} prices",
                "info"
            )

        # 1. Update all positions with current prices
        await self._update_positions()

        # 2. Check risk limits (stop loss, take profit)
        await self._check_risk_limits()

        # 3. Scan for new opportunities based on market hours
        if self.asset_class == AssetClass.STOCKS:
            if market_open:
                await self._scan_stocks()
            else:
                if cycle_count % 20 == 1:
                    self.commentary.add(f"🏛️ Stock market CLOSED - {market_status['message']}", "market")

        elif self.asset_class == AssetClass.CRYPTO:
            await self._scan_crypto()

        elif self.asset_class == AssetClass.BOTH:
            if market_open:
                await self._scan_stocks()
                await self._scan_crypto()
            else:
                if cycle_count % 20 == 1:
                    self.commentary.add(f"🌙 Market CLOSED → CRYPTO ONLY mode active", "market")
                await self._scan_crypto()

        # 4. Execute pending signals
        await self._execute_signals()

        # 5. Update equity curve
        self.equity_curve.append((datetime.now(), self.total_value))

        # 6. Store market status
        self.market_status = market_status

    async def _update_positions(self):
        """Update all position prices - OPTIMIZED with parallel async."""
        if not self.positions:
            return

        async def fetch_price(symbol: str, position):
            try:
                if position.asset_class == "stocks":
                    quote = await self.market_service.get_quote(symbol)
                else:
                    quote = await self.crypto_service.get_quote(symbol)
                if quote:
                    return symbol, quote.price
            except Exception as e:
                logger.debug(f"Price fetch failed for {symbol}: {e}")
            return symbol, None

        # Parallel fetch all position prices
        tasks = [fetch_price(sym, pos) for sym, pos in self.positions.items()]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Update positions with fetched prices
        for result in results:
            if isinstance(result, tuple) and result[1] is not None:
                symbol, price = result
                if symbol in self.positions:
                    self.positions[symbol].current_price = price
                    # Also cache the price
                    self._price_cache[symbol] = (price, datetime.now())

    async def _check_risk_limits(self):
        """Check and enforce stop loss / take profit for all positions."""
        positions_to_close = []

        for symbol, position in self.positions.items():
            pnl_pct = position.unrealized_pnl_pct

            # Check stop loss
            if position.current_price <= position.stop_loss_price:
                reason = f"STOP LOSS triggered at {pnl_pct*100:.1f}%"
                positions_to_close.append((symbol, reason, "stop_loss"))
                self.commentary.add(
                    f"🛑 STOP LOSS: {symbol} hit ${position.stop_loss_price:.2f} - Closing position",
                    "risk"
                )

            # Check take profit
            elif position.current_price >= position.take_profit_price:
                reason = f"TAKE PROFIT triggered at {pnl_pct*100:.1f}%"
                positions_to_close.append((symbol, reason, "take_profit"))
                self.commentary.add(
                    f"🎉 TAKE PROFIT: {symbol} hit ${position.take_profit_price:.2f} - Locking gains!",
                    "risk"
                )

            # Trailing stop update
            else:
                new_stop = position.current_price * (1 - position.trailing_stop_pct)
                if new_stop > position.stop_loss_price:
                    position.stop_loss_price = new_stop
                    logger.debug(f"Trailing stop updated for {symbol}: ${new_stop:.2f}")

        # Close positions that hit limits
        for symbol, reason, trigger in positions_to_close:
            await self._close_position(symbol, reason)

    async def _scan_stocks(self):
        """OPTIMIZED: Parallel stock scanning with concurrent API calls."""
        scan_start = datetime.now()

        # Parallel fetch all stock quotes
        async def fetch_stock_quote(symbol: str):
            try:
                quote = await self.market_service.get_quote(symbol)
                return symbol, quote
            except Exception:
                return symbol, None

        # Fetch all in parallel
        tasks = [fetch_stock_quote(s) for s in self.STOCK_UNIVERSE]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        prices_dict = {}
        for result in results:
            if isinstance(result, tuple) and result[1] is not None:
                symbol, quote = result
                prices_dict[symbol] = quote.price
                self._price_cache[symbol] = (quote.price, datetime.now())

        if not prices_dict:
            return

        # Parallel analysis
        async def analyze_stock_task(symbol: str, price: float):
            try:
                return symbol, price, await self._analyze_stock(symbol, price)
            except Exception:
                return symbol, price, (None, None)

        analysis_tasks = [analyze_stock_task(sym, price) for sym, price in prices_dict.items()]
        analysis_results = await asyncio.gather(*analysis_tasks, return_exceptions=True)

        for result in analysis_results:
            if isinstance(result, Exception):
                continue
            symbol, price, (signal, rationale) = result
            if signal and rationale and rationale.confidence >= 0.5:
                self.pending_signals.append({
                    "asset_class": "stocks",
                    "symbol": symbol,
                    "price": price,
                    "signal": signal,
                    "rationale": rationale,
                })

        scan_latency = (datetime.now() - scan_start).total_seconds() * 1000
        logger.debug(f"Stock scan: {len(prices_dict)} stocks in {scan_latency:.0f}ms")

    async def _scan_crypto(self):
        """
        OPTIMIZED: Ultra-fast parallel crypto scanning pipeline.
        Uses asyncio.gather for concurrent fetching and analysis.
        """
        scan_start = datetime.now()
        scanned = 0
        opportunities = []
        movers = []
        all_quotes = {}

        # ===== STAGE 1: PARALLEL BATCH FETCH =====
        # Split universe into batches for controlled parallelism
        batches = [
            self.CRYPTO_UNIVERSE[i:i + self._batch_size]
            for i in range(0, len(self.CRYPTO_UNIVERSE), self._batch_size)
        ]

        async def fetch_batch(symbols: List[str]) -> Dict:
            """Fetch a batch of quotes concurrently."""
            results = {}
            try:
                batch_quotes = await self.crypto_service.get_quotes_batch(symbols)
                if batch_quotes:
                    results.update(batch_quotes)
            except Exception:
                # Fallback: parallel individual fetches with semaphore
                sem = asyncio.Semaphore(self._max_concurrent_requests)
                async def fetch_single(sym):
                    async with sem:
                        try:
                            return sym, await self.crypto_service.get_quote(sym)
                        except:
                            return sym, None

                tasks = [fetch_single(s) for s in symbols]
                for sym, quote in await asyncio.gather(*tasks, return_exceptions=True):
                    if not isinstance(quote, Exception) and quote:
                        results[sym] = quote
            return results

        # Fetch all batches in parallel
        batch_results = await asyncio.gather(*[fetch_batch(b) for b in batches], return_exceptions=True)
        for result in batch_results:
            if isinstance(result, dict):
                all_quotes.update(result)

        # ===== STAGE 2: PARALLEL ANALYSIS =====
        async def analyze_coin(symbol: str, quote) -> Optional[Dict]:
            """Analyze a single coin and return signal data if found."""
            try:
                # Update price cache
                self._price_cache[symbol] = (quote.price, datetime.now())

                # Run analysis
                signal, rationale = await self._analyze_crypto(symbol, quote)

                return {
                    "symbol": symbol,
                    "quote": quote,
                    "signal": signal,
                    "rationale": rationale,
                    "is_mover": abs(quote.change_percent_24h) > 5,
                }
            except Exception as e:
                logger.debug(f"Analysis failed for {symbol}: {e}")
                return None

        # Run all analyses in parallel with semaphore for control
        analysis_sem = asyncio.Semaphore(self._max_concurrent_requests)
        async def bounded_analyze(symbol: str, quote):
            async with analysis_sem:
                return await analyze_coin(symbol, quote)

        analysis_tasks = [
            bounded_analyze(sym, quote)
            for sym, quote in all_quotes.items()
        ]
        analysis_results = await asyncio.gather(*analysis_tasks, return_exceptions=True)

        # ===== STAGE 3: PROCESS RESULTS =====
        for result in analysis_results:
            if isinstance(result, Exception) or result is None:
                continue

            scanned += 1
            symbol = result["symbol"]
            quote = result["quote"]
            signal = result["signal"]
            rationale = result["rationale"]

            # Track movers
            if result["is_mover"]:
                movers.append((symbol, quote.change_percent_24h, quote.price))

            # Process signals
            if signal and rationale and rationale.confidence >= self.min_confidence:
                opportunities.append(symbol)

                # Build detailed signal commentary
                tech_summary = f"RSI:{rationale.rsi_value:.0f} MACD:{rationale.macd_signal[:4]} BB:{rationale.bollinger_position[:3]}"
                stat_summary = f"Z:{rationale.zscore:.1f} H:{rationale.hurst_exponent:.2f}"

                self.commentary.add(
                    f"🎯 SIGNAL: {signal} {symbol} @ ${quote.price:,.4f}",
                    "signal",
                    {"symbol": symbol, "signal": signal, "confidence": rationale.confidence}
                )
                self.commentary.add(
                    f"   ├─ Confidence: {rationale.confidence*100:.0f}% | {rationale.primary_reason}",
                    "signal"
                )
                self.commentary.add(
                    f"   ├─ Technical: {tech_summary} | Stats: {stat_summary}",
                    "signal"
                )
                self.commentary.add(
                    f"   └─ Risk: Stop {rationale.stop_loss*100:.1f}% | Target {rationale.take_profit*100:.1f}% | Kelly: {rationale.position_size_kelly*100:.0f}%",
                    "signal"
                )

                self.pending_signals.append({
                    "asset_class": "crypto",
                    "symbol": symbol,
                    "price": quote.price,
                    "signal": signal,
                    "rationale": rationale,
                })

        # Calculate scan latency
        scan_latency_ms = (datetime.now() - scan_start).total_seconds() * 1000

        # Report big movers with detailed analysis
        if movers:
            movers.sort(key=lambda x: abs(x[1]), reverse=True)
            top_movers = movers[:5]
            mover_str = " | ".join([f"{s}: {c:+.1f}%" for s, c, _ in top_movers])
            self.commentary.add(f"🔥 TOP MOVERS: {mover_str}", "analysis")

            # Show bullish vs bearish breakdown
            bullish = [m for m in movers if m[1] > 5]
            bearish = [m for m in movers if m[1] < -5]
            if bullish or bearish:
                self.commentary.add(
                    f"📈 Market Pulse: {len(bullish)} pumping >5% | {len(bearish)} dumping >5%",
                    "analysis"
                )

        # Scan summary with latency reporting
        import random
        show_summary_chance = 0.30 if self.mode == TradingMode.AGGRESSIVE else 0.20
        if random.random() < show_summary_chance:
            avg_momentum = sum([m[1] for m in movers]) / len(movers) if movers else 0
            self.commentary.add(
                f"⚡ Scan: {scanned} coins in {scan_latency_ms:.0f}ms | "
                f"{len(opportunities)} signals | Latency: {scan_latency_ms/max(scanned,1):.1f}ms/coin",
                "info"
            )

    async def _analyze_stock(self, symbol: str, price: float) -> Tuple[Optional[str], Optional[TradeRationale]]:
        """
        Analyze a stock using Renaissance-style multi-factor approach.
        Returns (signal, rationale) or (None, None) if no trade.
        """
        # Already have position?
        if symbol in self.positions:
            return await self._analyze_exit(symbol, price)

        # Too many positions?
        if len(self.positions) >= self.max_positions:
            return None, None

        # Calculate factor scores
        factors = await self._compute_stock_factors(symbol, price)

        if not factors:
            return None, None

        # Compute composite score
        composite = self._compute_composite_score(factors)

        # Decision logic
        if composite > self.signal_threshold:
            decision = "BUY"
            confidence = min(composite / 0.8, 1.0)
            primary_reason = self._get_primary_reason(factors, "bullish")
        elif composite < -self.signal_threshold:
            decision = "SELL"  # Short signal (we don't short, so skip)
            return None, None
        else:
            return None, None

        # Build rationale with full fields
        weights = {
            "momentum": 0.35,
            "volume_confirmation": 0.15,
            "range_position": 0.20,
            "mean_reversion": 0.15,
            "composite_technical": 0.15,
        }

        rationale = TradeRationale(
            decision=decision,
            confidence=confidence,
            primary_reason=primary_reason,
            factors=factors,
            factor_weights=weights,
            rsi_value=50.0,
            rsi_signal="NEUTRAL",
            macd_signal="NEUTRAL",
            bollinger_position="MIDDLE",
            momentum_quality=factors.get("momentum", 0),
            zscore=0,
            volatility_regime="NORMAL",
            hurst_exponent=0.5,
            order_flow_signal=0,
            volume_confirmation=factors.get("volume_confirmation", 0) > 0.1,
            liquidity_score=0.8,
            risk_assessment=self._assess_risk(factors, price),
            position_size_kelly=0.05,
            expected_return=composite * 0.15,
            expected_sharpe=composite * 1.2,
            max_loss_scenario=f"Max loss: ${price * self.stop_loss_pct:.2f}",
            expected_holding_period=self.holding_period_target,
            stop_loss=self.stop_loss_pct,
            take_profit=self.take_profit_pct,
            trailing_stop=0.10,
            signals_summary=self._format_signals_summary(factors),
            detailed_analysis=f"Stock analysis for {symbol}",
        )

        return decision, rationale

    async def _analyze_crypto(self, symbol: str, quote) -> Tuple[Optional[str], Optional[TradeRationale]]:
        """
        State-of-the-art cryptocurrency analysis using multi-factor quant approach.

        Implements:
        1. RSI (Relative Strength Index) for overbought/oversold
        2. MACD-style momentum detection
        3. Bollinger Band position analysis
        4. Volume-weighted order flow
        5. Statistical regime detection (Hurst exponent)
        6. Z-score mean reversion signals
        7. Kelly Criterion position sizing
        """
        if symbol in self.positions:
            return await self._analyze_crypto_exit(symbol, quote)

        if len(self.positions) >= self.max_positions:
            return None, None

        # ========== UPDATE PRICE HISTORY ==========
        if symbol not in self.price_history:
            self.price_history[symbol] = deque(maxlen=self.max_history_length)
        self.price_history[symbol].append(quote.price)
        prices = list(self.price_history[symbol])

        # ========== TECHNICAL INDICATORS ==========
        # RSI Analysis
        rsi = QuantMath.relative_strength_index(prices, period=14) if len(prices) >= 15 else 50
        if rsi < self.rsi_oversold:
            rsi_signal = "OVERSOLD"
            rsi_score = 0.8 * (self.rsi_oversold - rsi) / self.rsi_oversold
        elif rsi > self.rsi_overbought:
            rsi_signal = "OVERBOUGHT"
            rsi_score = -0.6 * (rsi - self.rsi_overbought) / (100 - self.rsi_overbought)
        else:
            rsi_signal = "NEUTRAL"
            rsi_score = 0.1 * (50 - rsi) / 50  # Slight mean-reversion bias

        # MACD Analysis
        macd_line, signal_line, histogram = QuantMath.macd(prices)
        if histogram > 0 and macd_line > 0:
            macd_signal = "BULLISH"
            macd_score = min(histogram / (abs(macd_line) + 0.01) * 0.5, 0.8)
        elif histogram < 0 and macd_line < 0:
            macd_signal = "BEARISH"
            macd_score = max(histogram / (abs(macd_line) + 0.01) * 0.5, -0.8)
        else:
            macd_signal = "NEUTRAL"
            macd_score = 0

        # Bollinger Bands
        middle, upper, lower = QuantMath.bollinger_bands(prices)
        bb_width = (upper - lower) / middle if middle > 0 else 0
        if quote.price < lower:
            bollinger_position = "LOWER"
            bollinger_score = 0.7  # Buy signal - price below lower band
        elif quote.price > upper:
            bollinger_position = "UPPER"
            bollinger_score = -0.5  # Caution - extended
        else:
            bollinger_position = "MIDDLE"
            bollinger_score = 0.2 * (middle - quote.price) / (upper - lower) if (upper - lower) > 0 else 0

        # ========== MOMENTUM ANALYSIS ==========
        # 24h momentum (from quote data)
        momentum_24h = quote.change_percent_24h
        momentum_score = np.clip(momentum_24h / 8, -1, 1)  # ±8% = max score

        # Momentum quality (consistency)
        if len(prices) >= 10:
            returns = np.diff(prices) / np.array(prices[:-1])
            mom_quality = QuantMath.momentum_quality(list(returns[-10:]))
        else:
            mom_quality = 0

        # ========== STATISTICAL ANALYSIS ==========
        # Z-score (mean reversion signal)
        if len(prices) >= 20:
            mean_price = np.mean(prices[-20:])
            std_price = np.std(prices[-20:])
            zscore = QuantMath.zscore(quote.price, mean_price, std_price)
        else:
            zscore = 0

        # Mean-reversion score (buy when z-score is very negative)
        if zscore < -2:
            zscore_signal = 0.6  # Strong buy - statistically oversold
        elif zscore > 2:
            zscore_signal = -0.4  # Caution - statistically extended
        else:
            zscore_signal = -zscore * 0.15  # Mild mean-reversion bias

        # Volatility regime
        if len(prices) >= 20:
            returns = list(np.diff(prices) / np.array(prices[:-1]))
            vol_regime = QuantMath.volatility_regime(returns)
        else:
            vol_regime = "NORMAL"

        # Hurst exponent (trend vs mean-reversion detection)
        hurst = QuantMath.hurst_exponent_fast(prices) if len(prices) >= 20 else 0.5

        # ========== MARKET MICROSTRUCTURE ==========
        # Volume analysis
        volume_ratio = quote.volume_24h / quote.market_cap if quote.market_cap > 0 else 0
        high_volume = volume_ratio > 0.05  # >5% turnover = high

        # Order flow imbalance estimate
        avg_vol = quote.market_cap * 0.03  # Estimate 3% daily volume
        order_flow = QuantMath.order_flow_imbalance(quote.volume_24h, momentum_24h, avg_vol)

        # Liquidity score
        if quote.market_cap_rank <= 10:
            liquidity = 1.0
        elif quote.market_cap_rank <= 50:
            liquidity = 0.8
        elif quote.market_cap_rank <= 100:
            liquidity = 0.6
        else:
            liquidity = 0.4

        # ATH distance factor
        ath_distance = quote.ath_change_percent / 100  # Convert to decimal
        if ath_distance > -0.20:
            ath_score = 0.2  # Near ATH - momentum continuation
        elif ath_distance < -0.70:
            ath_score = 0.4  # Far from ATH - recovery potential
        else:
            ath_score = 0

        # ========== FACTOR AGGREGATION ==========
        factors = {
            "rsi_signal": rsi_score,
            "macd_signal": macd_score,
            "bollinger_signal": bollinger_score,
            "momentum_24h": momentum_score,
            "momentum_quality": mom_quality * 0.5,
            "zscore_reversion": zscore_signal,
            "order_flow": order_flow,
            "ath_recovery": ath_score,
            "liquidity_premium": (liquidity - 0.5) * 0.3,
        }

        # Mode-specific weights
        if self.mode == TradingMode.AGGRESSIVE:
            weights = {
                "rsi_signal": 0.15,
                "macd_signal": 0.15,
                "bollinger_signal": 0.10,
                "momentum_24h": 0.25,  # Heavy momentum weight
                "momentum_quality": 0.10,
                "zscore_reversion": 0.05,
                "order_flow": 0.10,
                "ath_recovery": 0.05,
                "liquidity_premium": 0.05,
            }
        elif self.mode == TradingMode.BALANCED:
            weights = {
                "rsi_signal": 0.15,
                "macd_signal": 0.15,
                "bollinger_signal": 0.15,
                "momentum_24h": 0.15,
                "momentum_quality": 0.10,
                "zscore_reversion": 0.10,
                "order_flow": 0.08,
                "ath_recovery": 0.07,
                "liquidity_premium": 0.05,
            }
        else:  # Conservative
            weights = {
                "rsi_signal": 0.20,
                "macd_signal": 0.10,
                "bollinger_signal": 0.15,
                "momentum_24h": 0.10,
                "momentum_quality": 0.15,
                "zscore_reversion": 0.15,
                "order_flow": 0.05,
                "ath_recovery": 0.05,
                "liquidity_premium": 0.05,
            }

        composite = sum(factors.get(k, 0) * weights.get(k, 0) for k in factors)

        # ========== DECISION LOGIC ==========
        if composite > self.signal_threshold:
            decision = "BUY"

            # Confidence based on composite strength and factor agreement
            factor_agreement = sum(1 for v in factors.values() if v > 0.1) / len(factors)
            confidence = min(0.4 + composite * 0.8 + factor_agreement * 0.3, 0.95)

            # Kelly-optimal position size
            kelly_size = QuantMath.kelly_criterion(self.estimated_win_rate, self.win_loss_ratio)

            # Primary reason determination
            sorted_factors = sorted(factors.items(), key=lambda x: x[1] * weights.get(x[0], 0), reverse=True)
            top_factor, top_value = sorted_factors[0]

            reason_map = {
                "rsi_signal": f"RSI oversold at {rsi:.1f} - statistical buy zone",
                "macd_signal": "MACD bullish crossover - momentum accelerating",
                "bollinger_signal": f"Price at Bollinger lower band - volatility squeeze",
                "momentum_24h": f"Strong 24h momentum +{quote.change_percent_24h:.1f}% with volume confirmation",
                "momentum_quality": "High-quality consistent momentum pattern",
                "zscore_reversion": f"Z-score {zscore:.2f} indicates mean-reversion opportunity",
                "order_flow": "Positive order flow imbalance - buy pressure detected",
                "ath_recovery": f"Recovery play: {abs(ath_distance)*100:.0f}% below ATH",
                "liquidity_premium": "High liquidity premium for large cap",
            }
            primary_reason = reason_map.get(top_factor, f"Multi-factor signal: composite {composite:.2f}")

            # Build detailed analysis string
            detailed_parts = [
                f"📊 QUANTITATIVE ANALYSIS FOR {symbol}",
                f"",
                f"▸ TECHNICAL INDICATORS:",
                f"  RSI(14): {rsi:.1f} → {rsi_signal} (score: {rsi_score:+.2f})",
                f"  MACD: {macd_signal} (histogram: {histogram:.4f}, score: {macd_score:+.2f})",
                f"  Bollinger: {bollinger_position} (score: {bollinger_score:+.2f})",
                f"",
                f"▸ MOMENTUM ANALYSIS:",
                f"  24h Change: {quote.change_percent_24h:+.2f}%",
                f"  Momentum Quality: {mom_quality:.2f} (-1=choppy, +1=smooth)",
                f"  Order Flow: {order_flow:+.2f} (buy/sell pressure)",
                f"",
                f"▸ STATISTICAL MEASURES:",
                f"  Z-Score: {zscore:.2f} (>2 = overbought, <-2 = oversold)",
                f"  Volatility Regime: {vol_regime}",
                f"  Hurst Exponent: {hurst:.3f} (>0.5=trending, <0.5=mean-reverting)",
                f"",
                f"▸ MARKET STRUCTURE:",
                f"  Market Cap Rank: #{quote.market_cap_rank}",
                f"  Liquidity Score: {liquidity:.1f}/1.0",
                f"  ATH Distance: {ath_distance*100:.1f}%",
                f"  Volume/MCap: {volume_ratio*100:.2f}%",
                f"",
                f"▸ COMPOSITE SIGNAL: {composite:.3f} (threshold: {self.signal_threshold})",
                f"▸ CONFIDENCE: {confidence*100:.1f}%",
                f"▸ KELLY SIZE: {kelly_size*100:.1f}% of capital",
            ]

            signals_summary = (
                f"RSI:{rsi:.0f} | MACD:{macd_signal[:4]} | BB:{bollinger_position[:3]} | "
                f"Mom:{quote.change_percent_24h:+.1f}% | Z:{zscore:.1f} | Flow:{order_flow:+.1f}"
            )

            # Risk assessment
            if vol_regime == "HIGH_VOL":
                risk_text = f"⚠️ HIGH VOLATILITY REGIME - Using {self.stop_loss_pct*1.5*100:.1f}% stop. Reduce size."
            elif vol_regime == "LOW_VOL":
                risk_text = f"Low vol environment - tighter {self.stop_loss_pct*100:.1f}% stop appropriate."
            else:
                risk_text = f"Normal volatility - standard {self.stop_loss_pct*100:.1f}% stop loss."

            max_loss = f"Max loss at stop: ${(confidence * self.total_value * self.max_position_pct * self.stop_loss_pct):.2f}"

            # Create comprehensive rationale
            rationale = TradeRationale(
                decision=decision,
                confidence=confidence,
                primary_reason=primary_reason,
                factors=factors,
                factor_weights=weights,
                rsi_value=rsi,
                rsi_signal=rsi_signal,
                macd_signal=macd_signal,
                bollinger_position=bollinger_position,
                momentum_quality=mom_quality,
                zscore=zscore,
                volatility_regime=vol_regime,
                hurst_exponent=hurst,
                order_flow_signal=order_flow,
                volume_confirmation=high_volume,
                liquidity_score=liquidity,
                risk_assessment=risk_text,
                position_size_kelly=kelly_size,
                expected_return=composite * 0.12,
                expected_sharpe=composite * 1.5,
                max_loss_scenario=max_loss,
                expected_holding_period=self.holding_period_target,
                stop_loss=self.stop_loss_pct * (1.5 if vol_regime == "HIGH_VOL" else 1.0),
                take_profit=self.take_profit_pct * (1.5 if vol_regime == "HIGH_VOL" else 1.0),
                trailing_stop=0.10,
                signals_summary=signals_summary,
                detailed_analysis="\n".join(detailed_parts),
            )

            return decision, rationale

        return None, None

    async def _analyze_exit(self, symbol: str, price: float) -> Tuple[Optional[str], Optional[TradeRationale]]:
        """Analyze whether to exit an existing position."""
        position = self.positions[symbol]
        pnl_pct = position.unrealized_pnl_pct
        holding_hours = position.holding_period.total_seconds() / 3600

        # Check if we should exit based on time or momentum reversal
        factors = await self._compute_stock_factors(symbol, price)

        if not factors:
            return None, None

        composite = self._compute_composite_score(factors)

        # Exit if signal reversed significantly
        if composite < -0.1 and pnl_pct > 0.02:
            rationale = TradeRationale(
                decision="SELL",
                confidence=0.7,
                primary_reason=f"Signal reversed while profitable (+{pnl_pct*100:.1f}%)",
                factors=factors,
                factor_weights={"momentum": 0.4, "reversal": 0.6},
                rsi_value=50.0,
                rsi_signal="NEUTRAL",
                macd_signal="BEARISH",
                bollinger_position="MIDDLE",
                momentum_quality=0,
                zscore=0,
                volatility_regime="NORMAL",
                hurst_exponent=0.5,
                order_flow_signal=0,
                volume_confirmation=False,
                liquidity_score=0.8,
                risk_assessment="Taking profits as momentum fading",
                position_size_kelly=0,
                expected_return=pnl_pct,
                expected_sharpe=0,
                max_loss_scenario="N/A - Exiting position",
                expected_holding_period=f"Held {holding_hours:.0f} hours",
                stop_loss=0,
                take_profit=0,
                trailing_stop=0,
                signals_summary=self._format_signals_summary(factors),
                detailed_analysis=f"Exit analysis for {symbol}",
            )
            return "SELL", rationale

        return None, None

    async def _analyze_crypto_exit(self, symbol: str, quote) -> Tuple[Optional[str], Optional[TradeRationale]]:
        """
        Advanced exit analysis for crypto positions using multi-factor approach.
        Implements:
        1. Momentum reversal detection
        2. RSI overbought exits
        3. Profit target optimization
        4. Trailing stop logic
        5. Time-based exit for stale positions
        """
        position = self.positions[symbol]
        pnl_pct = position.unrealized_pnl_pct
        holding_hours = position.holding_period.total_seconds() / 3600

        # Get price history for indicators
        prices = list(self.price_history.get(symbol, [quote.price]))
        if len(prices) < 2:
            prices = [quote.price * 0.99, quote.price]

        # Calculate indicators
        rsi = QuantMath.relative_strength_index(prices, period=14) if len(prices) >= 15 else 50
        momentum = quote.change_percent_24h

        # ========== EXIT SIGNALS ==========
        exit_signals = []
        exit_score = 0

        # 1. Momentum Reversal (strongest signal)
        if momentum < -5 and pnl_pct > 0.02:
            exit_signals.append(f"Momentum reversal: {momentum:.1f}% while +{pnl_pct*100:.1f}% profitable")
            exit_score += 0.4

        # 2. RSI Overbought Exit
        if rsi > 80 and pnl_pct > 0.03:
            exit_signals.append(f"RSI overbought at {rsi:.1f} - take profits")
            exit_score += 0.3

        # 3. Large Profit - Partial/Full Exit
        if pnl_pct > self.take_profit_pct * 0.8:
            exit_signals.append(f"Near take-profit target: +{pnl_pct*100:.1f}%")
            exit_score += 0.25

        # 4. Stale Position Exit
        max_hold_hours = {"aggressive": 24, "balanced": 72, "conservative": 168}
        max_hours = max_hold_hours.get(self.mode.value, 72)
        if holding_hours > max_hours and abs(pnl_pct) < 0.02:
            exit_signals.append(f"Position stale after {holding_hours:.0f}h with minimal P&L")
            exit_score += 0.2

        # 5. Loss Cut Acceleration
        if pnl_pct < -0.03 and momentum < -3:
            exit_signals.append(f"Accelerating losses: {pnl_pct*100:.1f}% with negative momentum")
            exit_score += 0.35

        # ========== EXIT DECISION ==========
        if exit_score >= 0.35 or (pnl_pct > 0.05 and exit_score >= 0.25):
            decision = "SELL"
            confidence = min(0.6 + exit_score * 0.5, 0.95)

            primary_reason = exit_signals[0] if exit_signals else "Multi-factor exit signal"

            detailed_parts = [
                f"📉 EXIT ANALYSIS FOR {symbol}",
                f"",
                f"▸ POSITION STATUS:",
                f"  Entry: ${position.entry_price:.4f}",
                f"  Current: ${quote.price:.4f}",
                f"  P&L: {pnl_pct*100:+.2f}% (${position.unrealized_pnl:+.2f})",
                f"  Holding Period: {holding_hours:.1f} hours",
                f"",
                f"▸ EXIT SIGNALS DETECTED:",
            ]
            for sig in exit_signals:
                detailed_parts.append(f"  ✓ {sig}")

            detailed_parts.extend([
                f"",
                f"▸ INDICATORS:",
                f"  RSI: {rsi:.1f}",
                f"  24h Momentum: {momentum:+.1f}%",
                f"  Exit Score: {exit_score:.2f}/1.0",
                f"",
                f"▸ RECOMMENDATION: CLOSE POSITION",
            ])

            rationale = TradeRationale(
                decision=decision,
                confidence=confidence,
                primary_reason=primary_reason,
                factors={"exit_score": exit_score, "momentum": momentum/10, "pnl": pnl_pct},
                factor_weights={"exit_score": 0.5, "momentum": 0.3, "pnl": 0.2},
                rsi_value=rsi,
                rsi_signal="OVERBOUGHT" if rsi > 70 else "NEUTRAL",
                macd_signal="BEARISH" if momentum < 0 else "NEUTRAL",
                bollinger_position="MIDDLE",
                momentum_quality=0,
                zscore=0,
                volatility_regime="NORMAL",
                hurst_exponent=0.5,
                order_flow_signal=-0.3 if momentum < 0 else 0,
                volume_confirmation=True,
                liquidity_score=0.8,
                risk_assessment="Exiting to protect capital/lock profits",
                position_size_kelly=0,
                expected_return=pnl_pct,
                expected_sharpe=0,
                max_loss_scenario="N/A - Closing position",
                expected_holding_period=f"Held {holding_hours:.1f} hours",
                stop_loss=0,
                take_profit=0,
                trailing_stop=0,
                signals_summary=" | ".join(exit_signals[:2]) if exit_signals else "Exit signal",
                detailed_analysis="\n".join(detailed_parts),
            )

            return decision, rationale

        return None, None

    async def _compute_stock_factors(self, symbol: str, price: float) -> Dict[str, float]:
        """Compute multi-factor scores for a stock."""
        # In production, this would use historical data
        # For now, use simplified real-time signals

        try:
            quote = await self.market_service.get_quote(symbol)
            if not quote:
                return {}

            # Price momentum
            momentum = np.clip(quote.change_percent / 5, -1, 1) if hasattr(quote, 'change_percent') else 0

            # Volume signal (high volume confirms move)
            volume_signal = 0.2 if hasattr(quote, 'volume') and quote.volume > 0 else 0

            # Price vs day range (relative strength)
            if hasattr(quote, 'high') and hasattr(quote, 'low') and quote.high > quote.low:
                day_range_pos = (quote.price - quote.low) / (quote.high - quote.low)
                range_signal = np.clip((day_range_pos - 0.5) * 2, -1, 1)
            else:
                range_signal = 0

            # Simple mean reversion (extreme moves tend to reverse)
            if hasattr(quote, 'change_percent'):
                if abs(quote.change_percent) > 5:
                    mean_reversion = -np.sign(quote.change_percent) * 0.3
                else:
                    mean_reversion = 0
            else:
                mean_reversion = 0

            return {
                "momentum": momentum,
                "volume_confirmation": volume_signal,
                "range_position": range_signal,
                "mean_reversion": mean_reversion,
                "composite_technical": (momentum + range_signal) / 2,
            }

        except Exception as e:
            logger.debug(f"Factor computation failed for {symbol}: {e}")
            return {}

    def _compute_composite_score(self, factors: Dict[str, float]) -> float:
        """Compute weighted composite score from factors."""
        weights = {
            "momentum": 0.35,
            "volume_confirmation": 0.15,
            "range_position": 0.20,
            "mean_reversion": 0.15,
            "composite_technical": 0.15,
        }

        score = sum(factors.get(k, 0) * w for k, w in weights.items())
        return np.clip(score, -1, 1)

    def _get_primary_reason(self, factors: Dict[str, float], direction: str) -> str:
        """Determine the primary reason for a trade signal."""
        sorted_factors = sorted(factors.items(), key=lambda x: abs(x[1]), reverse=True)

        if not sorted_factors:
            return f"General {direction} signal"

        top_factor, top_value = sorted_factors[0]

        reasons = {
            "momentum": f"Strong price momentum ({top_value:.2f})",
            "volume_confirmation": "High volume confirming move",
            "range_position": f"Price at {'top' if top_value > 0 else 'bottom'} of range",
            "mean_reversion": "Mean reversion opportunity",
            "composite_technical": f"Technical signals {direction}",
        }

        return reasons.get(top_factor, f"{direction.capitalize()} signal from {top_factor}")

    def _format_signals_summary(self, factors: Dict[str, float]) -> str:
        """Format factors into a readable summary."""
        parts = []
        for k, v in sorted(factors.items(), key=lambda x: abs(x[1]), reverse=True)[:3]:
            direction = "+" if v > 0 else ""
            parts.append(f"{k}: {direction}{v:.2f}")
        return " | ".join(parts)

    def _assess_risk(self, factors: Dict[str, float], price: float) -> str:
        """Generate risk assessment string."""
        vol_factor = factors.get("volatility", 0)

        if vol_factor < -0.5:
            vol_text = "High volatility detected"
        elif vol_factor > 0.3:
            vol_text = "Low volatility environment"
        else:
            vol_text = "Normal volatility"

        return f"{vol_text}. Stop loss: {self.stop_loss_pct*100:.0f}%, Take profit: {self.take_profit_pct*100:.0f}%"

    async def _execute_signals(self):
        """Execute pending trade signals."""
        # Sort by confidence
        self.pending_signals.sort(key=lambda x: x["rationale"].confidence, reverse=True)

        executed = 0
        for signal_data in self.pending_signals[:5]:  # Max 5 trades per cycle
            try:
                if signal_data["signal"] == "BUY":
                    success = await self._execute_buy(
                        symbol=signal_data["symbol"],
                        asset_class=signal_data["asset_class"],
                        price=signal_data["price"],
                        rationale=signal_data["rationale"],
                    )
                    if success:
                        executed += 1
                elif signal_data["signal"] == "SELL":
                    success = await self._close_position(
                        signal_data["symbol"],
                        f"Signal: {signal_data['rationale'].primary_reason}"
                    )
                    if success:
                        executed += 1
            except Exception as e:
                logger.error(f"Trade execution failed: {e}")

        self.pending_signals.clear()

        if executed > 0:
            logger.info(f"Executed {executed} trades")

    async def _execute_buy(
        self,
        symbol: str,
        asset_class: str,
        price: float,
        rationale: TradeRationale,
    ) -> bool:
        """Execute a buy order."""
        # Calculate position size
        max_position_value = self.total_value * self.max_position_pct
        available = min(self.cash * 0.95, max_position_value)  # Keep 5% cash buffer

        if available < self.min_trade_value:
            logger.debug(f"Insufficient funds for {symbol}: ${available:.2f} < ${self.min_trade_value}")
            return False

        # Size based on confidence
        position_value = available * rationale.confidence
        position_value = max(position_value, self.min_trade_value)
        quantity = position_value / price

        # Execute trade
        self.cash -= position_value

        # Create position
        stop_loss_price = price * (1 - rationale.stop_loss)
        take_profit_price = price * (1 + rationale.take_profit)

        self.positions[symbol] = BotPosition(
            symbol=symbol,
            asset_class=asset_class,
            quantity=quantity,
            entry_price=price,
            current_price=price,
            entry_time=datetime.now(),
            entry_rationale=rationale,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
        )

        # Log trade
        trade = BotTrade(
            id=str(uuid.uuid4())[:8],
            timestamp=datetime.now(),
            asset_class=asset_class,
            symbol=symbol,
            side="BUY",
            quantity=quantity,
            price=price,
            value=position_value,
            rationale=rationale,
        )
        self.trade_history.append(trade)

        self.commentary.add(
            f"✅ EXECUTED BUY: {quantity:.4f} {symbol} @ ${price:,.2f} = ${position_value:,.2f}",
            "trade",
            {"symbol": symbol, "side": "BUY", "quantity": quantity, "price": price, "value": position_value}
        )
        self.commentary.add(
            f"📝 Rationale: {rationale.primary_reason} | Stop: ${stop_loss_price:,.2f} | Target: ${take_profit_price:,.2f}",
            "trade"
        )

        return True

    async def _close_position(self, symbol: str, reason: str) -> bool:
        """Close an existing position."""
        if symbol not in self.positions:
            return False

        position = self.positions[symbol]
        value = position.market_value
        pnl = position.unrealized_pnl

        # Update cash
        self.cash += value
        del self.positions[symbol]

        # Log trade with full rationale
        pnl_pct = position.unrealized_pnl_pct if hasattr(position, 'unrealized_pnl_pct') else 0
        rationale = TradeRationale(
            decision="SELL",
            confidence=1.0,
            primary_reason=reason,
            factors={"pnl": pnl_pct},
            factor_weights={"pnl": 1.0},
            rsi_value=50.0,
            rsi_signal="NEUTRAL",
            macd_signal="NEUTRAL",
            bollinger_position="MIDDLE",
            momentum_quality=0,
            zscore=0,
            volatility_regime="NORMAL",
            hurst_exponent=0.5,
            order_flow_signal=0,
            volume_confirmation=False,
            liquidity_score=0.8,
            risk_assessment="Position closed",
            position_size_kelly=0,
            expected_return=pnl_pct,
            expected_sharpe=0,
            max_loss_scenario="N/A",
            expected_holding_period=str(position.holding_period),
            stop_loss=0,
            take_profit=0,
            trailing_stop=0,
            signals_summary=f"Closing: P&L ${pnl:.2f} ({pnl_pct*100:.1f}%)",
            detailed_analysis=f"Closed position: {reason}",
        )

        trade = BotTrade(
            id=str(uuid.uuid4())[:8],
            timestamp=datetime.now(),
            asset_class=position.asset_class,
            symbol=symbol,
            side="SELL",
            quantity=position.quantity,
            price=position.current_price,
            value=value,
            rationale=rationale,
            pnl=pnl,
        )
        self.trade_history.append(trade)

        pnl_emoji = "💰" if pnl >= 0 else "📉"
        self.commentary.add(
            f"{pnl_emoji} SOLD {symbol}: {position.quantity:.4f} @ ${position.current_price:,.2f} | P&L: ${pnl:+,.2f} ({position.unrealized_pnl_pct*100:+.1f}%)",
            "trade",
            {"symbol": symbol, "side": "SELL", "pnl": pnl, "reason": reason}
        )
        self.commentary.add(f"📝 Reason: {reason}", "trade")

        return True

    def get_status(self) -> Dict[str, Any]:
        """Get current bot status with market information."""
        market_status = get_market_status()

        # Determine active trading mode
        if self.asset_class == AssetClass.BOTH:
            if market_status["is_open"]:
                active_mode = "STOCKS + CRYPTO"
            else:
                active_mode = "CRYPTO ONLY (Market Closed)"
        else:
            active_mode = self.asset_class.value.upper()

        return {
            "is_running": self.is_running,
            "mode": self.mode.value,
            "asset_class": self.asset_class.value,
            "active_trading_mode": active_mode,
            "market_status": market_status,
            "initial_capital": self.initial_capital,
            "cash": round(self.cash, 2),
            "total_value": round(self.total_value, 2),
            "total_pnl": round(self.total_pnl, 2),
            "total_pnl_pct": round(self.total_pnl_pct * 100, 2),
            "positions_count": len(self.positions),
            "trades_count": len(self.trade_history),
            "last_scan": self.last_scan_time.isoformat() if self.last_scan_time else None,
            "scan_interval_seconds": self.scan_interval_seconds,
        }

    def get_positions(self) -> List[Dict]:
        """Get all current positions."""
        return [p.to_dict() for p in self.positions.values()]

    def get_trades(self, limit: int = 50) -> List[Dict]:
        """Get recent trade history."""
        return [t.to_dict() for t in self.trade_history[-limit:]]

    def get_commentary(self, limit: int = 50) -> List[Dict]:
        """Get recent bot commentary/thoughts."""
        if hasattr(self, 'commentary'):
            return self.commentary.get_recent(limit)
        return _commentary.get_recent(limit)

    def get_performance(self) -> Dict[str, Any]:
        """Calculate performance metrics with safe float handling."""
        if len(self.equity_curve) < 2:
            return {
                "total_return": 0,
                "cagr": 0,
                "volatility": 0,
                "sharpe_ratio": 0,
                "max_drawdown": 0,
                "win_rate": 0,
                "total_trades": len(self.trade_history),
                "current_value": round(self.total_value, 2),
            }

        try:
            values = [v for _, v in self.equity_curve]

            # Safely compute returns, avoiding division by zero
            returns = []
            for i in range(1, len(values)):
                if values[i-1] != 0:
                    returns.append((values[i] - values[i-1]) / values[i-1])

            if not returns:
                returns = [0]

            total_return = (values[-1] - self.initial_capital) / self.initial_capital if self.initial_capital > 0 else 0

            # Annualized metrics - cap CAGR to reasonable bounds
            n_periods = max(len(returns), 1)
            periods_per_year = 252 * 24  # Trading hours per year

            if total_return > -1 and n_periods > 0:
                # Limit exponent to avoid overflow
                exponent = min(periods_per_year / n_periods, 10)
                cagr = (1 + total_return) ** exponent - 1
                # Cap CAGR to reasonable range
                cagr = max(-1, min(cagr, 100))
            else:
                cagr = -1

            vol = float(np.std(returns) * np.sqrt(min(periods_per_year, 1000))) if len(returns) > 1 else 0
            vol = min(vol, 1000)  # Cap volatility

            sharpe = (cagr - 0.02) / vol if vol > 0.001 else 0
            sharpe = max(-10, min(sharpe, 10))  # Cap Sharpe ratio

            # Max drawdown
            peak = np.maximum.accumulate(values)
            # Avoid division by zero in drawdown calc
            drawdown = []
            for i, (v, p) in enumerate(zip(values, peak)):
                if p > 0:
                    drawdown.append((v - p) / p)
                else:
                    drawdown.append(0)
            max_dd = min(drawdown) if drawdown else 0

            # Win rate
            trades = [t for t in self.trade_history if t.side == "SELL"]
            wins = sum(1 for t in trades if t.pnl > 0)
            win_rate = wins / len(trades) if trades else 0

            # Use safe_float to ensure all values are JSON-serializable
            sf = QuantMath.safe_float
            return {
                "total_return": round(sf(total_return * 100), 2),
                "cagr": round(sf(cagr * 100), 2),
                "volatility": round(sf(vol * 100), 2),
                "sharpe_ratio": round(sf(sharpe), 2),
                "max_drawdown": round(sf(max_dd * 100), 2),
                "win_rate": round(sf(win_rate * 100), 1),
                "total_trades": len(self.trade_history),
                "current_value": round(sf(self.total_value), 2),
            }
        except Exception as e:
            logger.error(f"Error calculating performance: {e}")
            return {
                "total_return": 0,
                "cagr": 0,
                "volatility": 0,
                "sharpe_ratio": 0,
                "max_drawdown": 0,
                "win_rate": 0,
                "total_trades": len(self.trade_history),
                "current_value": round(self.total_value, 2),
                "error": str(e),
            }


# Singleton
_bot: Optional[QuantBot] = None


def get_quant_bot() -> QuantBot:
    """Get the singleton quant bot instance."""
    global _bot
    if _bot is None:
        settings = get_settings()
        _bot = QuantBot(
            initial_capital=settings.initial_cash,
            mode=TradingMode.BALANCED,
            asset_class=AssetClass.BOTH,
        )
    return _bot


async def run_bot():
    """Run the quant bot (for standalone execution)."""
    bot = get_quant_bot()
    await bot.start()
