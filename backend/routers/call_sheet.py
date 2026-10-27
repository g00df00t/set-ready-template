import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from urllib.parse import quote
from uuid import UUID
from pydantic import BaseModel
from typing import List, Optional
from database import get_client
from auth import get_current_user, get_accessible_owner_ids, get_write_owner_id, get_user_brand, get_user_identity
import usage
from services.claude_service import strip_to_markup
from services.call_sheet_builder import build_call_sheet
from services.email_service import send_call_sheet_emails, send_call_sheet_to_contacts
from services.pdf_service import render_call_sheet_pdf, safe_pdf_filename
from services.attachment_service import human_size
from routers.attachments import fetch_attachment_files
from services.location_service import geocode, get_weather, get_nearest_hospital, miles_between
from config import settings
from time_utils import to_display_time, CALL_TIME_LABEL_CHOICES
from rate_limit import limiter, user_or_ip
from services.job_dates import day_label
from routers.account import on_jobs_beta

logger = logging.getLogger(__name__)

router = APIRouter(tags=["call-sheet"])

# SendGrid's per-message ceiling, measured after base64 encoding.
_MAX_MESSAGE_BYTES = 29 * 1024 * 1024


class CallSheetResponse(BaseModel):
    id: str
    project_id: str
    html_content: str
    generated_at: str
    sent_at: Optional[str] = None


class SendRequest(BaseModel):
    update_note: Optional[str] = None
    # Which people to send to. None means everyone — keeps older clients and
    # the plain "send it to the whole unit" case working unchanged. An explicit
    # empty list is a no-op and is rejected, so a mis-wired UI can't silently
    # "succeed" at sending to nobody.
    crew_ids: Optional[List[UUID]] = None
    contact_ids: Optional[List[UUID]] = None


def _pdf_for(recipients: list, sheet_html: str) -> bytes | None:
    """Render the sheet once per send, and only if somebody actually wants it.

    A failed render must never block delivery — a call sheet that arrives
    without its attachment is recoverable; one that doesn't arrive on a shoot
    morning is not. Sentry still gets the exception.
    """
    if not any(r.get("wants_pdf") for r in recipients):
        return None
    try:
        return render_call_sheet_pdf(sheet_html)
    except Exception:
        logger.exception("Call sheet PDF render failed; sending without attachment")
        return None


def _sheet_html(sheet: dict) -> str:
    """Stored sheet HTML, with any stray leading text dropped.

    Sheets generated before the sanitizer stopped preserving <title> text have
    that text baked into the saved row, where it printed above the sheet in
    emails. Cleaning on read fixes those without anyone regenerating.
    """
    return strip_to_markup(sheet["html_content"] or "")


def _day_label(client, project: dict, user_id: str) -> str | None:
    """"Day 2 of 4" when this day is one of several shoot days in a job —
    printed under the date on the sheet and added to the email subject, since
    every day of a job carries the job's name and a sheet otherwise can't say
    which day it is. Best-effort: a sheet without it is still a sheet.

    Only for someone on Jobs. Everyone's Duplicate joins the source's job, so
    for anyone else a shoot reused as a template would say "Day 2 of 2" to its
    crew, about a numbering they can't see in the app."""
    if not project.get("job_id") or not on_jobs_beta(client, user_id):
        return None
    try:
        job = client.table("jobs").select("crew_dates").eq("id", project["job_id"]).execute().data
        days = client.table("projects").select("id,shoot_date,created_at").eq("job_id", project["job_id"]).execute().data
        return day_label(job[0].get("crew_dates") if job else None, days, project["id"])
    except Exception as e:
        logger.error("day label for %s failed: %s", project.get("id"), e, exc_info=True)
        return None


def _sheet_title(client, project: dict, user_id: str) -> str:
    """The name the emails and texts use: the job's name, plus which day."""
    label = _day_label(client, project, user_id)
    return f"{project['name']} · {label}" if label else project["name"]


