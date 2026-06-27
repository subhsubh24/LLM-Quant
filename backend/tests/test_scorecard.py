"""
Tests for scripts/check_scorecard.py — the maker's consumer-side guard for the
independent Quality Auditor's grade. Pure-logic tests (no file IO, no pandas) so they
run inside the light CI gate.
"""
import os
import sys

import pytest

# Make scripts/ importable.
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_ROOT, "scripts"))

import check_scorecard as cs  # noqa: E402


def test_validate_grades_accepts_valid():
    block = {
        "overall": "B",
        "dimensions": [
            {"name": "functional_reality", "grade": "A", "ship_critical": True},
            {"name": "backtest_integrity", "grade": "C", "ship_critical": True},
            {"name": "docs", "grade": None, "ship_critical": False},
        ],
    }
    assert cs.validate_grades(block) == []


def test_validate_grades_rejects_invalid():
    block = {"dimensions": [{"name": "x", "grade": "A++", "ship_critical": True}]}
    bad = cs.validate_grades(block)
    assert bad == [("x", "A++")]


def test_validate_grades_rejects_bad_overall():
    block = {"overall": "Z", "dimensions": []}
    assert ("overall", "Z") in cs.validate_grades(block)


def test_dimensions_supports_mapping_form():
    block = {"dimensions": {"security": {"grade": "A", "ship_critical": True}}}
    assert cs.dimensions(block) == [("security", "A", True)]


def test_readiness_passes_when_all_meet_bar():
    block = {
        "dimensions": [
            {"name": "functional_reality", "grade": "A", "ship_critical": True},
            {"name": "security", "grade": "A+", "ship_critical": True},
            {"name": "docs", "grade": "B", "ship_critical": False},
        ],
    }
    assert cs.readiness_failures(block) == []


def test_readiness_fails_ship_critical_below_A():
    block = {
        "dimensions": [
            {"name": "backtest_integrity", "grade": "B", "ship_critical": True},
        ],
    }
    fails = cs.readiness_failures(block)
    assert len(fails) == 1 and "ship-critical needs A/A+" in fails[0]


def test_readiness_fails_noncritical_below_B():
    block = {
        "dimensions": [
            {"name": "docs", "grade": "C", "ship_critical": False},
        ],
    }
    fails = cs.readiness_failures(block)
    assert len(fails) == 1 and "needs >= B" in fails[0]


def test_readiness_fails_ungraded_dimension():
    block = {"dimensions": [{"name": "x", "grade": None, "ship_critical": True}]}
    assert cs.readiness_failures(block) == ["x: ungraded"]


def test_grade_ordering_is_sane():
    assert cs.ORDER["A+"] > cs.ORDER["A"] > cs.ORDER["B"] > cs.ORDER["C"] > cs.ORDER["D"] > cs.ORDER["F"]
