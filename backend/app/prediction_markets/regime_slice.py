"""regime_slice.py — backtest robustness / regime-slice + concentration report
(ROADMAP F10, the anti-overfitting integrity check).

WHY THIS EXISTS
An aggregate out-of-sample PnL that clears the weekly floor can still hide a
FRAGILE edge — all the profit concentrated in ONE market category, ONE
resolution-horizon band, ONE lucky time window, or a HANDFUL of correlated
markets. That is NOT a validated, durable edge even though the headline number
looks good; shipping it would be a textbook overfit. This module slices a
walk-forward backtest's realized OOS trades along the dimensions where a real
edge should be BROAD, builds a concentration map, and FLAGS fragility so the
go-live-eligible audit (FACTORY_STANDARD §7/§8) and the DoD can block a
concentrated edge from being read as a real one.

It is the prediction-market analog of a quant "regime-sliced view + exposure map
so concentration never hides" — tailored to this product's real regimes
(category / resolution-horizon / crowd-confidence / time), not vol-regimes.

HONEST SCOPE
This is a DIAGNOSTIC, not an edge. It never invents PnL: it only re-partitions
the REAL ``BacktestTrade`` records ``walk_forward`` already produced. Three of the
four dimensions (horizon, crowd-confidence, time) derive purely from a
``BacktestTrade``; CATEGORY is not carried on a trade, so the caller supplies a
``category_by_market_id`` map (built from the ``ResolvedMarket`` list before the
backtest drops it) — absent, category-slicing honestly reports ``"uncategorized"``
rather than fabricating a label.

DETERMINISTIC + PURE: stdlib only, no I/O, frozen dataclasses, stable ordering —
the same trades produce the same report, so it is reproducible + fixture-testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Mapping, Optional, Sequence

from .walk_forward import BacktestTrade

# ---------------------------------------------------------------------------
# Named, defensible thresholds (no magic numbers). A dimension is "concentrated"
# when a SINGLE bucket holds more than this share of the total NET PnL; a single
# market holding more than TOP_MARKET_PNL_CONCENTRATION of net PnL is a few-correlated-
# markets red flag. LEAVE_ONE_OUT flips the edge if removing the top CATEGORY
# takes the remaining net PnL to <= 0 (the edge lives entirely in one category).
# ---------------------------------------------------------------------------
CATEGORY_PNL_CONCENTRATION = 0.70
HORIZON_PNL_CONCENTRATION = 0.70
TIME_PNL_CONCENTRATION = 0.70
CONFIDENCE_PNL_CONCENTRATION = 0.70
TOP_MARKET_PNL_CONCENTRATION = 0.50
# EXTREME-confidence concentration: the single-bucket confidence check above misses an edge
# SPLIT across BOTH near-certain entry buckets (e.g. 50% from '0-10%' + 45% from '90-100%' —
# neither alone > 70%, but 95% combined). This product's own OOS research is the motivation:
# the crowd is SHARP on price-pinned markets, so an edge living in the near-0/near-1 entry
# buckets is exactly the regime most likely to be spurious (few headroom). Flag when the two
# extreme confidence buckets together hold more than this share of net PnL. Set above the
# single-bucket 0.70 (it takes TWO buckets to trip) so it only fires on genuine
# extremes-concentration; tightening-only (can add a fragile flag, never clear one).
EXTREME_CONFIDENCE_PNL_CONCENTRATION = 0.85
_EXTREME_CONFIDENCE_LABELS = ("0-10%", "90-100%")

# Bucket edges.
_HORIZON_EDGES_DAYS = (1.0, 3.0, 7.0, 30.0)          # <=1d, 1-3d, 3-7d, 7-30d, >30d
_CONFIDENCE_EDGES = (0.1, 0.25, 0.5, 0.75, 0.9)      # by entry_price (bought-side cost)

UNCATEGORIZED = "uncategorized"


# ---------------------------------------------------------------------------
# Output types (immutable)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class SlicePnL:
    """One bucket of a slice dimension."""

    label: str
    n_trades: int
    gross_budget_usd: float
    net_pnl_usd: float
    hit_rate: float
    budget_share: float                 # gross_budget / total_gross_budget (in [0,1])
    pnl_share: Optional[float]          # net_pnl / total_pnl when total_pnl>0, else None


@dataclass(frozen=True)
class RegimeSliceReport:
    n_trades: int
    total_pnl_usd: float
    total_gross_budget_usd: float
    has_positive_edge: bool
    by_category: tuple[SlicePnL, ...]
    by_horizon: tuple[SlicePnL, ...]
    by_confidence: tuple[SlicePnL, ...]
    by_time: tuple[SlicePnL, ...]
    # Concentration map.
    top_category_budget_share: float
    top2_category_budget_share: float
    top_category_pnl_share: Optional[float]
    top_market_pnl_share: Optional[float]
    # Verdict.
    fragile: bool
    fragile_reasons: tuple[str, ...]


# ---------------------------------------------------------------------------
# Bucketers (pure)
# ---------------------------------------------------------------------------
def _horizon_label(t: BacktestTrade) -> str:
    days = (t.resolution_time - t.decision_time).total_seconds() / 86400.0
    e = _HORIZON_EDGES_DAYS
    if days <= e[0]:
        return "<=1d"
    if days <= e[1]:
        return "1-3d"
    if days <= e[2]:
        return "3-7d"
    if days <= e[3]:
        return "7-30d"
    return ">30d"


def _confidence_label(t: BacktestTrade) -> str:
    p = t.entry_price
    e = _CONFIDENCE_EDGES
    if p <= e[0]:
        return "0-10%"
    if p <= e[1]:
        return "10-25%"
    if p <= e[2]:
        return "25-50%"
    if p <= e[3]:
        return "50-75%"
    if p <= e[4]:
        return "75-90%"
    return "90-100%"


def _iso_monday(d) -> date:
    day = d.date()
    return day - timedelta(days=day.weekday())


def _time_label(t: BacktestTrade) -> str:
    return _iso_monday(t.resolution_time).isoformat()


# Deterministic display order for the fixed-vocabulary dimensions (unknown labels
# sort after, alphabetically, so ordering is always total + stable).
_HORIZON_ORDER = ("<=1d", "1-3d", "3-7d", "7-30d", ">30d")
_CONFIDENCE_ORDER = ("0-10%", "10-25%", "25-50%", "50-75%", "75-90%", "90-100%")


def _order_key(fixed: Sequence[str]):
    idx = {label: i for i, label in enumerate(fixed)}
    return lambda label: (idx.get(label, len(fixed)), label)


# ---------------------------------------------------------------------------
# Aggregation (pure)
# ---------------------------------------------------------------------------
def _build_slices(
    trades: Sequence[BacktestTrade],
    label_of,
    total_pnl: float,
    total_budget: float,
    order_key=None,
) -> tuple[SlicePnL, ...]:
    """Group trades by ``label_of(trade)`` into immutable, deterministically-ordered
    ``SlicePnL`` buckets."""
    agg: dict[str, dict] = {}
    for t in trades:
        b = agg.setdefault(
            label_of(t), {"n": 0, "budget": 0.0, "pnl": 0.0, "wins": 0}
        )
        b["n"] += 1
        b["budget"] += t.budget_usd
        b["pnl"] += t.pnl_usd
        b["wins"] += 1 if t.is_win else 0

    labels = sorted(agg.keys(), key=order_key) if order_key else sorted(agg.keys())
    out = []
    for label in labels:
        b = agg[label]
        out.append(
            SlicePnL(
                label=label,
                n_trades=b["n"],
                gross_budget_usd=round(b["budget"], 6),
                net_pnl_usd=round(b["pnl"], 6),
                hit_rate=round(b["wins"] / b["n"], 6) if b["n"] else 0.0,
                budget_share=round(b["budget"] / total_budget, 6) if total_budget > 0 else 0.0,
                pnl_share=(round(b["pnl"] / total_pnl, 6) if total_pnl > 0 else None),
            )
        )
    return tuple(out)


def _top_pnl_share(slices: Sequence[SlicePnL], total_pnl: float) -> Optional[float]:
    """The largest single-bucket share of POSITIVE total net PnL (None if no edge)."""
    if total_pnl <= 0 or not slices:
        return None
    return round(max(s.net_pnl_usd for s in slices) / total_pnl, 6)


def analyze_regime_slices(
    trades: Sequence[BacktestTrade],
    *,
    category_by_market_id: Optional[Mapping[str, str]] = None,
) -> RegimeSliceReport:
    """Partition realized OOS ``BacktestTrade`` records into regime slices + a
    concentration map, and FLAG a fragile (concentrated) edge.

    ``category_by_market_id`` maps a trade's ``market_id`` to a coarse category (built
    from the resolved-market list before the backtest dropped it). Trades with no entry
    fall in ``"uncategorized"`` — never a fabricated label.

    ``fragile`` is True (with named reasons) when a positive aggregate edge is
    concentrated in a single category / horizon / confidence / time bucket beyond the
    named thresholds, when removing the top category flips the remaining edge to <= 0
    (leave-one-out), or when a single market drives more than ``TOP_MARKET_PNL_CONCENTRATION``
    of net PnL. When the aggregate net PnL is <= 0 there is no positive edge to assess,
    so ``fragile`` is False with an explicit reason (the aggregate itself already shows
    no edge — concentration is moot)."""
    trades = list(trades)
    n = len(trades)
    total_pnl = round(sum(t.pnl_usd for t in trades), 6)
    total_budget = round(sum(t.budget_usd for t in trades), 6)
    # Distinguish "no category labels were supplied" from "labels supplied, some unknown".
    # When NONE are supplied every trade falls in the single UNCATEGORIZED bucket, so a
    # category-concentration or leave-one-out flag would fire on EVERY profitable run
    # regardless of the true diversification — a structurally false signal. In that case
    # the category dimension carries NO information and is excluded from fragility (the
    # horizon / confidence / time / single-market checks still apply).
    categories_known = category_by_market_id is not None
    cat_map = dict(category_by_market_id or {})

    def cat_of(t: BacktestTrade) -> str:
        return cat_map.get(t.market_id, UNCATEGORIZED)

    by_category = _build_slices(trades, cat_of, total_pnl, total_budget)
    by_horizon = _build_slices(trades, _horizon_label, total_pnl, total_budget, _order_key(_HORIZON_ORDER))
    by_confidence = _build_slices(trades, _confidence_label, total_pnl, total_budget, _order_key(_CONFIDENCE_ORDER))
    by_time = _build_slices(trades, _time_label, total_pnl, total_budget)

    # Exposure (budget) concentration — always well-defined regardless of PnL sign.
    cat_budgets = sorted((s.gross_budget_usd for s in by_category), reverse=True)
    top_cat_budget = round(cat_budgets[0] / total_budget, 6) if (cat_budgets and total_budget > 0) else 0.0
    top2_cat_budget = (
        round(sum(cat_budgets[:2]) / total_budget, 6) if (cat_budgets and total_budget > 0) else 0.0
    )

    # PnL concentration + fragility (only meaningful with a positive aggregate edge).
    has_edge = total_pnl > 0
    top_cat_pnl = _top_pnl_share(by_category, total_pnl)
    top_market_pnl = None
    if has_edge and trades:
        # Aggregate PnL per market (a market may appear in multiple trades / scale-ins).
        per_market: dict[str, float] = {}
        for t in trades:
            per_market[t.market_id] = per_market.get(t.market_id, 0.0) + t.pnl_usd
        top_market_pnl = round(max(per_market.values()) / total_pnl, 6)

    reasons: list[str] = []
    fragile = False
    if not has_edge:
        reasons.append(
            f"aggregate net PnL {total_pnl:.2f} <= 0: no positive edge to assess for "
            f"concentration (the aggregate already shows no edge)."
        )
    else:
        def _flag(slices, thresh, dim):
            nonlocal fragile
            share = _top_pnl_share(slices, total_pnl)
            if share is not None and share > thresh:
                top = max(slices, key=lambda s: s.net_pnl_usd)
                fragile = True
                reasons.append(
                    f"{dim}: {share:.0%} of net PnL from a single bucket "
                    f"('{top.label}') > {thresh:.0%} threshold"
                )

        # Category concentration + leave-one-out are only meaningful with real labels;
        # with none supplied every trade is UNCATEGORIZED and these would fire spuriously.
        if categories_known:
            _flag(by_category, CATEGORY_PNL_CONCENTRATION, "category")
        else:
            reasons.append(
                "category concentration + leave-one-out NOT assessed (no category labels "
                "supplied for this corpus) — horizon/confidence/time/single-market still apply"
            )
        _flag(by_horizon, HORIZON_PNL_CONCENTRATION, "horizon")
        _flag(by_confidence, CONFIDENCE_PNL_CONCENTRATION, "confidence")
        _flag(by_time, TIME_PNL_CONCENTRATION, "time-window")

        # Extreme-confidence concentration — the two NEAR-CERTAIN entry buckets combined
        # (see EXTREME_CONFIDENCE_PNL_CONCENTRATION). Catches an edge split across both
        # extremes that each single-bucket check misses; tightening-only.
        extreme_pnl = sum(
            s.net_pnl_usd for s in by_confidence if s.label in _EXTREME_CONFIDENCE_LABELS
        )
        extreme_share = extreme_pnl / total_pnl if total_pnl > 0 else 0.0
        if extreme_share > EXTREME_CONFIDENCE_PNL_CONCENTRATION:
            fragile = True
            reasons.append(
                f"confidence-extremes: {extreme_share:.0%} of net PnL from the near-certain "
                f"entry buckets ({'/'.join(_EXTREME_CONFIDENCE_LABELS)}) > "
                f"{EXTREME_CONFIDENCE_PNL_CONCENTRATION:.0%} threshold — edge concentrated in "
                f"crowd-pinned markets (the low-headroom regime this product's OOS research flags)"
            )

        # Leave-one-out on the top CATEGORY: does the edge survive dropping it? Only with
        # real labels (otherwise "the top category" is the sole UNCATEGORIZED bucket and
        # removing it trivially leaves 0 — a false alarm on every run).
        if categories_known and by_category:
            top_cat = max(by_category, key=lambda s: s.net_pnl_usd)
            remaining = round(total_pnl - top_cat.net_pnl_usd, 6)
            if remaining <= 0:
                fragile = True
                reasons.append(
                    f"leave-one-out: removing the top category ('{top_cat.label}') leaves "
                    f"net PnL {remaining:.2f} <= 0 — the entire edge lives in one category"
                )

        if top_market_pnl is not None and top_market_pnl > TOP_MARKET_PNL_CONCENTRATION:
            fragile = True
            reasons.append(
                f"single-market: {top_market_pnl:.0%} of net PnL from ONE market "
                f"> {TOP_MARKET_PNL_CONCENTRATION:.0%} threshold (few-correlated-markets risk)"
            )

        if not fragile:
            reasons.append("edge is broad across categories, horizons, confidence bands, and time")

    return RegimeSliceReport(
        n_trades=n,
        total_pnl_usd=total_pnl,
        total_gross_budget_usd=total_budget,
        has_positive_edge=has_edge,
        by_category=by_category,
        by_horizon=by_horizon,
        by_confidence=by_confidence,
        by_time=by_time,
        top_category_budget_share=top_cat_budget,
        top2_category_budget_share=top2_cat_budget,
        top_category_pnl_share=top_cat_pnl,
        top_market_pnl_share=top_market_pnl,
        fragile=fragile,
        fragile_reasons=tuple(reasons),
    )


__all__ = [
    "SlicePnL",
    "RegimeSliceReport",
    "analyze_regime_slices",
    "CATEGORY_PNL_CONCENTRATION",
    "HORIZON_PNL_CONCENTRATION",
    "TIME_PNL_CONCENTRATION",
    "CONFIDENCE_PNL_CONCENTRATION",
    "TOP_MARKET_PNL_CONCENTRATION",
]
