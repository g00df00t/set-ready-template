"""The Whole crew dates, one person's own dates, and what happens when the crew
dates move under them.

    cd backend && venv/bin/python tests/test_crew_date_conflicts.py

Pure functions — services/job_dates.py has no database. The case that started
this (docs/job-layer-plan.md §6): moving the crew's shoot to Oct 7–10 left
Marcus Feld's custom prep on Oct 10–12, after shooting had already started.
"""

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services import job_dates as jd  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else '  -- ' + str(detail)}")
    if not ok:
        FAILS.append(name)


def types(conflicts):
    return [c["type"] for c in conflicts]


CREW = {
    "travel": [["2026-10-11", "2026-10-11"]],
    "prep": [["2026-10-12", "2026-10-12"]],
    "shoot": [["2026-10-13", "2026-10-15"]],
    "wrap": [],
    "travel_out": [["2026-10-16", "2026-10-16"]],
}

print("\nDate lines — the shared cases the front end checks too")
cases = json.loads((Path(__file__).parent / "date_line_cases.json").read_text())["cases"]
for c in cases:
    got = jd.format_line(c["type"], *c["span"])
    check(f"{c['line']!r}", got == c["line"], f"got {got!r}")

print("\nEffective dates: missing key = same as crew, empty list = none")
eff = jd.effective_dates(CREW, {})
check("no override follows the crew exactly", eff == {**{t: [] for t in jd.DAY_TYPES}, **CREW}, eff)
eff = jd.effective_dates(CREW, {"travel": []})
check("an empty list is 'none' — a local hire with no travel day", eff["travel"] == [])
check("...and everything else still follows the crew", eff["shoot"] == CREW["shoot"])
eff = jd.effective_dates(CREW, {"shoot": [["2026-10-13", "2026-10-13"], ["2026-10-15", "2026-10-15"]]})
check("two separate shoot blocks are kept as two", len(eff["shoot"]) == 2)

print("\nTalent keep their own schedule")
check("crew follow every crew date", jd.base_dates(CREW, "crew") == CREW)
check("no kind (before talent_hires.sql) reads as crew", jd.base_dates(CREW, None) == CREW)
check("talent follow nothing", jd.base_dates(CREW, "talent") == {})
check("hire_base reads the job and the hire's kind", jd.hire_base({"crew_dates": CREW}, {"kind": "talent"}) == {})
eff = jd.effective_dates(jd.base_dates(CREW, "talent"), {})
check("a talent with no dates has none", all(eff[t] == [] for t in jd.DAY_TYPES))
td = jd.talent_dates(["2026-10-13"])
check("one shoot day: in the day before, out the day after",
      (td["travel"], td["shoot"], td["travel_out"]) == ([["2026-10-12", "2026-10-12"]], [["2026-10-13", "2026-10-13"]],
                                                          [["2026-10-14", "2026-10-14"]]), td)
td = jd.talent_dates(["2026-10-15", "2026-10-13", "2026-10-14"])
check("consecutive days are one block", td["shoot"] == [["2026-10-13", "2026-10-15"]] and td["off"] == [])
td = jd.talent_dates(["2026-10-13", "2026-10-16"])
check("a gap stays: down days between, not a trip home", td["off"] == [["2026-10-14", "2026-10-15"]]
      and td["shoot"] == [["2026-10-13", "2026-10-13"], ["2026-10-16", "2026-10-16"]], td)
check("every type is set, so nothing reads as 'same as crew'", set(td) == set(jd.DAY_TYPES))
check("no days, no dates", jd.talent_dates([]) == {})
check("the result is valid stored dates", jd.validate_dates(td) == {k: v for k, v in td.items()})
check("a talent on a shoot day or a fitting goes on that day's list; travel doesn't",
      jd.talent_on_day(td, "2026-10-13") and not jd.talent_on_day(td, "2026-10-12")
      and jd.talent_on_day({"prep": [["2026-10-11", "2026-10-11"]]}, "2026-10-11"))
