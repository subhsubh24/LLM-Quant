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

TWO DISCOVERY PATHS (they reach DIFFERENT universes — pick deliberately)
* ``fetch_resolved_markets`` pages ``/markets?status=settled``. Live-probed, that feed
  is ~100% high-frequency sports; its ``categories`` argument is a POST-FETCH LOCAL
  filter and therefore cannot surface a political or economic market.
* ``fetch_resolved_markets_by_category`` pages ``/events?status=settled`` (the listing
  that actually carries Kalshi's ``category``, and which is ~70% political/economic)
  and then joins each event to its markets. This is the only path that reaches the
  political/economic universe. It produces the SAME ``KalshiResolvedMarket`` type and
  feeds the SAME leakage-safe assembly — it changes DISCOVERY only, never pricing.
  See the "EVENTS-BY-CATEGORY discovery" section for the live-vs-documented findings
  (notably: ``/events?category=`` is accepted and IGNORED by Kalshi today).

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

# Market ``status`` values we have actually OBSERVED on the live wire (census run
# 2026-07-27 over 150 settled political/economic events, both the live and the
# ``/historical`` tier): {"finalized": 828, "active": 198} dominate. An independent
# reviewer's own live census over 40 settled Politics events also turned up a single
# ``"closed"`` — rarer than the two above but real, so the earlier "and NOTHING else"
# claim here was an overstatement of one sample and is corrected rather than kept.
# (It was already in the set below as a documented lifecycle state, so nothing behaved
# wrongly; the comment was simply describing a stronger observation than we made.) The
# older docs (and this module's original comments) named "settled"/"determined";
# those never appeared in either census, so they are kept here as ACCEPTED-BUT-UNSEEN
# rather than dropped — a status we cannot vouch for must not be silently discarded.
#
# WHY A SET AND NOT A SILENT PASS-THROUGH: the co-listed universe is discovered by
# fanning out over events, so a Kalshi contract change (a new status token) would
# show up as a quiet shortfall in record count — the exact BUILDS≠WORKS failure this
# file has already been burned by. An unrecognised status therefore logs at WARNING
# (once per market) and the market is STILL parsed on its ``result`` field, which is
# the only thing the YES/NO outcome has ever been derived from. Loud, never dropped.
KNOWN_MARKET_STATUSES = frozenset(
    {
        "active",       # LIVE-OBSERVED — open, not yet resolved
        "finalized",    # LIVE-OBSERVED — resolved and settled; carries result yes/no
        "settled",      # documented; not observed in the 2026-07-27 census
        "determined",   # documented; not observed in the 2026-07-27 census
        "closed",       # documented lifecycle state
        "initialized",  # documented lifecycle state
        "unopened",     # documented lifecycle state
    }
)

# Kalshi event ``category`` values that carry the political/economic universe the
# cross-venue (B8) work needs. Exposed as a NAMED constant so any use of it is a
# PRE-REGISTERED choice rather than a post-hoc subset (see the module docstring's
# p-hacking caveat). LIVE census over 1600 settled events (2026-07-27):
# Elections 751, Politics 263, Economics 57, Financials 41 — vs Sports 125. The
# ``/markets?status=settled`` feed this module already had is, by contrast, ~100%
# high-frequency sports, which is precisely why an events-first path is needed.
POLITICAL_ECONOMIC_CATEGORIES = ("Politics", "Elections", "Economics", "Financials")


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


@dataclass(frozen=True)
class KalshiEvent:
    """One Kalshi EVENT from the ``/events`` listing — the discovery unit that carries
    a ``category``.

    WHY THIS TYPE EXISTS AT ALL: an individual Kalshi MARKET returned by
    ``/events/{event_ticker}`` carries no ``category`` field — the taxonomy lives one
    level up, on the event. So the events listing is both the only place the category
    is legible AND the only listing whose settled feed is not swamped by
    high-frequency sports. Keeping the event as a first-class record (rather than a
    bare ticker string) is what lets the events→markets join stamp the real category
    onto each resolved market without a second lookup.

    Fields are the ones the LIVE ``/events`` payload actually carries (verified
    2026-07-27); anything missing degrades to "" rather than being invented.
    """

    event_ticker: str
    series_ticker: str
    category: str
    title: str


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
    # EVENTS-BY-CATEGORY discovery (ROADMAP B8 / A3)
    #
    # WHY THIS PATH EXISTS — READ BEFORE CHANGING ANYTHING BELOW.
    # ``fetch_resolved_markets`` above pages ``/markets?status=settled``. That feed was
    # live-probed and is ~100% high-frequency sports (1200 markets scanned, 0 political
    # — dominated by KXMVESPORTS*/KXMVECROSSCATEGORY). The ``categories`` argument on
    # that method is a POST-FETCH LOCAL filter: it can only subset a page that is
    # already sports-only, so it can never surface a political or economic market. That
    # is the entire reason every prior B8 co-listed-universe probe found 0 matches.
    #
    # Kalshi's taxonomy lives on the EVENT, not the market, and the ``/events`` listing
    # is category-diverse where ``/markets`` is not. LIVE census 2026-07-27, 1600
    # settled events paged from ``/events?status=settled``:
    #     Elections 751 · Politics 263 · Entertainment 241 · Sports 125 · Economics 57
    #     · Financials 41 · Science and Technology 32 · Mentions 31 · Crypto 24 · …
    # i.e. 1112 / 1600 political-or-economic. So: discover EVENTS, then resolve each
    # event to its markets, then hand those markets to the SAME ``_parse_resolved`` and
    # the SAME leakage-safe assembly the rest of this module already uses.
    #
    # WHAT THE LIVE API ACTUALLY DOES vs. WHAT IS DOCUMENTED (probed 2026-07-27; this
    # module has been burned before by encoding a documented contract that differed
    # from the live response, so every claim here is a real observation):
    #   * ``GET /events?status=settled`` — WORKS. Cursor-paginated, response shape
    #     ``{"cursor": str, "events": [...], "milestones": [...]}``. Each event carries
    #     ``event_ticker``/``series_ticker``/``category``/``title``. An event carries NO
    #     ``status`` field of its own in the response — ``status`` is request-side only.
    #   * ``GET /events?category=…`` — **DOES NOT FILTER.** Passing ``Politics``,
    #     ``Economics``, ``Financials`` or the deliberate nonsense ``NOTAREALCATEGORY``
    #     all returned the BYTE-IDENTICAL first page (same cursor, same 50 tickers, same
    #     mixed category histogram). The parameter is accepted (HTTP 200) and ignored.
    #     We still FORWARD it (harmless, and it starts working the day Kalshi implements
    #     it) but we MUST NOT trust it: ``_event_matches_category`` re-checks the
    #     ``category`` the response actually carries. That backstop is not belt-and-
    #     braces, it is the only thing doing the filtering today.
    #   * ``GET /events?series_ticker=…&status=settled`` — WORKS server-side (a real
    #     series returned only its own events; a nonsense series returned ``[]``).
    #   * ``GET /series?category=Politics`` — WORKS server-side, and is the ONE genuine
    #     server-side category filter on this API: 2120 series returned, 2046 of them
    #     ``Politics``; ``category=Bogus`` returns ``{"series": null}``. Exposed as
    #     ``fetch_series_tickers`` so a caller can narrow the event query to a
    #     server-side-selected series set instead of relying on the response backstop.
    #   * ``GET /markets?ticker=…`` and ``GET /markets?category=…`` — DO NOT FILTER
    #     either (``?ticker=`` returns the unfiltered firehose). Not used here.
    # ------------------------------------------------------------------
    def fetch_series_tickers(
        self,
        category: str,
        *,
        max_series: Optional[int] = None,
    ) -> List[str]:
        """Series tickers in ``category``, filtered SERVER-SIDE by ``/series?category=``.

        This is the only endpoint on the public Kalshi API whose ``category`` parameter
        was observed to actually filter (live 2026-07-27: ``Politics`` → 2120 series,
        2046 of them categorised ``Politics``; ``Bogus`` → ``{"series": null}``). Use it
        when you want the category narrowing to happen on Kalshi's side — feed the
        returned tickers to ``fetch_resolved_events(series_ticker=…)``, whose
        ``series_ticker`` filter is also genuinely server-side.

        ``/series`` is NOT cursor-paginated in the observed response (no ``cursor`` key),
        so this is a single bounded request — there is no loop to run away. ``max_series``
        truncates the returned list purely to bound a caller's downstream fan-out.

        Args:
            category: Kalshi category string, e.g. "Politics" (case as Kalshi returns it).
            max_series: Optional cap on how many tickers are returned.

        Returns:
            List of series ticker strings (possibly empty — never None).
        """
        data = self._get(f"{self.base_url}/series", params={"category": category})
        if not isinstance(data, dict):
            return []
        # A rejected/unknown category comes back as {"series": null}, NOT as an error and
        # NOT as [] — hence the explicit isinstance check rather than a truthiness test.
        raw_series = data.get("series")
        if not isinstance(raw_series, list):
            logger.info(
                "Kalshi /series?category=%r returned no series list (category unknown "
                "to Kalshi, or an empty category)",
                category,
            )
            return []

        tickers: List[str] = []
        for item in raw_series:
            if not isinstance(item, dict):
                continue
            ticker = item.get("ticker")
            if ticker:
                tickers.append(str(ticker))
        if max_series is not None:
            tickers = tickers[:max_series]
        logger.info(
            "fetched %d Kalshi series for category=%r (server-side filter)",
            len(tickers),
            category,
        )
        return tickers

    def fetch_resolved_events(
        self,
        *,
        categories: Optional[Sequence[str]] = None,
        series_ticker: Optional[str] = None,
        status: str = "settled",
        limit: int = 200,
        max_pages: int = 10,
    ) -> List[KalshiEvent]:
        """Page ``/events`` for events whose markets are resolved, optionally by category.

        ``status`` is forwarded server-side and defaults to ``"settled"`` — the same
        request-side filter word ``fetch_resolved_markets`` uses, and the reason the
        returned events are ones whose markets have (mostly) resolved. Note that an
        event under ``status=settled`` can still contain individual ``active`` markets
        (LIVE-OBSERVED: 198 of 1026 markets across 150 settled political events); those
        are skipped by ``_parse_resolved`` on their empty ``result``, which is correct —
        the event-level filter is a coarse discovery hint, not a per-market guarantee.

        ``categories`` is forwarded as the documented ``category`` query parameter AND
        re-applied against the ``category`` each event actually carries. The forwarding
        is currently a no-op on Kalshi's side (see the section comment above: a nonsense
        category returns the identical page), so the response-side check is what really
        selects. Unlike ``fetch_resolved_markets(categories=…)`` — which subsets an
        already-sports-only page and is therefore useless — this filters a feed that is
        genuinely ~70% political/economic, so it reaches the universe B8 needs.

        ``max_pages`` HARD-BOUNDS the cursor loop; it must never run unbounded. Every
        request goes through ``_get``, i.e. carries the module-wide ``timeout=15``.

        Args:
            categories: Optional allowlist of Kalshi category strings (case-insensitive).
            series_ticker: Optional Kalshi series filter (genuinely server-side).
            status: Kalshi event status filter, forwarded server-side.
            limit: Events per page.
            max_pages: Hard upper bound on page requests (safety: never unbounded).

        Returns:
            List of ``KalshiEvent`` records.
        """
        cats = {c.lower() for c in categories} if categories else None
        out: List[KalshiEvent] = []
        cursor: Optional[str] = None

        for _page in range(max_pages):
            params: dict = {"limit": limit}
            if status:
                params["status"] = status
            if series_ticker:
                params["series_ticker"] = series_ticker
            if cats:
                # Forwarded for the day Kalshi honours it; NOT relied upon (see above).
                # Deterministic ordering so a fixture/assertion can pin the exact value.
                params["category"] = ",".join(sorted(categories or ()))
            if cursor:
                params["cursor"] = cursor

            data = self._get(f"{self.base_url}/events", params=params)
            if not isinstance(data, dict):
                break

            raw_events = data.get("events")
            if not raw_events or not isinstance(raw_events, list):
                break

            for raw in raw_events:
                ev = _parse_event(raw)
                if ev is None:
                    continue
                if cats is not None and ev.category.lower() not in cats:
                    continue
                out.append(ev)

            # Same cursor discipline as fetch_resolved_markets: stop on a missing cursor
            # or a short page. Kalshi returns "" (falsy) for the final page's cursor.
            cursor = data.get("cursor") or None
            if not cursor or len(raw_events) < limit:
                break

        logger.info(
            "discovered %d Kalshi events (status=%r, categories=%s) across <=%d pages",
            len(out),
            status,
            sorted(cats) if cats else None,
            max_pages,
        )
        return out

    def fetch_event_markets(
        self,
        event_ticker: str,
        *,
        historical: bool = False,
    ) -> List[dict]:
        """Raw market dicts belonging to one event — the events→markets JOIN.

        WHICH ENDPOINT, AND WHY (all three candidates were probed live over the SAME 60
        settled political/economic events, 2026-07-27):
          * ``GET /events/{event_ticker}``            → markets for 17 / 60 events  ← used
          * ``GET /markets?event_ticker=…``           → markets for  8 / 60 events
          * ``GET /historical/markets?event_ticker=…``→ markets for 18 / 60 events  ← used
        So the documented ``/markets?event_ticker=`` route is strictly WORSE than reading
        the event detail and is not used. The live and historical routes are
        COMPLEMENTARY, not redundant (Kalshi's live tier only serves a rolling window —
        ``/historical/cutoff`` reported ``market_settled_ts = 2026-05-28`` on this run),
        so ``historical`` selects which tier to read and a corpus build runs both.

        RESPONSE-SHAPE TRAP (cost a probe iteration): ``/events/{t}`` returns its markets
        at the TOP LEVEL as ``{"event": {...}, "markets": [...]}`` by DEFAULT, but moves
        them to ``{"event": {"markets": [...]}}`` when ``with_nested_markets=true`` is
        passed. Reading only one of the two silently yields zero markets. We pass the
        documented ``with_nested_markets=true`` and accept BOTH placements.

        Returns raw dicts (not parsed) so the caller can stamp the event's category on
        them before handing them to the shared ``_parse_resolved``.

        Args:
            event_ticker: e.g. "KXNEXTUKPM-30".
            historical: Read the deep ``/historical/markets`` tier instead of the live one.

        Returns:
            List of raw market dicts (possibly empty — never None).
        """
        if historical:
            data = self._get(
                f"{self.base_url}/historical/markets",
                params={"event_ticker": event_ticker, "limit": 200},
            )
        else:
            data = self._get(
                f"{self.base_url}/events/{event_ticker}",
                params={"with_nested_markets": "true"},
            )
        if not isinstance(data, dict):
            return []

        # Accept both observed placements (see RESPONSE-SHAPE TRAP above). Presence, not
        # truthiness, is irrelevant here — an empty list at one key legitimately means
        # "look at the other key", which is exactly what the `or` chain does.
        markets = data.get("markets")
        if not markets:
            event_obj = data.get("event")
            if isinstance(event_obj, dict):
                markets = event_obj.get("markets")
        if not isinstance(markets, list):
            return []
        return [m for m in markets if isinstance(m, dict)]

    def fetch_resolved_markets_by_category(
        self,
        categories: Sequence[str] = POLITICAL_ECONOMIC_CATEGORIES,
        *,
        limit: int = 200,
        max_pages: int = 10,
        max_events: int = 200,
        series_ticker: Optional[str] = None,
        status: str = "settled",
        historical: bool = False,
    ) -> List[KalshiResolvedMarket]:
        """Resolved markets reached via EVENTS-BY-CATEGORY → MARKETS-BY-EVENT.

        This is the discovery path ``fetch_resolved_markets`` cannot provide: it selects
        on the EVENT taxonomy (where Kalshi's category actually lives, and whose settled
        feed is ~70% political/economic) instead of subsetting the sports-only
        ``/markets?status=settled`` page. The OUTPUT type is unchanged —
        ``KalshiResolvedMarket`` — so the existing leakage-safe assembly
        (``to_historical_market`` / ``build_historical_markets``) consumes it verbatim,
        with the identical anti-leakage guarantee. Nothing about pricing is re-implemented
        here; this method does discovery only.

        SELECTION BIAS + P-HACKING (the module docstring's caveats apply with FULL force):
        ``categories`` is a pre-registration obligation, not a tuning knob. It defaults to
        the named ``POLITICAL_ECONOMIC_CATEGORIES`` constant so the common case is a
        declared choice rather than an ad-hoc one. Only markets with an unambiguous
        yes/no ``result`` survive, so contested/voided markets — the ones where the crowd
        was most wrong — are excluded, exactly as in ``fetch_resolved_markets``.

        EVERY LOOP IS BOUNDED: ``max_pages`` bounds the ``/events`` cursor paging and
        ``max_events`` bounds the per-event fan-out (one request per event), so the worst
        case is ``max_pages + max_events`` requests, each with ``timeout=15``.

        ``historical`` selects the market tier for the join AND must be passed through to
        ``build_historical_markets(historical=…)`` for the matching candlestick tier — the
        live candlesticks 404 for a market past Kalshi's rolling cutoff, and vice versa.

        Args:
            categories: Kalshi event categories to keep (PRE-REGISTER these).
            limit: Events per ``/events`` page.
            max_pages: Hard bound on ``/events`` page requests.
            max_events: Hard bound on how many events are expanded to markets.
            series_ticker: Optional server-side series narrowing for the event query.
            status: Event status filter forwarded to ``/events``.
            historical: Use the deep ``/historical`` market tier for the join.

        Returns:
            List of ``KalshiResolvedMarket``, deduplicated by ticker (an event's markets
            can be reachable from more than one query in a multi-series build).
        """
        events = self.fetch_resolved_events(
            categories=categories,
            series_ticker=series_ticker,
            status=status,
            limit=limit,
            max_pages=max_pages,
        )

        out: List[KalshiResolvedMarket] = []
        seen: set = set()
        for event in events[:max_events]:
            for raw in self.fetch_event_markets(event.event_ticker, historical=historical):
                _warn_unknown_status(raw)
                # A market returned under an event carries NO category of its own — the
                # taxonomy is on the event. Stamp the event's category on a COPY (never
                # mutate the API payload, which a caller may still be holding) so the
                # shared _parse_resolved derives a real correlation bucket instead of
                # falling through to "General". An explicit category on the market wins.
                if not raw.get("category") and event.category:
                    raw = {**raw, "category": event.category}
                try:
                    rm = self._parse_resolved(raw)
                except Exception as e:
                    logger.debug("skipping unparseable Kalshi market: %s", e)
                    continue
                if rm is None:
                    continue
                if rm.ticker in seen:
                    continue
                seen.add(rm.ticker)
                out.append(rm)

        logger.info(
            "events-by-category discovery: %d resolved Kalshi markets from %d/%d events "
            "(categories=%s, historical=%s)",
            len(out),
            min(len(events), max_events),
            len(events),
            list(categories),
            historical,
        )
        return out

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


def _parse_event(raw: Any) -> Optional[KalshiEvent]:
    """Parse one raw ``/events`` item into a ``KalshiEvent``; None if it has no ticker.

    Only ``event_ticker`` is load-bearing (it is the join key for
    ``fetch_event_markets``) so it is the only hard requirement. ``series_ticker``,
    ``category`` and ``title`` degrade to "" rather than being invented — an event with
    a missing category simply fails the category allowlist instead of being guessed into
    one. LIVE-OBSERVED: one event in a 1600-event census had a null ``category``."""
    if not isinstance(raw, dict):
        return None
    event_ticker = raw.get("event_ticker")
    if not event_ticker:
        logger.debug("skip Kalshi event missing event_ticker")
        return None
    return KalshiEvent(
        event_ticker=str(event_ticker),
        series_ticker=str(raw.get("series_ticker") or ""),
        category=str(raw.get("category") or ""),
        title=str(raw.get("title") or ""),
    )


def _warn_unknown_status(raw: dict) -> None:
    """Log LOUDLY (WARNING) when a market's ``status`` is one we have never observed
    and cannot vouch for — and then let the market through anyway.

    This mirrors the convention ``_parse_resolved`` already uses for an unrecognised
    ``result``: a real CONTRACT surprise the owner must SEE on the first live fetch is a
    WARNING, while an ordinary absence stays quiet. An unknown status is NEVER a reason
    to drop a market — the YES/NO outcome has only ever been derived from ``result``, so
    dropping on status would silently shrink the corpus for a cosmetic field change,
    which is the exact BUILDS≠WORKS class of failure this module has already hit. An
    ABSENT status is silent (nothing surprising happened); an unknown non-empty token is
    loud."""
    status = str(raw.get("status") or "").lower().strip()
    if status and status not in KNOWN_MARKET_STATUSES:
        logger.warning(
            "Kalshi market ticker=%s has UNRECOGNIZED status=%r (known: %s) — the market "
            "is still parsed from its `result` field, but verify the Kalshi market "
            "lifecycle contract",
            raw.get("ticker"),
            status,
            sorted(KNOWN_MARKET_STATUSES),
        )


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
    "KNOWN_MARKET_STATUSES",
    "POLITICAL_ECONOMIC_CATEGORIES",
    "KalshiEvent",
    "KalshiResolvedMarket",
    "KalshiHistoryFetcher",
]
