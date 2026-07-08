"""Deterministic tests for the B9 per-category crowd-calibration diagnostic."""

import json
from dataclasses import asdict, dataclass
from typing import Optional

from backend.app.prediction_markets.per_category_diagnostics import (
    per_category_calibration,
)


@dataclass
class _M:
    market_price: float
    outcome: int
    category: Optional[str] = None


def _sharp(cat, n):
    """A well-calibrated category: crowd prices ~match outcomes (low ECE)."""
    out = []
    for i in range(n):
        yes = i % 2 == 0
        out.append(_M(market_price=0.95 if yes else 0.05, outcome=1 if yes else 0, category=cat))
    return out


def _miscalibrated(cat, n):
    """A soft category: crowd prices everything 0.5 but 80% resolve YES (high ECE, beatable)."""
    return [_M(market_price=0.5, outcome=1 if (i % 5) < 4 else 0, category=cat) for i in range(n)]


def test_ranks_miscalibrated_category_as_most_beatable():
    markets = _sharp("Sports", 40) + _miscalibrated("Politics", 40)
    r = per_category_calibration(markets, min_category_n=30)
    assert r.n_markets == 80
    assert r.n_categories_assessed == 2
    assert r.most_beatable == "Politics"                 # the miscalibrated crowd
    # ranked beatable-first: Politics (high ECE) before Sports (low ECE)
    assert r.categories[0].category == "Politics"
    assert r.categories[0].crowd_ece > r.categories[1].crowd_ece


def test_insufficient_category_not_ranked_beatable():
    # Politics is very miscalibrated but under-sampled (n=5) -> must NOT be most_beatable.
    markets = _sharp("Sports", 40) + _miscalibrated("Politics", 5)
    r = per_category_calibration(markets, min_category_n=30)
    assert r.n_categories_assessed == 1                  # only Sports qualifies
    assert r.most_beatable == "Sports"
    politics = [c for c in r.categories if c.category == "Politics"][0]
    assert politics.sufficient is False
    # insufficient categories sort AFTER sufficient ones
    assert r.categories[-1].category == "Politics"


def test_bonferroni_alpha_tightens_with_category_count():
    two = per_category_calibration(_sharp("A", 30) + _sharp("B", 30), min_category_n=30)
    assert abs(two.bonferroni_alpha - 0.025) < 1e-9      # 0.05 / 2
    one = per_category_calibration(_sharp("A", 30), min_category_n=30)
    assert abs(one.bonferroni_alpha - 0.05) < 1e-9       # 0.05 / 1


def test_none_category_folds_into_general():
    markets = [_M(market_price=0.5, outcome=1, category=None) for _ in range(30)]
    r = per_category_calibration(markets, min_category_n=30)
    assert r.n_categories_total == 1
    assert r.categories[0].category == "General"


def test_base_rate_and_pinned_pct_computed():
    # A near-certain crowd priced at 0.02/0.98 (strictly beyond the <0.05 / >0.95 pin band).
    markets = [
        _M(market_price=0.98 if i % 2 == 0 else 0.02, outcome=1 if i % 2 == 0 else 0, category="Sports")
        for i in range(40)
    ]
    r = per_category_calibration(markets, min_category_n=30)
    c = r.categories[0]
    assert abs(c.base_rate - 0.5) < 1e-9
    assert c.pinned_pct == 1.0                           # every market is already near-certain
    assert c.crowd_brier < 0.01                          # a sharp crowd -> tiny Brier


def test_pinned_pct_uses_strict_boundary():
    # 0.95 / 0.05 sit exactly ON the boundary and must NOT count as pinned (strict < / >).
    markets = [
        _M(market_price=0.95 if i % 2 == 0 else 0.05, outcome=1 if i % 2 == 0 else 0, category="X")
        for i in range(30)
    ]
    r = per_category_calibration(markets, min_category_n=30)
    assert r.categories[0].pinned_pct == 0.0


def test_determinism():
    markets = _sharp("Sports", 40) + _miscalibrated("Politics", 40)
    a = per_category_calibration(markets, min_category_n=30)
    b = per_category_calibration(markets, min_category_n=30)
    assert a == b


def test_note_discloses_diagnostic_and_bonferroni():
    r = per_category_calibration(_sharp("A", 30) + _sharp("B", 30), min_category_n=30)
    assert "Diagnostic only" in r.note
    assert "NOT a validated edge" in r.note
    assert "Bonferroni" in r.note


def test_empty_corpus_brier_is_none_not_nan_and_json_valid():
    # An empty corpus (e.g. the fetch timed out / returned nothing) must NOT poison the
    # report with float("nan"): asdict()+json.dumps of the report emits the invalid RFC-8259
    # `NaN` token that jq / non-Python parsers reject (the same class the F11 #249 fix caught).
    # scripts/per_category_edge_search.py --json serializes exactly this shape.
    r = per_category_calibration([], min_category_n=30)
    assert r.n_markets == 0
    assert r.aggregate_crowd_brier is None            # None, never NaN
    payload = {
        "categories": [asdict(c) for c in r.categories],
        "aggregate_crowd_brier": r.aggregate_crowd_brier,
        "bonferroni_alpha": r.bonferroni_alpha,
        "most_beatable": r.most_beatable,
    }
    dumped = json.dumps(payload)                        # would raise-free but emit NaN pre-fix
    assert "NaN" not in dumped                          # RFC-8259 valid
    assert json.loads(dumped)["aggregate_crowd_brier"] is None
