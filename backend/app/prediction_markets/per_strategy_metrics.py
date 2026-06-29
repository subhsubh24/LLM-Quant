"""
per_strategy_metrics.py — per-strategy realized-PnL attribution (ROADMAP E6).

WHY THIS EXISTS
``weekly_metrics.py`` aggregates PnL PORTFOLIO-WIDE — it answers "did we make money this
week?" but not "WHICH alpha made or lost it?". VISION's learning loop needs the second
question (step 4: *attribute — which strategies, markets, and conditions made or lost
money, and why*) to decide what to promote (B3), A/B-compare (E4), and retire when
decayed (E2/E4). This module is the attribution primitive: given strategy-TAGGED resolved
trades, it computes each alpha's realized PnL, trade count, hit-rate, and a weekly PnL
series — purely and deterministically, like ``weekly_metrics``.

HONESTY
  * Pure: stdlib only, no DB/network/side-effects. Callers feed real resolved trades
    (e.g. built from ``PredictionPosition`` rows, which DO carry ``strategy``).
  * Never invents fields. ``hit_rate`` is the share of winning trades; with zero trades a
    strategy simply does not appear in the output (we never emit a fabricated 0/0).
  * Deterministic: outputs are ordered (strategies sorted by name; weeks by ISO date), so
    serialization is byte-stable and reconciliation across runs is exact.

SCOPE
  This measures realized attribution; it does not decide promotion/retirement (that's the
  ``strategy_registry`` gate consuming these numbers) and it is not wired into the live
  scan loop in this change — it is the tested engine the wiring will call.
"""

from __future__ import annotations

import types
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Mapping, Sequence


@dataclass(frozen=True)
class StrategyTradePnL:
    """A single resolved trade, tagged with the strategy that opened it.

    ``strategy`` — the alpha/strategy name (e.g. "no_position_scanner").
    ``timestamp`` — when the position resolved/closed (UTC). Only the date is used for
    weekly bucketing.
    ``pnl_usd`` — realized PnL in USD (negative = loss).
    ``is_win`` — True if the trade won (caller's convention; pnl_usd > 0 by default).
    """

    strategy: str
    timestamp: datetime
    pnl_usd: float
    is_win: bool


@dataclass(frozen=True)
class StrategyAttribution:
    """Realized attribution for one strategy."""

    strategy: str
    num_trades: int
    num_wins: int
    total_pnl_usd: float
    mean_pnl_usd: float
    hit_rate: float
    best_trade_usd: float
    worst_trade_usd: float
    # ISO-date (Monday) -> realized PnL that week, sorted by week start. An immutable
    # mapping (MappingProxyType) so a frozen attribution cannot be mutated in place.
    # ``total_pnl_usd`` is the exact sum of these weekly values (reconciles to the cent).
    weekly_pnl: Mapping[str, float]


def _week_start(d: date) -> date:
    """Monday of the ISO week containing ``d`` (matches weekly_metrics bucketing)."""
    return d - timedelta(days=d.weekday())


def _as_date(ts: datetime) -> date:
    """Date component of a (possibly naive) timestamp, treated as UTC."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc).date()


def attribute_by_strategy(
    trades: Sequence[StrategyTradePnL],
) -> Dict[str, StrategyAttribution]:
    """Group resolved trades by strategy and compute each strategy's attribution.

    Returns a dict keyed by strategy name. Strategies with zero trades never appear
    (we do not fabricate empty attributions). Deterministic: ``weekly_pnl`` is ordered by
    week start, and iterating the returned dict in sorted-key order is stable.
    """
    by_strategy: Dict[str, List[StrategyTradePnL]] = defaultdict(list)
    for t in trades:
        by_strategy[t.strategy].append(t)

    out: Dict[str, StrategyAttribution] = {}
    for strategy in sorted(by_strategy):
        rows = by_strategy[strategy]
        n = len(rows)
        wins = sum(1 for r in rows if r.is_win)
        pnls = [r.pnl_usd for r in rows]

        weekly: Dict[date, float] = defaultdict(float)
        for r in rows:
            weekly[_week_start(_as_date(r.timestamp))] += r.pnl_usd
        weekly_sorted = {wk.isoformat(): weekly[wk] for wk in sorted(weekly)}
        # Derive the total from the SAME weekly values so the weekly series always
        # reconciles to total_pnl_usd exactly (no rounding-drift between the two views).
        total = sum(weekly_sorted.values())

        out[strategy] = StrategyAttribution(
            strategy=strategy,
            num_trades=n,
            num_wins=wins,
            total_pnl_usd=total,
            mean_pnl_usd=total / n,
            hit_rate=wins / n,
            best_trade_usd=max(pnls),
            worst_trade_usd=min(pnls),
            weekly_pnl=types.MappingProxyType(weekly_sorted),
        )
    return out


def rank_by_total_pnl(
    attributions: Dict[str, StrategyAttribution],
) -> List[StrategyAttribution]:
    """Strategies ranked by total realized PnL (desc); ties broken by name (asc).

    The ordering input for E4 A/B comparison + decayed-alpha retirement decisions.
    """
    return sorted(
        attributions.values(),
        key=lambda a: (-a.total_pnl_usd, a.strategy),
    )
