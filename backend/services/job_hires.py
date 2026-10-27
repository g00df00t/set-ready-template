"""Keeping every day inside a job, and everyone on a day hired on its job.

The job owns hiring, the day owns call times (docs/job-layer-plan.md §3, §6).
So adding someone to a day's crew makes sure they're hired on the job — the
same act as making sure they're in the Roster (roster_upsert.py), one level up,
and deduped by the same matcher so it can't manufacture duplicates either.

⚠️ BEST-EFFORT, ALL OF IT. These run inside the current version's own paths —
add crew, paste import, Duplicate, New project — for every account, flagged or
not, so that everyone's data is already in the job shape when they switch
(plan §11). That makes them the one way the Jobs beta could reach a producer who
never opted in. So nothing here raises: a failure is logged at ERROR (which
Sentry captures) and the caller carries on exactly as it did before jobs
existed. tests/test_job_bookkeeping_best_effort.py forces every one of these to
fail and checks the producer's action still succeeds.

A safety net for whatever fails quietly: scripts/backfill_jobs.py re-runs the
migration's backfill for an account, and opting in to the beta runs it first.
"""

import logging
from datetime import date

from services.person_match import contact_keys, find, name_key, Verdict
from services.roster_sync import person_updates

logger = logging.getLogger(__name__)

# The identity a hire shares with a crew row. Role and department are copied
# when a hire is CREATED from a day row, but never synced afterwards — someone
# hired as Gaffer can be listed differently on one day's sheet.
HIRE_FIELDS = ("name", "email", "phone", "role", "department")


def _log_failure(what: str, ref, exc: Exception) -> None:
    # ERROR, with the traceback, so Sentry's logging integration raises it as
    # an event. A warning would only be a breadcrumb, and a quietly failing
    # bookkeeping path is exactly what nobody would otherwise notice.
    logger.error("job bookkeeping: %s failed for %s: %s", what, ref, exc, exc_info=True)


def job_from_project(project: dict) -> dict:
    """The job a project would have been created inside: same owner and name,
    and the three job-level fields that used to live on the day."""
    return {
        "owner_id": project["owner_id"],
        "name": project.get("name") or "Untitled job",
        "client_name": project.get("client_name"),
        "production_company": project.get("production_company"),
        "payroll_provider": project.get("payroll_provider"),
    }


def create_job_for_project(client, project: dict) -> str | None:
    """Wrap a job-less project in a new job of its own. Returns the job id.

    Raises — callers inside the current version's paths go through
    ensure_job_for_project, which doesn't.
    """
    job = client.table("jobs").insert(job_from_project(project)).execute().data[0]
    client.table("projects").update({"job_id": job["id"]}).eq("id", project["id"]).execute()
    return job["id"]


def ensure_job_for_project(client, project_id: str) -> str | None:
    """The project's job id, creating a job for it if it has none. None when
    that couldn't be done — never raises."""
    try:
        rows = client.table("projects").select("*").eq("id", project_id).execute().data
        if not rows:
            return None
        project = rows[0]
        if project.get("job_id"):
            return project["job_id"]
        if "job_id" not in project:
            # The column doesn't exist: the migration hasn't run here yet. Not
            # an error worth paging on — jobs simply aren't live in this DB.
            return None
        return create_job_for_project(client, project)
    except Exception as e:
        _log_failure("ensure_job_for_project", project_id, e)
        return None


