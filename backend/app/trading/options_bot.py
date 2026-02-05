"""
Options Quant Bot - Autonomous Options/Derivatives Trading System

A professional-grade options trading bot implementing institutional strategies:
- IV Rank/Percentile analysis for premium selling
- Delta-neutral portfolio management
- Defined-risk spreads (iron condors, butterflies, verticals)
- Earnings plays (straddles, strangles)
- Theta harvesting with calendar spreads
- Dynamic Greeks-based risk management

This is for PAPER TRADING / EDUCATIONAL purposes only.
"""

import asyncio
import logging
import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from enum import Enum
from typing import Dict, List, Optional, Any, Tuple
import numpy as np


def _safe_float(value: float, default: float = 0.0) -> float:
    """Sanitize float value for JSON serialization (handle inf/nan)."""
    if value is None or math.isnan(value) or math.isinf(value):
        return default
    return value

from .options import (
    OptionType,
    OptionStyle,
    Greeks,
    OptionContract,
    OptionsStrategy,
    OptionsManager,
    BlackScholes,
)

logger = logging.getLogger(__name__)


class OptionsMode(Enum):
    """Trading mode affecting strategy selection and risk parameters."""
    AGGRESSIVE = "aggressive"      # High premium, tighter strikes, more gamma risk
    BALANCED = "balanced"          # Mix of strategies, moderate risk
    CONSERVATIVE = "conservative"  # Wide spreads, low delta, theta focused


class StrategySignal(Enum):
    """Signal types for options strategies."""
    HIGH_IV_SELL_PREMIUM = "high_iv_sell_premium"      # IV Rank > 50, sell strangles/condors
    LOW_IV_BUY_PREMIUM = "low_iv_buy_premium"          # IV Rank < 20, buy straddles
    EARNINGS_PLAY = "earnings_play"                     # Pre-earnings straddle
    THETA_HARVEST = "theta_harvest"                     # Calendar/diagonal spreads
    DIRECTIONAL_BULLISH = "directional_bullish"        # Bull call spread
    DIRECTIONAL_BEARISH = "directional_bearish"        # Bear put spread
    VOLATILITY_CRUSH = "volatility_crush"              # Post-event IV crush play
    DELTA_HEDGE = "delta_hedge"                        # Portfolio rebalancing


@dataclass
class IVAnalysis:
    """Implied Volatility analysis for a symbol."""
    symbol: str
    current_iv: float
    iv_rank: float          # 0-100, where current IV sits in 52-week range
    iv_percentile: float    # 0-100, % of days IV was lower
    iv_30_day_avg: float
    iv_trend: str           # "rising", "falling", "stable"
    hv_iv_spread: float     # IV - HV (historical volatility)

    @property
    def is_high_iv(self) -> bool:
        return self.iv_rank > 50

    @property
    def is_low_iv(self) -> bool:
        return self.iv_rank < 30

    @property
    def premium_selling_favorable(self) -> bool:
        return self.iv_rank > 40 and self.hv_iv_spread > 0

    def to_dict(self) -> Dict:
        return {
            "symbol": self.symbol,
            "current_iv": round(_safe_float(self.current_iv * 100), 1),
            "iv_rank": round(_safe_float(self.iv_rank), 1),
            "iv_percentile": round(_safe_float(self.iv_percentile), 1),
            "iv_30_day_avg": round(_safe_float(self.iv_30_day_avg * 100), 1),
            "iv_trend": self.iv_trend,
            "hv_iv_spread": round(_safe_float(self.hv_iv_spread * 100), 1),
            "is_high_iv": self.is_high_iv,
            "premium_selling_favorable": self.premium_selling_favorable,
        }


@dataclass
class OptionsPosition:
    """Represents an open options position/strategy."""
    id: str
    symbol: str
    strategy_name: str
    strategy: OptionsStrategy
    entry_time: datetime
    entry_iv: float
    entry_underlying_price: float

    # Current state
    current_iv: float = 0.0
    current_underlying_price: float = 0.0
    current_pnl: float = 0.0
    days_in_trade: int = 0

    # Risk metrics
    max_profit: float = 0.0
    max_loss: float = 0.0
    current_delta: float = 0.0
    current_theta: float = 0.0
    current_vega: float = 0.0

    # Management
    profit_target_pct: float = 0.50  # Close at 50% of max profit
    loss_limit_pct: float = 2.0      # Close at 2x premium received
    days_to_expiry_close: int = 21   # Close at 21 DTE

    def should_close(self) -> Tuple[bool, str]:
        """Check if position should be closed."""
        # Profit target hit
        if self.max_profit > 0:
            profit_pct = self.current_pnl / self.max_profit
            if profit_pct >= self.profit_target_pct:
                return True, f"Profit target reached: {profit_pct*100:.1f}%"

        # Loss limit hit
        if self.max_loss < 0:
            loss_pct = self.current_pnl / abs(self.max_loss)
            if loss_pct <= -self.loss_limit_pct:
                return True, f"Loss limit reached: {loss_pct*100:.1f}%"

        # Time-based exit (21 DTE rule)
        if self.strategy.legs:
            min_dte = min(leg.days_to_expiry() for leg in self.strategy.legs)
            if min_dte <= self.days_to_expiry_close:
                return True, f"DTE threshold: {min_dte} days remaining"

        return False, ""

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "strategy_name": self.strategy_name,
            "entry_time": self.entry_time.isoformat(),
            "entry_iv": round(_safe_float(self.entry_iv * 100), 1),
            "entry_price": round(_safe_float(self.entry_underlying_price), 2),
            "current_price": round(_safe_float(self.current_underlying_price), 2),
            "current_pnl": round(_safe_float(self.current_pnl), 2),
            "days_in_trade": self.days_in_trade,
            "max_profit": round(_safe_float(self.max_profit), 2),
            "max_loss": round(_safe_float(self.max_loss), 2),
            "greeks": {
                "delta": round(_safe_float(self.current_delta), 2),
                "theta": round(_safe_float(self.current_theta), 2),
                "vega": round(_safe_float(self.current_vega), 2),
            },
            "legs_count": len(self.strategy.legs),
            "strategy_details": self.strategy.to_dict() if self.strategy else None,
        }


@dataclass
class OptionsTrade:
    """Record of an options trade."""
    id: str
    timestamp: datetime
    symbol: str
    strategy_name: str
    action: str  # "OPEN" or "CLOSE"
    legs: List[Dict]
    net_premium: float
    pnl: float
    rationale: str
    iv_at_trade: float
    underlying_at_trade: float

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat(),
            "symbol": self.symbol,
            "strategy_name": self.strategy_name,
            "action": self.action,
            "legs": self.legs,
            "net_premium": round(_safe_float(self.net_premium), 2),
            "pnl": round(_safe_float(self.pnl), 2),
            "rationale": self.rationale,
            "iv_at_trade": round(_safe_float(self.iv_at_trade * 100), 1),
            "underlying_at_trade": round(_safe_float(self.underlying_at_trade), 2),
        }


