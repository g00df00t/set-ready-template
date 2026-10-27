"""Shared rate limiter — per IP for the public endpoints, per user for the
authenticated ones that call a model (see `user_or_ip` and `per_user`).

Authenticated routes are throttled naturally by the Supabase token round-trip in
auth.get_current_user; the public token/confirm/support routes have no such gate,
so we cap them per client IP here. The tokenized URL is still the primary access
control — this is a backstop against a single-IP abuse script or accidental hammering.

Storage is in-memory (per-process), which is fine for a single backend instance.
If we scale to multiple instances, point the Limiter at shared Redis storage so the
counts are global rather than per-process.
"""
from fastapi import Depends
from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from auth import get_current_user


def _client_ip(request: Request) -> str:
    # On Railway/Vercel the socket peer is the platform proxy, so the real client
    # is the first hop in X-Forwarded-For. Fall back to the socket address locally.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return get_remote_address(request)


def user_or_ip(request: Request) -> str:
    """Key for per-user limits on authenticated, expensive (AI) endpoints. The
    bearer token uniquely identifies the user's session, so a single account
    can't hammer Claude and run up the bill. Falls back to client IP."""
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return _client_ip(request)


def limit_by_user(request: Request, user_id: str = Depends(get_current_user)) -> str:
    """A route's auth dependency, for routes limited with `per_user`.

    Records the *verified* user id where the key function can read it. FastAPI
    resolves dependencies before slowapi's wrapper runs the limit check, so by
    the time `per_user` looks, the token has already been checked with Supabase
    — the key can't be forged by decoding a made-up JWT. FastAPI caches
    get_current_user within a request, so a route that also depends on
    get_accessible_owner_ids still makes one auth round trip, not two.
    """
    request.state.rate_limit_user = user_id
    return user_id


def per_user(request: Request) -> str:
    """Key for per-account limits on endpoints that spend money on every call.

    `user_or_ip` keys on the bearer token, which changes every time Supabase
    refreshes the session — so a token refresh quietly resets that budget. This
    keys on the account itself. Pair it with `limit_by_user` as the route's auth
    dependency; without it there is no verified id to read, and this falls back
    to `user_or_ip` rather than leaving the route unlimited.
    """
    user_id = getattr(request.state, "rate_limit_user", None)
    if user_id:
        return f"user:{user_id}"
    return user_or_ip(request)


#: Paste-a-list imports (Roster, and a day's Crew / Talent / Contacts page), per
#: account via `per_user`. Each is one model call at a cent or two; no producer
#: pastes 60 lists an hour, so this never bites real use, and it caps a retry
#: loop or a leaked login at a dollar or two an hour. Patrick, 2026-09-28.
PASTE_IMPORT_LIMIT = "60/hour"


limiter = Limiter(key_func=_client_ip)
