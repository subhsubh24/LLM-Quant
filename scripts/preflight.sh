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

# --- FACTORY_STANDARD §22: computation-integrity gate (fail-safe; vacuous until analysis/figures.json has entries) ---
if [ -f scripts/validate-computation.mjs ] && ! node scripts/validate-computation.mjs; then
  echo "PREFLIGHT FAIL: validate-computation (§22) — a committed figure is mis-computed or non-reproducible." >&2
  exit 1
fi
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
say "2. Code gate — prediction-market tests"
# Target the prediction-market test module specifically. We deliberately do NOT
# glob test_*risk* — those are the heavy ML risk/backtest suites (pandas/sklearn)
# outside the gate's light dependency surface. The prediction-markets risk manager
# is covered inside test_prediction_markets.py.
if "$PY" -c "import pytest" 2>/dev/null; then
  _testfiles=""
  for t in backend/tests/test_prediction_markets.py \
           backend/tests/test_cost_model.py \
           backend/tests/test_loss_caps.py \
           backend/tests/test_loss_cap_fees.py \
           backend/tests/test_audit_log.py \
           backend/tests/test_config_safety.py \
           backend/tests/test_live_gate_defense.py \
           backend/tests/test_metrics_aggregator.py \
           backend/tests/test_regime_slice.py \
           backend/tests/test_real_data_validation.py \
           backend/tests/test_history_fetcher.py \
           backend/tests/test_strategy_audit.py \
           backend/tests/test_self_validation.py \
           backend/tests/test_validate_gtm.py \
           backend/tests/test_live_validation_tiers.py \
           backend/tests/test_persistence_default_portfolio.py \
           backend/tests/test_validate_real_oos.py \
           backend/tests/test_orchestrator_persist_fk.py \
           backend/tests/test_scorecard.py \
           backend/tests/test_calibration.py \
           backend/tests/test_data_quality.py \
           backend/tests/test_market_text.py \
           backend/tests/test_strategy_registry.py \
           backend/tests/test_per_strategy_metrics.py \
           backend/tests/test_learning_loop_wiring.py \
           backend/tests/test_same_market_arb_costs.py \
           backend/tests/test_evaluation_window.py \
           backend/tests/test_calibration_drift.py \
           backend/tests/test_calibration_bucket_strategy.py \
           backend/tests/test_executor_state_persistence.py \
           backend/tests/test_rest_order_validation.py \
           backend/tests/test_backend_auth.py \
           backend/tests/test_risk_config_validation.py \
           backend/tests/test_durable_tables_created.py \
           backend/tests/test_walk_forward_pm.py \
           backend/tests/test_kalshi_client.py \
           backend/tests/test_kalshi_history_fetcher.py \
           backend/tests/test_polymarket_parse.py \
           backend/tests/test_polymarket_v1_hf_fetcher.py \
           backend/tests/test_websocket_feeds.py \
           backend/tests/test_unvalidated_strategy_gating.py \
           backend/tests/test_strategy_drawdown_disable.py \
           backend/tests/test_forward_record_coherence.py \
           backend/tests/test_market_category.py \
           backend/tests/test_weekly_metrics.py \
           backend/tests/test_cross_venue_matcher.py; do
    [ -f "$t" ] && _testfiles="$_testfiles $t"
  done
  if [ -n "$_testfiles" ]; then
    if "$PY" -m pytest -q $_testfiles 2>/dev/null; then
      ok "prediction-market + scorecard-guard tests pass"
    else
      bad "prediction-market/scorecard tests failed"
    fi
  else
    warn "no targeted tests found; skipping (add ROADMAP F1 coverage)"
  fi
else
  warn "pytest not installed; skipping tests"
fi
[ "$FAIL" = 0 ] || die "tests"

