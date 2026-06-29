"""
Tests for the backend shared-secret bearer auth (security top_gap).

Validates the PURE authorization decision (auth_core) — fastapi-free so it runs in the
lightweight CI gate. Proves the EFFECT, not a message:

  * token UNSET  -> every request allowed (degrades safely; unchanged paper/dev behaviour);
  * token SET    -> only an exact `Authorization: Bearer <token>` is allowed; missing /
                    wrong / wrong-scheme / empty is denied;
  * comparison is value-based and constant-time (hmac.compare_digest).

Deterministic, no network, no fastapi.
"""

import pytest

import backend.app.auth_core as auth_core


def test_unset_token_allows_everything():
    assert auth_core.is_request_authorized("", None) is True
    assert auth_core.is_request_authorized("", "anything") is True
    assert auth_core.is_request_authorized("", "Bearer whatever") is True


def test_set_token_requires_exact_bearer():
    assert auth_core.is_request_authorized("s3cret", "Bearer s3cret") is True


@pytest.mark.parametrize("header", [
    None,                  # missing
    "",                    # empty
    "s3cret",              # no scheme
    "Bearer wrong",        # wrong token
    "Bearer ",             # empty token
    "Basic s3cret",        # wrong scheme
    "bearer s3cret",       # case-sensitive scheme
    "Bearer s3cret ",      # trailing space
])
def test_set_token_denies_mismatches(header):
    assert auth_core.is_request_authorized("s3cret", header) is False


def test_configured_token_reads_settings(monkeypatch):
    class _S:
        backend_api_token = "from-settings"

    # configured_token imports get_settings lazily from backend.app.config; patch there.
    import backend.app.config as cfg
    monkeypatch.setattr(cfg, "get_settings", lambda: _S())
    assert auth_core.configured_token() == "from-settings"


def test_configured_token_degrades_on_settings_error(monkeypatch):
    import backend.app.config as cfg

    def _boom():
        raise RuntimeError("no settings")

    monkeypatch.setattr(cfg, "get_settings", _boom)
    # Must not raise; treats as unset (open) — same as the documented default.
    assert auth_core.configured_token() == ""

    # NOTE: the end-to-end FastAPI 401 wiring (Header extraction + HTTPException) is
    # verified in test_backend_auth_fastapi.py, which is intentionally OUTSIDE the curated
    # CI list: it imports the api package (→ fastapi, absent in the lightweight CI gate)
    # and triggers the dual-import table-registration path, so it must not run alongside
    # the curated suite. This file stays pure (fastapi-free) and CI-safe.
