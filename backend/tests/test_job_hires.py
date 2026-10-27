"""The job owns hiring, the day owns call times.

    cd backend && venv/bin/python tests/test_job_hires.py

docs/job-layer-plan.md §6, rule by rule: adding someone to a day hires them on
the job exactly once; someone already hired is matched, by roster_id and by the
one person matcher; removing a hire is refused while they're on a day; person
fields sync hire ↔ day rows and role doesn't. Plus Duplicate and New project,
which have to keep every day inside a job.

Calls the route functions directly against tests/fake_supabase.py.
"""

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import HTTPException  # noqa: E402

from tests.fake_supabase import FakeClient  # noqa: E402
from routers import crew as crew_router, jobs as jobs_router, projects as projects_router  # noqa: E402
from routers import roster as roster_router  # noqa: E402
from models.crew import CrewMemberCreate, CrewMemberUpdate, CrewImportConfirmRequest  # noqa: E402
from models.job import HireCreate, HireUpdate, AddDay, CrewDatesUpdate, HireShift, MoveDay  # noqa: E402
from models.project import ProjectCreate  # noqa: E402
from models.roster import RosterEntryUpdate  # noqa: E402
from services.job_hires import ensure_all_in_job  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else '  -- ' + str(detail)}")
    if not ok:
        FAILS.append(name)


YESTERDAY = (date.today() - timedelta(days=1)).isoformat()
TOMORROW = (date.today() + timedelta(days=1)).isoformat()
OWNER = {"o1"}
# Ids that pass through a request model have to be real UUIDs.
R_DANA = "00000000-0000-0000-0000-0000000000d1"
H_DANA = "00000000-0000-0000-0000-0000000000a1"
H_OTHER = "00000000-0000-0000-0000-0000000000a2"
J1 = "00000000-0000-0000-0000-0000000000b1"
J2 = "00000000-0000-0000-0000-0000000000b2"
J_X = "00000000-0000-0000-0000-0000000000b9"


def make_db():
    return {
        "jobs": [{"id": J1, "owner_id": "o1", "name": "Northwind", "crew_dates": {}},
                 {"id": J2, "owner_id": "o1", "name": "Other job", "crew_dates": {}},
                 {"id": J_X, "owner_id": "o2", "name": "Someone else's", "crew_dates": {}}],
        "projects": [
            {"id": "d1", "owner_id": "o1", "job_id": J1, "name": "Northwind", "shoot_date": TOMORROW},
            {"id": "d2", "owner_id": "o1", "job_id": J1, "name": "Northwind", "shoot_date": YESTERDAY},
            {"id": "d3", "owner_id": "o1", "job_id": J2, "name": "Other job", "shoot_date": TOMORROW},
        ],
        "job_hires": [
            {"id": H_DANA, "job_id": J1, "name": "Dana Whitfield", "email": "dana@example.com",
             "phone": "310-555-0100", "role": "Producer", "roster_id": R_DANA, "sort_order": 0,
             "dates_override": {}},
            {"id": H_OTHER, "job_id": J2, "name": "Sam Other", "email": "sam@example.com",
             "sort_order": 0, "dates_override": {}},
        ],
        "crew_members": [],
        "roster": [{"id": R_DANA, "owner_id": "o1", "type": "crew", "name": "Dana Whitfield",
                    "email": "dana@example.com", "phone": "310-555-0100"}],
        "call_sheets": [], "company_moves": [], "talent": [], "project_contacts": [],
        "schedule_items": [], "project_locations": [], "project_accommodations": [],
        "call_sheet_attachments": [], "team_members": [],
    }


def use(db):
    client = FakeClient(db)
    for mod in (crew_router, jobs_router, projects_router, roster_router):
        mod.get_client = lambda: client
    return client


def add(pid, **kw):
    body = {"name": "Alex Kim", "email": "alex@example.com", "role": "Gaffer", **kw}
    return crew_router.add_crew_member(pid, CrewMemberCreate(**body), owner_ids=OWNER)


