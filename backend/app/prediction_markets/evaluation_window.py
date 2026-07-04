"""
evaluation_window.py — evaluation-window engine + realized-vs-backtest reconciliation
(ROADMAP E5, with the E6 reconciliation primitive).

WHY THIS EXISTS
VISION's learning loop is: propose -> backtest-gate -> run a STABLE evaluation window in
paper -> at window close measure + attribute -> RECONCILE realized vs backtest-expected
(divergence = overfit/leakage) -> next targeted change. ``weekly_metrics`` and
``per_strategy_metrics`` already cover "did we make money?" and "which alpha made it?".
The two pieces still missing are loop steps 4 and 5:

  * Step 4 (window-boundary DISCIPLINE): an evaluation window must hold its strategy
    config STABLE so the window's evidence is clean. A config change mid-window
    contaminates the evidence, so config changes only take effect at a window BOUNDARY —
    and once a window is closed its config snapshot is frozen and never retroactively
    rewritten. This module records that discipline structurally: each window carries a
    versioned ``StrategyConfigSnapshot`` taken at the window's start, with a
    deterministic ``config_hash`` so a config change between windows is detectable.

  * Step 5 (RECONCILIATION): given a window's REALIZED PnL and the BACKTEST-EXPECTED PnL
    for that same window+config, compute the divergence and raise an ``overfit_flag``
    when the gap exceeds a caller-supplied threshold. That gap is the top-priority
    "the backtest is overfit/leaky" learning signal.

This is the pure, deterministic, tested ENGINE those steps need.

WHAT THIS IS NOT
  * NOT wired into the orchestrator in this change. It is the engine the live wiring
    (resolved-trade stream + recorded backtest expectations) will later call. No DB, no
    network, no orchestrator import.
  * NOT a scheduler. It does not decide WHEN a window opens/closes in wall-clock time and
    it never calls ``now()``. Window boundaries are derived purely from caller-supplied
    trade timestamps (ISO-week Monday bucketing, matching ``weekly_metrics``).
  * NOT a promotion/retirement decision-maker. It produces evidence; the
    ``strategy_registry`` gate (B3) consumes it.

HONESTY / DETERMINISM GUARANTEES (these are load-bearing — adversarial auditors check them)
  * All timestamps are caller-supplied; this module NEVER calls ``now()`` or uses
    randomness. Naive datetimes are normalized to UTC (same convention as
    ``per_strategy_metrics._as_date``) so the same inputs are byte-identical across hosts.
  * Reconciliation NEVER fabricates a backtest expectation. ``overfit_flag`` is TRI-STATE:
    ``True`` (diverged past threshold), ``False`` (within threshold), or ``None``
    (UNKNOWN — no expectation supplied). It is never ``False`` by default.
  * Zero-trade windows are represented HONESTLY: a window is only ever emitted because it
    contains at least one resolved trade (we never fabricate an empty 0/0 window out of
    thin air), and its metrics carry ``num_trades`` truthfully. A window that exists but
    whose metrics are all zero is impossible by construction — there is always >=1 trade.
  * A window's ``realized_pnl_usd`` is derived from the SAME per-trade series the rest of
    the window's stats use, so total reconciles to the parts with no rounding drift
    (the ``weekly_metrics`` / ``per_strategy_metrics`` derive-total-from-series pattern).
  * Frozen dataclasses throughout; any contained mapping is wrapped in
    ``types.MappingProxyType`` so a frozen object cannot be mutated in place.
  * Pure stdlib (plus optionally the two sibling pure metric modules). No pandas/numpy/
    torch, no DB, trivially importable in CI.
"""

from __future__ import annotations

import hashlib
import json
import types
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Mapping, Optional, Sequence, Tuple, Union

# Reuse the sibling pure primitives where helpful. These imports are stdlib-equivalent:
# both modules are pure, dependency-light, and CI-importable. We use ``max_drawdown`` for
# the per-window drawdown so the math matches the portfolio aggregator exactly.
from .weekly_metrics import max_drawdown

