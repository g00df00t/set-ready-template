"""Uploading an old call sheet PDF to the Roster's Quick Import.

    cd backend && venv/bin/python tests/test_call_sheet_import.py

POST /api/roster/import/call-sheet is the most expensive request the app makes
— a whole PDF handed to a model — and its answer is a list of real people's
names and numbers. So the things that matter are asserted here, through the
real route, limiter and dependency chain rather than by calling helpers:

- only a real, small, unlocked PDF ever reaches the model;
- one account can't run up the bill (per-user limit, not per-token or IP);
- the model is sent the PDF itself, as a document block;
- people come back typed crew / talent / client, and nothing about pay does;
- nothing is written: parse only, the producer confirms separately.

Uses a fake Anthropic client and a fake Supabase client. No network, no cost.
"""

import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pymupdf  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from slowapi import _rate_limit_exceeded_handler  # noqa: E402
from slowapi.errors import RateLimitExceeded  # noqa: E402

import auth  # noqa: E402
from rate_limit import limiter  # noqa: E402
from routers import roster  # noqa: E402
from services import call_sheet_import, claude_service  # noqa: E402

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

    def insert(self, rows):
        self.db["_writes"].append((self.name, "insert", rows)); return self

    def update(self, c):
        self.db["_writes"].append((self.name, "update", c)); return self

    def delete(self):
        self.db["_writes"].append((self.name, "delete", None)); return self

    def execute(self):
        rows = [r for r in self.db.get(self.name, [])
                if all(r.get(k) == v for k, v in self.f.items())
                and all(r.get(k) in v for k, v in self._in.items())]
        return type("R", (), {"data": [dict(r) for r in rows]})


class FakeSupabase:
    def __init__(self, db): self.db = db
    def table(self, n): return FakeTable(self.db, n)


DB = {
    "_writes": [],
    "roster": [
        # Already saved as crew, under a shorter name — the email decides.
        {"id": "r-crew", "owner_id": "user-1", "type": "crew", "name": "Rosalind Hart",
         "email": "roz.hart@example.com", "phone": None, "role": "Gaffer"},
        # Same email as a CLIENT on the sheet, but saved as crew: a different
        # hat, not a match — types never cross.
        {"id": "r-other-type", "owner_id": "user-1", "type": "crew", "name": "Luca Brannigan",
         "email": "luca.b@example.com", "phone": None, "role": "Grip"},
        # Someone else's Roster entry for a person on the sheet. Must not be seen.
        {"id": "r-stranger", "owner_id": "user-2", "type": "talent", "name": "Calloway Resnick",
         "email": "calloway@example.com", "phone": None, "role": "Talent"},
    ],
}
roster.get_client = lambda: FakeSupabase(DB)


MODEL_REPLY = [
    {"name": "Rosalind Achebe-Hart", "type": "crew", "role": "Gaffer",
     "department": "Grip & Electric", "email": "roz.hart@example.com",
     "phone": "(555) 201-4430", "organization": "Should be dropped — crew",
     # Everything below must never survive.
     "day_rate": "$750/10", "rate": "$750", "rate_note": "10 hr day", "call_time": "6:00 AM"},
    {"name": "Kit Oyelaran", "type": "crew", "role": "PA $250/day",
     "department": "Production", "email": "kit.o@example.com", "phone": "(555) 201-4412"},
    {"name": "Calloway Resnick", "type": "talent", "role": "Hero Talent",
     "department": "Should be dropped — talent", "email": "calloway@example.com", "phone": None},
    {"name": "Luca Brannigan", "type": "client", "role": "Art Buyer",
     "organization": "Tidewater Agency", "email": "luca.b@example.com", "phone": "(555) 402-7711"},
    {"name": "Sam Unsure", "type": "producer?", "role": "Something"},
    {"name": "", "type": "crew", "role": "Nameless row"},
    {"name": "TBD", "type": "crew", "role": "2nd AC"},
    "not a person",
]


class FakeMessages:
    def __init__(self):
        self.calls = []
        self.reply = json.dumps(MODEL_REPLY)
        self.raise_error = None

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.raise_error:
            raise self.raise_error
        text = type("T", (), {"text": self.reply})()
        usage = type("U", (), {"input_tokens": 3000, "output_tokens": 1400})()
        return type("M", (), {"content": [text], "usage": usage, "stop_reason": "end_turn"})()


class FakeAnthropic:
    def __init__(self): self.messages = FakeMessages()


fake = FakeAnthropic()
claude_service._client = fake


# ── App: the real router, limiter and error handler; auth faked ──────────────

app = FastAPI()
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.include_router(roster.router, prefix="/api")

CURRENT_USER = {"id": "user-1"}
app.dependency_overrides[auth.get_current_user] = lambda: CURRENT_USER["id"]
# The real resolvers ask team_members; this user is on no team.
app.dependency_overrides[auth.get_accessible_owner_ids] = lambda: {CURRENT_USER["id"]}
app.dependency_overrides[auth.get_write_owner_id] = lambda: CURRENT_USER["id"]
# Belt and braces: anything auth.py still reaches for gets the fake, never a
# real Supabase project.
auth.get_client = lambda: FakeSupabase(DB)

