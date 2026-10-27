from fastapi import APIRouter, Depends, HTTPException, Request
from uuid import UUID
from typing import List, Optional
from database import get_client
from auth import get_accessible_owner_ids, get_write_owner_id
from services.person_match import find, Verdict
from services.roster_duplicates import find_duplicate_groups
from services.roster_merge import merge_entries

import logging

logger = logging.getLogger(__name__)
from services.roster_sync import propagate_from_roster
from services.job_hires import propagate_roster_to_hires
from models.roster import (
    RosterMergeRequest,
    RosterEntryCreate,
    RosterEntryUpdate,
    RosterEntryResponse,
    RosterImportParseRequest,
    RosterImportConfirmRequest,
)
from services.claude_service import (
    parse_crew_import,
    parse_talent_import,
    parse_contacts_import,
)

import usage
from services import call_sheet_import
from services.import_match import classify_against_roster
from starlette.concurrency import run_in_threadpool

from rate_limit import limiter, per_user, limit_by_user, PASTE_IMPORT_LIMIT

router = APIRouter(tags=["roster"])

#: Each upload is one model call with a whole PDF attached — the most expensive
#: request the app makes — so it is capped per account, not per token or IP.
CALL_SHEET_IMPORT_LIMIT = "20/hour"

_PARSERS = {
    "crew": parse_crew_import,
    "talent": parse_talent_import,
    "client": parse_contacts_import,
}


@router.get("/roster", response_model=List[RosterEntryResponse])
def list_roster(owner_ids: set[str] = Depends(get_accessible_owner_ids), type: Optional[str] = None):
    client = get_client()
    query = client.table("roster").select("*").in_("owner_id", list(owner_ids))
    if type:
        query = query.eq("type", type)
    result = query.order("name").execute()
    return result.data


@router.post("/roster", response_model=RosterEntryResponse)
def add_roster_entry(
    data: RosterEntryCreate,
    owner_ids: set[str] = Depends(get_accessible_owner_ids),
    write_owner_id: str = Depends(get_write_owner_id),
):
    client = get_client()
    # This endpoint fires automatically whenever someone is added to a project,
    # so it is where duplicates were being MADE. It used to decide "already known"
    # with ilike(name) — exact apart from case — which saw "Pat", "Pat Kehoe" and
    # "patrick kehoe" as three different people and duly created three entries.
    # Contact details decide now; see services/person_match.py.
    candidates = client.table("roster").select("*").in_("owner_id", list(owner_ids)).eq("type", data.type).execute().data
    found = find({"name": data.name, "email": data.email, "phone": data.phone}, candidates)

    if found.verdict is Verdict.MATCH:
        # Already on the roster: fill in only what the entry is MISSING. A blank
        # is never a correction (services/roster_sync.py's rule), and neither is
        # a different value typed into an Add form — that used to overwrite the
        # saved role and email (found testing staging, 2026-09-28: "Add" with a
        # known email quietly turned a Best Boy Grip into a Grip). Corrections
        # go through Edit, where the producer can see what they're changing.
        existing = found.entry
        # Every field the form has, not just contact details: the Roster page
        # says "anything they were missing was filled in", and a staging retest
        # found company and day rate silently dropped.
        updates = {k: v.strip() for k, v in data.model_dump(exclude={"name", "type"}).items()
                   if isinstance(v, str) and v.strip() and not (existing.get(k) or "").strip()}
        if updates:
            return client.table("roster").update(updates).eq("id", found.entry["id"]).execute().data[0]
        return found.entry

    if found.verdict is Verdict.AMBIGUOUS:
        # Two or more entries share these details and the name doesn't separate
        # them. Nothing here can ask, and picking one would silently merge two
        # people with no undo — so add the entry and leave it visible for the
        # duplicate view to offer later. A spare row is recoverable; a wrong
        # merge is not.
        logger.info("roster auto-save ambiguous for owner %s across %d entries",
                    write_owner_id, len(found.candidates))

    result = client.table("roster").insert({
        "owner_id": write_owner_id,
        "name": data.name,
        "email": data.email,
        "phone": data.phone,
        "role": data.role,
        "department": data.department,
        "organization": data.organization,
        "type": data.type,
        "company": data.company,
        "day_rate": data.day_rate,
        "rate_note": data.rate_note,
        "agency": data.agency,
        "agent_name": data.agent_name,
        "agent_email": data.agent_email,
        "agent_phone": data.agent_phone,
    }).execute()
    return result.data[0]