def hires(db, job):
    return [h for h in db["job_hires"] if h["job_id"] == job]


print("\nAdding someone to a day hires them on the job, once")
db = make_db(); use(db)
row = add("d1")
check("a new person gets exactly one hire", len(hires(db, J1)) == 2)
new_hire = [h for h in hires(db, J1) if h["name"] == "Alex Kim"][0]
check("the crew row links to it", row.get("hire_id") == new_hire["id"], row)
check("identity and role are copied onto the hire",
      new_hire["email"] == "alex@example.com" and new_hire["role"] == "Gaffer")
add("d1")
check("adding them again (another day, a re-add) creates no second hire", len(hires(db, J1)) == 2)

db = make_db(); use(db)
row = add("d1", name="Dana W.", email="different@example.com", roster_id=R_DANA)
check("already hired, matched by roster_id even with other details differing",
      row.get("hire_id") == H_DANA and len(hires(db, J1)) == 1, row)

db = make_db(); use(db)
row = add("d1", name="Dana Whitfield", email="DANA@example.com")
check("already hired, matched by the person matcher (email)",
      row.get("hire_id") == H_DANA and len(hires(db, J1)) == 1, row)

db = make_db(); use(db)
row = add("d1", name="Suki", email="dana@example.com", phone="310-555-0100", role="Grip")
check("a DIFFERENT name on a hire's email is a new person, not merged into the hire",
      row.get("hire_id") not in (None, H_DANA) and len(hires(db, J1)) == 2, row)
crew_router.update_crew_member("d1", row["id"], CrewMemberUpdate(name="Suki Kehoe"),
                               owner_ids=OWNER, write_owner_id="o1")
check("...so correcting her name never renames Dana's hire",
      [h for h in db["job_hires"] if h["id"] == H_DANA][0]["name"] == "Dana Whitfield")

print("\nBackfill: several people sharing the producer's email on one day")
db = make_db(); use(db)
db["crew_members"] = [
    {"id": f"c{i}", "project_id": "d3", "name": n, "email": "me@example.com", "role": r,
     "sort_order": i}
    for i, (n, r) in enumerate([("Pat Kehoe", "Producer"), ("Mandy", "PA"),
                                ("Suki", "Grip"), ("Pat Kehoe", "Producer")])]
db["job_hires"] = [h for h in db["job_hires"] if h["job_id"] != J2]
from services.job_backfill import backfill  # noqa: E402
r = backfill(FakeClient(db), apply=True)
links = {c["id"]: c.get("hire_id") for c in db["crew_members"] if c["project_id"] == "d3"}
check("three different people get three hires", len(hires(db, J2)) == 3,
      sorted(h["name"] for h in hires(db, J2)))
check("the same person twice on a day shares one hire", links["c0"] == links["c3"] and links["c0"])
check("...and nobody else is linked to it", len({links["c0"], links["c1"], links["c2"]}) == 3, links)

db = make_db(); use(db)
row = add("d1", name="Sam Other", email="sam@example.com")
check("a hire on ANOTHER job isn't reused — each job hires for itself",
      row.get("hire_id") not in (None, H_OTHER) and len(hires(db, J1)) == 2)

print("\nPaste import")
db = make_db(); use(db)
req = CrewImportConfirmRequest(members=[
    {"name": "Alex Kim", "email": "alex@example.com", "role": "Gaffer"},
    {"name": "Alex Kim", "email": "alex@example.com", "role": "Gaffer"},
    {"name": "Dana Whitfield", "email": "dana@example.com", "role": "Producer"},
    {"name": "Jo Park", "email": "jo@example.com", "role": "Key Grip"},
], save_to_roster=False)
rows = crew_router.confirm_crew_import("d1", req, owner_ids=OWNER, write_owner_id="o1")
check("four rows imported", len(rows) == 4)
check("one bulk insert for the hires: Alex once, Jo once, Dana matched",
      sorted(h["name"] for h in hires(db, J1)) == ["Alex Kim", "Dana Whitfield", "Jo Park"])
