"""calibration_bucket_strategy.py — the first ``model_prob != crowd`` alpha
(ROADMAP B-track; the EXP-002 ``CalibrationBucketStrategy`` factory_next_action).

WHY THIS EXISTS
Every strategy shipped so far seeds ``model_prob == crowd price``, so the walk-forward
makes 0 trades and the calibration eval is honestly degenerate. The binding constraint
for go-live is a real *decision-time* probability that DIFFERS from the crowd and is
better calibrated out-of-sample. This module produces that probability the honest way:
it fits **per-price-bucket empirical resolution rates** on a TRAINING set of
already-resolved markets, then — for a candidate market — replaces the crowd price with
the bucket's empirical YES-rate, but ONLY when that bucket has enough training samples to
be meaningful. Otherwise it ABSTAINS. It never hardcodes a reversal rate, never invents a
bucket it has no data for, and never fabricates an edge.

HONEST SCOPE (read before trusting any number this produces)
- This is a *mechanism*, not a validated edge. Fed a well-calibrated crowd it returns
  ``model_prob ~= crowd`` and trades ~nothing; fed a genuinely miscalibrated crowd (the
  EXP-002 horizon-effect hypothesis) it surfaces the gap. Whether a real gap EXISTS is an
  empirical question answered ONLY by running it on a real out-of-sample corpus (OA-11 /
  the 7-day decision-lead fetch) through ``walk_forward`` + the B2 calibration gate — NOT
  by this code and NOT on the data it was fitted on.
- LEAKAGE is prevented structurally, not by convention. The fit may only ever see markets
  that resolved strictly *before* the decision. Inside ``walk_forward`` that is GUARANTEED:
  the engine passes a ``training`` set filtered to pre-window resolutions and a
  ``MarketView`` that does not carry the ``outcome``. The live wrapper refuses to fit on
  the markets it is scanning — it requires a model pre-fitted on genuinely historical data.
- OVERFITTING is bounded by ``min_bucket_n``: a bucket with fewer than ``min_bucket_n``
  resolved training markets is treated as UNCALIBRATED and the strategy abstains there
  (the empirical rate of a handful of markets is noise, not a calibration).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from .cost_model import DEFAULT_COST_MODEL, CostModel
from .polymarket_client import Market, PolymarketClient, ScanResult
from .strategies import BaseStrategy, StrategyConfig
from .walk_forward import HistoricalMarket, MarketView, StrategyFn, TradeDecision


# ---------------------------------------------------------------------------
# Per-bucket calibration model (pure, deterministic)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class BucketStat:
    """Empirical calibration of one price bucket over a training set."""

    lo: float
    hi: float
    n: int               # resolved training markets whose crowd price fell in [lo, hi)
    yes_rate: float      # empirical P[YES] over those markets (0.0 when n == 0)
    calibrated: bool     # n >= min_bucket_n — only then is yes_rate trusted


def default_bucket_edges() -> Tuple[float, ...]:
    """Ten equal-width buckets over [0, 1]; left-inclusive, last bucket right-inclusive."""
    return tuple(round(i / 10.0, 4) for i in range(11))


class CalibrationBucketModel:
    """Fits per-price-bucket empirical resolution rates from resolved history.

    ``fit`` groups resolved markets by the bucket their *crowd price* falls into and
    records the empirical YES-rate per bucket. ``predict`` returns that empirical rate
    for a candidate price — but ONLY when the bucket is calibrated (``n >= min_bucket_n``);
    otherwise it returns ``None`` (ABSTAIN), and it also abstains for any price outside the
    bucket range. It NEVER fabricates a rate for a bucket it has insufficient data for.
    """

    def __init__(
        self,
        *,
        edges: Optional[Sequence[float]] = None,
        min_bucket_n: int = 30,
    ) -> None:
        edges = tuple(edges) if edges is not None else default_bucket_edges()
        if len(edges) < 2:
            raise ValueError("CalibrationBucketModel needs >= 2 bucket edges")
        for a, b in zip(edges, edges[1:]):
            if not (b > a):
                raise ValueError(f"bucket edges must be strictly increasing: {edges}")
        if edges[0] < 0.0 or edges[-1] > 1.0:
            raise ValueError(f"bucket edges must lie within [0, 1]: {edges}")
        if int(min_bucket_n) < 1:
            raise ValueError("min_bucket_n must be >= 1")
        self._edges: Tuple[float, ...] = tuple(float(e) for e in edges)
        self.min_bucket_n = int(min_bucket_n)
        self._stats: Optional[Tuple[BucketStat, ...]] = None

    @property
    def edges(self) -> Tuple[float, ...]:
        return self._edges

    @property
    def fitted(self) -> bool:
        return self._stats is not None

    @property
    def stats(self) -> Tuple[BucketStat, ...]:
        if self._stats is None:
            raise ValueError("CalibrationBucketModel.stats accessed before fit()")
        return self._stats

    def _bucket_index(self, price: float) -> Optional[int]:
        """Index of the bucket containing ``price``, or None if out of range.

        Buckets are left-inclusive ``[lo, hi)`` except the LAST, which is inclusive on the
        right ``[lo, hi]`` so that a price exactly at the top edge (e.g. 1.0) still maps.
        """
        if price < self._edges[0] or price > self._edges[-1]:
            return None
        last = len(self._edges) - 2
        for i in range(len(self._edges) - 1):
            lo, hi = self._edges[i], self._edges[i + 1]
            if i == last:
                if lo <= price <= hi:
                    return i
            elif lo <= price < hi:
                return i
        return None

    def fit(self, training: Sequence[HistoricalMarket]) -> "CalibrationBucketModel":
        """Compute per-bucket empirical YES-rates from resolved training markets.

        Raises ``ValueError`` on empty training data (absence of data is a setup BUG,
        distinct from a legitimate per-market abstain). Determinism: pure integer counting
        in a fixed bucket order — identical training ⇒ identical stats.
        """
        markets = list(training)
        if not markets:
            raise ValueError("CalibrationBucketModel.fit requires non-empty training data")
        n_buckets = len(self._edges) - 1
        counts = [0] * n_buckets
        yes = [0] * n_buckets
        for m in markets:
            idx = self._bucket_index(m.market_price)
            if idx is None:
                continue
            counts[idx] += 1
            if m.outcome == 1:
                yes[idx] += 1
        stats: List[BucketStat] = []
        for i in range(n_buckets):
            n = counts[i]
            rate = (yes[i] / n) if n > 0 else 0.0
            stats.append(
                BucketStat(
                    lo=self._edges[i],
                    hi=self._edges[i + 1],
                    n=n,
                    yes_rate=rate,
                    calibrated=(n >= self.min_bucket_n),
                )
            )
        self._stats = tuple(stats)
        return self

    def predict(self, market_price: float) -> Optional[float]:
        """Empirical P[YES] for ``market_price``'s bucket, or ``None`` to ABSTAIN.

        Abstains (returns None) when fit has not produced a calibrated bucket for this
        price — either the price is out of range or the bucket has ``n < min_bucket_n``.
        """
        if self._stats is None:
            raise ValueError("CalibrationBucketModel.predict called before fit()")
        idx = self._bucket_index(market_price)
        if idx is None:
            return None
        st = self._stats[idx]
        if not st.calibrated:
            return None
        return st.yes_rate


def fit_model_from_history(
    markets: Sequence[HistoricalMarket],
    *,
    edges: Optional[Sequence[float]] = None,
    min_bucket_n: int = 30,
) -> CalibrationBucketModel:
    """Convenience: build + fit a model from a resolved-history corpus (research/owner path).

    The CALLER is responsible for leakage discipline — ``markets`` must be genuinely
    historical (resolved before any market the resulting model will be used to trade).
    """
    return CalibrationBucketModel(edges=edges, min_bucket_n=min_bucket_n).fit(markets)


# ---------------------------------------------------------------------------
# Net-edge Kelly sizing on the model probability (mirrors walk_forward's default)
# ---------------------------------------------------------------------------
def _net_edge_decision(
    p_yes: float,
    market_price: float,
    cost_model: CostModel,
    min_edge: float,
    kelly_fraction: float,
) -> TradeDecision:
    """Buy the side whose cost-NET edge clears ``min_edge``, sized at fractional Kelly.

    Identical in form to ``walk_forward.make_net_edge_strategy`` so backtest EV and the
    live signal use the SAME cost-aware logic — the only difference is that ``p_yes`` is
    the calibration model's probability, not the crowd's.
    """
    yes_edge = cost_model.net_edge(p_yes, market_price)
    no_price = 1.0 - market_price
    no_edge = cost_model.net_edge(1.0 - p_yes, no_price)

    side, edge, basis = ("YES", yes_edge, market_price)
    if no_edge > yes_edge:
        side, edge, basis = ("NO", no_edge, no_price)

    if edge < min_edge:
        return TradeDecision(trade=False)

    c_eff = cost_model.effective_buy_price(basis)
    if c_eff <= 0.0 or c_eff >= 1.0:
        return TradeDecision(trade=False)
    b = (1.0 - c_eff) / c_eff
    q = p_yes if side == "YES" else (1.0 - p_yes)
    full_kelly = (b * q - (1.0 - q)) / b
    if full_kelly <= 0.0:
        return TradeDecision(trade=False)
    return TradeDecision(
        trade=True, side=side, kelly_fraction=min(full_kelly * kelly_fraction, 1.0)
    )


def make_calibration_bucket_strategy(
    *,
    edges: Optional[Sequence[float]] = None,
    min_bucket_n: int = 30,
    min_edge: float = 0.02,
    kelly_fraction: float = 0.25,
    cost_model: CostModel = DEFAULT_COST_MODEL,
) -> StrategyFn:
    """A ``walk_forward`` ``StrategyFn`` that calibrates on the (leakage-safe) training set.

    The engine hands this closure a ``training`` set already filtered to markets that
    resolved strictly before the OOS window, plus a ``MarketView`` with no outcome — so
    the fit cannot leak. It builds a FRESH model and refits on every call (pure +
    stateless — no shared mutable state across calls, so re-using the same closure on a
    different corpus is correct; the datasets are small), abstains where the price's
    bucket is uncalibrated or where the training set is empty, and otherwise trades the
    cost-net edge between the bucket's empirical rate and the crowd price.
    """

    def strategy(training: Sequence[HistoricalMarket], view: MarketView) -> TradeDecision:
        if not training:
            # Nothing to calibrate on yet (e.g. the first OOS window before any market
            # has resolved) — abstain rather than raise.
            return TradeDecision(trade=False)
        # Fresh model per call: stateless + correct under closure re-use (a shared model
        # would silently carry a prior call's fit — reviewer MUST-FIX).
        model = CalibrationBucketModel(edges=edges, min_bucket_n=min_bucket_n).fit(training)
        model_prob = model.predict(view.market_price)
        if model_prob is None:
            return TradeDecision(trade=False)
        return _net_edge_decision(
            model_prob, view.market_price, cost_model, min_edge, kelly_fraction
        )

    return strategy


# ---------------------------------------------------------------------------
# Live-scan wrapper (honest: abstains entirely without a pre-fitted model)
# ---------------------------------------------------------------------------
def _yes_outcome_index(market: Market) -> Optional[int]:
    """Index of the YES outcome (label match), or None if the market isn't a clear
    binary YES/NO — the bucket model is defined on P[YES], so we refuse ambiguous markets
    rather than guess."""
    if not market.is_binary:
        return None
    for i, o in enumerate(market.outcomes):
        if o.label.strip().lower() in ("yes", "y", "true"):
            return i
    return None


class CalibrationBucketStrategy(BaseStrategy):
    """Live-scan wrapper around a PRE-FITTED ``CalibrationBucketModel``.

    The model must be fitted on genuinely historical resolved markets (never on the
    markets being scanned — that would be look-ahead). With ``model=None`` (or an unfitted
    model) the strategy ABSTAINS entirely (``scan`` returns ``[]``): it never fabricates a
    signal, so it is safe to leave UNWIRED in the default scanner until a real fitted model
    exists — an empty strategy is honest, a faked one is not (DECISION COROLLARY).
    """

    def __init__(
        self,
        client: PolymarketClient,
        config: StrategyConfig,
        *,
        model: Optional[CalibrationBucketModel] = None,
        min_edge: float = 0.02,
        cost_model: CostModel = DEFAULT_COST_MODEL,
    ) -> None:
        super().__init__(client, config)
        self._model = model
        self.min_edge = min_edge
        self._cost_model = cost_model

    @property
    def name(self) -> str:
        return "calibration_bucket"

    def scan(self, markets: List[Market]) -> List[ScanResult]:
        results: List[ScanResult] = []
        if self._model is None or not self._model.fitted:
            # Honest abstain — no calibration fitted, so no edge can be claimed.
            return results
        for market in markets:
            # Respect the venue/parser tradeability signal like every other deployed
            # strategy (NearCertainty, CrossMarketArb, NOPositionScanner, …). A market the
            # parser marked untradeable (active=False — e.g. inconsistent/incomplete outcome
            # arrays) must NEVER produce a signal here: for a non-price failure mode (a length
            # mismatch / missing token_id) the YES price is still a real in-range value, so
            # without this gate the honesty guard would leak through this consumer once it is
            # wired with a fitted model.
            if not market.active or market.closed:
                continue
            yes_idx = _yes_outcome_index(market)
            if yes_idx is None:
                continue
            crowd = market.outcomes[yes_idx].price
            if not (0.0 < crowd < 1.0):
                continue
            model_prob = self._model.predict(crowd)
            if model_prob is None:
                continue  # uncalibrated bucket — abstain on this market
            decision = _net_edge_decision(
                model_prob, crowd, self._cost_model, self.min_edge, kelly_fraction=1.0
            )
            if not decision.trade:
                continue
            # _yes_outcome_index only returns non-None for a binary (exactly-2-outcome)
            # market, so the NO leg is unambiguously the other index.
            no_idx = 1 - yes_idx
            outcome_idx = yes_idx if decision.side == "YES" else no_idx
            basis = crowd if decision.side == "YES" else (1.0 - crowd)
            edge = self._cost_model.net_edge(
                model_prob if decision.side == "YES" else (1.0 - model_prob), basis
            )
            results.append(
                ScanResult(
                    market=market,
                    strategy=self.name,
                    outcome_idx=outcome_idx,
                    side="BUY",
                    entry_price=market.outcomes[outcome_idx].price,
                    expected_value=model_prob if decision.side == "YES" else (1.0 - model_prob),
                    edge=edge,
                    confidence=min(max(edge / max(self.min_edge, 1e-9), 0.0), 1.0),
                    reason=(
                        f"calibration bucket: empirical P[YES]={model_prob:.3f} vs "
                        f"crowd={crowd:.3f} → BUY {decision.side} (net edge {edge:.3f})"
                    ),
                )
            )
        return results


__all__ = [
    "BucketStat",
    "CalibrationBucketModel",
    "CalibrationBucketStrategy",
    "default_bucket_edges",
    "fit_model_from_history",
    "make_calibration_bucket_strategy",
]
