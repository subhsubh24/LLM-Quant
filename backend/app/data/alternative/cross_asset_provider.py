"""
Cross-asset signal provider.

This is arguably the MOST impactful alternative data source because:

1. It's FREE (uses yfinance, same infra you already have)
2. Cross-asset correlations are PROVEN alpha sources
3. The signals are orthogonal to single-stock price features

KEY SIGNALS AND WHY THEY WORK:

Credit Spreads (HYG - LQD):
  - Widens when credit risk increases = risk-off regime
  - Leads equity selloffs by days/weeks
  - The bond market is smarter and faster than equities

Yield Curve (10Y - 2Y):
  - Inversion predicts recession with 12-18 month lead
  - Steepening signals recovery/risk-on
  - Drives bank stocks, growth vs value rotation

US Dollar (UUP):
  - Strong dollar hurts multinational earnings
  - Weak dollar = commodity/EM tailwind
  - Inverse correlation with risk assets

Gold (GLD):
  - Flight-to-safety indicator
  - Inflation hedge signal
  - Central bank policy proxy

Copper/Gold Ratio:
  - "Dr. Copper" = economic health barometer
  - Rising ratio = economic expansion
  - Falling ratio = contraction fears

VIX Term Structure:
  - Contango (front < back) = complacent market
  - Backwardation (front > back) = panic/hedging demand
  - The SLOPE matters more than the level
"""

from datetime import date, timedelta
from typing import Optional, List, Dict
import pandas as pd
import numpy as np
import logging

from .base import AlternativeDataProvider, AltDataConfig

logger = logging.getLogger(__name__)


