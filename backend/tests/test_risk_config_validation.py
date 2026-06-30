"""
Tests for the pure risk-config bounds validator (ROADMAP D2 / security).

These run in the CI-light gate (no fastapi needed): the validation DECISION is
framework-free in ``risk_config_validation.py``; the FastAPI route is a thin adapter
that calls it and raises 422 on any error. The headline safety property: a non-positive
``daily_loss_limit_usd`` (which would DISABLE the loss cap) is rejected.
"""

import math

from backend.app.prediction_markets.risk_config_validation import (
    validate_risk_config_update,
)


def test_empty_update_is_valid():
    assert validate_risk_config_update() == []


def test_all_sane_values_valid():
    assert validate_risk_config_update(
        daily_loss_limit_usd=500.0,
        max_portfolio_exposure_usd=2000.0,
        max_single_position_usd=50.0,
        max_total_positions=20,
        max_orders_per_minute=10,
    ) == []


def test_negative_daily_loss_limit_rejected():
    # THE safety case: a negative cap would never trip (check is realized_loss > limit),
    # silently disabling loss protection.
    errs = validate_risk_config_update(daily_loss_limit_usd=-1.0)
    assert errs
    assert any("daily_loss_limit_usd" in e for e in errs)


def test_zero_values_rejected():
    for field, kwargs in [
        ("daily_loss_limit_usd", {"daily_loss_limit_usd": 0.0}),
        ("max_portfolio_exposure_usd", {"max_portfolio_exposure_usd": 0.0}),
        ("max_single_position_usd", {"max_single_position_usd": 0.0}),
    ]:
        errs = validate_risk_config_update(**kwargs)
        assert any(field in e for e in errs), (field, errs)


def test_nan_and_inf_rejected():
    assert validate_risk_config_update(daily_loss_limit_usd=float("nan"))
    assert validate_risk_config_update(max_portfolio_exposure_usd=float("inf"))
    assert validate_risk_config_update(max_single_position_usd=-math.inf)


def test_absurdly_large_values_rejected():
    assert validate_risk_config_update(daily_loss_limit_usd=1e12)
    assert validate_risk_config_update(max_portfolio_exposure_usd=1e15)


def test_int_fields_must_be_positive_ints():
    assert validate_risk_config_update(max_total_positions=0)
    assert validate_risk_config_update(max_total_positions=-5)
    assert validate_risk_config_update(max_orders_per_minute=0)
    # Sane positive ints pass.
    assert validate_risk_config_update(max_total_positions=10, max_orders_per_minute=5) == []


def test_bool_is_not_accepted_as_number():
    # bool is an int subclass; True/False must not pose as a valid limit.
    assert validate_risk_config_update(daily_loss_limit_usd=True)
    assert validate_risk_config_update(max_total_positions=True)


def test_partial_update_only_validates_provided_fields():
    # Providing one good field and omitting the rest is valid (a partial update).
    assert validate_risk_config_update(max_orders_per_minute=30) == []
    # One bad + one good -> only the bad one errors.
    errs = validate_risk_config_update(max_orders_per_minute=30, daily_loss_limit_usd=-1.0)
    assert len(errs) == 1
    assert "daily_loss_limit_usd" in errs[0]
