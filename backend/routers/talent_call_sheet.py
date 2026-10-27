"""The per-talent call sheet for agents (services/talent_call_sheet.py decides,
this fetches): the job's talent with what's still missing from each sheet, the
sheet's job-level settings, and the PDFs — one talent, or every booked one as
a zip.

Every route gates on the job through jobs._own_job, so team sharing covers it.
Weather is looked up only when a PDF is made, best effort: a forecast more than
16 days out doesn't exist, and a failed lookup leaves the line off rather than
failing the download.
"""

import io
import logging
import zipfile
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from auth import get_accessible_owner_ids, get_user_identity
from database import get_client
from routers.deal_memo import _content_disposition, _roster_entries_by_id, _safe_filename_part
from routers.jobs import _own_hire, _own_job
from services import talent_call_sheet as tcs
from services.holds import is_booked, status_of
from services import job_dates
from services.job_dates import DatesError
from services.location_service import geocode, get_weather
from services.pdf_service import render_call_sheet_pdf

router = APIRouter(tags=["talent call sheets"])
logger = logging.getLogger(__name__)


class TalentSheetSettings(BaseModel):
    talent_sheet: dict


def _hires(client, job_id: str) -> list[dict]:
    return client.table("job_hires").select("*").eq("job_id", job_id).order("sort_order").execute().data


def _job_days(client, job_id: str) -> dict:
    """Everything per day the sheets read, fetched once for the whole job:
    {project_id: {project, location, meals, talent: [rows]}}."""
    projects = client.table("projects").select("*").eq("job_id", job_id).execute().data
    ids = [p["id"] for p in projects]
    out = {p["id"]: {"project": p, "location": None, "meals": None, "talent": []} for p in projects}
    if not ids:
        return out
    for loc in client.table("project_locations").select("*").in_("project_id", ids).execute().data:
        out[loc["project_id"]]["location"] = loc
    try:
        for m in client.table("project_meals").select("*").in_("project_id", ids).execute().data:
            out[m["project_id"]]["meals"] = m
    except Exception:
        logger.warning("project_meals unavailable", exc_info=True)
    for t in client.table("talent").select("*").in_("project_id", ids).execute().data:
        out[t["project_id"]]["talent"].append(t)
    return out


def _row_for(rows: list[dict], hire: dict) -> dict | None:
    """Their row on a day's talent list: the one linked to the hire, else the
    one with their email — the same rule hiring uses, which leaves a row that
    was already on the day (added by hand, before the hire) unlinked."""
    for r in rows:
        if str(r.get("hire_id") or "") == str(hire["id"]):
            return r
    email = (hire.get("email") or "").strip().lower()
    if email:
        for r in rows:
            if not r.get("hire_id") and (r.get("email") or "").strip().lower() == email:
                return r
    return None


def _days_for(job: dict, job_days: dict, hire: dict) -> list[dict]:
    """The shoot days this talent is on, in date order: a row on that day's
    talent list AND a shoot or fitting on that date by their own dates. Their
    dates are the truth — a row left on a day they now only travel (added by
    hand before they were hired) doesn't make it a shoot day."""
    mine = job_dates.effective_dates(job_dates.hire_base(job, hire), hire.get("dates_override"))
    days = [{"project": d["project"], "location": d["location"], "meals": d["meals"], "talent_row": row}
            for d in job_days.values()
            if d["project"].get("shoot_date") and job_dates.talent_on_day(mine, str(d["project"]["shoot_date"]))
            and (row := _row_for(d["talent"], hire))]
    return sorted(days, key=lambda d: (d["project"].get("shoot_date") is None, d["project"].get("shoot_date") or ""))


def _with_weather(days: list[dict], cache: dict) -> list[dict]:
    out = []
    for d in days:
        address = (d.get("location") or {}).get("address")
        when = d["project"].get("shoot_date")
        weather = None
        if address and when:
            key = (address, str(when))
            if key not in cache:
                try:
                    coords = geocode(address)
                    cache[key] = get_weather(coords[0], coords[1], str(when)) if coords else None
                except Exception:
                    logger.warning("talent sheet weather lookup failed", exc_info=True)
                    cache[key] = None
            weather = cache[key]
        out.append({**d, "weather": weather})
    return out