__all__ = [
    "StrategyConfigSnapshot",
    "ResolvedTrade",
    "EvaluationWindow",
    "WindowMetrics",
    "ReconciliationReport",
    "config_hash_of",
    "window_start_of",
    "compute_window_metrics",
    "reconcile",
    "build_windows",
    "WindowManager",
]


# ---------------------------------------------------------------------------
# Time / hashing helpers (shared determinism conventions)
# ---------------------------------------------------------------------------

def _as_utc_date(ts: Union[datetime, date]) -> date:
    """Date component of a timestamp, normalizing naive datetimes to UTC.

    Matches ``per_strategy_metrics._as_date``: a naive datetime is interpreted as UTC,
    a tz-aware one is converted to UTC, then the date is taken. A plain ``date`` passes
    through unchanged. This is what makes bucketing host-independent.
    """
    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts.astimezone(timezone.utc).date()
    return ts


def _as_utc_datetime(ts: Union[datetime, date]) -> datetime:
    """Full UTC-aware datetime for ORDERING (preserves time-of-day).

    Unlike ``_as_utc_date`` — which drops the time-of-day for calendar (ISO-week)
    bucketing — this keeps the time so trades on the SAME day order chronologically. A
    naive datetime is interpreted as UTC, a tz-aware one is converted to UTC, and a plain
    ``date`` becomes midnight UTC. Always tz-aware, so a mixed naive/aware input list never
    raises on comparison (host-independent).
    """
    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts.astimezone(timezone.utc)
    return datetime(ts.year, ts.month, ts.day, tzinfo=timezone.utc)


def window_start_of(d: Union[datetime, date]) -> date:
    """Monday opening the ISO week containing ``d`` (matches ``weekly_metrics``)."""
    day = _as_utc_date(d)
    return day - timedelta(days=day.isoweekday() - 1)


def _canonical_number(x: float) -> Union[int, float]:
    """Render a number stably for hashing: integral floats become ints.

    So ``5.0`` and ``5`` hash identically — a config value typed either way is the same
    config. Keeps ``config_hash`` from being sensitive to incidental float/int typing.
    """
    if isinstance(x, bool):
        return x
    if isinstance(x, float) and x.is_integer():
        return int(x)
    return x


def _canonical_value(val: object) -> object:
    """Deep, type-normalized, JSON-safe copy of a config value.

    Recurses into nested dicts/lists/tuples so the result shares NO mutable state with the
    caller's input (adversarial-audit finding: a shallow copy aliased nested mutables, so a
    later caller-side mutation silently rewrote a "frozen" snapshot AND left its load-bearing
    ``config_hash`` stale).
    """
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return _canonical_number(val)
    if isinstance(val, Mapping):
        return {str(k): _canonical_value(val[k]) for k in sorted(val)}
    if isinstance(val, (list, tuple)):
        return [_canonical_value(v) for v in val]
    return val


def _canonical_params(params: Mapping[str, object]) -> Dict[str, object]:
    """Sorted, JSON-serializable, type-normalized DEEP copy of a params mapping."""
    return {str(key): _canonical_value(params[key]) for key in sorted(params)}


def _deep_freeze(obj: object) -> object:
    """Recursively convert a canonical (plain) structure into a deeply-immutable one:
    dicts → MappingProxyType, lists → tuples. Scalars pass through. So neither the stored
    snapshot nor any nested container can be mutated in place after construction.
    """
    if isinstance(obj, Mapping):
        return types.MappingProxyType({k: _deep_freeze(v) for k, v in obj.items()})
    if isinstance(obj, (list, tuple)):
        return tuple(_deep_freeze(v) for v in obj)
    return obj