@router.post("/roster/import/parse")
@limiter.limit(PASTE_IMPORT_LIMIT, key_func=per_user)
def parse_roster_import(
    request: Request,
    data: RosterImportParseRequest,
    owner_ids: set[str] = Depends(get_accessible_owner_ids),
    write_owner_id: str = Depends(get_write_owner_id),
    user_id: str = Depends(limit_by_user),
):
    parser = _PARSERS.get(data.type)
    if parser is None:
        raise HTTPException(status_code=422, detail=f"Unknown roster type: {data.type}")
    client = get_client()
    try:
        members = parser(data.text, usage.import_recorder(
            client, write_owner_id, None, usage.IMPORT_ROSTER_PASTE))
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Could not parse pasted text: {str(e)}")
    # A paste is all one type — the tab it was pasted on — so every row is
    # checked against that type's Roster entries, the same as a call sheet row.
    people = [dict(m, type=data.type) for m in members if isinstance(m, dict)]
    return {"members": classify_against_roster(client, people, owner_ids)}


async def _read_capped(request: Request, limit: int) -> bytes:
    """The raw request body, refusing to read past `limit` bytes.

    The PDF arrives as the body itself (Content-Type: application/pdf), not as a
    multipart form: a form is parsed — and spooled to a temp file on disk — in
    full before any code here runs, whereas this stops reading at the cap and
    never writes the file anywhere.
    """
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise call_sheet_import.Rejected(
            f"That file is too big. Call sheets can be up to {limit // (1024 * 1024)} MB.", status=413)
    chunks, total = [], 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > limit:
            raise call_sheet_import.Rejected(
                f"That file is too big. Call sheets can be up to {limit // (1024 * 1024)} MB.", status=413)
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/roster/import/call-sheet")
@limiter.limit(CALL_SHEET_IMPORT_LIMIT, key_func=per_user)
async def parse_call_sheet_import(
    request: Request,
    user_id: str = Depends(limit_by_user),
    owner_ids: set[str] = Depends(get_accessible_owner_ids),
    write_owner_id: str = Depends(get_write_owner_id),
):
    """Read the people off an uploaded call sheet PDF — crew, talent and client.

    Parse only; nothing is saved. The producer reviews the rows on the Roster
    page, which then sends each type through /roster/import/confirm exactly as a
    paste import does. The body is the PDF itself, never stored.
    """
    client = get_client()
    try:
        data = await _read_capped(request, call_sheet_import.MAX_BYTES)
        # Blocking — PyMuPDF and a model call that takes several seconds — so
        # it runs off the event loop instead of stalling every other request.
        people = await run_in_threadpool(
            call_sheet_import.read_call_sheet, data,
            usage.import_recorder(client, write_owner_id, None, usage.IMPORT_ROSTER_CALL_SHEET))
    except call_sheet_import.Rejected as e:
        raise HTTPException(status_code=e.status, detail=str(e))
    except Exception as e:
        # The type only: the exception text can quote the model's reply, which
        # is a list of names and phone numbers.
        logger.warning("call sheet import failed for user %s: %s", user_id, type(e).__name__)
        raise HTTPException(
            status_code=502,
            detail="Couldn't read that call sheet. Try again, or paste the list instead.",
        )

    logger.info("call sheet import for user %s: %d people", user_id, len(people))
    if not people:
        return {"members": []}
    return {"members": await run_in_threadpool(classify_against_roster, client, people, owner_ids)}


@router.post("/roster/import/confirm", response_model=List[RosterEntryResponse])
def confirm_roster_import(
    data: RosterImportConfirmRequest,
    owner_ids: set[str] = Depends(get_accessible_owner_ids),
    write_owner_id: str = Depends(get_write_owner_id),
):
    client = get_client()
    valid = [m for m in data.members if m.name.strip()]
    if not valid:
        raise HTTPException(status_code=422, detail="No valid contacts to import")

    # Identity comes from services/person_match.py, the same rule the crew import
    # and the single-add path use. This endpoint used to dedupe on the name alone,
    # so pasting "Pat J Kehoe" beside an existing "Patrick Kehoe" made a second
    # person out of one — the exact duplicate this feature exists to stop.
    existing = client.table("roster").select("*").in_("owner_id", list(owner_ids)).eq("type", data.type).execute().data

    results = []
    to_insert = []
    for m in valid:
        dept = m.department if data.type == "crew" else None
        org = m.organization if data.type == "client" else None
        candidate = {"name": m.name, "email": m.email, "phone": m.phone}

        # Pending inserts are searched too, so one paste containing the same
        # person twice collapses into a single entry instead of two.
        found = find(candidate, existing + to_insert)

        if found.verdict is Verdict.MATCH and found.entry in to_insert:
            # Not saved yet — fill the gaps on the row about to be written.
            for key, value in (("email", m.email), ("phone", m.phone),
                               ("role", m.role), ("department", dept),
                               ("organization", org)):
                if value and not found.entry.get(key):
                    found.entry[key] = value
            continue

        if found.verdict is Verdict.MATCH:
            # Fill blanks only. A bulk paste is not the place to overwrite details
            # the producer has already curated.
            updates = {}
            for key, value in (("email", m.email), ("phone", m.phone), ("role", m.role),
                               ("department", dept), ("organization", org)):
                if value and not found.entry.get(key):
                    updates[key] = value
            if updates:
                results.append(client.table("roster").update(updates).eq("id", found.entry["id"]).execute().data[0])
            else:
                results.append(found.entry)
            continue

        # NONE, or AMBIGUOUS — which must not be resolved by guessing. A spare
        # row is recoverable; merging two people is not.
        to_insert.append({
            "owner_id": write_owner_id,
            "name": m.name,
            "email": m.email,
            "phone": m.phone,
            "role": m.role,
            "department": dept,
            "organization": org,
            "type": data.type,
        })

    if to_insert:
        inserted = client.table("roster").insert(to_insert).execute()
        results.extend(inserted.data)
    return results


