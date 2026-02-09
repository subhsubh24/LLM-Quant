#!/usr/bin/env python3
"""
Simple runner script for the training pipeline.
"""

import asyncio
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend', 'app'))

async def main():
    from trading.master_bot import run_training_pipeline

    print("\n" + "="*70)
    print("STARTING TRAINING PIPELINE WITH CHECKPOINT LOADING FIX")
    print("="*70)
    print("\nExpected behavior:")
    print("  1. Download 730 days of historical data")
    print("  2. Train ensemble models on multi-horizon labels")
    print("  3. Early stopping (patience=2) should complete in 5-7 epochs")
    print("  4. Load best checkpoint before adversarial validation")
    print("  5. Test accuracy should match validation (~50-60%)")
    print()

    result = await run_training_pipeline(
        days_of_data=730,
        training_epochs=999999  # Unlimited, controlled by early stopping
    )

    print("\n" + "="*70)
    print("TRAINING PIPELINE COMPLETE")
    print("="*70)

    # Print summary
    if result:
        print("\nResults:")
        for key, value in result.items():
            if isinstance(value, dict):
                print(f"  {key}:")
                for k, v in value.items():
                    if isinstance(v, float):
                        print(f"    {k}: {v:.4f}")
                    else:
                        print(f"    {k}: {v}")
            else:
                print(f"  {key}: {value}")

    return result

if __name__ == "__main__":
    result = asyncio.run(main())
    sys.exit(0 if result else 1)
