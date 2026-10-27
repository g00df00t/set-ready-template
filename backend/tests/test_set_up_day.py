"""Setting up a day from the Shoot days placeholders.

    cd backend && venv/bin/python tests/test_set_up_day.py

POST /jobs/{id}/days with copy_from / blank / include: copy chosen parts of
another day in the job, or start blank — and either way crew the new day with
the people whose dates include it, keeping the source day's call times. Also
that Duplicate, which shares copy_day and is live for everyone, copies exactly
what it always has.

Calls the route functions directly against tests/fake_supabase.py.
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import HTTPException  # noqa: E402

from tests.fake_supabase import FakeClient  # noqa: E402
from routers import jobs as jobs_router, projects as projects_router  # noqa: E402
from services import job_hires  # noqa: E402
from models.job import AddDay, CrewDatesUpdate, HireCreate, HireUpdate  # noqa: E402

FAILS = []


# The job below runs 2026-10-12 → 16, written as fixed dates because the
# day labels and the deal-memo lines are checked against them. Hiring and
# date changes only touch UPCOMING days (job_hires / routers.jobs compare
# shoot_date to date.today()), so once the real calendar passed Oct 12 every
# "they land on Day 1" check failed. Freeze "today" just before the job.
class _Today(date):
    @classmethod
    def today(cls):
        return cls(2026, 10, 10)


jobs_router.date = _Today
job_hires.date = _Today


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else '  -- ' + str(detail)}")
    if not ok:
        FAILS.append(name)


OWNER = {"o1"}
J1 = "00000000-0000-0000-0000-0000000000b1"
J2 = "00000000-0000-0000-0000-0000000000b2"
D1 = "00000000-0000-0000-0000-0000000000d1"
D_OTHER = "00000000-0000-0000-0000-0000000000d9"
H_DANA, H_JO, H_SAM = "h-dana", "h-jo", "h-sam"


def make_db():
    return {
        "jobs": [
            {"id": J1, "owner_id": "o1", "name": "Northwind",
             "crew_dates": {"prep": [["2026-10-12", "2026-10-12"]], "shoot": [["2026-10-13", "2026-10-16"]]}},
            {"id": J2, "owner_id": "o1", "name": "Other job", "crew_dates": {}},
        ],
        "projects": [
            {"id": D1, "owner_id": "o1", "job_id": J1, "name": "Northwind", "shoot_date": "2026-10-13",
             "general_call_time": "06:30:00", "notes": "Day 1 only: drone permit"},
            {"id": D_OTHER, "owner_id": "o1", "job_id": J2, "name": "Other job", "shoot_date": "2026-10-13"},
        ],
        "job_hires": [
            # Follows the crew's dates: working every shoot day.
            {"id": H_DANA, "job_id": J1, "name": "Dana Whitfield", "email": "dana@example.com",
             "role": "Gaffer", "roster_id": "r-dana", "dates_override": {}, "created_at": "1"},
            # Only on Oct 13.
            {"id": H_JO, "job_id": J1, "name": "Jo Park", "email": "jo@example.com", "role": "Grip",
             "dates_override": {"shoot": [["2026-10-13", "2026-10-13"]]}, "created_at": "2"},
            # Hired, follows the crew, but not on Day 1's crew list.
            {"id": H_SAM, "job_id": J1, "name": "Sam Ortiz", "email": "sam@example.com", "role": "Photographer",
             "department": "Camera Department", "dates_override": {}, "created_at": "3"},
        ],
        "crew_members": [
            {"id": "c-dana", "project_id": D1, "hire_id": H_DANA, "roster_id": "r-dana", "name": "Dana Whitfield",
             "email": "dana@example.com", "role": "Gaffer", "call_time": "06:00:00", "sort_order": 0,
             "confirmed_at": "2026-10-10T10:00:00", "wants_pdf": True},
            {"id": "c-jo", "project_id": D1, "hire_id": H_JO, "name": "Jo Park", "email": "jo@example.com",
             "role": "Grip", "call_time": "07:00:00", "sort_order": 1},
        ],
        "project_locations": [{"id": "l1", "project_id": D1, "location_name": "Pier 57 Studio", "address": "25 11th Ave"}],
        "project_meals": [{"id": "m1", "project_id": D1, "lunch_start": "12:30:00", "lunch_notes": "Catered"}],
        "schedule_items": [{"id": "s1", "project_id": D1, "start_time": "07:00", "description": "Hero shot", "sort_order": 0}],
        "talent": [{"id": "t1", "project_id": D1, "name": "Ava Lee", "sort_order": 0}],
        "project_contacts": [], "company_moves": [], "project_accommodations": [],
        "call_sheets": [], "call_sheet_attachments": [], "team_members": [], "roster": [],
    }


def client_for(db):
    return jobs_router.get_client()


def use(db):
    client = FakeClient(db)
    for mod in (jobs_router, projects_router):
        mod.get_client = lambda: client
    return client


def set_up(**kw):
    return jobs_router.add_day(J1, AddDay(**kw), owner_ids=OWNER, write_owner_id="o1")


def crew_on(db, pid):
    return sorted((c for c in db["crew_members"] if c["project_id"] == pid), key=lambda c: c.get("sort_order", 0))


def rows(db, table, pid):
    return [r for r in db[table] if r["project_id"] == pid]


print("\nCopy from Day 1, the default parts")
db = make_db(); use(db)
day = set_up(copy_from=D1, shoot_date="2026-10-14")
crew = crew_on(db, day["id"])
names = [c["name"] for c in crew]
check("it's in the job, on the date asked", day["job_id"] == J1 and day["shoot_date"] == "2026-10-14", day)
check("crew is the people working Oct 14 — Dana and Sam, not Jo (Oct 13 only)",
      names == ["Dana Whitfield", "Sam Ortiz"], names)
dana = crew[0]
check("Dana keeps Day 1's call time and settings", dana["call_time"] == "06:00:00" and dana["wants_pdf"] is True, dana)
check("...and her links to the hire and the Roster", dana["hire_id"] == H_DANA and dana["roster_id"] == "r-dana", dana)
check("...but not Day 1's confirmation", not dana.get("confirmed_at"), dana)
sam = crew[1]
check("Sam, hired but not on Day 1, arrives with no call time", sam["call_time"] is None and sam["hire_id"] == H_SAM, sam)
check("...after the people who were on Day 1", sam["sort_order"] > dana["sort_order"], crew)
check("...with his details from the hire", sam["department"] == "Camera Department" and sam["email"] == "sam@example.com", sam)
check("every new row carries hide_contact/wants_pdf (both NOT NULL)",
      all(c.get("hide_contact") is not None and c.get("wants_pdf") is not None for c in crew), crew)
check("the day's general call time comes with the crew", day.get("general_call_time") == "06:30:00", day)
check("location copied", [r["location_name"] for r in rows(db, "project_locations", day["id"])] == ["Pier 57 Studio"])
check("meals copied", [r["lunch_notes"] for r in rows(db, "project_meals", day["id"])] == ["Catered"])
check("talent copied", [r["name"] for r in rows(db, "talent", day["id"])] == ["Ava Lee"])
check("schedule is opt-in, so not copied", rows(db, "schedule_items", day["id"]) == [])
check("notes are opt-in, so not copied", not day.get("notes"), day.get("notes"))
check("named after the job", day["name"] == "Northwind")

print("\nCopy only some parts")
db = make_db(); use(db)
day = set_up(copy_from=D1, shoot_date="2026-10-14", include=["location", "schedule", "notes"])
check("location, schedule and notes come", rows(db, "project_locations", day["id"]) and
      rows(db, "schedule_items", day["id"]) and day.get("notes") == "Day 1 only: drone permit")
check("crew doesn't", crew_on(db, day["id"]) == [])
check("nor the general call time", not day.get("general_call_time"))
check("nor talent or meals", rows(db, "talent", day["id"]) == [] and rows(db, "project_meals", day["id"]) == [])

print("\nStart blank")
db = make_db(); use(db)
day = set_up(blank=True, shoot_date="2026-10-15", include=["crew"])
check("crew is still the people working that day", [c["name"] for c in crew_on(db, day["id"])] == ["Dana Whitfield", "Sam Ortiz"])
check("with no call times — there's no day to take them from",
      all(c["call_time"] is None for c in crew_on(db, day["id"])))
check("and nothing else", rows(db, "project_locations", day["id"]) == [] and rows(db, "talent", day["id"]) == [])
day = set_up(blank=True, shoot_date="2026-10-16", include=[])
check("blank with crew unticked is truly empty", crew_on(db, day["id"]) == [])

print("\nA date the crew's dates don't reach")
db = make_db(); use(db)
day = set_up(copy_from=D1, shoot_date="2026-10-20")
check("the dates can't say who's working, so Day 1's crew is copied as it is",
      [c["name"] for c in crew_on(db, day["id"])] == ["Dana Whitfield", "Jo Park"], crew_on(db, day["id"]))
day = set_up(blank=True, shoot_date="2026-10-20", include=["crew"])
check("...and a blank day there starts with nobody", crew_on(db, day["id"]) == [])
day = set_up(copy_from=D1)
check("an undated copy also copies Day 1's crew", len(crew_on(db, day["id"])) == 2)

print("\nGuards")
db = make_db(); use(db)
try:
    set_up(copy_from=D_OTHER, shoot_date="2026-10-14")
    check("copying a day from another job is refused", False)
except HTTPException as e:
    check("copying a day from another job is refused", e.status_code == 404, e.detail)
try:
    AddDay(include=["crew", "payroll"])
    check("an unknown part is rejected", False)
except Exception:
    check("an unknown part is rejected", True)

print("\nThe original Add a day and Duplicate are unchanged")
db = make_db(); use(db)
day = set_up(shoot_date="2026-10-14")
check("Add a day with no set-up fields still duplicates the latest day's whole crew",
      [c["name"] for c in crew_on(db, day["id"])] == ["Dana Whitfield", "Jo Park"])
dup = projects_router.duplicate_project(D1, owner_ids=OWNER, write_owner_id="o1")
check("Duplicate still copies schedule and notes", rows(db, "schedule_items", dup["id"]) and dup.get("notes"))
check("Duplicate still leaves meals and the general call time alone",
      rows(db, "project_meals", dup["id"]) == [] and not dup.get("general_call_time"))

print("\nHiring someone puts them on the days that already exist (add-only)")
db = make_db(); use(db)
PAST = "00000000-0000-0000-0000-0000000000d7"
db["projects"].append({"id": PAST, "owner_id": "o1", "job_id": J1, "name": "Northwind", "shoot_date": "2026-01-05"})
db["jobs"][0]["crew_dates"]["shoot"] = [["2026-01-05", "2026-01-05"], ["2026-10-13", "2026-10-16"]]
view = jobs_router.add_hire(J1, HireCreate(name="Riley New", email="riley@example.com", role="Grip",
                                           save_to_roster=False), owner_ids=OWNER, write_owner_id="o1")
riley = [c for c in db["crew_members"] if c["name"] == "Riley New"]
check("they land on Day 1, which already existed", [c["project_id"] for c in riley] == [D1], riley)
check("...linked to the hire, with no call time yet", riley and riley[0]["hire_id"] == view["id"] and riley[0]["call_time"] is None)
check("...and the response says so, for the toast", view["added_to_days"] == 1, view.get("added_to_days"))
check("a day that's already happened is never touched", not any(c["project_id"] == PAST for c in riley))
jobs_router._crew_days_up_to_date(client_for(db), db["jobs"][0])
check("running it again adds nobody twice", len([c for c in db["crew_members"] if c["name"] == "Riley New"]) == 1)
before = len(crew_on(db, D1))
jobs_router.add_hire(J1, HireCreate(name="Pat Solo", email="pat@example.com", save_to_roster=False,
                                    dates_override={"shoot": [["2026-10-15", "2026-10-15"]], "travel": [],
                                                    "prep": []}), owner_ids=OWNER, write_owner_id="o1")
check("someone whose own dates skip Day 1 isn't put on it", len(crew_on(db, D1)) == before)

print("\nDates changing onto an existing day bring people with them")
D14 = "00000000-0000-0000-0000-0000000000d4"
db["projects"].append({"id": D14, "owner_id": "o1", "job_id": J1, "name": "Northwind", "shoot_date": "2026-10-20"})
jobs_router.update_crew_dates(J1, CrewDatesUpdate(crew_dates={"shoot": [["2026-10-13", "2026-10-20"]]}), owner_ids=OWNER)
on14 = {c["name"] for c in crew_on(db, D14)}
check("the crew's dates growing to reach a day puts the people following them on it",
      {"Dana Whitfield", "Sam Ortiz", "Riley New"} <= on14, on14)
check("...but not people whose own dates don't reach it", "Jo Park" not in on14 and "Pat Solo" not in on14, on14)
pat = next(h for h in db["job_hires"] if h["name"] == "Pat Solo")
jobs_router.update_hire(J1, pat["id"], HireUpdate(dates_override={"shoot": [["2026-10-15", "2026-10-20"]]}),
                        owner_ids=OWNER, write_owner_id="o1")
check("someone's own dates growing to reach a day puts them on it", "Pat Solo" in {c["name"] for c in crew_on(db, D14)})

print("\nDates moving off a day: untouched rows follow, anything else stays and is flagged")
riley_hire = next(h for h in db["job_hires"] if h["name"] == "Riley New")
next(c for c in crew_on(db, D14) if c["name"] == "Pat Solo")["call_time"] = "07:00:00"   # Pat has a call time there
jobs_router.update_hire(J1, pat["id"], HireUpdate(dates_override={"shoot": [["2026-10-15", "2026-10-15"]]}),
                        owner_ids=OWNER, write_owner_id="o1")
jobs_router.update_hire(J1, riley_hire["id"], HireUpdate(dates_override={"shoot": [["2026-10-13", "2026-10-15"]]}),
                        owner_ids=OWNER, write_owner_id="o1")
on14 = {c["name"] for c in crew_on(db, D14)}
check("someone with a call time on that day stays on it", "Pat Solo" in on14, on14)
check("someone nothing's been done with comes off it", "Riley New" not in on14, on14)
cards = {d["id"]: d for d in jobs_router.get_job(J1, owner_ids=OWNER)["days"]}
check("...and the day's card counts who's left there off their dates", cards[D14]["off_dates_crew"] == 1, cards[D14])
check("...by name", cards[D14].get("off_dates_names") == ["Pat Solo"], cards[D14])
check("a day whose crew all match their dates counts none", cards[D1]["off_dates_crew"] == 0, cards[D1])

print("\n\"Day N of M\" on the call sheet — the Shoot days tab's numbering")
from services.job_dates import day_label  # noqa: E402
CD = {"prep": [["2026-10-12", "2026-10-12"]], "shoot": [["2026-10-13", "2026-10-16"]]}
DAYS = [{"id": "a", "shoot_date": "2026-10-13"}, {"id": "old", "shoot_date": "2026-08-24"},
        {"id": "scout", "shoot_date": "2026-10-12"}, {"id": "c", "shoot_date": "2026-10-15"},
        {"id": "u", "shoot_date": None}]
check("shoot dates not set up yet still count: Oct 15 is Day 3 of 4", day_label(CD, DAYS, "c") == "Day 3 of 4")
check("the first shoot date is Day 1", day_label(CD, DAYS, "a") == "Day 1 of 4")
check("a scout on a prep date has no number", day_label(CD, DAYS, "scout") is None)
check("a day off every crew date has no number", day_label(CD, DAYS, "old") is None)
check("an undated day has no number", day_label(CD, DAYS, "u") is None)
check("a one-day job says nothing", day_label({"shoot": [["2026-10-13", "2026-10-13"]]},
                                              [{"id": "x", "shoot_date": "2026-10-13"}], "x") is None)
check("no shoot dates: days number in order", day_label({}, [{"id": "x", "shoot_date": "2026-08-24"},
                                                            {"id": "y", "shoot_date": None}], "y") == "Day 2 of 2")

print()
print(f"{len(FAILS)} FAILED: {', '.join(FAILS)}" if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
