"""Budget tab → "Read an estimate": a PDF or Excel estimate in, DRAFT budget
lines out, each with a suggested basis for the producer to confirm
(services/estimate_import.py decides what's read). Nothing is added here —
she checks the drafts and the kept ones go through routers/budget.py's
POST .../budget/lines/batch. The file itself isn't kept: once its lines are
on the budget it has done its job, and an estimate names a client and prices.

Refused on a signed estimate before any model call — its lines couldn't be
added anyway. Every route gates on the job through jobs._own_job, so team
sharing covers it.
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool

import usage
from auth import get_accessible_owner_ids
from database import get_client
from rate_limit import limit_by_user, limiter, per_user
from routers.budget import SIGNED, _signed
from routers.jobs import _own_job
from routers.receipts import _read_capped
from services import estimate_import

logger = logging.getLogger(__name__)
router = APIRouter(tags=["estimate-import"])

#: Per account. An estimate is one model call of a few cents, and a job has one
#: estimate (maybe a revision or two) — this only caps a retry loop.
ESTIMATE_READ_LIMIT = "30/hour"


@router.post("/jobs/{job_id}/budget/import")
@limiter.limit(ESTIMATE_READ_LIMIT, key_func=per_user)
async def read_estimate(
    request: Request,
    job_id: UUID,
    user_id: str = Depends(limit_by_user),
    owner_ids: set[str] = Depends(get_accessible_owner_ids),
):
    """One estimate (the body is the file itself) → draft lines + the total check."""
    client = get_client()
    job = _own_job(client, str(job_id), owner_ids)
    if _signed(job):
        raise HTTPException(status_code=409, detail=SIGNED)
    try:
        data = await _read_capped(request, estimate_import.MAX_BYTES)
        out = await run_in_threadpool(
            estimate_import.read_estimate, data,
            usage.import_recorder(client, job["owner_id"], None, usage.IMPORT_ESTIMATE))
    except estimate_import.Rejected as e:
        raise HTTPException(status_code=e.status, detail=str(e))
    except Exception as e:
        # The type only: the exception text can quote what the estimate says.
        logger.warning("estimate read failed for user %s: %s", user_id, type(e).__name__)
        raise HTTPException(status_code=502, detail="Couldn't read that estimate. Try again, or add its lines by hand.")
    note = None if out["lines"] else "No priced lines could be read on that estimate. Add them by hand instead."
    logger.info("estimate read for user %s: %d lines, %d skipped", user_id, len(out["lines"]), out["skipped"])
    return {**out, "note": note}
