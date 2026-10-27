"""Roster <-> project syncing.

    cd backend && venv/bin/python tests/test_roster_sync.py

Uses a fake Supabase client rather than a database, so the rule that matters most
-- a wrapped job is never touched -- is tested directly instead of being hoped
for. Getting that wrong would silently rewrite a shoot that already happened.
"""

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.roster_sync import (  # noqa: E402
    person_updates, unwrapped_project_ids, propagate_from_roster, write_back_to_roster,
)

FAILS = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else '  -- ' + detail}")
    if not ok:
        FAILS.append(name)


YESTERDAY = (date.today() - timedelta(days=1)).isoformat()
TOMORROW = (date.today() + timedelta(days=1)).isoformat()
TODAY = date.today().isoformat()


class FakeTable:
    def __init__(self, db, name):
        self.db, self.name, self.filters, self._update = db, name, {}, None

    def select(self, *_a, **_k): return self
    def eq(self, k, v): self.filters[k] = v; return self
    def in_(self, k, vs): self.filters[k] = ("in", vs); return self

    def update(self, changes): self._update = changes; return self

    def _matches(self, row):
        for k, v in self.filters.items():
            if isinstance(v, tuple) and v[0] == "in":
                if row.get(k) not in v[1]: return False
            elif row.get(k) != v:
                return False
        return True

    def execute(self):
        rows = [r for r in self.db[self.name] if self._matches(r)]
        if self._update is not None:
            for r in rows:
                r.update(self._update)
            self.db["_writes"].append((self.name, dict(self._update), len(rows)))
        return type("R", (), {"data": [dict(r) for r in rows]})


class FakeClient:
    def __init__(self, db): self.db = db
    def table(self, name): return FakeTable(self.db, name)


def make_db():
    return {
        "_writes": [],
        # A hire is the person on a Job; its job is open while any day is still to come, or it has none.
        "job_hires": [
            {"id": "h_open", "job_id": "j_open", "roster_id": "r1", "phone": "old"},
            {"id": "h_done", "job_id": "j_done", "roster_id": "r1", "phone": "old"},
            {"id": "h_new", "job_id": "j_new", "roster_id": "r1", "phone": "old"},
            {"id": "h_else", "job_id": "j_open", "roster_id": "r2", "phone": "old"},
        ],
        "projects": [
            {"id": "p_open", "owner_id": "o1", "shoot_date": TOMORROW, "job_id": "j_open"},
            {"id": "p_today", "owner_id": "o1", "shoot_date": TODAY},
            {"id": "p_wrapped", "owner_id": "o1", "shoot_date": YESTERDAY, "job_id": "j_done"},
            {"id": "p_nodate", "owner_id": "o1", "shoot_date": None},
            {"id": "p_other", "owner_id": "o2", "shoot_date": TOMORROW},
        ],
        "crew_members": [
            {"id": "c1", "project_id": "p_open", "roster_id": "r1", "phone": "old"},
            {"id": "c2", "project_id": "p_wrapped", "roster_id": "r1", "phone": "old"},
            {"id": "c3", "project_id": "p_nodate", "roster_id": "r1", "phone": "old"},
            {"id": "c4", "project_id": "p_open", "roster_id": None, "phone": "old"},
            {"id": "c5", "project_id": "p_other", "roster_id": "r1", "phone": "old"},
        ],
        "talent": [], "project_contacts": [],
        "call_sheets": [{"project_id": "p_open"}],
        "roster": [{"id": "r1", "owner_id": "o1", "name": "Pat", "phone": "old"}],
    }


print("\nOnly person fields sync -- job fields stay with the job")
check("name, email and phone pass through",
      person_updates({"name": "Pat", "email": "p@x.com", "phone": "310"})
      == {"name": "Pat", "email": "p@x.com", "phone": "310"})
check("role and department do not",
      person_updates({"role": "Gaffer", "department": "G&E", "phone": "310"}) == {"phone": "310"})
check("call time does not", person_updates({"call_time": "06:30", "name": "Pat"}) == {"name": "Pat"})
check("day rate never syncs to a job row",
      person_updates({"phone": "310", "day_rate": "650", "rate_note": "10hr"}) == {"phone": "310"},
      "crew_members/talent/project_contacts have no rate column — this filter "
      "is the only thing keeping a rate off a call sheet")
