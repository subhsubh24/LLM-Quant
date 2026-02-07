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

        # Track macro conditions at position entry for comparison
        self.position_macro_context = {}  # position_id -> macro_regime_at_entry

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

        # Step 6: Store macro regime context at entry for later comparison
        position_id = self.position_counter
        self.position_counter += 1
        self.position_macro_context[position_id] = {
            "overall_regime": macro_regime["overall_regime"],
            "vix_level": macro_regime.get("vix_level", 20),
            "credit_spreads": macro_regime.get("credit_spreads", 150),
            "seasonal_factor": macro_regime.get("seasonal_factor", 1.0),
            "entry_time": datetime.now(),
        }

        # Store position ID for later reference
        if symbol not in self.positions:
            self.positions[symbol] = []

        logger.info(
            f"✅ Trade approved: {symbol} | "
            f"ID: {position_id} | "
            f"Size: {position_size:.2f} | "
            f"Confidence: {adjusted_confidence:.2f} | "
            f"Regime: {macro_regime['overall_regime']} | "
            f"VIX: {macro_regime.get('vix_level', 20):.1f} | "
            f"Spreads: {macro_regime.get('credit_spreads', 150):.0f}bps"
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
        Evaluate if should exit position with MACRO-AWARE management.

        Checks (in order of priority):
        1. Stop loss hit (hard stop)
        2. Take profit hit (profit target)
        3. Macro deterioration (early exit if conditions worsened)
        4. Time exit (max holding period)
        5. Regime change during holding (position scaling)
        """
        if symbol not in self.positions:
            return False, "No position"

        positions = self.positions[symbol]
        if not positions:
            return False, "No active positions"

        pos = positions[0]  # Simplified - would iterate all
        position_id = pos.get("id")

        # ==================== STEP 1: Hard Stops ====================
        stop_loss = pos.get("stop_loss", 0.02)
        take_profit = pos.get("take_profit", 0.05)

        if unrealized_pnl_pct <= -stop_loss:
            logger.info(f"🔴 Stop loss hit: {symbol} at {unrealized_pnl_pct:.2%}")
            return True, "stop_loss"

        if unrealized_pnl_pct >= take_profit:
            logger.info(f"🟢 Take profit hit: {symbol} at {unrealized_pnl_pct:.2%}")
            return True, "take_profit"

        # ==================== STEP 2: Macro Deterioration Checks ====================
        macro_exit, macro_reason = self._check_macro_deterioration(
            symbol, pos, unrealized_pnl_pct, timestamp
        )
        if macro_exit:
            logger.warning(f"⚠️ Macro exit triggered: {symbol} | {macro_reason}")
            return True, macro_reason

        # ==================== STEP 3: Time Exit ====================
        hours_held = (timestamp - pos["entry_time"]).total_seconds() / 3600
        horizon = pos.get("horizon", 100)
        max_hours = horizon * 2  # Can hold 2x the horizon

        if hours_held > max_hours:
            logger.info(f"⏱️ Time exit: {symbol} held {hours_held:.1f}h > {max_hours}h max")
            return True, "time_exit"

        # ==================== STEP 4: Position Scaling ====================
        scale_adjustment = self._check_position_scaling(symbol, pos, timestamp)
        if scale_adjustment != 1.0:
            logger.warning(
                f"📊 Position scaling triggered for {symbol}: "
                f"adjusting from 1.0x to {scale_adjustment:.2f}x due to macro shift"
            )
            pos["size"] *= scale_adjustment
            pos["stop_loss"] *= scale_adjustment  # Adjust stops proportionally

        return False, "holding"

    def _check_macro_deterioration(
        self,
        symbol: str,
        position: Dict,
        unrealized_pnl_pct: float,
        timestamp: datetime,
    ) -> Tuple[bool, str]:
        """
        Check if macro conditions deteriorated enough to warrant early exit.
        Critical for 66+ day positions that span regime changes.
        """
        current_regime = self.macro.get_macro_regime()
        entry_regime = self.position_macro_context.get(position.get("id"), {})

        if not entry_regime:
            return False, ""

        # ========== CRITICAL DETERIORATION SIGNALS ==========

        # 1. RISK_OFF Shift - Major regime flip
        if (
            entry_regime.get("overall_regime") in ["RISK_ON", "BALANCED"]
            and current_regime["overall_regime"] == "RISK_OFF"
        ):
            hours_held = (timestamp - position["entry_time"]).total_seconds() / 3600
            # Only exit if we've been holding long enough to evaluate thesis
            if hours_held > 24:  # At least 1 day
                logger.warning(
                    f"🚨 CRITICAL: Regime shift to RISK_OFF for {symbol} "
                    f"after {hours_held:.1f}h holding"
                )
                # For long positions in RISK_OFF, early exit is prudent
                if position.get("action") == "BUY":
                    return True, "macro_risk_off_shift"

        # 2. VIX Spike - Sudden volatility increase
        current_vix = current_regime.get("vix_level", 20)
        entry_vix = entry_regime.get("vix_level", 20)

        if current_vix > 40 and current_vix > entry_vix + 15:
            logger.warning(
                f"🚨 VIX spike: {entry_vix:.1f} → {current_vix:.1f} for {symbol}"
            )
            if unrealized_pnl_pct > 0:
                # If profitable, take the win and avoid spike risk
                return True, "macro_vix_spike"

        # 3. Credit Stress - Market stress signal
        current_spreads = current_regime.get("credit_spreads", 150)
        entry_spreads = entry_regime.get("credit_spreads", 150)

        if current_spreads > 300:  # High stress
            if current_spreads > entry_spreads + 100:
                logger.warning(
                    f"🚨 Credit stress: {entry_spreads:.0f}bps → {current_spreads:.0f}bps for {symbol}"
                )
                if unrealized_pnl_pct > 0:
                    return True, "macro_credit_stress"

        # 4. Fed Event Risk - Don't hold through announcements
        current_events = self.macro.get_upcoming_events(timestamp)
        if current_events:
            major_events = [e for e in current_events if e.get("severity") == "HIGH"]
            if major_events:
                hours_to_event = min(
                    (e.get("timestamp", timestamp) - timestamp).total_seconds() / 3600
                    for e in major_events
                )
                if 0 < hours_to_event < 4:  # Major event in next 4 hours
                    logger.warning(
                        f"🚨 Major event in {hours_to_event:.1f}h for {symbol}: "
                        f"{major_events[0].get('description', 'unknown')}"
                    )
                    if unrealized_pnl_pct > 0:
                        return True, "macro_major_event_approaching"

        # 5. Seasonal Risk Period - Avoid weakness seasons
        current_seasonal = current_regime.get("seasonal_factor", 1.0)
        if current_seasonal < 0.85:  # Weak seasonal period
            entry_seasonal = entry_regime.get("seasonal_factor", 1.0)
            if entry_seasonal >= 0.95:
                logger.warning(
                    f"⚠️ Entered in strong season ({entry_seasonal:.2f}) "
                    f"but now in weak season ({current_seasonal:.2f}) for {symbol}"
                )
                if unrealized_pnl_pct > 0.02:  # Wait for 2%+ profit
                    return True, "macro_seasonal_deterioration"

        # 6. Correlation Breakdown - Diversification fails
        if position.get("horizon", 100) >= 400:  # Long positions only
            correlations = self.portfolio_risk.get_correlation_matrix()
            symbol_correlations = correlations.get(symbol, {})
            high_corr_count = sum(1 for c in symbol_correlations.values() if c > 0.80)

            if high_corr_count > len(symbol_correlations) * 0.5:
                logger.warning(
                    f"⚠️ Correlation breakdown: {symbol} now highly correlated "
                    f"with {high_corr_count} other positions"
                )

        return False, ""

    def _check_position_scaling(
        self,
        symbol: str,
        position: Dict,
        timestamp: datetime,
    ) -> float:
        """
        Calculate position scaling multiplier if macro conditions changed.
        Returns: scaling factor (1.0 = no change, 0.5 = half size, 0.0 = close)
        """
        current_regime = self.macro.get_macro_regime()
        entry_regime = self.position_macro_context.get(position.get("id"), {})

        if not entry_regime:
            return 1.0

        scaling = 1.0

        # Adjust for regime changes
        entry_regime_type = entry_regime.get("overall_regime", "BALANCED")
        current_regime_type = current_regime["overall_regime"]

        if entry_regime_type == "RISK_ON" and current_regime_type == "BALANCED":
            scaling *= 0.85  # Slight reduction for less favorable conditions
        elif entry_regime_type == "RISK_ON" and current_regime_type == "RISK_OFF":
            scaling *= 0.5  # Half size in risk-off
        elif entry_regime_type == "BALANCED" and current_regime_type == "RISK_OFF":
            scaling *= 0.75

        # Adjust for VIX changes
        current_vix = current_regime.get("vix_level", 20)
        entry_vix = entry_regime.get("vix_level", 20)

        if current_vix > entry_vix * 1.5:  # 50% VIX increase
            scaling *= (20 / max(current_vix, 1))  # Inverse scaling

        # Adjust for event risk
        upcoming = self.macro.get_upcoming_events(timestamp)
        if upcoming:
            major = [e for e in upcoming if e.get("severity") == "HIGH"]
            if major:
                hours_to = min(
                    (e.get("timestamp", timestamp) - timestamp).total_seconds() / 3600
                    for e in major
                )
                if 0 < hours_to < 24:  # Event within 24h
                    scaling *= max(0.25, 1.0 - (24 - hours_to) / 48)

        return max(0.0, scaling)

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
