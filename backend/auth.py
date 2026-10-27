import logging
import re
import httpx
from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from supabase_auth.errors import AuthApiError, AuthRetryableError
from config import settings
from database import RETRY_ERRORS, get_client

logger = logging.getLogger(__name__)
security = HTTPBearer()

UNREACHABLE_DETAIL = "Couldn't reach the server. Please try again."


def _is_unreachable(exc: Exception) -> bool:
    """True when we never got an answer about the token, as opposed to being
    told it's bad.

    The distinction matters because the two need opposite handling. A rejected
    token is final: stop, sign in again. A network blip is not: retry. Reporting
    the second as the first is what made a dropped connection surface to a
    producer as "Invalid token" on a session that was perfectly valid, and stop
    the frontend retrying, since it treats a 401 as a real answer.

    httpx.TransportError is the connection failing (read/connect/timeout);
    note HTTPStatusError is deliberately NOT one of its subclasses, so a real
    403 from Supabase still falls through to a 401 here.
    """
    if isinstance(exc, (httpx.TransportError, AuthRetryableError)):
        return True
    # Supabase answered, but with its own failure — 5xx is theirs, not the token's.
    return isinstance(exc, AuthApiError) and (exc.status or 0) >= 500


def _get_user(token: str):
    """get_user, retried ONCE when the pooled connection under it was already
    dead — the same failure database.py retries for PostgREST reads. Auth was
    left out of that, so after a quiet spell the first burst of page loads
    (every request checks its token) could each answer 503 — seen twice on
    production on 2026-10-02, opening a job's Pre-production tab. get_user is a
    read (GET /auth/v1/user), so a retry can't repeat anything. Any other
    failure, or a second one, is handled by the caller exactly as before."""
    try:
        return get_client().auth.get_user(token)
    except RETRY_ERRORS as e:
        logger.warning("Auth check: %s on a pooled connection; retrying once", type(e).__name__)
        return get_client().auth.get_user(token)


def get_current_user(credentials: HTTPAuthorizationCredentials = Security(security)) -> str:
    token = credentials.credentials
    try:
        response = _get_user(token)
    except Exception as e:
        if _is_unreachable(e):
            # 503, not 401: nothing is wrong with the caller's session, and the
            # frontend already retries 5xx on reads.
            logger.warning("Auth check could not reach Supabase: %s: %s", type(e).__name__, e)
            raise HTTPException(status_code=503, detail=UNREACHABLE_DETAIL)
        # Anything else is treated as a rejection — failing closed is the only
        # safe default for an unrecognised error in an auth path.
        logger.warning("Auth failed: %s: %s", type(e).__name__, e)
        raise HTTPException(status_code=401, detail="Invalid token")
    if not response.user:
        raise HTTPException(status_code=401, detail="Invalid token")
    if settings.single_owner and not is_owner(response.user):
        # A copy belongs to one person. The publishable key is in the page
        # source by design, and a fresh Supabase project accepts sign-ups by
        # default, so without this a stranger could make themselves an account
        # and use the owner's backend — their AI key, their mail — as a second
        # user. 403, not 404: the copy isn't hiding, it's just not theirs.
        raise HTTPException(status_code=403, detail=NOT_OWNER_DETAIL)
    return response.user.id


NOT_OWNER_DETAIL = "This Set Ready belongs to someone else."

# Set by routers/setup.py when the owner is created. app_metadata, not
# user_metadata: user_metadata is writable by the user through Supabase's own
# auth API, so anyone who got an account could promote themselves. app_metadata
# is only writable with the secret key, which only the backend holds.
OWNER_MARK = "set_ready_owner"


def is_owner(user) -> bool:
    return (getattr(user, "app_metadata", None) or {}).get(OWNER_MARK) is True


def get_accessible_owner_ids(user_id: str = Depends(get_current_user)) -> set[str]:
    """Every owner_id this user may read: themselves, plus any owner whose
    team they've accepted an invite to.

    {user_id} is unioned in rather than replaced, so someone who had their own
    projects before accepting an invite doesn't lose access to them the moment
    they join a team — accepting an invite only ever adds reach, never removes
    it.

    Every `.eq("owner_id", user_id)` a route used for reading is meant to
    become `.in_("owner_id", get_accessible_owner_ids(...))`. Writes are a
    different question — see get_write_owner_id below — because a set has no
    single answer for "which owner_id does a new row belong to".
    """
    if settings.single_owner:
        return {user_id}   # one person, no team: skip the round trip every request would pay
    client = get_client()
    rows = (client.table("team_members").select("owner_id")
            .eq("member_user_id", user_id).eq("status", "accepted").execute().data)
    return {user_id} | {r["owner_id"] for r in rows}


