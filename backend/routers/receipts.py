"""Receipts on the PC log: read one with Claude into draft lines, keep the file
with the lines the producer confirms, and serve it back to her alone
(services/receipt_import.py decides what's read; routers/budget.py adds the
lines she keeps, with their receipt_path).

One request per file: the page loops over a batch. Nothing is added to the log
here — a read returns DRAFTS; she checks them and adds the ones she wants.

The file goes in the PRIVATE `receipts` bucket at {job_id}/{uuid}.{ext}, so a
job's receipts are one folder: deleting the job (or the account) removes it,
drafts she never confirmed included. Downloads proxy through here after the
ownership check — the bucket is never public, receipts carry card digits and
names. Until supabase/receipts.sql has run, or while the bucket doesn't exist,
receipts are still read and their lines still added; only the file isn't kept.

Every route gates on the job through jobs._own_job, so team sharing covers it.
"""

import logging
from urllib.parse import quote
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from starlette.concurrency import run_in_threadpool

import usage
from auth import get_accessible_owner_ids
from database import get_client
from rate_limit import limit_by_user, limiter, per_user
from routers.budget import _is_missing_table
from routers.jobs import _own_job
from services import receipt_import
from services.receipt_import import clean_name, valid_path
from services.receipt_store import BUCKET, remove_if_unused
from services.pc_log import CATEGORIES

logger = logging.getLogger(__name__)
router = APIRouter(tags=["receipts"])

#: Per account. A receipt is one model call at about a cent; a producer may drop
#: thirty after a job, so this is roomy — it only caps a retry loop or a leaked
#: login at a couple of dollars an hour.
RECEIPT_READ_LIMIT = "120/hour"

_TYPES = set(receipt_import.EXTENSIONS)


def receipts_migrated(client) -> bool:
    try:
        client.table("job_expenses").select("receipt_path").limit(1).execute()
        return True
    except Exception as e:
        if _is_missing_table(e) or "receipt_path" in str(e):
            return False
        raise


async def _read_capped(request: Request, limit: int) -> bytes:
    """The raw body, refusing to read past `limit` — never spooled to disk."""
    too_big = receipt_import.Rejected(f"That file is too big. A receipt can be up to {limit // (1024 * 1024)} MB.", status=413)
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise too_big
    chunks, total = [], 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > limit:
            raise too_big
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/jobs/{job_id}/receipts/read")
@limiter.limit(RECEIPT_READ_LIMIT, key_func=per_user)
async def read_receipt(
    request: Request,
    job_id: UUID,
    category: str | None = None,
    filename: str | None = None,
    user_id: str = Depends(limit_by_user),
    owner_ids: set[str] = Depends(get_accessible_owner_ids),
):
    """One receipt (the body is the file itself) → draft lines, and the kept
    file they'll point at. `category` is "these are all…" for a labelled batch."""
    client = get_client()
    job = _own_job(client, str(job_id), owner_ids)
    if category is not None and category not in CATEGORIES:
        raise HTTPException(status_code=422, detail="Pick one of the PC log's columns.")
    try:
        data = await _read_capped(request, receipt_import.MAX_BYTES)
        kept, media_type, lines = await run_in_threadpool(
            receipt_import.read_receipt, data, category,
            usage.import_recorder(client, job["owner_id"], None, usage.IMPORT_RECEIPT))
    except receipt_import.Rejected as e:
        raise HTTPException(status_code=e.status, detail=str(e))
    except Exception as e:
        # The type only: the exception text can quote what the receipt says.
        logger.warning("receipt read failed for user %s: %s", user_id, type(e).__name__)
        raise HTTPException(status_code=502, detail="Couldn't read that receipt. Try again, or type it in.")

    receipt, note = None, None
    if not lines:
        note = "No total could be read on that receipt. Type it in instead."
    elif not await run_in_threadpool(receipts_migrated, client):
        note = "The receipt was read, but this server can't keep a copy of it yet."
    else:
        path = f"{job_id}/{uuid4()}{receipt_import.EXTENSIONS[media_type]}"
        try:
            await run_in_threadpool(lambda: client.storage.from_(BUCKET).upload(path, kept, {"content-type": media_type}))
            receipt = {"receipt_path": path, "receipt_name": clean_name(filename), "receipt_type": media_type}
        except Exception:
            logger.warning("Receipt not kept for job %s (is the bucket there?)", job_id, exc_info=True)
            note = "The receipt was read, but a copy couldn't be kept with it."
    logger.info("receipt read for user %s: %d lines, kept=%s", user_id, len(lines), bool(receipt))
    return {"lines": lines, "receipt": receipt, "note": note}


@router.delete("/jobs/{job_id}/receipts")
def discard_receipt(job_id: UUID, path: str, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    """A draft she didn't keep: its file goes, unless a line already uses it."""
    client = get_client()
    _own_job(client, str(job_id), owner_ids)
    if not valid_path(str(job_id), path):
        raise HTTPException(status_code=404, detail="That receipt isn't on this job.")
    remove_if_unused(client, str(job_id), path)
    return {"ok": True}


@router.get("/jobs/{job_id}/expenses/{expense_id}/receipt")
def get_receipt(job_id: UUID, expense_id: str, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    """The receipt behind one line, to whoever may open the job — and nobody else."""
    client = get_client()
    _own_job(client, str(job_id), owner_ids)
    try:
        rows = client.table("job_expenses").select("id,receipt_path,receipt_name,receipt_type") \
            .eq("id", expense_id).eq("job_id", str(job_id)).execute().data
    except Exception:
        rows = []
    row = rows[0] if rows else None
    if not row or not valid_path(str(job_id), row.get("receipt_path")) or row.get("receipt_type") not in _TYPES:
        raise HTTPException(status_code=404, detail="There's no receipt kept with that line.")
    try:
        data = client.storage.from_(BUCKET).download(row["receipt_path"])
    except Exception:
        logger.warning("Receipt download failed for job %s", job_id, exc_info=True)
        raise HTTPException(status_code=404, detail="That receipt couldn't be found.")
    name = clean_name(row.get("receipt_name"))
    return Response(content=data, media_type=row["receipt_type"],
                    headers={"Content-Disposition": f"inline; filename*=UTF-8''{quote(name)}",
                             "X-Content-Type-Options": "nosniff"})
