"""Market category coherence — the fix for the confirmed live forward-loop FREEZE.

CONTEXT (2026-07-02, from the live OA-17 forward-paper cycle logs): real Polymarket Gamma
markets ship an EMPTY top-level ``category`` field, so the risk manager bucketed every
market as ``"General"`` and the per-category cap ($200) became a de-facto GLOBAL cap below
the real portfolio cap ($500). The live cycle froze — 154/154 opportunities skipped with
"Category 'General' exposure: $164.18 + $50.00 > $200.0".

These tests prove the end-to-end fix:
  (1) `derive_market_category` maps a market into a real coarse correlation bucket from the
      tags/question (deterministic, honest "General" only when genuinely unclassifiable);
  (2) the Polymarket parser now stamps that derived category (not the empty raw field);
  (3) a REHYDRATED position carries its persisted category so it counts against its REAL
      bucket across the fresh-process paper cycle (not "General");
  (4) `_get_category_exposure` therefore spreads exposure across buckets — a Crypto
      position does NOT count toward the Sports cap, so the freeze lifts.

Import via ``app.*`` (conftest puts backend/ on sys.path) — the suite-wide convention.
"""

from __future__ import annotations

import types

import pytest
from sqlmodel import Session, create_engine

from app.prediction_markets import models as m
from app.prediction_markets import persistence
from app.prediction_markets.execution import Exchange, Position, PredictionMarketExecutor
from app.prediction_markets.market_category import (
    CATEGORY_CRYPTO,
    CATEGORY_ECONOMICS,
    CATEGORY_ENTERTAINMENT,
    CATEGORY_GENERAL,
    CATEGORY_POLITICS,
    CATEGORY_SPORTS,
    CATEGORY_WEATHER,
    derive_market_category,
)
from app.prediction_markets.polymarket_client import PolymarketClient
from app.prediction_markets.risk_manager import RiskManager


# ---------------------------------------------------------------------------
# (1) the pure classifier
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "question,expected",
    [
        ("Will the price of Bitcoin be above $62,000 on July 2?", CATEGORY_CRYPTO),
        ("Will ETH flip BTC in 2026?", CATEGORY_CRYPTO),
        ("Will Belgium win the 2026 FIFA World Cup?", CATEGORY_SPORTS),
        ("Wimbledon ATP: Zizou Bergs vs Jaime Faria", CATEGORY_SPORTS),
        ("Will Spain vs. Austria end in a draw?", CATEGORY_SPORTS),
        ("Will the Fed increase interest rates by 25 bps after the July meeting?", CATEGORY_ECONOMICS),
        ("Will US CPI inflation come in above 3% in July?", CATEGORY_ECONOMICS),
        ("Will Renan Santos win the 2026 Brazilian presidential election?", CATEGORY_POLITICS),
        ("Will the Senate confirm the nominee before August?", CATEGORY_POLITICS),
        ("Will a hurricane make landfall in Florida in July?", CATEGORY_WEATHER),
        ("Will the next Marvel movie top the box office opening weekend?", CATEGORY_ENTERTAINMENT),
        ("Will aliens be officially confirmed by the government?", CATEGORY_POLITICS),  # 'government'
        ("Some entirely unclassifiable prompt about widgets", CATEGORY_GENERAL),
        ("", CATEGORY_GENERAL),
    ],
)
def test_classifier_question_only(question, expected):
    assert derive_market_category(question) == expected


def test_politics_beats_sports_on_election_win():
    # "win ... election" contains the Sports verb "win the" but must resolve to Politics
    # because Politics is checked first (order matters — the ambiguous Sports verbs are last).
    assert (
        derive_market_category("Who will win the presidential election?")
        == CATEGORY_POLITICS
    )


def test_explicit_raw_category_is_honored_when_known():
    # If the venue ever DOES populate a recognizable category, trust it over the heuristic.
    assert derive_market_category("some sports question", raw_category="Crypto") == CATEGORY_CRYPTO


def test_tags_used_when_category_empty():
    assert (
        derive_market_category("ambiguous text", raw_category="", tags=["Politics", "2026"])
        == CATEGORY_POLITICS
    )


def test_unknown_raw_category_falls_through_not_trusted_blindly():
    # An unknown free-text category is NOT trusted verbatim (it would create an unlimited
    # private bucket); we fall through to the keyword heuristic on the question.
    result = derive_market_category(
        "Will Bitcoin close above $70k?", raw_category="zzz-unknown-freeform"
    )
    assert result == CATEGORY_CRYPTO


def test_token_boundary_no_false_crypto_match():
    # "eth" as a token must not match inside "whether"/"together"; this stays General.
    assert derive_market_category("Whether they finish together by Friday") == CATEGORY_GENERAL


def test_deterministic_same_input_same_output():
    q = "Will France win the 2026 FIFA World Cup?"
    assert derive_market_category(q) == derive_market_category(q) == CATEGORY_SPORTS


# ---------------------------------------------------------------------------
# (2) the parser stamps the derived category (not the empty raw field)
# ---------------------------------------------------------------------------

