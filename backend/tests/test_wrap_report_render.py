"""Structural checks on the rendered wrap report.

    cd backend && venv/bin/python tests/test_wrap_report_render.py

Two things here are not style preferences and would be real bugs:
the CSS must stay scoped (the fragment is injected into an app page), and
producer free text must arrive escaped (it reaches a browser verbatim).
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.wrap_report_data import build_wrap_data  # noqa: E402
from services.wrap_report_template import render_wrap_report  # noqa: E402

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else '  — ' + detail}")
    if not ok:
        FAILS.append(name)


def full_day() -> dict:
    return build_wrap_data(
        project={"name": "Northwind Athletic — Spring Campaign", "shoot_date": "2026-04-14",
                 "first_call_time": "06:40", "first_shot_time": "08:15", "est_wrap_time": "19:55"},
        crew=[
            {"name": "Dana Whitfield", "role": "Director", "department": "Production",
             "call_time": "06:40", "confirmed_at": "2026-04-13T18:02:00Z", "wants_pdf": True,
             "email": "dana@example.com", "phone": "555-0100"},
            {"name": "Marcus Oyelaran", "role": "1st AC", "department": "Camera",
             "call_time": "07:00", "confirmed_at": None,
             "email": "marcus@example.com", "phone": "555-0101"},
            {"name": "Priya Raghunathan", "role": "Gaffer", "department": "Lighting",
             "call_time": "06:40", "confirmed_at": "2026-04-13T20:14:00Z"},
            {"name": "Sam Brody", "role": "Swing", "department": "", "call_time": "09:00",
             "confirmed_at": None},
        ],
        talent=[{"name": "Ari Delacroix", "role": "Principal", "call_time": "08:30",
                 "confirmed_at": "2026-04-14T05:50:00Z"}],
        schedule=[
            {"description": "Block A — track & field", "start_time": "08:15", "end_time": "12:00"},
            {"description": "Lunch", "start_time": "12:00", "end_time": "12:30"},
            {"description": "Block B — <b>studio</b> pickups", "start_time": "13:30", "end_time": "18:30"},
        ],
        location={"location_name": "Fairview Track", "address": "1400 Fairview Ave, Seattle WA",
                  "parking_notes": "Lot C only.\nNo idling by the gate."},
        moves=[{"label": "Move to studio", "move_time": "12:45", "address": "500 Dexter Ave N, Seattle WA"}],
        meals={"lunch_start": "12:00", "lunch_end": "12:30", "lunch_notes": "Walk-away"},
        accommodation={"hotel_name": "The Sound Hotel", "address": "2120 4th Ave, Seattle WA",
                       "room_block": "NW-APRIL"},
        call_sheet={"sent_at": "2026-04-13T16:00:00Z"},
        attachments=[{"filename": "parking-map.pdf"}],
    )


print("\nA full day renders")
html = render_wrap_report(full_day())
check("renders something substantial", len(html) > 3000, f"{len(html)} chars")
check("opens with the scoped style block", html.lstrip().startswith("<style>"))

print("\nThe CSS stays scoped — this fragment is injected into an app page")
css = html[html.find("<style>"): html.find("</style>")]
selectors = [s.strip() for line in css.splitlines() if "{" in line
             for s in line.split("{")[0].split(",") if s.strip()]
unscoped = [s for s in selectors
            if not s.startswith((".wrap-report", "[data-theme", "@media", "}"))]
check("every rule is under .wrap-report", not unscoped, "; ".join(unscoped[:4]))

print("\nProducer free text is escaped, not interpreted")
check("a bold tag in a schedule line arrives as text", "&lt;b&gt;studio&lt;/b&gt;" in html)
check("and never as markup", "<b>studio</b>" not in html)
check("parking notes keep their line break", "Lot C only.<br>No idling" in html)

print("\nThe report says what happened")
check("everyone on the sheet is named", all(n in html for n in
      ("Dana Whitfield", "Marcus Oyelaran", "Priya Raghunathan", "Sam Brody", "Ari Delacroix")))
check("the two crew who never confirmed are called out by name",
      re.search(r"never confirmed.*Marcus Oyelaran.*Sam Brody", html, re.S) is not None)
check("talent are NOT in that callout — nobody asked them to confirm",
      re.search(r"never confirmed[^<]*Ari Delacroix", html, re.S) is None,
      "the talent table has no confirmed_at column; they can never answer")
check("undepartmented crew get a heading rather than vanishing", "No department" in html)
check("talent are their own group", ">Talent<" in html)
check("the day length is stated", "13h 15m" in html)

print("\nContact details never reach the page")
check("no email address anywhere", "@example.com" not in html)
check("no phone number anywhere", "555-01" not in html)

print("\nMaps links, both providers")
check("Apple Maps for the location", "maps.apple.com/?q=1400%20Fairview" in html)
check("Google Maps for the location", "google.com/maps/search/?api=1&amp;query=1400%20Fairview" in html)
check("the company move gets its own links", "500%20Dexter" in html)
check("so does the hotel", "2120%204th%20Ave" in html)

print("\nThe timeline is drawn to the day, in percentages")
lefts = [float(m) for m in re.findall(r"left:([\d.]+)%", html)]
check("every position is on the axis", lefts and all(0 <= v <= 100 for v in lefts),
      f"out of range: {[v for v in lefts if not 0 <= v <= 100][:3]}")
widths = [float(m) for m in re.findall(r"width:([\d.]+)%", html)]
check("no block runs off the end",
      all(l + w <= 100.01 for l, w in zip(lefts, widths)), "a block overflows the axis")
check("the meal block is styled as a meal", 'class="blk meal"' in html)
check("the company move is marked", "Move to studio" in html)

print("\nEvery section has a null path")
bare = build_wrap_data(project={"name": "Untitled", "shoot_date": None}, crew=[], talent=[],
                       schedule=[], location=None, moves=[], meals=None, accommodation=None,
                       call_sheet=None, attachments=[])
try:
    empty = render_wrap_report(bare)
    check("an empty project still renders", "Untitled" in empty, "")
    check("no timeline without a day", "class=\"tl\"" not in empty)
    check("no locations section without a location", ">Locations<" not in empty)
    check("no crew rows, but the section stands", ">The crew<" in empty)
    check("no logistics section with nothing in it", ">Logistics<" not in empty)
except Exception as exc:  # noqa: BLE001
    check("an empty project still renders", False, repr(exc))

print("\nAn accommodation row that exists but is blank shows nothing")
blank_hotel = build_wrap_data(project={"name": "X", "shoot_date": "2026-01-01"}, crew=[], talent=[],
                              schedule=[], location=None, moves=[], meals=None,
                              accommodation={"hotel_name": "", "address": "", "notes": ""},
                              call_sheet=None, attachments=[])
check("no empty Accommodations block", ">Accommodations<" not in render_wrap_report(blank_hotel))
check("and no Logistics heading either", ">Logistics<" not in render_wrap_report(blank_hotel))

print()
print(f"{len(FAILS)} FAILED: {', '.join(FAILS)}" if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
