"""Jobs: the level above a shoot day (docs/job-layer-plan.md).

    Account   Master Roster · Location Roster · Team
    └─ Job    Pre-production │ Shoot days │ Wrap      ← this router
       └─ Day the existing /projects/{id}/* workspace, unchanged

The job owns hiring (job_hires) and the Whole crew dates; the day owns call
times. Days never need to know about each other — that coordination is what
sank the June attempt (plan §2).

Every route gates on get_accessible_owner_ids through _own_job, the same pattern
as _own_project, so team sharing covers jobs from day one. These routes are not
behind the beta flag: only the screens are (plan §11), and a team member on the
current version works on the same data.
"""

import logging
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from auth import get_accessible_owner_ids, get_write_owner_id
from database import get_client
from models.job import (
    DAY_PARTS, AddDay, CrewDatesUpdate, DayLabelsUpdate, HireCreate, HireShift, HireUpdate,
    JobCreate, JobResponse, JobUpdate, MoveDay,
)
from routers.account import job_defaults_for
from routers.attachments import delete_project_attachments
from services.receipt_store import delete_job_receipts
from routers.projects import copy_day
from services import job_dates
from services.job_dates import day_label
from services.job_rates import RATE_FIELDS, has_rates, suggest_rates
from services import holds
from services.talent_sheet import safe_link
from services.job_hires import (
    HIRE_FIELDS, ensure_all_in_job, sync_hire_to_days, _match_hire,
)
from services.person_match import Verdict
from services.roster_sync import write_back_to_roster
from services.roster_upsert import ensure_all_in_roster
from time_utils import to_pg_time

router = APIRouter(tags=["jobs"])
logger = logging.getLogger(__name__)


def _own_job(client, job_id: str, owner_ids: set[str]) -> dict:
    result = client.table("jobs").select("*").eq("id", job_id).in_("owner_id", list(owner_ids)).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Job not found")
    return result.data[0]


def _own_hire(client, job_id: str, hire_id: str) -> dict:
    rows = client.table("job_hires").select("*").eq("id", hire_id).eq("job_id", job_id).execute().data
    if not rows:
        raise HTTPException(status_code=404, detail="Hire not found")
    return rows[0]


def _clean(value):
    """Blank text lands as NULL, not "" — same rule the rest of the app uses so
    a document never prints an empty "Client:"."""
    if isinstance(value, str):
        return value.strip() or None
    return value


def _day_text_or_422(value) -> dict:
    try:
        return job_dates.validate_day_text(value)
    except job_dates.DatesError as e:
        raise HTTPException(status_code=422, detail=str(e))


def _segment(value) -> str | None:
    """A talent segment groups the hold sheet, so spacing must not split one
    section into two: "Northwind   Swim" is "Northwind Swim"."""
    return " ".join((value or "").split()) or None


def _status_or_422(status, rank) -> tuple[str, int | None]:
    try:
        return holds.validate_status(status, rank)
    except job_dates.DatesError as e:
        raise HTTPException(status_code=422, detail=str(e))


def _fill_slot(client, job: dict, slot_id: str, hire_id: str | None) -> None:
    """Point a role slot at a hire (or back to open with None). Best-effort:
    the hire itself never fails over its slot."""
    try:
        slots = [{**s, "hire_id": hire_id} if s.get("id") == slot_id else s for s in job.get("role_slots") or []]
        client.table("jobs").update({"role_slots": slots}).eq("id", job["id"]).execute()
    except Exception as e:
        logger.error("Filling role slot %s on job %s failed: %s", slot_id, job.get("id"), e, exc_info=True)


def _dates_or_422(value) -> dict:
    try:
        return job_dates.validate_dates(value)
    except job_dates.DatesError as e:
        raise HTTPException(status_code=422, detail=str(e))


def _short_date(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d:%b} {d.day}"


def _day_order_key(day: dict):
    """Shooting order: dated days by date, undated ones after, by creation."""
    return (day.get("shoot_date") is None, day.get("shoot_date") or "", day.get("created_at") or "")


def _off_dates(crew: list[dict], day: dict, dates_of: dict) -> dict:
    """Who's on this day's crew but not working it by their own dates — named,
    so the card can say who rather than "1 person"."""
    off = [c["name"] for c in crew if day.get("shoot_date") and c.get("hire_id") in dates_of
           and not _dates_cover(dates_of[c["hire_id"]], day["shoot_date"])]
    return {"off_dates_crew": len(off), "off_dates_names": off}


