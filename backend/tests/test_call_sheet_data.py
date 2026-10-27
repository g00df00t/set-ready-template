"""Checks on the data handed to the renderer.

    cd backend && venv/bin/python tests/test_call_sheet_data.py

test_call_sheet_render.py feeds hand-built dicts straight to the renderer, so it
never touches the code that *builds* those dicts. This covers that half — and
particularly the two rules build_project_data enforces by removing values rather
than by asking the renderer to skip them:

  - a crew member flagged hide_contact has no phone/email key at all
  - agency and client phone/email are stripped unconditionally

Both are asserted on the dict AND on the rendered HTML, because "the renderer
doesn't print it today" is a weaker promise than "the value isn't there."

Input rows are shaped like the database returns them: hide_contact still set,
call_time_note still a separate column, talent still holding a location id.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.call_sheet_builder import build_call_sheet  # noqa: E402
from services.call_sheet_data import build_project_data  # noqa: E402

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else '  — ' + detail}")
    if not ok:
        FAILS.append(name)


PROJECT = {
    "name": "Northwind Athletic", "shoot_date": "2026-09-14",
    "notes": "internal producer note",
    "first_call_time": "06:30:00", "first_shot_time": None,
    "lunch_time": "12:30:00", "est_wrap_time": None,
    "general_call_time": "07:00:00",
}
CREW = [
    {"name": "Hidden Hank", "role": "Gaffer", "department": "Grip & Electric",
     "call_time": "06:30:00", "call_time_note": None, "hide_contact": True,
     "email": "hank@example.com", "phone": "310-555-0199"},
    {"name": "Noted Nora", "role": "2nd AD", "department": "Production",
     "call_time": "07:00:00", "call_time_note": "Own Call", "hide_contact": False,
     "email": "nora@example.com", "phone": "310-555-0200"},
]
MOVES = [{"id": "m1", "location_name": "Ridge Trail", "move_time": "11:00:00"}]
TALENT = [{"name": "Ada Lead", "role": "Lead", "call_time": "08:00:00",
           "call_time_note": None, "location_assignment": "m1", "hide_contact": False,
           "email": "ada@example.com", "phone": "310-555-0300"}]
CONTACTS = [{"organization": "Meridian & Co.", "name": "Cal Client",
             "role": "Agency Producer", "call_time": "09:00:00", "call_time_note": None,
             "email": "cal@agency.com", "phone": "310-555-0400"}]
MEALS = {"breakfast_start": None, "breakfast_end": None, "breakfast_notes": "",
         "lunch_start": "12:30:00", "lunch_end": "13:15:00", "lunch_notes": "Walk-away"}

data = build_project_data(PROJECT, CREW, [], None, CONTACTS, TALENT,
                          None, None, MOVES, None, MEALS)

print("\nThe project dict carries only what the sheet prints")
check("raw time columns withheld — header_times is their one representation",
      not any(k in data["project"] for k in
              ("first_call_time", "first_shot_time", "lunch_time",
               "est_wrap_time", "general_call_time")))
check("the producer's private notes are withheld", "notes" not in data["project"])
check("name and shoot date survive",
      data["project"]["name"] == "Northwind Athletic"
      and data["project"]["shoot_date"] == "2026-09-14")

print("\nHeader pills: only times that are set, already formatted")
check("unset times produce no pill",
      data["header_times"] == [{"label": "FIRST CALL", "time": "6:30 AM"},
                               {"label": "LUNCH", "time": "12:30 PM"}],
      str(data["header_times"]))

print("\nhide_contact removes the values, it doesn't hide them")
hank, nora = data["crew"]
check("hidden crew member has no phone key", "phone" not in hank)
check("hidden crew member has no email key", "email" not in hank)
# Crew call times are NOT formatted here — only the header pills and meals are.
# Rows keep the raw Postgres value and the renderer's display_time filter turns
# it into "6:30 AM", which is what lets a note like "Own Call" pass through the
# same field untouched.
check("hidden crew member keeps their name and their raw call time",
      hank["name"] == "Hidden Hank" and hank["call_time"] == "06:30:00",
      f'name={hank.get("name")!r} call_time={hank.get("call_time")!r}')
check("a visible crew member keeps both", nora["phone"] == "310-555-0200"
      and nora["email"] == "nora@example.com")
check("the hide_contact flag is bookkeeping and never passed on",
      all("hide_contact" not in c for c in data["crew"] + data["talent"]))

print("\nAgency and client contact details are stripped unconditionally")
check("no phone", "phone" not in data["agency_and_client_contacts"][0])
check("no email", "email" not in data["agency_and_client_contacts"][0])
check("organization, name, role and call time remain",
      data["agency_and_client_contacts"][0]["organization"] == "Meridian & Co.")

print("\ncall_time_note collapses into call_time")
check("a named call replaces the clock time", nora["call_time"] == "Own Call")
check("the note column itself is gone",
      all("call_time_note" not in r for r in data["crew"] + data["talent"]
          + data["agency_and_client_contacts"]))

print("\nTalent locations resolve from ids to names crew can read")
check("a company move id becomes its name", data["talent"][0]["location_label"] == "Ridge Trail")
check("an unassigned talent gets no label",
      build_project_data(PROJECT, [], [], None, None,
                         [{"name": "Solo", "location_assignment": None}],
                         None, None, [], None, None)["talent"][0]["location_label"] is None)
check("'primary' falls back when no location is set yet",
      build_project_data(PROJECT, [], [], None, None,
                         [{"name": "Solo", "location_assignment": "primary"}],
                         None, None, [], None, None)["talent"][0]["location_label"]
      == "Primary Location")

print("\nMeals: empty ones dropped, times formatted")
check("breakfast with nothing in it is dropped",
      data["meal_plan"] == [{"label": "LUNCH", "start": "12:30 PM",
                             "end": "1:15 PM", "notes": "Walk-away"}],
      str(data["meal_plan"]))
check("a meal with only notes still appears",
      build_project_data(PROJECT, [], [], None, None, None, None, None, [], None,
                         {"lunch_notes": "Walk-away, no catering"})["meal_plan"]
      == [{"label": "LUNCH", "start": None, "end": None, "notes": "Walk-away, no catering"}])

print("\nAnd none of it reaches the rendered sheet")
html = build_call_sheet(PROJECT, CREW, [], None, CONTACTS, TALENT,
                        None, None, MOVES, None, MEALS)
for label, needle in [("hidden crew phone", "310-555-0199"),
                      ("hidden crew email", "hank@example.com"),
                      ("agency phone", "310-555-0400"),
                      ("agency email", "cal@agency.com"),
                      ("producer's private notes", "internal producer note")]:
    check(f"{label} absent from the HTML", needle not in html)
check("the sheet still rendered something real",
      "Own Call" in html and "Ridge Trail" in html and html.rstrip().endswith("</html>"))

print()
print("ALL PASS" if not FAILS else f"{len(FAILS)} FAILURES: " + ", ".join(FAILS))
sys.exit(1 if FAILS else 0)
