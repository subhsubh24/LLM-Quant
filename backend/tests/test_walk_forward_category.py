"""End-to-end category threading (ROADMAP F10 — anti-overfitting integrity).

The resolved-history fetchers now derive a coarse correlation CATEGORY
(``market_category.derive_market_category``) and thread it onto each
``HistoricalMarket``; the walk-forward carries it onto every ``BacktestTrade``; and
``validate_real_oos`` builds a ``category_by_market_id`` map so the F10
``analyze_regime_slices`` report can assess CATEGORY concentration on real OOS trades
(an aggregate edge concentrated in one category is NOT robust). Previously the category
was dropped, so the F10 category dimension was never assessed on real corpora.

The load-bearing safety property tested here (CORRECTED 2026-07-26, ROADMAP C6): ``category``
is leakage-neutral — it never enters a DECISION — but it is **NOT** PnL-neutral. Both
per-category caps size trades down by category, and a per-category ``fee_schedule`` prices
fills by category. So ``category`` is fingerprinted by ``_seed_hash`` UNCONDITIONALLY, and two
datasets that differ ONLY in their category labels MUST hash differently.

This file previously asserted the OPPOSITE ("category is METADATA … EXCLUDED from
``_seed_hash``") and pinned that invariant with a test that only ever exercised the cap-free
case. The invariant was false: on the shipped frozen corpus the published headline hash
``79a4cca4b966138f`` provably covered four distinct (trades, PnL) pairs. A test that documents
and pins a false safety property is worse than a missing test, so it is inverted here and
backed by a cap-ACTIVE collision-closure test that fails loud on the pre-fix engine.
All offline + deterministic.
"""

from datetime import datetime, timedelta, timezone

from app.prediction_markets import walk_forward as wf
from app.prediction_markets.market_category import (
    CATEGORY_CRYPTO,
    CATEGORY_GENERAL,
    CATEGORY_POLITICS,
    CATEGORY_SPORTS,
)
from app.prediction_markets.polymarket_history_fetcher import PolymarketHistoryFetcher
from app.prediction_markets.polymarket_v1_hf_fetcher import HFDailyRow, _assemble_one
from app.prediction_markets.regime_slice import analyze_regime_slices

UTC = timezone.utc


def _mkt(mid, price, prob, outcome, day, *, category=None, res_offset_days=10):
    d = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=day)
    return wf.HistoricalMarket(
        market_id=mid,
        decision_time=d,
        resolution_time=d + timedelta(days=res_offset_days),
        market_price=price,
        model_prob=prob,
        outcome=outcome,
        category=category,
    )


# --------------------------------------------------------------------------- #
# 1. seed_hash COVERS category — the reproducibility guarantee (ROADMAP C6).   #
# --------------------------------------------------------------------------- #
def test_category_is_fingerprinted_in_seed_hash():
    """The SAME dataset, once unlabeled and once category-labeled, must produce DIFFERENT
    seed_hashes — `category` is a PnL-determining DATA field, so the reproducibility
    fingerprint has to cover it. (Cap-free, these two runs happen to price identically; the
    hash must still distinguish them, because the engine CONFIG under which they are replayed
    is not part of the data and a capped replay would diverge.)"""
    base = [
        _mkt("a", 0.80, 0.95, 1, 0),
        _mkt("b", 0.30, 0.10, 0, 5),
        _mkt("c", 0.55, 0.60, 1, 40),
    ]
    labeled = [
        _mkt("a", 0.80, 0.95, 1, 0, category=CATEGORY_CRYPTO),
        _mkt("b", 0.30, 0.10, 0, 5, category=CATEGORY_POLITICS),
        _mkt("c", 0.55, 0.60, 1, 40, category=CATEGORY_SPORTS),
    ]
    r_unlabeled = wf.walk_forward_backtest(base, seed=42)
    r_labeled = wf.walk_forward_backtest(labeled, seed=42)
    assert r_unlabeled.seed_hash != r_labeled.seed_hash, (
        "labeling the SAME data with categories must move the fingerprint — category is a "
        "PnL-determining input under the per-category caps and the per-category fee schedule"
    )
    # Cap-free the two price identically; the fingerprint difference is about COVERAGE of the
    # input, not about this particular run's PnL.
    assert r_unlabeled.total_pnl_usd == r_labeled.total_pnl_usd
    assert r_unlabeled.n_trades == r_labeled.n_trades


