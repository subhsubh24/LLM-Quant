"""
Signal Filtering Module

Extracted from WalkForwardBacktester: all signal filtering logic including
trend filter, mean-reversion filter, microstructure filter, confidence checks,
model consensus, cooldown logic, flip-flop detection, and statistical significance.
"""

import logging
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


def is_signal_statistically_significant(symbol: str, action: int, signal_history: Dict) -> bool:
    """
    Test if a signal's historical win rate is statistically significant at 95% confidence.
    Uses binomial test: H0 = win_rate = 50%, H1 = win_rate > 50%

    Args:
        symbol: Trading pair symbol
        action: Action code (0=short, 2=long)
        signal_history: Dict of symbol -> {action -> [win/loss results]}

    Returns:
        True if win rate is significantly > 50% at 95% confidence (p < 0.05)
    """
    try:
        from scipy import stats

        if symbol not in signal_history:
            return True  # No history, allow the signal

        if action not in signal_history[symbol]:
            return True  # No history for this action

        trade_results = signal_history[symbol][action]

        if len(trade_results) < 10:
            return True  # Not enough data yet

        wins = sum(trade_results)
        total = len(trade_results)

        # BUG FIX #20: Handle scipy API compatibility
        try:
            p_value = stats.binomtest(wins, total, 0.5, alternative='greater').pvalue
        except AttributeError:
            p_value = stats.binom_test(wins, total, 0.5, alternative='greater')

        is_significant = p_value < 0.05

        if not is_significant and total >= 20:
            win_rate = (wins / max(total, 1)) * 100 if total > 0 else 0.0
            if total >= 10:
                logger.debug(f"Signal {symbol}:{action} filtered: {win_rate:.1f}% win rate ({wins}/{total}) not significantly > 50% (p={p_value:.3f})")

        return is_significant

    except Exception as e:
        logger.error(f"CRITICAL: Significance test failed for {symbol}:{action}: {e}")
        return False  # If error, reject the signal


def check_trend_filter(
    prediction_action: int,
    window_data_for_symbol: list,
    config: Dict,
) -> bool:
    """
    Trend-following filter: only go long in uptrends, short in downtrends.

    Args:
        prediction_action: 0=short, 1=hold, 2=long
        window_data_for_symbol: Recent candle data for the symbol
        config: Config dict with trend_filter_enabled, trend_ema_fast, trend_ema_slow

    Returns:
        True if the trade is allowed by the trend filter, False if blocked
    """
    if not config.get("trend_filter_enabled", True):
        return True

    if len(window_data_for_symbol) < config.get("trend_ema_slow", 200):
        return True  # Not enough data, allow

    trend_closes = np.array([c.close for c in window_data_for_symbol[-config["trend_ema_slow"]:]])
    ema_fast_period = config["trend_ema_fast"]
    ema_fast = np.mean(trend_closes[-ema_fast_period:])
    ema_slow = np.mean(trend_closes)
    trend_direction = "up" if ema_fast > ema_slow else "down"

    if prediction_action == 0 and trend_direction == "up":
        # Trying to SHORT in an uptrend -- BLOCK
        return False
    elif prediction_action == 2 and trend_direction == "down":
        # Trying to go LONG in a downtrend -- BLOCK
        return False

    return True


def check_mean_reversion_filter(
    prediction_action: int,
    window_data_for_symbol: list,
) -> bool:
    """
    Mean-reversion entry filter: only buy near support, only short near resistance.

    For LONGS: RSI < 40 (oversold) OR price below 50-SMA (dip)
    For SHORTS: RSI > 60 (overbought) OR price above 50-SMA (extended)

    Args:
        prediction_action: 0=short, 1=hold, 2=long
        window_data_for_symbol: Recent candle data for the symbol

    Returns:
        True if the trade passes the mean-reversion filter
    """
    if prediction_action == 1:
        return True  # HOLD bypasses

    if len(window_data_for_symbol) < 50:
        return True  # Not enough data

    mr_closes = np.array([c.close for c in window_data_for_symbol[-50:]])
    # RSI-14
    mr_gains = np.maximum(np.diff(mr_closes), 0)
    mr_losses = np.maximum(-np.diff(mr_closes), 0)
    mr_avg_gain = np.mean(mr_gains[-14:]) if len(mr_gains) >= 14 else np.mean(mr_gains)
    mr_avg_loss = np.mean(mr_losses[-14:]) if len(mr_losses) >= 14 else np.mean(mr_losses)
    mr_rsi = 100 - (100 / (1 + mr_avg_gain / (mr_avg_loss + 1e-8)))
    # 50-period SMA
    mr_sma50 = np.mean(mr_closes)
    mr_current_price = mr_closes[-1]
    mr_price_vs_sma = (mr_current_price - mr_sma50) / (mr_sma50 + 1e-8)

    if prediction_action == 2:  # LONG
        rsi_ok = mr_rsi < 40
        sma_ok = mr_price_vs_sma < 0.02
        return rsi_ok or sma_ok
    elif prediction_action == 0:  # SHORT
        rsi_ok = mr_rsi > 60
        sma_ok = mr_price_vs_sma > -0.02
        return rsi_ok or sma_ok

    return True


