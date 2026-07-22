"""Deterministic test for the real-data OOS validator's core (no network).

Locks that `evaluate()`: (1) returns a well-formed report, (2) the crowd baseline trades 0
(model_prob==crowd is a tautology), and (3) the B4a calibration alpha RECOVERS a known injected
edge (so a green result means the validator can actually detect an edge, not just report null)."""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import validate_real_oos as v  # noqa: E402
from app.prediction_markets import walk_forward as wf  # noqa: E402
from app.prediction_markets import calibration_bucket_strategy as cal  # noqa: E402


def _synthetic(n: int = 300):
    """Crowd prices every market at 0.5 but 70% resolve YES — a real, learnable injected edge."""
    base = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
    out = []
    for i in range(n):
        outcome = 1 if (i % 10) < 7 else 0
        out.append(wf.HistoricalMarket(
            market_id=f"syn{i}",
            decision_time=base + dt.timedelta(days=i),
            resolution_time=base + dt.timedelta(days=i + 1),
            market_price=0.5, model_prob=0.5, outcome=outcome,
        ))
    return out


def test_report_shape_and_baseline_is_a_tautology():
    r = v.evaluate(_synthetic(), wf, cal, seed=42)
    assert {"corpus", "crowd_baseline", "calibration_alpha_b4a", "verdict"} <= set(r)
    assert r["crowd_baseline"]["trades"] == 0            # model_prob == crowd -> no edge -> 0 trades
    assert r["corpus"]["n_markets"] == 300


def test_alpha_recovers_a_known_injected_edge():
    r = v.evaluate(_synthetic(), wf, cal, seed=42)
    alpha = r["calibration_alpha_b4a"]
    assert alpha["trades"] > 0                            # the calibration model finds the 0.5-vs-0.7 gap
    assert alpha["total_pnl_usd"] > 0                     # and profits from it OOS
    assert "validated edge" in r["verdict"]               # honest: recovering a synthetic edge is NOT a validated one


def test_report_includes_regime_slice_and_flags_concentration():
    """ROADMAP F10 wiring: a run where the alpha trades carries a regime-slice report so a
    concentrated (fragile) edge cannot hide behind the aggregate number. The _synthetic()
    corpus is priced at a single level (0.5) with a single 1-day horizon, so the alpha's
    entire edge concentrates in ONE confidence/horizon bucket — which the guard MUST flag
    fragile (the anti-overfitting point: this aggregate edge is not regime-robust)."""
    r = v.evaluate(_synthetic(), wf, cal, seed=42)
    assert "regime_slice_alpha" in r
    rs = r["regime_slice_alpha"]
    assert rs["n_trades"] == r["calibration_alpha_b4a"]["trades"] > 0
    assert isinstance(rs["fragile"], bool) and isinstance(rs["fragile_reasons"], list)
    # A single-price, single-horizon corpus is maximally concentrated → fragile with reasons.
    assert rs["fragile"] is True
    assert len(rs["fragile_reasons"]) > 0
    assert rs["has_positive_edge"] is True
    # Fragility here is REAL (single price bucket → one confidence bucket; single 1-day
    # horizon), NOT the false category signal: with no category labels the category /
    # leave-one-out checks are explicitly NOT assessed (F10 review fix), so they must not
    # be what trips the flag.
    assert any(rr.startswith("confidence:") or rr.startswith("horizon:") for rr in rs["fragile_reasons"])
    assert not any(rr.startswith("category:") for rr in rs["fragile_reasons"])
    assert not any(rr.startswith("leave-one-out:") for rr in rs["fragile_reasons"])
    # With a positive edge the concentration shares are real numbers (not fabricated Nones).
    assert rs["top_confidence_bucket_pnl_share"] is not None
    # And the fragility is surfaced in the human-readable verdict.
    assert "FRAGILE" in r["verdict"]