def _match_hire(person: dict, hires: list[dict]):
    """The hire this person already is, if any: roster_id first, then the one
    matcher everything else uses (services/person_match.py)."""
    rid = person.get("roster_id")
    if rid:
        by_roster = [h for h in hires if h.get("roster_id") and str(h["roster_id"]) == str(rid)]
        if len(by_roster) == 1:
            return Verdict.MATCH, by_roster[0]
    found = find(person, hires)
    # One hire shares this contact but carries a different name. On the Roster
    # that's surfaced for a human to judge; here nobody sees it, and producers
    # reuse their own email across several people (person_match's 2026-09-05
    # note). Merging them would link two humans to one hire, and the hire ↔ day
    # sync would then rename one person's rows after the other. A second hire
    # for one person is visible and harmless; a false merge is neither.
    named = name_key(person.get("name"))
    if (found.verdict is Verdict.MATCH and found.name_differs
            and named and name_key(found.entry.get("name"))):
        return Verdict.NONE, None
    # Likewise when the contact matches SEVERAL hires and the name is none of
    # theirs: that's one more person behind the shared email, not a guess
    # between the ones already hired.
    if (found.verdict is Verdict.AMBIGUOUS and named
            and all(contact_keys(person) & contact_keys(c) for c in found.candidates)
            and not any(name_key(c.get("name")) == named for c in found.candidates)):
        return Verdict.NONE, None
    return found.verdict, found.entry


def ensure_all_in_job(client, job_id: str, people: list[dict]) -> list:
    """A hire id for each person, hiring anyone the job doesn't have yet.

    Returns a list positionally matching `people`. An entry is None when the
    person couldn't be matched with confidence (AMBIGUOUS — two hires already
    fit, and choosing would merge two humans) or when anything failed. Never
    raises. One read and at most one bulk insert, however many people.
    """
    ids: list = [None] * len(people)
    if not job_id or not people:
        return ids
    try:
        hires = client.table("job_hires").select("*").eq("job_id", job_id).execute().data
        next_sort = max([h.get("sort_order") or 0 for h in hires], default=-1) + 1

        pending: list[dict] = []
        waiting: list[int] = []
        for i, p in enumerate(people):
            if not (p.get("name") or "").strip():
                continue
            # Pending rows are searched too, so one paste naming the same
            # person twice hires them once.
            verdict, entry = _match_hire(p, hires + pending)
            if verdict is Verdict.MATCH:
                if entry in pending:
                    waiting.append(i)
                else:
                    ids[i] = entry["id"]
                continue
            if verdict is Verdict.AMBIGUOUS:
                logger.info("job bookkeeping: %r matches several hires on job %s; left unlinked",
                            p.get("name"), job_id)
                continue
            row = {"job_id": job_id, "sort_order": next_sort + len(pending),
                   "roster_id": str(p["roster_id"]) if p.get("roster_id") else None}
            row.update({k: (p.get(k) or None) for k in HIRE_FIELDS})
            pending.append(row)
            waiting.append(i)

        if not pending:
            return ids
        created = client.table("job_hires").insert(pending).execute().data
        # Back to the people who asked, by identity rather than position — a
        # collapsed duplicate means fewer rows back than positions waiting.
        for i in waiting:
            verdict, entry = _match_hire(people[i], created)
            if verdict is Verdict.MATCH:
                ids[i] = entry["id"]
        return ids
    except Exception as e:
        _log_failure("ensure_all_in_job", job_id, e)
        return [None] * len(people)


def hire_ids_for_new_crew(client, project_id: str, people: list[dict]) -> list | None:
    """For crew rows about to be inserted on a day: the hire each one should
    link to. None (not a list) when the job layer isn't usable here — the
    caller then inserts exactly what it always did, without a hire_id key, so
    a database that hasn't had the migration yet sees no new column at all.
    """
    job_id = ensure_job_for_project(client, project_id)
    if not job_id:
        return None
    ids = ensure_all_in_job(client, job_id, people)
    return ids


def with_hire_ids(rows: list[dict], hire_ids: list | None) -> list[dict]:
    """Add hire_id to each crew row to be inserted — or leave the rows
    untouched when bookkeeping had nothing to offer."""
    if hire_ids is None:
        return rows
    return [{**r, "hire_id": hire_ids[i]} for i, r in enumerate(rows)]


# ── Hire ↔ day sync (person fields only) ─────────────────────────────────────

