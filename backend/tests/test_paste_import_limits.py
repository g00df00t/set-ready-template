"""The paste-a-list imports: 60 an hour, per account.

    cd backend && venv/bin/python tests/test_paste_import_limits.py

Four routes turn pasted text into people with a model call: the Roster's Quick
Import and a day's Crew / Talent / Contacts import. Each call costs a cent or
two, so each is capped at rate_limit.PASTE_IMPORT_LIMIT per ACCOUNT (Patrick,
2026-09-28). They used to be keyed on the bearer token, which Supabase replaces
on every session refresh — so a refresh quietly reset the budget. The property
tested here is the one that closes that: a fresh token on every request still
counts against the same account.

Real routes, limiter and 429 handler through a TestClient. Auth, Supabase and
the parsers are faked; every database client points at a fake. No network.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from slowapi import _rate_limit_exceeded_handler  # noqa: E402
from slowapi.errors import RateLimitExceeded  # noqa: E402

import auth  # noqa: E402
import rate_limit  # noqa: E402
from rate_limit import limiter  # noqa: E402
from routers import contacts, crew, roster, talent  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else '  -- ' + detail}")
    if not ok:
        FAILS.append(name)


# ── Fakes ────────────────────────────────────────────────────────────────────

class FakeTable:
    def __init__(self, db, name):
        self.db, self.name, self.f, self._in = db, name, {}, {}

    def select(self, *_a, **_k): return self
    def order(self, *_a, **_k): return self
    def eq(self, k, v): self.f[k] = v; return self
    def in_(self, k, vs): self._in[k] = set(vs); return self
    def insert(self, _row): return self   # usage_events; accepted and dropped

    def execute(self):
        rows = [r for r in self.db.get(self.name, [])
                if all(r.get(k) == v for k, v in self.f.items())
                and all(r.get(k) in v for k, v in self._in.items())]
        return type("R", (), {"data": [dict(r) for r in rows]})


PROJECT = "11111111-1111-1111-1111-111111111111"
DB = {
    # Both test accounts own the project, so a day-page import is allowed for
    # either and the only thing that can refuse one is the limiter.
    "projects": [{"id": PROJECT, "owner_id": "user-1"}, {"id": PROJECT, "owner_id": "user-2"}],
    "roster": [], "crew_members": [], "talent": [], "project_contacts": [],
}
fake_db = type("FakeSupabase", (), {"table": lambda self, n: FakeTable(DB, n)})()

for module in (roster, crew, talent, contacts):
    module.get_client = lambda: fake_db
auth.get_client = lambda: fake_db   # never a real project

CALLS = []


def fake_parser(text, on_usage=None):
    CALLS.append(text)
    return [{"name": "Jane Placeholder", "role": "Grip", "email": None, "phone": None}]


crew.parse_crew_import = fake_parser
talent.parse_talent_import = fake_parser
contacts.parse_contacts_import = fake_parser
for kind in list(roster._PARSERS):
    roster._PARSERS[kind] = fake_parser

app = FastAPI()
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
for module in (roster, crew, talent, contacts):
    app.include_router(module.router, prefix="/api")

CURRENT = {"id": "user-1"}
app.dependency_overrides[auth.get_current_user] = lambda: CURRENT["id"]
app.dependency_overrides[auth.get_accessible_owner_ids] = lambda: {CURRENT["id"]}
app.dependency_overrides[auth.get_write_owner_id] = lambda: CURRENT["id"]
http = TestClient(app)

ROUTES = [
    ("Roster paste", "/api/roster/import/parse", {"text": "pasted", "type": "crew"}),
    ("Crew page paste", f"/api/projects/{PROJECT}/crew/import/parse", {"text": "pasted"}),
    ("Talent page paste", f"/api/projects/{PROJECT}/talent/import/parse", {"text": "pasted"}),
    ("Contacts page paste", f"/api/projects/{PROJECT}/contacts/import/parse", {"text": "pasted"}),
]


# ── The limit ────────────────────────────────────────────────────────────────

print("\nThe limit")
check('PASTE_IMPORT_LIMIT is "60/hour"', rate_limit.PASTE_IMPORT_LIMIT == "60/hour",
      repr(rate_limit.PASTE_IMPORT_LIMIT))
LIMIT = 60

for label, url, body in ROUTES:
    print(f"\n{label}")
    limiter.reset()
    CALLS.clear()
    CURRENT["id"] = "user-1"

    # A new bearer token each time, as after a session refresh. The old
    # per-token key would have given every one of these a fresh budget.
    codes = [http.post(url, json=body, headers={"Authorization": f"Bearer refreshed-{i}"}).status_code
             for i in range(LIMIT)]
    check(f"{LIMIT} in an hour are allowed, a fresh token on every one",
          all(c == 200 for c in codes), str(sorted(set(codes))))
    check(f"all {LIMIT} reached the parser", len(CALLS) == LIMIT, f"{len(CALLS)} calls")

    r = http.post(url, json=body, headers={"Authorization": "Bearer yet-another-refresh"})
    check(f"number {LIMIT + 1} is refused with 429", r.status_code == 429, f"got {r.status_code}")
    check("and never reaches the parser", len(CALLS) == LIMIT, f"{len(CALLS)} calls")

    CURRENT["id"] = "user-2"
    r = http.post(url, json=body, headers={"Authorization": "Bearer someone-else"})
    check("a different account still gets 200", r.status_code == 200, f"got {r.status_code}")

print()
print(f"{len(FAILS)} FAILURES: {', '.join(FAILS)}" if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
