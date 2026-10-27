"""The wrap report — what a shoot day turned out to be.

Rendered live rather than stored. That is the opposite of the call sheet, and
deliberate: confirmations keep arriving after the sheet goes out, so a saved
copy would be wrong by the time anyone opened it. Rendering costs a millisecond
and no API call, so there is nothing to save by caching it.

Reads only. Nothing here writes to a project, which is what makes it safe to
open on a finished job.
"""

import logging
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

import usage
from auth import get_accessible_owner_ids, get_write_owner_id
from config import settings
from database import get_client
from rate_limit import limiter
from services.wrap_report_data import build_wrap_data, is_wrapped
from services.wrap_report_template import render_wrap_report

logger = logging.getLogger(__name__)

router = APIRouter(tags=["wrap-report"])


class ShareLink(BaseModel):
    #: None when the report has never been shared, or the link was revoked.
    url: str | None = None


class WrapReportResponse(BaseModel):
    project_id: str
    project_name: str
    shoot_date: str | None = None
    #: False when the shoot date hasn't passed. The report still renders — a
    #: producer may want to look early — but the app only links to it once the
    #: day is over, and this is what it checks.
    wrapped: bool
    html: str
    #: The public link, when one exists. Null is the normal state.
    share_url: str | None = None


def _rows(client, table: str, project_id: str, order: str | None = "sort_order") -> list:
    """One project's rows, or none. A table that doesn't exist yet degrades to
    an empty section rather than a 500 — same guard the call sheet uses for
    project_meals, and for the same reason: the backend deploys the moment main
    is pushed, which can be before a migration is run.
    """
    try:
        query = client.table(table).select("*").eq("project_id", project_id)
        if order:
            query = query.order(order)
        return query.execute().data or []
    except Exception:
        logger.warning("%s unavailable for the wrap report", table, exc_info=True)
        return []


def _share_url(token) -> str | None:
    return f"{settings.app_base_url.rstrip('/')}/wrap/{token}" if token else None


def _assemble(client, project: dict) -> dict:
    """Every figure the report needs, for one project. Shared by the owner's
    route and the public one so a shared link can never show a different day
    than the producer sees."""
    pid = str(project["id"])

    locations = _rows(client, "project_locations", pid, order=None)
    stays = _rows(client, "project_accommodations", pid, order=None)
    meals = _rows(client, "project_meals", pid, order=None)
    sheets = _rows(client, "call_sheets", pid, order=None)

    data = build_wrap_data(
        project=project,
        crew=_rows(client, "crew_members", pid),
        talent=_rows(client, "talent", pid),
        schedule=_rows(client, "schedule_items", pid),
        location=locations[0] if locations else None,
        moves=_rows(client, "company_moves", pid),
        meals=meals[0] if meals else None,
        accommodation=stays[0] if stays else None,
        # Newest first: a project can hold only one sheet, but ordering makes
        # that an assumption the query states rather than one it relies on.
        call_sheet=max(sheets, key=lambda s: s.get("generated_at") or "") if sheets else None,
        attachments=_rows(client, "call_sheet_attachments", pid, order=None),
    )
    return data


def _response(client, project: dict, include_share: bool) -> WrapReportResponse:
    data = _assemble(client, project)
    return WrapReportResponse(
        project_id=str(project["id"]),
        project_name=data["project"]["name"],
        shoot_date=str(project.get("shoot_date")) if project.get("shoot_date") else None,
        wrapped=is_wrapped(project),
        html=render_wrap_report(data),
        # Never handed to a public viewer: whoever opens a shared link already
        # has it, and echoing it back invites it into somewhere it can be logged.
        share_url=_share_url(project.get("wrap_share_token")) if include_share else None,
    )


def _own_project(client, project_id: str, owner_ids: set[str]) -> dict:
    owned = client.table("projects").select("*").eq("id", project_id).in_("owner_id", list(owner_ids)).execute()
    if not owned.data:
        raise HTTPException(status_code=404, detail="Project not found")
    return owned.data[0]


@router.get("/projects/{project_id}/wrap", response_model=WrapReportResponse)
def wrap_report(
    project_id: UUID,
    owner_ids: set[str] = Depends(get_accessible_owner_ids),
    write_owner_id: str = Depends(get_write_owner_id),
):
    client = get_client()
    project = _own_project(client, str(project_id), owner_ids)
    # Attributed to the account, not whoever's viewing — see the same note on
    # call_sheet.py's usage.record_event calls.
    usage.record_event(client, write_owner_id, str(project_id), usage.WRAP_VIEWED)
    return _response(client, project, include_share=True)


@router.post("/projects/{project_id}/wrap/share", response_model=ShareLink)
def create_share_link(
    project_id: UUID,
    owner_ids: set[str] = Depends(get_accessible_owner_ids),
    write_owner_id: str = Depends(get_write_owner_id),
):
    """Mint a public link, or hand back the one that already exists.

    Idempotent on purpose. A producer who clicks Share twice should get the same
    URL, not silently break the one they already pasted into an email.
    """
    client = get_client()
    project = _own_project(client, str(project_id), owner_ids)

    token = project.get("wrap_share_token")
    if not token:
        token = str(uuid4())
        client.table("projects").update({"wrap_share_token": token}).eq("id", str(project_id)).execute()
        usage.record_event(client, write_owner_id, str(project_id), usage.WRAP_SHARED)

    return ShareLink(url=_share_url(token))


@router.delete("/projects/{project_id}/wrap/share", response_model=ShareLink)
def revoke_share_link(project_id: UUID, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    """Kill the link. The next Share mints a different one, so a revoked URL
    stays dead rather than coming back to life."""
    client = get_client()
    _own_project(client, str(project_id), owner_ids)
    client.table("projects").update({"wrap_share_token": None}).eq("id", str(project_id)).execute()
    return ShareLink(url=None)


@router.get("/wrap/{token}", response_model=WrapReportResponse)
@limiter.limit("60/minute")
def shared_wrap_report(request: Request, token: UUID):
    """The public view. No account, no auth — the token is the access control,
    the same bargain /confirm/{token} makes.

    A dead or unknown token is a flat 404 with no detail. Saying "this link was
    revoked" would confirm the project exists to anyone holding an old URL.
    """
    client = get_client()
    found = client.table("projects").select("*").eq("wrap_share_token", str(token)).execute()
    if not found.data:
        raise HTTPException(status_code=404, detail="Not found")
    return _response(client, found.data[0], include_share=False)
