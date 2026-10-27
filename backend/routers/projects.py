from fastapi import APIRouter, Depends, HTTPException
from uuid import UUID
from typing import List
from database import get_client
from auth import get_accessible_owner_ids, get_write_owner_id
from models.project import (
    ProjectCreate, ProjectUpdate, ProjectResponse, LocationCreate, LocationResponse,
    AccommodationCreate, AccommodationResponse, MealPlanCreate, MealPlanResponse,
)
from time_utils import to_pg_time
from routers.attachments import delete_project_attachments
from services.job_hires import ensure_job_for_project, ensure_all_in_job, with_hire_ids

import logging

logger = logging.getLogger(__name__)

router = APIRouter(tags=["projects"])

# Project columns stored as Postgres `time`, normalized on the way in.
_TIME_FIELDS = (
    "general_call_time", "first_call_time", "first_shot_time", "lunch_time", "est_wrap_time",
)


def _own_project(client, project_id: str, owner_ids: set[str]) -> dict:
    result = client.table("projects").select("*").eq("id", project_id).in_("owner_id", list(owner_ids)).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Project not found")
    return result.data[0]


def _own_job(client, job_id: str, owner_ids: set[str]) -> dict:
    result = client.table("jobs").select("*").eq("id", job_id).in_("owner_id", list(owner_ids)).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Job not found")
    return result.data[0]


# The job-level fields that still live on the day in the current version.
# Mirrored up to the job when edited there, so an account that switches to Jobs
# later finds what it last typed (plan §11: the backend keeps everyone's data in
# the job shape as it's created).
_JOB_FIELDS = ("client_name", "production_company", "payroll_provider")


@router.post("/projects", response_model=ProjectResponse)
def create_project(
    data: ProjectCreate,
    owner_ids: set[str] = Depends(get_accessible_owner_ids),
    write_owner_id: str = Depends(get_write_owner_id),
):
    client = get_client()
    row = {
        "owner_id": write_owner_id,
        "name": data.name,
        "shoot_date": data.shoot_date.isoformat() if data.shoot_date else None,
        "general_call_time": to_pg_time(data.general_call_time) if data.general_call_time else None,
    }
    if data.job_id:
        # Asked for by name, from the Jobs screens: not best-effort. A job this
        # user can't reach is a 404, not a silently job-less day.
        row["job_id"] = _own_job(client, str(data.job_id), owner_ids)["id"]
    project = client.table("projects").insert(row).execute().data[0]
    if not project.get("job_id"):
        # Every new project gets a job, whichever version created it — a
        # one-day job is a job with one day. Best-effort: the project is made
        # either way.
        project["job_id"] = ensure_job_for_project(client, project["id"])
    return project


