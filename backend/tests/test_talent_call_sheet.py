"""The per-talent call sheet for agents (services/talent_call_sheet.py,
routers/talent_call_sheet.py).

    cd backend && venv/bin/python tests/test_talent_call_sheet.py

The producer's talent call sheet (docs/producer-documents-map.md §1.8): one talent, sent
to their agent — dates as date lines, travel, hotel, the shoot day's call time,
location, meals and weather, who to call, and prep instructions. One sheet per
talent per job (Patrick, 2026-10-02). It goes outside the production, so it
carries no rate, fee or per diem, and only the phones the producer chose.
Every person, number and address here is invented.
"""

import io
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import HTTPException  # noqa: E402

from services import talent_call_sheet as tcs  # noqa: E402
from services.job_dates import DatesError, talent_dates  # noqa: E402
from services.travel import validate_legs  # noqa: E402
from tests.fake_supabase import FakeClient  # noqa: E402
from routers import talent_call_sheet as router  # noqa: E402
import routers.jobs as jobs_router  # noqa: E402  (the _own_job the router uses)

FAILS = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else '  -- ' + str(detail)}")
    if not ok:
        FAILS.append(name)


CREW = {"travel": [["2026-08-12", "2026-08-12"]], "shoot": [["2026-08-13", "2026-08-14"]],
        "travel_out": [["2026-08-15", "2026-08-15"]]}
J = "00000000-0000-0000-0000-0000000000d1"
JOB = {"id": J, "owner_id": "o1", "name": "Northwind Fall", "client_name": "Northwind", "payroll_provider": "Wrapbook",
       "crew_dates": CREW, "day_labels": {"2026-08-13": "Nike"}, "producer_phone": "555-0199",
       "per_diem_shoot": 50, "per_diem_other": 70,
       "hotels": [{"id": "s1", "name": "The Oxford", "address": "1 Main St, Portland", "phone": "555-0300",
                   "check_in": "2026-08-12", "check_out": "2026-08-15", "rooms": []}],
       "talent_sheet": {"contacts": ["c1", "c2", "gone"], "hotel_note": "Room and tax to the production.\nIncidentals on your own card.",
                        "prep_note": "No makeup\nClean hair", "notes": "Breakfast and lunch on location"}}
DEE = {"id": "t1", "job_id": J, "kind": "talent", "name": "Dee Park", "role": "Model", "roster_id": "r1",
       "phone": "555-0102", "email": "dee@example.com", "rate_shoot": 1500, "agency_fee_pct": 20,
       "dates_override": talent_dates(["2026-08-13", "2026-08-14"]), "day_notes": {"2026-08-12": "rideshare and bill back"},
       "travel_legs": validate_legs([{"direction": "in", "date": "2026-08-12", "carrier": "Delta", "flight": "DL 401",
                                      "from_airport": "LAX", "depart_time": "7:00 AM", "to_airport": "PDX",
                                      "arrive_time": "3:20 PM", "plan": "car_service"}]),
       "sort_order": 0}
HELD = {"id": "t2", "job_id": J, "kind": "talent", "name": "Held Talent", "status": "hold", "hold_rank": 1,
        "dates_override": {}, "sort_order": 1}
STYLIST = {"id": "c1", "job_id": J, "kind": "crew", "name": "Sam Ortiz", "role": "Stylist", "phone": "555-0101",
           "email": "sam@example.com", "rate_shoot": 900, "dates_override": {}, "sort_order": 2}
HMU = {"id": "c2", "job_id": J, "name": "Rob Lee", "role": "HMU", "phone": "555-0105", "status": "released",
       "dates_override": {}, "sort_order": 3}
GAFFER = {"id": "c3", "job_id": J, "kind": "crew", "name": "Not Ticked", "role": "Gaffer", "phone": "555-0177",
          "dates_override": {}, "sort_order": 4}
HIRES = [DEE, HELD, STYLIST, HMU, GAFFER]
ROSTER = {"id": "r1", "owner_id": "o1", "name": "Dee Park", "agency": "Wilhelmina", "agent_name": "Ana Agent",
          "agent_email": "ana@example.com"}
