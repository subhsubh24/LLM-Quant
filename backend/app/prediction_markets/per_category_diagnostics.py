"""Per-category crowd-calibration diagnostic — "where, if anywhere, is a crowd beatable?" (B9).

The pivoted binding constraint (per ROADMAP A6/A8): the aggregate crowd Brier (~0.08–0.09)
is dragged DOWN by systematically-sharp categories (Sports, near-certain Crypto) that dominate
the corpus — so an aggregate "no edge" can HIDE a real edge in a *less-efficient* category
(niche politics, long-horizon econ). This module measures the crowd's calibration PER
``market_category`` on a real leakage-safe corpus and ranks categories by how MISCALIBRATED
(hence plausibly beatable) the crowd looks — a SEARCH-prioritization map for a future targeted
alpha (B4/B8), NOT an edge claim in itself.

HONESTY (this is a diagnostic, not a licence to slice-until-signal):
  * It reports crowd Brier + ECE + N per category on the CROWD's own price. It does NOT
    trade, size, or fit any model, so it cannot p-hack a PnL out of the sample.
  * Testing K categories is a multiple-comparison problem. The report carries the
    Bonferroni-corrected ``bonferroni_alpha = alpha / K`` that any DOWNSTREAM per-category
    edge test MUST use (mirrors calibration.evaluate_calibration's ``strategies_screened``).
  * A category is only assessed when it has ``>= min_category_n`` resolved markets; below
    that it is reported ``insufficient`` (never ranked, never called beatable).
  * The ranking says only "the crowd looks LESS calibrated here" — turning that into a real
    edge still requires a pre-registered alpha that beats the crowd OOS in that category,
    survives the Bonferroni bar, a passing B2 calibration gate, and F10/F11 non-fragility +
    significance. The report states this explicitly.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import List, Optional, Sequence

from .calibration import brier_score, expected_calibration_error, reliability_curve


@dataclass(frozen=True)
class CategoryCalibration:
    """The crowd's calibration on one market category (crowd price scored vs. real outcomes)."""

    category: str
    n: int
    base_rate: float           # empirical P(YES) in this category
    crowd_brier: float         # mean squared error of the crowd price vs. outcome
    crowd_ece: float           # expected calibration error of the crowd price (miscalibration)
    price_median: float
    pinned_pct: float          # fraction of markets priced <0.05 or >0.95 (already near-certain)
    sufficient: bool           # n >= min_category_n


@dataclass(frozen=True)
class PerCategoryReport:
    """Ranked per-category crowd-calibration map + the multiple-comparison bar for downstream use."""

    categories: List[CategoryCalibration]      # ALL categories, beatable-first among sufficient ones
    n_markets: int
    n_categories_total: int
    n_categories_assessed: int                 # those with n >= min_category_n
    min_category_n: int
    bonferroni_alpha: float                    # alpha / n_categories_assessed (K), for downstream tests
    aggregate_crowd_brier: float
    most_beatable: Optional[str]               # highest-ECE sufficient category, or None
    note: str


def per_category_calibration(
    markets: Sequence,
    *,
    min_category_n: int = 30,
    alpha: float = 0.05,
) -> PerCategoryReport:
    """Measure the crowd's per-category calibration on a leakage-safe corpus.

    ``markets`` is a sequence of records carrying ``.market_price`` (crowd P[YES] at decision),
    ``.outcome`` (0/1), and ``.category`` (coarse correlation bucket; None → "General").
    Returns a ranked map: among categories with ``>= min_category_n`` markets, the one whose
    crowd is LEAST calibrated (highest ECE) is ``most_beatable`` — a candidate to target with
    a real alpha, NOT a validated edge (see the module docstring).
    """
    n = len(markets)
    by_cat: dict[str, list] = {}
    for m in markets:
        cat = getattr(m, "category", None) or "General"
        by_cat.setdefault(cat, []).append(m)

    all_prices = [m.market_price for m in markets]
    all_outs = [m.outcome for m in markets]
    aggregate_brier = brier_score(all_prices, all_outs) if n else float("nan")

    cats: List[CategoryCalibration] = []
    for cat, ms in by_cat.items():
        prices = [m.market_price for m in ms]
        outs = [m.outcome for m in ms]
        cn = len(ms)
        curve = reliability_curve(prices, outs)
        cats.append(CategoryCalibration(
            category=cat,
            n=cn,
            base_rate=round(sum(outs) / cn, 4),
            crowd_brier=round(brier_score(prices, outs), 6),
            crowd_ece=round(expected_calibration_error(curve), 6),
            price_median=round(statistics.median(prices), 4),
            pinned_pct=round(sum(1 for p in prices if p < 0.05 or p > 0.95) / cn, 4),
            sufficient=cn >= min_category_n,
        ))

    assessed = [c for c in cats if c.sufficient]
    k = len(assessed)
    # Rank: sufficient categories first, ordered by DESCENDING crowd ECE (most miscalibrated =
    # most beatable), then insufficient ones (by n desc) so the map is complete but never
    # ranks an under-sampled category as beatable.
    cats_sorted = sorted(
        cats,
        key=lambda c: (0 if c.sufficient else 1, -(c.crowd_ece if c.sufficient else -1), -c.n),
    )
    most_beatable = max(assessed, key=lambda c: c.crowd_ece).category if assessed else None
    bonferroni_alpha = (alpha / k) if k else alpha

    note = (
        f"Diagnostic only: crowd calibration per category on {n} leakage-safe markets. "
        f"{k}/{len(cats)} categories have >= {min_category_n} markets and are ranked by ECE "
        f"(higher = crowd less calibrated = more plausibly beatable). A high-ECE category is a "
        f"CANDIDATE to target with a real alpha, NOT a validated edge: a downstream per-category "
        f"edge test must use the Bonferroni-corrected alpha={round(bonferroni_alpha, 5)} "
        f"(0.05/{k or 1}) and still pass B2 calibration + F10 non-fragility + F11 significance "
        f"OOS. This module never trades or fits a model, so it cannot p-hack a PnL."
    )

    return PerCategoryReport(
        categories=cats_sorted,
        n_markets=n,
        n_categories_total=len(cats),
        n_categories_assessed=k,
        min_category_n=min_category_n,
        bonferroni_alpha=round(bonferroni_alpha, 6),
        aggregate_crowd_brier=round(aggregate_brier, 6) if n else float("nan"),
        most_beatable=most_beatable,
        note=note,
    )
