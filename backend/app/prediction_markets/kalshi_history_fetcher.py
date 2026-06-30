"""kalshi_history_fetcher.py — leakage-safe ingestion of REAL resolved Kalshi
history into ``walk_forward.HistoricalMarket`` records (ROADMAP A3).

WHY THIS EXISTS
``walk_forward`` needs genuinely resolved market history with a LEAKAGE-SAFE
pre-resolution crowd price. This module pulls Kalshi's resolved markets and
assembles ``HistoricalMarket`` records with the same anti-leakage guarantees as
``polymarket_history_fetcher.py``.

HONEST SCOPE
This module INGESTS real resolved history when network access is available (public
Kalshi API — no credentials required). Outbound access may be blocked by egress
policy in some environments; the owner runs it where Kalshi's API is reachable.
The PARSING and LEAKAGE-SAFETY logic is fully unit-tested offline with a mocked
HTTP session (no real network).

RESEARCH-INTEGRITY CAVEATS (read before trusting any eval built on this data)
* SELECTION / SURVIVORSHIP BIAS: only unambiguously resolved markets (status in
  "finalized"/"settled") are kept. Contested, voided, or re-resolved markets are
  excluded — exactly the cases where the crowd was most wrong. The sample is biased
  TOWARD clean, crowd-friendly outcomes. Any calibration eval on it is an OPTIMISTIC
  upper bound and must say so.
* LATE-LIFE PRICE PINNING: Kalshi prices often pin to ~0.99/~0.01 well before
  ``close_time``. If ``decision_lead`` is too small, ``decision_time`` lands after
  the price has already pinned, so ``market_price`` ≈ the answer. Choose a
  ``decision_lead`` large relative to typical market lifetime so the decision is
  sampled while the market is still genuinely uncertain.
* CATEGORY SUBSETTING IS A P-HACKING LEVER: any ``categories`` filter must be
  PRE-REGISTERED before seeing results. Post-hoc category selection is textbook
  p-hacking and requires multiple-comparison correction.

THE ANTI-LEAKAGE GUARANTEE (the whole point — an auditor WILL attack this)
A resolved market's ``result`` (YES/NO) is the final answer. Using that answer as
the decision-time crowd price is 100% look-ahead leakage. ``market_price`` is NEVER
taken from the result field. It is taken ONLY from a price-history tick whose
timestamp is at-or-before ``decision_time`` AND strictly before ``resolution_time``.
If no qualifying pre-resolution tick exists, we RAISE (single record) or skip with a
loud warning (batch) — we NEVER fabricate a price.

CI-SAFETY
Imports only ``requests`` + stdlib + ``HistoricalMarket``. No pandas/numpy/backtest
deps (absent from CI).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional, Sequence

import requests

from .walk_forward import HistoricalMarket

logger = logging.getLogger(__name__)

# Public Kalshi elections base URL — no auth required for market data.
KALSHI_BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"

# Hard per-request deadline — required safety rule for every external call.
REQUEST_TIMEOUT = 15

# Tolerance for treating a settled YES/NO result as unambiguous.
# Kalshi result field is a string "yes"/"no"/"" — we use it directly.
# For price-based settlement detection we keep the same SETTLE_TOL as Polymarket.
SETTLE_TOL = 0.02


@dataclass(frozen=True)
class KalshiResolvedMarket:
    """One genuinely-resolved binary Kalshi market.

    ``outcome`` (1 = YES resolved true, 0 = NO resolved true) is derived ONLY from
    the market's ``result`` field when it is unambiguously "yes" or "no". Markets
    with an empty/unknown result are rejected upstream and never reach this object.
    """

    ticker: str            # e.g. "KXBTC-25DEC-T50000"
    title: str
    category: str
    resolution_time: datetime
    outcome: int           # 1 = YES, 0 = NO
    volume: float


class KalshiHistoryFetcher:
    """Read-only fetcher for resolved Kalshi history (public API, no auth).

    The ``session`` is injectable so the entire class is testable with a fake
    session that returns canned JSON (see backend/tests/test_kalshi_history_fetcher.py).
    """

    def __init__(
        self,
        session: Optional[requests.Session] = None,
        base_url: str = KALSHI_BASE_URL,
    ):
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "LLM-Quant/1.0",
                "Accept": "application/json",
            }
        )
        self.base_url = base_url.rstrip("/")

    # ------------------------------------------------------------------
    # HTTP — mirror polymarket_history_fetcher._get exactly.
    # ------------------------------------------------------------------
    def _get(self, url: str, params: Optional[dict] = None) -> Any:
        """GET with a hard ``timeout=15`` deadline. Returns parsed JSON or None."""
        try:
            resp = self.session.get(url, params=params, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            logger.warning(
                "Kalshi history fetch error: %s (status=%s, url=%s)", e, status, url
            )
            return None

    # ------------------------------------------------------------------
    # Resolved-market discovery
    # ------------------------------------------------------------------
    def fetch_resolved_markets(
        self,
        limit: int = 200,
        max_pages: int = 10,
        categories: Optional[Sequence[str]] = None,
    ) -> List[KalshiResolvedMarket]:
        """Page Kalshi /markets for settled/finalized binary markets.

        ``max_pages`` BOUNDS the loop — it must never run unbounded. Markets whose
        ``result`` is not unambiguously "yes" or "no" are SKIPPED, never guessed.

        SELECTION BIAS: only finalized/settled markets are kept (see module docstring).
        ``categories`` must be PRE-REGISTERED, not tuned after seeing eval results.

        Args:
            limit: Markets per page.
            max_pages: Hard upper bound on page requests (safety: never unbounded).
            categories: Optional allowlist of category strings (case-insensitive).

        Returns:
            List of ``KalshiResolvedMarket`` objects.
        """
        cats = {c.lower() for c in categories} if categories else None
        out: List[KalshiResolvedMarket] = []
        cursor: Optional[str] = None

        for page in range(max_pages):
            params: dict = {"limit": limit, "status": "finalized"}
            if cursor:
                params["cursor"] = cursor

            data = self._get(f"{self.base_url}/markets", params=params)
            if not isinstance(data, dict):
                break

            raw_markets = data.get("markets")
            if not raw_markets or not isinstance(raw_markets, list):
                break

            for raw in raw_markets:
                try:
                    rm = self._parse_resolved(raw)
                except Exception as e:
                    logger.debug("skipping unparseable Kalshi market: %s", e)
                    continue
                if rm is None:
                    continue
                if cats is not None and rm.category.lower() not in cats:
                    continue
                out.append(rm)

            # Pagination: use cursor if provided; stop if short page or no cursor.
            cursor = data.get("cursor") or None
            if not cursor or len(raw_markets) < limit:
                break

        logger.info(
            "fetched %d resolved Kalshi markets across <=%d pages", len(out), max_pages
        )
        return out

    def _parse_resolved(self, raw: dict) -> Optional[KalshiResolvedMarket]:
        """Parse one raw Kalshi market into a KalshiResolvedMarket, or None if
        the market is not unambiguously resolved with a clear YES/NO result."""
        ticker = raw.get("ticker")
        if not ticker:
            logger.debug("skip Kalshi market missing ticker")
            return None

        result = str(raw.get("result", "")).lower().strip()
        if result == "yes":
            outcome = 1
        elif result == "no":
            outcome = 0
        else:
            logger.debug(
                "skip Kalshi market ticker=%s: result=%r is not 'yes'/'no'",
                ticker,
                result,
            )
            return None

        # Resolution time from close_time or expiration_time.
        resolution_time = _parse_dt(raw.get("close_time")) or _parse_dt(
            raw.get("expiration_time")
        )
        if resolution_time is None:
            logger.debug("skip Kalshi market ticker=%s: missing close_time", ticker)
            return None

        return KalshiResolvedMarket(
            ticker=str(ticker),
            title=str(raw.get("title", "")),
            category=str(raw.get("category", "")),
            resolution_time=resolution_time,
            outcome=outcome,
            volume=_to_float(raw.get("volume")) or 0.0,
        )

    # ------------------------------------------------------------------
    # Price history (candlestick/history endpoint)
    # ------------------------------------------------------------------
    def fetch_price_history(
        self,
        ticker: str,
        start_ts: int,
        end_ts: int,
    ) -> List[dict]:
        """Fetch price-history ticks for ``ticker`` over [start_ts, end_ts].

        Uses the Kalshi /markets/{ticker}/history endpoint.
        Returns a list of ticks ``[{"t": <unix_seconds>, "p": <price 0..1>}, ...]``
        or ``[]`` on failure.

        Kalshi's history endpoint returns prices as probabilities (0.0-1.0) or cents
        (0-100); we normalise to [0, 1] (divide by 100 if > 1.0).

        Args:
            ticker: Kalshi market ticker.
            start_ts: Start of window as Unix seconds.
            end_ts: End of window as Unix seconds.

        Returns:
            List of normalised tick dicts with keys "t" (unix seconds) and "p" (0..1).
        """
        params = {
            "start_ts": int(start_ts),
            "end_ts": int(end_ts),
        }
        data = self._get(f"{self.base_url}/markets/{ticker}/history", params=params)
        if not isinstance(data, dict):
            return []

        # Try common Kalshi response shapes.
        history: Any = data.get("history") or data.get("candlesticks") or []
        if not isinstance(history, list):
            return []

        ticks = []
        for item in history:
            t = _to_float(item.get("t") or item.get("ts") or item.get("end_period_ts"))
            p_raw = _to_float(
                item.get("p") or item.get("yes_price") or item.get("close")
            )
            if t is None or p_raw is None:
                continue
            # Normalise: Kalshi may return prices as cents (>1.0) or fractions.
            p = p_raw / 100.0 if p_raw > 1.0 else p_raw
            if not (0.0 <= p <= 1.0):
                continue
            ticks.append({"t": t, "p": p})
        return ticks

    # ------------------------------------------------------------------
    # Assembly into HistoricalMarket (anti-leakage core)
    # ------------------------------------------------------------------
    def to_historical_market(
        self,
        resolved: KalshiResolvedMarket,
        decision_lead: timedelta,
        *,
        buffer: timedelta = timedelta(days=2),
    ) -> HistoricalMarket:
        """Build a leakage-safe ``HistoricalMarket`` from a resolved Kalshi market.

        ``decision_time = resolution_time - decision_lead`` (must be strictly before
        resolution_time). ``market_price`` is the price ``p`` of the LAST tick
        at-or-before ``decision_time`` and strictly before ``resolution_time``.

        ANTI-LEAKAGE: the settled result ("yes"/"no") is NEVER used as the
        decision-time price. Any tick whose timestamp >= resolution_time is
        rejected. If no qualifying pre-resolution tick exists, this RAISES
        ``ValueError`` — it does not fabricate a price.

        CHOOSE ``decision_lead`` CAREFULLY: too small a lead samples ``market_price``
        after the market has already pinned to ~0.99/~0.01 (see module docstring on
        LATE-LIFE PRICE PINNING) — a contemporaneous, non-look-ahead price, but one
        that flatters crowd calibration and leaves a real model little headroom.
        Prefer a lead large relative to the market's lifetime so the decision is
        sampled while still uncertain.

        Args:
            resolved: A ``KalshiResolvedMarket`` (must have unambiguous YES/NO result).
            decision_lead: How far before resolution to set the decision timestamp.
            buffer: Extra lookback window before decision_time for the price history fetch.

        Returns:
            A ``HistoricalMarket`` with a leakage-safe ``market_price``.

        Raises:
            ValueError: if decision_lead <= 0, or if no pre-resolution price tick exists.
        """
        if decision_lead <= timedelta(0):
            raise ValueError(f"decision_lead must be positive: {decision_lead}")
        decision_time = resolved.resolution_time - decision_lead
        assert decision_time < resolved.resolution_time, (
            "decision_time must be strictly before resolution_time"
        )

        start_ts = int((decision_time - buffer).timestamp())
        end_ts = int(resolved.resolution_time.timestamp())
        history = self.fetch_price_history(resolved.ticker, start_ts, end_ts)

        decision_ts = decision_time.timestamp()
        resolution_ts = resolved.resolution_time.timestamp()
        market_price = _last_pre_decision_price(history, decision_ts, resolution_ts)
        if market_price is None:
            raise ValueError(
                f"no pre-resolution price tick at/before decision_time for Kalshi "
                f"market {resolved.ticker!r}; refusing to fabricate decision-time price"
            )

        return HistoricalMarket(
            market_id=resolved.ticker,
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
        resolved_list: Sequence[KalshiResolvedMarket],
        decision_lead: timedelta,
        *,
        buffer: timedelta = timedelta(days=2),
    ) -> List[HistoricalMarket]:
        """Batch ``to_historical_market``, SKIPPING (loud warning) any market whose
        anti-leakage guard cannot be satisfied. Returns only leakage-safe records."""
        out: List[HistoricalMarket] = []
        skipped = 0
        for rm in resolved_list:
            try:
                out.append(self.to_historical_market(rm, decision_lead, buffer=buffer))
            except (ValueError, AssertionError) as e:
                skipped += 1
                logger.warning(
                    "skipping Kalshi market %s (no leakage-safe price): %s",
                    rm.ticker,
                    e,
                )
        logger.info(
            "built %d leakage-safe HistoricalMarket records (%d skipped)",
            len(out),
            skipped,
        )
        return out


# ---------------------------------------------------------------------------
# Pure helpers (no I/O — exhaustively unit-testable)
# ---------------------------------------------------------------------------
def _to_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_dt(value: Any) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp into a UTC-aware datetime."""
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
    contaminated by) the settled result and must never become a decision price.
    This is the same logic as in polymarket_history_fetcher._last_pre_decision_price.
    """
    best_t: Optional[float] = None
    best_p: Optional[float] = None
    for tick in history:
        t = _to_float(tick.get("t"))
        p = _to_float(tick.get("p"))
        if t is None or p is None:
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
    "KALSHI_BASE_URL",
    "REQUEST_TIMEOUT",
    "KalshiResolvedMarket",
    "KalshiHistoryFetcher",
]
