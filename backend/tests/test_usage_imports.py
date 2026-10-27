"""What every AI import costs, and that recording it can never break an import.

    cd backend && venv/bin/python tests/test_usage_imports.py

Each paste-a-list import (Roster, and a day's Crew / Talent / Contacts page) and
each call sheet upload records one usage_events row with the model's own token
counts. That needs supabase/usage_import_events.sql, which Patrick runs by hand
— so the property that matters most is the one before it has run: the insert is
refused, a warning is logged, and the producer's import works exactly as before.

Also here:
- the recorded row holds counts and a model id, never a name, email, phone,
  file name or pasted text;
- a reply that fails to parse is still recorded, because it was still paid for;
- the Roster paste preview now carries the same In your Roster / Possible match
  / New verdict as the call sheet upload, from the same shared helper;
- usage_stats turns tokens into measured spend at the listed price, keeps the
  flat-rate generation figure apart, and survives a database without the new
  columns.

Fake Anthropic and Supabase clients throughout. No network, no cost.
"""

import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pymupdf  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from slowapi import _rate_limit_exceeded_handler  # noqa: E402
from slowapi.errors import RateLimitExceeded  # noqa: E402

import auth  # noqa: E402
import usage  # noqa: E402
import usage_stats  # noqa: E402
from rate_limit import limiter  # noqa: E402
from routers import crew, contacts, roster, talent  # noqa: E402
from services import claude_service  # noqa: E402
from services.import_match import classify_against_roster  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else '  -- ' + detail}")
    if not ok:
        FAILS.append(name)


# ── Fakes ────────────────────────────────────────────────────────────────────

class Refused(Exception):
    """Stands in for postgrest's APIError when the old CHECK constraint (or a
    missing column) rejects the row."""


class FakeTable:
    def __init__(self, fake, name):
        self.fake, self.name, self.f, self._in, self._cols = fake, name, {}, {}, "*"

    def select(self, cols="*", **_k):
        self._cols = cols
        return self

    def order(self, *_a, **_k): return self
    def range(self, *_a): return self
    def eq(self, k, v): self.f[k] = v; return self
    def in_(self, k, vs): self._in[k] = set(vs); return self

    def insert(self, row):
        if self.name == "usage_events" and self.fake.schema_old:
            raise Refused('new row for relation "usage_events" violates check constraint '
                          '"usage_events_event_type_check"')
        self.fake.writes.append((self.name, row))
        return self

    def execute(self):
        if self.name in self.fake.broken_tables:
            raise Refused(f"{self.name} unavailable")
        if (self.name == "usage_events" and self.fake.schema_old
                and "input_tokens" in self._cols):
            raise Refused('column usage_events.input_tokens does not exist')
        rows = [r for r in self.fake.db.get(self.name, [])
                if all(r.get(k) == v for k, v in self.f.items())
                and all(r.get(k) in v for k, v in self._in.items())]
        return type("R", (), {"data": [dict(r) for r in rows]})


class FakeSupabase:
    def __init__(self, db, schema_old=False):
        self.db, self.schema_old, self.writes, self.broken_tables = db, schema_old, [], set()
        users = db.get("_users", [])
        self.auth = type("A", (), {"admin": type("Adm", (), {
            "list_users": staticmethod(lambda page=1, per_page=50: users if page == 1 else []),
        })()})()

    def table(self, n): return FakeTable(self, n)


class FakeMessages:
    def __init__(self):
        self.reply = "[]"

    def create(self, **kwargs):
        text = type("T", (), {"text": self.reply})()
        usage_ = type("U", (), {"input_tokens": 812, "output_tokens": 240})()
        return type("M", (), {"content": [text], "usage": usage_, "model": kwargs["model"],
                              "stop_reason": "end_turn"})()


fake_model = type("FakeAnthropic", (), {})()
fake_model.messages = FakeMessages()
claude_service._client = fake_model


