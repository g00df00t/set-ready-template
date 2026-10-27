"""Deal memos: one per crew member, rendered from the Roster and the project.

Two sets of routes while the Jobs beta runs (docs/job-layer-plan.md §11):
/projects/{id}/deal-memos/... for the current version, reading a day's crew
rows and their free-text dates, and /jobs/{id}/deal-memos/... for Jobs, reading
the job's hires and structured dates. The day routes go when the beta ends.

Generation only — no BoldSign send yet. A producer downloads the PDF (one or
all) and handles getting it signed the way they already do today. See
docs/master-record-documents-plan.md Phase 2 and
docs/master-record-documents-review.md §2.
"""

import io
import logging
import re
import zipfile
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from auth import get_accessible_owner_ids
from database import get_client
from services.deal_memo_builder import build_deal_memo
from services.deal_memo_data import job_memo_dates, job_memo_location_line, select_hires
from services.holds import is_booked
from services.pdf_service import render_call_sheet_pdf

logger = logging.getLogger(__name__)

router = APIRouter(tags=["deal-memo"])


def _own_project(client, project_id: str, owner_ids: set[str]) -> dict:
    result = client.table("projects").select("*").eq("id", project_id).in_("owner_id", list(owner_ids)).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Project not found")
    return result.data[0]


def _safe_filename_part(value: str) -> str:
    """A filename fragment that survives every mail client and filesystem —
    same rule pdf_service.safe_pdf_filename uses for the job name."""
    cleaned = re.sub(r"[^\w\s-]", " ", value or "")
    return re.sub(r"\s+", " ", cleaned).strip(" -")


def _content_disposition(filename: str) -> str:
    ascii_name = filename.encode("ascii", "replace").decode("ascii").replace("?", "_")
    return f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{quote(filename)}'


def _location_for(client, project_id: str) -> dict | None:
    result = client.table("project_locations").select("*").eq("project_id", project_id).execute()
    return result.data[0] if result.data else None


def _roster_entries_by_id(client, owner_ids: set[str], roster_ids: list[str]) -> dict:
    if not roster_ids:
        return {}
    result = client.table("roster").select("*").in_("id", roster_ids).in_("owner_id", list(owner_ids)).execute()
    return {row["id"]: row for row in result.data}


def _render_memo(client, project: dict, crew_member: dict, roster_by_id: dict, location: dict | None) -> bytes:
    roster_entry = roster_by_id.get(str(crew_member.get("roster_id"))) if crew_member.get("roster_id") else None
    html = build_deal_memo(project, crew_member, roster_entry, location)
    return render_call_sheet_pdf(html)


@router.get("/projects/{project_id}/deal-memos/{crew_id}/pdf")
def download_deal_memo(project_id: UUID, crew_id: UUID, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    project = _own_project(client, str(project_id), owner_ids)

    crew_result = client.table("crew_members").select("*").eq("id", str(crew_id)).eq("project_id", str(project_id)).execute()
    if not crew_result.data:
        raise HTTPException(status_code=404, detail="Crew member not found")
    crew_member = crew_result.data[0]

    location = _location_for(client, str(project_id))
    roster_by_id = _roster_entries_by_id(
        client, owner_ids, [str(crew_member["roster_id"])] if crew_member.get("roster_id") else []
    )

    try:
        pdf = _render_memo(client, project, crew_member, roster_by_id, location)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not render the PDF: {type(e).__name__}: {e}")

    filename = f"Deal Memo - {_safe_filename_part(crew_member['name'])} - {_safe_filename_part(project['name'])}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": _content_disposition(filename)},
    )


@router.get("/projects/{project_id}/deal-memos/zip")
def download_all_deal_memos(project_id: UUID, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    """Every crew member's memo, one PDF each, zipped — the "thirteen PDFs per
    job" case from the producer's email in one click instead of one per person."""
    client = get_client()
    project = _own_project(client, str(project_id), owner_ids)

    crew_result = client.table("crew_members").select("*").eq("project_id", str(project_id)).order("sort_order").execute()
    crew = crew_result.data
    if not crew:
        raise HTTPException(status_code=400, detail="Add crew before generating deal memos.")

    location = _location_for(client, str(project_id))
    roster_ids = [str(c["roster_id"]) for c in crew if c.get("roster_id")]
    roster_by_id = _roster_entries_by_id(client, owner_ids, roster_ids)

    buffer = io.BytesIO()
    seen_names: dict[str, int] = {}
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for crew_member in crew:
            try:
                pdf = _render_memo(client, project, crew_member, roster_by_id, location)
            except Exception:
                logger.exception("Deal memo render failed for crew member %s", crew_member["id"])
                continue
            # Two "Alex Kim"s on the same job shouldn't silently overwrite one
            # another in the zip.
            base = _safe_filename_part(crew_member["name"])
            seen_names[base] = seen_names.get(base, 0) + 1
            suffix = f" ({seen_names[base]})" if seen_names[base] > 1 else ""
            zf.writestr(f"{base}{suffix}.pdf", pdf)

    filename = f"Deal Memos - {_safe_filename_part(project['name'])}.zip"
    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": _content_disposition(filename)},
    )


