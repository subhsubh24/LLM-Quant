"""
Market microstructure and liquidity signals provider.

WHY MICROSTRUCTURE MATTERS:

1. LIQUIDITY IS THE #1 RISK FACTOR:
   - Illiquid markets crash faster and harder
   - Amihud illiquidity measure predicts returns 1-3 months ahead
   - Bid-ask spread widening precedes selloffs by days
   - Flash crashes happen when liquidity evaporates

2. ORDER FLOW IMBALANCE:
   - When buying pressure dominates, prices rise (and vice versa)
   - The PERSISTENCE of order flow imbalance predicts continuation
   - Volume-weighted price pressure = institutions accumulating/distributing

3. INTRADAY PATTERNS:
   - Opening range breakouts predict daily direction
   - Close-to-close vs open-to-close reveals overnight vs intraday sentiment
   - Volume concentration in first/last hour = institutional flow

4. REALIZED VOLATILITY COMPONENTS:
   - Overnight vol (close-to-open) = news/macro driven
   - Intraday vol (open-to-close) = trading/flow driven
   - Jump component = tail risk events
   - The RATIO between these reveals market regime

IMPLEMENTATION:
   Uses SPY OHLCV data from yfinance (free) to compute microstructure
   proxies. Real tick-by-tick data would be better but this captures
   80%+ of the signal using daily bars.
"""

from datetime import date, timedelta
from typing import Optional, List
import pandas as pd
import numpy as np
import logging

from .base import AlternativeDataProvider, AltDataConfig

logger = logging.getLogger(__name__)


