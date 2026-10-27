"""Opting in to Jobs, and switching back.

    cd backend && venv/bin/python tests/test_beta_conversion.py

docs/job-layer-plan.md §11: POST /account/beta repairs the account (the
backfill, scoped to it) and converts its old deal memo dates onto the hires,
once, listing any line it can't read. The flag lives in user_metadata next to
the Terms acceptance, which must survive the write. Switching back changes
the flag and nothing else.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.fake_supabase import FakeClient  # noqa: E402
from routers import account  # noqa: E402
from models.job import BetaToggle  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else '  -- ' + str(detail)}")
    if not ok:
        FAILS.append(name)


def make_db():
    return {
        "projects": [
            {"id": "p1", "owner_id": "o1", "job_id": None, "name": "Fall", "shoot_date": "2026-08-25"},
            {"id": "p_team", "owner_id": "owner", "job_id": None, "name": "Team shoot", "shoot_date": "2026-10-13"},
        ],
        "crew_members": [
            {"id": "c1", "project_id": "p1", "hire_id": None, "name": "Susan Test", "email": "susan@example.com",
             "role": "Stylist", "deal_memo_dates": "Aug 24th - Mon - check in\nAug 25th - Tues - Shoot\nparking TBD"},
            {"id": "c2", "project_id": "p_team", "hire_id": None, "name": "Kit Moss", "email": "kit@example.com",
             "role": "PA", "deal_memo_dates": "Oct 13th - Tue - Shoot day"},
        ],
        "jobs": [], "job_hires": [],
    }


db = make_db()
client = FakeClient(db)
client.users["o1"] = {"terms_version": "2026-06-19", "full_name": "Pat"}
account.get_client = lambda: client

print("\nSwitching on")
res = account.set_beta(BetaToggle(enabled=True), user_id="o1", write_owner_id="o1")
check("the flag is set", client.users["o1"].get("beta_jobs") is True)
check("the Terms acceptance and display name survive the write",
      client.users["o1"].get("terms_version") == "2026-06-19" and client.users["o1"].get("full_name") == "Pat",
      client.users["o1"])
check("the account was repaired first: its day has a job, its crew a hire",
      db["projects"][0]["job_id"] and db["crew_members"][0]["hire_id"])
hire = [h for h in db["job_hires"] if h["name"] == "Susan Test"][0]
check("old lines became structured dates, in the right year",
      # The producer's "check in" with no travel: a check-in since 2026-10-01 (Q2).
      hire["dates_override"].get("checkin") == [["2026-08-24", "2026-08-24"]]
      and hire["dates_override"].get("shoot") == [["2026-08-25", "2026-08-25"]], hire["dates_override"])
check("the unreadable line comes back to the screen, with whose it was",
      [(u["name"], u["line"]) for u in res["report"]["dates"]["unparsed"]] == [("Susan Test", "parking TBD")],
      res["report"])
check("another account's data is untouched",
      db["projects"][1]["job_id"] is None and db["crew_members"][1]["hire_id"] is None)
check("GET says it's on", account.get_beta(user_id="o1") == {"beta_jobs": True})

print("\nSwitching back, then on again")
account.set_beta(BetaToggle(enabled=False), user_id="o1", write_owner_id="o1")
check("the flag is off", client.users["o1"].get("beta_jobs") is False)
check("nothing is converted back or deleted", hire in db["job_hires"] and hire["dates_override"])
# In Jobs they reset Susan to the crew dates; later they switch on again.
hire["dates_override"] = {}
res = account.set_beta(BetaToggle(enabled=True), user_id="o1", write_owner_id="o1")
check("the conversion runs once per person — the reset isn't undone by old lines",
      hire["dates_override"] == {} and res["report"]["dates"] is None, res["report"])

print("\nA team member switching on repairs the SHARED account")
client.users["member"] = {}
account.set_beta(BetaToggle(enabled=True), user_id="member", write_owner_id="owner")
check("the owner's day is in a job now", db["projects"][1]["job_id"])
check("the member's own flag is what's set, not the owner's",
      client.users["member"].get("beta_jobs") is True and "owner" not in client.users)

print("\nA repair that fails doesn't switch anyone")
db2 = make_db()
bad = FakeClient(db2, fail={"jobs"})
bad.users["o1"] = {}
account.get_client = lambda: bad
try:
    account.set_beta(BetaToggle(enabled=True), user_id="o1", write_owner_id="o1")
    check("the opt-in reports the failure", False)
except Exception as e:
    check("the opt-in reports the failure", getattr(e, "status_code", None) == 500, e)
check("...and the flag stays off", not bad.users["o1"].get("beta_jobs"))

print()
print("ALL PASS" if not FAILS else f"{len(FAILS)} FAILURES: " + ", ".join(FAILS))
sys.exit(1 if FAILS else 0)