check("every imported row is linked", all(r.get("hire_id") for r in rows), rows)

print("\nAmbiguous never guesses")
db = make_db(); use(db)
db["job_hires"] += [{"id": "h_a", "job_id": J1, "name": "Chris Lee", "sort_order": 1, "dates_override": {}},
                    {"id": "h_b", "job_id": J1, "name": "Chris Lee", "sort_order": 2, "dates_override": {}}]
ids = ensure_all_in_job(FakeClient(db), J1, [{"name": "Chris Lee"}])
check("a name matching two hires is left unlinked, and nobody new is hired",
      ids == [None] and len(hires(db, J1)) == 3)

print("\n'Add from this job's hires'")
db = make_db(); use(db)
row = add("d1", name="Dana Whitfield", email="dana@example.com", hire_id=H_DANA)
check("a hire picked from this job is the link", row.get("hire_id") == H_DANA)
db = make_db(); use(db)
row = add("d1", name="Sam Other", email="sam@example.com", hire_id=H_OTHER)
check("a hire id from ANOTHER job is never trusted", row.get("hire_id") != H_OTHER, row)

print("\nAdding someone on the job doesn't add them to a day")
db = make_db(); use(db)
jobs_router.add_hire(J1, HireCreate(name="Jo Park", email="jo@example.com", save_to_roster=False),
                     owner_ids=OWNER, write_owner_id="o1")
check("hired", any(h["name"] == "Jo Park" for h in hires(db, J1)))
check("on no day", db["crew_members"] == [])
try:
    jobs_router.add_hire(J1, HireCreate(name="Dana Whitfield", email="dana@example.com"),
                         owner_ids=OWNER, write_owner_id="o1")
    check("hiring someone already hired is refused", False)
except HTTPException as e:
    check("hiring someone already hired is refused", e.status_code == 409, e.detail)
db = make_db(); use(db)
jobs_router.add_hire(J1, HireCreate(name="Jo Park", email="jo@example.com"),
                     owner_ids=OWNER, write_owner_id="o1")
check("someone typed in is saved to the Master Roster too",
      any(r["name"] == "Jo Park" for r in db["roster"])
      and [h for h in hires(db, J1) if h["name"] == "Jo Park"][0]["roster_id"])

print("\nRemoving")
db = make_db(); use(db)
row = add("d1", name="Dana Whitfield", email="dana@example.com")
crew_router.remove_crew_member("d1", row["id"], owner_ids=OWNER)
check("removing someone from a day leaves the hire", any(h["id"] == H_DANA for h in db["job_hires"]))
row = add("d1", name="Dana Whitfield", email="dana@example.com", call_time="07:00")
try:
    jobs_router.remove_hire(J1, H_DANA, owner_ids=OWNER)
    check("removing a hire with a call time on a day is refused", False)
except HTTPException as e:
    check("removing a hire with a call time on a day is refused", e.status_code == 409)
    check("...and the refusal names the day by number", "Day 2" in e.detail, e.detail)
check("...and nothing was deleted", any(h["id"] == H_DANA for h in db["job_hires"])
      and len(db["crew_members"]) == 1)
crew_router.remove_crew_member("d1", row["id"], owner_ids=OWNER)
jobs_router.remove_hire(J1, H_DANA, owner_ids=OWNER)
check("once off every day, the hire can go", not any(h["id"] == H_DANA for h in db["job_hires"]))

db = make_db(); use(db)
add("d1", name="Dana Whitfield", email="dana@example.com")      # no call time: untouched
jobs_router.remove_hire(J1, H_DANA, owner_ids=OWNER)
check("a hire on a day where nothing's been done with them can go",
      not any(h["id"] == H_DANA for h in db["job_hires"]))
check("...and comes off that day with them", db["crew_members"] == [], db["crew_members"])

