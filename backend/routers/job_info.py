"""The job's Job info tab — what's left of the producer's Job Info Sheet once
vendors have their own tab: the four usage dates and the job-wide contact
sheet (services/contact_sheet.py), on screen and as Excel.

Every route gates on the job through jobs._own_job, so team sharing covers it.
⚠️ The contact sheet carries everyone's phone and email: producer-only.
"""

from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from auth import get_accessible_owner_ids
from database import get_client
from routers.deal_memo import _roster_entries_by_id
from routers.jobs import _own_job
from routers.vendors import view as vendors_view
from services import contact_sheet
from services.job_dates import DatesError
from services.vendors import USAGE, validate_usage

router = APIRouter(tags=["job info"])


class UsageBody(BaseModel):
    usage_dates: dict


def _sheet(client, job: dict, owner_ids: set[str]) -> dict:
    hires = client.table("job_hires").select("*").eq("job_id", job["id"]).order("sort_order").execute().data
    roster_by_id = _roster_entries_by_id(client, owner_ids,
                                         [str(h["roster_id"]) for h in hires if h.get("kind") == "talent" and h.get("roster_id")])
    day_ids = [d["id"] for d in client.table("projects").select("id").eq("job_id", job["id"]).execute().data]
    contacts = (client.table("project_contacts").select("*").in_("project_id", day_ids).order("sort_order").execute().data
                if day_ids else [])
    return contact_sheet.build(job, hires, roster_by_id, contacts, vendors_view(client, job)["vendors"])


@router.get("/jobs/{job_id}/job-info")
def get_job_info(job_id: UUID, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    job = _own_job(client, str(job_id), owner_ids)
    return {"usage_dates": job.get("usage_dates") or {}, "usage_labels": USAGE,
            **_sheet(client, job, owner_ids)}


@router.put("/jobs/{job_id}/usage-dates")
def update_usage_dates(job_id: UUID, data: UsageBody, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    _own_job(client, str(job_id), owner_ids)
    try:
        clean = validate_usage(data.usage_dates)
    except DatesError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return client.table("jobs").update({"usage_dates": clean}).eq("id", str(job_id)).execute().data[0]["usage_dates"]


@router.get("/jobs/{job_id}/job-info/xlsx")
def download_job_info(job_id: UUID, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    job = _own_job(client, str(job_id), owner_ids)
    usage = [(f"{label}:", (job.get("usage_dates") or {}).get(k) or "") for k, label in USAGE.items()]
    raw = contact_sheet.title(job).replace("—", "-").replace("–", "-")
    name = " ".join("".join(ch for ch in raw if ch.isalnum() or ch in " -_.,()&").split()) or "Job info"
    return Response(content=contact_sheet.to_xlsx(job, _sheet(client, job, owner_ids), usage),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name + '.xlsx')}"})
