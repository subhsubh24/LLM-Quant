"""recency_weighted_bucket_strategy.py — a recency-weighted per-bucket calibration
alpha (ROADMAP B4a-revised; the pre-registered follow-up to the REFUTED EXP-002).

WHY THIS EXISTS
The first ``model_prob != crowd`` alpha — ``CalibrationBucketStrategy`` (EXP-002) — was
tested on real data for the first time in Research Run 14 (2026-07-04, N=510) and
**REFUTED**: it lost money out-of-sample (walk-forward net −$2,938; static-split Brier
significantly WORSE than the crowd). The diagnosed cause was NOT "no calibration edge
exists" — it was the specific mechanism. EXP-002 replaces the crowd price with a bucket's
**all-time** empirical YES-rate; but the true resolution rate of a bucket appears
TIME-VARYING (the research-run diagnosis: the dominant ``[0, 0.1)`` bucket resolved YES at
1.0% in the 2024-01→2026-01 training slice but 7.59% in the 2026-01→2026-06 OOS slice), so
an all-time average is a LAGGING estimate — it replaces the crowd's own live (and, on that
corpus, less-wrong) price with a staler number.

THE REVISED, PRE-REGISTERED HYPOTHESIS (falsifiable — recorded in RESEARCH_MEMORY BEFORE
any real-data run of this module)
A bucket model that weights RECENT resolved training markets more heavily — an exponential
recency decay on each training market's ``resolution_time`` relative to the decision time —
tracks a time-varying true rate better than an all-time average, and so produces a
better-calibrated decision-time probability than the crowd on a bucket whose true rate has
drifted. PRE-REGISTERED PARAMETERS (chosen from first principles, NOT tuned on any test
set): ``half_life_days = 60`` (prediction-market regimes shift on a monthly-to-quarterly
scale; 60 days balances sample size against drift-tracking), ``min_effective_n = 30`` (the
same Kish effective-sample-size floor the shipped EXP-002 model uses), 10 equal-width
buckets over [0, 1] (same as EXP-002 for apples-to-apples comparability), and the SAME
cost-net Kelly sizing (``min_edge = 0.02``, ``kelly_fraction = 0.25``). Only ONE new degree
of freedom (``half_life_days``) is introduced, and it is fixed by first principles.

HONEST SCOPE (read before trusting any number this produces)
* This is a *mechanism*, not a validated edge. Whether recency-weighting actually beats the
  crowd is an empirical question answered ONLY by running it ONCE on a real out-of-sample
  corpus (egress-permitted) through ``walk_forward`` + the B2 calibration gate — NOT by this
  code, NOT on the data it was fitted on, and NOT by re-tuning ``half_life_days`` after
  seeing a result (that would be the p-hacking EXP-002's refutation explicitly warns against).
* LEAKAGE is prevented structurally, exactly as in EXP-002. Inside ``walk_forward`` the fit
  may only ever see markets that resolved strictly before the decision window (the engine
  passes a ``training`` set filtered to pre-window resolutions and a ``MarketView`` that
  carries no ``outcome``). The recency weight uses each TRAINING market's ``resolution_time``
  (all in the past relative to the candidate's ``decision_time``) — it reads no future
  information. The live wrapper refuses to signal without a model pre-fitted on genuinely
  historical data.
* OVERFITTING is bounded by ``min_effective_n`` on the Kish effective sample size (a few
  heavily-weighted recent markets do NOT clear the floor), and the strategy ABSTAINS on any
  bucket below it — it never fabricates a rate for a bucket it has too little (weighted) data
  for, and never hardcodes a reversal rate.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Sequence, Tuple

# Deliberate reuse of EXP-002's cost-net Kelly sizing + YES-index resolution so the two
# calibration alphas size IDENTICALLY and any OOS difference is attributable to the
# recency-weighting mechanism ALONE (apples-to-apples), not a sizing divergence.
from .calibration_bucket_strategy import _net_edge_decision, _yes_outcome_index
from .cost_model import DEFAULT_COST_MODEL, CostModel
from .polymarket_client import Market, PolymarketClient, ScanResult
from .strategies import BaseStrategy, StrategyConfig
from .walk_forward import HistoricalMarket, MarketView, StrategyFn, TradeDecision

_SECONDS_PER_DAY = 86400.0


def default_bucket_edges() -> Tuple[float, ...]:
    """Ten equal-width buckets over [0, 1]; left-inclusive, last bucket right-inclusive."""
    return tuple(round(i / 10.0, 4) for i in range(11))


@dataclass(frozen=True)
class RecencyBucketStat:
    """Recency-weighted empirical calibration of one price bucket."""

    lo: float
    hi: float
    weighted_n: float        # sum of recency weights over training markets in [lo, hi)
    effective_n: float       # Kish effective sample size (Σw)^2 / Σ(w^2)
    yes_rate: float          # recency-weighted empirical P[YES] (0.0 when weighted_n == 0)
    calibrated: bool         # effective_n >= min_effective_n — only then is yes_rate trusted


class RecencyWeightedBucketModel:
    """Fits per-price-bucket recency-WEIGHTED empirical resolution rates.

    ``fit(training, as_of)`` groups resolved markets by the bucket their *crowd price* falls
    into and records a recency-weighted empirical YES-rate per bucket, weighting each
    training market ``m`` by ``0.5 ** (age_days / half_life_days)`` where
    ``age_days = (as_of - m.resolution_time)`` in days (clamped at 0 — a market that somehow
    resolved after ``as_of`` gets full weight, never a negative/inflating one). ``predict``
    returns that rate for a candidate price — but ONLY when the bucket's Kish effective
    sample size clears ``min_effective_n``; otherwise it returns ``None`` (ABSTAIN), as it
    does for any price outside the bucket range. It NEVER fabricates a rate.
    """

    def __init__(
        self,
        *,
        edges: Optional[Sequence[float]] = None,
        half_life_days: float = 60.0,
        min_effective_n: float = 30.0,
    ) -> None:
        edges = tuple(edges) if edges is not None else default_bucket_edges()
        if len(edges) < 2:
            raise ValueError("RecencyWeightedBucketModel needs >= 2 bucket edges")
        for a, b in zip(edges, edges[1:]):
            if not (b > a):
                raise ValueError(f"bucket edges must be strictly increasing: {edges}")
        if edges[0] < 0.0 or edges[-1] > 1.0:
            raise ValueError(f"bucket edges must lie within [0, 1]: {edges}")
        if not (float(half_life_days) > 0.0):
            raise ValueError("half_life_days must be > 0")
        if float(min_effective_n) < 1.0:
            raise ValueError("min_effective_n must be >= 1")
        self._edges: Tuple[float, ...] = tuple(float(e) for e in edges)
        self.half_life_days = float(half_life_days)
        self.min_effective_n = float(min_effective_n)
        self._stats: Optional[Tuple[RecencyBucketStat, ...]] = None

    @property
    def edges(self) -> Tuple[float, ...]:
        return self._edges

    @property
    def fitted(self) -> bool:
        return self._stats is not None

    @property
    def stats(self) -> Tuple[RecencyBucketStat, ...]:
        if self._stats is None:
            raise ValueError("RecencyWeightedBucketModel.stats accessed before fit()")
        return self._stats

    def _bucket_index(self, price: float) -> Optional[int]:
        """Index of the bucket containing ``price``, or None if out of range.

        Buckets are left-inclusive ``[lo, hi)`` except the LAST, which is inclusive on the
        right ``[lo, hi]`` so a price exactly at the top edge (e.g. 1.0) still maps.
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

    def _weight(self, resolution_time: datetime, as_of: datetime) -> float:
        """Exponential recency weight for a training market that resolved at
        ``resolution_time``, viewed from ``as_of``. Age is clamped at 0 so a training
        market cannot receive a weight > 1 (it never sees the future either way — inside
        walk_forward every training market resolved before the window)."""
        age_days = (as_of - resolution_time).total_seconds() / _SECONDS_PER_DAY
        if age_days < 0.0:
            age_days = 0.0
        return 0.5 ** (age_days / self.half_life_days)

    def fit(
        self, training: Sequence[HistoricalMarket], as_of: datetime
    ) -> "RecencyWeightedBucketModel":
        """Compute per-bucket recency-weighted empirical YES-rates from resolved training
        markets, viewed from ``as_of`` (the decision time).

        Raises ``ValueError`` on empty training data (absence of data is a setup BUG,
        distinct from a legitimate per-market abstain). Determinism: floating weights are
        accumulated in a FIXED market order (the input order) within a fixed bucket order —
        identical ``(training, as_of)`` ⇒ identical stats.
        """
        markets = list(training)
        if not markets:
            raise ValueError(
                "RecencyWeightedBucketModel.fit requires non-empty training data"
            )
        n_buckets = len(self._edges) - 1
        sum_w = [0.0] * n_buckets          # Σ w
        sum_w2 = [0.0] * n_buckets         # Σ w^2   (for the Kish effective sample size)
        sum_w_yes = [0.0] * n_buckets      # Σ w · 1[outcome == 1]
        for m in markets:
            idx = self._bucket_index(m.market_price)
            if idx is None:
                continue
            w = self._weight(m.resolution_time, as_of)
            sum_w[idx] += w
            sum_w2[idx] += w * w
            if m.outcome == 1:
                sum_w_yes[idx] += w
        stats: List[RecencyBucketStat] = []
        for i in range(n_buckets):
            w_tot = sum_w[i]
            rate = (sum_w_yes[i] / w_tot) if w_tot > 0.0 else 0.0
            eff_n = (w_tot * w_tot / sum_w2[i]) if sum_w2[i] > 0.0 else 0.0
            stats.append(
                RecencyBucketStat(
                    lo=self._edges[i],
                    hi=self._edges[i + 1],
                    weighted_n=w_tot,
                    effective_n=eff_n,
                    yes_rate=rate,
                    calibrated=(eff_n >= self.min_effective_n),
                )
            )
        self._stats = tuple(stats)
        return self

    def predict(self, market_price: float) -> Optional[float]:
        """Recency-weighted empirical P[YES] for ``market_price``'s bucket, or ``None`` to
        ABSTAIN (price out of range, or the bucket's effective sample size is below the
        floor)."""
        if self._stats is None:
            raise ValueError("RecencyWeightedBucketModel.predict called before fit()")
        idx = self._bucket_index(market_price)
        if idx is None:
            return None
        st = self._stats[idx]
        if not st.calibrated:
            return None
        return st.yes_rate