print("\nPerson fields sync hire ↔ day rows; role doesn't")
db = make_db(); use(db)
on_d1 = add("d1", name="Dana Whitfield", email="dana@example.com", role="Producer")
# d2 has wrapped; put Dana on it directly, the way she'd have been added then.
db["crew_members"].append({"id": "c_old", "project_id": "d2", "hire_id": H_DANA, "name": "Dana Whitfield",
                           "email": "dana@example.com", "phone": "310-555-0100", "role": "Producer"})
jobs_router.update_hire(J1, H_DANA, HireUpdate(phone="310-555-9999", role="EP"),
                        owner_ids=OWNER, write_owner_id="o1")
d1_row = [c for c in db["crew_members"] if c["id"] == on_d1["id"]][0]
old_row = [c for c in db["crew_members"] if c["id"] == "c_old"][0]
check("a hire's phone reaches their row on an upcoming day", d1_row["phone"] == "310-555-9999")
check("a WRAPPED day is left as it was", old_row["phone"] == "310-555-0100")
check("role stays with the hire, not their day rows", d1_row["role"] == "Producer")
check("...and the correction reaches the Master Roster", db["roster"][0]["phone"] == "310-555-9999")

db = make_db(); use(db)
a = add("d1", name="Dana Whitfield", email="dana@example.com")
db["projects"].append({"id": "d4", "owner_id": "o1", "job_id": J1, "name": "Northwind", "shoot_date": None})
b = add("d4", name="Dana Whitfield", email="dana@example.com")
crew_router.update_crew_member("d1", a["id"], CrewMemberUpdate(email="dana@new.example.com", role="Line Producer"),
                               owner_ids=OWNER, write_owner_id="o1")
hire = [h for h in db["job_hires"] if h["id"] == H_DANA][0]
other_day = [c for c in db["crew_members"] if c["id"] == b["id"]][0]
check("a correction on one day reaches the hire", hire["email"] == "dana@new.example.com")
check("...and their other days on the job", other_day["email"] == "dana@new.example.com")
check("a role change on one day doesn't reach the hire", hire["role"] == "Producer")
check("...or their other days", other_day["role"] == "Gaffer")

print("\nMaster Roster edits reach hires on jobs that haven't wrapped")
db = make_db(); use(db)
db["job_hires"].append({"id": "h_wrapped", "job_id": "j_w", "name": "Dana Whitfield", "roster_id": R_DANA,
                        "phone": "310-555-0100", "dates_override": {}, "sort_order": 0})
db["jobs"].append({"id": "j_w", "owner_id": "o1", "name": "Last spring", "crew_dates": {}})
db["projects"].append({"id": "d_w", "owner_id": "o1", "job_id": "j_w", "name": "Last spring",
                       "shoot_date": YESTERDAY})
roster_router.update_roster_entry(R_DANA, RosterEntryUpdate(phone="212-555-0000"),
                                  owner_ids=OWNER, write_owner_id="o1")
by_id = {h["id"]: h for h in db["job_hires"]}
check("hire on an open job updated", by_id[H_DANA]["phone"] == "212-555-0000")
check("hire on a job whose every day has wrapped is left alone", by_id["h_wrapped"]["phone"] == "310-555-0100")
check("a job with one wrapped day and one upcoming day is still open — j1 has both",
      by_id[H_DANA]["phone"] == "212-555-0000")

print("\nEvery day stays inside a job")
db = make_db(); use(db)
p = projects_router.create_project(ProjectCreate(name="Fresh shoot"), owner_ids=OWNER, write_owner_id="o1")
job = [j for j in db["jobs"] if j["id"] == p["job_id"]]
check("New project (current version) gets a one-day job of its own",
      job and job[0]["name"] == "Fresh shoot" and job[0]["owner_id"] == "o1", p)
p = projects_router.create_project(ProjectCreate(name="Day 3", job_id=J1), owner_ids=OWNER, write_owner_id="o1")
check("a day created inside a job joins it", p["job_id"] == J1)
try:
    projects_router.create_project(ProjectCreate(name="Sneaky", job_id=J_X), owner_ids=OWNER, write_owner_id="o1")
    check("a day can't be created in someone else's job", False)
