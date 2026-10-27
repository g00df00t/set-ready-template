"""The job's PC log tab: the producer's reconciliation cover sheet (services/pc_log.py
decides, this fetches). Typed expenses and invoices are written through
routers/budget.py; this adds what only the log has — its settings, hand changes
to generated lines, "Mark as sent", and the Excel/PDF.

Generated lines are live until the log is marked sent; a send freezes a copy
in job_pc_log_sends, the files print the latest copy, and anything that has
moved since is listed as a change — never applied to the copy.

Every route gates on the job through jobs._own_job, so team sharing covers it.
"""

import logging
from datetime import date
from typing import Literal, Optional
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from auth import get_accessible_owner_ids, get_user_identity
from database import get_client
from routers.budget import NOT_MIGRATED, _rows, _write
from routers.jobs import _own_job
from routers.vendors import _days_and_locations
from services import pc_log, per_diem, vendors as vendors_svc
from services.pc_log_documents import title, to_html, to_xlsx
from services.pdf_service import render_call_sheet_pdf

logger = logging.getLogger(__name__)
router = APIRouter(tags=["pc log"])


class SettingsBody(BaseModel):
    production_fee_bp: Optional[int] = Field(None, ge=0, le=10_000)
    pc_log_camera: Optional[Literal["photography", "video"]] = None


class GeneratedBody(BaseModel):
    """The whole of one generated line's hand changes; an empty body puts it
    back the way the job works it out."""
    hidden: bool = False
    amount_cents: Optional[int] = None
    category: Optional[str] = None


class SendBody(BaseModel):
    sent_on: Optional[date] = None


def _producer(job: dict) -> str | None:
    return get_user_identity(job["owner_id"]).get("name")


def _live(client, job: dict) -> tuple[dict, dict]:
    """(the live log, what else the screen needs)."""
    hires = client.table("job_hires").select("*").eq("job_id", job["id"]).order("sort_order").execute().data
    days, locations = _days_and_locations(client, job["id"])
    resolved = vendors_svc.resolve(job, job.get("vendors") or [], days, locations)
    generated = pc_log.generated_lines(job, hires, resolved, per_diem.build_sheet(job, hires))
    expenses, invoices, sends = (_rows(client, t, job["id"]) for t in ("job_expenses", "job_invoices", "job_pc_log_sends"))
    migrated = expenses is not None and invoices is not None and sends is not None and "production_fee_bp" in job
    hdr = pc_log.header(job, [d.get("shoot_date") for d in days], _producer(job))
    log = pc_log.build_log(job, generated, expenses or [], invoices or [], hdr)
    sends = sorted(sends or [], key=lambda s: (str(s.get("created_at") or ""), str(s["id"])))
    return log, {"migrated": migrated, "invoices": invoices or [], "sends": sends}


def view(client, job: dict) -> dict:
    log, extra = _live(client, job)
    latest = extra["sends"][-1] if extra["sends"] else None
    return {
        **log,
        "migrated": extra["migrated"],
        "settings": {"production_fee_bp": log["totals"]["fee_bp"],
                     "pc_log_camera": job.get("pc_log_camera") or "photography"},
        "invoices": extra["invoices"],
        "sent": {"id": latest["id"], "sent_on": latest["sent_on"], "created_at": latest.get("created_at")} if latest else None,
        "sends": [{"id": s["id"], "sent_on": s["sent_on"]} for s in extra["sends"]],
        "changes": pc_log.changes_since(latest["snapshot"], log) if latest else [],
        "categories": pc_log.CATEGORIES,
        "legend": pc_log.LEGEND,
        # The estimate's lines, for "which line is this receipt against?" (the
        # Budget tab's Reconcile view sums them into the line's actual cost).
        "budget_lines": [{"id": ln["id"], "name": ln["name"], "section": ln.get("section"), "block": ln.get("block"),
                          "dropped": bool(ln.get("dropped"))}
                         for ln in _rows(client, "job_budget_lines", job["id"]) or []],
    }


@router.get("/jobs/{job_id}/pc-log")
def get_pc_log(job_id: UUID, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    return view(client, _own_job(client, str(job_id), owner_ids))


@router.put("/jobs/{job_id}/pc-log/settings")
def update_settings(job_id: UUID, data: SettingsBody, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    job = _own_job(client, str(job_id), owner_ids)
    changes = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None}
    if changes:
        job = _write(lambda: client.table("jobs").update(changes).eq("id", job["id"]).execute().data[0])
    return view(client, job)


@router.put("/jobs/{job_id}/pc-log/generated/{key}")
def update_generated(job_id: UUID, key: str, data: GeneratedBody,
                     owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    job = _own_job(client, str(job_id), owner_ids)
    try:
        value = pc_log.validate_override(key, data.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if "production_fee_bp" not in job:
        raise HTTPException(status_code=503, detail=NOT_MIGRATED)
    current = dict(job.get("pc_log_generated") or {})
    if value is None:
        current.pop(key, None)
    else:
        current[key] = value
    job = _write(lambda: client.table("jobs").update({"pc_log_generated": current}).eq("id", job["id"]).execute().data[0])
    return view(client, job)


@router.post("/jobs/{job_id}/pc-log/send")
def mark_sent(job_id: UUID, data: SendBody, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    """Freeze the log as it stands. Every send is kept, so any version that
    went to the client can be printed again."""
    client = get_client()
    job = _own_job(client, str(job_id), owner_ids)
    log, extra = _live(client, job)
    if not extra["migrated"]:
        raise HTTPException(status_code=503, detail=NOT_MIGRATED)
    if not any(not r.get("hidden") for r in log["rows"]):
        raise HTTPException(status_code=422, detail="There's nothing on the PC log to send yet.")
    sent_on = (data.sent_on or date.today()).isoformat()
    row = {"job_id": job["id"], "sent_on": sent_on, "snapshot": pc_log.snapshot(log, sent_on)}
    _write(lambda: client.table("job_pc_log_sends").insert(row).execute())
    return view(client, job)


def _for_file(client, job: dict, send_id: str | None) -> dict:
    """What a download prints: a chosen send, else the latest send, else the
    live log (nothing has been sent yet)."""
    log, extra = _live(client, job)
    sends = extra["sends"]
    if send_id:
        chosen = next((s for s in sends if str(s["id"]) == send_id), None)
        if not chosen:
            raise HTTPException(status_code=404, detail="That version of the PC log isn't on this job.")
        return chosen["snapshot"]
    return sends[-1]["snapshot"] if sends else log


def _headers(log: dict, ext: str) -> dict:
    raw = title(log)
    name = " ".join("".join(ch for ch in raw if ch.isalnum() or ch in " -_.,()&").split()) or "PC Log"
    return {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name + '.' + ext)}"}


@router.get("/jobs/{job_id}/pc-log/xlsx")
def download_xlsx(job_id: UUID, send_id: str | None = None, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    log = _for_file(client, _own_job(client, str(job_id), owner_ids), send_id)
    return Response(content=to_xlsx(log),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers=_headers(log, "xlsx"))


@router.get("/jobs/{job_id}/pc-log/pdf")
def download_pdf(job_id: UUID, send_id: str | None = None, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    log = _for_file(client, _own_job(client, str(job_id), owner_ids), send_id)
    try:
        pdf = render_call_sheet_pdf(to_html(log))
    except Exception as e:
        logger.exception("PC log PDF failed for job %s", job_id)
        raise HTTPException(status_code=500, detail=f"Could not render the PDF: {type(e).__name__}")
    return Response(content=pdf, media_type="application/pdf", headers=_headers(log, "pdf"))
