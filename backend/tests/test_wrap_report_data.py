"""The figures behind a wrap report.

    cd backend && venv/bin/python tests/test_wrap_report_data.py

The timeline scale is the part worth testing hardest: it turns clock times into
percentages, and an off-by-an-hour there draws a plausible-looking picture of a
day that did not happen.
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.wrap_report_data import build_wrap_data, is_wrapped  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else '  -- ' + detail}")
    if not ok:
        FAILS.append(name)


PROJECT = {"name": "Tidewater Provisions", "shoot_date": "2026-08-21",
           "first_call_time": "05:45:00", "first_shot_time": "06:40:00",
           "est_wrap_time": "19:00:00"}
CREW = [
    {"name": "Dana Whitfield", "role": "Producer", "department": "Production",
     "call_time": "05:45:00", "confirmed_at": "2026-08-20T16:02:00Z", "wants_pdf": True},
    {"name": "Aisha Bello", "role": "Gaffer", "department": "Grip & Electric",
     "call_time": "05:45:00", "confirmed_at": "2026-08-20T15:51:00Z", "wants_pdf": False},
    {"name": "Colm Byrne", "role": "Key Grip", "department": "Grip & Electric",
     "call_time": "05:45:00", "confirmed_at": None, "wants_pdf": False},
    {"name": "Sam Okonkwo", "role": "PA", "department": None,
     "call_time": "06:30:00", "confirmed_at": "2026-08-20T17:10:00Z", "wants_pdf": True},
]
# No confirmed_at, because the talent table has no such column. Only
# crew_members carries a confirmation_token — talent are never asked.
TALENT = [{"name": "Imani Cole", "role": "Lead", "call_time": "10:00:00"}]
SCHEDULE = [
    {"start_time": "06:40:00", "end_time": "09:30:00", "description": "Scene 1 - Sunrise"},
    {"start_time": "12:15:00", "end_time": "13:00:00", "description": "Lunch"},
    {"start_time": "13:00:00", "end_time": None, "description": "Scene 3 - Beach hero"},
]
MOVES = [{"label": "Arcadia Beach", "move_time": "09:30:00", "location_name": "Arcadia"}]


def build(**over):
    args = dict(project=PROJECT, crew=CREW, talent=TALENT, schedule=SCHEDULE,
                location={"location_name": "Ecola"}, moves=MOVES, meals=None,
                accommodation=None, call_sheet={"sent_at": "2026-08-20T15:40:00Z"},
                attachments=[{"filename": "Shoot Zones.pdf"}])
    args.update(over)
    return build_wrap_data(**args)


d = build()

print("\nThe header figures")
check("day length spans first call to est wrap", d["project"]["day_length"] == "13h 15m",
      d["project"]["day_length"])
check("times are formatted for reading", d["project"]["first_call"] == "5:45 AM")
check("headcount separates crew and talent",
      d["headcount"]["crew"] == 4 and d["headcount"]["talent"] == 1)
check("departments counts only real ones, not the undepartmented",
      d["headcount"]["departments"] == 2, str(d["headcount"]["departments"]))
check("on the call sheet is everyone", d["headcount"]["on_call_sheet"] == 5)

print("\nConfirmations: the actionable half only")
c = d["confirmations"]
check("counted over crew, who are the only ones asked",
      c["confirmed"] == 3 and c["total"] == 4, f'{c["confirmed"]} of {c["total"]}')
check("the missing are NAMED", sorted(p["name"] for p in c["missing"]) == ["Colm Byrne"])
check("talent are never in the missing list",
      not any(p["name"] == "Imani Cole" for p in c["missing"]),
      "they have no way to confirm; listing them accuses them of ignoring nothing")
check("and are marked unconfirmable rather than unconfirmed",
      d["talent"][0]["confirmable"] is False and d["talent"][0]["confirmed"] is False)
check("crew stay confirmable",
      all(p["confirmable"] for dept in d["departments"] for p in dept["people"]))
check("with their department, so they can be chased",
      any(p["department"] == "Grip & Electric" for p in c["missing"]))
check("no average, median or duration anywhere in the block",
      not any(k in c for k in ("median", "average", "fastest", "slowest")),
      "cut on purpose — see the module docstring")

print("\nContact details never reach the report")
everyone = [p for g in d["departments"] for p in g["people"]] + d["talent"]
check("no email on anyone", all("email" not in p for p in everyone))
check("no phone on anyone", all("phone" not in p for p in everyone),
      "the Roster holds those; a wrap report would freeze a stale copy")

print("\nDepartments keep the producer's order, undepartmented last")
labels = [g["label"] for g in d["departments"]]
check("first-appearance order", labels[:2] == ["Production", "Grip & Electric"], str(labels))
check("undepartmented sit last, unlabelled", labels[-1] is None)

print("\nCall spread")
check("earliest and latest", d["earliest_call"] == "5:45 AM" and d["latest_call"] == "10:00 AM")
check("spread computed", d["call_spread"] == "4h 15m", str(d["call_spread"]))

print("\nThe timeline is drawn to a real scale")
tl = d["timeline"]
check("it exists", tl is not None)
check("starts at first call and ends at wrap", tl["start"] == "5:45 AM" and tl["end"] == "7:00 PM")
first = tl["blocks"][0]
# 6:40 is 55 min into a 795 min day -> 6.918%
check("a block lands at its true position", abs(first["left"] - 6.918) < 0.01, str(first["left"]))
check("and has its true width", abs(first["width"] - 21.384) < 0.01, str(first["width"]))
check("every block stays inside the axis",
      all(0 <= b["left"] <= 100 and b["left"] + b["width"] <= 100.01 for b in tl["blocks"]))
check("lunch is marked as a meal, not a shot",
      [b["kind"] for b in tl["blocks"] if b["label"] == "Lunch"] == ["meal"])
check("a block with no end still appears", any(b["label"].startswith("Scene 3") for b in tl["blocks"]))
check("the company move is a marker on the axis",
      len(tl["markers"]) == 1 and abs(tl["markers"][0]["left"] - 28.302) < 0.01,
      str(tl["markers"]))
check("hour ticks are on the hour and inside the span",
      tl["ticks"][0]["label"] == "6a" and all(0 < t["left"] < 100 for t in tl["ticks"]))
check("thirteen ticks between 6a and 7p", len(tl["ticks"]) == 13, str(len(tl["ticks"])))

print("\nA day with nothing to draw draws nothing")
check("no times at all -> no timeline",
      build(project={"name": "Bare", "shoot_date": "2026-08-21"},
            crew=[{"name": "X", "call_time": None, "confirmed_at": None}],
            talent=[], schedule=[], moves=[])["timeline"] is None)
check("but the report still builds",
      build(project={"name": "Bare", "shoot_date": None}, crew=[], talent=[],
            schedule=[], moves=[], location=None, call_sheet=None,
            attachments=[])["headcount"]["on_call_sheet"] == 0)

print("\nWrapped means the shoot date has passed")
check("yesterday is wrapped", is_wrapped({"shoot_date": "2026-08-21"}, date(2026, 9, 5)))
check("today is NOT wrapped yet", not is_wrapped({"shoot_date": "2026-09-05"}, date(2026, 9, 5)))
check("tomorrow is not", not is_wrapped({"shoot_date": "2026-09-06"}, date(2026, 9, 5)))
check("no shoot date is not", not is_wrapped({"shoot_date": None}, date(2026, 9, 5)))

print()
print("ALL PASS" if not FAILS else f"{len(FAILS)} FAILURES: " + ", ".join(FAILS))
sys.exit(1 if FAILS else 0)
