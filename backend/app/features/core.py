"""
Core feature computation functions.

CRITICAL: All features must be computed using ONLY information
available at time t to predict returns at time t+1 or later.

Leakage Prevention Rules:
1. Never use future prices in feature computation
2. Always lag features by at least 1 period
3. Rolling calculations should use closed='left' or explicit lags
4. Document the information date for each feature
"""

import pandas as pd
import numpy as np
from typing import Optional, Tuple


def compute_returns(
    prices: pd.DataFrame,
    periods: list = [1, 5, 21, 63, 126, 252],
    log_returns: bool = True
) -> pd.DataFrame:
    """
    Compute return features over multiple horizons.

    Args:
        prices: DataFrame with tickers as columns, dates as index
        periods: List of lookback periods in trading days
        log_returns: Use log returns (preferred for modeling)

    Returns:
        DataFrame with columns like 'AAPL_ret_1d', 'AAPL_ret_5d', etc.

    Note: Returns at time t use prices from t-n to t-1.
    The return is LAGGED by 1 day so it's known at market close on day t.
    """
    result = pd.DataFrame(index=prices.index)

    for ticker in prices.columns:
        price = prices[ticker]

        for period in periods:
            if log_returns:
                # CRITICAL FIX #1: Add epsilon to prevent log(0) = -inf
                ret = np.log(np.maximum(price / price.shift(period), 1e-8))
            else:
                ret = price.pct_change(period)

            # Lag by 1 to ensure we don't use today's close to predict today
            # At time t, we know returns up to t-1
            col_name = f"{ticker}_ret_{period}d"
            result[col_name] = ret.shift(1)

    return result


def compute_momentum(
    prices: pd.DataFrame,
    windows: list = [21, 63, 126, 252],
    skip_recent: int = 5
) -> pd.DataFrame:
    """
    Compute momentum features (return over window, skipping recent days).

    Momentum typically excludes the most recent few days to avoid
    short-term reversal effects. This is the "12-1 momentum" concept.

    Args:
        prices: DataFrame with tickers as columns
        windows: Lookback windows in trading days
        skip_recent: Days to skip (short-term reversal adjustment)

    Returns:
        DataFrame with momentum features
    """
    result = pd.DataFrame(index=prices.index)

    for ticker in prices.columns:
        price = prices[ticker]

        for window in windows:
            # Momentum = return from (t-window) to (t-skip_recent)
            # Excludes most recent 'skip_recent' days
            if window <= skip_recent:
                continue

            # Price at t-window relative to price at t-skip_recent
            # CRITICAL FIX #3: Add epsilon to prevent log(0) = -inf
            mom = np.log(np.maximum(price.shift(skip_recent) / price.shift(window), 1e-8))

            # Lag by 1 for safety
            col_name = f"{ticker}_mom_{window}d"
            result[col_name] = mom.shift(1)

    return result


