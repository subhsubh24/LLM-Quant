"""
Trading System Constants

Unified numerical stability and configuration constants used throughout the trading system.
"""

# Numerical Stability Constants
EPSILON = 1e-8
"""Small epsilon value for numerical stability in divisions and comparisons"""

FLOAT_COMPARISON_EPSILON = 1e-8
"""Epsilon for comparing floating-point values (avoids exact == 0 comparisons)"""

PRICE_MINIMUM = 0.01
"""Minimum realistic price value in USD (filters out invalid/corrupt price data)"""

VOLATILITY_MINIMUM = 1e-8
"""Minimum volatility value to avoid division by zero in risk calculations"""

CORRELATION_MINIMUM = 1e-8
"""Minimum value for correlation-based calculations"""

# Risk Management Constants
MAX_LEVERAGE = 10.0
"""Maximum leverage multiplier for position sizing"""

MIN_CAPITAL_THRESHOLD = 100.0
"""Minimum capital required to open new positions (USD)"""

# Data Validation Constants
MAX_HEDGE_RATIO = 100.0
"""Maximum hedge ratio for statistical arbitrage pairs"""

MAX_BETA_VALUE = 100.0
"""Maximum beta value for regression-based calculations"""

# Model Training Constants
MIN_TRAINING_SAMPLES = 50
"""Minimum samples required for model retraining"""

MIN_REBALANCE_BUFFER = 50
"""Minimum samples before triggering rebalance calculations"""

# Metrics Constants
MIN_VAR_SAMPLES = 20
"""Minimum samples required for Value-at-Risk calculation"""

MIN_SHARPE_SAMPLES = 10
"""Minimum samples required for Sharpe ratio calculation"""

RISK_FREE_RATE = 0.02
"""Annual risk-free rate for Sharpe ratio calculations (2%)"""
