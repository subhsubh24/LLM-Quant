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


def compute_enhanced_technical_features(
    prices: pd.DataFrame,
    highs: pd.DataFrame,
    lows: pd.DataFrame,
    volumes: Optional[pd.DataFrame] = None
) -> pd.DataFrame:
    """
    Compute enhanced technical analysis features beyond basic RSI/ATR/MA.

    Includes MACD, Stochastic Oscillator, ADX, OBV, Fibonacci retracement
    levels, Bollinger Band features, and VWAP ratio.

    Args:
        prices: Close prices DataFrame with tickers as columns, dates as index
        highs: High prices DataFrame (same structure)
        lows: Low prices DataFrame (same structure)
        volumes: Optional volume DataFrame (same structure)

    Returns:
        DataFrame with enhanced technical features, all lagged by 1 period
        to prevent look-ahead bias.

    Note: All features at time t use data available up to t-1 only.
    """
    eps = 1e-8
    result = pd.DataFrame(index=prices.index)

    for ticker in prices.columns:
        close = prices[ticker]
        high = highs[ticker] if ticker in highs.columns else close
        low = lows[ticker] if ticker in lows.columns else close

        # ---------------------------------------------------------------
        # 1. MACD (12, 26, 9) - Moving Average Convergence Divergence
        # ---------------------------------------------------------------
        ema_12 = close.ewm(span=12, min_periods=12, adjust=False).mean()
        ema_26 = close.ewm(span=26, min_periods=26, adjust=False).mean()
        macd_line = ema_12 - ema_26
        signal_line = macd_line.ewm(span=9, min_periods=9, adjust=False).mean()
        macd_histogram = macd_line - signal_line

        # Normalize by price for cross-asset comparability
        result[f"{ticker}_macd_line"] = (macd_line / np.maximum(close, eps)).shift(1)
        result[f"{ticker}_macd_signal"] = (signal_line / np.maximum(close, eps)).shift(1)
        result[f"{ticker}_macd_histogram"] = (macd_histogram / np.maximum(close, eps)).shift(1)

        # ---------------------------------------------------------------
        # 2. Stochastic Oscillator (14, 3) - %K and %D
        # ---------------------------------------------------------------
        stoch_window = 14
        stoch_smooth = 3

        lowest_low = low.rolling(window=stoch_window, min_periods=stoch_window // 2).min()
        highest_high = high.rolling(window=stoch_window, min_periods=stoch_window // 2).max()

        # %K = (Close - Lowest Low) / (Highest High - Lowest Low) * 100
        stoch_range = highest_high - lowest_low
        pct_k = ((close - lowest_low) / np.maximum(stoch_range, eps)) * 100.0

        # %D = 3-period SMA of %K
        pct_d = pct_k.rolling(window=stoch_smooth, min_periods=1).mean()

        result[f"{ticker}_stoch_k"] = pct_k.shift(1)
        result[f"{ticker}_stoch_d"] = pct_d.shift(1)

        # ---------------------------------------------------------------
        # 3. ADX (Average Directional Index, 14-period)
        # ---------------------------------------------------------------
        adx_window = 14

        # True Range components
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        # Directional movement
        up_move = high - high.shift(1)
        down_move = low.shift(1) - low

        # +DM: positive directional movement
        plus_dm = pd.Series(0.0, index=close.index)
        plus_dm_mask = (up_move > down_move) & (up_move > 0)
        plus_dm[plus_dm_mask] = up_move[plus_dm_mask]

        # -DM: negative directional movement
        minus_dm = pd.Series(0.0, index=close.index)
        minus_dm_mask = (down_move > up_move) & (down_move > 0)
        minus_dm[minus_dm_mask] = down_move[minus_dm_mask]

        # Smoothed TR, +DM, -DM using Wilder's smoothing (EMA with alpha=1/window)
        atr_smooth = true_range.ewm(alpha=1.0 / adx_window, min_periods=adx_window, adjust=False).mean()
        plus_dm_smooth = plus_dm.ewm(alpha=1.0 / adx_window, min_periods=adx_window, adjust=False).mean()
        minus_dm_smooth = minus_dm.ewm(alpha=1.0 / adx_window, min_periods=adx_window, adjust=False).mean()

        # +DI and -DI
        plus_di = (plus_dm_smooth / np.maximum(atr_smooth, eps)) * 100.0
        minus_di = (minus_dm_smooth / np.maximum(atr_smooth, eps)) * 100.0

        # DX = |+DI - -DI| / (|+DI| + |-DI|)
        di_sum = plus_di + minus_di
        di_diff = (plus_di - minus_di).abs()
        dx = (di_diff / np.maximum(di_sum, eps)) * 100.0

        # ADX = smoothed DX
        adx = dx.ewm(alpha=1.0 / adx_window, min_periods=adx_window, adjust=False).mean()

        result[f"{ticker}_adx"] = adx.shift(1)
        result[f"{ticker}_plus_di"] = plus_di.shift(1)
        result[f"{ticker}_minus_di"] = minus_di.shift(1)

        # ---------------------------------------------------------------
        # 4. OBV (On Balance Volume)
        # ---------------------------------------------------------------
        if volumes is not None and ticker in volumes.columns:
            volume = volumes[ticker]

            # OBV: cumulative sum of signed volume
            price_change = close.diff()
            obv_sign = pd.Series(0.0, index=close.index)
            obv_sign[price_change > 0] = 1.0
            obv_sign[price_change < 0] = -1.0

            obv = (obv_sign * volume).cumsum()

            # Normalize OBV by rolling mean volume for comparability
            rolling_vol_mean = volume.rolling(window=21, min_periods=10).mean()
            obv_normalized = obv / np.maximum(rolling_vol_mean, eps)

            # OBV momentum: rate of change of OBV over 14 periods
            obv_mom = obv.diff(14) / np.maximum(rolling_vol_mean, eps)

            result[f"{ticker}_obv_normalized"] = obv_normalized.shift(1)
            result[f"{ticker}_obv_momentum"] = obv_mom.shift(1)

        # ---------------------------------------------------------------
        # 5. Fibonacci Retracement Levels (52-week high/low based)
        # ---------------------------------------------------------------
        fib_window = 252  # ~52 weeks of trading days
        high_52w = high.rolling(window=fib_window, min_periods=fib_window // 2).max()
        low_52w = low.rolling(window=fib_window, min_periods=fib_window // 2).min()

        fib_range = high_52w - low_52w

        # Key Fibonacci levels
        fib_236 = high_52w - 0.236 * fib_range  # 23.6% retracement
        fib_382 = high_52w - 0.382 * fib_range  # 38.2% retracement
        fib_500 = high_52w - 0.500 * fib_range  # 50.0% retracement
        fib_618 = high_52w - 0.618 * fib_range  # 61.8% retracement

        # Distance from current price to each Fibonacci level (normalized)
        result[f"{ticker}_fib_dist_236"] = ((close - fib_236) / np.maximum(fib_range, eps)).shift(1)
        result[f"{ticker}_fib_dist_382"] = ((close - fib_382) / np.maximum(fib_range, eps)).shift(1)
        result[f"{ticker}_fib_dist_500"] = ((close - fib_500) / np.maximum(fib_range, eps)).shift(1)
        result[f"{ticker}_fib_dist_618"] = ((close - fib_618) / np.maximum(fib_range, eps)).shift(1)

        # ---------------------------------------------------------------
        # 6. Bollinger Band Features (20-period, 2 std)
        # ---------------------------------------------------------------
        bb_window = 20
        bb_std_mult = 2.0

        bb_ma = close.rolling(window=bb_window, min_periods=bb_window // 2).mean()
        bb_std = close.rolling(window=bb_window, min_periods=bb_window // 2).std()

        upper_band = bb_ma + bb_std_mult * bb_std
        lower_band = bb_ma - bb_std_mult * bb_std

        # %B = (Price - Lower Band) / (Upper Band - Lower Band)
        bb_width = upper_band - lower_band
        pct_b = (close - lower_band) / np.maximum(bb_width, eps)

        # Bandwidth = (Upper - Lower) / Middle (squeeze indicator)
        bandwidth = bb_width / np.maximum(bb_ma, eps)

        result[f"{ticker}_bb_pct_b"] = pct_b.shift(1)
        result[f"{ticker}_bb_bandwidth"] = bandwidth.shift(1)

        # ---------------------------------------------------------------
        # 7. VWAP Ratio (if volume available)
        # ---------------------------------------------------------------
        if volumes is not None and ticker in volumes.columns:
            volume = volumes[ticker]

            # Rolling VWAP: sum(price * volume) / sum(volume) over window
            vwap_window = 20
            typical_price = (high + low + close) / 3.0
            tp_vol = typical_price * volume
            rolling_tp_vol = tp_vol.rolling(window=vwap_window, min_periods=vwap_window // 2).sum()
            rolling_vol = volume.rolling(window=vwap_window, min_periods=vwap_window // 2).sum()

            vwap = rolling_tp_vol / np.maximum(rolling_vol, eps)

            # VWAP ratio: close / VWAP
            vwap_ratio = close / np.maximum(vwap, eps)

            result[f"{ticker}_vwap_ratio"] = vwap_ratio.shift(1)

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