talent = {"kind": "talent", "dates_override": jd.talent_dates(["2026-10-13"])}
check("talent coming and going isn't a conflict", jd.conflicts_for(CREW, talent) == [])
check("a talent shooting a day the crew doesn't is",
      [c["type"] for c in jd.conflicts_for(CREW, {"kind": "talent", "dates_override": jd.talent_dates(["2026-10-20"])})] == ["shoot"])
check("crew still get the crew rule", jd.conflicts_for(CREW, {"dates_override": {}}) == [])
block = jd.dates_block({}, jd.talent_dates(["2026-10-13", "2026-10-15"]), kind="talent")
check("a talent's down day prints without the crew's half rate", "Down day (no shoot)" in block and "½" not in block, block)
check("a talent's prep date prints as a fitting",
      "Fitting" in jd.dates_block({}, {"prep": [["2026-10-12", "2026-10-12"]]}, kind="talent"))

print("\nPeople following the crew dates are never flagged")
moved = {**CREW, "shoot": [["2026-10-07", "2026-10-10"]]}
check("no override, crew moved: nothing flagged", jd.find_conflicts(moved, {}) == [])
check("no override, nonsense crew dates: still nothing", jd.find_conflicts(
    {"prep": [["2026-10-20", "2026-10-20"]], "shoot": [["2026-10-01", "2026-10-01"]]}, {}) == [])

print("\nThe rules")
# His own travel and prep: in two days early to prep ahead of the crew.
marcus = {"travel": [["2026-10-09", "2026-10-09"]], "prep": [["2026-10-10", "2026-10-12"]]}
check("arriving two days early to prep is never flagged", jd.find_conflicts(CREW, marcus) == [],
      jd.find_conflicts(CREW, marcus))
far = {**CREW, "shoot": [["2026-10-01", "2026-10-04"]], "travel": [["2026-09-30", "2026-09-30"]],
       "prep": [], "wrap": [], "travel_out": [["2026-10-05", "2026-10-05"]]}
c = jd.find_conflicts(far, marcus)
check("the crew moves a week earlier and his dates stay: adrift, flagged", {"travel", "prep"} <= set(types(c)), c)
check("...with the one-line reason", any(x["reason"] == "Days away from the rest of the job" for x in c), c)
c = jd.find_conflicts(CREW, {"shoot": [["2026-10-12", "2026-10-13"]]})
check("shooting on the crew's prep day is fine — prep then shoot is a real day", c == [], c)
c = jd.find_conflicts(CREW, {"shoot": [["2026-10-17", "2026-10-17"]]})
check("shooting on a day the crew has nothing at all is flagged", "shoot" in types(c), c)

print("\nWhat the producer's real schedules do — never flagged")
# Travel · Prep · Shoot A · Shoot A · Prep · Shoot B · Travel/Wrap
JOB = {"travel": [["2026-08-23", "2026-08-23"]],
       "prep": [["2026-08-24", "2026-08-24"], ["2026-08-27", "2026-08-27"]],
       "shoot": [["2026-08-25", "2026-08-26"], ["2026-08-28", "2026-08-28"]],
       "wrap": [["2026-08-29", "2026-08-29"]]}
check("someone on her own shoot days, following the crew's two preps (one mid-job)",
      jd.find_conflicts(JOB, {"shoot": [["2026-08-25", "2026-08-26"]]}) == [])
check("someone who flies home early (wrap mid-job, on a crew day)",
      jd.find_conflicts(JOB, {"wrap": [["2026-08-26", "2026-08-26"]], "shoot": [["2026-08-25", "2026-08-25"]]}) == [])
check("someone who flies in a day early",
      jd.find_conflicts(JOB, {"travel": [["2026-08-22", "2026-08-22"]]}) == [])
