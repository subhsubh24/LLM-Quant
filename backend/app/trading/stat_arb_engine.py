"""
Statistical Arbitrage Engine

Implements low-correlation systematic strategies:
- Pairs trading with cointegration
- Mean-reversion in correlation spreads
- Funding rate arbitrage (crypto)
- Calendar spreads (derivatives)

Key references:
- Vidyamurthy (2004) "Pairs Trading"
- Gatev et al. (2006) "Pairs Trading Performance"
- Johansen & Juselius (1990) "Cointegration in VAR"
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta
from enum import Enum
import numpy as np
import pandas as pd
import logging
from scipy import stats

logger = logging.getLogger(__name__)


class ArbitrageType(Enum):
    """Types of statistical arbitrage strategies."""
    PAIRS_TRADING = "pairs"
    CORRELATION_MEAN_REVERSION = "corr_mean_reversion"
    FUNDING_RATE_ARBITRAGE = "funding_rate"
    CALENDAR_SPREAD = "calendar"


@dataclass
class PairSignal:
    """Signal for pairs trading."""
    symbol_a: str
    symbol_b: str
    timestamp: datetime

    # Cointegration info
    adf_statistic: float  # Lower is more cointegrated
    adf_pvalue: float
    cointegration_score: float  # 0-1, 1=perfectly cointegrated

    # Spread info
    spread_current: float  # Current spread
    spread_zscore: float  # Z-score of spread

    # Entry/exit signals
    action: str = "HOLD"  # BUY_A_SELL_B, SELL_A_BUY_B, CLOSE, HOLD
    confidence: float = 0.0  # 0-1
    target_entry_zscore: float = 2.0  # Entry when spread > ±2 std dev
    target_exit_zscore: float = 0.5  # Exit when spread < ±0.5 std dev

    # Position sizing
    position_ratio_a_to_b: float = 1.0  # How many A to buy for each B sold
    recommended_size_a: float = 0.0
    recommended_size_b: float = 0.0

    # Risk metrics
    expected_return: float = 0.0
    expected_volatility: float = 0.0
    holding_period_days: int = 0

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            "symbol_a": self.symbol_a,
            "symbol_b": self.symbol_b,
            "timestamp": self.timestamp.isoformat(),
            "adf_statistic": round(self.adf_statistic, 4),
            "adf_pvalue": round(self.adf_pvalue, 4),
            "cointegration_score": round(self.cointegration_score, 3),
            "spread_current": round(self.spread_current, 6),
            "spread_zscore": round(self.spread_zscore, 3),
            "action": self.action,
            "confidence": round(self.confidence, 3),
            "position_ratio_a_to_b": round(self.position_ratio_a_to_b, 3),
            "expected_return": round(self.expected_return, 4),
            "expected_volatility": round(self.expected_volatility, 4),
            "holding_period_days": self.holding_period_days,
        }


class CointegrationTester:
    """
    Tests for cointegration using Augmented Dickey-Fuller (ADF).

    Johansen test for multivariate cointegration can be added later.
    """

    def __init__(self, lookback_days: int = 252):
        """
        Initialize tester.

        Args:
            lookback_days: Window for cointegration testing
        """
        self.lookback_days = lookback_days

    def test_adf(
        self,
        series: pd.Series,
        maxlag: int = 10,
        regression: str = "c"
    ) -> Tuple[float, float]:
        """
        Augmented Dickey-Fuller test.

        Args:
            series: Time series to test
            maxlag: Maximum number of lags
            regression: Regression type ('c'=constant, 'ct'=constant+trend)

        Returns:
            (adf_statistic, pvalue)
        """
        from statsmodels.tsa.stattools import adfuller

        try:
            result = adfuller(series.dropna(), maxlag=maxlag, regression=regression)
            return result[0], result[1]
        except Exception as e:
            logger.warning(f"ADF test failed: {e}")
            return 0, 1  # Return non-significant result

    def find_cointegration_strength(
        self,
        price_a: pd.Series,
        price_b: pd.Series,
        method: str = "adf"
    ) -> Tuple[float, float, float]:
        """
        Find cointegration strength between two price series.

        Args:
            price_a: Price series A
            price_b: Price series B
            method: 'adf' for ADF on spread

        Returns:
            (adf_statistic, pvalue, cointegration_score)
            cointegration_score: 0-1 where 1=strongly cointegrated
        """
        # Normalize prices to same scale
        a_norm = (price_a - price_a.mean()) / price_a.std()
        b_norm = (price_b - price_b.mean()) / price_b.std()

        # Find hedge ratio using OLS regression
        X = np.column_stack([np.ones(len(a_norm)), b_norm])
        try:
            beta = np.linalg.lstsq(X, a_norm, rcond=None)[0]
            hedge_ratio = beta[1]
        except Exception as e:
            # BUG FIX #2: Use specific exception handling instead of bare except
            logger.warning(f"OLS regression failed for hedge ratio calculation: {e}")
            hedge_ratio = 1.0

        # Compute spread
        spread = price_a - hedge_ratio * price_b

        # Test if spread is mean-reverting (stationary)
        adf_stat, pvalue = self.test_adf(spread)

        # Cointegration score: higher = more mean-reverting
        # Score 1 if pvalue < 0.05 (statistically significant)
        coint_score = max(0, min(1, 1 - pvalue * 2))

        return adf_stat, pvalue, coint_score


class PairsTradingEngine:
    """
    Pairs trading using cointegration and mean-reversion.

    Strategy:
    1. Identify cointegrated pairs (hedged long-short)
    2. Monitor spread for mean-reversion
    3. Enter when spread reaches 2+ sigma
    4. Exit when spread reverts to mean
    """

    def __init__(
        self,
        lookback_days: int = 252,
        min_cointegration_score: float = 0.70,
        zscore_entry: float = 2.0,
        zscore_exit: float = 0.5,
    ):
        """
        Initialize pairs trading engine.

        Args:
            lookback_days: Window for cointegration testing
            min_cointegration_score: Minimum score to consider pair
            zscore_entry: Z-score threshold for entry
            zscore_exit: Z-score threshold for exit
        """
        self.lookback_days = lookback_days
        self.min_cointegration_score = min_cointegration_score
        self.zscore_entry = zscore_entry
        self.zscore_exit = zscore_exit
        self.coint_tester = CointegrationTester(lookback_days)
        self.pair_hedges: Dict[str, float] = {}  # Cache hedge ratios

    def find_pairs(
        self,
        prices: pd.DataFrame,
        sectors: Optional[Dict[str, str]] = None,
        same_sector_only: bool = False,
        max_pairs: int = 50,
    ) -> List[PairSignal]:
        """
        Find profitable pairs in universe.

        Args:
            prices: DataFrame with dates x tickers
            sectors: Optional ticker -> sector mapping
            same_sector_only: Only pair stocks in same sector
            max_pairs: Maximum pairs to return

        Returns:
            List of PairSignals for top pairs by cointegration
        """
        candidates = []
        tickers = prices.columns.tolist()

        # Get lookback window
        if len(prices) >= self.lookback_days:
            prices_window = prices.iloc[-self.lookback_days:]
        else:
            prices_window = prices

        # Test each pair (upper triangle to avoid duplicates)
        for i, ticker_a in enumerate(tickers):
            for ticker_b in tickers[i+1:]:
                try:
                    # Sector filter if specified
                    if same_sector_only and sectors:
                        sector_a = sectors.get(ticker_a)
                        sector_b = sectors.get(ticker_b)
                        if sector_a != sector_b:
                            continue

                    # Get prices
                    price_a = prices_window[ticker_a].dropna()
                    price_b = prices_window[ticker_b].dropna()

                    if len(price_a) < 50 or len(price_b) < 50:
                        continue

                    # Test cointegration
                    adf_stat, pvalue, coint_score = (
                        self.coint_tester.find_cointegration_strength(price_a, price_b)
                    )

                    if coint_score >= self.min_cointegration_score:
                        # Compute hedge ratio
                        a_norm = (price_a - price_a.mean()) / price_a.std()
                        b_norm = (price_b - price_b.mean()) / price_b.std()
                        X = np.column_stack([np.ones(len(a_norm)), b_norm])
                        beta = np.linalg.lstsq(X, a_norm, rcond=None)[0]
                        hedge_ratio = beta[1]

                        self.pair_hedges[f"{ticker_a}_{ticker_b}"] = hedge_ratio

                        # Create signal
                        signal = PairSignal(
                            symbol_a=ticker_a,
                            symbol_b=ticker_b,
                            timestamp=datetime.now(),
                            adf_statistic=adf_stat,
                            adf_pvalue=pvalue,
                            cointegration_score=coint_score,
                            spread_current=0.0,  # Will compute in signal generation
                            spread_zscore=0.0,
                            position_ratio_a_to_b=abs(hedge_ratio),
                        )
                        candidates.append((signal, coint_score))

                except Exception as e:
                    logger.debug(f"Error testing pair {ticker_a}-{ticker_b}: {e}")
                    continue

        # Sort by cointegration score and return top N
        candidates.sort(key=lambda x: x[1], reverse=True)
        return [s for s, _ in candidates[:max_pairs]]

    def generate_pair_signals(
        self,
        prices: pd.DataFrame,
        pairs: List[PairSignal],
        spread_lookback: int = 60,
    ) -> List[PairSignal]:
        """
        Generate trading signals for identified pairs.

        Args:
            prices: Price data
            pairs: List of pairs from find_pairs()
            spread_lookback: Window for spread statistics

        Returns:
            Updated pair signals with entry/exit recommendations
        """
        for pair in pairs:
            try:
                # Get prices
                price_a = prices[pair.symbol_a].dropna()
                price_b = prices[pair.symbol_b].dropna()

                if len(price_a) == 0 or len(price_b) == 0:
                    continue

                # Compute spread
                hedge_ratio = self.pair_hedges.get(
                    f"{pair.symbol_a}_{pair.symbol_b}",
                    pair.position_ratio_a_to_b
                )
                spread = price_a - hedge_ratio * price_b

                # Get historical spread stats (last spread_lookback days)
                if len(spread) >= spread_lookback:
                    spread_hist = spread.iloc[-spread_lookback:]
                else:
                    spread_hist = spread

                spread_mean = spread_hist.mean()
                spread_std = spread_hist.std()

                # Current Z-score
                if spread_std > 0:
                    zscore = (spread.iloc[-1] - spread_mean) / spread_std
                else:
                    zscore = 0

                pair.spread_current = spread.iloc[-1]
                pair.spread_zscore = zscore
                pair.expected_volatility = spread_std * np.sqrt(252)  # Annualized

                # Generate action
                if abs(zscore) >= self.zscore_entry:
                    # Extreme spread - trade it
                    if zscore > 0:
                        # Spread too high, sell A buy B
                        pair.action = "SELL_A_BUY_B"
                        pair.expected_return = (zscore - self.zscore_exit) * spread_std / 252
                    else:
                        # Spread too low, buy A sell B
                        pair.action = "BUY_A_SELL_B"
                        pair.expected_return = (abs(zscore) - self.zscore_exit) * spread_std / 252

                    pair.confidence = min(0.95, abs(zscore) / 3.0)  # Max 95% confidence
                    pair.holding_period_days = 30  # Typical holding

                elif abs(zscore) >= self.zscore_exit:
                    # Partially reverted, close position if open
                    pair.action = "CLOSE"
                    pair.confidence = 0.8
                else:
                    # Normal range, hold or don't trade
                    pair.action = "HOLD"
                    pair.confidence = 0.5

            except Exception as e:
                logger.debug(f"Error generating signal for {pair.symbol_a}-{pair.symbol_b}: {e}")
                pair.action = "HOLD"

        return pairs


class MeanReversionDetector:
    """
    Detects mean-reversion opportunities in correlation spreads.

    Strategy: Find asset pairs with elevated correlation and trade the divergence.
    """

    def __init__(
        self,
        correlation_lookback: int = 60,
        deviation_threshold: float = 1.5,
        min_correlation: float = 0.7,
    ):
        """
        Initialize mean-reversion detector.

        Args:
            correlation_lookback: Window for correlation calculation
            deviation_threshold: Threshold for correlation deviation
            min_correlation: Minimum correlation to monitor
        """
        self.correlation_lookback = correlation_lookback
        self.deviation_threshold = deviation_threshold
        self.min_correlation = min_correlation

    def detect_correlation_breakdown(
        self,
        price_a: pd.Series,
        price_b: pd.Series,
    ) -> Tuple[float, float, float, str]:
        """
        Detect correlation breakdowns (mean-reversion signal).

        Args:
            price_a: Price series A
            price_b: Price series B

        Returns:
            (correlation_now, correlation_mean, deviation, action)
            action: "mean_revert_a_buy" | "mean_revert_b_buy" | "hold"
        """
        # Compute returns
        ret_a = price_a.pct_change().dropna()
        ret_b = price_b.pct_change().dropna()

        if len(ret_a) < self.correlation_lookback:
            return 0, 0, 0, "hold"

        # Current correlation (last 60 days)
        recent_returns = pd.DataFrame({
            'a': ret_a.iloc[-self.correlation_lookback:],
            'b': ret_b.iloc[-self.correlation_lookback:],
        })
        corr_now = recent_returns['a'].corr(recent_returns['b'])

        # Historical correlation (previous 60 days)
        if len(ret_a) >= 2 * self.correlation_lookback:
            historical = pd.DataFrame({
                'a': ret_a.iloc[-2*self.correlation_lookback:-self.correlation_lookback],
                'b': ret_b.iloc[-2*self.correlation_lookback:-self.correlation_lookback],
            })
            corr_hist = historical['a'].corr(historical['b'])
        else:
            corr_hist = corr_now

        corr_mean = (corr_now + corr_hist) / 2

        # Detect breakdown
        if abs(corr_now - corr_mean) > self.deviation_threshold * 0.1:  # 0.1 = rough std dev
            deviation = abs(corr_now - corr_mean)

            # Mean reversion signal
            if corr_now < corr_mean and corr_now < self.min_correlation:
                # Correlation collapsed, expect reversion
                if price_a.iloc[-1] > price_a.iloc[-5:].mean():
                    action = "mean_revert_b_buy"  # B likely to rally
                else:
                    action = "mean_revert_a_buy"  # A likely to rally
            else:
                action = "hold"
        else:
            deviation = 0
            action = "hold"

        return corr_now, corr_mean, deviation, action


class StatArbEngine:
    """
    Main statistical arbitrage engine orchestrator.

    Combines multiple stat arb strategies:
    - Pairs trading
    - Correlation mean-reversion
    - Spread trading
    """

    def __init__(
        self,
        lookback_days: int = 252,
        use_pairs_trading: bool = True,
        use_correlation_arb: bool = True,
        pairs_per_strategy: int = 25,
    ):
        """
        Initialize stat arb engine.

        Args:
            lookback_days: Historical window for cointegration
            use_pairs_trading: Enable pairs trading strategy
            use_correlation_arb: Enable correlation arbitrage
            pairs_per_strategy: Max pairs per strategy
        """
        self.lookback_days = lookback_days
        self.use_pairs_trading = use_pairs_trading
        self.use_correlation_arb = use_correlation_arb
        self.pairs_per_strategy = pairs_per_strategy

        self.pairs_engine = PairsTradingEngine(lookback_days=lookback_days)
        self.correlation_detector = MeanReversionDetector()

    def generate_strategies(
        self,
        prices: pd.DataFrame,
        sectors: Optional[Dict[str, str]] = None,
    ) -> Dict[str, List[PairSignal]]:
        """
        Generate all stat arb strategies.

        Args:
            prices: Price DataFrame
            sectors: Optional sector mapping

        Returns:
            Dict with strategy -> list of signals
        """
        strategies = {}

        # Pairs trading strategy
        if self.use_pairs_trading:
            pairs = self.pairs_engine.find_pairs(
                prices,
                sectors=sectors,
                max_pairs=self.pairs_per_strategy
            )
            pair_signals = self.pairs_engine.generate_pair_signals(
                prices, pairs
            )
            strategies['pairs_trading'] = pair_signals

        # Could add more strategies here
        # - Correlation arbitrage
        # - Calendar spreads
        # - Funding rate arbitrage

        return strategies

    def get_all_signals(
        self,
        strategies: Dict[str, List[PairSignal]]
    ) -> List[PairSignal]:
        """
        Get all stat arb signals combined.

        Args:
            strategies: Output from generate_strategies()

        Returns:
            Combined list of all signals
        """
        all_signals = []
        for strategy_name, signals in strategies.items():
            all_signals.extend(signals)

        # Sort by confidence
        all_signals.sort(key=lambda x: x.confidence, reverse=True)

        return all_signals