def check_microstructure_filter(
    prediction_action: int,
    symbol: str,
    microstructure_extractors: Dict,
    order_book_cache: Dict,
) -> Tuple[bool, float, List[str]]:
    """
    Microstructure signal quality filter using order book data.

    Args:
        prediction_action: 0=short, 1=hold, 2=long
        symbol: Trading symbol
        microstructure_extractors: Dict of symbol -> MicrostructureExtractor
        order_book_cache: Dict of symbol -> order book data

    Returns:
        Tuple of (passes_filter, microstructure_score, flags_list)
    """
    microstructure_score = 1.0
    microstructure_filters_pass = True
    microstructure_flags = []

    if symbol not in microstructure_extractors or order_book_cache.get(symbol) is None:
        logger.debug(f"No order book data for {symbol} yet - skipping microstructure filter")
        return True, 1.0, []

    try:
        micro_features = microstructure_extractors[symbol].extract_features()

        is_short = prediction_action == 0
        is_long = prediction_action == 2

        # Micro Filter 1: Bid-Ask Spread
        spread_bps = micro_features.get("spread_bps", 5.0)
        if spread_bps < 2:
            spread_score = 1.0
        elif spread_bps < 5:
            spread_score = 0.9
        elif spread_bps < 10:
            spread_score = 0.7
        else:
            spread_score = 0.4
            microstructure_filters_pass = False
            microstructure_flags.append(f"spread_bps={spread_bps:.1f}")

        # Micro Filter 2: Order Book Imbalance
        ob_imbalance = micro_features.get("ob_imbalance", 0.5)
        if is_long and ob_imbalance > 0.6:
            imbalance_score = 1.0
        elif is_short and ob_imbalance < 0.4:
            imbalance_score = 1.0
        elif abs(ob_imbalance - 0.5) < 0.15:
            imbalance_score = 0.8
        else:
            imbalance_score = 0.5
            microstructure_flags.append(f"imbalance={ob_imbalance:.2f}")

        # Micro Filter 3: Order Flow
        order_flow = micro_features.get("order_flow_imbalance", 0.0)
        if is_long and order_flow > 0.3:
            flow_score = 1.0
        elif is_short and order_flow < -0.3:
            flow_score = 1.0
        else:
            flow_score = 0.6
            microstructure_flags.append(f"flow={order_flow:.2f}")

        # Micro Filter 4: Large Order Presence
        large_buy = micro_features.get("large_buy_presence", 0.0)
        large_sell = micro_features.get("large_sell_presence", 0.0)
        if is_long and large_buy > 0.5:
            whale_score = 1.0
        elif is_short and large_sell > 0.5:
            whale_score = 1.0
        else:
            whale_score = 0.7

        # Composite score
        microstructure_score = (spread_score * 0.3 + imbalance_score * 0.35 + flow_score * 0.25 + whale_score * 0.1)

        if microstructure_score < 0.6:
            microstructure_filters_pass = False
            logger.debug(f"Microstructure score low: {symbol} score={microstructure_score:.2f} flags={microstructure_flags}")

    except Exception as e:
        logger.warning(f"Microstructure feature extraction error for {symbol}: {type(e).__name__}: {e}")

    return microstructure_filters_pass, microstructure_score, microstructure_flags


