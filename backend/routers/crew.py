from fastapi import APIRouter, Depends, HTTPException, Request
from uuid import UUID
from typing import List
from database import get_client
from auth import get_accessible_owner_ids, get_write_owner_id
from services.roster_sync import write_back_to_roster
from services.import_match import classify
from services.roster_upsert import ensure_all_in_roster
from services.job_hires import hire_ids_for_new_crew, with_hire_ids, sync_day_row_to_hire

import logging

logger = logging.getLogger(__name__)
from models.crew import CrewMemberCreate, CrewMemberUpdate, CrewMemberResponse, CrewImportParseRequest, CrewImportConfirmRequest
from services.claude_service import parse_crew_import
from time_utils import split_call_time, split_call_time_lenient
from rate_limit import limiter, per_user, limit_by_user, PASTE_IMPORT_LIMIT
import usage

router = APIRouter(tags=["crew"])


def _own_project(client, project_id: str, owner_ids: set[str]):
    result = client.table("projects").select("id").eq("id", project_id).in_("owner_id", list(owner_ids)).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Project not found")


def _next_sort_order(client, project_id: str) -> int:
    existing = client.table("crew_members").select("id", count="exact").eq("project_id", project_id).execute()
    return existing.count or 0


def _hire_on_projects_job(client, project_id: str, hire_id: str) -> bool:
    """True when this hire belongs to the project's own job — a hire id from a
    request is never trusted to link across jobs, let alone accounts."""
    try:
        job_id = client.table("projects").select("job_id").eq("id", project_id).execute().data[0].get("job_id")
        rows = client.table("job_hires").select("id").eq("id", hire_id).eq("job_id", job_id).execute().data
        return bool(job_id and rows)
    except Exception as e:
        logger.error("job bookkeeping: hire check failed for %s: %s", hire_id, e, exc_info=True)
        return False


