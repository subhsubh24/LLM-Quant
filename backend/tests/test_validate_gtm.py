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


# --- F9.1: a malformed GROWTH_STATUS block must produce a PRECISE diagnostic, not the
# generic "no parseable block" that masked an unquoted-colon-space scalar stall for ~24h. ---

# The exact recurring failure (Run 21): an unquoted `as_of` free-text scalar carrying a `: `.
_MALFORMED_STATUS = (
    "```yaml\n"
    "GROWTH_STATUS:\n"
    "  as_of: 2026-07-13 Run 21 EXP-006 scoping: the needs-intraday note\n"
    "  weekly_pnl_paper: null\n"
    "```\n"
)


def test_malformed_block_yields_precise_diagnostic(tmp_path):
    """_yaml_block flags a malformed TARGET block with line/col + the unquoted-scalar hint."""
    p = tmp_path / "GROWTH_STATUS.md"
    p.write_text(_MALFORMED_STATUS)
    value, present, parse_error = g._yaml_block(p, "GROWTH_STATUS")
    assert value is None and present is True
    assert parse_error is not None
    # names the field, prescribes single-quoting, and locates the failure — none of which
    # the generic message carries.
    assert "as_of" in parse_error
    assert "single quotes" in parse_error
    assert "line" in parse_error and "failed to parse" in parse_error


def test_malformed_block_fails_closed_with_hint_end_to_end():
    """evaluate surfaces the diagnostic (fail-closed) instead of the generic message."""
    errs = g.evaluate(None, True, None, False,
                      gs_parse_error="GROWTH_STATUS `GROWTH_STATUS:` block failed to parse at "
                                     "line 2, col 42: mapping values are not allowed here. "
                                     "HINT: `as_of` looks like an UNQUOTED free-text scalar "
                                     "containing a `: ` — wrap the value in single quotes.")
    assert errs, "a malformed block must still fail closed"
    assert any("UNQUOTED" in e and "as_of" in e for e in errs)
    # the generic masking message must NOT be what surfaces
    assert not any(e == "GROWTH_STATUS.md has no parseable fenced `GROWTH_STATUS:` YAML block."
                   for e in errs)


def test_absent_block_still_gives_generic_message(tmp_path):
    """A file with NO GROWTH_STATUS block (vs a malformed one) keeps the generic message."""
    p = tmp_path / "GROWTH_STATUS.md"
    p.write_text("```yaml\nSOMETHING_ELSE:\n  x: 1\n```\n")
    value, present, parse_error = g._yaml_block(p, "GROWTH_STATUS")
    assert value is None and present is True and parse_error is None
    errs = g.evaluate(value, present, None, False, gs_parse_error=parse_error)
    assert any("no parseable" in e for e in errs)


def test_unrelated_yaml_error_not_blamed_on_growth_status(tmp_path):
    """A YAMLError in an UNRELATED fenced block must not be reported as a GROWTH_STATUS error."""
    p = tmp_path / "GROWTH_STATUS.md"
    # first block is malformed but is NOT the GROWTH_STATUS block; second is a valid target block
    p.write_text("```yaml\nOTHER:\n  k: v: bad\n```\n"
                 "```yaml\nGROWTH_STATUS:\n  weekly_pnl_paper: null\n```\n")
    value, present, parse_error = g._yaml_block(p, "GROWTH_STATUS")
    assert present is True and parse_error is None
    assert isinstance(value, dict) and value.get("weekly_pnl_paper") is None
