"""Finding probable duplicates in a Roster.

    cd backend && venv/bin/python tests/test_roster_duplicates.py

The transitive case is the one that matters: A shares an email with B, B shares a
phone with C. Treating that as two pairs means merging A into B leaves C behind,
still a duplicate and now harder to see.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.roster_duplicates import find_duplicate_groups, BY_CONTACT, BY_NAME  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else '  -- ' + detail}")
    if not ok:
        FAILS.append(name)


def E(i, name, email=None, phone=None):
    return {"id": i, "name": name, "email": email, "phone": phone}


print("\nA clean roster has nothing to report")
check("no duplicates found", find_duplicate_groups([
    E("1", "Dana Whitfield", "dana@x.com", "3105550100"),
    E("2", "Tomas Vance", "tomas@x.com", "3105550102"),
]) == [])
check("an empty roster", find_duplicate_groups([]) == [])
check("a single entry", find_duplicate_groups([E("1", "Solo", "s@x.com")]) == [])

print("\nA shared email or phone groups people")
g = find_duplicate_groups([
    E("1", "Pat", "pat@x.com", "5550149544"),
    E("2", "Pat Kehoe", "pat@x.com", None),
])
check("one group", len(g) == 1)
check("both entries in it", len(g[0]["entries"]) == 2)
check("reason is the shared contact", g[0]["reason"] == BY_CONTACT)
check("and it says WHAT they share", "pat@x.com" in g[0]["shared"],
      "a producer has to see the evidence, not just the verdict")

print("\nOverlapping links collapse into ONE group, not several pairs")
# A--email--B, B--phone--C: one person in three records.
g = find_duplicate_groups([
    E("a", "Pat",         "pat@x.com", None),
    E("b", "Pat Kehoe",   "pat@x.com", "5550149544"),
    E("c", "P. Kehoe",    None,        "5550149544"),
])
check("a single group of three", len(g) == 1 and len(g[0]["entries"]) == 3,
      f"got {[len(x['entries']) for x in g]} — merging a pair would strand the third")

print("\nThe real 2026-09-05 shape: one contact identity, six records")
personas = [E(str(i), n, "pat@example.com", "5550149544")
            for i, n in enumerate(["Pat", "Pat Kehoe", "patrick kehoe", "Mandy", "DALE", "Suki"])]
g = find_duplicate_groups(personas)
check("all six in one group", len(g) == 1 and len(g[0]["entries"]) == 6)
check("flagged as a question, with the shared values attached",
      g[0]["reason"] == BY_CONTACT and len(g[0]["shared"]) == 2,
      "these were NOT all the same person — a dog was among them")

print("\nSame name with nothing to confirm it is a weaker, separate signal")
g = find_duplicate_groups([E("1", "Dana Whitfield"), E("2", "dana whitfield")])
check("grouped", len(g) == 1 and len(g[0]["entries"]) == 2)
check("marked as the weaker reason", g[0]["reason"] == BY_NAME)
check("two people who merely share a name are NOT grouped",
      find_duplicate_groups([
          E("1", "Dana Whitfield", "dana@studio.com", "3105550100"),
          E("2", "Dana Whitfield", "dana.w@other.com", "3105559999"),
      ]) == [],
      "contradicting details mean different people, however alike the names")

print("\nA stronger reason wins; nobody is reported twice")
g = find_duplicate_groups([
    E("1", "Pat Kehoe", "pat@x.com", None),
    E("2", "Pat Kehoe", "pat@x.com", None),
])
check("one group only", len(g) == 1)
check("reported as the shared contact, not the name", g[0]["reason"] == BY_CONTACT)
ids = [e["id"] for grp in g for e in grp["entries"]]
check("no entry appears in two groups", len(ids) == len(set(ids)))

print("\nBiggest tangle first")
g = find_duplicate_groups([
    E("1", "A", "a@x.com"), E("2", "A2", "a@x.com"),
    E("3", "B", "b@x.com"), E("4", "B2", "b@x.com"), E("5", "B3", "b@x.com"),
])
check("the group of three is listed before the pair",
      len(g) == 2 and len(g[0]["entries"]) == 3 and len(g[1]["entries"]) == 2)

print("\nBlank values never join anyone")
check("empty email and phone are not a shared identity",
      find_duplicate_groups([E("1", "X", "", ""), E("2", "Y", "", "")]) == [])
check("a short junk phone is ignored",
      find_duplicate_groups([E("1", "X", None, "555"), E("2", "Y", None, "555")]) == [])

print()
print("ALL PASS" if not FAILS else f"{len(FAILS)} FAILURES: " + ", ".join(FAILS))
sys.exit(1 if FAILS else 0)
