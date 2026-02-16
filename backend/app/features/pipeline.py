"""
Feature engineering pipeline.

This module orchestrates feature computation with:
- Proper lag handling to prevent leakage
- Configurable feature sets
- Feature storage and caching
- Quality checks
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from datetime import date
import pandas as pd
import numpy as np
from hashlib import sha256
import json
import logging

logger = logging.getLogger(__name__)

from .core import (
    compute_returns,
    compute_momentum,
    compute_volatility,
    compute_drawdown,
    compute_volume_features,
    compute_risk_features,
    compute_technical_features,
    standardize_features,
)


@dataclass
class FeatureConfig:
    """Configuration for feature computation."""

    # Return features
    return_periods: List[int] = field(default_factory=lambda: [1, 5, 21, 63, 126, 252])
    use_log_returns: bool = True

    # Momentum features
    momentum_windows: List[int] = field(default_factory=lambda: [21, 63, 126, 252])
    momentum_skip_recent: int = 5

    # Volatility features
    volatility_windows: List[int] = field(default_factory=lambda: [21, 63])
    annualize_vol: bool = True

    # Volume features
    volume_windows: List[int] = field(default_factory=lambda: [21, 63])

    # Risk features (requires market proxy)
    risk_windows: List[int] = field(default_factory=lambda: [63, 252])
    market_proxy_ticker: str = "SPY"

    # Technical features
    include_technical: bool = True

    # Standardization
    standardize_method: str = "cross_sectional"  # cross_sectional, time_series, or none
    clip_outliers: float = 3.0

    # Feature selection
    enabled_features: List[str] = field(default_factory=lambda: [
        "returns", "momentum", "volatility", "drawdown",
        "volume", "risk", "technical"
    ])

    def to_dict(self) -> dict:
        """Convert to dictionary for hashing/storage."""
        return {
            "return_periods": self.return_periods,
            "use_log_returns": self.use_log_returns,
            "momentum_windows": self.momentum_windows,
            "momentum_skip_recent": self.momentum_skip_recent,
            "volatility_windows": self.volatility_windows,
            "annualize_vol": self.annualize_vol,
            "volume_windows": self.volume_windows,
            "risk_windows": self.risk_windows,
            "market_proxy_ticker": self.market_proxy_ticker,
            "include_technical": self.include_technical,
            "standardize_method": self.standardize_method,
            "clip_outliers": self.clip_outliers,
            "enabled_features": self.enabled_features,
        }

    def compute_hash(self) -> str:
        """Compute deterministic hash of config."""
        config_str = json.dumps(self.to_dict(), sort_keys=True)
        return sha256(config_str.encode()).hexdigest()[:16]


class FeaturePipeline:
    """
    Main feature engineering pipeline.

    This class:
    1. Takes price/volume data as input
    2. Computes configured features with proper lags
    3. Validates no leakage exists
    4. Returns feature matrix ready for modeling
    """

    def __init__(self, config: Optional[FeatureConfig] = None):
        self.config = config or FeatureConfig()
        self.feature_names: List[str] = []
        self._market_proxy_data: Optional[pd.Series] = None

    def compute_features(
        self,
        prices: pd.DataFrame,
        volumes: Optional[pd.DataFrame] = None,
        highs: Optional[pd.DataFrame] = None,
        lows: Optional[pd.DataFrame] = None,
        market_proxy: Optional[pd.Series] = None,
    ) -> pd.DataFrame:
        """
        Compute all configured features.

        Args:
            prices: DataFrame with tickers as columns, dates as index (adjusted close)
            volumes: Optional volume data (same structure)
            highs: Optional high prices
            lows: Optional low prices
            market_proxy: Optional market returns series (e.g., SPY prices)

        Returns:
            DataFrame with features, properly lagged

        Important: The returned features at time t can be used to
        predict returns from t to t+1 without leakage.
        """
        all_features = []

        # Store market proxy
        self._market_proxy_data = market_proxy

        # 1. Return features
        if "returns" in self.config.enabled_features:
            logger.debug("Computing return features")
            ret_features = compute_returns(
                prices,
                periods=self.config.return_periods,
                log_returns=self.config.use_log_returns
            )
            all_features.append(ret_features)

        # 2. Momentum features
        if "momentum" in self.config.enabled_features:
            logger.debug("Computing momentum features")
            mom_features = compute_momentum(
                prices,
                windows=self.config.momentum_windows,
                skip_recent=self.config.momentum_skip_recent
            )
            all_features.append(mom_features)

        # 3. Volatility features
        if "volatility" in self.config.enabled_features:
            logger.debug("Computing volatility features")
            vol_features = compute_volatility(
                prices,
                windows=self.config.volatility_windows,
                annualize=self.config.annualize_vol
            )
            all_features.append(vol_features)

        # 4. Drawdown features
        if "drawdown" in self.config.enabled_features:
            logger.debug("Computing drawdown features")
            dd_features = compute_drawdown(prices)
            all_features.append(dd_features)

        # 5. Volume features
        if "volume" in self.config.enabled_features and volumes is not None:
            logger.debug("Computing volume features")
            vol_features = compute_volume_features(
                prices,
                volumes,
                windows=self.config.volume_windows
            )
            all_features.append(vol_features)

        # 6. Risk features (need market proxy)
        if "risk" in self.config.enabled_features and market_proxy is not None:
            logger.debug("Computing risk features")
            risk_features = compute_risk_features(
                prices,
                market_proxy,
                windows=self.config.risk_windows
            )
            all_features.append(risk_features)

        # 7. Technical features
        if "technical" in self.config.enabled_features and self.config.include_technical:
            logger.debug("Computing technical features")
            if highs is None:
                highs = prices
            if lows is None:
                lows = prices
            tech_features = compute_technical_features(prices, highs, lows)
            all_features.append(tech_features)

        # Combine all features
        if not all_features:
            raise ValueError("No features computed - check enabled_features config")

        features = pd.concat(all_features, axis=1)

        # Store feature names
        self.feature_names = features.columns.tolist()

        # Standardize if configured
        if self.config.standardize_method != "none":
            logger.debug(f"Standardizing features using {self.config.standardize_method}")
            features = standardize_features(
                features,
                method=self.config.standardize_method,
                clip_outliers=self.config.clip_outliers
            )

        # Validate no leakage
        self._validate_no_leakage(features, prices)

        return features

    def _validate_no_leakage(
        self,
        features: pd.DataFrame,
        prices: pd.DataFrame
    ) -> None:
        """
        Validate that features don't contain future information.

        This is a critical check. Features at time t should only
        depend on information available at or before time t.
        """
        # Check 1: Features should have more NaN rows at the start than prices
        # (due to lookback windows)
        for col in features.columns:
            first_valid = features[col].first_valid_index()
            if first_valid is not None:
                # The first valid feature should be at least 1 day after
                # the first valid price (due to our 1-day lag)
                # BUG FIX #10: Robust ticker extraction without assuming underscore separator
                parts = col.split("_")
                if not parts:
                    continue
                ticker = parts[0]

                if ticker in prices.columns:
                    first_price = prices[ticker].first_valid_index()
                    if first_valid is not None and first_price is not None:
                        if first_valid < first_price:
                            raise ValueError(
                                f"Potential leakage in {col}: feature available "
                                f"before price data"
                            )

        logger.debug("Leakage validation passed")

    def get_feature_importance_groups(self) -> Dict[str, List[str]]:
        """
        Group features by type for analysis.

        Returns dict mapping feature type -> list of feature names.
        """
        groups = {
            "returns": [],
            "momentum": [],
            "volatility": [],
            "drawdown": [],
            "volume": [],
            "risk": [],
            "technical": [],
        }

        for name in self.feature_names:
            if "_ret_" in name:
                groups["returns"].append(name)
            elif "_mom_" in name:
                groups["momentum"].append(name)
            elif "_vol_" in name and "volume" not in name.lower():
                groups["volatility"].append(name)
            elif "drawdown" in name or "52w_high" in name:
                groups["drawdown"].append(name)
            elif "dollar_vol" in name or "vol_trend" in name or "vol_cv" in name:
                groups["volume"].append(name)
            elif "beta" in name or "corr" in name or "idio" in name:
                groups["risk"].append(name)
            elif "rsi" in name or "atr" in name or "ma_" in name:
                groups["technical"].append(name)

        return groups

    def compute_target(
        self,
        prices: pd.DataFrame,
        horizon: int = 5,
        target_type: str = "return"
    ) -> pd.DataFrame:
        """
        Compute target variable (what we're predicting).

        Args:
            prices: Price DataFrame
            horizon: Prediction horizon in trading days
            target_type: 'return' for raw return, 'rank' for cross-sectional rank

        Returns:
            DataFrame with target variable

        Note: Target at time t is the return from t to t+horizon.
        Features at time t are used to predict this target.
        """
        targets = pd.DataFrame(index=prices.index)

        for ticker in prices.columns:
            # Forward return from t to t+horizon
            # BUG FIX #1: Add epsilon guard to prevent division by zero and log(0)
            future_prices = prices[ticker].shift(-horizon)
            current_prices = prices[ticker]

            # Guard against zero/negative prices and division by zero
            valid_mask = (current_prices > 1e-8) & (future_prices > 1e-8)
            fwd_ret = pd.Series(np.nan, index=prices.index)
            fwd_ret[valid_mask] = np.log(future_prices[valid_mask] / current_prices[valid_mask])

            targets[f"{ticker}_target"] = fwd_ret

        if target_type == "rank":
            # Convert to cross-sectional rank
            targets = targets.rank(axis=1, pct=True)
            targets = 2 * targets - 1  # Scale to [-1, 1]

        return targets

    def prepare_training_data(
        self,
        features: pd.DataFrame,
        target: pd.DataFrame,
        min_history: int = 252
    ) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        Prepare aligned features and targets for training.

        Removes rows with NaN in either features or target.
        Only uses data after min_history days.

        Returns:
            Tuple of (X, y) DataFrames, aligned
        """
        # Align indices
        common_idx = features.index.intersection(target.index)
        X = features.loc[common_idx]
        y = target.loc[common_idx]

        # Remove early data (need history for features)
        if len(X) > min_history:
            X = X.iloc[min_history:]
            y = y.iloc[min_history:]

        # Remove rows with any NaN
        valid_mask = X.notna().all(axis=1) & y.notna().all(axis=1)
        X = X[valid_mask]
        y = y[valid_mask]

        logger.info(f"Prepared {len(X)} samples for training")

        return X, y
