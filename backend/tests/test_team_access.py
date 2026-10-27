"""Team-sharing access boundary.

    cd backend && venv/bin/python tests/test_team_access.py

The property that matters: an accepted team member reaches everything the
owner reaches; a non-member reaches none of it -- not a random producer, not a
revoked former member, not someone with only a pending (unaccepted) invite.
Uses a fake Supabase client, the same shape test_roster_sync.py and
test_wrap_share.py use, so the boundary is tested directly rather than hoped
for.

Phase 1 only builds the resolvers below (auth.py's get_accessible_owner_ids
and get_write_owner_id) plus every backend call site that now uses them --
not the self-serve /team/invites accept flow, which is Phase 2 per
docs/team-sharing-plan.md. So there's nothing here yet about matching an
invite's email to the accepting user; that boundary gets its own test when
that endpoint exists.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import auth  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else '  -- ' + detail}")
    if not ok:
        FAILS.append(name)


class FakeTable:
    def __init__(self, db, name):
        self.db, self.name, self.filters = db, name, {}

    def select(self, *_a, **_k): return self
    def eq(self, k, v): self.filters[k] = v; return self

    def execute(self):
        rows = [r for r in self.db[self.name]
                if all(r.get(k) == v for k, v in self.filters.items())]
        return type("R", (), {"data": [dict(r) for r in rows]})


class FakeClient:
    def __init__(self, db): self.db = db
    def table(self, name): return FakeTable(self.db, name)


def make_db():
    return {
        "team_members": [
            {"owner_id": "owner-a", "member_user_id": "member-x", "status": "accepted"},
            {"owner_id": "owner-b", "member_user_id": "member-y", "status": "pending"},
            {"owner_id": "owner-c", "member_user_id": "member-z", "status": "revoked"},
        ],
    }


# Both resolvers are FastAPI dependencies (user_id defaults to
# Depends(get_current_user)), so calling them directly with an explicit
# user_id= keyword argument bypasses the DI layer, not the resolver's own
# logic -- the same pattern test_wrap_share.py uses for the route functions.

print("\nget_accessible_owner_ids")
auth.get_client = lambda: FakeClient(make_db())

check("a plain owner with no team_members rows resolves to just themselves",
      auth.get_accessible_owner_ids(user_id="owner-a") == {"owner-a"})

check("an ACCEPTED member's resolved set includes the owner",
      auth.get_accessible_owner_ids(user_id="member-x") == {"member-x", "owner-a"})

check("a PENDING (not yet accepted) invitee's resolved set does NOT include the owner",
      auth.get_accessible_owner_ids(user_id="member-y") == {"member-y"},
      "accepting is what grants access, not being invited")

check("a REVOKED former member's resolved set does not include the owner",
      auth.get_accessible_owner_ids(user_id="member-z") == {"member-z"},
      "a row existing and a row granting access are different things")

check("a random third user with no team_members row at all resolves to just themselves",
      auth.get_accessible_owner_ids(user_id="someone-else") == {"someone-else"})

print("\nget_write_owner_id")
auth.get_client = lambda: FakeClient(make_db())

check("a plain (non-member) user's write target is their own id",
      auth.get_write_owner_id(user_id="owner-a") == "owner-a")

check("an accepted member's write target is the OWNER's id, not their own",
      auth.get_write_owner_id(user_id="member-x") == "owner-a",
      "a project a team member creates has to belong to the shared account")

check("a pending invitee's write target is still their own id",
      auth.get_write_owner_id(user_id="member-y") == "member-y",
      "not yet accepted, so nothing has changed for them yet")

check("a revoked former member's write target is back to their own id",
      auth.get_write_owner_id(user_id="member-z") == "member-z")

print("\nJobs and hires (docs/job-layer-plan.md §9): same boundary, one level up")
# The fuller fake the job-layer suites use; the resolvers above decide the
# owner set, and _own_job gates every jobs route on it, as _own_project does.
from fastapi import HTTPException  # noqa: E402
from tests.fake_supabase import FakeClient as JobsClient  # noqa: E402
from routers import jobs as jobs_router  # noqa: E402

jobs_db = {
    **make_db(),
    "jobs": [{"id": "job-a", "owner_id": "owner-a", "name": "Owner A's job", "crew_dates": {}}],
    "job_hires": [{"id": "hire-1", "job_id": "job-a", "name": "Dana", "dates_override": {}, "sort_order": 0}],
    "projects": [], "crew_members": [], "call_sheets": [],
}
jobs_client = JobsClient(jobs_db)
auth.get_client = lambda: jobs_client
jobs_router.get_client = lambda: jobs_client


def reaches(user):
    owners = auth.get_accessible_owner_ids(user_id=user)
    try:
        jobs_router.get_job("job-a", owner_ids=owners)
        hires = jobs_router.list_hires("job-a", owner_ids=owners)
        listed = [j["id"] for j in jobs_router.list_jobs(owner_ids=owners)]
        return bool(hires) and listed == ["job-a"]
    except HTTPException as e:
        assert e.status_code == 404, e
        return False


check("the owner reaches their own job and its hires", reaches("owner-a"))
check("an ACCEPTED team member reaches the owner's job and its hires", reaches("member-x"))
check("a PENDING invitee reaches neither", not reaches("member-y"))
check("a REVOKED former member reaches neither", not reaches("member-z"))
check("a stranger reaches neither — and the job doesn't show in their list either",
      not reaches("someone-else")
      and jobs_router.list_jobs(owner_ids=auth.get_accessible_owner_ids(user_id="someone-else")) == [])

print()
print("ALL PASS" if not FAILS else f"{len(FAILS)} FAILURES: " + ", ".join(FAILS))
sys.exit(1 if FAILS else 0)