def check_confidence_and_consensus(
    prediction: Dict,
    config: Dict,
    regime: str,
    model_names: List[str],
    model_recent_trades: Dict,
) -> Tuple[bool, bool, int, float]:
    """
    Check model confidence thresholds and consensus requirements.

    Args:
        prediction: Prediction dict with action, confidence, predictions
        config: Config dict with confidence thresholds and agreement settings
        regime: Current market regime
        model_names: List of model names
        model_recent_trades: Dict of model_name -> recent trade outcomes

    Returns:
        Tuple of (meets_confidence, strong_consensus, model_agreement, weighted_agreement_pct)
    """
    is_short = prediction["action"] == 0
    is_long = prediction["action"] == 2
    individual_preds = prediction.get("predictions", [])
    final_action = prediction["action"]

    # Calculate per-model win rates
    model_weights = {}
    for i, model_name in enumerate(model_names):
        if len(model_recent_trades.get(model_name, [])) > 0:
            recent_wr = np.mean(model_recent_trades[model_name][-20:])
            model_weights[i] = 0.8 + (recent_wr - 0.5) * 1.6
        else:
            model_weights[i] = 1.0

    # Weighted agreement
    weighted_agreement = sum(
        model_weights.get(i, 1.0)
        for i, p in enumerate(individual_preds)
        if p == final_action and i < len(model_names)
    )
    total_model_weight = sum(model_weights.values())
    weighted_agreement_pct = weighted_agreement / total_model_weight if total_model_weight > 0 else 0

    # Simple agreement
    min_agreement = config["min_model_agreement_short"] if is_short else config["min_model_agreement"]
    model_agreement = sum(1 for p in individual_preds if p == final_action)

    strong_consensus = (weighted_agreement_pct > config["weighted_agreement_threshold"]) and (model_agreement >= min_agreement)

    # HORIZON-AWARE CONFIDENCE
    if model_agreement == 4:
        min_confidence = config["confidence_4x4_models"]
    elif model_agreement == 3:
        min_confidence = config["confidence_3x4_models"]
    else:
        min_confidence = config["confidence_fallback"]

    # REGIME-AWARE CONFIDENCE ADJUSTMENT (additive)
    if regime == 'bull' and is_short:
        min_confidence += config["regime_bull_confidence_mult"] - 1.0
    elif regime == 'bear' and is_long:
        min_confidence += config["regime_bear_confidence_mult"] - 1.0

    meets_confidence = prediction["confidence"] >= min_confidence

    return meets_confidence, strong_consensus, model_agreement, weighted_agreement_pct


def check_cooldown(
    symbol: str,
    prediction_action: int,
    candles_processed: int,
    last_exit_time: Dict,
    trade_directions: Dict,
    flip_block_until: Dict,
    max_flips_per_symbol: int,
    min_cooldown_candles: int,
    min_flip_cooldown_candles: int,
    flip_confidence_penalty: float,
    prediction_confidence: float,
    config: Dict,
    signals_generated: int,
) -> bool:
    """
    Check if a symbol is in trading cooldown (standard or flip-flop).

    Args:
        symbol: Trading symbol
        prediction_action: 0=short, 2=long
        candles_processed: Current candle index
        last_exit_time: Dict of symbol -> last exit candle index
        trade_directions: Dict of symbol -> last trade direction
        flip_block_until: Dict of symbol -> candle index when block expires
        max_flips_per_symbol: Max direction flips before blocking
        min_cooldown_candles: Standard cooldown period
        min_flip_cooldown_candles: Flip-flop cooldown period
        flip_confidence_penalty: Confidence penalty for direction flips
        prediction_confidence: Current prediction confidence
        config: Config dict
        signals_generated: Number of signals generated so far

    Returns:
        True if in cooldown (should NOT trade), False if clear to trade
    """
    new_direction = "long" if prediction_action == 2 else "short"
    is_direction_flip = symbol in trade_directions and trade_directions[symbol] != new_direction

    # Check if symbol is blocked due to excessive flipping
    if symbol in flip_block_until and candles_processed < flip_block_until[symbol]:
        remaining = flip_block_until[symbol] - candles_processed
        if signals_generated <= 100 or np.random.random() < 0.001:
            logger.debug(f"{symbol} BLOCKED for {remaining} more candles (exceeded {max_flips_per_symbol} direction flips)")
        return True

    if symbol in last_exit_time:
        candles_since_exit = candles_processed - last_exit_time[symbol]
        required_cooldown = min_flip_cooldown_candles if is_direction_flip else min_cooldown_candles

        if candles_since_exit < required_cooldown:
            cooldown_type = "flip-flop" if is_direction_flip else "standard"
            if signals_generated <= 100 or np.random.random() < 0.001:
                logger.debug(f"{symbol} in {cooldown_type} cooldown ({candles_since_exit}/{required_cooldown} candles since exit)")
            return True

        if is_direction_flip:
            effective_confidence = prediction_confidence
            penalty_threshold = effective_confidence - flip_confidence_penalty
            if penalty_threshold < config.get("confidence_fallback", 0.45):
                if signals_generated <= 100 or np.random.random() < 0.001:
                    logger.debug(f"{symbol} flip confidence too low ({effective_confidence:.2f} - {flip_confidence_penalty:.2f} penalty < threshold)")
                return True

    return False
