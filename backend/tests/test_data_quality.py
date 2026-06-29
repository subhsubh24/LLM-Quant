"""
Tests for ROADMAP A5: Data-Quality Gates.

All tests are deterministic and network-free — they construct Market/Outcome
fixtures in-process and run the validator directly.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.app.prediction_markets.data_quality import (
    DataQualityValidator,
    QualityCheckResult,
    QualityIssue,
)
from backend.app.prediction_markets.polymarket_client import Market, Outcome


# ============================================================
# Helpers / fixtures
# ============================================================


def _make_outcome(
    token_id: str = "tok_yes",
    label: str = "Yes",
    price: float = 0.55,
    midpoint: float = 0.55,
    volume: float = 50_000,
) -> Outcome:
    return Outcome(
        token_id=token_id,
        label=label,
        price=price,
        midpoint=midpoint,
        volume=volume,
    )


def _make_binary_market(
    condition_id: str = "cond_abc",
    question: str = "Will it rain tomorrow?",
    yes_price: float = 0.55,
    total_volume: float = 100_000,
    liquidity: float = 40_000,
    yes_token: str = "tok_yes",
    no_token: str = "tok_no",
) -> Market:
    no_price = round(1.0 - yes_price, 6)
    return Market(
        id="m_test",
        condition_id=condition_id,
        question=question,
        slug="will-it-rain",
        description="",
        category="Weather",
        end_date=datetime.now(timezone.utc) + timedelta(days=1),
        outcomes=[
            _make_outcome(token_id=yes_token, label="Yes", price=yes_price),
            _make_outcome(token_id=no_token, label="No", price=no_price),
        ],
        total_volume=total_volume,
        liquidity=liquidity,
        active=True,
        closed=False,
        resolved=False,
    )


def _make_multi_market(prices: list[float]) -> Market:
    outcomes = [
        _make_outcome(token_id=f"tok_{i}", label=f"Option {i}", price=p)
        for i, p in enumerate(prices)
    ]
    return Market(
        id="m_multi",
        condition_id="cond_multi",
        question="Which city will host the 2030 World Cup?",
        slug="world-cup-2030",
        description="",
        category="Sports",
        end_date=datetime.now(timezone.utc) + timedelta(days=200),
        outcomes=outcomes,
        total_volume=500_000,
        liquidity=100_000,
        active=True,
        closed=False,
        resolved=False,
    )


# ============================================================
# Basic structural tests
# ============================================================


class TestQualityIssueAndResult:
    def test_issue_fields_accessible(self):
        issue = QualityIssue(dimension="completeness", detail="price is None")
        assert issue.dimension == "completeness"
        assert "price" in issue.detail

    def test_result_ok_reason(self):
        result = QualityCheckResult(ok=True, issues=[])
        assert result.ok
        assert result.reason == "ok"

    def test_result_fail_reason_contains_all_issues(self):
        issues = [
            QualityIssue("completeness", "token_id missing"),
            QualityIssue("price_sanity", "price > 1"),
        ]
        result = QualityCheckResult(ok=False, issues=issues)
        assert not result.ok
        assert "completeness" in result.reason
        assert "price_sanity" in result.reason
        assert "token_id missing" in result.reason


# ============================================================
# Completeness checks
# ============================================================


class TestCompleteness:
    def setup_method(self):
        self.v = DataQualityValidator()

    def test_valid_binary_market_no_issues(self):
        market = _make_binary_market()
        issues = self.v.check_completeness(market)
        assert issues == [], f"Unexpected issues: {issues}"

    def test_missing_token_id_flagged(self):
        market = _make_binary_market(yes_token="")
        issues = self.v.check_completeness(market)
        dims = [i.dimension for i in issues]
        assert "completeness" in dims

    def test_none_price_flagged(self):
        market = _make_binary_market()
        # Mutate price to None via direct object manipulation
        market.outcomes[0] = Outcome(
            token_id="tok_yes", label="Yes", price=None, midpoint=0.55, volume=50_000
        )
        issues = self.v.check_completeness(market)
        dims = [i.dimension for i in issues]
        assert "completeness" in dims

    def test_price_above_one_flagged(self):
        market = _make_binary_market()
        market.outcomes[0] = Outcome(
            token_id="tok_yes", label="Yes", price=1.5, midpoint=1.5, volume=50_000
        )
        issues = self.v.check_completeness(market)
        dims = [i.dimension for i in issues]
        assert "completeness" in dims

    def test_negative_volume_flagged(self):
        market = _make_binary_market(total_volume=-1)
        issues = self.v.check_completeness(market)
        dims = [i.dimension for i in issues]
        assert "completeness" in dims

    def test_empty_condition_id_flagged(self):
        market = _make_binary_market(condition_id="")
        issues = self.v.check_completeness(market)
        dims = [i.dimension for i in issues]
        assert "completeness" in dims

    def test_empty_question_flagged(self):
        market = _make_binary_market(question="")
        issues = self.v.check_completeness(market)
        dims = [i.dimension for i in issues]
        assert "completeness" in dims

    def test_negative_liquidity_flagged(self):
        market = _make_binary_market(liquidity=-500)
        issues = self.v.check_completeness(market)
        dims = [i.dimension for i in issues]
        assert "completeness" in dims


# ============================================================
# Price-sanity checks
# ============================================================


class TestPriceSanity:
    def setup_method(self):
        self.v = DataQualityValidator(max_binary_spread=0.06, multi_sum_tol=0.05)

    def test_valid_binary_market_passes(self):
        # yes=0.55, no=0.45 → sum=1.00, spread=0
        market = _make_binary_market(yes_price=0.55)
        issues = self.v.check_price_sanity(market)
        assert issues == [], f"Unexpected issues: {issues}"

    def test_binary_sum_1_2_fails(self):
        """YES=0.7, NO=0.5 → sum=1.2, spread=0.2 > max_binary_spread"""
        market = _make_binary_market(yes_price=0.70)
        # Override no-price to 0.50 so sum = 1.20
        market.outcomes[1] = Outcome(
            token_id="tok_no", label="No", price=0.50, midpoint=0.50, volume=50_000
        )
        issues = self.v.check_price_sanity(market)
        dims = [i.dimension for i in issues]
        assert "price_sanity" in dims, f"Expected price_sanity issue; got: {issues}"

    def test_multi_sum_1_0_passes(self):
        # 3-way market summing exactly to 1.0
        market = _make_multi_market([0.50, 0.30, 0.20])
        issues = self.v.check_price_sanity(market)
        assert issues == [], f"Unexpected issues: {issues}"

    def test_multi_sum_1_3_fails(self):
        # 3-way market summing to 1.30 → deviation 0.30 > multi_sum_tol=0.05
        market = _make_multi_market([0.50, 0.50, 0.30])
        issues = self.v.check_price_sanity(market)
        dims = [i.dimension for i in issues]
        assert "price_sanity" in dims, f"Expected price_sanity issue; got: {issues}"

    def test_price_above_one_individual_flagged(self):
        market = _make_binary_market(yes_price=0.55)
        market.outcomes[0] = Outcome(
            token_id="tok_yes", label="Yes", price=1.2, midpoint=1.2, volume=50_000
        )
        issues = self.v.check_price_sanity(market)
        dims = [i.dimension for i in issues]
        assert "price_sanity" in dims

    def test_price_below_zero_individual_flagged(self):
        market = _make_binary_market(yes_price=0.55)
        market.outcomes[0] = Outcome(
            token_id="tok_yes", label="Yes", price=-0.01, midpoint=-0.01, volume=50_000
        )
        issues = self.v.check_price_sanity(market)
        dims = [i.dimension for i in issues]
        assert "price_sanity" in dims


# ============================================================
# Staleness checks
# ============================================================


class TestStaleness:
    def setup_method(self):
        self.v = DataQualityValidator(max_age_seconds=600)
        self.now = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

    def test_700s_old_fails(self):
        fetched_at = self.now - timedelta(seconds=700)
        issues = self.v.check_staleness(
            market=_make_binary_market(), now=self.now, fetched_at=fetched_at
        )
        dims = [i.dimension for i in issues]
        assert "staleness" in dims, f"Expected staleness issue; got: {issues}"

    def test_500s_old_passes(self):
        fetched_at = self.now - timedelta(seconds=500)
        issues = self.v.check_staleness(
            market=_make_binary_market(), now=self.now, fetched_at=fetched_at
        )
        assert issues == [], f"Unexpected staleness issues: {issues}"

    def test_no_timestamp_not_flagged(self):
        """When no fetched_at is provided and the market has no timestamp attribute,
        the check should return [] (cannot assess — do not penalise)."""
        market = _make_binary_market()
        issues = self.v.check_staleness(market=market, now=self.now, fetched_at=None)
        assert issues == [], f"Unexpected issues with no timestamp: {issues}"

    def test_exactly_max_age_passes(self):
        fetched_at = self.now - timedelta(seconds=600)
        issues = self.v.check_staleness(
            market=_make_binary_market(), now=self.now, fetched_at=fetched_at
        )
        assert issues == [], f"Exactly at boundary should pass: {issues}"

    def test_market_attribute_timestamp_used(self):
        """If market has a fetched_at attribute, it should be used."""
        market = _make_binary_market()
        # Market is a non-frozen dataclass — set a stale fetch timestamp directly.
        market.fetched_at = self.now - timedelta(seconds=800)
        issues = self.v.check_staleness(market=market, now=self.now, fetched_at=None)
        dims = [i.dimension for i in issues]
        assert "staleness" in dims

    def test_expired_end_date_flagged_without_timestamp(self):
        """A market whose end_date passed (beyond the grace period) is stale data even
        with NO fetch timestamp — this is the staleness guard that actually fires in the
        live scan path, where Market carries an end_date but no fetch time."""
        market = _make_binary_market()
        market.end_date = self.now - timedelta(hours=5)   # 5h past, grace 1h
        issues = self.v.check_staleness(market=market, now=self.now, fetched_at=None)
        assert "staleness" in [i.dimension for i in issues]

    def test_future_end_date_not_flagged(self):
        market = _make_binary_market()
        market.end_date = self.now + timedelta(hours=2)
        issues = self.v.check_staleness(market=market, now=self.now, fetched_at=None)
        assert issues == []

    def test_end_date_within_grace_not_flagged(self):
        market = _make_binary_market()
        market.end_date = self.now - timedelta(seconds=1800)  # 30min past, grace 1h
        issues = self.v.check_staleness(market=market, now=self.now, fetched_at=None)
        assert issues == []


# ============================================================
# check_market integration
# ============================================================


class TestCheckMarket:
    def setup_method(self):
        self.v = DataQualityValidator()

    def test_valid_binary_market_ok(self):
        market = _make_binary_market()
        result = self.v.check_market(market)
        assert result.ok, f"Expected ok=True; reason: {result.reason}"
        assert result.issues == []
        assert result.reason == "ok"

    def test_bad_market_not_ok(self):
        market = _make_binary_market(yes_token="")  # missing token_id
        result = self.v.check_market(market)
        assert not result.ok
        assert len(result.issues) >= 1

    def test_staleness_propagates_through_check_market(self):
        now = datetime(2025, 6, 1, 10, 0, 0, tzinfo=timezone.utc)
        fetched_at = now - timedelta(seconds=700)
        market = _make_binary_market()
        result = self.v.check_market(market, now=now, fetched_at=fetched_at)
        assert not result.ok
        dims = [i.dimension for i in result.issues]
        assert "staleness" in dims

    def test_pure_validator_no_external_deps(self):
        """Validator must work with no network, no DB, no imports beyond stdlib."""
        v = DataQualityValidator(
            max_age_seconds=300,
            max_binary_spread=0.04,
            multi_sum_tol=0.03,
            price_eps=1e-9,
        )
        market = _make_binary_market(yes_price=0.60)  # sum=1.0, spread=0
        result = v.check_market(market)
        assert result.ok

    def test_multiple_issues_combined(self):
        """A market with both missing token and bad price accumulates multiple issues."""
        market = _make_binary_market()
        market.outcomes[0] = Outcome(
            token_id="",  # missing
            label="Yes",
            price=1.5,  # out of range
            midpoint=1.5,
            volume=50_000,
        )
        result = self.v.check_market(market)
        assert not result.ok
        dims = {i.dimension for i in result.issues}
        # completeness (missing token_id, price out of range) and price_sanity (price > 1)
        assert "completeness" in dims


# ============================================================
# ROADMAP A5: wall-clock fetch-age staleness now fires on ingested data
# ============================================================

class TestFetchAgeStaleness:
    """The fetch-age branch must fire on a Market that carries a stale ``fetched_at``.

    Before A5 the Market had no ingest timestamp, so this branch could never fire on
    live data (a misleading no-op). Now ``_parse_market`` stamps ``fetched_at`` and the
    validator reads it off the market with no caller argument.
    """

    def _validator(self) -> DataQualityValidator:
        return DataQualityValidator(max_age_seconds=600, max_past_end_seconds=3600)

    def test_fresh_fetched_at_no_staleness(self):
        now = datetime.now(timezone.utc)
        m = _make_binary_market()
        m.fetched_at = now  # just ingested
        issues = self._validator().check_staleness(m, now=now)
        assert issues == [], f"a fresh snapshot must not be stale: {issues}"

    def test_stale_fetched_at_fires_via_market_attribute(self):
        now = datetime.now(timezone.utc)
        m = _make_binary_market()
        # end_date still in the future (helper sets +1 day) so ONLY the fetch-age path
        # can fire — isolating the A5 behavior.
        m.fetched_at = now - timedelta(seconds=1800)  # 30 min old, max_age 600s
        issues = self._validator().check_staleness(m, now=now)
        assert any(i.dimension == "staleness" for i in issues), (
            "a 30-min-old snapshot with max_age=600s must be flagged stale"
        )

    def test_caller_fetched_at_overrides_market_attribute(self):
        now = datetime.now(timezone.utc)
        m = _make_binary_market()
        m.fetched_at = now  # market says fresh...
        # ...but the caller supplies an explicitly old timestamp → must fire.
        issues = self._validator().check_staleness(
            m, now=now, fetched_at=now - timedelta(seconds=3600)
        )
        assert any(i.dimension == "staleness" for i in issues)

    def test_check_market_aggregate_includes_fetch_age(self):
        now = datetime.now(timezone.utc)
        m = _make_binary_market()
        m.fetched_at = now - timedelta(seconds=2000)
        result = self._validator().check_market(m, now=now)
        assert not result.ok
        assert "stale" in result.reason.lower() or "old" in result.reason.lower()

    def test_parsed_market_carries_fetched_at(self):
        from backend.app.prediction_markets.polymarket_client import PolymarketClient

        client = PolymarketClient()
        raw = {
            "id": "1",
            "conditionId": "c1",
            "question": "Will X happen?",
            "outcomes": '["Yes","No"]',
            "outcomePrices": '["0.4","0.6"]',
            "clobTokenIds": '["t1","t2"]',
            "active": True,
            "closed": False,
        }
        m = client._parse_market(raw)
        assert isinstance(m.fetched_at, datetime), "parse must stamp fetched_at"

    def test_parsed_market_with_injected_old_timestamp_is_stale(self):
        from backend.app.prediction_markets.polymarket_client import PolymarketClient

        now = datetime.now(timezone.utc)
        client = PolymarketClient()
        raw = {
            "id": "1", "conditionId": "c1", "question": "Will X happen?",
            "outcomes": '["Yes","No"]', "outcomePrices": '["0.4","0.6"]',
            "clobTokenIds": '["t1","t2"]', "active": True, "closed": False,
            "endDate": (now + timedelta(days=5)).isoformat(),  # future → only fetch-age
        }
        m = client._parse_market(raw, fetched_at=now - timedelta(seconds=5000))
        issues = DataQualityValidator(max_age_seconds=600).check_staleness(m, now=now)
        assert any(i.dimension == "staleness" for i in issues)