def _day_summaries(client, days: list[dict], job: dict | None = None) -> list[dict]:
    """One card per day: date, call time, confirmed count, sheet sent — and,
    given the job, how many of the day's crew aren't working it by their own
    dates (off_dates_crew). Hires only ever get ADDED to days automatically
    (_crew_days_up_to_date), so when someone's dates move off a day, this is
    how the day says so. Four queries however many days."""
    if not days:
        return []
    ids = [d["id"] for d in days]
    crew = client.table("crew_members").select("project_id,confirmed_at,hire_id,name").in_("project_id", ids).execute().data
    dates_of = {}
    if job and job.get("crew_dates"):
        hires = client.table("job_hires").select("*").eq("job_id", job["id"]).execute().data
        dates_of = {h["id"]: job_dates.effective_dates(job_dates.hire_base(job, h), h.get("dates_override")) for h in hires}
    sheets = client.table("call_sheets").select("project_id,sent_at").in_("project_id", ids).execute().data
    out = []
    for d in sorted(days, key=_day_order_key):
        mine = [c for c in crew if c["project_id"] == d["id"]]
        out.append({
            "id": d["id"], "name": d["name"], "shoot_date": d.get("shoot_date"),
            "general_call_time": d.get("general_call_time"),
            "crew_count": len(mine),
            # Crew only — talent have no confirmation at all (CLAUDE.md).
            "confirmed_count": len([c for c in mine if c.get("confirmed_at")]),
            "call_sheet_sent": any(s["project_id"] == d["id"] and s.get("sent_at") for s in sheets),
            **_off_dates(mine, d, dates_of),
        })
    return out


def _hire_view(job: dict, hire: dict, days_on: list[dict] | None = None) -> dict:
    """A hire as the Crew & dates table needs it. Everything the Sheet shows is
    worked out here, once, so the screen and the deal memo can't disagree.
    `days` is only included when it was looked up — an absent key is "not
    fetched", never "on no days"."""
    override = hire.get("dates_override") or {}
    base = job_dates.hire_base(job, hire)
    view = {
        **hire,
        "custom": job_dates.is_custom(override),
        "effective_dates": job_dates.effective_dates(base, override),
        "conflicts": job_dates.conflicts_for(job.get("crew_dates"), hire),
        "dates_text": job_dates.dates_block(base, override,
                                            job.get("day_labels"), hire.get("day_notes"), hire.get("kind")),
        "person_days": job_dates.person_days(base, override,
                                             job.get("day_labels"), hire.get("day_notes")),
    }
    if days_on is not None:
        view["days"] = days_on
    return view


def _rate_context(client, owner_ids: set[str], roster_ids: list[str]) -> tuple[dict, dict, dict]:
    """Everything suggest_rates needs for these people, in three queries:
    their Roster rows, their hires on the account's jobs, and those jobs.
    Scoped by owner throughout — a roster_id must never reach another
    producer's rates."""
    roster_ids = [r for r in roster_ids if r]
    if not roster_ids:
        return {}, {}, {}
    roster = {r["id"]: r for r in client.table("roster").select("id,day_rate,rate_note").in_(
        "id", roster_ids).in_("owner_id", list(owner_ids)).execute().data}
    hires = client.table("job_hires").select("*").in_("roster_id", roster_ids).execute().data
    jobs = {j["id"]: j for j in client.table("jobs").select("id,name,client_name,created_at").in_(
        "id", list({h["job_id"] for h in hires}) or ["00000000-0000-0000-0000-000000000000"]).in_(
        "owner_id", list(owner_ids)).execute().data}
    by_person: dict[str, list] = {}
    for h in hires:
        if h["job_id"] in jobs:
            by_person.setdefault(h["roster_id"], []).append((h, jobs[h["job_id"]]))
    return roster, by_person, jobs


def _suggestion_for(client, job: dict, owner_ids: set[str], roster_id: str | None) -> dict | None:
    """Best-effort: a missing rates migration or a failed read means no
    suggestion, never a failed hire."""
    if not roster_id:
        return None
    try:
        roster, past, _ = _rate_context(client, owner_ids, [roster_id])
        return suggest_rates(job, roster.get(roster_id), past.get(roster_id, []))
    except Exception as e:
        logger.error("Rate suggestion for %s failed: %s", roster_id, e, exc_info=True)
        return None


# ── Jobs ─────────────────────────────────────────────────────────────────────