@dataclass
class CryptoDerivativePosition:
    """
    Represents a crypto derivative position (perpetual futures or options).

    Supports Deribit-style crypto derivatives:
    - Perpetual futures (BTC-PERP, ETH-PERP)
    - Options (BTC-OPT, ETH-OPT)
    """
    id: str
    symbol: str  # e.g., "BTC-PERP", "ETH-28MAR25-3000-C"
    derivative_type: str  # "perpetual", "call", "put"
    side: str  # "long" or "short"
    entry_price: float
    size: float  # Contract size in USD or crypto units
    leverage: float = 1.0

    # Current state
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    funding_received: float = 0.0  # For perpetuals
    liquidation_price: float = 0.0

    # Greeks (for options)
    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0
    iv: float = 0.0

    # Management
    take_profit: float = 0.0
    stop_loss: float = 0.0

    # Trade tracking
    trade_id: Optional[str] = None  # Links to master trade log
    opened_at: Optional[datetime] = None

    def calculate_pnl(self) -> float:
        """Calculate current P&L including funding.

        Note: self.size is in USD (full position value, NOT margin).
        For a $500 position with 5x leverage, size=$500, margin=$100.
        PnL = percentage_change * position_size (NOT multiplied by leverage again!)
        """
        if self.entry_price <= 0:
            return 0.0

        # Calculate percentage change
        pct_change = (self.current_price - self.entry_price) / self.entry_price

        # For short positions, profit when price goes down
        if self.side == "short":
            pct_change = -pct_change

        # PnL = percentage change * position size + funding
        # size is already the full leveraged position, don't multiply by leverage again!
        return pct_change * self.size + self.funding_received

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "derivative_type": self.derivative_type,
            "side": self.side,
            "entry_price": round(_safe_float(self.entry_price), 2),
            "size": round(_safe_float(self.size), 4),
            "leverage": _safe_float(self.leverage, 1.0),
            "current_price": round(_safe_float(self.current_price), 2),
            "unrealized_pnl": round(_safe_float(self.calculate_pnl()), 2),
            "funding_received": round(_safe_float(self.funding_received), 2),
            "liquidation_price": round(_safe_float(self.liquidation_price), 2),
            "greeks": {
                "delta": round(_safe_float(self.delta), 4),
                "gamma": round(_safe_float(self.gamma), 6),
                "theta": round(_safe_float(self.theta), 4),
                "vega": round(_safe_float(self.vega), 4),
                "iv": round(_safe_float(self.iv * 100), 1),
            },
        }


class OptionsRiskManager:
    """
    Options-specific risk management.

    Manages:
    - Portfolio Greeks exposure
    - Delta neutrality
    - Vega exposure limits
    - Correlation risk
    - Buying power utilization
    """

    def __init__(
        self,
        max_portfolio_delta: float = 100,       # Max net delta exposure
        max_portfolio_vega: float = 500,        # Max vega exposure
        max_single_position_pct: float = 0.10,  # Max 10% of capital per position
        max_sector_exposure: float = 0.30,      # Max 30% in one sector
        buying_power_limit: float = 0.50,       # Use max 50% of buying power
    ):
        self.max_portfolio_delta = max_portfolio_delta
        self.max_portfolio_vega = max_portfolio_vega
        self.max_single_position_pct = max_single_position_pct
        self.max_sector_exposure = max_sector_exposure
        self.buying_power_limit = buying_power_limit

        # Current state
        self.current_delta = 0.0
        self.current_gamma = 0.0
        self.current_theta = 0.0
        self.current_vega = 0.0
        self.buying_power_used = 0.0

        # Risk mode
        self.risk_mode = "NORMAL"  # NORMAL, REDUCED, DEFENSIVE

    def update_portfolio_greeks(
        self,
        options_positions: List[OptionsPosition],
        crypto_positions: Optional[List] = None
    ):
        """Update aggregate portfolio Greeks including crypto positions."""
        # Options Greeks
        self.current_delta = sum(p.current_delta for p in options_positions)
        self.current_theta = sum(p.current_theta for p in options_positions)
        self.current_vega = sum(p.current_vega for p in options_positions)

        # Add crypto position deltas (perpetuals have delta of position size)
        if crypto_positions:
            crypto_delta = sum(p.delta for p in crypto_positions if hasattr(p, 'delta'))
            self.current_delta += crypto_delta
            # Crypto perpetuals have no theta (no time decay) and no vega (no IV sensitivity)

        # Update risk mode based on exposure
        if abs(self.current_delta) > self.max_portfolio_delta * 0.8:
            self.risk_mode = "REDUCED"
        elif abs(self.current_vega) > self.max_portfolio_vega * 0.8:
            self.risk_mode = "REDUCED"
        else:
            self.risk_mode = "NORMAL"

    def can_open_position(
        self,
        strategy: OptionsStrategy,
        buying_power_required: float,
        total_buying_power: float,
    ) -> Tuple[bool, str]:
        """Check if a new position can be opened within risk limits."""
        # Check buying power
        new_bp_used = self.buying_power_used + buying_power_required
        if new_bp_used / total_buying_power > self.buying_power_limit:
            return False, f"Buying power limit exceeded: {new_bp_used/total_buying_power*100:.1f}%"

        # Check delta impact
        strategy_greeks = strategy.portfolio_greeks()
        new_delta = self.current_delta + strategy_greeks.delta
        if abs(new_delta) > self.max_portfolio_delta:
            return False, f"Delta limit exceeded: {new_delta:.0f}"

        # Check vega impact
        new_vega = self.current_vega + strategy_greeks.vega
        if abs(new_vega) > self.max_portfolio_vega:
            return False, f"Vega limit exceeded: {new_vega:.0f}"

        return True, "OK"

    def get_position_size_adjustment(self, iv_rank: float) -> float:
        """
        Adjust position size based on IV conditions.
        Higher IV = larger positions for premium selling.
        """
        if iv_rank > 70:
            return 1.2  # 20% larger in high IV
        elif iv_rank > 50:
            return 1.0  # Normal size
        elif iv_rank > 30:
            return 0.8  # 20% smaller in moderate IV
        else:
            return 0.6  # 40% smaller in low IV

    def get_risk_summary(self) -> Dict:
        return {
            "risk_mode": self.risk_mode,
            "portfolio_delta": round(self.current_delta, 2),
            "portfolio_theta": round(self.current_theta, 2),
            "portfolio_vega": round(self.current_vega, 2),
            "delta_utilization": round(abs(self.current_delta) / self.max_portfolio_delta * 100, 1),
            "vega_utilization": round(abs(self.current_vega) / self.max_portfolio_vega * 100, 1),
            "buying_power_used_pct": round(self.buying_power_used * 100, 1),
        }


