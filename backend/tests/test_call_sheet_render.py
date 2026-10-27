"""Structural checks on the rendered call sheet.

    cd backend && venv/bin/python tests/test_call_sheet_render.py

Asserts what a dropped section or an unescaped name would break, not what the
markup happens to look like — a test that pins exact HTML fails on every
whitespace change and stops being read.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fixtures  # noqa: E402  (needs backend on the path first)
from services.call_sheet_template import render_call_sheet  # noqa: E402

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else '  — ' + detail}")
    if not ok:
        FAILS.append(name)


def has_section(html: str, title: str) -> bool:
    """Section bars carry their title in a navy header cell."""
    return re.search(rf">{re.escape(title)}<", html, re.I) is not None


def section_order(html: str, titles: list[str]) -> list[str]:
    found = [(html.lower().find(f">{t.lower()}<"), t) for t in titles]
    return [t for pos, t in sorted(p for p in found if p[0] >= 0)]


print("\nEvery fixture renders, and is a complete document")
rendered = {}
for name, build in fixtures.ALL.items():
    try:
        html = render_call_sheet(build())
        rendered[name] = html
        ok = html.lstrip().startswith("<!DOCTYPE html>") and html.rstrip().endswith("</html>")
        check(f"{name} renders a full document", ok, f"{len(html)} chars")
    except Exception as e:
        check(f"{name} renders", False, f"{type(e).__name__}: {e}")

full = rendered.get("full", "")

print("\nThe full sheet has every section, in the prompt's order")
expected = ["Weather", "Location &amp; Parking", "Nearest Hospital", "Crew",
            "Agency &amp; Client", "Talent", "Meal Plan", "Schedule", "Accommodations"]
for title in expected:
    check(f"section present: {title.replace('&amp;', '&')}", has_section(full, title))
check("hospital sits between location and crew",
      section_order(full, ["Location &amp; Parking", "Nearest Hospital", "Crew"])
      == ["Location &amp; Parking", "Nearest Hospital", "Crew"],
      "order was " + str(section_order(full, ["Location &amp; Parking", "Nearest Hospital", "Crew"])))

print("\nConditional sections disappear when their data does")
minimal = rendered.get("minimal", "")
for title in ["Weather", "Location &amp; Parking", "Nearest Hospital",
              "Agency &amp; Client", "Talent", "Meal Plan", "Schedule", "Accommodations"]:
    check(f"minimal omits {title.replace('&amp;', '&')}", not has_section(minimal, title))
check("minimal still has Crew", has_section(minimal, "Crew"))
check("no_weather omits only Weather",
      not has_section(rendered["no_weather"], "Weather") and has_section(rendered["no_weather"], "Crew"))
check("no_hospital omits only Nearest Hospital",
      not has_section(rendered["no_hospital"], "Nearest Hospital")
      and has_section(rendered["no_hospital"], "Location &amp; Parking"))
check("no_header_pills drops the pills row", "FIRST CALL" not in rendered["no_header_pills"])

print("\nGrouping follows the producer's order, and only when there is one")
flat = rendered["undepartmented_crew"]
check("flat crew table has no department sub-headers", "#dce8f0" not in flat)
grouped = full
check("departments appear as sub-headers", "#dce8f0" in grouped)
positions = [grouped.find(d) for d in ["Production", "Camera", "Grip &amp; Electric"]]
check("departments in first-appearance order, not alphabetical",
      positions == sorted(positions) and -1 not in positions, str(positions))
mixed = rendered["mixed_departments"]
check("undepartmented crew go last", mixed.rfind("Sam Okonkwo") > mixed.rfind("Aisha Bello"))

print("\nColumns drop when nothing fills them")
nocols = rendered["no_contact_columns"]
check("phone column omitted when nobody has one", ">Phone<" not in nocols)
check("email column omitted when nobody has one", ">Email<" not in nocols)
check("phone column present when someone has one", ">Phone<" in full)

print("\nCall times: formatted, noted, or explicitly N/A")
check("raw 06:30:00 renders as 6:30 AM", "6:30 AM" in full and "06:30:00" not in full)
noted = rendered["redacted_and_noted"]
check("a call-time note passes through verbatim", "Own Call" in noted)
check("a missing call time prints N/A, never blank", "N/A" in noted)

print("\nFree text is escaped, not executed")
hostile = rendered["hostile_text"]
check("script tag is escaped", "<script>" not in hostile and "&lt;script&gt;" in hostile)
check("attribute break is escaped", 'onmouseover="alert(1)"' not in hostile)
check("ampersand in a name survives as text", "Fish &amp; Chips" in hostile)
check("legitimate markup in notes is not executed",
      "<b>only</b>" not in hostile and "&lt;b&gt;only&lt;/b&gt;" in hostile)

print("\nLine breaks and dates — both were wrong on the first render")
check("newlines become real <br>, not visible text",
      "<br>" in full and "&lt;br&gt;" not in full,
      "Markup.replace escapes its arguments, which turned the <br> itself into text")
check("free text keeps its line breaks", "Catering at basecamp.<br>" in full)
check("shoot date is written out with the weekday",
      "Monday, September 14, 2026" in full and "2026-09-14" not in full)

print("\nLayout rules that exist because real data is longer than sample data")
longn = rendered["long_names"]
check("hospital name and phone are separate cells, not adjacent spans",
      longn.count('align="right"') >= 2)
check("no null or undefined leaks into the output",
      "None" not in full.replace("None-", "") and "undefined" not in full and "null" not in full)
check("no <style> block — email clients strip them", "<style" not in full)
check("every table sets width in CSS, not only the legacy attribute",
      full.count('style="width:100%;border-collapse') > 0
      and full.count('style="border-collapse') == 0,
      "WeasyPrint ignores width=\"100%\" and shrinks tables to content in the PDF")
check("th cells are nowrap so headings do not stack",
      full.count("white-space:nowrap") >= 5)
emails = rendered["long_emails"]
check("phone numbers never wrap, even beside a long email",
      emails.count("white-space:nowrap") > full.count("white-space:nowrap") - 1
      and 'padding:9px 12px;white-space:nowrap;">310-555' in emails,
      "a phone split mid-digit is unusable")

print("\nCompany moves render with their own hospital line")
moves = rendered["company_moves"]
check("both moves present", moves.count("Company Move") == 2)
check("move-level hospital appears", "Children&#39;s Hospital Los Angeles" in moves
      or "Children's Hospital Los Angeles" in moves)
check("move time is formatted", "11:00 AM" in moves)

print("\nA hotel with no distance never says \"miles from set\" with no number")
no_dist = fixtures.full()
del no_dist["accommodation"]["distance_from_set_miles"]   # no address, or it didn't geocode
html_nd = render_call_sheet(no_dist)
check("the hotel still prints", "Courtyard by Marriott" in html_nd)
check("no bare 'miles from set'", "miles from set" not in html_nd)
check("with a distance, it prints the number", "8.4 miles from set" in full)

print("\nWhich day of the job it is")
labelled = fixtures.full()
labelled["project"]["day_label"] = "Day 2 of 4"
check("a day in a multi-day job says which day", "Day 2 of 4" in render_call_sheet(labelled))
check("a one-day sheet says nothing extra", "Day 1 of" not in full and "of 4" not in full)

print()
print("ALL PASS" if not FAILS else f"{len(FAILS)} FAILURES: " + ", ".join(FAILS))
sys.exit(1 if FAILS else 0)
