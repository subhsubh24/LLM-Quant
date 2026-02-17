"""
Enhanced Multi-Factor Signal Engine with Advanced Features

This module extends the base signal engine with:
- Principal Component Analysis (PCA) for factor decorrelation
- Adaptive factor weighting based on rolling validation performance
- Regime-aware position sizing
- Sector rotation and correlation limits
- Advanced compositing that avoids multicollinearity

References:
- Blitz et al. (2013) "Quality Investing"
- Asness et al. (2019) "Fact, Fiction and Factor Investing"
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, date, timedelta
import numpy as np
import pandas as pd
import logging
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler

logger = logging.getLogger(__name__)


@dataclass
class AdaptiveWeights:
    """Adaptive factor weights with historical performance tracking."""
    momentum: float
    value: float
    quality: float
    volatility: float
    technical: float
    timestamp: datetime = field(default_factory=datetime.now)

    # Performance metrics used to compute weights
    momentum_sharpe: float = 0.0
    value_sharpe: float = 0.0
    quality_sharpe: float = 0.0
    volatility_sharpe: float = 0.0
    technical_sharpe: float = 0.0

    def to_dict(self) -> Dict[str, float]:
        """Convert to dictionary."""
        return {
            "momentum": self.momentum,
            "value": self.value,
            "quality": self.quality,
            "volatility": self.volatility,
            "technical": self.technical,
            "timestamp": self.timestamp.isoformat(),
            "sharpe_scores": {
                "momentum": self.momentum_sharpe,
                "value": self.value_sharpe,
                "quality": self.quality_sharpe,
                "volatility": self.volatility_sharpe,
                "technical": self.technical_sharpe,
            }
        }


class FactorDecorrelator:
    """
    Decorrelates factors using PCA to avoid multicollinearity.

    The key insight: factor returns are often highly correlated, so a simple
    linear combination amplifies errors. PCA extracts uncorrelated components.
    """

    def __init__(self, n_components: int = 4, variance_explained: float = 0.90):
        """
        Initialize decorrelator.

        Args:
            n_components: Number of PCA components to keep
            variance_explained: Target variance explained (overrides n_components if higher)
        """
        self.n_components = n_components
        self.variance_explained = variance_explained
        self.pca: Optional[PCA] = None
        self.scaler: Optional[StandardScaler] = None
        self.fitted = False

    def fit(self, factor_scores: pd.DataFrame) -> 'FactorDecorrelator':
        """
        Fit PCA on factor scores.

        Args:
            factor_scores: DataFrame with columns as factors, rows as stocks

        Returns:
            self
        """
        # Standardize factors
        self.scaler = StandardScaler()
        scaled = self.scaler.fit_transform(factor_scores.fillna(0))

        # Fit PCA with enough components to explain target variance
        pca = PCA(n_components=min(len(factor_scores.columns), self.n_components))
        pca.fit(scaled)

        # Select number of components
        cumsum = np.cumsum(pca.explained_variance_ratio_)
        n_keep = np.argmax(cumsum >= self.variance_explained) + 1
        n_keep = max(1, min(n_keep, self.n_components))

        self.pca = PCA(n_components=n_keep)
        self.pca.fit(scaled)
        self.fitted = True

        logger.info(
            f"PCA fitted with {n_keep} components explaining "
            f"{cumsum[n_keep-1]:.1%} variance"
        )

        return self

    def transform(self, factor_scores: pd.DataFrame) -> pd.DataFrame:
        """
        Transform factor scores into orthogonal components.

        Args:
            factor_scores: DataFrame with columns as factors

        Returns:
            DataFrame with PCA components as columns
        """
        if not self.fitted:
            raise ValueError("Decorrelator not fitted")

        scaled = self.scaler.transform(factor_scores.fillna(0))
        components = self.pca.transform(scaled)

        # Create DataFrame with component scores
        col_names = [f"PC{i+1}" for i in range(components.shape[1])]
        return pd.DataFrame(components, index=factor_scores.index, columns=col_names)


class AdaptiveWeightingSystem:
    """
    Adaptively weights factors based on recent out-of-sample performance.

    Key principle: factors perform differently in different market regimes.
    Rather than static weights, we track recent Sharpe ratios and reweight daily.
    """

    def __init__(
        self,
        lookback_days: int = 60,
        min_confidence: float = 0.3,
        momentum_factor: float = 0.2
    ):
        """
        Initialize adaptive weighting.

        Args:
            lookback_days: Rolling window for performance measurement
            min_confidence: Minimum score to override zero weight
            momentum_factor: Weight given to momentum in weight updates (0-1)
        """
        self.lookback_days = lookback_days
        self.min_confidence = min_confidence
        self.momentum_factor = momentum_factor
        self.performance_history: Dict[str, pd.Series] = {}
        self.previous_weights: Optional[Dict[str, float]] = None

    def compute_adaptive_weights(
        self,
        factor_returns: Dict[str, pd.Series],
        returns_actual: pd.Series,
        market_regime: str = "normal"
    ) -> AdaptiveWeights:
        """
        Compute adaptive weights based on rolling factor performance.

        Args:
            factor_returns: Dict of factor_name -> daily returns series
            returns_actual: Actual portfolio returns
            market_regime: Current market regime (bull, bear, normal, high_vol)

        Returns:
            AdaptiveWeights object with performance metrics
        """
        # Compute Sharpe for each factor in the lookback window
        lookback_returns = {}
        sharpe_scores = {}

        for factor_name, factor_ret in factor_returns.items():
            # Align with actual returns
            aligned = pd.DataFrame({
                'factor': factor_ret,
                'actual': returns_actual
            }).dropna()

            if len(aligned) < self.lookback_days:
                aligned = aligned
            else:
                aligned = aligned.iloc[-self.lookback_days:]

            if len(aligned) > 0:
                # Compute factor contribution to returns
                correlation = aligned['factor'].corr(aligned['actual'])
                factor_vol = aligned['factor'].std()

                # Sharpe approximation: correlation * factor vol
                sharpe = abs(correlation) * factor_vol if factor_vol > 0 else 0
                sharpe_scores[factor_name] = sharpe
                lookback_returns[factor_name] = aligned['factor'].mean() * 252
            else:
                sharpe_scores[factor_name] = 0
                lookback_returns[factor_name] = 0

        # Normalize Sharpe scores to weights
        total_sharpe = sum(abs(s) for s in sharpe_scores.values())

        if total_sharpe > self.min_confidence:
            # Weight by Sharpe ratio
            base_weights = {
                k: max(0, sharpe_scores[k]) / total_sharpe
                for k in sharpe_scores
            }
        else:
            # Fall back to equal weighting if confidence is low
            base_weights = {k: 0.2 for k in sharpe_scores}

        # Apply regime adjustments
        regime_adjustment = self._get_regime_adjustment(market_regime)
        adjusted_weights = {}
        for factor, weight in base_weights.items():
            adjusted_weights[factor] = weight * regime_adjustment.get(factor, 1.0)

        # Renormalize
        total_weight = sum(adjusted_weights.values())
        if total_weight > 0:
            adjusted_weights = {k: v / total_weight for k, v in adjusted_weights.items()}

        # Apply momentum to weights (slow changes)
        if self.previous_weights is not None:
            smoothed_weights = {}
            for factor in adjusted_weights:
                prev = self.previous_weights.get(factor, adjusted_weights[factor])
                new = adjusted_weights[factor]
                smoothed = prev * (1 - self.momentum_factor) + new * self.momentum_factor
                smoothed_weights[factor] = smoothed
            adjusted_weights = smoothed_weights

        # Renormalize again
        total_weight = sum(adjusted_weights.values())
        if total_weight > 0:
            adjusted_weights = {k: v / total_weight for k, v in adjusted_weights.items()}

        self.previous_weights = adjusted_weights

        return AdaptiveWeights(
            momentum=adjusted_weights.get('momentum', 0.2),
            value=adjusted_weights.get('value', 0.2),
            quality=adjusted_weights.get('quality', 0.2),
            volatility=adjusted_weights.get('volatility', 0.2),
            technical=adjusted_weights.get('technical', 0.2),
            momentum_sharpe=sharpe_scores.get('momentum', 0),
            value_sharpe=sharpe_scores.get('value', 0),
            quality_sharpe=sharpe_scores.get('quality', 0),
            volatility_sharpe=sharpe_scores.get('volatility', 0),
            technical_sharpe=sharpe_scores.get('technical', 0),
        )

    def _get_regime_adjustment(self, regime: str) -> Dict[str, float]:
        """Get factor weight adjustments for market regime."""
        adjustments = {
            "bull": {
                "momentum": 1.3,     # Momentum works in bull markets
                "value": 0.7,        # Value works in bear markets
                "quality": 1.0,
                "volatility": 0.8,   # High vol preferred in bull
                "technical": 1.1,
            },
            "bear": {
                "momentum": 0.5,     # Momentum reverses in bear
                "value": 1.5,        # Value works in bear
                "quality": 1.3,      # Quality defensive
                "volatility": 1.2,   # Low vol preferred
                "technical": 0.9,
            },
            "high_vol": {
                "momentum": 0.8,
                "value": 0.6,
                "quality": 1.4,      # Quality most important
                "volatility": 1.5,   # Volatility factor most important
                "technical": 1.1,
            },
            "normal": {
                "momentum": 1.0,
                "value": 1.0,
                "quality": 1.0,
                "volatility": 1.0,
                "technical": 1.0,
            }
        }
        return adjustments.get(regime, adjustments["normal"])


class SectorRotationManager:
    """
    Manages sector rotation to avoid concentrated risk.

    Implements:
    - Sector correlation tracking
    - Sector momentum detection
    - Position limits per sector
    - Factor rotation between growth/value
    """

    def __init__(
        self,
        sector_max_pct: float = 0.25,
        max_correlation: float = 0.85,
        rotation_lookback: int = 60
    ):
        """
        Initialize sector rotation manager.

        Args:
            sector_max_pct: Maximum % of portfolio in single sector
            max_correlation: Maximum correlation allowed between sector positions
            rotation_lookback: Lookback for sector momentum calculation
        """
        self.sector_max_pct = sector_max_pct
        self.max_correlation = max_correlation
        self.rotation_lookback = rotation_lookback

    def check_sector_concentration(
        self,
        weights: Dict[str, float],
        sector_map: Dict[str, str]
    ) -> Dict[str, float]:
        """
        Adjust weights to respect sector concentration limits.

        Args:
            weights: Current position weights
            sector_map: Dict of ticker -> sector mapping

        Returns:
            Adjusted weights respecting sector limits
        """
        # Normalize input weights first
        total_weight = sum(weights.values())
        if total_weight <= 0:
            return weights

        normalized = {k: v / total_weight for k, v in weights.items()}

        # Calculate sector exposures
        sector_weights = {}
        for ticker, weight in normalized.items():
            sector = sector_map.get(ticker, "other")
            sector_weights[sector] = sector_weights.get(sector, 0) + weight

        # Find overweight sectors
        overweight_sectors = {
            s: w for s, w in sector_weights.items()
            if w > self.sector_max_pct
        }

        if not overweight_sectors:
            return normalized

        # Scale down positions in overweight sectors
        adjusted = normalized.copy()
        for ticker in adjusted:
            sector = sector_map.get(ticker, "other")
            if sector in overweight_sectors:
                scale = self.sector_max_pct / sector_weights[sector]
                adjusted[ticker] *= scale

        # After scaling, renormalize but preserve the constraint
        # by capping each sector at the maximum
        total = sum(adjusted.values())
        if total > 0:
            # First pass: normalize
            normalized_again = {k: v / total for k, v in adjusted.items()}

            # Second pass: cap each sector and redistribute
            final = {}
            sector_totals = {}
            excess = 0

            for ticker, weight in normalized_again.items():
                sector = sector_map.get(ticker, "other")
                sector_totals[sector] = sector_totals.get(sector, 0) + weight

            # Find overweight sectors after first normalization
            for ticker, weight in normalized_again.items():
                sector = sector_map.get(ticker, "other")
                if sector_totals.get(sector, 0) > self.sector_max_pct:
                    # Trim excess from this sector
                    scale = self.sector_max_pct / sector_totals[sector]
                    final[ticker] = weight * scale
                else:
                    final[ticker] = weight

            # Final renormalization
            final_total = sum(final.values())
            if final_total > 0:
                final = {k: v / final_total for k, v in final.items()}

            return final

        return normalized

    def get_sector_momentum(
        self,
        prices: pd.DataFrame,
        sector_map: Dict[str, str],
        lookback: int = 60
    ) -> Dict[str, float]:
        """
        Calculate momentum by sector for rotation signals.

        Args:
            prices: Price DataFrame
            sector_map: Ticker -> sector mapping
            lookback: Lookback period in days

        Returns:
            Dict of sector -> momentum score
        """
        sector_returns = {}

        for sector in set(sector_map.values()):
            tickers = [t for t, s in sector_map.items() if s == sector]
            sector_prices = prices[tickers].mean(axis=1)

            if len(sector_prices) >= lookback:
                ret = (sector_prices.iloc[-1] / sector_prices.iloc[-lookback] - 1)
                sector_returns[sector] = ret
            else:
                sector_returns[sector] = 0

        return sector_returns


class EnhancedSignalEngine:
    """
    Enhanced signal engine combining all improvements:
    - Factor decorrelation
    - Adaptive weighting
    - Sector rotation
    - Regime-aware position sizing
    """

    def __init__(
        self,
        use_pca: bool = True,
        use_adaptive_weights: bool = True,
        use_sector_rotation: bool = True,
        decorrelation_lookback: int = 252
    ):
        """Initialize enhanced engine."""
        self.use_pca = use_pca
        self.use_adaptive_weights = use_adaptive_weights
        self.use_sector_rotation = use_sector_rotation
        self.decorrelation_lookback = decorrelation_lookback

        self.decorrelator: Optional[FactorDecorrelator] = None
        self.weighting_system: Optional[AdaptiveWeightingSystem] = None
        self.sector_manager: Optional[SectorRotationManager] = None

        if use_adaptive_weights:
            self.weighting_system = AdaptiveWeightingSystem()
        if use_sector_rotation:
            self.sector_manager = SectorRotationManager()

    def compute_decorrelated_factors(
        self,
        momentum_scores: Dict[str, float],
        value_scores: Dict[str, float],
        quality_scores: Dict[str, float],
        volatility_scores: Dict[str, float],
        technical_scores: Dict[str, float]
    ) -> Tuple[pd.DataFrame, Dict[str, List[float]]]:
        """
        Decorrelate factor scores using PCA.

        Returns:
            - DataFrame of decorrelated factor scores
            - Dict mapping original factors to PC loadings
        """
        # Combine into DataFrame
        factor_df = pd.DataFrame({
            'momentum': pd.Series(momentum_scores),
            'value': pd.Series(value_scores),
            'quality': pd.Series(quality_scores),
            'volatility': pd.Series(volatility_scores),
            'technical': pd.Series(technical_scores),
        }).fillna(0)

        if not self.use_pca or len(factor_df) < 10:
            # Fall back if insufficient data
            return factor_df, {}

        # Fit decorrelator
        decorrelator = FactorDecorrelator(variance_explained=0.90)
        decorrelator.fit(factor_df)

        # Transform to decorrelated components
        decorrelated = decorrelator.transform(factor_df)

        # Get PCA loadings (how original factors contribute to PCs)
        loadings = {}
        for i, factor in enumerate(factor_df.columns):
            loadings[factor] = decorrelator.pca.components_[0, :].tolist()

        self.decorrelator = decorrelator

        return decorrelated, loadings

    def compose_composite_score(
        self,
        momentum: float,
        value: float,
        quality: float,
        volatility: float,
        technical: float,
        weights: Optional[Dict[str, float]] = None
    ) -> float:
        """
        Compose final score from factor scores using adaptive weights.

        Args:
            Individual factor scores (normalized -1 to 1)
            weights: Optional custom weights (else use adaptive)

        Returns:
            Composite score (-1 to 1)
        """
        if weights is None:
            weights = {
                'momentum': 0.25,
                'value': 0.20,
                'quality': 0.20,
                'volatility': 0.15,
                'technical': 0.20,
            }

        # Ensure weights sum to 1
        total_weight = sum(weights.values())
        if total_weight > 0:
            weights = {k: v / total_weight for k, v in weights.items()}

        # Composite with proper normalization
        composite = (
            weights.get('momentum', 0) * momentum +
            weights.get('value', 0) * value +
            weights.get('quality', 0) * quality +
            weights.get('volatility', 0) * volatility +
            weights.get('technical', 0) * technical
        )

        # Clip to [-1, 1]
        return np.clip(composite, -1, 1)


# Utility functions for integration
def create_enhanced_engine(
    use_pca: bool = True,
    use_adaptive_weights: bool = True,
    use_sector_rotation: bool = True
) -> EnhancedSignalEngine:
    """Factory function to create enhanced engine with all features."""
    return EnhancedSignalEngine(
        use_pca=use_pca,
        use_adaptive_weights=use_adaptive_weights,
        use_sector_rotation=use_sector_rotation
    )
