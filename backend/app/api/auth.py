"""
Shared-secret bearer auth for the backend's STATE-MUTATING prediction-market routes.

THREAT MODEL. The frontend monitoring panel has its own password gate, but that gate
lives in the Next.js app — it does NOT protect the FastAPI backend. Anyone who can reach
the backend URL directly (a public deploy, a leaked origin) can today POST to the
kill-switch, risk-config, execute, and bot-control routes with no credential. This module
closes that gap with a server-side shared secret.

SAFE BY DEFAULT (degrades safely). ``BACKEND_API_TOKEN`` defaults to "" (unset):
  * UNSET  -> auth is DISABLED; every request passes. Preserves the current paper/dev
              behaviour exactly (local panel + tests keep working with no token), so
              turning the capability on is a deliberate owner step, never a silent break.
  * SET    -> the guarded routes REQUIRE ``Authorization: Bearer <token>``; a missing or
              wrong token is rejected with HTTP 401. The owner sets it on a public deploy
              (PENDING_OPS OA-14) and the frontend attaches it via a server-side proxy
              (so the secret is never shipped to the browser).

The authorization DECISION is the pure, fastapi-free :mod:`auth_core` (validated in the CI
gate, which does not install fastapi). This module is only the thin FastAPI adapter. The
autonomous loop NEVER sets this token — it is a deployment secret, like the live keys.
"""

from __future__ import annotations

from typing import Optional

from fastapi import Header, HTTPException

from ..auth_core import configured_token, is_request_authorized


def require_backend_token(authorization: Optional[str] = Header(default=None)) -> None:
    """FastAPI dependency: enforce the shared-secret bearer token when one is configured.

    No-op when ``BACKEND_API_TOKEN`` is unset (degrades safely). Raises 401 when a token is
    configured and the request's ``Authorization`` header does not match exactly.
    """
    if not is_request_authorized(configured_token(), authorization):
        raise HTTPException(status_code=401, detail="invalid or missing backend API token")
