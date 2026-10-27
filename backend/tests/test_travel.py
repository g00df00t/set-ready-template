"""Travel legs, the car service's copy and arrival groups (services/travel.py,
services/travel_documents.py, routers/travel.py).

    cd backend && venv/bin/python tests/test_travel.py

The producer's Travel Doc (docs/producer-documents-map.md §1.7): ARRIVALS then DEPARTURES,
shared — filtered — with the car service. Her Q9 answer: the car service gets
phone numbers, some swapped for the producer's. Every person and number here
is invented.
"""

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import HTTPException  # noqa: E402

from services import travel  # noqa: E402
from services.job_dates import DatesError  # noqa: E402
from services.travel_documents import blocks, to_html, to_xlsx  # noqa: E402
from tests.fake_supabase import FakeClient  # noqa: E402
from routers import travel as travel_router  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else '  -- ' + str(detail)}")
    if not ok:
        FAILS.append(name)


def refused(name, fn, *args, **kw):
    try:
        fn(*args, **kw)
        check(name, False, "not refused")
    except DatesError:
        check(name, True)


CREW = {"travel": [["2026-08-24", "2026-08-24"]], "shoot": [["2026-08-25", "2026-08-27"]],
        "travel_out": [["2026-08-28", "2026-08-28"]]}
JOB = {"id": "j", "name": "Northwind Fall", "client_name": "Northwind", "crew_dates": CREW,
       "producer_phone": "555-0199"}


def leg(direction, day, **kw):
    return {"direction": direction, "date": day, **kw}


print("\nShape")
legs = travel.validate_legs([
    leg("out", "2026-08-28", carrier="Delta", flight="DL 412", from_airport="EWR", depart_time="6:10 PM",
        to_airport="PDX", arrive_time="9:05 pm", plan="car_service"),
    leg("in", "2026-08-24", carrier="Delta", flight="DL 401", from_airport="PDX", depart_time="07:00",
        to_airport="EWR", arrive_time="3:20 PM", arrive_date="2026-08-24", plan="ride", ride_with="h2"),
], hire_ids={"h1", "h2"}, own_id="h1")
check("legs come back in travel order", [x["direction"] for x in legs] == ["in", "out"])
check("times are stored 24h", legs[0]["arrive_time"] == "15:20" and legs[1]["depart_time"] == "18:10")
check("an arrive date the same as the date is dropped", legs[0]["arrive_date"] is None)
check("each leg gets an id", all(x["id"] for x in legs))
check("ride_with is kept for a ride", legs[0]["ride_with"] == "h2")
check("ride_with is dropped for any other plan",
      travel.validate_legs([leg("in", "2026-08-24", plan="rental", ride_with="h2")])[0]["ride_with"] is None)
check("an overnight flight keeps its landing date",
      travel.validate_legs([leg("in", "2026-08-23", arrive_date="2026-08-24")])[0]["arrive_date"] == "2026-08-24")
refused("a direction that isn't in/out", travel.validate_legs, [leg("sideways", "2026-08-24")])
refused("a bad date", travel.validate_legs, [leg("in", "Aug 24")])
refused("a bad time", travel.validate_legs, [leg("in", "2026-08-24", arrive_time="soon")])
refused("landing before it leaves", travel.validate_legs, [leg("in", "2026-08-24", arrive_date="2026-08-23")])
refused("an unknown plan", travel.validate_legs, [leg("in", "2026-08-24", plan="helicopter")])
refused("a ride with yourself", travel.validate_legs, [leg("in", "2026-08-24", plan="ride", ride_with="h1")],
        {"h1"}, "h1")
refused("a ride with someone not on the job", travel.validate_legs,
        [leg("in", "2026-08-24", plan="ride", ride_with="zz")], {"h1"}, "h1")
refused("more than the cap", travel.validate_legs, [leg("in", "2026-08-24")] * (travel.LEGS_MAX + 1))
check("None is no legs", travel.validate_legs(None) == [])

print("\nWhose phone the car service gets (Q9)")
check("crew: their own by default", travel.uses_producer_phone({"kind": "crew"}) is False)
check("talent: the producer's by default", travel.uses_producer_phone({"kind": "talent"}) is True)
check("no kind (before talent_hires.sql) reads as crew", travel.uses_producer_phone({}) is False)
check("a choice beats the default", travel.uses_producer_phone({"kind": "talent", "car_service_producer_phone": False}) is False
      and travel.uses_producer_phone({"kind": "crew", "car_service_producer_phone": True}) is True)

