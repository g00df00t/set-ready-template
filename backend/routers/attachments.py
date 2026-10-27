"""Producer-supplied files that ride along with the call sheet email.

Set plots, layout diagrams, scout photo boards — the things a producer draws
themselves and that no map link can express. They are attachments only: they
never appear on the sheet, because a call sheet that shows everything gets read
for nothing.
"""

import logging
import re
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile

from auth import get_accessible_owner_ids
from database import get_client
from models.attachment import AttachmentResponse
from rate_limit import limiter, user_or_ip
from services.attachment_service import compress, human_size

logger = logging.getLogger(__name__)

router = APIRouter(tags=["attachments"])

BUCKET = "call-sheet-attachments"

# Generous, because Keynote exports are fat before we touch them — the file this
# was built for arrived at 23.6MB.
MAX_UPLOAD_BYTES = 60 * 1024 * 1024

# After compression. A single file bigger than this can't share a message with
# the call sheet PDF and still clear SendGrid's ~30MB ceiling once base64
# inflates everything by a third.
MAX_STORED_BYTES = 15 * 1024 * 1024

_ALLOWED = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


def _own_project(client, project_id: str, owner_ids: set[str]) -> dict:
    result = client.table("projects").select("id").eq("id", project_id).in_("owner_id", list(owner_ids)).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Project not found")
    return result.data[0]


def _safe_filename(name: str) -> str:
    """Keep the producer's own filename — crew see it in their mail client, and
    'Monday Aug 3 - Ogio Shoot Zones.pdf' tells them what it is. Strip only what
    a mail client or filesystem would choke on."""
    cleaned = re.sub(r"[/\\\r\n\t]", " ", name or "").strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:120] or "attachment"


@router.post("/projects/{project_id}/attachments", response_model=AttachmentResponse)
@limiter.limit("40/hour", key_func=user_or_ip)
async def upload_attachment(
    request: Request,
    project_id: UUID,
    file: UploadFile = File(...),
    owner_ids: set[str] = Depends(get_accessible_owner_ids),
):
    client = get_client()
    _own_project(client, str(project_id), owner_ids)

    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if content_type not in _ALLOWED:
        raise HTTPException(
            status_code=400,
            detail="Attach a PDF or an image (JPG, PNG, WEBP, GIF).",
        )

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="That file came through empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"That file is {human_size(len(data))}. The limit is {human_size(MAX_UPLOAD_BYTES)}.",
        )

    original_size = len(data)
    data = compress(data, content_type)

    if len(data) > MAX_STORED_BYTES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Even compressed, that file is {human_size(len(data))} — too big to email "
                f"alongside the call sheet. Try splitting it or exporting at a lower quality."
            ),
        )

    storage_path = f"{project_id}/{uuid4()}{_ALLOWED[content_type]}"
    try:
        client.storage.from_(BUCKET).upload(
            storage_path, data, {"content-type": content_type},
        )
    except Exception as e:
        logger.warning("Attachment upload to storage failed", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Could not store that file: {type(e).__name__}")

    existing = client.table("call_sheet_attachments").select("sort_order").eq("project_id", str(project_id)).execute().data
    next_order = max((row["sort_order"] for row in existing), default=-1) + 1

    result = client.table("call_sheet_attachments").insert({
        "project_id": str(project_id),
        "filename": _safe_filename(file.filename),
        "storage_path": storage_path,
        "content_type": content_type,
        "byte_size": len(data),
        "original_byte_size": original_size,
        "sort_order": next_order,
    }).execute()
    return result.data[0]


@router.get("/projects/{project_id}/attachments", response_model=list[AttachmentResponse])
def list_attachments(project_id: UUID, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    _own_project(client, str(project_id), owner_ids)
    return client.table("call_sheet_attachments").select("*").eq("project_id", str(project_id)).order("sort_order").execute().data


@router.delete("/projects/{project_id}/attachments/{attachment_id}")
def delete_attachment(project_id: UUID, attachment_id: UUID, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    _own_project(client, str(project_id), owner_ids)
    # Scoped to the project as well as the id, so an attachment id from someone
    # else's job can't be deleted by guessing it.
    found = client.table("call_sheet_attachments").select("*").eq("id", str(attachment_id)).eq("project_id", str(project_id)).execute()
    if not found.data:
        raise HTTPException(status_code=404, detail="Attachment not found")

    # Storage first: a row with no file behind it would break every later send,
    # whereas a file with no row is invisible and gets swept with the project.
    try:
        client.storage.from_(BUCKET).remove([found.data[0]["storage_path"]])
    except Exception:
        logger.warning("Could not remove attachment from storage", exc_info=True)
    client.table("call_sheet_attachments").delete().eq("id", str(attachment_id)).execute()
    return {"ok": True}


def fetch_attachment_files(client, project_id: str) -> list[tuple[bytes, str, str]]:
    """(bytes, filename, content_type) for every attachment on a project.

    Used by the send path. A file that can't be downloaded is skipped rather
    than raising — a missing set plot should not stop the call sheet itself
    from reaching the crew.
    """
    # Guarded like the read itself: sending the call sheet is the one action on
    # a shoot day that must not fail, and an optional set plot must never be the
    # reason a crew doesn't get their sheet.
    try:
        rows = client.table("call_sheet_attachments").select("*").eq("project_id", project_id).order("sort_order").execute().data
    except Exception:
        logger.warning("call_sheet_attachments unavailable — has the migration been run?", exc_info=True)
        return []
    files = []
    for row in rows or []:
        try:
            files.append((
                client.storage.from_(BUCKET).download(row["storage_path"]),
                row["filename"],
                row["content_type"],
            ))
        except Exception:
            logger.warning("Skipping unreadable attachment %s", row.get("id"), exc_info=True)
    return files


def delete_project_attachments(client, project_id: str) -> None:
    """Remove a project's stored files. The metadata rows cascade with the
    project, but storage objects do not — without this, deleting a project (or
    an account) would leave the producer's files sitting in the bucket."""
    rows = client.table("call_sheet_attachments").select("storage_path").eq("project_id", project_id).execute().data
    paths = [row["storage_path"] for row in rows or []]
    if not paths:
        return
    try:
        client.storage.from_(BUCKET).remove(paths)
    except Exception:
        logger.warning("Could not clean up attachments for project %s", project_id, exc_info=True)