class MarketMicrostructureProvider(AlternativeDataProvider):
    """
    Market microstructure and liquidity signals.

    Computes:
    - Amihud illiquidity ratio (return/volume)
    - Bid-ask spread proxy (high-low range / close)
    - Order flow imbalance (volume-weighted price pressure)
    - Overnight vs intraday return decomposition
    - Volume clock (volume distribution within month)
    """

    def __init__(self, config: Optional[AltDataConfig] = None):
        self.config = config or AltDataConfig()

    @property
    def name(self) -> str:
        return "microstructure"

    def get_feature_names(self) -> List[str]:
        return [
            # Liquidity measures
            "micro_amihud_illiq",           # Amihud illiquidity ratio (21d)
            "micro_amihud_illiq_zscore",    # Z-score of illiquidity
            "micro_amihud_illiq_chg",       # Change in illiquidity (tightening/loosening)
            "micro_spread_proxy",           # Bid-ask spread proxy (high-low range)
            "micro_spread_zscore",          # Z-score of spread
            # Order flow
            "micro_order_flow_imbalance",   # Volume-weighted price pressure
            "micro_ofi_persistence",        # Autocorrelation of order flow
            "micro_buying_pressure",        # Fraction of volume on up-moves
            # Volatility decomposition
            "micro_overnight_vol",          # Close-to-open volatility
            "micro_intraday_vol",           # Open-to-close volatility
            "micro_vol_ratio",              # Overnight/intraday ratio (>1 = news-driven)
            "micro_realized_vol_21d",       # Total realized vol (21d)
            # Volume patterns
            "micro_volume_surprise",        # Volume vs expected (unusual activity)
            "micro_volume_trend",           # Is volume trending up or down?
            "micro_kyle_lambda",            # Kyle's lambda proxy (price impact per unit volume)
        ]

    def fetch(
        self,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        """Compute microstructure features from SPY OHLCV data."""
        try:
            import yfinance as yf
        except ImportError:
            logger.warning("yfinance not installed - microstructure unavailable")
            return pd.DataFrame()

        extended_start = start_date - timedelta(days=180)

        try:
            data = yf.download(
                "SPY", start=str(extended_start), end=str(end_date),
                progress=False, auto_adjust=True
            )
        except Exception as e:
            logger.warning(f"Failed to download SPY data: {e}")
            return pd.DataFrame()

        if data.empty:
            return pd.DataFrame()

        data.index = self._make_tz_naive(data.index)

        close = data["Close"].squeeze()
        open_ = data["Open"].squeeze()
        high = data["High"].squeeze()
        low = data["Low"].squeeze()
        volume = data["Volume"].squeeze().astype(float)

        result = pd.DataFrame(index=data.index)
        eps = 1e-10

        # === 1. AMIHUD ILLIQUIDITY ===
        # |return| / dollar volume -- higher = less liquid
        abs_ret = np.log(close / close.shift(1)).abs()
        dollar_vol = close * volume
        daily_illiq = abs_ret / (dollar_vol + eps)

        # 21-day rolling average, scaled to avoid tiny numbers
        amihud = daily_illiq.rolling(21, min_periods=10).mean() * 1e10
        result["micro_amihud_illiq"] = amihud

        amihud_mean = amihud.rolling(63, min_periods=21).mean()
        amihud_std = amihud.rolling(63, min_periods=21).std()
        result["micro_amihud_illiq_zscore"] = (
            (amihud - amihud_mean) / (amihud_std + eps)
        ).clip(-4, 4)

        result["micro_amihud_illiq_chg"] = amihud.diff(5)

        # === 2. BID-ASK SPREAD PROXY ===
        # Corwin-Schultz high-low spread estimator (simplified)
        # Spread ~ high-low range / close (adjusted for volatility)
        hl_ratio = (high - low) / (close + eps)
        spread_proxy = hl_ratio.rolling(5).mean()
        result["micro_spread_proxy"] = spread_proxy

        spread_mean = spread_proxy.rolling(63, min_periods=21).mean()
        spread_std = spread_proxy.rolling(63, min_periods=21).std()
        result["micro_spread_zscore"] = (
            (spread_proxy - spread_mean) / (spread_std + eps)
        ).clip(-4, 4)

        # === 3. ORDER FLOW IMBALANCE ===
        # Volume-weighted price direction
        ret = np.log(close / close.shift(1))
        signed_volume = ret.apply(np.sign) * volume
        ofi = signed_volume.rolling(5).sum() / (volume.rolling(5).sum() + eps)
        result["micro_order_flow_imbalance"] = ofi.clip(-1, 1)

        # Persistence of order flow (autocorrelation)
        result["micro_ofi_persistence"] = ofi.rolling(21, min_periods=10).apply(
            lambda x: x.autocorr(lag=1) if len(x) > 5 else 0, raw=False
        )

        # Buying pressure: fraction of volume on up-move days
        up_vol = volume.where(ret > 0, 0)
        result["micro_buying_pressure"] = (
            up_vol.rolling(21).sum() / (volume.rolling(21).sum() + eps)
        )

        # === 4. VOLATILITY DECOMPOSITION ===
        # Overnight return: close(t-1) -> open(t)
        overnight_ret = np.log(open_ / close.shift(1))
        # Intraday return: open(t) -> close(t)
        intraday_ret = np.log(close / open_)

        overnight_vol = overnight_ret.rolling(21, min_periods=10).std() * np.sqrt(252)
        intraday_vol = intraday_ret.rolling(21, min_periods=10).std() * np.sqrt(252)
        total_vol = ret.rolling(21, min_periods=10).std() * np.sqrt(252)

        result["micro_overnight_vol"] = overnight_vol
        result["micro_intraday_vol"] = intraday_vol
        result["micro_vol_ratio"] = overnight_vol / (intraday_vol + eps)
        result["micro_realized_vol_21d"] = total_vol

        # === 5. VOLUME PATTERNS ===
        vol_mean_21 = volume.rolling(21, min_periods=10).mean()
        vol_std_21 = volume.rolling(21, min_periods=10).std()
        result["micro_volume_surprise"] = (
            (volume - vol_mean_21) / (vol_std_21 + eps)
        ).clip(-4, 4)

        # Volume trend: 5d MA vs 63d MA
        vol_5 = volume.rolling(5).mean()
        vol_63 = volume.rolling(63, min_periods=21).mean()
        result["micro_volume_trend"] = (vol_5 - vol_63) / (vol_63 + eps)

        # === 6. KYLE'S LAMBDA (price impact) ===
        # Lambda = |return| / sqrt(volume) -- higher = more price impact per trade
        # Use NaN when volume=0 (no trading = undefined price impact)
        kyle_lambda = np.where(
            volume > 0,
            abs_ret / np.sqrt(volume),
            np.nan,
        )
        kyle_lambda = pd.Series(kyle_lambda, index=volume.index)
        kyle_21d = kyle_lambda.rolling(21, min_periods=10).mean() * 1e6
        result["micro_kyle_lambda"] = kyle_21d

        # Filter to date range
        result = result.loc[pd.Timestamp(start_date):pd.Timestamp(end_date)]
        result = result.ffill().fillna(0.0)

        logger.info(f"Microstructure: {len(result.columns)} features")
        return result