def config_hash_of(params: Mapping[str, object]) -> str:
    """Deterministic, host-stable hash of a config's params.

    A change to any param value (or the set of params) changes the hash, so a config
    change between windows is detectable by comparing hashes. The hash is computed from a
    sorted, type-normalized, ``sort_keys`` JSON encoding, so dict insertion order and
    ``5`` vs ``5.0`` typing do not affect it. Returns a 16-hex-char (64-bit) digest —
    short enough to log, wide enough that incidental collisions are not a concern.
    """
    canonical = _canonical_params(params)
    blob = json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Core data types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StrategyConfigSnapshot:
    """A versioned snapshot of one strategy's config at a window's start.

    ``name`` — the strategy/alpha name.
    ``params`` — its config params as an immutable, sorted mapping.
    ``config_hash`` — a deterministic digest of ``params`` (see ``config_hash_of``); two
    snapshots are config-equal iff their hashes match, so a config change is detectable.

    Construct via ``StrategyConfigSnapshot.create(name, params)`` so the params are frozen
    (``MappingProxyType``) and the hash is derived from them — never pass a hand-supplied
    hash that could disagree with the params.
    """

    name: str
    params: Mapping[str, object]
    config_hash: str

    @classmethod
    def create(
        cls, name: str, params: Mapping[str, object]
    ) -> "StrategyConfigSnapshot":
        """Build a snapshot, deriving ``config_hash`` from the (sorted) params.

        ``params`` is DEEP-copied + deeply frozen, so nested mutables cannot alias the
        caller's input or be mutated in place — keeping ``config_hash`` consistent with the
        stored content (adversarial-audit fix).
        """
        canonical = _canonical_params(params)  # deep, JSON-safe, type-normalized
        return cls(
            name=name,
            params=_deep_freeze(canonical),
            config_hash=config_hash_of(canonical),
        )

    def same_config_as(self, other: "StrategyConfigSnapshot") -> bool:
        """True iff ``other`` carries the same strategy name and config hash."""
        return self.name == other.name and self.config_hash == other.config_hash

    def to_dict(self) -> Dict[str, object]:
        return {
            "name": self.name,
            "params": dict(self.params),
            "config_hash": self.config_hash,
        }


@dataclass(frozen=True)
class ResolvedTrade:
    """A single resolved trade that falls inside an evaluation window.

    ``strategy`` — the alpha that opened it (ties the trade to a config snapshot).
    ``timestamp`` — when the position resolved/closed; only the UTC date is used for
    window (ISO-week) bucketing.
    ``pnl_usd`` — realized PnL in USD (negative = loss).
    ``is_win`` — True if the trade won (caller's convention; pnl_usd > 0 by default).
    ``predicted_prob`` / ``actual_outcome`` — OPTIONAL. If both are supplied for trades in
    a window, a Brier score is computed for that window. ``predicted_prob`` is the
    model's pre-resolution probability of the event in [0, 1]; ``actual_outcome`` is the
    realized outcome (1.0 if the event happened, 0.0 if not). Either being ``None`` means
    "no calibration signal for this trade" — it is then excluded from the Brier average,
    never imputed.
    """

    strategy: str
    timestamp: datetime
    pnl_usd: float
    is_win: bool
    predicted_prob: Optional[float] = None
    actual_outcome: Optional[float] = None


@dataclass(frozen=True)
class WindowMetrics:
    """Deterministic per-window realized metrics.

    ``num_trades`` — count of resolved trades in the window (always >= 1; a window with no
    trades is never emitted).
    ``num_wins`` / ``hit_rate`` — winning-trade count and share.
    ``realized_pnl_usd`` — sum of per-trade PnL, derived from the SAME ordered series the
    drawdown uses so the parts reconcile to the total exactly.
    ``max_drawdown_usd`` / ``max_drawdown_pct`` — peak-to-trough decline of the in-window
    cumulative-PnL curve (trades ordered by timestamp then input order), via
    ``weekly_metrics.max_drawdown``. Non-negative magnitudes.
    ``brier_score`` — mean squared error of ``predicted_prob`` vs ``actual_outcome`` over
    trades where BOTH are supplied; ``None`` when no trade carries both (never fabricated).
    ``brier_n`` — number of trades that contributed to ``brier_score`` (0 when ``None``).
    """

    realized_pnl_usd: float
    num_trades: int
    num_wins: int
    hit_rate: float
    max_drawdown_usd: float
    max_drawdown_pct: float
    brier_score: Optional[float]
    brier_n: int

    def to_dict(self) -> Dict[str, object]:
        return {
            "realized_pnl_usd": self.realized_pnl_usd,
            "num_trades": self.num_trades,
            "num_wins": self.num_wins,
            "hit_rate": self.hit_rate,
            "max_drawdown_usd": self.max_drawdown_usd,
            "max_drawdown_pct": self.max_drawdown_pct,
            "brier_score": self.brier_score,
            "brier_n": self.brier_n,
        }


