"""Regression: a TEST-ONLY rate-limit bypass must never be active with real money on.

The CI functional gate may set E2E_DISABLE_RATE_LIMIT=1. This guards that the flag can
NEVER coexist with LIVE_TRADING_ENABLED=true — if it does, the app refuses to boot.
"""

from __future__ import annotations

import logging

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


_VENUE_CREDS = {
    "POLYMARKET_API_KEY": "k",
    "POLYMARKET_API_SECRET": "s",
    "POLYMARKET_PASSPHRASE": "p",
    "POLYMARKET_PRIVATE_KEY": "0x" + "a" * 64,
}


def test_live_without_bypass_but_with_control_token_is_allowed(monkeypatch):
    """A FULLY-provisioned live host (bypass OFF + control token + venue creds) boots."""
    for k, v in _VENUE_CREDS.items():
        monkeypatch.setenv(k, v)
    s = Settings(
        e2e_disable_rate_limit=False,
        live_trading_enabled=True,
        backend_api_token="a-strong-secret",
    )
    assert s.live_trading_enabled is True
    assert s.backend_api_token == "a-strong-secret"


def test_live_without_venue_credentials_refuses_to_boot(monkeypatch):
    """Real money on the line + missing Polymarket order credentials → hard boot refusal.

    A live-enabled host without the venue creds would boot but fail EVERY real order at
    runtime (the executor is not authenticated). FAIL LOUD at boot instead (§28). The
    control token is set here so this isolates the NEW venue-credential gate.
    """
    for k in _VENUE_CREDS:
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(ValidationError):
        Settings(live_trading_enabled=True, backend_api_token="a-strong-secret")


def test_live_with_partial_venue_credentials_refuses_to_boot(monkeypatch):
    """Even ONE missing venue credential (private key) refuses to boot — all four required."""
    for k, v in _VENUE_CREDS.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("POLYMARKET_PRIVATE_KEY", raising=False)
    with pytest.raises(ValidationError):
        Settings(live_trading_enabled=True, backend_api_token="a-strong-secret")


def test_paper_mode_needs_no_venue_credentials(monkeypatch):
    """Paper (default) must NEVER require venue creds — the loop runs paper with none set."""
    for k in _VENUE_CREDS:
        monkeypatch.delenv(k, raising=False)
    s = Settings(live_trading_enabled=False, backend_api_token="")
    assert s.live_trading_enabled is False


# --- POLYMARKET_FUNDER live-boot advisory (fail-loud-not-late, §28) ---
# FUNDER is NOT a hard boot requirement (funder=None is a valid EOA setup), so an unset
# FUNDER must NOT refuse boot — but for the standard Polymarket proxy-wallet setup it
# silently routes every order to the empty signer address, so warn LOUD at boot.

def test_live_without_funder_boots_but_warns_loud(monkeypatch, caplog):
    """4 creds present + FUNDER unset → boots (no refusal) AND emits a loud FUNDER warning."""
    for k, v in _VENUE_CREDS.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("POLYMARKET_FUNDER", raising=False)
    with caplog.at_level(logging.WARNING, logger="app.config"):
        s = Settings(live_trading_enabled=True, backend_api_token="a-strong-secret")
    assert s.live_trading_enabled is True  # NOT over-blocked (EOA config is valid)
    assert any("POLYMARKET_FUNDER" in r.message and r.levelno >= logging.WARNING
               for r in caplog.records), "missing FUNDER must warn loud at live boot"


def test_live_with_funder_set_does_not_warn(monkeypatch, caplog):
    """FUNDER present → no FUNDER warning (the advisory is targeted, not noise)."""
    for k, v in _VENUE_CREDS.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("POLYMARKET_FUNDER", "0x" + "b" * 40)
    with caplog.at_level(logging.WARNING, logger="app.config"):
        Settings(live_trading_enabled=True, backend_api_token="a-strong-secret")
    assert not any("POLYMARKET_FUNDER" in r.message for r in caplog.records)


def test_paper_mode_never_warns_about_funder(monkeypatch, caplog):
    """Paper (default) must never emit the live-only FUNDER advisory."""
    for k in _VENUE_CREDS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.delenv("POLYMARKET_FUNDER", raising=False)
    with caplog.at_level(logging.WARNING, logger="app.config"):
        Settings(live_trading_enabled=False, backend_api_token="")
    assert not any("POLYMARKET_FUNDER" in r.message for r in caplog.records)


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


def test_get_settings_boot_error_does_not_leak_secrets(monkeypatch):
    """A boot-time config error must FAIL LOUD without printing any secret VALUE.

    pydantic's native ValidationError repr embeds ``input_value={...}`` — the raw env dict,
    which carries SECRET values (BACKEND_API_TOKEN, GEMINI_API_KEY, venue keys). That error
    is logged by the ASGI server at startup, so unmodified it leaks secrets into the process
    logs. get_settings() re-raises with the messages ONLY. This asserts the real boot path
    (get_settings) neither prints a secret nor exposes the leaky input dict, while still
    failing loud (§12/§13/§28).
    """
    import app.config as cfg

    secret_token = "tok_SUPER_SECRET_DO_NOT_LOG_9zX"
    secret_llm = "sk_live_LLMKEY_DO_NOT_LOG_7qP"
    for k in _VENUE_CREDS:  # missing venue creds → the live validator raises
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "true")
    monkeypatch.setenv("BACKEND_API_TOKEN", secret_token)
    monkeypatch.setenv("GEMINI_API_KEY", secret_llm)
    cfg.get_settings.cache_clear()
    try:
        with pytest.raises(ValueError) as ei:  # sanitized ValueError, NOT the native ValidationError
            cfg.get_settings()
    finally:
        cfg.get_settings.cache_clear()

    text = f"{ei.value}\n{repr(ei.value)}"
    assert secret_token not in text, "BACKEND_API_TOKEN leaked into the boot error"
    assert secret_llm not in text, "GEMINI_API_KEY leaked into the boot error"
    assert "input_value" not in text, "the leaky pydantic input dict reached the error"
    # Still fails LOUD + names the missing credential so the owner can act.
    assert "refusing to boot" in text.lower()
    assert "POLYMARKET_API_KEY" in text


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
