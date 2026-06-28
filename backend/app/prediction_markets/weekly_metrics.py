"""
ROADMAP C5 — Weekly Metrics Aggregator
=======================================
Measurement backbone for the LLM-Quant prediction-markets learning loop.

This module is a PURE, deterministic computation layer — no database, no
network, no side-effects.  Callers feed it resolved ``TradePnL`` records and
receive ``MetricsSummary`` / ``WeeklyMetrics`` objects they can log, store, or
act upon.

Key design decisions
--------------------
* Dependency-light: stdlib ``math`` / ``statistics`` only (no pandas/numpy
  required, though numpy IS available in CI).
* ``frozen=True`` dataclasses ensure immutability; all aggregation functions
  are pure and referentially transparent.
* Week boundaries follow ISO 8601 (Monday = start of week).

Go-live floor (ROADMAP C5)
--------------------------
The ``floor_met`` helper exposes the $2 k/week average PnL threshold the team
uses as a live-trading gate.  It reads from a ``MetricsSummary``; it does NOT
touch any ledger or execution layer.

NOTE on sparse weeks
--------------------
``aggregate_weekly`` only emits ``WeeklyMetrics`` for calendar weeks that
contain at least one resolved trade.  Weeks with zero trades are silently
omitted.  This keeps the cumulative curve contiguous with respect to the
returned list, but callers filling a time-series chart should be aware of
potential gaps.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Sequence, Union


# ---------------------------------------------------------------------------
# Core data types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TradePnL:
    """A single resolved position's realized profit-and-loss.

    Parameters
    ----------
    timestamp:
        UTC-naive (or tz-aware) datetime when the position was closed /
        resolved.  Only the *date component* is used for weekly bucketing, so
        timezone handling is the caller's responsibility.
    pnl_usd:
        Realized PnL in USD.  Negative values represent losses.
    is_win:
        True if the trade was a winning trade (pnl_usd > 0 by convention,
        though callers may define the threshold differently).
    """

    timestamp: datetime
    pnl_usd: float
    is_win: bool


@dataclass(frozen=True)
class WeeklyMetrics:
    """Aggregated metrics for a single ISO calendar week.

    Parameters
    ----------
    week_start:
        The Monday that opens the ISO week.
    realized_pnl_usd:
        Sum of ``TradePnL.pnl_usd`` for all trades that closed in this week.
    num_trades:
        Count of resolved trades in this week.
    num_wins:
        Count of winning trades (``TradePnL.is_win is True``) in this week.
    hit_rate:
        ``num_wins / num_trades``; 0.0 when ``num_trades == 0``.
    cumulative_pnl_usd:
        Running cumulative PnL from the first week in the series up to and
        including this week (NOT an all-time figure — scoped to the input
        trade sequence).
    """

    week_start: date
    realized_pnl_usd: float
    num_trades: int
    num_wins: int
    hit_rate: float
    cumulative_pnl_usd: float


@dataclass(frozen=True)
class MetricsSummary:
    """Portfolio-level summary built from a sequence of ``TradePnL`` records.

    Parameters
    ----------
    weeks:
        Ordered list of ``WeeklyMetrics`` (ascending by ``week_start``).
        Weeks with no trades are omitted (see module docstring).
    total_pnl_usd:
        Sum of all realized PnL across the entire period.
    avg_weekly_pnl_usd:
        Arithmetic mean of ``WeeklyMetrics.realized_pnl_usd`` across all
        active weeks.  0.0 when there are no weeks.
    weekly_sharpe:
        Mean / sample-stdev of the weekly PnL series (non-annualized).
        0.0 when fewer than 2 weeks or when stdev == 0.
    max_drawdown_usd:
        Maximum peak-to-trough decline in the cumulative equity curve,
        expressed as a non-negative USD magnitude.
    max_drawdown_pct:
        Same decline expressed as a fraction of the running peak (0.0 if
        the peak is <= 0 at the time of the trough).  Non-negative.
    hit_rate:
        Overall ``num_wins / num_trades`` across all trades.  0.0 when no
        trades exist.
    total_trades:
        Total count of resolved trades in the input.
    best_week_usd:
        Highest single-week realized PnL.  0.0 when no weeks exist.
    worst_week_usd:
        Lowest single-week realized PnL.  0.0 when no weeks exist.
    num_weeks:
        Number of active (non-zero-trade) weeks in the series.
    """

    weeks: list[WeeklyMetrics]
    total_pnl_usd: float
    avg_weekly_pnl_usd: float
    weekly_sharpe: float
    max_drawdown_usd: float
    max_drawdown_pct: float
    hit_rate: float
    total_trades: int
    best_week_usd: float
    worst_week_usd: float
    num_weeks: int


# ---------------------------------------------------------------------------
# Pure helper functions
# ---------------------------------------------------------------------------

def week_start_of(d: Union[datetime, date]) -> date:
    """Return the ISO Monday that opens the week containing *d*.

    Parameters
    ----------
    d:
        A ``datetime`` or ``date`` instance.  For ``datetime`` objects only
        the date component is examined; timezone information is ignored.

    Returns
    -------
    date
        The Monday of the ISO week (``isoweekday() == 1``).

    Examples
    --------
    >>> week_start_of(date(2024, 1, 17))  # Wednesday
    datetime.date(2024, 1, 15)
    >>> week_start_of(date(2024, 1, 15))  # Monday
    datetime.date(2024, 1, 15)
    >>> week_start_of(date(2024, 1, 21))  # Sunday
    datetime.date(2024, 1, 15)
    """
    if isinstance(d, datetime):
        d = d.date()
    # isoweekday(): Monday=1 … Sunday=7
    return d - timedelta(days=d.isoweekday() - 1)


def aggregate_weekly(trades: Sequence[TradePnL]) -> list[WeeklyMetrics]:
    """Group trades by ISO week and compute per-week metrics.

    Parameters
    ----------
    trades:
        Any sequence of ``TradePnL`` records, in any order.

    Returns
    -------
    list[WeeklyMetrics]
        One entry per ISO week that contains at least one trade, sorted
        ascending by ``week_start``.  Weeks with no trades are NOT emitted
        (see module-level docstring for implications when filling charts).

    Notes
    -----
    ``cumulative_pnl_usd`` on each row is the running sum of
    ``realized_pnl_usd`` from the first (oldest) week through that row.
    It is NOT an all-time figure — it is scoped to the provided *trades*
    sequence.
    """
    if not trades:
        return []

    # Bucket: week_start (date) → list of TradePnL
    buckets: dict[date, list[TradePnL]] = defaultdict(list)
    for trade in trades:
        ws = week_start_of(trade.timestamp)
        buckets[ws].append(trade)

    running_pnl = 0.0
    result: list[WeeklyMetrics] = []

    for ws in sorted(buckets.keys()):
        week_trades = buckets[ws]
        realized = sum(t.pnl_usd for t in week_trades)
        num_trades = len(week_trades)
        num_wins = sum(1 for t in week_trades if t.is_win)
        hit_rate = num_wins / num_trades if num_trades > 0 else 0.0
        running_pnl += realized

        result.append(
            WeeklyMetrics(
                week_start=ws,
                realized_pnl_usd=realized,
                num_trades=num_trades,
                num_wins=num_wins,
                hit_rate=hit_rate,
                cumulative_pnl_usd=running_pnl,
            )
        )

    return result


def weekly_sharpe(weekly_pnls: Sequence[float]) -> float:
    """Compute a non-annualized Sharpe ratio from a weekly PnL series.

    This is the arithmetic mean divided by the sample standard deviation
    (ddof=1) of the weekly PnL values.  It is NOT annualized — it is a
    pure signal-to-noise measure of the weekly series as presented.

    To convert to an annualized Sharpe (52-week year) multiply by
    ``math.sqrt(52)`` at the call site.

    Parameters
    ----------
    weekly_pnls:
        Sequence of per-week realized PnL figures (USD).

    Returns
    -------
    float
        0.0 if fewer than 2 data points or if sample stdev is zero
        (constant series); otherwise ``mean / stdev``.
    """
    pnls = list(weekly_pnls)
    if len(pnls) < 2:
        return 0.0
    mean = statistics.mean(pnls)
    stdev = statistics.stdev(pnls)  # sample stdev, ddof=1
    if stdev == 0.0:
        return 0.0
    return mean / stdev


def max_drawdown(cumulative_curve: Sequence[float]) -> tuple[float, float]:
    """Compute max drawdown (USD and %) from a running equity curve.

    Scans the cumulative PnL curve for the largest peak-to-trough decline.
    Both return values are non-negative magnitudes.

    Parameters
    ----------
    cumulative_curve:
        Ordered sequence of cumulative PnL values (USD).  Typically the
        ``cumulative_pnl_usd`` field from a sorted ``WeeklyMetrics`` list.

    Returns
    -------
    tuple[float, float]
        ``(max_drawdown_usd, max_drawdown_pct)`` where:

        * ``max_drawdown_usd`` — largest peak-to-trough drop in USD
          (non-negative).
        * ``max_drawdown_pct`` — that drop expressed as a fraction of the
          running peak (non-negative).  Returns 0.0 when the running peak
          at the time of the trough is <= 0 (avoids divide-by-zero and
          undefined semantics for negative equity bases).

    Examples
    --------
    >>> max_drawdown([100, 120, 90, 150, 80])
    (70.0, 0.4666...)   # peak 150 → trough 80; pct = 70/150
    """
    curve = list(cumulative_curve)
    if not curve:
        return 0.0, 0.0

    peak = curve[0]
    max_dd_usd = 0.0
    max_dd_pct = 0.0

    for value in curve:
        if value > peak:
            peak = value
        dd_usd = peak - value
        if dd_usd > max_dd_usd:
            max_dd_usd = dd_usd
            max_dd_pct = (dd_usd / peak) if peak > 0 else 0.0

    return max_dd_usd, max_dd_pct


def summarize(trades: Sequence[TradePnL]) -> MetricsSummary:
    """Build a ``MetricsSummary`` from raw ``TradePnL`` records.

    This is the primary entry-point for ROADMAP C5 metrics.  It computes
    all tracked KPIs from real, realized trade records — it never invents
    or interpolates numbers.

    Parameters
    ----------
    trades:
        Sequence of resolved ``TradePnL`` records.  May be empty; all
        metrics will be zero-valued in that case.

    Returns
    -------
    MetricsSummary
        Fully populated summary.  Deterministic: identical inputs always
        produce identical outputs.
    """
    weeks = aggregate_weekly(trades)

    total_pnl = sum(w.realized_pnl_usd for w in weeks)
    num_weeks = len(weeks)
    avg_weekly_pnl = total_pnl / num_weeks if num_weeks > 0 else 0.0

    weekly_pnl_series = [w.realized_pnl_usd for w in weeks]
    sharpe = weekly_sharpe(weekly_pnl_series)

    cumulative_curve = [w.cumulative_pnl_usd for w in weeks]
    dd_usd, dd_pct = max_drawdown(cumulative_curve)

    total_trades = sum(w.num_trades for w in weeks)
    total_wins = sum(w.num_wins for w in weeks)
    overall_hit_rate = total_wins / total_trades if total_trades > 0 else 0.0

    best_week = max(weekly_pnl_series) if weekly_pnl_series else 0.0
    worst_week = min(weekly_pnl_series) if weekly_pnl_series else 0.0

    return MetricsSummary(
        weeks=weeks,
        total_pnl_usd=total_pnl,
        avg_weekly_pnl_usd=avg_weekly_pnl,
        weekly_sharpe=sharpe,
        max_drawdown_usd=dd_usd,
        max_drawdown_pct=dd_pct,
        hit_rate=overall_hit_rate,
        total_trades=total_trades,
        best_week_usd=best_week,
        worst_week_usd=worst_week,
        num_weeks=num_weeks,
    )


def floor_met(
    summary: MetricsSummary,
    floor_usd: float = 2000.0,
    min_weeks: int = 1,
) -> bool:
    """Return True iff the summary clears the go-live performance floor.

    The $2 k/week average PnL threshold is the ROADMAP C5 gate for
    transitioning from paper-trading to live capital.  This helper reads
    purely from an already-computed ``MetricsSummary``; it does NOT touch
    any ledger, execution layer, or external state.

    Parameters
    ----------
    summary:
        A ``MetricsSummary`` produced by ``summarize()``.
    floor_usd:
        Minimum required average weekly PnL in USD.  Defaults to 2000.0.
    min_weeks:
        Minimum number of active weeks that must be present in the summary
        before the floor can be considered met.  Defaults to 1.

    Returns
    -------
    bool
        ``True`` iff ``summary.num_weeks >= min_weeks`` AND
        ``summary.avg_weekly_pnl_usd >= floor_usd``.
    """
    return summary.num_weeks >= min_weeks and summary.avg_weekly_pnl_usd >= floor_usd


# ---------------------------------------------------------------------------
# Public API surface
# ---------------------------------------------------------------------------

__all__ = [
    "TradePnL",
    "WeeklyMetrics",
    "MetricsSummary",
    "week_start_of",
    "aggregate_weekly",
    "weekly_sharpe",
    "max_drawdown",
    "summarize",
    "floor_met",
]