# ---------------------------------------------------------------------------
say "3. Code gate — lint + type-check (degrade gracefully)"
# ENFORCED lint = CORRECTNESS rules only (ROADMAP F7): E9 (syntax/runtime), F821
# (undefined name), F811 (redefinition of an unused name — a real shadowing bug).
# These catch defects, not style; the tree is at zero for them, so this is a true
# lint-at-zero ratchet the required gate can enforce without red-blocking on the
# ~150 remaining hygiene findings (F401/E402/F841/…), which stay UNENFORCED until
# cleared module-by-module. A NEW correctness finding now FAILS the gate.
if command -v ruff >/dev/null 2>&1; then
  ruff check --select E9,F821,F811 backend/app >/dev/null 2>&1 \
    && ok "ruff correctness-clean (E9,F821,F811)" || bad "ruff reported CORRECTNESS issues (E9/F821/F811)"
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
say "7. Machine-readable YAML blocks parse (FENCED — dashboard-readable)"
# The AutoFactory dashboard reads each block from a fenced ```yaml code block whose
# content carries the tag (GROWTH_STATUS:/OWNER_ACTIONS: as a top-level key, or a
# `# BUSINESS_CASE_SUMMARY` marker / arr_year1). Mirror that here so a block the
# dashboard can't read fails the gate.
"$PY" - <<'PYEOF'
import re, sys, pathlib
# path -> (tag, marker_regex that must appear in the fenced block)
blocks = {
  "docs/BUSINESS_CASE.md": ("BUSINESS_CASE_SUMMARY", r"(BUSINESS_CASE_SUMMARY|(^|\n)\s*arr_year1\s*:)"),
  "docs/growth/GROWTH_STATUS.md": ("GROWTH_STATUS", r"(^|\n)\s*GROWTH_STATUS\s*:"),
  "PENDING_OPS.md": ("OWNER_ACTIONS", r"(^|\n)\s*OWNER_ACTIONS\s*:"),
}
try:
    import yaml
    have_yaml = True
except Exception:
    have_yaml = False

def fenced_blocks(md):
    lines = md.replace("\r\n", "\n").split("\n")
    out, open_, body = [], False, []
    for ln in lines:
        if re.match(r"^\s*(```|~~~)", ln):
            if not open_:
                open_, body = True, []
            else:
                out.append("\n".join(body)); open_ = False
            continue
        if open_:
            body.append(ln)
    return out

fail = 0
for path, (tag, marker) in blocks.items():
    txt = pathlib.Path(path).read_text()
    cand = [b for b in fenced_blocks(txt) if re.search(marker, b)]
    if not cand:
        print(f"  FAIL no fenced block carrying {tag} in {path}"); fail = 1; continue
    body = cand[0]
    if have_yaml:
        try:
            yaml.safe_load(body)
            print(f"  OK   {tag} parses (fenced)")
        except Exception as e:
            print(f"  FAIL {tag} YAML error: {e}"); fail = 1
    else:
        print(f"  WARN pyyaml not installed; presence-checked {tag}")
sys.exit(fail)
PYEOF
[ $? -eq 0 ] && ok "YAML blocks present/parse (dashboard-readable)" || bad "YAML block parse failure"
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

# ---------------------------------------------------------------------------
say "9b. Quality scorecard — parse guard (a malformed scorecard cannot ship)"
# maker != checker: the independent Quality Auditor OWNS docs/quality/*. We only
# consume the grade. Absent scorecard = bootstrap (the auditor hasn't run yet) = OK
# in code scope; a malformed scorecard (bad YAML / invalid grade) FAILS.
if [ -f scripts/check_scorecard.py ]; then
  if "$PY" scripts/check_scorecard.py parse; then
    ok "scorecard parse guard"
  else
    bad "scorecard malformed (see above)"
  fi
else
  bad "scripts/check_scorecard.py missing"
fi
[ "$FAIL" = 0 ] || die "scorecard parse guard"

# ---------------------------------------------------------------------------
say "9c. GO signal integrity (a fake 'eligible' cannot ship)"
# The go_live signal is DERIVED, never hand-set: 'eligible' is allowed ONLY when every
# criterion is true AND floor_met AND all DoD boxes checked. Runs in BOTH scopes so a
# falsely-green GO can never merge. At baseline status=not_ready -> passes (honest).
"$PY" - <<'PYEOF'
import re, sys, pathlib
try:
    import yaml
except Exception:
    print("  WARN pyyaml not installed; skipping GO integrity"); sys.exit(0)

def fenced(md):
    out, op, body = [], False, []
    for ln in md.replace("\r\n", "\n").split("\n"):
        if re.match(r"^\s*(```|~~~)", ln):
            if not op: op, body = True, []
            else: out.append("\n".join(body)); op = False
            continue
        if op: body.append(ln)
    return out

