"""The simulation-pricer probability override on the REAL sizing path.

This path sized production bets and was covered by NOTHING: every test that touched
``size_from_scan_result`` set ``use_monte_carlo=False`` (9 call sites), while the production
default was ``True`` — so backtest sizing and live sizing were different code. The
independent Quality Auditor named this as the top ``functional_reality`` gap, together with
the fabricated ``vol=0.3`` / ``T=30/365`` constants and the UNSEEDED pricer construction on
the production-default paper path (a ``correctness_reliability`` determinism violation).

These tests pin the corrected contract:

1. the override is OFF by default, so the default path sizes identically to the backtest;
2. it never runs on a fabricated horizon — no usable ``end_date`` means SKIP, not invent;
3. it never runs on a fabricated volatility — no explicit ``vol`` means SKIP;
4. when it does run, ``T`` comes from the market's real ``end_date``;
5. it is deterministic (seeded), run to run.

All offline, no network, no venue credentials.
"""

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from app.prediction_markets import orchestrator as orch
from app.prediction_markets.orchestrator import (
    KellyConfig,
    _time_to_resolution_years,
    size_from_scan_result,
)
from app.prediction_markets.polymarket_client import Market, Outcome, ScanResult

UTC = timezone.utc
NOW = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)


def _market(end_date):
    return Market(
        id="sim",
        condition_id="c_sim",
        question="Will the simulation override price on a real horizon?",
        slug="sim",
        description="",
        category="General",
        end_date=end_date,
        outcomes=[
            Outcome(token_id="sim_yes", label="Yes", price=0.62, midpoint=0.62, volume=50_000.0),
            Outcome(token_id="sim_no", label="No", price=0.38, midpoint=0.38, volume=50_000.0),
        ],
        total_volume=100_000.0,
        liquidity=50_000.0,
        active=True,
        closed=False,
        resolved=False,
    )


def _scan(end_date=NOW + timedelta(days=30), entry_price=0.62, edge=0.05):
    return ScanResult(
        market=_market(end_date),
        strategy="test_strategy",
        outcome_idx=0,
        side="BUY",
        entry_price=entry_price,
        expected_value=1.0,
        edge=edge,
        confidence=entry_price + edge,
        reason="unit test",
        timestamp=NOW,
    )


# --------------------------------------------------------------------------- #
# 1. DEFAULT OFF — backtest sizing == live sizing.                             #
# --------------------------------------------------------------------------- #
def test_simulation_pricer_is_off_by_default():
    """The production default must not run the uncalibrated override."""
    assert KellyConfig().use_simulation_pricer is False


def test_default_config_sizes_identically_to_explicitly_disabled():
    """The exact property the 9 ``use_monte_carlo=False`` test call sites assumed but never
    verified: the DEFAULT config and an explicitly-pricer-disabled config size the same."""
    result = _scan()
    default_bet, default_contracts = size_from_scan_result(
        result, bankroll=10_000.0, config=KellyConfig()
    )
    disabled_bet, disabled_contracts = size_from_scan_result(
        result, bankroll=10_000.0, config=KellyConfig(use_simulation_pricer=False)
    )
    assert default_bet == disabled_bet
    assert default_contracts == disabled_contracts
    assert default_bet > 0, "the fixture should produce a real bet, or this proves nothing"


# --------------------------------------------------------------------------- #
# 2 + 3. NEVER on fabricated inputs.                                           #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "end_date",
    [None, NOW - timedelta(days=1), NOW],
    ids=["no_end_date", "already_resolved", "resolves_now"],
)
def test_override_skipped_when_horizon_cannot_be_derived(end_date):
    """No real horizon => SKIP. The old code invented ``T = 30/365`` here."""
    result = _scan(end_date=end_date)
    enabled = KellyConfig(use_simulation_pricer=True, simulation_vol=0.30)
    with_pricer, _ = size_from_scan_result(result, bankroll=10_000.0, config=enabled)
    baseline, _ = size_from_scan_result(result, bankroll=10_000.0, config=KellyConfig())
    assert with_pricer == baseline, "a missing horizon must not change the bet size"


def test_override_skipped_when_vol_not_supplied():
    """No explicit vol => SKIP. The old code invented ``vol = 0.3`` here."""
    result = _scan()
    enabled_without_vol = KellyConfig(use_simulation_pricer=True, simulation_vol=None)
    with_pricer, _ = size_from_scan_result(
        result, bankroll=10_000.0, config=enabled_without_vol
    )
    baseline, _ = size_from_scan_result(result, bankroll=10_000.0, config=KellyConfig())
    assert with_pricer == baseline