check("someone who leaves a day late",
      jd.find_conflicts(JOB, {"wrap": [["2026-08-30", "2026-08-30"]]}) == [])
check("a travel day mid-job, on a crew working day",
      jd.find_conflicts(JOB, {"travel": [["2026-08-23", "2026-08-23"], ["2026-08-27", "2026-08-27"]],
                              "prep": [["2026-08-24", "2026-08-24"]]}) == [])
check("prep two days before anyone arrives is fine — an early start",
      jd.find_conflicts(JOB, {"prep": [["2026-08-21", "2026-08-21"]]}) == [])
check("prep a week before anyone arrives is flagged",
      "prep" in types(jd.find_conflicts(JOB, {"prep": [["2026-08-16", "2026-08-16"]]})))

print("\nOverlaps")
check("travel and prep on the same day is fine — fly in and prep",
      jd.find_conflicts(CREW, {"prep": [["2026-10-10", "2026-10-12"]], "travel": [["2026-10-11", "2026-10-11"]]}) == [])
check("shoot and wrap on the same day is fine — shoot, then fly out (B1's 'flying home early' edit)",
      jd.find_conflicts({"shoot": [["2026-10-20", "2026-10-22"]], "wrap": [["2026-10-23", "2026-10-23"]]},
                        {"wrap": [["2026-10-22", "2026-10-22"]]}) == [])
c = jd.find_conflicts(CREW, {"shoot": [["2026-10-13", "2026-10-14"], ["2026-10-14", "2026-10-15"]]})
check("two shoot blocks overlapping each other are flagged", types(c) == ["shoot"], c)

check("no crew dates at all: only overlaps can fire",
      jd.find_conflicts({}, {"prep": [["2026-10-20", "2026-10-20"]]}) == [])

print("\nMove with the crew")
check("the crew moving its shoot back six days is a shift of -6",
      jd.crew_shift_days(CREW, moved) == -6, jd.crew_shift_days(CREW, moved))
check("no dates on either side is no shift", jd.crew_shift_days({}, CREW) == 0)
shifted = jd.shift_dates(marcus, -6)
check("custom days shift by the same number of days",
      shifted == {"travel": [["2026-10-03", "2026-10-03"]], "prep": [["2026-10-04", "2026-10-06"]]}, shifted)
# A real move takes the whole schedule with it, not just the shoot.
whole_move = jd.shift_dates(CREW, -6)
check("...and after Move with the crew, they fit again", jd.find_conflicts(whole_move, shifted) == [],
      jd.find_conflicts(whole_move, shifted))
check("'none' stays none after a shift, never back to 'same as crew'",
      jd.shift_dates({"travel": []}, 3) == {"travel": []})

print("\nShape checks on what the API accepts")
try:
    jd.validate_dates({"lunch": []})
    check("an unknown day type is refused", False)
except jd.DatesError:
    check("an unknown day type is refused", True)
try:
    jd.validate_dates({"shoot": [["2026-13-01", "2026-13-02"]]})
    check("a date that isn't one is refused", False)
except jd.DatesError:
    check("a date that isn't one is refused", True)
check("a backwards span is put the right way round",
      jd.validate_dates({"shoot": [["2026-10-15", "2026-10-13"]]}) == {"shoot": [["2026-10-13", "2026-10-15"]]})
check("an empty list survives — it means 'none'", jd.validate_dates({"travel": []}) == {"travel": []})

print("\nDashboard date span")
check("from the crew dates when there are any",
      jd.date_span(CREW, ["2026-01-01"]) == ("2026-10-11", "2026-10-16"))
check("else first-to-last day", jd.date_span({}, ["2026-10-14", None, "2026-10-12"]) == ("2026-10-12", "2026-10-14"))
check("nothing at all is None", jd.date_span({}, [None]) is None)