SAM = {"id": "h1", "name": "Sam Ortiz", "role": "Gaffer", "kind": "crew", "phone": "555-0101",
       "email": "sam@example.com", "rate_shoot": 900, "dates_override": {},
       "travel_legs": travel.validate_legs([
           leg("in", "2026-08-24", carrier="Delta", flight="DL 401", from_airport="PDX", to_airport="EWR",
               arrive_time="15:20", plan="car_service"),
           leg("out", "2026-08-28", carrier="Delta", flight="DL 412", from_airport="EWR", depart_time="18:10",
               to_airport="PDX", plan="car_service")])}
DEE = {"id": "h2", "name": "Dee Park", "role": "Model", "kind": "talent", "phone": "555-0102",
       "dates_override": {},
       "travel_legs": travel.validate_legs([
           leg("in", "2026-08-24", carrier="United", flight="UA 9", to_airport="ewr ", arrive_time="15:55",
               plan="car_service")])}
ROB = {"id": "h3", "name": "Rob Lee", "role": "Grip", "kind": "crew", "phone": None, "dates_override": {},
       "car_service_producer_phone": False,
       "travel_legs": travel.validate_legs([
           leg("in", "2026-08-24", to_airport="EWR", arrive_time="17:30", plan="rental",
               note="picks up Sam"),
           leg("in", "2026-08-23", to_airport="EWR", plan="own")])}
HELD = {"id": "h4", "name": "Held Person", "status": "hold", "hold_rank": 1, "dates_override": {},
        "travel_legs": travel.validate_legs([leg("in", "2026-08-24", to_airport="EWR", arrive_time="15:30",
                                                 plan="car_service")])}
LOCAL = {"id": "h5", "name": "Lou Local", "away": [], "dates_override": {}, "phone": "555-0105",
         "travel_legs": travel.validate_legs([leg("in", "2026-08-24", plan="car_service")])}
HIRES = [SAM, DEE, ROB, HELD, LOCAL]

view = travel.build(JOB, HIRES)
names = [r["name"] for r in view["arrivals"]]
check("a hold flies on no document", "Held Person" not in names and
      all(r["name"] != "Held Person" for r in view["manifest"]))
check("arrivals in landing order", names[:3] == ["Rob Lee", "Sam Ortiz", "Dee Park"], names)
check("departures listed apart", [r["name"] for r in view["departures"]] == ["Sam Ortiz"])
man = {(r["name"], r["direction"]): r for r in view["manifest"]}
check("airport codes are stored upper case", DEE["travel_legs"][0]["to_airport"] == "EWR")
check("the manifest is car service legs only", ("Rob Lee", "in") not in man and len(view["manifest"]) == 4)
check("the manifest covers departures too", ("Sam Ortiz", "out") in man)
check("crew get their own number", man[("Sam Ortiz", "in")]["phone"] == "555-0101")
check("talent get the producer's", man[("Dee Park", "in")]["phone"] == "555-0199" and man[("Dee Park", "in")]["phone_is_producer"])
check("someone with no number on file is named", view["missing_phone"] == [], view["missing_phone"])
v2 = travel.build({**JOB, "producer_phone": None}, [DEE])
check("no producer number → the talent is named as missing one", v2["missing_phone"] == ["Dee Park"])
check("a ride shows who with", travel.plan_text({"plan": "ride", "ride_with": "h1"}, {"h1": "Sam Ortiz"}) == "Ride with Sam Ortiz")
check("a plan and a note read together", next(r for r in view["arrivals"] if r["name"] == "Rob Lee" and r["arrive_time"])["plan_text"]
      == "Rental car — picks up Sam")

print("\nArrival groups")
g = view["groups"]
first = next(x for x in g if x["date"] == "2026-08-24" and x["first"] == "15:20")
check("landings within the hour share a group, airports matched loosely",
      [p["name"] for p in first["people"]] == ["Sam Ortiz", "Dee Park"], g)
check("a landing more than an hour after the first starts a new group",
      any([p["name"] for p in x["people"]] == ["Rob Lee"] and x["first"] == "17:30" for x in g))
check("no time set → a group of its own", any(x["first"] is None and x["date"] == "2026-08-24" for x in g))
check("the groups don't include a hold", all(p["name"] != "Held Person" for x in g for p in x["people"]))

print("\nChecked against away dates")
w = {r["name"] + r["date"]: r["warning"] for r in view["arrivals"] + view["departures"]}
check("an arrival on their first away day is quiet", w["Sam Ortiz2026-08-24"] is None)
check("a departure on their last away day is quiet", w["Sam Ortiz2026-08-28"] is None)
check("a day-early arrival is noted, not refused", w["Rob Lee2026-08-23"] == "Lands Aug 23; their first day away is Aug 24.")
check("a local with a flight is told why", w["Lou Local2026-08-24"].startswith("Set as local"))
check("an overnight flight is checked on its landing day",
      travel.leg_warning(JOB, SAM, {"direction": "in", "date": "2026-08-23", "arrive_date": "2026-08-24"}) is None)