check("agency fields do not sync either",
      person_updates({"phone": "310", "agency": "CAA", "agent_name": "Sam",
                      "agent_email": "sam@caa.com", "agent_phone": "555"}) == {"phone": "310"})
check("a blank is not a correction and is ignored",
      person_updates({"phone": "   ", "email": ""}) == {},
      "clearing a phone on one job must not wipe it from the address book")
check("None is ignored", person_updates({"phone": None}) == {})

print("\nWhich projects count as still open")
ids = unwrapped_project_ids(FakeClient(make_db()), "o1")
check("a future shoot is open", "p_open" in ids)
check("a shoot TODAY is still open", "p_today" in ids, "the job has not happened yet")
check("a past shoot is wrapped", "p_wrapped" not in ids)
check("no shoot date counts as open", "p_nodate" in ids, "a project still being built")
check("another producer's project is never included", "p_other" not in ids)

print("\nPropagation reaches open jobs and stops at wrapped ones")
db = make_db()
res = propagate_from_roster(FakeClient(db), "r1", "o1", {"phone": "new", "role": "ignored"})
rows = {r["id"]: r["phone"] for r in db["crew_members"]}
check("an open project is updated", rows["c1"] == "new")
check("a project with no date is updated", rows["c3"] == "new")
check("a WRAPPED project is left alone", rows["c2"] == "old",
      "correcting a number must not reach back into a finished shoot")
check("an unlinked row is left alone", rows["c4"] == "old")
check("another producer's row is untouched", rows["c5"] == "old")
check("the job field was not written", all("role" not in w[1] for w in db["_writes"]))
check("counts reported", res["rows_updated"] == 2 and res["projects_updated"] == 2,
      str(res))
check("stale sheets counted so the caller can say so", res["sheets_now_stale"] == 1,
      f"p_open has a stored sheet; got {res}")

print("\nHires follow the Roster too")
db = make_db()
res = propagate_from_roster(FakeClient(db), "r1", "o1", {"phone": "555-0142"})
h = {r["id"]: r["phone"] for r in db["job_hires"]}
check("a hire on a job with a day still to come gets the correction", h["h_open"] == "555-0142", str(h))
check("so does one on a job with no days yet", h["h_new"] == "555-0142", str(h))
check("a hire on a finished job is left alone", h["h_done"] == "old", str(h))
check("someone else's hire is untouched", h["h_else"] == "old", str(h))
check("and the count says so", res["hires_updated"] == 2, str(res))
db = make_db()
propagate_from_roster(FakeClient(db), "r1", "o1", {"phone": ""})
check("a blank is still not a correction, for hires either", db["job_hires"][0]["phone"] == "old")
db = make_db()
del db["job_hires"]
res = propagate_from_roster(FakeClient(db), "r1", "o1", {"phone": "new"})
check("no job tables (before the Jobs migration): day rows still sync", res["rows_updated"] > 0 and res["hires_updated"] == 0, str(res))

print("\nNothing to do is not an error")
db = make_db()
res = propagate_from_roster(FakeClient(db), "r1", "o1", {"role": "Gaffer"})
check("job-field-only edit writes nothing",
      res == {"rows_updated": 0, "projects_updated": 0, "sheets_now_stale": 0, "hires_updated": 0} and not db["_writes"])
db = make_db()
res = propagate_from_roster(FakeClient(db), "r_unknown", "o1", {"phone": "new"})
check("an unknown roster id writes nothing", res["rows_updated"] == 0)

print("\nWrite-back, from a project row to the master record")
db = make_db()
ok = write_back_to_roster(FakeClient(db), "r1", "o1", {"phone": "corrected", "call_time": "06:30"})
check("the roster is updated", ok and db["roster"][0]["phone"] == "corrected")
check("the job field is not written to the roster", "call_time" not in db["roster"][0])
db = make_db()
check("another producer's roster entry is unreachable",
      not write_back_to_roster(FakeClient(db), "r1", "o2", {"phone": "x"})
      and db["roster"][0]["phone"] == "old",
      "a row must never reach into someone else's address book")
db = make_db()
check("a blank writes nothing", not write_back_to_roster(FakeClient(db), "r1", "o1", {"phone": "  "}))

print()
print("ALL PASS" if not FAILS else f"{len(FAILS)} FAILURES: " + ", ".join(FAILS))
sys.exit(1 if FAILS else 0)