@dataclass(frozen=True)
class EvaluationWindow:
    """One evaluation window: its boundaries, active config snapshots, and trades.

    ``window_start`` — the ISO Monday opening the window.
    ``window_end`` — exclusive end boundary (``window_start + 7 days`` for ISO-week
    windows). A trade ``t`` belongs to the window iff
    ``window_start <= utc_date(t) < window_end``.
    ``configs`` — the config snapshots ACTIVE for this window, keyed by strategy name,
    immutable and sorted. These are taken at the window's start and FROZEN: once the
    window object exists, a later config change does not rewrite it.
    ``trades`` — the resolved trades that fell in the window, ordered deterministically
    (by UTC timestamp, then by original input index for ties).
    """

    window_start: date
    window_end: date
    configs: Mapping[str, StrategyConfigSnapshot]
    trades: Tuple[ResolvedTrade, ...]

    def metrics(self) -> WindowMetrics:
        """Compute this window's realized metrics (pure, deterministic)."""
        return compute_window_metrics(self.trades)

    def to_dict(self) -> Dict[str, object]:
        return {
            "window_start": self.window_start.isoformat(),
            "window_end": self.window_end.isoformat(),
            "configs": {
                name: self.configs[name].to_dict() for name in sorted(self.configs)
            },
            "trades": [
                {
                    "strategy": t.strategy,
                    "timestamp": _as_utc_date(t.timestamp).isoformat(),
                    "pnl_usd": t.pnl_usd,
                    "is_win": t.is_win,
                    "predicted_prob": t.predicted_prob,
                    "actual_outcome": t.actual_outcome,
                }
                for t in self.trades
            ],
            "metrics": self.metrics().to_dict(),
        }


@dataclass(frozen=True)
class ReconciliationReport:
    """Realized-vs-backtest reconciliation for one window (E6 overfit primitive).

    ``realized_pnl_usd`` — the window's measured realized PnL.
    ``expected_pnl_usd`` — the BACKTEST-EXPECTED PnL for the same window+config, supplied
    by the caller. ``None`` means no expectation was recorded.
    ``divergence_usd`` — ``realized - expected`` (signed), or ``None`` if no expectation.
    ``divergence_pct`` — ``divergence_usd / |expected|`` (signed), or ``None`` if no
    expectation or if ``expected == 0`` (relative divergence is undefined against a zero
    base — we do not fabricate one).
    ``overfit_flag`` — TRI-STATE:
        * ``None``  — UNKNOWN: no backtest expectation was supplied. NOT False.
        * ``True``  — realized diverged from expected past the threshold.
        * ``False`` — within threshold.
    ``threshold_kind`` / ``threshold`` — echo the caller's threshold for auditability.
    """

    realized_pnl_usd: float
    expected_pnl_usd: Optional[float]
    divergence_usd: Optional[float]
    divergence_pct: Optional[float]
    overfit_flag: Optional[bool]
    threshold_kind: Optional[str]
    threshold: Optional[float]

    def to_dict(self) -> Dict[str, object]:
        return {
            "realized_pnl_usd": self.realized_pnl_usd,
            "expected_pnl_usd": self.expected_pnl_usd,
            "divergence_usd": self.divergence_usd,
            "divergence_pct": self.divergence_pct,
            "overfit_flag": self.overfit_flag,
            "threshold_kind": self.threshold_kind,
            "threshold": self.threshold,
        }