except HTTPException as e:
    check("a day can't be created in someone else's job", e.status_code == 404)

db = make_db(); use(db)
add("d1", name="Dana Whitfield", email="dana@example.com")
add("d1")
db["crew_members"].append({"id": "c_legacy", "project_id": "d1", "name": "Jo Park", "email": "jo@example.com",
                           "role": "Key Grip", "hire_id": None})
copy = projects_router.duplicate_project("d1", owner_ids=OWNER, write_owner_id="o1")
copied = [c for c in db["crew_members"] if c["project_id"] == copy["id"]]
check("Duplicate keeps the day in the same job", copy.get("job_id") == J1, copy)
check("...with every crew row carrying its hire", len(copied) == 3 and all(c.get("hire_id") for c in copied), copied)
check("...Dana's is the same hire as on Day 1", any(c["hire_id"] == H_DANA for c in copied))
check("...and a row that had no hire yet is hired on the way", len(hires(db, J1)) == 3)

db = make_db(); use(db)
db["projects"].append({"id": "d_old", "owner_id": "o1", "job_id": None, "name": "Pre-jobs shoot"})
copy = projects_router.duplicate_project("d_old", owner_ids=OWNER, write_owner_id="o1")
src = [p for p in db["projects"] if p["id"] == "d_old"][0]
check("Duplicating a day from before jobs puts both in one new job",
      src["job_id"] and copy.get("job_id") == src["job_id"], (src, copy))

db = make_db(); use(db)
add("d1", name="Dana Whitfield", email="dana@example.com")
day = jobs_router.add_day(J1, AddDay(), owner_ids=OWNER, write_owner_id="o1")
check("Add a day copies the job's latest day, into this job", day["job_id"] == J1)
check("...with the same hires", any(c["project_id"] == day["id"] and c.get("hire_id") == H_DANA
                                    for c in db["crew_members"]))

print("\nSaving the Whole crew row, and Move with the crew")
db = make_db(); use(db)
crew_dates = {"travel": [["2026-10-12", "2026-10-12"]], "shoot": [["2026-10-13", "2026-10-16"]]}
jobs_router.update_crew_dates(J1, CrewDatesUpdate(crew_dates=crew_dates), owner_ids=OWNER)
[h for h in db["job_hires"] if h["id"] == H_DANA][0]["dates_override"] = {
    "travel": [["2026-10-09", "2026-10-09"]], "prep": [["2026-10-10", "2026-10-12"]]}
# The whole schedule moves twelve days earlier, travel and all — far enough
# that her own dates are left adrift. (A small move leaves dates that still
# look legal; the page's "Move them too" banner is what catches those.)
res = jobs_router.update_crew_dates(J1, CrewDatesUpdate(crew_dates={"travel": [["2026-09-30", "2026-09-30"]],
                                                                    "shoot": [["2026-10-01", "2026-10-04"]]}),
                                    owner_ids=OWNER)
check("moving the crew's shoot says how far it moved", res["shift_days"] == -12, res["shift_days"])
check("...and flags the custom person it left adrift", H_DANA in res["conflicts"], res["conflicts"])
check("...without touching their dates",
      [h for h in db["job_hires"] if h["id"] == H_DANA][0]["dates_override"]["prep"] == [["2026-10-10", "2026-10-12"]])
view = jobs_router.shift_hire_dates(J1, H_DANA, HireShift(days=-12), owner_ids=OWNER)
check("Move with the crew shifts them and clears the conflict", view["conflicts"] == [], view["conflicts"])
try:
    jobs_router.update_crew_dates(J1, CrewDatesUpdate(crew_dates={"lunch": []}), owner_ids=OWNER)
    check("a malformed crew row is a readable 422", False)
except HTTPException as e:
    check("a malformed crew row is a readable 422", e.status_code == 422 and "lunch" in e.detail, e.detail)
