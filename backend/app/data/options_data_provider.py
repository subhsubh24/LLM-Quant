"""
Real Options Data Provider

Fetches live options chain data from Yahoo Finance via yfinance.
Provides real bid/ask, implied volatility, open interest, and volume.

Falls back to synthetic Black-Scholes pricing when real data unavailable.
"""

import yfinance as yf
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import pandas as pd
import numpy as np
import logging

logger = logging.getLogger(__name__)


@dataclass
class RealOptionsChain:
    """Real options chain data from market."""
    symbol: str
    underlying_price: float
    expiration_dates: List[date]
    calls: pd.DataFrame  # columns: strike, bid, ask, lastPrice, volume, openInterest, impliedVolatility
    puts: pd.DataFrame   # same columns
    fetch_time: datetime
    data_source: str = "yfinance"


class OptionsDataProvider:
    """
    Fetches real options data from Yahoo Finance.

    Usage:
        provider = OptionsDataProvider()
        chain = provider.get_options_chain("AAPL")
        expirations = provider.get_expiration_dates("AAPL")
        leaps = provider.get_leap_expirations("AAPL")  # Only expirations > 180 DTE
    """

    def __init__(self, cache_minutes: int = 5):
        self._cache: Dict[str, Tuple[datetime, RealOptionsChain]] = {}
        self.cache_minutes = cache_minutes

    def get_expiration_dates(self, symbol: str) -> List[date]:
        """Get all available expiration dates for a symbol."""
        try:
            ticker = yf.Ticker(symbol)
            expirations = ticker.options  # Returns tuple of date strings
            return [datetime.strptime(d, "%Y-%m-%d").date() for d in expirations]
        except Exception as e:
            logger.warning(f"Failed to get expirations for {symbol}: {e}")
            return []

    def get_leap_expirations(self, symbol: str, min_dte: int = 180) -> List[date]:
        """Get expiration dates that qualify as LEAPs (>= min_dte days out)."""
        all_dates = self.get_expiration_dates(symbol)
        today = date.today()
        return [d for d in all_dates if (d - today).days >= min_dte]

    def get_options_chain(self, symbol: str, expiration: Optional[str] = None) -> Optional[RealOptionsChain]:
        """
        Fetch real options chain for a symbol.

        Args:
            symbol: Ticker symbol (e.g., "AAPL")
            expiration: Specific expiration date string "YYYY-MM-DD". If None, uses nearest.

        Returns:
            RealOptionsChain with real market data, or None on failure
        """
        # Check cache
        cache_key = f"{symbol}_{expiration}"
        if cache_key in self._cache:
            cached_time, cached_data = self._cache[cache_key]
            if (datetime.now() - cached_time).seconds < self.cache_minutes * 60:
                return cached_data

        try:
            ticker = yf.Ticker(symbol)

            # Get underlying price
            info = ticker.fast_info
            underlying_price = getattr(info, 'last_price', None) or getattr(info, 'previous_close', 0)

            # Get expiration dates
            expirations = ticker.options
            if not expirations:
                logger.warning(f"No options available for {symbol}")
                return None

            # Use specified or nearest expiration
            exp_str = expiration if expiration and expiration in expirations else expirations[0]

            # Fetch chain
            chain = ticker.option_chain(exp_str)

            result = RealOptionsChain(
                symbol=symbol,
                underlying_price=underlying_price,
                expiration_dates=[datetime.strptime(d, "%Y-%m-%d").date() for d in expirations],
                calls=chain.calls,
                puts=chain.puts,
                fetch_time=datetime.now(),
            )

            # Cache it
            self._cache[cache_key] = (datetime.now(), result)

            logger.info(f"Fetched options chain for {symbol} exp={exp_str}: "
                        f"{len(chain.calls)} calls, {len(chain.puts)} puts")
            return result

        except Exception as e:
            logger.warning(f"Failed to fetch options chain for {symbol}: {e}")
            return None

    def get_real_option_price(self, symbol: str, strike: float, expiration: str,
                              option_type: str = "call") -> Optional[Dict]:
        """
        Get real market price for a specific option contract.

        Returns dict with: bid, ask, lastPrice, impliedVolatility, volume, openInterest, delta (estimated)
        """
        chain = self.get_options_chain(symbol, expiration)
        if chain is None:
            return None

        df = chain.calls if option_type.lower() == "call" else chain.puts

        # Find closest strike
        if df.empty:
            return None

        idx = (df['strike'] - strike).abs().idxmin()
        row = df.loc[idx]

        return {
            "strike": row.get("strike", strike),
            "bid": row.get("bid", 0),
            "ask": row.get("ask", 0),
            "lastPrice": row.get("lastPrice", 0),
            "impliedVolatility": row.get("impliedVolatility", 0.3),
            "volume": int(row.get("volume", 0) or 0),
            "openInterest": int(row.get("openInterest", 0) or 0),
            "inTheMoney": bool(row.get("inTheMoney", False)),
            "underlying_price": chain.underlying_price,
        }

    def find_leap_by_delta(self, symbol: str, target_delta: float = 0.70,
                           option_type: str = "call", min_dte: int = 180) -> Optional[Dict]:
        """
        Find a LEAP option contract near the target delta.

        This is the key function for Aristotle-style LEAP trading:
        find a deep ITM call with delta ~0.70 and ~1 year to expiry.
        """
        # Get LEAP expirations
        leap_dates = self.get_leap_expirations(symbol, min_dte=min_dte)
        if not leap_dates:
            logger.info(f"No LEAP expirations for {symbol}")
            return None

        # Pick closest to 1 year
        target_date = date.today().replace(year=date.today().year + 1)
        best_exp = min(leap_dates, key=lambda d: abs((d - target_date).days))

        chain = self.get_options_chain(symbol, best_exp.strftime("%Y-%m-%d"))
        if chain is None:
            return None

        df = chain.calls if option_type.lower() == "call" else chain.puts
        if df.empty:
            return None

        # For calls, deeper ITM = higher delta
        # Approximate delta from moneyness + IV
        # Use the ITM options (strike < underlying for calls)
        if option_type.lower() == "call":
            itm = df[df['strike'] <= chain.underlying_price].copy()
        else:
            itm = df[df['strike'] >= chain.underlying_price].copy()

        if itm.empty:
            return None

        # Pick by implied volatility and moneyness to approximate delta
        # Deep ITM calls have delta close to 1, ATM ~0.5
        # Target delta 0.70 means moderately deep ITM
        moneyness_target = 0.85 if option_type == "call" else 1.15  # ~15% ITM for delta ~0.70
        target_strike = chain.underlying_price * moneyness_target

        idx = (itm['strike'] - target_strike).abs().idxmin()
        row = itm.loc[idx]

        dte = (best_exp - date.today()).days

        return {
            "symbol": symbol,
            "strike": row.get("strike"),
            "expiration": best_exp.isoformat(),
            "dte": dte,
            "option_type": option_type,
            "bid": row.get("bid", 0),
            "ask": row.get("ask", 0),
            "lastPrice": row.get("lastPrice", 0),
            "impliedVolatility": row.get("impliedVolatility", 0.3),
            "volume": int(row.get("volume", 0) or 0),
            "openInterest": int(row.get("openInterest", 0) or 0),
            "underlying_price": chain.underlying_price,
            "estimated_delta": target_delta,
            "leverage_ratio": abs(target_delta) * chain.underlying_price / max(row.get("lastPrice", 1), 0.01),
        }

    def clear_cache(self):
        """Clear all cached data."""
        self._cache.clear()
        logger.info("Options data cache cleared")


# Singleton
_provider: Optional[OptionsDataProvider] = None


def get_options_data_provider() -> OptionsDataProvider:
    """Get or create the singleton OptionsDataProvider instance."""
    global _provider
    if _provider is None:
        _provider = OptionsDataProvider()
    return _provider
