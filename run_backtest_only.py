#!/usr/bin/env python3
"""
Run full train + backtest pipeline using synthetic data.
Validates the entire pipeline end-to-end including hybrid signals.

Usage:
    python run_backtest_only.py
"""

import asyncio
import logging
import sys
import time
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "backend"))

from backend.app.trading.backtester import (
    get_model_pretrainer, get_backtester,
    CHECKPOINT_DIR, OHLCV
)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[
        logging.FileHandler('backtest_only_output.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


def generate_synthetic_data(symbols, n_candles=2500):
    """
    Generate realistic synthetic OHLCV data for backtesting.
    Uses geometric Brownian motion with trends, mean-reversion, and vol clustering.
    """
    np.random.seed(42)  # Reproducible
    data = {}

    base_prices = {
        "BTC": 45000, "ETH": 2800, "SOL": 120, "BNB": 350,
        "XRP": 0.55, "ADA": 0.45, "DOGE": 0.12, "LINK": 15,
        "AVAX": 35, "DOT": 7.5, "MATIC": 0.85, "ATOM": 10,
    }

    start_time = datetime(2024, 1, 1)

    for sym in symbols:
        price = base_prices.get(sym, 100.0)
        candles = []

        # Parameters for this symbol
        drift = np.random.uniform(-0.00005, 0.00015)  # Mild upward bias
        base_vol = np.random.uniform(0.008, 0.018)     # 0.8-1.8% hourly vol
        vol = base_vol

        for i in range(n_candles):
            ts = start_time + timedelta(hours=i)

            # Vol clustering (GARCH-like)
            vol = 0.95 * vol + 0.05 * base_vol + 0.015 * abs(np.random.randn()) * base_vol

            # Trend + noise
            ret = drift + vol * np.random.randn()

            # Occasional regime shifts (less extreme)
            if np.random.random() < 0.001:
                ret += np.random.choice([-1, 1]) * np.random.uniform(0.02, 0.05)

            # Mean reversion component
            if i > 200:
                sma200 = np.mean([c.close for c in candles[-200:]])
                mr_signal = (sma200 - price) / price
                ret += mr_signal * 0.002  # Mild mean-reversion

            new_price = price * (1 + ret)
            new_price = max(new_price, price * 0.90)  # Floor at -10% per candle

            # Generate OHLCV
            high = max(price, new_price) * (1 + abs(np.random.randn()) * vol * 0.4)
            low = min(price, new_price) * (1 - abs(np.random.randn()) * vol * 0.4)
            volume = np.random.lognormal(mean=15, sigma=1.0) * (price / 100)

            candles.append(OHLCV(
                timestamp=ts,
                open=price,
                high=high,
                low=low,
                close=new_price,
                volume=volume,
            ))
            price = new_price

        data[sym] = candles
        pct_chg = 100 * (candles[-1].close / candles[0].close - 1)
        logger.info(f"  {sym}: {n_candles} candles, "
                     f"${candles[0].close:.2f} -> ${candles[-1].close:.2f} "
                     f"({pct_chg:+.1f}%)")

    return data


async def main():
    logger.info("=" * 70)
    logger.info("FULL TRAIN + BACKTEST PIPELINE (synthetic data)")
    logger.info("Validates: feature pipeline, model training, hybrid signals")
    logger.info("=" * 70)

    # Initialize
    pretrainer = get_model_pretrainer()
    backtester = get_backtester()

    # Generate synthetic data
    logger.info("\n1. Generating synthetic market data...")
    symbols = ["BTC", "ETH", "SOL", "BNB", "XRP", "ADA",
               "DOGE", "LINK", "AVAX", "DOT"]
    historical_data = generate_synthetic_data(symbols, n_candles=2500)

    total_candles = sum(len(c) for c in historical_data.values())
    logger.info(f"   Total: {total_candles:,} candles across {len(historical_data)} symbols")

    # Prepare training data
    logger.info("\n2. Preparing training features and labels...")
    t0 = time.time()
    try:
        features, labels, rewards = pretrainer.prepare_training_data(historical_data, backtester)
    except Exception as e:
        logger.error(f"Feature preparation failed: {e}", exc_info=True)
        return 1

    if len(features) == 0:
        logger.error("No training samples generated!")
        return 1

    prep_time = time.time() - t0
    logger.info(f"   {len(features)} samples, {features.shape[1]} features each, took {prep_time:.1f}s")

    # Train models
    logger.info("\n3. Training ML models (early stopping, patience=2)...")
    t0 = time.time()
    try:
        training_metrics = pretrainer.train(
            features, labels, rewards,
            epochs=999999,  # Early stopping controls
            batch_size=256,
        )
    except Exception as e:
        logger.error(f"Training failed: {e}", exc_info=True)
        return 1

    train_time = time.time() - t0
    logger.info(f"   Training complete in {train_time:.1f}s")
    logger.info(f"   {training_metrics.to_dict()}")

    # Run backtest
    logger.info("\n4. Running walk-forward backtest (with hybrid signals)...")
    t0 = time.time()
    try:
        result = backtester.run_backtest(historical_data, pretrainer)
    except Exception as e:
        logger.error(f"Backtest failed: {e}", exc_info=True)
        return 1

    bt_time = time.time() - t0

    # Print results
    logger.info("\n" + "=" * 70)
    logger.info("BACKTEST RESULTS")
    logger.info("=" * 70)
    r = result.to_dict()
    for key, val in r.items():
        if key not in ("equity_curve", "trades"):
            logger.info(f"  {key}: {val}")
    logger.info(f"\n  Training took {train_time:.1f}s, Backtest took {bt_time:.1f}s")
    logger.info("=" * 70)

    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
