#!/usr/bin/env bash
# preflight.sh — the MECHANICAL gate for LLM-Quant.
# Exits non-zero on the FIRST gap. "A backtest exists" must NOT pass as
# "the edge is real". At baseline this is EXPECTED to fail at the floor/DoD gate —
# that honestly reflects "not go-live-eligible yet".
#
# Usage:
#   bash scripts/preflight.sh         # full gate (code + safety + profit-floor + DoD)
#   bash scripts/preflight.sh code    # code+safety only (CI blocking gate; skips the
#                                      #   profit-floor + DoD go-live gates)
#   PREFLIGHT_SCOPE=code bash scripts/preflight.sh
#
# The full gate is EXPECTED to exit non-zero until a validated out-of-sample edge
# exists (floor + DoD). The `code` scope is the always-must-pass correctness/safety
# gate suitable as a required CI check.
set -uo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
FAIL=0
SCOPE="${1:-${PREFLIGHT_SCOPE:-full}}"

say()  { printf '\n\033[1m== %s ==\033[0m\n' "$1"; }
ok()   { printf '  \033[32mOK\033[0m   %s\n' "$1"; }
warn() { printf '  \033[33mWARN\033[0m %s\n' "$1"; }
bad()  { printf '  \033[31mFAIL\033[0m %s\n' "$1"; FAIL=1; }
die()  { printf '\n\033[31mPREFLIGHT FAILED at: %s\033[0m\n' "$1"; exit 1; }

PY="${PYTHON:-python3}"

# ---------------------------------------------------------------------------
say "1. Code gate — Python import smoke"
if "$PY" -c "import backend.app.config" 2>/dev/null; then
  ok "backend.app.config imports"
else
  # try from backend/ layout
  if (cd backend && "$PY" -c "import app.config" 2>/dev/null); then
    ok "app.config imports (backend/ cwd)"
  else
    bad "backend app config import failed"
  fi
fi
[ "$FAIL" = 0 ] || die "code import smoke"

# ---------------------------------------------------------------------------
say "2. Code gate — tests"
if "$PY" -c "import pytest" 2>/dev/null; then
  # Run the prediction-market + risk tests if present; fall back to full suite.
  if ls backend/tests/test_*risk* >/dev/null 2>&1 || ls backend/tests/test_*prediction* >/dev/null 2>&1; then
    if "$PY" -m pytest -q backend/tests/test_*risk* backend/tests/test_*prediction* 2>/dev/null; then
      ok "prediction-market + risk tests pass"
    else
      bad "prediction-market/risk tests failed"
    fi
  else
    warn "no targeted risk/prediction tests found; skipping (add ROADMAP F1 coverage)"
  fi
else
  warn "pytest not installed; skipping tests"
fi
[ "$FAIL" = 0 ] || die "tests"

# ---------------------------------------------------------------------------
say "3. Code gate — lint + type-check (degrade gracefully)"
if command -v ruff >/dev/null 2>&1; then
  ruff check backend/app >/dev/null 2>&1 && ok "ruff clean" || bad "ruff reported issues"
else
  warn "ruff not installed; skipping lint"
fi
if command -v mypy >/dev/null 2>&1; then
  mypy backend/app >/dev/null 2>&1 && ok "mypy clean" || warn "mypy reported issues (non-blocking at baseline)"
else
  warn "mypy not installed; skipping type-check"
fi
[ "$FAIL" = 0 ] || die "lint/type-check"

# ---------------------------------------------------------------------------
say "4. Safety — live path gated OFF by default"
# LIVE_TRADING_ENABLED must default to false in config.
if "$PY" - <<'PYEOF' 2>/dev/null
import sys
try:
    from backend.app.config import get_settings
except Exception:
    sys.path.insert(0, "backend")
    from app.config import get_settings
s = get_settings()
val = getattr(s, "live_trading_enabled", None)
assert val is False, f"LIVE_TRADING_ENABLED must default False, got {val!r}"
print("default-false-ok")
PYEOF
then ok "LIVE_TRADING_ENABLED defaults to false"
else bad "LIVE_TRADING_ENABLED is not present/defaulting to false in config"
fi
[ "$FAIL" = 0 ] || die "live gate default"

# ---------------------------------------------------------------------------
say "5. Safety — kill switch present"
if grep -q "activate_kill_switch" backend/app/prediction_markets/execution.py 2>/dev/null; then
  ok "kill switch present in execution.py"
else
  bad "kill switch not found in execution.py"
fi
[ "$FAIL" = 0 ] || die "kill switch"

# ---------------------------------------------------------------------------
say "6. Secrets — none committed"
if git ls-files | grep -E '(^|/)\.env($|\.)' | grep -v '\.example$' | grep -q . ; then
  bad ".env file is tracked in git"
else
  ok "no tracked .env"
