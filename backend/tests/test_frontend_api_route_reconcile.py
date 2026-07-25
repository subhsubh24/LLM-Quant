"""Every frontend fetch URL must resolve to a route the backend actually serves.

This is a DOC/CODE reconciliation guard for a defect class that no existing check caught:
`MetricsPanel.tsx` fetched all six metrics endpoints WITHOUT the `/api` prefix that
`main.py` mounts the router under, so the whole Metrics tab rendered six stacked
"Failed to load: HTTP 404" cards in every configuration — and did so undetected from
2026-07-17 until the independent Quality Auditor found it by reading the rendered page.

Nothing structural could have caught it: the frontend has no test suite and no lint rule
that validates URLs, and TypeScript cannot type-check a template-literal path against a
Python router. So the check lives here, in the gate that actually runs.

It parses the committed `.tsx` sources for fetch URLs and asserts each one has a matching
`@router.get/post/...` decorator in `routes.py`, accounting for the `/api` mount prefix.
Pure text analysis — no network, no Node, no running backend.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND = REPO_ROOT / "frontend"
ROUTES_PY = REPO_ROOT / "backend" / "app" / "api" / "routes.py"
MAIN_PY = REPO_ROOT / "backend" / "app" / "api" / "main.py"

# A fetch URL built from the API base, e.g. `${API_BASE}/api/prediction-markets/markets`
# or `${METRICS_BASE}/weekly` where METRICS_BASE itself is an API_BASE-rooted constant.
_URL_IN_TEMPLATE = re.compile(r"`\$\{(\w+)\}(/[A-Za-z0-9\-_/${}]*)`")
_CONST_DEF = re.compile(r"^const (\w+) = `\$\{(\w+)\}(/[A-Za-z0-9\-_/]*)`", re.MULTILINE)
_ROUTE_DECORATOR = re.compile(r'@router\.(?:get|post|put|patch|delete)\(\s*"([^"]+)"')
_MOUNT_PREFIX = re.compile(r'include_router\(\s*router\s*,\s*prefix="([^"]+)"')


def _mount_prefix() -> str:
    if not MAIN_PY.exists():
        pytest.skip("backend/app/api/main.py not present")
    m = _MOUNT_PREFIX.search(MAIN_PY.read_text())
    return m.group(1) if m else ""


def _backend_routes() -> set:
    if not ROUTES_PY.exists():
        pytest.skip("backend/app/api/routes.py not present")
    prefix = _mount_prefix()
    return {prefix + p for p in _ROUTE_DECORATOR.findall(ROUTES_PY.read_text())}


def _frontend_paths():
    """(file, path) for every API-base-rooted fetch URL in the committed frontend."""
    if not FRONTEND.exists():
        pytest.skip("frontend/ not present")
    found = []
    for src in sorted(FRONTEND.rglob("*.tsx")):
        if "node_modules" in src.parts:
            continue
        text = src.read_text()
        # Resolve intermediate constants (e.g. METRICS_BASE) down to their API_BASE suffix.
        bases = {"API_BASE": ""}
        for _ in range(3):  # a couple of passes is plenty; guards against a cycle
            for name, parent, suffix in _CONST_DEF.findall(text):
                if parent in bases:
                    bases[name] = bases[parent] + suffix
        for base, suffix in _URL_IN_TEMPLATE.findall(text):
            if base not in bases:
                continue  # not rooted at the API base (e.g. a purely local template)
            path = bases[base] + suffix
            if "${" in path:
                # A path with a runtime-interpolated segment (an id, a strategy name).
                # Compare only the literal prefix before the first interpolation.
                path = path.split("${", 1)[0].rstrip("/")
            found.append((src.relative_to(REPO_ROOT), path.split("?", 1)[0]))
    return found


def test_frontend_fetch_paths_resolve_to_real_backend_routes():
    routes = _backend_routes()
    assert routes, "no backend routes parsed — the guard would be vacuous"

    frontend_paths = _frontend_paths()
    assert frontend_paths, "no frontend fetch URLs parsed — the guard would be vacuous"

    broken = []
    for src, path in frontend_paths:
        # Exact match, or a literal prefix of a parameterized route.
        if path in routes:
            continue
        if any(r.startswith(path.rstrip("/") + "/") for r in routes):
            continue
        broken.append(f"{src}: {path}")

    assert not broken, (
        "frontend fetches a path the backend does not serve (these 404 at runtime):\n  "
        + "\n  ".join(sorted(broken))
        + f"\n\nBackend mounts the router at {_mount_prefix()!r}."
    )


def test_metrics_panel_uses_the_api_prefix():
    """A targeted regression pin for the specific defect, so a future refactor that drops
    the shared constant still fails here with an obvious message."""
    panel = FRONTEND / "components" / "metrics" / "MetricsPanel.tsx"
    if not panel.exists():
        pytest.skip("MetricsPanel.tsx not present")
    text = panel.read_text()
    assert "${API_BASE}/prediction-markets/" not in text, (
        "MetricsPanel fetches without the /api prefix — every one of these 404s and the "
        "Metrics tab renders stacked error cards"
    )
    assert "/api/prediction-markets/metrics" in text