# ── Jobs version ─────────────────────────────────────────────────────────────


def _own_job(client, job_id: str, owner_ids: set[str]) -> dict:
    result = client.table("jobs").select("*").eq("id", job_id).in_("owner_id", list(owner_ids)).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Job not found")
    return result.data[0]


def _job_location(client, job: dict) -> dict | None:
    """The memo's Location line: the job's own line when the producer wrote
    one ("NJ and NY" — a job across several places), otherwise the first
    day's location, in shooting order. Days without a date sort last; a day
    without a location is skipped."""
    line = job_memo_location_line(job)
    if line:
        return {"location_name": line}
    job_id = job["id"]
    days = client.table("projects").select("id,shoot_date,created_at").eq("job_id", job_id).execute().data
    if not days:
        return None
    ordered = sorted(days, key=lambda d: (d.get("shoot_date") is None, d.get("shoot_date") or "",
                                          d.get("created_at") or ""))
    locations = client.table("project_locations").select("*").in_(
        "project_id", [d["id"] for d in ordered]).execute().data
    by_day = {loc["project_id"]: loc for loc in locations}
    for d in ordered:
        loc = by_day.get(d["id"])
        if loc and (loc.get("location_name") or loc.get("address")):
            return loc
    return None


def _render_hire_memo(job: dict, hire: dict, roster_by_id: dict, location: dict | None) -> bytes:
    roster_entry = roster_by_id.get(str(hire.get("roster_id"))) if hire.get("roster_id") else None
    return render_call_sheet_pdf(build_deal_memo(job, hire, roster_entry, location,
                                                 dates=job_memo_dates(job, hire)))


@router.get("/jobs/{job_id}/deal-memos/{hire_id}/pdf")
def download_job_deal_memo(job_id: UUID, hire_id: UUID, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    job = _own_job(client, str(job_id), owner_ids)
    rows = client.table("job_hires").select("*").eq("id", str(hire_id)).eq("job_id", str(job_id)).execute().data
    if not rows:
        raise HTTPException(status_code=404, detail="Hire not found")
    hire = rows[0]
    if hire.get("kind") == "talent":
        raise HTTPException(status_code=400, detail="Talent book through their agency — there's no crew deal memo for them.")
    roster_by_id = _roster_entries_by_id(client, owner_ids, [str(hire["roster_id"])] if hire.get("roster_id") else [])
    try:
        pdf = _render_hire_memo(job, hire, roster_by_id, _job_location(client, job))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not render the PDF: {type(e).__name__}: {e}")
    filename = f"Deal Memo - {_safe_filename_part(hire['name'])} - {_safe_filename_part(job['name'])}.pdf"
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": _content_disposition(filename)})


@router.get("/jobs/{job_id}/deal-memos/zip")
def download_all_job_deal_memos(job_id: UUID, hire_id: list[UUID] | None = Query(None),
                                owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    """Every hire's memo, zipped — or only the ones ticked, passed as repeated
    ?hire_id=. Reads the job's hires, not a day's crew — so someone hired for
    the job before any call sheet exists still gets one."""
    client = get_client()
    job = _own_job(client, str(job_id), owner_ids)
    hires = client.table("job_hires").select("*").eq("job_id", str(job_id)).order("sort_order").execute().data
    if not hires:
        raise HTTPException(status_code=400, detail="Add crew before generating deal memos.")
    # Download all = everyone booked; a hold's memo comes when it's asked for
    # by name (ticked), not with the batch (Patrick, 2026-10-02).
    hires = [h for h in hires if h.get("kind") != "talent"]     # talent never get a crew deal memo
    hires = select_hires([h for h in hires if is_booked(h)] if hire_id is None else hires, hire_id)
    if not hires:
        raise HTTPException(status_code=400, detail="None of those people are on this job any more.")
    roster_by_id = _roster_entries_by_id(client, owner_ids, [str(h["roster_id"]) for h in hires if h.get("roster_id")])
    location = _job_location(client, job)

    buffer = io.BytesIO()
    seen_names: dict[str, int] = {}
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for hire in hires:
            try:
                pdf = _render_hire_memo(job, hire, roster_by_id, location)
            except Exception:
                logger.exception("Deal memo render failed for hire %s", hire["id"])
                continue
            base = _safe_filename_part(hire["name"])
            seen_names[base] = seen_names.get(base, 0) + 1
            suffix = f" ({seen_names[base]})" if seen_names[base] > 1 else ""
            zf.writestr(f"{base}{suffix}.pdf", pdf)

    filename = f"Deal Memos - {_safe_filename_part(job['name'])}.zip"
    return Response(content=buffer.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": _content_disposition(filename)})