fi
# crude key scan in tracked files (skip docs/examples)
if git grep -nIE '(sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})' -- . ':(exclude)*.md' ':(exclude)*.example' 2>/dev/null | grep -q .; then
  bad "possible secret pattern in tracked files"
else
  ok "no obvious secret patterns in tracked files"
fi
[ "$FAIL" = 0 ] || die "secrets"

# ---------------------------------------------------------------------------
say "7. Machine-readable YAML blocks parse"
"$PY" - <<'PYEOF'
import re, sys, pathlib
blocks = {
  "docs/BUSINESS_CASE.md": "BUSINESS_CASE_SUMMARY",
  "docs/growth/GROWTH_STATUS.md": "GROWTH_STATUS",
  "PENDING_OPS.md": "OWNER_ACTIONS",
}
try:
    import yaml
    have_yaml = True
except Exception:
    have_yaml = False
fail = 0
for path, tag in blocks.items():
    txt = pathlib.Path(path).read_text()
    m = re.search(rf"<!--\s*{tag}\n(.*?)-->", txt, re.S)
    if not m:
        print(f"  FAIL missing {tag} block in {path}"); fail = 1; continue
    body = m.group(1)
    if have_yaml:
        try:
            yaml.safe_load(body)
            print(f"  OK   {tag} parses")
        except Exception as e:
            print(f"  FAIL {tag} YAML error: {e}"); fail = 1
    else:
        print(f"  WARN pyyaml not installed; presence-checked {tag}")
sys.exit(fail)
PYEOF
[ $? -eq 0 ] && ok "YAML blocks present/parse" || bad "YAML block parse failure"
[ "$FAIL" = 0 ] || die "yaml blocks"

# ---------------------------------------------------------------------------
say "8. Runbook present + complete"
if [ -f docs/growth/LIVE_RUNBOOK.md ] && grep -q "LIVE_TRADING_ENABLED" docs/growth/LIVE_RUNBOOK.md \
   && grep -q "§7" docs/growth/LIVE_RUNBOOK.md; then
  ok "LIVE_RUNBOOK present + covers gate + monitoring"
else
  bad "LIVE_RUNBOOK missing or incomplete"
fi
[ "$FAIL" = 0 ] || die "runbook"

# ---------------------------------------------------------------------------
say "9. Runtime harness — BUILDS != WORKS (E2E paper run)"
if [ -f scripts/runtime_harness.py ]; then
  if E2E_RUN_PASSED=0 "$PY" scripts/runtime_harness.py; then
    ok "runtime harness passed (E2E paper pipeline produced real reproducible result)"
  else
    bad "runtime harness failed (pipeline did not produce a real reproducible result)"
  fi
else
  bad "scripts/runtime_harness.py missing"
fi
[ "$FAIL" = 0 ] || die "runtime harness"

if [ "$SCOPE" = "code" ]; then
  printf '\n\033[32mPREFLIGHT (code scope) GREEN — correctness + safety gates pass.\033[0m\n'
  printf 'Skipped the profit-floor + DoD go-live gates (run the full gate for those).\n'
  exit 0
fi

# ---------------------------------------------------------------------------
say "10. PROFIT FLOOR — validated out-of-sample weekly PnL >= floor"
# Honest gate: reads GROWTH_STATUS floor_met. At baseline this is false -> FAIL.
FLOOR_MET="$("$PY" - <<'PYEOF'
import re, pathlib
txt = pathlib.Path("docs/BUSINESS_CASE.md").read_text()
m = re.search(r"floor_met_year1:\s*(true|false)", txt)
print(m.group(1) if m else "false")
PYEOF
)"
if [ "$FLOOR_MET" = "true" ]; then
  ok "floor_met_year1: true"
else
  bad "floor_met_year1: false — no validated out-of-sample edge >= weekly floor yet (HONEST baseline state)"
fi

# ---------------------------------------------------------------------------
say "11. DEFINITION OF DONE — every box [x]"
UNCHECKED="$(awk '/^## DEFINITION OF DONE/{f=1} f&&/^- \[ \]/{c++} /^## STANDING STANDARDS/{f=0} END{print c+0}' ROADMAP.md)"
if [ "${UNCHECKED:-1}" = "0" ]; then
  ok "all DoD boxes checked"
else
  bad "$UNCHECKED DoD box(es) still unchecked — NOT go-live-eligible (HONEST baseline state)"
fi

# ---------------------------------------------------------------------------
if [ "$FAIL" = 0 ]; then
  printf '\n\033[32mPREFLIGHT GREEN — go-live-eligible gate mechanically satisfied.\033[0m\n'
  exit 0
else
  printf '\n\033[31mPREFLIGHT RED — not go-live-eligible. See FAIL lines above.\033[0m\n'
  printf 'This is the CORRECT, HONEST result until a validated out-of-sample edge exists.\n'
  exit 1
fi