def fit_recency_model_from_history(
    markets: Sequence[HistoricalMarket],
    as_of: datetime,
    *,
    edges: Optional[Sequence[float]] = None,
    half_life_days: float = 60.0,
    min_effective_n: float = 30.0,
) -> RecencyWeightedBucketModel:
    """Convenience: build + fit a recency-weighted model from a resolved-history corpus.

    The CALLER is responsible for leakage discipline — ``markets`` must be genuinely
    historical (resolved before any market the resulting model will be used to trade), and
    ``as_of`` must be a decision time at-or-after every training market's resolution.
    """
    return RecencyWeightedBucketModel(
        edges=edges, half_life_days=half_life_days, min_effective_n=min_effective_n
    ).fit(markets, as_of)


def make_recency_weighted_bucket_strategy(
    *,
    edges: Optional[Sequence[float]] = None,
    half_life_days: float = 60.0,
    min_effective_n: float = 30.0,
    min_edge: float = 0.02,
    kelly_fraction: float = 0.25,
    cost_model: CostModel = DEFAULT_COST_MODEL,
) -> StrategyFn:
    """A ``walk_forward`` ``StrategyFn`` that recency-weights the (leakage-safe) training set.

    The engine hands this closure a ``training`` set already filtered to markets that
    resolved strictly before the OOS window, plus a ``MarketView`` with no outcome — so the
    fit cannot leak. It builds a FRESH model and refits on every call, anchoring the recency
    weights on the CANDIDATE'S ``view.decision_time`` (so each decision weights training
    history by recency AS OF that decision), abstains where the price's bucket has too little
    effective data or the training set is empty, and otherwise trades the cost-net edge
    between the bucket's recency-weighted rate and the crowd price — using the SAME sizing as
    EXP-002.
    """

    def strategy(training: Sequence[HistoricalMarket], view: MarketView) -> TradeDecision:
        if not training:
            # Nothing to calibrate on yet (the first OOS window before any market has
            # resolved) — abstain rather than raise.
            return TradeDecision(trade=False)
        model = RecencyWeightedBucketModel(
            edges=edges, half_life_days=half_life_days, min_effective_n=min_effective_n
        ).fit(training, view.decision_time)
        model_prob = model.predict(view.market_price)
        if model_prob is None:
            return TradeDecision(trade=False)
        return _net_edge_decision(
            model_prob, view.market_price, cost_model, min_edge, kelly_fraction
        )

    return strategy