def test_seed_hash_is_deterministic_for_a_fixed_labeling():
    """The flip side of the test above: the fingerprint must still be a pure function of the
    data. The same labeled dataset, hashed twice, must be identical — otherwise 'the hash
    moved' would stop meaning 'the inputs changed'."""
    labeled = [
        _mkt("a", 0.80, 0.95, 1, 0, category=CATEGORY_CRYPTO),
        _mkt("b", 0.30, 0.10, 0, 5, category=CATEGORY_POLITICS),
    ]
    assert (
        wf.walk_forward_backtest(labeled, seed=42).seed_hash
        == wf.walk_forward_backtest(list(reversed(labeled)), seed=42).seed_hash
    ), "the fingerprint must stay input-order-invariant with categories in the payload"


def test_different_category_assignment_under_a_cap_moves_the_hash_and_the_pnl():
    """THE regression the C6 defect needed and did not have.

    Two datasets identical in every other fingerprinted field, differing ONLY in which
    category each market carries, run under an ACTIVE per-category cap. The cap sizes trades
    by category, so the two produce DIFFERENT PnL — and therefore MUST produce different
    hashes. On the pre-C6 engine (category absent from the payload) the two hashes were equal
    while the PnL differed: a fingerprint collision on a published number.

    Asserting BOTH halves is what makes this non-tautological — a hash difference alone would
    also pass if the hash were random, and a PnL difference alone would not test the fix.
    """
    # The decision days matter: `train_min_days=28` means anything decided before day 28 is
    # TRAINING and never trades. These six all decide after the training boundary and resolve
    # 60 days out, so their exposure is CONCURRENT — which is what a concurrent cap acts on.
    # At `max_fraction_per_trade=0.05` a 0.20 per-category cap admits ~4 before it bites, so
    # six in one bucket makes it bind and six spread across three buckets leaves room.
    # A walk-forward needs a TRAINING period before any test window exists (n_windows==0
    # otherwise, and the fixture would silently pin nothing). These three are identical in
    # both books, so the ONLY difference between them is the traded markets' labeling.
    def _train():
        return [
            _mkt(f"t{i}", 0.55, 0.60, 1, i, category=CATEGORY_GENERAL, res_offset_days=3)
            for i in range(3)
        ]

    def _book(cats):
        return _train() + [
            _mkt(mid, 0.60, 0.95, 1, day, category=cat, res_offset_days=60)
            for mid, day, cat in cats
        ]

    days = (30, 31, 32, 33, 34, 35)
    ids = ("a", "b", "c", "d", "e", "f")
    # A: all six in ONE category — the cap binds hard on the shared bucket.
    book_a = _book([(i, d, CATEGORY_CRYPTO) for i, d in zip(ids, days)])
    # B: the SAME six markets spread across three categories — each bucket has room.
    spread = (CATEGORY_CRYPTO, CATEGORY_POLITICS, CATEGORY_SPORTS,
              CATEGORY_CRYPTO, CATEGORY_POLITICS, CATEGORY_SPORTS)
    book_b = _book([(i, d, c) for i, d, c in zip(ids, days, spread)])

    r_a = wf.walk_forward_backtest(book_a, seed=42, category_exposure_cap=0.20)
    r_b = wf.walk_forward_backtest(book_b, seed=42, category_exposure_cap=0.20)

    assert r_a.n_trades > 0 and r_b.n_trades > 0, (
        "fixture must actually trade under the cap, else this pins nothing"
    )
    assert r_a.total_pnl_usd != r_b.total_pnl_usd, (
        "fixture must make the cap BIND differently across the two labelings, else the "
        "collision this test guards against cannot be demonstrated"
    )
    assert r_a.seed_hash != r_b.seed_hash, (
        "REGRESSION: two datasets with different category assignments produced different PnL "
        "under ONE seed_hash — the reproducibility fingerprint does not cover category"
    )


# --------------------------------------------------------------------------- #
# 2. category THREADS through walk_forward onto every BacktestTrade.           #
# --------------------------------------------------------------------------- #
def test_category_threads_onto_backtest_trades():
    markets = [
        _mkt("a", 0.80, 0.98, 1, 0, category=CATEGORY_CRYPTO),
        _mkt("b", 0.20, 0.02, 0, 5, category=CATEGORY_POLITICS),
        _mkt("c", 0.85, 0.99, 1, 40, category=CATEGORY_CRYPTO),
    ]
    res = wf.walk_forward_backtest(markets, seed=42)
    assert res.n_trades > 0, "fixture must produce trades to assert category threading"
    cat_by_id = {m.market_id: m.category for m in markets}
    for t in res.trades:
        assert t.category == cat_by_id[t.market_id]


