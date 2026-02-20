"""
Alternative data feature engineer.

This is the CRITICAL piece that transforms raw alternative data into
model-ready features. The key principles:

1. LAG EVERYTHING - Alt data features must be lagged to prevent leakage.
   Monthly data (CPI, jobs) is already lagged by publication delay.
   Daily data (VIX, spreads) needs explicit 1-day lag.

2. COMPUTE CHANGES, NOT LEVELS - The model needs to know if the yield
   curve is steepening, not what the absolute spread is. Rate of change
   and regime changes matter more than levels.

3. STANDARDIZE APPROPRIATELY - Alt data has different scales (VIX is
   10-80, credit spread is -0.01 to 0.01). Z-score or rank transform.

4. CREATE INTERACTION FEATURES - The magic is in combinations:
   - VIX rising + credit spreads widening = confirmed risk-off
   - Dollar strengthening + EM underperforming = carry unwind
   - Yield curve steepening + breadth improving = recovery signal

5. REGIME FEATURES - Convert continuous signals to regime states.
   Markets spend 80% of time in "normal" and 20% in "stress."
   Your model needs to know which regime it's in.
"""

from dataclasses import dataclass
from typing import Optional, List, Dict
from datetime import date
import pandas as pd
import numpy as np
import logging

from .base import AltDataConfig
from .fred_provider import FREDProvider
from .cross_asset_provider import CrossAssetProvider
from .sentiment_provider import SentimentProvider
from .calendar_provider import CalendarEffectsProvider
from .options_signals_provider import OptionsSignalsProvider
from .edgar_provider import EDGARProvider
from .news_sentiment_provider import NewsSentimentProvider
from .google_trends_provider import GoogleTrendsProvider
from .weather_provider import WeatherProvider
from .short_volume_provider import ShortVolumeProvider
from .crypto_sentiment_provider import CryptoSentimentProvider
from .congressional_provider import CongressionalProvider
from .economic_surprise_provider import EconomicSurpriseProvider
from .sector_rotation_provider import SectorRotationProvider
from .bond_stress_provider import BondStressProvider
from .market_microstructure_provider import MarketMicrostructureProvider
from .volatility_surface_provider import VolatilitySurfaceProvider
from .earnings_seasonality_provider import EarningsSeasonalityProvider
from .factor_momentum_provider import FactorMomentumProvider
from .correlation_regime_provider import CorrelationRegimeProvider
from .turbulence_provider import TurbulenceProvider

logger = logging.getLogger(__name__)