http = TestClient(app)
URL = "/api/roster/import/call-sheet"


def pdf(pages=1, **save_kwargs) -> bytes:
    doc = pymupdf.open()
    for i in range(pages):
        doc.new_page().insert_text((72, 72), f"CALL SHEET page {i + 1} — fabricated")
    return doc.tobytes(**save_kwargs)


def upload(body: bytes, headers=None):
    return http.post(URL, content=body,
                     headers={"Content-Type": "application/pdf", **(headers or {})})


def reset():
    limiter.reset()
    fake.messages.calls.clear()
    fake.messages.reply = json.dumps(MODEL_REPLY)
    fake.messages.raise_error = None
    CURRENT_USER["id"] = "user-1"


GOOD = pdf()


# ── Refusals, before any model call ──────────────────────────────────────────

print("\nOnly a real PDF reaches the model")
reset()
for label, body in [
    ("a PNG renamed .pdf", b"\x89PNG\r\n\x1a\n" + b"\x00" * 200),
    ("a Word document", b"PK\x03\x04" + b"\x00" * 200),
    ("plain text", b"Jane Smith, Gaffer, 555-0100"),
]:
    r = upload(body)
    check(f"{label} is refused with 415", r.status_code == 415, f"got {r.status_code}")
check("and says what to do", "PDF" in upload(b"hello").json().get("detail", ""))
r = upload(b"")
check("an empty upload is refused", r.status_code == 400, f"got {r.status_code}")
check("the model was never called for any of them", not fake.messages.calls,
      f"{len(fake.messages.calls)} calls")

print("\nSize and page caps")
reset()
big = b"%PDF-1.7\n" + b"0" * (call_sheet_import.MAX_BYTES + 1)
r = upload(big)
check("over 10 MB is refused with 413", r.status_code == 413, f"got {r.status_code}")
check("with a friendly message", "MB" in r.json().get("detail", ""), r.text[:200])
try:
    call_sheet_import.check_pdf(big)
    check("check_pdf refuses oversize on its own too", False, "accepted")
except call_sheet_import.Rejected as e:
    check("check_pdf refuses oversize on its own too", e.status == 413)
r = upload(pdf(pages=call_sheet_import.MAX_PAGES + 1))
check("11 pages is refused", r.status_code == 400 and "pages" in r.json().get("detail", ""),
      f"{r.status_code} {r.text[:200]}")
r = upload(pdf(pages=call_sheet_import.MAX_PAGES))
check("10 pages is accepted", r.status_code == 200, f"{r.status_code} {r.text[:200]}")
locked = pdf(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="fabricated", owner_pw="fabricated2")
r = upload(locked)
check("a password-protected PDF is refused", r.status_code == 400
      and "password" in r.json().get("detail", "").lower(), f"{r.status_code} {r.text[:200]}")
r = upload(b"%PDF-1.7\nthis is not really a pdf at all")
check("a damaged PDF is refused", r.status_code == 400, f"{r.status_code} {r.text[:200]}")
check("only the one good PDF reached the model", len(fake.messages.calls) == 1,
      f"{len(fake.messages.calls)} calls")


# ── What the model is sent ───────────────────────────────────────────────────

print("\nThe model is sent the PDF itself")
reset()
r = upload(GOOD)
check("a good PDF is read", r.status_code == 200, f"{r.status_code} {r.text[:300]}")
sent = fake.messages.calls[0]
blocks = sent["messages"][0]["content"]
docs = [b for b in blocks if isinstance(b, dict) and b.get("type") == "document"]
check("as a document block", len(docs) == 1, json.dumps(blocks, default=str)[:300])
src = docs[0]["source"] if docs else {}
check("base64, application/pdf", src.get("type") == "base64"
      and src.get("media_type") == "application/pdf", str(src.keys()))
check("carrying exactly the uploaded bytes", base64.b64decode(src.get("data", "")) == GOOD)
check("with the same model the paste import uses", sent["model"] == claude_service.MODEL)
prompt = " ".join(b.get("text", "") for b in blocks if b.get("type") == "text").lower()
check("and the prompt forbids pay", "rates" in prompt and "pay" in prompt)


# ── What comes back ──────────────────────────────────────────────────────────

members = r.json()["members"]
by_name = {m["name"]: m for m in members}

print("\nThree types, typed correctly")
check("crew is crew", by_name["Rosalind Achebe-Hart"]["type"] == "crew")
check("talent is talent", by_name["Calloway Resnick"]["type"] == "talent")
check("client is client", by_name["Luca Brannigan"]["type"] == "client")
check("an unknown type falls back to crew", by_name["Sam Unsure"]["type"] == "crew")
check("rows with no real name are dropped",
      len(members) == 5 and "TBD" not in by_name, str(sorted(by_name)))
check("department only on crew",
      by_name["Calloway Resnick"]["department"] is None
      and by_name["Rosalind Achebe-Hart"]["department"] == "Grip & Electric")
