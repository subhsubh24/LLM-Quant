"""
BUILDS != WORKS regression: init_db() must actually CREATE the durable singleton tables.

The audit log (G3), the alpha-lifecycle registry (B3), and the executor safety-state
(D3/D4 / run-risk-readiness) all persist to `table=True` singleton tables that live in
their own modules and are imported only LAZILY (inside orchestrator/executor construction,
which at app startup runs AFTER `init_db()`'s `create_all`). An adversarial auditor caught
that this made the tables NEVER get created in prod — every load/save hit "no such table"
and was silently swallowed, so the advertised cross-restart durability was a no-op.

`init_db()` now imports those modules so their tables register before `create_all`. This
test pins that end-to-end against a REAL fresh SQLite DB and FAILS LOUD if a durable table
goes missing again. It runs init_db in a CLEAN SUBPROCESS (fresh interpreter, fresh
metadata, a temp DATABASE_URL) so the result reflects the true cold-start prod path and is
not contaminated by tables other tests happened to import into the shared process.
"""

import subprocess
import sys
import textwrap


DURABLE_TABLES = [
    "prediction_audit_log",          # G3 audit log
    "prediction_strategy_registry",  # B3 alpha-lifecycle registry
    "prediction_executor_state",     # D3/D4 kill-switch + realized-PnL durability
]


def test_init_db_creates_durable_tables(tmp_path):
    db_path = tmp_path / "probe.db"
    # backend/ is the import root (canonical `app.*` path, matching conftest) — one level
    # up from this test file's dir (backend/tests/ -> backend/).
    backend_root = __file__.rsplit("/tests/", 1)[0]
    script = textwrap.dedent(
        f"""
        import os, sys, json
        sys.path.insert(0, {backend_root!r})
        os.environ["DATABASE_URL"] = "sqlite:///{db_path}"
        from app.db.database import init_db, engine
        from sqlmodel import Session, text
        init_db()
        with Session(engine) as s:
            names = sorted(r[0] for r in s.exec(text(
                "SELECT name FROM sqlite_master WHERE type='table'")))
        print(json.dumps(names))
        """
    )
    out = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, timeout=120,
    )
    assert out.returncode == 0, f"init_db subprocess failed:\n{out.stderr}"
    import json
    names = set(json.loads(out.stdout.strip().splitlines()[-1]))
    missing = [t for t in DURABLE_TABLES if t not in names]
    assert not missing, (
        f"init_db() did not create durable tables {missing} — cross-restart durability "
        f"(audit log / strategy registry / executor safety state) would silently no-op in "
        f"prod. Tables created: {sorted(names)}"
    )