DAY1 = {"id": "p1", "owner_id": "o1", "job_id": J, "name": "Northwind Nike", "shoot_date": "2026-08-13"}
DAY2 = {"id": "p2", "owner_id": "o1", "job_id": J, "name": "Northwind Day 2", "shoot_date": "2026-08-14"}
LOC = {"id": "l1", "project_id": "p1", "location_name": "Studio 4", "address": "200 Water St, Portland",
       "parking_notes": "Lot behind the building"}
TROW = {"id": "tr1", "project_id": "p1", "hire_id": "t1", "name": "Dee Park", "call_time": "07:00:00",
        "call_time_note": "meet at basecamp"}
# Already on day 2's list before she was hired: hiring finds her by email and
# leaves the row unlinked, so the sheet has to find it the same way.
TROW2 = {"id": "tr2", "project_id": "p2", "hire_id": None, "name": "Dee Park", "email": "DEE@example.com",
         "call_time": "08:00:00"}
SOMEONE = {"id": "tr3", "project_id": "p2", "hire_id": "zz", "name": "Other", "email": "dee@example.com"}
MEALS = {"id": "m1", "project_id": "p1", "breakfast_start": "06:30:00", "breakfast_end": "07:30:00",
         "lunch_start": "12:30:00", "lunch_notes": "walk-away"}
WEATHER = {"condition": "Partly cloudy", "high_f": 74, "low_f": 58, "precipitation_chance": 10, "sunrise": "6:12 AM"}

print("\nSettings")
s = tcs.validate_settings({"contacts": ["c1", "c1", "c3"], "prep_note": "  No makeup  \n\n Clean   hair ",
                           "hotel_note": "", "notes": None}, {"c1", "c3"})
check("contacts de-duplicate, keep their order", s["contacts"] == ["c1", "c3"])
check("a note keeps its lines, tidied", s["prep_note"] == "No makeup\nClean hair")
check("blank notes are None", s["hotel_note"] is None and s["notes"] is None)
try:
    tcs.validate_settings({"contacts": ["t1"]}, {"c1"})
    check("a contact who isn't crew on the job is refused", False)
except DatesError:
    check("a contact who isn't crew on the job is refused", True)
try:
    tcs.validate_settings({"prep_note": "x" * (tcs.TEXT_MAX + 1)}, set())
    check("an overlong note is refused", False)
except DatesError:
    check("an overlong note is refused", True)
check("a job before the migration reads as empty settings", tcs.settings_of({})["contacts"] == [])

print("\nWho gets a sheet")
check("booked talent only — no hold, no crew", [h["name"] for h in tcs.talent_hires(HIRES)] == ["Dee Park"])

print("\nThe sheet")
days = [{"project": DAY1, "location": LOC, "talent_row": TROW, "meals": MEALS, "weather": WEATHER}]
sheet = tcs.build_sheet(JOB, DEE, roster=ROSTER, hires=HIRES, days=days,
                        producer={"name": "Alex Producer", "email": "producer@example.com"})
html = tcs.to_html(sheet)
check("header: talent, job, client, agency + agent, bill to",
      sheet["talent"] == "Dee Park" and sheet["client"] == "Northwind" and sheet["agency"] == "Wilhelmina"
      and sheet["agent"] == "Ana Agent" and sheet["bill_to"] == "Wrapbook")
check("dates are the deal memo's date lines, with labels and notes",
      any("Nike" in line for line in sheet["dates"]) and any("rideshare and bill back" in line for line in sheet["dates"]),
      sheet["dates"])
check("travel reads as a sentence", sheet["travel"] == ["Arrives Wed, Aug 12 — Delta DL 401, LAX 7:00 AM to PDX 3:20 PM. Car service"],
      sheet["travel"])
