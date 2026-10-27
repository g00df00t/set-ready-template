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
from models.contact import ContactCreate, ContactUpdate, ContactResponse, ContactImportParseRequest, ContactImportConfirmRequest
from services.claude_service import parse_contacts_import
from time_utils import split_call_time, split_call_time_lenient
from rate_limit import limiter, per_user, limit_by_user, PASTE_IMPORT_LIMIT
import usage

router = APIRouter(tags=["contacts"])


def _own_project(client, project_id: str, owner_ids: set[str]):
    result = client.table("projects").select("id").eq("id", project_id).in_("owner_id", list(owner_ids)).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Project not found")


@router.post("/projects/{project_id}/contacts", response_model=ContactResponse)
def add_contact(project_id: UUID, data: ContactCreate, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    _own_project(client, str(project_id), owner_ids)
    _ct = split_call_time(data.call_time)
    result = client.table("project_contacts").insert({
        "project_id": str(project_id),
        "roster_id": str(data.roster_id) if data.roster_id else None,
        "organization": data.organization,
        "name": data.name,
        "role": data.role,
        "email": data.email,
        "phone": data.phone,
        "call_time": _ct[0],
        "call_time_note": _ct[1],
        "sort_order": data.sort_order,
    }).execute()
    return result.data[0]


@router.get("/projects/{project_id}/contacts", response_model=List[ContactResponse])
def list_contacts(project_id: UUID, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    _own_project(client, str(project_id), owner_ids)
    result = client.table("project_contacts").select("*").eq("project_id", str(project_id)).order("sort_order").execute()
    return result.data


@router.put("/projects/{project_id}/contacts/{contact_id}", response_model=ContactResponse)
def update_contact(
    project_id: UUID,
    contact_id: UUID,
    data: ContactUpdate,
    owner_ids: set[str] = Depends(get_accessible_owner_ids),
    write_owner_id: str = Depends(get_write_owner_id),
):
    client = get_client()
    _own_project(client, str(project_id), owner_ids)
    updates = data.model_dump(exclude_none=True)
    if "call_time" in updates:
        # One field in, two columns out — and always both, so switching from a
        # clock time to "Own Call" (or back) can't leave the old value behind.
        updates["call_time"], updates["call_time_note"] = split_call_time(updates["call_time"])
    result = client.table("project_contacts").update(updates).eq("id", str(contact_id)).eq("project_id", str(project_id)).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Contact not found")
    row = result.data[0]
    # Same rule as crew and talent: a correction here fixes the master record too.
    if row.get("roster_id"):
        row["roster_synced"] = write_back_to_roster(client, row["roster_id"], write_owner_id, updates)
    return row


@router.delete("/projects/{project_id}/contacts/{contact_id}")
def remove_contact(project_id: UUID, contact_id: UUID, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    _own_project(client, str(project_id), owner_ids)
    result = client.table("project_contacts").delete().eq("id", str(contact_id)).eq("project_id", str(project_id)).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Contact not found")
    return {"ok": True}


@router.post("/projects/{project_id}/contacts/import/parse")
@limiter.limit(PASTE_IMPORT_LIMIT, key_func=per_user)
def parse_contacts_import_endpoint(
    request: Request,
    project_id: UUID,
    data: ContactImportParseRequest,
    owner_ids: set[str] = Depends(get_accessible_owner_ids),
    write_owner_id: str = Depends(get_write_owner_id),
    user_id: str = Depends(limit_by_user),
):
    client = get_client()
    _own_project(client, str(project_id), owner_ids)
    try:
        members = parse_contacts_import(data.text, usage.import_recorder(
            client, write_owner_id, str(project_id), usage.IMPORT_CONTACTS_PASTE))
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Could not parse contacts data: {str(e)}")

    # Same contract as crew: say what each row already is, decide nothing.
    # Failing to classify must not cost the parse the producer just paid for.
    try:
        project_rows = client.table("project_contacts").select(
            "id,name,email,phone,role,organization,call_time").eq("project_id", str(project_id)).execute().data
        roster_rows = client.table("roster").select(
            "id,name,email,phone,role,organization").in_("owner_id", list(owner_ids)).eq("type", "client").execute().data
        members = classify(members, project_rows, roster_rows)
    except Exception as e:
        logger.warning("contact import classification failed for %s: %s", project_id, e)
    return {"members": members}


@router.post("/projects/{project_id}/contacts/import/confirm")
def confirm_contacts_import(
    project_id: UUID,
    data: ContactImportConfirmRequest,
    owner_ids: set[str] = Depends(get_accessible_owner_ids),
    write_owner_id: str = Depends(get_write_owner_id),
):
    client = get_client()
    _own_project(client, str(project_id), owner_ids)
    # ⚠️ This function referenced an undefined `valid` before this change, so
    # every contacts Quick Import raised NameError and returned a 500. It is
    # rewritten here rather than patched, and the bug is worth remembering: the
    # crew and talent versions both defined it, so it read as correct at a glance.
    base = len(client.table("project_contacts").select("id").eq("project_id", str(project_id)).execute().data)
    named = [m for m in data.members if m.name.strip()]

    # The producer's choice from the preview wins; the API does not re-decide.
    skipped = [m for m in named if m.action == "skip"]
    updates = [m for m in named if m.action == "update" and m.match_id]
    adds = [m for m in named if m not in skipped and m not in updates]

    updated_rows = []
    for m in updates:
        ct = split_call_time_lenient(m.call_time)
        patch = {k: v for k, v in (("role", m.role), ("email", m.email),
                                   ("phone", m.phone), ("organization", m.organization))
                 if isinstance(v, str) and v.strip()}
        patch["call_time"], patch["call_time_note"] = ct
        updated_rows += client.table("project_contacts").update(patch).eq("id", str(m.match_id)).eq(
            "project_id", str(project_id)).execute().data

    # Everyone added lands in the Roster too, the same as adding one at a time.
    roster_ids: list = [None] * len(adds)
    if data.save_to_roster and adds:
        roster_ids = ensure_all_in_roster(
            client, write_owner_id,
            [{"name": m.name, "email": m.email, "phone": m.phone, "role": m.role} for m in adds],
            "client",
        )

    _times = [split_call_time_lenient(m.call_time) for m in adds]
    rows = [
        {
            "project_id": str(project_id),
            "roster_id": (str(m.match_id) if (m.match_state == "in_roster" and m.match_id)
                          else roster_ids[i]),
            "name": m.name,
            "organization": m.organization or None,
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
        raise HTTPException(status_code=422, detail="No valid contacts to import")
    inserted = client.table("project_contacts").insert(rows).execute().data if rows else []
    return inserted + updated_rows
