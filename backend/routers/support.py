from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from services.email_service import send_support_request
from rate_limit import limiter

router = APIRouter(tags=["support"])


class SupportRequest(BaseModel):
    name: str
    email: str
    message: str
    website: str | None = None  # honeypot — real users never fill this


@router.post("/support")
@limiter.limit("10/hour")
def submit_support(request: Request, body: SupportRequest):
    # Bots tend to fill every field, including the hidden honeypot. Pretend it
    # worked so they don't retry, but don't actually send anything.
    if body.website:
        return {"ok": True}

    if not body.name.strip() or not body.email.strip() or not body.message.strip():
        raise HTTPException(status_code=400, detail="Name, email, and message are required.")

    try:
        send_support_request(body.name.strip(), body.email.strip(), body.message.strip())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not send your message ({type(e).__name__}). Please try again.")

    return {"ok": True}