def test_regime_slice_absent_edge_reports_no_shares():
    """When the alpha does not trade (calibrated crowd), the regime report is present,
    empty, and honestly reports no positive edge / null concentration shares."""
    base = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
    markets = [wf.HistoricalMarket(market_id=f"c{i}", decision_time=base + dt.timedelta(days=i),
                                   resolution_time=base + dt.timedelta(days=i + 1),
                                   market_price=0.7, model_prob=0.7, outcome=1 if (i % 10) < 7 else 0)
               for i in range(300)]
    r = v.evaluate(markets, wf, cal, seed=42)
    rs = r["regime_slice_alpha"]
    assert rs["n_trades"] == 0
    assert rs["fragile"] is False              # no positive edge → nothing to flag
    assert rs["top_market_pnl_share"] is None  # never fabricated when there is no PnL


def test_no_edge_verdict_on_calibrated_crowd():
    """A well-calibrated crowd (price == outcome-rate) gives the alpha nothing -> 0 trades, NO-EDGE verdict."""
    base = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
    # price 0.7, 70% YES => crowd is right; alpha should abstain/not-beat -> 0 trades
    markets = [wf.HistoricalMarket(market_id=f"c{i}", decision_time=base + dt.timedelta(days=i),
                                   resolution_time=base + dt.timedelta(days=i + 1),
                                   market_price=0.7, model_prob=0.7, outcome=1 if (i % 10) < 7 else 0)
               for i in range(300)]
    r = v.evaluate(markets, wf, cal, seed=42)
    assert r["calibration_alpha_b4a"]["trades"] == 0
    assert "NO EDGE" in r["verdict"]


def test_report_includes_f11_significance_and_serializes_valid_json():
    """ROADMAP F11 wiring: every run carries a bootstrap significance block on the tradeable
    PnL, and the WHOLE report must be RFC-8259-valid JSON (no NaN) even when the alpha trades
    fewer than min_trades (the common case) — the insufficient_data branch reports None, not NaN."""
    import json
    r = v.evaluate(_synthetic(), wf, cal, seed=42)
    assert "significance_alpha_f11" in r
    sig = r["significance_alpha_f11"]
    assert "verdict" in sig and "is_significant_edge" in sig
    text = json.dumps(r)                       # emits invalid `NaN` tokens if any field is NaN
    assert "NaN" not in text
    assert json.loads(text)["significance_alpha_f11"]["verdict"] in {
        "insufficient_data", "significant_positive", "significant_negative",
        "indistinguishable_from_zero",
    }


def test_floor_lane_refuses_research_only_play_money_records():
    """ROADMAP A8 STRUCTURAL guardrail: the real-money floor lane must REFUSE play-money
    (research_only) records — a Manifold edge validates a METHOD but never counts toward the
    real-money profit floor. Fail LOUD, never silently average play money into the floor."""
    import pytest

    play = _synthetic()
    # Stamp ONE record research_only (as the Manifold fetcher does) — simulating an accidental
    # copy-paste of the play-money venue into the floor lane.
    p = play[7]
    play[7] = wf.HistoricalMarket(
        market_id=p.market_id, decision_time=p.decision_time, resolution_time=p.resolution_time,
        market_price=p.market_price, model_prob=p.model_prob, outcome=p.outcome,
        research_only=True,
    )
    with pytest.raises(ValueError, match="research_only"):
        v.evaluate(play, wf, cal, seed=42)

    # A pure real-money corpus (default research_only=False) is unaffected.
    assert v.evaluate(_synthetic(), wf, cal, seed=42)["corpus"]["n_markets"] == 300


# --------------------------------------------------------------------------- #
# concentration_capped_variant — the per-category de-concentration block was   #
# reachable via the CLI (--category-exposure-cap / --cumulative-category-      #
# budget-cap) but had ZERO regression coverage. These lock its shape + the     #
# faithful CUMULATIVE-cap claim (it bounds F10's top_category_budget_share,    #
# which the CONCURRENT cap cannot on a recycling corpus) + backward-compat.    #
# --------------------------------------------------------------------------- #
from app.prediction_markets.market_category import (  # noqa: E402
    CATEGORY_CRYPTO,
    CATEGORY_ECONOMICS,
    CATEGORY_POLITICS,
)