@router.get("/jobs/{job_id}/talent-sheets")
def get_talent_sheets(job_id: UUID, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    """The panel: settings, each booked talent with their shoot days and what's
    missing, and the crew who could be ticked as contacts."""
    client = get_client()
    job = _own_job(client, str(job_id), owner_ids)
    hires = _hires(client, job["id"])
    job_days = _job_days(client, job["id"])
    talent = []
    for h in tcs.talent_hires(hires):
        days = _days_for(job, job_days, h)
        talent.append({"hire_id": h["id"], "name": h.get("name"), "role": h.get("role"),
                       "shoot_dates": [d["project"].get("shoot_date") for d in days],
                       "gaps": tcs.gaps(job, h, days)})
    held = [h.get("name") for h in hires if h.get("kind") == "talent" and status_of(h) == "hold"]
    crew = [{"hire_id": h["id"], "name": h.get("name"), "role": h.get("role"), "has_phone": bool((h.get("phone") or "").strip())}
            for h in hires if (h.get("kind") or "crew") == "crew" and is_booked(h)]   # a hold isn't on the job yet
    return {"settings": tcs.settings_of(job), "talent": talent, "held": held, "crew": crew,
            "producer_phone": (job.get("producer_phone") or "").strip() or None}


@router.put("/jobs/{job_id}/talent-sheets/settings")
def update_talent_sheet_settings(job_id: UUID, data: TalentSheetSettings,
                                 owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    job = _own_job(client, str(job_id), owner_ids)
    crew_ids = {h["id"] for h in _hires(client, job["id"]) if (h.get("kind") or "crew") == "crew"}
    try:
        clean = tcs.validate_settings(data.talent_sheet, crew_ids)
    except DatesError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return client.table("jobs").update({"talent_sheet": clean}).eq("id", str(job_id)).execute().data[0]["talent_sheet"]


def _render(job: dict, hire: dict, hires: list[dict], job_days: dict, roster_by_id: dict,
            producer: dict, weather_cache: dict) -> bytes:
    days = _with_weather(_days_for(job, job_days, hire), weather_cache)
    sheet = tcs.build_sheet(job, hire, roster=roster_by_id.get(str(hire.get("roster_id"))),
                            hires=hires, days=days, producer=producer)
    return render_call_sheet_pdf(tcs.to_html(sheet))


@router.get("/jobs/{job_id}/talent-sheets/zip")
def download_all_talent_sheets(job_id: UUID, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    """Every booked talent's sheet, zipped. Holds come once confirmed."""
    client = get_client()
    job = _own_job(client, str(job_id), owner_ids)
    hires = _hires(client, job["id"])
    talent = tcs.talent_hires(hires)
    if not talent:
        raise HTTPException(status_code=400, detail="No booked talent on this job yet.")
    job_days = _job_days(client, job["id"])
    roster_by_id = _roster_entries_by_id(client, owner_ids, [str(h["roster_id"]) for h in talent if h.get("roster_id")])
    producer = get_user_identity(job["owner_id"])
    cache: dict = {}
    buffer = io.BytesIO()
    seen: dict[str, int] = {}
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for h in talent:
            try:
                pdf = _render(job, h, hires, job_days, roster_by_id, producer, cache)
            except Exception:
                logger.exception("Talent sheet render failed for hire %s", h["id"])
                continue
            base = _safe_filename_part(h["name"])
            seen[base] = seen.get(base, 0) + 1
            zf.writestr(f"{base}{f' ({seen[base]})' if seen[base] > 1 else ''}.pdf", pdf)
    filename = f"Talent Call Sheets - {_safe_filename_part(job['name'])}.zip"
    return Response(content=buffer.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": _content_disposition(filename)})


@router.get("/jobs/{job_id}/talent-sheets/{hire_id}/pdf")
def download_talent_sheet(job_id: UUID, hire_id: UUID, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    job = _own_job(client, str(job_id), owner_ids)
    hire = _own_hire(client, str(job_id), str(hire_id))
    if hire.get("kind") != "talent":
        raise HTTPException(status_code=400, detail="Talent call sheets are for talent hires.")
    hires = _hires(client, job["id"])
    roster_by_id = _roster_entries_by_id(client, owner_ids, [str(hire["roster_id"])] if hire.get("roster_id") else [])
    try:
        pdf = _render(job, hire, hires, _job_days(client, job["id"]), roster_by_id,
                      get_user_identity(job["owner_id"]), {})
    except Exception as e:
        logger.exception("Talent sheet PDF failed for hire %s", hire_id)
        raise HTTPException(status_code=500, detail=f"Could not render the PDF: {type(e).__name__}")
    filename = f"Call Sheet - {_safe_filename_part(hire['name'])} - {_safe_filename_part(job['name'])}.pdf"
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": _content_disposition(filename)})
