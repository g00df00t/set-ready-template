"""Holds across the account, and each job's role checklist
(services/holds.py decides, this fetches).

GET /holds is the stacked view of the producer's Crew Holds sheet: every upcoming job
the account can see. Role slots are per job, gated through jobs._own_job.
"""

from uuid import UUID

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from auth import get_accessible_owner_ids
from database import get_client
from routers.jobs import _own_job
from services import holds
from services.job_dates import DatesError
from services.pdf_service import render_call_sheet_pdf
from services.talent_sheet import build_talent_sheet, to_html as talent_html, to_xlsx as talent_xlsx

router = APIRouter(tags=["holds"])


class RoleSlotsUpdate(BaseModel):
    role_slots: list


@router.get("/holds")
def get_holds(owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    jobs = client.table("jobs").select("*").in_("owner_id", list(owner_ids)).execute().data
    if not jobs:
        return holds.build_holds([], [])
    hires = client.table("job_hires").select("*").in_("job_id", [j["id"] for j in jobs]).execute().data
    return holds.build_holds(jobs, hires)


@router.put("/jobs/{job_id}/role-slots")
def update_role_slots(job_id: UUID, data: RoleSlotsUpdate, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    """The job's role checklist — the whole list, as the screen holds it."""
    client = get_client()
    _own_job(client, str(job_id), owner_ids)
    hire_ids = {h["id"] for h in client.table("job_hires").select("id").eq("job_id", str(job_id)).execute().data}
    try:
        slots = holds.validate_slots(data.role_slots, hire_ids)
    except DatesError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return client.table("jobs").update({"role_slots": slots}).eq("id", str(job_id)).execute().data[0]["role_slots"]


# ── The talent hold sheet ────────────────────────────────────────────────────

def _talent_sheet(client, job_id: str, owner_ids: set[str]) -> tuple[dict, dict]:
    job = _own_job(client, job_id, owner_ids)
    hires = client.table("job_hires").select("*").eq("job_id", job_id).execute().data
    ids = [str(h["roster_id"]) for h in hires if h.get("kind") == "talent" and h.get("roster_id")]
    roster = {str(r["id"]): r for r in client.table("roster").select("*").in_("id", ids).in_(
        "owner_id", list(owner_ids)).execute().data} if ids else {}
    return job, build_talent_sheet(job, hires, roster)


def _filename(job: dict, ext: str) -> dict:
    raw = f"Talent Holds - {job.get('name') or 'Job'}".replace("—", "-").replace("–", "-")
    name = " ".join("".join(ch for ch in raw if ch.isalnum() or ch in " -_.,()&").split())
    return {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name + '.' + ext)}"}


@router.get("/jobs/{job_id}/talent-sheet/xlsx")
def download_talent_xlsx(job_id: UUID, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    job, sheet = _talent_sheet(get_client(), str(job_id), owner_ids)
    return Response(content=talent_xlsx(sheet),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers=_filename(job, "xlsx"))


@router.get("/jobs/{job_id}/talent-sheet/pdf")
def download_talent_pdf(job_id: UUID, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    job, sheet = _talent_sheet(get_client(), str(job_id), owner_ids)
    try:
        pdf = render_call_sheet_pdf(talent_html(sheet))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not render the PDF: {type(e).__name__}")
    return Response(content=pdf, media_type="application/pdf", headers=_filename(job, "pdf"))
