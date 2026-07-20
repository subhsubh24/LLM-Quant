"""spike_robustness_surface.py — EXP-006 pre-registered config robustness surface.

WHY THIS EXISTS
The first real-data EXP-006 fade-the-spike run (2026-07-19c, #390) reported
**EDGE-NOT-PROVEN** at the pre-registered DEFAULT config (threshold 0.10, window 1h,
horizon 24h): N=108, net +$285.44, but F11 ``indistinguishable_from_zero`` and F10 fragile
(``docs/autonomous-loop/EXP006_REAL_DATA_VALIDATION.md``). That single cell leaves one honest
question open, and both the ROADMAP (E3) and the EXP-006 writeup file it as the very next
buildable step: **is the null a fluke of the default knobs, or is the whole fade-the-spike
config family null?** This module answers it by running the SAME committed corpus through a
PRE-REGISTERED grid of (threshold × window × horizon) configs, reporting EVERY cell, and
selecting NONE.

READ THIS — WHAT THIS SURFACE CAN AND CANNOT CONCLUDE
- **It reuses the SINGLE committed corpus.** It is therefore a WITHIN-SAMPLE
  config-sensitivity MAP, not an out-of-sample test. **No cell here can ever constitute a
  validated edge, however green** — an in-sample sweep that finds a green cell has, by
  construction, searched for it. The ONLY conclusions this surface can support are:
  (a) whether the default's EDGE-NOT-PROVEN is config-fragile or config-family-wide, and
  (b) whether any region is promising enough to justify a FRESH, pre-registered OOS on
  genuinely NEW data (a different corpus / era). It NEVER reaches a revenue field and NEVER
  sets a validated-edge flag at the family level.
- **Selecting the greenest cell and calling it an edge is textbook p-hacking and is
  FORBIDDEN.** With K cells searched, some pass by chance alone: under the global null (no
  reversion edge anywhere in the family) the F11 CI excludes zero on the positive side with
  probability ≤ ``alpha/2`` per cell, so ≈ ``K·alpha/2`` cells go green by luck — and the
  AND with F10-non-fragility and hit>50% only lowers that. A green count within this chance
  band is CONSISTENT WITH NO EDGE. The surface computes this expectation and refuses to
  promote any cell.
- **The cells are NOT independent** (overlapping configs on the same corpus share trades), so
  the chance expectation is a conservative descriptor, not a formal multiple-comparisons test.
  The load-bearing safeguard is simpler and absolute: this is in-sample, so nothing here is an
  edge.

DESIGN — HONEST BY CONSTRUCTION
- The grid is PRE-REGISTERED as module constants below, chosen first-principles to BRACKET the
  default (0.10 / 1h / 24h), NOT tuned on any result. Every cell is reported; none is dropped.
- Horizons are held at or below the 24h default so the fade engine's horizon-axis F10
  exclusion (legitimate only while the horizon is structurally single-valued, ≤ 1 day) applies
  uniformly — every cell gets the SAME fair F10 treatment rather than some cells carrying a
  structural always-fragile horizon flag.
- ``max_trades_per_market`` stays at the honest **1** for every cell (raising it feeds
  correlated same-market trades into F11 as if independent — see ``spike_reversal_backtest``).
- Category labels are passed through when supplied, engaging the F10 category-slice axis, which
  makes each cell's fragility check STRICTER than the headline default run (which omitted them).
- Pure + deterministic: stdlib + the fade engine only; the engine is itself deterministic
  (sorted iteration, seeded bootstrap), so the same corpus + same grid ⇒ byte-identical surface.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Mapping, Optional, Sequence, Tuple

from .spike_detection import (
    DEFAULT_REVERSAL_HORIZON_SECONDS,
    DEFAULT_SPIKE_THRESHOLD,
    DEFAULT_WINDOW_SECONDS,
)
from .spike_reversal_backtest import (
    FadeSpikeConfig,
    backtest_fade_the_spike,
)

# ---------------------------------------------------------------------------
# PRE-REGISTERED GRID — bracketing the default (0.10 / 3600s / 86400s), first-principles,
# NOT tuned on any result. Fixed here so a reader can verify no post-hoc cell was added.
# ---------------------------------------------------------------------------
# Spike thresholds (absolute probability move to trigger a spike). Brackets the 0.10 default
# from a small 5-point swing to a large 20-point swing.
PRE_REGISTERED_THRESHOLDS: Tuple[float, ...] = (0.05, 0.08, 0.10, 0.15, 0.20)
# Spike detection windows (seconds): 30m / 1h(default) / 2h / 6h — how fast the move must occur.
PRE_REGISTERED_WINDOWS_SECONDS: Tuple[int, ...] = (1800, 3600, 7200, 21600)
# Reversal horizons (seconds): 6h / 12h / 24h(default). ALL are ≤ the 24h default so the fade
# engine's horizon-axis F10 exclusion applies uniformly and every cell gets a fair F10 (see
# module docstring). Longer horizons would re-engage a structurally-single-valued horizon check
# and trivially flag fragility, muddying the map — deliberately excluded.
PRE_REGISTERED_HORIZONS_SECONDS: Tuple[int, ...] = (21600, 43200, 86400)


@dataclass(frozen=True)
class SurfaceCell:
    """One (threshold, window, horizon) config's honest fade-the-spike verdict on the corpus.

    Every field is copied verbatim from the fade engine's ``SpikeReversalResult`` — this module
    tabulates, it never re-implements or overrides the gate. ``is_validated_edge`` is the
    engine's own AND-of-gates (N≥floor ∧ F11 significant_positive ∧ F10 non-fragile ∧
    hit>50%); at the FAMILY level it is still NOT an edge (in-sample — see module docstring)."""

    threshold: float
    window_seconds: int
    horizon_seconds: int
    is_default: bool
    n_trades: int
    n_markets_traded: int
    total_pnl_usd: float
    hit_rate: Optional[float]
    f11_verdict: str
    f11_ci_low: Optional[float]
    f11_ci_high: Optional[float]
    f10_fragile: Optional[bool]
    f10_fragile_reasons: Tuple[str, ...]
    size_robustness: str
    is_validated_edge: bool


@dataclass(frozen=True)
class RobustnessSurface:
    """The full, honest config-sensitivity map over the pre-registered grid.

    ``family_verdict`` is one of:
      - ``FAMILY-NULL-STRONG``            — zero cells validate; the default null is
                                            config-family-wide, not a default artifact.
      - ``FAMILY-NULL-WITHIN-CHANCE``     — 1..⌈chance⌉ cells validate; consistent with the
                                            global null (green cells are expected by luck at
                                            this search size). NOT an edge.
      - ``HYPOTHESES-FLAGGED-NOT-AN-EDGE``— more green cells than chance expects. These are
                                            candidates for a FRESH pre-registered OOS on NEW
                                            data ONLY; this in-sample surface still claims NO
                                            edge and reaches no revenue field.
    """

    cells: Tuple[SurfaceCell, ...]
    k_cells: int
    n_validated: int
    n_positive_pnl: int
    n_f11_significant_positive: int
    n_f11_significant_negative: int
    n_f10_fragile: int
    default_cell: Optional[SurfaceCell]
    # Conservative expected count of chance-green cells under the global null (≈ K·alpha/2);
    # a descriptor, not a formal test (cells are correlated). See module docstring.
    chance_green_expectation: float
    validated_cells: Tuple[SurfaceCell, ...]
    family_verdict: str
    caveats: Tuple[str, ...]


_IN_SAMPLE_CAVEATS: Tuple[str, ...] = (
    "IN-SAMPLE: this reuses the single committed corpus; no cell can be a validated edge, "
    "however green — an OOS claim requires a FRESH corpus / era.",
    "SELECTION FORBIDDEN: picking the greenest cell to claim an edge is p-hacking; the "
    "chance_green_expectation shows how many cells go green by luck at this search size.",
    "CORRELATED CELLS: overlapping configs on one corpus share trades, so the chance "
    "expectation is a conservative descriptor, not a formal multiple-comparisons test.",
    "NO REVENUE FIELD: the family verdict never sets a validated edge and never reaches "
    "weekly_pnl / total_trades — it advances the research question only.",
)


def run_robustness_surface(
    ticks_by_market: Mapping[str, Sequence[Mapping]],
    *,
    category_by_market: Optional[Mapping[str, str]] = None,
    thresholds: Sequence[float] = PRE_REGISTERED_THRESHOLDS,
    windows_seconds: Sequence[int] = PRE_REGISTERED_WINDOWS_SECONDS,
    horizons_seconds: Sequence[int] = PRE_REGISTERED_HORIZONS_SECONDS,
) -> RobustnessSurface:
    """Run the fade engine across the pre-registered grid and return the honest surface.

    Deterministic: cells are generated in a fixed (threshold, window, horizon) sorted order and
    the engine is itself deterministic, so the same corpus + grid ⇒ identical surface. The
    surface NEVER claims an edge (in-sample) — see the module docstring.
    """
    # Fixed, reproducible cell order.
    grid = sorted(
        (t, w, h)
        for t in thresholds
        for w in windows_seconds
        for h in horizons_seconds
    )
    cells: List[SurfaceCell] = []
    alpha_seen: Optional[float] = None
    for threshold, window, horizon in grid:
        cfg = FadeSpikeConfig(
            threshold=threshold,
            window_seconds=window,
            horizon_seconds=horizon,
        )
        res = backtest_fade_the_spike(
            ticks_by_market, config=cfg, category_by_market=category_by_market
        )
        sig = res.significance
        if alpha_seen is None:
            alpha_seen = sig.alpha
        is_default = (
            threshold == DEFAULT_SPIKE_THRESHOLD
            and window == DEFAULT_WINDOW_SECONDS
            and horizon == DEFAULT_REVERSAL_HORIZON_SECONDS
        )
        cells.append(
            SurfaceCell(
                threshold=threshold,
                window_seconds=window,
                horizon_seconds=horizon,
                is_default=is_default,
                n_trades=res.n_trades,
                n_markets_traded=res.n_markets_traded,
                total_pnl_usd=res.total_pnl_usd,
                hit_rate=res.hit_rate,
                f11_verdict=sig.verdict,
                f11_ci_low=sig.total_ci_low,
                f11_ci_high=sig.total_ci_high,
                f10_fragile=(res.regime.fragile if res.regime is not None else None),
                f10_fragile_reasons=(
                    tuple(res.regime.fragile_reasons) if res.regime is not None else ()
                ),
                size_robustness=res.size_robustness,
                is_validated_edge=res.is_validated_edge,
            )
        )

    k = len(cells)
    validated = tuple(c for c in cells if c.is_validated_edge)
    n_validated = len(validated)
    # Conservative chance expectation: F11 excludes zero on the positive side with prob ≤
    # alpha/2 per cell under the null; the AND with F10 + hit>50% only reduces it. Default
    # alpha 0.05 ⇒ 0.025/cell. If no cell produced a significance object (empty corpus), the
    # expectation is 0.
    per_cell_false_green = (alpha_seen / 2.0) if alpha_seen is not None else 0.0
    chance = k * per_cell_false_green
    chance_ceiling = math.ceil(chance)

    if n_validated == 0:
        family_verdict = "FAMILY-NULL-STRONG"
    elif n_validated <= chance_ceiling:
        family_verdict = "FAMILY-NULL-WITHIN-CHANCE"
    else:
        family_verdict = "HYPOTHESES-FLAGGED-NOT-AN-EDGE"

    default_cell = next((c for c in cells if c.is_default), None)

    return RobustnessSurface(
        cells=tuple(cells),
        k_cells=k,
        n_validated=n_validated,
        n_positive_pnl=sum(1 for c in cells if c.total_pnl_usd > 0.0),
        n_f11_significant_positive=sum(
            1 for c in cells if c.f11_verdict == "significant_positive"
        ),
        n_f11_significant_negative=sum(
            1 for c in cells if c.f11_verdict == "significant_negative"
        ),
        n_f10_fragile=sum(1 for c in cells if c.f10_fragile is True),
        default_cell=default_cell,
        chance_green_expectation=round(chance, 4),
        validated_cells=validated,
        family_verdict=family_verdict,
        caveats=_IN_SAMPLE_CAVEATS,
    )


def summarize(surface: RobustnessSurface) -> str:
    """Human-readable, always-honest one-block summary of the surface."""
    lines: List[str] = []
    lines.append(
        f"EXP-006 robustness surface: {surface.k_cells} pre-registered cells "
        f"(threshold × window × horizon), SAME committed corpus (IN-SAMPLE)."
    )
    dc = surface.default_cell
    if dc is not None:
        lines.append(
            f"default cell (0.10/1h/24h): N={dc.n_trades} net ${dc.total_pnl_usd:,.2f} "
            f"hit {dc.hit_rate} F11={dc.f11_verdict} F10_fragile={dc.f10_fragile} "
            f"validated={dc.is_validated_edge}"
        )
    lines.append(
        f"cells positive-PnL: {surface.n_positive_pnl}/{surface.k_cells} | "
        f"F11 significant_positive: {surface.n_f11_significant_positive} | "
        f"significant_negative: {surface.n_f11_significant_negative} | "
        f"F10 fragile: {surface.n_f10_fragile}/{surface.k_cells}"
    )
    lines.append(
        f"validated cells (engine AND-gate): {surface.n_validated} "
        f"(chance-green expectation ≈ {surface.chance_green_expectation})"
    )
    lines.append(f"FAMILY VERDICT: {surface.family_verdict}")
    if surface.validated_cells:
        lines.append(
            "  green cells (HYPOTHESES for FRESH-DATA OOS ONLY — NOT an edge): "
            + "; ".join(
                f"t={c.threshold} w={c.window_seconds}s h={c.horizon_seconds}s "
                f"(N={c.n_trades}, ${c.total_pnl_usd:,.2f})"
                for c in surface.validated_cells
            )
        )
    lines.append("CAVEATS: " + " | ".join(surface.caveats))
    return "\n".join(lines)