check("a hire without the migration's fields reads as no legs",
      travel.build(JOB, [{"id": "x", "name": "Old", "dates_override": {}}])["arrivals"] == [])

print("\nThe documents")
cols, secs = blocks(view, car_service=False)
doc_text = str(secs) + to_html(JOB, view, False)
check("the travel doc has her columns", cols[:2] == ["Name", "Date"] and cols[-1] == "Transportation Plan")
check("ARRIVALS then DEPARTURES", [s[0] for s in secs] == ["ARRIVALS", "DEPARTURES"])
check("the travel doc carries no phone", "555-01" not in doc_text and "Phone" not in cols)
check("...no email or rate", "example.com" not in doc_text and "900" not in doc_text)
cols, secs = blocks(view, car_service=True)
cs_html = to_html(JOB, view, True)
check("the car service copy has a Phone column", cols[1] == "Phone")
check("...with the producer's number marked", "555-0199 (producer)" in cs_html)
check("...and the production contact on top", "Production contact" in cs_html)
check("...and no email or rate", "example.com" not in cs_html and "900" not in cs_html)
check("...and only car service legs", all("Rental" not in row[-1] for _l, rows in secs for row in rows))
check("times print 12h", "3:20 PM" in to_html(JOB, view, False))
check("a block with nothing in it says so", "None" in to_html(JOB, travel.build(JOB, []), True))
from openpyxl import load_workbook  # noqa: E402
wb = load_workbook(io.BytesIO(to_xlsx(JOB, view, True)))
vals = [c for row in wb.active.iter_rows(values_only=True) for c in row if c]
check("the Excel opens, titled", vals[0] == "Car Service - Northwind Fall")
check("...with both blocks", "ARRIVALS" in vals and "DEPARTURES" in vals)
wb = load_workbook(io.BytesIO(to_xlsx(JOB, view, False)))
check("the travel doc's Excel has no phone", not any("555-01" in str(c) for row in wb.active.iter_rows(values_only=True) for c in row if c))

print("\nThrough the API")
J = "00000000-0000-0000-0000-0000000000c1"
OTHER = "00000000-0000-0000-0000-0000000000c9"
db = {"jobs": [{**JOB, "id": J, "owner_id": "o1"}, {"id": OTHER, "owner_id": "o2", "name": "Theirs", "crew_dates": {}}],
      "job_hires": [{**{k: v for k, v in SAM.items() if k != "travel_legs"}, "job_id": J, "sort_order": 0},
                    {**{k: v for k, v in DEE.items() if k != "travel_legs"}, "job_id": J, "sort_order": 1},
                    {"id": "h9", "job_id": J, "name": "Gone", "status": "released", "sort_order": 2}]}
client = FakeClient(db)
travel_router.get_client = lambda: client
import routers.jobs as jobs_router  # noqa: E402  (the _own_job travel uses)
jobs_router.get_client = lambda: client
U = travel_router.HireTravelUpdate
travel_router.update_hire_travel(J, "h1", U(travel_legs=[leg("in", "2026-08-24", to_airport="EWR", arrive_time="3:20 PM",
                                                             plan="ride", ride_with="h2")]), owner_ids={"o1"})
check("saving legs stores them normalised", db["job_hires"][0]["travel_legs"][0]["arrive_time"] == "15:20")
try:
    travel_router.update_hire_travel(J, "h1", U(travel_legs=[leg("in", "2026-08-24", plan="ride", ride_with="nobody")]),
                                     owner_ids={"o1"})
    check("a ride with someone off the job is a 422", False)
except HTTPException as e:
    check("a ride with someone off the job is a 422", e.status_code == 422)
travel_router.update_hire_travel(J, "h2", U(car_service_producer_phone=False), owner_ids={"o1"})
check("the phone switch saves", db["job_hires"][1]["car_service_producer_phone"] is False)
travel_router.update_hire_travel(J, "h2", U(car_service_producer_phone=None), owner_ids={"o1"})
check("null puts them back on the default", db["job_hires"][1]["car_service_producer_phone"] is None)
out = travel_router.get_travel(J, owner_ids={"o1"})
check("the tab leaves released people off", [p["name"] for p in out["people"]] == ["Sam Ortiz", "Dee Park"])
check("...and says talent default to the producer's number",
      out["people"][1]["producer_phone"] is True and out["people"][1]["producer_phone_chosen"] is False)
check("...and the ride reads with a name", out["arrivals"][0]["plan_text"] == "Ride with Dee Park")
try:
    travel_router.get_travel(OTHER, owner_ids={"o1"})
    check("someone else's job is refused", False)
except HTTPException as e:
    check("someone else's job is refused", e.status_code == 404)

print()
print(f"{len(FAILS)} FAILED: {', '.join(FAILS)}" if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
