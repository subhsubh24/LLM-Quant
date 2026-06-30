"""
risk_config_validation.py — pure, framework-free bounds validation for the
risk-manager config update (ROADMAP D2 / security).

WHY THIS EXISTS (and is pure):
The ``POST /prediction-markets/risk/config`` route lets a caller overwrite the live
risk-manager limits (daily-loss cap, portfolio exposure, per-position size, max open
positions, order rate). With NO bounds, a caller (compromised token, fat-finger, or a
misconfigured client) could set ``daily_loss_limit_usd = -1`` — which DISABLES the loss
cap (the ``check`` is ``realized_loss > limit``; a negative limit can never trip) — or
``max_portfolio_exposure_usd = 0`` to halt all trading. A risk-control surface that can
silently turn OFF the loss cap is a safety hole.

The DECISION lives here, fastapi-free, so the lightweight CI gate (which does NOT install
fastapi) can validate it directly — mirroring the ``auth_core`` pattern. The FastAPI route
is a thin adapter that calls ``validate_risk_config_update`` and raises 422 on any error.

All fields are OPTIONAL (a partial update only sets the provided ones); only a PROVIDED
value is validated. Bounds are deliberately generous upper limits — the point is to reject
nonsensical / dangerous values (non-positive, NaN/inf, absurd), not to second-guess a
sane owner. Raising a cap is still HUMAN-CORE; this only rejects values that are unsafe by
construction.
"""

from __future__ import annotations

import math
from typing import List, Optional

# Generous upper sanity bounds. These are not the owner's policy — they only reject
# values that are nonsensical for a personal prediction-markets bankroll.
_MAX_USD = 10_000_000.0          # $10M ceiling on any USD limit
_MAX_DAILY_LOSS_USD = 1_000_000.0  # $1M ceiling on the daily-loss cap specifically
_MAX_POSITIONS = 100_000
_MAX_ORDERS_PER_MINUTE = 100_000


def _check_positive_usd(
    errors: List[str], name: str, value: Optional[float], ceiling: float
) -> None:
    if value is None:
        return
    # bool is an int subclass — reject it explicitly so True/False can't pose as a number.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        errors.append(f"{name} must be a number")
        return
    if not math.isfinite(value):
        errors.append(f"{name} must be a finite number (got {value!r})")
        return
    if value <= 0:
        errors.append(f"{name} must be > 0 (got {value}); a non-positive limit disables the control")
        return
    if value > ceiling:
        errors.append(f"{name} must be <= {ceiling:g} (got {value})")


def _check_positive_int(
    errors: List[str], name: str, value: Optional[int], ceiling: int
) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int):
        errors.append(f"{name} must be an integer")
        return
    if value < 1:
        errors.append(f"{name} must be >= 1 (got {value})")
        return
    if value > ceiling:
        errors.append(f"{name} must be <= {ceiling} (got {value})")


def validate_risk_config_update(
    *,
    daily_loss_limit_usd: Optional[float] = None,
    max_portfolio_exposure_usd: Optional[float] = None,
    max_single_position_usd: Optional[float] = None,
    max_total_positions: Optional[int] = None,
    max_orders_per_minute: Optional[int] = None,
) -> List[str]:
    """Return a list of human-readable validation errors (empty list == valid).

    Pure: no I/O, no framework, deterministic — safe to unit-test in the CI gate. Only
    PROVIDED (non-None) fields are validated, so a partial update is accepted as long as
    each supplied value is safe.
    """
    errors: List[str] = []
    _check_positive_usd(errors, "daily_loss_limit_usd", daily_loss_limit_usd, _MAX_DAILY_LOSS_USD)
    _check_positive_usd(errors, "max_portfolio_exposure_usd", max_portfolio_exposure_usd, _MAX_USD)
    _check_positive_usd(errors, "max_single_position_usd", max_single_position_usd, _MAX_USD)
    _check_positive_int(errors, "max_total_positions", max_total_positions, _MAX_POSITIONS)
    _check_positive_int(errors, "max_orders_per_minute", max_orders_per_minute, _MAX_ORDERS_PER_MINUTE)
    return errors
