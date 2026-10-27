"""Where kept receipts live: the PRIVATE `receipts` bucket, one folder per job
({job_id}/{uuid}.{ext}). Never public — a receipt carries card digits and
names; routers/receipts.py serves one back only after the ownership check.

Rows cascade with their job; storage objects don't. So deleting a job, or an
account, removes the job's folder here — drafts that were read but never
confirmed included. Neither helper raises: a missing bucket means nothing was
ever kept, and cleanup must never be why a delete fails.
"""

import logging

from services.receipt_import import valid_path

logger = logging.getLogger(__name__)

BUCKET = "receipts"


def delete_job_receipts(client, job_id: str) -> None:
    try:
        files = client.storage.from_(BUCKET).list(str(job_id)) or []
        paths = [f"{job_id}/{f['name']}" for f in files if f.get("name")]
        if paths:
            client.storage.from_(BUCKET).remove(paths)
    except Exception:
        logger.warning("Could not clean up receipts for job %s", job_id, exc_info=True)


def remove_if_unused(client, job_id: str, path: str | None) -> None:
    """Remove a receipt file once no line on the job points at it. Several
    lines can share one (a statement read into many purchases)."""
    if not valid_path(job_id, path):
        return
    try:
        still = client.table("job_expenses").select("id").eq("job_id", str(job_id)).eq("receipt_path", path).execute().data
    except Exception:
        return          # no receipt columns: nothing was ever kept
    if still:
        return
    try:
        client.storage.from_(BUCKET).remove([path])
    except Exception:
        logger.warning("Could not remove a receipt file for job %s", job_id, exc_info=True)
