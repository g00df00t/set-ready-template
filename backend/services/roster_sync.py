"""Keeping a person's details in step between the Roster and their projects.

The Roster is the master record of a *person*. A project row is that person on a
*job*. Which fields belong to which is the whole design:

    person  ->  name, email, phone
    job     ->  role, department, call time, sort order, hide_contact, wants_pdf

Variance in the job column is the point — the same gaffer is a different role and
call time on every shoot. Variance in the person column is almost always a
mistake: in production, 1 person out of 68 who appear on more than one project
had contact details that disagreed, and 5 of 202 were entered under more than one
spelling of their name. So only the person fields sync, in both directions.

Two rules that came out of the design conversation and are enforced here:

1. **A wrapped job is never touched.** Correcting someone's number should not
   reach back into a shoot that already happened. Wrapped means the shoot date is
   in the past; a project with no shoot date counts as upcoming, because it is a
   job still being built and that is exactly where a correction should land.

   The same goes for a job's HIRES (job_hires, the person on a Job — whose
   phone the car service gets): a job is open while it has a day still to
   come, or no days yet. Hires were left out until 2026-10-02, so a corrected
   Roster number never reached the Travel tab.

2. **Propagation updates rows, not already-generated call sheets.** The sheet is
   stored HTML, frozen at generation. Fixing a phone number on three projects
   leaves three sheets showing the old one until each is regenerated, so the
   counts returned here include how many sheets went stale — a caller that
   doesn't surface it is lying to the producer.
"""

import logging
from datetime import date

logger = logging.getLogger(__name__)

# The tables holding a person on a job. All three link back the same way.
LINKED_TABLES = ("crew_members", "talent", "project_contacts")

# Fields that belong to the person rather than the job.
#
# Deliberately excludes company/day_rate/rate_note/agency/agent_* even though
# those are also person facts, not job facts. LINKED_TABLES above have no
# columns for them, so this tuple is the only thing standing between a Roster
# entry's rate and a job row — adding one of those names here would give
# propagate_from_roster a path to write it onto crew_members/talent/
# project_contacts, and from there call_sheet_data.py and wrap_report_data.py
# would have no reason not to render it. Keep rate and agent details
# Roster-only, read directly from there wherever they're actually needed.
PERSON_FIELDS = ("name", "email", "phone")


def person_updates(updates: dict) -> dict:
    """Just the person fields from a set of changes, dropping empties.

    A blank is not a correction — clearing the phone on one job shouldn't wipe
    the number from the producer's address book.
    """
    return {k: v for k, v in updates.items()
            if k in PERSON_FIELDS and isinstance(v, str) and v.strip()}


def unwrapped_project_ids(client, owner_id: str) -> set[str]:
    """Projects belonging to this owner whose shoot hasn't happened yet.

    A null shoot_date counts as upcoming — an unscheduled project is one being
    built, not one that wrapped.
    """
    rows = client.table("projects").select("id,shoot_date").eq("owner_id", owner_id).execute().data
    today = date.today().isoformat()
    return {r["id"] for r in rows if not r.get("shoot_date") or r["shoot_date"] >= today}


def propagate_from_roster(client, roster_id: str, owner_id: str, updates: dict) -> dict:
    """Push person-field changes out to linked rows on projects not yet wrapped.

    Returns what actually happened, so the caller can tell the producer rather
    than silently rewriting their jobs.
    """
    changes = person_updates(updates)
    if not changes:
        return {"rows_updated": 0, "projects_updated": 0, "sheets_now_stale": 0, "hires_updated": 0}

    hires_updated = _propagate_to_hires(client, roster_id, changes)
    open_ids = unwrapped_project_ids(client, owner_id)
    if not open_ids:
        return {"rows_updated": 0, "projects_updated": 0, "sheets_now_stale": 0, "hires_updated": hires_updated}

    rows_updated = 0
    touched: set[str] = set()
    for table in LINKED_TABLES:
        linked = client.table(table).select("id,project_id").eq("roster_id", roster_id).execute().data
        for row in linked:
            if row["project_id"] not in open_ids:
                continue          # wrapped — deliberately left alone
            client.table(table).update(changes).eq("id", row["id"]).execute()
            rows_updated += 1
            touched.add(row["project_id"])

    # A project with a stored sheet now shows details that no longer match its
    # rows. That is not an error, but the producer has to be told.
    stale = 0
    if touched:
        sheets = client.table("call_sheets").select("project_id").in_("project_id", list(touched)).execute().data
        stale = len({s["project_id"] for s in sheets})

    return {"rows_updated": rows_updated,
            "projects_updated": len(touched),
            "sheets_now_stale": stale,
            "hires_updated": hires_updated}


def _propagate_to_hires(client, roster_id: str, changes: dict) -> int:
    """The person's hires on jobs that haven't wrapped. Best-effort: a database
    without the job tables, or a failure here, never fails the Roster edit."""
    try:
        hires = client.table("job_hires").select("id,job_id").eq("roster_id", roster_id).execute().data
        if not hires:
            return 0
        job_ids = list({h["job_id"] for h in hires})
        days = client.table("projects").select("job_id,shoot_date").in_("job_id", job_ids).execute().data
        today = date.today().isoformat()
        wrapped = {j for j in job_ids
                   if (dates := [d.get("shoot_date") for d in days if d.get("job_id") == j])
                   and all(x and x < today for x in dates)}
        n = 0
        for h in hires:
            if h["job_id"] in wrapped:
                continue          # a finished job's records stay as they were
            client.table("job_hires").update(changes).eq("id", h["id"]).execute()
            n += 1
        return n
    except Exception as e:
        logger.warning("roster → hires sync skipped for %s: %s", roster_id, type(e).__name__)
        return 0


def write_back_to_roster(client, roster_id: str, owner_id: str, updates: dict) -> bool:
    """Push a correction made on a project back to the person's master record.

    The producer's decision, 2026-09-05: *"if you're correcting something that's
    wrong, having it corrected in the roster seems like it's the right choice."*

    Scoped by owner as well as id — the roster_id came off a row, and a row must
    never be able to reach another producer's address book.
    """
    changes = person_updates(updates)
    if not changes:
        return False
    try:
        result = (client.table("roster").update(changes)
                  .eq("id", roster_id).eq("owner_id", owner_id).execute())
        return bool(result.data)
    except Exception as e:
        # A failed write-back must never fail the edit the producer actually
        # asked for. Their change to the project is already saved.
        logger.warning("roster write-back failed for %s: %s", roster_id, e)
        return False
