"""
Autonomous Quant Trading Bot

Renaissance Technologies-style autonomous trading system that:
1. Runs continuously monitoring markets
2. Uses multi-factor signals (momentum, mean-reversion, statistical arbitrage)
3. Executes trades with full reasoning/rationale
4. Manages positions with dynamic risk controls
5. Supports both stocks and crypto

Paper trading only - for educational purposes.
"""

import asyncio
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta, time
from enum import Enum
import numpy as np
import pandas as pd
import logging
import uuid
import pytz

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(message)s', datefmt='%H:%M:%S')
import json


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
    """Detailed reasoning for a trade decision."""
    decision: str  # BUY, SELL, HOLD
    confidence: float  # 0-1
    primary_reason: str
    factors: Dict[str, float]
    signals_summary: str
    risk_assessment: str
    expected_return: float
    expected_holding_period: str
    stop_loss: float
    take_profit: float
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict:
        return {
            "decision": self.decision,
            "confidence": round(self.confidence, 3),
            "primary_reason": self.primary_reason,
            "factors": {k: round(v, 4) for k, v in self.factors.items()},
            "signals_summary": self.signals_summary,
            "risk_assessment": self.risk_assessment,
            "expected_return": f"{self.expected_return*100:.1f}%",
            "expected_holding_period": self.expected_holding_period,
            "stop_loss": f"{self.stop_loss*100:.1f}%",
            "take_profit": f"{self.take_profit*100:.1f}%",
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

    # Stock universe for trading
    STOCK_UNIVERSE = [
        "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "AMD",
        "JPM", "BAC", "GS", "V", "MA", "PYPL",
        "JNJ", "PFE", "UNH", "MRK", "ABBV",
        "XOM", "CVX", "COP",
        "HD", "LOW", "TGT", "COST", "WMT",
        "DIS", "NFLX", "CMCSA",
    ]

    # Crypto universe - Top 50+ cryptocurrencies by market cap
    CRYPTO_UNIVERSE = [
        # Top 10
        "BTC", "ETH", "BNB", "XRP", "SOL", "ADA", "DOGE", "TRX", "AVAX", "LINK",
        # 11-20
        "DOT", "MATIC", "SHIB", "TON", "LTC", "BCH", "UNI", "ATOM", "XLM", "ICP",
        # 21-30
        "ETC", "FIL", "APT", "NEAR", "IMX", "HBAR", "OP", "INJ", "VET", "MKR",
        # 31-40
        "ARB", "GRT", "AAVE", "ALGO", "RUNE", "FTM", "SAND", "MANA", "AXS", "SNX",
        # 41-50
        "LDO", "CRV", "EGLD", "THETA", "XTZ", "FLOW", "KAVA", "NEO", "IOTA", "ZEC",
        # 51-60 - More altcoins
        "CAKE", "1INCH", "COMP", "ENJ", "BAT", "CELO", "ZRX", "YFI", "SUSHI", "KSM",
        # 61-70 - DeFi & Layer 2
        "GMX", "DYDX", "STX", "SUI", "SEI", "TIA", "JUP", "PYTH", "WIF", "BONK",
        # 71-80 - Meme & New
        "PEPE", "FLOKI", "RNDR", "FET", "AGIX", "OCEAN", "TAO", "AR", "HNT", "QNT",
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

    def _get_scan_interval(self) -> int:
        """Get scan interval based on mode - fast for real-time trading."""
        if self.mode == TradingMode.AGGRESSIVE:
            return 3  # 3 seconds for HFT-style
        elif self.mode == TradingMode.BALANCED:
            return 5  # 5 seconds
        else:
            return 10  # 10 seconds for conservative

    def _configure_mode(self):
        """Configure bot based on trading mode."""
        if self.mode == TradingMode.AGGRESSIVE:
            self.stop_loss_pct = 0.03  # 3% stop
            self.take_profit_pct = 0.05  # 5% take profit
            self.signal_threshold = 0.15  # Lower threshold, more trades
            self.holding_period_target = "hours to 1 day"
        elif self.mode == TradingMode.BALANCED:
            self.stop_loss_pct = 0.06
            self.take_profit_pct = 0.12
            self.signal_threshold = 0.25
            self.holding_period_target = "1-5 days"
        else:  # Conservative
            self.stop_loss_pct = 0.08
            self.take_profit_pct = 0.20
            self.signal_threshold = 0.35
            self.holding_period_target = "1-4 weeks"

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
            f"🚀 QuantBot ACTIVATED | Capital: ${self.initial_capital:,.2f} | Mode: {self.mode.value.upper()} | Assets: {self.asset_class.value.upper()}",
            "market"
        )
        self.commentary.add(
            f"⚡ Scan frequency: every {self.scan_interval_seconds} seconds | Max positions: {self.max_positions}",
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
        self.last_scan_time = datetime.now()

        # Check market status
        market_status = get_market_status()
        market_open = market_status["is_open"]

        # Log cycle start every 10 cycles
        if cycle_count % 10 == 1:
            self.commentary.add(
                f"📊 Cycle #{cycle_count} | Portfolio: ${self.total_value:,.2f} | P&L: ${self.total_pnl:+,.2f} ({self.total_pnl_pct*100:+.2f}%)",
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
        """Update all position prices."""
        for symbol, position in self.positions.items():
            try:
                if position.asset_class == "stocks":
                    quote = await self.market_service.get_quote(symbol)
                    if quote:
                        position.current_price = quote.price
                else:  # crypto
                    quote = await self.crypto_service.get_quote(symbol)
                    if quote:
                        position.current_price = quote.price
            except Exception as e:
                logger.warning(f"Failed to update price for {symbol}: {e}")

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
        """Scan stock universe for trading opportunities."""
        logger.debug(f"Scanning {len(self.STOCK_UNIVERSE)} stocks...")

        # Get current prices for all stocks
        prices_dict = {}
        for symbol in self.STOCK_UNIVERSE:
            try:
                quote = await self.market_service.get_quote(symbol)
                if quote:
                    prices_dict[symbol] = quote.price
            except Exception:
                pass

        if not prices_dict:
            return

        # Generate signals
        for symbol, price in prices_dict.items():
            try:
                signal, rationale = await self._analyze_stock(symbol, price)
                if signal and rationale.confidence >= 0.5:
                    self.pending_signals.append({
                        "asset_class": "stocks",
                        "symbol": symbol,
                        "price": price,
                        "signal": signal,
                        "rationale": rationale,
                    })
            except Exception as e:
                logger.debug(f"Analysis failed for {symbol}: {e}")

    async def _scan_crypto(self):
        """Scan crypto universe for trading opportunities."""
        scanned = 0
        opportunities = []
        movers = []  # Track big movers

        # Batch fetch all quotes for efficiency
        try:
            quotes = await self.crypto_service.get_quotes_batch(self.CRYPTO_UNIVERSE)
        except Exception as e:
            logger.warning(f"Batch crypto fetch failed, falling back to individual: {e}")
            quotes = {}

        for symbol in self.CRYPTO_UNIVERSE:
            try:
                # Use batch result or fetch individually
                quote = quotes.get(symbol) if quotes else None
                if not quote:
                    quote = await self.crypto_service.get_quote(symbol)

                if quote:
                    scanned += 1
                    signal, rationale = await self._analyze_crypto(symbol, quote)

                    # Track big movers for summary
                    if abs(quote.change_percent_24h) > 5:
                        movers.append((symbol, quote.change_percent_24h, quote.price))

                    if signal and rationale.confidence >= 0.5:
                        opportunities.append(symbol)
                        self.commentary.add(
                            f"🎯 SIGNAL: {signal} {symbol} @ ${quote.price:,.2f} | Confidence: {rationale.confidence*100:.0f}% | {rationale.primary_reason}",
                            "signal",
                            {"symbol": symbol, "signal": signal, "confidence": rationale.confidence}
                        )
                        self.pending_signals.append({
                            "asset_class": "crypto",
                            "symbol": symbol,
                            "price": quote.price,
                            "signal": signal,
                            "rationale": rationale,
                        })
            except Exception as e:
                logger.debug(f"Crypto analysis failed for {symbol}: {e}")

        # Report big movers
        if movers:
            movers.sort(key=lambda x: abs(x[1]), reverse=True)
            top_movers = movers[:3]
            mover_str = " | ".join([f"{s}: {c:+.1f}%" for s, c, _ in top_movers])
            self.commentary.add(f"🔥 Top movers: {mover_str}", "analysis")

        # Scan summary
        import random
        if random.random() < 0.15:  # 15% of the time
            self.commentary.add(
                f"📡 Scanned {scanned}/{len(self.CRYPTO_UNIVERSE)} cryptos | {len(movers)} big movers | {len(opportunities)} signals",
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

        # Build rationale
        rationale = TradeRationale(
            decision=decision,
            confidence=confidence,
            primary_reason=primary_reason,
            factors=factors,
            signals_summary=self._format_signals_summary(factors),
            risk_assessment=self._assess_risk(factors, price),
            expected_return=composite * 0.15,  # Rough estimate
            expected_holding_period=self.holding_period_target,
            stop_loss=self.stop_loss_pct,
            take_profit=self.take_profit_pct,
        )

        return decision, rationale

    async def _analyze_crypto(self, symbol: str, quote) -> Tuple[Optional[str], Optional[TradeRationale]]:
        """Analyze cryptocurrency for trading opportunity."""
        if symbol in self.positions:
            return await self._analyze_crypto_exit(symbol, quote)

        if len(self.positions) >= self.max_positions:
            return None, None

        # Crypto-specific factors
        factors = {
            "momentum_24h": np.clip(quote.change_percent_24h / 10, -1, 1),
            "momentum_7d": 0,  # Would need historical data
            "volatility": -0.2,  # Crypto is high vol, slight negative
            "volume_signal": np.clip((quote.volume_24h / quote.market_cap - 0.05) * 10, -1, 1) if quote.market_cap > 0 else 0,
            "ath_distance": np.clip(quote.ath_change_percent / 50, -1, 0),  # How far from ATH
            "market_cap_rank": -np.clip((quote.market_cap_rank - 10) / 20, 0, 0.5),  # Prefer top coins
        }

        # Weight the factors
        weights = {
            "momentum_24h": 0.35,
            "momentum_7d": 0.15,
            "volatility": 0.10,
            "volume_signal": 0.20,
            "ath_distance": 0.10,
            "market_cap_rank": 0.10,
        }

        composite = sum(factors.get(k, 0) * w for k, w in weights.items())

        if composite > self.signal_threshold * 0.8:  # Lower threshold for crypto
            decision = "BUY"
            confidence = min(composite / 0.6, 1.0)

            # Determine primary driver
            if factors["momentum_24h"] > 0.3:
                primary_reason = f"Strong 24h momentum: +{quote.change_percent_24h:.1f}%"
            elif factors["ath_distance"] > -0.3:
                primary_reason = f"Price recovery towards ATH, currently {quote.ath_change_percent:.0f}% from peak"
            else:
                primary_reason = f"Positive multi-factor signal score: {composite:.2f}"

            rationale = TradeRationale(
                decision=decision,
                confidence=confidence,
                primary_reason=primary_reason,
                factors=factors,
                signals_summary=f"24h: {quote.change_percent_24h:+.1f}% | Vol: ${quote.volume_24h/1e9:.1f}B | MCap Rank: #{quote.market_cap_rank}",
                risk_assessment=f"High volatility asset. Stop loss at {self.stop_loss_pct*100:.0f}%.",
                expected_return=composite * 0.20,  # Crypto has higher potential returns
                expected_holding_period=self.holding_period_target,
                stop_loss=self.stop_loss_pct * 1.5,  # Wider stops for crypto
                take_profit=self.take_profit_pct * 1.5,
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
                signals_summary=self._format_signals_summary(factors),
                risk_assessment="Taking profits as momentum fading",
                expected_return=pnl_pct,
                expected_holding_period=f"Held {holding_hours:.0f} hours",
                stop_loss=0,
                take_profit=0,
            )
            return "SELL", rationale

        return None, None

    async def _analyze_crypto_exit(self, symbol: str, quote) -> Tuple[Optional[str], Optional[TradeRationale]]:
        """Analyze whether to exit a crypto position."""
        position = self.positions[symbol]
        pnl_pct = position.unrealized_pnl_pct

        # Exit on momentum reversal
        if quote.change_percent_24h < -5 and pnl_pct > 0.03:
            rationale = TradeRationale(
                decision="SELL",
                confidence=0.75,
                primary_reason=f"24h momentum turned negative ({quote.change_percent_24h:.1f}%) while profitable",
                factors={"momentum_24h": quote.change_percent_24h / 10},
                signals_summary=f"Locking in {pnl_pct*100:.1f}% gain",
                risk_assessment="Momentum reversal detected",
                expected_return=pnl_pct,
                expected_holding_period=str(position.holding_period),
                stop_loss=0,
                take_profit=0,
            )
            return "SELL", rationale

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

        # Log trade
        rationale = TradeRationale(
            decision="SELL",
            confidence=1.0,
            primary_reason=reason,
            factors={},
            signals_summary=f"Closing: P&L ${pnl:.2f} ({position.unrealized_pnl_pct*100:.1f}%)",
            risk_assessment="Position closed",
            expected_return=position.unrealized_pnl_pct,
            expected_holding_period=str(position.holding_period),
            stop_loss=0,
            take_profit=0,
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
        """Calculate performance metrics."""
        if len(self.equity_curve) < 2:
            return {"error": "Insufficient data"}

        values = [v for _, v in self.equity_curve]
        returns = np.diff(values) / np.array(values[:-1])

        total_return = (values[-1] - self.initial_capital) / self.initial_capital

        # Annualized metrics (assume hourly data)
        n_periods = len(returns)
        periods_per_year = 252 * 24  # Trading hours per year
        cagr = (1 + total_return) ** (periods_per_year / max(n_periods, 1)) - 1 if total_return > -1 else -1

        vol = np.std(returns) * np.sqrt(periods_per_year) if len(returns) > 1 else 0
        sharpe = (cagr - 0.02) / vol if vol > 0 else 0

        # Max drawdown
        peak = np.maximum.accumulate(values)
        drawdown = (np.array(values) - peak) / peak
        max_dd = np.min(drawdown) if len(drawdown) > 0 else 0

        # Win rate
        trades = [t for t in self.trade_history if t.side == "SELL"]
        wins = sum(1 for t in trades if t.pnl > 0)
        win_rate = wins / len(trades) if trades else 0

        return {
            "total_return": round(total_return * 100, 2),
            "cagr": round(cagr * 100, 2),
            "volatility": round(vol * 100, 2),
            "sharpe_ratio": round(sharpe, 2),
            "max_drawdown": round(max_dd * 100, 2),
            "win_rate": round(win_rate * 100, 1),
            "total_trades": len(self.trade_history),
            "current_value": round(self.total_value, 2),
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
