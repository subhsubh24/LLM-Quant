"""Regression for the 'real' self-validation tier: the forward paper-cycle runner's SAFETY
belt, and the live-integration smoke's honest failure classification.

These do NOT hit the network (that's the scheduled non-blocking job's job) — they lock the
invariants that must hold regardless: a paper cycle can never run with live trading on, and
the smoke only reports a CODE failure on a genuine code break (never on external unavailability).
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import run_paper_cycle as rpc  # noqa: E402
import live_integration_smoke as smoke  # noqa: E402


# --- paper-cycle safety belt ---

def test_paper_cycle_refuses_when_live_enabled():
    live = types.SimpleNamespace(live_trading_enabled=True)
    with pytest.raises(SystemExit):
        rpc.assert_paper_safe(live)


def test_paper_cycle_allows_paper_mode():
    paper = types.SimpleNamespace(live_trading_enabled=False)
    assert rpc.assert_paper_safe(paper) is None  # no raise


def test_empty_database_url_falls_back_to_sqlite():
    """An unset CI secret interpolates DATABASE_URL='' — the engine must fall back to the
    local SQLite default, never crash boot with a SQLAlchemy parse error (live-tier regression)."""
    from app.db.database import _make_engine
    for bad in ("", "   ", None):
        eng = _make_engine(bad)  # type: ignore[arg-type]
        assert eng.url.get_backend_name() == "sqlite"


# --- live smoke: honest exit classification ---

def test_smoke_fail_only_on_code_failure(monkeypatch):
    # a genuine code failure -> exit 1
    monkeypatch.setattr(smoke, "check_gemini", lambda: {"path": "gemini", "status": "fail", "detail": "boom"})
    monkeypatch.setattr(smoke, "check_polymarket", lambda: {"path": "polymarket", "status": "ok", "detail": "x"})
    assert smoke.main([]) == 1


def test_smoke_ok_on_external_unavailability(monkeypatch):
    # missing key + egress-blocked are NOT code failures -> exit 0 (non-blocking, just reported)
    monkeypatch.setattr(smoke, "check_gemini", lambda: {"path": "gemini", "status": "skipped", "detail": "no key"})
    monkeypatch.setattr(smoke, "check_polymarket", lambda: {"path": "polymarket", "status": "unavailable", "detail": "egress"})
    assert smoke.main([]) == 0


def test_smoke_ok_when_all_pass(monkeypatch):
    monkeypatch.setattr(smoke, "check_gemini", lambda: {"path": "gemini", "status": "ok", "detail": "x"})
    monkeypatch.setattr(smoke, "check_polymarket", lambda: {"path": "polymarket", "status": "ok", "detail": "y"})
    assert smoke.main([]) == 0


def test_smoke_gemini_skips_without_key(monkeypatch):
    """No key -> degrade-safe skip, never a fabricated 'ok' and never a code fail."""
    fake_cfg = types.ModuleType("app.config")
    fake_cfg.get_settings = lambda: types.SimpleNamespace(has_llm_key=False)
    monkeypatch.setattr(smoke, "_imp", lambda a, b: fake_cfg)
    r = smoke.check_gemini()
    assert r["status"] == "skipped"
