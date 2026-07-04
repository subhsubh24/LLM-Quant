"""polymarket_history_fetcher.py — leakage-safe ingestion of REAL resolved
Polymarket history into ``walk_forward.HistoricalMarket`` records (ROADMAP A2 /
EXP-001).

WHY THIS EXISTS
``walk_forward`` is an honest backtest ENGINE but it has nothing real to chew on:
the repo ships no committed dataset of resolved markets, so the "validated OOS
edge >= floor" Definition-of-Done box stays unchecked. That box is the named
blocking dependency for ALL out-of-sample validation. This module is the missing
ingest: it pulls genuinely resolved binary Polymarket markets plus a
PRE-resolution crowd-price snapshot, and assembles them into the exact
``HistoricalMarket`` shape the walk-forward backtest + calibration eval consume.

HONEST SCOPE
This module INGESTS real resolved history when network access is available; it
does NOT itself prove any edge — fed to the backtest it produces a naive
crowd-baseline (``model_prob`` defaults to the crowd price), which by construction
has ~zero edge until a real strategy overrides ``model_prob``. In some execution
environments outbound access to Polymarket is restricted by egress policy (an
owner/runbook concern), so the fetch path may need to run where network is
permitted. The PARSING and LEAKAGE-SAFETY logic is what matters for correctness,
and it is fully unit-tested offline with a mocked HTTP session (no real network).

RESEARCH-INTEGRITY CAVEATS (read before trusting any eval built on this data)
* SELECTION / SURVIVORSHIP BIAS: ``fetch_resolved_markets`` keeps only markets whose
  ``outcomePrices`` are UNAMBIGUOUSLY settled (~[1,0]/[0,1]). It therefore EXCLUDES
  contested / re-resolved / UMA-disputed / cancelled markets — which are exactly the
  cases where the crowd was most wrong near resolution. The resulting sample is biased
  TOWARD clean, crowd-friendly outcomes, so any measured crowd calibration on it is an
  OPTIMISTIC upper bound. A calibration/edge eval must disclose this and not treat the
  sample as representative of all resolutions.
* LATE-LIFE PRICE PINNING: Polymarket prices often pin to ~1.0/~0.0 well before the
  official ``endDate``. If ``decision_lead`` is too small, ``decision_time`` lands after
  the price has pinned, so ``market_price`` ≈ the answer (a contemporaneous price, not
  look-ahead, but it inflates apparent crowd calibration and shrinks model headroom).
  Choose a ``decision_lead`` large relative to typical market lifetime so the decision
  is sampled while the market is still genuinely uncertain.
* CATEGORY SUBSETTING IS A P-HACKING LEVER: the ``categories`` filter must be
  PRE-REGISTERED, never chosen after seeing which category looks best — post-hoc
  selection on the test set is textbook p-hacking and requires multiple-comparison
  correction.

THE ANTI-LEAKAGE GUARANTEE (the whole point — an auditor WILL attack this)
A resolved market's ``outcomePrices`` have already settled to ≈[1,0] or ≈[0,1].
Using that settled price as the decision-time crowd price would be 100%
look-ahead leakage — you'd be "predicting" with the answer. So ``market_price``
is NEVER taken from the resolved outcome price. It is taken ONLY from a CLOB
price-history tick whose timestamp is at-or-before ``decision_time`` AND strictly
before ``resolution_time``. If no such pre-resolution tick exists, we RAISE (single
record) or skip with a loud warning (batch) — we never fabricate a price.

CI-SAFETY
Imports only ``requests`` + stdlib + ``HistoricalMarket``. No pandas / numpy /
backtest deps (absent from CI).
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional, Sequence

import requests

from .walk_forward import HistoricalMarket

logger = logging.getLogger(__name__)

# API endpoints — mirror polymarket_client.py.
GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"

# Gamma's ``/markets`` endpoint silently caps each response at this many rows regardless
# of the requested ``limit`` (verified live: ``limit=500`` returns exactly 100 rows). The
# pager caps its per-page stride to this so ``offset`` stays aligned and it keeps paging
# instead of mistaking the first (capped) page for the end of the data.
_GAMMA_MAX_PAGE = 100

# A hard per-request deadline. ALWAYS shorter than any run budget — a required
# safety rule for every external call so a hung endpoint cannot stall the job.
REQUEST_TIMEOUT = 15

# Tolerance for treating a settled outcome price as exactly 0 or 1. Resolved
# Polymarket markets settle to "1"/"0", but we allow a small slop and reject
# anything ambiguous rather than guessing the outcome.
SETTLE_TOL = 0.02


@dataclass(frozen=True)
class ResolvedMarket:
    """One genuinely-resolved binary Polymarket market.

    ``outcome`` (1 = YES resolved true, 0 = NO) is derived from settled
    ``outcomePrices`` ONLY when they are unambiguously settled; ambiguous markets
    are rejected upstream and never reach this object.
    """

    market_id: str
    condition_id: str
    question: str
    category: str
    yes_token_id: str
    no_token_id: str
    resolution_time: datetime
    outcome: int
    volume: float
    liquidity: float
    # Market START time (Gamma ``startDate``), captured for POINT-IN-TIME / earlier-life
    # sampling (ROADMAP A7): the decision point can be drawn at a FRACTION of the market's
    # [start_date, resolution_time] life, where the crowd can still be miscalibrated —
    # instead of only a fixed lead before resolution (which lands ~70% of liquid markets
    # already price-pinned, leaving no edge headroom). Optional/defaulted so every existing
    # positional/keyword construction (tests + fetch path) is unchanged.
    start_date: Optional[datetime] = None


class PolymarketHistoryFetcher:
    """Read-only fetcher for resolved Polymarket history.

    No auth, no order placement — only public Gamma + CLOB reads. The ``session``
    is injectable so the entire class is testable with a fake session that returns
    canned JSON (see backend/tests/test_history_fetcher.py).
    """

    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "LLM-Quant/1.0",
                "Accept": "application/json",
            }
        )

    # ------------------------------------------------------------------
    # HTTP — mirror polymarket_client._get exactly: ALWAYS timeout=15,
    # swallow requests.RequestException, return None on failure.
    # ------------------------------------------------------------------
    def _get(self, url: str, params: Optional[dict] = None) -> Any:
        """GET with a hard ``timeout=15`` deadline. Returns parsed JSON, or None on
        any ``requests.RequestException`` (network error, timeout, bad status)."""
        try:
            resp = self.session.get(url, params=params, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            logger.warning(
                "Polymarket history fetch error: %s (status=%s, url=%s)", e, status, url
            )
            return None

    # ------------------------------------------------------------------
    # Resolved-market discovery (Gamma API)
    # ------------------------------------------------------------------
    def fetch_resolved_markets(
        self,
        limit: int = 500,
        max_pages: int = 10,
        categories: Optional[Sequence[str]] = None,
        order: str = "endDate",
    ) -> List[ResolvedMarket]:
        """Page Gamma ``/markets`` for closed, unambiguously-settled binary markets.

        ``max_pages`` BOUNDS the loop — it must never run unbounded. Markets that
        are not binary, lack token ids / endDate, or whose ``outcomePrices`` are not
        unambiguously settled (≈[1,0] or ≈[0,1]) are SKIPPED (logged), never guessed.

        ``order`` is the Gamma sort field (descending). The default ``"endDate"`` sorts
        by resolution date, but in practice that surfaces never-traded junk — markets
        closed early with a far-future endDate and an EMPTY CLOB price history, so every
        one is skipped by the anti-leakage guard for lack of a pre-decision tick. Pass
        ``order="volumeNum"`` to harvest markets that ACTUALLY TRADED (liquid, multi-day,
        retrievable CLOB history) — the only ones that yield a leakage-safe record.

        SELECTION/SURVIVORSHIP BIAS (see module docstring): excluding ambiguous /
        contested / re-resolved markets biases the sample toward clean crowd-friendly
        outcomes — and ``order="volumeNum"`` adds a LIQUIDITY-selection bias (only deep
        markets). Both are defensible + PRE-REGISTERED here, but any eval built on this
        sample overstates crowd calibration and must say so. ``categories`` must be
        PRE-REGISTERED, not chosen after seeing results.
        """
        cats = {c.lower() for c in categories} if categories else None
        # Gamma's ``/markets`` endpoint SILENTLY caps each response at
        # ``_GAMMA_MAX_PAGE`` (100) rows regardless of the requested ``limit`` — so a
        # request for ``limit=500`` returns exactly 100 rows. If we paged with a stride
        # of ``limit`` and stopped on ``len(data) < limit``, the very FIRST (capped) page
        # would look "short" (100 < 500) and paging would stop after ONE page — silently
        # under-sampling by up to ``max_pages`` worth of history (this is why every real
        # corpus fetched before this fix topped out near 100 records). Cap the per-page
        # stride to the real Gamma page size so ``offset`` stays aligned (0, 100, 200, …)
        # and the loop keeps paging until a genuinely short page or ``max_pages``.
        # Effective rows fetched ≈ ``min(limit, 100) * max_pages`` — grow the corpus via
        # ``max_pages``, not ``limit``.
        page_size = min(int(limit), _GAMMA_MAX_PAGE)
        out: List[ResolvedMarket] = []
        for page in range(max_pages):
            params = {
                "closed": "true",
                "order": order,
                "ascending": "false",
                "limit": page_size,
                "offset": page * page_size,
            }
            data = self._get(f"{GAMMA_API}/markets", params)
            if isinstance(data, dict):
                data = data.get("data")
            if not data or not isinstance(data, list):
                # No more rows (or a transient failure) — stop paging.
                break
            for raw in data:
                try:
                    rm = self._parse_resolved(raw)
                except Exception as e:  # defensive: one bad row must not kill the page
                    logger.debug("skipping unparseable market: %s", e)
                    continue
                if rm is None:
                    continue
                if cats is not None and rm.category.lower() not in cats:
                    continue
                out.append(rm)
            if len(data) < page_size:
                # Short page → we've reached the end of available history.
                break
        logger.info("fetched %d resolved markets across <=%d pages", len(out), max_pages)
        return out

    def _parse_resolved(self, raw: dict) -> Optional[ResolvedMarket]:
        """Parse one raw Gamma market into a ResolvedMarket, or None if it is not a
        clean, unambiguously-settled binary market."""
        outcomes = _parse_json_list(raw.get("outcomes", "[]"))
        prices = [_to_float(p) for p in _parse_json_list(raw.get("outcomePrices", "[]"))]
        token_ids = [str(t) for t in _parse_json_list(raw.get("clobTokenIds", "[]"))]

        # Binary-only (v1). Require exactly 2 outcomes / prices / token ids.
        if len(outcomes) != 2 or len(prices) != 2 or len(token_ids) != 2:
            logger.debug("skip non-binary market id=%s", raw.get("id"))
            return None
        if not token_ids[0] or not token_ids[1]:
            logger.debug("skip market missing token ids id=%s", raw.get("id"))
            return None
        if any(p is None for p in prices):
            logger.debug("skip market with unparseable prices id=%s", raw.get("id"))
            return None

        outcome = _settled_outcome(prices[0], prices[1])
        if outcome is None:
            logger.warning(
                "skip ambiguous/unsettled market id=%s outcomePrices=%s",
                raw.get("id"),
                prices,
            )
            return None

        resolution_time = _parse_dt(raw.get("endDate")) or _parse_dt(raw.get("closedTime"))
        if resolution_time is None:
            logger.debug("skip market missing endDate/closedTime id=%s", raw.get("id"))
            return None

        return ResolvedMarket(
            market_id=str(raw.get("id", "")),
            condition_id=str(raw.get("conditionId", "")),
            question=str(raw.get("question", "")),
            category=str(raw.get("category", "")),
            yes_token_id=token_ids[0],
            no_token_id=token_ids[1],
            resolution_time=resolution_time,
            outcome=outcome,
            volume=_to_float(raw.get("volume")) or 0.0,
            liquidity=_to_float(raw.get("liquidity")) or 0.0,
            # Market start (for A7 point-in-time sampling). Missing/unparseable => None;
            # fraction sampling then RAISES rather than fabricating a start (honest skip).
            start_date=_parse_dt(raw.get("startDate")) or _parse_dt(raw.get("startDateIso")),
        )

    # ------------------------------------------------------------------
    # Price history (CLOB API)
    # ------------------------------------------------------------------
    def fetch_price_history(
        self,
        token_id: str,
        start_ts: int,
        end_ts: int,
        fidelity: int = 60,
    ) -> List[dict]:
        """Fetch CLOB ``/prices-history`` ticks for ``token_id`` over [start_ts, end_ts].

        ``fidelity`` is the sampling interval in minutes. Returns the history list
        ``[{"t": <unix_seconds>, "p": <price 0..1>}, ...]`` or ``[]`` on failure.
        """
        params = {
            "market": token_id,
            "startTs": int(start_ts),
            "endTs": int(end_ts),
            "fidelity": int(fidelity),
        }
        data = self._get(f"{CLOB_API}/prices-history", params)
        if not isinstance(data, dict):
            return []
        history = data.get("history")
        return history if isinstance(history, list) else []

    # ------------------------------------------------------------------
    # Assembly into HistoricalMarket (anti-leakage core)
    # ------------------------------------------------------------------
    def to_historical_market(
        self,
        resolved: ResolvedMarket,
        decision_lead: timedelta,
        *,
        buffer: timedelta = timedelta(days=2),
        fidelity: int = 60,
    ) -> HistoricalMarket:
        """Build a leakage-safe ``HistoricalMarket`` from a resolved market.

        ``decision_time = resolution_time - decision_lead`` (must be strictly before
        resolution_time). ``market_price`` is the price ``p`` of the LAST YES-token
        tick at-or-before ``decision_time`` and strictly before ``resolution_time``.

        ANTI-LEAKAGE: the settled resolved outcomePrice is NEVER used as the
        decision-time price. Any tick whose timestamp ``>= resolution_time`` is
        rejected. If no qualifying pre-resolution tick exists, this RAISES
        ``ValueError`` — it does not fabricate a price.

        CHOOSE ``decision_lead`` CAREFULLY: too small a lead samples ``market_price``
        after the market has already pinned to ~1.0/~0.0 (see module docstring "LATE-LIFE
        PRICE PINNING") — a contemporaneous, non-look-ahead price, but one that flatters
        crowd calibration and leaves a real model little headroom. Prefer a lead large
        relative to the market's lifetime so the decision is sampled while still uncertain.
        """
        if decision_lead <= timedelta(0):
            raise ValueError(f"decision_lead must be positive: {decision_lead}")
        decision_time = resolved.resolution_time - decision_lead
        assert decision_time < resolved.resolution_time, (
            "decision_time must be strictly before resolution_time"
        )

        start_ts = int((decision_time - buffer).timestamp())
        end_ts = int(resolved.resolution_time.timestamp())
        history = self.fetch_price_history(
            resolved.yes_token_id, start_ts, end_ts, fidelity=fidelity
        )

        decision_ts = decision_time.timestamp()
        resolution_ts = resolved.resolution_time.timestamp()
        market_price = _last_pre_decision_price(history, decision_ts, resolution_ts)
        if market_price is None:
            # No PRE-resolution tick at-or-before the decision instant. We refuse to
            # invent one (that would be leakage or fabrication).
            raise ValueError(
                f"no pre-resolution price tick at/before decision_time for market "
                f"{resolved.market_id} (yes_token={resolved.yes_token_id}); refusing to "
                f"fabricate decision-time price"
            )

        return HistoricalMarket(
            market_id=resolved.market_id,
            decision_time=decision_time,
            resolution_time=resolved.resolution_time,
            market_price=market_price,
            # Naive crowd baseline: a real strategy OVERRIDES model_prob with its own
            # decision-time estimate (computed from info available up to decision_time).
            model_prob=market_price,
            outcome=resolved.outcome,
        )

    def build_historical_markets(
        self,
        resolved_list: Sequence[ResolvedMarket],
        decision_lead: timedelta,
        *,
        buffer: timedelta = timedelta(days=2),
        fidelity: int = 60,
    ) -> List[HistoricalMarket]:
        """Batch ``to_historical_market``, SKIPPING (loud warning) any market whose
        anti-leakage guard cannot be satisfied. Returns only leakage-safe records."""
        out: List[HistoricalMarket] = []
        skipped = 0
        for rm in resolved_list:
            try:
                out.append(
                    self.to_historical_market(
                        rm, decision_lead, buffer=buffer, fidelity=fidelity
                    )
                )
            except (ValueError, AssertionError) as e:
                skipped += 1
                logger.warning("skipping market %s (no leakage-safe price): %s", rm.market_id, e)
        logger.info(
            "built %d leakage-safe HistoricalMarket records (%d skipped)", len(out), skipped
        )
        return out

    # ------------------------------------------------------------------
    # POINT-IN-TIME / earlier-life sampling (ROADMAP A7)
    # ------------------------------------------------------------------
    def to_historical_market_at_fraction(
        self,
        resolved: ResolvedMarket,
        fraction: float,
        *,
        buffer: timedelta = timedelta(days=2),
        fidelity: int = 60,
    ) -> HistoricalMarket:
        """Build a leakage-safe ``HistoricalMarket`` whose decision point is drawn at
        ``fraction`` of the market's life instead of a fixed lead before resolution.

        ``decision_time = start_date + fraction * (resolution_time - start_date)``, so
        ``fraction=0`` samples at market open (maximum edge headroom, the crowd least
        settled) and ``fraction→1`` samples near resolution (like a tiny lead — usually
        pinned). This is the A7 answer to the OA-11 finding that a fixed 2-day lead lands
        ~70% of liquid markets already price-pinned (no edge to find): earlier-life
        sampling gives a model room to out-calibrate a not-yet-sharp crowd.

        SELECTION-PROFILE DISCLOSURE: sampling earlier changes the corpus's bias profile
        — earlier decision points include more genuinely-uncertain (and more eventually-
        surprising) markets, so a calibration eval on a fraction-sampled corpus measures a
        DIFFERENT population than a fixed-lead one. Choose + PRE-REGISTER the fraction; do
        not sweep it post-hoc on the test set (a p-hacking lever, like ``decision_lead``).

        ANTI-LEAKAGE IS UNCHANGED: ``market_price`` is still ONLY a CLOB tick at-or-before
        the (earlier) ``decision_time`` AND strictly before ``resolution_time`` — the SAME
        ``_last_pre_decision_price`` guard. The settled outcome is never the price. If the
        market has no captured ``start_date``, or no pre-decision tick exists, this RAISES
        rather than fabricating.
        """
        if not (0.0 <= fraction < 1.0):
            # fraction==1.0 would put the decision AT resolution (zero holding period, and
            # the leakage guard would reject every tick) — a degenerate, non-tradeable point.
            raise ValueError(f"fraction must be in [0.0, 1.0): {fraction}")
        if resolved.start_date is None:
            raise ValueError(
                f"market {resolved.market_id} has no start_date; cannot sample at a life "
                f"fraction (refusing to fabricate a market start)"
            )
        if resolved.start_date >= resolved.resolution_time:
            raise ValueError(
                f"market {resolved.market_id} start_date {resolved.start_date} is not before "
                f"resolution_time {resolved.resolution_time}"
            )

        life = resolved.resolution_time - resolved.start_date
        decision_time = resolved.start_date + fraction * life
        assert decision_time < resolved.resolution_time, (
            "decision_time must be strictly before resolution_time"
        )

        start_ts = int((decision_time - buffer).timestamp())
        end_ts = int(resolved.resolution_time.timestamp())
        history = self.fetch_price_history(
            resolved.yes_token_id, start_ts, end_ts, fidelity=fidelity
        )

        decision_ts = decision_time.timestamp()
        resolution_ts = resolved.resolution_time.timestamp()
        market_price = _last_pre_decision_price(history, decision_ts, resolution_ts)
        if market_price is None:
            raise ValueError(
                f"no pre-resolution price tick at/before life-fraction decision_time for "
                f"market {resolved.market_id} (yes_token={resolved.yes_token_id}, "
                f"fraction={fraction}); refusing to fabricate decision-time price"
            )

        return HistoricalMarket(
            market_id=resolved.market_id,
            decision_time=decision_time,
            resolution_time=resolved.resolution_time,
            market_price=market_price,
            model_prob=market_price,   # naive crowd baseline; a real strategy overrides it
            outcome=resolved.outcome,
        )

    def build_historical_markets_at_fraction(
        self,
        resolved_list: Sequence[ResolvedMarket],
        fraction: float,
        *,
        buffer: timedelta = timedelta(days=2),
        fidelity: int = 60,
    ) -> List[HistoricalMarket]:
        """Batch ``to_historical_market_at_fraction``, SKIPPING (loud warning) any market
        with no captured start_date or no leakage-safe pre-decision tick. Returns only
        leakage-safe records sampled at the pre-registered life ``fraction``."""
        out: List[HistoricalMarket] = []
        skipped = 0
        for rm in resolved_list:
            try:
                out.append(
                    self.to_historical_market_at_fraction(
                        rm, fraction, buffer=buffer, fidelity=fidelity
                    )
                )
            except (ValueError, AssertionError) as e:
                skipped += 1
                logger.warning(
                    "skipping market %s (no leakage-safe fraction record): %s", rm.market_id, e
                )
        logger.info(
            "built %d leakage-safe HistoricalMarket records at life-fraction %.3f (%d skipped)",
            len(out), fraction, skipped,
        )
        return out


# ---------------------------------------------------------------------------
# Pure helpers (no I/O — exhaustively unit-testable)
# ---------------------------------------------------------------------------
def _parse_json_list(value: Any) -> list:
    """Gamma encodes parallel arrays as JSON-strings ('["1","0"]') or real lists."""
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except (ValueError, TypeError):
            return [v.strip() for v in value.split(",") if v.strip()]
    return []


def _to_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _settled_outcome(p_yes: float, p_no: float) -> Optional[int]:
    """Return 1 if settled YES (≈[1,0]), 0 if settled NO (≈[0,1]), else None.

    BOTH prices must be within ``SETTLE_TOL`` of 0 or 1 AND sum to ≈1 — anything
    ambiguous (e.g. [0.6, 0.4]) returns None so the caller skips it rather than
    guessing the resolved outcome."""
    # Use a tiny float-slop guard on the tolerance edge: abs(0.98 - 1.0) is
    # 0.020000000000000018 in IEEE-754, which is strictly > 0.02 and would wrongly
    # reject a market that resolved to a rounded 0.98/0.02. The +eps makes the
    # boundary inclusive as the SETTLE_TOL docstring intends.
    tol = SETTLE_TOL + 1e-9
    if abs(p_yes + p_no - 1.0) > tol:
        return None
    yes_one = abs(p_yes - 1.0) <= tol and abs(p_no) <= tol
    no_one = abs(p_yes) <= tol and abs(p_no - 1.0) <= tol
    if yes_one:
        return 1
    if no_one:
        return 0
    return None


def _parse_dt(value: Any) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp (Gamma uses trailing 'Z') into a UTC datetime."""
    if not value or not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _last_pre_decision_price(
    history: Sequence[dict],
    decision_ts: float,
    resolution_ts: float,
) -> Optional[float]:
    """The price ``p`` of the LAST tick with ``t <= decision_ts`` AND ``t <
    resolution_ts``. Returns None if no such pre-resolution tick exists.

    Ticks at/after resolution are explicitly excluded — they are (or are
    contaminated by) the settled outcome and must never become a decision price."""
    best_t: Optional[float] = None
    best_p: Optional[float] = None
    for tick in history:
        t = _to_float(tick.get("t"))
        p = _to_float(tick.get("p"))
        if t is None or p is None:
            continue
        if not math.isfinite(t):
            # A NaN/inf timestamp fails every ordered comparison silently: NaN would pin
            # best_t=NaN and block all later real ticks, returning a fabricated price (a
            # malformed API tick poisoning the decision price — the data analog of a fake
            # fill). Reject it up front. Covered by a regression test proven to fail pre-fix.
            continue
        if t > decision_ts:
            continue
        if t >= resolution_ts:  # belt-and-suspenders: never use a settled tick
            continue
        if not (0.0 <= p <= 1.0):
            continue
        if best_t is None or t > best_t:
            best_t, best_p = t, p
    return best_p


__all__ = [
    "GAMMA_API",
    "CLOB_API",
    "REQUEST_TIMEOUT",
    "ResolvedMarket",
    "PolymarketHistoryFetcher",
]
