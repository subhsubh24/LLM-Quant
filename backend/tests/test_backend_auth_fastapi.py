"""
End-to-end FastAPI wiring check for the backend route auth (the adapter, not the decision).

INTENTIONALLY OUTSIDE the curated CI list (scripts/preflight.sh): it imports the api
package, which (a) needs fastapi — absent in the lightweight CI gate — and (b) triggers the
`app.*` vs `backend.app.*` dual-import table-registration path that collides if run after
`test_prediction_markets.py`. The CI gate validates the PURE decision in
`test_backend_auth.py`; this file proves the FastAPI adapter (Header extraction +
HTTPException 401) where fastapi is installed. Run it standalone:

    pytest backend/tests/test_backend_auth_fastapi.py
"""

import pytest


def test_fastapi_dependency_enforces_401(monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi import FastAPI, Depends
    from fastapi.testclient import TestClient
    from backend.app.api.auth import require_backend_token
    import backend.app.config as cfg

    app = FastAPI()

    @app.post("/mutate", dependencies=[Depends(require_backend_token)])
    def _mutate():
        return {"ok": True}

    client = TestClient(app)

    class _S:
        backend_api_token = ""

    # token unset -> open (degrades safely)
    monkeypatch.setattr(cfg, "get_settings", lambda: _S())
    assert client.post("/mutate").status_code == 200

    # token set -> enforced (exact Bearer required; 401 on any mismatch)
    _S.backend_api_token = "s3cret"
    assert client.post("/mutate").status_code == 401
    assert client.post("/mutate", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.post("/mutate", headers={"Authorization": "Bearer s3cret"}).status_code == 200


def _router_client():
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.app.api.routes import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _set_token(monkeypatch, token: str):
    import backend.app.config as cfg

    class _S:
        backend_api_token = token
    monkeypatch.setattr(cfg, "get_settings", lambda: _S())


def test_scan_route_requires_token_when_set(monkeypatch):
    # /prediction-markets/scan is state-mutating + expensive; it must be guarded like its
    # sibling /bot/scan-now. With a token set, a tokenless POST is 401 — the guard runs
    # BEFORE the scanner, so no network call happens.
    client = _router_client()
    _set_token(monkeypatch, "s3cret")
    assert client.post("/prediction-markets/scan").status_code == 401
    assert client.post(
        "/prediction-markets/scan", headers={"Authorization": "Bearer nope"}
    ).status_code == 401


def test_scan_market_limit_is_bounded(monkeypatch):
    # Token unset -> auth open; an out-of-range market_limit is rejected by validation
    # (422) before any work, so the endpoint can't be driven into a million-page fetch.
    client = _router_client()
    _set_token(monkeypatch, "")
    assert client.post("/prediction-markets/scan?market_limit=999999").status_code == 422
    assert client.post("/prediction-markets/scan?market_limit=0").status_code == 422


def test_risk_config_rejects_unsafe_bounds(monkeypatch):
    # THE safety case: a non-positive daily-loss cap would DISABLE loss protection. The
    # route must reject it (422) rather than silently writing it to the live risk config.
    client = _router_client()
    _set_token(monkeypatch, "")
    assert client.post(
        "/prediction-markets/risk/config", json={"daily_loss_limit_usd": -1}
    ).status_code == 422
    assert client.post(
        "/prediction-markets/risk/config", json={"max_portfolio_exposure_usd": 0}
    ).status_code == 422


def test_search_query_and_limit_bounded(monkeypatch):
    client = _router_client()
    _set_token(monkeypatch, "")
    assert client.post(
        "/prediction-markets/search", json={"query": "btc", "limit": 99999}
    ).status_code == 422
    assert client.post(
        "/prediction-markets/search", json={"query": "", "limit": 10}
    ).status_code == 422