def compute_volatility(
    prices: pd.DataFrame,
    windows: list = [21, 63],
    annualize: bool = True
) -> pd.DataFrame:
    """
    Compute volatility features.

    Args:
        prices: DataFrame with tickers as columns
        windows: Rolling window sizes in trading days
        annualize: Multiply by sqrt(252) for annualized vol

    Returns:
        DataFrame with volatility features

    Note: Volatility at time t uses returns up to t-1.
    """
    result = pd.DataFrame(index=prices.index)

    # First compute daily log returns
    log_rets = np.log(prices / prices.shift(1))

    for ticker in prices.columns:
        rets = log_rets[ticker]

        for window in windows:
            # Rolling std of returns
            vol = rets.rolling(window=window, min_periods=window//2).std()

            if annualize:
                vol = vol * np.sqrt(252)

            # Lag by 1
            col_name = f"{ticker}_vol_{window}d"
            result[col_name] = vol.shift(1)

        # Downside volatility (only negative returns)
        neg_rets = rets.clip(upper=0)
        downside_vol = neg_rets.rolling(window=21, min_periods=10).std() * np.sqrt(252)
        result[f"{ticker}_downside_vol_21d"] = downside_vol.shift(1)

    return result


def compute_drawdown(prices: pd.DataFrame) -> pd.DataFrame:
    """
    Compute drawdown features.

    Args:
        prices: DataFrame with tickers as columns

    Returns:
        DataFrame with drawdown features
    """
    result = pd.DataFrame(index=prices.index)

    for ticker in prices.columns:
        price = prices[ticker]

        # Running maximum (cumulative)
        running_max = price.expanding().max()

        # Drawdown as percentage from peak
        # CRITICAL FIX #4: Add epsilon to prevent division by zero
        drawdown = (price - running_max) / np.maximum(running_max, 1e-8)

        # Current drawdown (lagged by 1)
        result[f"{ticker}_drawdown"] = drawdown.shift(1)

        # Distance from 52-week high (252 trading days)
        high_252 = price.rolling(252, min_periods=126).max()
        # CRITICAL FIX #5: Add epsilon to prevent division by zero
        result[f"{ticker}_dist_from_52w_high"] = ((price / np.maximum(high_252, 1e-8)) - 1).shift(1)

    return result


def compute_volume_features(
    prices: pd.DataFrame,
    volumes: pd.DataFrame,
    windows: list = [21, 63]
) -> pd.DataFrame:
    """
    Compute volume/liquidity features.

    Args:
        prices: DataFrame with tickers as columns (close prices)
        volumes: DataFrame with tickers as columns (daily volume)
        windows: Rolling window sizes

    Returns:
        DataFrame with volume features
    """
    result = pd.DataFrame(index=prices.index)

    for ticker in prices.columns:
        if ticker not in volumes.columns:
            continue

        price = prices[ticker]
        volume = volumes[ticker]

        # Dollar volume (price * volume)
        dollar_vol = price * volume

        for window in windows:
            # Average dollar volume
            avg_dv = dollar_vol.rolling(window, min_periods=window//2).mean()
            result[f"{ticker}_avg_dollar_vol_{window}d"] = avg_dv.shift(1)

            # Volume trend (current vs average) - FIX #9: Add epsilon to prevent division by zero
            vol_trend = volume / (volume.rolling(window, min_periods=window//2).mean() + 1e-8)
            result[f"{ticker}_vol_trend_{window}d"] = vol_trend.shift(1)

        # Volume volatility - FIX #9: Add epsilon to prevent division by zero
        vol_std = volume.rolling(21, min_periods=10).std()
        vol_mean = volume.rolling(21, min_periods=10).mean()
        result[f"{ticker}_vol_cv"] = (vol_std / (vol_mean + 1e-8)).shift(1)

    return result


def compute_risk_features(
    prices: pd.DataFrame,
    market_proxy: pd.Series,
    windows: list = [63, 252]
) -> pd.DataFrame:
    """
    Compute risk features including beta and correlation to market.

    Args:
        prices: DataFrame with tickers as columns
        market_proxy: Series with market returns (e.g., SPY)
        windows: Rolling window sizes

    Returns:
        DataFrame with risk features

    Note: Beta and correlations use lagged data to avoid leakage.
    """
    result = pd.DataFrame(index=prices.index)

    # Compute returns
    # CRITICAL FIX #9 & #10: Add epsilon to prevent log(0) = -inf
    stock_rets = np.log(np.maximum(prices / prices.shift(1), 1e-8))
    market_rets = np.log(np.maximum(market_proxy / market_proxy.shift(1), 1e-8))

    for ticker in prices.columns:
        rets = stock_rets[ticker]

        for window in windows:
            # Rolling beta = Cov(stock, market) / Var(market) - FIX #9: Add epsilon for division guard
            cov = rets.rolling(window, min_periods=window//2).cov(market_rets)
            var = market_rets.rolling(window, min_periods=window//2).var()
            beta = cov / (var + 1e-8)

            # Lag by 1
            result[f"{ticker}_beta_{window}d"] = beta.shift(1)

            # Correlation to market
            corr = rets.rolling(window, min_periods=window//2).corr(market_rets)
            result[f"{ticker}_mkt_corr_{window}d"] = corr.shift(1)

        # Idiosyncratic volatility (residual vol after removing market)
        # Using 63-day beta
        beta_63 = result.get(f"{ticker}_beta_63d")
        if beta_63 is not None:
            predicted_ret = beta_63 * market_rets
            residual = rets - predicted_ret
            idio_vol = residual.rolling(63, min_periods=31).std() * np.sqrt(252)
            result[f"{ticker}_idio_vol"] = idio_vol.shift(1)

    return result


def compute_technical_features(
    prices: pd.DataFrame,
    highs: pd.DataFrame,
    lows: pd.DataFrame
) -> pd.DataFrame:
    """
    Compute technical analysis features.

    Note: While we include some TA features, they should be used
    with caution. Many TA features are not robust alpha sources.

    Args:
        prices: Close prices
        highs: High prices
        lows: Low prices

    Returns:
        DataFrame with technical features
    """
    result = pd.DataFrame(index=prices.index)

    for ticker in prices.columns:
        close = prices[ticker]
        high = highs[ticker] if ticker in highs.columns else close
        low = lows[ticker] if ticker in lows.columns else close

        # Relative Strength Index (RSI) - 14 day
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = (-delta).clip(lower=0)

        avg_gain = gain.rolling(14, min_periods=7).mean()
        avg_loss = loss.rolling(14, min_periods=7).mean()

        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        result[f"{ticker}_rsi_14d"] = rsi.shift(1)

        # Average True Range (ATR) - 14 day
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(14, min_periods=7).mean()
        # Normalize by price for comparability
        # CRITICAL FIX #6: Add epsilon to prevent division by zero
        result[f"{ticker}_atr_pct"] = (atr / np.maximum(close, 1e-8)).shift(1)

        # Moving average crossover signals
        ma_20 = close.rolling(20, min_periods=10).mean()
        ma_50 = close.rolling(50, min_periods=25).mean()
        ma_200 = close.rolling(200, min_periods=100).mean()

        # CRITICAL FIX #7: Add epsilon to prevent division by zero in MA ratios
        result[f"{ticker}_ma_20_50_ratio"] = (ma_20 / np.maximum(ma_50, 1e-8)).shift(1)
        # CRITICAL FIX #8: Add epsilon to prevent division by zero
        result[f"{ticker}_price_ma_200_ratio"] = (close / np.maximum(ma_200, 1e-8)).shift(1)

    return result


def standardize_features(
    features: pd.DataFrame,
    method: str = "cross_sectional",
    clip_outliers: float = 3.0
) -> pd.DataFrame:
    """
    Standardize features for modeling.

    Args:
        features: Raw feature DataFrame
        method: 'cross_sectional' (rank within each day) or 'time_series' (rolling z-score)
        clip_outliers: Clip values beyond this many std devs

    Returns:
        Standardized features

    Note: Cross-sectional ranking is preferred for factor models
    as it's more robust to outliers and non-stationarity.
    """
    result = pd.DataFrame(index=features.index, columns=features.columns)

    if method == "cross_sectional":
        # Rank transform within each day, then scale to [-1, 1]
        for col in features.columns:
            # Extract ticker from column name
            # Group by date and rank
            ranked = features.groupby(features.index)[col].rank(pct=True)
            # Scale from [0, 1] to [-1, 1]
            result[col] = 2 * ranked - 1

    elif method == "time_series":
        # Rolling z-score
        window = 252  # 1 year
        for col in features.columns:
            rolling_mean = features[col].rolling(window, min_periods=63).mean()
            rolling_std = features[col].rolling(window, min_periods=63).std()
            z = (features[col] - rolling_mean) / rolling_std.replace(0, np.nan)

            # Clip outliers
            z = z.clip(-clip_outliers, clip_outliers)
            result[col] = z

    else:
        # Simple standardization
        # BUG FIX #1: Add epsilon guard to prevent division by zero if all features identical
        result = (features - features.mean()) / (features.std() + 1e-8)
        result = result.clip(-clip_outliers, clip_outliers)

    return result