class AlternativeFeatureEngineer:
    """
    Orchestrates alternative data collection and feature engineering.

    This is the main interface for the feature pipeline to get
    alternative data features. It:
    1. Fetches data from all 21 configured provider categories
    2. Engineers features (changes, z-scores, regimes)
    3. Computes interaction features
    4. Returns a properly lagged, standardized feature matrix
    """

    def __init__(self, config: Optional[AltDataConfig] = None):
        self.config = config or AltDataConfig()

        # Initialize providers (each can be independently enabled/disabled)
        self.providers = {}
        if self.config.fred_enabled:
            self.providers["fred"] = FREDProvider(self.config)
        if self.config.cross_asset_enabled:
            self.providers["cross_asset"] = CrossAssetProvider(self.config)
        if self.config.sentiment_enabled:
            self.providers["sentiment"] = SentimentProvider(self.config)
        if self.config.calendar_enabled:
            self.providers["calendar"] = CalendarEffectsProvider(self.config)
        if self.config.options_signals_enabled:
            self.providers["options"] = OptionsSignalsProvider(self.config)
        if self.config.edgar_enabled:
            self.providers["edgar"] = EDGARProvider(self.config)
        if self.config.news_sentiment_enabled:
            self.providers["news"] = NewsSentimentProvider(self.config)
        if self.config.google_trends_enabled:
            self.providers["gtrends"] = GoogleTrendsProvider(self.config)
        if self.config.weather_enabled:
            self.providers["weather"] = WeatherProvider(self.config)
        if self.config.short_volume_enabled:
            self.providers["short_volume"] = ShortVolumeProvider(self.config)
        if self.config.crypto_sentiment_enabled:
            self.providers["crypto"] = CryptoSentimentProvider(self.config)
        if self.config.congressional_enabled:
            self.providers["congressional"] = CongressionalProvider(self.config)
        if self.config.economic_surprise_enabled:
            self.providers["econ_surprise"] = EconomicSurpriseProvider(self.config)
        if self.config.sector_rotation_enabled:
            self.providers["sector_rotation"] = SectorRotationProvider(self.config)
        if self.config.bond_stress_enabled:
            self.providers["bond_stress"] = BondStressProvider(self.config)
        if self.config.microstructure_enabled:
            self.providers["microstructure"] = MarketMicrostructureProvider(self.config)
        if self.config.vol_surface_enabled:
            self.providers["vol_surface"] = VolatilitySurfaceProvider(self.config)
        if self.config.earnings_seasonality_enabled:
            self.providers["earnings_seasonality"] = EarningsSeasonalityProvider(self.config)
        if self.config.factor_momentum_enabled:
            self.providers["factor_momentum"] = FactorMomentumProvider(self.config)
        if self.config.correlation_regime_enabled:
            self.providers["correlation_regime"] = CorrelationRegimeProvider(self.config)
        if self.config.turbulence_enabled:
            self.providers["turbulence"] = TurbulenceProvider(self.config)

        self.feature_names: List[str] = []

    def compute_features(
        self,
        start_date: date,
        end_date: date,
        price_index: Optional[pd.DatetimeIndex] = None,
    ) -> pd.DataFrame:
        """
        Fetch all alternative data and compute features.

        Args:
            start_date: Start of data range
            end_date: End of data range
            price_index: Optional DatetimeIndex to align features to
                        (should match your stock price data index)

        Returns:
            DataFrame with alternative data features, properly lagged.
            All features at time t use information available before t.
        """
        all_features = []

        # 1. Fetch raw data from each provider
        for name, provider in self.providers.items():
            try:
                raw_data = provider.fetch(start_date, end_date)
                if not raw_data.empty:
                    all_features.append(raw_data)
                    logger.info(f"Provider '{name}': {len(raw_data.columns)} features")
                else:
                    logger.warning(f"Provider '{name}' returned empty data")
            except Exception as e:
                logger.error(f"Provider '{name}' failed: {e}")

        if not all_features:
            logger.warning("No alternative data features computed")
            return pd.DataFrame()

        # 2. Combine all raw features (handle duplicate column names)
        features = pd.concat(all_features, axis=1)
        # Remove duplicate columns (keep first occurrence)
        features = features.loc[:, ~features.columns.duplicated()]

        # 3. Engineer derived features
        engineered = self._engineer_features(features)
        features = pd.concat([features, engineered], axis=1)

        # 4. Compute interaction features
        interactions = self._compute_interactions(features)
        if not interactions.empty:
            features = pd.concat([features, interactions], axis=1)

        # 5. Compute regime features
        regimes = self._compute_regime_features(features)
        if not regimes.empty:
            features = pd.concat([features, regimes], axis=1)

        # 5b. Compute composite market signals
        composites = self._compute_composite_signals(features)
        if not composites.empty:
            features = pd.concat([features, composites], axis=1)

        # 6. Apply lag to all features (prevent leakage)
        features = features.shift(self.config.feature_lag_days)

        # 7. Align to price index if provided
        if price_index is not None:
            features = features.reindex(price_index)
            features = features.ffill()  # Forward-fill only

        # 8. Store feature names
        self.feature_names = features.columns.tolist()

        logger.info(
            f"Alternative features: {len(features.columns)} total features, "
            f"{len(features)} rows"
        )

        return features

    # Prefixes for columns that are binary/categorical and should NOT
    # have z-score/roc/percentile engineering applied (already informative as-is)
    _SKIP_ENGINEERING_PREFIXES = (
        "cal_",       # Calendar flags are binary (0/1)
        "regime_",    # Regime indicators are binary (0/1)
        "opt_vix_regime",  # Categorical regime label (0-5)
        "crypto_btc_corr_regime",  # Categorical regime label (0-3)
        "sector_momentum_leader",  # Encoded sector index (categorical)
        "sector_momentum_laggard",  # Encoded sector index (categorical)
        "pol_",       # Political/congressional flags are mostly binary
        "econ_pre_",  # Economic release windows are binary
        "econ_release_day",  # Binary flag
        "econ_post_", # Binary flag
        "econ_q4_",   # Binary seasonal flags
        "econ_tax_",  # Binary seasonal flags
        "econ_summer_",  # Binary seasonal flags
        "vol_term_contango",       # Binary contango flag
        "vol_regime_compressed",   # Binary regime
        "vol_regime_exploding",    # Binary regime
        "vol_risk_premium_regime", # Binary regime
        "earn_",                   # Earnings seasonality flags are binary/calendar
        "turb_regime_",            # Turbulence regime indicators are binary (0/1)
        "interact_",               # Interaction features are already normalized products
        "composite_",              # Composite signals are already aggregated/clipped
    )

    def _engineer_features(self, raw: pd.DataFrame) -> pd.DataFrame:
        """
        Engineer features from raw alternative data.

        Computes rate-of-change, z-scores, and momentum for each
        CONTINUOUS raw series. Skips binary/categorical columns
        (calendar flags, regime indicators) since z-scoring 0/1
        values is meaningless.

        Uses dict-of-Series approach to avoid DataFrame fragmentation
        (PerformanceWarning from repeated column insertion).
        """
        engineered = {}

        for col in raw.columns:
            # Skip binary/categorical columns
            if any(col.startswith(prefix) for prefix in self._SKIP_ENGINEERING_PREFIXES):
                continue

            series = raw[col]
            if series.isna().all():
                continue

            # Skip columns that are already binary (only 0s and 1s)
            unique_vals = series.dropna().unique()
            if len(unique_vals) <= 2 and set(unique_vals).issubset({0.0, 1.0, 0, 1}):
                continue

            for window in self.config.lookback_windows:
                # Rate of change
                roc = series.diff(window) / (series.shift(window).abs() + 1e-8)
                engineered[f"{col}_roc_{window}d"] = roc.clip(-5, 5)

                # Rolling z-score
                rolling_mean = series.rolling(window, min_periods=window // 2).mean()
                rolling_std = series.rolling(window, min_periods=window // 2).std()
                zscore = (series - rolling_mean) / (rolling_std + 1e-8)
                engineered[f"{col}_zscore_{window}d"] = zscore.clip(-4, 4)

            # Percentile rank (63-day) - use >= to include ties, compare against full window
            engineered[f"{col}_pctile_63d"] = series.rolling(63, min_periods=21).apply(
                lambda x: (x.iloc[-1] >= x).sum() / len(x) if len(x) > 0 else np.nan,
                raw=False,
            )

            # EWMA crossover (signal decay detection):
            # Fast EWMA / slow EWMA ratio — captures trend in the signal itself
            # When fast > slow, the signal is trending up (strengthening)
            ewma_fast = series.ewm(span=5, min_periods=3).mean()
            ewma_slow = series.ewm(span=21, min_periods=10).mean()
            denom = ewma_slow.abs() + 1e-8
            engineered[f"{col}_ewma_cross"] = ((ewma_fast - ewma_slow) / denom).clip(-3, 3)

            # Momentum-reversal: recent change vs longer-term change
            # Positive when short-term and long-term agree (trend continuation)
            # Negative when they disagree (potential reversal)
            chg_5 = series.diff(5)
            chg_21 = series.diff(21)
            denom_mr = chg_21.abs() + 1e-8
            engineered[f"{col}_mom_reversal"] = (chg_5 / denom_mr).clip(-3, 3)

        if engineered:
            return pd.DataFrame(engineered, index=raw.index)
        return pd.DataFrame(index=raw.index)

    def _compute_interactions(self, features: pd.DataFrame) -> pd.DataFrame:
        """
        Compute interaction features between different data sources.

        These capture the RELATIONSHIPS between signals, which is where
        the real alpha lives. Single signals are easily arbitraged away;
        multi-dimensional patterns are much harder to exploit.
        """
        result = pd.DataFrame(index=features.index)

        # --- Macro x Sentiment interactions ---

        # Yield curve + VIX: Both signaling stress = strong risk-off
        yc_col = self._find_col(features, "xasset_yield_curve_slope")
        vix_col = self._find_col(features, "sent_vix_zscore_21d")
        if yc_col and vix_col:
            # Both negative = confirmed stress
            result["interact_yieldcurve_x_vix"] = (
                features[yc_col] * features[vix_col]
            )

        # Credit spread + Breadth: Credit stress with poor breadth = danger
        credit_col = self._find_col(features, "xasset_credit_spread")
        breadth_col = self._find_col(features, "sent_breadth_mcclellan")
        if credit_col and breadth_col:
            result["interact_credit_x_breadth"] = (
                features[credit_col] * features[breadth_col]
            )

        # Dollar + EM: Strong dollar + weak EM = carry unwind
        dollar_col = self._find_col(features, "xasset_dollar_momentum_21d")
        em_col = self._find_col(features, "xasset_em_vs_dm")
        if dollar_col and em_col:
            result["interact_dollar_x_em"] = (
                features[dollar_col] * features[em_col]
            )

        # Gold + Risk-on/off: Gold rising in risk-on = inflation worry
        gold_col = self._find_col(features, "xasset_gold_momentum_21d")
        risk_col = self._find_col(features, "xasset_risk_on_off")
        if gold_col and risk_col:
            result["interact_gold_x_risk"] = (
                features[gold_col] * features[risk_col]
            )

        # --- FRED Macro interactions ---

        # Inflation expectations + Fed rate: Policy error risk
        infl_col = self._find_col(features, "fred_t5yie")
        rate_col = self._find_col(features, "fred_dff")
        if infl_col and rate_col:
            # Compute change in each over 21 days, multiply
            infl_chg = self._find_col(features, "fred_t5yie_roc_21d")
            rate_chg = self._find_col(features, "fred_dff_roc_21d")
            if infl_chg and rate_chg:
                result["interact_inflation_x_fedrate"] = (
                    features[infl_chg] * features[rate_chg]
                )

        # Credit stress + Jobless claims: Real economy + credit stress
        hy_col = self._find_col(features, "fred_bamlh0a0hym2")
        claims_col = self._find_col(features, "fred_icsa")
        if hy_col and claims_col:
            hy_z = self._find_col(features, "fred_bamlh0a0hym2_zscore_21d")
            claims_z = self._find_col(features, "fred_icsa_zscore_21d")
            if hy_z and claims_z:
                result["interact_credit_stress_x_employment"] = (
                    features[hy_z] * features[claims_z]
                )

        # --- Calendar x Weather interactions ---

        # SAD effect + seasonal calendar: winter darkness + poor market seasonality
        sad_col = self._find_col(features, "weather_sad_proxy")
        jan_col = self._find_col(features, "cal_month_jan")
        if sad_col and jan_col:
            # January effect amplified by SAD (short dark days in Jan)
            result["interact_sad_x_january"] = (
                features[sad_col] * features[jan_col]
            )

        # FOMC window + VIX: Pre-FOMC drift stronger when vol is high
        fomc_col = self._find_col(features, "cal_fomc_window")
        vix_z_col = self._find_col(features, "sent_vix_zscore_21d")
        if fomc_col and vix_z_col:
            result["interact_fomc_x_vix"] = (
                features[fomc_col] * features[vix_z_col]
            )

        # --- Economic x Political interactions ---

        # Election proximity + economic cycle: markets nervous when election + weak economy
        election_col = self._find_col(features, "pol_election_window_90d")
        cycle_col = self._find_col(features, "econ_cycle_phase")
        if election_col and cycle_col:
            result["interact_election_x_cycle"] = (
                features[election_col] * features[cycle_col]
            )

        # Data release day + political uncertainty: releases matter more in uncertain times
        release_col = self._find_col(features, "econ_release_day")
        pol_uncertainty = self._find_col(features, "pol_fiscal_year_end")
        if release_col and pol_uncertainty:
            result["interact_release_x_fiscal"] = (
                features[release_col] * features[pol_uncertainty]
            )

        # Presidential cycle + economic surprise: pre-election year + positive surprises
        preelection_col = self._find_col(features, "pol_preelection_year")
        surprise_col = self._find_col(features, "econ_surprise_proxy")
        if preelection_col and surprise_col:
            result["interact_preelection_x_surprise"] = (
                features[preelection_col] * features[surprise_col]
            )

        # Energy demand + weather: extreme weather + energy demand = utility sector play
        energy_col = self._find_col(features, "weather_energy_demand_proxy")
        hdd_col = self._find_col(features, "weather_hdd")
        if energy_col and hdd_col:
            result["interact_energy_x_cold"] = (
                features[energy_col] * features[hdd_col]
            )

        # --- Sector Rotation x Bond Stress interactions ---

        # Sector rotation + bond stress: defensive rotation confirms credit stress
        sec_risk = self._find_col(features, "sector_risk_appetite")
        bond_stress = self._find_col(features, "bond_stress_score")
        if sec_risk and bond_stress:
            result["interact_sector_x_bondstress"] = (
                features[sec_risk] * features[bond_stress]
            )

        # Sector breadth + bond-equity correlation: broad rally with negative corr = healthy
        sec_breadth = self._find_col(features, "sector_breadth")
        bond_eq_corr = self._find_col(features, "bond_equity_corr_21d")
        if sec_breadth and bond_eq_corr:
            result["interact_breadth_x_bondcorr"] = (
                features[sec_breadth] * features[bond_eq_corr]
            )

        # HY momentum + sector rotation: credit improving + cyclical rotation = risk-on confirmed
        hy_mom = self._find_col(features, "bond_hy_momentum")
        cyc_def = self._find_col(features, "sector_cyclical_vs_defensive")
        if hy_mom and cyc_def:
            result["interact_hy_x_cyclical"] = (
                features[hy_mom] * features[cyc_def]
            )

        # --- Microstructure x Vol Surface interactions ---

        # Liquidity drying up + vol term structure inverting = crash risk
        illiq_col = self._find_col(features, "micro_amihud_illiq_zscore")
        term_col = self._find_col(features, "vol_term_slope_30_90")
        if illiq_col and term_col:
            result["interact_illiq_x_termslope"] = (
                features[illiq_col] * features[term_col]
            )

        # Risk premium collapsing + volume surprise = dislocation
        rp_col = self._find_col(features, "vol_risk_premium_zscore")
        volsurp_col = self._find_col(features, "micro_volume_surprise")
        if rp_col and volsurp_col:
            result["interact_vrp_x_volume"] = (
                features[rp_col] * features[volsurp_col]
            )

        # Order flow + VIX: buying pressure in high-vol = smart money accumulation
        ofi_col = self._find_col(features, "micro_order_flow_imbalance")
        vix_z = self._find_col(features, "sent_vix_zscore_21d")
        if ofi_col and vix_z:
            result["interact_ofi_x_vix"] = (
                features[ofi_col] * features[vix_z]
            )

        # Overnight vol dominance + crypto move = macro event
        vol_ratio_col = self._find_col(features, "micro_vol_ratio")
        btc_col = self._find_col(features, "crypto_btc_ret_1d")
        if vol_ratio_col and btc_col:
            result["interact_overnightvol_x_btc"] = (
                features[vol_ratio_col] * features[btc_col]
            )

        # --- Factor Momentum interactions ---

        # Growth-value spread + VIX: factor rotation in different vol regimes
        gv_col = self._find_col(features, "factor_growth_value_21d")
        vix_z2 = self._find_col(features, "sent_vix_zscore_21d")
        if gv_col and vix_z2:
            result["interact_growthvalue_x_vix"] = (
                features[gv_col] * features[vix_z2]
            )

        # Small-large spread + credit: small caps hurt most in credit stress
        sl_col = self._find_col(features, "factor_small_large_21d")
        credit2 = self._find_col(features, "xasset_credit_spread")
        if sl_col and credit2:
            result["interact_smalllarge_x_credit"] = (
                features[sl_col] * features[credit2]
            )

        # Sector dispersion + vol: high dispersion in low vol = stock picking heaven
        disp_col = self._find_col(features, "factor_sector_dispersion")
        realized_vol = self._find_col(features, "micro_realized_vol_21d")
        if disp_col and realized_vol:
            result["interact_dispersion_x_vol"] = (
                features[disp_col] * features[realized_vol]
            )

        # Earnings season + vol surface: vol term structure during earnings
        earn_peak = self._find_col(features, "earn_season_peak")
        term_slope = self._find_col(features, "vol_term_slope_30_90")
        if earn_peak and term_slope:
            result["interact_earnings_x_termslope"] = (
                features[earn_peak] * features[term_slope]
            )

        # --- Correlation Regime interactions ---

        # Stock-bond correlation × VIX: crisis regime amplified by vol
        corr_eb = self._find_col(features, "corr_equity_bond")
        vix_z3 = self._find_col(features, "sent_vix_zscore_21d")
        if corr_eb and vix_z3:
            result["interact_corr_x_vix"] = (
                features[corr_eb] * features[vix_z3]
            )

        # Absorption ratio × credit stress: systemic + credit = maximum danger
        absorption = self._find_col(features, "corr_absorption_ratio")
        credit_stress = self._find_col(features, "bond_credit_stress")
        if absorption and credit_stress:
            result["interact_absorption_x_credit"] = (
                features[absorption] * features[credit_stress]
            )

        # --- Turbulence interactions ---

        # Turbulence × VIX: turb spike + VIX spike = confirmed crisis
        turb_z = self._find_col(features, "turb_zscore")
        vix_z4 = self._find_col(features, "sent_vix_zscore_21d")
        if turb_z and vix_z4:
            result["interact_turb_x_vix"] = (
                features[turb_z] * features[vix_z4]
            )

        # Turbulence × credit: turb + credit stress = systemic event
        turb_z2 = self._find_col(features, "turb_zscore")
        bond_credit = self._find_col(features, "bond_credit_stress")
        if turb_z2 and bond_credit:
            result["interact_turb_x_credit"] = (
                features[turb_z2] * features[bond_credit]
            )

        # Turbulence mean-reversion × buying pressure: turb reverting + buying = recovery
        turb_mr = self._find_col(features, "turb_mean_reversion")
        buy_press2 = self._find_col(features, "micro_buying_pressure")
        if turb_mr and buy_press2:
            result["interact_turb_reversal_x_buying"] = (
                features[turb_mr] * (features[buy_press2] - 0.5) * 4
            )

        # --- New signals from enriched providers ---

        # VVIX × VIX: when BOTH vol-of-vol and VIX are elevated = genuine fear spike
        vvix_z = self._find_col(features, "vol_vvix_zscore")
        vix_z5 = self._find_col(features, "sent_vix_zscore_21d")
        if vvix_z and vix_z5:
            result["interact_vvix_x_vix"] = features[vvix_z] * features[vix_z5]

        # Commodity breadth × dollar: many commodities rising + weak dollar = inflation trade
        com_breadth = self._find_col(features, "xasset_commodity_breadth")
        dollar_mom = self._find_col(features, "xasset_dollar_momentum_21d")
        if com_breadth and dollar_mom:
            # Positive when commodities up AND dollar down (classic inflation signal)
            result["interact_commodity_x_dollar"] = (
                features[com_breadth] * (-features[dollar_mom])
            )

        # Real yield × growth-value: negative real yield favors growth stocks
        real_yield = self._find_col(features, "fred_real_yield_10y")
        gv_col2 = self._find_col(features, "factor_growth_value_21d")
        if real_yield and gv_col2:
            # Negative real yield + growth outperformance = momentum aligned
            result["interact_realyield_x_growth"] = (
                (-features[real_yield]) * features[gv_col2]
            )

        # M2 growth × real yield: money printing + tightening = policy stress signal
        m2_growth = self._find_col(features, "fred_m2_yoy_growth")
        real_yield2 = self._find_col(features, "fred_real_yield_10y")
        if m2_growth and real_yield2:
            # Rising M2 while real yield is negative = maximum liquidity
            result["interact_m2_x_realyield"] = (
                features[m2_growth] * (-features[real_yield2])
            )

        return result

    def _compute_regime_features(self, features: pd.DataFrame) -> pd.DataFrame:
        """
        Compute market regime indicators.

        Convert continuous signals into discrete regime states.
        Markets exhibit different statistical properties in different
        regimes, and your model needs to adapt accordingly.
        """
        result = pd.DataFrame(index=features.index)

        # --- Volatility Regime (from VIX) ---
        vix_col = self._find_col(features, "sent_vix_level")
        if vix_col:
            vix = features[vix_col]
            # Low vol: VIX < 15, Normal: 15-25, High: 25-35, Crisis: >35
            result["regime_vol_low"] = (vix < 15).astype(float)
            result["regime_vol_high"] = (vix > 25).astype(float)
            result["regime_vol_crisis"] = (vix > 35).astype(float)

        # --- Credit Regime (from HY spread) ---
        hy_col = self._find_col(features, "fred_bamlh0a0hym2")
        if hy_col:
            hy_spread = features[hy_col]
            # Compute z-score relative to 1-year history
            hy_mean = hy_spread.rolling(252, min_periods=63).mean()
            hy_std = hy_spread.rolling(252, min_periods=63).std()
            hy_z = (hy_spread - hy_mean) / (hy_std + 1e-8)

            result["regime_credit_tight"] = (hy_z < -0.5).astype(float)
            result["regime_credit_stress"] = (hy_z > 1.0).astype(float)
            result["regime_credit_crisis"] = (hy_z > 2.0).astype(float)

        # --- Trend Regime (from risk-on/off composite) ---
        risk_col = self._find_col(features, "xasset_risk_on_off")
        if risk_col:
            risk = features[risk_col]
            risk_smooth = risk.rolling(10, min_periods=5).mean()
            result["regime_risk_on"] = (risk_smooth > 0.005).astype(float)
            result["regime_risk_off"] = (risk_smooth < -0.005).astype(float)

        # --- Macro Regime (from yield curve) ---
        yc_col = self._find_col(features, "fred_t10y2y")
        if yc_col:
            yc = features[yc_col]
            result["regime_yieldcurve_inverted"] = (yc < 0).astype(float)
            result["regime_yieldcurve_steep"] = (yc > 1.0).astype(float)

        # --- Bond Stress Regime ---
        bond_stress_col = self._find_col(features, "bond_stress_score")
        if bond_stress_col:
            bs = features[bond_stress_col]
            result["regime_bond_calm"] = (bs < -0.3).astype(float)
            result["regime_bond_stress"] = (bs > 0.3).astype(float)
            result["regime_bond_crisis"] = (bs > 0.7).astype(float)

        # --- Sector Rotation Regime ---
        sec_risk_col = self._find_col(features, "sector_risk_appetite")
        if sec_risk_col:
            sr = features[sec_risk_col]
            result["regime_sector_riskon"] = (sr > 0.2).astype(float)
            result["regime_sector_riskoff"] = (sr < -0.2).astype(float)

        # --- Liquidity Regime (from microstructure) ---
        illiq_col = self._find_col(features, "micro_amihud_illiq_zscore")
        if illiq_col:
            illiq = features[illiq_col]
            result["regime_liquidity_tight"] = (illiq > 1.0).astype(float)
            result["regime_liquidity_crisis"] = (illiq > 2.0).astype(float)

        # --- Vol Surface Regime ---
        term_col = self._find_col(features, "vol_term_contango")
        if term_col:
            result["regime_vol_backwardation"] = (features[term_col] == 0).astype(float)
        rp_regime_col = self._find_col(features, "vol_risk_premium_regime")
        if rp_regime_col:
            result["regime_negative_vrp"] = features[rp_regime_col]

        # --- Correlation Regime ---
        corr_crisis_col = self._find_col(features, "corr_crisis_regime")
        if corr_crisis_col:
            result["regime_corr_crisis"] = features[corr_crisis_col]
        absorption_col = self._find_col(features, "corr_absorption_ratio")
        if absorption_col:
            ab = features[absorption_col]
            # High absorption (>0.5) = systemic risk elevated
            result["regime_systemic_risk"] = (ab > 0.5).astype(float)

        # --- Turbulence Regime ---
        turb_crisis_col = self._find_col(features, "turb_regime_crisis")
        if turb_crisis_col:
            result["regime_turb_crisis"] = features[turb_crisis_col]
        turb_calm_col = self._find_col(features, "turb_regime_calm")
        if turb_calm_col:
            result["regime_turb_calm"] = features[turb_calm_col]

        # --- Real Yield Regime (from derived FRED features) ---
        # Negative real yield = financial conditions still stimulative
        # This drives growth/tech outperformance vs value/cyclicals
        real_yield_col = self._find_col(features, "fred_real_yield_10y")
        if real_yield_col:
            ry = features[real_yield_col]
            result["regime_negative_real_yield"] = (ry < 0).astype(float)
            result["regime_deeply_neg_real_yield"] = (ry < -1.0).astype(float)

        # --- Combined Regime Score ---
        # Sum of all regime indicators for a composite state
        regime_cols = [c for c in result.columns if c.startswith("regime_")]
        if regime_cols:
            # Risk-off score: higher = more stress indicators firing
            stress_cols = [c for c in regime_cols if any(
                kw in c for kw in ["high", "crisis", "stress", "inverted", "risk_off"]
            )]
            if stress_cols:
                result["regime_stress_score"] = result[stress_cols].sum(axis=1)

        return result

    def _compute_composite_signals(self, features: pd.DataFrame) -> pd.DataFrame:
        """
        Compute composite market signals that combine multiple data sources.

        These aggregate multiple weak signals into stronger composite
        indicators. Each composite is designed to capture a specific
        market dynamic that no single provider can measure alone.
        """
        result = pd.DataFrame(index=features.index)

        # === COMPOSITE STRESS INDEX ===
        # Combine VIX, credit spread, breadth, and bond stress into one score
        stress_components = []

        vix_z = self._find_col(features, "sent_vix_zscore_21d")
        if vix_z:
            stress_components.append(features[vix_z].clip(-3, 3))

        credit = self._find_col(features, "xasset_credit_spread")
        if credit:
            # Credit spread widening = negative values = stress
            # Z-score credit spread to match other component scales
            cs = features[credit]
            cs_mean = cs.rolling(63, min_periods=21).mean()
            cs_std = cs.rolling(63, min_periods=21).std()
            cs_z = ((cs - cs_mean) / (cs_std + 1e-8)).clip(-3, 3)
            stress_components.append(-cs_z)

        breadth = self._find_col(features, "sent_breadth_mcclellan")
        if breadth:
            # Poor breadth (negative) = stress
            stress_components.append(-features[breadth].clip(-3, 3))

        bond_stress = self._find_col(features, "bond_stress_score")
        if bond_stress:
            stress_components.append(features[bond_stress].clip(-3, 3))

        illiq = self._find_col(features, "micro_amihud_illiq_zscore")
        if illiq:
            stress_components.append(features[illiq].clip(-3, 3))

        turb = self._find_col(features, "turb_zscore")
        if turb:
            stress_components.append(features[turb].clip(-3, 3))

        if len(stress_components) >= 2:
            combined = pd.concat(stress_components, axis=1)
            result["composite_stress_index"] = combined.mean(axis=1)
            # Rate of change of stress
            result["composite_stress_chg_5d"] = result["composite_stress_index"].diff(5)

        # === COMPOSITE RISK APPETITE ===
        # Combine cross-asset, factor, and sentiment signals
        appetite_components = []

        risk_onoff = self._find_col(features, "xasset_risk_on_off")
        if risk_onoff:
            # Z-score the risk-on/off signal to match other component scales
            ro = features[risk_onoff]
            ro_mean = ro.rolling(63, min_periods=21).mean()
            ro_std = ro.rolling(63, min_periods=21).std()
            ro_z = ((ro - ro_mean) / (ro_std + 1e-8)).clip(-3, 3)
            appetite_components.append(ro_z)

        sec_risk = self._find_col(features, "sector_risk_appetite")
        if sec_risk:
            appetite_components.append(features[sec_risk].clip(-3, 3))

        breadth2 = self._find_col(features, "factor_sector_breadth")
        if breadth2:
            appetite_components.append((features[breadth2] - 0.5) * 4)  # center at 0

        btc = self._find_col(features, "crypto_btc_ret_5d")
        if btc:
            appetite_components.append(features[btc].clip(-0.2, 0.2) * 10)

        if len(appetite_components) >= 2:
            combined = pd.concat(appetite_components, axis=1)
            result["composite_risk_appetite"] = combined.mean(axis=1)

        # === COMPOSITE MOMENTUM QUALITY ===
        # Strong momentum + good breadth + factor confirmation = quality trend
        quality_components = []

        ofi = self._find_col(features, "micro_order_flow_imbalance")
        if ofi:
            quality_components.append(features[ofi].clip(-1, 1))

        buy_press = self._find_col(features, "micro_buying_pressure")
        if buy_press:
            quality_components.append((features[buy_press] - 0.5) * 4)

        fac_breadth = self._find_col(features, "factor_sector_breadth")
        if fac_breadth:
            quality_components.append((features[fac_breadth] - 0.5) * 4)

        if len(quality_components) >= 2:
            combined = pd.concat(quality_components, axis=1)
            result["composite_momentum_quality"] = combined.mean(axis=1)

        return result

    def _find_col(self, df: pd.DataFrame, pattern: str) -> Optional[str]:
        """Find column matching pattern (exact match first, then shortest contains match)."""
        if pattern in df.columns:
            return pattern
        matches = [c for c in df.columns if pattern in c]
        if not matches:
            return None
        # Return shortest match to avoid e.g. "bond_hy_momentum" matching "bond_hy_momentum_roc_5d"
        return min(matches, key=len)

    def get_feature_groups(self) -> Dict[str, List[str]]:
        """Group features by source for analysis."""
        groups = {
            "fred_macro": [],
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
            "microstructure": [],
            "vol_surface": [],
            "earnings_seasonality": [],
            "factor_momentum": [],
            "correlation_regime": [],
            "turbulence": [],
            "interactions": [],
            "composites": [],
            "regimes": [],
            "engineered": [],
        }

        for name in self.feature_names:
            # Check for engineered suffixes first
            is_engineered = "_roc_" in name or "_zscore_" in name or "_pctile_" in name

            if name.startswith("fred_"):
                groups["engineered" if is_engineered else "fred_macro"].append(name)
            elif name.startswith("xasset_"):
                groups["engineered" if is_engineered else "cross_asset"].append(name)
            elif name.startswith("sent_"):
                groups["engineered" if is_engineered else "sentiment"].append(name)
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
            elif name.startswith("micro_"):
                groups["microstructure"].append(name)
            elif name.startswith("vol_"):
                groups["vol_surface"].append(name)
            elif name.startswith("earn_"):
                groups["earnings_seasonality"].append(name)
            elif name.startswith("factor_"):
                groups["factor_momentum"].append(name)
            elif name.startswith("corr_"):
                groups["correlation_regime"].append(name)
            elif name.startswith("turb_"):
                groups["turbulence"].append(name)
            elif name.startswith("composite_"):
                groups["composites"].append(name)
            elif name.startswith("interact_"):
                groups["interactions"].append(name)
            elif name.startswith("regime_"):
                groups["regimes"].append(name)

        return groups
