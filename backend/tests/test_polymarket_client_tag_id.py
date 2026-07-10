"""Regression: PolymarketClient.get_markets forwards the INTEGER ``tag_id`` server-side
filter, never a silently-ignored string ``tag`` (ROADMAP A7 dormant sibling bug).

Gamma's ``/markets`` endpoint SILENTLY IGNORES a string ``tag`` param (returns the
unfiltered global top — verified live 2026-07-10 in PR #285) and only filters when the
INTEGER ``tag_id`` is sent. The pre-fix ``get_markets(tag=...)`` set ``params["tag"]`` — a
silent no-op that would mislead any future caller into believing it filtered by category.
These tests pin the corrected contract: ``tag_id`` is forwarded as ``params["tag_id"]``,
``tag`` is never sent, and ``tag_id`` is omitted by default (back-compat) while a
legitimate ``tag_id`` of 0 is still honored (``is not None`` guard, not truthiness).

Fully offline — the client's HTTP layer is stubbed to capture the request params.
"""
from __future__ import annotations

from backend.app.prediction_markets.polymarket_client import PolymarketClient


class _CaptureClient(PolymarketClient):
    """Captures the params of the last Gamma ``/markets`` request; returns no rows."""

    def __init__(self):  # noqa: D107 - test double, skip PolymarketClient.__init__ network setup
        self.captured_params = None

    def _get(self, url, params=None):  # type: ignore[override]
        self.captured_params = dict(params or {})
        return []  # empty market list — we only assert the outbound params


def _params_for(**kwargs):
    c = _CaptureClient()
    c.get_markets(**kwargs)
    return c.captured_params


def test_tag_id_forwarded_as_integer_tag_id_param():
    params = _params_for(tag_id=100639)
    assert params.get("tag_id") == 100639, "integer tag_id must be forwarded server-side"
    assert "tag" not in params, "the silently-ignored string `tag` must never be sent"


def test_tag_id_zero_is_honored_not_dropped():
    # `is not None` guard (not truthiness): a legitimate tag_id of 0 must still filter.
    params = _params_for(tag_id=0)
    assert params.get("tag_id") == 0
    assert "tag" not in params


def test_tag_id_omitted_by_default_backcompat():
    params = _params_for()
    assert "tag_id" not in params, "default None omits the key (back-compat, unfiltered)"
    assert "tag" not in params


def test_string_tag_id_is_coerced_to_int():
    # Defensive: a str id (e.g. from a CLI arg) is coerced so `params["tag_id"]` is a real int.
    params = _params_for(tag_id="100639")  # type: ignore[arg-type]
    assert params.get("tag_id") == 100639
    assert isinstance(params["tag_id"], int)


def test_no_string_tag_keyword_accepted():
    # The misleading string `tag` keyword was removed — passing it must be a TypeError,
    # not a silent no-op (fail loud beats a false-filter).
    import pytest

    with pytest.raises(TypeError):
        _params_for(tag="Sports")  # type: ignore[call-arg]
