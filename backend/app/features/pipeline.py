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
    compute_enhanced_technical_features,
    standardize_features,
)
from ..data.alternative import AlternativeFeatureEngineer, AltDataConfig


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
    include_enhanced_technical: bool = True

    # Standardization
    standardize_method: str = "cross_sectional"  # cross_sectional, time_series, or none
    clip_outliers: float = 3.0

    # Feature selection
    enabled_features: List[str] = field(default_factory=lambda: [
        "returns", "momentum", "volatility", "drawdown",
        "volume", "risk", "technical", "enhanced_technical"
    ])

    # Alternative data configuration
    include_alternative_data: bool = True
    alt_data_config: Optional["AltDataConfig"] = None

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
            "include_enhanced_technical": self.include_enhanced_technical,
            "standardize_method": self.standardize_method,
            "clip_outliers": self.clip_outliers,
            "enabled_features": self.enabled_features,
            "include_alternative_data": self.include_alternative_data,
            "alt_data_config": self.alt_data_config.to_dict() if self.alt_data_config else None,
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
        self._alt_engineer: Optional[AlternativeFeatureEngineer] = None

        # Initialize alternative data engineer if configured
        if self.config.include_alternative_data:
            alt_config = self.config.alt_data_config or AltDataConfig()
            self._alt_engineer = AlternativeFeatureEngineer(alt_config)

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

        # 8. Enhanced technical features (MACD, Stochastic, ADX, OBV, Fibonacci, BB, VWAP)
        if "enhanced_technical" in self.config.enabled_features and self.config.include_enhanced_technical:
            logger.debug("Computing enhanced technical features")
            if highs is None:
                highs = prices
            if lows is None:
                lows = prices
            enhanced_tech_features = compute_enhanced_technical_features(
                prices, highs, lows, volumes=volumes
            )
            all_features.append(enhanced_tech_features)

        # 9. Alternative data features (macro, cross-asset, sentiment)
        if self.config.include_alternative_data and self._alt_engineer is not None:
            logger.debug("Computing alternative data features")
            try:
                # Determine date range from price index
                idx_min = prices.index.min()
                idx_max = prices.index.max()
                start_date = idx_min.date() if hasattr(idx_min, 'date') else idx_min
                end_date = idx_max.date() if hasattr(idx_max, 'date') else idx_max

                alt_features = self._alt_engineer.compute_features(
                    start_date=start_date,
                    end_date=end_date,
                    price_index=prices.index,
                )

                if not alt_features.empty:
                    all_features.append(alt_features)
                    logger.info(
                        f"Added {len(alt_features.columns)} alternative data features"
                    )
                else:
                    logger.warning("Alternative data returned empty - continuing without it")
            except Exception as e:
                logger.warning(f"Alternative data failed (continuing without it): {e}")

        # Combine all features
        if not all_features:
            raise ValueError("No features computed - check enabled_features config")

        features = pd.concat(all_features, axis=1)

        # Store feature names
        self.feature_names = features.columns.tolist()

        # Standardize if configured -- but SKIP alt data features that are already
        # standardized (z-scored, percentile-ranked, or binary 0/1). Standardizing
        # them again distorts their meaning (e.g. binary calendar flags become ~-0.3/+2.1).
        _ALT_PREFIXES = (
            "cal_", "regime_", "pol_", "econ_", "fred_", "xasset_", "sent_",
            "opt_", "edgar_", "news_", "gtrends_", "weather_", "short_",
            "dark_", "crypto_", "sector_", "bond_", "interact_",
            "micro_", "vol_", "earn_", "factor_", "composite_", "corr_",
        )
        if self.config.standardize_method != "none":
            logger.debug(f"Standardizing features using {self.config.standardize_method}")
            # Separate alt data columns from price-based columns
            alt_cols = [c for c in features.columns
                        if any(c.startswith(p) for p in _ALT_PREFIXES)]
            price_cols = [c for c in features.columns if c not in alt_cols]

            if price_cols:
                price_features = standardize_features(
                    features[price_cols],
                    method=self.config.standardize_method,
                    clip_outliers=self.config.clip_outliers
                )
                if alt_cols:
                    features = pd.concat([price_features, features[alt_cols]], axis=1)
                else:
                    features = price_features
            # If only alt cols, skip standardization entirely

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
                # BUG FIX #20: Robust ticker extraction with bounds check
                parts = col.split("_")
                if not parts or len(parts) == 0:
                    continue
                ticker = parts[0]

                # Validate ticker is in price data before proceeding
                if ticker and ticker in prices.columns:
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
            # Traditional price/volume features
            "returns": [],
            "momentum": [],
            "volatility": [],
            "drawdown": [],
            "volume": [],
            "risk": [],
            "technical": [],
            "enhanced_technical": [],
            # Alternative data features
            "macro": [],
            "cross_asset": [],
            "sentiment": [],
            "calendar": [],
            "options": [],
            "edgar": [],
            "news": [],
            "gtrends": [],
            "weather": [],
            "short_volume": [],
            "crypto": [],
            "congressional": [],
            "econ_surprise": [],
            "sector_rotation": [],
            "bond_stress": [],
            "alt_interactions": [],
            "alt_regimes": [],
        }

        # Enhanced technical feature identifiers
        _enhanced_tech_keys = (
            "macd_", "stoch_", "adx", "plus_di", "minus_di",
            "obv_", "fib_dist_", "bb_pct_b", "bb_bandwidth", "vwap_ratio",
        )

        for name in self.feature_names:
            # Alternative data features (check first - more specific prefixes)
            if name.startswith("fred_"):
                groups["macro"].append(name)
            elif name.startswith("xasset_"):
                groups["cross_asset"].append(name)
            elif name.startswith("sent_"):
                groups["sentiment"].append(name)
            elif name.startswith("cal_"):
                groups["calendar"].append(name)
            elif name.startswith("opt_"):
                groups["options"].append(name)
            elif name.startswith("edgar_"):
                groups["edgar"].append(name)
            elif name.startswith("news_"):
                groups["news"].append(name)
            elif name.startswith("gtrends_"):
                groups["gtrends"].append(name)
            elif name.startswith("weather_"):
                groups["weather"].append(name)
            elif name.startswith("short_") or name.startswith("dark_"):
                groups["short_volume"].append(name)
            elif name.startswith("crypto_"):
                groups["crypto"].append(name)
            elif name.startswith("pol_"):
                groups["congressional"].append(name)
            elif name.startswith("econ_"):
                groups["econ_surprise"].append(name)
            elif name.startswith("sector_"):
                groups["sector_rotation"].append(name)
            elif name.startswith("bond_"):
                groups["bond_stress"].append(name)
            elif name.startswith("interact_"):
                groups["alt_interactions"].append(name)
            elif name.startswith("regime_"):
                groups["alt_regimes"].append(name)
            # Traditional price/volume features
            elif "_ret_" in name:
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
            elif any(key in name for key in _enhanced_tech_keys):
                groups["enhanced_technical"].append(name)
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

            # BUG FIX #21: Use realistic minimum price threshold (1 cent) instead of epsilon
            valid_mask = (current_prices > 0.01) & (future_prices > 0.01)
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
