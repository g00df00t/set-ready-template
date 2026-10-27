"""The job bookkeeping can fail without the current version noticing.

    cd backend && venv/bin/python tests/test_job_bookkeeping_best_effort.py

This is the test that keeps the Jobs beta from ever reaching a producer who
didn't opt in (docs/job-layer-plan.md §11). The backend hires people onto jobs
inside the current version's own paths — add crew, paste import, Duplicate,
New project, corrections, the Master Roster — so if that bookkeeping could
raise, a producer on the old screens could lose an import to a feature they've
never seen.

Two ways it can go wrong, both forced here:

  1. The job tables fail on every query (a Supabase blip, a bad deploy).
  2. The migration hasn't been run at all — no job tables, no job_id or
     hire_id columns. The fake refuses a write naming a missing column, the
     way PostgREST does, so the current version's inserts must be exactly
     what they were before jobs.

Either way, every action must succeed, and a failure must be logged at ERROR
(what Sentry captures) — silent is the other way this goes wrong.
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.fake_supabase import FakeClient, pre_migration_schema  # noqa: E402
from routers import crew as crew_router, projects as projects_router, roster as roster_router  # noqa: E402
from routers import account as account_router  # noqa: E402
from models.crew import CrewMemberCreate, CrewMemberUpdate, CrewImportConfirmRequest  # noqa: E402
from models.project import ProjectCreate, ProjectUpdate  # noqa: E402
from models.roster import RosterEntryUpdate, RosterMergeRequest  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else '  -- ' + str(detail)}")
    if not ok:
        FAILS.append(name)


class Errors(logging.Handler):
    def __init__(self):
        super().__init__(logging.ERROR)
        self.records = []

    def emit(self, record):
        self.records.append(record)


errors = Errors()
logging.getLogger().addHandler(errors)
logging.getLogger().setLevel(logging.CRITICAL + 1)   # keep the output readable
for name in ("services.job_hires", "routers.projects", "services.roster_merge", "routers.crew"):
    logging.getLogger(name).setLevel(logging.ERROR)
    logging.getLogger(name).addHandler(errors)
    logging.getLogger(name).propagate = False

OWNER = {"o1"}
R1 = "00000000-0000-0000-0000-0000000000d1"
R2 = "00000000-0000-0000-0000-0000000000d2"


def seed(with_jobs: bool):
    project = {"id": "d1", "owner_id": "o1", "name": "Northwind", "shoot_date": None}
    if with_jobs:
        project["job_id"] = "j1"
    db = {
        "projects": [project,
                     {"id": "d_nojob", "owner_id": "o1", "name": "Old shoot", "shoot_date": None,
                      **({"job_id": None} if with_jobs else {})}],
        "crew_members": [{"id": "c1", "project_id": "d1", "name": "Dana Whitfield", "email": "dana@example.com",
                          "role": "Producer", "roster_id": R1, "sort_order": 0,
                          **({"hire_id": None} if with_jobs else {})}],
        "roster": [{"id": R1, "owner_id": "o1", "type": "crew", "name": "Dana Whitfield",
                    "email": "dana@example.com"},
                   {"id": R2, "owner_id": "o1", "type": "crew", "name": "Dana W",
                    "email": "dana@example.com"}],
        "call_sheets": [], "company_moves": [], "talent": [], "project_contacts": [],
        "schedule_items": [], "project_locations": [], "project_accommodations": [],
        "call_sheet_attachments": [], "team_members": [], "usage_events": [], "location_roster": [],
    }
    if with_jobs:
        db["jobs"] = [{"id": "j1", "owner_id": "o1", "name": "Northwind", "crew_dates": {}}]
        db["job_hires"] = []
    return db


def use(client):
    for mod in (crew_router, projects_router, roster_router, account_router):
        mod.get_client = lambda: client


# What each current-version insert looked like before jobs existed. The
# current version's writes must be these, key for key, when bookkeeping fails.
OLD_ADD_KEYS = {"project_id", "roster_id", "name", "email", "role", "phone", "call_time",
                "call_time_note", "department", "sort_order"}


def run_everything(client, label):
    """Every current-version path the job layer touches. Each must succeed."""
    ok = {}

    def attempt(name, fn):
        try:
            ok[name] = fn()
        except Exception as e:
            ok[name] = e
        check(f"{label}: {name} still works", not isinstance(ok[name], Exception), ok[name])

    attempt("add one crew member", lambda: crew_router.add_crew_member(
        "d1", CrewMemberCreate(name="Alex Kim", email="alex@example.com", role="Gaffer"), owner_ids=OWNER))
    attempt("add crew to a day with no job", lambda: crew_router.add_crew_member(
        "d_nojob", CrewMemberCreate(name="Jo Park", email="jo@example.com", role="Grip"), owner_ids=OWNER))
    attempt("paste import", lambda: crew_router.confirm_crew_import(
        "d1", CrewImportConfirmRequest(members=[{"name": "Sam Lee", "email": "sam@example.com", "role": "AC"},
                                                {"name": "Kit Moss", "role": "PA"}]),
        owner_ids=OWNER, write_owner_id="o1"))
    attempt("correct someone on a day", lambda: crew_router.update_crew_member(
        "d1", "c1", CrewMemberUpdate(phone="310-555-1111"), owner_ids=OWNER, write_owner_id="o1"))
    attempt("Duplicate", lambda: projects_router.duplicate_project("d1", owner_ids=OWNER, write_owner_id="o1"))
    attempt("Duplicate a day with no job", lambda: projects_router.duplicate_project(
        "d_nojob", owner_ids=OWNER, write_owner_id="o1"))
    attempt("New project", lambda: projects_router.create_project(
        ProjectCreate(name="Fresh"), owner_ids=OWNER, write_owner_id="o1"))
    attempt("edit client / payroll on the day", lambda: projects_router.update_project(
        "d1", ProjectUpdate(client_name="Northwind"), owner_ids=OWNER))
    attempt("edit a Master Roster entry", lambda: roster_router.update_roster_entry(
        R1, RosterEntryUpdate(phone="212-555-0000"), owner_ids=OWNER, write_owner_id="o1"))
    attempt("merge Master Roster duplicates", lambda: roster_router.merge_roster_entries(
        RosterMergeRequest(keep_id=R1, drop_ids=[R2]), write_owner_id="o1"))
    attempt("delete the account", lambda: account_router.delete_account(user_id="o1"))
    return ok


print("\n1. The job tables fail on every query")
db = seed(with_jobs=True)
client = FakeClient(db, fail={"jobs", "job_hires"})
use(client)
errors.records.clear()
out = run_everything(client, "tables failing")
row = out["add one crew member"]
check("the crew row is saved, just without a hire", isinstance(row, dict) and row.get("hire_id") is None, row)
nojob = out["add crew to a day with no job"]
check("on a day with no job (and no way to make one), the row is saved unlinked",
      isinstance(nojob, dict) and nojob.get("hire_id") is None, nojob)
check("the import brought everyone in", isinstance(out["paste import"], list) and len(out["paste import"]) == 2)
check("New project still made the project, just job-less",
      isinstance(out["New project"], dict) and not out["New project"].get("job_id"))
check("every failure was logged at ERROR, where Sentry sees it", len(errors.records) >= 5,
      f"{len(errors.records)} error records")
check("...and they say what failed",
      all("job bookkeeping" in r.getMessage() or "Deleting jobs" in r.getMessage() for r in errors.records),
      [r.getMessage() for r in errors.records][:3])

print("\n2. The migration hasn't been run at all")
db = seed(with_jobs=False)
client = FakeClient(db, schema=pre_migration_schema(db))
use(client)
errors.records.clear()
out = run_everything(client, "no migration")
row = out["add one crew member"]
check("the single-add insert is key-for-key what it was before jobs",
      isinstance(row, dict) and "hire_id" not in row and "job_id" not in row, row)
added = [r for r in db["crew_members"] if r["name"] == "Alex Kim"]
check("...and so is what reached the table", added and set(added[0]) - {"id"} <= OLD_ADD_KEYS | set(
    pre_migration_schema(seed(False))["crew_members"]), added)
# Account deletion does try `jobs` (and shrugs) — the auth user's cascade
# covers a database that has them. Nothing else may even try to write one.
check("nothing but account deletion tries to write a job table",
      [c for c in client.calls if c[0] in ("jobs", "job_hires") and c[1] != "select"] == [("jobs", "delete")],
      [c for c in client.calls if c[0] in ("jobs", "job_hires")])
check("Duplicate made a job-less copy, like before", isinstance(out["Duplicate"], dict)
      and "job_id" not in out["Duplicate"])
check("a database without jobs isn't treated as an outage — no ERROR noise from the day paths",
      not [r for r in errors.records if "ensure_job_for_project" in r.getMessage()],
      [r.getMessage() for r in errors.records])

print()
print("ALL PASS" if not FAILS else f"{len(FAILS)} FAILURES: " + ", ".join(FAILS))
sys.exit(1 if FAILS else 0)