@router.get("/jobs")
def list_jobs(owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    """The dashboard: every job with its day count and date span."""
    client = get_client()
    jobs = client.table("jobs").select("*").in_("owner_id", list(owner_ids)).order(
        "created_at", desc=True).execute().data
    if not jobs:
        return []
    days = client.table("projects").select("id,job_id,name,shoot_date,created_at").in_(
        "job_id", [j["id"] for j in jobs]).execute().data
    out = []
    for j in jobs:
        mine = sorted([d for d in days if d["job_id"] == j["id"]], key=_day_order_key)
        span = job_dates.date_span(j.get("crew_dates"), [d.get("shoot_date") for d in mine])
        out.append({**j, "day_count": len(mine),
                    "first_date": span[0] if span else None,
                    "last_date": span[1] if span else None,
                    "days": [{"id": d["id"], "name": d["name"], "shoot_date": d.get("shoot_date")}
                             for d in mine]})
    return out


@router.post("/jobs")
def create_job(data: JobCreate, write_owner_id: str = Depends(get_write_owner_id)):
    """New job, and its Day 1 — the guided flow lands on Pre-production with a
    day already there to fill in."""
    client = get_client()
    job = client.table("jobs").insert({
        "owner_id": write_owner_id,
        "name": data.name.strip() or "Untitled job",
        "client_name": _clean(data.client_name),
        "production_company": _clean(data.production_company),
        "payroll_provider": _clean(data.payroll_provider),
    }).execute().data[0]
    # The account's per diem, in a separate write so a database without
    # supabase/rates_v1.sql still creates the job.
    try:
        job = client.table("jobs").update(job_defaults_for(client, write_owner_id)).eq(
            "id", job["id"]).execute().data[0]
    except Exception as e:
        logger.error("Applying job defaults to %s failed: %s", job["id"], e, exc_info=True)
    day = client.table("projects").insert({
        "owner_id": write_owner_id,
        "job_id": job["id"],
        "name": job["name"],
        "shoot_date": data.shoot_date.isoformat() if data.shoot_date else None,
        "general_call_time": to_pg_time(data.general_call_time) if data.general_call_time else None,
    }).execute().data[0]
    return {"job": job, "day": day}


@router.get("/jobs/{job_id}")
def get_job(job_id: UUID, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    """The job and its Shoot days cards."""
    client = get_client()
    job = _own_job(client, str(job_id), owner_ids)
    days = client.table("projects").select("*").eq("job_id", str(job_id)).execute().data
    return {"job": job, "days": _day_summaries(client, days, job)}


@router.put("/jobs/{job_id}", response_model=JobResponse)
def update_job(job_id: UUID, data: JobUpdate, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    client = get_client()
    _own_job(client, str(job_id), owner_ids)
    updates = {k: _clean(v) for k, v in data.model_dump(exclude_unset=True).items()}
    if "name" in updates and not updates["name"]:
        raise HTTPException(status_code=422, detail="A job needs a name.")
    if not updates:
        return _own_job(client, str(job_id), owner_ids)
    return client.table("jobs").update(updates).eq("id", str(job_id)).execute().data[0]


@router.delete("/jobs/{job_id}")
def delete_job(job_id: UUID, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    """Deletes the job, every day in it and every hire. Stored attachment files
    don't cascade with their rows, so each day's are removed first — the same
    care delete_project takes."""
    client = get_client()
    _own_job(client, str(job_id), owner_ids)
    for d in client.table("projects").select("id").eq("job_id", str(job_id)).execute().data:
        delete_project_attachments(client, d["id"])
    delete_job_receipts(client, str(job_id))        # the PC log's kept receipts, the same way
    client.table("jobs").delete().eq("id", str(job_id)).execute()
    return {"ok": True}


@router.put("/jobs/{job_id}/crew-dates")
def update_crew_dates(job_id: UUID, data: CrewDatesUpdate, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    """Save the Whole crew row.

    Everyone following the crew dates moves with them. People with their own
    dates don't, so this answers with what no longer fits (`conflicts`, by hire)
    and how far the crew moved (`shift_days`) — what "Move with the crew" would
    shift each of them by. Nothing about anyone's own dates changes here.
    """
    client = get_client()
    job = _own_job(client, str(job_id), owner_ids)
    new = _dates_or_422(data.crew_dates)
    shift = job_dates.crew_shift_days(job.get("crew_dates"), new)
    job = client.table("jobs").update({"crew_dates": new}).eq("id", str(job_id)).execute().data[0]
    hires = client.table("job_hires").select("*").eq("job_id", str(job_id)).execute().data
    conflicts = {h["id"]: c for h in hires
                 if (c := job_dates.conflicts_for(new, h))}
    # Crew dates now reaching an existing day bring its people onto it.
    _crew_days_up_to_date(client, job, hires)
    return {"job": job, "shift_days": shift, "conflicts": conflicts}


@router.put("/jobs/{job_id}/day-labels")
def update_day_labels(job_id: UUID, data: DayLabelsUpdate, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    """Save the job's day labels — the whole map, as the screen holds it."""
    client = get_client()
    _own_job(client, str(job_id), owner_ids)
    labels = _day_text_or_422(data.day_labels)
    return client.table("jobs").update({"day_labels": labels}).eq("id", str(job_id)).execute().data[0]


# ── Hires ────────────────────────────────────────────────────────────────────

@router.get("/jobs/{job_id}/hires")
def list_hires(job_id: UUID, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    """The Crew & dates table: one row per hire, with their effective dates,
    any conflicts with the crew dates, and which days they're on.

    Carries each hire's agreed rates for the producer's Rate column, and for
    anyone without any yet a `rate_suggestion` (services/job_rates.py) — their
    last job for this client, else the Roster. Producer-only like the rest of
    this page: no crew-facing surface reads job_hires' rate columns.
    """
    client = get_client()
    job = _own_job(client, str(job_id), owner_ids)
    hires = client.table("job_hires").select("*").eq("job_id", str(job_id)).order("sort_order").execute().data
    days = {d["id"]: d for d in client.table("projects").select("id,name,shoot_date,created_at").eq(
        "job_id", str(job_id)).execute().data}
    on = client.table("crew_members").select("hire_id,project_id").in_(
        "project_id", list(days)).execute().data if days else []
    if days:
        try:   # talent hires' days are on the talent lists (talent_hires.sql)
            on += client.table("talent").select("hire_id,project_id").in_("project_id", list(days)).execute().data
        except Exception:
            pass
    out = []
    for h in hires:
        # A set: someone listed twice on one day's crew is still on that day once.
        mine = sorted([days[pid] for pid in {r["project_id"] for r in on if r.get("hire_id") == h["id"]}],
                      key=_day_order_key)
        out.append(_hire_view(job, h, [{"id": d["id"], "name": d["name"], "shoot_date": d.get("shoot_date")}
                                       for d in mine]))
    _add_rate_context(client, job, owner_ids, out)
    return out


def _add_rate_context(client, job: dict, owner_ids: set[str], views: list[dict]) -> None:
    """A suggestion for each hire with no rates, and the name of the job any
    saved rates came from. Best-effort: the table still loads without them."""
    # Talent: their agency, agent, home city and portfolio link from the Roster
    # — read live, they're the person's, not the deal.
    talent_ids = [str(v["roster_id"]) for v in views if v.get("kind") == "talent" and v.get("roster_id")]
    if talent_ids:
        try:
            info = {str(r["id"]): r for r in client.table("roster").select("*").in_("id", talent_ids).in_(
                "owner_id", list(owner_ids)).execute().data}
            for v in views:
                r = info.get(str(v.get("roster_id"))) if v.get("kind") == "talent" else None
                if r:
                    v["talent_info"] = {"agency": r.get("agency"), "agent": r.get("agent_name") or r.get("agent_email"),
                                        "based": r.get("based"), "portfolio_url": safe_link(r.get("portfolio_url"))}
        except Exception as e:
            logger.error("Talent info for job %s failed: %s", job.get("id"), e, exc_info=True)
    try:
        roster, past, jobs = _rate_context(client, owner_ids, list({v.get("roster_id") for v in views}))
        for v in views:
            if v.get("rate_source_job_id"):
                v["rate_source_job_name"] = (jobs.get(v["rate_source_job_id"]) or {}).get("name")
            if not has_rates(v) and v.get("roster_id"):
                v["rate_suggestion"] = suggest_rates(job, roster.get(v["roster_id"]), past.get(v["roster_id"], []))
    except Exception as e:
        logger.error("Rate context for job %s failed: %s", job.get("id"), e, exc_info=True)


@router.post("/jobs/{job_id}/hires")
def add_hire(
    job_id: UUID,
    data: HireCreate,
    owner_ids: set[str] = Depends(get_accessible_owner_ids),
    write_owner_id: str = Depends(get_write_owner_id),
):
    """Hire someone on the job, and put them on every upcoming day their dates
    include (_crew_days_up_to_date). "added_to_days" says how many, for the
    toast."""
    client = get_client()
    job = _own_job(client, str(job_id), owner_ids)
    person = {k: _clean(getattr(data, k)) for k in HIRE_FIELDS}
    person["roster_id"] = str(data.roster_id) if data.roster_id else None
    if not person["name"]:
        raise HTTPException(status_code=422, detail="A hire needs a name.")

    talent = data.kind == "talent"
    existing = client.table("job_hires").select("*").eq("job_id", str(job_id)).execute().data
    # Someone can't be hired twice as the same kind; crew and talent are
    # matched separately (a stylist who also models is two different hires).
    verdict, entry = _match_hire(person, [h for h in existing if (h.get("kind") == "talent") == talent])
    if verdict is Verdict.MATCH:
        raise HTTPException(status_code=409, detail=f"{entry['name']} is already hired on this job.")
    if verdict is Verdict.AMBIGUOUS:
        raise HTTPException(status_code=409, detail="That matches more than one person already hired on this job.")

    if not person["roster_id"] and data.save_to_roster:
        person["roster_id"] = ensure_all_in_roster(client, write_owner_id, [person], "talent" if talent else "crew")[0]

    dates = data.dates_override
    if talent and not dates:
        # Talent keep their own schedule: built from the shoot days they're
        # booked for — every crew shoot day if none were picked.
        picked = data.shoot_days or [d.isoformat() for d in job_dates._days((job.get("crew_dates") or {}).get("shoot", []))]
        try:
            dates = job_dates.talent_dates(picked)
        except job_dates.DatesError as e:
            raise HTTPException(status_code=422, detail=str(e))
    row = {"job_id": str(job_id), **person,
           "dates_override": _dates_or_422(dates),
           "sort_order": max([h.get("sort_order") or 0 for h in existing], default=-1) + 1}
    if data.status == "hold":
        # Only when it isn't the default, so a database without holds.sql
        # still hires people as it always has.
        row["status"], row["hold_rank"] = _status_or_422("hold", data.hold_rank)
    if talent:
        # Same rule: only set for talent, so crew hiring never depends on
        # talent_hires.sql. Her standard agency fee is 20%.
        row.update({"kind": "talent", "segment": _segment(data.segment), "agency_fee_pct": 20})
    hire = client.table("job_hires").insert(row).execute().data[0]
    # The deal starts as their last one for this client, else the Roster's —
    # copied, so it's this hire's from now on. A separate write: a hire is
    # never lost to its rates.
    suggestion = _suggestion_for(client, job, owner_ids, hire.get("roster_id"))
    if suggestion:
        try:
            hire = client.table("job_hires").update(
                {k: suggestion[k] for k in (*RATE_FIELDS, "rate_note", "rate_source", "rate_source_job_id")}
            ).eq("id", hire["id"]).execute().data[0]
        except Exception as e:
            logger.error("Saving prefilled rates for hire %s failed: %s", hire["id"], e, exc_info=True)
    added = _crew_days_up_to_date(client, job, [hire])
    if data.slot_id:
        _fill_slot(client, job, data.slot_id, hire["id"])
    return {**_hire_view(job, hire), "added_to_days": len(added.get(hire["id"], []))}


@router.put("/jobs/{job_id}/hires/{hire_id}")
def update_hire(
    job_id: UUID,
    hire_id: UUID,
    data: HireUpdate,
    owner_ids: set[str] = Depends(get_accessible_owner_ids),
    write_owner_id: str = Depends(get_write_owner_id),
):
    """Edit a hire. Person fields (name, email, phone) reach their rows on
    days that haven't wrapped, and their Master Roster entry — the same rules
    as correcting someone on a day. Role and department stay with the hire:
    someone can be listed differently on one day's sheet."""
    client = get_client()
    job = _own_job(client, str(job_id), owner_ids)
    hire = _own_hire(client, str(job_id), str(hire_id))
    updates = data.model_dump(exclude_unset=True)
    if "dates_override" in updates:
        updates["dates_override"] = _dates_or_422(updates["dates_override"])
    if "day_notes" in updates:
        updates["day_notes"] = _day_text_or_422(updates["day_notes"])
    if "status" in updates or "hold_rank" in updates:
        updates["status"], updates["hold_rank"] = _status_or_422(
            updates.get("status") or hire.get("status") or "confirmed", updates.get("hold_rank", hire.get("hold_rank")))
    for k in (*HIRE_FIELDS, "dates_note", "rate_note", "notes"):
        if k in updates:
            updates[k] = _clean(updates[k])
    if "segment" in updates:
        updates["segment"] = _segment(updates["segment"])
    if updates.get("rate_source_job_id"):
        updates["rate_source_job_id"] = str(updates["rate_source_job_id"])
        _own_job(client, updates["rate_source_job_id"], owner_ids)
    if updates.get("rate_source") != "job" and "rate_source" in updates:
        updates["rate_source_job_id"] = None
    if "name" in updates and not updates["name"]:
        raise HTTPException(status_code=422, detail="A hire needs a name.")
    if updates:
        hire = client.table("job_hires").update(updates).eq("id", str(hire_id)).execute().data[0]
    if "dates_override" in updates or "status" in updates:
        # Confirming puts them on their days; a hold or a release takes them
        # off any day nobody has touched.
        _crew_days_up_to_date(client, job, [hire])
    result = _hire_view(job, hire)
    result["days_synced"] = sync_hire_to_days(client, str(hire_id), updates)
    result["roster_synced"] = (write_back_to_roster(client, hire["roster_id"], write_owner_id, updates)
                               if hire.get("roster_id") else False)
    return result


@router.post("/jobs/{job_id}/hires/{hire_id}/shift")
def shift_hire_dates(job_id: UUID, hire_id: UUID, data: HireShift,
                     owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    """"Move with the crew": shift this person's own dates by the same number
    of days the crew moved (update_crew_dates says how many)."""
    client = get_client()
    job = _own_job(client, str(job_id), owner_ids)
    hire = _own_hire(client, str(job_id), str(hire_id))
    shifted = job_dates.shift_dates(hire.get("dates_override"), data.days)
    hire = client.table("job_hires").update({"dates_override": shifted}).eq("id", str(hire_id)).execute().data[0]
    _crew_days_up_to_date(client, job, [hire])
    return _hire_view(job, hire)


@router.delete("/jobs/{job_id}/hires/{hire_id}")
def remove_hire(job_id: UUID, hire_id: UUID, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    """Removes them from the job, and from any day where nothing's been done
    with them yet (_untouched — the rows hiring put there). Refused while a
    day holds their call time, confirmation or a sent sheet, or has already
    happened, naming those days ("Day 1 (Oct 20)"): removing someone then
    would silently delete the producer's work."""
    client = get_client()
    job = _own_job(client, str(job_id), owner_ids)
    _own_hire(client, str(job_id), str(hire_id))
    on = client.table("crew_members").select(
        "id,project_id,call_time,call_time_note,confirmed_at,last_sent_at").eq("hire_id", str(hire_id)).execute().data
    if on:
        job_days = client.table("projects").select("id,name,shoot_date,created_at").eq("job_id", str(job_id)).execute().data
        wrapped = {d["id"] for d in job_days if d.get("shoot_date") and d["shoot_date"] < date.today().isoformat()}
        kept = [r for r in on if not _untouched(r) or r["project_id"] in wrapped]
        if kept:
            held = [d for d in sorted(job_days, key=_day_order_key) if d["id"] in {r["project_id"] for r in kept}]

            def label(d):
                n = day_label(job.get("crew_dates"), job_days, d["id"])
                name = n.split(" of ")[0] if n else d["name"]
                return f"{name} ({_short_date(d['shoot_date'])})" if d.get("shoot_date") else name
            raise HTTPException(status_code=409, detail=(
                f"Still on {', '.join(label(d) for d in held)} with a call time or confirmation. "
                "Remove them from that day's Crew page first."))
        client.table("crew_members").delete().in_("id", [r["id"] for r in on]).execute()
    # Talent: off the day talent lists where nothing's been done with them.
    # A row with a call time stays, as the day's own record (its hire_id
    # empties when the hire goes).
    try:
        client.table("talent").delete().eq("hire_id", str(hire_id)).is_("call_time", "null").execute()
    except Exception as e:
        logger.error("Removing talent rows for hire %s failed: %s", hire_id, e, exc_info=True)
    client.table("job_hires").delete().eq("id", str(hire_id)).eq("job_id", str(job_id)).execute()
    # A role they filled goes back to open, not silently "filled by nobody".
    for s in job.get("role_slots") or []:
        if s.get("hire_id") == str(hire_id):
            _fill_slot(client, job, s["id"], None)
    return {"ok": True}


# ── Days ─────────────────────────────────────────────────────────────────────

@router.post("/jobs/{job_id}/days")
def add_day(
    job_id: UUID,
    data: AddDay,
    owner_ids: set[str] = Depends(get_accessible_owner_ids),
    write_owner_id: str = Depends(get_write_owner_id),
):
    """"Add a day": duplicate the job's most recent day into it, same people
    and same hires. A job with no days gets a blank one.

    With copy_from, blank or include set, this is "Set up a day" instead (the
    Shoot days placeholders): copy chosen parts of one of this job's days, or
    start blank, and in both cases crew the day with the people whose dates
    include it."""
    client = get_client()
    job = _own_job(client, str(job_id), owner_ids)
    shoot_date = data.shoot_date.isoformat() if data.shoot_date else None
    if data.copy_from or data.blank or data.include is not None:
        return _set_up_day(client, job, data, shoot_date)
    days = client.table("projects").select("*").eq("job_id", str(job_id)).execute().data
    if not days:
        return client.table("projects").insert({
            "owner_id": job["owner_id"], "job_id": job["id"],
            "name": (data.name or job["name"]).strip(), "shoot_date": shoot_date,
        }).execute().data[0]
    source = max(days, key=lambda d: (d.get("shoot_date") or "", d.get("created_at") or ""))
    # The job's owner, not write_owner_id: the day must belong to the same
    # account as the job it's in, whoever on the team clicked.
    return copy_day(client, source, job["owner_id"], name=(data.name or source["name"]).strip(),
                    job_id=job["id"], shoot_date=shoot_date)


# Set up a day, when nobody says which parts: everything a day in the same
# place shares. Schedule and notes are the day-to-day bits, so they're opt-in.
_DEFAULT_SETUP_PARTS = set(DAY_PARTS) - {"schedule", "notes"}


def _set_up_day(client, job: dict, data: AddDay, shoot_date: str | None) -> dict:
    include = set(data.include) if data.include is not None else _DEFAULT_SETUP_PARTS
    name = (data.name or job["name"]).strip()
    if data.blank or not data.copy_from:
        day = client.table("projects").insert({
            "owner_id": job["owner_id"], "job_id": job["id"], "name": name, "shoot_date": shoot_date,
        }).execute().data[0]
        rows = _crew_for_day(client, job, shoot_date, []) if "crew" in include else None
        if rows:
            client.table("crew_members").insert([{**r, "project_id": day["id"]} for r in rows]).execute()
        return day
    found = client.table("projects").select("*").eq("id", str(data.copy_from)).eq("job_id", job["id"]).execute().data
    if not found:
        raise HTTPException(status_code=404, detail="That day isn't in this job.")
    source = found[0]
    crew_rows = None
    if "crew" in include:
        source_crew = client.table("crew_members").select("*").eq("project_id", source["id"]).order("sort_order").execute().data
        crew_rows = _crew_for_day(client, job, shoot_date, source_crew)
    # The job's owner, not the clicker's: same reason as add_day.
    return copy_day(client, source, job["owner_id"], name=name, job_id=job["id"],
                    shoot_date=shoot_date, include=include, crew_rows=crew_rows)


def _untouched(row: dict) -> bool:
    """A day's crew row nobody has done anything with yet: no call time, not
    confirmed, no sheet sent to them. Removing one loses nothing, so it can
    follow the person's dates; anything else is the producer's work."""
    return not (row.get("call_time") or row.get("call_time_note")
                or row.get("confirmed_at") or row.get("last_sent_at"))


def _crew_days_up_to_date(client, job: dict, hires: list[dict] | None = None) -> dict[str, list[str]]:
    """Put each hire on every upcoming day in the job whose date their dates
    include, if they aren't on it already — {hire_id: [day ids added]}.

    The rule set-up days already follow (_crew_for_day), applied to days that
    exist: hire someone after Day 1 was made and they're on Day 1 too, instead
    of Day 1 being the one day that starts empty (Patrick, 2026-09-28).

    And the other way, but only for rows nobody has touched (_untouched): a
    day their dates no longer include loses them. Hiring uses the crew's
    dates, so the common "hire, then set their own dates" put people on Day 1
    for good and made Remove refuse (staging retest, 2026-09-28). A row with a
    call time, a confirmation or a sent sheet is the producer's work and
    stays — that day is flagged on the Shoot days tab instead
    (_day_summaries' off_dates_crew). Wrapped days are never touched; undated
    days can't be matched to dates. Best-effort: hiring or saving dates must
    not fail over it.
    """
    try:
        today = date.today().isoformat()
        days = [d for d in client.table("projects").select("id,shoot_date").eq("job_id", job["id"]).execute().data
                if d.get("shoot_date") and d["shoot_date"] >= today]
        if not days:
            return {}
        if hires is None:
            hires = client.table("job_hires").select("*").eq("job_id", job["id"]).execute().data
        talent = [h for h in hires if h.get("kind") == "talent"]
        hires = [h for h in hires if h.get("kind") != "talent"]
        if talent:
            _talent_days_up_to_date(client, days, job, talent)
        crew = client.table("crew_members").select(
            "id,project_id,hire_id,email,sort_order,call_time,call_time_note,confirmed_at,last_sent_at").in_(
            "project_id", [d["id"] for d in days]).execute().data
        next_order = {d["id"]: max((c.get("sort_order") or 0 for c in crew if c["project_id"] == d["id"]),
                                   default=-1) + 1 for d in days}
        rows, added, drop = [], {}, []
        for h in hires:
            # A hold or a release works no days: never put on a day's crew,
            # and taken off any day nobody has touched.
            mine = (job_dates.effective_dates(job_dates.hire_base(job, h), h.get("dates_override"))
                    if holds.is_booked(h) else {})
            email = (h.get("email") or "").strip().lower()
            for d in days:
                if not _dates_cover(mine, d["shoot_date"]):
                    drop.extend(c["id"] for c in crew
                                if c["project_id"] == d["id"] and c.get("hire_id") == h["id"] and _untouched(c))
                    continue
                if any(c["project_id"] == d["id"] and (c.get("hire_id") == h["id"] or
                                                       (email and (c.get("email") or "").strip().lower() == email))
                       for c in crew):
                    continue
                rows.append({
                    "project_id": d["id"], "hire_id": h["id"], "roster_id": h.get("roster_id"),
                    "name": h["name"], "email": h.get("email") or "", "role": h.get("role") or "",
                    "phone": h.get("phone"), "department": h.get("department"),
                    # Every key on every row: a bulk insert NULLs a missing key,
                    # and these two columns are NOT NULL.
                    "call_time": None, "call_time_note": None, "sort_order": next_order[d["id"]],
                    "hide_contact": False, "wants_pdf": False,
                })
                next_order[d["id"]] += 1
                added.setdefault(h["id"], []).append(d["id"])
        if rows:
            client.table("crew_members").insert(rows).execute()
        if drop:
            client.table("crew_members").delete().in_("id", drop).execute()
        return added
    except Exception as e:
        logger.error("job bookkeeping: adding hires to %s's days failed: %s", job.get("id"), e, exc_info=True)
        return {}


def _talent_days_up_to_date(client, days: list[dict], job: dict, hires: list[dict]) -> None:
    """The talent version of the crew sync above: each booked talent hire on
    the day's talent list for every upcoming day they shoot or have a fitting
    (job_dates.talent_on_day — never a travel day); off any
    day they no longer work where nothing's been done (no call time or note).
    Best-effort — a database without talent.hire_id just skips it."""
    try:
        rows = client.table("talent").select("id,project_id,hire_id,email,sort_order,call_time,call_time_note").in_(
            "project_id", [d["id"] for d in days]).execute().data
        next_order = {d["id"]: max((r.get("sort_order") or 0 for r in rows if r["project_id"] == d["id"]),
                                   default=-1) + 1 for d in days}
        add, drop = [], []
        for h in hires:
            mine = (job_dates.effective_dates(job_dates.hire_base(job, h), h.get("dates_override"))
                    if holds.is_booked(h) else {})
            email = (h.get("email") or "").strip().lower()
            for d in days:
                here = [r for r in rows if r["project_id"] == d["id"]]
                if not job_dates.talent_on_day(mine, d["shoot_date"]):
                    drop.extend(r["id"] for r in here if r.get("hire_id") == h["id"]
                                and not r.get("call_time") and not r.get("call_time_note"))
                    continue
                if any(r.get("hire_id") == h["id"] or (email and (r.get("email") or "").strip().lower() == email)
                       for r in here):
                    continue
                add.append({"project_id": d["id"], "hire_id": h["id"], "roster_id": h.get("roster_id"),
                            "name": h["name"], "email": h.get("email"), "phone": h.get("phone"),
                            "role": h.get("role"), "sort_order": next_order[d["id"]],
                            "call_time": None, "call_time_note": None, "hide_contact": True})
                next_order[d["id"]] += 1
        if add:
            client.table("talent").insert(add).execute()
        if drop:
            client.table("talent").delete().in_("id", drop).execute()
    except Exception as e:
        logger.error("job bookkeeping: talent days for %s failed: %s", job.get("id"), e, exc_info=True)


def _dates_cover(dates: dict | None, day: str) -> bool:
    """Working that day by their dates. A down day or a check-in is a date
    they're away, not one they work, so it never puts them on a day's crew."""
    return job_dates.works_on(dates, day)


def _crew_for_day(client, job: dict, day: str | None, source_crew: list[dict]) -> list[dict] | None:
    """The crew rows (no project_id yet) for a day being set up: everyone hired
    on the job whose dates include `day` — the crew's dates, or their own where
    they have them. Anyone also on the source day keeps that day's call time,
    order and settings; the rest arrive with no call time, after them.

    None when the job's crew dates don't reach `day` at all (an undated day, a
    scout outside the schedule): the dates can't say who's working, so the
    caller copies the source day's crew as it is, as Duplicate would."""
    if not day or not _dates_cover(job.get("crew_dates"), day):
        return None
    hire_ids = [m.get("hire_id") for m in source_crew]
    missing = [i for i, h in enumerate(hire_ids) if not h]
    if missing:
        # Someone on the source day from before jobs: hire them now, as
        # copy_day does, so they're counted as the same person.
        for i, h in zip(missing, ensure_all_in_job(client, job["id"], [source_crew[i] for i in missing])):
            hire_ids[i] = h
    hires = client.table("job_hires").select("*").eq("job_id", job["id"]).execute().data
    working = {h["id"]: h for h in hires
               if holds.is_booked(h) and h.get("kind") != "talent"
               and _dates_cover(job_dates.effective_dates(job_dates.hire_base(job, h), h.get("dates_override")), day)}

    rows, seen = [], set()
    for m, hid in zip(source_crew, hire_ids):
        if hid in working and hid not in seen:
            seen.add(hid)
            rows.append({
                "hire_id": hid, "roster_id": m.get("roster_id"),
                "name": m["name"], "email": m["email"], "role": m["role"], "phone": m.get("phone"),
                "department": m.get("department"), "call_time": m.get("call_time"),
                "call_time_note": m.get("call_time_note"), "sort_order": m.get("sort_order", 0),
                "hide_contact": m.get("hide_contact", False), "wants_pdf": m.get("wants_pdf", False),
            })
    order = max((r["sort_order"] for r in rows), default=-1) + 1
    for h in sorted(working.values(), key=lambda h: h.get("created_at") or ""):
        if h["id"] in seen:
            continue
        rows.append({
            "hire_id": h["id"], "roster_id": h.get("roster_id"),
            "name": h["name"], "email": h.get("email") or "", "role": h.get("role") or "",
            "phone": h.get("phone"), "department": h.get("department"), "call_time": None,
            # Every key the rows above carry: a bulk insert fills a missing
            # key with NULL, and these two columns are NOT NULL.
            "call_time_note": None, "sort_order": order, "hide_contact": False, "wants_pdf": False,
        })
        order += 1
    return rows


@router.post("/jobs/{job_id}/days/{day_id}/move")
def move_day(job_id: UUID, day_id: UUID, data: MoveDay, owner_ids: set[str] = Depends(get_accessible_owner_ids)):
    """Move a day into another job — needed once for existing data (two days of
    one shoot migrate as two one-day jobs). The day's crew are hired on the
    target job, matched by the same rules as adding them; hires on the old job
    are left as they are."""
    client = get_client()
    source = _own_job(client, str(job_id), owner_ids)
    target = _own_job(client, str(data.to_job_id), owner_ids)
    if source["id"] == target["id"]:
        raise HTTPException(status_code=400, detail="That day is already in this job.")
    if source["owner_id"] != target["owner_id"]:
        raise HTTPException(status_code=400, detail="Both jobs must belong to the same account.")
    rows = client.table("projects").select("id").eq("id", str(day_id)).eq("job_id", str(job_id)).execute().data
    if not rows:
        raise HTTPException(status_code=404, detail="Day not found in this job")

    client.table("projects").update({"job_id": target["id"]}).eq("id", str(day_id)).execute()
    crew = client.table("crew_members").select("*").eq("project_id", str(day_id)).execute().data
    hire_ids = ensure_all_in_job(client, target["id"], crew)
    for row, hid in zip(crew, hire_ids):
        # None unlinks rather than leaving a link into the old job's hires.
        client.table("crew_members").update({"hire_id": hid}).eq("id", row["id"]).execute()
    return {"ok": True, "crew_relinked": len([h for h in hire_ids if h]),
            "crew_unlinked": len([h for h in hire_ids if not h])}
