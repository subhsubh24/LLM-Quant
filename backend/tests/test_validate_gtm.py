"""Regression: the GTM honesty gate fails closed on a growth metric with no connected source,
and on a malformed GTM_SCORECARD (the GTM analog of the self-validation gate)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import validate_gtm as g  # noqa: E402


def test_committed_growth_status_is_green():
    """The real committed feed (pre-launch, all 0/null) must pass — else we'd red-block."""
    assert g.check() == [], "committed GROWTH_STATUS is not GTM-green"


def test_metric_without_source_fails_closed():
    gs = {"metrics": {"hit_rate": 0.62}, "venues_connected": []}  # reported, NO source
    errs = g.evaluate(gs, True, None, False)
    assert any("METRIC WITHOUT A SOURCE" in e for e in errs)


def test_metric_with_connected_venue_passes():
    gs = {"metrics": {"hit_rate": 0.62}, "venues_connected": ["polymarket_paper"]}
    assert g.evaluate(gs, True, None, False) == []


def test_metric_with_channels_connected_passes():
    gs = {"acquisition": {"signups": 5}, "channels_connected": True}
    assert g.evaluate(gs, True, None, False) == []


def test_target_and_zero_keys_are_not_reported():
    gs = {"metrics": {"weekly_pnl_target_usd": 2000, "total_trades": 0, "hit_rate": None},
          "venues_connected": []}
    assert g.evaluate(gs, True, None, False) == []   # targets/zeros/null are not "reported traction"


def test_funnel_acquisition_pmf_sections_policed():
    gs = {"funnel": {"visitors": 100}, "venues_connected": []}
    assert any("METRIC WITHOUT A SOURCE" in e for e in g.evaluate(gs, True, None, False))


def test_missing_growth_status_fails():
    assert any("missing" in e for e in g.evaluate(None, False, None, False))


def test_unparseable_growth_status_fails():
    assert any("no parseable" in e for e in g.evaluate(None, True, None, False))


def test_gtm_scorecard_invalid_grade_fails():
    sc = {"dimensions": {"messaging": "Z", "ship_gate_met": False}}
    assert any("invalid grade" in e for e in g.evaluate({}, True, sc, True))


def test_gtm_scorecard_valid_passes():
    sc = {"dimensions": {"messaging": "A", "icp": "B"}, "ship_gate_met": False}
    assert g.evaluate({}, True, sc, True) == []


def test_gtm_scorecard_missing_ship_gate_fails():
    sc = {"dimensions": {"messaging": "A"}}
    assert any("ship_gate_met" in e for e in g.evaluate({}, True, sc, True))
