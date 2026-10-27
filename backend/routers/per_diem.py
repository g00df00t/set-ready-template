"""The job's Per diem tab: what each person is owed day by day, hand edits,
how it was paid, and the sheet as Excel and PDF (services/per_diem.py decides,
this fetches). Who's away is set on the Rooming tab and read here.

Every route gates on the job through jobs._own_job, so team sharing covers it.
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
from services import per_diem
from services.job_dates import DatesError
from services.pdf_service import render_call_sheet_pdf
from services.per_diem_documents import title, to_html, to_xlsx

router = APIRouter(tags=["per diem"])
logger = logging.getLogger(__name__)


class HirePerDiemUpdate(BaseModel):
    # Which were sent matters: `per_diem_paid: null` un-marks a payment.
    per_diem_overrides: Optional[dict] = None
    per_diem_note: Optional[str] = None
    per_diem_paid: Optional[dict] = None


def _sheet(client, job: dict) -> tuple[dict, list[dict]]:
    hires = client.table("job_hires").select("*").eq("job_id", job["id"]).order("sort_order").execute().data
    return per_diem.build_sheet(job, hires), hires


@router.get("/jobs/{job_id}/per-diem")
def get_per_diem(job_id: UUID, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    job = _own_job(client, str(job_id), owner_ids)
    sheet, hires = _sheet(client, job)
    overrides = {h["id"]: h.get("per_diem_overrides") or {} for h in hires}
    return {**sheet, "overrides": overrides}


@router.put("/jobs/{job_id}/hires/{hire_id}/per-diem")
def update_hire_per_diem(job_id: UUID, hire_id: UUID, data: HirePerDiemUpdate,
                         owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    """One person's per diem edits, note and payment. Job-only: never reaches a
    day's crew rows or the Roster."""
    client = get_client()
    _own_job(client, str(job_id), owner_ids)
    _own_hire(client, str(job_id), str(hire_id))
    sent = data.model_fields_set
    updates = {}
    try:
        if "per_diem_overrides" in sent:
            updates["per_diem_overrides"] = per_diem.validate_overrides(data.per_diem_overrides)
        if "per_diem_paid" in sent:
            updates["per_diem_paid"] = per_diem.validate_paid(data.per_diem_paid)
    except DatesError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if "per_diem_note" in sent:
        updates["per_diem_note"] = " ".join((data.per_diem_note or "").split())[:200] or None
    if not updates:
        return _own_hire(client, str(job_id), str(hire_id))
    return client.table("job_hires").update(updates).eq("id", str(hire_id)).execute().data[0]


def _download(job: dict, ext: str) -> dict:
    # A dash in a job name stays a dash, and nothing leaves a double space.
    raw = title(job).replace("—", "-").replace("–", "-")
    name = " ".join("".join(ch for ch in raw if ch.isalnum() or ch in " -_.,()&").split()) or "Per diem"
    return {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name + '.' + ext)}"}


@router.get("/jobs/{job_id}/per-diem/xlsx")
def download_per_diem_xlsx(job_id: UUID, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    job = _own_job(client, str(job_id), owner_ids)
    sheet, _ = _sheet(client, job)
    return Response(content=to_xlsx(job, sheet),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers=_download(job, "xlsx"))


@router.get("/jobs/{job_id}/per-diem/pdf")
def download_per_diem_pdf(job_id: UUID, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    job = _own_job(client, str(job_id), owner_ids)
    sheet, _ = _sheet(client, job)
    try:
        pdf = render_call_sheet_pdf(to_html(job, sheet))
    except Exception as e:
        logger.exception("Per diem PDF failed for job %s", job_id)
        raise HTTPException(status_code=500, detail=f"Could not render the PDF: {type(e).__name__}")
    return Response(content=pdf, media_type="application/pdf", headers=_download(job, "pdf"))