class OptionsQuantBot:
    """
    Autonomous Options Trading Bot.

    Implements institutional-grade options strategies:
    - IV-based premium selling (iron condors, strangles)
    - Directional spreads (bull call, bear put)
    - Volatility plays (straddles, calendars)
    - Greeks-based portfolio management

    Paper trading only - educational purposes.
    """

    # Watchlist - high-liquidity options underlyings
    OPTIONS_UNIVERSE = [
        # Index ETFs (most liquid options - highest priority)
        "SPY", "QQQ", "IWM", "DIA", "XLK", "XLV", "XLF", "XLE", "XLU", "XLI",
        # Mega-cap tech (very liquid)
        "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "AMD", "INTC", "CRM",
        # Commodities & Precious Metals (tangible assets)
        "GLD", "SLV", "GDX", "USO", "UNG", "WEAT", "CORN", "SOYB",
        # Energy & Materials
        "XOP", "OIH", "XME", "FCX", "CLF",
        # Volatility Products
        "VIX", "UVXY", "VXX",
        # Financials
        "JPM", "BAC", "GS", "MS", "WFC", "C",
        # Consumer & Retail
        "WMT", "COST", "TGT", "HD", "NKE",
        # Healthcare & Biotech
        "JNJ", "PFE", "MRNA", "UNH", "LLY",
        # Other high-liquidity
        "NFLX", "DIS", "BA", "V", "MA", "PYPL", "SQ", "COIN",
    ]

    # Crypto Derivatives (Deribit-style options on BTC/ETH)
    CRYPTO_DERIVATIVES = [
        # Bitcoin Options (Deribit)
        "BTC-PERP",   # Perpetual futures
        "BTC-OPT",    # Options (calls/puts)
        # Ethereum Options (Deribit)
        "ETH-PERP",   # Perpetual futures
        "ETH-OPT",    # Options (calls/puts)
        # Solana Derivatives
        "SOL-PERP",
        # Altcoin perpetuals
        "AVAX-PERP", "MATIC-PERP", "LINK-PERP", "ARB-PERP", "OP-PERP",
    ]

    # Kelly Criterion scaling for position sizing
    KELLY_FRACTION = 0.25  # Use 1/4 Kelly for conservative sizing

    def __init__(
        self,
        initial_capital: float = 100000.0,
        mode: OptionsMode = OptionsMode.BALANCED,
    ):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.mode = mode
        self.is_running = False

        # Core components
        self.options_manager = OptionsManager()
        self.risk_manager = OptionsRiskManager()

        # Positions and trades (traditional options)
        self.positions: Dict[str, OptionsPosition] = {}
        self.trade_history: List[OptionsTrade] = []

        # Crypto derivative positions
        self.crypto_positions: Dict[str, CryptoDerivativePosition] = {}

        # IV data cache
        self.iv_cache: Dict[str, IVAnalysis] = {}

        # Performance tracking
        self.equity_curve: List[Tuple[datetime, float]] = [(datetime.now(), initial_capital)]

        # Scanning state
        self.last_scan_time: Optional[datetime] = None
        self.scan_interval_seconds = 60  # Scan every minute

        # Commentary for UI
        self.commentary: List[Dict] = []

        # Mode-specific parameters
        self._configure_mode()

        logger.info(f"OptionsQuantBot initialized: ${initial_capital:,.0f}, mode={mode.value}")

    def _configure_mode(self):
        """Configure parameters based on trading mode for maximum ROI."""
        if self.mode == OptionsMode.AGGRESSIVE:
            # Maximum ROI mode - higher risk/reward
            self.target_delta_per_leg = 0.35      # 35 delta options (higher premium)
            self.min_iv_rank = 25                  # Enter on moderate IV
            self.profit_target = 0.65              # Take 65% of max profit
            self.loss_limit = 2.0                  # Cut at 2x credit received
            self.max_positions = 20
            self.min_dte = 25                      # 25-45 DTE sweet spot
            self.max_dte = 50
            self.roll_dte = 14                     # Roll at 14 DTE
            self.kelly_multiplier = 1.0           # Full Kelly fraction
            self.preferred_strategies = [
                "iron_condor", "strangle", "straddle", "vertical", "ratio_spread"
            ]
        elif self.mode == OptionsMode.BALANCED:
            # Balanced risk/reward
            self.target_delta_per_leg = 0.25      # 25 delta options
            self.min_iv_rank = 35                  # Moderate IV threshold
            self.profit_target = 0.50              # Take 50% of max profit
            self.loss_limit = 2.0
            self.max_positions = 12
            self.min_dte = 30
            self.max_dte = 50
            self.roll_dte = 21
            self.kelly_multiplier = 0.75
            self.preferred_strategies = [
                "iron_condor", "butterfly", "vertical", "calendar"
            ]
        else:  # CONSERVATIVE
            # Capital preservation focus
            self.target_delta_per_leg = 0.16      # 16 delta options (very safe)
            self.min_iv_rank = 45                  # High IV only
            self.profit_target = 0.40              # Take 40% of max profit
            self.loss_limit = 1.5                  # Tighter stop
            self.max_positions = 8
            self.min_dte = 35
            self.max_dte = 55
            self.roll_dte = 21
            self.kelly_multiplier = 0.5
            self.preferred_strategies = [
                "iron_condor", "butterfly", "jade_lizard"
            ]

    def _calculate_kelly_size(self, win_prob: float, win_amount: float, loss_amount: float) -> float:
        """
        Calculate position size using Kelly Criterion.

        Kelly % = (bp - q) / b
        where:
        - b = win_amount / loss_amount (odds)
        - p = probability of winning
        - q = probability of losing (1 - p)
        """
        if loss_amount == 0:
            return 0

        b = win_amount / loss_amount
        p = win_prob
        q = 1 - p

        kelly = (b * p - q) / b

        # Apply fraction and mode multiplier
        kelly_adjusted = max(0, kelly * self.KELLY_FRACTION * self.kelly_multiplier)

        # Cap at 5% of capital per position
        return min(kelly_adjusted, 0.05)

    @property
    def total_value(self) -> float:
        """Calculate total portfolio value."""
        positions_value = sum(p.current_pnl for p in self.positions.values())
        return self.cash + positions_value

    @property
    def total_pnl(self) -> float:
        return self.total_value - self.initial_capital

    @property
    def total_pnl_pct(self) -> float:
        return self.total_pnl / self.initial_capital

    async def start(self):
        """Start the options bot."""
        self.is_running = True
        self._add_commentary(
            f"🚀 OPTIONS BOT STARTED: ${self.initial_capital:,.0f} capital, {self.mode.value} mode",
            "system"
        )

        # Start main loop
        asyncio.create_task(self._run_loop())

    async def stop(self):
        """Stop the options bot."""
        self.is_running = False
        self._add_commentary("🛑 OPTIONS BOT STOPPED", "system")

    async def _run_loop(self):
        """Main trading loop."""
        while self.is_running:
            try:
                await self._trading_cycle()
            except Exception as e:
                logger.error(f"Trading cycle error: {e}")
                self._add_commentary(f"⚠️ Error in trading cycle: {str(e)[:100]}", "error")

            await asyncio.sleep(self.scan_interval_seconds)

    async def _trading_cycle(self):
        """Execute one trading cycle."""
        self.last_scan_time = datetime.now()

        # 1. Update all positions
        await self._update_positions()

        # 2. Check for exits
        await self._check_exits()

        # 3. Scan for new opportunities
        if len(self.positions) < self.max_positions:
            await self._scan_opportunities()

        # 4. Update equity curve
        self.equity_curve.append((datetime.now(), self.total_value))

    async def _update_positions(self):
        """Update current prices and Greeks for all positions."""
        for position in self.positions.values():
            try:
                # Get current underlying price (simulated for now)
                current_price = await self._get_underlying_price(position.symbol)
                position.current_underlying_price = current_price

                # Get current IV
                iv_analysis = await self._analyze_iv(position.symbol)
                position.current_iv = iv_analysis.current_iv

                # Recalculate position value
                position.current_pnl = self._calculate_position_pnl(position)
                position.days_in_trade = (datetime.now() - position.entry_time).days

                # Update Greeks
                if position.strategy:
                    greeks = position.strategy.portfolio_greeks()
                    position.current_delta = greeks.delta
                    position.current_theta = greeks.theta
                    position.current_vega = greeks.vega

            except Exception as e:
                logger.error(f"Failed to update position {position.symbol}: {e}")

        # Update risk manager with both options and crypto positions
        self.risk_manager.update_portfolio_greeks(
            list(self.positions.values()),
            list(self.crypto_positions.values())
        )

    async def _check_exits(self):
        """Check all positions for exit signals."""
        positions_to_close = []

        for pos_id, position in self.positions.items():
            should_close, reason = position.should_close()
            if should_close:
                positions_to_close.append((pos_id, reason))

        for pos_id, reason in positions_to_close:
            await self._close_position(pos_id, reason)

    async def _scan_opportunities(self):
        """Scan for new trading opportunities based on mode."""
        # CRITICAL: Check if stock market is open before scanning stock options
        from .quant_bot import is_market_open, get_market_status

        if not is_market_open():
            market_status = get_market_status()
            self._add_commentary(
                f"⛔ Stock market CLOSED ({market_status['message']}) - Skipping stock options scan",
                "scan"
            )
            return  # Don't scan stock options when market is closed

        # Scan more symbols in aggressive mode
        scan_count = {
            OptionsMode.AGGRESSIVE: 30,
            OptionsMode.BALANCED: 20,
            OptionsMode.CONSERVATIVE: 12,
        }.get(self.mode, 20)

        for symbol in self.OPTIONS_UNIVERSE[:scan_count]:
            try:
                # Skip if already have position
                if any(p.symbol == symbol for p in self.positions.values()):
                    continue

                # Analyze IV
                iv_analysis = await self._analyze_iv(symbol)
                self.iv_cache[symbol] = iv_analysis

                # Get signal
                signal = self._generate_signal(symbol, iv_analysis)

                if signal:
                    await self._execute_signal(symbol, signal, iv_analysis)

            except Exception as e:
                logger.debug(f"Scan failed for {symbol}: {e}")

    async def _analyze_iv(self, symbol: str) -> IVAnalysis:
        """
        Analyze volatility for a symbol using REAL historical data.

        Calculates Historical Volatility (HV) from actual price movements.
        For crypto, uses real Binance data. For stocks, uses yfinance data.
        """
        # Get current price
        current_price = await self._get_underlying_price(symbol)

        # Try to get real historical volatility from price data
        try:
            from .master_bot import get_master_bot
            bot = get_master_bot()
            if bot and hasattr(bot, 'analytics'):
                # Get price history for volatility calculation
                price_key = symbol.replace("-PERP", "") if "-PERP" in symbol else symbol
                if price_key in bot.analytics.price_history:
                    prices = bot.analytics.price_history[price_key]
                    if len(prices) >= 20:
                        # Calculate actual historical volatility
                        returns = np.diff(prices) / prices[:-1]
                        hv_20d = float(np.std(returns[-20:]) * np.sqrt(252))  # 20-day HV annualized
                        hv_60d = float(np.std(returns[-60:]) * np.sqrt(252)) if len(returns) >= 60 else hv_20d

                        # IV is typically HV + premium (we estimate)
                        base_iv = hv_20d * 1.15  # IV typically trades at premium to HV

                        # Calculate IV rank from historical HV range
                        if len(returns) >= 252:
                            hv_series = [float(np.std(returns[i:i+20]) * np.sqrt(252))
                                        for i in range(0, len(returns)-20, 5)]
                            hv_min = min(hv_series)
                            hv_max = max(hv_series)
                            iv_rank = ((base_iv - hv_min) / (hv_max - hv_min) * 100
                                       if hv_max > hv_min else 50)
                        else:
                            # Limited data - estimate rank
                            iv_rank = 50 + (base_iv - 0.25) * 100  # Centered at 25% vol

                        # Clamp iv_rank to valid range
                        iv_rank = max(0, min(100, iv_rank))

                        # Calculate trend from recent vs older HV
                        if len(returns) >= 40:
                            recent_hv = float(np.std(returns[-10:]) * np.sqrt(252))
                            older_hv = float(np.std(returns[-40:-30]) * np.sqrt(252))
                            if recent_hv > older_hv * 1.1:
                                iv_trend = "rising"
                            elif recent_hv < older_hv * 0.9:
                                iv_trend = "falling"
                            else:
                                iv_trend = "stable"
                        else:
                            iv_trend = "stable"

                        return IVAnalysis(
                            symbol=symbol,
                            current_iv=base_iv,
                            iv_rank=iv_rank,
                            iv_percentile=iv_rank * 0.95,
                            iv_30_day_avg=hv_60d * 1.1,
                            iv_trend=iv_trend,
                            hv_iv_spread=base_iv - hv_20d,
                        )
        except Exception as e:
            logger.debug(f"Could not calculate real IV for {symbol}: {e}")

        # Fallback: Use realistic base IV by asset class (no randomness)
        if symbol in ["SPY", "QQQ", "IWM"]:
            base_iv = 0.16  # Typical ETF IV
        elif symbol == "VIX":
            base_iv = 0.80  # VIX is inherently high vol
        elif symbol in ["TSLA", "NVDA", "AMD"]:
            base_iv = 0.45  # High-vol tech stocks
        elif "BTC" in symbol or "ETH" in symbol:
            base_iv = 0.55  # Crypto typically higher vol
        else:
            base_iv = 0.28  # Average stock vol

        hv = base_iv * 0.90  # Estimate HV at 90% of IV
        return IVAnalysis(
            symbol=symbol,
            current_iv=base_iv,
            iv_rank=50,  # Default to middle rank without data
            iv_percentile=47.5,
            iv_30_day_avg=base_iv * 0.95,
            iv_trend="stable",
            hv_iv_spread=base_iv - hv,
        )

    def _generate_signal(
        self,
        symbol: str,
        iv_analysis: IVAnalysis
    ) -> Optional[StrategySignal]:
        """Generate trading signal based on IV analysis."""

        # High IV = sell premium
        if iv_analysis.iv_rank > self.min_iv_rank and iv_analysis.premium_selling_favorable:
            if "iron_condor" in self.preferred_strategies:
                return StrategySignal.HIGH_IV_SELL_PREMIUM

        # Low IV = buy premium (for volatility expansion)
        if iv_analysis.iv_rank < 25 and "straddle" in self.preferred_strategies:
            return StrategySignal.LOW_IV_BUY_PREMIUM

        # Directional signals based on IV trend
        if iv_analysis.iv_trend == "falling" and iv_analysis.iv_rank > 40:
            # IV crush opportunity
            if "vertical" in self.preferred_strategies:
                return StrategySignal.VOLATILITY_CRUSH

        return None

    async def _execute_signal(
        self,
        symbol: str,
        signal: StrategySignal,
        iv_analysis: IVAnalysis
    ):
        """Execute a trading signal by opening appropriate strategy."""
        try:
            current_price = await self._get_underlying_price(symbol)

            if signal == StrategySignal.HIGH_IV_SELL_PREMIUM:
                strategy = await self._create_iron_condor(
                    symbol, current_price, iv_analysis
                )
                if strategy:
                    await self._open_position(
                        symbol, "Iron Condor", strategy, iv_analysis,
                        f"High IV Rank ({iv_analysis.iv_rank:.0f}%) - Premium selling favorable"
                    )

            elif signal == StrategySignal.LOW_IV_BUY_PREMIUM:
                strategy = await self._create_straddle(
                    symbol, current_price, iv_analysis, long=True
                )
                if strategy:
                    await self._open_position(
                        symbol, "Long Straddle", strategy, iv_analysis,
                        f"Low IV Rank ({iv_analysis.iv_rank:.0f}%) - Volatility expansion play"
                    )

            elif signal == StrategySignal.VOLATILITY_CRUSH:
                strategy = await self._create_vertical_spread(
                    symbol, current_price, iv_analysis, bullish=True
                )
                if strategy:
                    await self._open_position(
                        symbol, "Bull Call Spread", strategy, iv_analysis,
                        f"IV Crush expected - Defined risk directional"
                    )

        except Exception as e:
            logger.error(f"Failed to execute signal for {symbol}: {e}")

    async def _create_iron_condor(
        self,
        symbol: str,
        underlying_price: float,
        iv_analysis: IVAnalysis
    ) -> Optional[OptionsStrategy]:
        """Create an iron condor strategy."""
        from datetime import timedelta

        # Calculate strikes based on delta targets
        # Short strikes at ~20 delta, wings 5-10 points wider
        call_lower = round(underlying_price * (1 + 0.05), 0)  # 5% OTM (short call)
        call_upper = call_lower + 5  # Long call protection
        put_upper = round(underlying_price * (1 - 0.05), 0)   # 5% OTM (short put)
        put_lower = put_upper - 5  # Long put protection

        # ~45 DTE optimal for iron condors
        expiration = (datetime.now() + timedelta(days=45)).date()

        return self.options_manager.create_iron_condor(
            symbol=symbol,
            underlying_price=underlying_price,
            put_lower=put_lower,
            put_upper=put_upper,
            call_lower=call_lower,
            call_upper=call_upper,
            expiration=expiration,
            volatility=iv_analysis.current_iv,
        )

    async def _create_straddle(
        self,
        symbol: str,
        underlying_price: float,
        iv_analysis: IVAnalysis,
        long: bool = True
    ) -> Optional[OptionsStrategy]:
        """Create a straddle strategy."""
        from datetime import timedelta

        strike = round(underlying_price, 0)  # ATM strike
        # ~30 DTE for straddles
        expiration = (datetime.now() + timedelta(days=30)).date()

        return self.options_manager.create_straddle(
            symbol=symbol,
            underlying_price=underlying_price,
            strike=strike,
            expiration=expiration,
            volatility=iv_analysis.current_iv,
            is_long=long,
        )

    async def _create_vertical_spread(
        self,
        symbol: str,
        underlying_price: float,
        iv_analysis: IVAnalysis,
        bullish: bool = True
    ) -> Optional[OptionsStrategy]:
        """Create a vertical spread."""
        from datetime import timedelta

        # ~30 DTE for vertical spreads
        expiration = (datetime.now() + timedelta(days=30)).date()

        if bullish:
            # Bull call spread: buy lower strike, sell higher strike
            lower_strike = round(underlying_price * 0.98, 0)   # Slightly ITM
            upper_strike = round(underlying_price * 1.02, 0)   # Slightly OTM

            return self.options_manager.create_bull_call_spread(
                symbol=symbol,
                underlying_price=underlying_price,
                lower_strike=lower_strike,
                upper_strike=upper_strike,
                expiration=expiration,
                volatility=iv_analysis.current_iv,
            )
        else:
            # Bear put spread: buy higher strike, sell lower strike
            lower_strike = round(underlying_price * 0.98, 0)
            upper_strike = round(underlying_price * 1.02, 0)

            return self.options_manager.create_bear_put_spread(
                symbol=symbol,
                underlying_price=underlying_price,
                lower_strike=lower_strike,
                upper_strike=upper_strike,
                expiration=expiration,
                volatility=iv_analysis.current_iv,
            )

    async def _open_position(
        self,
        symbol: str,
        strategy_name: str,
        strategy: OptionsStrategy,
        iv_analysis: IVAnalysis,
        rationale: str
    ):
        """Open a new options position with Kelly Criterion sizing."""
        # Calculate optimal position size using Kelly Criterion
        max_profit = abs(strategy.max_profit) if strategy.max_profit else 0
        max_loss = abs(strategy.max_loss) if strategy.max_loss else 1000

        # Estimate win probability based on IV rank (higher IV rank = higher win prob for premium sellers)
        win_prob = min(0.75, 0.50 + (iv_analysis.iv_rank / 200))  # 50-75% based on IV rank

        kelly_pct = self._calculate_kelly_size(win_prob, max_profit, max_loss)
        optimal_allocation = self.initial_capital * kelly_pct

        # Calculate contracts to trade based on Kelly sizing
        buying_power_per_contract = max_loss if max_loss > 0 else 1000
        num_contracts = max(1, int(optimal_allocation / buying_power_per_contract))

        # Scale buying power required by number of contracts
        buying_power_required = buying_power_per_contract * num_contracts

        can_open, reason = self.risk_manager.can_open_position(
            strategy, buying_power_required, self.cash
        )

        if not can_open:
            self._add_commentary(f"⚠️ Cannot open {strategy_name} on {symbol}: {reason}", "risk")
            return

        current_price = await self._get_underlying_price(symbol)

        position = OptionsPosition(
            id=str(uuid.uuid4())[:8],
            symbol=symbol,
            strategy_name=strategy_name,
            strategy=strategy,
            entry_time=datetime.now(),
            entry_iv=iv_analysis.current_iv,
            entry_underlying_price=current_price,
            current_iv=iv_analysis.current_iv,
            current_underlying_price=current_price,
            max_profit=(strategy.max_profit or 0) * num_contracts,
            max_loss=(strategy.max_loss or 0) * num_contracts,
            profit_target_pct=self.profit_target,
            loss_limit_pct=self.loss_limit,
            days_to_expiry_close=self.roll_dte,
        )

        # Update Greeks
        greeks = strategy.portfolio_greeks()
        position.current_delta = greeks.delta
        position.current_theta = greeks.theta
        position.current_vega = greeks.vega

        self.positions[position.id] = position
        self.cash -= buying_power_required
        self.risk_manager.buying_power_used += buying_power_required / self.initial_capital

        # Record trade
        trade = OptionsTrade(
            id=str(uuid.uuid4())[:8],
            timestamp=datetime.now(),
            symbol=symbol,
            strategy_name=strategy_name,
            action="OPEN",
            legs=[leg.to_dict() for leg in strategy.legs],
            net_premium=strategy.net_premium,
            pnl=0,
            rationale=rationale,
            iv_at_trade=iv_analysis.current_iv,
            underlying_at_trade=current_price,
        )
        self.trade_history.append(trade)

        self._add_commentary(
            f"✅ OPENED {strategy_name} on {symbol} ({num_contracts} contracts): "
            f"Max Profit ${position.max_profit:,.0f} / Max Loss ${position.max_loss:,.0f} | "
            f"IV: {iv_analysis.current_iv*100:.1f}% | Kelly: {kelly_pct*100:.1f}%",
            "trade"
        )

        # Update portfolio-level Greeks with both options and crypto
        self.risk_manager.update_portfolio_greeks(
            list(self.positions.values()),
            list(self.crypto_positions.values())
        )

    async def _close_position(self, position_id: str, reason: str):
        """Close an options position."""
        if position_id not in self.positions:
            return

        position = self.positions[position_id]
        pnl = position.current_pnl

        # Return buying power
        buying_power_return = abs(position.max_loss) if position.max_loss else 0
        self.cash += buying_power_return + pnl
        self.risk_manager.buying_power_used -= buying_power_return / self.initial_capital

        # Record trade
        trade = OptionsTrade(
            id=str(uuid.uuid4())[:8],
            timestamp=datetime.now(),
            symbol=position.symbol,
            strategy_name=position.strategy_name,
            action="CLOSE",
            legs=[leg.to_dict() for leg in position.strategy.legs] if position.strategy else [],
            net_premium=0,
            pnl=pnl,
            rationale=reason,
            iv_at_trade=position.current_iv,
            underlying_at_trade=position.current_underlying_price,
        )
        self.trade_history.append(trade)

        emoji = "💰" if pnl >= 0 else "📉"
        self._add_commentary(
            f"{emoji} CLOSED {position.strategy_name} on {position.symbol}: "
            f"P&L ${pnl:+,.0f} | {reason}",
            "trade"
        )

        del self.positions[position_id]

    def _calculate_position_pnl(self, position: OptionsPosition) -> float:
        """Calculate current P&L for a position."""
        if not position.strategy:
            return 0

        # Simplified P&L based on underlying price change
        # In production, would reprice all options
        price_change_pct = (
            (position.current_underlying_price - position.entry_underlying_price)
            / position.entry_underlying_price
        )

        # Use delta to estimate P&L
        pnl = position.current_delta * price_change_pct * 100

        # Add theta decay (positive for short premium strategies)
        days_held = (datetime.now() - position.entry_time).days
        pnl += position.current_theta * days_held

        return pnl

    async def _get_underlying_price(self, symbol: str) -> float:
        """Get current underlying price - LIVE data only from Alpaca."""
        # Try to get live price from Alpaca broker
        try:
            from .live_brokers import get_broker_manager
            manager = get_broker_manager()
            if manager.alpaca and manager.alpaca._connected:
                live_price = await manager.get_live_price(symbol.upper(), "stock")
                if live_price > 0:
                    return live_price
                else:
                    logger.warning(f"Alpaca returned zero price for {symbol}")
            else:
                logger.warning(f"Alpaca not connected - cannot get price for {symbol}")
        except Exception as e:
            logger.error(f"Failed to get live price for {symbol}: {e}")

        # NO FALLBACK - Return 0 to indicate price unavailable
        # Callers should handle this and skip the trade
        logger.error(f"❌ NO LIVE PRICE for {symbol} - synthetic fallback DISABLED")
        return 0

    def _add_commentary(self, message: str, category: str):
        """Add commentary entry."""
        self.commentary.append({
            "timestamp": datetime.now().isoformat(),
            "message": message,
            "category": category,
        })
        # Keep last 100 entries
        if len(self.commentary) > 100:
            self.commentary = self.commentary[-100:]

    # ======================
    # CRYPTO DERIVATIVES
    # ======================

    async def _get_crypto_price(self, symbol: str) -> float:
        """Get current crypto price - LIVE data only from Binance."""
        # Extract base asset from derivative symbol
        base = symbol.split("-")[0].upper()

        # Try to get live price from Binance broker
        try:
            from .live_brokers import get_broker_manager
            manager = get_broker_manager()
            if manager.binance and manager.binance._connected:
                # Use futures price for perpetuals, spot otherwise
                if "-PERP" in symbol:
                    live_price = await manager.get_live_price(base, "crypto_futures")
                else:
                    live_price = await manager.get_live_price(base, "crypto")
                if live_price > 0:
                    return live_price
                else:
                    logger.warning(f"Binance returned zero price for {symbol}")
            else:
                logger.warning(f"Binance not connected - cannot get price for {symbol}")
        except Exception as e:
            logger.error(f"Failed to get live crypto price for {symbol}: {e}")

        # NO FALLBACK - Return 0 to indicate price unavailable
        # Callers should handle this and skip the trade
        logger.error(f"❌ NO LIVE PRICE for {symbol} - synthetic fallback DISABLED")
        return 0

    async def open_crypto_perpetual(
        self,
        symbol: str,
        side: str,
        size_usd: float,
        leverage: float = 1.0,
        take_profit_pct: float = 0.10,
        stop_loss_pct: float = 0.05,
    ) -> Optional[CryptoDerivativePosition]:
        """
        Open a crypto perpetual futures position.

        Args:
            symbol: e.g., "BTC-PERP", "ETH-PERP"
            side: "long" or "short"
            size_usd: Position size in USD
            leverage: Leverage multiplier (1-10x recommended)
            take_profit_pct: Take profit percentage
            stop_loss_pct: Stop loss percentage
        """
        if not symbol.endswith("-PERP"):
            self._add_commentary(f"⚠️ Invalid perpetual symbol: {symbol}", "error")
            return None

        # Get current price
        current_price = await self._get_crypto_price(symbol)

        # Calculate position
        position_id = str(uuid.uuid4())[:8]
        margin_required = size_usd / leverage

        if margin_required > self.cash:
            self._add_commentary(
                f"⚠️ Insufficient margin for {symbol}: need ${margin_required:,.0f}, have ${self.cash:,.0f}",
                "risk"
            )
            return None

        # Calculate liquidation price
        if side == "long":
            liq_price = current_price * (1 - 0.9 / leverage)
            take_profit_price = current_price * (1 + take_profit_pct)
            stop_loss_price = current_price * (1 - stop_loss_pct)
        else:
            liq_price = current_price * (1 + 0.9 / leverage)
            take_profit_price = current_price * (1 - take_profit_pct)
            stop_loss_price = current_price * (1 + stop_loss_pct)

        # Calculate effective delta for the perpetual
        # Long = positive delta, Short = negative delta
        # Delta represents USD exposure per $1 move in underlying
        effective_delta = size_usd / current_price if side == "long" else -size_usd / current_price

        position = CryptoDerivativePosition(
            id=position_id,
            symbol=symbol,
            derivative_type="perpetual",
            side=side,
            entry_price=current_price,
            size=size_usd,
            leverage=leverage,
            current_price=current_price,
            liquidation_price=liq_price,
            take_profit=take_profit_price,
            stop_loss=stop_loss_price,
            delta=effective_delta,  # Set delta for portfolio Greeks
        )

        self.crypto_positions[position_id] = position
        self.cash -= margin_required

        self._add_commentary(
            f"✅ OPENED {side.upper()} {symbol} @ ${current_price:,.0f} | "
            f"Size: ${size_usd:,.0f} | Leverage: {leverage}x | "
            f"Liq: ${liq_price:,.0f}",
            "trade"
        )

        return position

    async def close_crypto_perpetual(self, position_id: str, reason: str = "Manual close"):
        """Close a crypto perpetual position."""
        if position_id not in self.crypto_positions:
            return

        position = self.crypto_positions[position_id]
        position.current_price = await self._get_crypto_price(position.symbol)
        pnl = position.calculate_pnl()

        # Return margin + P&L
        margin = position.size / position.leverage
        self.cash += margin + pnl

        emoji = "💰" if pnl >= 0 else "📉"
        self._add_commentary(
            f"{emoji} CLOSED {position.side.upper()} {position.symbol}: "
            f"P&L ${pnl:+,.2f} | {reason}",
            "trade"
        )

        del self.crypto_positions[position_id]

    async def open_crypto_spot(
        self,
        symbol: str,
        side: str,
        size_usd: float,
        take_profit_pct: float = 0.10,
        stop_loss_pct: float = 0.05,
    ) -> Optional[CryptoDerivativePosition]:
        """
        Open a crypto spot position (buy/sell actual crypto).

        Args:
            symbol: e.g., "BTC", "ETH", "SOL"
            side: "buy" or "sell"
            size_usd: Position size in USD
            take_profit_pct: Take profit percentage
            stop_loss_pct: Stop loss percentage
        """
        # Get current price
        current_price = await self._get_crypto_price(symbol)
        if current_price <= 0:
            self._add_commentary(f"⚠️ Could not get price for {symbol}", "error")
            return None

        if size_usd > self.cash:
            self._add_commentary(
                f"⚠️ Insufficient funds for {symbol}: need ${size_usd:,.0f}, have ${self.cash:,.0f}",
                "risk"
            )
            return None

        # Calculate position
        position_id = str(uuid.uuid4())[:8]
        quantity = size_usd / current_price

        # Calculate take profit and stop loss prices
        if side == "buy":
            take_profit_price = current_price * (1 + take_profit_pct)
            stop_loss_price = current_price * (1 - stop_loss_pct)
        else:  # sell (shorting spot - would need borrowed crypto)
            take_profit_price = current_price * (1 - take_profit_pct)
            stop_loss_price = current_price * (1 + stop_loss_pct)

        position = CryptoDerivativePosition(
            id=position_id,
            symbol=symbol,
            derivative_type="spot",
            side=side,
            entry_price=current_price,
            size=size_usd,
            leverage=1.0,  # No leverage for spot
            current_price=current_price,
            liquidation_price=0,  # No liquidation for spot
            take_profit=take_profit_price,
            stop_loss=stop_loss_price,
        )

        self.crypto_positions[position_id] = position
        self.cash -= size_usd

        self._add_commentary(
            f"✅ SPOT {side.upper()} {quantity:.6f} {symbol} @ ${current_price:,.2f} | "
            f"Value: ${size_usd:,.0f} | TP: ${take_profit_price:,.2f} | SL: ${stop_loss_price:,.2f}",
            "trade"
        )

        return position

    async def open_crypto_option(
        self,
        base_asset: str,  # "BTC" or "ETH"
        option_type: str,  # "call" or "put"
        strike: float,
        expiry_days: int = 30,
        size_usd: float = 5000,
        is_buy: bool = True,
    ) -> Optional[CryptoDerivativePosition]:
        """
        Open a crypto option position (Deribit-style).

        Args:
            base_asset: "BTC" or "ETH"
            option_type: "call" or "put"
            strike: Strike price
            expiry_days: Days to expiration
            size_usd: Notional size in USD
            is_buy: True for long option, False for short (selling)
        """
        if base_asset not in ["BTC", "ETH"]:
            self._add_commentary(f"⚠️ Crypto options only supported for BTC/ETH", "error")
            return None

        # Get current price
        symbol = f"{base_asset}-OPT"
        current_price = await self._get_crypto_price(symbol)

        # Calculate option price using Black-Scholes approximation
        # In production, would use Deribit API for actual IV and prices
        from datetime import timedelta
        import math

        # Simulate crypto IV (typically 50-100% for BTC/ETH)
        iv = 0.65 + np.random.uniform(-0.15, 0.15)
        t = expiry_days / 365
        r = 0.05  # Risk-free rate

        # Black-Scholes for call/put
        d1 = (math.log(current_price / strike) + (r + iv**2 / 2) * t) / (iv * math.sqrt(t))
        d2 = d1 - iv * math.sqrt(t)

        from scipy.stats import norm
        if option_type == "call":
            option_price = current_price * norm.cdf(d1) - strike * math.exp(-r * t) * norm.cdf(d2)
            delta = norm.cdf(d1)
        else:  # put
            option_price = strike * math.exp(-r * t) * norm.cdf(-d2) - current_price * norm.cdf(-d1)
            delta = norm.cdf(d1) - 1

        # Calculate Greeks
        gamma = norm.pdf(d1) / (current_price * iv * math.sqrt(t))
        theta = -(current_price * norm.pdf(d1) * iv) / (2 * math.sqrt(t)) / 365
        vega = current_price * math.sqrt(t) * norm.pdf(d1) / 100

        # Calculate position cost
        contracts = size_usd / current_price
        premium = option_price * contracts

        if is_buy:
            cost = premium
            side = "long"
            max_loss = premium
        else:
            cost = premium * 0.2  # Margin for short options
            side = "short"
            max_loss = size_usd * 0.5  # Simplified max loss for shorts

        if cost > self.cash:
            self._add_commentary(
                f"⚠️ Insufficient funds for {base_asset} {option_type}: need ${cost:,.0f}",
                "risk"
            )
            return None

        position_id = str(uuid.uuid4())[:8]

        position = CryptoDerivativePosition(
            id=position_id,
            symbol=f"{base_asset}-{expiry_days}D-{strike}-{'C' if option_type == 'call' else 'P'}",
            derivative_type=option_type,
            side=side,
            entry_price=option_price,
            size=contracts,
            leverage=1.0,
            current_price=option_price,
            delta=delta * (1 if is_buy else -1),
            gamma=gamma,
            theta=theta * (1 if is_buy else -1),
            vega=vega * (1 if is_buy else -1),
            iv=iv,
        )

        self.crypto_positions[position_id] = position
        self.cash -= cost

        action = "BOUGHT" if is_buy else "SOLD"
        self._add_commentary(
            f"✅ {action} {base_asset} {strike} {option_type.upper()} ({expiry_days}D) | "
            f"Premium: ${premium:,.0f} | Delta: {delta:.2f} | IV: {iv*100:.0f}%",
            "trade"
        )

        return position

    async def close_crypto_option(self, position_id: str, reason: str = "Manual close"):
        """Close a crypto option position."""
        if position_id not in self.crypto_positions:
            return

        position = self.crypto_positions[position_id]

        # Parse option symbol: "ETH-30D-2200-P" -> base_asset, expiry, strike, type
        parts = position.symbol.split("-")
        base_asset = parts[0]
        strike = float(parts[2]) if len(parts) > 2 else 0
        option_type = "put" if parts[-1] == "P" else "call"

        # Get UNDERLYING price from Binance
        underlying_price = await self._get_crypto_price(base_asset)
        if underlying_price == 0:
            underlying_price = strike  # Fallback to strike if no price

        # Calculate current OPTION price using Black-Scholes
        # Use remaining time (simplified: assume some time passed)
        import math
        from scipy.stats import norm

        iv = position.iv if position.iv > 0 else 0.80
        r = 0.05
        t = max(0.01, 7 / 365)  # Assume ~1 week left (simplified)

        d1 = (math.log(underlying_price / strike) + (r + iv**2 / 2) * t) / (iv * math.sqrt(t))
        d2 = d1 - iv * math.sqrt(t)

        if option_type == "call":
            exit_option_price = underlying_price * norm.cdf(d1) - strike * math.exp(-r * t) * norm.cdf(d2)
        else:
            exit_option_price = strike * math.exp(-r * t) * norm.cdf(-d2) - underlying_price * norm.cdf(-d1)

        # Ensure option price is at least intrinsic value
        if option_type == "call":
            intrinsic = max(0, underlying_price - strike)
        else:
            intrinsic = max(0, strike - underlying_price)
        exit_option_price = max(exit_option_price, intrinsic, 0.01)

        # Calculate P&L based on option prices
        pnl = (exit_option_price - position.entry_price) * position.size
        if position.side == "short":
            pnl = -pnl

        self.cash += abs(position.entry_price * position.size) + pnl

        # Store the actual option exit price for logging
        position.current_price = exit_option_price

        emoji = "💰" if pnl >= 0 else "📉"
        self._add_commentary(
            f"{emoji} CLOSED {position.symbol}: P&L ${pnl:+,.2f} | {reason}",
            "trade"
        )

        del self.crypto_positions[position_id]

    def get_crypto_positions(self) -> List[Dict]:
        """Get all crypto derivative positions."""
        return [p.to_dict() for p in self.crypto_positions.values()]

    # ======================
    # STATUS & GETTERS
    # ======================

    def get_status(self) -> Dict:
        """Get current bot status."""
        crypto_pnl = sum(p.calculate_pnl() for p in self.crypto_positions.values())

        return {
            "is_running": self.is_running,
            "mode": self.mode.value,
            "asset_class": "options_and_derivatives",
            "initial_capital": self.initial_capital,
            "cash": round(self.cash, 2),
            "total_value": round(self.total_value + crypto_pnl, 2),
            "total_pnl": round(self.total_pnl + crypto_pnl, 2),
            "total_pnl_pct": round((self.total_pnl + crypto_pnl) / self.initial_capital * 100, 2),
            "positions_count": len(self.positions) + len(self.crypto_positions),
            "options_positions": len(self.positions),
            "crypto_positions": len(self.crypto_positions),
            "trades_count": len(self.trade_history),
            "last_scan": self.last_scan_time.isoformat() if self.last_scan_time else None,
            "risk_summary": self.risk_manager.get_risk_summary(),
            "strategy_info": {
                "preferred_strategies": self.preferred_strategies,
                "target_delta": self.target_delta_per_leg,
                "min_iv_rank": self.min_iv_rank,
                "profit_target": f"{self.profit_target*100:.0f}%",
            },
            "crypto_derivatives": {
                "supported": self.CRYPTO_DERIVATIVES,
                "active_perpetuals": len([p for p in self.crypto_positions.values() if p.derivative_type == "perpetual"]),
            },
        }

    def get_positions(self) -> List[Dict]:
        """Get all current positions."""
        return [p.to_dict() for p in self.positions.values()]

    def get_trades(self, limit: int = 50) -> List[Dict]:
        """Get recent trade history."""
        return [t.to_dict() for t in self.trade_history[-limit:]]

    def get_commentary(self, limit: int = 50) -> List[Dict]:
        """Get recent bot commentary."""
        return self.commentary[-limit:]

    def get_iv_analysis(self) -> Dict[str, Dict]:
        """Get IV analysis for all cached symbols."""
        return {symbol: analysis.to_dict() for symbol, analysis in self.iv_cache.items()}

    def get_performance(self) -> Dict:
        """Calculate performance metrics."""
        if len(self.equity_curve) < 2:
            return {
                "total_return": 0,
                "win_rate": 0,
                "total_trades": 0,
                "current_value": round(self.total_value, 2),
            }

        # Calculate win rate
        closed_trades = [t for t in self.trade_history if t.action == "CLOSE"]
        if closed_trades:
            wins = sum(1 for t in closed_trades if t.pnl > 0)
            win_rate = wins / len(closed_trades) * 100
            avg_win = np.mean([t.pnl for t in closed_trades if t.pnl > 0]) if wins else 0
            avg_loss = np.mean([t.pnl for t in closed_trades if t.pnl <= 0]) if (len(closed_trades) - wins) else 0
        else:
            win_rate = 0
            avg_win = 0
            avg_loss = 0

        return {
            "total_return": round(self.total_pnl_pct * 100, 2),
            "total_pnl": round(self.total_pnl, 2),
            "win_rate": round(win_rate, 1),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "total_trades": len(closed_trades),
            "open_positions": len(self.positions),
            "current_value": round(self.total_value, 2),
            "portfolio_theta": round(self.risk_manager.current_theta, 2),
            "portfolio_delta": round(self.risk_manager.current_delta, 2),
        }


# Singleton instance
_options_bot: Optional[OptionsQuantBot] = None


def get_options_bot() -> OptionsQuantBot:
    """Get or create the singleton OptionsQuantBot instance."""
    global _options_bot
    if _options_bot is None:
        _options_bot = OptionsQuantBot()
    return _options_bot


def create_options_bot(
    capital: float = 100000,
    mode: str = "balanced"
) -> OptionsQuantBot:
    """Create a new OptionsQuantBot instance."""
    global _options_bot

    mode_map = {
        "aggressive": OptionsMode.AGGRESSIVE,
        "balanced": OptionsMode.BALANCED,
        "conservative": OptionsMode.CONSERVATIVE,
    }

    _options_bot = OptionsQuantBot(
        initial_capital=capital,
        mode=mode_map.get(mode, OptionsMode.BALANCED)
    )
    return _options_bot