def roster_db():
    return {
        "roster": [
            {"id": "r-crew", "owner_id": "user-1", "type": "crew", "name": "Rosalind Hart",
             "email": "roz.hart@example.com", "phone": None, "role": "Gaffer"},
            {"id": "r-twin-a", "owner_id": "user-1", "type": "crew", "name": "Sam Lee",
             "email": "shared@example.com", "phone": None, "role": "Grip"},
            {"id": "r-twin-b", "owner_id": "user-1", "type": "crew", "name": "Sam Lee",
             "email": "shared@example.com", "phone": None, "role": "Grip"},
            {"id": "r-client", "owner_id": "user-1", "type": "client", "name": "Kit Oyelaran",
             "email": "kit.o@example.com", "phone": None, "role": "Art Buyer"},
            {"id": "r-stranger", "owner_id": "user-2", "type": "crew", "name": "Priya Venkataraman",
             "email": "priya.v@example.com", "phone": None, "role": "1st AC"},
        ],
        "projects": [{"id": "11111111-1111-1111-1111-111111111111", "owner_id": "user-1"}],
        "crew_members": [], "talent": [], "project_contacts": [],
    }


STATE = {"fake": FakeSupabase(roster_db())}


def current():
    return STATE["fake"]


for module in (roster, crew, talent, contacts):
    module.get_client = current
auth.get_client = current   # never a real project, whatever auth.py reaches for

app = FastAPI()
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
for module in (roster, crew, talent, contacts):
    app.include_router(module.router, prefix="/api")
app.dependency_overrides[auth.get_current_user] = lambda: "user-1"
app.dependency_overrides[auth.get_accessible_owner_ids] = lambda: {"user-1"}
app.dependency_overrides[auth.get_write_owner_id] = lambda: "user-1"
http = TestClient(app)

PROJECT = "11111111-1111-1111-1111-111111111111"
PASTED = [
    {"name": "Rosalind Achebe-Hart", "role": "Gaffer", "email": "roz.hart@example.com",
     "phone": "(555) 201-4430", "department": "Grip & Electric", "call_time": "6:00 AM"},
    {"name": "Sam Lee", "role": "Grip", "email": "shared@example.com", "phone": None},
    {"name": "Kit Oyelaran", "role": "PA", "email": "kit.o@example.com", "phone": None},
    {"name": "Priya Venkataraman", "role": "1st AC", "email": "priya.v@example.com", "phone": None},
    {"name": "Devon New", "role": "DIT", "email": "devon@example.com", "phone": None},
]


class Captured(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


captured = Captured()
logging.getLogger("usage").addHandler(captured)
logging.getLogger("usage").setLevel(logging.WARNING)


def fresh(schema_old=False):
    limiter.reset()
    STATE["fake"] = FakeSupabase(roster_db(), schema_old=schema_old)
    fake_model.messages.reply = json.dumps(PASTED)
    captured.lines.clear()
    return STATE["fake"]


def usage_rows(fake):
    return [row for table, row in fake.writes if table == "usage_events"]


def pdf() -> bytes:
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "CALL SHEET — fabricated")
    return doc.tobytes()


PII = ("Rosalind", "Kit", "@example.com", "555", "Gaffer", "fabricated", ".pdf")


# ── Recording, after the migration ───────────────────────────────────────────

print("\nEvery AI import records its spend")
cases = [
    ("Roster paste", lambda: http.post("/api/roster/import/parse", json={"text": "pasted", "type": "crew"}),
     "import_roster_paste", None),
    ("Roster call sheet", lambda: http.post("/api/roster/import/call-sheet", content=pdf(),
                                            headers={"Content-Type": "application/pdf"}),
     "import_roster_call_sheet", None),
    ("Crew page paste", lambda: http.post(f"/api/projects/{PROJECT}/crew/import/parse", json={"text": "pasted"}),
     "import_crew_paste", PROJECT),
    ("Talent page paste", lambda: http.post(f"/api/projects/{PROJECT}/talent/import/parse", json={"text": "pasted"}),
     "import_talent_paste", PROJECT),
    ("Contacts page paste", lambda: http.post(f"/api/projects/{PROJECT}/contacts/import/parse", json={"text": "pasted"}),
     "import_contacts_paste", PROJECT),
]
for label, call, event, project in cases:
    fake = fresh()
    r = call()
    rows = usage_rows(fake)
    check(f"{label}: import works", r.status_code == 200, f"{r.status_code} {r.text[:200]}")
    check(f"{label}: one {event} row", len(rows) == 1 and rows[0]["event_type"] == event, str(rows))
    if rows:
        row = rows[0]
        check(f"{label}: tokens and model as the model reported them",
              row["input_tokens"] == 812 and row["output_tokens"] == 240
              and row["model"] == claude_service.MODEL, str(row))
        check(f"{label}: recorded against the owning account", row["user_id"] == "user-1"
              and row["project_id"] == project, str(row))
        check(f"{label}: only counts and ids — no PII field",
              set(row) == {"user_id", "project_id", "event_type", "model", "input_tokens", "output_tokens"},
              str(sorted(row)))
        check(f"{label}: no name, email, phone, role or file name anywhere in the row",
              not any(s in json.dumps(row) for s in PII), json.dumps(row))

