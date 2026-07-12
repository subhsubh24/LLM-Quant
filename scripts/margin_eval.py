#!/usr/bin/env python3
"""
margin_eval.py — repo-specific eval runner for Margin cost-per-outcome.

Runs the ``llmquant-signal-check`` workflow across a representative matrix of
prediction-market scenarios (see ``backend/evals/margin/cases.py``), grades each
reply genuinely (``backend/evals/margin/grader.py``), and emits the measured
economics + GRADED outcomes to Margin via the published ``margin-meter`` SDK.
This gives Margin an accurate STATISTICAL cost-per-outcome for the workflow —
not just "did the model return text".

It exercises the REAL metered path: each case is sent through the production
``QuantAnalyst._call_llm`` (same Gemini client, model, system prompt, spend cap
and timeout). During that call the analyst's own inline emit is suppressed (by
hiding MARGIN_INGEST_KEY from the env for the duration) so this runner is the
SINGLE authoritative emitter — the graded outcome is the one that counts, and
call cost is never double-counted. The full response is captured so real token
counts and latency are metered.

SAFETY / GUARDS
  - NO real Gemini in the keyless CI gate: this is an ON-DEMAND / scheduled tool.
    With no Gemini key it prints a skip and exits 0. It is NOT wired into
    scripts/preflight.sh. Use ``--self-test`` for an offline (no-network,
    no-Gemini) check of the harness itself, safe to run anywhere.
  - Hermetic in CI: if ``CI`` is set the runner NEVER emits (the keyless gate
    must stay inert even if creds leak into its env). The dedicated margin-eval
    workflow clears ``CI`` (``env: CI: ""``) on its secrets-backed step so an
    intended run emits; ``--allow-ci-emit`` forces emit in a local CI-like shell.
  - Fail-safe emit: if MARGIN_INGEST_URL/KEY are unset it still runs + grades and
    prints the summary, just without emitting.
  - Cost-capped: stops the batch once measured spend crosses ``--max-cost-usd``;
    also honors the analyst's own ``llm_spend_cap_usd``.

USAGE
  # Offline self-test of the grader + matrix (no key, no network) — CI-safe:
  python3 scripts/margin_eval.py --self-test

  # List the matrix without calling anything:
  python3 scripts/margin_eval.py --list

  # Real run (needs GEMINI_API_KEY; emits if MARGIN_INGEST_URL/KEY set):
  GEMINI_API_KEY=... MARGIN_INGEST_URL=... MARGIN_INGEST_KEY=mgk_... \
      python3 scripts/margin_eval.py --run-id 2026-07-12a

  # Re-run with a model/config override (re-runnable comparison):
  python3 scripts/margin_eval.py --model gemini-2.5-pro --limit 20 --max-cost-usd 0.50

Env: GEMINI_API_KEY (Gemini), MARGIN_INGEST_URL + MARGIN_INGEST_KEY (Margin).
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from contextlib import contextmanager
from typing import Any, Dict, List

# Make `backend` importable whether run from repo root or backend/.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))

from backend.evals.margin.cases import (  # noqa: E402
    ALL_CASES,
    Case,
    bucket_of,
    build_signal_prompt,
    ground_truth,
)
from backend.evals.margin.grader import GradeResult, grade  # noqa: E402

WORKFLOW_ID = "llmquant-signal-check"


# --------------------------------------------------------------------------- #
# Response capture: run the REAL analyst path but grab the full response object
# (with usage_metadata) so we can meter real tokens. Non-invasive: we wrap the
# already-built Gemini client on the analyst instance; we never edit app code.
# --------------------------------------------------------------------------- #
class _CaptureModels:
    def __init__(self, real_models: Any, holder: Dict[str, Any]) -> None:
        self._real = real_models
        self._holder = holder

    def generate_content(self, **kwargs: Any) -> Any:
        resp = self._real.generate_content(**kwargs)
        self._holder["response"] = resp
        return resp


class _CaptureClient:
    def __init__(self, real_client: Any, holder: Dict[str, Any]) -> None:
        self._real = real_client
        self.models = _CaptureModels(real_client.models, holder)

    def __getattr__(self, name: str) -> Any:  # pragma: no cover - passthrough
        return getattr(self._real, name)


@contextmanager
def _suppressed_inline_emit():
    """Hide MARGIN_INGEST_KEY/URL so the analyst's inline meter no-ops.

    The runner captured the real values already and emits itself; this prevents
    double-counting the call/outcome during the ``_call_llm`` invocation.
    """
    saved = {k: os.environ.pop(k, None) for k in ("MARGIN_INGEST_KEY", "MARGIN_INGEST_URL")}
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v


def _usage(response: Any) -> Dict[str, int]:
    um = getattr(response, "usage_metadata", None)
    if um is None:
        return {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0}
    return {
        "input_tokens": int(getattr(um, "prompt_token_count", 0) or 0),
        "output_tokens": int(getattr(um, "candidates_token_count", 0) or 0),
        "cache_read_tokens": int(getattr(um, "cached_content_token_count", 0) or 0),
    }


# --------------------------------------------------------------------------- #
# Offline self-test — validates the harness with ZERO network/Gemini.
# --------------------------------------------------------------------------- #
def self_test() -> int:
    """Prove the grader is genuine (never always-pass) against canned replies."""
    failures: List[str] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        if not cond:
            failures.append(f"{name}: {detail}")

    by_bucket: Dict[str, List[Case]] = {}
    for c in ALL_CASES:
        by_bucket.setdefault(bucket_of(c), []).append(c)

    # Need genuine spread across the outcome spectrum.
    check("matrix-size", len(ALL_CASES) >= 40, f"only {len(ALL_CASES)} cases")
    for b in ("clear_edge", "no_edge_or_overpriced", "thin_liquidity", "ambiguous"):
        check(f"bucket:{b}", len(by_bucket.get(b, [])) >= 3,
              f"{len(by_bucket.get(b, []))} cases")

    # Pick one directional case and one ambiguous case.
    directional = next(c for c in ALL_CASES if ground_truth(c).acceptable is not None)
    correct_verdict = sorted(ground_truth(directional).acceptable)[0]
    wrong_pool = [v for v in ("allocate", "hold", "pass")
                  if v not in ground_truth(directional).acceptable]

    def reply(v: str, conf: float = 0.7) -> str:
        return f"Reasoning...\nVERDICT: {v}\nCONFIDENCE: {conf:.2f}"

    # 1) Empty / malformed replies MUST fail (not always-pass).
    check("empty-fails", not grade(directional, "").passed, "empty passed")
    check("none-fails", not grade(directional, None).passed, "None passed")
    check("noverdict-fails", not grade(directional, "I think allocate maybe").passed,
          "unparseable passed")
    check("noconf-fails", not grade(directional, "VERDICT: allocate").passed,
          "missing confidence passed")
    check("badconf-fails", not grade(directional, "VERDICT: allocate\nCONFIDENCE: 5").passed,
          "out-of-range confidence passed")

    # 2) Correct direction passes; wrong direction fails.
    g_ok = grade(directional, reply(correct_verdict))
    check("correct-passes", g_ok.passed and g_ok.quality_method == "ground_truth",
          f"correct verdict scored {g_ok}")
    if wrong_pool:
        g_bad = grade(directional, reply(wrong_pool[0]))
        check("wrong-fails", not g_bad.passed, f"wrong verdict passed: {g_bad}")

    # 3) Ambiguous: a well-formed coherent reply passes as heuristic (not GT).
    amb = next(c for c in ALL_CASES if ground_truth(c).acceptable is None)
    g_amb = grade(amb, reply("hold", 0.5))
    check("ambiguous-passes", g_amb.passed and g_amb.quality_method == "heuristic",
          f"ambiguous well-formed failed: {g_amb}")
    g_amb_bad = grade(amb, "totally unparseable")
    check("ambiguous-malformed-fails", not g_amb_bad.passed,
          "ambiguous malformed passed")

    # 4) Not always-pass overall: at least one canned wrong reply fails.
    if failures:
        print("SELF-TEST FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"SELF-TEST PASSED — {len(ALL_CASES)} cases; grader is genuine "
          f"(empty/malformed/wrong-direction all fail; correct/ambiguous grade sensibly).")
    return 0


# --------------------------------------------------------------------------- #
# Real run
# --------------------------------------------------------------------------- #
def run(args: argparse.Namespace) -> int:
    # Lazy imports so --self-test / --list never need the app or SDK.
    from backend.app.config import get_settings
    from backend.app.llm.analyst import QuantAnalyst, get_spend_tracker

    settings = get_settings()
    if args.model:
        try:
            settings.gemini_model = args.model
        except Exception:
            object.__setattr__(settings, "gemini_model", args.model)

    if not settings.has_llm_key:
        print("margin_eval: no GEMINI_API_KEY configured — nothing to meter. "
              "Skipping (fail-safe, exit 0). Set GEMINI_API_KEY to run for real.")
        return 0

    analyst = QuantAnalyst()
    client = analyst._get_client()
    if client is None:
        print("margin_eval: Gemini client unavailable (import/init failed) — "
              "skipping (fail-safe, exit 0).")
        return 0

    # Wrap the client so we can capture the full response for token metering.
    holder: Dict[str, Any] = {}
    analyst._client = _CaptureClient(client, holder)

    # --- Margin meter (fail-safe) ---
    run_id = args.run_id or time.strftime("%Y%m%dT%H%M%S")
    session_id = f"eval:{run_id}"
    ingest_url = args.ingest_url or os.environ.get("MARGIN_INGEST_URL")
    ingest_key = args.ingest_key or os.environ.get("MARGIN_INGEST_KEY")
    # HERMETIC GUARD: never emit real telemetry from a CI context. A keyless
    # gate (e.g. `preflight code`) runs with CI=true and must stay inert — this
    # ensures it can never accidentally emit even if ingest creds are present in
    # the env. The dedicated on-merge margin-eval workflow explicitly clears CI
    # (env: CI: "") on its secrets-backed step so a genuine, intended run DOES
    # emit. Override with --allow-ci-emit for a local CI-like shell if needed.
    ci_hermetic = bool(os.environ.get("CI")) and not args.allow_ci_emit
    meter = None
    if ci_hermetic:
        print("margin_eval: CI is set — HERMETIC mode, NOT emitting to Margin "
              "(the keyless gate must stay inert). The margin-eval workflow clears "
              "CI on its secrets-backed step so that run emits; use --allow-ci-emit "
              "to force emit in a CI-like shell.")
    elif ingest_key:
        try:
            from margin_meter import MarginMeter
            meter = MarginMeter(ingest_url=ingest_url, api_key=ingest_key, timeout=args.timeout)
        except Exception as exc:
            print(f"margin_eval: meter init failed ({exc}) — running WITHOUT emit.")
            meter = None
    else:
        print("margin_eval: MARGIN_INGEST_KEY unset — running + grading WITHOUT emit "
              "(fail-safe). Set MARGIN_INGEST_URL + MARGIN_INGEST_KEY to emit.")

    cases = ALL_CASES[: args.limit] if args.limit else ALL_CASES
    print(f"margin_eval: model={settings.gemini_model} cases={len(cases)} "
          f"run_id={run_id} emit={'on' if meter else 'off'} "
          f"max_cost=${args.max_cost_usd:.2f}")

    tracker = get_spend_tracker()
    start_spend = tracker.total_usd

    results: List[GradeResult] = []
    emitted_calls = 0
    emitted_outcomes = 0
    stopped_early = False

    for i, case in enumerate(cases, 1):
        # Cost guard: stop before exceeding the batch cap.
        if tracker.total_usd - start_spend >= args.max_cost_usd:
            print(f"margin_eval: reached max-cost ${args.max_cost_usd:.2f} — "
                  f"stopping after {i-1}/{len(cases)} cases.")
            stopped_early = True
            break

        prompt = build_signal_prompt(case)
        holder.pop("response", None)
        t0 = time.perf_counter()
        try:
            with _suppressed_inline_emit():
                text = analyst._call_llm(prompt, max_tokens=400)
        except Exception as exc:
            # Includes LLMBudgetExceeded (spend cap) — stop gracefully.
            print(f"  [{i:>3}/{len(cases)}] {case.id}: call error ({exc}) — stopping.")
            stopped_early = True
            break
        latency_ms = int((time.perf_counter() - t0) * 1000)

        response = holder.get("response")
        usage = _usage(response)
        g = grade(case, text)
        results.append(g)

        status = "PASS" if g.passed else "FAIL"
        print(f"  [{i:>3}/{len(cases)}] {case.id:<12} {bucket_of(case):<22} "
              f"verdict={str(g.verdict):<8} conf={g.confidence} "
              f"exp={g.expected:<12} q={g.quality_score:<5} {status}  "
              f"tok(in/out)={usage['input_tokens']}/{usage['output_tokens']}")

        # --- Emit (fail-safe) ---
        if meter is not None:
            try:
                r1 = meter.record_call(
                    workflow_id=WORKFLOW_ID,
                    provider="google",
                    model=settings.gemini_model,
                    input_tokens=usage["input_tokens"],
                    output_tokens=usage["output_tokens"],
                    cache_read_tokens=usage["cache_read_tokens"],
                    latency_ms=latency_ms,
                    status="ok" if text else "error",
                    session_id=session_id,
                    prompt_id=case.id,
                )
                if getattr(r1, "ok", False):
                    emitted_calls += 1
            except Exception:
                pass
            try:
                r2 = meter.record_outcome(
                    workflow_id=WORKFLOW_ID,
                    passed=g.passed,
                    quality_score=g.quality_score,
                    quality_method=g.quality_method,
                )
                if getattr(r2, "ok", False):
                    emitted_outcomes += 1
            except Exception:
                pass

    # --- Summary ---
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    spend = tracker.total_usd - start_spend
    print("\n=== margin_eval summary ===")
    print(f"run_id={run_id} session_id={session_id} model={settings.gemini_model}")
    print(f"cases_run={total} passed={passed} "
          f"pass_rate={ (passed/total*100) if total else 0:.1f}%")
    # Per-bucket pass rate (the statistical shape Margin needs).
    buckets: Dict[str, List[GradeResult]] = {}
    for case, r in zip(cases, results):
        buckets.setdefault(bucket_of(case), []).append(r)
    for b in sorted(buckets):
        rs = buckets[b]
        bp = sum(1 for r in rs if r.passed)
        print(f"  {b:<24} {bp}/{len(rs)} passed")
    print(f"measured_spend=${spend:.4f} (cap ${args.max_cost_usd:.2f})")
    print(f"emit: calls={emitted_calls} outcomes={emitted_outcomes} "
          f"{'(no meter)' if meter is None else ''}")
    if stopped_early:
        print("NOTE: batch stopped early (cost cap or call error).")
    # HONEST gaps note.
    if meter is not None and emitted_outcomes < total:
        print("NOTE: some outcome emits did not confirm ok (network/ingest); "
              "see per-call output above.")
    return 0


def list_cases() -> int:
    print(f"{len(ALL_CASES)} cases in the llmquant-signal-check matrix:\n")
    print(f"{'id':<12} {'category':<11} {'bucket':<24} {'price':>5} {'fair':>5} "
          f"{'liq$':>9} {'conf':>5}  expected")
    for c in ALL_CASES:
        gt = ground_truth(c)
        exp = "-" if gt.acceptable is None else "/".join(sorted(gt.acceptable))
        print(f"{c.id:<12} {c.category:<11} {bucket_of(c):<24} "
              f"{c.market_price:>5.2f} {c.model_fair_value:>5.2f} "
              f"{c.liquidity_usd:>9,.0f} {c.signal_confidence:>5.2f}  {exp}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Margin cost-per-outcome eval for LLM-Quant.")
    p.add_argument("--self-test", action="store_true",
                   help="offline harness check (no Gemini, no network); CI-safe.")
    p.add_argument("--list", action="store_true", help="print the case matrix and exit.")
    p.add_argument("--model", default=None, help="override gemini_model for this run.")
    p.add_argument("--run-id", default=None, help="batch id -> session_id=eval:<run-id>.")
    p.add_argument("--limit", type=int, default=0, help="run only the first N cases.")
    p.add_argument("--max-cost-usd", type=float, default=1.0,
                   help="stop the batch once measured spend crosses this (default 1.0).")
    p.add_argument("--timeout", type=float, default=2.0, help="meter HTTP timeout (s).")
    p.add_argument("--ingest-url", default=None, help="override MARGIN_INGEST_URL.")
    p.add_argument("--ingest-key", default=None, help="override MARGIN_INGEST_KEY.")
    p.add_argument("--allow-ci-emit", action="store_true",
                   help="emit even when CI is set (the margin-eval workflow instead "
                        "clears CI on its step; use this only for a local CI-like shell).")
    args = p.parse_args()

    if args.self_test:
        return self_test()
    if args.list:
        return list_cases()
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
