"""Eval-suite registry: one entry per metered AI workflow.

A Suite bundles everything the runner needs to evaluate one workflow:
  - ``workflow_id``  : the Margin workflow id emitted for its calls/outcomes.
  - ``cases``        : the input matrix.
  - ``bucket_of``    : a descriptive bucket for reporting.
  - ``invoke``       : run the case through the REAL metered analyst path and
                       return the model's text (the runner captures tokens via
                       the wrapped client and suppresses the inline emit).
  - ``grade``        : genuine grading -> GradeResult.
  - ``selftest``     : offline (no Gemini/network) assertions proving the grader
                       is not always-pass.

Adding a workflow = adding a Suite here; the runner iterates the registry.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Callable, Dict, List

from . import analyst_cases, analyst_graders, cases as signal_cases
from .grader import GradeResult, grade as signal_grade


@dataclass
class Suite:
    key: str
    workflow_id: str
    description: str
    cases: List[Any]
    bucket_of: Callable[[Any], str]
    invoke: Callable[[Any, Any], str]     # (analyst, case) -> model text
    grade: Callable[[Any, str], GradeResult]
    selftest: Callable[[], List[str]]     # returns list of failure strings


def _run(coro: Any) -> Any:
    """Run a coroutine to completion on a fresh loop (eval scale)."""
    return asyncio.new_event_loop().run_until_complete(coro)


def _text_from(result: Any, *keys: str) -> str:
    """Pull the text field out of an analyst method's return (dict or str)."""
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        for k in keys:
            if result.get(k):
                return str(result[k])
    return ""


# --------------------------------------------------------------------------- #
# Suite 1: signal-check (existing) — wraps cases.py + grader.py
# --------------------------------------------------------------------------- #
def _signal_invoke(analyst: Any, case: Any) -> str:
    return analyst._call_llm(signal_cases.build_signal_prompt(case), max_tokens=400) or ""


def _signal_selftest() -> List[str]:
    fails: List[str] = []
    directional = next(c for c in signal_cases.ALL_CASES
                       if signal_cases.ground_truth(c).acceptable is not None)
    ok = signal_grade(directional, "VERDICT: %s\nCONFIDENCE: 0.7"
                      % sorted(signal_cases.ground_truth(directional).acceptable)[0])
    if not ok.passed:
        fails.append("signal: correct verdict should pass")
    if signal_grade(directional, "").passed:
        fails.append("signal: empty should fail")
    return fails


# --------------------------------------------------------------------------- #
# Suites 2-4: advisory analyst workflows (rubric-graded)
# --------------------------------------------------------------------------- #
def _stock_invoke(analyst: Any, case: Any) -> str:
    p = case.payload
    res = _run(analyst.analyze_stock(p["symbol"], p["quote"], news=p.get("news")))
    return _text_from(res, "analysis")


def _portfolio_invoke(analyst: Any, case: Any) -> str:
    p = case.payload
    res = _run(analyst.analyze_portfolio(p["positions"], p["total_value"]))
    return _text_from(res, "analysis")


def _critique_invoke(analyst: Any, case: Any) -> str:
    p = case.payload
    res = _run(analyst.critique_strategy(p["strategy_description"],
                                         backtest_results=p.get("backtest_results")))
    return _text_from(res, "critique")


def _good_stock_reply(sym: str) -> str:
    return (f"## {sym} Analysis\n"
            "Technical Setup: price is holding support with improving momentum and a clear trend; "
            "watch the breakout level.\n"
            "Quant Factors: scores well on momentum and quality, moderate volatility and beta.\n"
            "Risk Assessment: main risk is a drawdown if momentum fades; size the position "
            "with a stop below support to cap downside exposure.\n"
            "Trading Ideas: consider an entry near support with an exit/target into resistance.\n"
            "For Learning: this name illustrates the momentum factor concept well.")


def _good_portfolio_reply(ticker: str) -> str:
    return (f"Portfolio review (incl. {ticker}).\n"
            "Concentration Risk: the book is over-weight a single name; diversification is thin.\n"
            "Factor Exposures: heavy momentum and growth factor exposure, high beta.\n"
            "Sector Tilts: concentrated sector/industry correlation.\n"
            "Risk Assessment: a drawdown in the top holding would hurt the portfolio.\n"
            "Suggested Adjustments: rebalance and trim the largest position; add a hedge.\n"
            "Learning Moment: position sizing and allocation discipline matter.")


