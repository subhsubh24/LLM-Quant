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