check("organization only on clients",
      by_name["Rosalind Achebe-Hart"]["organization"] is None
      and by_name["Luca Brannigan"]["organization"] == "Tidewater Agency")

print("\nNothing about pay is extracted")
PAY_KEYS = {"day_rate", "rate", "rate_note", "call_time", "agency", "agent_name",
            "agent_email", "agent_phone", "company"}
leaked = [(m["name"], k) for m in members for k in m if k in PAY_KEYS]
check("no rate, fee or call-time field on any row", not leaked, str(leaked))
check("a pay figure inside an allowed field is dropped too",
      by_name["Kit Oyelaran"]["role"] is None, repr(by_name["Kit Oyelaran"]["role"]))
check("no dollar amount anywhere in the response", "$" not in r.text)
for value in ("$650", "650/day", "£400", "day rate: 900", "1200 USD flat fee", "per hour"):
    check(f"clean_people drops {value!r}",
          call_sheet_import.clean_people([{"name": "A", "role": value}])[0]["role"] is None)
for value in ("Gaffer", "1st AC", "(555) 201-4430", "Hair & Makeup / Grooming"):
    check(f"clean_people keeps {value!r}",
          call_sheet_import.clean_people([{"name": "A", "role": value}])[0]["role"] == value)

print("\nEach row says whether it is already on the Roster")
check("a saved crew member is found by email under a different name",
      by_name["Rosalind Achebe-Hart"]["match_state"] == "in_roster"
      and by_name["Rosalind Achebe-Hart"]["match_id"] == "r-crew",
      str(by_name["Rosalind Achebe-Hart"].get("match_state")))
check("a crew entry never matches a client row",
      by_name["Luca Brannigan"]["match_state"] == "new",
      str(by_name["Luca Brannigan"].get("match_state")))
check("another producer's Roster is never consulted",
      by_name["Calloway Resnick"]["match_state"] == "new",
      str(by_name["Calloway Resnick"].get("match_state")))

print("\nParse only — nothing is written but the usage event")
people_writes = [w for w in DB["_writes"] if w[0] != "usage_events"]
check("no insert, update or delete of people", not people_writes, str(people_writes))
spend = [w for w in DB["_writes"] if w[0] == "usage_events"]
check("the upload's spend is recorded", spend and spend[-1][2]["event_type"] == "import_roster_call_sheet"
      and spend[-1][2]["input_tokens"] == 3000 and spend[-1][2]["output_tokens"] == 1400,
      str(spend[-1:]))
check("and carries no name, email or phone", spend and not any(
    s in json.dumps(spend[-1][2]) for s in ("Rosalind", "@example.com", "555")), str(spend[-1:]))


# ── Failures ─────────────────────────────────────────────────────────────────

print("\nA failed read is a friendly 502, never the model's text")
reset()
fake.messages.reply = "Here are the people: Jane Smith 555-0100"
r = upload(GOOD)
check("unparseable reply -> 502", r.status_code == 502, f"got {r.status_code}")
check("detail is the friendly line, no names", "Jane" not in r.text and "paste" in r.text, r.text)
reset()
fake.messages.reply = json.dumps({"name": "Jane Smith"})
check("a reply that isn't a list -> 502", upload(GOOD).status_code == 502)
reset()
fake.messages.raise_error = RuntimeError("upstream exploded with Jane Smith's number")
r = upload(GOOD)
check("a model error -> 502", r.status_code == 502, f"got {r.status_code}")
check("without echoing the exception", "Jane" not in r.text, r.text)
reset()
fake.messages.reply = "[]"
r = upload(GOOD)
check("a sheet with nobody on it is an empty list, not an error",
      r.status_code == 200 and r.json() == {"members": []}, f"{r.status_code} {r.text}")


# ── Rate limit ───────────────────────────────────────────────────────────────

print("\nPer-user rate limit")
reset()
limit = int(roster.CALL_SHEET_IMPORT_LIMIT.split("/")[0])
codes = [upload(GOOD, {"Authorization": f"Bearer token-{i}"}).status_code for i in range(limit)]
check(f"{limit} uploads in an hour are allowed", all(c == 200 for c in codes), str(codes))
r = upload(GOOD, {"Authorization": "Bearer yet-another-refreshed-token"})
check(f"upload {limit + 1} is refused with 429", r.status_code == 429, f"got {r.status_code}")
check("keyed on the account: a fresh token per request didn't reset it",
      len(fake.messages.calls) == limit, f"{len(fake.messages.calls)} model calls")
CURRENT_USER["id"] = "user-2"
check("a different account is unaffected", upload(GOOD).status_code == 200)

print("\nAuth is required")
reset()
app.dependency_overrides.clear()
r = http.post(URL, content=GOOD, headers={"Content-Type": "application/pdf"})
check("no bearer token -> refused", r.status_code in (401, 403), f"got {r.status_code}")
check("and the model is never called", not fake.messages.calls)

print()
print(f"{len(FAILS)} FAILURES: {', '.join(FAILS)}" if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
