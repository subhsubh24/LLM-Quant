"""
Tests for LLM safety enforcement in QuantAnalyst._call_llm:
  - Hard timeout: a hanging Gemini call returns None within the budget.
  - Spend cap: cumulative cost accumulates; next call over the cap raises
    LLMBudgetExceeded (fail-loud), not silently ignored.
  - Under the cap: calls proceed normally.
  - No API key: returns None, no exception.

All tests are deterministic and network-free — the Gemini client is fully
stubbed/monkeypatched.
"""

import time
import pytest

# ---- module under test -------------------------------------------------------
from backend.app.llm.analyst import (
    QuantAnalyst,
    LLMBudgetExceeded,
    LLM_CALL_TIMEOUT_SEC,
    get_spend_tracker,
    _SpendTracker,
)


# ---- helpers -----------------------------------------------------------------

def _make_analyst(fake_client, cap_usd: float = 20.0) -> QuantAnalyst:
    """Return a QuantAnalyst with *fake_client* already installed and a fresh
    Settings-like namespace so mutations don't bleed into the module singleton.

    We use a simple namespace object rather than get_settings() to avoid
    sharing the lru_cache'd Settings instance across tests.
    """
    from types import SimpleNamespace
    from backend.app.config import get_settings

    real = get_settings()
    settings = SimpleNamespace(
        gemini_model=real.gemini_model,
        llm_spend_cap_usd=cap_usd,
        has_llm_key=bool(real.gemini_api_key),
    )

    analyst = QuantAnalyst.__new__(QuantAnalyst)
    analyst.settings = settings
    analyst._client = fake_client
    return analyst


class _FakeResponse:
    """Minimal stand-in for a Gemini GenerateContentResponse."""
    def __init__(self, text: str = "fake llm response"):
        self.text = text


class _InstantClient:
    """Fake client whose generate_content returns immediately."""
    def __init__(self, text: str = "ok"):
        self._text = text
        self.models = self

    def generate_content(self, **kwargs):
        return _FakeResponse(self._text)


class _HangingClient:
    """Fake client that blocks for *delay* seconds — simulates a stalled
    Gemini endpoint."""
    def __init__(self, delay: float = 120.0):
        self._delay = delay
        self.models = self

    def generate_content(self, **kwargs):
        time.sleep(self._delay)
        return _FakeResponse("should never reach here")


class _ErrorClient:
    """Fake client that raises an exception."""
    def __init__(self, exc: Exception = RuntimeError("API error")):
        self._exc = exc
        self.models = self

    def generate_content(self, **kwargs):
        raise self._exc


# ---- fixtures ----------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_spend_tracker():
    """Reset the module-level spend tracker before every test so tests are
    fully independent of each other."""
    get_spend_tracker().reset()
    yield
    get_spend_tracker().reset()


# ---- timeout tests -----------------------------------------------------------

def test_hanging_call_returns_none_within_timeout(monkeypatch):
    """A stalled Gemini call must time out and return None, not hang forever.

    We use a SHORT test timeout (1 s) instead of the production 30 s so the
    test suite stays fast.  The module constant is monkeypatched just for
    this test.
    """
    TEST_TIMEOUT = 1.0  # seconds — fast for CI
    monkeypatch.setattr("backend.app.llm.analyst.LLM_CALL_TIMEOUT_SEC", TEST_TIMEOUT)

    analyst = _make_analyst(_HangingClient(delay=60.0))

    start = time.monotonic()
    result = analyst._call_llm("hello", max_tokens=10)
    elapsed = time.monotonic() - start

    assert result is None, "Expected None from a timed-out call"
    # Should return within 3× the test timeout (generous for slow CI)
    assert elapsed < TEST_TIMEOUT * 3, (
        f"Call took {elapsed:.2f}s — timeout not respected"
    )


def test_fast_call_returns_text():
    """A fast client should return the response text normally (not time out)."""
    analyst = _make_analyst(_InstantClient(text="analysis text"))
    result = analyst._call_llm("test prompt", max_tokens=100)
    assert result == "analysis text"


def test_api_error_returns_none():
    """When the client raises an exception, _call_llm returns None (not re-raised)."""
    analyst = _make_analyst(_ErrorClient())
    result = analyst._call_llm("test prompt", max_tokens=100)
    assert result is None


# ---- spend tracker unit tests ------------------------------------------------

def test_spend_tracker_accumulates():
    """Successive calls accumulate in the tracker."""
    tracker = _SpendTracker()
    cap = 100.0  # generous cap so nothing is blocked
    cost1 = tracker.estimate_cost("short prompt", 100)
    tracker.check_and_accrue(cost1, cap)
    cost2 = tracker.estimate_cost("another prompt", 200)
    tracker.check_and_accrue(cost2, cap)
    assert tracker.total_usd == pytest.approx(cost1 + cost2, rel=1e-6)


def test_spend_tracker_reset():
    """reset() brings cumulative spend back to zero."""
    tracker = _SpendTracker()
    tracker.check_and_accrue(0.01, 100.0)
    assert tracker.total_usd > 0
    tracker.reset()
    assert tracker.total_usd == 0.0


# ---- spend cap enforcement tests ---------------------------------------------

def test_spend_cap_blocks_when_exceeded():
    """Once cumulative cost exceeds the cap, the next call must raise
    LLMBudgetExceeded — not silently proceed."""
    # Use a very small cap so a single call easily exceeds it.
    cap = 0.000001  # one micro-dollar — any real call will exceed this

    analyst = _make_analyst(_InstantClient(), cap_usd=cap)

    # Any non-trivial prompt will produce an estimate that exceeds the cap
    with pytest.raises(LLMBudgetExceeded) as exc_info:
        analyst._call_llm("this prompt will tip the cap", max_tokens=100)

    assert "spend cap" in str(exc_info.value).lower(), (
        "Exception message should mention 'spend cap'"
    )


def test_spend_cap_accumulates_across_calls():
    """Each successful call accrues cost; eventually the cap is hit.

    Drive two calls through the same analyst with a cap sized so the first
    call fits but the second would push over the limit.
    """
    tracker = get_spend_tracker()
    assert tracker.total_usd == 0.0

    # Use a generous cap for the first call
    analyst = _make_analyst(_InstantClient(text="ok"), cap_usd=20.0)

    # First call succeeds
    result = analyst._call_llm("short", max_tokens=10)
    assert result == "ok"
    cost_after_first = tracker.total_usd
    assert cost_after_first > 0.0

    # Tighten the cap to exactly what we've spent: next call must be blocked
    analyst.settings.llm_spend_cap_usd = cost_after_first

    with pytest.raises(LLMBudgetExceeded):
        analyst._call_llm("second call should be blocked", max_tokens=10)


def test_under_cap_call_proceeds():
    """A call that fits within the cap should succeed and return a response."""
    # Explicit generous cap — no dependence on the shared Settings singleton
    analyst = _make_analyst(_InstantClient(text="good response"), cap_usd=20.0)
    result = analyst._call_llm("short prompt", max_tokens=50)
    assert result == "good response"
    # Tracker should have accrued something > 0
    assert get_spend_tracker().total_usd > 0


# ---- no-API-key path ---------------------------------------------------------

def test_no_api_key_returns_none_no_exception():
    """With no client (no API key configured), _call_llm must return None
    without raising anything — the template-fallback path must not be broken."""
    analyst = _make_analyst(None, cap_usd=20.0)
    result = analyst._call_llm("any prompt", max_tokens=100)
    assert result is None
    # No spend should have been accrued (budget check is skipped when no client)
    assert get_spend_tracker().total_usd == 0.0
