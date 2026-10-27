"""Merging two Roster entries into one.

    cd backend && venv/bin/python tests/test_roster_merge.py

A fake Supabase client, so the ordering that makes this safe is asserted rather
than assumed: repoint the project rows FIRST, then delete. The reverse leaves
rows pointing at an entry that no longer exists.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.roster_merge import merge_entries  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else '  -- ' + detail}")
    if not ok:
        FAILS.append(name)


class FakeTable:
    def __init__(self, db, name):
        self.db, self.name, self.f, self._u, self._del = db, name, {}, None, False

    def select(self, *_a, **_k): return self
    def eq(self, k, v): self.f[k] = v; return self
    def update(self, c): self._u = c; return self
    def delete(self): self._del = True; return self

    def _match(self, r): return all(r.get(k) == v for k, v in self.f.items())

    def execute(self):
        rows = [r for r in self.db[self.name] if self._match(r)]
        if self._u is not None:
            for r in rows:
                r.update(self._u)
            self.db["_log"].append(("update", self.name, len(rows)))
        if self._del:
            for r in rows:
                self.db[self.name].remove(r)
            self.db["_log"].append(("delete", self.name, len(rows)))
        return type("R", (), {"data": [dict(r) for r in rows]})


class FakeClient:
    def __init__(self, db): self.db = db
    def table(self, n): return FakeTable(self.db, n)


def make_db():
    return {
        "_log": [],
        "roster": [
            {"id": "keep", "owner_id": "o1", "name": "Pat Kehoe",
             "email": "pat@x.com", "phone": None, "role": "DP",
             "department": None, "organization": None},
            {"id": "drop", "owner_id": "o1", "name": "patrick kehoe",
             "email": "pat@x.com", "phone": "5550149544", "role": None,
             "department": "Camera", "organization": None},
            {"id": "other", "owner_id": "o2", "name": "Someone Else",
             "email": "s@x.com", "phone": None, "role": None,
             "department": None, "organization": None},
        ],
        "crew_members": [
            {"id": "c1", "roster_id": "drop"},
            {"id": "c2", "roster_id": "keep"},
            {"id": "c3", "roster_id": None},
        ],
        "talent": [{"id": "t1", "roster_id": "drop"}],
        "project_contacts": [],
    }


print("\nThe rows move, then the entry goes")
db = make_db()
res = merge_entries(FakeClient(db), "o1", "keep", ["drop"])
check("project rows repointed to the survivor",
      [r for r in db["crew_members"] if r["id"] == "c1"][0]["roster_id"] == "keep")
check("talent repointed too", db["talent"][0]["roster_id"] == "keep")
check("rows already on the survivor are untouched",
      [r for r in db["crew_members"] if r["id"] == "c2"][0]["roster_id"] == "keep")
check("unlinked rows are left alone",
      [r for r in db["crew_members"] if r["id"] == "c3"][0]["roster_id"] is None)
check("the merged entry is gone", [r for r in db["roster"] if r["id"] == "drop"] == [])
check("counts reported", res["repointed"] == 2 and res["deleted"] == 1, str(res))

print("\nOrdering is the safety property")
order = [step for step in db["_log"] if step[0] in ("update", "delete")]
first_delete = next((i for i, s in enumerate(order) if s[0] == "delete"), len(order))
repoints = [i for i, s in enumerate(order) if s[0] == "update" and s[1] != "roster"]
check("every repoint happens before any delete",
      all(i < first_delete for i in repoints),
      "deleting first would leave rows pointing at nothing")

print("\nBlanks are filled, real values are never overwritten")
db = make_db()
merge_entries(FakeClient(db), "o1", "keep", ["drop"])
keep = [r for r in db["roster"] if r["id"] == "keep"][0]
check("the survivor gains a phone it did not have", keep["phone"] == "5550149544")
check("the survivor gains a department", keep["department"] == "Camera")
check("its own role is NOT overwritten", keep["role"] == "DP",
      "the producer chose which entry survives; its values are the answer")
check("its own email is kept", keep["email"] == "pat@x.com")
check("the survivor's name is never changed by a merge", keep["name"] == "Pat Kehoe")

print("\nAnother producer's roster is unreachable")
db = make_db()
try:
    merge_entries(FakeClient(db), "o1", "keep", ["other"])
    check("merging someone else's entry is refused", False, "it went through")
except ValueError:
    check("merging someone else's entry is refused", True)
check("and that entry still exists", any(r["id"] == "other" for r in db["roster"]))
db = make_db()
try:
    merge_entries(FakeClient(db), "o2", "keep", ["drop"])
    check("a survivor you do not own is refused", False, "it went through")
except ValueError:
    check("a survivor you do not own is refused", True)

print("\nDegenerate input does nothing")
db = make_db()
check("merging an entry into itself", merge_entries(FakeClient(db), "o1", "keep", ["keep"])["deleted"] == 0)
check("an empty list", merge_entries(FakeClient(db), "o1", "keep", [])["deleted"] == 0)
check("nothing was deleted", len(db["roster"]) == 3)

print()
print("ALL PASS" if not FAILS else f"{len(FAILS)} FAILURES: " + ", ".join(FAILS))
sys.exit(1 if FAILS else 0)
