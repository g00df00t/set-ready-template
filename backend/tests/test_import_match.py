"""Classifying a pasted call sheet against what already exists.

    cd backend && venv/bin/python tests/test_import_match.py

The scenario, verbatim from the producer who raised it: finding an old call sheet
and pasting the crew in, while already having some of those people in the roster
from another job.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.import_match import classify, ON_PROJECT, IN_ROSTER, AMBIGUOUS, NEW  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else '  -- ' + detail}")
    if not ok:
        FAILS.append(name)


CREW = [
    {"id": "c1", "name": "Dana Whitfield", "email": "dana@studio.com",
     "phone": "3105550100", "role": "Producer", "department": "Production"},
]
ROSTER = [
    {"id": "r1", "name": "Tomas Vance", "email": "tomas@example.com",
     "phone": "3105550102", "role": "DP", "department": "Camera"},
    {"id": "r2", "name": "Aisha Bello", "email": "aisha@example.com", "phone": None},
]

print("\nThe three ordinary outcomes")
rows = classify([
    {"name": "Dana Whitfield", "email": "dana@studio.com"},
    {"name": "Tomas Vance", "email": "tomas@example.com"},
    {"name": "Priya Anand", "email": "priya@example.com"},
], CREW, ROSTER)
check("already on this shoot", rows[0]["match_state"] == ON_PROJECT)
check("  ...defaults to skip, because adding again IS the duplicate", rows[0]["action"] == "skip")
check("in the roster but not on this shoot", rows[1]["match_state"] == IN_ROSTER)
check("  ...defaults to add", rows[1]["action"] == "add")
check("nobody we know", rows[2]["match_state"] == NEW and rows[2]["action"] == "add")

print("\nThe project is checked before the roster")
# Dana is on the shoot AND would be in the roster; on-project is the urgent fact.
rows = classify([{"name": "Dana Whitfield", "email": "dana@studio.com"}],
                CREW, CREW + ROSTER)
check("being on the shoot wins", rows[0]["match_state"] == ON_PROJECT)

print("\nA different spelling is still the same person")
rows = classify([{"name": "D. Whitfield", "phone": "+1 (310) 555-0100"}], CREW, ROSTER)
check("matched on the phone despite the name", rows[0]["match_state"] == ON_PROJECT)
check("and the filed name is returned so the producer can see why",
      rows[0]["match_name"] == "Dana Whitfield")

print("\nThe case worth building well: already here, but the details moved")
rows = classify([{"name": "Dana Whitfield", "email": "dana@studio.com",
                  "phone": "3105559999", "role": "Line Producer",
                  "department": "Production", "call_time": "07:00"}], CREW, ROSTER)
d = {x["field"]: x for x in rows[0]["differs"]}
check("the changed phone is reported", "phone" in d and d["phone"]["existing"] == "3105550100")
check("the changed role is reported", "role" in d)
check("the unchanged department is NOT reported", "department" not in d,
      "reporting every field would bury the real differences")
check("a field only the paste has is not a difference", "call_time" not in d,
      "missing information is not a contradiction")
check("still defaults to skip — the producer chooses to take the new values",
      rows[0]["action"] == "skip")

print("\nAmbiguity is passed through, never guessed")
twins = [{"id": "t1", "name": "Sam A", "email": "shared@example.com"},
         {"id": "t2", "name": "Sam B", "email": "shared@example.com"}]
rows = classify([{"name": "Someone Else", "email": "shared@example.com"}], [], twins)
check("two roster entries match -> ambiguous", rows[0]["match_state"] == AMBIGUOUS)
check("no id is chosen", rows[0]["match_id"] is None,
      "picking one would merge two people, and there is no undo")
check("defaults to add — a spare row beats a wrong merge", rows[0]["action"] == "add")

print("\nThin rows still behave")
rows = classify([{"name": "Nameless Contact"}, {"name": ""}], CREW, ROSTER)
check("a name with no contact details and no match is new", rows[0]["match_state"] == NEW)
check("a blank row is new, not a match", rows[1]["match_state"] == NEW)
rows = classify([], CREW, ROSTER)
check("nothing pasted, nothing returned", rows == [])
rows = classify([{"name": "Dana Whitfield", "email": "dana@studio.com"}], [], [])
check("an empty project and roster means everyone is new", rows[0]["match_state"] == NEW)

print("\nThe original row survives classification")
rows = classify([{"name": "Priya Anand", "role": "Gaffer", "call_time": "06:30"}], CREW, ROSTER)
check("pasted fields are preserved untouched",
      rows[0]["name"] == "Priya Anand" and rows[0]["role"] == "Gaffer"
      and rows[0]["call_time"] == "06:30")

print()
print("ALL PASS" if not FAILS else f"{len(FAILS)} FAILURES: " + ", ".join(FAILS))
sys.exit(1 if FAILS else 0)