# ---------------------------------------------------------------------------
# Pure computation
# ---------------------------------------------------------------------------

def _ordered_trades(trades: Sequence[ResolvedTrade]) -> List[ResolvedTrade]:
    """Trades ordered deterministically: by UTC timestamp, then original input index.

    The original-index tiebreak keeps trades at the SAME instant in a stable, reproducible
    order so the in-window cumulative curve (and thus drawdown) is identical across runs
    regardless of incidental input ordering of same-instant trades.

    Ordering uses the FULL UTC timestamp (not just the calendar date): two trades on the
    same day at different times MUST order chronologically, or the order-dependent
    cumulative-PnL curve — and thus ``max_drawdown`` — is computed on the wrong sequence
    (a 3pm win booked before a 9am loss hides a real intra-day drawdown). ``_as_utc_date``
    is for WINDOW (ISO-week) bucketing only, never for intra-window ordering.
    """
    indexed = list(enumerate(trades))
    indexed.sort(key=lambda pair: (_as_utc_datetime(pair[1].timestamp), pair[0]))
    return [t for _, t in indexed]


def compute_window_metrics(trades: Sequence[ResolvedTrade]) -> WindowMetrics:
    """Compute realized metrics for the trades in a single window.

    Pure and deterministic. ``realized_pnl_usd`` is the sum of the SAME ordered per-trade
    PnL series used to build the cumulative curve for drawdown, so the total reconciles to
    the parts exactly (no rounding drift). Raises ``ValueError`` on an empty input — a
    zero-trade window is never represented as a metrics object (it is simply not emitted).
    """
    ordered = _ordered_trades(trades)
    if not ordered:
        raise ValueError(
            "compute_window_metrics: refusing to fabricate metrics for zero trades; "
            "a window with no trades is never emitted"
        )

    num_trades = len(ordered)
    num_wins = sum(1 for t in ordered if t.is_win)
    hit_rate = num_wins / num_trades

    pnl_series = [t.pnl_usd for t in ordered]
    realized = sum(pnl_series)

    # In-window cumulative curve for drawdown (reuses the portfolio aggregator's math).
    cumulative: List[float] = []
    running = 0.0
    for p in pnl_series:
        running += p
        cumulative.append(running)
    dd_usd, dd_pct = max_drawdown(cumulative)

    # Brier score over trades carrying BOTH a predicted prob and an actual outcome.
    brier_terms = [
        (t.predicted_prob - t.actual_outcome) ** 2
        for t in ordered
        if t.predicted_prob is not None and t.actual_outcome is not None
    ]
    brier_n = len(brier_terms)
    brier_score = (sum(brier_terms) / brier_n) if brier_n > 0 else None

    return WindowMetrics(
        realized_pnl_usd=realized,
        num_trades=num_trades,
        num_wins=num_wins,
        hit_rate=hit_rate,
        max_drawdown_usd=dd_usd,
        max_drawdown_pct=dd_pct,
        brier_score=brier_score,
        brier_n=brier_n,
    )