def edits_from(data, required: tuple[str, ...]) -> dict:
    """The fields an edit actually sent, with an emptied optional field saved
    as empty. This used to be model_dump(exclude_none=True), which drops the
    null the form sends for a field the producer just cleared — so nothing
    could ever be removed: the old phone number came straight back. Fields the
    form didn't send stay untouched (exclude_unset), and a required field
    can't be blanked."""
    out = {}
    for k, v in data.model_dump(exclude_unset=True).items():
        if isinstance(v, str):
            v = v.strip() or None
        if v is None and k in required:
            continue
        out[k] = v
    return out


@router.put("/roster/{entry_id}", response_model=RosterEntryResponse)
def update_roster_entry(
    entry_id: UUID,
    data: RosterEntryUpdate,
    owner_ids: set[str] = Depends(get_accessible_owner_ids),
    write_owner_id: str = Depends(get_write_owner_id),
):
    client = get_client()
    updates = edits_from(data, required=("name", "type"))
    if not updates:
        result = client.table("roster").select("*").eq("id", str(entry_id)).in_("owner_id", list(owner_ids)).execute()
    else:
        result = client.table("roster").update(updates).eq("id", str(entry_id)).in_("owner_id", list(owner_ids)).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Entry not found")
    row = result.data[0]
    # Push the correction out to this person's rows on jobs that haven't shot
    # yet. Wrapped jobs are deliberately left alone. The counts come back so the
    # UI can say what happened — including how many stored call sheets now show
    # details that no longer match, since propagation updates rows and not
    # already-generated HTML. Targets the shared account (write_owner_id), not
    # necessarily whoever is editing — a team member's correction should reach
    # the same projects the owner's own edit would.
    synced = propagate_from_roster(client, str(entry_id), write_owner_id, updates)
    # And to their hires on jobs that haven't wrapped. Never raises.
    propagate_roster_to_hires(client, str(entry_id), write_owner_id, updates)
    row["synced"] = synced if synced["rows_updated"] else None
    return row


@router.delete("/roster/{entry_id}")
def delete_roster_entry(entry_id: UUID, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    result = client.table("roster").delete().eq("id", str(entry_id)).in_("owner_id", list(owner_ids)).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Entry not found")
    return {"ok": True}


@router.get("/roster/duplicates")
def list_roster_duplicates(owner_ids: set[str] = Depends(get_accessible_owner_ids), type: Optional[str] = None):
    """Entries that are probably the same person, grouped.

    Detection is the half that matters — a producer with 74 contacts does not
    find duplicates by scrolling. Nothing here changes anything; every group is a
    question for the person who knows the answer.
    """
    client = get_client()
    query = client.table("roster").select("*").in_("owner_id", list(owner_ids))
    if type:
        query = query.eq("type", type)
    entries = query.execute().data

    # Grouped per type: a crew entry and a client entry sharing an email are a
    # producer wearing two hats, not a duplicate to merge away.
    out = []
    for kind in sorted({e.get("type") or "crew" for e in entries}):
        of_kind = [e for e in entries if (e.get("type") or "crew") == kind]
        for group in find_duplicate_groups(of_kind):
            out.append({"type": kind, **group})
    return {"groups": out}


@router.post("/roster/merge")
def merge_roster_entries(data: RosterMergeRequest, write_owner_id: str = Depends(get_write_owner_id)):
    """Fold entries together: repoint their project rows, then delete them.

    Only safe because roster_id exists — before it, this could only have deleted
    a record while every project kept its own stale copy.
    """
    client = get_client()
    try:
        return merge_entries(client, write_owner_id, str(data.keep_id), [str(d) for d in data.drop_ids])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