def _own_project(client, project_id: str, owner_ids: set[str]) -> dict:
    result = client.table("projects").select("*").eq("id", project_id).in_("owner_id", list(owner_ids)).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Project not found")
    return result.data[0]


@router.get("/projects/{project_id}/call-sheet/location-debug")
def location_debug(project_id: UUID, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    project = _own_project(client, str(project_id), owner_ids)
    location_result = client.table("project_locations").select("*").eq("project_id", str(project_id)).execute()
    location = location_result.data[0] if location_result.data else None

    if not location or not location.get("address"):
        return {"error": "No location address on file for this project"}

    address_str = location["address"]
    coords = geocode(address_str)
    if not coords:
        return {"address_used": address_str, "geocode": None, "weather": None, "hospital": None}

    lat, lon = coords
    shoot_date = str(project["shoot_date"]) if project.get("shoot_date") else None
    weather = get_weather(lat, lon, shoot_date) if shoot_date else None
    hospital = get_nearest_hospital(lat, lon)

    return {
        "address_used": address_str,
        "geocode": {"lat": lat, "lon": lon},
        "shoot_date": shoot_date,
        "weather": weather,
        "hospital": hospital,
    }


@router.post("/projects/{project_id}/call-sheet/generate", response_model=CallSheetResponse)
@limiter.limit("20/hour", key_func=user_or_ip)
def generate(
    request: Request,
    project_id: UUID,
    user_id: str = Depends(get_current_user),
    owner_ids: set[str] = Depends(get_accessible_owner_ids),
    write_owner_id: str = Depends(get_write_owner_id),
):
    client = get_client()
    project = _own_project(client, str(project_id), owner_ids)

    crew = client.table("crew_members").select("*").eq("project_id", str(project_id)).order("sort_order").execute().data
    schedule = client.table("schedule_items").select("*").eq("project_id", str(project_id)).order("sort_order").execute().data
    location_result = client.table("project_locations").select("*").eq("project_id", str(project_id)).execute()
    location = location_result.data[0] if location_result.data else None
    contacts = client.table("project_contacts").select("*").eq("project_id", str(project_id)).order("sort_order").execute().data
    talent = client.table("talent").select("*").eq("project_id", str(project_id)).order("sort_order").execute().data
    company_moves = client.table("company_moves").select("*").eq("project_id", str(project_id)).order("sort_order").execute().data

    stay_result = client.table("project_accommodations").select("*").eq("project_id", str(project_id)).execute()
    # Drop blanks on the way out too, so rows saved before the upsert started
    # normalizing them don't put empty labels on the sheet.
    accommodation = (
        {k: v for k, v in stay_result.data[0].items() if not (isinstance(v, str) and not v.strip())}
        if stay_result.data else None
    )

    # Guarded on purpose: this table arrives with a migration, and the backend
    # deploys the moment main is pushed. If the code lands first, an unguarded
    # read would 500 every generation for every user until the SQL is run — a
    # whole-product outage caused by an optional section. Degrade to no meal
    # plan instead. (Lesson from the ON DELETE CASCADE migration.)
    try:
        meals_result = client.table("project_meals").select("*").eq("project_id", str(project_id)).execute()
        meals = meals_result.data[0] if meals_result.data else None
    except Exception:
        logger.warning("project_meals unavailable — has the migration been run?", exc_info=True)
        meals = None

    weather = None
    hospital = None
    set_coords = None
    if location and location.get("address"):
        address_str = location["address"]
        set_coords = geocode(address_str)
        if set_coords:
            lat, lon = set_coords
            # Weather and hospital both need only the coordinates and nothing
            # from each other, so they run together rather than one after the
            # other. Hospital is the slow one — the wait is now whichever is
            # slower, not the sum.
            with ThreadPoolExecutor(max_workers=2) as pool:
                weather_future = (
                    pool.submit(get_weather, lat, lon, str(project["shoot_date"]))
                    if project.get("shoot_date") else None
                )
                hospital_future = pool.submit(get_nearest_hospital, lat, lon)
                # Neither raises in practice — both swallow their own failures
                # and return None — but a crash here must not take the whole
                # generation down over an optional section of the sheet.
                try:
                    weather = weather_future.result() if weather_future else None
                except Exception:
                    logger.warning("weather lookup failed", exc_info=True)
                try:
                    hospital = hospital_future.result()
                except Exception:
                    logger.warning("hospital lookup failed", exc_info=True)

    # "How far is my hotel from set" is the one thing crew want from this
    # section. Both addresses are already geocoded for weather and hospital, so
    # this is a local calculation, not another round trip.
    if accommodation and accommodation.get("address") and set_coords:
        hotel_coords = geocode(accommodation["address"])
        if hotel_coords:
            accommodation = {
                **accommodation,
                "distance_from_set_miles": miles_between(hotel_coords, set_coords),
            }

    enriched_moves = []
    for move in company_moves:
        move_data = dict(move)
        if move.get("address"):
            move_coords = geocode(move["address"])
            if move_coords:
                move_lat, move_lon = move_coords
                move_data["nearest_hospital"] = get_nearest_hospital(move_lat, move_lon)
        enriched_moves.append(move_data)

    try:
        html_content = build_call_sheet(
            {**project, "day_label": _day_label(client, project, user_id)}, crew, schedule, location, contacts, talent,
            weather, hospital, enriched_moves, accommodation, meals,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Call sheet generation failed: {type(e).__name__}: {e}")

    client.table("call_sheets").delete().eq("project_id", str(project_id)).execute()
    result = client.table("call_sheets").insert({
        "project_id": str(project_id),
        "html_content": html_content,
    }).execute()
    # Logged here rather than derived from the row, because the row above is the
    # only one that survives — the delete just erased the previous generation.
    # Attributed to write_owner_id (the account, not whoever is acting) so a
    # team member generating a sheet doesn't fork a phantom low-activity
    # account on /master under their own id — see docs/team-sharing-plan.md §5.
    usage.record_event(client, write_owner_id, project_id, usage.GENERATED)
    return result.data[0]


@router.get("/projects/{project_id}/call-sheet/pdf")
@limiter.limit("60/hour", key_func=user_or_ip)
def download_pdf(request: Request, project_id: UUID, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    """Render the current sheet to a PDF the producer downloads directly.

    This exists because the browser can't be trusted to make this file. The page
    used to be printed client-side via window.print(), which left the result up
    to whichever export the user picked in Chrome's dialog — and both macOS
    routes ("Print using system dialog…", "Open PDF in Preview") re-render
    through Quartz and discard hyperlink annotations. A producer's downloaded
    sheet had Apple Maps and Google Maps buttons that were painted on and dead.
    Verified: this path emits real link annotations, that one emits none.

    It also means the producer's copy and the crew's emailed copy are now the
    same document from the same renderer, rather than two that merely resemble
    each other.
    """
    client = get_client()
    project = _own_project(client, str(project_id), owner_ids)

    sheet_result = client.table("call_sheets").select("*").eq("project_id", str(project_id)).order("generated_at", desc=True).limit(1).execute()
    if not sheet_result.data:
        raise HTTPException(status_code=400, detail="Generate a call sheet before downloading it.")

    try:
        pdf = render_call_sheet_pdf(_sheet_html(sheet_result.data[0]))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not render the PDF: {type(e).__name__}: {e}")

    filename = safe_pdf_filename(project["name"])
    # Both forms on purpose: the quoted one for clients that only read ASCII,
    # filename* for anything with an accent or an em dash in the job name.
    ascii_name = filename.encode("ascii", "replace").decode("ascii").replace("?", "_")
    disposition = (
        f'attachment; filename="{ascii_name}"; '
        f"filename*=UTF-8''{quote(filename)}"
    )
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": disposition},
    )


@router.post("/projects/{project_id}/call-sheet/send")
def send(
    project_id: UUID,
    body: SendRequest = SendRequest(),
    user_id: str = Depends(get_current_user),
    owner_ids: set[str] = Depends(get_accessible_owner_ids),
    write_owner_id: str = Depends(get_write_owner_id),
):
    client = get_client()
    project = _own_project(client, str(project_id), owner_ids)

    sheet_result = client.table("call_sheets").select("*").eq("project_id", str(project_id)).order("generated_at", desc=True).limit(1).execute()
    if not sheet_result.data:
        raise HTTPException(status_code=400, detail="Generate a call sheet before sending.")
    sheet = sheet_result.data[0]

    crew = client.table("crew_members").select("*").eq("project_id", str(project_id)).execute().data
    if not crew:
        raise HTTPException(status_code=400, detail="Add crew members before sending.")

    contacts = client.table("project_contacts").select("*").eq("project_id", str(project_id)).execute().data
    contacts_with_email = [c for c in (contacts or []) if c.get("email")]

    # Narrow to the chosen recipients. Selection is filtered against this
    # project's own rows, so an id from another project can't be smuggled in.
    if body.crew_ids is not None:
        wanted = {str(i) for i in body.crew_ids}
        crew = [m for m in crew if m["id"] in wanted]
    if body.contact_ids is not None:
        wanted = {str(i) for i in body.contact_ids}
        contacts_with_email = [c for c in contacts_with_email if c["id"] in wanted]

    if not crew and not contacts_with_email:
        raise HTTPException(status_code=400, detail="Select at least one person to send to.")

    producer = get_user_identity(user_id)
    from_name, reply_to = producer["name"], producer["email"]

    sheet_html = _sheet_html(sheet)
    pdf = _pdf_for(crew + contacts_with_email, sheet_html)
    pdf_name = safe_pdf_filename(project["name"])
    extras = fetch_attachment_files(client, str(project_id))

    # Uploads are capped individually, but several together can still overrun
    # SendGrid's ~30MB message ceiling — and base64 inflates everything by a
    # third. Fail here with something a producer can act on, rather than letting
    # SendGrid reject it mid-send and leave half the unit without a call sheet.
    total_raw = len(pdf or b"") + sum(len(data) for data, _, _ in extras)
    if total_raw * 4 / 3 > _MAX_MESSAGE_BYTES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"The attachments come to {human_size(total_raw)}, which is too much to email "
                f"with the call sheet. Remove one and send again."
            ),
        )

    try:
        title = _sheet_title(client, project, user_id)
        send_call_sheet_emails(crew, sheet_html, settings.app_base_url, title, body.update_note, from_name, reply_to, pdf=pdf, pdf_filename=pdf_name, extras=extras)
        if contacts_with_email:
            send_call_sheet_to_contacts(contacts_with_email, sheet_html, title, body.update_note, from_name, reply_to, pdf=pdf, pdf_filename=pdf_name, extras=extras)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Email send failed: {type(e).__name__}: {e}")

    now = datetime.now(timezone.utc).isoformat()
    client.table("call_sheets").update({"sent_at": now}).eq("id", sheet["id"]).execute()
    # Stamp only who actually received it, so a partial send leaves the rest
    # correctly marked as still waiting.
    if crew:
        client.table("crew_members").update({"last_sent_at": now}).in_("id", [m["id"] for m in crew]).execute()
    if contacts_with_email:
        client.table("project_contacts").update({"last_sent_at": now}).in_("id", [c["id"] for c in contacts_with_email]).execute()

    recipients = len(crew) + len(contacts_with_email)
    usage.record_event(client, write_owner_id, project_id, usage.SENT, recipients)
    return {"ok": True, "sent_to": recipients}