check("no arrow in what the PDF prints", "→" not in html)
check("the hotel is theirs: their own check-in and check-out",
      sheet["hotels"] == [{"name": "The Oxford", "address": "1 Main St, Portland", "phone": "555-0300",
                           "check_in": "Wed, Aug 12", "check_out": "Sat, Aug 15", "nights": 3}], sheet["hotels"])
day = sheet["shoot_days"][0]
check("shoot day: date and label", day["date"] == "Thu, Aug 13" and day["label"] == "Nike")
check("call time with the meeting point", day["call"] == "7:00 AM — meet at basecamp", day["call"])
check("location, parking", day["location"] == "Studio 4" and day["parking"] == "Lot behind the building")
check("meals", day["meals"] == "Breakfast 6:30 AM–7:30 AM · Lunch 12:30 PM (walk-away)", day["meals"])
check("weather", day["weather"].startswith("Partly cloudy · High 74°F / Low 58°F"), day["weather"])
names = [c["name"] for c in sheet["contacts"]]
check("who to call: the producer first, with the job's number",
      sheet["contacts"][0] == {"name": "Alex Producer", "role": "Producer", "phone": "555-0199", "email": "producer@example.com"})
check("...then only the ticked crew", names == ["Alex Producer", "Sam Ortiz"], names)
check("...a released or removed contact drops off", "Rob Lee" not in names)
held_back = tcs.contacts({**JOB, "talent_sheet": {"contacts": ["c1"]}}, [{**STYLIST, "status": "hold"}], {"name": "Alex Producer"})
check("...and so does one put back on hold: an agent only gets the numbers of people on the job",
      [c["name"] for c in held_back] == ["Alex Producer"], held_back)
check("...an unticked crew member's number never prints", "555-0177" not in html)
check("the talent's own phone and email don't print", "555-0102" not in html and "dee@example.com" not in html)
check("the agent's email doesn't print", "ana@example.com" not in html)
check("NO rate, fee or per diem", all(x not in html for x in ("1500", "1,500", "20%", "$")), "money in the sheet")
check("the prep note prints, line by line", "Before you arrive" in html and "No makeup\nClean hair" in html)
check("the hotel note and the other info print", "Incidentals on your own card" in html and "Breakfast and lunch on location" in html)
check("free text is escaped", "&lt;b&gt;" in tcs.to_html({**sheet, "notes": "<b>hi</b>"}))
bare = tcs.build_sheet({"name": "Bare"}, {"name": "X", "kind": "talent"}, roster=None, hires=[], days=[], producer={})
check("a bare job still makes a sheet", bare["contacts"][0]["name"] == "Producer" and "X" in tcs.to_html(bare))
check("a call with no time set says 'To come'", "To come" in tcs.to_html({**sheet, "shoot_days": [{**day, "call": ""}]}))

print("\nWhat's missing (the screen)")
check("a complete sheet has no gaps", tcs.gaps(JOB, DEE, days) == [], tcs.gaps(JOB, DEE, days))
check("not on any day yet", "Not on any shoot day's talent list yet" in tcs.gaps(JOB, DEE, []))
check("no call time", "No call time on a shoot day" in tcs.gaps(JOB, DEE, [{**days[0], "talent_row": {}}]))
check("no flights for a traveller", "No flights" in tcs.gaps(JOB, {**DEE, "travel_legs": []}, days))
check("...but a local needs none", "No flights" not in tcs.gaps(JOB, {**DEE, "travel_legs": [], "away": []}, days))
check("no producer number", any("producer number" in g for g in tcs.gaps({**JOB, "producer_phone": ""}, DEE, days)))

print("\nThrough the API")
OTHER = "00000000-0000-0000-0000-0000000000d9"
db = {"jobs": [dict(JOB), {"id": OTHER, "owner_id": "o2", "name": "Theirs", "crew_dates": {}}],
      "job_hires": [dict(h) for h in HIRES], "roster": [ROSTER], "projects": [DAY1, DAY2],
      "project_locations": [LOC], "project_meals": [MEALS], "talent": [TROW, SOMEONE, TROW2]}
