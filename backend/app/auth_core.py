"""
Pure (fastapi-free) security primitive for the backend's shared-secret bearer auth.

The actual authorization DECISION lives here so it can be validated in the lightweight CI
gate (which does not install fastapi). ``auth.py`` is the thin FastAPI adapter that wires
this into the request path. Keeping the decision pure also makes it trivially testable and
free of framework behaviour.

POLICY (see auth.py for the full threat model):
  * token UNSET ("") -> auth DISABLED, every request allowed (degrades safely; unchanged
                        paper/dev behaviour).
  * token SET        -> require an exact ``Authorization: Bearer <token>`` (constant-time
                        compare); anything else is denied.
"""

from __future__ import annotations

import hmac
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def configured_token() -> str:
    """Return the configured backend token (best-effort; '' = auth disabled)."""
    try:
        from .config import get_settings
        return get_settings().backend_api_token or ""
    except Exception:  # pragma: no cover - defensive: never crash the request path
        # On a deploy that intentionally SET a token, a settings read failure here would
        # silently drop the guard — log at CRITICAL so an operator sees auth is open due to
        # a config error (the failure degrades to the documented unset/open default).
        logger.critical("[BACKEND AUTH] settings read FAILED; auth treated as DISABLED (open) — fix config")
        return ""


def is_request_authorized(token: str, authorization: Optional[str]) -> bool:
    """Pure decision: is a request with this ``Authorization`` header allowed?

    Empty/unset ``token`` => always allowed (auth disabled, degrades safely). Otherwise the
    header must equal ``"Bearer <token>"`` exactly, compared in constant time.
    """
    if not token:
        return True
    expected = f"Bearer {token}"
    return hmac.compare_digest(authorization or "", expected)