print("\nA reply that won't parse is still recorded — it was still paid for")
fake = fresh()
fake_model.messages.reply = "Sorry, here are the people: Rosalind 555-0100"
r = http.post("/api/roster/import/parse", json={"text": "pasted", "type": "crew"})
check("the import fails as it always did", r.status_code == 422, f"got {r.status_code}")
check("but the spend is recorded", len(usage_rows(fake)) == 1, str(usage_rows(fake)))


# ── Before the migration: degrade silently ───────────────────────────────────

print("\nBefore supabase/usage_import_events.sql runs, every import still works")
for label, call, event, _project in cases:
    fake = fresh(schema_old=True)
    r = call()
    check(f"{label}: still 200 with the old constraint", r.status_code == 200, f"{r.status_code} {r.text[:200]}")
    check(f"{label}: and still returns the people", bool(r.json().get("members")), r.text[:200])
    check(f"{label}: nothing recorded", not usage_rows(fake))
    warned = [line for line in captured.lines if event in line]
    check(f"{label}: a warning is logged", len(warned) == 1, str(captured.lines))
    check(f"{label}: naming only the error type, not the refused row",
          warned and "check constraint" not in warned[0] and "Refused" in warned[0], str(warned))

print("\nrecord_import never raises, whatever the client does")
for broken in (None, object(), FakeSupabase({}, schema_old=True)):
    try:
        usage.record_import(broken, "user-1", None, usage.IMPORT_ROSTER_PASTE, "m", 1, 2)
        check(f"no exception from {type(broken).__name__}", True)
    except Exception as e:
        check(f"no exception from {type(broken).__name__}", False, repr(e))

print("\nA callback that throws can't fail the import either")
fresh()
out = claude_service.parse_crew_import("pasted", lambda *_a: 1 / 0)
check("the parse still returns its people", len(out) == len(PASTED), str(out)[:200])


# ── Roster paste: the same verdict as the call sheet upload ─────────────────

print("\nThe Roster paste preview says what each row already is")
fresh()
r = http.post("/api/roster/import/parse", json={"text": "pasted", "type": "crew"})
members = {m["name"]: m for m in r.json()["members"]}
check("every row carries match_state", all("match_state" in m for m in members.values()), str(members)[:300])
check("every row is typed as the tab it was pasted on", all(m.get("type") == "crew" for m in members.values()))
roz = members["Rosalind Achebe-Hart"]
check("a saved crew member is found by email under a different name",
      roz["match_state"] == "in_roster" and roz["match_name"] == "Rosalind Hart" and roz["match_id"] == "r-crew",
      str(roz))
check("and says which fields differ", [d["field"] for d in roz["differs"]] == [], str(roz["differs"]))
check("two saved entries sharing the details -> Possible match",
      members["Sam Lee"]["match_state"] == "ambiguous", str(members["Sam Lee"]))
check("a client entry never matches a crew paste",
      members["Kit Oyelaran"]["match_state"] == "new", str(members["Kit Oyelaran"]))
check("another producer's Roster is never consulted",
      members["Priya Venkataraman"]["match_state"] == "new", str(members["Priya Venkataraman"]))
check("someone nobody has saved is New", members["Devon New"]["match_state"] == "new")

fresh()
r = http.post("/api/roster/import/parse", json={"text": "pasted", "type": "client"})
kit = {m["name"]: m for m in r.json()["members"]}["Kit Oyelaran"]
check("pasted on the Clients tab, the same person IS found", kit["match_state"] == "in_roster", str(kit))
check("and a differing role is reported", [d["field"] for d in kit["differs"]] == ["role"], str(kit["differs"]))

