#!/usr/bin/env python3
"""validate_gtm.py — the GTM/growth honesty gate (the GTM analog of check_self_validation).

Fails CLOSED so the loop cannot report a growth/traction number it cannot source. Mirrors
AptDesignerAI's `scripts/validate-gtm.mjs`, adapted to this stack (Python — the preflight gate
runs Python, not Node) and to this PRODUCT (a PERSONAL prediction-markets bot: NOT marketed, no
users, so the literal funnel/acquisition/pmf/channels GTM sections are absent — the meaningful
analog is the performance `metrics` block, whose "connected source" is `venues_connected`).

Hard, machine-checkable honesty rules:

  1. The `GROWTH_STATUS` fenced YAML parses.
  2. METRIC-WITHOUT-A-SOURCE tripwire: if any funnel/acquisition/pmf/channels/metrics number is
     reported (> 0, excluding TARGET/CONFIG keys), a connected source MUST be declared —
     `channels_connected` truthy, OR `venues_connected` non-empty, OR a `sources`/`validation`
     entry marked connected/available. A real number with NO connected source is a fabrication
     risk → FAIL. (Pre-launch everything is 0/null → passes.)
  3. `GTM_SCORECARD` (if present) parses and its grades are in {A+,A,B,C,D,F,null} with
     `ship_gate_met` set. (This personal bot has no GTM auditor, so the file is normally absent —
     that is fine; readiness GTM is N/A for a non-marketed product.)

Usage: python scripts/validate_gtm.py [--readiness]
Reads only the committed growth feeds. NEVER prints a secret. Exit 0 = green, 1 = fail-closed.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATUS = ROOT / "docs" / "growth" / "GROWTH_STATUS.md"
SCORECARD = ROOT / "docs" / "growth" / "GTM_SCORECARD.md"
GRADES = {"A+", "A", "B", "C", "D", "F", None}
METRIC_SECTIONS = ["funnel", "acquisition", "pmf", "channels", "metrics"]
# Keys that are TARGETS / CONFIG / progress, not REPORTED traction — excluded from the tripwire.
CONFIG_KEY_RE = re.compile(r"(target|floor|cap|limit|threshold|goal|budget|enabled|_pct$)", re.I)


def _yaml_block(path: Path, key: str):
    """Return (value, file_present). value is the YAML under `key`, or None."""
    try:
        import yaml
    except ImportError:
        raise RuntimeError("pyyaml not installed — REQUIRED for validate_gtm (declared in "
                           "backend/requirements-ci.txt); refusing to skip.")
    if not path.exists():
        return None, False
    for m in re.findall(r"```yaml\n(.*?)```", path.read_text(), re.S):
        try:
            d = yaml.safe_load(m)
        except yaml.YAMLError:
            continue
        if isinstance(d, dict) and key in d:
            return d[key], True
    return None, True


def _walk_reported(value, prefix: str, leaf_key: str, out: list[str]) -> None:
    """Collect `path=value` for every number > 0 whose leaf key is not a TARGET/CONFIG key."""
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        if value > 0 and not CONFIG_KEY_RE.search(leaf_key):
            out.append(f"{prefix}={value}")
        return
    if isinstance(value, list):
        for i, x in enumerate(value):
            _walk_reported(x, f"{prefix}[{i}]", leaf_key, out)
        return
    if isinstance(value, dict):
        for k, v in value.items():
            _walk_reported(v, f"{prefix}.{k}", str(k), out)


def _source_declared(gs: dict) -> bool:
    cc = gs.get("channels_connected")
    if cc is True:
        return True
    if isinstance(cc, list) and cc:
        return True
    if isinstance(cc, str) and cc.strip() and not re.fullmatch(r"none|n/a|\[\]", cc.strip(), re.I):
        return True
    # this product's analog: a connected trading venue is a real source of paper/live numbers
    vc = gs.get("venues_connected")
    if isinstance(vc, list) and len(vc) > 0:
        return True
    src = gs.get("sources") or gs.get("validation")
    if src:
        txt = str(src).lower()
        if "unavailable" not in txt and ("connected" in txt or "available" in txt or "live" in txt):
            return True
        if isinstance(src, list) and src and "unavailable" not in txt:
            return True
    return False


def evaluate(gs, gs_present: bool, sc, sc_present: bool, readiness: bool = False) -> list[str]:
    """Pure policy on already-loaded feeds (injectable for tests)."""
    errors: list[str] = []
    if not gs_present:
        errors.append("docs/growth/GROWTH_STATUS.md is missing (the dashboard growth feed).")
    elif gs is None:
        errors.append("GROWTH_STATUS.md has no parseable fenced `GROWTH_STATUS:` YAML block.")
    else:
        reported: list[str] = []
        for s in METRIC_SECTIONS:
            if s in gs:
                _walk_reported(gs[s], s, s, reported)
        if reported and not _source_declared(gs):
            errors.append(
                f"METRIC WITHOUT A SOURCE: {len(reported)} non-zero growth metric(s) reported but no "
                f"connected source declared (channels_connected falsy, venues_connected empty, no "
                f"sources/validation entry connected). A real number with no connected source is a "
                f"fabrication risk.\n    reported: {', '.join(reported[:8])}{' ...' if len(reported) > 8 else ''}\n"
                f"    -> set the metric to 0/null until a source is connected, OR declare the source "
                f"(venues_connected / channels_connected / a sources block; surface a gtm-connect-* / "
                f"validation-capability-* OWNER_ACTION if it needs the owner)."
            )

    # GTM_SCORECARD validity (if present). This personal bot normally has none.
    if sc_present:
        if sc is None:
            errors.append("GTM_SCORECARD.md exists but has no parseable fenced `GTM_SCORECARD:` YAML block.")
        else:
            dims = sc.get("dimensions") or sc.get("grades") or sc
            bad = []
            if isinstance(dims, dict):
                for k, v in dims.items():
                    if isinstance(v, str) and len(v) <= 2 and v not in GRADES:
                        bad.append(f"{k}={v}")  # a short string that isn't a valid grade
                    elif isinstance(v, dict) and "grade" in v and v["grade"] not in GRADES:
                        bad.append(f"{k}.grade={v['grade']}")
            if bad:
                errors.append(f"GTM_SCORECARD has invalid grade(s) (allowed A+/A/B/C/D/F/null): {', '.join(bad)}")
            if isinstance(sc, dict) and "ship_gate_met" not in sc and not (
                isinstance(dims, dict) and "ship_gate_met" in dims
            ):
                errors.append("GTM_SCORECARD is missing `ship_gate_met`.")
    elif readiness:
        # NOTE: LLM-Quant is a personal bot with no GTM auditor/scorecard — GTM readiness is N/A,
        # so --readiness is NOT wired into the gate for this product (documented in PROPOSED_CI).
        errors.append("--readiness: docs/growth/GTM_SCORECARD.md does not exist (no GTM auditor for "
                      "this personal bot — GTM readiness is N/A; do not wire --readiness into the gate).")
    return errors


def check(readiness: bool = False) -> list[str]:
    try:
        gs, gs_present = _yaml_block(STATUS, "GROWTH_STATUS")
        sc, sc_present = _yaml_block(SCORECARD, "GTM_SCORECARD")
    except RuntimeError as e:
        return [str(e)]
    return evaluate(gs, gs_present, sc, sc_present, readiness)


def main() -> int:
    readiness = "--readiness" in sys.argv[1:]
    errors = check(readiness=readiness)
    if errors:
        print(f"  validate-gtm: FAIL ({len(errors)})")
        for e in errors:
            print(f"    - {e}")
        return 1
    sc_present = SCORECARD.exists()
    print(f"  validate-gtm: OK ({'GTM_SCORECARD present' if sc_present else 'no GTM_SCORECARD (personal bot)'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
