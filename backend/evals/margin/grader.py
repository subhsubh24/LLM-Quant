"""Genuine grader for the ``llmquant-signal-check`` eval.

Grades a model reply against a case's DERIVED ground truth. It never
always-passes:

  - An empty reply, or one without a parseable ``VERDICT`` line, FAILS.
  - A verdict outside {allocate, hold, pass} FAILS.
  - A confidence that is missing or outside [0, 1] FAILS.
  - For a case with a correct direction (ground_truth), a verdict OUTSIDE the
    acceptable set FAILS.
  - For an ambiguous case (no correct direction), any well-formed + coherent
    verdict passes on VALIDITY, graded with method ``judge_proxy`` (never claimed
    as ground_truth) — but a malformed/incoherent one still FAILS.

``quality_score`` (0..1) is a graded number, not a self-report: 0 for invalid,
low for a well-formed-but-wrong-direction call, high for a correct/coherent one,
scaled by confidence coherence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .cases import Case, GroundTruth, ground_truth

VALID_VERDICTS = ("allocate", "hold", "pass")

# The Margin ingest API accepts ONLY these quality_method provenance labels
# (mirrors src/margin ingest `_ALLOWED_QUALITY_METHODS`). An outcome that names
# any other method (e.g. "rubric" or "heuristic") is rejected with 422 and never
# lands — which zeroes out cost-per-outcome. Every grader in this package MUST
# emit one of these; `margin_eval --self-test` enforces it so the bug can't recur.
INGEST_ACCEPTED_QUALITY_METHODS = frozenset(
    {"ground_truth", "llm_judge", "judge_proxy", "self_report"}
)

_VERDICT_RE = re.compile(r"verdict\s*[:\-]?\s*(allocate|hold|pass)", re.IGNORECASE)
_CONF_RE = re.compile(r"confidence\s*[:\-]?\s*([01](?:\.\d+)?|\.\d+|\d\.\d+)", re.IGNORECASE)


@dataclass
class GradeResult:
    case_id: str
    passed: bool
    quality_score: float
    quality_method: str          # "ground_truth" | "judge_proxy" (ingest-accepted)
    verdict: Optional[str]
    confidence: Optional[float]
    expected: Optional[str]       # printable acceptable-set / "-" for ambiguous
    reason: str


def parse_verdict(text: str) -> Optional[str]:
    """Extract the LAST verdict token from the reply (the model's final call)."""
    if not text:
        return None
    matches = _VERDICT_RE.findall(text)
    if not matches:
        return None
    return matches[-1].lower()


def parse_confidence(text: str) -> Optional[float]:
    """Extract the LAST confidence value; None if absent/unparseable/out of range."""
    if not text:
        return None
    matches = _CONF_RE.findall(text)
    if not matches:
        return None
    try:
        val = float(matches[-1])
    except (TypeError, ValueError):
        return None
    if 0.0 <= val <= 1.0:
        return val
    return None


def _coherence(verdict: str, confidence: float) -> float:
    """How internally coherent is (verdict, confidence)? 0..1.

    A conviction verdict (allocate) with near-zero confidence is incoherent; a
    'pass' asserted with extreme confidence is fine. This is a soft signal that
    only scales quality — it does not, on its own, flip a correct-direction pass.
    """
    if verdict == "allocate":
        # Allocating requires conviction; reward higher confidence.
        return max(0.0, min(1.0, confidence))
    if verdict == "hold":
        # Holding is a middling stance; mid confidence is most coherent.
        return 1.0 - abs(confidence - 0.5) * 2.0 * 0.5  # gentle penalty away from 0.5
    # pass
    return 1.0  # passing is always internally coherent


def grade(case: Case, text: Optional[str]) -> GradeResult:
    """Grade one model reply for one case. Returns a GradeResult."""
    gt: GroundTruth = ground_truth(case)
    method = gt.method
    expected_str = "-" if gt.acceptable is None else "/".join(sorted(gt.acceptable))

    verdict = parse_verdict(text or "")
    confidence = parse_confidence(text or "")

    # --- Validity gate (applies to every case) ---
    if verdict is None or verdict not in VALID_VERDICTS:
        return GradeResult(case.id, False, 0.0, method, verdict, confidence,
                           expected_str, "no valid VERDICT line")
    if confidence is None:
        return GradeResult(case.id, False, 0.0, method, verdict, confidence,
                           expected_str, "missing/invalid CONFIDENCE (need 0..1)")

    coherence = _coherence(verdict, confidence)

    # --- Ambiguous case: validity + coherence only, no direction claim ---
    if gt.acceptable is None:
        # Require minimal coherence so this is not an always-pass.
        passed = coherence >= 0.25
        score = round(0.55 + 0.45 * coherence, 3) if passed else round(0.2 * coherence, 3)
        reason = "ambiguous: well-formed + coherent" if passed else \
            "ambiguous: incoherent verdict/confidence"
        return GradeResult(case.id, passed, score, "judge_proxy", verdict,
                           confidence, expected_str, reason)

    # --- Directional (ground-truth) case ---
    correct = verdict in gt.acceptable
    if correct:
        # Full marks for the primary verdict; partial for an acceptable alt.
        base = 0.85 if verdict == gt.primary else 0.7
        score = round(min(1.0, base + 0.15 * coherence), 3)
        return GradeResult(case.id, True, score, "ground_truth", verdict,
                           confidence, expected_str,
                           f"correct ({verdict} in {{{expected_str}}})")
    # Wrong direction: well-formed but economically wrong -> FAIL, low score.
    score = round(0.15 * coherence, 3)
    return GradeResult(case.id, False, score, "ground_truth", verdict,
                       confidence, expected_str,
                       f"wrong: {verdict} not in {{{expected_str}}} — {gt.rationale}")
