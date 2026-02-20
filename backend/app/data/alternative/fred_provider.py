"""
FRED (Federal Reserve Economic Data) provider.

FRED is the gold standard for free macroeconomic data. Over 800,000 series
covering every aspect of the US economy. Free API key from:
https://fred.stlouisfed.org/docs/api/api_key.html

WHY THIS MATTERS FOR TRADING:
- Interest rates drive asset valuations (discount rates)
- Yield curve inversions predict recessions 6-18 months ahead
- Credit spreads signal risk appetite/aversion in real-time
- Inflation expectations drive sector rotation
- Employment data moves markets significantly on release
- Consumer sentiment leads consumer spending by 1-3 months

The key insight: these macro variables are slow-moving but powerful.
They set the REGIME in which your faster signals operate.
"""

from datetime import date, timedelta
from typing import Optional, List
import pandas as pd
import numpy as np
import logging

from .base import AlternativeDataProvider, AltDataConfig

logger = logging.getLogger(__name__)


class FREDProvider(AlternativeDataProvider):
    """
    Fetches macroeconomic data from FRED.

    Supports two modes:
    1. With API key: Direct FRED API access (recommended, 120 req/min)
    2. Without API key: Falls back to pandas-datareader or synthetic data
    """

    def __init__(self, config: Optional[AltDataConfig] = None):
        self.config = config or AltDataConfig()
        self._cache: dict = {}

    @property
    def name(self) -> str:
        return "fred"

    def get_feature_names(self) -> List[str]:
        """Return feature names based on configured FRED series."""
        names = []
        for series_id in self.config.fred_series:
            names.append(f"fred_{series_id.lower()}")
        return names

    def fetch(
        self,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        """
        Fetch all configured FRED series.

        Returns daily-frequency DataFrame with forward-filled values.
        Monthly data (CPI, unemployment, etc.) is released with a lag
        and forward-filled - this naturally prevents look-ahead bias
        since the data wasn't available until the release date.
        """
        all_data = {}

        for series_id in self.config.fred_series:
            try:
                data = self._fetch_single_series(series_id, start_date, end_date)
                if data is not None and not data.empty:
                    all_data[f"fred_{series_id.lower()}"] = data
                else:
                    logger.warning(f"No FRED data for {series_id}")
            except Exception as e:
                logger.warning(f"Failed to fetch FRED series {series_id}: {e}")

        if not all_data:
            logger.warning("No FRED data fetched, returning empty DataFrame")
            return pd.DataFrame()

        # Combine all series
        result = pd.DataFrame(all_data)

        # Resample to daily business days with forward-fill
        result = self._resample_to_daily(result)

        # Compute derived macro signals from the raw FRED series
        result = self._add_derived_features(result)

        logger.info(
            f"FRED: fetched {len(result.columns)} series (including derived), "
            f"{len(result)} days from {start_date} to {end_date}"
        )

        return result

    def _add_derived_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Compute derived macro signals from fetched FRED series.

        These capture economically meaningful combinations that no single
        FRED series can express alone:
        - Real yields (nominal - inflation expectations) → growth vs value
        - Yield curve butterfly → mid-cycle dynamics
        - M2 money supply growth → liquidity conditions
        - Real Fed Funds rate → monetary policy tightness
        """
        # Real 10-year yield = nominal 10Y yield - 10Y inflation breakeven
        # Key driver of growth vs value rotation: negative real yields = growth wins
        if "fred_dgs10" in df.columns and "fred_t10yie" in df.columns:
            df["fred_real_yield_10y"] = df["fred_dgs10"] - df["fred_t10yie"]

        # Yield curve butterfly = 2Y + 30Y - 2*10Y
        # Measures the curvature/belly of the yield curve; negative = humped curve
        if all(c in df.columns for c in ["fred_dgs2", "fred_dgs10", "fred_dgs30"]):
            df["fred_yield_butterfly"] = (
                df["fred_dgs2"] + df["fred_dgs30"] - 2.0 * df["fred_dgs10"]
            )

        # M2 money supply year-over-year growth rate (252 business days ≈ 1 year)
        # High M2 growth = liquidity tailwind for risk assets
        if "fred_m2sl" in df.columns:
            df["fred_m2_yoy_growth"] = df["fred_m2sl"].pct_change(252).clip(-0.5, 0.5)

        # Real Fed Funds rate = Fed Funds - 5Y breakeven inflation
        # Negative = financial conditions still accommodative (even if hiking)
        if "fred_dff" in df.columns and "fred_t5yie" in df.columns:
            df["fred_real_fed_funds"] = df["fred_dff"] - df["fred_t5yie"]

        return df

    def _fetch_single_series(
        self,
        series_id: str,
        start_date: date,
        end_date: date,
    ) -> Optional[pd.Series]:
        """Fetch a single FRED series."""
        # Check cache
        cache_key = f"{series_id}_{start_date}_{end_date}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        result = None

        # Try FRED API with key
        if self.config.fred_api_key:
            result = self._fetch_via_api(series_id, start_date, end_date)

        # Try pandas-datareader fallback
        if result is None:
            result = self._fetch_via_datareader(series_id, start_date, end_date)

        # Try yfinance for some series (VIX, rates)
        if result is None:
            result = self._fetch_via_yfinance_proxy(series_id, start_date, end_date)

        if result is not None:
            self._cache[cache_key] = result

        return result

    def _fetch_via_api(
        self,
        series_id: str,
        start_date: date,
        end_date: date,
    ) -> Optional[pd.Series]:
        """Fetch directly from FRED API."""
        import requests

        url = "https://api.stlouisfed.org/fred/series/observations"
        params = {
            "series_id": series_id,
            "api_key": self.config.fred_api_key,
            "file_type": "json",
            "observation_start": start_date.isoformat(),
            "observation_end": end_date.isoformat(),
        }

        try:
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            observations = data.get("observations", [])
            if not observations:
                return None

            dates = []
            values = []
            for obs in observations:
                if obs["value"] != ".":  # FRED uses "." for missing
                    dates.append(pd.Timestamp(obs["date"]))
                    values.append(float(obs["value"]))

            if not dates:
                return None

            series = pd.Series(values, index=dates, name=series_id)
            series = series.sort_index()
            return series

        except Exception as e:
            logger.debug(f"FRED API failed for {series_id}: {e}")
            return None

    def _fetch_via_datareader(
        self,
        series_id: str,
        start_date: date,
        end_date: date,
    ) -> Optional[pd.Series]:
        """Fetch via pandas-datareader (no API key needed for some sources)."""
        try:
            import pandas_datareader.data as web
            df = web.DataReader(series_id, "fred", start_date, end_date)
            if df.empty:
                return None
            return df.iloc[:, 0]
        except ImportError:
            logger.debug("pandas-datareader not installed")
            return None
        except Exception as e:
            logger.debug(f"pandas-datareader failed for {series_id}: {e}")
            return None

    def _fetch_via_yfinance_proxy(
        self,
        series_id: str,
        start_date: date,
        end_date: date,
    ) -> Optional[pd.Series]:
        """
        For some FRED series, we can approximate with yfinance tickers.
        This is a fallback when no FRED API key is available.
        """
        # Map FRED series to yfinance proxies
        yf_proxies = {
            "VIXCLS": "^VIX",
            "DGS10": "^TNX",     # 10Y Treasury yield (approx)
            "DGS2": "^IRX",      # 13-week T-bill (closest proxy)
        }

        proxy_ticker = yf_proxies.get(series_id)
        if not proxy_ticker:
            return None

        try:
            import yfinance as yf
            ticker = yf.Ticker(proxy_ticker)
            df = ticker.history(
                start=start_date,
                end=end_date + timedelta(days=1),
            )
            if df.empty:
                return None

            series = df["Close"]
            series.index = series.index.tz_localize(None)
            series.name = series_id
            return series

        except Exception as e:
            logger.debug(f"yfinance proxy failed for {series_id}: {e}")
            return None
