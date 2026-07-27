"""Tests for the C8 re-score harness (`scripts/rescore_with_spread.py`).

WHY THIS FILE EXISTS: an adversarial auditor found the harness had ZERO coverage while every
figure in `docs/autonomous-loop/C8_SPREAD_REALISM.md` and in the `half_spread_cost_realism`
SELF_VALIDATION entry comes out of it. Its own docstring advertised being "importable +
injectable ... so a test can assert the mechanics deterministically" — describing a test that
did not exist. The verdict logic in particular was never exercised: because no cell is ever a
survivor on the committed corpora, the branch that EXCLUDES the tick-floor bound from the
survivor test is structurally correct but behaviourally dead, so a regression there would ship
silently and would turn a bound into an edge claim.

These tests drive the verdict with synthetic cells so both branches run, and check the two
properties a reader of the published numbers is implicitly trusting.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "rescore_with_spread", REPO_ROOT / "scripts" / "rescore_with_spread.py"
)
rescore = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rescore)


def _result(bucket_ok=False, fade_ok=None):
    """A minimal `run()`-shaped result the verdict can score."""
    fade_ok = fade_ok or {}
    return {
        "bucket": {
            "by_cost_model": {
                m: {"is_validated_edge": bucket_ok if m != "flat" else False}
                for m in ("flat", "747book", "depth_probe", "conservative", "tick_floor")
            }
        },
        "fade": {
            "by_cost_model": {
                m: [{"threshold": 0.15, "is_validated_edge": fade_ok.get(m, False)}]
                for m in ("flat", "747book", "depth_probe", "conservative", "tick_floor")
            }
        },
    }


def test_a_survivor_under_the_tick_floor_alone_is_NOT_a_survivor() -> None:
    """The load-bearing case, and the reason this file exists.

    The tick floor is the tightest spread any order could cross — a BOUND, not a cost estimate.
    A cell that survives only there has not survived a cost model, and reporting it as one
    would convert a bound into an edge claim. This is exactly the shape of the real result:
    the fade th=0.15 cell keeps F11 significance under the floor and under nothing else.
    """
    v = rescore._verdict(_result(fade_ok={"tick_floor": True}))
    assert v["survivors_under_measured_spread"] == []
    assert v["survives_all_measured_models"] is False
    assert v["edge_verdict"] == "EDGE-NOT-PROVEN"
    # It is still visible in the unfiltered list — excluded from the claim, not from the report.
    assert any("tick_floor" in s for s in v["survivors_any_model"])


def test_a_survivor_under_flat_alone_is_NOT_a_survivor() -> None:
    """`flat` is the status quo ante — the cost model whose optimism the whole exercise
    exists to correct — so surviving there cannot support a cost claim either."""
    v = rescore._verdict(_result(fade_ok={"flat": True}))
    assert v["survivors_under_measured_spread"] == []
    assert v["edge_verdict"] == "EDGE-NOT-PROVEN"


def test_a_survivor_under_a_measured_model_IS_reported_as_a_candidate() -> None:
    """The other branch: the harness must not be incapable of ever reporting a survivor —
    that would make the EDGE-NOT-PROVEN verdict vacuous rather than earned."""
    v = rescore._verdict(_result(fade_ok={"747book": True}))
    assert v["survivors_under_measured_spread"] == ["fade@0.15/747book"]
    assert v["edge_verdict"] == "CANDIDATE-REQUIRES-FRESH-AUDIT"


def test_survives_all_measured_models_requires_every_measured_cell() -> None:
    all_measured = {"747book": True, "depth_probe": True, "conservative": True}
    partial = rescore._verdict(_result(fade_ok=all_measured))
    assert partial["survives_all_measured_models"] is False, "bucket cells are still failing"

    full = rescore._verdict(_result(bucket_ok=True, fade_ok=all_measured))
    assert full["survives_all_measured_models"] is True


def test_cost_model_lanes_are_the_three_measurements_plus_flat_plus_the_bound() -> None:
    """Pins the lane set so a model cannot be dropped (which would silently narrow the span)
    or a bound promoted into `MODELS` (which would let it support a cost claim)."""
    cm_mod = rescore._imp(
        "backend.app.prediction_markets.cost_model", "app.prediction_markets.cost_model"
    )
    hs_mod = rescore._imp(
        "backend.app.prediction_markets.half_spread", "app.prediction_markets.half_spread"
    )
    names = [n for n, _ in rescore._cost_models(cm_mod, hs_mod)]
    assert names == ["flat", "747book", "depth_probe", "conservative", "tick_floor"]
    assert "tick_floor" not in hs_mod.MODELS, "a BOUND must never sit in MODELS"
    assert "tick_floor" in hs_mod.BOUNDS


def test_flat_lane_carries_no_half_spread_model_at_all() -> None:
    """Not a zeroed one — the comparison column has to be the real prior result, byte for
    byte, or every published pre-C8 number stops being the thing it is compared against."""
    cm_mod = rescore._imp(
        "backend.app.prediction_markets.cost_model", "app.prediction_markets.cost_model"
    )
    hs_mod = rescore._imp(
        "backend.app.prediction_markets.half_spread", "app.prediction_markets.half_spread"
    )
    flat = dict(rescore._cost_models(cm_mod, hs_mod))["flat"]
    assert flat.half_spread_model is None
    assert flat == cm_mod.CostModel()


def test_exit_leg_delta_is_zero_against_itself_and_signed_correctly() -> None:
    """The emitted figure the doc quotes. Zero against the same model (a sanity floor that
    would catch a sign or basis error), and positive where the measured model is a discount."""
    cm_mod = rescore._imp(
        "backend.app.prediction_markets.cost_model", "app.prediction_markets.cost_model"
    )
    hs_mod = rescore._imp(
        "backend.app.prediction_markets.half_spread", "app.prediction_markets.half_spread"
    )

    class _T:
        def __init__(self, exit_basis, contracts):
            self.exit_basis = exit_basis
            self.contracts = contracts

    flat = cm_mod.CostModel()
    measured = cm_mod.CostModel(half_spread_model=hs_mod.MODELS["conservative"])
    trades = [_T(0.99, 100.0), _T(0.95, 100.0), _T(0.5, 100.0)]

    assert rescore._exit_leg_delta_vs_flat(trades, flat, flat)["delta_ge_090_usd"] == 0.0

    d = rescore._exit_leg_delta_vs_flat(trades, measured, flat)
    assert d["n_legs_ge_090"] == 2 and d["n_legs_ge_098"] == 1
    # Above 0.98 the measured model is a discount -> more proceeds -> positive.
    assert d["delta_ge_098_usd"] > 0.0
    # The 0.95 leg is still costlier under the measured model, so it pulls the total down.
    assert d["delta_ge_090_usd"] < d["delta_ge_098_usd"]


def test_thresholds_are_fixed_so_the_harness_cannot_become_a_search() -> None:
    assert rescore.FADE_THRESHOLDS == (0.15, 0.20)