def reconcile(
    realized_pnl_usd: float,
    expected_pnl_usd: Optional[float],
    threshold: Optional[float] = None,
    threshold_kind: str = "absolute",
) -> ReconciliationReport:
    """Reconcile realized vs backtest-expected PnL; emit a tri-state ``overfit_flag``.

    Parameters
    ----------
    realized_pnl_usd:
        The window's measured realized PnL.
    expected_pnl_usd:
        The backtest-expected PnL for the same window+config, or ``None`` if none was
        recorded. We NEVER fabricate this.
    threshold:
        The divergence beyond which we flag overfit/leakage. For ``threshold_kind ==
        "absolute"`` it is a USD magnitude (``|realized - expected| > threshold``). For
        ``threshold_kind == "relative"`` it is a fraction of ``|expected|``
        (``|divergence| / |expected| > threshold``). ``None`` (or no expectation) leaves
        the flag UNKNOWN.
    threshold_kind:
        ``"absolute"`` (default) or ``"relative"``.

    Returns
    -------
    ReconciliationReport
        With a TRI-STATE ``overfit_flag``: ``None`` when no expectation (or no threshold)
        is supplied, else ``True``/``False``. This is the E6 honesty contract: absence of
        a backtest expectation is "unknown", never "not overfit".
    """
    if threshold_kind not in ("absolute", "relative"):
        raise ValueError(
            f"threshold_kind must be 'absolute' or 'relative', got {threshold_kind!r}"
        )

    # No backtest expectation => the verdict is UNKNOWN (overfit_flag=None), not
    # False/zero. We still ECHO the caller's threshold/threshold_kind for auditability
    # (reviewer F4) — the report should reflect what the caller intended to test, even
    # when no expectation was available to test it against.
    if expected_pnl_usd is None:
        return ReconciliationReport(
            realized_pnl_usd=realized_pnl_usd,
            expected_pnl_usd=None,
            divergence_usd=None,
            divergence_pct=None,
            overfit_flag=None,
            threshold_kind=threshold_kind,
            threshold=threshold,
        )

    divergence_usd = realized_pnl_usd - expected_pnl_usd
    divergence_pct: Optional[float]
    if expected_pnl_usd != 0:
        divergence_pct = divergence_usd / abs(expected_pnl_usd)
    else:
        # Relative divergence against a zero base is undefined; we do not invent one.
        divergence_pct = None

    # A threshold is required to decide the flag. Without one we have a divergence but no
    # criterion => still UNKNOWN (we refuse to pick an arbitrary cutoff).
    overfit_flag: Optional[bool]
    if threshold is None:
        overfit_flag = None
    elif threshold_kind == "absolute":
        overfit_flag = abs(divergence_usd) > threshold
    else:  # relative
        if divergence_pct is None:
            # Relative test against a zero expectation is undefined => UNKNOWN.
            overfit_flag = None
        else:
            overfit_flag = abs(divergence_pct) > threshold

    return ReconciliationReport(
        realized_pnl_usd=realized_pnl_usd,
        expected_pnl_usd=expected_pnl_usd,
        divergence_usd=divergence_usd,
        divergence_pct=divergence_pct,
        overfit_flag=overfit_flag,
        threshold_kind=threshold_kind if threshold is not None else None,
        threshold=threshold,
    )


# ---------------------------------------------------------------------------
# Window assignment + manager
# ---------------------------------------------------------------------------

def build_windows(
    trades: Sequence[ResolvedTrade],
    configs_by_strategy: Optional[Mapping[str, StrategyConfigSnapshot]] = None,
) -> List[EvaluationWindow]:
    """Assign resolved trades to ISO-week evaluation windows, deterministically.

    Each window spans ``[Monday, Monday + 7 days)`` in UTC. Only windows that contain at
    least one trade are emitted (zero-trade windows are NOT fabricated). Windows are
    returned ascending by ``window_start``; within a window, trades are ordered by UTC
    date then input order.

    ``configs_by_strategy`` is the set of config snapshots ACTIVE across these windows
    (taken at each window's start by the caller / ``WindowManager``). Each window only
    carries the snapshots for strategies that actually traded in it. The snapshot stored
    on a window is whatever was active at the window's start: once built, a window's
    config is FROZEN — see ``WindowManager`` for the boundary discipline.
    """
    configs_by_strategy = configs_by_strategy or {}

    buckets: Dict[date, List[ResolvedTrade]] = defaultdict(list)
    for t in trades:
        buckets[window_start_of(t.timestamp)].append(t)

    windows: List[EvaluationWindow] = []
    for ws in sorted(buckets):
        win_trades = _ordered_trades(buckets[ws])
        strategies_present = sorted({t.strategy for t in win_trades})
        win_configs = {
            name: configs_by_strategy[name]
            for name in strategies_present
            if name in configs_by_strategy
        }
        windows.append(
            EvaluationWindow(
                window_start=ws,
                window_end=ws + timedelta(days=7),
                configs=types.MappingProxyType(win_configs),
                trades=tuple(win_trades),
            )
        )
    return windows


