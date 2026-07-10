"""
Regression: baseline security headers are present, and /health does not disclose
deployment posture to unauthenticated callers.

- Every response must carry the non-breaking security headers (nosniff, frame-deny,
  referrer-policy, HSTS) — defense-in-depth for the monitoring surface.
- /health must be liveness-only: it must NOT expose `live_trading_enabled` (previously
  it did, letting anyone probe whether the host is armed for real money).

This imports the api package, which needs fastapi. Rather than sit OUTSIDE the curated
CI list (where a header/hygiene regression would be invisible to the required gate — the
prior state flagged by QUALITY_SCORECARD), each test guards on `pytest.importorskip`
(the established pattern in `test_backend_auth_fastapi.py`): it SKIPS cleanly where the
lightweight gate omits fastapi, and RUNS wherever fastapi is installed (local + the full
CI gate). It is now registered in `scripts/preflight.sh` so #265's hardening is exercised
by the gate whenever fastapi is present, instead of being registered nowhere.
"""

import pytest


def _client():
    """Build a TestClient, skipping the test if fastapi is absent (the light gate)."""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from app.api.main import app

    return TestClient(app)


def test_security_headers_present_on_health():
    client = _client()
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("X-Frame-Options") == "DENY"
    assert resp.headers.get("Referrer-Policy") == "no-referrer"
    assert "max-age=" in (resp.headers.get("Strict-Transport-Security") or "")


def test_security_headers_present_on_root():
    client = _client()
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("X-Frame-Options") == "DENY"


def test_health_does_not_leak_live_trading_state():
    client = _client()
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "healthy"
    # Liveness only — deployment posture must not be disclosed unauthenticated.
    assert "live_trading_enabled" not in body
