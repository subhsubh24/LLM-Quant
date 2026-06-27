#!/usr/bin/env python3
"""
check_scorecard.py — the MAKER's consumer-side guard for the independent Quality
Auditor's grade.

maker != checker: the independent Quality Auditor routine OWNS and bootstraps
docs/quality/QUALITY_RUBRIC.md and docs/quality/QUALITY_SCORECARD.md. This script
NEVER writes them. It only READS the scorecard as DATA to (a) reject a malformed
scorecard and (b) enforce the go-live readiness bar.

Expected scorecard contract (the auditor produces this; we only consume it) — an
HTML-comment YAML block, same style as the repo's other machine-readable blocks:

    <!-- QUALITY_SCORECARD
    overall: B
    as_of: 2026-06-27
    dimensions:
      - name: functional_reality
        grade: A
        ship_critical: true
        top_gaps: []
      - name: backtest_integrity
        grade: C
        ship_critical: true
        top_gaps: ["no walk-forward", "costs not modeled"]
      # ... others ...
    -->

Grades must be one of: A+, A, B, C, D, F, or null (ungraded).

Modes:
  parse  - if the scorecard exists, its QUALITY_SCORECARD block must parse and every
           grade must be valid. ABSENT => OK (bootstrap: the auditor hasn't run yet).
           MALFORMED => exit 1 (a malformed scorecard cannot ship).
  gate   - go-live readiness: the scorecard must EXIST, every ship_critical dimension
           must be A or A+, and all others must be >= B. Otherwise exit 1.
"""
import sys
import re
import pathlib

PATH = pathlib.Path("docs/quality/QUALITY_SCORECARD.md")
VALID_GRADES = {"A+", "A", "B", "C", "D", "F", None}
ORDER = {"F": 0, "D": 1, "C": 2, "B": 3, "A": 4, "A+": 5}


def _norm(g):
    return g.strip() if isinstance(g, str) else g


def load_block():
    """Return the parsed YAML dict, or None if the scorecard file is absent."""
    if not PATH.exists():
        return None
    txt = PATH.read_text()
    m = re.search(r"<!--\s*QUALITY_SCORECARD\s*\n(.*?)-->", txt, re.S)
    if not m:
        raise ValueError("QUALITY_SCORECARD block not found in scorecard file")
    import yaml
    data = yaml.safe_load(m.group(1))
    if data is None:
        raise ValueError("QUALITY_SCORECARD block is empty")
    if not isinstance(data, dict):
        raise ValueError("QUALITY_SCORECARD block must be a mapping")
    return data


def dimensions(block):
    """Normalize dimensions to a list of (name, grade, ship_critical)."""
    dims = block.get("dimensions") or []
    out = []
    if isinstance(dims, dict):
        for name, v in dims.items():
            v = v or {}
            out.append((name, _norm(v.get("grade")), bool(v.get("ship_critical"))))
    elif isinstance(dims, list):
        for d in dims:
            d = d or {}
            out.append((d.get("name"), _norm(d.get("grade")), bool(d.get("ship_critical"))))
    else:
        raise ValueError("dimensions must be a list or mapping")
    return out


def validate_grades(block):
    """Return a list of (name, bad_grade) for any out-of-range grade."""
    bad = []
    for name, grade, _ in dimensions(block):
        if grade not in VALID_GRADES:
            bad.append((name, grade))
    overall = _norm(block.get("overall"))
    if "overall" in block and overall not in VALID_GRADES:
        bad.append(("overall", overall))
    return bad


def readiness_failures(block):
    """Go-live readiness: ship_critical dims need A/A+, others >= B.

    Returns a list of human-readable failure strings (empty == ready).
    """
    failures = []
    for name, grade, crit in dimensions(block):
        if grade is None:
            failures.append(f"{name}: ungraded")
            continue
        lvl = ORDER[grade]
        if crit and lvl < ORDER["A"]:
            failures.append(f"{name}: {grade} (ship-critical needs A/A+)")
        elif not crit and lvl < ORDER["B"]:
            failures.append(f"{name}: {grade} (needs >= B)")
    return failures


def main(argv):
    mode = argv[1] if len(argv) > 1 else "parse"

    try:
        block = load_block()
    except Exception as e:
        print(f"FAIL malformed QUALITY_SCORECARD: {e}")
        return 1

    if block is None:
        if mode == "gate":
            print("NOT-READY: docs/quality/QUALITY_SCORECARD.md absent — the independent "
                  "Quality Auditor has not graded this project yet.")
            return 1
        print("note: QUALITY_SCORECARD.md absent (bootstrap state) — parse guard skipped.")
        return 0

    bad = validate_grades(block)
    if bad:
        print(f"FAIL invalid grade(s) {bad} — allowed: A+, A, B, C, D, F, null")
        return 1

    dims = dimensions(block)
    overall = _norm(block.get("overall"))

    if mode == "parse":
        print(f"OK QUALITY_SCORECARD parses — {len(dims)} dimension(s), overall={overall}")
        return 0

    # gate mode — go-live readiness
    failures = readiness_failures(block)
    if failures:
        print("NOT-READY (quality): " + "; ".join(failures))
        return 1
    print(f"OK quality gate — all ship-critical A/A+, others >= B (overall={overall})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
