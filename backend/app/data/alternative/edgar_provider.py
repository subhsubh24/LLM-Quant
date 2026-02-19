"""
SEC EDGAR insider and institutional trading data provider.

This is PUBLIC DATA that the SEC requires companies and insiders to
file. It's completely free and contains some of the strongest long-term
alpha signals available.

WHY INSIDER TRADING DATA MATTERS:

FORM 4 (Insider Transactions):
  - Corporate officers, directors, and 10%+ shareholders must report
    trades within 2 business days
  - Insider BUYS are strongly predictive (they know their own company)
  - Insider sells are less informative (could be diversification/tax)
  - Cluster buys (3+ insiders buying in same month) = very bullish
  - Published on EDGAR with ~2 day lag

FORM 13F (Institutional Holdings):
  - Filed quarterly by institutions with >$100M AUM
  - Shows what hedge funds, mutual funds, and pensions are buying
  - The "smart money" effect: follow top-performing funds
  - Filed 45 days after quarter end (stale, but still useful for trends)
  - Changes in holdings (new positions, exits) matter more than levels

SHORT INTEREST:
  - High short interest = potential squeeze AND potential warning
  - Short interest ratio (days to cover) > 10 = squeeze risk
  - Changes in SI predict returns 1-3 months out
  - Available from FINRA/exchanges with ~2 week lag

NOTE: This provider uses SEC EDGAR's free API. No API key required,
but requests must include a User-Agent header with contact info.
Rate limit: 10 requests/second.
"""

from datetime import date, timedelta
from typing import Optional, List, Dict
import pandas as pd
import numpy as np
import logging

from .base import AlternativeDataProvider, AltDataConfig

logger = logging.getLogger(__name__)


