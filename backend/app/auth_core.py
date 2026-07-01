"""
Pure (fastapi-free) security primitive for the backend's shared-secret bearer auth.

The actual authorization DECISION lives here so it can be validated in the lightweight CI
gate (which does not install fastapi). ``auth.py`` is the thin FastAPI adapter that wires
this into the request path. Keeping the decision pure also makes it trivially testable and
free of framework behaviour.

This is the PURE PRIMITIVE only — it answers "does THIS token authorize THIS header".
The ENFORCED system policy is DEFAULT-CLOSED and lives in the ``auth.py`` adapter: an
absent token DENIES (401) unless the ``BACKEND_AUTH_DISABLED`` dev opt-out is set. So the
"empty token -> allowed" branch below is NOT the system default — the adapter never calls
this with an empty token (it 401s first). Do not read this file alone as the runtime story.

PRIMITIVE decision (what this module returns; see auth.py for the enforced policy + threat model):
  * token "" (empty)  -> returns True (auth-disabled sentinel). The ADAPTER does not reach
                         this branch — it treats an unset token as DENY (default-closed).
  * token SET         -> require an exact ``Authorization: Bearer <token>`` (constant-time
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
        # A settings read failure returns "" (no token). NOTE: the auth.py adapter is
        # DEFAULT-CLOSED, so an empty token there means DENY (401) — a config error
        # fails CLOSED, not open. Log at CRITICAL so an operator fixes the config.
        logger.critical("[BACKEND AUTH] settings read FAILED; no token -> control routes DENY (fail-closed) — fix config")
        return ""


def is_request_authorized(token: str, authorization: Optional[str]) -> bool:
    """Pure decision: is a request with this ``Authorization`` header allowed?

    Empty/unset ``token`` => returns True (the auth-disabled sentinel of the PURE primitive).
    The default-closed policy lives in the ``auth.py`` adapter, which does NOT call this with
    an empty token (it denies first). Otherwise the header must equal ``"Bearer <token>"``
    exactly, compared in constant time.
    """
    if not token:
        return True
    expected = f"Bearer {token}"
    return hmac.compare_digest(authorization or "", expected)
