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
import uuid
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from enum import Enum
from typing import Dict, List, Optional, Any, Tuple
import numpy as np

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
            "current_iv": round(self.current_iv * 100, 1),
            "iv_rank": round(self.iv_rank, 1),
            "iv_percentile": round(self.iv_percentile, 1),
            "iv_30_day_avg": round(self.iv_30_day_avg * 100, 1),
            "iv_trend": self.iv_trend,
            "hv_iv_spread": round(self.hv_iv_spread * 100, 1),
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
            "entry_iv": round(self.entry_iv * 100, 1),
            "entry_price": round(self.entry_underlying_price, 2),
            "current_price": round(self.current_underlying_price, 2),
            "current_pnl": round(self.current_pnl, 2),
            "days_in_trade": self.days_in_trade,
            "max_profit": round(self.max_profit, 2),
            "max_loss": round(self.max_loss, 2),
            "greeks": {
                "delta": round(self.current_delta, 2),
                "theta": round(self.current_theta, 2),
                "vega": round(self.current_vega, 2),
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
            "net_premium": round(self.net_premium, 2),
            "pnl": round(self.pnl, 2),
            "rationale": self.rationale,
            "iv_at_trade": round(self.iv_at_trade * 100, 1),
            "underlying_at_trade": round(self.underlying_at_trade, 2),
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

    def update_portfolio_greeks(self, positions: List[OptionsPosition]):
        """Update aggregate portfolio Greeks."""
        self.current_delta = sum(p.current_delta for p in positions)
        self.current_theta = sum(p.current_theta for p in positions)
        self.current_vega = sum(p.current_vega for p in positions)

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
        # Mega-cap tech (most liquid options)
        "SPY", "QQQ", "IWM", "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA",
        # Commodities ETFs
        "GLD", "SLV", "USO", "XLE",
        # Volatility
        "VIX",
        # Financials
        "XLF", "JPM", "BAC",
        # Other liquid names
        "AMD", "NFLX", "DIS", "BA", "V", "MA",
    ]

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

        # Positions and trades
        self.positions: Dict[str, OptionsPosition] = {}
        self.trade_history: List[OptionsTrade] = []

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
        """Configure parameters based on trading mode."""
        if self.mode == OptionsMode.AGGRESSIVE:
            self.target_delta_per_leg = 0.30      # 30 delta options
            self.min_iv_rank = 30                  # Lower IV threshold
            self.profit_target = 0.50              # 50% of max profit
            self.max_positions = 15
            self.preferred_strategies = [
                "iron_condor", "strangle", "straddle", "vertical"
            ]
        elif self.mode == OptionsMode.BALANCED:
            self.target_delta_per_leg = 0.20      # 20 delta options (safer)
            self.min_iv_rank = 40                  # Moderate IV threshold
            self.profit_target = 0.50
            self.max_positions = 10
            self.preferred_strategies = [
                "iron_condor", "butterfly", "vertical", "calendar"
            ]
        else:  # CONSERVATIVE
            self.target_delta_per_leg = 0.15      # 15 delta options (very safe)
            self.min_iv_rank = 50                  # High IV only
            self.profit_target = 0.40              # 40% of max profit
            self.max_positions = 6
            self.preferred_strategies = [
                "iron_condor", "butterfly", "covered_call"
            ]

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

        # Update risk manager
        self.risk_manager.update_portfolio_greeks(list(self.positions.values()))

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
        """Scan for new trading opportunities."""
        for symbol in self.OPTIONS_UNIVERSE[:15]:  # Top 15 most liquid
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
        Analyze implied volatility for a symbol.

        In production, this would use historical IV data.
        For now, we simulate based on recent price movements.
        """
        # Get current price
        current_price = await self._get_underlying_price(symbol)

        # Simulate IV (in real system, use options chain data)
        # Base IV varies by symbol type
        if symbol in ["SPY", "QQQ", "IWM"]:
            base_iv = 0.15 + np.random.uniform(-0.03, 0.05)
        elif symbol == "VIX":
            base_iv = 0.80 + np.random.uniform(-0.10, 0.20)
        elif symbol in ["TSLA", "NVDA", "AMD"]:
            base_iv = 0.40 + np.random.uniform(-0.08, 0.12)
        else:
            base_iv = 0.25 + np.random.uniform(-0.05, 0.08)

        # Simulate IV rank (would use 52-week data in production)
        iv_rank = np.random.uniform(20, 80)

        # Simulate HV-IV spread
        hv = base_iv * (0.8 + np.random.uniform(0, 0.4))
        hv_iv_spread = base_iv - hv

        return IVAnalysis(
            symbol=symbol,
            current_iv=base_iv,
            iv_rank=iv_rank,
            iv_percentile=iv_rank * 0.95,  # Simplified
            iv_30_day_avg=base_iv * 0.95,
            iv_trend="stable" if abs(np.random.randn()) < 1 else ("rising" if np.random.randn() > 0 else "falling"),
            hv_iv_spread=hv_iv_spread,
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
        # Calculate strikes based on delta targets
        # Short strikes at ~20 delta, wings 5-10 points wider

        call_short_strike = round(underlying_price * (1 + 0.05), 0)  # 5% OTM
        call_long_strike = call_short_strike + 5
        put_short_strike = round(underlying_price * (1 - 0.05), 0)   # 5% OTM
        put_long_strike = put_short_strike - 5

        expiration_days = 45  # ~45 DTE optimal for iron condors

        return self.options_manager.create_iron_condor(
            symbol=symbol,
            underlying_price=underlying_price,
            put_short_strike=put_short_strike,
            put_long_strike=put_long_strike,
            call_short_strike=call_short_strike,
            call_long_strike=call_long_strike,
            expiration_days=expiration_days,
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
        strike = round(underlying_price, 0)  # ATM strike
        expiration_days = 30  # ~30 DTE for straddles

        return self.options_manager.create_straddle(
            symbol=symbol,
            underlying_price=underlying_price,
            strike=strike,
            expiration_days=expiration_days,
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
        if bullish:
            long_strike = round(underlying_price * 0.98, 0)   # Slightly ITM
            short_strike = round(underlying_price * 1.02, 0)  # Slightly OTM

            return self.options_manager.create_bull_call_spread(
                symbol=symbol,
                underlying_price=underlying_price,
                long_strike=long_strike,
                short_strike=short_strike,
                expiration_days=30,
                volatility=iv_analysis.current_iv,
            )
        else:
            long_strike = round(underlying_price * 1.02, 0)
            short_strike = round(underlying_price * 0.98, 0)

            return self.options_manager.create_bear_put_spread(
                symbol=symbol,
                underlying_price=underlying_price,
                long_strike=long_strike,
                short_strike=short_strike,
                expiration_days=30,
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
        """Open a new options position."""
        # Check risk limits
        buying_power_required = abs(strategy.max_loss) if strategy.max_loss else 1000
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
            max_profit=strategy.max_profit or 0,
            max_loss=strategy.max_loss or 0,
            profit_target_pct=self.profit_target,
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
            f"✅ OPENED {strategy_name} on {symbol}: "
            f"Max Profit ${position.max_profit:,.0f} / Max Loss ${position.max_loss:,.0f} | "
            f"IV: {iv_analysis.current_iv*100:.1f}%",
            "trade"
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
        """Get current underlying price."""
        # In production, would use live data service
        # For now, return simulated prices
        base_prices = {
            "SPY": 480, "QQQ": 420, "IWM": 200, "AAPL": 185, "MSFT": 420,
            "GOOGL": 155, "AMZN": 185, "NVDA": 880, "META": 500, "TSLA": 250,
            "GLD": 195, "SLV": 22, "USO": 75, "XLE": 85, "VIX": 15,
            "XLF": 40, "JPM": 195, "BAC": 35, "AMD": 165, "NFLX": 610,
            "DIS": 110, "BA": 180, "V": 280, "MA": 460,
        }
        base = base_prices.get(symbol, 100)
        # Add small random movement
        return base * (1 + np.random.uniform(-0.01, 0.01))

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

    def get_status(self) -> Dict:
        """Get current bot status."""
        return {
            "is_running": self.is_running,
            "mode": self.mode.value,
            "asset_class": "options",
            "initial_capital": self.initial_capital,
            "cash": round(self.cash, 2),
            "total_value": round(self.total_value, 2),
            "total_pnl": round(self.total_pnl, 2),
            "total_pnl_pct": round(self.total_pnl_pct * 100, 2),
            "positions_count": len(self.positions),
            "trades_count": len(self.trade_history),
            "last_scan": self.last_scan_time.isoformat() if self.last_scan_time else None,
            "risk_summary": self.risk_manager.get_risk_summary(),
            "strategy_info": {
                "preferred_strategies": self.preferred_strategies,
                "target_delta": self.target_delta_per_leg,
                "min_iv_rank": self.min_iv_rank,
                "profit_target": f"{self.profit_target*100:.0f}%",
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