print("\nOld free-text lines → structured (the opt-in conversion)")
ref = date(2026, 10, 12)
check("a picker-written single day", jd.parse_legacy_line("Oct 11th - Sun - Travel in", ref)
      == ("travel", "2026-10-11", "2026-10-11"))
check("a picker-written range", jd.parse_legacy_line("Oct 13th (Tue) – Oct 15th (Thu) - Shoot day", ref)
      == ("shoot", "2026-10-13", "2026-10-15"))
check("The producer's own hand: 'Aug 24th - Mon - check in' is a check-in, not travel (Q2: paid differently)",
      jd.parse_legacy_line("Aug 24th - Mon - check in", date(2026, 8, 1)) == ("checkin", "2026-08-24", "2026-08-24"))
check("a check-in that says travel is still a travel day",
      jd.parse_legacy_line("Aug 24th - Mon - Travel in / check in", date(2026, 8, 1))[0] == "travel")
check("The producer's 'down day – ½ day rate' is a down day",
      jd.parse_legacy_line("Aug 26th - Wed - down day – ½ day rate", date(2026, 8, 1)) == ("off", "2026-08-26", "2026-08-26"))
check("the old combined 'Wrap/Travel out' reads as travel out — what it meant for most people",
      jd.parse_legacy_line("Oct 16th - Fri - Wrap/Travel out", ref)[0] == "travel_out")
check("'Travel Day - flies out' is travel out, not travel in",
      jd.parse_legacy_line("Aug 29th - Sat - Travel Day - Susan flies out", date(2026, 8, 1))[0] == "travel_out")
check("a wrap that doesn't mention leaving is a wrap day",
      jd.parse_legacy_line("Oct 17th - Sat - Wrap day, return props", ref)[0] == "wrap")
check("the year comes from the job, and a year-end span stays forward in time",
      jd.parse_legacy_line("Dec 31st (Thu) – Jan 2nd (Sat) - Shoot day", date(2026, 12, 20))
      == ("shoot", "2026-12-31", "2027-01-02"))
check("free prose is not guessed at", jd.parse_legacy_line("whole week, TBC with agent", ref) is None)
override, unparsed = jd.parse_legacy_text(
    ["Oct 11th - Sun - Travel in\nOct 13th (Tue) – Oct 15th (Thu) - Shoot day\nhotel TBC",
     "Oct 11th - Sun - Travel in"], ref)
check("every type is set once anything parsed — the old block was the whole story",
      set(override) == set(jd.DAY_TYPES) and override["prep"] == [] and override["wrap"] == [], override)
check("the same line on two days is read once", override["travel"] == [["2026-10-11", "2026-10-11"]])
check("what can't be read is reported, not dropped", unparsed == ["hotel TBC"], unparsed)
check("nothing readable leaves no override at all", jd.parse_legacy_text(["TBC"], ref) == ({}, ["TBC"]))

print("\nDown days and check-ins on the memo")
block = jd.dates_block({"travel": [["2026-08-24", "2026-08-24"]], "shoot": [["2026-08-25", "2026-08-25"], ["2026-08-27", "2026-08-27"]],
                        "off": [["2026-08-26", "2026-08-26"]]},
                       {"travel": [], "checkin": [["2026-08-24", "2026-08-24"]]})
check("a down day sits between the shoot days, in the producer's words", block.splitlines() == [
    "Aug 24th - Mon - Check into hotel (no travel)",
    "Aug 25th - Tue - Shoot day",
    "Aug 26th - Wed - Down day – ½ day rate",
    "Aug 27th - Thu - Shoot day",
], block)
check("a job that never uses them reads exactly as before",
      "Down day" not in jd.dates_block(CREW, {}) and "Check" not in jd.dates_block(CREW, {}))

print("\nWho's working a day")
mine = jd.effective_dates({"shoot": [["2026-08-25", "2026-08-27"]], "off": [["2026-08-26", "2026-08-26"]]},
                          {"checkin": [["2026-08-24", "2026-08-24"]]})
