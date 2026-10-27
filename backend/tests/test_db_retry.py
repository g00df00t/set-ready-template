"""A select that hits a dead pooled connection is retried once; a write never is.

    cd backend && venv/bin/python tests/test_db_retry.py

Every set-ready-backend Sentry issue from 2026-09-25 on was
`httpx.RemoteProtocolError: Server disconnected` on a plain select after an idle
spell — httpx reusing a keep-alive connection Supabase had already closed.
database.py now gives the PostgREST client a transport that retries GET/HEAD
once. This drives real supabase-py / postgrest query builders through
database.new_client, with a fake transport underneath in place of the network,
so it also fails if a library upgrade stops calling the hook the retry lives in.
"""

import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import RetryReadsTransport, new_client  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else '  -- ' + str(detail)}")
    if not ok:
        FAILS.append(name)


class FlakyTransport(httpx.BaseTransport):
    """Drops the connection on the first `drops` requests, then answers."""

    def __init__(self, drops=1, error=httpx.RemoteProtocolError):
        self.drops, self.error, self.seen = drops, error, []

    def handle_request(self, request):
        self.seen.append(request.method)
        if len(self.seen) <= self.drops:
            raise self.error("Server disconnected without sending a response.", request=request)
        body = [] if request.method == "HEAD" else [{"id": "c1", "name": "Dana Test"}]
        return httpx.Response(200, request=request, content=json.dumps(body).encode(),
                              headers={"content-type": "application/json", "content-range": "0-0/1"})


def client_over(transport):
    return new_client("https://test-project.supabase.co", "test-key", inner_transport=transport)


print("\nWired in")
c = client_over(FlakyTransport(drops=0))
check("the PostgREST client's transport is the retrying one",
      isinstance(c.postgrest.session._transport, RetryReadsTransport))
c._postgrest = None  # what supabase-py does on an auth state change
check("...and still is after the library rebuilds it",
      isinstance(c.postgrest.session._transport, RetryReadsTransport))

print("\nA select on a dead connection")
t = FlakyTransport(drops=1)
r = client_over(t).table("crew_members").select("*").eq("project_id", "p1").execute()
check("succeeds", r.data == [{"id": "c1", "name": "Dana Test"}], r.data)
check("after exactly one retry", t.seen == ["GET", "GET"], t.seen)

t = FlakyTransport(drops=1, error=httpx.ReadError)
r = client_over(t).table("crew_members").select("*").execute()
check("a ReadError is retried the same way", t.seen == ["GET", "GET"] and r.data, t.seen)

t = FlakyTransport(drops=1)
client_over(t).table("crew_members").select("id", count="exact", head=True).execute()
check("a head/count select (HEAD) is retried too", t.seen == ["HEAD", "HEAD"], t.seen)

t = FlakyTransport(drops=2)
try:
    client_over(t).table("crew_members").select("*").execute()
    check("two drops in a row still raise", False, "no exception")
except httpx.RemoteProtocolError:
    check("two drops in a row still raise — one retry, not a loop", t.seen == ["GET", "GET"], t.seen)

print("\nWrites are never retried")
writes = [
    ("insert", lambda q: q.insert({"name": "Dana Test"}), "POST"),
    ("upsert", lambda q: q.upsert({"id": "c1", "name": "Dana Test"}), "POST"),
    ("update", lambda q: q.update({"name": "Dana T"}).eq("id", "c1"), "PATCH"),
    ("delete", lambda q: q.delete().eq("id", "c1"), "DELETE"),
]
for label, build, method in writes:
    t = FlakyTransport(drops=1)
    try:
        build(client_over(t).table("crew_members")).execute()
        check(f"{label}: the drop reaches the caller", False, "no exception")
    except httpx.RemoteProtocolError:
        check(f"{label}: the drop reaches the caller, sent once", t.seen == [method], t.seen)

t = FlakyTransport(drops=1)
try:
    client_over(t).rpc("some_function", {}).execute()
    check("rpc (POST): not retried", False, "no exception")
except httpx.RemoteProtocolError:
    check("rpc (POST): not retried", t.seen == ["POST"], t.seen)

print("\nThe auth check: retried once on a dead connection, then a 503")
import auth  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from fastapi.security import HTTPAuthorizationCredentials  # noqa: E402


class FakeAuth:
    def __init__(self, errors):
        self.errors, self.calls = list(errors), 0

    def get_user(self, token):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return type("R", (), {"user": type("U", (), {"id": "u1"})()})()


def auth_with(errors):
    fake = FakeAuth(errors)
    auth.get_client = lambda: type("C", (), {"auth": fake})()
    return fake


creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="t")
fake = auth_with([httpx.RemoteProtocolError("Server disconnected")])
check("a dead pooled connection: retried once, and the user comes back",
      auth.get_current_user(creds) == "u1" and fake.calls == 2, fake.calls)
fake = auth_with([httpx.ReadError("reset"), httpx.RemoteProtocolError("again")])
try:
    auth.get_current_user(creds)
    check("dropped twice: a 503, not a 401", False, "no error")
except HTTPException as e:
    check("dropped twice: a 503, not a 401", e.status_code == 503 and fake.calls == 2, (e.status_code, fake.calls))
fake = auth_with([httpx.ConnectTimeout("slow")])
try:
    auth.get_current_user(creds)
    check("a timeout isn't retried (it may be Supabase down): still a 503 at once", False, "no error")
except HTTPException as e:
    check("a timeout isn't retried (it may be Supabase down): still a 503 at once", e.status_code == 503 and fake.calls == 1)
from supabase_auth.errors import AuthApiError  # noqa: E402
fake = auth_with([AuthApiError("bad jwt", 403, None)])
try:
    auth.get_current_user(creds)
    check("a rejected token is never retried: a 401", False, "no error")
except HTTPException as e:
    check("a rejected token is never retried: a 401", e.status_code == 401 and fake.calls == 1)

print()
print(f"{len(FAILS)} FAILED: {', '.join(FAILS)}" if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
