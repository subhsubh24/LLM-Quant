"""
Shared-secret bearer auth for the backend's STATE-MUTATING prediction-market routes.

THREAT MODEL. The frontend monitoring panel has its own password gate, but that gate
lives in the Next.js app — it does NOT protect the FastAPI backend. Anyone who can reach
the backend URL directly (a public deploy, a leaked origin) can today POST to the
kill-switch, risk-config, execute, and bot-control routes with no credential. This module
closes that gap with a server-side shared secret.

SECURE BY DEFAULT (fail-closed). The guarded routes are CLOSED unless explicitly opened:
  * DEFAULT (no token, no opt-out) -> DENY every mutating request with HTTP 401. A public
              paper deploy that forgets to set a token is therefore NOT silently
              unauthenticated — it exposes no kill-switch/execute/bot-control surface.
  * ``BACKEND_API_TOKEN`` set        -> the guarded routes REQUIRE ``Authorization: Bearer
              <token>``; a missing/wrong token is 401. The owner sets it on a public deploy
              (PENDING_OPS OA-14 step 1).
              NOT YET BUILT — the frontend has no way to send this token. OA-14 step (2),
              a server-side proxy that injects the header from a server-only env var (so
              the secret never reaches the browser), is still OPEN. An earlier version of
              this docstring described that proxy in the PRESENT tense, as though it
              existed; it does not, and there are zero ``BACKEND_API_TOKEN`` references
              under ``frontend/`` to back the claim. The consequence today is fail-CLOSED
              and therefore safe — setting the token makes the monitoring panel 401 rather
              than leaking the secret — but a reader was being told a control was in place
              when it was not.
  * ``BACKEND_AUTH_DISABLED=1``      -> explicit dev/paper opt-out: run OPEN on a trusted
              single-user host (local dev, tests). NEVER honoured with real money — config
              refuses to boot if it is set while ``LIVE_TRADING_ENABLED`` is on.

The authorization DECISION for a configured token is the pure, fastapi-free :mod:`auth_core`
(validated in the CI gate, which does not install fastapi). This module is the thin FastAPI
adapter and owns the default-closed / opt-out POLICY. The autonomous loop NEVER sets the
token or the opt-out — they are deployment config, like the live keys.
"""

from __future__ import annotations

from typing import Optional

from fastapi import Header, HTTPException

from ..auth_core import configured_token, is_request_authorized


def require_backend_token(authorization: Optional[str] = Header(default=None)) -> None:
    """FastAPI dependency: enforce the shared-secret bearer token (default-closed).

    Policy: DENY by default. Allow only when the dev opt-out ``BACKEND_AUTH_DISABLED`` is set
    (trusted-host dev/paper) or when a configured ``BACKEND_API_TOKEN`` matches the request's
    ``Authorization`` header exactly (constant-time). A public deploy that sets neither is
    fail-closed (401), never silently open.
    """
    # Import get_settings lazily (like auth_core.configured_token) so a test monkeypatch of
    # config.get_settings is respected, and so a settings-read failure fails CLOSED.
    try:
        from ..config import get_settings
        auth_disabled = bool(get_settings().backend_auth_disabled)
    except Exception:  # pragma: no cover - defensive: a settings read failure fails CLOSED
        auth_disabled = False
    if auth_disabled:
        return
    token = configured_token()
    if not token:
        raise HTTPException(
            status_code=401,
            detail="backend control auth required — set BACKEND_API_TOKEN (or BACKEND_AUTH_DISABLED=1 for local dev)",
        )
    if not is_request_authorized(token, authorization):
        raise HTTPException(status_code=401, detail="invalid or missing backend API token")
