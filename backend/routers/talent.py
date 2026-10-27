from fastapi import APIRouter, Depends, HTTPException, Request
from uuid import UUID
from typing import List
from database import get_client
from auth import get_accessible_owner_ids, get_write_owner_id
from services.import_match import classify
from services.roster_upsert import ensure_all_in_roster

import logging

logger = logging.getLogger(__name__)
from services.roster_sync import write_back_to_roster
from models.talent import TalentCreate, TalentUpdate, TalentResponse, TalentImportParseRequest, TalentImportConfirmRequest
from services.claude_service import parse_talent_import
from time_utils import split_call_time, split_call_time_lenient
from rate_limit import limiter, per_user, limit_by_user, PASTE_IMPORT_LIMIT
import usage

router = APIRouter(tags=["talent"])


def _own_project(client, project_id: str, owner_ids: set[str]):
    result = client.table("projects").select("id").eq("id", project_id).in_("owner_id", list(owner_ids)).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Project not found")


def _next_sort_order(client, project_id: str) -> int:
    existing = client.table("talent").select("id", count="exact").eq("project_id", project_id).execute()
    return existing.count or 0


@router.post("/projects/{project_id}/talent", response_model=TalentResponse)
def add_talent(project_id: UUID, data: TalentCreate, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    _own_project(client, str(project_id), owner_ids)
    _ct = split_call_time(data.call_time)
    result = client.table("talent").insert({
        "project_id": str(project_id),
        "roster_id": str(data.roster_id) if data.roster_id else None,
        "role": data.role,
        "name": data.name,
        "phone": data.phone,
        "email": data.email,
        "call_time": _ct[0],
        "call_time_note": _ct[1],
        "sort_order": _next_sort_order(client, str(project_id)),
        "location_assignment": data.location_assignment,
    }).execute()
    return result.data[0]


@router.get("/projects/{project_id}/talent", response_model=List[TalentResponse])
def list_talent(project_id: UUID, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    _own_project(client, str(project_id), owner_ids)
    result = client.table("talent").select("*").eq("project_id", str(project_id)).order("sort_order").execute()
    return result.data


@router.put("/projects/{project_id}/talent/{talent_id}", response_model=TalentResponse)
def update_talent(
    project_id: UUID,
    talent_id: UUID,
    data: TalentUpdate,
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
    result = client.table("talent").update(updates).eq("id", str(talent_id)).eq("project_id", str(project_id)).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Talent not found")
    row = result.data[0]
    # A correction made on a job travels back to the person's master record —
    # the producer's decision: if you are fixing something that is wrong, the
    # Roster should stop being wrong too. Only person fields move; role,
    # department and call time belong to this job. Never fails the edit itself.
    if row.get("roster_id"):
        row["roster_synced"] = write_back_to_roster(client, row["roster_id"], write_owner_id, updates)
    return row


@router.delete("/projects/{project_id}/talent/{talent_id}")
def remove_talent(project_id: UUID, talent_id: UUID, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    _own_project(client, str(project_id), owner_ids)
    result = client.table("talent").delete().eq("id", str(talent_id)).eq("project_id", str(project_id)).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Talent not found")
    return {"ok": True}


@router.post("/projects/{project_id}/talent/import/parse")
@limiter.limit(PASTE_IMPORT_LIMIT, key_func=per_user)
def parse_talent_import_endpoint(
    request: Request,
    project_id: UUID,
    data: TalentImportParseRequest,
    owner_ids: set[str] = Depends(get_accessible_owner_ids),
    write_owner_id: str = Depends(get_write_owner_id),
    user_id: str = Depends(limit_by_user),
):
    client = get_client()
    _own_project(client, str(project_id), owner_ids)
    try:
        members = parse_talent_import(data.text, usage.import_recorder(
            client, write_owner_id, str(project_id), usage.IMPORT_TALENT_PASTE))
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Could not parse talent data: {str(e)}")

    # Same contract as crew: say what each row already is, decide nothing.
    # Failing to classify must not cost the parse the producer just paid for.
    try:
        project_rows = client.table("talent").select(
            "id,name,email,phone,role,call_time").eq("project_id", str(project_id)).execute().data
        roster_rows = client.table("roster").select(
            "id,name,email,phone,role").in_("owner_id", list(owner_ids)).eq("type", "talent").execute().data
        members = classify(members, project_rows, roster_rows)
    except Exception as e:
        logger.warning("talent import classification failed for %s: %s", project_id, e)
    return {"members": members}


@router.post("/projects/{project_id}/talent/import/confirm")
def confirm_talent_import(
    project_id: UUID,
    data: TalentImportConfirmRequest,
    owner_ids: set[str] = Depends(get_accessible_owner_ids),
    write_owner_id: str = Depends(get_write_owner_id),
):
    client = get_client()
    _own_project(client, str(project_id), owner_ids)
    base = _next_sort_order(client, str(project_id))
    named = [m for m in data.members if m.name.strip()]

    # The producer's choice from the preview wins; the API does not re-decide.
    # A row with no action is added, which is what this endpoint did for
    # everything before the preview existed.
    skipped = [m for m in named if m.action == "skip"]
    updates = [m for m in named if m.action == "update" and m.match_id]
    adds = [m for m in named if m not in skipped and m not in updates]

    updated_rows = []
    for m in updates:
        ct = split_call_time_lenient(m.call_time)
        patch = {k: v for k, v in (("role", m.role), ("email", m.email), ("phone", m.phone)) if isinstance(v, str) and v.strip()}
        patch["call_time"], patch["call_time_note"] = ct
        updated_rows += client.table("talent").update(patch).eq("id", str(m.match_id)).eq(
            "project_id", str(project_id)).execute().data

    # Everyone added lands in the Roster too, the same as adding one at a time.
    roster_ids: list = [None] * len(adds)
    if data.save_to_roster and adds:
        roster_ids = ensure_all_in_roster(
            client, write_owner_id,
            [{"name": m.name, "email": m.email, "phone": m.phone, "role": m.role} for m in adds],
            "talent",
        )

    _times = [split_call_time_lenient(m.call_time) for m in adds]
    rows = [
        {
            "project_id": str(project_id),
            "roster_id": (str(m.match_id) if (m.match_state == "in_roster" and m.match_id)
                          else roster_ids[i]),
            "name": m.name,
            "role": m.role or None,
            "email": m.email or None,
            "phone": m.phone or None,
            "call_time": _times[i][0],
            "call_time_note": _times[i][1],
            "sort_order": base + i,
        }
        for i, m in enumerate(adds)
    ]
    if not rows and not updated_rows:
        # Everything skipped on purpose is a valid outcome, not a failure.
        if skipped:
            return []
        raise HTTPException(status_code=422, detail="No valid talent members to import")
    inserted = client.table("talent").insert(rows).execute().data if rows else []
    return inserted + updated_rows
