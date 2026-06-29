#!/usr/bin/env python3
"""check_self_validation.py — enforce that the loop can REALLY validate every capability.

Reads the self-validation manifest (docs/ci/SELF_VALIDATION.md, fenced ```yaml
SELF_VALIDATION block) and enforces two things, as a BLOCKING preflight step:

  1. COVERAGE: every capability that is ACTIVE (reachable in a real flow) must carry an
     honest validation status — `validated` (really exercised in the gate), `gated_off`
     (built but unreachable, and the gate proves it's off), or `degrades_safely` (works
     without the credential, no fake output). An active capability that is `unvalidated`
     or `needs_credential` FAILS the gate → blocks every merge until resolved.

  2. CREDENTIAL DECLARATION: every external-service credential the CODE reads — a
     `*_api_key/_secret/_token/_url/_passphrase/_private_key/_funder` field in
     config.Settings, or an `os.environ.get("X")` of the same shape anywhere under
     backend/app — MUST be declared in the manifest's credential_inventory. A NEW one
     that isn't declared FAILS the gate. This is the "the loop hit a new service that
     needs a key → it surfaces and blocks subsequent PRs" forcing function: the loop
     cannot ship a path that reads an undeclared credential; it must declare the
     capability + how it's validated and, if a key is genuinely required, record the
     owner action.

Resolution when a capability needs a credential the CI gate doesn't have: either the
owner provides it (env / GitHub Actions secret) so validation runs, OR the loop gates the
capability OFF (status gated_off) so no active flow depends on an unvalidated path.

Read-only. Exit 0 = green, 1 = blocking failure. Standalone (only stdlib + pyyaml).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs" / "ci" / "SELF_VALIDATION.md"
CONFIG = ROOT / "backend" / "app" / "config.py"
APP_DIR = ROOT / "backend" / "app"

# A credential-shaped name. Generic enough to catch a NEW service's key.
CRED_SUFFIX = r"(?:API_KEY|API_SECRET|KEY|SECRET|TOKEN|PASSPHRASE|PRIVATE_KEY|FUNDER|DATABASE_URL)"
ALLOWED_ACTIVE_STATUS = {"validated", "gated_off", "degrades_safely"}
# Env vars that are NOT external-service credentials (config knobs / test flags).
CRED_IGNORE = {"E2E_DISABLE_RATE_LIMIT"}


def _fenced_yaml(md: str) -> str:
    blocks = re.findall(r"```yaml\n(.*?)```", md, re.S)
    for b in blocks:
        if re.search(r"(^|\n)\s*SELF_VALIDATION\s*:", b):
            return b
    return ""


def _declared_credentials_in_code() -> set[str]:
    """Every credential-shaped env var the code actually reads (config fields + os.environ)."""
    found: set[str] = set()
    # 1) config.Settings fields: `gemini_api_key: str = ""` -> GEMINI_API_KEY
    cfg = CONFIG.read_text()
    for m in re.finditer(
        r"^\s*([a-z_]+(?:_api_key|_api_secret|_key|_secret|_token|_passphrase|_private_key|_funder|_url))\s*:",
        cfg,
        re.M,
    ):
        env = m.group(1).upper()
        if re.search(CRED_SUFFIX + r"$", env):
            found.add(env)
    # 2) os.environ.get("X") / os.getenv("X") of credential shape, anywhere under backend/app
    pat = re.compile(r"""os\.(?:environ\.get|getenv)\(\s*['"]([A-Z][A-Z0-9_]+)['"]""")
    for py in APP_DIR.rglob("*.py"):
        for m in pat.finditer(py.read_text(encoding="utf-8", errors="ignore")):
            env = m.group(1)
            if re.search(CRED_SUFFIX + r"$", env):
                found.add(env)
    return {c for c in found if c not in CRED_IGNORE}


def check(root: dict | None = None, in_code: set[str] | None = None) -> list[str]:
    """Return a list of blocking failures ([] = green).

    ``root`` / ``in_code`` are injectable for tests; by default they are read from the
    committed manifest and scanned from backend/app.
    """
    fails: list[str] = []
    if root is None:
        if not MANIFEST.exists():
            return [f"missing self-validation manifest: {MANIFEST.relative_to(ROOT)}"]
        try:
            import yaml
        except ImportError:
            # pitfall #2: the parser is a DECLARED dependency (backend/requirements-ci.txt).
            # If it's missing the gate must FAIL, not silently skip — a vanished parser must
            # never disable the check.
            return ["pyyaml not installed — REQUIRED for the self-validation gate "
                    "(declared in backend/requirements-ci.txt); refusing to skip."]
        block = _fenced_yaml(MANIFEST.read_text())
        if not block:
            return ["no fenced ```yaml SELF_VALIDATION block in the manifest"]
        try:
            root = (yaml.safe_load(block) or {}).get("SELF_VALIDATION", {})
        except yaml.YAMLError as e:
            return [f"SELF_VALIDATION block is not valid YAML: {e}"]

    caps = root.get("capabilities") or []
    inventory = root.get("credential_inventory") or {}

    # (1) coverage: every ACTIVE capability has an honest validated/gated/degrades status
    for c in caps:
        cid = c.get("id", "<unnamed>")
        if c.get("active") and c.get("status") not in ALLOWED_ACTIVE_STATUS:
            fails.append(
                f"capability '{cid}' is ACTIVE but status='{c.get('status')}' "
                f"(must be one of {sorted(ALLOWED_ACTIVE_STATUS)}). Validate it, or gate it OFF, "
                f"or record the owner credential it needs."
            )
    blocking = root.get("unvalidated_blocking") or []
    if blocking:
        fails.append(f"unvalidated_blocking is non-empty: {blocking} — these active capabilities block merges.")

    # (2) every credential the code reads must be declared
    declared = set(inventory.keys())
    if in_code is None:
        in_code = _declared_credentials_in_code()
    undeclared = sorted(in_code - declared)
    for env in undeclared:
        fails.append(
            f"UNDECLARED credential '{env}' is read in code but absent from SELF_VALIDATION "
            f"credential_inventory. The loop hit a service needing a key without declaring how it "
            f"is validated — add it (capability + validation + owner action if a key is required). "
            f"Until then, every PR is blocked."
        )
    # every declared credential should map to a real capability
    cap_ids = {c.get("id") for c in caps}
    for env, meta in inventory.items():
        cap = (meta or {}).get("capability")
        if cap and cap not in cap_ids:
            fails.append(f"credential '{env}' maps to unknown capability '{cap}'.")
    return fails


# ---------------------------------------------------------------------------
# Readiness mode (--readiness): surface UNMET capabilities (active but only
# validatable with an owner-only secret) and enforce they're visible in BOTH the
# dashboard feeds — an urgent OWNER_ACTION AND the LOOP_HEALTH validation block.
# ---------------------------------------------------------------------------
def readiness(root: dict) -> dict:
    """The validation sub-block the dashboard reads. An UNMET capability is one that is
    ACTIVE but `ci_validatable: false` — it cannot be honestly validated in CI without an
    owner-only secret (a gated-off or safely-degrading capability is NOT unmet)."""
    caps = root.get("capabilities") or []
    unmet = sorted(c.get("id") for c in caps if c.get("active") and not c.get("ci_validatable", True))
    return {"enforced_in_ci": True, "capabilities_total": len(caps), "unmet": unmet}


def _yaml_block(path: Path, tag: str) -> dict:
    import yaml
    if not path.exists():
        return {}
    for b in re.findall(r"```yaml\n(.*?)```", path.read_text(), re.S):
        if re.search(rf"(^|\n)\s*{tag}\s*:", b):
            try:
                return (yaml.safe_load(b) or {}).get(tag, {}) or {}
            except yaml.YAMLError:
                return {}
    return {}


def check_readiness(root: dict | None = None) -> list[str]:
    """Full gate: coverage + credential declaration + UNMET surfacing (dual-visibility)."""
    try:
        import yaml  # noqa: F401  (hard dep; pitfall #2)
    except ImportError:
        return ["pyyaml not installed — REQUIRED for the readiness gate."]
    if root is None:
        block = _fenced_yaml(MANIFEST.read_text()) if MANIFEST.exists() else ""
        if not block:
            return ["no fenced ```yaml SELF_VALIDATION block in the manifest"]
        root = (yaml.safe_load(block) or {}).get("SELF_VALIDATION", {})

    fails = check(root=root)
    rd = readiness(root)

    if rd["unmet"]:
        # PENDING_OPS owner-action ids + LOOP_HEALTH validation.unmet (the two dashboard channels)
        oa_items = (_yaml_block(ROOT / "PENDING_OPS.md", "OWNER_ACTIONS").get("items") or [])
        oa_ids = {str(it.get("id", "")) for it in oa_items}
        lh_unmet = set((_yaml_block(ROOT / "docs/autonomous-loop/LOOP_HEALTH.md", "LOOP_HEALTH")
                        .get("validation", {}) or {}).get("unmet", []) or [])
        for cid in rd["unmet"]:
            fails.append(
                f"capability '{cid}' is ACTIVE but ci_validatable=false (needs an owner-only "
                f"secret) — UNMET, blocks merges until the owner provides it or it's gated off."
            )
            if f"validation-capability-{cid}" not in oa_ids:
                fails.append(
                    f"unmet '{cid}' is INVISIBLE to the owner: add an urgent OWNER_ACTION "
                    f"'validation-capability-{cid}' to PENDING_OPS (the dashboard channel)."
                )
            if cid not in lh_unmet:
                fails.append(
                    f"unmet '{cid}' is missing from LOOP_HEALTH validation.unmet — an unmet "
                    f"capability must appear in BOTH PENDING_OPS and LOOP_HEALTH or it's a bug."
                )
    return fails


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--readiness" in argv:
        # Compute + print the validation block the loop copies into LOOP_HEALTH each run.
        try:
            import yaml
            block = _fenced_yaml(MANIFEST.read_text())
            root = (yaml.safe_load(block) or {}).get("SELF_VALIDATION", {})
            rd = readiness(root)
            print(f"  validation: enforced_in_ci={rd['enforced_in_ci']} "
                  f"capabilities_total={rd['capabilities_total']} unmet={rd['unmet']}")
        except Exception as e:
            print(f"  self-validation readiness: FAIL ({e})")
            return 1
        fails = check_readiness(root=root)
        label = "self-validation readiness"
    else:
        fails = check()
        label = "self-validation coverage"
    if fails:
        print(f"  {label}: FAIL")
        for f in fails:
            print(f"    - {f}")
        return 1
    print(f"  {label}: OK (every active capability validated; all credentials declared; no unmet)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
