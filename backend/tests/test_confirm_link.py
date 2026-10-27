"""Opening a confirm link must never confirm anyone.

    cd backend && venv/bin/python tests/test_confirm_link.py

Email security scanners and chat link previews fetch every link in a message.
The confirm page fetches GET /confirm/{token} while it renders, so when that
GET wrote confirmed_at, a scanner opening the link "confirmed" a crew member
who'd never seen the email. Found testing staging on 2026-09-28, and live since
confirmations launched. Now the GET only reads, and the crew member's own
"Got it" is a POST.

Calls the route functions directly against tests/fake_supabase.py.
"""

import json
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.fake_supabase import FakeClient  # noqa: E402
from routers import call_sheet  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else '  -- ' + str(detail)}")
    if not ok:
        FAILS.append(name)


TOKEN = UUID("00000000-0000-0000-0000-00000000c0f1")
DB = {
    "crew_members": [{"id": "c1", "project_id": "p1", "name": "Dana Test", "email": "dana@example.com",
                      "role": "Gaffer", "confirmation_token": str(TOKEN), "confirmed_at": None,
                      "call_time": "06:30:00"}],
    "call_sheets": [{"id": "s1", "project_id": "p1", "html_content": "<p>sheet</p>", "generated_at": "2026-09-28T00:00:00"}],
}
call_sheet.get_client = lambda: FakeClient(DB)


class Req:
    """slowapi's decorator needs a Request; its limit isn't under test here."""
    def __init__(self):
        self.client = type("C", (), {"host": "127.0.0.1"})()
        self.headers = {}
        self.url = type("U", (), {"path": "/api/confirm"})()
        self.method = "GET"
        self.state = type("S", (), {})()
        self.scope = {"type": "http"}


call_sheet.limiter.enabled = False


def body(resp):
    return json.loads(resp.body)


print("\nOpening the link (what a scanner or link preview does)")
for _ in range(3):
    r = body(call_sheet.confirm_page_data(Req(), TOKEN))
check("the page gets the name, call time and sheet", r["name"] == "Dana Test" and r["call_time"] == "06:30:00"
      and r["call_sheet_html"], r)
check("...and is told they haven't confirmed", r["confirmed"] is True and r["already_confirmed"] is False, r)
check("opening it three times confirms nobody", DB["crew_members"][0]["confirmed_at"] is None)

print("\nPressing \"Got it\"")
r = body(call_sheet.confirm_receipt(Req(), TOKEN))
first = DB["crew_members"][0]["confirmed_at"]
check("the POST confirms them", first is not None and r["confirmed"] is True and r["already_confirmed"] is False, r)
r = body(call_sheet.confirm_receipt(Req(), TOKEN))
check("pressing again keeps the first time", DB["crew_members"][0]["confirmed_at"] == first and r["already_confirmed"] is True)
r = body(call_sheet.confirm_page_data(Req(), TOKEN))
check("reopening the link now says already confirmed", r["already_confirmed"] is True)

print("\nA link that isn't one")
bogus = UUID("00000000-0000-0000-0000-00000000dead")
check("GET: not recognised", body(call_sheet.confirm_page_data(Req(), bogus))["confirmed"] is False)
check("POST: not recognised, and nothing written", body(call_sheet.confirm_receipt(Req(), bogus))["confirmed"] is False)

print()
print(f"{len(FAILS)} FAILED: {', '.join(FAILS)}" if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