class RecencyWeightedBucketStrategy(BaseStrategy):
    """Live-scan wrapper around a PRE-FITTED ``RecencyWeightedBucketModel``.

    The model must be fitted on genuinely historical resolved markets (never on the markets
    being scanned — that would be look-ahead). With ``model=None`` (or an unfitted model) the
    strategy ABSTAINS entirely (``scan`` returns ``[]``): it never fabricates a signal, so it
    is safe to leave UNWIRED in the default scanner until a real fitted model + a validated
    OOS edge exist — an empty strategy is honest, a faked one is not (DECISION COROLLARY).
    Mirrors ``CalibrationBucketStrategy`` exactly, including the tradeability gate.
    """

    def __init__(
        self,
        client: PolymarketClient,
        config: StrategyConfig,
        *,
        model: Optional[RecencyWeightedBucketModel] = None,
        min_edge: float = 0.02,
        cost_model: CostModel = DEFAULT_COST_MODEL,
    ) -> None:
        super().__init__(client, config)
        self._model = model
        self.min_edge = min_edge
        self._cost_model = cost_model

    @property
    def name(self) -> str:
        return "recency_weighted_bucket"

    def scan(self, markets: List[Market]) -> List[ScanResult]:
        results: List[ScanResult] = []
        if self._model is None or not self._model.fitted:
            # Honest abstain — no calibration fitted, so no edge can be claimed.
            return results
        for market in markets:
            # Respect the venue/parser tradeability signal like every other deployed
            # strategy — a market the parser marked untradeable (active=False) must NEVER
            # produce a signal, even though its YES price may still be an in-range value.
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
                continue  # under-sampled bucket — abstain on this market
            decision = _net_edge_decision(
                model_prob, crowd, self._cost_model, self.min_edge, kelly_fraction=1.0
            )
            if not decision.trade:
                continue
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
                        f"recency-weighted bucket: P[YES]={model_prob:.3f} vs "
                        f"crowd={crowd:.3f} → BUY {decision.side} (net edge {edge:.3f})"
                    ),
                )
            )
        return results


__all__ = [
    "RecencyBucketStat",
    "RecencyWeightedBucketModel",
    "RecencyWeightedBucketStrategy",
    "default_bucket_edges",
    "fit_recency_model_from_history",
    "make_recency_weighted_bucket_strategy",
]
