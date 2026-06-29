"""Regression: the self-validation coverage gate blocks unvalidated capabilities and
undeclared credentials (the "loop hit a new service needing a key -> surface + block").
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import check_self_validation as csv  # noqa: E402


def test_committed_manifest_is_green():
    """The real committed manifest must pass (else we'd red-block the loop today)."""
    assert csv.check() == [], "committed SELF_VALIDATION manifest is not green"


def test_active_unvalidated_capability_blocks():
    root = {
        "capabilities": [
            {"id": "new_alerting", "active": True, "status": "unvalidated"},
        ],
        "credential_inventory": {},
    }
    fails = csv.check(root=root, in_code=set())
    assert any("new_alerting" in f for f in fails)


def test_active_validated_capability_passes():
    root = {
        "capabilities": [{"id": "x", "active": True, "status": "validated"}],
        "credential_inventory": {},
    }
    assert csv.check(root=root, in_code=set()) == []


def test_gated_off_capability_does_not_block():
    root = {
        "capabilities": [{"id": "live", "active": False, "status": "gated_off"}],
        "credential_inventory": {},
    }
    assert csv.check(root=root, in_code=set()) == []


def test_undeclared_credential_in_code_blocks():
    """A NEW service key read in code but not declared in the manifest blocks every PR."""
    root = {"capabilities": [], "credential_inventory": {}}
    fails = csv.check(root=root, in_code={"KALSHI_API_KEY"})
    assert any("KALSHI_API_KEY" in f and "UNDECLARED" in f for f in fails)


def test_declared_credential_passes():
    root = {
        "capabilities": [{"id": "kalshi", "active": False, "status": "gated_off"}],
        "credential_inventory": {"KALSHI_API_KEY": {"capability": "kalshi", "owner_action": "OA-X"}},
    }
    assert csv.check(root=root, in_code={"KALSHI_API_KEY"}) == []


def test_unvalidated_blocking_list_blocks():
    root = {"capabilities": [], "credential_inventory": {}, "unvalidated_blocking": ["foo"]}
    assert any("unvalidated_blocking" in f for f in csv.check(root=root, in_code=set()))


def test_credential_maps_to_real_capability():
    root = {
        "capabilities": [{"id": "real", "active": True, "status": "validated"}],
        "credential_inventory": {"X_API_KEY": {"capability": "ghost"}},
    }
    assert any("ghost" in f for f in csv.check(root=root, in_code=set()))


# --- readiness mode + UNMET surfacing (the addendum) ---

def test_committed_readiness_is_green():
    assert csv.check_readiness() == [], "committed manifest is not readiness-green"


def test_readiness_block_counts_and_unmet():
    root = {
        "capabilities": [
            {"id": "a", "active": True, "ci_validatable": True, "status": "validated"},
            {"id": "kalshi", "active": True, "ci_validatable": False, "status": "validated"},
            {"id": "off", "active": False, "ci_validatable": False, "status": "gated_off"},
        ],
        "credential_inventory": {},
    }
    rd = csv.readiness(root)
    assert rd["capabilities_total"] == 3
    assert rd["unmet"] == ["kalshi"]          # active + ci_validatable:false; inactive 'off' exempt


def test_unmet_capability_must_be_surfaced_in_both_channels():
    """An active ci_validatable:false capability blocks AND must appear as an urgent
    OWNER_ACTION + in LOOP_HEALTH.validation.unmet (not present in the real files -> failures)."""
    root = {
        "capabilities": [{"id": "kalshi", "active": True, "ci_validatable": False, "status": "validated"}],
        "credential_inventory": {},
    }
    fails = csv.check_readiness(root=root)
    assert any("UNMET" in f and "kalshi" in f for f in fails)
    assert any("validation-capability-kalshi" in f for f in fails)   # missing OWNER_ACTION surfaced
    assert any("LOOP_HEALTH" in f and "kalshi" in f for f in fails)  # missing LOOP_HEALTH entry surfaced
