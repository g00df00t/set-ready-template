"""First run of a producer's own copy: creating its owner.

Only when SINGLE_OWNER is set (docs/own-copy-plan.md). The hosted site has no
sign-up — accounts are invited from the Supabase dashboard — and a copy has
nobody to invite its first user, so this is the one way an account comes to
exist there. It works exactly once: while no owner exists, anyone who can reach
the copy may claim it, which is why the frontend sends the buyer here straight
from the login page and the skill has them do it in the same sitting as the
deploy. After that it refuses, and auth.get_current_user turns away every
account but the owner's, so sign-ups being on in a fresh Supabase project (the
default) no longer matters.

Both routes are public: the person setting up has no token yet.
"""
import logging
import re

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from auth import OWNER_MARK, _clean_display_name
from config import settings
from database import get_client
from rate_limit import limiter

logger = logging.getLogger(__name__)
router = APIRouter(tags=["setup"])

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_MIN_PASSWORD = 8
_PAGE = 200
_MAX_PAGES = 10    # 2,000 accounts; a copy is meant to hold one


class OwnerCreate(BaseModel):
    name: str
    email: str
    password: str


def owner_exists(client) -> bool:
    """Whether any account carries the owner mark. Pages through list_users
    because it caps at 50 per page by default and silently omits the rest."""
    for page in range(1, _MAX_PAGES + 1):
        users = client.auth.admin.list_users(page=page, per_page=_PAGE)
        if any((getattr(u, "app_metadata", None) or {}).get(OWNER_MARK) is True for u in users):
            return True
        if len(users) < _PAGE:
            return False
    return False


@router.get("/setup/status")
@limiter.limit("60/minute")
def status(request: Request):
    """What the login page needs to know: is this a copy, and has it been
    claimed. Says nothing about who the owner is."""
    if not settings.single_owner:
        return {"single_owner": False, "owner_exists": None}
    return {"single_owner": True, "owner_exists": owner_exists(get_client())}


@router.post("/setup/owner", status_code=201)
@limiter.limit("5/hour")
def create_owner(request: Request, body: OwnerCreate):
    if not settings.single_owner:
        raise HTTPException(status_code=404, detail="Not found")
    name = _clean_display_name(body.name)
    email = body.email.strip().lower()
    if not name:
        raise HTTPException(status_code=400, detail="Your name is required.")
    if not _EMAIL.match(email):
        raise HTTPException(status_code=400, detail="That doesn't look like an email address.")
    if len(body.password) < _MIN_PASSWORD:
        raise HTTPException(status_code=400, detail=f"Use a password of at least {_MIN_PASSWORD} characters.")

    client = get_client()
    if owner_exists(client):
        raise HTTPException(status_code=409, detail="This Set Ready already has an owner. Sign in instead.")
    try:
        client.auth.admin.create_user({
            "email": email,
            "password": body.password,
            "email_confirm": True,              # nobody's set up mail yet; the owner is trusted by construction
            "app_metadata": {OWNER_MARK: True},
            "user_metadata": {"full_name": name, "beta_jobs": True},
        })
    except Exception as e:
        logger.error("Creating the owner failed: %s: %s", type(e).__name__, e)
        raise HTTPException(status_code=500, detail="Couldn't create the account. Please try again.")
    logger.info("Owner created for this copy")
    return {"ok": True}