add("d1", name="Dana Whitfield", email="dana@example.com")
add("d1", name="Dana Whitfield", email="dana@example.com")
listed = jobs_router.list_hires(J1, owner_ids=OWNER)
dana_days = [h for h in listed if h["id"] == H_DANA][0]["days"]
check("someone listed twice on one day is on that day once", [d["id"] for d in dana_days] == ["d1"], dana_days)
# The hires list is the producer's Pre-production table and does carry each
# hire's agreed rate now (services/job_rates.py, the producer 2026-10-01). What must
# never carry one is a day's crew row — the call sheet, its email and the
# confirm page all read those.
check("a day's crew rows carry no rate", not any("rate" in k for c in db["crew_members"] for k in c),
      [list(c) for c in db["crew_members"]][:1])

print("\nMove a day")
db = make_db(); use(db)
add("d1", name="Dana Whitfield", email="dana@example.com")
add("d1")
res = jobs_router.move_day(J1, "d1", MoveDay(to_job_id=J2), owner_ids=OWNER)
moved_rows = [c for c in db["crew_members"] if c["project_id"] == "d1"]
check("the day is in the other job", [p for p in db["projects"] if p["id"] == "d1"][0]["job_id"] == J2)
check("its crew are hired on the new job", all(
    [h for h in db["job_hires"] if h["id"] == c["hire_id"]][0]["job_id"] == J2 for c in moved_rows), moved_rows)
check("the old job's hires are left as they were", any(h["id"] == H_DANA for h in db["job_hires"]))
try:
    jobs_router.move_day(J2, "d1", MoveDay(to_job_id=J_X), owner_ids=OWNER)
    check("a day can't be moved into someone else's job", False)
except HTTPException as e:
    check("a day can't be moved into someone else's job", e.status_code == 404)


print("\nDay labels on the job, day notes on a hire")
from models.job import DayLabelsUpdate  # noqa: E402
from services.deal_memo_data import job_memo_dates  # noqa: E402
db = make_db(); use(db)
db["jobs"][0]["crew_dates"] = {"shoot": [["2026-10-20", "2026-10-21"]]}
jobs_router.update_day_labels(J1, DayLabelsUpdate(day_labels={"2026-10-20": "Brand A – Studio", "2026-10-21": " "}),
                              owner_ids=OWNER)
check("labels save trimmed, blanks dropped", db["jobs"][0]["day_labels"] == {"2026-10-20": "Brand A – Studio"})
jobs_router.update_hire(J1, H_DANA, HireUpdate(day_notes={"2026-10-21": "half day"}), owner_ids=OWNER, write_owner_id="o1")
dana = [h for h in db["job_hires"] if h["id"] == H_DANA][0]
check("a day note saves on the hire", dana["day_notes"] == {"2026-10-21": "half day"})
check("and never reaches a day row or the Roster", not any("day_notes" in c for c in db["crew_members"])
      and "day_notes" not in db["roster"][0])
memo = job_memo_dates(db["jobs"][0], dana)
check("the memo prints both", memo.splitlines() == ["Oct 20th - Tue - Shoot day - Brand A – Studio",
                                                     "Oct 21st - Wed - Shoot day - half day"], memo)
listed = [h for h in jobs_router.list_hires(J1, owner_ids=OWNER) if h["id"] == H_DANA][0]
check("the table gets the same lines and a per-date list",
      listed["dates_text"] == memo and [d["date"] for d in listed["person_days"]] == ["2026-10-20", "2026-10-21"])
try:
    jobs_router.update_day_labels(J_X, DayLabelsUpdate(day_labels={}), owner_ids=OWNER)
    check("someone else's job can't be labelled", False)
except HTTPException as e:
    check("someone else's job can't be labelled", e.status_code == 404)

print()
print("ALL PASS" if not FAILS else f"{len(FAILS)} FAILURES: " + ", ".join(FAILS))
sys.exit(1 if FAILS else 0)
