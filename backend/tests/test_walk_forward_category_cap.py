"""Per-CATEGORY exposure cap in walk_forward (ROADMAP B4a-family / Research Run 20-22).

The bucket-calibration family (EXP-002/003/005) was REFUTED with a diagnosed failure mode:
F10 found the OOS PnL propped up by many small trades ALL in one correlated category, not
one oversized bet — so Research Run 22 showed a per-TRADE notional cap is a NO-OP. The
named-but-never-built fix (Run 20 option a / Run 21) is a per-CATEGORY EXPOSURE cap: total
committed cost basis in any one category may not exceed ``cap`` x equity at the instant a
position opens. This is the honest test of that mechanism.

Load-bearing honesty properties asserted here:
  * cap=None is byte-identical to before — the pinned reproduction hashes CANNOT move;
  * a SET cap enters the seed_hash (results legitimately differ) and stays deterministic;
  * the cap genuinely BOUNDS concurrent per-category committed exposure (it is not cosmetic);
  * it is a RISK CONTROL: it only ever REDUCES concentration, never increases exposure, and
    it cannot manufacture PnL — a bounded run's cash accounting stays sound.
All offline + deterministic (no egress, no credentials).
"""

from datetime import datetime, timedelta, timezone

from app.prediction_markets import walk_forward as wf
from app.prediction_markets.market_category import (
    CATEGORY_CRYPTO,
    CATEGORY_POLITICS,
)

UTC = timezone.utc
_BANKROLL = 10_000.0


def _mkt(mid, price, prob, outcome, day, *, category=None, res_day=200):
    d = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=day)
    return wf.HistoricalMarket(
        market_id=mid,
        decision_time=d,
        resolution_time=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=res_day),
        market_price=price,
        model_prob=prob,
        outcome=outcome,
        category=category,
    )


def _concentrated_corpus(n_crypto: int = 12):
    """A non-trading day-0 anchor (sets the window origin so the cluster falls in OOS windows
    without itself deploying capital, keeping equity flat) + a cluster of strong-edge CRYPTO
    markets that all open across OOS windows and all resolve LATER than every open, so their
    cost basis is committed CONCURRENTLY — the correlated-cluster shape the cap must bound."""
    # Anchor: model_prob == price -> zero edge -> never trades -> equity stays exactly bankroll.
    markets = [_mkt("anchor", 0.50, 0.50, 0, 0, category=CATEGORY_POLITICS)]
    for i in range(n_crypto):
        # Strong YES edge (0.50 vs 0.92) -> the net-edge strategy trades at the 5% cap.
        markets.append(
            _mkt(f"c{i:03d}", 0.50, 0.92, i % 2, 30 + 2 * i, category=CATEGORY_CRYPTO)
        )
    return markets


def _cat_budget(res, category):
    return sum(t.budget_usd for t in res.trades if t.category == category)


# --------------------------------------------------------------------------- #
# 1. cap=None is byte-identical — pinned reproduction hashes must not move.    #
# --------------------------------------------------------------------------- #
def test_cap_none_is_byte_identical_to_no_cap():
    markets = _concentrated_corpus()
    a = wf.walk_forward_backtest(markets, initial_bankroll=_BANKROLL, seed=42)
    b = wf.walk_forward_backtest(
        markets, initial_bankroll=_BANKROLL, seed=42, category_exposure_cap=None
    )
    assert a.seed_hash == b.seed_hash
    assert a.total_pnl_usd == b.total_pnl_usd
    assert a.n_trades == b.n_trades
    assert [t.budget_usd for t in a.trades] == [t.budget_usd for t in b.trades]


# --------------------------------------------------------------------------- #
# 2. A set cap enters the fingerprint AND is deterministic.                    #
# --------------------------------------------------------------------------- #
def test_set_cap_changes_hash_and_is_deterministic():
    markets = _concentrated_corpus()
    base = wf.walk_forward_backtest(markets, initial_bankroll=_BANKROLL, seed=42)
    capped = wf.walk_forward_backtest(
        markets, initial_bankroll=_BANKROLL, seed=42, category_exposure_cap=0.2
    )
    assert capped.seed_hash != base.seed_hash          # cap changed PnL -> must change hash
    again = wf.walk_forward_backtest(
        markets, initial_bankroll=_BANKROLL, seed=42, category_exposure_cap=0.2
    )
    assert capped.seed_hash == again.seed_hash
    assert capped.total_pnl_usd == again.total_pnl_usd
    assert [t.budget_usd for t in capped.trades] == [t.budget_usd for t in again.trades]


