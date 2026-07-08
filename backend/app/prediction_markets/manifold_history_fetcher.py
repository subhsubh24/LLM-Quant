"""Manifold Markets resolved-history fetcher — a READ-ONLY, RESEARCH-ONLY venue (ROADMAP A8).

Manifold is a large, free, reachable set of resolved binary markets with a **PLAY-MONEY**
crowd. Both real-money crowds we have measured (Polymarket, Kalshi) are sharp (Brier
~0.08–0.09). A play-money crowd is plausibly *less* calibrated — exactly where a
calibration/reasoning edge would FIRST appear — so Manifold lets us test the METHOD
("can the model beat a softer crowd?") on a corpus we can actually reach.

CRITICAL RESEARCH-ONLY GUARDRAIL (honesty): Manifold is PLAY money. A Manifold edge validates
the *method* but does **NOT** transfer to real money and must **NEVER** count toward the profit
floor, go-live-eligibility, or any real-money decision (the floor is real-money OOS only). Every
record this module produces is `research_only`; callers must treat it as method-validation +
RESEARCH_MEMORY signal only. This module places NO orders, touches NO money, needs NO credentials.

STRUCTURAL GUARDRAIL (the named A8 follow-up, now IMPLEMENTED): every `HistoricalMarket` this
module emits carries `research_only=True` (the positive provenance tag on `walk_forward.HistoricalMarket`).
The real-money OOS floor lane (`scripts/validate_real_oos.evaluate`) REFUSES any record with that
flag set (raises loudly), so a Manifold corpus can never inflate the real-money profit floor / go-
live-eligibility even by an accidental copy-paste — the property is no longer convention-only. The
tag is pure metadata (EXCLUDED from `_seed_hash`), so it changes no backtest number or hash; it only
fails-closed the one place a play-money record must never reach. (Previously this was enforced only
by CONVENTION — module name + a marker + non-wiring — an adversarial-auditor-disclosed gap.)

Leakage-safety is IDENTICAL to the Polymarket/Kalshi fetchers and reuses their audited
guard (`polymarket_history_fetcher._last_pre_decision_price`):
  * ``decision_time = resolution_time - decision_lead`` — strictly before resolution.
  * ``market_price`` is the ``probAfter`` of the LAST bet at-or-before ``decision_time``
    AND strictly before ``resolution_time`` (a genuine pre-resolution crowd probability).
  * the settled outcome (Manifold ``resolution`` YES/NO) is NEVER the decision price.
  * if no qualifying pre-resolution bet exists, we RAISE (batch: SKIP loudly) — never
    fabricate a decision-time price.

Manifold API (https://docs.manifold.markets/api, public, no auth):
  * ``GET /v0/markets?limit=&before=`` — paged market list (newest-first). We keep only
    ``outcomeType == "BINARY"``, ``isResolved``, ``resolution in {"YES","NO"}``.
  * ``GET /v0/bets?contractId=&limit=&before=`` — the market's bet stream (newest-first);
    each bet carries ``createdTime`` (unix ms) + ``probAfter`` (P[YES] after the bet).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional, Sequence

import requests

from .market_category import derive_market_category
from .polymarket_history_fetcher import _last_pre_decision_price
from .walk_forward import HistoricalMarket

logger = logging.getLogger(__name__)

MANIFOLD_API = "https://api.manifold.markets/v0"
REQUEST_TIMEOUT = 15  # hard deadline on every external call (< the run budget)
_PAGE_LIMIT = 1000    # Manifold's max page size


@dataclass(frozen=True)
class ResolvedManifoldMarket:
    """A genuinely-resolved Manifold BINARY market (play money — research only)."""

    market_id: str
    question: str
    outcome: int                    # 1 if resolved YES, 0 if resolved NO
    created_time: datetime
    resolution_time: datetime
    category: Optional[str] = None


class ManifoldHistoryFetcher:
    """Assembles leakage-safe, RESEARCH-ONLY ``HistoricalMarket`` records from Manifold.

    Play money → the records are for METHOD validation only and must never feed a
    real-money / floor / go-live decision (see the module docstring).
    """

    research_only = True  # class-level marker; ALSO stamped positively onto every emitted
    #                       HistoricalMarket(research_only=True) — the real-money floor lane
    #                       (validate_real_oos.evaluate) refuses those records (structural guardrail).

    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or requests.Session()

    # -- HTTP: ALWAYS timeout=15; None on any RequestException (never hang, never raise up) --
    def _get(self, path: str, params: Optional[dict] = None) -> Any:
        try:
            resp = self.session.get(f"{MANIFOLD_API}/{path}", params=params, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.warning("Manifold GET %s failed: %s", path, e)
            return None
        except ValueError as e:  # malformed JSON
            logger.warning("Manifold GET %s returned non-JSON: %s", path, e)
            return None

    def fetch_resolved_markets(
        self, limit: int = 100, max_pages: int = 10
    ) -> List[ResolvedManifoldMarket]:
        """Page ``/v0/markets`` newest-first, keeping only resolved BINARY YES/NO markets.

        ``limit`` is the per-page size (capped at Manifold's 1000); ``max_pages`` bounds the
        sweep. Pagination uses ``before=<lastId>`` (Manifold's cursor). Non-binary,
        unresolved, and MKT/CANCEL resolutions are dropped (never fabricated into a 0/1).
        """
        out: List[ResolvedManifoldMarket] = []
        before: Optional[str] = None
        page_size = max(1, min(limit, _PAGE_LIMIT))
        for _ in range(max(1, max_pages)):
            params = {"limit": page_size}
            if before:
                params["before"] = before
            raw = self._get("markets", params)
            if not isinstance(raw, list) or not raw:
                break
            for m in raw:
                parsed = self._parse_resolved(m)
                if parsed is not None:
                    out.append(parsed)
            before = raw[-1].get("id")
            if not before or len(raw) < page_size:
                break
        return out

    def _parse_resolved(self, raw: dict) -> Optional[ResolvedManifoldMarket]:
        """Parse one raw market → ResolvedManifoldMarket, or None if not a clean resolved
        binary YES/NO (we never coerce an ambiguous resolution into a 0/1 outcome)."""
        if not isinstance(raw, dict):
            return None
        if raw.get("outcomeType") != "BINARY" or not raw.get("isResolved"):
            return None
        resolution = raw.get("resolution")
        if resolution == "YES":
            outcome = 1
        elif resolution == "NO":
            outcome = 0
        else:
            return None  # MKT / CANCEL / partial — not a clean binary settlement
        mid = raw.get("id")
        question = raw.get("question")
        created = _ms_to_dt(raw.get("createdTime"))
        resolved_at = _ms_to_dt(raw.get("resolutionTime"))
        if not mid or not question or created is None or resolved_at is None:
            return None
        if resolved_at <= created:
            return None  # incoherent lifetime — skip rather than build a degenerate record
        return ResolvedManifoldMarket(
            market_id=str(mid),
            question=str(question),
            outcome=outcome,
            created_time=created,
            resolution_time=resolved_at,
            category=derive_market_category(str(question)),
        )

    def fetch_bet_history(self, market_id: str, max_pages: int = 20) -> List[dict]:
        """Fetch the market's bet stream as ``{"t": <seconds>, "p": <probAfter>}`` ticks.

        Manifold returns bets newest-first; we page backward via ``before=<lastBetId>`` and
        normalize to the same ``{t, p}`` shape ``_last_pre_decision_price`` expects, with
        ``t`` in SECONDS (``createdTime`` ms / 1000) to match ``datetime.timestamp()``.
        A bet's ``probAfter`` is the market's P[YES] immediately after it — a valid
        observation of the crowd probability at ``createdTime``.
        """
        ticks: List[dict] = []
        before: Optional[str] = None
        for _ in range(max(1, max_pages)):
            params = {"contractId": market_id, "limit": _PAGE_LIMIT}
            if before:
                params["before"] = before
            raw = self._get("bets", params)
            if not isinstance(raw, list) or not raw:
                break
            for b in raw:
                t_ms = b.get("createdTime")
                p = b.get("probAfter")
                if isinstance(t_ms, (int, float)) and isinstance(p, (int, float)):
                    ticks.append({"t": float(t_ms) / 1000.0, "p": float(p)})
            before = raw[-1].get("id")
            if not before or len(raw) < _PAGE_LIMIT:
                break
        return ticks

    def to_historical_market(
        self,
        resolved: ResolvedManifoldMarket,
        decision_lead: timedelta,
        *,
        bet_history: Optional[Sequence[dict]] = None,
    ) -> HistoricalMarket:
        """Build a leakage-safe ``HistoricalMarket`` (research only) from a resolved market.

        ``decision_time = resolution_time - decision_lead`` (strictly before resolution).
        ``market_price`` = ``probAfter`` of the last bet at-or-before ``decision_time`` and
        strictly before ``resolution_time`` (via the audited ``_last_pre_decision_price``).
        The settled outcome is NEVER the decision price. RAISES if no qualifying bet exists.
        """
        if decision_lead <= timedelta(0):
            raise ValueError(f"decision_lead must be positive: {decision_lead}")
        decision_time = resolved.resolution_time - decision_lead
        if decision_time <= resolved.created_time:
            raise ValueError(
                f"decision_lead {decision_lead} predates market creation for "
                f"{resolved.market_id}; no pre-decision crowd price can exist"
            )
        assert decision_time < resolved.resolution_time

        history = bet_history if bet_history is not None else self.fetch_bet_history(resolved.market_id)
        decision_ts = decision_time.timestamp()
        resolution_ts = resolved.resolution_time.timestamp()
        market_price = _last_pre_decision_price(history, decision_ts, resolution_ts)
        if market_price is None:
            raise ValueError(
                f"no pre-resolution bet at/before decision_time for Manifold market "
                f"{resolved.market_id}; refusing to fabricate a decision-time price"
            )
        return HistoricalMarket(
            market_id=resolved.market_id,
            decision_time=decision_time,
            resolution_time=resolved.resolution_time,
            market_price=market_price,
            model_prob=market_price,   # naive crowd baseline; a real strategy overrides this
            outcome=resolved.outcome,
            category=resolved.category,
            research_only=True,        # PLAY-MONEY provenance — refused by the real-money floor lane
        )

    def build_historical_markets(
        self,
        resolved_list: Sequence[ResolvedManifoldMarket],
        decision_lead: timedelta,
    ) -> List[HistoricalMarket]:
        """Batch ``to_historical_market``, SKIPPING (loud warning) any market whose
        anti-leakage guard cannot be satisfied. Returns only leakage-safe records."""
        out: List[HistoricalMarket] = []
        skipped = 0
        for rm in resolved_list:
            try:
                out.append(self.to_historical_market(rm, decision_lead))
            except (ValueError, AssertionError) as e:
                skipped += 1
                logger.warning("Manifold: skipping %s (leakage guard): %s", rm.market_id, e)
        if skipped:
            logger.warning("Manifold: skipped %d/%d markets (no leakage-safe pre-decision price)",
                           skipped, len(resolved_list))
        return out


def _ms_to_dt(value: Any) -> Optional[datetime]:
    """A unix-ms timestamp → aware UTC datetime, or None if absent/non-finite."""
    if not isinstance(value, (int, float)):
        return None
    if value != value or value in (float("inf"), float("-inf")):  # NaN/inf guard
        return None
    try:
        return datetime.fromtimestamp(float(value) / 1000.0, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None
