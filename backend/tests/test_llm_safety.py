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
from app.llm.analyst import (
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
    from app.config import get_settings

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
    monkeypatch.setattr("app.llm.analyst.LLM_CALL_TIMEOUT_SEC", TEST_TIMEOUT)

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


# ---- Margin cost-per-outcome telemetry (#310/#312) ---------------------------
# The Margin economics meter emits cost-per-outcome telemetry AFTER each Gemini
# call. It MUST be a BLOCKING call in the same synchronous flow as the request —
# NOT a fire-and-forget daemon thread — because on serverless (Render) the
# function is frozen the instant it returns, which kills a background thread
# before its POST completes and drops every emit (the #312 regression). And it
# MUST degrade safely: the meter package is absent in the CI/default env
# (not in requirements-ci.txt), so the call path must still return the model
# text with no error. These tests validate the `cost_telemetry` capability
# declared in docs/ci/SELF_VALIDATION.md.


def test_margin_meter_emits_blocking_in_the_call_flow(monkeypatch):
    """Regression (#312): the Margin emit runs BLOCKING, in the SAME thread as the
    Gemini request — proving it is synchronous, not a fire-and-forget daemon thread the
    serverless freeze would drop. With margin_meter present, record_call + record_outcome
    must have fired by the time _call_llm returns, in generate_content's own thread."""
    import sys
    import threading
    import types

    seen = {"gen": None, "record_call": None, "record_outcome": None}

    class _Usage:
        prompt_token_count = 100
        candidates_token_count = 20
        cached_content_token_count = 0

    class _Resp:
        text = "analysis text"
        usage_metadata = _Usage()

    class _Client:
        def __init__(self):
            self.models = self

        def generate_content(self, **kwargs):
            seen["gen"] = threading.get_ident()
            return _Resp()

    class _FakeMeter:
        def __init__(self, timeout=2.0):
            pass

        def record_call(self, **kwargs):
            seen["record_call"] = threading.get_ident()

        def record_outcome(self, **kwargs):
            seen["record_outcome"] = threading.get_ident()

    fake_mod = types.ModuleType("margin_meter")
    fake_mod.MarginMeter = _FakeMeter
    monkeypatch.setitem(sys.modules, "margin_meter", fake_mod)

    analyst = _make_analyst(_Client(), cap_usd=20.0)
    result = analyst._call_llm("prompt", max_tokens=50)

    assert result == "analysis text"
    # The emit MUST have completed by the time _call_llm returned (blocking)...
    assert seen["record_call"] is not None, "record_call must fire (blocking) within the call"
    assert seen["record_outcome"] is not None, "record_outcome must fire (blocking) within the call"
    # ...and in the SAME thread as the Gemini request — a fire-and-forget daemon thread
    # (the #312 regression) would run the emit in a DIFFERENT thread (or not yet at all).
    assert seen["record_call"] == seen["gen"], "emit must be synchronous with the request, not a background thread"
    assert seen["record_outcome"] == seen["gen"]


def test_margin_meter_absent_degrades_safely(monkeypatch):
    """The cost_telemetry capability degrades safely: when margin_meter is NOT importable
    (the CI/default env — it is not in requirements-ci.txt), _call_llm still returns the
    model text with no error and simply skips the emit."""
    import sys

    # A None entry in sys.modules makes `from margin_meter import MarginMeter` raise
    # ImportError — modeling the package being absent, exactly as in CI.
    monkeypatch.setitem(sys.modules, "margin_meter", None)

    class _Resp:
        text = "ok"

    class _Client:
        def __init__(self):
            self.models = self

        def generate_content(self, **kwargs):
            return _Resp()

    analyst = _make_analyst(_Client(), cap_usd=20.0)
    assert analyst._call_llm("p", max_tokens=10) == "ok"


# -----------------------------------------------------------------------------
# Journey instrumentation: per-operation labels + shared session_id chaining.
#
# Every step of the AI user-journey (signal-check -> analyze-stock /
# analyze-portfolio -> critique-strategy, plus every other advisory op) must
# emit its OWN descriptive Margin ``operation`` (workflow_id), and steps run
# inside one ``journey_session`` must all carry the SAME ``session_id`` so
# Margin's supply-chain graph reconstructs the multi-step chain.
# -----------------------------------------------------------------------------


def _recording_meter_module():
    """Return a fake ``margin_meter`` module whose meter records every emit."""
    import types

    records = []  # list of record_call kwargs

    class _Meter:
        def __init__(self, timeout=2.0):
            pass

        def record_call(self, **kwargs):
            records.append(kwargs)

        def record_outcome(self, **kwargs):
            records.append({"_outcome": True, **kwargs})

    mod = types.ModuleType("margin_meter")
    mod.MarginMeter = _Meter
    return mod, records


def _capturing_analyst():
    class _Usage:
        prompt_token_count = 10
        candidates_token_count = 5
        cached_content_token_count = 0

    class _Resp:
        text = "some analysis text"
        usage_metadata = _Usage()

    class _Client:
        def __init__(self):
            self.models = self

        def generate_content(self, **kwargs):
            return _Resp()

    return _make_analyst(_Client(), cap_usd=100.0)


def test_each_operation_emits_its_own_workflow_id(monkeypatch):
    """A distinct ``operation`` per call flows through to the meter's workflow_id
    instead of the old hardcoded ``llmquant-signal-check`` for everything."""
    import sys
    import asyncio

    mod, records = _recording_meter_module()
    monkeypatch.setitem(sys.modules, "margin_meter", mod)
    analyst = _capturing_analyst()

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(analyst.analyze_stock("AAPL", {"price": 1.0}))
        loop.run_until_complete(
            analyst.analyze_portfolio([{"ticker": "AAPL"}], 1000.0)
        )
        loop.run_until_complete(analyst.critique_strategy("buy low sell high"))
        # signal-check path calls _call_llm directly with the default operation.
        analyst._call_llm("signal prompt", max_tokens=400)
    finally:
        loop.close()

    call_workflows = [r["workflow_id"] for r in records if "_outcome" not in r]
    assert "llmquant-analyze-stock" in call_workflows
    assert "llmquant-analyze-portfolio" in call_workflows
    assert "llmquant-critique-strategy" in call_workflows
    assert "llmquant-signal-check" in call_workflows
    # Each of the four steps is its own node — not one collapsed workflow.
    assert len(set(call_workflows)) >= 4


def test_journey_session_links_steps_into_one_chain(monkeypatch):
    """Steps run inside one ``journey_session`` share a single ``session_id`` so
    the chain links; each keeps its own ``operation`` label."""
    import sys
    import asyncio
    from app.llm.analyst import journey_session

    mod, records = _recording_meter_module()
    monkeypatch.setitem(sys.modules, "margin_meter", mod)
    analyst = _capturing_analyst()

    loop = asyncio.new_event_loop()
    try:
        with journey_session() as sid:
            loop.run_until_complete(analyst.analyze_stock("AAPL", {"price": 1.0}))
            loop.run_until_complete(
                analyst.analyze_portfolio([{"ticker": "AAPL"}], 1000.0)
            )
            loop.run_until_complete(analyst.critique_strategy("momentum"))
    finally:
        loop.close()

    calls = [r for r in records if "_outcome" not in r]
    session_ids = {r["session_id"] for r in calls}
    assert session_ids == {sid}, "all steps in one journey share the session_id"
    # ...yet remain distinct operations (a multi-node chain, not one node).
    assert len({r["workflow_id"] for r in calls}) == 3


def test_standalone_calls_get_independent_sessions(monkeypatch):
    """Outside a journey, two separate calls do NOT share a session id (they are
    independent runs, not a single chain)."""
    import sys

    mod, records = _recording_meter_module()
    monkeypatch.setitem(sys.modules, "margin_meter", mod)
    analyst = _capturing_analyst()

    analyst._call_llm("p1", max_tokens=50, operation="llmquant-signal-check")
    analyst._call_llm("p2", max_tokens=50, operation="llmquant-signal-check")

    calls = [r for r in records if "_outcome" not in r]
    session_ids = [r["session_id"] for r in calls]
    assert len(session_ids) == 2
    assert session_ids[0] != session_ids[1]
