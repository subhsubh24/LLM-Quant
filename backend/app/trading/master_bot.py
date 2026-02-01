"""
Master Quant Bot - Unified Autonomous Trading System

A professional-grade trading bot that intelligently allocates capital across:
- Stock/ETF Options (SPY, QQQ, AAPL, etc.)
- Crypto Perpetuals (BTC-PERP, ETH-PERP)
- Crypto Options (BTC/ETH calls/puts)
- Commodities (GLD, SLV, USO options)

The bot continuously scans all markets, ranks opportunities by expected return,
and autonomously manages positions with institutional-grade risk management.

PAPER TRADING / EDUCATIONAL purposes only.
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Tuple
import numpy as np

from .options_bot import (
    OptionsQuantBot,
    OptionsMode,
    OptionsPosition,
    OptionsTrade,
    CryptoDerivativePosition,
    IVAnalysis,
    create_options_bot,
)

logger = logging.getLogger(__name__)


class AssetClass(Enum):
    """Asset classes the bot can trade."""
    STOCK_OPTIONS = "stock_options"
    ETF_OPTIONS = "etf_options"
    COMMODITY_OPTIONS = "commodity_options"
    CRYPTO_PERPETUAL = "crypto_perpetual"
    CRYPTO_OPTIONS = "crypto_options"


class MarketRegime(Enum):
    """Current market regime affecting strategy selection."""
    HIGH_VOLATILITY = "high_volatility"     # VIX > 25 - sell premium
    LOW_VOLATILITY = "low_volatility"       # VIX < 15 - buy premium
    TRENDING_UP = "trending_up"             # Bullish bias
    TRENDING_DOWN = "trending_down"         # Bearish bias
    RANGE_BOUND = "range_bound"             # Neutral strategies


@dataclass
class Opportunity:
    """A scored trading opportunity across any asset class."""
    symbol: str
    asset_class: AssetClass
    strategy: str
    expected_return: float  # Annual expected return %
    max_profit: float
    max_loss: float
    probability_of_profit: float  # 0-1
    risk_reward_ratio: float
    iv_rank: float
    score: float  # Combined opportunity score
    rationale: str

    def to_dict(self) -> Dict:
        return {
            "symbol": self.symbol,
            "asset_class": self.asset_class.value,
            "strategy": self.strategy,
            "expected_return": round(self.expected_return, 2),
            "max_profit": round(self.max_profit, 2),
            "max_loss": round(self.max_loss, 2),
            "probability_of_profit": round(self.probability_of_profit * 100, 1),
            "risk_reward_ratio": round(self.risk_reward_ratio, 2),
            "iv_rank": round(self.iv_rank, 1),
            "score": round(self.score, 2),
            "rationale": self.rationale,
        }


class MasterQuantBot:
    """
    Unified Autonomous Trading Bot

    Scans ALL markets, ranks opportunities, and trades intelligently across:
    - Stock Options (AAPL, MSFT, NVDA, etc.)
    - ETF Options (SPY, QQQ, IWM)
    - Commodity Options (GLD, SLV, USO)
    - Crypto Perpetuals (BTC, ETH, SOL)
    - Crypto Options (BTC/ETH calls and puts)

    One button to start, then it runs autonomously.
    """

    # Full universe of tradeable assets
    STOCK_OPTIONS = [
        "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "AMD",
        "NFLX", "CRM", "INTC", "PYPL", "SQ", "COIN", "V", "MA", "JPM", "BAC",
    ]

    ETF_OPTIONS = [
        "SPY", "QQQ", "IWM", "DIA", "XLK", "XLF", "XLE", "XLV", "XLU", "XLI",
    ]

    COMMODITY_OPTIONS = [
        "GLD", "SLV", "GDX", "USO", "UNG", "WEAT", "CORN",
    ]

    CRYPTO_PERPETUALS = [
        "BTC-PERP", "ETH-PERP", "SOL-PERP", "AVAX-PERP", "LINK-PERP",
    ]

    CRYPTO_OPTIONS = ["BTC", "ETH"]  # For Deribit-style options

    def __init__(
        self,
        initial_capital: float = 100000.0,
        mode: str = "balanced",
    ):
        self.initial_capital = initial_capital
        self.mode = OptionsMode(mode)
        self.is_running = False
        self._task: Optional[asyncio.Task] = None

        # Core trading engine (uses OptionsQuantBot as foundation)
        self.engine = create_options_bot(capital=initial_capital, mode=mode)

        # Market state
        self.market_regime = MarketRegime.RANGE_BOUND
        self.vix_level = 18.0  # Simulated VIX

        # Opportunity tracking
        self.opportunities: List[Opportunity] = []
        self.last_full_scan: Optional[datetime] = None

        # Allocation limits by asset class
        self.allocation_limits = {
            AssetClass.STOCK_OPTIONS: 0.30,      # 30% max
            AssetClass.ETF_OPTIONS: 0.35,        # 35% max
            AssetClass.COMMODITY_OPTIONS: 0.15,  # 15% max
            AssetClass.CRYPTO_PERPETUAL: 0.15,   # 15% max
            AssetClass.CRYPTO_OPTIONS: 0.10,     # 10% max
        }

        # Current allocations
        self.current_allocations: Dict[AssetClass, float] = {
            ac: 0.0 for ac in AssetClass
        }

        # Performance tracking
        self.daily_pnl: List[Tuple[datetime, float]] = []

        # Commentary for UI
        self.commentary: List[Dict] = []

        logger.info(f"MasterQuantBot initialized: ${initial_capital:,.0f}, mode={mode}")
        self._add_commentary(
            f"🚀 MASTER BOT INITIALIZED: ${initial_capital:,.0f} capital, {mode} mode",
            "system"
        )

    # ===================
    # MARKET ANALYSIS
    # ===================

    async def _assess_market_regime(self):
        """Assess current market conditions to determine regime."""
        # Simulate VIX (in production, would fetch from data provider)
        self.vix_level = 15 + np.random.uniform(-5, 15)

        if self.vix_level > 25:
            self.market_regime = MarketRegime.HIGH_VOLATILITY
            self._add_commentary(
                f"📊 Market Regime: HIGH VOLATILITY (VIX: {self.vix_level:.1f}) - Favoring premium selling",
                "analysis"
            )
        elif self.vix_level < 15:
            self.market_regime = MarketRegime.LOW_VOLATILITY
            self._add_commentary(
                f"📊 Market Regime: LOW VOLATILITY (VIX: {self.vix_level:.1f}) - Favoring premium buying",
                "analysis"
            )
        else:
            self.market_regime = MarketRegime.RANGE_BOUND
            self._add_commentary(
                f"📊 Market Regime: RANGE BOUND (VIX: {self.vix_level:.1f}) - Balanced approach",
                "analysis"
            )

    # ===================
    # OPPORTUNITY SCANNING
    # ===================

    async def _scan_all_markets(self) -> List[Opportunity]:
        """Scan ALL markets and return ranked opportunities."""
        opportunities = []

        self._add_commentary("🔍 Starting full market scan across all asset classes...", "scan")

        # 1. Scan Stock Options
        stock_opps = await self._scan_stock_options()
        opportunities.extend(stock_opps)

        # 2. Scan ETF Options
        etf_opps = await self._scan_etf_options()
        opportunities.extend(etf_opps)

        # 3. Scan Commodity Options
        commodity_opps = await self._scan_commodity_options()
        opportunities.extend(commodity_opps)

        # 4. Scan Crypto Perpetuals
        crypto_perp_opps = await self._scan_crypto_perpetuals()
        opportunities.extend(crypto_perp_opps)

        # 5. Scan Crypto Options
        crypto_opt_opps = await self._scan_crypto_options()
        opportunities.extend(crypto_opt_opps)

        # Sort by score (highest first)
        opportunities.sort(key=lambda x: x.score, reverse=True)

        self._add_commentary(
            f"✅ Scan complete: {len(opportunities)} opportunities found across {len(AssetClass)} asset classes",
            "scan"
        )

        self.opportunities = opportunities
        self.last_full_scan = datetime.now()

        return opportunities

    async def _scan_stock_options(self) -> List[Opportunity]:
        """Scan stock options for opportunities."""
        opportunities = []

        for symbol in self.STOCK_OPTIONS[:10]:  # Top 10
            iv_analysis = await self.engine._analyze_iv(symbol)
            self.engine.iv_cache[symbol] = iv_analysis

            opp = self._score_options_opportunity(
                symbol, iv_analysis, AssetClass.STOCK_OPTIONS
            )
            if opp and opp.score > 50:
                opportunities.append(opp)

        return opportunities

    async def _scan_etf_options(self) -> List[Opportunity]:
        """Scan ETF options for opportunities."""
        opportunities = []

        for symbol in self.ETF_OPTIONS:
            iv_analysis = await self.engine._analyze_iv(symbol)
            self.engine.iv_cache[symbol] = iv_analysis

            opp = self._score_options_opportunity(
                symbol, iv_analysis, AssetClass.ETF_OPTIONS
            )
            if opp and opp.score > 50:
                opportunities.append(opp)

        return opportunities

    async def _scan_commodity_options(self) -> List[Opportunity]:
        """Scan commodity options for opportunities."""
        opportunities = []

        for symbol in self.COMMODITY_OPTIONS:
            iv_analysis = await self.engine._analyze_iv(symbol)
            self.engine.iv_cache[symbol] = iv_analysis

            opp = self._score_options_opportunity(
                symbol, iv_analysis, AssetClass.COMMODITY_OPTIONS
            )
            if opp and opp.score > 45:  # Lower threshold for commodities
                opportunities.append(opp)

        return opportunities

    async def _scan_crypto_perpetuals(self) -> List[Opportunity]:
        """Scan crypto perpetuals for opportunities."""
        opportunities = []

        for symbol in self.CRYPTO_PERPETUALS:
            opp = await self._score_crypto_perpetual(symbol)
            if opp and opp.score > 40:
                opportunities.append(opp)

        return opportunities

    async def _scan_crypto_options(self) -> List[Opportunity]:
        """Scan crypto options for opportunities."""
        opportunities = []

        for base_asset in self.CRYPTO_OPTIONS:
            # Check call opportunities
            call_opp = await self._score_crypto_option(base_asset, "call")
            if call_opp and call_opp.score > 45:
                opportunities.append(call_opp)

            # Check put opportunities
            put_opp = await self._score_crypto_option(base_asset, "put")
            if put_opp and put_opp.score > 45:
                opportunities.append(put_opp)

        return opportunities

    # ===================
    # OPPORTUNITY SCORING
    # ===================

    def _score_options_opportunity(
        self,
        symbol: str,
        iv_analysis: IVAnalysis,
        asset_class: AssetClass
    ) -> Optional[Opportunity]:
        """Score an options opportunity."""
        # Determine strategy based on IV and regime
        if iv_analysis.iv_rank > 50 or self.market_regime == MarketRegime.HIGH_VOLATILITY:
            strategy = "Iron Condor"
            expected_return = 25 + iv_analysis.iv_rank * 0.3
            probability = 0.70 + (iv_analysis.iv_rank - 50) * 0.002
            max_profit = 200 + iv_analysis.iv_rank * 3
            max_loss = 500
            rationale = f"High IV Rank ({iv_analysis.iv_rank:.0f}%) - selling premium"
        elif iv_analysis.iv_rank < 25:
            strategy = "Long Straddle"
            expected_return = 15 + (25 - iv_analysis.iv_rank) * 0.5
            probability = 0.45
            max_profit = 1000
            max_loss = 300
            rationale = f"Low IV Rank ({iv_analysis.iv_rank:.0f}%) - buying cheap premium"
        else:
            strategy = "Vertical Spread"
            expected_return = 20
            probability = 0.55
            max_profit = 300
            max_loss = 200
            rationale = f"Moderate IV ({iv_analysis.iv_rank:.0f}%) - directional play"

        # Calculate composite score
        risk_reward = max_profit / max_loss if max_loss > 0 else 0

        score = (
            expected_return * 0.3 +
            probability * 100 * 0.25 +
            iv_analysis.iv_rank * 0.2 +
            risk_reward * 10 * 0.15 +
            (30 if asset_class == AssetClass.ETF_OPTIONS else 20) * 0.1  # Liquidity bonus
        )

        return Opportunity(
            symbol=symbol,
            asset_class=asset_class,
            strategy=strategy,
            expected_return=expected_return,
            max_profit=max_profit,
            max_loss=max_loss,
            probability_of_profit=probability,
            risk_reward_ratio=risk_reward,
            iv_rank=iv_analysis.iv_rank,
            score=score,
            rationale=rationale,
        )

    async def _score_crypto_perpetual(self, symbol: str) -> Optional[Opportunity]:
        """Score a crypto perpetual opportunity."""
        base = symbol.split("-")[0]
        price = await self.engine._get_crypto_price(symbol)

        # Simulate funding rate analysis
        funding_rate = np.random.uniform(-0.001, 0.003)  # -0.1% to 0.3%

        if funding_rate > 0.001:
            # Positive funding = short bias
            strategy = "Short Perpetual"
            side = "short"
            expected_return = funding_rate * 365 * 100 * 3  # Annualized with 3x
            probability = 0.55
            rationale = f"High funding rate ({funding_rate*100:.3f}%) - short bias"
        elif funding_rate < -0.0005:
            strategy = "Long Perpetual"
            side = "long"
            expected_return = abs(funding_rate) * 365 * 100 * 3
            probability = 0.55
            rationale = f"Negative funding ({funding_rate*100:.3f}%) - long bias"
        else:
            # Neutral - look at trend
            strategy = "Long Perpetual"
            expected_return = 15
            probability = 0.50
            rationale = "Neutral funding - trend following"

        max_profit = price * 0.10  # 10% move
        max_loss = price * 0.05   # 5% stop
        risk_reward = max_profit / max_loss

        score = (
            expected_return * 0.35 +
            probability * 100 * 0.25 +
            risk_reward * 15 * 0.2 +
            20 * 0.2  # Crypto volatility bonus
        )

        return Opportunity(
            symbol=symbol,
            asset_class=AssetClass.CRYPTO_PERPETUAL,
            strategy=strategy,
            expected_return=expected_return,
            max_profit=max_profit,
            max_loss=max_loss,
            probability_of_profit=probability,
            risk_reward_ratio=risk_reward,
            iv_rank=65,  # Crypto always high IV
            score=score,
            rationale=rationale,
        )

    async def _score_crypto_option(self, base_asset: str, option_type: str) -> Optional[Opportunity]:
        """Score a crypto option opportunity."""
        symbol = f"{base_asset}-OPT"
        price = await self.engine._get_crypto_price(symbol)

        # Crypto options typically high IV
        iv = 0.65 + np.random.uniform(-0.1, 0.2)

        if iv > 0.70:
            # High IV - sell premium
            strategy = f"Sell {base_asset} {option_type.title()}"
            expected_return = 35
            probability = 0.65
            max_profit = price * 0.05
            max_loss = price * 0.15
            rationale = f"High crypto IV ({iv*100:.0f}%) - selling premium"
        else:
            strategy = f"Buy {base_asset} {option_type.title()}"
            expected_return = 25
            probability = 0.40
            max_profit = price * 0.20
            max_loss = price * 0.03
            rationale = f"Lower crypto IV ({iv*100:.0f}%) - directional play"

        risk_reward = max_profit / max_loss if max_loss > 0 else 0

        score = (
            expected_return * 0.3 +
            probability * 100 * 0.25 +
            iv * 100 * 0.2 +
            risk_reward * 10 * 0.15 +
            15 * 0.1  # Crypto option liquidity
        )

        return Opportunity(
            symbol=f"{base_asset}-{option_type.upper()}",
            asset_class=AssetClass.CRYPTO_OPTIONS,
            strategy=strategy,
            expected_return=expected_return,
            max_profit=max_profit,
            max_loss=max_loss,
            probability_of_profit=probability,
            risk_reward_ratio=risk_reward,
            iv_rank=iv * 100,
            score=score,
            rationale=rationale,
        )

    # ===================
    # TRADE EXECUTION
    # ===================

    async def _execute_best_opportunities(self):
        """Execute the best opportunities respecting allocation limits."""
        if not self.opportunities:
            return

        executed = 0
        max_new_positions = 3  # Max new positions per cycle

        for opp in self.opportunities[:10]:  # Consider top 10
            if executed >= max_new_positions:
                break

            # Check allocation limit
            current_alloc = self.current_allocations.get(opp.asset_class, 0)
            limit = self.allocation_limits.get(opp.asset_class, 0.20)

            if current_alloc >= limit:
                continue

            # Check if already have position in this symbol
            if self._has_position(opp.symbol):
                continue

            # Execute based on asset class
            success = await self._execute_opportunity(opp)

            if success:
                executed += 1
                # Update allocation
                position_size = opp.max_loss / self.initial_capital
                self.current_allocations[opp.asset_class] = current_alloc + position_size

        if executed > 0:
            self._add_commentary(
                f"📈 Executed {executed} new positions from top opportunities",
                "execution"
            )

    async def _execute_opportunity(self, opp: Opportunity) -> bool:
        """Execute a single opportunity."""
        try:
            if opp.asset_class in [AssetClass.STOCK_OPTIONS, AssetClass.ETF_OPTIONS, AssetClass.COMMODITY_OPTIONS]:
                # Use options engine
                iv_analysis = self.engine.iv_cache.get(opp.symbol)
                if not iv_analysis:
                    return False

                signal = self.engine._generate_signal(opp.symbol, iv_analysis)
                if signal:
                    await self.engine._execute_signal(opp.symbol, signal, iv_analysis)
                    return True

            elif opp.asset_class == AssetClass.CRYPTO_PERPETUAL:
                side = "long" if "Long" in opp.strategy else "short"
                position = await self.engine.open_crypto_perpetual(
                    symbol=opp.symbol,
                    side=side,
                    size_usd=min(5000, self.engine.cash * 0.05),
                    leverage=2.0,
                )
                return position is not None

            elif opp.asset_class == AssetClass.CRYPTO_OPTIONS:
                base = opp.symbol.split("-")[0]
                opt_type = "call" if "CALL" in opp.symbol or "Call" in opp.strategy else "put"
                is_buy = "Buy" in opp.strategy

                price = await self.engine._get_crypto_price(f"{base}-OPT")
                strike = round(price * (1.05 if opt_type == "call" else 0.95), -2)

                position = await self.engine.open_crypto_option(
                    base_asset=base,
                    option_type=opt_type,
                    strike=strike,
                    expiry_days=30,
                    size_usd=min(3000, self.engine.cash * 0.03),
                    is_buy=is_buy,
                )
                return position is not None

        except Exception as e:
            logger.error(f"Failed to execute {opp.symbol}: {e}")
            return False

        return False

    def _has_position(self, symbol: str) -> bool:
        """Check if already have a position in this symbol."""
        # Check options positions
        for pos in self.engine.positions.values():
            if pos.symbol == symbol:
                return True

        # Check crypto positions
        for pos in self.engine.crypto_positions.values():
            if symbol in pos.symbol:
                return True

        return False

    # ===================
    # BOT LIFECYCLE
    # ===================

    async def start(self):
        """Start the Master Quant Bot."""
        if self.is_running:
            return

        self.is_running = True
        await self.engine.start()

        self._add_commentary(
            "🚀 MASTER BOT STARTED - Scanning all markets for opportunities",
            "system"
        )

        # Start main loop
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self):
        """Stop the Master Quant Bot."""
        self.is_running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        await self.engine.stop()

        self._add_commentary(
            "🛑 MASTER BOT STOPPED - All trading halted",
            "system"
        )

    async def _run_loop(self):
        """Main trading loop."""
        scan_interval = 60  # Full scan every 60 seconds
        position_check_interval = 30  # Check positions every 30 seconds

        last_scan = datetime.min
        last_position_check = datetime.min

        while self.is_running:
            try:
                now = datetime.now()

                # Full market scan
                if (now - last_scan).seconds >= scan_interval:
                    await self._assess_market_regime()
                    await self._scan_all_markets()
                    await self._execute_best_opportunities()
                    last_scan = now

                # Position management
                if (now - last_position_check).seconds >= position_check_interval:
                    await self._manage_positions()
                    last_position_check = now

                await asyncio.sleep(5)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in master bot loop: {e}")
                await asyncio.sleep(10)

    async def _manage_positions(self):
        """Manage all open positions."""
        # Delegate to options engine for options positions
        await self.engine._check_exits()
        await self.engine._update_positions()

        # Check crypto positions for stop loss / take profit
        for pos_id, pos in list(self.engine.crypto_positions.items()):
            pos.current_price = await self.engine._get_crypto_price(pos.symbol)

            # Check stop loss
            if pos.side == "long" and pos.current_price <= pos.stop_loss:
                await self.engine.close_crypto_perpetual(pos_id, "Stop loss hit")
            elif pos.side == "short" and pos.current_price >= pos.stop_loss:
                await self.engine.close_crypto_perpetual(pos_id, "Stop loss hit")

            # Check take profit
            if pos.side == "long" and pos.current_price >= pos.take_profit:
                await self.engine.close_crypto_perpetual(pos_id, "Take profit hit")
            elif pos.side == "short" and pos.current_price <= pos.take_profit:
                await self.engine.close_crypto_perpetual(pos_id, "Take profit hit")

    # ===================
    # STATUS & GETTERS
    # ===================

    def _add_commentary(self, message: str, category: str):
        """Add commentary for UI."""
        self.commentary.append({
            "timestamp": datetime.now().isoformat(),
            "message": message,
            "category": category,
        })
        if len(self.commentary) > 100:
            self.commentary = self.commentary[-100:]

        # Also add to engine commentary
        self.engine._add_commentary(message, category)

    def get_status(self) -> Dict:
        """Get comprehensive bot status."""
        engine_status = self.engine.get_status()

        return {
            "is_running": self.is_running,
            "mode": self.mode.value,
            "market_regime": self.market_regime.value,
            "vix_level": round(self.vix_level, 1),
            "initial_capital": self.initial_capital,
            "cash": engine_status["cash"],
            "total_value": engine_status["total_value"],
            "total_pnl": engine_status["total_pnl"],
            "total_pnl_pct": engine_status["total_pnl_pct"],
            "positions": {
                "options": engine_status["options_positions"],
                "crypto": engine_status["crypto_positions"],
                "total": engine_status["positions_count"],
            },
            "allocations": {
                ac.value: round(alloc * 100, 1)
                for ac, alloc in self.current_allocations.items()
            },
            "last_scan": self.last_full_scan.isoformat() if self.last_full_scan else None,
            "opportunities_count": len(self.opportunities),
            "risk_summary": engine_status["risk_summary"],
        }

    def get_opportunities(self, limit: int = 20) -> List[Dict]:
        """Get top ranked opportunities."""
        return [opp.to_dict() for opp in self.opportunities[:limit]]

    def get_all_positions(self) -> Dict:
        """Get all positions across all asset classes."""
        return {
            "options_positions": self.engine.get_positions(),
            "crypto_positions": self.engine.get_crypto_positions(),
        }

    def get_commentary(self, limit: int = 50) -> List[Dict]:
        """Get bot commentary."""
        return self.commentary[-limit:]

    def get_performance(self) -> Dict:
        """Get performance metrics."""
        engine_perf = self.engine.get_performance()

        return {
            **engine_perf,
            "market_regime": self.market_regime.value,
            "vix_level": round(self.vix_level, 1),
            "opportunities_scanned": len(self.opportunities),
            "allocation_efficiency": sum(self.current_allocations.values()) * 100,
        }


# Singleton instance
_master_bot: Optional[MasterQuantBot] = None


def get_master_bot() -> MasterQuantBot:
    """Get or create the Master Quant Bot singleton."""
    global _master_bot
    if _master_bot is None:
        _master_bot = MasterQuantBot()
    return _master_bot


def create_master_bot(
    capital: float = 100000,
    mode: str = "balanced"
) -> MasterQuantBot:
    """Create a new Master Quant Bot instance."""
    global _master_bot
    _master_bot = MasterQuantBot(initial_capital=capital, mode=mode)
    return _master_bot
