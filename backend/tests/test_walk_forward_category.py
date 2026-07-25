"""End-to-end category threading (ROADMAP F10 — anti-overfitting integrity).

The resolved-history fetchers now derive a coarse correlation CATEGORY
(``market_category.derive_market_category``) and thread it onto each
``HistoricalMarket``; the walk-forward carries it onto every ``BacktestTrade``; and
``validate_real_oos`` builds a ``category_by_market_id`` map so the F10
``analyze_regime_slices`` report can assess CATEGORY concentration on real OOS trades
(an aggregate edge concentrated in one category is NOT robust). Previously the category
was dropped, so the F10 category dimension was never assessed on real corpora.

The load-bearing safety property tested here is CONDITIONAL, and the condition matters:

* **While both per-category caps are OFF**, ``category`` is pure metadata — it never enters
  a decision or PnL, so it is EXCLUDED from ``_seed_hash``. A dataset labeled with
  categories MUST reproduce bit-for-bit identically to the same dataset unlabeled (the
  pinned real-data reproduction hash 8dc358439ffb5746 must not move because we added a
  category field).
* **The moment EITHER cap is active**, category becomes PnL-DETERMINING (the concurrent
  lane sizes by ``cat_room``, the cumulative lane by ``cum_room``), so it MUST enter the
  fingerprint — otherwise two differently-labeled datasets share a hash while producing
  different PnL.

An earlier version of this module documented and pinned the unconditional claim ("category
is never a PnL input"), which became FALSE when the per-category caps shipped (#388/#404).
The independent Quality Auditor reproduced up to a 3.9x PnL divergence under one shared
hash. That false invariant is corrected here, and the cap-active case — which the old test
never exercised — is now covered directly. All offline + deterministic.
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
# 1. seed_hash INVARIANCE — the reproducibility guarantee.                     #
# --------------------------------------------------------------------------- #
def test_category_is_excluded_from_seed_hash_WHEN_NO_CAP_IS_ACTIVE():
    """CAP-FREE lane: the SAME dataset, once unlabeled and once fully category-labeled, must
    produce the IDENTICAL seed_hash — with both caps off, category really is regime-slice
    metadata and never a PnL input. If this fails, every pinned cap-free reproduction hash
    (8dc358439ffb5746 / b3a8d5e0e9579853 / 79a4cca4b966138f) has silently moved."""
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
    assert r_unlabeled.seed_hash == r_labeled.seed_hash
    # ... and the realized PnL series must be identical too (categories change nothing).
    assert r_unlabeled.total_pnl_usd == r_labeled.total_pnl_usd
    assert r_unlabeled.n_trades == r_labeled.n_trades


def _relabel_dataset(n=60, category_a=CATEGORY_POLITICS, category_b=CATEGORY_SPORTS):
    """Two datasets identical in EVERY fingerprinted field except the category ASSIGNMENT.

    Two properties are load-bearing and easy to get wrong:

    * Both share the same distinct-category COUNT (2), so the ``effective_cumulative_cap``
      count-based mitigation cannot mask the difference — a same-count relabel is exactly
      what defeats it.
    * Decisions are spaced 4 days apart across ~240 days, comfortably past the
      ``train_min_days=28`` default, so real OOS windows OPEN and real trades SETTLE. An
      earlier version of this fixture spanned only 14 days and produced ``n_trades=0`` for
      every variant — the hash assertion still passed, but only because the category strings
      differed in the JSON payload; no cap-driven sizing ever ran. A test that cannot
      distinguish "the fingerprint works" from "no trade happened" is not evidence.
    """
    def build(cats):
        return [
            _mkt(f"m{i}", 0.30, 0.62, i % 3 == 0, i * 4, category=c, res_offset_days=6)
            for i, c in enumerate(cats)
        ]
    interleaved = [category_a if i % 2 == 0 else category_b for i in range(n)]
    blocked = [category_a if i < n // 2 else category_b for i in range(n)]
    return build(interleaved), build(blocked)


def test_seed_hash_covers_category_when_cap_active():
    """CAP-ACTIVE lane — the regression that pins the reproducibility fix.

    With either per-category cap on, ``category`` is PnL-determining, so two datasets that
    differ ONLY in their category labels MUST NOT share a ``seed_hash``. Before the fix they
    did (the independent Quality Auditor measured up to a 3.9x PnL divergence under one
    hash), which actively misled any reviewer comparing hashes.

    Crucially this asserts the PnL genuinely DIVERGES as well as the hash differing — that
    divergence is the whole reason the fingerprint must cover category, so a test that only
    checked the hash would be pinning the fix without demonstrating the defect.
    """
    a, b = _relabel_dataset()
    for cap_kwargs in (
        {"category_exposure_cap": 0.10},
        {"cumulative_category_budget_cap": 0.30},
        {"category_exposure_cap": 0.10, "cumulative_category_budget_cap": 0.30},
    ):
        ra = wf.walk_forward_backtest(a, seed=42, **cap_kwargs)
        rb = wf.walk_forward_backtest(b, seed=42, **cap_kwargs)
        assert ra.n_trades > 0 and rb.n_trades > 0, (
            f"fixture produced NO trades under {cap_kwargs} — the cap never bound, so this "
            f"assertion would pass vacuously"
        )
        assert ra.total_pnl_usd != rb.total_pnl_usd, (
            f"fixture PnL did not diverge under {cap_kwargs} — without divergence there is "
            f"no reproducibility hole to close, so the hash assertion proves nothing"
        )
        assert ra.seed_hash != rb.seed_hash, (
            f"category relabel shares a seed_hash under {cap_kwargs} despite PnL "
            f"{ra.total_pnl_usd:.2f} vs {rb.total_pnl_usd:.2f} — the cap makes category "
            f"PnL-determining, so the fingerprint MUST distinguish it"
        )


def test_uncategorized_none_and_sentinel_hash_identically_under_cap():
    """``None`` and the literal ``__uncategorized__`` land in the SAME cap bucket, so they
    must also fingerprint identically — otherwise the hash would report a difference the
    sizing logic does not actually make (the mirror-image defect).

    Spaced like ``_relabel_dataset`` so real trades settle: an equal-PnL assertion over two
    zero-trade runs is ``0.0 == 0.0`` and proves nothing.
    """
    none_labeled = [
        _mkt(f"m{i}", 0.30, 0.62, i % 3 == 0, i * 4, category=None, res_offset_days=6)
        for i in range(60)
    ]
    sentinel = [
        _mkt(f"m{i}", 0.30, 0.62, i % 3 == 0, i * 4, category="__uncategorized__",
             res_offset_days=6)
        for i in range(60)
    ]
    ra = wf.walk_forward_backtest(none_labeled, seed=42, category_exposure_cap=0.10)
    rb = wf.walk_forward_backtest(sentinel, seed=42, category_exposure_cap=0.10)
    assert ra.n_trades > 0, "fixture produced no trades — the equality assertions are vacuous"
    assert ra.seed_hash == rb.seed_hash
    assert ra.total_pnl_usd == rb.total_pnl_usd
    assert ra.n_trades == rb.n_trades


def test_cap_free_hash_and_pnl_unchanged_by_the_category_fingerprint():
    """The fix must be strictly additive: turning a cap ON is what introduces the category
    key, so a cap-free run's payload — and therefore its hash — is untouched. The SAME two
    datasets that diverge under a cap must be indistinguishable without one."""
    a, b = _relabel_dataset()
    ra = wf.walk_forward_backtest(a, seed=42)
    rb = wf.walk_forward_backtest(b, seed=42)
    assert ra.n_trades > 0, "fixture produced no trades — this assertion would be vacuous"
    assert ra.seed_hash == rb.seed_hash
    assert ra.total_pnl_usd == rb.total_pnl_usd, (
        "cap-free PnL must NOT depend on category — if it does, the premise that category "
        "is pure metadata while both caps are off is false"
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
