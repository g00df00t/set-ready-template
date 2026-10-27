"""The job's Rooming tab: hotels, who's away, and the rooming list itself —
on screen, as Excel and as a PDF (services/rooming.py decides, this fetches).

Every route gates on the job through jobs._own_job, so team sharing covers it
the same way. The downloads go to a hotel: they read build_sheets' rows only,
which never carry a phone, an email, a rate or per diem.
"""

import logging
from typing import Optional
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from auth import get_accessible_owner_ids
from database import get_client
from routers.jobs import _own_hire, _own_job
from services import rooming
from services.job_dates import DatesError, hire_base
from services.pdf_service import render_call_sheet_pdf
from services.rooming_documents import title, to_html, to_xlsx

router = APIRouter(tags=["rooming"])
logger = logging.getLogger(__name__)


class HotelsUpdate(BaseModel):
    hotels: list


class HireRoomingUpdate(BaseModel):
    # Which were sent matters: `away: null` means "away on all their dates",
    # which is different from not touching it (model_fields_set).
    away: Optional[list] = None
    room_notes: Optional[str] = None
    reservations: Optional[dict] = None
    room_overrides: Optional[dict] = None


def _or_422(fn, value):
    try:
        return fn(value)
    except DatesError as e:
        raise HTTPException(status_code=422, detail=str(e))


def _sheets(client, job: dict) -> tuple[dict, list[dict]]:
    hires = client.table("job_hires").select("*").eq("job_id", job["id"]).order("sort_order").execute().data
    return rooming.build_sheets(job, hires), hires


@router.get("/jobs/{job_id}/rooming")
def get_rooming(job_id: UUID, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    """The tab: the job's hotels, a sheet per stay, any nights no stay covers,
    and each person's away setting with the dates it's chosen from."""
    client = get_client()
    job = _own_job(client, str(job_id), owner_ids)
    out, hires = _sheets(client, job)
    people = [{
        "hire_id": h["id"], "name": h.get("name"), "role": h.get("role"),
        "away": h.get("away"),
        "dates": rooming.their_dates(hire_base(job, h), h.get("dates_override")),
        "room_notes": h.get("room_notes"), "reservations": h.get("reservations") or {},
        "room_overrides": h.get("room_overrides") or {},
    } for h in hires]
    return {"hotels": job.get("hotels") or [], **out, "people": people}


@router.put("/jobs/{job_id}/hotels")
def update_hotels(job_id: UUID, data: HotelsUpdate, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    _own_job(client, str(job_id), owner_ids)
    hotels = _or_422(rooming.validate_hotels, data.hotels)
    if len(hotels) > 20:
        raise HTTPException(status_code=422, detail="That's more hotels than a job needs.")
    return client.table("jobs").update({"hotels": hotels}).eq("id", str(job_id)).execute().data[0]["hotels"]


class RoomsUpdate(BaseModel):
    rooms: list


@router.put("/jobs/{job_id}/hotels/{hotel_id}/rooms")
def update_rooms(job_id: UUID, hotel_id: str, data: RoomsUpdate, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    """One stay's extra rooms — the merch room and the like — the whole list,
    as the screen holds it. The rest of the stay is left exactly as it was."""
    client = get_client()
    job = _own_job(client, str(job_id), owner_ids)
    hotels = job.get("hotels") or []
    if not any(h.get("id") == hotel_id for h in hotels):
        raise HTTPException(status_code=404, detail="That hotel isn't on this job.")
    hotels = [{**h, "rooms": data.rooms} if h.get("id") == hotel_id else h for h in hotels]
    hotels = _or_422(rooming.validate_hotels, hotels)
    return client.table("jobs").update({"hotels": hotels}).eq("id", str(job_id)).execute().data[0]["hotels"]


@router.put("/jobs/{job_id}/hires/{hire_id}/rooming")
def update_hire_rooming(job_id: UUID, hire_id: UUID, data: HireRoomingUpdate,
                        owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    """One person's rooming fields. Job-only, like the deal: none of this
    reaches a day's crew rows or the Roster."""
    client = get_client()
    _own_job(client, str(job_id), owner_ids)
    _own_hire(client, str(job_id), str(hire_id))
    sent = data.model_fields_set
    updates = {}
    if "away" in sent:
        updates["away"] = _or_422(rooming.validate_away, data.away)
    if "room_notes" in sent:
        note = " ".join((data.room_notes or "").split())
        if len(note) > rooming.TEXT_MAX:
            raise HTTPException(status_code=422, detail=f"Keep the note under {rooming.TEXT_MAX} characters.")
        updates["room_notes"] = note or None
    if "reservations" in sent:
        res = {}
        for k, v in (data.reservations or {}).items():
            v = " ".join(str(v or "").split())[:80]
            if v:
                res[str(k)] = v
        updates["reservations"] = res
    if "room_overrides" in sent:
        updates["room_overrides"] = _or_422(rooming.validate_overrides, data.room_overrides)
    if not updates:
        return _own_hire(client, str(job_id), str(hire_id))
    return client.table("job_hires").update(updates).eq("id", str(hire_id)).execute().data[0]


def _one_sheet(client, job_id: str, owner_ids: set[str], hotel_id: str) -> tuple[dict, dict]:
    job = _own_job(client, job_id, owner_ids)
    out, _ = _sheets(client, job)
    for s in out["sheets"]:
        if (s["hotel"] or {}).get("id", "all") == hotel_id:
            return job, s
    raise HTTPException(status_code=404, detail="No rooming list for that hotel.")


def _filename(job: dict, sheet: dict, ext: str) -> dict:
    # A dash in a job name stays a dash, and nothing leaves a double space.
    raw = title(job, sheet).replace("—", "-").replace("–", "-")
    name = " ".join("".join(ch for ch in raw if ch.isalnum() or ch in " -_.,()&").split()) or "Rooming list"
    return {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name + '.' + ext)}"}


@router.get("/jobs/{job_id}/rooming/{hotel_id}/xlsx")
def download_rooming_xlsx(job_id: UUID, hotel_id: str, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    job, sheet = _one_sheet(get_client(), str(job_id), owner_ids, hotel_id)
    return Response(content=to_xlsx(job, sheet),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers=_filename(job, sheet, "xlsx"))


@router.get("/jobs/{job_id}/rooming/{hotel_id}/pdf")
def download_rooming_pdf(job_id: UUID, hotel_id: str, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    job, sheet = _one_sheet(get_client(), str(job_id), owner_ids, hotel_id)
    try:
        pdf = render_call_sheet_pdf(to_html(job, sheet))
    except Exception as e:
        logger.exception("Rooming list PDF failed for job %s", job_id)
        raise HTTPException(status_code=500, detail=f"Could not render the PDF: {type(e).__name__}")
    return Response(content=pdf, media_type="application/pdf", headers=_filename(job, sheet, "pdf"))