@router.get("/projects", response_model=List[ProjectResponse])
def list_projects(owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    result = client.table("projects").select("*").in_("owner_id", list(owner_ids)).order("created_at", desc=True).execute()
    return result.data


@router.get("/projects/{project_id}", response_model=ProjectResponse)
def get_project(project_id: UUID, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    return _own_project(client, str(project_id), owner_ids)


@router.put("/projects/{project_id}", response_model=ProjectResponse)
def update_project(project_id: UUID, data: ProjectUpdate, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    _own_project(client, str(project_id), owner_ids)
    updates = data.model_dump(exclude_unset=True)
    if "shoot_date" in updates and updates["shoot_date"]:
        updates["shoot_date"] = updates["shoot_date"].isoformat()
    # An explicit empty value clears the column — that's how a producer hides a
    # header pill, so it has to survive as NULL rather than be skipped.
    for field in _TIME_FIELDS:
        if field in updates:
            updates[field] = to_pg_time(updates[field]) if updates[field] else None
    result = client.table("projects").update(updates).eq("id", str(project_id)).execute()
    project = result.data[0]
    job_updates = {k: updates[k] for k in _JOB_FIELDS if k in updates}
    if job_updates and project.get("job_id"):
        try:
            client.table("jobs").update(job_updates).eq("id", project["job_id"]).execute()
        except Exception as e:
            logger.error("job bookkeeping: mirroring job fields failed for %s: %s",
                         project_id, e, exc_info=True)
    return project


@router.delete("/projects/{project_id}")
def delete_project(project_id: UUID, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    _own_project(client, str(project_id), owner_ids)
    # Metadata rows cascade with the project, but storage objects don't. Without
    # this the producer's uploaded files stay in the bucket after they delete the
    # job — and after they delete their account.
    delete_project_attachments(client, str(project_id))
    client.table("projects").delete().eq("id", str(project_id)).execute()
    return {"ok": True}


@router.put("/projects/{project_id}/location", response_model=LocationResponse)
def upsert_location(project_id: UUID, data: LocationCreate, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    _own_project(client, str(project_id), owner_ids)
    result = client.table("project_locations").upsert({
        "project_id": str(project_id),
        **data.model_dump(exclude_none=True),
    }, on_conflict="project_id").execute()
    return result.data[0]


@router.get("/projects/{project_id}/location", response_model=LocationResponse)
def get_location(project_id: UUID, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    _own_project(client, str(project_id), owner_ids)
    result = client.table("project_locations").select("*").eq("project_id", str(project_id)).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="No location set for this project")
    return result.data[0]


@router.put("/projects/{project_id}/accommodation", response_model=AccommodationResponse)
def upsert_accommodation(project_id: UUID, data: AccommodationCreate, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    _own_project(client, str(project_id), owner_ids)
    # A field the producer left blank arrives as "" and must be stored as NULL,
    # not as an empty string. The call sheet omits absent values — an empty
    # string is "present" and would print a bare "Booked under:" with nothing
    # after it.
    fields = {
        k: (v.strip() or None) if isinstance(v, str) else v
        for k, v in data.model_dump(exclude_none=True).items()
    }
    result = client.table("project_accommodations").upsert({
        "project_id": str(project_id),
        **fields,
    }, on_conflict="project_id").execute()
    return result.data[0]


@router.get("/projects/{project_id}/accommodation", response_model=AccommodationResponse)
def get_accommodation(project_id: UUID, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    _own_project(client, str(project_id), owner_ids)
    result = client.table("project_accommodations").select("*").eq("project_id", str(project_id)).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="No accommodation set for this project")
    return result.data[0]


@router.delete("/projects/{project_id}/accommodation")
def delete_accommodation(project_id: UUID, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    _own_project(client, str(project_id), owner_ids)
    client.table("project_accommodations").delete().eq("project_id", str(project_id)).execute()
    return {"ok": True}


_MEAL_TIME_FIELDS = ("breakfast_start", "breakfast_end", "lunch_start", "lunch_end")


@router.put("/projects/{project_id}/meals", response_model=MealPlanResponse)
def upsert_meals(project_id: UUID, data: MealPlanCreate, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    _own_project(client, str(project_id), owner_ids)
    # Every field is dumped, not just the set ones, so clearing a meal actually
    # clears it. A blank must land as NULL rather than "": the call sheet omits
    # absent values, and an empty string counts as present — it would print a
    # meal row with nothing in it.
    fields = {}
    for key, raw in data.model_dump().items():
        value = raw.strip() if isinstance(raw, str) else raw
        if not value:
            fields[key] = None
        else:
            fields[key] = to_pg_time(value) if key in _MEAL_TIME_FIELDS else value
    result = client.table("project_meals").upsert({
        "project_id": str(project_id),
        **fields,
    }, on_conflict="project_id").execute()
    return result.data[0]


@router.get("/projects/{project_id}/meals", response_model=MealPlanResponse)
def get_meals(project_id: UUID, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    _own_project(client, str(project_id), owner_ids)
    result = client.table("project_meals").select("*").eq("project_id", str(project_id)).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="No meal plan set for this project")
    return result.data[0]


@router.delete("/projects/{project_id}/meals")
def delete_meals(project_id: UUID, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    _own_project(client, str(project_id), owner_ids)
    client.table("project_meals").delete().eq("project_id", str(project_id)).execute()
    return {"ok": True}


@router.post("/projects/{project_id}/duplicate", response_model=ProjectResponse)
def duplicate_project(
    project_id: UUID,
    owner_ids: set[str] = Depends(get_accessible_owner_ids),
    write_owner_id: str = Depends(get_write_owner_id),
):
    client = get_client()
    source = _own_project(client, str(project_id), owner_ids)
    # Duplicate makes the next day of the same job, so Day 2's people are still
    # the same hires (plan §6). A project from before jobs gets its job here.
    job_id = source.get("job_id") or ensure_job_for_project(client, source["id"])
    return copy_day(client, source, write_owner_id, name=f"Copy of {source['name']}", job_id=job_id)


# What Duplicate (and the original "Add a day") has always copied. Meals and
# the day's general call time were never part of it, and Duplicate is live for
# everyone, so they only come across when "Set up a day" asks for them.
_DUPLICATE_PARTS = {"crew", "location", "talent", "contacts", "schedule", "hotel", "notes"}


def copy_day(client, source: dict, owner_id: str, *, name: str, job_id: str | None,
             shoot_date: str | None = None, include: set[str] | None = None,
             crew_rows: list[dict] | None = None) -> dict:
    """A new day with everything the source day had except its date, its
    call sheet and its confirmations. Shared by Duplicate and the job's
    "Add a day".

    `include` narrows it to some of models.job.DAY_PARTS ("Set up a day");
    None is Duplicate's own set. `crew_rows`, when given, is the crew to put on
    the new day instead of the source's (the people working that date, worked
    out by the caller); None copies the source day's crew."""
    pid = source["id"]
    explicit = include is not None
    parts = include if explicit else _DUPLICATE_PARTS

    # New project — no shoot date unless asked (user will set it)
    row = {"owner_id": owner_id, "name": name,
           "notes": source.get("notes") if "notes" in parts else None,
           "shoot_date": shoot_date}
    if explicit and "crew" in parts:
        row["general_call_time"] = source.get("general_call_time")
    if job_id:
        row["job_id"] = job_id
    new_project = client.table("projects").insert(row).execute().data[0]
    npid = new_project["id"]

    if "crew" in parts and crew_rows is not None:
        if crew_rows:
            client.table("crew_members").insert([{**r, "project_id": npid} for r in crew_rows]).execute()
        crew = []
    elif "crew" in parts:
        # Crew — new confirmation tokens generated by DB default
        crew = client.table("crew_members").select("*").eq("project_id", pid).execute().data
    else:
        crew = []
    if crew:
        rows = [{
            "project_id": npid,
            "name": m["name"],
            "email": m["email"],
            "role": m["role"],
            "phone": m.get("phone"),
            "call_time": m.get("call_time"),
            "department": m.get("department"),
            "sort_order": m.get("sort_order", 0),
            "hide_contact": m.get("hide_contact", False),
            "wants_pdf": m.get("wants_pdf", False),
        } for m in crew]
        if job_id:
            # Same hires, carried across. Anyone on the source day without a
            # hire yet (added before jobs, or bookkeeping missed them) is hired
            # now — best-effort, so a failure copies the day without links.
            hire_ids = [m.get("hire_id") for m in crew]
            missing = [i for i, h in enumerate(hire_ids) if not h]
            if missing:
                found = ensure_all_in_job(client, job_id, [crew[i] for i in missing])
                for i, h in zip(missing, found):
                    hire_ids[i] = h
            rows = with_hire_ids(rows, hire_ids)
        client.table("crew_members").insert(rows).execute()

    # Company moves — copied before talent so talent's location_assignment can be
    # remapped onto the new moves (each move gets a fresh ID on copy). PostgREST
    # returns inserted rows in input order, so we zip old→new to build the map.
    move_id_map = {}
    moves = (client.table("company_moves").select("*").eq("project_id", pid).order("sort_order").execute().data
             if "location" in parts else [])
    if moves:
        new_moves = client.table("company_moves").insert([{
            "project_id": npid,
            "label": m.get("label"),
            "location_name": m.get("location_name"),
            "address": m.get("address"),
            "parking_notes": m.get("parking_notes"),
            "parking_address": m.get("parking_address"),
            "additional_notes": m.get("additional_notes"),
            "move_time": str(m["move_time"]) if m.get("move_time") else None,
            "sort_order": m["sort_order"],
        } for m in moves]).execute().data
        move_id_map = {old["id"]: new["id"] for old, new in zip(moves, new_moves)}

    def _remap_assignment(a):
        # "primary" is project-relative so it carries as-is; a move assignment is
        # remapped to the duplicated move, or dropped if that move didn't copy.
        if not a or a == "primary":
            return a
        return move_id_map.get(a)

    # Talent
    talent = client.table("talent").select("*").eq("project_id", pid).execute().data if "talent" in parts else []
    if talent:
        client.table("talent").insert([{
            "project_id": npid,
            "name": t["name"],
            "role": t.get("role"),
            "email": t.get("email"),
            "phone": t.get("phone"),
            "call_time": t.get("call_time"),
            "location_assignment": _remap_assignment(t.get("location_assignment")),
            "sort_order": t["sort_order"],
            "hide_contact": t.get("hide_contact", True),
        } for t in talent]).execute()

    # Contacts
    contacts = (client.table("project_contacts").select("*").eq("project_id", pid).execute().data
                if "contacts" in parts else [])
    if contacts:
        client.table("project_contacts").insert([{
            "project_id": npid,
            "organization": c.get("organization"),
            "name": c["name"],
            "role": c.get("role"),
            "email": c.get("email"),
            "phone": c.get("phone"),
            "call_time": c.get("call_time"),
            "sort_order": c["sort_order"],
            "wants_pdf": c.get("wants_pdf", True),
        } for c in contacts]).execute()

    # Schedule
    schedule = (client.table("schedule_items").select("*").eq("project_id", pid).execute().data
                if "schedule" in parts else [])
    if schedule:
        client.table("schedule_items").insert([{
            "project_id": npid,
            "start_time": s["start_time"],
            "end_time": s.get("end_time"),
            "description": s["description"],
            "sort_order": s["sort_order"],
        } for s in schedule]).execute()

    # Location
    location = (client.table("project_locations").select("*").eq("project_id", pid).execute().data
                if "location" in parts else [])
    if location:
        loc = location[0]
        client.table("project_locations").insert({
            "project_id": npid,
            "location_name": loc.get("location_name"),
            "address": loc.get("address"),
            "parking_notes": loc.get("parking_notes"),
            "parking_address": loc.get("parking_address"),
            "additional_notes": loc.get("additional_notes"),
        }).execute()

    # Accommodation — a multi-day travel job duplicated into the next day is
    # staying at the same hotel, so this should carry.
    stay = (client.table("project_accommodations").select("*").eq("project_id", pid).execute().data
            if "hotel" in parts else [])
    if stay:
        s = stay[0]
        client.table("project_accommodations").insert({
            "project_id": npid,
            **{k: s.get(k) for k in (
                "hotel_name", "address", "phone", "website_url", "room_block",
                "check_in_time", "check_out_time", "amenities", "notes",
            )},
        }).execute()

    # Meals — only when asked (see _DUPLICATE_PARTS).
    meals = (client.table("project_meals").select("*").eq("project_id", pid).execute().data
             if "meals" in parts else [])
    if meals:
        m = meals[0]
        client.table("project_meals").insert({
            "project_id": npid,
            **{k: m.get(k) for k in (
                "breakfast_start", "breakfast_end", "breakfast_notes",
                "lunch_start", "lunch_end", "lunch_notes",
            )},
        }).execute()

    return new_project


@router.get("/projects/{project_id}/summary")
def get_project_summary(project_id: UUID, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    _own_project(client, str(project_id), owner_ids)
    pid = str(project_id)

    crew = client.table("crew_members").select("id,call_time").eq("project_id", pid).execute().data
    crew_count = len(crew)
    # Reported, not enforced. Leaving a call time off is a legitimate choice —
    # an agent who wants the sheet but isn't on set — so this is a notice the
    # producer can confirm, never a failed check that blocks "All clear".
    crew_missing_call_time = len([m for m in crew if not m.get("call_time")])
    talent_count = len(client.table("talent").select("id").eq("project_id", pid).execute().data)
    contact_count = len(client.table("project_contacts").select("id").eq("project_id", pid).execute().data)
    schedule_count = len(client.table("schedule_items").select("id").eq("project_id", pid).execute().data)

    location = client.table("project_locations").select("address").eq("project_id", pid).execute().data
    has_location = bool(location and location[0].get("address"))

    stay = client.table("project_accommodations").select("hotel_name,address").eq("project_id", pid).execute().data
    has_accommodation = bool(stay and (stay[0].get("hotel_name") or stay[0].get("address")))

    call_sheet = client.table("call_sheets").select("sent_at").eq("project_id", pid).order("generated_at", desc=True).limit(1).execute().data
    call_sheet_generated = bool(call_sheet)
    call_sheet_sent = bool(call_sheet and call_sheet[0].get("sent_at"))

    return {
        "crew_count": crew_count,
        "crew_missing_call_time": crew_missing_call_time,
        "talent_count": talent_count,
        "contact_count": contact_count,
        "schedule_item_count": schedule_count,
        "has_location": has_location,
        "has_accommodation": has_accommodation,
        "call_sheet_generated": call_sheet_generated,
        "call_sheet_sent": call_sheet_sent,
    }
