"""kalshi_client.py — read-only Kalshi market-data adapter (ROADMAP A3).

Wraps Kalshi's PUBLIC trade-API v2 (no credentials required for market data).
Parses raw Kalshi JSON into the SAME ``Market``/``Outcome`` model shape used by
``polymarket_client.py`` so the scanner/orchestrator consume it unchanged.

CAPABILITY: kalshi_market_data (no credential required — public data only).

API shape (Kalshi elections base):
  GET /markets
    -> { "markets": [ { ticker, title, subtitle,
                        yes_bid, yes_ask, last_price,               # LEGACY cents [0,100]
                        yes_bid_dollars, yes_ask_dollars,           # CURRENT $ [0,1] = prob
                        last_price_dollars, volume, volume_fp,
                        open_time, close_time,
                        status, result, category, ... } ] }

QUOTE SCHEMA (dual — see _yes_probability_from_quotes): Kalshi exposes BOTH a legacy
integer-cents quote (``yes_bid``/``yes_ask``/``last_price`` in [0,100], ÷100 -> prob) and a
current dollar-string quote (``yes_bid_dollars``/``yes_ask_dollars``/``last_price_dollars``,
each already an implied YES probability in [0,1]). As of 2026-07 the LIVE elections API
returns the cents fields as ``null`` and carries the real quote ONLY in ``*_dollars`` — so a
cents-only read marked every live market untradeable. The parser prefers whichever schema
yields a usable, strictly-positive quote (cents first for back-compat, then dollars) and
never fabricates a midpoint from a one-sided/zero book. Binary markets have YES and NO
outcomes; neg_risk is always False (N/A for binary).

INJECTABLE SESSION — accept a ``requests.Session``-like so tests pass a FakeSession.
EVERY outbound call uses ``timeout=15`` (a hard rule — never omit).
``fetched_at`` is stamped at parse time (UTC-aware), matching Polymarket's approach.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any, List, Optional

import requests

# Re-use the canonical Market/Outcome model — do NOT redefine them.
from .polymarket_client import Market, Outcome

logger = logging.getLogger(__name__)

# Public Kalshi elections base URL (no auth for market data).
KALSHI_BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"

# Hard per-request deadline — a required safety rule for every external call.
REQUEST_TIMEOUT = 15

# Kalshi market lifecycle `status` values, per the documented trade-API contract.
# LIVE-CONFIRMED (2026-07): a real /markets?status=open response returns items with
# `status: "active"` (NOT "open" — "open" is the request-side FILTER value). The
# remaining strings (settled/finalized/closed/…) are still validated OFFLINE against the
# DOCUMENTED contract and not each exercised live; an unrecognized status is logged
# LOUDLY below so a contract mismatch surfaces immediately rather than silently dropping
# (or mis-trading) markets. Resolved markets are "settled"/"finalized"/"determined".
_ACTIVE_STATUSES = frozenset({"active", "open"})            # tradeable now
_RESOLVED_STATUSES = frozenset({"settled", "finalized", "determined"})  # winner decided
_CLOSED_STATUSES = frozenset({"closed"})                    # trading ended, not yet determined
_PREOPEN_STATUSES = frozenset({"initialized", "unopened", "inactive"})  # not yet tradeable


class KalshiClient:
    """Read-only Kalshi market-data client.

    Parses public Kalshi market JSON into the same ``Market``/``Outcome`` shape
    used by PolymarketClient so the scanner/orchestrator plug in unchanged.

    Args:
        session: Injectable requests.Session-like (default: real requests.Session).
                 Pass a FakeSession in tests so no real network call is made.
        base_url: Override the API base (useful for pointing at a local mock).
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
    # HTTP helper — mirrors polymarket_client._get exactly.
    # ------------------------------------------------------------------
    def _get(self, url: str, params: Optional[dict] = None) -> Any:
        """GET with a hard ``timeout=15`` deadline. Returns parsed JSON or None."""
        try:
            resp = self.session.get(url, params=params, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status == 404:
                logger.debug("Kalshi API 404: %s", url)
            else:
                logger.error(
                    "Kalshi API error: %s (status=%s, url=%s)", e, status, url
                )
            return None

    # ------------------------------------------------------------------
    # Market discovery
    # ------------------------------------------------------------------
    def get_markets(
        self,
        limit: int = 100,
        cursor: Optional[str] = None,
        status: Optional[str] = None,
        category: Optional[str] = None,
        series_ticker: Optional[str] = None,
    ) -> List[Market]:
        """Fetch markets from Kalshi's public /markets endpoint.

        Args:
            limit: Max markets per page (Kalshi default/max varies; use sensible bound).
            cursor: Pagination cursor returned by a previous call (None = first page).
            status: Filter by market status (e.g. "open", "closed", "settled").
            category: Filter by category slug.
            series_ticker: Restrict to one series (e.g. ``"KXBTCMAXY"``). The B8 co-listed
                numeric universe (BTC/ETH/Fed strikes) is reachable ONLY per-series — the
                unfiltered list is dominated by multi-leg cross-category combos — so this is
                the per-series discovery step of the pinned dual-venue quote path.

        Returns:
            List of ``Market`` objects (same shape as PolymarketClient output).
        """
        params: dict = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        if status:
            params["status"] = status
        if category:
            params["category"] = category
        if series_ticker:
            params["series_ticker"] = series_ticker

        data = self._get(f"{self.base_url}/markets", params=params)
        if not data:
            logger.warning("[KALSHI] /markets returned empty/null (params=%s)", params)
            return []

        raw_markets = data.get("markets") if isinstance(data, dict) else None
        if not isinstance(raw_markets, list):
            logger.warning(
                "[KALSHI] /markets response has no 'markets' list; keys=%s",
                list(data.keys()) if isinstance(data, dict) else type(data).__name__,
            )
            return []

        now = datetime.now(timezone.utc)
        markets: List[Market] = []
        parse_errors = 0
        for raw in raw_markets:
            try:
                m = self._parse_market(raw, fetched_at=now)
                markets.append(m)
            except Exception as e:
                parse_errors += 1
                if parse_errors <= 3:
                    logger.warning(
                        "[KALSHI] Market parse error: %s | raw keys: %s",
                        e,
                        list(raw.keys()) if isinstance(raw, dict) else type(raw).__name__,
                    )
        if parse_errors > 3:
            logger.warning("[KALSHI] %d total parse errors", parse_errors)
        logger.info(
            "[KALSHI] Fetched %d markets (raw=%d, errors=%d)",
            len(markets),
            len(raw_markets),
            parse_errors,
        )
        return markets

    # ------------------------------------------------------------------
    # Parsing — the core logic (pure, fully unit-testable)
    # ------------------------------------------------------------------
    def _parse_market(
        self,
        raw: dict,
        fetched_at: Optional[datetime] = None,
    ) -> Market:
        """Parse one raw Kalshi market dict into a ``Market`` object.

        Price conversion: Kalshi prices are integer cents [0, 100]. YES price comes from
        the best available signal (both-sided midpoint, else the one quoted side, else
        last_price); a market with NO usable quote is marked untradeable (active=False)
        rather than presenting a fabricated 0.50. NO price = 1 - YES (binary).

        Status mapping uses the documented _*_STATUSES sets (active/open -> active;
        settled/finalized/determined -> resolved; closed -> closed; initialized/unopened
        -> pre-open; UNRECOGNIZED -> untradeable + a loud warning). See the module-level
        honesty caveat: the contract is offline-validated, not yet confirmed live.

        Args:
            raw: Raw dict from Kalshi /markets response item.
            fetched_at: UTC-aware ingest timestamp (stamped at parse time if not supplied).

        Returns:
            ``Market`` instance with ``Outcome`` objects for YES and NO.

        Raises:
            KeyError/ValueError: if the raw dict is fundamentally malformed (ticker missing, etc.)
                                  Callers (get_markets) catch and skip.
        """
        if fetched_at is None:
            fetched_at = datetime.now(timezone.utc)

        ticker: str = str(raw["ticker"])  # raises KeyError if missing — caller skips

        title: str = str(raw.get("title", ""))
        subtitle: str = str(raw.get("subtitle", ""))
        category: str = str(raw.get("category", ""))

        # ---- Price conversion (best available quote -> probability) ------
        # Kalshi ships TWO quote schemas in the wild and we support BOTH (see
        # _yes_probability_from_quotes): the LEGACY integer-cents fields
        # (yes_bid/yes_ask/last_price in [0,100]) and the CURRENT dollar-string fields
        # (yes_bid_dollars/yes_ask_dollars/last_price_dollars, each an implied YES
        # probability in [0,1] on a $1-settling contract). As of 2026-07 the live
        # elections API returns the cents fields as null and carries the real quote ONLY
        # in the *_dollars fields, so reading cents alone marked EVERY live market
        # untradeable. The derivation NEVER fabricates a midpoint from a one-sided or
        # zero/out-of-range book — a market with no usable quote on either schema is
        # forced untradeable rather than presenting a fake 50/50 (#101 honesty rule).
        yes_price, has_quote = _yes_probability_from_quotes(raw)
        no_price = 1.0 - yes_price

        # Volume: legacy `volume` (a plain number) else current `volume_fp` (a fixed-point
        # string); either is coerced to a finite float, defaulting to 0.0.
        volume = _to_float(raw.get("volume"))
        if volume is None:
            volume = _to_float(raw.get("volume_fp"))
        volume = volume or 0.0

        # ---- Status mapping --------------------------------------------
        # See the module-level _*_STATUSES sets + the honesty caveat there. An
        # UNRECOGNIZED status is logged LOUDLY and treated as untradeable so a live
        # contract mismatch surfaces on the first real run instead of silently dropping
        # (or, worse, mis-trading) markets.
        status_str = str(raw.get("status", "")).lower().strip()
        if status_str in _ACTIVE_STATUSES:
            active, closed, resolved = True, False, False
        elif status_str in _RESOLVED_STATUSES:
            active, closed, resolved = False, True, True
        elif status_str in _CLOSED_STATUSES:
            active, closed, resolved = False, True, False
        elif status_str in _PREOPEN_STATUSES:
            active, closed, resolved = False, False, False
        else:
            logger.warning(
                "Kalshi market %s: unrecognized status %r — treating as untradeable. "
                "Verify the live Kalshi status contract (egress-blocked offline).",
                ticker, status_str,
            )
            active, closed, resolved = False, False, False

        # A market with no usable quote is NEVER tradeable, regardless of status —
        # don't let a no-quote 'active' market present a fabricated 0.50 price.
        if not has_quote:
            active = False

        # ---- End date --------------------------------------------------
        end_date: Optional[datetime] = None
        for date_field in ("close_time", "expiration_time", "open_time"):
            raw_dt = raw.get(date_field)
            if raw_dt:
                end_date = _parse_dt(raw_dt)
                if end_date is not None:
                    break

        # ---- Build Outcomes --------------------------------------------
        # YES outcome — token_id is ticker + "-YES" (Kalshi's conventional token id)
        yes_outcome = Outcome(
            token_id=f"{ticker}-YES",
            label="Yes",
            price=yes_price,
            midpoint=yes_price,
            volume=volume,
        )
        # NO outcome — price is complement; volume attributed to YES side (binary)
        no_outcome = Outcome(
            token_id=f"{ticker}-NO",
            label="No",
            price=no_price,
            midpoint=no_price,
            volume=volume,
        )

        return Market(
            id=ticker,
            condition_id=ticker,
            question=title,
            slug=ticker.lower(),
            description=subtitle,
            category=category,
            end_date=end_date,
            outcomes=[yes_outcome, no_outcome],
            total_volume=volume,
            liquidity=0.0,  # Kalshi /markets doesn't expose liquidity directly
            active=active,
            closed=closed,
            resolved=resolved,
            resolution_source="kalshi",
            tags=[category] if category else [],
            neg_risk=False,  # Kalshi binary markets: neg_risk is N/A
            fetched_at=fetched_at,
        )


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------
def _yes_probability_from_quotes(raw: dict) -> tuple[float, bool]:
    """Derive the YES probability in [0, 1] + a ``has_quote`` flag from either Kalshi
    quote schema, WITHOUT fabricating a midpoint from a one-sided or zero/garbage book.

    Kalshi exposes two schemas: the LEGACY integer-cents fields
    (``yes_bid``/``yes_ask``/``last_price`` in (0, 100]) and the CURRENT dollar-string
    fields (``yes_bid_dollars``/``yes_ask_dollars``/``last_price_dollars``, each already an
    implied YES probability in (0, 1] on a $1-settling contract). As of 2026-07 the live
    elections API returns the cents fields as ``null`` and quotes ONLY in ``*_dollars``, so
    a cents-only read marked every live market untradeable. Preference order (cents first
    for back-compat, then dollars), each branch requiring a STRICTLY-POSITIVE in-range
    quote so a 0 / missing / out-of-range side can never invent a tradeable price:

        both bid & ask -> midpoint;  one side -> that side;  else -> last trade price.

    Returns ``(0.5, False)`` when NEITHER schema yields a usable quote — a neutral
    placeholder the caller forces untradeable, never a fabricated 50/50 (#101 honesty rule).
    """
    # Legacy integer cents in (0, 100] -> /100. The upper bound rejects a garbage quote
    # (e.g. yes_bid=150) that a bare `> 0` would clamp to a fabricated certain outcome.
    yb, ya = _to_float(raw.get("yes_bid")), _to_float(raw.get("yes_ask"))
    lp = _to_float(raw.get("last_price"))
    bid_ok = yb is not None and 0 < yb <= 100
    ask_ok = ya is not None and 0 < ya <= 100
    if bid_ok and ask_ok:
        return max(0.0, min(1.0, (yb + ya) / 200.0)), True
    if bid_ok:
        return max(0.0, min(1.0, yb / 100.0)), True
    if ask_ok:
        return max(0.0, min(1.0, ya / 100.0)), True
    if lp is not None and 0 < lp <= 100:
        return max(0.0, min(1.0, lp / 100.0)), True

    # Current dollar strings — already a probability in (0, 1]; the same (0, 1] bound
    # rejects a "0.0000" placeholder (untradeable) and any out-of-range garbage.
    dyb, dya = _to_float(raw.get("yes_bid_dollars")), _to_float(raw.get("yes_ask_dollars"))
    dlp = _to_float(raw.get("last_price_dollars"))
    dbid_ok = dyb is not None and 0 < dyb <= 1
    dask_ok = dya is not None and 0 < dya <= 1
    if dbid_ok and dask_ok:
        return max(0.0, min(1.0, (dyb + dya) / 2.0)), True
    if dbid_ok:
        return dyb, True
    if dask_ok:
        return dya, True
    if dlp is not None and 0 < dlp <= 1:
        return dlp, True

    return 0.5, False


def _to_float(value: Any) -> Optional[float]:
    """Coerce a value to a FINITE float, returning None on failure.

    A malformed ``"nan"``/``"inf"``/``"Infinity"`` coerces cleanly through ``float()``
    but must never survive: the volume path does ``_to_float(...) or 0.0`` and a NaN is
    truthy, so a non-finite volume would flow into the ``Market`` and slip past strategy
    filters (``NaN < min_volume`` is False) — the same invented-data-into-the-decision
    class the Polymarket parser guards against. Reject non-finite here (returns None) so
    every ``_to_float`` caller stays finite by construction."""
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


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


__all__ = [
    "KALSHI_BASE_URL",
    "REQUEST_TIMEOUT",
    "KalshiClient",
]