def _categorized_synthetic(n: int = 180):
    """The learnable-edge corpus (0.5 crowd price, 70% YES) but LABELED across categories, with
    POLITICS deliberately dominant (2 of every 4 markets) so its cumulative budget SHARE is high
    — the shape a de-concentration cap must bound. Short-lived (resolve next day) so cost basis
    RECYCLES: the concurrent cap becomes a no-op on cumulative concentration, the cumulative cap
    does not."""
    base = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
    cats = [CATEGORY_POLITICS, CATEGORY_POLITICS, CATEGORY_ECONOMICS, CATEGORY_CRYPTO]
    out = []
    for i in range(n):
        outcome = 1 if (i % 10) < 7 else 0
        out.append(wf.HistoricalMarket(
            market_id=f"cat{i}",
            decision_time=base + dt.timedelta(days=i),
            resolution_time=base + dt.timedelta(days=i + 1),
            market_price=0.5, model_prob=0.5, outcome=outcome,
            category=cats[i % len(cats)],
        ))
    return out


def test_no_cap_leaves_report_free_of_variant_block():
    # Backward-compat: with neither cap set the report is byte-for-byte the old shape — the
    # variant block is ABSENT (the live/frozen lanes and their pinned outputs stay untouched).
    r = v.evaluate(_categorized_synthetic(), wf, cal, seed=42)
    assert "concentration_capped_variant" not in r


def test_concentration_variant_shape_and_cumulative_cap_binds_F10_share():
    r = v.evaluate(
        _categorized_synthetic(), wf, cal, seed=42,
        category_exposure_cap=0.2, cumulative_category_budget_cap=0.4,
    )
    assert "concentration_capped_variant" in r
    b = r["concentration_capped_variant"]
    assert b["category_exposure_cap"] == 0.2
    assert b["cumulative_category_budget_cap"] == 0.4
    # Both strategy families run, each with uncapped + concurrent + cumulative variants.
    for fam in ("calibration", "recency_weighted"):
        assert {"uncapped", "concurrent_capped", "cumulative_capped"} <= set(b[fam])
        cum = b[fam]["cumulative_capped"]
        # The cumulative cap bounds F10's OWN metric to <= the cap (bootstrap slack included in
        # the flag), where the concurrent cap does not (recycling defeats it).
        assert cum["top_category_budget_share"] <= 0.4 + 1e-6
        assert cum["cumulative_share_bounded"] is True
        assert b[fam]["uncapped"]["top_category_budget_share"] > 0.4  # genuinely de-concentrated
    assert b["cumulative_cap_bound_on_this_corpus"] is True
    assert b["cumulative_share_bounded_below_cap"] is True
    assert "REFUTED" in b["verdict"] and "Honest NULL" in b["verdict"]


def test_variant_accepts_cumulative_cap_alone():
    # The cumulative cap is usable on its own (no concurrent cap) — the concurrent variant is
    # then omitted from each family, the cumulative one present.
    r = v.evaluate(_categorized_synthetic(), wf, cal, seed=42, cumulative_category_budget_cap=0.4)
    b = r["concentration_capped_variant"]
    assert b["category_exposure_cap"] is None
    for fam in ("calibration", "recency_weighted"):
        assert "cumulative_capped" in b[fam]
        assert "concurrent_capped" not in b[fam]


def test_variant_never_manufactures_edge_on_losing_signal():
    # HONESTY: a de-concentration cap can only REDUCE deployed capital. On any family whose
    # uncapped aggregate is non-positive, an F10 non-fragile pass is explicitly VACUOUS and the
    # verdict must NOT claim a validated edge.
    r = v.evaluate(
        _categorized_synthetic(), wf, cal, seed=42, cumulative_category_budget_cap=0.4
    )
    b = r["concentration_capped_variant"]
    for fam in ("calibration", "recency_weighted"):
        cum = b[fam]["cumulative_capped"]
        if cum["total_pnl_usd"] <= 0.0 and not cum["f10_fragile"]:
            assert cum["f10_nonfragile_is_vacuous"] is True