def test_unlabeled_market_yields_none_category_on_trade():
    markets = [_mkt("a", 0.80, 0.98, 1, 0), _mkt("b", 0.20, 0.02, 0, 40)]
    res = wf.walk_forward_backtest(markets, seed=42)
    assert res.n_trades > 0
    assert all(t.category is None for t in res.trades)


# --------------------------------------------------------------------------- #
# 3. F10 CATEGORY dimension is now assessable on threaded trades.              #
# --------------------------------------------------------------------------- #
def test_regime_slice_assesses_category_when_threaded():
    """With category threaded onto trades, the caller can build a category_by_market_id
    map and analyze_regime_slices reports REAL category buckets (not 'uncategorized') —
    the F10 category dimension that was previously unassessable on real OOS runs."""
    markets = [
        _mkt("a", 0.80, 0.98, 1, 0, category=CATEGORY_CRYPTO),
        _mkt("b", 0.82, 0.98, 1, 3, category=CATEGORY_CRYPTO),
        _mkt("c", 0.30, 0.02, 0, 6, category=CATEGORY_POLITICS),
        _mkt("d", 0.28, 0.02, 0, 50, category=CATEGORY_POLITICS),
    ]
    res = wf.walk_forward_backtest(markets, seed=42)
    cat_map = {t.market_id: t.category for t in res.trades if t.category}
    report = analyze_regime_slices(res.trades, category_by_market_id=cat_map)
    buckets = {s.label for s in report.by_category}
    assert "uncategorized" not in buckets
    assert buckets <= {CATEGORY_CRYPTO, CATEGORY_POLITICS}


# --------------------------------------------------------------------------- #
# 4. FETCHERS derive a REAL category from question text (not the empty raw).   #
# --------------------------------------------------------------------------- #
def test_polymarket_history_fetcher_derives_category():
    """A real Gamma resolved market ships an EMPTY category — the fetcher must derive a
    coarse bucket from the question text, else every record collapses to 'General'."""
    f = PolymarketHistoryFetcher()
    raw = {
        "id": "m1", "conditionId": "c1",
        "question": "Will Bitcoin close above $100k by June 2026?",
        "category": "",  # empty, as real Gamma data is
        "outcomes": '["Yes", "No"]',
        "outcomePrices": '["1", "0"]',
        "clobTokenIds": '["tok_yes", "tok_no"]',
        "endDate": "2026-06-01T00:00:00Z",
        "startDate": "2026-01-01T00:00:00Z",
        "volume": "5000", "liquidity": "1000",
    }
    rm = f._parse_resolved(raw)
    assert rm is not None
    assert rm.category == CATEGORY_CRYPTO  # derived from "Bitcoin", not left ""


def test_polymarket_history_fetcher_unclassifiable_is_general():
    f = PolymarketHistoryFetcher()
    raw = {
        "id": "m2", "conditionId": "c2",
        "question": "Will the mystery box be opened before the deadline?",
        "category": "",
        "outcomes": '["Yes", "No"]', "outcomePrices": '["0", "1"]',
        "clobTokenIds": '["y", "n"]', "endDate": "2026-06-01T00:00:00Z",
    }
    rm = f._parse_resolved(raw)
    assert rm is not None
    assert rm.category == CATEGORY_GENERAL  # honest shared default, never fabricated


def test_hf_assembler_derives_category_from_question():
    """The HF (1.3M-corpus) assembler must derive the category from the question/slug so
    the large corpus carries a real bucket for EXP-003 / the F10 category dimension."""
    res_t = datetime(2026, 6, 1, tzinfo=UTC)
    rows = [
        HFDailyRow(
            market_id="hf1", timestamp=res_t - timedelta(days=d), price_yes=0.6,
            resolution_time=res_t, outcome=1, category="",
            question="Will the Democrats win the 2026 Senate election?",
        )
        for d in (10, 8, 6, 4)
    ]
    hm = _assemble_one("hf1", rows, decision_lead=timedelta(days=3), cats=None)
    assert hm is not None
    assert hm.category == CATEGORY_POLITICS  # derived from "election"/"Senate"/"Democrats"
