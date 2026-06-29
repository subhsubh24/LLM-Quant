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