def _good_critique_reply() -> str:
    return ("Red Flags: several concerns here.\n"
            "Hidden Risks: this could blow up in a regime change; tail risk is understated.\n"
            "Data Issues: likely overfitting and in-sample data mining with such a small sample; "
            "watch for look-ahead leakage and survivorship bias.\n"
            "Implementation: transaction costs, slippage, commission and capacity/liquidity are "
            "ignored and will erode the edge.\n"
            "Improvements: test out-of-sample with walk-forward validation and more data to be robust.\n"
            "Verdict: I would not allocate capital until it survives out-of-sample.")


def _rubric_selftest(workflow: str, good: str, must_token: str) -> List[str]:
    fails: List[str] = []
    cs = analyst_cases.ANALYST_CASES[workflow]
    normal = next(c for c in cs if c.bucket == "normal")
    # A good, on-task reply (grounded with the required mention) passes.
    grounded = good
    for m in normal.must_mention:
        if m.lower() not in grounded.lower():
            grounded = f"{m}: " + grounded
    g_ok = analyst_graders.rubric_grade(normal, grounded)
    if not (g_ok.passed and g_ok.quality_method == "judge_proxy"):
        fails.append(f"{workflow}: good reply should pass ({g_ok.reason})")
    # Empty and refusal must fail.
    if analyst_graders.rubric_grade(normal, "").passed:
        fails.append(f"{workflow}: empty should fail")
    if analyst_graders.rubric_grade(normal, "I cannot help with that.").passed:
        fails.append(f"{workflow}: refusal should fail")
    # An on-topic reply that ignores the required mention must fail (if any).
    if normal.must_mention:
        no_mention = good.replace(normal.must_mention[0], "the name").replace(
            normal.must_mention[0].lower(), "the name")
        if analyst_graders.rubric_grade(normal, no_mention).passed:
            fails.append(f"{workflow}: reply ignoring required mention should fail")
    # A flawed critique that misses the built-in flaw must fail.
    if workflow == "critique_strategy":
        flaw = next((c for c in cs if c.expected_flags), None)
        if flaw is not None:
            weak = ("This looks fine to me. Nice trend. I would allocate. "
                    "Momentum is good and the chart looks clean. " * 4)
            if analyst_graders.rubric_grade(flaw, weak).passed:
                fails.append("critique: missing an obvious flaw should fail")
    return fails


def _build_registry() -> Dict[str, Suite]:
    reg: Dict[str, Suite] = {}

    reg["signal-check"] = Suite(
        key="signal-check", workflow_id="llmquant-signal-check",
        description="prediction-market entry decision (allocate/hold/pass)",
        cases=signal_cases.ALL_CASES,
        bucket_of=signal_cases.bucket_of,
        invoke=_signal_invoke, grade=signal_grade, selftest=_signal_selftest,
    )
    reg["analyze-stock"] = Suite(
        key="analyze-stock", workflow_id="llmquant-analyze-stock",
        description="single-name stock analysis (advisory)",
        cases=analyst_cases.STOCK_CASES,
        bucket_of=lambda c: c.bucket,
        invoke=_stock_invoke,
        grade=analyst_graders.rubric_grade,
        selftest=lambda: _rubric_selftest("analyze_stock", _good_stock_reply("AAPL"), "AAPL"),
    )
    reg["analyze-portfolio"] = Suite(
        key="analyze-portfolio", workflow_id="llmquant-analyze-portfolio",
        description="portfolio concentration/factor/risk analysis (advisory)",
        cases=analyst_cases.PORTFOLIO_CASES,
        bucket_of=lambda c: c.bucket,
        invoke=_portfolio_invoke,
        grade=analyst_graders.rubric_grade,
        selftest=lambda: _rubric_selftest("analyze_portfolio", _good_portfolio_reply("AAPL"), "AAPL"),
    )
    reg["critique-strategy"] = Suite(
        key="critique-strategy", workflow_id="llmquant-critique-strategy",
        description="ruthless strategy critique (advisory)",
        cases=analyst_cases.CRITIQUE_CASES,
        bucket_of=lambda c: c.bucket,
        invoke=_critique_invoke,
        grade=analyst_graders.rubric_grade,
        selftest=lambda: _rubric_selftest("critique_strategy", _good_critique_reply(), ""),
    )
    return reg


SUITES: Dict[str, Suite] = _build_registry()
SUITE_KEYS: List[str] = list(SUITES.keys())
