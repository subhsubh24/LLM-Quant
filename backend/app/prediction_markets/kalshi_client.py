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
from .polymarket_client import Market, Outcome

logger = logging.getLogger(__name__)

# Public Kalshi elections base URL (no auth for market data).
KALSHI_BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"

# Hard per-request deadline — a required safety rule for every external call.
REQUEST_TIMEOUT = 15


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

        Price conversion: Kalshi prices are integer cents [0, 100].
        YES price = midpoint of (yes_bid, yes_ask) / 100.
        NO price  = 1 - YES  (binary, so NO = 1 - P[YES]).
        If both bid/ask are missing/zero we fall back to 0.5 (midpoint assumption).

        Status mapping:
          status == "open"                        -> active=True,  closed=False, resolved=False
          status in ("finalized", "settled")      -> active=False, closed=True,  resolved=True
          status == "closed"                      -> active=False, closed=True,  resolved=False
          anything else                           -> active=False, closed=False, resolved=False

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

        # ---- Price conversion (cents -> probability) --------------------
        yes_bid = _to_float(raw.get("yes_bid")) or 0.0
        yes_ask = _to_float(raw.get("yes_ask")) or 0.0
        # Kalshi prices are cents (integers 0-100). Midpoint of bid/ask.
        if yes_bid > 0 or yes_ask > 0:
            yes_mid_cents = (yes_bid + yes_ask) / 2.0
        else:
            yes_mid_cents = 50.0  # fallback when no quotes
        yes_price = yes_mid_cents / 100.0
        # Clamp to [0, 1] as a safety guard against stale/weird quotes.
        yes_price = max(0.0, min(1.0, yes_price))
        no_price = 1.0 - yes_price

        volume = _to_float(raw.get("volume")) or 0.0

        # ---- Status mapping --------------------------------------------
        status_str = str(raw.get("status", "")).lower()
        if status_str == "open":
            active, closed, resolved = True, False, False
        elif status_str in ("finalized", "settled"):
            active, closed, resolved = False, True, True
        elif status_str == "closed":
            active, closed, resolved = False, True, False
        else:
            active, closed, resolved = False, False, False

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
