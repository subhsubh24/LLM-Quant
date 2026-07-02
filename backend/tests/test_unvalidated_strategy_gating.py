"""
Tests for the UNVALIDATED-STRATEGY gate + the removal of the fabricated whale seed.

Context (2026-07-01 Research Run 11 integrity finding, docs/growth/RESEARCH_MEMORY.md):
`WhaleCopyTradingStrategy` and `WeatherArbitrageStrategy` were wired UNCONDITIONALLY into
both default scanners (orchestrator + API) despite being untracked in ROADMAP/RESEARCH_MEMORY,
having no B3 registry evidence and no forensic-audit proof they fire on real-shaped data —
and the whale feed shipped a FABRICATED hardcoded `KNOWN_WHALES` seed (wrong / placeholder
wallet addresses). Per FACTORY_STANDARD "no alpha ships while integrity is weak", these
strategies must stay OUT of the default scan unless the owner explicitly opts in via
`ENABLE_UNVALIDATED_STRATEGIES` (default off), and the fabricated seed must be gone.

These tests are pure (no network, no fastapi) so they run in the blocking preflight gate.
"""

from app.config import get_settings
from app.prediction_markets import orchestrator, whale_feed
from app.prediction_markets.whale_feed import WhaleDataFeed


# --- The fabricated seed is gone ---------------------------------------------

def test_known_whales_seed_is_empty():
    """The hardcoded fabricated-legitimacy whale seed must be removed."""
    assert whale_feed.KNOWN_WHALES == []


class _NoLeaderboardClient:
    """A client whose public Data-API is unreachable (the in-env reality)."""

    def get_leaderboard(self, *args, **kwargs):
        return []


def test_seed_produces_no_whales_without_real_data():
    """
    With an empty seed AND no reachable leaderboard, seeding yields ZERO whales —
    the honest no-op, never a fabricated wallet.
    """
    feed = WhaleDataFeed(_NoLeaderboardClient())
    feed.seed_known_whales()
    assert feed.whales == {}


class _RaisingLeaderboardClient:
    def get_leaderboard(self, *args, **kwargs):
        raise ConnectionError("egress blocked")


def test_seed_no_whales_when_leaderboard_errors():
    """A leaderboard fetch error must not fall back to a fabricated seed."""
    feed = WhaleDataFeed(_RaisingLeaderboardClient())
    feed.seed_known_whales()
    assert feed.whales == {}


# --- The default scanner gates the unvalidated strategies ---------------------

_VALIDATED_NAMES = {
    "same_market_arb",
    "market_making",
    "flash_crash",
    "logical_implication",
    "wallet_divergence",
}
_UNVALIDATED_NAMES = {"whale_copy", "weather_arb"}


def _scanner_names(monkeypatch, enabled: bool):
    monkeypatch.setattr(get_settings(), "enable_unvalidated_strategies", enabled)
    scanner = orchestrator._build_default_scanner()
    return {s.name for s in scanner.strategies}


def test_default_scanner_excludes_unvalidated_by_default(monkeypatch):
    names = _scanner_names(monkeypatch, enabled=False)
    # Unvalidated strategies must NOT be present by default.
    assert not (_UNVALIDATED_NAMES & names), f"unvalidated leaked into default scan: {names}"
    # The validated strategies are still there (we didn't break the scan).
    assert _VALIDATED_NAMES <= names, f"validated strategies missing: {_VALIDATED_NAMES - names}"


def test_flag_enables_unvalidated_strategies(monkeypatch):
    names = _scanner_names(monkeypatch, enabled=True)
    assert _UNVALIDATED_NAMES <= names, f"opt-in did not enable them: {names}"
    # And the validated ones are still present.
    assert _VALIDATED_NAMES <= names


def test_default_flag_is_off():
    """Ship-safe default: the flag is off unless the owner sets it."""
    # A fresh Settings() (no env override) must default to off.
    from app.config import Settings
    assert Settings().enable_unvalidated_strategies is False


# NOTE: the API scanner (`routes._get_prediction_scanner`) gates identically via the same
# `get_settings().enable_unvalidated_strategies` flag. It is NOT asserted here — importing
# `app.api.routes` pulls in fastapi (absent in the lightweight CI gate), so this file stays
# dependency-light and proves the orchestrator path. (It historically also tripped the
# `app.*` vs `backend.app.*` dual-import table-registration conflict, now resolved by
# standardizing every test on `app.*`.) The gating logic in routes.py mirrors the path above.
