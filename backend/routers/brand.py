"""A producer's title-card artwork.

The name and the colour live in Supabase user_metadata, written straight from
the browser — no backend involved. The image can't work that way: it needs
re-encoding, a size ceiling, and somewhere public to live, because the people
who see it (a crew member on a confirm page, a client on a shared wrap report)
have no account and cannot authenticate against anything.

Hence a **public** bucket, separate from call-sheet-attachments, which is
private and proxies its downloads through the backend. Two different postures
on purpose: a company's own brand art is meant to be seen by anyone holding the
link, and a producer's set plots are not.
"""

import logging
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from auth import get_current_user
from database import get_client
from rate_limit import limiter, user_or_ip
from services.attachment_service import human_size
from services.brand_image import UnreadableImage, prepare

logger = logging.getLogger(__name__)

router = APIRouter(tags=["brand"])

BUCKET = "brand-assets"

_ALLOWED = {"image/jpeg", "image/png", "image/webp"}

#: Before re-encoding. A phone photo or an export from a painting app arrives
#: fat; prepare() brings it down to something a crew member can load on mobile
#: data. This ceiling only exists to stop someone streaming a 200MB TIFF.
MAX_UPLOAD_BYTES = 25 * 1024 * 1024

#: Two pictures, because the two surfaces want different ones. "card" is the
#: finished title card — typography included — that fronts a call sheet on
#: screen. "background" is the plain artwork the app's page mastheads are set
#: over; anything painted into that one fights the page title sitting on it.
#: One producer, one of each, replaced independently.
_SLOTS = ("card", "background")


@router.post("/brand/image")
@limiter.limit("20/hour", key_func=user_or_ip)
async def upload_brand_image(
    request: Request,
    file: UploadFile = File(...),
    slot: str = Form("card"),
    user_id: str = Depends(get_current_user),
):
    if slot not in _SLOTS:
        raise HTTPException(status_code=400, detail="Unknown image slot.")
    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if content_type not in _ALLOWED:
        raise HTTPException(status_code=400, detail="Use a JPG, PNG or WEBP image.")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="That file came through empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"That image is {human_size(len(data))}. The limit is {human_size(MAX_UPLOAD_BYTES)}.",
        )

    try:
        jpeg, width, height = prepare(data)
    except UnreadableImage:
        raise HTTPException(status_code=400, detail="That file didn't open as an image.")

    client = get_client()
    # Keyed by user, and a fresh name every time. Overwriting one fixed path
    # would be tidier and wrong: the old URL is already cached by every browser
    # and CDN that has seen it, so a producer replacing their artwork would keep
    # seeing the previous one and conclude the upload silently failed.
    path = f"{user_id}/{slot}-{uuid4()}.jpg"
    try:
        client.storage.from_(BUCKET).upload(path, jpeg, {"content-type": "image/jpeg"})
    except Exception as e:  # noqa: BLE001
        logger.warning("Brand image upload failed", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Could not store that image: {type(e).__name__}")

    url = client.storage.from_(BUCKET).get_public_url(path)

    _replace_previous(client, user_id, slot, keep=path)

    return {"url": url, "slot": slot, "width": width, "height": height, "byte_size": len(jpeg)}


@router.delete("/brand/image")
def remove_brand_image(slot: str = "card", user_id: str = Depends(get_current_user)):
    """Drop every stored image for this producer.

    The metadata field is cleared by the browser, the same way it was written.
    This only removes the objects, so clearing the artwork doesn't quietly leave
    it public forever at a URL someone still has.
    """
    if slot not in _SLOTS:
        raise HTTPException(status_code=400, detail="Unknown image slot.")
    client = get_client()
    _replace_previous(client, user_id, slot, keep=None)
    return {"ok": True}


def _replace_previous(client, user_id: str, slot: str, keep: str | None) -> None:
    """Keep at most one image per producer PER SLOT.

    Scoped to the slot, and that is the whole point: without it, uploading a
    masthead background would delete the title card the call sheet is using.

    Best-effort. A leftover object is a few hundred kilobytes; a failed upload
    because the cleanup threw would be a producer unable to set their brand.
    """
    try:
        existing = client.storage.from_(BUCKET).list(user_id) or []
        stale = [f"{user_id}/{o['name']}" for o in existing
                 if o["name"].startswith(f"{slot}-")
                 and (keep is None or f"{user_id}/{o['name']}" != keep)]
        if stale:
            client.storage.from_(BUCKET).remove(stale)
    except Exception:
        logger.warning("Could not clear previous brand images for %s", user_id, exc_info=True)