def get_write_owner_id(user_id: str = Depends(get_current_user)) -> str:
    """The single owner_id a new row this user creates belongs to.

    A person can be an accepted team member of at most one owner at a time
    (enforced by a unique constraint on team_members — see
    docs/team-sharing-plan.md §3 for why: a write has to pick one owner_id,
    and nothing here should be guessing which of several teams a person meant
    when they hit Save). So this never has to choose between candidates: it's
    either the one team they've joined, or themselves.
    """
    if settings.single_owner:
        return user_id
    client = get_client()
    rows = (client.table("team_members").select("owner_id")
            .eq("member_user_id", user_id).eq("status", "accepted").execute().data)
    return rows[0]["owner_id"] if rows else user_id


# A display name is bounded and single-line before it goes anywhere near a mail
# header. This is not belt-and-braces: user_metadata is writable by the user
# through Supabase's own auth API, so whatever the account page does or doesn't
# allow, this value arrives from the client and lands in the From header of mail
# sent to a producer's whole crew. A newline in it is header injection.
_NAME_MAX = 80


def _clean_display_name(raw) -> str | None:
    """One line, bounded length, or nothing at all."""
    if not isinstance(raw, str):
        return None
    # Whitespace FIRST, and the order is load-bearing. str.split() treats tabs,
    # newlines and returns alike, so every one of them becomes a single space and
    # word boundaries survive. Doing it the other way round drops the character
    # entirely and welds the words together — "Pat<tab>Kehoe" came out as
    # "PatKehoe", which a test caught.
    cleaned = " ".join(raw.split())
    # Then remove what is left that cannot be printed — NUL, escapes, the things
    # that confuse downstream encoders. These are not separators, so deleting
    # them is right. Everything printable stays, which keeps accents,
    # apostrophes and non-Latin scripts intact.
    cleaned = "".join(ch for ch in cleaned if ch.isprintable())
    if not cleaned:
        return None
    return cleaned[:_NAME_MAX].strip() or None


_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _is_our_asset(url) -> bool:
    """True only for a public object in our own brand bucket.

    The brand image URL is written by the browser into user_metadata, which
    means a value could be anything by the time the backend reads it back. It
    lands in an <img src> on a page opened by crew who have no account, so it
    is validated against the project's own storage origin.
    """
    if not isinstance(url, str):
        return False
    prefix = f"{settings.supabase_url.rstrip('/')}/storage/v1/object/public/brand-assets/"
    return url.startswith(prefix) and "\n" not in url and "\r" not in url


def get_user_brand(user_id: str) -> dict:
    """A producer's company name and accent colour, for the screens their crew
    open — the confirm page, and a shared wrap report.

    The signed-in app reads this straight off the session, but nobody looking at
    those pages has a session or an account, so it has to come through the API.

    ⚠️ The colour is re-validated here rather than trusted. It was written by a
    browser calling Supabase's auth API directly, so the backend has never seen
    it before this moment, and it is about to land in a style attribute.
    Anything that isn't exactly #rrggbb becomes None — there is no half-valid
    colour worth rescuing.
    """
    try:
        client = get_client()
        meta = (client.auth.admin.get_user_by_id(user_id).user.user_metadata) or {}
        accent = meta.get("brand_accent")
        image = meta.get("brand_image_url")
        background = meta.get("brand_background_url")
        return {
            "name": _clean_display_name(meta.get("brand_name")),
            "accent": accent.lower() if isinstance(accent, str) and _HEX.match(accent) else None,
            # Only a URL we issued. The value round-tripped through a browser,
            # so it is checked against our own storage prefix rather than
            # trusted — otherwise this field is an open redirect for an <img>
            # on every crew member's confirm page.
            "image_url": image if _is_our_asset(image) else None,
            # Whether the artwork is a finished title card with the name already
            # in it. The confirm page has no session, so this has to travel too
            # — without it a producer's own title card gets our wordmark set on
            # top of it for every crew member.
            "image_has_name": meta.get("brand_image_has_name") is True,
            # The plain artwork the page mastheads sit over. Same validation:
            # it round-tripped through a browser and is about to become a CSS
            # background on a page opened by someone with no account.
            "background_url": background if _is_our_asset(background) else None,
        }
    except Exception as e:
        logger.warning("Could not load brand for %s: %s", user_id, e)
        return {"name": None, "accent": None}


def get_user_identity(user_id: str) -> dict:
    """Look up a producer's display name + email for use as the email sender
    identity (From display name + Reply-To). Falls back gracefully so a missing
    name never blocks a send.

    Prefers full_name: it is the name crew know the producer by, which is the
    whole point of the From line. `company` is still read as a fallback because
    some accounts were seeded with it before there was any UI to set a name."""
    try:
        client = get_client()
        user = client.auth.admin.get_user_by_id(user_id).user
        meta = user.user_metadata or {}
        name = _clean_display_name(meta.get("full_name")) or _clean_display_name(meta.get("company"))
        return {"name": name, "email": user.email}
    except Exception as e:
        logger.warning("Could not load user identity for %s: %s", user_id, e)
        return {"name": None, "email": None}
