"""Master Access — the operator's view of the whole site.

Counts and metadata only, by design. A customer's shoot *content* (crew names,
call times, locations, client names, project names) is never read here and never
leaves the database. What this answers is "who is using this, how much, and what
is it costing me" — see usage_stats for where each number comes from and which
ones are floors rather than exact counts.

Access is a fixed allowlist of user ids in OWNER_USER_IDS, and it fails CLOSED:
an unset or empty variable locks everyone out, including the operator. That's
the safe direction for a misconfigured deploy — the alternative default, "no
owners configured means everyone is an owner", would expose every account's
usage the moment the variable was dropped from an environment.

Non-owners get 404 rather than 403 so the route's existence isn't confirmed to
someone probing for it.
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, Query, Request

import usage_stats
from auth import get_current_user
from config import settings
from database import get_client
from rate_limit import limiter

logger = logging.getLogger(__name__)
router = APIRouter(tags=["admin"])

NOT_FOUND = "Not found"


def owner_ids() -> set[str]:
    return {o.strip() for o in settings.owner_user_ids.split(",") if o.strip()}


def require_owner(user_id: str = Depends(get_current_user)) -> str:
    owners = owner_ids()
    if not owners:
        logger.warning("Master Access denied: OWNER_USER_IDS is not set")
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    if user_id not in owners:
        logger.warning("Master Access denied for user %s", user_id)
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    return user_id


@router.get("/admin/overview")
@limiter.limit("60/minute")
def overview(
    request: Request,
    days: int = Query(7, ge=1, le=365),
    _owner: str = Depends(require_owner),
):
    """Site-wide usage for the last `days` days.

    Rate-limited because it reads several tables end to end on every call; it is
    a dashboard refresh, not a hot path.
    """
    try:
        return usage_stats.collect(get_client(), days)
    except Exception as e:
        logger.warning("Master Access overview failed: %s: %s", type(e).__name__, e)
        raise HTTPException(status_code=503, detail="Couldn't load usage right now. Please try again.")
