"""
LEAP Options Trading Engine

Implements Long-Term Equity Anticipation Securities (LEAPS) trading capability
following an Aristotle-style deep-value leverage approach:

- Deep ITM calls (delta 0.70-0.85) give stock-like returns at ~1/3 the capital
- This creates 2-3x leverage with defined risk (max loss = premium paid)
- Roll positions before expiry to maintain continuous exposure
- Size positions so total premium at risk is < 30% of portfolio

Key principles:
1. LEAPs as stock replacement: buy deep ITM calls with 1+ year to expiry
2. Delta targeting: 0.70 sweet spot balances leverage vs. time decay
3. Rolling discipline: roll when DTE < 60 to avoid accelerating theta
4. Position sizing: half-Kelly with hard portfolio limits
5. Signal integration: only enter LEAPs on strong directional signals

This is paper trading only - educational purposes.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, date, timedelta
import math
import uuid
import logging

import numpy as np

from .options import (
    BlackScholes,
    OptionContract,
    OptionType,
    OptionStyle,
    Greeks,
    _safe_float,
)
from ..signals.engine import StockSignal, SignalStrength

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. LEAPConfig
# ---------------------------------------------------------------------------

@dataclass
class LEAPConfig:
    """
    Configuration for LEAP options trading strategy.

    Defaults are tuned for a conservative stock-replacement approach:
    deep ITM calls with ~1 year to expiry, sized so that total premium
    at risk never exceeds 30 % of the portfolio.
    """

    # --- Expiry window ---
    min_dte: int = 180       # Minimum days to expiry (6 months floor)
    max_dte: int = 730       # Maximum days to expiry (2 years ceiling)
    target_dte: int = 365    # Ideal ~1 year out

    # --- Delta targeting ---
    min_delta: float = 0.60  # Deep ITM lower bound
    max_delta: float = 0.85  # Deep ITM upper bound
    target_delta: float = 0.70  # Sweet spot for leverage vs. cost

    # --- Portfolio-level limits ---
    max_portfolio_options_pct: float = 0.30   # Max 30 % of portfolio in LEAP premium
    max_single_position_pct: float = 0.05     # Max 5 % per option position

    # --- Risk management ---
    stop_loss_pct: float = 0.40    # Close if premium falls 40 %
    take_profit_pct: float = 1.00  # Close if premium doubles (100 % gain)

    # --- Rolling ---
    roll_dte_threshold: int = 60   # Roll when DTE drops below 60

    # --- Pricing assumptions ---
    risk_free_rate: float = 0.05   # 5 % annualized risk-free rate


# ---------------------------------------------------------------------------
# 2. LEAPSelector
# ---------------------------------------------------------------------------

class LEAPSelector:
    """
    Selects optimal LEAP contracts for a given underlying.

    The selector uses Black-Scholes to find the strike whose delta is closest
    to the configured target, then prices the contract and computes useful
    derived metrics (leverage ratio, breakeven, annualised cost).
    """

    def __init__(self, config: Optional[LEAPConfig] = None):
        self.config = config or LEAPConfig()

    # ----- public API -----

    def select_call_leap(
        self,
        symbol: str,
        current_price: float,
        volatility: float,
        signal_strength: SignalStrength,
    ) -> OptionContract:
        """
        Select the optimal deep-ITM LEAP call for *symbol*.

        Strategy:
        - Target expiry ~1 year out (configurable via config.target_dte)
        - Search strikes below current price to find delta ~ target_delta
        - Adjust delta target slightly based on signal conviction

        Returns a fully-priced OptionContract with Greeks populated.
        """
        target_delta = self._adjusted_delta(signal_strength, OptionType.CALL)
        expiration = self._target_expiration()
        T = (expiration - date.today()).days / 365.0
        r = self.config.risk_free_rate

        strike = self._find_strike_for_delta(
            current_price, volatility, T, r, target_delta, OptionType.CALL
        )

        contract = self._build_contract(
            symbol, current_price, strike, expiration, volatility, OptionType.CALL
        )

        logger.info(
            "Selected LEAP call: %s strike=%.2f exp=%s delta=%.3f premium=%.2f leverage=%.2fx",
            symbol, strike, expiration, contract.greeks.delta,
            contract.premium, self.calculate_leverage_ratio(contract),
        )
        return contract

    def select_put_leap(
        self,
        symbol: str,
        current_price: float,
        volatility: float,
        signal_strength: SignalStrength,
    ) -> OptionContract:
        """
        Select the optimal deep-ITM LEAP put for *symbol*.

        Mirror of select_call_leap but for bearish exposure.
        Strikes are above current price so the put is deep ITM.
        """
        target_delta = self._adjusted_delta(signal_strength, OptionType.PUT)
        expiration = self._target_expiration()
        T = (expiration - date.today()).days / 365.0
        r = self.config.risk_free_rate

        strike = self._find_strike_for_delta(
            current_price, volatility, T, r, target_delta, OptionType.PUT
        )

        contract = self._build_contract(
            symbol, current_price, strike, expiration, volatility, OptionType.PUT
        )

        logger.info(
            "Selected LEAP put: %s strike=%.2f exp=%s delta=%.3f premium=%.2f leverage=%.2fx",
            symbol, strike, expiration, contract.greeks.delta,
            contract.premium, self.calculate_leverage_ratio(contract),
        )
        return contract

    def calculate_leverage_ratio(self, contract: OptionContract) -> float:
        """
        Effective leverage = |delta| * underlying_price / premium.

        Tells you how much underlying exposure you get per dollar of premium.
        A deep ITM LEAP call with delta 0.75 at $30 premium on a $150 stock
        gives leverage = 0.75 * 150 / 30 = 3.75x.
        """
        if contract.premium <= 0:
            return 0.0
        delta_abs = abs(contract.greeks.delta) if contract.greeks else 0.0
        return delta_abs * contract.underlying_price / contract.premium

    def calculate_breakeven(self, contract: OptionContract) -> float:
        """
        Breakeven price at expiration.

        Call: strike + premium
        Put:  strike - premium
        """
        if contract.option_type == OptionType.CALL:
            return contract.strike + contract.premium
        else:
            return contract.strike - contract.premium

    def calculate_annualized_cost(self, contract: OptionContract) -> float:
        """
        Annualised cost of leverage ("rent" for the LEAP position).

        This is the time value component annualised:
            annualised_cost = time_value / (underlying_price * T)

        where T is time to expiry in years.  Expressed as a percentage of
        the underlying price -- analogous to the interest rate on a margin
        loan, making it easy to compare LEAP leverage vs. margin leverage.
        """
        time_val = contract.time_value()
        T = contract.time_to_expiry()
        if T <= 0 or contract.underlying_price <= 0:
            return 0.0
        return time_val / (contract.underlying_price * T)

    # ----- internal helpers -----

    def _adjusted_delta(
        self, signal_strength: SignalStrength, option_type: OptionType
    ) -> float:
        """
        Adjust the target delta based on signal conviction.

        Stronger signals -> deeper ITM (higher delta) for more stock-like
        behaviour and less time-value drag.
        Weaker signals -> closer to ATM for cheaper entry but more risk.
        """
        base = self.config.target_delta
        adjustment_map = {
            SignalStrength.STRONG_BUY: 0.10,
            SignalStrength.BUY: 0.0,
            SignalStrength.HOLD: -0.05,
            SignalStrength.SELL: 0.0,
            SignalStrength.STRONG_SELL: 0.10,
        }
        adjustment = adjustment_map.get(signal_strength, 0.0)
        target = base + adjustment
        target = max(self.config.min_delta, min(self.config.max_delta, target))

        # For puts, delta is negative; we work with absolute values internally
        return target

    def _target_expiration(self) -> date:
        """Return the ideal expiration date (target_dte days from today)."""
        return date.today() + timedelta(days=self.config.target_dte)

    def _find_strike_for_delta(
        self,
        S: float,
        sigma: float,
        T: float,
        r: float,
        target_delta: float,
        option_type: OptionType,
    ) -> float:
        """
        Binary search for the strike that produces the target |delta|.

        For calls, lower strike -> higher delta.
        For puts, higher strike -> higher |delta|.
        """
        # Determine search bounds as multiples of underlying price
        if option_type == OptionType.CALL:
            lo_strike = S * 0.50   # very deep ITM
            hi_strike = S * 1.10   # slightly OTM
        else:
            lo_strike = S * 0.90   # slightly OTM put
            hi_strike = S * 1.50   # very deep ITM put

        best_strike = S  # fallback = ATM
        best_diff = float("inf")

        # Fine-grained search: 200 steps across the range
        num_steps = 200
        step = (hi_strike - lo_strike) / num_steps

        for i in range(num_steps + 1):
            K = lo_strike + i * step
            greeks = BlackScholes.greeks(S, K, T, r, sigma, option_type)
            delta_abs = abs(greeks.delta)
            diff = abs(delta_abs - target_delta)
            if diff < best_diff:
                best_diff = diff
                best_strike = K

        # Round to a reasonable tick (nearest $0.50 for readability)
        best_strike = round(best_strike * 2) / 2.0
        return best_strike

    def _build_contract(
        self,
        symbol: str,
        current_price: float,
        strike: float,
        expiration: date,
        volatility: float,
        option_type: OptionType,
    ) -> OptionContract:
        """Create a fully-priced OptionContract with Greeks."""
        T = (expiration - date.today()).days / 365.0
        r = self.config.risk_free_rate

        premium = BlackScholes.price(current_price, strike, T, r, volatility, option_type)
        greeks = BlackScholes.greeks(current_price, strike, T, r, volatility, option_type)

        contract_id = (
            f"LEAP_{symbol}_{option_type.value}_{strike:.0f}"
            f"_{expiration.strftime('%Y%m%d')}_{uuid.uuid4().hex[:6]}"
        )

        return OptionContract(
            id=contract_id,
            symbol=symbol,
            option_type=option_type,
            strike=strike,
            expiration=expiration,
            style=OptionStyle.AMERICAN,
            underlying_price=current_price,
            premium=premium,
            bid=premium * 0.98,
            ask=premium * 1.02,
            last_price=premium,
            implied_volatility=volatility,
            greeks=greeks,
        )


# ---------------------------------------------------------------------------
# 3. LEAPPositionSizer
# ---------------------------------------------------------------------------

class LEAPPositionSizer:
    """
    Conservative position sizing for LEAP options.

    Uses half-Kelly criterion combined with hard portfolio-level caps
    to determine how many contracts to buy for a given signal.
    """

    def __init__(self, config: Optional[LEAPConfig] = None):
        self.config = config or LEAPConfig()

    def size_position(
        self,
        signal: StockSignal,
        portfolio_value: float,
        current_options_exposure: float,
        config: Optional[LEAPConfig] = None,
    ) -> Dict[str, Any]:
        """
        Determine how many LEAP contracts to buy.

        Args:
            signal: The trading signal for the underlying.
            portfolio_value: Total portfolio value in dollars.
            current_options_exposure: Current premium invested in options.
            config: Override config (uses self.config if None).

        Returns:
            Dict with keys:
                contracts       - number of contracts to buy
                premium_cost    - total premium outlay (contracts * premium * 100)
                delta_exposure  - equivalent share exposure
                max_loss        - maximum loss (= premium_cost, since LEAP buyer)
        """
        cfg = config or self.config

        # Remaining budget for new options positions
        remaining_budget = (
            portfolio_value * cfg.max_portfolio_options_pct - current_options_exposure
        )
        if remaining_budget <= 0:
            logger.info("Options budget exhausted; no new LEAP position.")
            return {
                "contracts": 0,
                "premium_cost": 0.0,
                "delta_exposure": 0.0,
                "max_loss": 0.0,
            }

        # Per-position cap
        position_cap = portfolio_value * cfg.max_single_position_pct

        # Kelly sizing (half-Kelly for conservatism)
        win_prob = self._win_probability(signal)
        avg_win = signal.take_profit_pct if signal.take_profit_pct > 0 else cfg.take_profit_pct
        avg_loss = signal.stop_loss_pct if signal.stop_loss_pct > 0 else cfg.stop_loss_pct
        kelly = self.kelly_fraction(win_prob, avg_win, avg_loss)

        kelly_budget = portfolio_value * kelly

        # Final allocation = min of all constraints
        allocation = max(0.0, min(remaining_budget, position_cap, kelly_budget))

        # Estimate per-contract cost (premium * 100 shares)
        estimated_premium = signal.expected_volatility * 0.25  # rough heuristic
        per_contract_cost = max(estimated_premium * 100, 1.0)

        contracts = int(allocation / per_contract_cost)
        contracts = max(0, contracts)

        premium_cost = contracts * per_contract_cost
        # Delta exposure: assume target delta * 100 shares per contract
        delta_exposure = contracts * cfg.target_delta * 100

        return {
            "contracts": contracts,
            "premium_cost": round(premium_cost, 2),
            "delta_exposure": round(delta_exposure, 2),
            "max_loss": round(premium_cost, 2),
        }

    def kelly_fraction(
        self,
        win_prob: float,
        avg_win: float,
        avg_loss: float,
    ) -> float:
        """
        Half-Kelly criterion for conservative sizing.

        Full Kelly:  f* = (p * b - q) / b
            where p = win probability, q = 1-p, b = avg_win / avg_loss

        We use half of that to reduce drawdown variance.
        """
        if avg_loss <= 0 or avg_win <= 0:
            return 0.0

        p = max(0.0, min(1.0, win_prob))
        q = 1.0 - p
        b = avg_win / avg_loss

        full_kelly = (p * b - q) / b if b > 0 else 0.0
        half_kelly = max(0.0, full_kelly) / 2.0

        # Hard cap at 25 % of portfolio regardless of Kelly output
        return min(half_kelly, 0.25)

    def risk_budget_allocation(
        self,
        signals: List[StockSignal],
        portfolio_value: float,
    ) -> Dict[str, float]:
        """
        Allocate the options risk budget across multiple signals.

        Allocation is proportional to (composite_score * confidence), subject
        to per-position and portfolio-wide caps.

        Returns:
            Dict mapping symbol -> dollar allocation for premium spend.
        """
        cfg = self.config
        total_budget = portfolio_value * cfg.max_portfolio_options_pct
        position_cap = portfolio_value * cfg.max_single_position_pct

        # Score each signal
        scored: List[Tuple[str, float]] = []
        for sig in signals:
            if sig.signal_strength in (SignalStrength.STRONG_BUY, SignalStrength.BUY):
                score = max(sig.composite_score, 0.0) * sig.confidence
                scored.append((sig.symbol, score))
            elif sig.signal_strength in (SignalStrength.STRONG_SELL, SignalStrength.SELL):
                # Bearish signals also get budget (for LEAP puts)
                score = abs(min(sig.composite_score, 0.0)) * sig.confidence
                scored.append((sig.symbol, score))

        if not scored:
            return {}

        total_score = sum(s for _, s in scored)
        if total_score <= 0:
            return {}

        allocations: Dict[str, float] = {}
        for symbol, score in scored:
            raw_alloc = total_budget * (score / total_score)
            allocations[symbol] = round(min(raw_alloc, position_cap), 2)

        # Verify total does not exceed budget
        alloc_sum = sum(allocations.values())
        if alloc_sum > total_budget:
            scale = total_budget / alloc_sum
            allocations = {k: round(v * scale, 2) for k, v in allocations.items()}

        return allocations

    # ----- internal helpers -----

    @staticmethod
    def _win_probability(signal: StockSignal) -> float:
        """
        Estimate win probability from signal strength and confidence.

        Heuristic mapping -- in production this would be calibrated from
        backtested hit rates.
        """
        base_map = {
            SignalStrength.STRONG_BUY: 0.65,
            SignalStrength.BUY: 0.55,
            SignalStrength.HOLD: 0.50,
            SignalStrength.SELL: 0.55,
            SignalStrength.STRONG_SELL: 0.65,
        }
        base = base_map.get(signal.signal_strength, 0.50)
        # Adjust by confidence (0-1 scale)
        return base * (0.7 + 0.3 * signal.confidence)


# ---------------------------------------------------------------------------
# 4. LEAPPosition (dataclass)
# ---------------------------------------------------------------------------

@dataclass
class LEAPPosition:
    """
    Represents a live LEAP position in the portfolio.

    Tracks the contract, entry details, and evolving P&L.
    """

    contract: OptionContract
    entry_date: date
    entry_premium: float
    current_premium: float
    contracts: int                # Number of contracts held (each = 100 shares)
    signal_at_entry: SignalStrength

    # Derived / updated fields
    unrealized_pnl: float = 0.0
    days_held: int = 0

    def __post_init__(self):
        self.days_held = (date.today() - self.entry_date).days
        self.unrealized_pnl = (
            (self.current_premium - self.entry_premium) * self.contracts * 100
        )

    def update(self, new_premium: float) -> None:
        """Update the position with a new market premium."""
        self.current_premium = new_premium
        self.days_held = (date.today() - self.entry_date).days
        self.unrealized_pnl = (
            (self.current_premium - self.entry_premium) * self.contracts * 100
        )

    @property
    def total_cost(self) -> float:
        """Total premium paid at entry."""
        return self.entry_premium * self.contracts * 100

    @property
    def current_value(self) -> float:
        """Current market value of the position."""
        return self.current_premium * self.contracts * 100

    @property
    def return_pct(self) -> float:
        """Percentage return on premium invested."""
        if self.total_cost <= 0:
            return 0.0
        return self.unrealized_pnl / self.total_cost

    @property
    def delta_exposure(self) -> float:
        """Equivalent share delta exposure."""
        if self.contract.greeks:
            return abs(self.contract.greeks.delta) * self.contracts * 100
        return 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "contract": self.contract.to_dict(),
            "entry_date": self.entry_date.isoformat(),
            "entry_premium": round(_safe_float(self.entry_premium), 2),
            "current_premium": round(_safe_float(self.current_premium), 2),
            "contracts": self.contracts,
            "signal_at_entry": self.signal_at_entry.name,
            "unrealized_pnl": round(_safe_float(self.unrealized_pnl), 2),
            "days_held": self.days_held,
            "total_cost": round(_safe_float(self.total_cost), 2),
            "current_value": round(_safe_float(self.current_value), 2),
            "return_pct": round(_safe_float(self.return_pct), 4),
            "delta_exposure": round(_safe_float(self.delta_exposure), 2),
        }


# ---------------------------------------------------------------------------
# 5. LEAPPortfolioManager
# ---------------------------------------------------------------------------

class LEAPPortfolioManager:
    """
    Manages a portfolio of LEAP positions end-to-end:

    - Evaluates trading signals to decide whether a LEAP is appropriate
    - Selects optimal contracts via LEAPSelector
    - Sizes positions via LEAPPositionSizer
    - Monitors P&L, Greeks, and rolling needs
    - Produces aggregate portfolio summaries
    """

    def __init__(self, config: Optional[LEAPConfig] = None):
        self.config = config or LEAPConfig()
        self.positions: Dict[str, LEAPPosition] = {}   # keyed by contract id
        self.selector = LEAPSelector(self.config)
        self.sizer = LEAPPositionSizer(self.config)

    # ------------------------------------------------------------------ #
    # Signal evaluation
    # ------------------------------------------------------------------ #

    def evaluate_signal_for_leaps(
        self,
        signal: StockSignal,
    ) -> Optional[Dict[str, Any]]:
        """
        Given a trading signal, decide whether a LEAP trade is appropriate
        and return a recommendation dict.

        Decision matrix:
            STRONG_BUY + high confidence  -> deep ITM LEAP call
            BUY        + moderate conf    -> slightly less deep ITM call
            STRONG_SELL                   -> LEAP put (or close existing calls)
            SELL                          -> close existing calls; optionally put
            HOLD                          -> no new positions, maintain existing

        Returns None when no LEAP action is warranted.
        """
        strength = signal.signal_strength
        confidence = signal.confidence

        # Check if we already hold a LEAP on this symbol
        existing = self._positions_for_symbol(signal.symbol)

        # ------ STRONG_BUY ------
        if strength == SignalStrength.STRONG_BUY and confidence >= 0.50:
            if existing:
                return {
                    "action": "HOLD_EXISTING",
                    "symbol": signal.symbol,
                    "reason": "Already holding LEAP; STRONG_BUY confirms position.",
                    "existing_positions": [p.to_dict() for p in existing],
                }
            return {
                "action": "OPEN_CALL_LEAP",
                "symbol": signal.symbol,
                "option_type": "call",
                "target_delta": self.selector._adjusted_delta(strength, OptionType.CALL),
                "target_dte": self.config.target_dte,
                "confidence": confidence,
                "reason": "STRONG_BUY with high confidence warrants deep ITM LEAP call.",
            }

        # ------ BUY ------
        if strength == SignalStrength.BUY and confidence >= 0.40:
            if existing:
                return {
                    "action": "HOLD_EXISTING",
                    "symbol": signal.symbol,
                    "reason": "Already holding LEAP; BUY signal supports position.",
                    "existing_positions": [p.to_dict() for p in existing],
                }
            return {
                "action": "OPEN_CALL_LEAP",
                "symbol": signal.symbol,
                "option_type": "call",
                "target_delta": self.selector._adjusted_delta(strength, OptionType.CALL),
                "target_dte": self.config.target_dte,
                "confidence": confidence,
                "reason": "BUY with moderate confidence; slightly ITM LEAP call.",
            }

        # ------ STRONG_SELL ------
        if strength == SignalStrength.STRONG_SELL:
            result: Dict[str, Any] = {
                "action": "OPEN_PUT_LEAP",
                "symbol": signal.symbol,
                "option_type": "put",
                "target_delta": self.selector._adjusted_delta(strength, OptionType.PUT),
                "target_dte": self.config.target_dte,
                "confidence": confidence,
                "reason": "STRONG_SELL signal warrants deep ITM LEAP put.",
            }
            if existing:
                call_positions = [
                    p for p in existing
                    if p.contract.option_type == OptionType.CALL
                ]
                if call_positions:
                    result["action"] = "CLOSE_CALLS_AND_OPEN_PUT"
                    result["close_positions"] = [p.to_dict() for p in call_positions]
                    result["reason"] += " Closing existing call LEAPs."
            return result

        # ------ SELL ------
        if strength == SignalStrength.SELL:
            if existing:
                call_positions = [
                    p for p in existing
                    if p.contract.option_type == OptionType.CALL
                ]
                if call_positions:
                    return {
                        "action": "CLOSE_CALLS",
                        "symbol": signal.symbol,
                        "close_positions": [p.to_dict() for p in call_positions],
                        "reason": "SELL signal; closing existing call LEAPs to reduce exposure.",
                    }
            # No existing position and only a moderate sell -- skip
            return None

        # ------ HOLD ------
        if strength == SignalStrength.HOLD:
            if existing:
                return {
                    "action": "HOLD_EXISTING",
                    "symbol": signal.symbol,
                    "reason": "HOLD signal; maintaining existing LEAP positions.",
                    "existing_positions": [p.to_dict() for p in existing],
                }
            # No position, no action
            return None

        return None

    # ------------------------------------------------------------------ #
    # Rolling management
    # ------------------------------------------------------------------ #

    def check_roll_needed(self, position: LEAPPosition) -> bool:
        """
        Determine whether a position should be rolled.

        Roll triggers:
        1. DTE < roll_dte_threshold (approaching expiry, theta accelerates)
        2. Position hit stop-loss or take-profit
        """
        dte = position.contract.days_to_expiry()
        if dte < self.config.roll_dte_threshold:
            logger.info(
                "Roll needed for %s: DTE=%d < threshold=%d",
                position.contract.id, dte, self.config.roll_dte_threshold,
            )
            return True

        # Check stop-loss / take-profit
        ret = position.return_pct
        if ret <= -self.config.stop_loss_pct:
            logger.info(
                "Roll/close needed for %s: return %.1f%% hit stop-loss (%.1f%%)",
                position.contract.id, ret * 100, -self.config.stop_loss_pct * 100,
            )
            return True
        if ret >= self.config.take_profit_pct:
            logger.info(
                "Roll/close needed for %s: return %.1f%% hit take-profit (%.1f%%)",
                position.contract.id, ret * 100, self.config.take_profit_pct * 100,
            )
            return True

        return False

    def calculate_roll(
        self,
        old_contract: OptionContract,
        new_expiry: date,
    ) -> Dict[str, Any]:
        """
        Calculate the cost and impact of rolling a LEAP position to a new expiry.

        A "roll" means closing the current contract and opening a new one
        at the same (or adjusted) strike with a later expiration.

        Returns dict with:
            old_contract    - summary of the contract being closed
            new_contract    - the replacement contract (fully priced)
            roll_debit      - net cost to roll (new premium - old premium)
            new_greeks      - Greeks of the replacement contract
            pnl_impact      - realised P&L from closing the old contract
        """
        T_new = max(0, (new_expiry - date.today()).days / 365.0)
        r = self.config.risk_free_rate
        sigma = old_contract.implied_volatility
        S = old_contract.underlying_price
        K = old_contract.strike
        opt_type = old_contract.option_type

        new_premium = BlackScholes.price(S, K, T_new, r, sigma, opt_type)
        new_greeks = BlackScholes.greeks(S, K, T_new, r, sigma, opt_type)

        roll_debit = new_premium - old_contract.premium
        pnl_impact = 0.0  # P&L would depend on entry price; caller can compute

        new_contract_id = (
            f"LEAP_{old_contract.symbol}_{opt_type.value}_{K:.0f}"
            f"_{new_expiry.strftime('%Y%m%d')}_{uuid.uuid4().hex[:6]}"
        )

        new_contract = OptionContract(
            id=new_contract_id,
            symbol=old_contract.symbol,
            option_type=opt_type,
            strike=K,
            expiration=new_expiry,
            style=OptionStyle.AMERICAN,
            underlying_price=S,
            premium=new_premium,
            bid=new_premium * 0.98,
            ask=new_premium * 1.02,
            last_price=new_premium,
            implied_volatility=sigma,
            greeks=new_greeks,
        )

        return {
            "old_contract": old_contract.to_dict(),
            "new_contract": new_contract.to_dict(),
            "roll_debit": round(_safe_float(roll_debit), 2),
            "new_greeks": new_greeks.to_dict(),
            "pnl_impact": round(_safe_float(pnl_impact), 2),
        }

    # ------------------------------------------------------------------ #
    # Position management helpers
    # ------------------------------------------------------------------ #

    def add_position(self, position: LEAPPosition) -> None:
        """Add a new LEAP position to the portfolio."""
        self.positions[position.contract.id] = position
        logger.info(
            "Added LEAP position: %s (%d contracts, premium=%.2f)",
            position.contract.id, position.contracts, position.entry_premium,
        )

    def close_position(self, contract_id: str) -> Optional[LEAPPosition]:
        """Remove and return a LEAP position from the portfolio."""
        position = self.positions.pop(contract_id, None)
        if position:
            logger.info(
                "Closed LEAP position: %s (P&L=%.2f, return=%.1f%%)",
                contract_id, position.unrealized_pnl, position.return_pct * 100,
            )
        return position

    # ------------------------------------------------------------------ #
    # Portfolio-level analytics
    # ------------------------------------------------------------------ #

    def get_portfolio_greeks(self) -> Dict[str, float]:
        """
        Aggregate Greeks across all LEAP positions.

        Each contract controls 100 shares, so multiply per-share Greeks
        by (contracts * 100).
        """
        total = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "rho": 0.0}

        for pos in self.positions.values():
            g = pos.contract.greeks
            if g is None:
                continue
            multiplier = pos.contracts * 100
            total["delta"] += g.delta * multiplier
            total["gamma"] += g.gamma * multiplier
            total["theta"] += g.theta * multiplier
            total["vega"] += g.vega * multiplier
            total["rho"] += g.rho * multiplier

        return {k: round(_safe_float(v), 4) for k, v in total.items()}

    def get_portfolio_summary(self) -> Dict[str, Any]:
        """
        Comprehensive summary of the LEAP portfolio.

        Includes:
            total_premium_invested  - sum of entry premiums * contracts * 100
            current_market_value    - sum of current premiums * contracts * 100
            unrealized_pnl          - aggregate unrealised P&L
            total_delta_exposure    - equivalent share exposure
            daily_theta_decay       - aggregate theta per day (in dollars)
            positions               - per-position summaries
            portfolio_greeks        - aggregate Greeks
            positions_needing_roll  - list of positions that should be rolled
        """
        total_invested = 0.0
        total_current = 0.0
        total_pnl = 0.0
        total_delta = 0.0
        total_theta = 0.0
        needs_roll: List[str] = []

        position_summaries: List[Dict[str, Any]] = []

        for cid, pos in self.positions.items():
            pos.update(pos.current_premium)  # refresh days_held / pnl
            total_invested += pos.total_cost
            total_current += pos.current_value
            total_pnl += pos.unrealized_pnl
            total_delta += pos.delta_exposure

            if pos.contract.greeks:
                total_theta += pos.contract.greeks.theta * pos.contracts * 100

            if self.check_roll_needed(pos):
                needs_roll.append(cid)

            position_summaries.append(pos.to_dict())

        return {
            "total_positions": len(self.positions),
            "total_premium_invested": round(_safe_float(total_invested), 2),
            "current_market_value": round(_safe_float(total_current), 2),
            "unrealized_pnl": round(_safe_float(total_pnl), 2),
            "return_pct": round(
                _safe_float(total_pnl / total_invested if total_invested > 0 else 0.0), 4
            ),
            "total_delta_exposure": round(_safe_float(total_delta), 2),
            "daily_theta_decay": round(_safe_float(total_theta), 2),
            "portfolio_greeks": self.get_portfolio_greeks(),
            "positions": position_summaries,
            "positions_needing_roll": needs_roll,
        }

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _positions_for_symbol(self, symbol: str) -> List[LEAPPosition]:
        """Return all active LEAP positions for *symbol*."""
        return [
            p for p in self.positions.values()
            if p.contract.symbol == symbol
        ]


# ---------------------------------------------------------------------------
# Module-level singleton accessors
# ---------------------------------------------------------------------------

_leap_manager: Optional[LEAPPortfolioManager] = None


def get_leap_manager(config: Optional[LEAPConfig] = None) -> LEAPPortfolioManager:
    """Get or create the singleton LEAPPortfolioManager."""
    global _leap_manager
    if _leap_manager is None:
        _leap_manager = LEAPPortfolioManager(config)
    return _leap_manager