def test_parser_derives_category_when_raw_empty():
    client = PolymarketClient()
    raw = {
        "id": "12345",
        "conditionId": "0xabc",
        "question": "Will Belgium win the 2026 FIFA World Cup?",
        "category": "",  # real Polymarket data: empty
        "outcomes": '["Yes", "No"]',
        "outcomePrices": '["0.30", "0.70"]',
        "clobTokenIds": '["tokA", "tokB"]',
        "active": True,
        "volume": "5000",
    }
    market = client._parse_market(raw)
    assert market is not None
    assert market.category == CATEGORY_SPORTS
    assert market.category != CATEGORY_GENERAL


def test_parser_two_markets_land_in_different_buckets():
    client = PolymarketClient()
    base = {
        "conditionId": "0xabc",
        "outcomes": '["Yes", "No"]',
        "outcomePrices": '["0.30", "0.70"]',
        "clobTokenIds": '["tokA", "tokB"]',
        "active": True,
        "volume": "5000",
    }
    sports = client._parse_market({**base, "id": "1", "question": "Will Brazil win the World Cup?", "category": ""})
    crypto = client._parse_market({**base, "id": "2", "question": "Will Bitcoin be above $70k?", "category": ""})
    assert sports.category != crypto.category  # the whole point: they DON'T share one bucket


# ---------------------------------------------------------------------------
# (3) + (4) rehydration coherence + exposure spread — the freeze fix
# ---------------------------------------------------------------------------

@pytest.fixture
def db(monkeypatch):
    from app.db import database

    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    for tbl in (m.PredictionPortfolio, m.PredictionPosition, m.PredictionOrder):
        tbl.__table__.create(eng, checkfirst=True)
    with Session(eng) as s:
        s.add(m.PredictionPortfolio(id=persistence.DEFAULT_PORTFOLIO_ID, name="default", exchange="all"))
        s.commit()
    monkeypatch.setattr(database, "engine", eng)
    return eng


def _insert_position(eng, token_id, market_id, category, avg=0.4, size=10.0):
    with Session(eng) as s:
        s.add(
            m.PredictionPosition(
                portfolio_id=persistence.DEFAULT_PORTFOLIO_ID,
                exchange="polymarket",
                market_id=market_id,
                token_id=token_id,
                category=category,
                side="long",
                size=size,
                avg_entry_price=avg,
                current_price=avg,
                market_value=size * avg,
                is_resolved=False,
                strategy="test_strat",
            )
        )
        s.commit()


def test_rehydrated_position_carries_its_category(db):
    _insert_position(db, "TOK_C", "mktCrypto", category=CATEGORY_CRYPTO)
    ex = PredictionMarketExecutor(dry_run=True)
    persistence.load_positions_into_executor(ex)
    assert ex.positions["TOK_C"].category == CATEGORY_CRYPTO


def _pos(market_id, category, value):
    # Build a Position whose market_value == `value` (value = size * current_price).
    return Position(
        exchange=Exchange.POLYMARKET,
        market_id=market_id,
        token_id="tok_" + market_id,
        market_question="q",
        outcome_label="Yes",
        side="long",
        size=value,
        avg_entry_price=1.0,
        current_price=1.0,
        unrealized_pnl=0.0,
        realized_pnl=0.0,
        category=category,
    )


def test_exposure_counts_rehydrated_position_in_its_real_bucket():
    # A rehydrated Sports position (empty per-market map, as on a fresh process) must count
    # toward "Sports", NOT "General" — the pre-fix bug bucketed it as "General".
    rm = RiskManager()
    ex = types.SimpleNamespace(positions={"a": _pos("mktS", CATEGORY_SPORTS, 164.0)})
    assert rm._get_category_exposure(CATEGORY_SPORTS, ex) == pytest.approx(164.0)
    # And it is NOT double-counted into General.
    assert rm._get_category_exposure(CATEGORY_GENERAL, ex) == pytest.approx(0.0)


def test_exposure_spreads_across_buckets_so_freeze_lifts():
    # THE freeze fix: with a big Sports position and a big Crypto position, neither bucket
    # sees the other's exposure — so a new Crypto (or Sports) opportunity is measured against
    # only its own bucket, not the combined total (which is what froze the loop at $200).
    rm = RiskManager()
    ex = types.SimpleNamespace(
        positions={
            "s": _pos("mktS", CATEGORY_SPORTS, 164.0),
            "c": _pos("mktC", CATEGORY_CRYPTO, 150.0),
        }
    )
    assert rm._get_category_exposure(CATEGORY_SPORTS, ex) == pytest.approx(164.0)
    assert rm._get_category_exposure(CATEGORY_CRYPTO, ex) == pytest.approx(150.0)
    # Pre-fix (everything "General"): General would have been 164 + 150 = 314 > 200 → frozen.
    # Post-fix each bucket is under the $200 cap, so new trades in either can still execute.
    assert rm._get_category_exposure(CATEGORY_GENERAL, ex) == pytest.approx(0.0)
