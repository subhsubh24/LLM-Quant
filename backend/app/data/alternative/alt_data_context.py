"""
Alternative data context for the backtester's feature system.

This bridges the alternative data providers (pandas-based, daily frequency)
with the backtester's feature system (numpy-based, hourly candles).

The backtester operates on OHLCV candles (often hourly). Alternative data
is daily or lower frequency. This class:

1. Pre-computes all alternative data features for a date range
2. Converts them to a flat numpy array indexed by date
3. Provides fast lookup: given a candle timestamp, returns the
   alternative data feature vector for that date
4. Handles the frequency mismatch (many candles map to the same
   day of alt data, which is correct - alt data doesn't change intraday)

USAGE IN BACKTESTER:

    # During setup
    alt_context = AltDataContext()
    alt_context.prepare(start_date, end_date)

    # During feature extraction (inside prepare_features loop)
    candle_date = candle.timestamp.date()
    alt_vector = alt_context.get_features(candle_date)  # numpy array
    feature_vector = base_features + list(alt_vector)    # append to 64-dim
"""

from datetime import date, timedelta
from typing import Optional, List, Dict
import bisect
import pandas as pd
import numpy as np
import logging

from .base import AltDataConfig
from .alt_feature_engineer import AlternativeFeatureEngineer

logger = logging.getLogger(__name__)