client = FakeClient(db)
client.users["o1"] = {"full_name": "Alex Producer"}
router.get_client = jobs_router.get_client = lambda: client
router.get_user_identity = lambda uid: {"name": "Alex Producer", "email": "producer@example.com"}
router.geocode = lambda address: (45.5, -122.6)
looked_up = []
router.get_weather = lambda lat, lon, when: looked_up.append(when) or WEATHER
router.render_call_sheet_pdf = lambda html: html.encode()      # the HTML stands in for the PDF

panel = router.get_talent_sheets(J, owner_ids={"o1"})
check("the panel lists booked talent with their shoot days",
      [(t["name"], t["shoot_dates"]) for t in panel["talent"]] == [("Dee Park", ["2026-08-13", "2026-08-14"])], panel["talent"])
db["talent"].append({"id": "tr4", "project_id": "p0", "hire_id": None, "name": "Dee Park", "email": "dee@example.com"})
db["projects"].append({"id": "p0", "owner_id": "o1", "job_id": J, "name": "Travel day", "shoot_date": "2026-08-12"})
check("a row on a day she only travels isn't a shoot day on her sheet",
      [t["shoot_dates"] for t in router.get_talent_sheets(J, owner_ids={"o1"})["talent"]] == [["2026-08-13", "2026-08-14"]])
check("...finding an unlinked row by email, never someone else's linked row",
      router._row_for([SOMEONE, TROW2], DEE)["id"] == "tr2")
check("...names who's on hold", panel["held"] == ["Held Talent"])
check("...offers crew (not talent, not released) as contacts", [c["name"] for c in panel["crew"]] == ["Sam Ortiz", "Not Ticked"])
check("...and passes the settings back", panel["settings"]["prep_note"].startswith("No makeup"))
pdf = router.download_talent_sheet(J, "t1", owner_ids={"o1"}).body.decode()
check("one talent's PDF renders their sheet", "Dee Park" in pdf and "Studio 4" in pdf and "Partly cloudy" in pdf)
check("...both their days, the second at its own call time", "8:00 AM" in pdf and "Fri, Aug 14" in pdf)
check("...with weather looked up only where there's an address", looked_up == ["2026-08-13"], looked_up)
try:
    router.download_talent_sheet(J, "c1", owner_ids={"o1"})
    check("a crew hire gets no talent sheet", False)
except HTTPException as e:
    check("a crew hire gets no talent sheet", e.status_code == 400)
resp = router.download_all_talent_sheets(J, owner_ids={"o1"})
zf = zipfile.ZipFile(io.BytesIO(resp.body))
check("the zip holds every booked talent, no holds", zf.namelist() == ["Dee Park.pdf"], zf.namelist())
check("the zip is named for the job", "Talent Call Sheets - Northwind Fall.zip" in resp.headers["content-disposition"])
saved = router.update_talent_sheet_settings(J, router.TalentSheetSettings(talent_sheet={"contacts": ["c3"], "prep_note": "Bring heels"}),
                                            owner_ids={"o1"})
check("settings save", saved["contacts"] == ["c3"] and db["jobs"][0]["talent_sheet"]["prep_note"] == "Bring heels")
try:
    router.update_talent_sheet_settings(J, router.TalentSheetSettings(talent_sheet={"contacts": ["t1"]}), owner_ids={"o1"})
    check("ticking a talent as a contact is a 422", False)
except HTTPException as e:
    check("ticking a talent as a contact is a 422", e.status_code == 422)
try:
    router.get_talent_sheets(OTHER, owner_ids={"o1"})
    check("someone else's job is refused", False)
except HTTPException as e:
    check("someone else's job is refused", e.status_code == 404)
db["job_hires"] = [h for h in db["job_hires"] if h["id"] != "t1"]
try:
    router.download_all_talent_sheets(J, owner_ids={"o1"})
    check("no booked talent → a 400, not an empty zip", False)
except HTTPException as e:
    check("no booked talent → a 400, not an empty zip", e.status_code == 400)

print()
print(f"{len(FAILS)} FAILED: {', '.join(FAILS)}" if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
