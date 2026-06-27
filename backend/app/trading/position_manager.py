"""
Position Management Module

Extracted from WalkForwardBacktester: handles position exit logic including
stop losses, trailing stops, profit pyramiding, time-based exits, and
partial position management.
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


def get_optimal_stop_distance(stop_distance_effectiveness: Dict) -> float:
    """
    Learn optimal stop distance from historical data.
    Returns the stop distance with highest win rate.

    Args:
        stop_distance_effectiveness: Dict mapping distance -> {wins, losses}

    Returns:
        Optimal stop distance to use (default 0.05 = 5%)
    """
    try:
        best_distance = 0.05  # Default fallback
        best_win_rate = 0.0
        min_trades = 10  # Need at least 10 trades to trust the metric

        for distance, results in stop_distance_effectiveness.items():
            total_trades = results["wins"] + results["losses"]
            if total_trades >= min_trades:
                win_rate = results["wins"] / total_trades
                if win_rate > best_win_rate:
                    best_win_rate = win_rate
                    best_distance = distance

        return best_distance
    except Exception as e:
        logger.error(f"Optimal stop distance calculation failed: {e} - using default 5%")
        return 0.05  # Fallback to 5% if any error


def calculate_stop_loss(
    pos: Dict,
    config: Dict,
    volatility: float,
    regime: str,
    stop_distance_effectiveness: Dict,
) -> float:
    """
    Calculate the stop loss percentage for a position.

    Incorporates:
    - ATR-based stop set at entry
    - Breakeven stop after pyramid 1
    - Learned optimal stop distance
    - Regime-aware adjustments
    - Volatility adjustment

    Args:
        pos: Position dict with keys like entry_atr_pct, pyramided_1, side
        config: Config dict with stop_loss_min, stop_loss_max, regime_base_threshold, etc.
        volatility: Current volatility of recent returns
        regime: Current market regime ('bull', 'bear', 'sideways')
        stop_distance_effectiveness: Historical stop distance performance data

    Returns:
        stop_loss_pct: The calculated stop loss percentage
    """
    side = pos["side"]
    entry_atr_pct = pos.get("entry_atr_pct", 0.02)

    # Stop = 1.2x ATR, clamped to [1.2%, 3.5%]
    base_stop = np.clip(1.2 * entry_atr_pct, 0.012, 0.035)

    # After pyramid 1 is hit, move stop to breakeven (entry price)
    if pos.get("pyramided_1", False):
        base_stop = 0.002  # 0.2% = essentially breakeven (covers slippage)

    # TIER 2 FIX: LEARN OPTIMAL STOP DISTANCE FROM HISTORICAL DATA
    if not pos.get("pyramided_1", False):
        optimal_stop = get_optimal_stop_distance(stop_distance_effectiveness)
        if optimal_stop < base_stop:
            base_stop = optimal_stop

    # TIER 3 FIX: REGIME-AWARE STOP ADJUSTMENTS
    if regime == 'bull':
        if side == "long":
            base_stop *= 1.15  # With trend: +15% room
        else:
            base_stop *= 0.85  # Against trend: -15%
    elif regime == 'bear':
        if side == "short":
            base_stop *= 1.15  # With trend: +15% room
        else:
            base_stop *= 0.85  # Against trend: -15%

    # Apply volatility adjustment
    stop_loss_pct = base_stop + (volatility * 0.5)

    # Reasonable bounds
    stop_loss_pct = max(config["stop_loss_min"], min(config["stop_loss_max"], stop_loss_pct))

    return stop_loss_pct


def check_exit_conditions(
    pos: Dict,
    candle_close: float,
    candle_high: float,
    candle_low: float,
    timestamp: datetime,
    stop_loss_pct: float,
    config: Dict,
    recent_trades_window: List,
) -> Tuple[bool, str, float, float, float]:
    """
    Check all exit conditions for a position.

    Returns:
        Tuple of (should_exit, exit_reason, partial_exit_pct, exit_price, pnl_pct)
    """
    entry_price = pos["entry_price"]
    side = pos["side"]
    current_price = candle_close
    high_price = candle_high
    low_price = candle_low

    # Calculate current P&L
    if side == "long":
        pnl_pct = (current_price - entry_price) / entry_price
    else:
        pnl_pct = (entry_price - current_price) / entry_price

    should_exit = False
    exit_reason = ""
    partial_exit_pct = 0.0

    # TRAILING STOP: Only activates AFTER pyramid 1 hits
    trailing_stop_pct = 0.05
    if pos.get("pyramided_1", False):
        if side == "long" and pos.get("highest_price", entry_price) > entry_price:
            if low_price < pos["highest_price"] * (1 - trailing_stop_pct):
                should_exit = True
                exit_reason = "trailing_stop"
                partial_exit_pct = 1.0
                current_price = low_price
                pnl_pct = (current_price - entry_price) / entry_price
        elif side == "short" and pos.get("lowest_price", entry_price) < entry_price:
            if high_price > pos["lowest_price"] * (1 + trailing_stop_pct):
                should_exit = True
                exit_reason = "trailing_stop"
                partial_exit_pct = 1.0
                current_price = high_price
                pnl_pct = (entry_price - current_price) / entry_price

    # PROFIT PYRAMIDING
    pyramid_target_1 = pos.get("pyramid_target_1", 0.05)
    pyramid_target_2 = pos.get("pyramid_target_2", 0.15)

    if side == "long":
        target_1_price = entry_price * (1 + pyramid_target_1)
        target_2_price = entry_price * (1 + pyramid_target_2)
        hit_target_1 = high_price >= target_1_price
        hit_target_2 = high_price >= target_2_price
    else:
        target_1_price = entry_price * (1 - pyramid_target_1)
        target_2_price = entry_price * (1 - pyramid_target_2)
        hit_target_1 = low_price <= target_1_price
        hit_target_2 = low_price <= target_2_price

    if not should_exit and not pos.get("pyramided_1", False) and hit_target_1:
        partial_exit_pct = 0.30
        exit_reason = "profit_pyramid_1"
        should_exit = True
        if partial_exit_pct < 1.0 - 1e-8:
            pos["pyramided_1"] = True
        current_price = target_1_price
        if side == "long":
            pnl_pct = (current_price - entry_price) / entry_price
        else:
            pnl_pct = (entry_price - current_price) / entry_price
        logger.debug(f"Pyramid 1: {pos.get('symbol', '?')} at {pyramid_target_1*100:.2f}% target, exiting 30%")

    if not should_exit and not pos.get("pyramided_2", False) and hit_target_2:
        partial_exit_pct = 1.0
        should_exit = True
        exit_reason = "take_profit"
        pos["pyramided_2"] = True
        current_price = target_2_price
        if side == "long":
            pnl_pct = (current_price - entry_price) / entry_price
        else:
            pnl_pct = (entry_price - current_price) / entry_price
        logger.debug(f"Pyramid 2: {pos.get('symbol', '?')} at {pyramid_target_2*100:.2f}% target, exiting remaining 70%")

    # Stop loss
    if side == "long":
        stop_price = entry_price * (1 - stop_loss_pct)
        hit_stop = low_price <= stop_price
    else:
        stop_price = entry_price * (1 + stop_loss_pct)
        hit_stop = high_price >= stop_price

    if not should_exit and hit_stop:
        should_exit = True
        exit_reason = "stop_loss"
        partial_exit_pct = 1.0
        current_price = stop_price
        if side == "long":
            pnl_pct = (current_price - entry_price) / entry_price
        else:
            pnl_pct = (entry_price - current_price) / entry_price

    # ADAPTIVE HOLD PERIODS
    max_hold_hours = config["max_hold_hours_default"]
    if len(recent_trades_window) >= 10:
        recent_win_rate = np.mean(recent_trades_window[-10:])
        if recent_win_rate > 0.60:
            max_hold_hours = config["max_hold_hours_winner"]
        elif recent_win_rate < 0.40:
            max_hold_hours = config["max_hold_hours_loser"]

    # Time-based exit
    if not should_exit and (timestamp - pos["entry_time"]).total_seconds() > max_hold_hours * 3600:
        should_exit = True
        exit_reason = "time_exit"
        partial_exit_pct = 1.0

    return should_exit, exit_reason, partial_exit_pct, current_price, pnl_pct


def update_position_tracking(pos: Dict, candle_close: float, candle_high: float, candle_low: float) -> None:
    """
    Update highest/lowest prices for trailing stops (in-place mutation of pos dict).
    """
    entry_price = pos["entry_price"]
    side = pos["side"]

    if side == "long":
        pos["highest_price"] = max(pos.get("highest_price", entry_price), candle_close)
        pos["lowest_price_ever"] = min(pos.get("lowest_price_ever", entry_price), candle_low)
    else:
        pos["lowest_price"] = min(pos.get("lowest_price", entry_price), candle_close)
        pos["highest_price_ever"] = max(pos.get("highest_price_ever", entry_price), candle_high)


def calculate_position_volatility(window_data_for_symbol: list, entry_price: float) -> float:
    """
    Calculate volatility for adaptive stops from recent candles.

    Args:
        window_data_for_symbol: List of recent OHLCV candles for the symbol
        entry_price: Entry price of the position (used as fallback)

    Returns:
        Volatility estimate
    """
    recent_closes = [c.close for c in window_data_for_symbol[-20:]] if len(window_data_for_symbol) >= 20 else [entry_price]
    if len(recent_closes) > 1:
        volatility = np.std(np.diff(recent_closes) / (np.array(recent_closes[:-1]) + 1e-8))
    else:
        volatility = 0.02  # Default 2% volatility
    return volatility


def process_exit(
    pos: Dict,
    symbol: str,
    partial_exit_pct: float,
    pnl_pct: float,
    current_price: float,
    timestamp: datetime,
    capital: float,
    COST_PER_SIDE: float,
) -> Tuple[Dict, float, bool]:
    """
    Process a position exit (full or partial) and return the trade record.

    Args:
        pos: Position dict
        symbol: Trading symbol
        partial_exit_pct: Fraction of position to exit (0.0-1.0)
        pnl_pct: P&L percentage
        current_price: Exit price
        timestamp: Exit timestamp
        capital: Current capital
        COST_PER_SIDE: Transaction cost per side

    Returns:
        Tuple of (trade_dict, capital_change, is_full_exit)
    """
    entry_price = pos["entry_price"]
    side = pos["side"]
    exit_size = pos["size"] * partial_exit_pct
    exit_cost = exit_size * COST_PER_SIDE
    realized_pnl = exit_size * pnl_pct - exit_cost
    capital_change = exit_size + realized_pnl
    is_full_exit = partial_exit_pct >= 1.0

    # Track MFE/MAE for excursion analysis
    if side == "long":
        mfe = (pos.get("highest_price", entry_price) - entry_price) / entry_price
        mae = (entry_price - pos.get("lowest_price_ever", entry_price)) / entry_price
    else:
        mfe = (entry_price - pos.get("lowest_price", entry_price)) / entry_price
        mae = (pos.get("highest_price_ever", entry_price) - entry_price) / entry_price

    trade = {
        "symbol": symbol,
        "side": side,
        "entry_price": entry_price,
        "exit_price": current_price,
        "entry_time": pos["entry_time"].isoformat(),
        "exit_time": timestamp.isoformat(),
        "pnl": realized_pnl,
        "pnl_pct": pnl_pct * 100,
        "size": exit_size,
        "exit_size_pct": partial_exit_pct * 100,
        "exit_reason": "",  # Caller sets this from exit_reason
        "trade_costs": pos.get("entry_cost", 0) + exit_cost,
        "max_favorable_excursion": mfe,
        "max_adverse_excursion": mae,
    }

    # Handle partial exit: reduce position size and reset trailing stop baseline
    if not is_full_exit:
        pos["size"] *= (1.0 - partial_exit_pct)
        if side == "long":
            pos["highest_price"] = current_price
        else:
            pos["lowest_price"] = current_price
        logger.debug(f"Partial exit {symbol}: reset trailing stop baseline, size now ${pos['size']:.0f}")

    return trade, capital_change, is_full_exit
