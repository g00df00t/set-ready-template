"""Who can open a shared wrap report, and who can't.

    cd backend && venv/bin/python tests/test_wrap_share.py

This is an access-control surface — an unauthenticated URL that returns a
producer's crew list — so the invariants are asserted with a fake Supabase
client rather than trusted to read correctly.

The three that matter: a revoked link stays dead, one producer's link never
opens another producer's shoot, and the public response never echoes the token
back out.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import HTTPException  # noqa: E402
from starlette.requests import Request  # noqa: E402

from routers import wrap_report as wr  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else '  -- ' + detail}")
    if not ok:
        FAILS.append(name)


class FakeTable:
    def __init__(self, db, name):
        self.db, self.name, self.f, self._in, self._u = db, name, {}, {}, None

    def select(self, *_a, **_k): return self
    def order(self, *_a, **_k): return self
    def insert(self, _c): return self
    def eq(self, k, v): self.f[k] = v; return self
    def in_(self, k, vs): self._in[k] = set(vs); return self
    def update(self, c): self._u = c; return self

    def execute(self):
        rows = [r for r in self.db.get(self.name, [])
                if all(r.get(k) == v for k, v in self.f.items())
                and all(r.get(k) in v for k, v in self._in.items())]
        if self._u is not None:
            for r in rows:
                r.update(self._u)
        return type("R", (), {"data": [dict(r) for r in rows]})


class FakeClient:
    def __init__(self, db): self.db = db
    def table(self, n): return FakeTable(self.db, n)


def make_db():
    return {
        "projects": [
            {"id": "p1", "owner_id": "producer-a", "name": "Ridgeline",
             "shoot_date": "2020-01-01", "wrap_share_token": None},
            {"id": "p2", "owner_id": "producer-b", "name": "Someone Else's Shoot",
             "shoot_date": "2020-01-01", "wrap_share_token": None},
        ],
        "crew_members": [], "talent": [], "schedule_items": [],
        "project_locations": [], "company_moves": [], "project_meals": [],
        "project_accommodations": [], "call_sheets": [], "call_sheet_attachments": [],
        "usage_events": [],
    }


db = make_db()
client = FakeClient(db)
wr.get_client = lambda: client

class Pid(str):
    """Stands in for the path's UUID. FastAPI hands the route a real UUID and
    every use inside is str(project_id), so a str subclass satisfies both while
    keeping the fake database's ids readable."""


def fake_request() -> Request:
    """slowapi insists on a real starlette Request before it will let the public
    route run, so give it the smallest one that scopes."""
    return Request({"type": "http", "method": "GET", "path": "/api/wrap/x",
                    "headers": [], "client": ("127.0.0.1", 0)})


print("\nMinting a link")
link1 = wr.create_share_link(Pid("p1"), owner_ids={"producer-a"}, write_owner_id="producer-a")
check("a link is created", bool(link1.url), str(link1.url))
token1 = db["projects"][0]["wrap_share_token"]
check("the token is stored on the project", bool(token1))
check("the url ends with the token", link1.url.endswith(token1))

print("\nClicking Share twice does not break the link already pasted in an email")
link2 = wr.create_share_link(Pid("p1"), owner_ids={"producer-a"}, write_owner_id="producer-a")
check("the same url comes back", link2.url == link1.url)

print("\nThe public route")
res = wr.shared_wrap_report(request=fake_request(), token=token1)
check("opens the right project", res.project_name == "Ridgeline")
check("and never echoes the token back", res.share_url is None,
      "the holder already has it; echoing invites it into logs")

print("\nRevoking")
wr.revoke_share_link(Pid("p1"), owner_ids={"producer-a"})
check("the token is cleared", db["projects"][0]["wrap_share_token"] is None)
try:
    wr.shared_wrap_report(request=fake_request(), token=token1)
    check("the old link is dead", False, "a revoked link still opened")
except HTTPException as e:
    check("the old link is dead", e.status_code == 404, f"got {e.status_code}")
    check("and says nothing about why", "revoke" not in str(e.detail).lower()
          and "Ridgeline" not in str(e.detail),
          "confirming the project exists to a holder of a dead URL")

print("\nRe-sharing mints a NEW token, so the revoked one stays dead")
link3 = wr.create_share_link(Pid("p1"), owner_ids={"producer-a"}, write_owner_id="producer-a")
check("a different url", link3.url != link1.url)

print("\nOne producer's link never reaches another producer's shoot")
try:
    wr.create_share_link(Pid("p2"), owner_ids={"producer-a"}, write_owner_id="producer-a")
    check("sharing someone else's project is refused", False, "it was allowed")
except HTTPException as e:
    check("sharing someone else's project is refused", e.status_code == 404)
try:
    wr.revoke_share_link(Pid("p2"), owner_ids={"producer-a"})
    check("revoking someone else's link is refused", False, "it was allowed")
except HTTPException as e:
    check("revoking someone else's link is refused", e.status_code == 404)

print("\nAn unknown token is a flat 404")
try:
    wr.shared_wrap_report(request=fake_request(), token="not-a-real-token")
    check("unknown token refused", False, "it returned a report")
except HTTPException as e:
    check("unknown token refused", e.status_code == 404)

print()
print(f"{len(FAILS)} FAILED: {', '.join(FAILS)}" if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