print("\nA classification failure never costs the producer the parse")
fake = fresh()
fake.broken_tables.add("roster")
r = http.post("/api/roster/import/parse", json={"text": "pasted", "type": "crew"})
check("still 200", r.status_code == 200, f"{r.status_code} {r.text[:200]}")
check("with every row, unannotated", len(r.json()["members"]) == len(PASTED)
      and not any("match_state" in m for m in r.json()["members"]), r.text[:300])
people = [{"name": "A", "type": "crew"}]
check("classify_against_roster returns its input on failure",
      classify_against_roster(fake, people, {"user-1"}) == people)


# ── usage_stats: measured import spend beside the assumed generation rate ───

print("\nusage_stats: measured import spend")
now = datetime.now(timezone.utc)
recent = (now - timedelta(days=1)).isoformat()
old = (now - timedelta(days=60)).isoformat()
User = type("User", (), {})
u1, u2 = User(), User()
u1.id, u1.email, u1.created_at, u1.last_sign_in_at = "user-1", "a@example.com", recent, recent
u2.id, u2.email, u2.created_at, u2.last_sign_in_at = "user-2", "b@example.com", recent, recent
db = {
    "_users": [u1, u2], "projects": [], "call_sheets": [], "crew_members": [], "project_contacts": [],
    "usage_events": [
        {"user_id": "user-1", "event_type": "call_sheet_generated", "recipient_count": None, "created_at": recent},
        {"user_id": "user-1", "event_type": "import_roster_call_sheet", "created_at": recent,
         "model": "claude-sonnet-4-6", "input_tokens": 1_000_000, "output_tokens": 100_000},
        {"user_id": "user-2", "event_type": "import_crew_paste", "created_at": recent,
         "model": "claude-sonnet-4-6", "input_tokens": 2_000, "output_tokens": 1_000},
        {"user_id": "user-2", "event_type": "import_crew_paste", "created_at": recent,
         "model": "some-future-model", "input_tokens": 5_000, "output_tokens": 5_000},
        {"user_id": "user-1", "event_type": "import_talent_paste", "created_at": old,
         "model": "claude-sonnet-4-6", "input_tokens": 9_999_999, "output_tokens": 9_999_999},
    ],
}
data = usage_stats.collect(FakeSupabase(db), days=7)
t = data["totals"]
check("three imports in the window (the 60-day-old one is out)", t["imports"] == 3, str(t["imports"]))
# 1M in x $3 + 100k out x $15 = $4.50; 2k x $3 + 1k x $15 per 1M = $0.021
check("measured spend is tokens x the published price", abs(t["import_cost_usd"] - 4.521) < 1e-9,
      str(t["import_cost_usd"]))
check("the rate is returned beside the total", t["import_prices"] == [
    {"model": "claude-sonnet-4-6", "input_per_mtok_usd": 3.0, "output_per_mtok_usd": 15.0}], str(t["import_prices"]))
check("an unpriced model is counted but not guessed at",
      t["import_unpriced"] == 1 and t["import_models_unpriced"] == ["some-future-model"], str(t))
by = {s["event_type"]: s for s in t["import_by_source"]}
check("broken down by which import", by["import_crew_paste"]["count"] == 2
      and by["import_roster_call_sheet"]["count"] == 1 and by["import_talent_paste"]["count"] == 0)
check("the flat-rate generation figure is untouched",
      t["generates"] == 1 and t["estimated_cost_usd"] == usage_stats.COST_PER_GENERATION_USD
      and t["cost_rate_usd"] == usage_stats.COST_PER_GENERATION_USD, str(t))
check("imports are not counted as sends", t["sends"] == 0 and t["emails"] == 0)
accounts = {a["email"]: a for a in data["accounts"]}
check("per-account import counts", accounts["a@example.com"]["imports"] == 1
      and accounts["b@example.com"]["imports"] == 2)
check("the daily chart counts imports", sum(d["imports"] for d in data["daily"]) == 3)

print("\nusage_stats before the migration: the event log still loads")
data = usage_stats.collect(FakeSupabase({**db, "usage_events": db["usage_events"][:1]}, schema_old=True), days=7)
check("event log available (fell back to the old columns)", data["event_log"]["available"])
check("generations still counted", data["totals"]["generates"] == 1)
check("imports read zero", data["totals"]["imports"] == 0 and data["totals"]["import_cost_usd"] == 0)

print()
print(f"{len(FAILS)} FAILURES: {', '.join(FAILS)}" if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
