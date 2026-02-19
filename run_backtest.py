#!/usr/bin/env python3
"""
Entry point for running the full training and backtesting pipeline.

Usage:
    python run_backtest.py
    python run_backtest.py --days 730
    python run_backtest.py --days 730 --epochs 50
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add project root and backend to path
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "backend"))

from backend.app.trading.backtester import run_full_training_pipeline

# Setup logging — quiet mode: suppress HTTP noise, keep key events
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(message)s',
    datefmt='%H:%M:%S',
    handlers=[
        logging.FileHandler('backtest_output.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
# Suppress noisy HTTP/network libraries
for lib in ('urllib3', 'aiohttp', 'httpx', 'asyncio', 'charset_normalizer',
            'requests', 'aiohttp.client', 'aiohttp.connector'):
    logging.getLogger(lib).setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


async def main():
    """Run the full training and backtesting pipeline."""
    logger.info("=" * 80)
    logger.info("STARTING FULL TRAINING & BACKTESTING PIPELINE")
    logger.info("=" * 80)

    try:
        # Run pipeline with default parameters
        # Can be customized with command-line args if needed
        result = await run_full_training_pipeline(
            days_of_data=730,      # 2 years of historical data
            training_epochs=999999  # Unlimited, stopped by early stopping (patience=2)
        )

        logger.info("\n" + "=" * 80)
        logger.info("PIPELINE COMPLETE")
        logger.info("=" * 80)

        # Print summary
        if isinstance(result, dict):
            if "error" in result:
                logger.error(f"Pipeline failed: {result['error']}")
                return 1
            else:
                logger.info(f"Results: {result}")
                return 0
        else:
            logger.error(f"Unexpected result type: {type(result)}")
            return 1

    except Exception as e:
        logger.error(f"Pipeline failed with exception: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
