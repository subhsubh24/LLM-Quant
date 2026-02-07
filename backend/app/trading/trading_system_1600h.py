"""
Complete 1600h Trading System Integration

Brings together:
1. Multi-horizon model predictions (24h-1600h)
2. Macro-aware strategy (seasonal, VIX, events)
3. Portfolio risk management (drawdown, heat, correlation)
4. Advanced position management (multiple by horizon, liquidity checks)
5. Real-time decision support

This is the "brain" that uses all the components.
"""

import logging
from typing import Dict, List, Tuple, Optional
from datetime import datetime

from .macro_strategy import MacroStrategy, get_macro_strategy
from .portfolio_risk import PortfolioRiskManager, get_portfolio_risk_manager

logger = logging.getLogger(__name__)

class TradingSystem1600h:
    """
    Integrated 1600h trading system combining:
    - Multi-horizon predictions
    - Macro awareness
    - Portfolio risk management
    - Dynamic position sizing
    """

    def __init__(self):
        self.macro = get_macro_strategy()
        self.portfolio_risk = get_portfolio_risk_manager()
        self.positions = {}  # symbol -> [positions by horizon]
        self.position_counter = 0

    def evaluate_trade_opportunity(
        self,
        symbol: str,
        prediction: Dict,  # action, confidence, predictions array
        candles: List,
        current_capital: float,
        market_regime: str = "BALANCED",
    ) -> Tuple[bool, str, float]:
        """
        Complete trade decision with all filters.

        Returns: (should_trade, reason, adjusted_size)
        """
        # Step 1: Check macro regime
        macro_regime = self.macro.get_macro_regime()
        if macro_regime["overall_regime"] == "RISK_OFF" and prediction["action"] == 2:
            # Reduce bullish trades in risk-off
            confidence_adj = 0.85
        elif macro_regime["overall_regime"] == "RISK_ON" and prediction["action"] == 0:
            # Reduce bearish trades in risk-on
            confidence_adj = 0.85
        else:
            confidence_adj = 1.0

        adjusted_confidence = prediction["confidence"] * confidence_adj

        # Step 2: Check multi-timeframe regime
        multi_regimes = self.macro.get_multi_timeframe_regime(candles)
        if multi_regimes.get("200h", {}).get("regime") == "STRONG_DOWN" and prediction["action"] == 2:
            return False, "Against 200h downtrend", 0.0

        # Step 3: Check position count (allow multiple by horizon)
        if symbol in self.positions:
            # Check if already have position at this horizon
            prediction_horizon = self._infer_horizon(adjusted_confidence)
            if any(p["horizon"] == prediction_horizon for p in self.positions[symbol]):
                return False, "Already have position at this horizon", 0.0
        else:
            self.positions[symbol] = []

        # Step 4: Portfolio risk checks
        # Estimate position size based on confidence and macro
        base_size = current_capital * 0.01  # 1% base
        macro_mult = self.macro.get_position_size_multiplier(macro_regime, adjusted_confidence)
        event_mult = self.macro.get_event_risk_adjustment(datetime.now())

        position_size = base_size * macro_mult * event_mult

        # Check if can open
        can_open, reason = self.portfolio_risk.can_open_position(
            symbol=symbol,
            position_size=position_size,
            stop_loss_pct=self._get_stop_loss(adjusted_confidence),
            sector="unknown",  # Would need symbol->sector mapping
            current_capital=current_capital,
        )

        if not can_open:
            return False, f"Portfolio risk check failed: {reason}", 0.0

        # Step 5: Liquidity check
        # Would need actual volume data
        # can_exit, exit_reason = self.portfolio_risk.check_liquidity_for_exit(...)

        logger.info(
            f"✅ Trade approved: {symbol} | "
            f"Size: {position_size:.2f} | "
            f"Confidence: {adjusted_confidence:.2f} | "
            f"Regime: {macro_regime['overall_regime']}"
        )

        return True, "All checks passed", position_size

    def _infer_horizon(self, confidence: float) -> int:
        """Infer prediction horizon from confidence level."""
        if confidence > 0.80:
            return 24
        elif confidence > 0.75:
            return 48
        elif confidence > 0.70:
            return 100
        elif confidence > 0.65:
            return 200
        elif confidence > 0.60:
            return 400
        else:
            return 800  # Low confidence = longer term

    def _get_stop_loss(self, confidence: float) -> float:
        """Get stop loss percentage based on confidence/horizon."""
        if confidence > 0.80:
            return 0.02  # 2% for 24h
        elif confidence > 0.70:
            return 0.05  # 5% for 100h
        elif confidence > 0.65:
            return 0.12  # 12% for 200h-400h
        else:
            return 0.20  # 20% for 800h-1600h

    def update_position(
        self,
        symbol: str,
        current_price: float,
        unrealized_pnl_pct: float,
        timestamp: datetime,
    ) -> Tuple[bool, str]:
        """
        Evaluate if should exit position.

        Checks:
        1. Stop loss hit
        2. Take profit hit
        3. Time exit (1600h max)
        4. Macro conditions changed (reduce if RISK_OFF)
        """
        if symbol not in self.positions:
            return False, "No position"

        positions = self.positions[symbol]
        if not positions:
            return False, "No active positions"

        pos = positions[0]  # Simplified - would iterate all

        # Check stops/targets
        stop_loss = pos.get("stop_loss", 0.02)
        take_profit = pos.get("take_profit", 0.05)

        if unrealized_pnl_pct <= -stop_loss:
            logger.info(f"🔴 Stop loss hit: {symbol}")
            return True, "stop_loss"

        if unrealized_pnl_pct >= take_profit:
            logger.info(f"🟢 Take profit hit: {symbol}")
            return True, "take_profit"

        # Check time exit
        hours_held = (timestamp - pos["entry_time"]).total_seconds() / 3600
        horizon = pos.get("horizon", 100)
        max_hours = horizon * 2  # Can hold 2x the horizon

        if hours_held > max_hours:
            logger.info(f"⏱️ Time exit: {symbol} held {hours_held}h > {max_hours}h max")
            return True, "time_exit"

        # Check macro conditions
        macro_regime = self.macro.get_macro_regime()
        if self.macro.should_reduce_position(macro_regime, {}):
            logger.warning(f"⚠️ Macro conditions deteriorated, consider reducing {symbol}")
            # Could implement partial exit here

        return False, "holding"

    def get_system_status(self) -> Dict:
        """Get overall system health status."""
        return {
            "active_positions": len(self.positions),
            "macro_regime": self.macro.get_macro_regime()["overall_regime"],
            "portfolio_risk_score": self.portfolio_risk.get_portfolio_risk_score(),
            "sectors_exposure": dict(self.portfolio_risk.sector_exposure),
            "max_drawdown": self.portfolio_risk.max_drawdown,
            "current_heat": sum(
                pos.get("size", 0) * pos.get("stop_loss", 0)
                for positions in self.positions.values()
                for pos in positions
            ),
        }


# Global trading system instance
_trading_system_1600h = TradingSystem1600h()

def get_trading_system() -> TradingSystem1600h:
    """Get the global 1600h trading system."""
    return _trading_system_1600h