class CrossAssetProvider(AlternativeDataProvider):
    """
    Fetches cross-asset price data and computes inter-market signals.

    Uses yfinance to download ETF proxies for bonds, commodities,
    currencies, and volatility products. Then computes derived signals
    like credit spreads, yield curve slope, and risk-on/risk-off ratios.
    """

    def __init__(self, config: Optional[AltDataConfig] = None):
        self.config = config or AltDataConfig()
        self._cache: dict = {}

    @property
    def name(self) -> str:
        return "cross_asset"

    def get_feature_names(self) -> List[str]:
        """Return all cross-asset feature names."""
        names = []
        # Raw asset returns
        for alias in self.config.cross_asset_tickers.values():
            names.append(f"xasset_{alias}_ret_1d")
            names.append(f"xasset_{alias}_ret_5d")
            names.append(f"xasset_{alias}_ret_21d")
        # Derived signals
        names.extend([
            "xasset_credit_spread",
            "xasset_credit_spread_chg_5d",
            "xasset_yield_curve_slope",
            "xasset_yield_curve_chg_5d",
            "xasset_risk_on_off",
            "xasset_copper_gold_ratio",
            "xasset_copper_gold_chg_21d",
            "xasset_dollar_momentum_21d",
            "xasset_gold_momentum_21d",
            "xasset_em_vs_dm",
            "xasset_defensive_vs_cyclical",
            # Commodity breadth and momentum
            "xasset_commodity_breadth",    # Fraction of commodities trending up
            "xasset_commodity_momentum",   # Aggregate commodity return (inflation signal)
            # Real estate and T-bill signals
            "xasset_reit_vs_bonds",        # REITs vs long bonds (rate sensitivity)
            "xasset_tbill_momentum",       # T-bill momentum (flight-to-safety signal)
        ])
        return names

    def fetch(
        self,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        """
        Fetch cross-asset data and compute derived signals.

        Returns DataFrame with:
        - Raw asset returns (1d, 5d, 21d) for each cross-asset
        - Derived spread/ratio signals
        """
        # Fetch all ETF data
        raw_prices = self._fetch_etf_prices(start_date, end_date)

        if raw_prices.empty:
            logger.warning("No cross-asset data fetched")
            return pd.DataFrame()

        result = pd.DataFrame(index=raw_prices.index)

        # 1. Compute returns for each asset
        for ticker, alias in self.config.cross_asset_tickers.items():
            if ticker not in raw_prices.columns:
                continue
            price = raw_prices[ticker]
            for period in [1, 5, 21]:
                ratio = price / price.shift(period)
                ret = np.log(ratio)  # NaN propagates naturally for missing data
                ret = ret.clip(-1, 1)  # Reasonable bounds for log returns
                result[f"xasset_{alias}_ret_{period}d"] = ret

        # 2. Derived signals
        self._compute_credit_spread(raw_prices, result)
        self._compute_yield_curve(raw_prices, result)
        self._compute_risk_on_off(raw_prices, result)
        self._compute_copper_gold(raw_prices, result)
        self._compute_dollar_signals(raw_prices, result)
        self._compute_relative_strength(raw_prices, result)
        self._compute_commodity_breadth(raw_prices, result)
        self._compute_rate_sensitive_signals(raw_prices, result)

        # Resample to fill any gaps
        result = self._resample_to_daily(result)

        logger.info(
            f"CrossAsset: computed {len(result.columns)} features, "
            f"{len(result)} days"
        )

        return result

    def _fetch_etf_prices(
        self,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        """Fetch ETF prices for all cross-asset tickers."""
        tickers = list(self.config.cross_asset_tickers.keys())

        try:
            import yfinance as yf

            # Extra history for computing rolling features
            extended_start = start_date - timedelta(days=90)

            data = yf.download(
                tickers,
                start=extended_start,
                end=end_date + timedelta(days=1),
                auto_adjust=True,
                threads=True,
            )

            if data.empty:
                return pd.DataFrame()

            # Extract close prices
            if len(tickers) == 1:
                prices = data[["Close"]].copy()
                prices.columns = tickers
            else:
                prices = data["Close"].copy()

            prices.index = pd.to_datetime(prices.index).tz_localize(None)
            prices = prices.ffill()

            return prices

        except Exception as e:
            logger.error(f"Failed to fetch cross-asset ETF data: {e}")
            return pd.DataFrame()

    def _compute_credit_spread(
        self, prices: pd.DataFrame, result: pd.DataFrame
    ) -> None:
        """
        Credit spread = HYG return - LQD return (proxy for OAS).

        When HYG underperforms LQD, credit spreads are widening = risk-off.
        This is one of the best leading indicators for equity drawdowns.
        """
        if "HYG" not in prices.columns or "LQD" not in prices.columns:
            return

        hyg_ret = np.log(prices["HYG"] / prices["HYG"].shift(1)).clip(-1, 1)
        lqd_ret = np.log(prices["LQD"] / prices["LQD"].shift(1)).clip(-1, 1)

        # Spread: negative = risk-off (HYG underperforming)
        spread = hyg_ret - lqd_ret
        result["xasset_credit_spread"] = spread.rolling(5).mean()
        result["xasset_credit_spread_chg_5d"] = (
            spread.rolling(5).mean() - spread.rolling(21).mean()
        )

    def _compute_yield_curve(
        self, prices: pd.DataFrame, result: pd.DataFrame
    ) -> None:
        """
        Yield curve slope proxy using bond ETFs.

        TLT (long duration) vs SHY (short duration).
        When TLT outperforms SHY, curve is flattening/inverting.
        """
        if "TLT" not in prices.columns or "SHY" not in prices.columns:
            return

        tlt_ret = np.log(prices["TLT"] / prices["TLT"].shift(1)).clip(-1, 1)
        shy_ret = np.log(prices["SHY"] / prices["SHY"].shift(1)).clip(-1, 1)

        # When TLT rallies vs SHY: curve flattening (risk-off signal)
        slope_proxy = shy_ret - tlt_ret  # Positive = steepening = risk-on
        result["xasset_yield_curve_slope"] = slope_proxy.rolling(5).mean()
        result["xasset_yield_curve_chg_5d"] = (
            slope_proxy.rolling(5).mean() - slope_proxy.rolling(21).mean()
        )

    def _compute_risk_on_off(
        self, prices: pd.DataFrame, result: pd.DataFrame
    ) -> None:
        """
        Composite risk-on/risk-off indicator.

        Combines multiple signals:
        - HYG vs TLT (credit vs safety)
        - EEM vs EFA (high-beta vs low-beta)
        - XLK vs XLU (growth vs defensive)
        """
        risk_signals = []

        # HYG / TLT ratio change
        if "HYG" in prices.columns and "TLT" in prices.columns:
            ratio = prices["HYG"] / prices["TLT"]
            risk_signals.append(np.log(ratio / ratio.shift(5)).clip(-1, 1))

        # EEM / EFA ratio change
        if "EEM" in prices.columns and "EFA" in prices.columns:
            ratio = prices["EEM"] / prices["EFA"]
            risk_signals.append(np.log(ratio / ratio.shift(5)).clip(-1, 1))

        # XLK / XLU ratio change
        if "XLK" in prices.columns and "XLU" in prices.columns:
            ratio = prices["XLK"] / prices["XLU"]
            risk_signals.append(np.log(ratio / ratio.shift(5)).clip(-1, 1))

        if risk_signals:
            # Average of all risk-on/off signals
            combined = pd.concat(risk_signals, axis=1).mean(axis=1)
            result["xasset_risk_on_off"] = combined

    def _compute_copper_gold(
        self, prices: pd.DataFrame, result: pd.DataFrame
    ) -> None:
        """
        Copper/Gold ratio - classic economic health indicator.

        Rising = economic expansion expectations
        Falling = contraction/uncertainty
        """
        if "DBB" not in prices.columns or "GLD" not in prices.columns:
            return

        ratio = prices["DBB"] / prices["GLD"]
        result["xasset_copper_gold_ratio"] = ratio
        result["xasset_copper_gold_chg_21d"] = np.log(ratio / ratio.shift(21)).clip(-1, 1)

    def _compute_dollar_signals(
        self, prices: pd.DataFrame, result: pd.DataFrame
    ) -> None:
        """US Dollar and Gold momentum signals."""
        if "UUP" in prices.columns:
            uup = prices["UUP"]
            result["xasset_dollar_momentum_21d"] = np.log(uup / uup.shift(21)).clip(-1, 1)

        if "GLD" in prices.columns:
            gld = prices["GLD"]
            result["xasset_gold_momentum_21d"] = np.log(gld / gld.shift(21)).clip(-1, 1)

    def _compute_relative_strength(
        self, prices: pd.DataFrame, result: pd.DataFrame
    ) -> None:
        """
        Relative strength signals for sector/geography rotation.

        EM vs DM: risk appetite proxy
        Defensive vs Cyclical: market regime signal
        """
        # EM vs DM spread
        if "EEM" in prices.columns and "EFA" in prices.columns:
            em_ret = np.log(prices["EEM"] / prices["EEM"].shift(21)).clip(-1, 1)
            dm_ret = np.log(prices["EFA"] / prices["EFA"].shift(21)).clip(-1, 1)
            result["xasset_em_vs_dm"] = em_ret - dm_ret

        # Defensive (XLU + XLP) vs Cyclical (XLF + XLE)
        defensive = []
        cyclical = []
        for ticker in ["XLU", "XLP"]:
            if ticker in prices.columns:
                defensive.append(
                    np.log(prices[ticker] / prices[ticker].shift(21)).clip(-1, 1)
                )
        for ticker in ["XLF", "XLE"]:
            if ticker in prices.columns:
                cyclical.append(
                    np.log(prices[ticker] / prices[ticker].shift(21)).clip(-1, 1)
                )

        if defensive and cyclical:
            def_avg = pd.concat(defensive, axis=1).mean(axis=1)
            cyc_avg = pd.concat(cyclical, axis=1).mean(axis=1)
            # Negative = defensive outperforming = risk-off
            result["xasset_defensive_vs_cyclical"] = cyc_avg - def_avg

    def _compute_commodity_breadth(
        self, prices: pd.DataFrame, result: pd.DataFrame
    ) -> None:
        """
        Commodity breadth: what fraction of commodities are trending up?

        A broad commodity rally (gold + oil + agriculture + metals all rising)
        signals genuine inflationary pressure or global growth uptick.
        A narrow rally (just gold) often signals risk-off, not inflation.
        """
        commodity_tickers = ["GLD", "SLV", "USO", "DBA", "DBB"]
        commodity_rets = {}
        for t in commodity_tickers:
            if t in prices.columns:
                ret_21d = np.log(prices[t] / prices[t].shift(21)).clip(-1, 1)
                commodity_rets[t] = ret_21d

        if len(commodity_rets) < 3:
            return

        com_df = pd.DataFrame(commodity_rets)

        # Fraction with positive 21d momentum (NaN-aware)
        available_each_day = com_df.notna().sum(axis=1).clip(lower=1)
        breadth = (com_df > 0).sum(axis=1) / available_each_day
        # Smooth slightly and center at 0 (0.5 = half trending up = neutral)
        result["xasset_commodity_breadth"] = (
            breadth.rolling(5, min_periods=1).mean() * 2 - 1
        )

        # Aggregate commodity momentum (equal-weight average 21d return)
        result["xasset_commodity_momentum"] = com_df.mean(axis=1)

    def _compute_rate_sensitive_signals(
        self, prices: pd.DataFrame, result: pd.DataFrame
    ) -> None:
        """
        Signals from rate-sensitive assets: REITs and T-bills.

        REITs vs Long Bonds: When VNQ outperforms TLT, real estate is
        getting a growth benefit beyond just falling rates.

        T-bill momentum: When BIL gains relative strength, cash is king
        = extreme risk-off / liquidity preference.
        """
        # REITs vs Long Treasury (rate sensitivity differential)
        if "VNQ" in prices.columns and "TLT" in prices.columns:
            vnq_ret = np.log(prices["VNQ"] / prices["VNQ"].shift(21)).clip(-1, 1)
            tlt_ret = np.log(prices["TLT"] / prices["TLT"].shift(21)).clip(-1, 1)
            result["xasset_reit_vs_bonds"] = vnq_ret - tlt_ret

        # T-bill momentum: rising = flight to safety
        if "BIL" in prices.columns:
            bil_ret = np.log(prices["BIL"] / prices["BIL"].shift(21)).clip(-0.1, 0.1)
            result["xasset_tbill_momentum"] = bil_ret