@dataclass(frozen=True)
class _PendingConfigChange:
    """A config change recorded but not yet applied — it lands at the next boundary."""

    strategy: str
    snapshot: StrategyConfigSnapshot
    requested_after_window: date


class WindowManager:
    """Stateful (but deterministic) manager enforcing window-boundary config discipline.

    The discipline (VISION loop step 3): a strategy config is held STABLE for the duration
    of an evaluation window. A config change requested mid-window does NOT take effect
    immediately and does NOT rewrite the closed window — it is recorded and applied at the
    NEXT window boundary, so each window's evidence is clean.

    Usage is pure and caller-driven (no clock):
      * ``set_config(snapshot)`` before any window opens establishes the initial active
        config for a strategy.
      * ``request_config_change(snapshot, effective_after)`` records a change to apply at
        the boundary AFTER the given window-start date. It never alters an already-built
        window.
      * ``build(trades)`` assigns trades to ISO-week windows and, walking windows in
        ascending date order, applies any pending config changes whose
        ``effective_after`` is strictly before a window's start. The config a window sees
        is the config active at that window's start.

    Determinism: windows ascending by start; strategies sorted by name; pending changes
    applied in (effective_after, strategy) order. Same inputs -> identical ``to_dict``.
    """

    def __init__(self) -> None:
        self._active: Dict[str, StrategyConfigSnapshot] = {}
        self._pending: List[_PendingConfigChange] = []

    def set_config(self, snapshot: StrategyConfigSnapshot) -> None:
        """Set the initial active config for a strategy (before windows open)."""
        self._active[snapshot.name] = snapshot

    def request_config_change(
        self,
        snapshot: StrategyConfigSnapshot,
        effective_after: Union[datetime, date],
    ) -> None:
        """Record a config change to take effect at the boundary after ``effective_after``.

        ``effective_after`` is interpreted as a window-start date (normalized to its ISO
        Monday in UTC). The change applies to any window whose start is STRICTLY AFTER
        that Monday — i.e. it lands at the next boundary, never mid-window and never
        retroactively.
        """
        boundary = window_start_of(effective_after)
        self._pending.append(
            _PendingConfigChange(
                strategy=snapshot.name,
                snapshot=snapshot,
                requested_after_window=boundary,
            )
        )

    def build(self, trades: Sequence[ResolvedTrade]) -> List[EvaluationWindow]:
        """Build ordered windows, applying pending config changes at boundaries only."""
        # Bucket trades into ISO-week windows.
        buckets: Dict[date, List[ResolvedTrade]] = defaultdict(list)
        for t in trades:
            buckets[window_start_of(t.timestamp)].append(t)

        pending = sorted(
            self._pending, key=lambda c: (c.requested_after_window, c.strategy)
        )
        active = dict(self._active)

        windows: List[EvaluationWindow] = []
        for ws in sorted(buckets):
            # Apply every pending change whose boundary is strictly before this window's
            # start: it becomes effective for this and all subsequent windows. Changes
            # whose boundary == ws are NOT applied yet (they land at the NEXT boundary),
            # preserving "the config is whatever was active at the window's start".
            for change in pending:
                if change.requested_after_window < ws:
                    active[change.strategy] = change.snapshot

            win_trades = _ordered_trades(buckets[ws])
            strategies_present = sorted({t.strategy for t in win_trades})
            win_configs = {
                name: active[name]
                for name in strategies_present
                if name in active
            }
            windows.append(
                EvaluationWindow(
                    window_start=ws,
                    window_end=ws + timedelta(days=7),
                    configs=types.MappingProxyType(win_configs),
                    trades=tuple(win_trades),
                )
            )
        return windows
