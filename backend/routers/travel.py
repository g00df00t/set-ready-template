"""The job's Travel tab: everyone's flights in and out, whose number the car
service gets, and the travel doc + car service copy as Excel and PDF
(services/travel.py decides, this fetches).

Every route gates on the job through jobs._own_job, so team sharing covers it.
The producer's number lives on the job (jobs.producer_phone) and is saved
through PUT /jobs/{id} like the job's other fields.
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
from services import travel
from services.holds import status_of
from services.job_dates import DatesError, hire_base
from services.pdf_service import render_call_sheet_pdf
from services.rooming import away_dates
from services.travel_documents import title, to_html, to_xlsx

router = APIRouter(tags=["travel"])
logger = logging.getLogger(__name__)


class HireTravelUpdate(BaseModel):
    # Which were sent matters: `car_service_producer_phone: null` puts the
    # person back on the default for their kind (model_fields_set).
    travel_legs: Optional[list] = None
    car_service_producer_phone: Optional[bool] = None


def _hires(client, job_id: str) -> list[dict]:
    return client.table("job_hires").select("*").eq("job_id", job_id).order("sort_order").execute().data


@router.get("/jobs/{job_id}/travel")
def get_travel(job_id: UUID, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    """The tab: each person with their legs (released people left off), and
    the views built from the booked ones."""
    client = get_client()
    job = _own_job(client, str(job_id), owner_ids)
    hires = _hires(client, job["id"])
    view = travel.build(job, hires)
    people = []
    for h in hires:
        status = status_of(h)
        if status == "released":
            continue
        away = away_dates(hire_base(job, h), h.get("dates_override"), h.get("away"))
        people.append({
            "hire_id": h["id"], "name": h.get("name"), "role": h.get("role"),
            "kind": h.get("kind") or "crew", "status": status,
            "has_phone": bool((h.get("phone") or "").strip()),
            "phone": (h.get("phone") or "").strip() or None,      # producer-only tab; editable there
            "producer_phone": travel.uses_producer_phone(h),
            "producer_phone_chosen": h.get("car_service_producer_phone") is not None,
            "first_away": away[0] if away else None, "last_away": away[-1] if away else None,
            "legs": [{**leg, "warning": travel.leg_warning(job, h, leg)} for leg in h.get("travel_legs") or []],
        })
    return {**view, "people": people}


@router.put("/jobs/{job_id}/hires/{hire_id}/travel")
def update_hire_travel(job_id: UUID, hire_id: UUID, data: HireTravelUpdate,
                       owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    """One person's legs (the whole list, as the screen holds it) and whose
    number the car service gets. Job-only: never reaches a day or the Roster."""
    client = get_client()
    _own_job(client, str(job_id), owner_ids)
    _own_hire(client, str(job_id), str(hire_id))
    sent = data.model_fields_set
    updates = {}
    if "travel_legs" in sent:
        ids = {h["id"] for h in client.table("job_hires").select("id").eq("job_id", str(job_id)).execute().data}
        try:
            updates["travel_legs"] = travel.validate_legs(data.travel_legs, ids, str(hire_id))
        except DatesError as e:
            raise HTTPException(status_code=422, detail=str(e))
    if "car_service_producer_phone" in sent:
        updates["car_service_producer_phone"] = data.car_service_producer_phone
    if not updates:
        return _own_hire(client, str(job_id), str(hire_id))
    return client.table("job_hires").update(updates).eq("id", str(hire_id)).execute().data[0]


def _view(job_id: UUID, owner_ids: set[str]) -> tuple[dict, dict]:
    client = get_client()
    job = _own_job(client, str(job_id), owner_ids)
    return job, travel.build(job, _hires(client, job["id"]))


def _filename(job: dict, car_service: bool, ext: str) -> dict:
    # A dash in a job name stays a dash, and nothing leaves a double space.
    raw = title(job, car_service).replace("—", "-").replace("–", "-")
    name = " ".join("".join(ch for ch in raw if ch.isalnum() or ch in " -_.,()&").split()) or "Travel"
    return {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name + '.' + ext)}"}


def _xlsx(job_id: UUID, owner_ids: set[str], car_service: bool) -> Response:
    job, view = _view(job_id, owner_ids)
    return Response(content=to_xlsx(job, view, car_service),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers=_filename(job, car_service, "xlsx"))


def _pdf(job_id: UUID, owner_ids: set[str], car_service: bool) -> Response:
    job, view = _view(job_id, owner_ids)
    try:
        pdf = render_call_sheet_pdf(to_html(job, view, car_service))
    except Exception as e:
        logger.exception("Travel PDF failed for job %s", job_id)
        raise HTTPException(status_code=500, detail=f"Could not render the PDF: {type(e).__name__}")
    return Response(content=pdf, media_type="application/pdf", headers=_filename(job, car_service, "pdf"))


@router.get("/jobs/{job_id}/travel/xlsx")
def download_travel_xlsx(job_id: UUID, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    return _xlsx(job_id, owner_ids, car_service=False)


@router.get("/jobs/{job_id}/travel/pdf")
def download_travel_pdf(job_id: UUID, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    return _pdf(job_id, owner_ids, car_service=False)


@router.get("/jobs/{job_id}/car-service/xlsx")
def download_car_service_xlsx(job_id: UUID, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    return _xlsx(job_id, owner_ids, car_service=True)


@router.get("/jobs/{job_id}/car-service/pdf")
def download_car_service_pdf(job_id: UUID, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    return _pdf(job_id, owner_ids, car_service=True)