@router.post("/projects/{project_id}/crew", response_model=CrewMemberResponse)
def add_crew_member(project_id: UUID, data: CrewMemberCreate, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    _own_project(client, str(project_id), owner_ids)
    _ct = split_call_time(data.call_time)
    row = {
        "project_id": str(project_id),
        "roster_id": str(data.roster_id) if data.roster_id else None,
        "name": data.name,
        # The column is NOT NULL, but not "non-empty" — an unknown email is
        # exactly what "" already means everywhere else crew rows are built
        # (paste import, Duplicate).
        "email": data.email or "",
        "role": data.role,
        "phone": data.phone,
        "call_time": _ct[0],
        "call_time_note": _ct[1],
        "department": data.department,
        "sort_order": _next_sort_order(client, str(project_id)),
    }
    # Being on a day means being hired on its job. Picked from the job's hires,
    # the link is the one they chose; otherwise the same matcher finds or makes
    # it. Best-effort: with no job layer, the row goes in exactly as before.
    if data.hire_id and _hire_on_projects_job(client, str(project_id), str(data.hire_id)):
        hire_ids = [str(data.hire_id)]
    else:
        hire_ids = hire_ids_for_new_crew(client, str(project_id), [row])
    result = client.table("crew_members").insert(with_hire_ids([row], hire_ids)[0]).execute()
    return result.data[0]


@router.get("/projects/{project_id}/crew", response_model=List[CrewMemberResponse])
def list_crew(project_id: UUID, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    _own_project(client, str(project_id), owner_ids)
    result = client.table("crew_members").select("*").eq("project_id", str(project_id)).order("sort_order").execute()
    return result.data


@router.put("/projects/{project_id}/crew/{crew_id}", response_model=CrewMemberResponse)
def update_crew_member(
    project_id: UUID,
    crew_id: UUID,
    data: CrewMemberUpdate,
    owner_ids: set[str] = Depends(get_accessible_owner_ids),
    write_owner_id: str = Depends(get_write_owner_id),
):
    client = get_client()
    _own_project(client, str(project_id), owner_ids)
    updates = data.model_dump(exclude_unset=True)
    if "call_time" in updates:
        # One field in, two columns out — and always both, so switching from a
        # clock time to "Own Call" (or back) can't leave the old value behind.
        updates["call_time"], updates["call_time_note"] = split_call_time(updates["call_time"])
    result = client.table("crew_members").update(updates).eq("id", str(crew_id)).eq("project_id", str(project_id)).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Crew member not found")
    row = result.data[0]
    # A correction made on a job travels back to the person's master record —
    # the producer's decision: if you are fixing something that is wrong, the
    # Roster should stop being wrong too. Only person fields move; role,
    # department and call time belong to this job. Never fails the edit itself.
    # Targets the shared account's Roster (write_owner_id), not necessarily the
    # acting member's own — a team member correcting a phone number here is
    # fixing the owner's address book, the one this project actually reads from.
    if row.get("roster_id"):
        row["roster_synced"] = write_back_to_roster(client, row["roster_id"], write_owner_id, updates)
    # The same correction reaches their hire on the job, and their other days
    # on it. Person fields only; never fails the edit.
    sync_day_row_to_hire(client, row, updates)
    return row


@router.delete("/projects/{project_id}/crew/{crew_id}")
def remove_crew_member(project_id: UUID, crew_id: UUID, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    _own_project(client, str(project_id), owner_ids)
    result = client.table("crew_members").delete().eq("id", str(crew_id)).eq("project_id", str(project_id)).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Crew member not found")
    return {"ok": True}


@router.post("/projects/{project_id}/crew/import/parse")
@limiter.limit(PASTE_IMPORT_LIMIT, key_func=per_user)
def parse_crew_import_endpoint(
    request: Request,
    project_id: UUID,
    data: CrewImportParseRequest,
    owner_ids: set[str] = Depends(get_accessible_owner_ids),
    write_owner_id: str = Depends(get_write_owner_id),
    user_id: str = Depends(limit_by_user),
):
    client = get_client()
    _own_project(client, str(project_id), owner_ids)
    try:
        # Spend is recorded against the account the project belongs to, the
        # same owner call_sheet.py records generations against.
        members = parse_crew_import(data.text, usage.import_recorder(
            client, write_owner_id, str(project_id), usage.IMPORT_CREW_PASTE))
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Could not parse crew data: {str(e)}")

    # Say what each row already is, so the preview can show it. Nothing is
    # decided here — the producer chooses in the preview and confirm obeys.
    # A failure to classify must never cost them the parse they just paid for.
    try:
        project_rows = client.table("crew_members").select(
            "id,name,email,phone,role,department,call_time").eq("project_id", str(project_id)).execute().data
        roster_rows = client.table("roster").select(
            "id,name,email,phone,role,department").in_("owner_id", list(owner_ids)).eq("type", "crew").execute().data
        members = classify(members, project_rows, roster_rows)
    except Exception as e:
        logger.warning("import classification failed for project %s: %s", project_id, e)
    return {"members": members}


@router.post("/projects/{project_id}/crew/import/confirm")
def confirm_crew_import(
    project_id: UUID,
    data: CrewImportConfirmRequest,
    owner_ids: set[str] = Depends(get_accessible_owner_ids),
    write_owner_id: str = Depends(get_write_owner_id),
):
    client = get_client()
    _own_project(client, str(project_id), owner_ids)
    base = _next_sort_order(client, str(project_id))
    named = [m for m in data.members if m.name.strip()]

    # The producer's choice from the preview is authoritative. The API does not
    # re-decide: an override always wins, and a row with no action set is added,
    # which is what this endpoint did for everything before.
    skipped = [m for m in named if m.action == "skip"]
    updates = [m for m in named if m.action == "update" and m.match_id]
    adds = [m for m in named if m not in skipped and m not in updates]

    updated_rows = []
    for m in updates:
        ct = split_call_time_lenient(m.call_time)
        patch = {k: v for k, v in (("role", m.role), ("phone", m.phone),
                                   ("department", m.department), ("email", m.email))
                 if isinstance(v, str) and v.strip()}
        patch["call_time"], patch["call_time_note"] = ct
        r = client.table("crew_members").update(patch).eq("id", str(m.match_id)).eq(
            "project_id", str(project_id)).execute()
        updated_rows += r.data
        for row in r.data:
            sync_day_row_to_hire(client, row, patch)

    # Everyone added lands in the Roster too, the same as adding one person at a
    # time. Someone the preview already matched keeps that link; everyone else
    # gets an entry created for them, deduped by the same matcher so importing
    # cannot manufacture the duplicates this work exists to prevent.
    roster_ids: list = [None] * len(adds)
    if data.save_to_roster and adds:
        roster_ids = ensure_all_in_roster(
            client, write_owner_id,
            [{"name": m.name, "email": m.email, "phone": m.phone,
              "role": m.role, "department": m.department} for m in adds],
            "crew",
        )

    _times = [split_call_time_lenient(m.call_time) for m in adds]
    rows = [
        {
            "project_id": str(project_id),
            # Carry the link when the preview identified them, so an imported
            # person is as connected to the Roster as one picked from it.
            "roster_id": (str(m.match_id) if (m.match_state == "in_roster" and m.match_id)
                          else roster_ids[i]),
            "name": m.name,
            "email": m.email or "",
            "role": m.role or "",
            "phone": m.phone or None,
            "department": m.department or None,
            "call_time": _times[i][0],
            "call_time_note": _times[i][1],
            "sort_order": base + i,
        }
        for i, m in enumerate(adds)
    ]
    if not rows and not updated_rows:
        # Everything was skipped on purpose — that is a valid outcome, not a
        # failure. Only a paste with nothing usable in it is an error.
        if skipped:
            return []
        raise HTTPException(status_code=422, detail="No valid crew members to import")
    # Everyone added is hired on the job too — one read, one bulk insert, and
    # best-effort, so a failure imports the crew exactly as before jobs.
    if rows:
        rows = with_hire_ids(rows, hire_ids_for_new_crew(client, str(project_id), rows))
    inserted = client.table("crew_members").insert(rows).execute().data if rows else []
    return inserted + updated_rows
