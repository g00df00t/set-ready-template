"""The backfill that puts existing data into the job shape.

    cd backend && venv/bin/python tests/test_job_migration.py

docs/job-layer-plan.md §8 steps 2–3: one job per project; one hire per crew
row; hire_id linked; identity and roster_id copied; a dry run writes nothing;
re-running changes nothing (it doubles as the per-account repair); scoped to
one owner when asked; and old free-text deal memo dates that can't be read are
reported rather than dropped.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.fake_supabase import FakeClient  # noqa: E402
from services.job_backfill import backfill, convert_legacy_dates  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else '  -- ' + str(detail)}")
    if not ok:
        FAILS.append(name)


def make_db():
    return {
        "projects": [
            {"id": "p1", "owner_id": "o1", "job_id": None, "name": "Northwind Fall 2026 Day 1",
             "shoot_date": "2026-10-13", "client_name": "Northwind", "production_company": "Example Productions",
             "payroll_provider": "Example Payroll"},
            {"id": "p2", "owner_id": "o1", "job_id": None, "name": "Northwind Fall 2026 Day 2",
             "shoot_date": "2026-10-14"},
            {"id": "p3", "owner_id": "o2", "job_id": None, "name": "Other producer", "shoot_date": None},
        ],
        "crew_members": [
            {"id": "c1", "project_id": "p1", "hire_id": None, "name": "Dana Whitfield", "email": "dana@example.com",
             "phone": "310-555-0100", "role": "Producer", "department": "Production", "roster_id": "r1",
             "sort_order": 0,
             "deal_memo_dates": "Oct 11th - Sun - Travel in\nOct 13th (Tue) – Oct 14th (Wed) - Shoot day"},
            {"id": "c2", "project_id": "p1", "hire_id": None, "name": "Alex Kim", "email": "alex@example.com",
             "role": "Gaffer", "sort_order": 1, "deal_memo_dates": "the week of the 12th, TBC"},
            # Same person twice on one day — one hire, both rows linked.
            {"id": "c3", "project_id": "p1", "hire_id": None, "name": "Alex Kim", "email": "alex@example.com",
             "role": "Gaffer", "sort_order": 2},
            {"id": "c4", "project_id": "p2", "hire_id": None, "name": "Dana Whitfield",
             "email": "dana@example.com", "role": "Producer", "roster_id": "r1", "sort_order": 0},
            {"id": "c5", "project_id": "p3", "hire_id": None, "name": "Someone", "email": "s@example.com",
             "role": "PA", "sort_order": 0},
        ],
        "jobs": [], "job_hires": [],
    }


print("\nDry run")
db = make_db()
r = backfill(FakeClient(db), apply=False)
check("reports a job per project", r["jobs_created"] == 3, r)
check("reports a hire per distinct person per job", r["hires_created"] == 4, r)
check("writes nothing", db["jobs"] == [] and db["job_hires"] == []
      and all(p["job_id"] is None for p in db["projects"])
      and all(c["hire_id"] is None for c in db["crew_members"]))

print("\nApply")
db = make_db()
r = backfill(FakeClient(db), apply=True)
jobs = {j["id"]: j for j in db["jobs"]}
proj = {p["id"]: p for p in db["projects"]}
check("one job per project", len(db["jobs"]) == 3 and len({p["job_id"] for p in db["projects"]}) == 3)
j1 = jobs[proj["p1"]["job_id"]]
check("the job takes the project's owner and name", j1["owner_id"] == "o1" and j1["name"].startswith("Northwind"))
check("...and its client, production company and payroll provider",
      (j1["client_name"], j1["production_company"], j1["payroll_provider"]) == ("Northwind", "Example Productions", "Example Payroll"))
check("two days of one shoot arrive as two one-day jobs — joining them is Move a day",
      proj["p1"]["job_id"] != proj["p2"]["job_id"])

crew = {c["id"]: c for c in db["crew_members"]}
hires = {h["id"]: h for h in db["job_hires"]}
check("every crew row is linked", all(c["hire_id"] for c in crew.values()))
dana = hires[crew["c1"]["hire_id"]]
check("identity, role and department copied",
      (dana["name"], dana["email"], dana["phone"], dana["role"], dana["department"])
      == ("Dana Whitfield", "dana@example.com", "310-555-0100", "Producer", "Production"), dana)
check("roster_id copied", dana["roster_id"] == "r1")
check("the hire is on the row's own job", dana["job_id"] == proj["p1"]["job_id"])
check("the same person twice on a day is one hire", crew["c2"]["hire_id"] == crew["c3"]["hire_id"])
check("Dana on Day 2 is a different hire — Day 2 is its own job until moved",
      crew["c4"]["hire_id"] != crew["c1"]["hire_id"])
check("counts match what happened", r["crew_linked"] == 5 and r["hires_created"] == 4, r)
check("rows with old deal memo dates are counted", r["legacy_dates_rows"] == 2, r)

print("\nRe-running is the repair, and changes nothing that's whole")
before = (len(db["jobs"]), len(db["job_hires"]))
r = backfill(FakeClient(db), apply=True)
check("no new jobs or hires", (len(db["jobs"]), len(db["job_hires"])) == before, r)
check("reports everything as already linked", r["crew_already_linked"] == 5 and r["crew_linked"] == 0, r)
db["crew_members"].append({"id": "c6", "project_id": "p1", "hire_id": None, "name": "Dana Whitfield",
                           "email": "dana@example.com", "role": "Producer", "roster_id": "r1"})
r = backfill(FakeClient(db), apply=True)
check("a row the bookkeeping missed is linked to the EXISTING hire",
      [c for c in db["crew_members"] if c["id"] == "c6"][0]["hire_id"] == crew["c1"]["hire_id"]
      and r["hires_created"] == 0, r)

print("\nScoped to one account")
db = make_db()
backfill(FakeClient(db), owner_ids=["o2"], apply=True)
check("only o2's project gets a job",
      [p["id"] for p in db["projects"] if p["job_id"]] == ["p3"])
check("only o2's crew is hired", [h["name"] for h in db["job_hires"]] == ["Someone"])

print("\nOld deal memo dates: converted when asked, and unreadable lines reported")
db = make_db()
client = FakeClient(db)
backfill(client, apply=True)
c = convert_legacy_dates(client, ["o1"], apply=True)
dana = [h for h in db["job_hires"] if h["name"] == "Dana Whitfield" and h["job_id"] == db["projects"][0]["job_id"]][0]
check("Dana's lines become structured dates",
      dana["dates_override"].get("travel") == [["2026-10-11", "2026-10-11"]]
      and dana["dates_override"].get("shoot") == [["2026-10-13", "2026-10-14"]], dana["dates_override"])
check("Alex's line can't be read and is REPORTED, with whose it was",
      [(u["name"], u["line"]) for u in c["unparsed"]] == [("Alex Kim", "the week of the 12th, TBC")], c)
alex = [h for h in db["job_hires"] if h["name"] == "Alex Kim"][0]
check("...and nothing is guessed for him", alex["dates_override"] == {})
check("the crew row keeps its old text — the current version still reads it",
      db["crew_members"][0]["deal_memo_dates"].startswith("Oct 11th"))

print()
print("ALL PASS" if not FAILS else f"{len(FAILS)} FAILURES: " + ", ".join(FAILS))
sys.exit(1 if FAILS else 0)
