"""Rates on the hire, per diem on the job (services/job_rates.py).

    cd backend && venv/bin/python tests/test_job_rates.py

The producer's answers of 2026-10-01 decide the rules checked here: rates change by
client, so a new hire is filled in from that person's last job for the same
client, else the Master Roster; the hire then keeps its own copy, which
nothing rewrites; per diem is $50 shoot days / $70 every other day, as an
account default each job copies. Rates print on the deal memo and never reach
a day's crew rows or the Roster.

Calls the route functions directly against tests/fake_supabase.py.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.fake_supabase import FakeClient  # noqa: E402
from routers import account as account_router, jobs as jobs_router  # noqa: E402
from models.job import HireCreate, HireUpdate, JobCreate, JobDefaults, JobUpdate  # noqa: E402
from services.deal_memo_builder import build_deal_memo  # noqa: E402
from services.job_rates import (  # noqa: E402
    clean_defaults, memo_rate_lines, money, per_diem_text, roster_rates, suggest_rates,
)

FAILS = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else '  -- ' + str(detail)}")
    if not ok:
        FAILS.append(name)


OWNER = {"o1"}
R_SAM = "00000000-0000-0000-0000-0000000000d1"
R_MARCUS = "00000000-0000-0000-0000-0000000000d2"
J_NOW = "00000000-0000-0000-0000-0000000000b1"
J_SPRING = "00000000-0000-0000-0000-0000000000b2"
J_OLDER = "00000000-0000-0000-0000-0000000000b3"
J_OTHER_CLIENT = "00000000-0000-0000-0000-0000000000b4"
J_SOMEONE_ELSE = "00000000-0000-0000-0000-0000000000b9"


def make_db():
    return {
        "jobs": [
            {"id": J_NOW, "owner_id": "o1", "name": "Fall Lookbook", "client_name": "Riverbend Outdoor",
             "crew_dates": {}, "created_at": "2026-10-01"},
            {"id": J_SPRING, "owner_id": "o1", "name": "Spring Catalog", "client_name": " riverbend outdoor ",
             "crew_dates": {}, "created_at": "2026-04-01"},
            {"id": J_OLDER, "owner_id": "o1", "name": "Old Riverbend", "client_name": "Riverbend Outdoor",
             "crew_dates": {}, "created_at": "2025-04-01"},
            {"id": J_OTHER_CLIENT, "owner_id": "o1", "name": "Northwind", "client_name": "Northwind",
             "crew_dates": {}, "created_at": "2026-09-01"},
            # Another producer's job with this roster_id — must never be read.
            {"id": J_SOMEONE_ELSE, "owner_id": "o2", "name": "Theirs", "client_name": "Riverbend Outdoor",
             "crew_dates": {}, "created_at": "2026-09-30"},
        ],
        "projects": [],
        "job_hires": [
            {"id": "h-spring", "job_id": J_SPRING, "roster_id": R_SAM, "name": "Sam Ortiz",
             "rate_shoot": 800, "rate_travel": 400, "rate_prep": 400, "rate_note": "10-hour day",
             "dates_override": {}, "created_at": "2026-04-01"},
            {"id": "h-older", "job_id": J_OLDER, "roster_id": R_SAM, "name": "Sam Ortiz",
             "rate_shoot": 700, "dates_override": {}, "created_at": "2025-04-01"},
            {"id": "h-other-client", "job_id": J_OTHER_CLIENT, "roster_id": R_SAM, "name": "Sam Ortiz",
             "rate_shoot": 1200, "dates_override": {}, "created_at": "2026-09-01"},
            {"id": "h-theirs", "job_id": J_SOMEONE_ELSE, "roster_id": R_SAM, "name": "Sam Ortiz",
             "rate_shoot": 9999, "dates_override": {}, "created_at": "2026-09-30"},
        ],
        "crew_members": [],
        "roster": [
            {"id": R_SAM, "owner_id": "o1", "type": "crew", "name": "Sam Ortiz",
             "email": "sam@example.com", "day_rate": "$750/day"},
            {"id": R_MARCUS, "owner_id": "o1", "type": "crew", "name": "Marcus Chen",
             "email": "marcus@example.com",
             "day_rate": "Shoot day rate = $1,200, Travel day rate = $600"},
        ],
        "team_members": [],
    }


def use(db):
    client = FakeClient(db)
    for mod in (jobs_router, account_router):
        mod.get_client = lambda: client
    return client


def hire_on(db, job, name):
    return next(h for h in db["job_hires"] if h["job_id"] == job and h["name"] == name)


print("\nReading the Roster's free-text rate")
check("a plain day rate is the shoot rate, and prep defaults to it",
      roster_rates({"day_rate": "$650/day"}) == {"rate_shoot": 650, "rate_prep": 650})
check("The producer's own wording splits into shoot and travel",
      roster_rates({"day_rate": "Shoot day rate = $1,200, Travel day rate = $600"})
      == {"rate_shoot": 1200, "rate_prep": 1200, "rate_travel": 600})
check("a named prep rate is kept", roster_rates({"day_rate": "$800 shoot, $400 prep"})["rate_prep"] == 400)
check("nothing readable → nothing", roster_rates({"day_rate": "TBD"}) == {} and roster_rates(None) == {})

print("\nThe memo's lines")
check("money keeps commas and drops .00", money(1200) == "$1,200" and money("62.5") == "$62.50")
check("only the rates that are set print, then the note",
      memo_rate_lines({"rate_shoot": 800, "rate_prep": 400, "rate_note": "10-hour day"})
      == "Shoot day rate = $800\nPrep/Scout day rate = $400\n10-hour day")
check("per diem prints in the producer's wording",
      per_diem_text({"per_diem_shoot": 50, "per_diem_other": 70, "per_diem_paid_by": "Venmo or cash"})
      == "$70/non shoot day and $50/shoot day - paid via Venmo or cash")
check("a job with no amounts keeps its free-text line",
      per_diem_text({"per_diem_line": "$70/day for travel"}) == "$70/day for travel")

print("\nSuggesting a deal")
job = {"id": J_NOW, "client_name": "Riverbend Outdoor"}
past = [({"rate_shoot": 700, "created_at": "a"}, {"id": "x", "client_name": "Riverbend Outdoor", "created_at": "2025"}),
        ({"rate_shoot": 800, "created_at": "b"}, {"id": "y", "client_name": "riverbend outdoor", "created_at": "2026"}),
        ({"rate_shoot": 1200, "created_at": "c"}, {"id": "z", "client_name": "Northwind", "created_at": "2027"})]
s = suggest_rates(job, {"day_rate": "$500"}, past)
check("the most recent same-client job wins, whatever the case and spacing",
      s["rate_shoot"] == 800 and s["rate_source"] == "job" and s["rate_source_job_id"] == "y", s)
s = suggest_rates({"id": J_NOW, "client_name": "Nike"}, {"day_rate": "$500"}, past)
check("no job for this client → the Roster", s["rate_shoot"] == 500 and s["rate_source"] == "roster", s)
check("a job with no client never matches on blank",
      suggest_rates({"id": J_NOW, "client_name": None}, None,
                    [({"rate_shoot": 1}, {"id": "q", "client_name": None})]) is None)

print("\nHiring fills the deal in")
db = make_db(); use(db)
jobs_router.add_hire(J_NOW, HireCreate(name="Sam Ortiz", roster_id=R_SAM, email="sam@example.com"),
                     owner_ids=OWNER, write_owner_id="o1")
sam = hire_on(db, J_NOW, "Sam Ortiz")
check("from their last Riverbend job — not the newer Northwind one, not someone else's",
      sam.get("rate_shoot") == 800 and sam.get("rate_travel") == 400 and sam.get("rate_prep") == 400, sam)
check("the note comes along", sam.get("rate_note") == "10-hour day")
check("and it says where from", sam.get("rate_source") == "job" and sam.get("rate_source_job_id") == J_SPRING)

jobs_router.add_hire(J_NOW, HireCreate(name="Marcus Chen", roster_id=R_MARCUS, email="marcus@example.com"),
                     owner_ids=OWNER, write_owner_id="o1")
marcus = hire_on(db, J_NOW, "Marcus Chen")
check("first job for this client → the Roster's rates, read as numbers",
      marcus.get("rate_shoot") == 1200 and marcus.get("rate_travel") == 600 and marcus.get("rate_source") == "roster",
      marcus)

jobs_router.add_hire(J_NOW, HireCreate(name="New Person", email="new@example.com", save_to_roster=False),
                     owner_ids=OWNER, write_owner_id="o1")
check("someone with no Roster record is hired with no rate", not hire_on(db, J_NOW, "New Person").get("rate_shoot"))

print("\nThe hire keeps its own copy")
db["roster"][0]["day_rate"] = "$2000/day"
hire_on(db, J_SPRING, "Sam Ortiz")["rate_shoot"] = 5000
check("later Roster or other-job edits don't touch it", hire_on(db, J_NOW, "Sam Ortiz")["rate_shoot"] == 800)

result = jobs_router.update_hire(J_NOW, sam["id"], HireUpdate(rate_shoot=850, rate_prep=425),
                                 owner_ids=OWNER, write_owner_id="o1")
check("editing a rate saves it on the hire", hire_on(db, J_NOW, "Sam Ortiz")["rate_shoot"] == 850)
check("and reaches neither the Roster nor any day",
      db["roster"][0]["day_rate"] == "$2000/day" and result["roster_synced"] is False and result["days_synced"] == 0)
try:
    jobs_router.update_hire(J_NOW, sam["id"], HireUpdate(rate_source="job", rate_source_job_id=J_SOMEONE_ELSE),
                            owner_ids=OWNER, write_owner_id="o1")
    check("a source job must be one of yours", False)
except Exception as e:
    check("a source job must be one of yours", getattr(e, "status_code", None) == 404, e)

print("\nThe list offers a deal to anyone without one")
db = make_db(); use(db)
db["job_hires"].append({"id": "h-new", "job_id": J_NOW, "roster_id": R_SAM, "name": "Sam Ortiz",
                        "dates_override": {}, "sort_order": 0})
view = next(v for v in jobs_router.list_hires(J_NOW, owner_ids=OWNER) if v["id"] == "h-new")
check("a hire with no rates gets a suggestion", (view.get("rate_suggestion") or {}).get("rate_shoot") == 800, view)
check("it names the job it came from", view["rate_suggestion"].get("rate_source_job_name") == "Spring Catalog")

print("\nThe deal memo prints the hire's deal")
memo = build_deal_memo({"name": "Fall Lookbook", "per_diem_shoot": 50, "per_diem_other": 70,
                        "per_diem_paid_by": "Venmo or cash"},
                       {"name": "Sam", "rate_shoot": 800, "rate_travel": 400, "rate_note": None},
                       {"day_rate": "$650/day", "rate_note": "ROSTER-NOTE-XYZ"}, None, dates="")
check("the hire's lines replace the Roster's rate entirely",
      "Shoot day rate = $800<br>Travel day rate = $400" in memo and "$650/day" not in memo and "ROSTER-NOTE-XYZ" not in memo)
check("the per diem line prints", "$70/non shoot day and $50/shoot day - paid via Venmo or cash" in memo)
memo = build_deal_memo({"name": "x"}, {"name": "Sam"}, {"day_rate": "$650/day"}, None, dates="")
check("a hire with no rates still falls back to the Roster", "$650/day" in memo)

print("\nPer diem on the job, defaults on the account")
db = make_db(); client = use(db)
check("an account that never set any gets the producer's $50 / $70",
      account_router.get_job_defaults(write_owner_id="o1")["per_diem_other"] == 70)
client.users["o1"] = {"beta_jobs": True, "terms_version": "v3"}
account_router.set_job_defaults(JobDefaults(per_diem_shoot=55, per_diem_other=75, per_diem_paid_by="Zelle"),
                                write_owner_id="o1")
check("saving defaults keeps the rest of the metadata",
      client.users["o1"].get("beta_jobs") is True and client.users["o1"].get("terms_version") == "v3")
new = jobs_router.create_job(JobCreate(name="New job"), write_owner_id="o1")["job"]
check("a new job copies them", new.get("per_diem_shoot") == 55 and new.get("per_diem_other") == 75
      and new.get("per_diem_paid_by") == "Zelle", new)
jobs_router.update_job(new["id"], JobUpdate(per_diem_other=80), owner_ids=OWNER)
check("and a job can change its own",
      next(j for j in db["jobs"] if j["id"] == new["id"])["per_diem_other"] == 80)
check("garbage in the browser-writable metadata never reaches a job",
      clean_defaults({"per_diem_shoot": "lots", "per_diem_other": -5, "per_diem_paid_by": 7})
      == {"per_diem_shoot": None, "per_diem_other": None, "per_diem_paid_by": None})

print()
print(f"{len(FAILS)} FAILED: {', '.join(FAILS)}" if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
