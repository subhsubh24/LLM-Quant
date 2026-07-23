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
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional, Sequence

import requests

from .market_category import derive_market_category
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
    # STRUCTURED strike (ROADMAP B8 cross-venue matching), mirroring the LIVE client (#400).
    # Kalshi crypto/scalar RESOLVED markets carry a GENERIC title ("Bitcoin price on Jul 20,
    # 2026?") so the title-text strike parser finds nothing; the real strike lives ONLY here.
    # Capturing them on the RESOLVED record (previously strike-BLIND) is what lets a future
    # HISTORICAL co-listed corpus match a resolved Kalshi market on strike+window against a
    # resolved Polymarket market whose strike is in its title — the pinned B8 next step.
    # Absent/garbage/non-finite fields stay None: NEVER fabricated (the matcher refuses to
    # guess a strike). Defaulted to None so every existing construction is byte-unchanged.
    floor_strike: Optional[float] = None
    cap_strike: Optional[float] = None
    strike_type: Optional[str] = None


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
        *,
        series_ticker: Optional[str] = None,
        historical: bool = False,
    ) -> List[KalshiResolvedMarket]:
        """Page Kalshi for settled/finalized binary markets.

        ``max_pages`` BOUNDS the loop — it must never run unbounded. Markets whose
        ``result`` is not unambiguously "yes" or "no" are SKIPPED, never guessed.

        SELECTION BIAS: only finalized/settled markets are kept (see module docstring).
        ``categories`` must be PRE-REGISTERED, not tuned after seeing eval results.

        ``historical`` selects Kalshi's SEPARATE public ``/historical/markets`` tier. The
        LIVE ``/markets?status=settled`` feed only serves a rolling window (its floor is
        ``GET /historical/cutoff``'s ``market_settled_ts``, live-probed at ~3 months) — so
        every prior B8/Kalshi probe that paged the live feed saw only recent, sports-heavy
        markets and MISSED the multi-year resolved history that funds a real OOS corpus.
        The historical tier is the SAME cursor-paginated contract, needs NO auth, does NOT
        take a ``status`` filter (it serves only resolved markets — the per-market YES/NO
        is still derived from ``result`` below), and is where the deep economics/employment
        (EXP-009) and crypto (B8 co-listed) series actually live. ``series_ticker`` narrows
        the query to one Kalshi series (e.g. ``KXJOBLESS``) — required in practice for the
        historical tier to reach a target category rather than the platform-wide firehose.

        Args:
            limit: Markets per page.
            max_pages: Hard upper bound on page requests (safety: never unbounded).
            categories: Optional allowlist of category strings (case-insensitive).
            series_ticker: Optional Kalshi series filter (forwarded to the API).
            historical: Query the deep ``/historical/markets`` tier instead of the live feed.

        Returns:
            List of ``KalshiResolvedMarket`` objects.
        """
        cats = {c.lower() for c in categories} if categories else None
        out: List[KalshiResolvedMarket] = []
        cursor: Optional[str] = None
        endpoint = (
            f"{self.base_url}/historical/markets"
            if historical
            else f"{self.base_url}/markets"
        )

        for page in range(max_pages):
            params: dict = {"limit": limit}
            if not historical:
                # "settled" is the documented Kalshi GetMarkets `status` FILTER value for
                # resolved markets (valid filter values: unopened/open/closed/settled).
                # "finalized" is NOT a valid filter value — using it returned nothing. The
                # historical tier serves ONLY resolved markets, so it takes no status filter
                # (passing one returned 0). The per-market YES/NO outcome is derived from
                # the `result` field below, never from this filter.
                params["status"] = "settled"
            if series_ticker:
                params["series_ticker"] = series_ticker
            if cursor:
                params["cursor"] = cursor

            data = self._get(endpoint, params=params)
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
            # Distinguish the two "not yes/no" cases honestly (SELF_VALIDATION claims an
            # UNRECOGNIZED status is logged LOUDLY — this makes that true without spamming):
            #  * an EMPTY result = the market simply isn't resolved yet, an ordinary skip (debug);
            #  * a NON-EMPTY unrecognized token (e.g. "void"/"cancel"/an unexpected Kalshi value)
            #    = a real CONTRACT surprise the owner must SEE on the first live fetch → WARNING.
            if result:
                logger.warning(
                    "skip Kalshi market ticker=%s: UNRECOGNIZED result=%r (expected "
                    "'yes'/'no') — verify the Kalshi settlement contract",
                    ticker,
                    result,
                )
            else:
                logger.debug("skip Kalshi market ticker=%s: no result yet (unresolved)", ticker)
            return None

        # Resolution time from close_time or expiration_time.
        resolution_time = _parse_dt(raw.get("close_time")) or _parse_dt(
            raw.get("expiration_time")
        )
        if resolution_time is None:
            logger.debug("skip Kalshi market ticker=%s: missing close_time", ticker)
            return None

        # STRUCTURED strike capture (finite-coerced, garbage/absent → None, never fabricated),
        # normalized exactly as the live kalshi_client (#400) does so the two paths agree.
        floor_strike = _finite_float(raw.get("floor_strike"))
        cap_strike = _finite_float(raw.get("cap_strike"))
        strike_type_raw = raw.get("strike_type")
        strike_type = (
            str(strike_type_raw).lower().strip() if strike_type_raw else None
        ) or None

        return KalshiResolvedMarket(
            ticker=str(ticker),
            title=str(raw.get("title", "")),
            # Derive a coarse correlation bucket from the raw category + the title text (the
            # SAME deriver the other venues use) so Kalshi resolved records carry a REAL
            # category for the F10 category dimension, not the frequently-empty raw field.
            category=derive_market_category(
                str(raw.get("title", "")), str(raw.get("category", ""))
            ),
            resolution_time=resolution_time,
            outcome=outcome,
            # The historical tier serves `volume` as null and puts the count in `volume_fp`
            # (Kalshi's fixed-point field, mirroring the `*_dollars`/`*_fp` migration #397);
            # fall back to it so a historical record still carries a real volume.
            volume=_to_float(raw.get("volume"))
            or _to_float(raw.get("volume_fp"))
            or 0.0,
            floor_strike=floor_strike,
            cap_strike=cap_strike,
            strike_type=strike_type,
        )

    # ------------------------------------------------------------------
    # Price history (candlestick/history endpoint)
    # ------------------------------------------------------------------
    def fetch_price_history(
        self,
        ticker: str,
        start_ts: int,
        end_ts: int,
        *,
        period_interval: int = 60,
        historical: bool = False,
    ) -> List[dict]:
        """Fetch price-history ticks for ``ticker`` over [start_ts, end_ts].

        Uses the Kalshi **candlesticks** endpoint. For a LIVE (recent) market that is
        ``/series/{series_ticker}/markets/{ticker}/candlesticks`` (VERIFIED HTTP 200,
        OA-15); for a market past the live cutoff (``historical=True``) the live path
        **404s** and the working endpoint is ``/historical/markets/{ticker}/candlesticks``
        (LIVE-CONFIRMED this run — a resolved 2022 ``JOBLESS`` market returned real
        candles there while the ``/series/...`` path 404'd). The old
        ``/markets/{ticker}/history`` path also 404s (it does not exist). ``series_ticker``
        (live path only) is the prefix of the market ticker before the first ``-`` (e.g.
        ``KXBTC`` from ``KXBTC-25DEC-T50000``). ``period_interval`` is the candle width in
        MINUTES (Kalshi requires it); the default 60 (hourly) is ample for a decision
        sampled ~a day or more before resolution.

        Returns a list of ticks ``[{"t": <unix_seconds>, "p": <price 0..1>}, ...]`` or
        ``[]`` on failure. Prices are normalised to [0, 1] by ``_candle_price`` — which
        reads the current Kalshi DOLLAR candlestick schema (nested ``price``/``yes_ask``/
        ``yes_bid`` objects carry dollars in [0,1], LIVE-CONFIRMED this run) as well as the
        legacy integer-cents form (see ``_candle_price`` for the exact disambiguation).

        FIDELITY CAVEAT (an auditor break, disclosed not silently changed): for an ILLIQUID
        candle whose traded-``price`` object is all-null, ``_candle_price`` falls back to
        ``yes_ask`` — so on a ONE-SIDED book (``yes_bid`` = 0, common on thin markets like
        the economics/employment series this feeds) the recorded "crowd price" is the ASK,
        biased HIGH vs the true mid. Any calibration read built on this data must treat that
        bias as a known upper-lean on crowd confidence, NOT a clean midpoint.

        Args:
            ticker: Kalshi market ticker (e.g. "KXBTC-25DEC-T50000").
            start_ts: Start of window as Unix seconds.
            end_ts: End of window as Unix seconds.
            period_interval: Candle width in minutes (Kalshi-required).

        Returns:
            List of normalised tick dicts with keys "t" (unix seconds) and "p" (0..1).
        """
        params = {
            "start_ts": int(start_ts),
            "end_ts": int(end_ts),
            "period_interval": int(period_interval),
        }
        if historical:
            url = f"{self.base_url}/historical/markets/{ticker}/candlesticks"
        else:
            series_ticker = _series_ticker(ticker)
            url = f"{self.base_url}/series/{series_ticker}/markets/{ticker}/candlesticks"
        data = self._get(url, params=params)
        if not isinstance(data, dict):
            return []

        # Candlesticks under "candlesticks"; a flat "history" shape is also accepted so
        # the offline fixtures + any simplified response still parse.
        history: Any = data.get("candlesticks")
        if history is None:
            history = data.get("history")
        if not isinstance(history, list):
            return []

        ticks = []
        for item in history:
            if not isinstance(item, dict):
                continue
            # Use explicit None-presence (NOT `a or b`): a legitimate tick with t==0 or
            # p==0 is falsy and would be silently dropped by an `or`-chain (a deep-audit
            # finding). p==0 (YES≈0¢) is a valid extreme price that must survive.
            t = _to_float(_first_present(item, ("t", "ts", "end_period_ts")))
            # _candle_price returns a UNIT-AWARE price already normalised to [0,1] across
            # the dollar (live + historical) and legacy-cents candle schemas, so a real
            # $0.67 is 0.67 (never a fabricated 0.0067) and a 1¢ longshot is 0.01 (never a
            # fabricated 1.0). The final [0,1] range check below drops anything still out
            # of range rather than fabricating.
            p = _candle_price(item)
            if t is None or p is None:
                continue
            if not math.isfinite(t):
                continue
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
        historical: bool = False,
    ) -> HistoricalMarket:
        """Build a leakage-safe ``HistoricalMarket`` from a resolved Kalshi market.

        ``historical`` routes the price fetch to the deep ``/historical/*`` candlestick
        tier — required for any market drawn from ``fetch_resolved_markets(historical=True)``
        (its live candlesticks 404 past the cutoff).

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
        history = self.fetch_price_history(
            resolved.ticker, start_ts, end_ts, historical=historical
        )

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
            category=resolved.category,
        )

    def build_historical_markets(
        self,
        resolved_list: Sequence[KalshiResolvedMarket],
        decision_lead: timedelta,
        *,
        buffer: timedelta = timedelta(days=2),
        historical: bool = False,
    ) -> List[HistoricalMarket]:
        """Batch ``to_historical_market``, SKIPPING (loud warning) any market whose
        anti-leakage guard cannot be satisfied. Returns only leakage-safe records.

        ``historical`` routes every price fetch to the deep ``/historical/*`` candlestick
        tier — pass it whenever ``resolved_list`` came from ``fetch_resolved_markets(
        historical=True)``."""
        out: List[HistoricalMarket] = []
        skipped = 0
        for rm in resolved_list:
            try:
                out.append(
                    self.to_historical_market(
                        rm, decision_lead, buffer=buffer, historical=historical
                    )
                )
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
def _first_present(d: dict, keys: Sequence[str]) -> Any:
    """Return the value of the first key whose value is not None (presence test, NOT
    truthiness — so a legitimate 0 / 0.0 is returned, not skipped). None if all absent."""
    for k in keys:
        v = d.get(k)
        if v is not None:
            return v
    return None


def _series_ticker(ticker: str) -> str:
    """Derive the Kalshi SERIES ticker from a market ticker: the prefix before the first
    ``-`` (e.g. ``KXBTC`` from ``KXBTC-25DEC-T50000``). A ticker with no ``-`` is its own
    series. Used to build the candlesticks endpoint path."""
    return ticker.split("-", 1)[0] if "-" in ticker else ticker


def _candle_price(item: dict) -> Optional[float]:
    """Extract the YES price from a Kalshi candlestick (or a flat tick), NORMALISED to
    [0, 1]. None if absent/unparseable.

    UNIT-AWARE normalisation across the TWO real Kalshi candlestick schemas (both
    LIVE-CONFIRMED this run via HTTP 200 probes — the prior "always cents" assumption was
    encoded against an EMPTY candle list (OA-15) and is contradicted by real data):

    * DOLLAR schema (the current Kalshi contract, the ``*_dollars`` migration #397 first
      saw on the list feed, now confirmed on candlesticks too). The nested
      ``price``/``yes_ask``/``yes_bid`` sub-fields carry a dollar value already in [0, 1],
      either under an explicit ``*_dollars`` key (LIVE ``/series/.../candlesticks``:
      ``{"close_dollars": "0.2200"}``) or under a BARE key whose VALUE is a decimal string
      (HISTORICAL ``/historical/markets/{t}/candlesticks``: ``{"close": "0.6700"}``). A
      dollar value is taken AS-IS — never divided by 100 (dividing "0.6700" by 100 would
      fabricate 0.0067, a real-money-relevant price error).
    * LEGACY CENTS schema (the documented 0-100 integer form the offline fixtures use). A
      bare NUMERIC sub-field is cents → divided by 100 (62 → 0.62; a 1¢ longshot → 0.01,
      never a fabricated 1.0).

    Disambiguation (per matched sub-field, in this order): an explicit ``*_dollars`` key is
    unconditionally dollars; a bare value ``> 1.0`` is cents (only cents exceed 1); a bare
    NON-whole value is dollars (a real legacy cents value is ALWAYS a whole number in
    [0,100], so a fractional bare value can only be dollars — this closes a bare-dollar-FLOAT
    misread that a pure type check would divide by 100); only a bare WHOLE ``0``/``1`` stays
    genuinely ambiguous and is resolved by wire type — a STRING is dollars (``"1.0000"`` →
    1.0), a NUMBER is legacy cents (``1`` → 0.01). The final [0, 1] range check in
    ``fetch_price_history`` drops anything still out of range rather than fabricating.

    A FLAT tick (``p``/``yes_price``/``close`` — the offline fixtures + any simplified
    shape) keeps the plain magnitude heuristic (``/100`` only when ``> 1.0``). Presence,
    not truthiness, so a legit 0¢/`$0.00` survives; nested objects are checked FIRST."""
    for key in ("price", "yes_ask", "yes_bid"):
        obj = item.get(key)
        if isinstance(obj, dict):
            p = _price_from_candle_obj(obj)
            if p is not None:
                return p
    # Flat tick — fraction (fixtures) or cents; disambiguate by magnitude.
    v = _to_float(_first_present(item, ("p", "yes_price", "close")))
    if v is not None:
        return v / 100.0 if v > 1.0 else v
    return None


def _price_from_candle_obj(obj: dict) -> Optional[float]:
    """Normalise a nested Kalshi candlestick sub-object (``price``/``yes_ask``/``yes_bid``)
    to a YES price in [0, 1], handling BOTH the dollar and legacy-cents schemas (see
    ``_candle_price``). Returns None if no usable value is present.

    Field preference mean > close > open; for each, an explicit ``*_dollars`` key wins over
    the bare key. Value normalisation for a bare (non-``*_dollars``) key:
      * ``> 1.0``            → cents/100 (only cents exceed 1);
      * a NON-whole number  → dollars as-is (a real legacy cents value is ALWAYS a whole
                              number in [0,100], so a fractional bare value like ``0.44`` or
                              ``0.6700`` can only be dollars — this closes the auditor-flagged
                              bare-dollar-FLOAT path that a pure type check would misread as
                              ``0.0044``, a silent 100x fabrication that passes the [0,1]
                              range gate);
      * a whole ``0``/``1`` → genuinely ambiguous (0¢/1¢ cents vs $0.00/$1.00 dollars): a
                              decimal STRING is dollars (``"1.0000"`` → 1.0), a NUMBER is
                              legacy cents (``1`` → 0.01). This is the only residual reliance
                              on wire type, and only at the two integer boundaries."""
    for base in ("mean", "close", "open"):
        for key, is_dollars in ((base + "_dollars", True), (base, False)):
            if key not in obj:
                continue
            raw = obj[key]
            if raw is None:
                continue
            v = _to_float(raw)
            if v is None:
                continue
            if is_dollars:
                return v  # explicit dollar field — already a [0,1] probability
            if v > 1.0:
                return v / 100.0  # only cents exceed 1
            if not float(v).is_integer():
                return v  # a fractional bare value can only be dollars (cents are whole)
            # whole 0/1: a decimal STRING is dollars ("1.0000"); a NUMBER is legacy cents.
            return v if isinstance(raw, str) else v / 100.0
    return None


def _to_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _finite_float(value: Any) -> Optional[float]:
    """``_to_float`` but ALSO rejects non-finite (NaN/±inf), booleans, and overflow — so a
    garbage structured strike can never license a cross-venue pairing. A strike is a value the
    matcher will compare numerically; anything that is not a genuine finite number must degrade
    to None (refuse to guess), never propagate. Explicitly:
      * ``bool`` → None (``float(True)==1.0`` would otherwise smuggle a fake 1.0/0.0 strike past
        the matcher's own bool guard, which only sees the already-coerced float);
      * a huge-integer strike whose ``float()`` OVERFLOWS → None (keep the market, drop the
        un-representable strike) rather than raising."""
    if isinstance(value, bool):
        return None
    try:
        f = _to_float(value)
    except OverflowError:  # float(an arbitrarily large int) — a JSON payload may carry one
        return None
    if f is None or not math.isfinite(f):
        return None
    return f


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
        if not math.isfinite(t):
            # A NaN/inf timestamp fails every ordered comparison silently: NaN would pin
            # best_t=NaN and block all later real ticks, returning a fabricated decision
            # price. Reject it up front (the A6/A7/A3 finiteness hardening; regression-tested).
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
