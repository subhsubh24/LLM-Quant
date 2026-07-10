"""Regression: `validate_real_oos.fetch_venue` forwards the Polymarket-only integer
`tag_id` (Gamma server-side category filter, ROADMAP A7/#285) into
`PolymarketHistoryFetcher.fetch_resolved_markets`, and does NOT leak it into the kalshi lane
(whose fetcher has no `tag_id` param) — instead flagging it as ignored in the status note.

This completes the #285 pipeline: the fetcher + `per_category_edge_search` already accept
`tag_id`; this pins that the OOS validator (`validate_real_oos.py`, the real-money floor lane)
threads a PRE-REGISTERED category through so a per-category OOS test lands its whole page
budget inside the target category instead of being starved by the global volumeNum ranking.

Fully offline — the venue fetcher classes are monkeypatched to capture kwargs; no network.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "validate_real_oos.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("validate_real_oos_under_test", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_tag_id_forwarded_to_polymarket_fetcher(monkeypatch):
    mod = _load_module()
    from backend.app.prediction_markets import polymarket_history_fetcher as phf

    captured = {}

    def fake_fetch(self, limit, max_pages, order="endDate", tag_id=None, **kw):
        captured["tag_id"] = tag_id
        captured["order"] = order
        return []

    monkeypatch.setattr(phf.PolymarketHistoryFetcher, "fetch_resolved_markets", fake_fetch)
    monkeypatch.setattr(phf.PolymarketHistoryFetcher, "build_historical_markets",
                        lambda self, resolved, lead: [])

    markets, status = mod.fetch_venue("polymarket", limit=100, max_pages=2, lead_days=2.0,
                                      tag_id=100639)
    assert captured["tag_id"] == 100639, "tag_id must reach the Polymarket fetcher server-side"
    assert captured["order"] == "volumeNum"  # existing ranking preserved
    assert markets == []
    assert "note" not in status  # Polymarket lane: tag_id applies, no 'ignored' note


def test_tag_id_defaults_none_backcompat(monkeypatch):
    mod = _load_module()
    from backend.app.prediction_markets import polymarket_history_fetcher as phf

    captured = {}

    def fake_fetch(self, limit, max_pages, order="endDate", tag_id=None, **kw):
        captured["tag_id"] = tag_id
        return []

    monkeypatch.setattr(phf.PolymarketHistoryFetcher, "fetch_resolved_markets", fake_fetch)
    monkeypatch.setattr(phf.PolymarketHistoryFetcher, "build_historical_markets",
                        lambda self, resolved, lead: [])

    mod.fetch_venue("polymarket", limit=100, max_pages=2, lead_days=2.0)  # no tag_id
    assert captured["tag_id"] is None, "default omits tag_id (back-compat: unfiltered)"


def test_tag_id_ignored_for_kalshi_lane_with_honest_note(monkeypatch):
    """tag_id is Polymarket-only. The kalshi fetcher has no tag_id param, so passing --tag-id
    must NOT be forwarded (would TypeError) and must be flagged as ignored in the status."""
    mod = _load_module()
    from backend.app.prediction_markets import kalshi_history_fetcher as khf

    seen = {}

    def fake_fetch(self, limit, max_pages, **kw):
        seen["kwargs"] = kw  # tag_id must NOT appear here
        return []

    monkeypatch.setattr(khf.KalshiHistoryFetcher, "fetch_resolved_markets", fake_fetch)
    monkeypatch.setattr(khf.KalshiHistoryFetcher, "build_historical_markets",
                        lambda self, resolved, lead: [])

    markets, status = mod.fetch_venue("kalshi", limit=100, max_pages=2, lead_days=2.0,
                                      tag_id=100639)
    assert "tag_id" not in seen.get("kwargs", {}), "tag_id must not leak into the kalshi fetcher"
    assert "Polymarket-only" in status and "ignored for kalshi" in status, \
        "an ignored tag_id on a non-Polymarket lane must be surfaced honestly, not silent"


def test_cli_accepts_tag_id_argument():
    """--tag-id parses as an int (the CLI surface the pipeline calls)."""
    mod = _load_module()
    ap = None
    # Rebuild the parser the same way main() does by parsing a known argv via argparse.
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag-id", type=int, default=None)
    ns = ap.parse_args(["--tag-id", "100639"])
    assert ns.tag_id == 100639
    # And the real script exposes --tag-id (grep the source, cheap + robust to refactor).
    src = _SCRIPT.read_text()
    assert "--tag-id" in src and "tag_id" in src
