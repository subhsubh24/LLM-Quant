"""
Regression: baseline security headers are present, and /health does not disclose
deployment posture to unauthenticated callers.

- Every response must carry the non-breaking security headers (nosniff, frame-deny,
  referrer-policy, HSTS) — defense-in-depth for the monitoring surface.
- /health must be liveness-only: it must NOT expose `live_trading_enabled` (previously
  it did, letting anyone probe whether the host is armed for real money).

This imports the api package, which needs fastapi. To give #265 REAL blocking-gate
coverage (the prior state, flagged by QUALITY_SCORECARD, was "registered nowhere → a
header/hygiene regression is invisible to required CI"), two things change together:
(1) fastapi + httpx are added to `backend/requirements-ci.txt`, so the required
`preflight.sh code` gate now INSTALLS them and this test actually RUNS there — it is no
longer skipped in every CI job; and (2) it is registered in `scripts/preflight.sh`'s
curated list. The `pytest.importorskip("fastapi")` guard (the `test_backend_auth_fastapi.py`
pattern) remains defence-in-depth: in an environment that genuinely lacks fastapi the test
SKIPS cleanly instead of erroring collection — but in CI, where fastapi is now installed,
it runs and asserts the headers for real.
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
