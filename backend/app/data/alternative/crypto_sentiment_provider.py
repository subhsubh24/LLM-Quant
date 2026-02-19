"""
Crypto as risk sentiment proxy.

Bitcoin has become a MACRO RISK ASSET since 2020. Its correlation
with equity markets is now significant and it often LEADS equity moves:

WHY CRYPTO MATTERS FOR EQUITY TRADING:

1. RISK APPETITE BAROMETER:
   - BTC is the ultimate speculative asset
   - When BTC rallies hard, risk appetite is high across all assets
   - BTC selloffs often precede or coincide with equity weakness

2. LIQUIDITY PROXY:
   - Crypto trades 24/7 including weekends
   - Weekend BTC moves predict Monday equity opens
   - BTC reacts to macro news faster than equities (no market hours)

3. RETAIL SENTIMENT:
   - Crypto is heavily retail-driven
   - BTC volume/volatility = retail engagement proxy
   - Spills over to meme stocks and speculative equities

4. CORRELATION REGIME:
   - BTC-SPY correlation ranges from -0.2 to +0.8
   - When correlation is HIGH, both are driven by same macro factors
   - When correlation BREAKS, it signals a regime shift
"""

from datetime import date, timedelta
from typing import Optional, List
import pandas as pd
import numpy as np
import logging

from .base import AlternativeDataProvider, AltDataConfig

logger = logging.getLogger(__name__)


class CryptoSentimentProvider(AlternativeDataProvider):
    """
    Uses crypto price action as a risk sentiment proxy.

    BTC trades 24/7 so it captures macro sentiment outside of
    equity market hours. Weekend BTC moves are particularly
    informative for Monday equity opens.
    """

    def __init__(self, config: Optional[AltDataConfig] = None):
        self.config = config or AltDataConfig()

    @property
    def name(self) -> str:
        return "crypto_sentiment"

    def get_feature_names(self) -> List[str]:
        return [
            "crypto_btc_ret_1d",
            "crypto_btc_ret_5d",
            "crypto_btc_ret_21d",
            "crypto_btc_vol_21d",
            "crypto_btc_vol_zscore",
            "crypto_btc_drawdown",
            "crypto_btc_spy_corr_21d",
            "crypto_btc_spy_corr_63d",
            "crypto_btc_corr_regime",
            "crypto_eth_btc_ratio_chg",
            "crypto_risk_appetite",
        ]

    def fetch(
        self,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        """Fetch crypto data and compute sentiment features."""
        result = pd.DataFrame()

        try:
            import yfinance as yf

            extended_start = start_date - timedelta(days=365)

            # Fetch BTC, ETH, and SPY
            tickers = ["BTC-USD", "ETH-USD", "SPY"]
            data = yf.download(
                tickers,
                start=extended_start,
                end=end_date + timedelta(days=1),
                auto_adjust=True,
                threads=True,
            )

            if data.empty:
                return result

            prices = data["Close"]
            prices.index = pd.to_datetime(prices.index).tz_localize(None)
            prices = prices.ffill()

            result = pd.DataFrame(index=prices.index)
            eps = 1e-8

            # BTC features
            if "BTC-USD" in prices.columns:
                btc = prices["BTC-USD"]

                # Returns
                result["crypto_btc_ret_1d"] = np.log(np.maximum(btc / btc.shift(1), eps))
                result["crypto_btc_ret_5d"] = np.log(np.maximum(btc / btc.shift(5), eps))
                result["crypto_btc_ret_21d"] = np.log(np.maximum(btc / btc.shift(21), eps))

                # Volatility
                btc_ret = np.log(np.maximum(btc / btc.shift(1), eps))
                vol_21d = btc_ret.rolling(21).std() * np.sqrt(365)
                result["crypto_btc_vol_21d"] = vol_21d
                vol_mean = vol_21d.rolling(63, min_periods=21).mean()
                vol_std = vol_21d.rolling(63, min_periods=21).std()
                result["crypto_btc_vol_zscore"] = (
                    (vol_21d - vol_mean) / (vol_std + eps)
                ).clip(-3, 3)

                # Drawdown from ATH
                rolling_max = btc.expanding().max()
                result["crypto_btc_drawdown"] = (btc - rolling_max) / (rolling_max + eps)

                # BTC-SPY correlation
                if "SPY" in prices.columns:
                    spy_ret = np.log(np.maximum(
                        prices["SPY"] / prices["SPY"].shift(1), eps
                    ))
                    corr_21d = btc_ret.rolling(21, min_periods=10).corr(spy_ret)
                    corr_63d = btc_ret.rolling(63, min_periods=21).corr(spy_ret)
                    result["crypto_btc_spy_corr_21d"] = corr_21d
                    result["crypto_btc_spy_corr_63d"] = corr_63d

                    # Correlation regime: high (>0.5), low (<0.2), negative (<0)
                    result["crypto_btc_corr_regime"] = pd.cut(
                        corr_63d,
                        bins=[-1, 0, 0.3, 0.6, 1],
                        labels=[0, 1, 2, 3],
                    ).astype(float)

            # ETH/BTC ratio (risk-on within crypto = more speculative)
            if "ETH-USD" in prices.columns and "BTC-USD" in prices.columns:
                eth_btc = prices["ETH-USD"] / (prices["BTC-USD"] + eps)
                result["crypto_eth_btc_ratio_chg"] = np.log(
                    np.maximum(eth_btc / eth_btc.shift(5), eps)
                )

            # Composite risk appetite from crypto
            risk_components = []
            if "crypto_btc_ret_5d" in result.columns:
                risk_components.append(result["crypto_btc_ret_5d"] * 10)
            if "crypto_btc_vol_zscore" in result.columns:
                risk_components.append(-result["crypto_btc_vol_zscore"])
            if risk_components:
                result["crypto_risk_appetite"] = (
                    pd.concat(risk_components, axis=1).mean(axis=1).clip(-3, 3)
                )

        except Exception as e:
            logger.warning(f"Crypto sentiment provider failed: {e}")

        if not result.empty:
            result = self._resample_to_daily(result)

        logger.info(f"Crypto sentiment: {len(result.columns)} features")
        return result