@router.post("/projects/{project_id}/call-sheet/remind/{crew_id}")
@limiter.limit("60/hour", key_func=user_or_ip)
def remind(
    request: Request,
    project_id: UUID,
    crew_id: UUID,
    user_id: str = Depends(get_current_user),
    owner_ids: set[str] = Depends(get_accessible_owner_ids),
    write_owner_id: str = Depends(get_write_owner_id),
):
    """Re-send the current call sheet to one crew member as a nudge.

    The sheet itself is the stored HTML, unchanged — this is the same email they
    already got, so a reminder can't quietly deliver different information than
    the rest of the unit received. Deliberately allowed even for someone who has
    already confirmed: a producer may just be resending a lost email.
    """
    client = get_client()
    project = _own_project(client, str(project_id), owner_ids)

    sheet_result = client.table("call_sheets").select("*").eq("project_id", str(project_id)).order("generated_at", desc=True).limit(1).execute()
    if not sheet_result.data:
        raise HTTPException(status_code=400, detail="Generate a call sheet before sending reminders.")
    sheet = sheet_result.data[0]
    if not sheet.get("sent_at"):
        raise HTTPException(status_code=400, detail="Send the call sheet to the crew before sending reminders.")

    member_result = client.table("crew_members").select("*").eq("id", str(crew_id)).eq("project_id", str(project_id)).execute()
    if not member_result.data:
        raise HTTPException(status_code=404, detail="Crew member not found")
    member = member_result.data[0]
    if not member.get("email"):
        raise HTTPException(status_code=400, detail=f"{member['name']} has no email address on file.")

    producer = get_user_identity(user_id)
    sheet_html = _sheet_html(sheet)
    try:
        send_call_sheet_emails(
            [member], sheet_html, settings.app_base_url, _sheet_title(client, project, user_id),
            from_name=producer["name"], reply_to=producer["email"], reminder=True,
            pdf=_pdf_for([member], sheet_html), pdf_filename=safe_pdf_filename(project["name"]),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Reminder send failed: {type(e).__name__}: {e}")

    client.table("crew_members").update({
        "last_sent_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", str(crew_id)).execute()

    usage.record_event(client, write_owner_id, project_id, usage.REMINDED, 1)
    return {"ok": True, "name": member["name"]}


class TextNudge(BaseModel):
    crew_id: str
    phone: str
    message: str


def _nudge_message(first_name: str, project_name: str, shoot_date, call_time: str | None, url: str) -> str:
    """The text the producer sends from their own phone.

    Deliberately written as if they typed it — no product name, no branding.
    It arrives from a number the crew already have saved, and that recognition
    is the whole reason this beats an automated send. Kept short — the confirm
    URL alone is ~65 characters — and punctuated with a plain hyphen rather than
    an em dash, which would push the whole message out of GSM-7 into UCS-2 and
    cut the per-segment budget from 160 characters to 70.
    """
    date_part = ""
    if shoot_date:
        d = shoot_date if hasattr(shoot_date, "strftime") else datetime.fromisoformat(str(shoot_date)).date()
        date_part = f" for {d.strftime('%a')} {d.strftime('%b')} {d.day}"
    # "Your call is 8:00 AM." reads naturally; "Your call is Own Call." does not.
    if not call_time:
        time_part = ""
    elif call_time in CALL_TIME_LABEL_CHOICES:
        time_part = f" Call time: {call_time}."
    else:
        time_part = f" Your call is {call_time}."
    return f"{first_name} - {project_name} call sheet{date_part}.{time_part} Confirm you got it: {url}"


@router.get("/projects/{project_id}/call-sheet/text-nudges", response_model=List[TextNudge])
def text_nudges(project_id: UUID, user_id: str = Depends(get_current_user),
                owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    """Pre-written confirm-link texts for crew who have a phone number.

    The producer sends these from their own phone — nothing is transmitted from
    here. That keeps the feature clear of carrier registration and of consent
    rules that would apply if Set Ready were the sender: the crew gave their
    number to the producer, not to us.

    Returns an empty list rather than an error when there is no sent sheet yet,
    since asking someone to confirm a sheet they were never sent is nonsense —
    and the tracker that calls this only renders after a send anyway.
    """
    client = get_client()
    project = _own_project(client, str(project_id), owner_ids)

    sheet_result = (
        client.table("call_sheets").select("sent_at").eq("project_id", str(project_id))
        .order("generated_at", desc=True).limit(1).execute()
    )
    if not sheet_result.data or not sheet_result.data[0].get("sent_at"):
        return []

    crew = client.table("crew_members").select("*").eq("project_id", str(project_id)).order("sort_order").execute().data

    title = _sheet_title(client, project, user_id)
    nudges = []
    for member in crew:
        phone = (member.get("phone") or "").strip()
        if not phone:
            continue
        first = (member["name"] or "").strip().split(" ")[0] or member["name"]
        nudges.append({
            "crew_id": member["id"],
            "phone": phone,
            "message": _nudge_message(
                first,
                title,
                project.get("shoot_date"),
                member.get("call_time_note") or to_display_time(member.get("call_time")),
                f"{settings.app_base_url}/confirm/{member['confirmation_token']}",
            ),
        })
    return nudges


@router.get("/projects/{project_id}/call-sheet", response_model=CallSheetResponse)
def get_call_sheet(project_id: UUID, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    _own_project(client, str(project_id), owner_ids)
    result = client.table("call_sheets").select("*").eq("project_id", str(project_id)).order("generated_at", desc=True).limit(1).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="No call sheet generated yet")
    return {**result.data[0], "html_content": _sheet_html(result.data[0])}


# Opening a confirm link must never confirm anyone. Email security scanners
# (Outlook Safe Links, corporate gateways) and chat link previews fetch every
# link in a message, and the confirm page fetches this during render — so when
# the GET wrote confirmed_at, a scanner "confirmed" crew who never opened the
# email (found testing staging, 2026-09-28; it had been live since launch).
# The GET only reads; the crew member's own button press is the POST.

def _confirm_payload(client, member: dict, already_confirmed: bool) -> JSONResponse:
    sheet_result = (
        client.table("call_sheets")
        .select("html_content")
        .eq("project_id", member["project_id"])
        .order("generated_at", desc=True)
        .limit(1)
        .execute()
    )
    call_sheet_html = _sheet_html(sheet_result.data[0]) if sheet_result.data else None

    # Whose call sheet this is. The crew member opening this page has no
    # account, so the producer's branding can only reach them through here.
    # Best-effort: a failed lookup costs a title card, never the confirmation.
    owner = client.table("projects").select("owner_id").eq("id", member["project_id"]).execute()
    brand = get_user_brand(owner.data[0]["owner_id"]) if owner.data else {"name": None, "accent": None}

    return JSONResponse({
        # "confirmed" means "a real link" — the name the page has always read;
        # already_confirmed is whether this person has actually confirmed.
        "confirmed": True,
        "already_confirmed": already_confirmed,
        "name": member["name"],
        "call_time": member.get("call_time_note") or (str(member["call_time"]) if member.get("call_time") else None),
        "call_sheet_html": call_sheet_html,
        "brand": brand,
    })


_UNKNOWN_LINK = {"confirmed": False, "already_confirmed": False, "name": None, "call_time": None, "call_sheet_html": None}


def _member_for(client, token: UUID) -> dict | None:
    rows = client.table("crew_members").select("*").eq("confirmation_token", str(token)).execute().data
    return rows[0] if rows else None


@router.get("/confirm/{token}")
@limiter.limit("60/minute")
def confirm_page_data(request: Request, token: UUID):
    """What the confirm page shows. Reads only — see the note above."""
    client = get_client()
    member = _member_for(client, token)
    if not member:
        return JSONResponse(_UNKNOWN_LINK)
    return _confirm_payload(client, member, member.get("confirmed_at") is not None)


@router.post("/confirm/{token}")
@limiter.limit("30/minute")
def confirm_receipt(request: Request, token: UUID):
    """The crew member pressed "Got it". Idempotent: confirming twice keeps
    the first time."""
    client = get_client()
    member = _member_for(client, token)
    if not member:
        return JSONResponse(_UNKNOWN_LINK)
    already_confirmed = member.get("confirmed_at") is not None
    if not already_confirmed:
        client.table("crew_members").update({
            "confirmed_at": datetime.now(timezone.utc).isoformat(),
        }).eq("confirmation_token", str(token)).execute()
    return _confirm_payload(client, member, already_confirmed)