def test_use_monte_carlo_alone_no_longer_enables_the_override():
    """The regression guard for the flag split. ``use_monte_carlo=True`` is the PRODUCTION
    default and used to drag the unvalidated pricer override along with it."""
    result = _scan()
    assert KellyConfig().use_monte_carlo is True, "guard: the mc_kelly default is unchanged"
    mc_only, _ = size_from_scan_result(
        result,
        bankroll=10_000.0,
        config=KellyConfig(use_monte_carlo=True, simulation_vol=0.30),
    )
    baseline, _ = size_from_scan_result(
        result, bankroll=10_000.0, config=KellyConfig(use_simulation_pricer=False)
    )
    assert mc_only == baseline


# --------------------------------------------------------------------------- #
# 4. Real horizon derivation.                                                  #
# --------------------------------------------------------------------------- #
def test_time_to_resolution_uses_the_markets_real_end_date():
    years = _time_to_resolution_years(_market(NOW + timedelta(days=73)), now=NOW)
    assert years == pytest.approx(73.0 / 365.0, rel=1e-9)


def test_time_to_resolution_normalizes_a_naive_end_date():
    """Polymarket's parser can yield a naive datetime; subtracting it from an aware ``now``
    would raise inside a broadly-caught sizing path."""
    naive_end = (NOW + timedelta(days=10)).replace(tzinfo=None)
    years = _time_to_resolution_years(_market(naive_end), now=NOW)
    assert years == pytest.approx(10.0 / 365.0, rel=1e-9)


def test_time_to_resolution_returns_none_rather_than_a_fallback():
    assert _time_to_resolution_years(_market(None), now=NOW) is None
    assert _time_to_resolution_years(_market(NOW - timedelta(seconds=1)), now=NOW) is None


def test_enabled_override_prices_on_the_real_horizon(monkeypatch):
    """When the override IS enabled with real inputs, the pricer receives the market's real
    ``T`` (not 30/365) and an explicit seed (not an unseeded RNG)."""
    if orch.EnhancedContractPricer is None:
        pytest.skip("simulation_integration not importable in this environment")

    seen = {}

    class _SpyPricer:
        def __init__(self, seed=None):
            seen["seed"] = seed

        def price_contract(self, current_prob, vol, T, n_paths=50_000):
            seen["vol"] = vol
            seen["T"] = T
            return {"probability": current_prob, "method": "spy"}

    monkeypatch.setattr(orch, "EnhancedContractPricer", _SpyPricer)
    result = _scan(end_date=NOW + timedelta(days=73))
    size_from_scan_result(
        result,
        bankroll=10_000.0,
        config=KellyConfig(use_simulation_pricer=True, simulation_vol=0.42),
    )
    assert seen["seed"] == 42, "the pricer must be constructed SEEDED (determinism contract)"
    assert seen["vol"] == 0.42, "vol must be the supplied value, never an invented constant"
    assert seen["T"] == pytest.approx(73.0 / 365.0, rel=1e-9), (
        "T must come from the market's real end_date, never the old 30/365 constant"
    )
    assert seen["T"] != pytest.approx(30.0 / 365.0, rel=1e-9)


# --------------------------------------------------------------------------- #
# 5. Determinism.                                                              #
# --------------------------------------------------------------------------- #
def test_enabled_override_is_deterministic_run_to_run():
    """The production-default paper path must be reproducible. The pricer used to be
    constructed unseeded, so repeated sizing of the SAME opportunity could differ."""
    if orch.EnhancedContractPricer is None:
        pytest.skip("simulation_integration not importable in this environment")
    result = _scan()
    cfg = KellyConfig(use_simulation_pricer=True, simulation_vol=0.30)
    sizes = {size_from_scan_result(result, bankroll=10_000.0, config=cfg) for _ in range(5)}
    assert len(sizes) == 1, f"non-deterministic sizing across identical runs: {sizes}"


def test_config_is_immutable_style_replaceable():
    """Guard that the new fields participate in the dataclass contract other call sites use."""
    cfg = replace(KellyConfig(), use_simulation_pricer=True, simulation_vol=0.25)
    assert cfg.use_simulation_pricer is True
    assert cfg.simulation_vol == 0.25
    assert cfg.simulation_pricer_seed == 42