txt = pathlib.Path("docs/growth/GROWTH_STATUS.md").read_text()
blk = [b for b in fenced(txt) if re.search(r"(^|\n)\s*GROWTH_STATUS\s*:", b)]
if not blk:
    print("  FAIL GROWTH_STATUS block missing"); sys.exit(1)
root = (yaml.safe_load(blk[0]) or {}).get("GROWTH_STATUS", {})
go = root.get("go_live") or {}
status = go.get("status"); conf = go.get("confidence"); crit = go.get("criteria") or {}
fail = 0
if status not in ("not_ready", "eligible"):
    print(f"  FAIL go_live.status invalid: {status!r}"); fail = 1
if conf not in ("none", "building", "high"):
    print(f"  FAIL go_live.confidence invalid: {conf!r}"); fail = 1
if conf == "high" and status != "eligible":
    print("  FAIL confidence=high requires status=eligible"); fail = 1
if status == "eligible":
    false_crit = [k for k, v in crit.items() if v is not True]
    if false_crit:
        print(f"  FAIL status=eligible but criteria not all true: {false_crit}"); fail = 1
    bc = pathlib.Path("docs/BUSINESS_CASE.md").read_text()
    if not re.search(r"floor_met_year1:\s*true", bc):
        print("  FAIL status=eligible but floor_met_year1 != true"); fail = 1
    rm = pathlib.Path("ROADMAP.md").read_text()
    unchecked = 0
    f = False
    for ln in rm.split("\n"):
        if ln.startswith("## DEFINITION OF DONE"): f = True
        elif ln.startswith("## STANDING STANDARDS"): f = False
        elif f and ln.startswith("- [ ]"): unchecked += 1
    if unchecked:
        print(f"  FAIL status=eligible but {unchecked} DoD box(es) unchecked"); fail = 1
if not fail:
    print(f"  OK   go_live well-formed (status={status}, confidence={conf})")
sys.exit(fail)
PYEOF
[ $? -eq 0 ] && ok "GO signal integrity" || bad "GO signal integrity failed"
[ "$FAIL" = 0 ] || die "GO signal integrity"

say "9d. Self-validation coverage (every capability validated; new credential surfaces + blocks)"
# BLOCKING: fails if an ACTIVE capability is unvalidated, or if the code reads a credential
# (a *_api_key/_secret/_token/_url/... env var) that is NOT declared in the self-validation
# manifest. This is the forcing function: the loop cannot ship a capability it can't really
# validate, and a NEW service needing a key surfaces (here + PENDING_OPS) and blocks merges.
if [ -f scripts/check_self_validation.py ]; then
  if "$PY" scripts/check_self_validation.py --readiness; then
    ok "self-validation coverage"
  else
    bad "self-validation coverage failed"
  fi
else
  bad "scripts/check_self_validation.py missing"
fi
[ "$FAIL" = 0 ] || die "self-validation coverage"

say "9e. GTM honesty (a growth number with no connected source is a fabrication risk)"
# BLOCKING: fails closed if any GROWTH_STATUS funnel/acquisition/pmf/channels/metrics number is
# reported (>0, excl. target/config keys) without a connected source (channels_connected /
# venues_connected / a sources block), or if a GTM_SCORECARD is present but malformed. Pre-launch
# everything is 0/null -> green. (GTM analog of self-validation; mirrors AptDesignerAI validate-gtm.)
if [ -f scripts/validate_gtm.py ]; then
  if "$PY" scripts/validate_gtm.py; then
    ok "GTM honesty"
  else
    bad "GTM honesty failed"
  fi
else
  bad "scripts/validate_gtm.py missing"
fi
[ "$FAIL" = 0 ] || die "GTM honesty"

if [ "$SCOPE" = "code" ]; then
  printf '\n\033[32mPREFLIGHT (code scope) GREEN — correctness + safety gates pass.\033[0m\n'
  printf 'Skipped the profit-floor + DoD + quality go-live gates (run the full gate for those).\n'
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
say "12. QUALITY GRADE — ship-critical dims A/A+, others >= B (independent auditor)"
# Consumes the independent Quality Auditor's grade. Absent or below-bar = not ready.
if "$PY" scripts/check_scorecard.py gate; then
  ok "quality grade meets the go-live bar"
else
  bad "quality grade below the go-live bar (or not yet graded) — NOT go-live-eligible"
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
