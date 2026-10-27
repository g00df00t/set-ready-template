"""One definition of "the same person".

    cd backend && venv/bin/python tests/test_person_match.py

The cases are drawn from real production data (2026-09-05), because the
counter-intuitive rule -- contact details decide, the name only corroborates --
was derived from it and would otherwise look arbitrary.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.person_match import find, Verdict  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else '  -- ' + detail}")
    if not ok:
        FAILS.append(name)


def E(id, name, email=None, phone=None):
    return {"id": id, "name": name, "email": email, "phone": phone}


PAT = E("r1", "Pat", "pat@example.com", "5550149544")

print("\nContact details decide, whatever the name says")
m = find({"name": "Pat Kehoe", "email": "pat@example.com"}, [PAT])
check("a different spelling still matches on email", m.verdict is Verdict.MATCH and m.entry["id"] == "r1")
check("and the spelling difference is reported", m.name_differs,
      "this is the drift the feature exists to fix; the caller has to be able to say so")
m = find({"name": "patrick kehoe", "phone": "+1 (555) 014-9544"}, [PAT])
check("a differently formatted phone still matches", m.verdict is Verdict.MATCH and m.entry["id"] == "r1")
check("this is the bug that made three copies of one producer",
      find({"name": "Pat Kehoe", "email": "pat@example.com"}, [PAT]).verdict is Verdict.MATCH,
      "ilike(name) saw Pat / Pat Kehoe / patrick kehoe as three people")

print("\nSharing a name is not sharing an identity")
dana_a = E("r2", "Dana Whitfield", "dana@studio.com", "3105550100")
cand = {"name": "Dana Whitfield", "email": "dana.whitfield@other.com", "phone": "3105559999"}
check("same name, contradicting details -> a different person",
      find(cand, [dana_a]).verdict is Verdict.NONE,
      "two real people do share names")

print("\nA name match is allowed only to fill a blank")
contactless = E("r3", "Dana Whitfield")
m = find({"name": "Dana Whitfield", "email": "dana@studio.com"}, [contactless])
check("matches an entry holding no contact details", m.verdict is Verdict.MATCH and m.entry["id"] == "r3")
check("and is marked as the weaker signal", m.by_name_only)
m = find({"name": "Dana Whitfield", "email": "dana@studio.com"}, [E("r4", "Dana Whitfield", phone="3105550100")])
check("a blank email beside a different phone is still fillable",
      m.verdict is Verdict.MATCH, "no contradiction: one field empty, the other untested")
check("but a contradicting phone blocks it",
      find({"name": "Dana Whitfield", "phone": "3105559999"},
           [E("r5", "Dana Whitfield", phone="3105550100")]).verdict is Verdict.NONE)

print("\nAmbiguity is an answer, not a coin toss")
# The real 2026-09-05 case: one producer's details reused across test personas.
personas = [PAT, E("r6", "Suki", "pat@example.com", "5550149544"),
            E("r7", "Mandy", "pat@example.com", "5550149544")]
m = find({"name": "Pat J Kehoe", "email": "pat@example.com"}, personas)
check("one contact identity across three entries -> AMBIGUOUS", m.verdict is Verdict.AMBIGUOUS)
check("every candidate is handed back so a human can choose", len(m.candidates) == 3)
check("no entry is picked", m.entry is None,
      "guessing here would have merged a producer, a stylist and a dog")
check("but an exact name inside that group resolves it",
      find({"name": "Suki", "email": "pat@example.com"}, personas).entry["id"] == "r6",
      "contact details establish a group; the name is what separates its members")
check("a name matching none of the group stays ambiguous",
      find({"name": "Someone Else", "email": "pat@example.com"}, personas).verdict
      is Verdict.AMBIGUOUS)

m = find({"name": "Dana Whitfield"}, [E("r8", "Dana Whitfield"), E("r9", "dana whitfield")])
check("two contactless entries with the same name -> AMBIGUOUS", m.verdict is Verdict.AMBIGUOUS)

print("\nNothing to go on")
check("no match at all", find({"name": "Nobody", "email": "n@x.com"}, [PAT]).verdict is Verdict.NONE)
check("an empty roster", find({"name": "Pat"}, []).verdict is Verdict.NONE)
check("a candidate with no name and no contact details",
      find({"name": "", "email": None, "phone": None}, [PAT]).verdict is Verdict.NONE)
check("a nameless candidate does not match a nameless entry",
      find({"name": "  "}, [E("r10", "")]).verdict is Verdict.NONE,
      "two blanks are not the same person")

print("\nShort or junk phone numbers never join two people")
check("a 3-digit 'phone' is ignored",
      find({"name": "X", "phone": "555"}, [E("r11", "Y", phone="555")]).verdict is Verdict.NONE)
check("an empty email is not a shared identity",
      find({"name": "X", "email": ""}, [E("r12", "Y", email="")]).verdict is Verdict.NONE)

print()
print("ALL PASS" if not FAILS else f"{len(FAILS)} FAILURES: " + ", ".join(FAILS))
sys.exit(1 if FAILS else 0)
