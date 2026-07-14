"""Regression (B / correctness): the UNITS CONTRACT (#263/#268/#275) applied to the two
remaining trade-EXECUTING strategies — ``WeatherArbitrageStrategy`` and
``WhaleCopyTradingStrategy``.

These two are gated OFF by default (``ENABLE_UNVALIDATED_STRATEGIES``, B7), but they are a
SUPPORTED owner opt-in: when enabled, the orchestrator adds them to the live scanner
(orchestrator.py:1719-1728) and each emits a real single-outcome ``ScanResult``
(``outcome_idx >= 0``) that the executor can fill. Both emitted a confidence DECOUPLED from
the reconstructed win-probability:

  * Weather emitted ``confidence = forecast.confidence`` (``c``), but its own edge is
    ``edge = (1-price)*c - price`` → the orchestrator reconstructs
    ``win_probability = price + edge = (1-price)*c`` — so the raw ``c`` OVERSTATES the
    win-probability by ``1/(1-price)`` and the ``min_confidence`` gate ADMITS BUYs whose
    true fair value is below the gate.
  * Whale emitted ``confidence = min(0.90, buy_consensus)`` with a hardcoded ``edge = 0.15``.
    The whale-consensus fraction is INDEPENDENT of ``price``, so it can overstate
    ``win_probability = price + 0.15`` and admit BUYs weaker than they appear.

The fix pins ``confidence = gate_confidence(entry_price, edge) = clip(entry+edge, 0, 1)`` at
both emission sites. These tests assert the post-fix value and prove the PRE-FIX confidence
would have bypassed the ``min_confidence`` gate on the SAME signal.

Offline + deterministic: the scan paths under test never touch the network.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List

from app.prediction_markets.polymarket_client import (
    Market,
    Outcome,
    ScanResult,
    gate_confidence,
)
from app.prediction_markets.strategies import (
    StrategyConfig,
    WeatherArbitrageStrategy,
    WeatherForecast,
    WhaleCopyTradingStrategy,
)
from app.prediction_markets.advanced_strategies import WalletBehaviorDivergence
from app.prediction_markets.orchestrator import KellyConfig, size_from_scan_result


class _DummyClient:
    """The scan paths under test never touch the client (fully offline)."""


def _weather_market() -> Market:
    end = datetime.now(timezone.utc) + timedelta(days=3)
    return Market(
        id="wx",
        condition_id="c_wx",
        question="What will the temperature be in NYC on Friday?",
        slug="wx",
        description="",
        category="Weather",
        end_date=end,
        outcomes=[
            # The correct bucket per the forecast, priced cheap (< entry_threshold 0.15).
            Outcome(token_id="wx_bucket", label="40-45°F", price=0.10, midpoint=0.10, volume=20_000.0),
            Outcome(token_id="wx_other", label="Something else", price=0.90, midpoint=0.90, volume=20_000.0),
        ],
        total_volume=20_000.0,
        liquidity=20_000.0,
        active=True,
        closed=False,
        resolved=False,
    )


def _generic_market(mid: str, yes_price: float) -> Market:
    end = datetime.now(timezone.utc) + timedelta(days=30)
    return Market(
        id=mid,
        condition_id=f"c_{mid}",
        question="Will the underdog win?",
        slug=mid,
        description="",
        category="Sports",
        end_date=end,
        outcomes=[
            Outcome(token_id=f"{mid}_yes", label="Yes", price=yes_price, midpoint=yes_price, volume=50_000.0),
            Outcome(token_id=f"{mid}_no", label="No", price=round(1.0 - yes_price, 4), midpoint=round(1.0 - yes_price, 4), volume=50_000.0),
        ],
        total_volume=50_000.0,
        liquidity=50_000.0,
        active=True,
        closed=False,
        resolved=False,
    )


def _assert_invariant(results: List[ScanResult]) -> None:
    for r in results:
        expected = gate_confidence(r.entry_price, r.edge)
        assert abs(r.confidence - expected) < 1e-9, (
            f"{r.strategy}/{r.side}: confidence {r.confidence} != clip(entry+edge) "
            f"{expected} (entry={r.entry_price}, edge={r.edge})"
        )
        assert 0.0 <= r.confidence <= 1.0


# ── WeatherArbitrageStrategy ──

def test_weather_confidence_is_fair_value_not_forecast_confidence():
    strat = WeatherArbitrageStrategy(_DummyClient(), StrategyConfig(dry_run=True))
    forecast_conf = 0.90
    strat.update_forecasts({
        "NYC": WeatherForecast(
            location="NYC",
            date=datetime.now(timezone.utc),
            temp_high_f=46.0,
            temp_low_f=38.0,
            temp_mean_f=42.0,  # inside the 40-45°F bucket
            precipitation_pct=0.0,
            wind_mph=5.0,
            confidence=forecast_conf,
        )
    })
    results = strat.scan([_weather_market()])
    buys = [r for r in results if r.side == "BUY"]
    assert buys, "expected a NOAA-bucket BUY signal"
    _assert_invariant(results)

    r = buys[0]
    # win_probability = price + edge = (1 - price) * forecast_conf; NOT the raw forecast_conf.
    win_prob = r.entry_price + r.edge
    assert abs(r.confidence - win_prob) < 1e-9
    assert r.confidence < forecast_conf - 1e-6, (
        "the fix must OVERWRITE the raw forecast confidence with the (lower) fair value"
    )

    # Behavioral flip: a min_confidence just above the true fair value gates the trade out.
    kcfg = KellyConfig(use_monte_carlo=False, min_confidence=round(win_prob + 0.02, 6))
    bet_usd, contracts = size_from_scan_result(r, bankroll=1_000.0, config=kcfg)
    assert bet_usd == 0.0 and contracts == 0.0, (
        "a signal whose fair value is below min_confidence must be gated out post-fix"
    )
    # Control: the PRE-FIX confidence (the raw forecast confidence) would have passed the gate.
    r.confidence = forecast_conf
    bet_prefix, _ = size_from_scan_result(r, bankroll=1_000.0, config=kcfg)
    assert bet_prefix > 0.0, "sanity: the pre-fix forecast-confidence bypassed the gate"


# ── WhaleCopyTradingStrategy ──

def test_whale_confidence_is_fair_value_not_consensus():
    strat = WhaleCopyTradingStrategy(_DummyClient(), StrategyConfig(dry_run=True))
    strat.add_wallet("0xaaa", name="whale_a")
    strat.add_wallet("0xbbb", name="whale_b")
    # Two tracked whales BUY the same "Yes" outcome within the hour → consensus = 2/2 = 1.0.
    for w in ("0xaaa", "0xbbb"):
        strat.record_trade(w, market_id="wm", outcome="Yes", side="BUY", price=0.50, size=5_000.0)

    market = _generic_market("wm", 0.50)
    results = strat.scan([market])
    buys = [r for r in results if r.side == "BUY"]
    assert buys, "expected a whale-consensus BUY signal"
    _assert_invariant(results)

    r = buys[0]
    # edge is a hardcoded 0.15 → win_probability = 0.50 + 0.15 = 0.65; NOT the 1.0 consensus.
    win_prob = r.entry_price + r.edge
    assert abs(r.confidence - win_prob) < 1e-9
    assert abs(r.confidence - 0.65) < 1e-9

    kcfg = KellyConfig(use_monte_carlo=False, min_confidence=0.70)
    bet_usd, contracts = size_from_scan_result(r, bankroll=1_000.0, config=kcfg)
    assert bet_usd == 0.0 and contracts == 0.0, (
        "a whale signal whose fair value (0.65) is below min_confidence (0.70) must be gated out"
    )
    # Control: the PRE-FIX confidence (min(0.90, consensus) = 0.90) would have passed.
    r.confidence = 0.90
    bet_prefix, _ = size_from_scan_result(r, bankroll=1_000.0, config=kcfg)
    assert bet_prefix > 0.0, "sanity: the pre-fix consensus confidence bypassed the gate"


# ── WalletBehaviorDivergence ──
# Gated OFF by default (ENABLE_UNVALIDATED_STRATEGIES, B7), but a SUPPORTED owner opt-in:
# when enabled the orchestrator adds it to the live scanner and it emits a real SINGLE-outcome
# ScanResult (outcome_idx >= 0) the executor can fill. It previously emitted
# ``confidence = _compute_confidence(signal)`` — a whale-count / historical-accuracy /
# divergence-magnitude heuristic DECOUPLED from entry_price + edge — so the min_confidence gate
# filtered on the wrong quantity (same class as #263/#268/#275/#280/#284). The fix pins it to
# ``gate_confidence(entry_price, edge)`` and DELETES the heuristic helper.

def test_wallet_divergence_confidence_is_fair_value_not_heuristic():
    strat = WalletBehaviorDivergence(_DummyClient(), StrategyConfig(dry_run=True))
    # Two distinct whales BUY the same market at 0.40 into a high-volatility regime (0.25, above
    # the public "max_volatility" alpha of 0.10) → a volatility-divergence signal with 2 unique
    # wallets and a consensus BUY on market "m1".
    for w in ("0xa1", "0xb2"):
        strat.record_whale_trade(
            wallet=w, market_id="m1", outcome="Yes", side="BUY",
            price=0.40, size=5_000.0, market_volatility=0.25,
            market_liquidity=50_000.0, edge_estimate=0.03,
        )

    results = strat.scan([_generic_market("m1", 0.40)])
    buys = [r for r in results if r.side == "BUY"]
    assert buys, "expected a whale-divergence BUY signal"
    _assert_invariant(results)

    r = buys[0]
    # entry_price = avg whale price = 0.40; edge = max(avg_edge 0.03, min_edge+0.01 0.03) = 0.03.
    # win_probability = 0.40 + 0.03 = 0.43 — the fair value, NOT the removed heuristic.
    win_prob = r.entry_price + r.edge
    assert abs(r.confidence - win_prob) < 1e-9
    assert abs(r.confidence - 0.43) < 1e-9

    # The removed ``_compute_confidence`` heuristic is genuinely gone — no decoupled-confidence
    # source can be re-wired.
    assert not hasattr(strat, "_compute_confidence")

    # Behavioral flip: a min_confidence just above the true fair value gates the trade out.
    kcfg = KellyConfig(use_monte_carlo=False, min_confidence=round(win_prob + 0.05, 6))
    bet_usd, contracts = size_from_scan_result(r, bankroll=1_000.0, config=kcfg)
    assert bet_usd == 0.0 and contracts == 0.0, (
        "a signal whose fair value (0.43) is below min_confidence must be gated out post-fix"
    )
    # Control: the old heuristic (whale-count 0.40*0.5 + accuracy 0.35*acc + magnitude 0.25*~0.95)
    # sat well ABOVE 0.43 and would have bypassed the same gate — the wrong-units bug this fixes.
    r.confidence = 0.60
    bet_prefix, _ = size_from_scan_result(r, bankroll=1_000.0, config=kcfg)
    assert bet_prefix > 0.0, "sanity: a decoupled (higher) heuristic confidence bypassed the gate"