check("a shoot day is a working day", jd.works_on(mine, "2026-08-25"))
check("a down day is not, even inside a shoot span's dates", not jd.works_on(
    {"off": [["2026-08-26", "2026-08-26"]]}, "2026-08-26"))
check("a check-in is not", not jd.works_on(mine, "2026-08-24"))

print("\nDay labels and day notes (the producer's 'Brand A Shoot Day - Studio, NJ')")
JOB_DATES = {"travel": [["2026-08-24", "2026-08-24"]], "shoot": [["2026-08-25", "2026-08-27"]],
             "travel_out": [["2026-08-28", "2026-08-28"]]}
plain = jd.dates_block(JOB_DATES, {})
check("no labels and no notes: exactly the old block, spans unsplit",
      plain == jd.dates_block(JOB_DATES, {}, {}, {}) and "Aug 25th (Tue) – Aug 27th (Thu) - Shoot day" in plain, plain)
labels = {"2026-08-25": "Brand A – Studio, NJ", "2026-08-26": "Brand A – Studio, NJ", "2026-08-27": "Brand B – NYC",
          "2026-08-24": "should not print on travel"}
block = jd.dates_block(JOB_DATES, {}, labels, {"2026-08-24": "already in town"})
check("a span splits only where the label changes; matching days stay one line", block.splitlines() == [
    "Aug 24th - Mon - Travel in - already in town",
    "Aug 25th (Tue) – Aug 26th (Wed) - Shoot day - Brand A – Studio, NJ",
    "Aug 27th - Thu - Shoot day - Brand B – NYC",
    "Aug 28th - Fri - Travel out",
], block)
check("a label never prints on a travel line", "should not print" not in block)
two = jd.dates_block({"travel": [["2026-08-24", "2026-08-24"]], "shoot": [["2026-08-24", "2026-08-24"]]}, {},
                     {}, {"2026-08-24": "early call"})
check("a note prints once, on its date's first line", two.count("early call") == 1 and
      two.splitlines()[0].endswith("Travel in - early call"), two)
days = jd.person_days(JOB_DATES, {"travel": []}, labels, {"2026-08-25": "x"})
check("person_days lists each date once, in order, with its label and note",
      [d["date"] for d in days] == ["2026-08-25", "2026-08-26", "2026-08-27", "2026-08-28"]
      and days[0]["label"] == "Brand A – Studio, NJ" and days[0]["note"] == "x" and days[3]["label"] is None, days)
check("validation trims, drops blanks and refuses non-dates",
      jd.validate_day_text({"2026-08-25": "  Brand   A ", "2026-08-26": "  "}) == {"2026-08-25": "Brand A"})
try:
    jd.validate_day_text({"Aug 25": "x"})
    check("a key that isn't a date is refused", False)
except jd.DatesError:
    check("a key that isn't a date is refused", True)

print("\nThe deal memo Dates block")
block = jd.dates_block(CREW, {"travel": [], "shoot": [["2026-10-13", "2026-10-13"], ["2026-10-15", "2026-10-15"]]})
check("in the order the job happens, one line per span", block.splitlines() == [
    "Oct 12th - Mon - Prep/Scout",
    "Oct 13th - Tue - Shoot day",
    "Oct 15th - Thu - Shoot day",
    "Oct 16th - Fri - Travel out",
], block)
block = jd.dates_block(CREW, {"wrap": [["2026-10-16", "2026-10-16"]], "travel_out": [["2026-10-17", "2026-10-17"]]})
check("a stylist's wrap day, then travel out, each on its own line", block.splitlines()[-2:] == [
    "Oct 16th - Fri - Wrap day",
    "Oct 17th - Sat - Travel out",
], block)

print()
print("ALL PASS" if not FAILS else f"{len(FAILS)} FAILURES: " + ", ".join(FAILS))
sys.exit(1 if FAILS else 0)
