"""kalshi_client.py — read-only Kalshi market-data adapter (ROADMAP A3).

Wraps Kalshi's PUBLIC trade-API v2 (no credentials required for market data).
Parses raw Kalshi JSON into the SAME ``Market``/``Outcome`` model shape used by
``polymarket_client.py`` so the scanner/orchestrator consume it unchanged.

CAPABILITY: kalshi_market_data (no credential required — public data only).

API shape (Kalshi elections base):
  GET /markets
    -> { "markets": [ { ticker, title, subtitle,
                        yes_bid, yes_ask, no_bid, no_ask,
                        volume, open_time, close_time,
                        status, result, category, ... } ] }

Kalshi prices are integer cents in [0, 100]; we divide by 100 to get [0, 1].
Binary markets have YES and NO outcomes; neg_risk is always False (N/A for binary).

INJECTABLE SESSION — accept a ``requests.Session``-like so tests pass a FakeSession.
EVERY outbound call uses ``timeout=15`` (a hard rule — never omit).
``fetched_at`` is stamped at parse time (UTC-aware), matching Polymarket's approach.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, List, Optional

import requests

# Re-use the canonical Market/Outcome model — do NOT redefine them.
from .market_category import derive_market_category
from .polymarket_client import Market, Outcome

logger = logging.getLogger(__name__)

# Public Kalshi elections base URL (no auth for market data).
KALSHI_BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"

# Hard per-request deadline — a required safety rule for every external call.
REQUEST_TIMEOUT = 15

# Kalshi market lifecycle `status` values, per the documented trade-API contract.
# IMPORTANT (honesty caveat): the loop's environment blocks Kalshi egress, so this
# mapping is validated OFFLINE against the DOCUMENTED contract only — it is NOT yet
# confirmed against a live Kalshi response. The OWNER must verify the exact status
# strings on the first real run (an unrecognized status is logged LOUDLY below so a
# contract mismatch surfaces immediately rather than silently dropping every market).
# A response market is tradeable with `status: "active"` (NOT "open" — "open" is the
# request-side FILTER value); resolved markets are "settled"/"finalized"/"determined".
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
    ) -> List[Market]:
        """Fetch markets from Kalshi's public /markets endpoint.

        Args:
            limit: Max markets per page (Kalshi default/max varies; use sensible bound).
            cursor: Pagination cursor returned by a previous call (None = first page).
            status: Filter by market status (e.g. "open", "closed", "settled").
            category: Filter by category slug.

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
        raw_category: str = str(raw.get("category", ""))
        # Route the raw Kalshi category through the SAME coarse correlation-bucket deriver
        # the Polymarket parser uses (ROADMAP A3 follow-up), so the per-category exposure
        # cap buckets Kalshi markets consistently with Polymarket ones (Crypto/Politics/…)
        # instead of stamping a raw venue label verbatim (which would silently sidestep the
        # cap-coherence fix #156). Deterministic + pure; never enters a backtest seed_hash.
        category: str = derive_market_category(
            title, raw_category, tags=[raw_category] if raw_category else None
        )

        # ---- Price conversion (cents -> probability) --------------------
        # Kalshi prices are integer cents [0, 100]. Derive the YES price from the best
        # available signal WITHOUT fabricating a midpoint from a one-sided book:
        #   - both bid & ask quoted -> midpoint
        #   - only one side quoted   -> that side (best available; never average with 0)
        #   - neither, but last_price-> last trade price
        #   - no usable price at all -> NOT tradeable (see has_quote below); never
        #     manufacture a fake 50/50 market (a deep-audit finding: a 0/0 book used to
        #     fall through to 0.5 and pass DataQualityValidator as a tradeable market).
        yes_bid = _to_float(raw.get("yes_bid"))
        yes_ask = _to_float(raw.get("yes_ask"))
        last_price = _to_float(raw.get("last_price"))
        # Bound bid/ask to the documented cent range (0, 100] — the SAME bound the
        # last_price branch already applies below. Without the upper bound an
        # out-of-range/garbage quote (e.g. yes_bid=150, an API glitch or contract
        # change) would pass a bare `> 0`, feed yes_mid_cents, and CLAMP to a
        # fabricated certain-outcome price (150/100 -> min(1.0) = 1.0 YES) — a
        # tradeable market invented from garbage (the data analog of a fake fill /
        # the #101 "a missing quote is not a 50/50 market" honesty rule). A rejected
        # side falls through to has_quote=False -> untradeable, never a fabricated 1.0.
        bid_ok = yes_bid is not None and 0 < yes_bid <= 100
        ask_ok = yes_ask is not None and 0 < yes_ask <= 100
        has_quote = True
        if bid_ok and ask_ok:
            yes_mid_cents = (yes_bid + yes_ask) / 2.0
        elif bid_ok:
            yes_mid_cents = yes_bid
        elif ask_ok:
            yes_mid_cents = yes_ask
        elif last_price is not None and 0.0 < last_price <= 100.0:
            yes_mid_cents = last_price
        else:
            yes_mid_cents = 50.0   # neutral placeholder ONLY — forced untradeable below
            has_quote = False
        yes_price = max(0.0, min(1.0, yes_mid_cents / 100.0))
        no_price = 1.0 - yes_price

        volume = _to_float(raw.get("volume")) or 0.0

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
            tags=[raw_category] if raw_category else [],
            neg_risk=False,  # Kalshi binary markets: neg_risk is N/A
            fetched_at=fetched_at,
        )


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------
def _to_float(value: Any) -> Optional[float]:
    """Coerce a value to float, returning None on failure."""
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


__all__ = [
    "KALSHI_BASE_URL",
    "REQUEST_TIMEOUT",
    "KalshiClient",
]
