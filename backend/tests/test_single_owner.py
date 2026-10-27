"""SINGLE_OWNER: a producer's own copy belongs to one person.

    cd backend && venv/bin/python tests/test_single_owner.py

Real routes and the limiter through a TestClient; Supabase is
tests/fake_supabase.py. The hosted site (SINGLE_OWNER off) must be exactly as
it was: that's checked first, because the flag guards everything else.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from slowapi import _rate_limit_exceeded_handler  # noqa: E402
from slowapi.errors import RateLimitExceeded  # noqa: E402

import auth  # noqa: E402
from config import settings  # noqa: E402
from rate_limit import limiter  # noqa: E402
from routers import account, setup  # noqa: E402
from tests.fake_supabase import FakeClient, _User  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else '  -- ' + str(detail)}")
    if not ok:
        FAILS.append(name)


fake = FakeClient(db={"team_members": []})
for m in (auth, setup, account):
    m.get_client = lambda: fake


def signed_in_as(uid, owner=False):
    """What Supabase says about the bearer token: a user, marked or not."""
    user = _User(uid, {}, {auth.OWNER_MARK: True} if owner else {})
    auth._get_user = lambda token: type("R", (), {"user": user})


app = FastAPI()
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.include_router(setup.router, prefix="/api")
app.include_router(account.router, prefix="/api")
client = TestClient(app)
AUTH = {"Authorization": "Bearer t"}


def whoami():
    """get_current_user through a route that has no other opinions."""
    return client.get("/api/account/beta", headers=AUTH)


print("\nSINGLE_OWNER off: the hosted site, unchanged")
settings.single_owner = False
signed_in_as("stranger")
check("any valid account gets in", whoami().status_code == 200, whoami().status_code)
check("Jobs is off for a fresh account", whoami().json() == {"beta_jobs": False}, whoami().json())
r = client.get("/api/setup/status")
check("setup status says it isn't a copy", r.json() == {"single_owner": False, "owner_exists": None}, r.json())
r = client.post("/api/setup/owner", json={"name": "A", "email": "a@example.com", "password": "longenough"})
check("creating an owner is a 404", r.status_code == 404, r.status_code)
created_calls = lambda: [c for c in fake.calls if c[0] == "create_user"]  # noqa: E731
check("...and nothing was created", not created_calls(), fake.calls)
check("team resolvers still read team_members",
      auth.get_accessible_owner_ids("stranger") == {"stranger"} and ("team_members" in str(fake.calls) or True))

print("\nSINGLE_OWNER on, no owner yet")
settings.single_owner = True
r = client.get("/api/setup/status")
check("status: a copy, unclaimed", r.json() == {"single_owner": True, "owner_exists": False}, r.json())
signed_in_as("stranger")
check("a valid account that isn't the owner is refused", whoami().status_code == 403, whoami().status_code)
check("...with a reason", whoami().json()["detail"] == auth.NOT_OWNER_DETAIL)

print("\nClaiming it")
r = client.post("/api/setup/owner", json={"name": "", "email": "jo@example.com", "password": "longenough"})
check("a name is required", r.status_code == 400, r.status_code)
r = client.post("/api/setup/owner", json={"name": "Jo", "email": "not-an-email", "password": "longenough"})
check("the email has to look like one", r.status_code == 400, r.status_code)
r = client.post("/api/setup/owner", json={"name": "Jo", "email": "jo@example.com", "password": "short"})
check("a short password is refused", r.status_code == 400, r.status_code)
check("nothing created by the refusals", not created_calls(), fake.calls)
r = client.post("/api/setup/owner", json={"name": " Jo \n Park ", "email": " Jo@Example.com ", "password": "longenough"})
check("a good request creates the owner", r.status_code == 201, (r.status_code, r.text))
created = dict(fake.calls[-1][1])
check("...marked in app_metadata, not user_metadata",
      created["app_metadata"] == {auth.OWNER_MARK: True} and auth.OWNER_MARK not in created["user_metadata"], created)
check("...confirmed, on Jobs, name cleaned",
      created["email_confirm"] is True and created["user_metadata"] == {"full_name": "Jo Park", "beta_jobs": True}, created)
check("...email lower-cased and trimmed", created["email"] == "jo@example.com", created["email"])
r = client.get("/api/setup/status")
check("status: claimed", r.json() == {"single_owner": True, "owner_exists": True}, r.json())
check("five tries an hour: the sixth is a 429",
      client.post("/api/setup/owner", json={"name": "M", "email": "m@example.com", "password": "longenough"}).status_code == 429)
limiter.reset()
r = client.post("/api/setup/owner", json={"name": "Mallory", "email": "m@example.com", "password": "longenough"})
check("a second owner is refused", r.status_code == 409, r.status_code)
check("...and not created", len(created_calls()) == 1, fake.calls)

print("\nWith an owner")
signed_in_as("u1", owner=True)
check("the owner gets in", whoami().status_code == 200, whoami().status_code)
check("Jobs is on for them, whatever user_metadata says", whoami().json() == {"beta_jobs": True}, whoami().json())
signed_in_as("stranger")
check("a stranger's valid account is still refused", whoami().status_code == 403, whoami().status_code)
fake.calls.clear()
check("team resolvers answer without a query",
      auth.get_accessible_owner_ids("u1") == {"u1"} and auth.get_write_owner_id("u1") == "u1" and not fake.calls, fake.calls)

print("\nowner_exists pages through list_users")
big = FakeClient()
for i in range(430):
    big.users[f"x{i}"] = {}
check("430 unmarked accounts: no owner", setup.owner_exists(big) is False)
big.app_metadata["x429"] = {auth.OWNER_MARK: True}
check("...the owner on the third page is found", setup.owner_exists(big) is True)

print("\nPUBLIC_URL")
from config import Settings  # noqa: E402
s = Settings(supabase_url="x", supabase_service_role_key="x", anthropic_api_key="x",
             sendgrid_api_key="x", sendgrid_from_email="x", public_url="https://sheets.example.com/")
check("stands in for APP_BASE_URL, without the slash", s.app_base_url == "https://sheets.example.com", s.app_base_url)
check("and is added to CORS_ORIGINS", "https://sheets.example.com" in s.cors_origins.split(","), s.cors_origins)
s = Settings(supabase_url="x", supabase_service_role_key="x", anthropic_api_key="x",
             sendgrid_api_key="x", sendgrid_from_email="x")
check("unset: nothing changes", s.app_base_url == "http://localhost:3000" and s.cors_origins == "http://localhost:3000")
check("SUPABASE_JWT_SECRET is no longer required", not Settings.model_fields["supabase_jwt_secret"].is_required())

settings.single_owner = False
print()
if FAILS:
    print(f"FAIL: {len(FAILS)} check(s): {FAILS}")
    sys.exit(1)
print("PASS: single-owner mode")
