from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from services.email_service import send_waitlist_request
from rate_limit import limiter

router = APIRouter(tags=["waitlist"])


class WaitlistRequest(BaseModel):
    name: str
    email: str
    note: str | None = None
    website: str | None = None  # honeypot — real users never fill this


@router.post("/waitlist")
@limiter.limit("10/hour")
def submit_waitlist(request: Request, body: WaitlistRequest):
    # Bots tend to fill every field, including the hidden honeypot. Pretend it
    # worked so they don't retry, but don't actually send anything.
    if body.website:
        return {"ok": True}

    if not body.name.strip() or not body.email.strip():
        raise HTTPException(status_code=400, detail="Name and email are required.")

    try:
        send_waitlist_request(body.name.strip(), body.email.strip(), (body.note or "").strip() or None)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not submit your request ({type(e).__name__}). Please try again.")

    return {"ok": True}
