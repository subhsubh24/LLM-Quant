"""Regression: a TEST-ONLY rate-limit bypass must never be active with real money on.

The CI functional gate may set E2E_DISABLE_RATE_LIMIT=1. This guards that the flag can
NEVER coexist with LIVE_TRADING_ENABLED=true — if it does, the app refuses to boot.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_bypass_with_live_trading_refuses_to_boot():
    """E2E_DISABLE_RATE_LIMIT + LIVE_TRADING_ENABLED → hard boot refusal."""
    with pytest.raises(ValidationError):
        Settings(e2e_disable_rate_limit=True, live_trading_enabled=True)


def test_bypass_in_paper_mode_is_allowed():
    """Bypass is fine when NOT live (paper default) — the CI gate runs paper-only."""
    s = Settings(e2e_disable_rate_limit=True, live_trading_enabled=False)
    assert s.e2e_disable_rate_limit is True
    assert s.live_trading_enabled is False


def test_live_without_bypass_but_with_control_token_is_allowed():
    """Live mode with the bypass OFF + a control token set boots normally."""
    s = Settings(
        e2e_disable_rate_limit=False,
        live_trading_enabled=True,
        backend_api_token="a-strong-secret",
    )
    assert s.live_trading_enabled is True
    assert s.backend_api_token == "a-strong-secret"


def test_live_without_control_token_refuses_to_boot():
    """Real money on the line + an UNAUTHENTICATED control surface → hard boot refusal.

    LIVE_TRADING_ENABLED=true with an empty BACKEND_API_TOKEN would leave the
    kill-switch / execute / bot-control routes open on a real-money deploy.
    """
    with pytest.raises(ValidationError):
        Settings(live_trading_enabled=True, backend_api_token="")


def test_live_with_whitespace_only_token_refuses_to_boot():
    """A blank/whitespace token is not a credential — still refuses in live mode."""
    with pytest.raises(ValidationError):
        Settings(live_trading_enabled=True, backend_api_token="   ")


def test_live_with_auth_disabled_refuses_to_boot():
    """The dev opt-out must NEVER be honoured with real money.

    BACKEND_AUTH_DISABLED=1 runs the control routes OPEN (dev/paper only). Combined with
    LIVE_TRADING_ENABLED it would leave the kill-switch / execute / bot-control routes
    unauthenticated on a real-money deploy, so config HARD-REFUSES to boot — even if a
    token is also present, the opt-out wins and is unsafe live.
    """
    with pytest.raises(ValidationError):
        Settings(live_trading_enabled=True, backend_auth_disabled=True)
    # ...even with a token set, the opt-out (which disables enforcement) is refused live.
    with pytest.raises(ValidationError):
        Settings(live_trading_enabled=True, backend_auth_disabled=True, backend_api_token="a-strong-secret")


def test_paper_mode_with_auth_disabled_is_allowed():
    """The dev opt-out is fine in paper/dev (live OFF) — runs the control routes open."""
    s = Settings(live_trading_enabled=False, backend_auth_disabled=True)
    assert s.live_trading_enabled is False
    assert s.backend_auth_disabled is True


def test_paper_mode_needs_no_control_token():
    """Paper/dev (live OFF, the default) boots fine with no token.

    The control routes are DEFAULT-CLOSED (deny) in this state unless BACKEND_AUTH_DISABLED
    is set; either way config boots — the auth policy is enforced per-request in auth.py.
    """
    s = Settings(live_trading_enabled=False, backend_api_token="")
    assert s.live_trading_enabled is False
    assert s.backend_api_token == ""


def test_default_is_safe():
    """Defaults: bypass off, live off."""
    s = Settings()
    assert s.e2e_disable_rate_limit is False
    assert s.live_trading_enabled is False
