"""Regression: a TEST-ONLY rate-limit bypass must never be active with real money on.

The CI functional gate may set E2E_DISABLE_RATE_LIMIT=1. This guards that the flag can
NEVER coexist with LIVE_TRADING_ENABLED=true — if it does, the app refuses to boot.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.app.config import Settings


def test_bypass_with_live_trading_refuses_to_boot():
    """E2E_DISABLE_RATE_LIMIT + LIVE_TRADING_ENABLED → hard boot refusal."""
    with pytest.raises(ValidationError):
        Settings(e2e_disable_rate_limit=True, live_trading_enabled=True)


def test_bypass_in_paper_mode_is_allowed():
    """Bypass is fine when NOT live (paper default) — the CI gate runs paper-only."""
    s = Settings(e2e_disable_rate_limit=True, live_trading_enabled=False)
    assert s.e2e_disable_rate_limit is True
    assert s.live_trading_enabled is False


def test_live_without_bypass_is_allowed():
    """Live mode with the bypass OFF boots normally."""
    s = Settings(e2e_disable_rate_limit=False, live_trading_enabled=True)
    assert s.live_trading_enabled is True


def test_default_is_safe():
    """Defaults: bypass off, live off."""
    s = Settings()
    assert s.e2e_disable_rate_limit is False
    assert s.live_trading_enabled is False
