"""
Data-Quality Gates for Prediction Markets — ROADMAP A5.

Bad market data leads to bad fills: stale quotes produce mis-sized orders,
incomplete markets hide missing token IDs that break execution, and price
imbalances signal feed corruption or illiquid books.  This module is the
single choke-point that checks every market **before** any sizing or
execution occurs.  A market that fails any gate is skipped with a logged
reason; valid markets are never affected.

Three dimensions are checked:
  staleness    — how old is the price snapshot we received?
  completeness — are all required fields present and well-typed?
  price_sanity — are individual prices in [0,1] and do they sum correctly?
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional


# ============================================================
# Result types
# ============================================================


@dataclass(frozen=True)
class QualityIssue:
    """A single data-quality problem detected on a market."""

    dimension: str  # one of "staleness", "completeness", "price_sanity"
    detail: str


@dataclass(frozen=True)
class QualityCheckResult:
    """Aggregated result of all quality checks for one market."""

    ok: bool
    issues: list[QualityIssue]

    @property
    def reason(self) -> str:
        """Human-readable summary — empty if ok, joined issues otherwise."""
        if not self.issues:
            return "ok"
        return "; ".join(f"[{i.dimension}] {i.detail}" for i in self.issues)


# ============================================================
# Validator
# ============================================================


class DataQualityValidator:
    """
    Runs staleness, completeness, and price-sanity checks against a Market.

    All checks are **deterministic and network-free** — they only inspect the
    data already present in the Market object.  The injected ``now`` / ``fetched_at``
    parameters let unit tests drive the clock.

    Args:
        max_age_seconds:  Maximum acceptable age (seconds) for a price snapshot.
        max_binary_spread: Maximum allowed |sum(prices) - 1| for binary markets.
        multi_sum_tol:    Maximum allowed |sum(prices) - 1| for multi-outcome markets.
        price_eps:        Tolerance added to the [0, 1] bounds check
                          (handles floating-point representation noise).
        max_past_end_seconds: Grace period after a market's ``end_date`` before its data
                          is treated as stale. A market still being scanned more than
                          this long after it was due to resolve is a real
                          data-staleness signal that fires even WITHOUT a fetch
                          timestamp (the wall-clock age check needs an ingested
                          timestamp, which the current Market model does not carry — so
                          this end_date check is what actually guards staleness in the
                          live scan path today).
    """

    def __init__(
        self,
        max_age_seconds: float = 600,
        max_binary_spread: float = 0.06,
        multi_sum_tol: float = 0.05,
        price_eps: float = 1e-9,
        max_past_end_seconds: float = 3600,
    ) -> None:
        self.max_age_seconds = max_age_seconds
        self.max_binary_spread = max_binary_spread
        self.multi_sum_tol = multi_sum_tol
        self.price_eps = price_eps
        self.max_past_end_seconds = max_past_end_seconds

    # ----------------------------------------------------------
    # Individual dimension checks
    # ----------------------------------------------------------

    def check_completeness(self, market) -> List[QualityIssue]:
        """
        Verify that all required fields are present and well-typed.

        Rules:
        - ``condition_id`` must be a non-empty string.
        - ``question`` must be a non-empty string.
        - At least 2 outcomes must be present.
        - Each outcome must have a non-empty ``token_id``.
        - Each outcome ``price`` must be non-None and in [0, 1].
        - ``total_volume`` and ``liquidity`` must be numeric and >= 0.
        """
        issues: List[QualityIssue] = []

        # Market-level fields
        if not market.condition_id or not str(market.condition_id).strip():
            issues.append(
                QualityIssue("completeness", "condition_id is missing or empty")
            )

        if not market.question or not str(market.question).strip():
            issues.append(
                QualityIssue("completeness", "question is missing or empty")
            )

        outcomes = getattr(market, "outcomes", None) or []
        if len(outcomes) < 2:
            issues.append(
                QualityIssue(
                    "completeness",
                    f"market has {len(outcomes)} outcome(s); at least 2 required",
                )
            )

        # Per-outcome fields
        for idx, outcome in enumerate(outcomes):
            label = getattr(outcome, "label", None) or f"outcome[{idx}]"

            if not getattr(outcome, "token_id", None) or not str(outcome.token_id).strip():
                issues.append(
                    QualityIssue(
                        "completeness",
                        f"{label}: token_id is missing or empty",
                    )
                )

            price = getattr(outcome, "price", None)
            if price is None:
                issues.append(
                    QualityIssue("completeness", f"{label}: price is None")
                )
            elif not isinstance(price, (int, float)):
                issues.append(
                    QualityIssue(
                        "completeness",
                        f"{label}: price has non-numeric type {type(price).__name__}",
                    )
                )
            elif not (0.0 <= float(price) <= 1.0):
                issues.append(
                    QualityIssue(
                        "completeness",
                        f"{label}: price {price} is outside [0, 1]",
                    )
                )

        # Numeric scalar fields
        for field_name in ("total_volume", "liquidity"):
            val = getattr(market, field_name, None)
            if val is None or not isinstance(val, (int, float)):
                issues.append(
                    QualityIssue(
                        "completeness",
                        f"{field_name} is missing or non-numeric",
                    )
                )
            elif float(val) < 0:
                issues.append(
                    QualityIssue(
                        "completeness",
                        f"{field_name} is negative ({val})",
                    )
                )

        return issues

    def check_price_sanity(self, market) -> List[QualityIssue]:
        """
        Verify that prices are self-consistent.

        Rules:
        - Every outcome price must be in [-price_eps, 1 + price_eps]; values
          strictly outside [0, 1] (beyond tolerance) are a hard issue.
        - For binary markets (2 outcomes): |spread| <= max_binary_spread,
          where spread = |1 - sum(prices)| (via market.spread property).
        - For multi-outcome markets (>2 outcomes): |sum(prices) - 1| <= multi_sum_tol.
        """
        issues: List[QualityIssue] = []
        outcomes = getattr(market, "outcomes", None) or []

        for outcome in outcomes:
            price = getattr(outcome, "price", None)
            if price is None or not isinstance(price, (int, float)):
                # Already flagged by completeness; skip to avoid duplicate noise.
                continue
            p = float(price)
            if p < (0.0 - self.price_eps) or p > (1.0 + self.price_eps):
                issues.append(
                    QualityIssue(
                        "price_sanity",
                        f"{getattr(outcome, 'label', 'outcome')}: price {p} is outside [0, 1]",
                    )
                )

        # Sum check — only when all prices are individually valid
        valid_prices = [
            float(o.price)
            for o in outcomes
            if getattr(o, "price", None) is not None
            and isinstance(o.price, (int, float))
            and (0.0 - self.price_eps) <= float(o.price) <= (1.0 + self.price_eps)
        ]

        if len(valid_prices) == len(outcomes) and outcomes:
            if getattr(market, "is_binary", False):
                # Use the market's own spread property (already computed)
                spread = getattr(market, "spread", None)
                if spread is None:
                    spread = abs(1.0 - sum(valid_prices))
                if spread > self.max_binary_spread:
                    issues.append(
                        QualityIssue(
                            "price_sanity",
                            f"binary market spread {spread:.4f} exceeds "
                            f"max_binary_spread {self.max_binary_spread}",
                        )
                    )
            elif getattr(market, "is_multi", False):
                total = sum(valid_prices)
                deviation = abs(total - 1.0)
                if deviation > self.multi_sum_tol:
                    issues.append(
                        QualityIssue(
                            "price_sanity",
                            f"multi-outcome prices sum to {total:.4f}; "
                            f"deviation {deviation:.4f} exceeds multi_sum_tol {self.multi_sum_tol}",
                        )
                    )

        return issues

    def check_staleness(
        self,
        market,
        now: Optional[datetime] = None,
        fetched_at: Optional[datetime] = None,
    ) -> List[QualityIssue]:
        """
        Check that the price snapshot is recent enough.

        Two complementary staleness signals:
          1. **end_date expiry (fires in production):** a market whose ``end_date`` is
             more than ``max_past_end_seconds`` in the past is stale/closed data and
             should not be traded as a live opportunity. This needs only the ``end_date``
             the Market already carries, so it is the staleness guard that actually runs
             in the live scan path today.
          2. **fetch-age (fires when a timestamp is available):** if ``fetched_at`` is
             provided (or the market carries a ``fetched_at``/``updated_at`` attribute),
             the snapshot age ``now - fetched_at`` must be <= ``max_age_seconds``. The
             current Market model does not ingest a fetch timestamp, so this branch is
             exercised mainly by callers/tests that supply one — documented honestly
             rather than presented as always-on.

        Args:
            market:     The market to check.
            now:        Override for "current time" (UTC). Defaults to
                        ``datetime.now(timezone.utc)``.
            fetched_at: When the market data was retrieved.
        """
        # Resolve "now"
        if now is None:
            now = datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        issues: List[QualityIssue] = []

        # (1) end_date expiry — uses data the Market already carries, so it fires in the
        # live scan path even with no fetch timestamp.
        end_date = getattr(market, "end_date", None)
        if isinstance(end_date, datetime):
            end_cmp = end_date if end_date.tzinfo else end_date.replace(tzinfo=timezone.utc)
            past_end = (now - end_cmp).total_seconds()
            if past_end > self.max_past_end_seconds:
                issues.append(
                    QualityIssue(
                        "staleness",
                        f"market end_date passed {past_end:.0f}s ago "
                        f"(grace {self.max_past_end_seconds}s) — data stale/should be resolved",
                    )
                )

        # (2) fetch-age — only when a timestamp is available.
        # Resolve timestamp: caller-supplied > market attribute > nothing
        ts: Optional[datetime] = fetched_at
        if ts is None:
            for attr in ("fetched_at", "updated_at"):
                candidate = getattr(market, attr, None)
                if isinstance(candidate, datetime):
                    ts = candidate
                    break

        if ts is None:
            # No fetch timestamp to assess wall-clock age — return whatever the
            # end_date expiry check found (possibly empty); do not otherwise penalise.
            return issues

        # Ensure timezone-aware comparison
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        age_seconds = (now - ts).total_seconds()
        if age_seconds > self.max_age_seconds:
            issues.append(
                QualityIssue(
                    "staleness",
                    f"data is {age_seconds:.0f}s old; max_age_seconds={self.max_age_seconds}",
                )
            )

        return issues

    # ----------------------------------------------------------
    # Aggregate check
    # ----------------------------------------------------------

    def check_market(
        self,
        market,
        now: Optional[datetime] = None,
        fetched_at: Optional[datetime] = None,
    ) -> QualityCheckResult:
        """
        Run all three dimension checks and return a combined result.

        A market is ``ok`` only when **no** issues are found across all dimensions.
        """
        issues: List[QualityIssue] = []
        issues.extend(self.check_completeness(market))
        issues.extend(self.check_price_sanity(market))
        issues.extend(self.check_staleness(market, now=now, fetched_at=fetched_at))
        return QualityCheckResult(ok=len(issues) == 0, issues=issues)
