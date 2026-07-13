"""Genuine RUBRIC graders for the advisory analyst workflows.

These tasks have no market ground truth, so we grade genuine TASK COMPLETION,
never "always-pass":

  - A refusal / empty / too-short reply FAILS.
  - A reply that ignores the input (doesn't mention the required symbol/ticker)
    FAILS.
  - A reply that covers too few of the task's required topic areas FAILS.
  - For critique_strategy, a reply that MISSES an obvious flaw the scenario was
    built to contain (``expected_flags``) FAILS — that is a genuine, assertive
    check, not a structural rubber-stamp.

``quality_method`` is ``judge_proxy`` — Margin's provenance label for a bounded,
deterministic answer-quality proxy (NOT an LLM judge, NOT ground truth). This is
the honest, server-accepted label for a rubric grader: the ingest API only
accepts {ground_truth, llm_judge, judge_proxy, self_report}, so an outcome
labeled ``rubric`` is rejected (422) and never lands. ``quality_score`` is graded
from coverage + input-grounding + flaw-catching.
"""

from __future__ import annotations

from typing import Dict, List

from .analyst_cases import AnalystCase
from .grader import GradeResult

# Topic areas each workflow's output should cover (any synonym counts).
STOCK_TOPICS: Dict[str, List[str]] = {
    "technical": ["support", "resistance", "trend", "momentum", "moving average",
                  "level", "breakout", "rsi", "macd", "chart"],
    "quant": ["momentum", "value", "quality", "volatility", "factor", "beta", "sharpe"],
    "risk": ["risk", "drawdown", "position siz", "stop", "downside", "exposure", "volatil"],
    "trading": ["entry", "exit", "target", "stop-loss", "stop loss", "buy", "sell", "accumulate"],
    "learning": ["concept", "learn", "illustrat", "teach", "example"],
}
PORTFOLIO_TOPICS: Dict[str, List[str]] = {
    "concentration": ["concentrat", "diversif", "overweight", "weight", "single name",
                      "single-name"],
    "factor": ["factor", "exposure", "beta", "momentum", "value", "quality", "growth"],
    "sector": ["sector", "industry", "correlat"],
    "risk": ["risk", "drawdown", "hurt", "downside", "volatil", "tail"],
    "rebalance": ["rebalanc", "adjust", "trim", "add", "reduce", "recommend", "hedge"],
    "sizing": ["position siz", "sizing", "allocation", "size"],
}
CRITIQUE_TOPICS: Dict[str, List[str]] = {
    "redflag": ["red flag", "concern", "problem", "issue", "weak", "caution"],
    "risk": ["risk", "blow up", "blow-up", "drawdown", "tail", "loss", "ruin"],
    "bias": ["leakage", "look-ahead", "lookahead", "survivorship", "overfit", "over-fit",
             "snoop", "in-sample", "in sample", "data mining", "data-mining", "curve fit",
             "curve-fit", "sample size", "small sample", "p-hack"],
    "cost": ["transaction cost", "slippage", "commission", "capacity", "liquidity",
             "fees", "fill", "impact"],
    "improve": ["improve", "robust", "out-of-sample", "out of sample", "walk-forward",
                "walk forward", "cross-valid", "cross valid", "regulariz", "more data"],
    "verdict": ["verdict", "allocate", "would not", "wouldn't", "would i", "recommend",
                "pass on", "deploy", "capital"],
}

_TOPICS_BY_WORKFLOW = {
    "analyze_stock": STOCK_TOPICS,
    "analyze_portfolio": PORTFOLIO_TOPICS,
    "critique_strategy": CRITIQUE_TOPICS,
}

_REFUSAL_MARKERS = (
    "i cannot help", "i can't help", "i cannot assist", "i can't assist",
    "as an ai language model", "i'm unable to", "i am unable to",
    "i cannot provide", "i can't provide",
)

# Minimum body length (chars) — a real analysis is long; this floors out
# empties, refusals and one-liners without over-fitting to length.
_MIN_CHARS = 200


def _covered_topics(text_l: str, topics: Dict[str, List[str]]) -> List[str]:
    hit = []
    for key, syns in topics.items():
        if any(s in text_l for s in syns):
            hit.append(key)
    return hit


def _is_refusal(text_l: str) -> bool:
    return any(m in text_l for m in _REFUSAL_MARKERS)


def rubric_grade(case: AnalystCase, text: str) -> GradeResult:
    """Grade one advisory reply for one case. quality_method='judge_proxy'."""
    topics = _TOPICS_BY_WORKFLOW[case.workflow]
    # Normal cases must cover >=3 topic areas; edge/fuzz relax to >=2 (degenerate
    # inputs legitimately yield thinner analysis) but STILL must be valid + on-task.
    required = 3 if case.bucket == "normal" else 2

    body = (text or "").strip()
    text_l = body.lower()

    # --- Validity gate ---
    if not body or len(body) < _MIN_CHARS:
        return GradeResult(case.id, False, 0.0, "judge_proxy", None, None,
                           f">={required}topics", f"empty/too-short ({len(body)}<{_MIN_CHARS} chars)")
    if _is_refusal(text_l):
        return GradeResult(case.id, False, 0.0, "judge_proxy", None, None,
                           f">={required}topics", "refusal / non-answer")

    # --- Input grounding: required mentions must appear ---
    missing = [m for m in case.must_mention if m.lower() not in text_l]
    if missing:
        return GradeResult(case.id, False, 0.1, "judge_proxy", None, None,
                           f">={required}topics",
                           f"ignores input (missing mention: {missing})")

    # --- Topic coverage ---
    covered = _covered_topics(text_l, topics)
    coverage_ok = len(covered) >= required

    # --- Obvious-flaw catching (critique) — assertive, not structural ---
    missed_flags = [f for f in case.expected_flags if f not in covered]
    if case.expected_flags and missed_flags:
        # Built-in flaw not caught -> genuine failure.
        score = round(0.2 + 0.1 * (len(covered) / max(1, len(topics))), 3)
        return GradeResult(case.id, False, score, "judge_proxy", None, None,
                           "flags:" + ",".join(case.expected_flags),
                           f"missed obvious flaw(s): {missed_flags}")

    if not coverage_ok:
        score = round(0.2 + 0.4 * (len(covered) / required), 3)
        return GradeResult(case.id, False, score, "judge_proxy", None, None,
                           f">={required}topics",
                           f"thin: covered {len(covered)}/{required} topics ({covered})")

    # --- Passed: score by coverage breadth (+ flaw catching credit) ---
    breadth = min(1.0, len(covered) / len(topics))
    score = round(0.6 + 0.4 * breadth, 3)
    exp = ("flags:" + ",".join(case.expected_flags)) if case.expected_flags \
        else f">={required}topics"
    return GradeResult(case.id, True, score, "judge_proxy", None, None, exp,
                       f"on-task: covered {covered}")