class AltDataContext:
    """
    Pre-computed alternative data context for fast lookup during backtesting.

    Computes all alternative data features once, stores them as a numpy
    matrix indexed by date, and provides O(1) lookup per candle.
    """

    def __init__(self, config: Optional[AltDataConfig] = None):
        self.config = config or AltDataConfig()
        self._engineer = AlternativeFeatureEngineer(self.config)

        # Internal state (populated by prepare())
        self._features: Optional[np.ndarray] = None
        self._feature_names: List[str] = []
        self._date_to_idx: Dict[date, int] = {}
        self._sorted_dates: List[date] = []  # For binary search fallback
        self._n_features: int = 0
        self._is_prepared: bool = False

    @property
    def n_features(self) -> int:
        """Number of alternative data features per timestep."""
        return self._n_features

    @property
    def feature_names(self) -> List[str]:
        """Names of alternative data features."""
        return self._feature_names

    @property
    def is_prepared(self) -> bool:
        """Whether prepare() has been called successfully."""
        return self._is_prepared

    def prepare(
        self,
        start_date: date,
        end_date: date,
    ) -> bool:
        """
        Pre-compute alternative data features for the date range.

        Returns True if features were successfully computed.
        Returns False if all providers failed (backtester should proceed
        without alt data).
        """
        try:
            logger.info(
                f"AltDataContext: preparing features from {start_date} to {end_date}"
            )

            # Compute all features
            features_df = self._engineer.compute_features(
                start_date=start_date,
                end_date=end_date,
            )

            if features_df.empty:
                logger.warning("AltDataContext: no features computed")
                self._is_prepared = False
                return False

            # Feature selection BEFORE fillna so correlation matrix
            # isn't biased by leading zeros from lag shift (BUG #8 fix)
            n_before = len(features_df.columns)
            features_df = self._select_features(features_df)
            n_after = len(features_df.columns)
            if n_before != n_after:
                logger.info(
                    f"Feature selection: {n_before} → {n_after} features "
                    f"(removed {n_before - n_after} noisy/redundant)"
                )

            # Fill remaining NaN with 0 AFTER selection (safe for model input)
            features_df = features_df.fillna(0.0)

            # Store feature names
            self._feature_names = features_df.columns.tolist()
            self._n_features = len(self._feature_names)

            # Convert to numpy for fast lookup
            self._features = features_df.values.astype(np.float32)

            # Build date -> row index map
            self._date_to_idx = {}
            for i, ts in enumerate(features_df.index):
                d = ts.date() if hasattr(ts, 'date') else ts
                self._date_to_idx[d] = i

            # Pre-sort dates for binary search in get_features()
            self._sorted_dates = sorted(self._date_to_idx.keys())

            self._is_prepared = True

            logger.info(
                f"AltDataContext: prepared {self._n_features} features "
                f"for {len(self._date_to_idx)} dates"
            )

            return True

        except Exception as e:
            logger.error(f"AltDataContext preparation failed: {e}")
            self._is_prepared = False
            return False

    def get_features(self, query_date: date) -> np.ndarray:
        """
        Get alternative data feature vector for a specific date.

        Returns:
            numpy array of shape (n_features,) with alt data for that date.
            Returns zeros if date is not in the prepared range.

        This is designed to be called inside the backtester's
        prepare_features() loop, once per candle.
        """
        if not self._is_prepared or self._features is None:
            return np.zeros(max(self._n_features, 1), dtype=np.float32)

        idx = self._date_to_idx.get(query_date)
        if idx is not None:
            return self._features[idx]

        # If exact date not found, find the most recent available date
        # (forward-fill logic - use last available data)
        if not self._sorted_dates:
            return np.zeros(self._n_features, dtype=np.float32)

        # Binary search for the latest date <= query_date (O(log n))
        pos = bisect.bisect_right(self._sorted_dates, query_date)
        if pos > 0:
            best_date = self._sorted_dates[pos - 1]
            return self._features[self._date_to_idx[best_date]]

        return np.zeros(self._n_features, dtype=np.float32)

    def _select_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Feature selection to remove noise and redundancy.

        Steps:
        1. Drop constant features (zero variance - carry no information)
        2. Drop near-constant features (>95% same value)
        3. Drop highly correlated features (|corr| > 0.95 - redundant)

        This reduces dimensionality without losing signal, which:
        - Speeds up training
        - Reduces overfitting risk
        - Focuses model capacity on informative features
        """
        if df.empty or len(df.columns) < 2:
            return df

        cols_to_keep = list(df.columns)

        # 1. Drop constant features (variance = 0)
        variances = df.var()
        constant_cols = variances[variances < 1e-10].index.tolist()
        if constant_cols:
            cols_to_keep = [c for c in cols_to_keep if c not in constant_cols]
            logger.info(f"  Dropped {len(constant_cols)} constant features")

        # 2. Drop near-constant features (>95% identical values)
        near_constant = []
        for col in cols_to_keep:
            if col in df.columns:
                mode_pct = df[col].value_counts(normalize=True).iloc[0] if len(df[col].value_counts()) > 0 else 1.0
                if mode_pct > 0.95:
                    # Exception: binary features by design (calendar flags, regimes)
                    # These are meant to be mostly 0 with occasional 1s
                    is_binary = set(df[col].unique()) <= {0.0, 1.0, 0, 1}
                    if not is_binary:
                        near_constant.append(col)
        if near_constant:
            cols_to_keep = [c for c in cols_to_keep if c not in near_constant]
            logger.info(f"  Dropped {len(near_constant)} near-constant features")

        # 3. Drop highly correlated features (keep the one with higher variance)
        if len(cols_to_keep) > 5:
            try:
                corr_matrix = df[cols_to_keep].corr().abs()
                # Create upper triangle mask
                upper = corr_matrix.where(
                    np.triu(np.ones(corr_matrix.shape), k=1).astype(bool)
                )
                # Find pairs with correlation > 0.95
                redundant = set()
                for col in upper.columns:
                    highly_corr = upper.index[upper[col] > 0.95].tolist()
                    for hc in highly_corr:
                        # Drop the one with lower variance
                        if hc not in redundant:
                            if variances.get(col, 0) >= variances.get(hc, 0):
                                redundant.add(hc)
                            else:
                                redundant.add(col)
                if redundant:
                    cols_to_keep = [c for c in cols_to_keep if c not in redundant]
                    logger.info(f"  Dropped {len(redundant)} redundant features (|corr| > 0.95)")
            except Exception as e:
                logger.debug(f"Correlation check skipped: {e}")

        return df[cols_to_keep]

    def get_summary(self) -> Dict:
        """Get summary statistics about the prepared context."""
        if not self._is_prepared:
            return {"status": "not_prepared"}

        groups = self._engineer.get_feature_groups()
        group_counts = {k: len(v) for k, v in groups.items() if v}

        return {
            "status": "prepared",
            "n_features": self._n_features,
            "n_dates": len(self._date_to_idx),
            "date_range": {
                "start": min(self._date_to_idx.keys()).isoformat() if self._date_to_idx else None,
                "end": max(self._date_to_idx.keys()).isoformat() if self._date_to_idx else None,
            },
            "feature_groups": group_counts,
        }
