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


def test_read_endpoint_limits_are_bounded(monkeypatch):
    # Read endpoints used to take an UNBOUNDED limit/offset → a single request could ask
    # for a million-row fetch + serialization (resource exhaustion). Validation now rejects
    # out-of-range values (422) BEFORE the handler runs, so no DB/work happens.
    client = _router_client()
    _set_token(monkeypatch, "")
    assert client.get("/prediction-markets/markets?limit=999999").status_code == 422
    assert client.get("/prediction-markets/markets?limit=0").status_code == 422
    assert client.get("/prediction-markets/markets?offset=-1").status_code == 422
    assert client.get("/prediction-markets/orders?limit=999999").status_code == 422
    assert client.get("/prediction-markets/price-history/tok?limit=999999").status_code == 422
    assert client.get("/prediction-markets/pnl-history?limit=999999").status_code == 422
    assert client.get("/prediction-markets/bot/activity?limit=999999").status_code == 422
    # happy path: an IN-BOUNDS value must NOT be rejected (guards against a too-tight bound).
    # The handler may 200/500 on egress, but validation must pass (never 422).
    assert client.get("/prediction-markets/markets?limit=1000&offset=0").status_code != 422
    assert client.get("/prediction-markets/orders?limit=1000").status_code != 422
    assert client.get("/prediction-markets/bot/activity?limit=1").status_code != 422


def test_quant_endpoint_floats_are_bounded(monkeypatch):
    # Quant endpoints expect constrained numerics (mid_price ∈ [0,1], hours > 0,
    # kelly ∈ (0,1], bankroll > 0). Out-of-range / non-finite inputs are rejected (422)
    # instead of crashing the model or poisoning Bayesian state.
    client = _router_client()
    _set_token(monkeypatch, "")
    base = "/prediction-markets/quant/avellaneda-stoikov?token_id=t"
    assert client.get(f"{base}&mid_price=1.5").status_code == 422
    assert client.get(f"{base}&mid_price=-0.1").status_code == 422
    assert client.get(f"{base}&mid_price=inf").status_code == 422
    assert client.get(f"{base}&mid_price=nan").status_code == 422
    assert client.get(f"{base}&mid_price=0.5&hours_to_resolution=0").status_code == 422
    mc = "/prediction-markets/quant/monte-carlo-kelly"
    assert client.get(f"{mc}?naive_kelly_fraction=2.0").status_code == 422
    assert client.get(f"{mc}?bankroll=-10").status_code == 422
    # the bayesian update is also auth-guarded; with token unset, bounds still apply
    assert client.post(
        "/prediction-markets/quant/bayesian/update?key=k&signal_mean=1.5"
    ).status_code == 422
    # happy path: in-bounds quant inputs are accepted by validation (never 422)
    assert client.get(f"{base}&mid_price=0.5&hours_to_resolution=24").status_code != 422
    assert client.get(f"{mc}?naive_kelly_fraction=0.05&bankroll=500").status_code != 422


def test_status_error_is_sanitized_no_raw_exception(monkeypatch):
    # The public /status endpoint must not leak a raw exception string (URL, internals,
    # stack) when a venue request fails — only the exception TYPE name is surfaced.
    import requests as _requests

    def _boom(*a, **k):
        raise RuntimeError("secret-internal-host:5432/db?token=leak")

    # the /status route does `import requests; requests.get(...)`, so patch requests.get
    monkeypatch.setattr(_requests, "get", _boom)
    client = _router_client()
    r = client.get("/prediction-markets/status")
    assert r.status_code == 200
    body = r.json()
    for venue in ("gamma_api", "clob_api"):
        err = body[venue]["error"]
        assert err == "RuntimeError"
        assert "secret-internal-host" not in str(err)


def test_place_order_request_bounds():
    # §12: /execute payload flows into the executor + sizing; bound it so a caller can't
    # inject size=inf / price=NaN / a multi-MB id. Validation happens at the model, before
    # the handler runs. (importorskip: routes.py imports fastapi at module load.)
    pytest.importorskip("fastapi")
    from pydantic import ValidationError
    from backend.app.api.routes import PlaceOrderRequest

    ok = PlaceOrderRequest(market_id="253591", token_id="t1", size=10.0, price=0.5)
    assert ok.size == 10.0 and ok.price == 0.5

    bad_payloads = [
        dict(market_id="m", token_id="t", size=float("inf")),
        dict(market_id="m", token_id="t", size=float("nan")),
        dict(market_id="m", token_id="t", size=0.0),          # must be > 0
        dict(market_id="m", token_id="t", size=-5.0),
        dict(market_id="m", token_id="t", size=2_000_000.0),  # > max
        dict(market_id="m", token_id="t", price=1.5),         # price must be in [0,1]
        dict(market_id="m", token_id="t", price=float("nan")),
        dict(market_id="", token_id="t"),                     # empty id
        dict(market_id="x" * 201, token_id="t"),              # id too long
        dict(token_id="t"),                                   # missing required market_id
    ]
    for bad in bad_payloads:
        with pytest.raises(ValidationError):
            PlaceOrderRequest(**bad)


def test_subscribe_request_bounds():
    # §12: an unbounded identifiers list = unbounded WS subscription fan-out.
    pytest.importorskip("fastapi")
    from pydantic import ValidationError
    from backend.app.api.routes import SubscribeRequest

    assert SubscribeRequest(identifiers=["a", "b"]).identifiers == ["a", "b"]
    assert SubscribeRequest().identifiers == []              # default is empty, mutable-safe
    with pytest.raises(ValidationError):
        SubscribeRequest(identifiers=["x"] * 1001)           # too many identifiers
    with pytest.raises(ValidationError):
        SubscribeRequest(identifiers=["y" * 201])            # a single identifier too long