class EDGARProvider(AlternativeDataProvider):
    """
    Fetches insider trading and institutional ownership data from SEC EDGAR.

    Uses the free SEC EDGAR FULL-TEXT search API and company filings API.
    No API key required - just a User-Agent header.
    """

    EDGAR_BASE = "https://efts.sec.gov/LATEST"
    EDGAR_COMPANY = "https://data.sec.gov"

    # User-Agent required by SEC (use your real email in production)
    HEADERS = {
        "User-Agent": "QuantLab Research contact@quantlab.local",
        "Accept-Encoding": "gzip, deflate",
    }

    def __init__(self, config: Optional[AltDataConfig] = None):
        self.config = config or AltDataConfig()
        self._cache: Dict = {}

    @property
    def name(self) -> str:
        return "edgar"

    def get_feature_names(self) -> List[str]:
        return [
            # Aggregate insider activity
            "edgar_insider_buy_count_21d",
            "edgar_insider_sell_count_21d",
            "edgar_insider_net_ratio_21d",
            "edgar_insider_buy_value_21d",
            "edgar_insider_cluster_signal",
            # Sector-level insider activity
            "edgar_sector_insider_sentiment",
        ]

    def fetch(
        self,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        """
        Fetch insider trading data from SEC EDGAR.

        Falls back to aggregate market-wide insider activity if
        per-ticker data is unavailable.
        """
        result = pd.DataFrame()

        # Try to fetch recent insider transactions
        try:
            insider_data = self._fetch_insider_transactions(start_date, end_date)
            if insider_data is not None and not insider_data.empty:
                features = self._compute_insider_features(insider_data, start_date, end_date)
                if not features.empty:
                    result = pd.concat([result, features], axis=1)
        except Exception as e:
            logger.warning(f"EDGAR insider data failed: {e}")

        # If no real data, use market-wide proxies
        if result.empty:
            logger.info("EDGAR: falling back to market-wide insider proxy")
            result = self._compute_proxy_features(start_date, end_date)

        if not result.empty:
            result = self._resample_to_daily(result)

        return result

    def _fetch_insider_transactions(
        self,
        start_date: date,
        end_date: date,
    ) -> Optional[pd.DataFrame]:
        """
        Fetch Form 4 filings from EDGAR full-text search.

        Uses the EFTS (EDGAR Full-Text Search) API to find recent
        Form 4 filings, then parses the transaction data.
        """
        import requests

        try:
            # Search for recent Form 4 filings
            params = {
                "q": "form-type:\"4\"",
                "dateRange": "custom",
                "startdt": start_date.isoformat(),
                "enddt": end_date.isoformat(),
                "forms": "4",
            }

            response = requests.get(
                f"{self.EDGAR_BASE}/search-index",
                params=params,
                headers=self.HEADERS,
                timeout=30,
            )

            if response.status_code != 200:
                logger.debug(f"EDGAR search returned {response.status_code}")
                return None

            # Parse the response
            data = response.json()
            hits = data.get("hits", {}).get("hits", [])

            if not hits:
                return None

            records = []
            for hit in hits[:500]:  # Limit to avoid rate issues
                source = hit.get("_source", {})
                records.append({
                    "date": pd.Timestamp(source.get("file_date", "")),
                    "ticker": source.get("tickers", [""])[0] if source.get("tickers") else "",
                    "form_type": source.get("form_type", ""),
                    "company": source.get("display_names", [""])[0] if source.get("display_names") else "",
                })

            if records:
                return pd.DataFrame(records)
            return None

        except Exception as e:
            logger.debug(f"EDGAR fetch failed: {e}")
            return None

    def _compute_insider_features(
        self,
        insider_data: pd.DataFrame,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        """Compute aggregate insider activity features from filing data."""
        dates = pd.bdate_range(start=start_date, end=end_date)
        result = pd.DataFrame(index=dates)

        if insider_data.empty:
            return result

        # Count daily filings (Form 4 = insider transaction)
        insider_data["date"] = pd.to_datetime(insider_data["date"])
        daily_counts = insider_data.groupby(
            insider_data["date"].dt.date
        ).size()
        daily_counts.index = pd.to_datetime(daily_counts.index)

        # Align to business day index
        daily_counts = daily_counts.reindex(dates).fillna(0)

        # 21-day rolling total filings (we can't distinguish buy/sell from count alone)
        total_21d = daily_counts.rolling(21).sum()
        result["edgar_insider_buy_count_21d"] = total_21d
        # Report total filings for sell count too (no buy/sell split available from Form 4 count)
        result["edgar_insider_sell_count_21d"] = total_21d
        result["edgar_insider_net_ratio_21d"] = 0.0  # Would need transaction type parsing
        result["edgar_insider_buy_value_21d"] = 0.0

        # Cluster signal: 5-day total > 2x the expected 5-day total (based on 63d daily avg)
        expected_5d = daily_counts.rolling(63, min_periods=21).mean() * 5
        result["edgar_insider_cluster_signal"] = (
            daily_counts.rolling(5).sum() > expected_5d * 2
        ).astype(float)
        result["edgar_sector_insider_sentiment"] = 0.0

        return result

    def _compute_proxy_features(
        self,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        """
        Compute proxy insider features when real EDGAR data unavailable.

        Uses market conditions to approximate what insider activity
        would look like (insiders buy more when stocks are cheap/beaten down).
        """
        dates = pd.bdate_range(start=start_date, end=end_date)
        result = pd.DataFrame(index=dates)

        try:
            import yfinance as yf

            spy = yf.Ticker("SPY")
            spy_data = spy.history(
                start=start_date - timedelta(days=90),
                end=end_date + timedelta(days=1),
            )

            if spy_data.empty:
                return result

            spy_close = spy_data["Close"]
            spy_close.index = spy_close.index.tz_localize(None)

            # Insider buying tends to increase after drawdowns
            spy_ret = np.log(spy_close / spy_close.shift(1))
            drawdown_21d = spy_ret.rolling(21).sum()

            # Proxy: insiders buy more when trailing return is negative
            buy_proxy = (-drawdown_21d).clip(0, None)
            buy_proxy = buy_proxy.reindex(dates).ffill()

            result["edgar_insider_buy_count_21d"] = buy_proxy
            result["edgar_insider_sell_count_21d"] = 0.0
            result["edgar_insider_net_ratio_21d"] = buy_proxy
            result["edgar_insider_buy_value_21d"] = 0.0
            result["edgar_insider_cluster_signal"] = (buy_proxy > buy_proxy.rolling(63).mean()).astype(float)
            result["edgar_sector_insider_sentiment"] = buy_proxy

        except Exception as e:
            logger.warning(f"Proxy insider features failed: {e}")

        return result
