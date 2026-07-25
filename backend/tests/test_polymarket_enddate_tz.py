"""`endDate` must always parse to a timezone-AWARE datetime.

The scan path filters stale markets with `m.end_date < datetime.now(timezone.utc)`. A
timezone-NAIVE `end_date` makes that comparison raise `TypeError: can't compare
offset-naive and offset-aware datetimes`, and the orchestrator's scan loop catches
Exception broadly — so the failure mode is not a crash but a PERMANENT SILENT SCAN
BLACKOUT: one log line per cycle and zero opportunities, forever.

Every sibling parser in this codebase already carries the tz guard
(`polymarket_history_fetcher._parse_dt`, `kalshi_history_fetcher._parse_dt`,
`kalshi_client._parse_dt`, `polymarket_v1_hf_fetcher`); `PolymarketClient._parse_market`
was the one that did not. Reported by the independent Quality Auditor (2026-07-24) as a
`correctness_reliability` latent swallowed-crash.

These tests fail LOUD on the pre-fix parser. All offline, no network.
"""

from datetime import datetime, timezone

import pytest

from app.prediction_markets.polymarket_client import PolymarketClient

UTC = timezone.utc


def _raw(end_date_value):
    """A minimal but VALID Gamma payload — valid enough that the parser produces a
    tradeable market, so a tz assertion below is really exercising the parse."""
    return {
        "id": "m-tz",
        "conditionId": "c-tz",
        "question": "Will the endDate parse tz-aware?",
        "slug": "will-the-enddate-parse-tz-aware",
        "description": "",
        "category": "",
        "outcomes": '["Yes", "No"]',
        "outcomePrices": '["0.60", "0.40"]',
        "clobTokenIds": '["tok_yes", "tok_no"]',
        "endDate": end_date_value,
        "volume": "5000",
        "liquidity": "1000",
        "active": True,
        "closed": False,
    }


@pytest.mark.parametrize(
    "end_date_value,expected_naive_utc",
    [
        # The NAIVE forms — these are what the pre-fix parser mishandled.
        ("2026-06-01T00:00:00", datetime(2026, 6, 1)),
        ("2026-06-01 00:00:00", datetime(2026, 6, 1)),
        ("2026-06-01", datetime(2026, 6, 1)),
        # ... and the already-aware forms, which must pass through UNCHANGED.
        ("2026-06-01T00:00:00Z", datetime(2026, 6, 1)),
        ("2026-06-01T00:00:00+00:00", datetime(2026, 6, 1)),
    ],
)
def test_end_date_is_always_timezone_aware(end_date_value, expected_naive_utc):
    market = PolymarketClient()._parse_market(_raw(end_date_value))
    assert market is not None, "fixture must parse, or the tz assertion proves nothing"
    assert market.end_date is not None
    assert market.end_date.tzinfo is not None, (
        f"endDate {end_date_value!r} parsed TIMEZONE-NAIVE — the stale-market filter will "
        f"raise TypeError and the scan loop will swallow it into a silent blackout"
    )
    assert market.end_date.utcoffset().total_seconds() == 0, "must be normalized to UTC"
    assert market.end_date.replace(tzinfo=None) == expected_naive_utc, (
        "normalization must STAMP the timezone, never shift the wall-clock value"
    )


def test_naive_end_date_survives_the_comparison_that_used_to_raise():
    """The exact expression on the scan path. Pre-fix this raised TypeError."""
    market = PolymarketClient()._parse_market(_raw("2026-06-01T00:00:00"))
    now = datetime.now(UTC)
    assert (market.end_date < now) in (True, False)  # the point is that it does not raise


def test_unparseable_end_date_still_degrades_to_none_not_a_fabricated_date():
    """The guard must not turn an unparseable value into an invented timestamp."""
    market = PolymarketClient()._parse_market(_raw("not-a-date"))
    assert market is not None
    assert market.end_date is None


def test_absent_end_date_stays_none():
    raw = _raw("2026-06-01T00:00:00Z")
    del raw["endDate"]
    market = PolymarketClient()._parse_market(raw)
    assert market is not None
    assert market.end_date is None
