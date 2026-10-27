"""The call sheet says "Day 2 of 4" only for someone on Jobs.

    cd backend && venv/bin/python tests/test_day_label_beta.py

Everyone's Duplicate joins the source's job (plan §6), so before this the
label reached accounts that never opted in: found on production on
2026-10-01, when a duplicated one-day test project's sheet said "Day 2 of 2"
on an account without the flag. A shoot reused as a template would have told
its crew the same thing. The flag is read for whoever is acting, the same as
the screens.

Calls the helpers directly against tests/fake_supabase.py.
"""

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.fake_supabase import FakeClient  # noqa: E402
from routers import call_sheet  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else '  -- ' + str(detail)}")
    if not ok:
        FAILS.append(name)


DB = {
    "jobs": [{"id": "j1", "crew_dates": {}}],
    "projects": [
        {"id": "d1", "name": "Northwind", "job_id": "j1", "shoot_date": "2026-10-08", "created_at": "2026-10-01T10:00:00"},
        {"id": "d2", "name": "Northwind", "job_id": "j1", "shoot_date": None, "created_at": "2026-10-01T11:00:00"},
        {"id": "solo", "name": "Solo", "job_id": None, "shoot_date": "2026-10-08", "created_at": "2026-10-01T09:00:00"},
    ],
}
DAY2 = DB["projects"][1]


def client(beta_users=()):
    c = FakeClient(DB)
    c.users = {"on": {"beta_jobs": True}, "off": {"beta_jobs": False}, "never": {}}
    for u in beta_users:
        c.users[u] = {"beta_jobs": True}
    return c


print("Day N of M follows the acting person's Jobs flag")
c = client()
check("on Jobs: a two-day job's second day is Day 2 of 2",
      call_sheet._day_label(c, DAY2, "on") == "Day 2 of 2", call_sheet._day_label(c, DAY2, "on"))
check("switched off: no label", call_sheet._day_label(c, DAY2, "off") is None)
check("never opted in: no label", call_sheet._day_label(c, DAY2, "never") is None)
check("a project with no job: no label, even on Jobs",
      call_sheet._day_label(c, DB["projects"][2], "on") is None)

print("The email subject and texts follow the same rule")
check("on Jobs: subject carries the day", call_sheet._sheet_title(c, DAY2, "on") == "Northwind · Day 2 of 2",
      call_sheet._sheet_title(c, DAY2, "on"))
check("not on Jobs: subject is just the name", call_sheet._sheet_title(c, DAY2, "never") == "Northwind",
      call_sheet._sheet_title(c, DAY2, "never"))


class Broken(FakeClient):
    """The flag can't be read: the sheet must still generate, unlabelled."""
    def __init__(self, db):
        super().__init__(db)
        def boom(uid):
            raise RuntimeError("auth admin down")
        self.auth.admin.get_user_by_id = boom


print("An unreadable flag counts as off")
check("no label, no exception", call_sheet._day_label(Broken(DB), DAY2, "on") is None)
check("subject still renders", call_sheet._sheet_title(Broken(DB), DAY2, "on") == "Northwind")

print("Every route that labels a sheet knows who is acting")
for fn in (call_sheet.generate, call_sheet.send, call_sheet.remind, call_sheet.text_nudges):
    check(f"{fn.__name__} takes user_id", "user_id" in inspect.signature(fn).parameters)

if FAILS:
    print(f"\n{len(FAILS)} FAILED")
    sys.exit(1)
print("\nALL PASS")
