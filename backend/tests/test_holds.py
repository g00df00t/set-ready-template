"""Holds and the role checklist (services/holds.py, routers/holds.py).

    cd backend && venv/bin/python tests/test_holds.py

The producer, 2026-10-01: a placeholder row for every role, needed or not; 1 = first
hold, 2 = second. Patrick, 2026-10-02: until someone's confirmed they stay off
a day's crew, the rooming list, per diem and "Download all"; the Holds view
stacks every upcoming job and flags the same person on two jobs on one date.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import HTTPException  # noqa: E402

from services import holds, per_diem, rooming  # noqa: E402
from services.job_dates import DatesError  # noqa: E402
from tests.fake_supabase import FakeClient  # noqa: E402
from routers import deal_memo as memo_router, holds as holds_router, jobs as jobs_router  # noqa: E402
from models.job import HireCreate, HireUpdate  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else '  -- ' + str(detail)}")
    if not ok:
        FAILS.append(name)


CREW = {"shoot": [["2030-10-20", "2030-10-21"]], "travel": [["2030-10-19", "2030-10-19"]]}

print("\nStatus")
check("no status column yet: everyone is confirmed", holds.status_of({}) == "confirmed" and holds.is_booked({}))
check("labels", [holds.status_label(h) for h in ({"status": "hold", "hold_rank": 1}, {"status": "hold", "hold_rank": 2},
                                                  {"status": "confirmed"}, {"status": "released"})]
      == ["1st hold", "2nd hold", "Confirmed", "Released"])
check("a hold defaults to 1st; anything else clears the rank",
      holds.validate_status("hold", None) == ("hold", 1) and holds.validate_status("confirmed", 2) == ("confirmed", None))
for bad in (("maybe", None), ("hold", 3)):
    try:
        holds.validate_status(*bad)
        check(f"refused: {bad}", False)
    except DatesError:
        check(f"refused: {bad}", True)

print("\nRole slots")
slots = holds.validate_slots([{"role": "  HMU "}, {"role": "Stylist", "state": "not_needed"},
                              {"role": "Photographer", "hire_id": "someone-elses"}], {"h1"})
check("roles trim, default to open, get ids", slots[0]["role"] == "HMU" and slots[0]["state"] == "open" and slots[0]["id"])
check("a hire_id not on this job is dropped, never trusted", slots[2]["hire_id"] is None)
try:
    holds.validate_slots([{"role": " "}], set())
    check("a role needs a name", False)
except DatesError:
    check("a role needs a name", True)

print("\nThe Holds view")
JOB_A = {"id": "a", "name": "Northwind", "crew_dates": CREW,
         "role_slots": [{"id": "s1", "role": "HMU", "state": "open"}, {"id": "s2", "role": "Stylist", "state": "not_needed"},
                        {"id": "s3", "role": "Photographer", "state": "open", "hire_id": "h1"}]}
JOB_B = {"id": "b", "name": "Nike", "crew_dates": {"shoot": [["2030-10-21", "2030-10-21"]]}}
OLD = {"id": "c", "name": "Last year", "crew_dates": {"shoot": [["2020-01-01", "2020-01-01"]]}}
HIRES = [{"id": "h1", "job_id": "a", "name": "Sam", "roster_id": "r1", "status": "confirmed", "dates_override": {}},
         {"id": "h2", "job_id": "a", "name": "Dana", "roster_id": "r2", "status": "hold", "hold_rank": 2, "dates_override": {}},
         {"id": "h3", "job_id": "a", "name": "Gone", "status": "released", "dates_override": {}},
         {"id": "h4", "job_id": "b", "name": "Sam", "roster_id": "r1", "status": "hold", "hold_rank": 1, "dates_override": {}},
         {"id": "h5", "job_id": "c", "name": "Old", "dates_override": {}}]
view = holds.build_holds([JOB_A, JOB_B, OLD], HIRES, today="2030-10-01")
names = [b["job"]["name"] for b in view["jobs"]]
check("upcoming jobs only, in date order", names == ["Northwind", "Nike"], names)
a = view["jobs"][0]
rows = {(r["kind"], r["role"], r["name"]): r for r in a["rows"]}
check("a confirmed person is ✓ on every day they work, travel included",
      rows[("hire", "Photographer", "Sam")]["cells"] == {"2030-10-19": "✓", "2030-10-20": "✓", "2030-10-21": "✓"},
      rows[("hire", "Photographer", "Sam")]["cells"])
check("a 2nd hold is 2", rows[("hire", "", "Dana")]["cells"]["2030-10-20"] == "2")
check("a filled slot shows its role on the person", ("hire", "Photographer", "Sam") in rows)
check("an open role is its own row, not cast", rows[("slot", "HMU", None)]["label"] == "Not cast")
check("not-needed roles and released people are left off",
      not any(r["role"] == "Stylist" for r in a["rows"]) and not any(r["name"] == "Gone" for r in a["rows"]))
check("counts for the job's heading", a["open_roles"] == 1 and a["holds"] == 1)
recast = holds.build_holds([{**JOB_A, "role_slots": [{"id": "s9", "role": "HMU", "state": "open", "hire_id": "h3"}]}],
                           HIRES[:3], today="2030-10-01")["jobs"][0]
check("a role whose person was released is open again, not lost",
      recast["open_roles"] == 1 and any(r["kind"] == "slot" and r["role"] == "HMU" for r in recast["rows"]), recast["rows"])
check("the same person on two jobs on one date is flagged, once per pair of jobs",
      [(c["name"], c["dates"], sorted(j["job"] for j in c["jobs"])) for c in view["conflicts"]]
      == [("Sam", ["2030-10-21"], ["Nike", "Northwind"])], view["conflicts"])
long = holds.build_holds([{**JOB_A, "role_slots": []}, {**JOB_B, "crew_dates": CREW}], HIRES[:1] + HIRES[3:4], today="2030-10-01")
check("several clashing dates are one entry with all its dates",
      len(long["conflicts"]) == 1 and long["conflicts"][0]["dates"] == ["2030-10-19", "2030-10-20", "2030-10-21"],
      long["conflicts"])
check("her usual roles are offered", "HMU" in view["default_roles"] and len(view["default_roles"]) == 10)

print("\nHolds stay off what's booked")
JOB = {"id": "a", "name": "Northwind", "crew_dates": CREW, "per_diem_shoot": 50, "per_diem_other": 70}
pd = per_diem.build_sheet(JOB, HIRES[:3])
check("per diem: confirmed only", [r["name"] for r in pd["rows"]] == ["Sam"])
rm = rooming.build_sheets(JOB, HIRES[:3])
check("rooming list: confirmed only", [r["name"] for r in rm["sheets"][0]["rows"]] == ["Sam"])

print("\nThrough the API")
J = "00000000-0000-0000-0000-0000000000b1"
OTHER = "00000000-0000-0000-0000-0000000000b9"
db = {"jobs": [{"id": J, "owner_id": "o1", "name": "Northwind", "crew_dates": CREW,
                "role_slots": [{"id": "slot-hmu", "role": "HMU", "state": "open", "hire_id": None}]},
               {"id": OTHER, "owner_id": "o2", "name": "Theirs", "crew_dates": {}, "role_slots": []}],
      "projects": [{"id": "d1", "owner_id": "o1", "job_id": J, "name": "Northwind", "shoot_date": "2030-10-20"}],
      "job_hires": [], "crew_members": [], "roster": [], "team_members": []}
client = FakeClient(db)
for mod in (jobs_router, holds_router, memo_router):
    mod.get_client = lambda: client
hired = jobs_router.add_hire(J, HireCreate(name="Dana Hold", email="dana@example.com", role="HMU", status="hold",
                                           hold_rank=2, slot_id="slot-hmu", save_to_roster=False),
                             owner_ids={"o1"}, write_owner_id="o1")
dana = db["job_hires"][0]
check("hiring as a 2nd hold saves the status", dana["status"] == "hold" and dana["hold_rank"] == 2)
check("...fills the slot it was hired into", db["jobs"][0]["role_slots"][0]["hire_id"] == dana["id"])
check("...and puts a hold on no day's crew", hired["added_to_days"] == 0 and db["crew_members"] == [])
jobs_router.update_hire(J, dana["id"], HireUpdate(status="confirmed"), owner_ids={"o1"}, write_owner_id="o1")
check("confirming puts them on their days", [c["project_id"] for c in db["crew_members"]] == ["d1"] and
      db["job_hires"][0]["hold_rank"] is None)
jobs_router.update_hire(J, dana["id"], HireUpdate(status="released"), owner_ids={"o1"}, write_owner_id="o1")
check("releasing takes them off a day nobody's touched", db["crew_members"] == [])
jobs_router.update_hire(J, dana["id"], HireUpdate(status="hold"), owner_ids={"o1"}, write_owner_id="o1")
check("back to a hold: a 1st unless said", db["job_hires"][0]["hold_rank"] == 1)
try:
    memo_router.download_all_job_deal_memos(J, None, owner_ids={"o1"})
    check("Download all leaves holds out (nobody booked → nothing to zip)", False)
except HTTPException as e:
    check("Download all leaves holds out (nobody booked → nothing to zip)", e.status_code == 400, e.detail)
jobs_router.remove_hire(J, dana["id"], owner_ids={"o1"})
check("removing the hire opens their role again", db["jobs"][0]["role_slots"][0]["hire_id"] is None)
saved = holds_router.update_role_slots(J, holds_router.RoleSlotsUpdate(role_slots=[{"role": "Stylist"}, {"role": "HMU", "state": "not_needed"}]),
                                       owner_ids={"o1"})
check("the checklist saves", [(s["role"], s["state"]) for s in saved] == [("Stylist", "open"), ("HMU", "not_needed")])
try:
    holds_router.update_role_slots(OTHER, holds_router.RoleSlotsUpdate(role_slots=[]), owner_ids={"o1"})
    check("someone else's job is refused", False)
except HTTPException as e:
    check("someone else's job is refused", e.status_code == 404)
check("GET /holds sees only the account's jobs", [b["job"]["name"] for b in holds_router.get_holds(owner_ids={"o1"})["jobs"]] == ["Northwind"])

print()
print(f"{len(FAILS)} FAILED: {', '.join(FAILS)}" if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
