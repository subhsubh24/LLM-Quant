"""
Options Trading Module

Implements PhD-level options analysis:
- Black-Scholes pricing
- Greeks calculation (delta, gamma, theta, vega, rho)
- Implied volatility computation
- Options strategies (spreads, straddles, etc.)
- Risk analysis

This is paper trading only - educational purposes.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, date, timedelta
from enum import Enum
import math
import numpy as np
from scipy.stats import norm
from scipy.optimize import brentq


def _safe_float(value: float, default: float = 0.0) -> float:
    """Sanitize float value for JSON serialization (handle inf/nan)."""
    if value is None or math.isnan(value) or math.isinf(value):
        return default
    return value
import uuid
import logging

logger = logging.getLogger(__name__)


class OptionType(Enum):
    CALL = "call"
    PUT = "put"


class OptionStyle(Enum):
    EUROPEAN = "european"
    AMERICAN = "american"


@dataclass
class Greeks:
    """Option Greeks for risk analysis."""
    delta: float  # Price sensitivity to underlying
    gamma: float  # Rate of change of delta
    theta: float  # Time decay (per day)
    vega: float   # Sensitivity to volatility
    rho: float    # Sensitivity to interest rate

    def to_dict(self) -> Dict:
        return {
            "delta": round(_safe_float(self.delta), 4),
            "gamma": round(_safe_float(self.gamma), 4),
            "theta": round(_safe_float(self.theta), 4),
            "vega": round(_safe_float(self.vega), 4),
            "rho": round(_safe_float(self.rho), 4),
        }


@dataclass
class OptionContract:
    """Represents an options contract."""
    id: str
    symbol: str  # Underlying symbol
    option_type: OptionType
    strike: float
    expiration: date
    style: OptionStyle = OptionStyle.AMERICAN

    # Pricing
    underlying_price: float = 0.0
    premium: float = 0.0
    bid: float = 0.0
    ask: float = 0.0
    last_price: float = 0.0

    # Greeks
    greeks: Optional[Greeks] = None

    # Market data
    implied_volatility: float = 0.0
    open_interest: int = 0
    volume: int = 0

    # Position (if held)
    quantity: int = 0
    avg_cost: float = 0.0

    def days_to_expiry(self) -> int:
        """Calculate days until expiration."""
        return max(0, (self.expiration - date.today()).days)

    def time_to_expiry(self) -> float:
        """Calculate time to expiry in years."""
        return self.days_to_expiry() / 365.0

    def is_itm(self) -> bool:
        """Check if option is in the money."""
        if self.option_type == OptionType.CALL:
            return self.underlying_price > self.strike
        else:
            return self.underlying_price < self.strike

    def intrinsic_value(self) -> float:
        """Calculate intrinsic value."""
        if self.option_type == OptionType.CALL:
            return max(0, self.underlying_price - self.strike)
        else:
            return max(0, self.strike - self.underlying_price)

    def time_value(self) -> float:
        """Calculate time value."""
        return max(0, self.premium - self.intrinsic_value())

    def moneyness(self) -> str:
        """Get moneyness description."""
        pct = (self.underlying_price - self.strike) / self.strike
        if self.option_type == OptionType.PUT:
            pct = -pct

        if pct > 0.05:
            return "ITM"
        elif pct < -0.05:
            return "OTM"
        else:
            return "ATM"

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "option_type": self.option_type.value,
            "strike": _safe_float(self.strike),
            "expiration": self.expiration.isoformat(),
            "days_to_expiry": self.days_to_expiry(),
            "underlying_price": round(_safe_float(self.underlying_price), 2),
            "premium": round(_safe_float(self.premium), 2),
            "bid": round(_safe_float(self.bid), 2),
            "ask": round(_safe_float(self.ask), 2),
            "implied_volatility": round(_safe_float(self.implied_volatility), 4),
            "greeks": self.greeks.to_dict() if self.greeks else None,
            "intrinsic_value": round(_safe_float(self.intrinsic_value()), 2),
            "time_value": round(_safe_float(self.time_value()), 2),
            "moneyness": self.moneyness(),
            "open_interest": self.open_interest,
            "volume": self.volume,
            "quantity": self.quantity,
            "avg_cost": round(_safe_float(self.avg_cost), 2),
        }


class BlackScholes:
    """
    Black-Scholes Option Pricing Model.

    The foundation of modern options theory (Nobel Prize 1997).
    """

    @staticmethod
    def d1(S: float, K: float, T: float, r: float, sigma: float) -> float:
        """Calculate d1 parameter."""
        if T <= 0 or sigma <= 0:
            return 0.0
        return (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))

    @staticmethod
    def d2(S: float, K: float, T: float, r: float, sigma: float) -> float:
        """Calculate d2 parameter."""
        if T <= 0 or sigma <= 0:
            return 0.0
        return BlackScholes.d1(S, K, T, r, sigma) - sigma * np.sqrt(T)

    @classmethod
    def price(
        cls,
        S: float,        # Underlying price
        K: float,        # Strike price
        T: float,        # Time to expiry (years)
        r: float,        # Risk-free rate
        sigma: float,    # Volatility
        option_type: OptionType = OptionType.CALL
    ) -> float:
        """
        Calculate option price using Black-Scholes formula.

        For calls: C = S*N(d1) - K*e^(-rT)*N(d2)
        For puts:  P = K*e^(-rT)*N(-d2) - S*N(-d1)
        """
        if T <= 0:
            # At expiration, return intrinsic value
            if option_type == OptionType.CALL:
                return max(0, S - K)
            else:
                return max(0, K - S)

        d1 = cls.d1(S, K, T, r, sigma)
        d2 = cls.d2(S, K, T, r, sigma)

        if option_type == OptionType.CALL:
            price = S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
        else:
            price = K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)

        return max(0, price)

    @classmethod
    def greeks(
        cls,
        S: float,
        K: float,
        T: float,
        r: float,
        sigma: float,
        option_type: OptionType = OptionType.CALL
    ) -> Greeks:
        """Calculate all option Greeks."""
        if T <= 0 or sigma <= 0:
            # At expiration
            delta = 1.0 if (option_type == OptionType.CALL and S > K) else 0.0
            if option_type == OptionType.PUT:
                delta = -1.0 if S < K else 0.0
            return Greeks(delta=delta, gamma=0, theta=0, vega=0, rho=0)

        d1 = cls.d1(S, K, T, r, sigma)
        d2 = cls.d2(S, K, T, r, sigma)

        # Delta: dV/dS
        if option_type == OptionType.CALL:
            delta = norm.cdf(d1)
        else:
            delta = norm.cdf(d1) - 1

        # Gamma: d^2V/dS^2 (same for calls and puts)
        gamma = norm.pdf(d1) / (S * sigma * np.sqrt(T))

        # Theta: dV/dT (negative because options lose value over time)
        common_theta = -(S * norm.pdf(d1) * sigma) / (2 * np.sqrt(T))
        if option_type == OptionType.CALL:
            theta = common_theta - r * K * np.exp(-r * T) * norm.cdf(d2)
        else:
            theta = common_theta + r * K * np.exp(-r * T) * norm.cdf(-d2)
        theta = theta / 365  # Convert to per-day

        # Vega: dV/d_sigma (same for calls and puts)
        vega = S * norm.pdf(d1) * np.sqrt(T) / 100  # Per 1% move in vol

        # Rho: dV/dr
        if option_type == OptionType.CALL:
            rho = K * T * np.exp(-r * T) * norm.cdf(d2) / 100  # Per 1% move in rates
        else:
            rho = -K * T * np.exp(-r * T) * norm.cdf(-d2) / 100

        return Greeks(
            delta=delta,
            gamma=gamma,
            theta=theta,
            vega=vega,
            rho=rho,
        )

    @classmethod
    def implied_volatility(
        cls,
        option_price: float,
        S: float,
        K: float,
        T: float,
        r: float,
        option_type: OptionType = OptionType.CALL,
        max_iterations: int = 100,
        tolerance: float = 1e-6,
    ) -> float:
        """
        Calculate implied volatility using Brent's method.

        This is the volatility that makes the Black-Scholes price
        equal to the market price.
        """
        if T <= 0 or option_price <= 0:
            return 0.0

        # Define objective function
        def objective(sigma):
            return cls.price(S, K, T, r, sigma, option_type) - option_price

        try:
            # Search between 1% and 500% volatility
            iv = brentq(objective, 0.01, 5.0, xtol=tolerance, maxiter=max_iterations)
            return iv
        except (ValueError, RuntimeError):
            # If brentq fails, use Newton-Raphson
            sigma = 0.3  # Initial guess
            for _ in range(max_iterations):
                price = cls.price(S, K, T, r, sigma, option_type)
                vega = cls.greeks(S, K, T, r, sigma, option_type).vega * 100

                if abs(vega) < 1e-10:
                    break

                sigma = sigma - (price - option_price) / vega
                sigma = max(0.01, min(5.0, sigma))  # Bound sigma

                if abs(price - option_price) < tolerance:
                    break

            return sigma


@dataclass
class OptionsStrategy:
    """Represents an options strategy (multiple legs)."""
    id: str
    name: str
    legs: List[OptionContract]

    # Strategy info
    max_profit: Optional[float] = None
    max_loss: Optional[float] = None
    breakeven_prices: List[float] = field(default_factory=list)

    # Position
    net_premium: float = 0.0  # Positive = credit, negative = debit

    def calculate_pnl_at_price(self, underlying_price: float) -> float:
        """Calculate P&L at a given underlying price at expiration."""
        pnl = self.net_premium

        for leg in self.legs:
            if leg.option_type == OptionType.CALL:
                intrinsic = max(0, underlying_price - leg.strike)
            else:
                intrinsic = max(0, leg.strike - underlying_price)

            if leg.quantity > 0:  # Long position
                pnl += intrinsic * abs(leg.quantity) * 100
            else:  # Short position
                pnl -= intrinsic * abs(leg.quantity) * 100

        return pnl

    def get_pnl_profile(
        self,
        price_range_pct: float = 0.3,
        num_points: int = 50
    ) -> List[Tuple[float, float]]:
        """Get P&L profile across a range of prices."""
        if not self.legs:
            return []

        current_price = self.legs[0].underlying_price
        if current_price <= 0:
            return []
        low = current_price * (1 - price_range_pct)
        high = current_price * (1 + price_range_pct)

        prices = np.linspace(low, high, num_points)
        return [(_safe_float(float(p)), _safe_float(self.calculate_pnl_at_price(p))) for p in prices]

    def portfolio_greeks(self) -> Greeks:
        """Calculate aggregate Greeks for the strategy."""
        total_delta = 0
        total_gamma = 0
        total_theta = 0
        total_vega = 0
        total_rho = 0

        for leg in self.legs:
            if leg.greeks:
                multiplier = leg.quantity * 100  # Each contract is 100 shares
                total_delta += leg.greeks.delta * multiplier
                total_gamma += leg.greeks.gamma * multiplier
                total_theta += leg.greeks.theta * multiplier
                total_vega += leg.greeks.vega * multiplier
                total_rho += leg.greeks.rho * multiplier

        return Greeks(
            delta=total_delta,
            gamma=total_gamma,
            theta=total_theta,
            vega=total_vega,
            rho=total_rho,
        )

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "legs": [leg.to_dict() for leg in self.legs],
            "net_premium": round(_safe_float(self.net_premium), 2),
            "max_profit": round(_safe_float(self.max_profit), 2) if self.max_profit else None,
            "max_loss": round(_safe_float(self.max_loss), 2) if self.max_loss else None,
            "breakeven_prices": [round(_safe_float(p), 2) for p in self.breakeven_prices],
            "portfolio_greeks": self.portfolio_greeks().to_dict(),
            "pnl_profile": self.get_pnl_profile(),
        }


class OptionsManager:
    """
    Manages options positions and strategies.
    Provides tools for building and analyzing options trades.
    """

    DEFAULT_RISK_FREE_RATE = 0.05  # 5% risk-free rate

    def __init__(self):
        self.contracts: Dict[str, OptionContract] = {}
        self.strategies: Dict[str, OptionsStrategy] = {}
        self.positions: Dict[str, OptionContract] = {}  # Active positions

    def price_option(
        self,
        symbol: str,
        underlying_price: float,
        strike: float,
        expiration: date,
        volatility: float,
        option_type: OptionType = OptionType.CALL,
    ) -> OptionContract:
        """Price an option and calculate Greeks."""
        contract_id = f"{symbol}_{option_type.value}_{strike}_{expiration}"

        T = max(0, (expiration - date.today()).days) / 365.0
        r = self.DEFAULT_RISK_FREE_RATE

        # Calculate price and Greeks
        premium = BlackScholes.price(underlying_price, strike, T, r, volatility, option_type)
        greeks = BlackScholes.greeks(underlying_price, strike, T, r, volatility, option_type)

        contract = OptionContract(
            id=contract_id,
            symbol=symbol,
            option_type=option_type,
            strike=strike,
            expiration=expiration,
            underlying_price=underlying_price,
            premium=premium,
            bid=premium * 0.98,  # Simulate spread
            ask=premium * 1.02,
            last_price=premium,
            implied_volatility=volatility,
            greeks=greeks,
        )

        self.contracts[contract_id] = contract
        return contract

    def generate_options_chain(
        self,
        symbol: str,
        underlying_price: float,
        expiration: date,
        volatility: float = 0.30,
        num_strikes: int = 11,
        strike_interval: Optional[float] = None,
    ) -> Dict[str, List[OptionContract]]:
        """Generate a full options chain."""
        if strike_interval is None:
            # Auto-calculate strike interval
            strike_interval = underlying_price * 0.025  # 2.5% intervals
            # Round to nice numbers
            if strike_interval >= 10:
                strike_interval = round(strike_interval / 5) * 5
            elif strike_interval >= 1:
                strike_interval = round(strike_interval)
            else:
                strike_interval = round(strike_interval, 1)

        # Generate strikes around ATM
        atm_strike = round(underlying_price / strike_interval) * strike_interval
        half_range = (num_strikes // 2) * strike_interval

        strikes = np.arange(
            atm_strike - half_range,
            atm_strike + half_range + strike_interval,
            strike_interval
        )

        calls = []
        puts = []

        for strike in strikes:
            call = self.price_option(
                symbol, underlying_price, strike, expiration, volatility, OptionType.CALL
            )
            put = self.price_option(
                symbol, underlying_price, strike, expiration, volatility, OptionType.PUT
            )
            calls.append(call)
            puts.append(put)

        return {
            "calls": calls,
            "puts": puts,
            "underlying_price": underlying_price,
            "expiration": expiration.isoformat(),
        }

    # ================== Real Market Data ==================

    def generate_real_options_chain(
        self,
        symbol: str,
        expiration: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Generate options chain using REAL market data from yfinance.

        Returns None if real data is unavailable. Never falls back to synthetic
        data -- callers should handle None explicitly rather than silently
        consuming fabricated prices.
        """
        from ..data.options_data_provider import get_options_data_provider

        provider = get_options_data_provider()
        real_chain = provider.get_options_chain(symbol, expiration)

        if real_chain is None:
            logger.warning(f"Real options data unavailable for {symbol} - no synthetic fallback")
            return None

        # Convert real data to our OptionContract format
        calls = []
        puts = []

        # Determine expiration date from the chain
        if expiration:
            exp_date = datetime.strptime(expiration, "%Y-%m-%d").date()
        elif real_chain.expiration_dates:
            exp_date = real_chain.expiration_dates[0]
        else:
            exp_date = date.today()

        for _, row in real_chain.calls.iterrows():
            contract = self._real_row_to_contract(
                symbol, row, real_chain.underlying_price,
                OptionType.CALL, exp_date
            )
            if contract:
                calls.append(contract)

        for _, row in real_chain.puts.iterrows():
            contract = self._real_row_to_contract(
                symbol, row, real_chain.underlying_price,
                OptionType.PUT, exp_date
            )
            if contract:
                puts.append(contract)

        return {
            "calls": calls,
            "puts": puts,
            "underlying_price": real_chain.underlying_price,
            "data_source": "yfinance_real",
            "fetch_time": real_chain.fetch_time.isoformat(),
        }

    def _real_row_to_contract(self, symbol, row, underlying_price, option_type, expiration):
        """Convert a yfinance options row to our OptionContract."""
        try:
            strike = float(row.get('strike', 0))
            if strike <= 0:
                return None

            T = max(0, (expiration - date.today()).days) / 365.0
            iv = float(row.get('impliedVolatility', 0.3) or 0.3)

            # Use real market prices
            bid = float(row.get('bid', 0) or 0)
            ask = float(row.get('ask', 0) or 0)
            last = float(row.get('lastPrice', 0) or 0)
            premium = last if last > 0 else (bid + ask) / 2

            # Calculate Greeks using real IV
            greeks = BlackScholes.greeks(
                underlying_price, strike, T, self.DEFAULT_RISK_FREE_RATE, iv, option_type
            )

            contract_id = f"{symbol}_{option_type.value}_{strike}_{expiration}_real"
            contract = OptionContract(
                id=contract_id,
                symbol=symbol,
                option_type=option_type,
                strike=strike,
                expiration=expiration,
                underlying_price=underlying_price,
                premium=premium,
                bid=bid,
                ask=ask,
                last_price=last,
                implied_volatility=iv,
                greeks=greeks,
                open_interest=int(row.get('openInterest', 0) or 0),
                volume=int(row.get('volume', 0) or 0),
            )

            self.contracts[contract_id] = contract
            return contract
        except Exception as e:
            logger.debug(f"Failed to convert options row: {e}")
            return None

    # ================== Common Strategies ==================

    def create_covered_call(
        self,
        symbol: str,
        underlying_price: float,
        strike: float,
        expiration: date,
        volatility: float,
        shares: int = 100,
    ) -> OptionsStrategy:
        """
        Covered Call: Long stock + short call.
        - Bullish to neutral outlook
        - Generates income from premium
        - Caps upside at strike price
        """
        call = self.price_option(
            symbol, underlying_price, strike, expiration, volatility, OptionType.CALL
        )
        call.quantity = -1  # Short

        strategy = OptionsStrategy(
            id=str(uuid.uuid4())[:8],
            name=f"Covered Call {symbol} @ ${strike}",
            legs=[call],
            net_premium=call.premium * 100,  # Credit received
            max_profit=(strike - underlying_price) * shares + call.premium * 100,
            max_loss=underlying_price * shares - call.premium * 100,  # Stock to zero
            breakeven_prices=[underlying_price - call.premium],
        )

        self.strategies[strategy.id] = strategy
        logger.info(f"Created covered call: {strategy.name}")
        return strategy

    def create_protective_put(
        self,
        symbol: str,
        underlying_price: float,
        strike: float,
        expiration: date,
        volatility: float,
        shares: int = 100,
    ) -> OptionsStrategy:
        """
        Protective Put: Long stock + long put.
        - Insurance against downside
        - Unlimited upside potential
        - Cost is the put premium
        """
        put = self.price_option(
            symbol, underlying_price, strike, expiration, volatility, OptionType.PUT
        )
        put.quantity = 1  # Long

        strategy = OptionsStrategy(
            id=str(uuid.uuid4())[:8],
            name=f"Protective Put {symbol} @ ${strike}",
            legs=[put],
            net_premium=-put.premium * 100,  # Debit paid
            max_profit=float('inf'),  # Unlimited
            max_loss=(underlying_price - strike + put.premium) * 100,
            breakeven_prices=[underlying_price + put.premium],
        )

        self.strategies[strategy.id] = strategy
        logger.info(f"Created protective put: {strategy.name}")
        return strategy

    def create_bull_call_spread(
        self,
        symbol: str,
        underlying_price: float,
        lower_strike: float,
        upper_strike: float,
        expiration: date,
        volatility: float,
    ) -> OptionsStrategy:
        """
        Bull Call Spread: Long lower strike call + short higher strike call.
        - Moderately bullish
        - Limited risk, limited reward
        - Lower cost than buying call outright
        """
        long_call = self.price_option(
            symbol, underlying_price, lower_strike, expiration, volatility, OptionType.CALL
        )
        long_call.quantity = 1

        short_call = self.price_option(
            symbol, underlying_price, upper_strike, expiration, volatility, OptionType.CALL
        )
        short_call.quantity = -1

        net_debit = (long_call.premium - short_call.premium) * 100
        max_profit = (upper_strike - lower_strike) * 100 - net_debit
        max_loss = net_debit
        breakeven = lower_strike + (long_call.premium - short_call.premium)

        strategy = OptionsStrategy(
            id=str(uuid.uuid4())[:8],
            name=f"Bull Call Spread {symbol} ${lower_strike}/${upper_strike}",
            legs=[long_call, short_call],
            net_premium=-net_debit,
            max_profit=max_profit,
            max_loss=max_loss,
            breakeven_prices=[breakeven],
        )

        self.strategies[strategy.id] = strategy
        logger.info(f"Created bull call spread: {strategy.name}")
        return strategy

    def create_bear_put_spread(
        self,
        symbol: str,
        underlying_price: float,
        lower_strike: float,
        upper_strike: float,
        expiration: date,
        volatility: float,
    ) -> OptionsStrategy:
        """
        Bear Put Spread: Long higher strike put + short lower strike put.
        - Moderately bearish
        - Limited risk, limited reward
        """
        long_put = self.price_option(
            symbol, underlying_price, upper_strike, expiration, volatility, OptionType.PUT
        )
        long_put.quantity = 1

        short_put = self.price_option(
            symbol, underlying_price, lower_strike, expiration, volatility, OptionType.PUT
        )
        short_put.quantity = -1

        net_debit = (long_put.premium - short_put.premium) * 100
        max_profit = (upper_strike - lower_strike) * 100 - net_debit
        max_loss = net_debit
        breakeven = upper_strike - (long_put.premium - short_put.premium)

        strategy = OptionsStrategy(
            id=str(uuid.uuid4())[:8],
            name=f"Bear Put Spread {symbol} ${lower_strike}/${upper_strike}",
            legs=[long_put, short_put],
            net_premium=-net_debit,
            max_profit=max_profit,
            max_loss=max_loss,
            breakeven_prices=[breakeven],
        )

        self.strategies[strategy.id] = strategy
        logger.info(f"Created bear put spread: {strategy.name}")
        return strategy

    def create_straddle(
        self,
        symbol: str,
        underlying_price: float,
        strike: float,
        expiration: date,
        volatility: float,
        is_long: bool = True,
    ) -> OptionsStrategy:
        """
        Straddle: Long/short call and put at same strike.
        - Long straddle: Bet on volatility (big move in either direction)
        - Short straddle: Bet on low volatility (stay near strike)
        """
        call = self.price_option(
            symbol, underlying_price, strike, expiration, volatility, OptionType.CALL
        )
        put = self.price_option(
            symbol, underlying_price, strike, expiration, volatility, OptionType.PUT
        )

        quantity = 1 if is_long else -1
        call.quantity = quantity
        put.quantity = quantity

        total_premium = (call.premium + put.premium) * 100

        if is_long:
            strategy = OptionsStrategy(
                id=str(uuid.uuid4())[:8],
                name=f"Long Straddle {symbol} @ ${strike}",
                legs=[call, put],
                net_premium=-total_premium,
                max_profit=float('inf'),
                max_loss=total_premium,
                breakeven_prices=[
                    strike - call.premium - put.premium,
                    strike + call.premium + put.premium,
                ],
            )
        else:
            strategy = OptionsStrategy(
                id=str(uuid.uuid4())[:8],
                name=f"Short Straddle {symbol} @ ${strike}",
                legs=[call, put],
                net_premium=total_premium,
                max_profit=total_premium,
                max_loss=float('inf'),
                breakeven_prices=[
                    strike - call.premium - put.premium,
                    strike + call.premium + put.premium,
                ],
            )

        self.strategies[strategy.id] = strategy
        logger.info(f"Created straddle: {strategy.name}")
        return strategy

    def create_strangle(
        self,
        symbol: str,
        underlying_price: float,
        put_strike: float,
        call_strike: float,
        expiration: date,
        volatility: float,
        is_long: bool = True,
    ) -> OptionsStrategy:
        """
        Strangle: Long/short OTM call and OTM put.
        - Cheaper than straddle
        - Needs bigger move to profit
        """
        call = self.price_option(
            symbol, underlying_price, call_strike, expiration, volatility, OptionType.CALL
        )
        put = self.price_option(
            symbol, underlying_price, put_strike, expiration, volatility, OptionType.PUT
        )

        quantity = 1 if is_long else -1
        call.quantity = quantity
        put.quantity = quantity

        total_premium = (call.premium + put.premium) * 100

        if is_long:
            strategy = OptionsStrategy(
                id=str(uuid.uuid4())[:8],
                name=f"Long Strangle {symbol} ${put_strike}/${call_strike}",
                legs=[call, put],
                net_premium=-total_premium,
                max_profit=float('inf'),
                max_loss=total_premium,
                breakeven_prices=[
                    put_strike - total_premium / 100,
                    call_strike + total_premium / 100,
                ],
            )
        else:
            strategy = OptionsStrategy(
                id=str(uuid.uuid4())[:8],
                name=f"Short Strangle {symbol} ${put_strike}/${call_strike}",
                legs=[call, put],
                net_premium=total_premium,
                max_profit=total_premium,
                max_loss=float('inf'),
                breakeven_prices=[
                    put_strike - total_premium / 100,
                    call_strike + total_premium / 100,
                ],
            )

        self.strategies[strategy.id] = strategy
        logger.info(f"Created strangle: {strategy.name}")
        return strategy

    def create_iron_condor(
        self,
        symbol: str,
        underlying_price: float,
        put_lower: float,
        put_upper: float,
        call_lower: float,
        call_upper: float,
        expiration: date,
        volatility: float,
    ) -> OptionsStrategy:
        """
        Iron Condor: Bull put spread + bear call spread.
        - Profit if price stays in range
        - Popular income strategy
        - Limited risk, limited reward
        """
        # Bull put spread (short upper put, long lower put)
        short_put = self.price_option(
            symbol, underlying_price, put_upper, expiration, volatility, OptionType.PUT
        )
        short_put.quantity = -1

        long_put = self.price_option(
            symbol, underlying_price, put_lower, expiration, volatility, OptionType.PUT
        )
        long_put.quantity = 1

        # Bear call spread (short lower call, long upper call)
        short_call = self.price_option(
            symbol, underlying_price, call_lower, expiration, volatility, OptionType.CALL
        )
        short_call.quantity = -1

        long_call = self.price_option(
            symbol, underlying_price, call_upper, expiration, volatility, OptionType.CALL
        )
        long_call.quantity = 1

        # Net credit = premium received - premium paid
        net_credit = (
            short_put.premium + short_call.premium -
            long_put.premium - long_call.premium
        ) * 100

        # Max loss is width of spread - net credit
        put_width = (put_upper - put_lower) * 100
        call_width = (call_upper - call_lower) * 100
        max_loss = max(put_width, call_width) - net_credit

        strategy = OptionsStrategy(
            id=str(uuid.uuid4())[:8],
            name=f"Iron Condor {symbol} ${put_lower}/{put_upper}/{call_lower}/{call_upper}",
            legs=[long_put, short_put, short_call, long_call],
            net_premium=net_credit,
            max_profit=net_credit,
            max_loss=max_loss,
            breakeven_prices=[
                put_upper - net_credit / 100,
                call_lower + net_credit / 100,
            ],
        )

        self.strategies[strategy.id] = strategy
        logger.info(f"Created iron condor: {strategy.name}")
        return strategy

    def create_butterfly(
        self,
        symbol: str,
        underlying_price: float,
        lower_strike: float,
        middle_strike: float,
        upper_strike: float,
        expiration: date,
        volatility: float,
        use_calls: bool = True,
    ) -> OptionsStrategy:
        """
        Butterfly Spread: Limited risk bet on low volatility.
        - Buy 1 lower, sell 2 middle, buy 1 upper
        - Max profit at middle strike at expiration
        """
        option_type = OptionType.CALL if use_calls else OptionType.PUT

        lower = self.price_option(
            symbol, underlying_price, lower_strike, expiration, volatility, option_type
        )
        lower.quantity = 1

        middle = self.price_option(
            symbol, underlying_price, middle_strike, expiration, volatility, option_type
        )
        middle.quantity = -2

        upper = self.price_option(
            symbol, underlying_price, upper_strike, expiration, volatility, option_type
        )
        upper.quantity = 1

        net_debit = (lower.premium - 2 * middle.premium + upper.premium) * 100
        max_profit = (middle_strike - lower_strike) * 100 - net_debit
        max_loss = net_debit

        strategy = OptionsStrategy(
            id=str(uuid.uuid4())[:8],
            name=f"Butterfly {symbol} ${lower_strike}/${middle_strike}/${upper_strike}",
            legs=[lower, middle, upper],
            net_premium=-net_debit,
            max_profit=max_profit,
            max_loss=max_loss,
            breakeven_prices=[
                lower_strike + net_debit / 100,
                upper_strike - net_debit / 100,
            ],
        )

        self.strategies[strategy.id] = strategy
        logger.info(f"Created butterfly: {strategy.name}")
        return strategy

    def analyze_strategy_risk(self, strategy_id: str) -> Dict[str, Any]:
        """Comprehensive risk analysis for a strategy."""
        strategy = self.strategies.get(strategy_id)
        if not strategy:
            return {"error": "Strategy not found"}

        greeks = strategy.portfolio_greeks()
        pnl_profile = strategy.get_pnl_profile(0.3, 100)

        # Calculate probability of profit (simplified)
        # In practice, would use Monte Carlo simulation
        pnl_at_current = strategy.calculate_pnl_at_price(strategy.legs[0].underlying_price)

        return {
            "strategy_id": strategy_id,
            "name": strategy.name,
            "greeks": greeks.to_dict(),
            "net_premium": strategy.net_premium,
            "max_profit": strategy.max_profit,
            "max_loss": strategy.max_loss,
            "breakeven_prices": strategy.breakeven_prices,
            "risk_reward_ratio": abs(strategy.max_profit / strategy.max_loss) if strategy.max_loss else float('inf'),
            "pnl_at_current": pnl_at_current,
            "pnl_profile": pnl_profile[:20],  # Sample
            "theta_decay_daily": greeks.theta,
            "delta_exposure": greeks.delta,
            "vega_exposure": greeks.vega,
        }

    def get_strategy(self, strategy_id: str) -> Optional[OptionsStrategy]:
        """Get strategy by ID."""
        return self.strategies.get(strategy_id)

    def list_strategies(self) -> List[Dict]:
        """List all strategies."""
        return [s.to_dict() for s in self.strategies.values()]


# Singleton
_manager: Optional[OptionsManager] = None

def get_options_manager() -> OptionsManager:
    global _manager
    if _manager is None:
        _manager = OptionsManager()
    return _manager