def wrapped_project_ids(client, project_ids: list[str]) -> set[str]:
    """Which of these days have already happened. Same rule as the Roster
    sync: a past shoot date is wrapped; no date is a day still being built."""
    if not project_ids:
        return set()
    today = date.today().isoformat()
    rows = client.table("projects").select("id,shoot_date").in_("id", project_ids).execute().data
    return {r["id"] for r in rows if r.get("shoot_date") and r["shoot_date"] < today}


def sync_hire_to_days(client, hire_id: str, updates: dict, skip_crew_id: str | None = None) -> int:
    """Push person-field changes on a hire out to their crew rows on days that
    haven't wrapped. Returns how many rows changed. Never raises."""
    changes = person_updates(updates)
    if not changes:
        return 0
    n = 0
    # A crew hire's rows are crew_members; a talent hire's are talent rows
    # (talent.hire_id, supabase/talent_hires.sql). Each table on its own, so a
    # database without the talent column still syncs crew.
    for table in ("crew_members", "talent"):
        try:
            rows = client.table(table).select("id,project_id").eq("hire_id", hire_id).execute().data
            rows = [r for r in rows if r["id"] != skip_crew_id]
            wrapped = wrapped_project_ids(client, list({r["project_id"] for r in rows}))
            for r in rows:
                if r["project_id"] in wrapped:
                    continue        # a finished day is a record, left as it was
                client.table(table).update(changes).eq("id", r["id"]).execute()
                n += 1
        except Exception as e:
            _log_failure(f"sync_hire_to_days ({table})", hire_id, e)
    return n


def sync_day_row_to_hire(client, crew_row: dict, updates: dict) -> bool:
    """A correction made on one day's crew row reaches the hire, and through it
    that person's other days on the job. Mirrors roster_sync.write_back_to_roster:
    only person fields, blanks ignored, never fails the edit itself."""
    hire_id = crew_row.get("hire_id")
    changes = person_updates(updates)
    if not hire_id or not changes:
        return False
    try:
        client.table("job_hires").update(changes).eq("id", hire_id).execute()
    except Exception as e:
        _log_failure("sync_day_row_to_hire", hire_id, e)
        return False
    sync_hire_to_days(client, hire_id, changes, skip_crew_id=crew_row.get("id"))
    return True


def unwrapped_job_ids(client, owner_id: str) -> set[str] | None:
    """This owner's jobs that haven't wrapped. A job has wrapped when every one
    of its days has; a job with no days yet is very much still open."""
    jobs = client.table("jobs").select("id").eq("owner_id", owner_id).execute().data
    if not jobs:
        return set()
    days = client.table("projects").select("job_id,shoot_date").in_(
        "job_id", [j["id"] for j in jobs]).execute().data
    today = date.today().isoformat()
    open_ids = set()
    for j in jobs:
        mine = [d for d in days if d.get("job_id") == j["id"]]
        if not mine or any(not d.get("shoot_date") or d["shoot_date"] >= today for d in mine):
            open_ids.add(j["id"])
    return open_ids


def propagate_roster_to_hires(client, roster_id: str, owner_id: str, updates: dict) -> int:
    """A Roster correction reaches this person's hires on unwrapped jobs, the
    way roster_sync.propagate_from_roster reaches their day rows. Never raises
    — it runs inside the Roster edit every account uses."""
    changes = person_updates(updates)
    if not changes:
        return 0
    try:
        open_ids = unwrapped_job_ids(client, owner_id)
        if not open_ids:
            return 0
        hires = client.table("job_hires").select("id,job_id").eq("roster_id", roster_id).execute().data
        n = 0
        for h in hires:
            if h["job_id"] in open_ids:
                client.table("job_hires").update(changes).eq("id", h["id"]).execute()
                n += 1
        return n
    except Exception as e:
        _log_failure("propagate_roster_to_hires", roster_id, e)
        return 0
