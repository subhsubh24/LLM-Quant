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

from app.prediction_markets import regime_slice as _rs
from app.prediction_markets import walk_forward as wf
from app.prediction_markets.market_category import (
    CATEGORY_CRYPTO,
    CATEGORY_ECONOMICS,
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


# =========================================================================== #
# CUMULATIVE per-category budget-SHARE cap (ROADMAP B4a-family / Research Run  #
# 21 — the FAITHFUL de-concentration control the concurrent cap could not      #
# provide). The concurrent cap bounds INSTANTANEOUS open exposure; because     #
# positions settle and free room, a category can cycle unbounded CUMULATIVE    #
# volume, so the concurrent cap does NOT bound F10's top_category_budget_share  #
# (Σ per-cat budget ÷ Σ total budget). THIS cap does — it is the exact control  #
# Runs 20-22 named-but-never-built. Same honesty properties as the concurrent  #
# cap: None is byte-identical; a set cap enters seed_hash; it only REDUCES     #
# concentration and can never manufacture PnL.                                 #
# =========================================================================== #
def _recycling_multi_cat_corpus(n_pol: int = 24, n_eco: int = 12):
    """A dominant POLITICS category + a minority ECONOMICS category, every market SHORT-LIVED
    (resolves 2 days after it opens) so cost basis RECYCLES through the bankroll — the shape
    where CONCURRENT exposure is ~one position at a time but CUMULATIVE per-category volume is
    large (a category cycles unbounded budget through recycled room). The non-trading day-0
    anchor sets the window origin without deploying capital. Categories are interleaved across
    the timeline so both are represented throughout, and POLITICS dominates the trade COUNT so
    its cumulative budget SHARE is high (~n_pol/(n_pol+n_eco)) before any de-concentration."""
    markets = [_mkt("anchor", 0.50, 0.50, 0, 0, category=CATEGORY_POLITICS, res_day=2)]
    day = 30
    pol = eco = 0
    i = 0
    # Interleave pattern [POL, POL, ECO] so POLITICS is 2/3 of the count; each opens on its own
    # day and resolves 2 days later (short-lived → recycles before the next opens).
    while pol < n_pol or eco < n_eco:
        want_eco = (i % 3 == 2)
        if want_eco and eco < n_eco:
            markets.append(_mkt(f"e{eco:03d}", 0.50, 0.92, eco % 2, day, category=CATEGORY_ECONOMICS, res_day=day + 2))
            eco += 1
        elif pol < n_pol:
            markets.append(_mkt(f"p{pol:03d}", 0.50, 0.92, pol % 2, day, category=CATEGORY_POLITICS, res_day=day + 2))
            pol += 1
        elif eco < n_eco:
            markets.append(_mkt(f"e{eco:03d}", 0.50, 0.92, eco % 2, day, category=CATEGORY_ECONOMICS, res_day=day + 2))
            eco += 1
        day += 3
        i += 1
    return markets


def _top_cat_budget_share(res):
    """F10's exposure-concentration metric computed straight from the settled trades:
    max over categories of (Σ category budget) ÷ (Σ total budget). Matches
    regime_slice.top_category_budget_share when the category map mirrors trade.category."""
    by_cat: dict = {}
    for t in res.trades:
        by_cat[t.category] = by_cat.get(t.category, 0.0) + t.budget_usd
    total = sum(by_cat.values())
    return (max(by_cat.values()) / total) if total > 0 else 0.0


def test_cumulative_cap_none_is_byte_identical():
    markets = _recycling_multi_cat_corpus()
    a = wf.walk_forward_backtest(markets, initial_bankroll=_BANKROLL, seed=42)
    b = wf.walk_forward_backtest(
        markets, initial_bankroll=_BANKROLL, seed=42, cumulative_category_budget_cap=None
    )
    assert a.seed_hash == b.seed_hash
    assert a.total_pnl_usd == b.total_pnl_usd
    assert [t.budget_usd for t in a.trades] == [t.budget_usd for t in b.trades]


def test_cumulative_cap_enters_hash_and_is_deterministic():
    markets = _recycling_multi_cat_corpus()
    base = wf.walk_forward_backtest(markets, initial_bankroll=_BANKROLL, seed=42)
    capped = wf.walk_forward_backtest(
        markets, initial_bankroll=_BANKROLL, seed=42, cumulative_category_budget_cap=0.4
    )
    again = wf.walk_forward_backtest(
        markets, initial_bankroll=_BANKROLL, seed=42, cumulative_category_budget_cap=0.4
    )
    assert capped.seed_hash != base.seed_hash          # a set cap changed PnL → must change hash
    assert capped.seed_hash == again.seed_hash          # deterministic
    assert [t.budget_usd for t in capped.trades] == [t.budget_usd for t in again.trades]


def test_cumulative_cap_bounds_F10_share_where_concurrent_cap_cannot():
    """THE load-bearing test: on a RECYCLING corpus the CONCURRENT cap is a no-op on cumulative
    concentration, but the CUMULATIVE cap bounds F10's own top_category_budget_share to the cap
    (plus a disclosed one-trade bootstrap slack)."""
    CAP = 0.4
    markets = _recycling_multi_cat_corpus(n_pol=24, n_eco=12)
    uncapped = wf.walk_forward_backtest(markets, initial_bankroll=_BANKROLL, seed=42)
    concurrent = wf.walk_forward_backtest(
        markets, initial_bankroll=_BANKROLL, seed=42, category_exposure_cap=0.2
    )
    cumulative = wf.walk_forward_backtest(
        markets, initial_bankroll=_BANKROLL, seed=42, cumulative_category_budget_cap=CAP
    )

    share_uncapped = _top_cat_budget_share(uncapped)
    share_concurrent = _top_cat_budget_share(concurrent)
    share_cumulative = _top_cat_budget_share(cumulative)

    # Precondition: POLITICS genuinely dominates cumulative budget when unbounded.
    assert share_uncapped > CAP + 0.1

    # The CONCURRENT cap does NOT bound cumulative concentration (recycling defeats it): the
    # dominant category's cumulative SHARE is essentially unchanged from uncapped.
    assert share_concurrent > CAP + 0.1

    # The CUMULATIVE cap DOES bound it — top share at/under the cap + a one-trade bootstrap slack
    # (the exempt first deployed trade, diluted by later turnover). Slack is DISCLOSED, not magic.
    max_trade_budget = max((t.budget_usd for t in cumulative.trades), default=0.0)
    total_budget_cum = sum(t.budget_usd for t in cumulative.trades)
    slack = (max_trade_budget / total_budget_cum) if total_budget_cum > 0 else 0.0
    assert share_cumulative <= CAP + slack + 1e-6
    assert share_cumulative < share_uncapped              # it genuinely de-concentrated

    # It matches F10's OWN metric (regime_slice), i.e. this is the quantity the gate reads.
    cat_map = {m.market_id: m.category for m in markets if m.category}
    reg = _rs.analyze_regime_slices(cumulative.trades, category_by_market_id=cat_map)
    assert reg.top_category_budget_share <= CAP + slack + 1e-6


def test_cumulative_cap_is_risk_control_never_manufactures_pnl():
    markets = _recycling_multi_cat_corpus()
    uncapped = wf.walk_forward_backtest(markets, initial_bankroll=_BANKROLL, seed=42)
    cumulative = wf.walk_forward_backtest(
        markets, initial_bankroll=_BANKROLL, seed=42, cumulative_category_budget_cap=0.4
    )
    # A de-concentration cap only ever REDUCES deployed capital — it can never deploy MORE, so it
    # cannot manufacture an edge from a signal (the honest claim in the docstring).
    assert sum(t.budget_usd for t in cumulative.trades) <= sum(t.budget_usd for t in uncapped.trades)
    assert cumulative.final_bankroll >= 0.0               # cash accounting stays sound


def test_cumulative_cap_validation_rejects_out_of_range():
    import pytest

    markets = _recycling_multi_cat_corpus(n_pol=2, n_eco=1)
    for bad in (0.0, -0.1, 1.0001, 2.0):
        with pytest.raises(ValueError):
            wf.walk_forward_backtest(
                markets, initial_bankroll=_BANKROLL, seed=42, cumulative_category_budget_cap=bad
            )
