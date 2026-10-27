"""The job's Vendors tab: bookings with their checklist (services/vendors.py
decides, this fetches). Stored on the job (jobs.vendors), but written one
booking at a time — the server reads the list, changes one entry and writes
it back, so two people editing different bookings don't overwrite each other's
whole list.

Every route gates on the job through jobs._own_job, so team sharing covers it.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import get_accessible_owner_ids
from database import get_client
from routers.jobs import _own_job
from services import vendors as svc
from services.job_dates import DatesError

router = APIRouter(tags=["vendors"])


class VendorBody(BaseModel):
    vendor: dict


def _days_and_locations(client, job_id: str) -> tuple[list[dict], dict]:
    days = client.table("projects").select("id,name,shoot_date").eq("job_id", job_id).execute().data
    days = sorted(days, key=lambda d: (d.get("shoot_date") is None, str(d.get("shoot_date") or "")))
    locations = {}
    if days:
        for loc in client.table("project_locations").select("*").in_("project_id", [d["id"] for d in days]).execute().data:
            locations[loc["project_id"]] = loc
    return days, locations


def view(client, job: dict) -> dict:
    days, locations = _days_and_locations(client, job["id"])
    resolved = svc.resolve(job, job.get("vendors") or [], days, locations)
    return {
        "vendors": resolved,
        "open_items": svc.open_items(resolved),
        "unbooked": svc.unbooked(job, job.get("vendors") or [], days, locations),
        "hotels": [{"id": h["id"], "name": h.get("name") or "Hotel"} for h in job.get("hotels") or []],
        "days": [{"id": d["id"], "shoot_date": d.get("shoot_date"),
                  "location": (locations.get(d["id"]) or {}).get("location_name")} for d in days],
        "kinds": svc.KINDS, "steps": svc.STEPS,
    }


@router.get("/jobs/{job_id}/vendors")
def get_vendors(job_id: UUID, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    return view(client, _own_job(client, str(job_id), owner_ids))


def _save(client, job: dict, vendors: list[dict]) -> dict:
    job = client.table("jobs").update({"vendors": vendors}).eq("id", job["id"]).execute().data[0]
    return view(client, job)


def _validated(client, job: dict, raw: dict) -> dict:
    days, _locations = _days_and_locations(client, job["id"])
    try:
        return svc.validate_vendor(raw, {h["id"] for h in job.get("hotels") or []}, {d["id"] for d in days})
    except DatesError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/jobs/{job_id}/vendors")
def add_vendor(job_id: UUID, data: VendorBody, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    job = _own_job(client, str(job_id), owner_ids)
    current = job.get("vendors") or []
    if len(current) >= svc.VENDORS_MAX:
        raise HTTPException(status_code=422, detail=f"A job can hold {svc.VENDORS_MAX} bookings.")
    vendor = _validated(client, job, {**data.vendor, "id": None})
    return _save(client, job, current + [vendor])


@router.put("/jobs/{job_id}/vendors/{vendor_id}")
def update_vendor(job_id: UUID, vendor_id: str, data: VendorBody, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    job = _own_job(client, str(job_id), owner_ids)
    current = job.get("vendors") or []
    if not any(v["id"] == vendor_id for v in current):
        raise HTTPException(status_code=404, detail="That booking isn't on this job.")
    vendor = _validated(client, job, {**data.vendor, "id": vendor_id})
    return _save(client, job, [vendor if v["id"] == vendor_id else v for v in current])


@router.delete("/jobs/{job_id}/vendors/{vendor_id}")
def delete_vendor(job_id: UUID, vendor_id: str, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    job = _own_job(client, str(job_id), owner_ids)
    current = job.get("vendors") or []
    if not any(v["id"] == vendor_id for v in current):
        raise HTTPException(status_code=404, detail="That booking isn't on this job.")
    return _save(client, job, [v for v in current if v["id"] != vendor_id])