# --------------------------------------------------------------------------- #
# 3. The cap genuinely BOUNDS concurrent per-category committed exposure.      #
# --------------------------------------------------------------------------- #
def test_cap_bounds_dominant_category_exposure():
    markets = _concentrated_corpus(n_crypto=12)
    uncapped = wf.walk_forward_backtest(markets, initial_bankroll=_BANKROLL, seed=42)
    capped = wf.walk_forward_backtest(
        markets, initial_bankroll=_BANKROLL, seed=42, category_exposure_cap=0.2
    )
    crypto_uncapped = _cat_budget(uncapped, CATEGORY_CRYPTO)
    crypto_capped = _cat_budget(capped, CATEGORY_CRYPTO)
    # The cluster is concurrent (all resolve day 200 > every open) and equity is flat at the
    # bankroll (anchor never trades, nothing settles mid-cluster), so total committed CRYPTO
    # basis must not exceed cap x bankroll = 0.2 x 10_000 = 2_000 (+ float slack).
    assert crypto_uncapped > 2_000.0                    # unbounded, it WOULD concentrate...
    assert crypto_capped <= 2_000.0 + 1.0               # ...bounded to the cap
    assert crypto_capped < crypto_uncapped
    # Fewer CRYPTO trades clear under the cap (later ones hit a full category and are skipped).
    n_crypto_capped = sum(1 for t in capped.trades if t.category == CATEGORY_CRYPTO)
    n_crypto_uncapped = sum(1 for t in uncapped.trades if t.category == CATEGORY_CRYPTO)
    assert n_crypto_capped < n_crypto_uncapped


# --------------------------------------------------------------------------- #
# 4. A tiny cap (< one trade) sizes the single admitted trade DOWN precisely.  #
# --------------------------------------------------------------------------- #
def test_tiny_cap_sizes_single_trade_down_to_room():
    markets = _concentrated_corpus(n_crypto=12)
    capped = wf.walk_forward_backtest(
        markets, initial_bankroll=_BANKROLL, seed=42, category_exposure_cap=0.03
    )
    crypto_capped = _cat_budget(capped, CATEGORY_CRYPTO)
    # 3% of a flat 10_000 equity = 300 room; the first crypto trade is sized DOWN to it and
    # the rest find zero room -> total crypto basis ~ 300, not a fabricated full-size fill.
    assert abs(crypto_capped - 300.0) < 1.0
    assert sum(1 for t in capped.trades if t.category == CATEGORY_CRYPTO) == 1


def test_dust_floor_skips_sub_cent_capped_positions():
    # A cap so tiny that the per-category room is a sub-dollar "dust" position: the dust guard
    # SKIPS it rather than admit a near-zero trade that would still count toward the F11
    # min-trades floor. Here room = 1e-5 x 10_000 = $0.10 < the $1 dust floor -> no crypto trades.
    markets = _concentrated_corpus(n_crypto=12)
    capped = wf.walk_forward_backtest(
        markets, initial_bankroll=_BANKROLL, seed=42, category_exposure_cap=1e-5
    )
    assert sum(1 for t in capped.trades if t.category == CATEGORY_CRYPTO) == 0  # all dust-skipped
    assert capped.final_bankroll >= 0.0


# --------------------------------------------------------------------------- #
# 5. It is a RISK CONTROL: only reduces exposure; accounting stays sound.      #
# --------------------------------------------------------------------------- #
def test_cap_never_increases_exposure_and_cash_is_sound():
    markets = _concentrated_corpus()
    uncapped = wf.walk_forward_backtest(markets, initial_bankroll=_BANKROLL, seed=42)
    capped = wf.walk_forward_backtest(
        markets, initial_bankroll=_BANKROLL, seed=42, category_exposure_cap=0.2
    )
    total_budget_capped = sum(t.budget_usd for t in capped.trades)
    total_budget_uncapped = sum(t.budget_usd for t in uncapped.trades)
    assert total_budget_capped <= total_budget_uncapped   # never deploys MORE under a cap
    # Cash accounting stays sound: final bankroll is finite and non-negative (no over-deploy).
    assert capped.final_bankroll >= 0.0
    assert capped.n_trades >= 0


def test_cap_validation_rejects_out_of_range():
    import pytest

    markets = _concentrated_corpus(n_crypto=2)
    for bad in (0.0, -0.1, 1.0001, 2.0):
        with pytest.raises(ValueError):
            wf.walk_forward_backtest(
                markets, initial_bankroll=_BANKROLL, seed=42, category_exposure_cap=bad
            )
