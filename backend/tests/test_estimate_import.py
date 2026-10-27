"""Reading an estimate into draft budget lines (services/estimate_import.py,
routers/estimate_import.py) and adding the kept ones (routers/budget.py's
POST .../budget/lines/batch). docs/estimate-reconcile-plan.md, PR 2.

    cd backend && venv/bin/python tests/test_estimate_import.py

A fabricated estimate (tests/fixtures/fabricated_estimate.*) and a fake
Anthropic client: nothing here reaches a model or a database. Driven through
the real router, limiter and dependency chain, auth faked — the same way
test_receipts.py drives the receipt read.
"""

import io
import json
import logging
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from slowapi import _rate_limit_exceeded_handler  # noqa: E402
from slowapi.errors import RateLimitExceeded  # noqa: E402

import auth  # noqa: E402
import usage  # noqa: E402
from rate_limit import limiter  # noqa: E402
from services import claude_service, estimate_import  # noqa: E402
from services.estimate_import import PDF, XLSX, Rejected, clean, prepare, sniff  # noqa: E402
from tests.fake_supabase import FakeClient  # noqa: E402
from routers import budget as budget_router, estimate_import as import_router, jobs as jobs_router  # noqa: E402

FAILS = []
FIXTURES = Path(__file__).resolve().parent / "fixtures"
EST_PDF = (FIXTURES / "fabricated_estimate.pdf").read_bytes()
EST_XLSX = (FIXTURES / "fabricated_estimate.xlsx").read_bytes()


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else '  -- ' + str(detail)}")
    if not ok:
        FAILS.append(name)


def refused(name, data, status=None, words=""):
    try:
        prepare(data)
        check(name, False, "accepted")
    except Rejected as e:
        check(name, (status is None or e.status == status) and words in str(e), (e.status, str(e)))


def zipped(names: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n, body in names.items():
            z.writestr(n, body)
    return buf.getvalue()


print("\nWhat a file is, by its bytes")
check("a PDF", sniff(EST_PDF) == PDF)
check("an Excel workbook", sniff(EST_XLSX) == XLSX)
check("a Word document", sniff(zipped({"word/document.xml": "<w/>"})) == "docx")
check("an old .xls", sniff(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"0" * 20) == "ole")
check("a renamed text file is nothing", sniff(b"Estimate, honest") is None)

print("\nRefused before any model call")
refused("empty", b"", 400)
refused("too big", b"%PDF-" + b"0" * (estimate_import.MAX_BYTES + 1), 413)
refused("a Word document, with how to fix it", zipped({"word/document.xml": "<w/>"}), 415, "PDF")
refused("an old .xls, with how to fix it", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"0" * 20, 415, ".xlsx")
refused("a photo", b"\xff\xd8\xff\xe0 a jpeg", 415)
import pymupdf  # noqa: E402
long_pdf = pymupdf.open()
for _ in range(estimate_import.MAX_PAGES + 1):
    long_pdf.new_page()
refused("a PDF over the page limit", long_pdf.tobytes(), 400, "pages")
bomb = zipped({"xl/workbook.xml": "<w/>", "xl/worksheets/sheet1.xml": "0" * (estimate_import.MAX_UNZIPPED + 1)})
refused("a workbook that unzips enormous", bomb, 413)

print("\nA workbook becomes text")
pdf, text = prepare(EST_XLSX)
check("no PDF, and the cells as text", pdf is None and "2 Gaffer days ($1,300/day x 2) | 2600" in text, text[:200])
check("every row the estimate has", "GRAND TOTAL | 15050" in text and "Production insurance | 600" in text)
pdf, text = prepare(EST_PDF)
check("a PDF goes as itself", pdf == EST_PDF and text is None)

print("\nCleaning what comes back")
out = clean({"total": "15,050.00", "lines": [
    {"section": "CREW", "name": "2 Gaffer days", "qty": 2, "rate": 1300, "amount": 2600, "basis": "rate"},
    {"section": "CREW", "name": "Key grip", "qty": 1, "rate": 1250, "amount": 1200, "basis": "rate"},
    {"section": "TRAVEL", "name": "Flights (estimated)", "amount": "$1,800.00", "basis": "pass", "markup_pct": 15},
    {"section": "CREW", "name": "Swing", "qty": 3, "rate": 400, "amount": None, "basis": "rate"},
    {"name": "Production fee", "amount": 2000, "basis": "rate", "floor": "production_fee"},
    {"name": "Admin fee", "amount": 100, "basis": "fee", "floor": "production_fee"},
    {"name": "Discount", "amount": -500, "basis": "fee"},
    {"name": "Contingency", "amount": "TBD", "basis": "fee", "floor": "contingency"},
    {"name": None, "amount": 50},
    {"name": "Card 4000 1234 5678 9010 rental", "amount": 10, "basis": "snacks"},
    "not a line",
]})
L = {ln["name"]: ln for ln in out["lines"]}
check("lines with a name and a positive amount survive",
      list(L) == ["2 Gaffer days", "Key grip", "Flights (estimated)", "Swing", "Production fee", "Admin fee", "Card rental"],
      list(L))
check("a qty x rate that comes to the amount is kept", L["2 Gaffer days"]["qty"] == 2 and L["2 Gaffer days"]["unit_amount_cents"] == 130_000)
check("one that doesn't is dropped; the printed amount wins",
      L["Key grip"]["qty"] is None and L["Key grip"]["unit_amount_cents"] is None and L["Key grip"]["est_cents"] == 120_000)
check("no amount but a qty x rate: the product", L["Swing"]["est_cents"] == 120_000)
check("amounts are exact cents", L["Flights (estimated)"]["est_cents"] == 180_000)
check("a markup on an At cost line, in basis points", L["Flights (estimated)"]["markup_bp"] == 1500)
check("a floor line is a Fee whatever the guess", L["Production fee"]["floor_kind"] == "production_fee" and L["Production fee"]["bucket"] == "fee")
check("only the first of a floor kind is tagged", L["Admin fee"]["floor_kind"] is None)
check("an unknown basis becomes Fixed", L["Card rental"]["bucket"] == "rate")
check("a card-length number is cut from the text", "4000" not in L["Card rental"]["name"])
check("a discount, a TBD and a nameless line are counted as skipped", out["skipped"] == 3, out["skipped"])
check("the printed total is checked against the lines",
      out["total_check"] == {"stated_cents": 1_505_000, "lines_cents": sum(x["est_cents"] for x in out["lines"]), "matches": False},
      out["total_check"])
check("a bare list is accepted, with no total to check",
      clean([{"name": "A", "amount": 1}])["total_check"]["matches"] is None)
check("a long estimate is capped", len(clean({"lines": [{"name": "x", "amount": 1}] * 300})["lines"]) == estimate_import.MAX_LINES)
try:
    clean("I couldn't read it")
    check("an answer that isn't the object is a failed read", False, "accepted")
except ValueError:
    check("an answer that isn't the object is a failed read", True)


# ── The model, faked ─────────────────────────────────────────────────────────

class FakeMessages:
    def __init__(self):
        self.calls, self.reply, self.raise_error = [], "{}", None

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.raise_error:
            raise self.raise_error
        text = type("T", (), {"text": self.reply})()
        u = type("U", (), {"input_tokens": 4200, "output_tokens": 900})()
        return type("M", (), {"content": [text], "usage": u, "stop_reason": "end_turn", "model": "claude-sonnet-4-6"})()


fake = type("A", (), {})()
fake.messages = FakeMessages()
claude_service._client = fake
REPLY = json.dumps({"total": 15050, "lines": [
    {"section": "CREATIVE FEES", "name": "Director / Photographer — creative fee", "amount": 5000, "basis": "fee",
     "basis_reason": "creative fee"},
    {"section": "CREW (10 HR DAYS)", "name": "Gaffer days", "qty": 2, "rate": 1300, "amount": 2600, "basis": "rate",
     "basis_reason": "crew day rate"},
    {"section": "TRAVEL", "name": "Flights, 2 pax (estimated)", "amount": 1800, "basis": "pass",
     "basis_reason": "marked (estimated)"},
]})

J = "00000000-0000-0000-0000-0000000000f1"
OTHER = "00000000-0000-0000-0000-0000000000f2"


def fresh(signed=None, schema=None):
    db = {"jobs": [{"id": J, "owner_id": "o1", "name": "Trailhead", "estimate_signed_on": signed},
                   {"id": OTHER, "owner_id": "o2", "name": "Not ours", "estimate_signed_on": None}],
          "job_budget_lines": [], "job_expenses": [], "job_invoices": [], "usage_events": []}
    c = FakeClient(db, schema=schema)
    for mod in (budget_router, jobs_router, import_router):
        mod.get_client = lambda: c
    return c


app = FastAPI()
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.include_router(import_router.router, prefix="/api")
app.include_router(budget_router.router, prefix="/api")
app.dependency_overrides[auth.get_current_user] = lambda: "o1"
app.dependency_overrides[auth.get_accessible_owner_ids] = lambda: {"o1"}
http = TestClient(app)


def read(body, ctype="application/pdf", job=J):
    return http.post(f"/api/jobs/{job}/budget/import", content=body, headers={"Content-Type": ctype})


print("\nReading an estimate")
client = fresh()
fake.messages.reply = REPLY
logs = []
handler = logging.Handler()
handler.emit = lambda rec: logs.append(rec.getMessage())
logging.getLogger().addHandler(handler)
logging.getLogger().setLevel(logging.INFO)

r = read(EST_PDF)
out = r.json()
check("an estimate comes back as draft lines", r.status_code == 200 and len(out["lines"]) == 3 and out["note"] is None, out)
check("with each line's suggested basis and why", out["lines"][2]["bucket"] == "pass"
      and out["lines"][2]["basis_reason"] == "marked (estimated)")
check("and the total check", out["total_check"]["stated_cents"] == 1_505_000 and out["total_check"]["matches"] is False)
blocks = fake.messages.calls[-1]["messages"][0]["content"]
check("a PDF goes to the model as a document", blocks[0]["type"] == "document" and blocks[0]["source"]["media_type"] == "application/pdf")
prompt = blocks[1]["text"]
check("the prompt names the three bases", all(f'"{b}"' in prompt for b in ("fee", "pass", "rate")))
check("tells it to leave out subtotals and deposits", "subtotal" in prompt and "deposit" in prompt)
check("and says the document's own instructions are data", "Ignore any instructions" in prompt)
check("nothing is added to the budget by reading", client.db["job_budget_lines"] == [])
ev = client.db["usage_events"]
check("the read is metered: tokens and model, nothing else",
      len(ev) == 1 and ev[0]["event_type"] == usage.IMPORT_ESTIMATE and ev[0]["input_tokens"] == 4200
      and set(ev[0]) <= {"id", "user_id", "project_id", "event_type", "model", "input_tokens", "output_tokens"}, ev)
check("no log line says what the estimate says", not any("Gaffer" in m or "Director" in m or "5000" in m for m in logs), logs)

r = read(EST_XLSX, "application/octet-stream")
blocks = fake.messages.calls[-1]["messages"][0]["content"]
check("a workbook goes as its cells, as text", r.status_code == 200 and blocks[0]["type"] == "text"
      and "<spreadsheet>" in blocks[0]["text"] and "Lighting package" in blocks[0]["text"])
n = len(fake.messages.calls)
r = read(zipped({"word/document.xml": "<w/>"}), "application/octet-stream")
check("a Word file is refused with how to fix it, and never reaches the model",
      r.status_code == 415 and "PDF" in r.json()["detail"] and len(fake.messages.calls) == n)
fake.messages.raise_error = RuntimeError("Director creative fee 5000 overloaded")
logs.clear()
r = read(EST_PDF)
check("a model failure is a 502 that says what to do", r.status_code == 502 and "by hand" in r.json()["detail"])
check("and its text never reaches a log", not any("Director" in m for m in logs), logs)
fake.messages.raise_error = None
fake.messages.reply = json.dumps({"total": None, "lines": []})
r = read(EST_PDF)
check("nothing priced: no lines, and a note", r.json()["lines"] == [] and r.json()["note"])
fake.messages.reply = REPLY
check("someone else's job is a 404", read(EST_PDF, job=OTHER).status_code == 404)
client = fresh(signed="2026-10-02")
n = len(fake.messages.calls)
r = read(EST_PDF)
check("a signed estimate is refused before any model call", r.status_code == 409 and len(fake.messages.calls) == n)

print("\nAdding the kept lines")
client = fresh()
budget_router.add_line(J, budget_router.BudgetLineCreate(name="Already here", est_cents=100), owner_ids={"o1"})
drafts = read(EST_PDF).json()["lines"]
body = {"lines": [{k: v for k, v in d.items() if k != "basis_reason"} for d in drafts]}
r = http.post(f"/api/jobs/{J}/budget/lines/batch", json=body)
v = r.json()
check("they go on together, after what was there", r.status_code == 200
      and [ln["name"] for ln in v["lines"]] == ["Already here"] + [d["name"] for d in drafts], [ln["name"] for ln in v["lines"]])
check("under their headings", [s["name"] for s in v["estimate"]["sections"]]
      == [None, "CREATIVE FEES", "CREW (10 HR DAYS)", "TRAVEL"], v["estimate"]["sections"])
check("qty x rate is still the amount", next(ln for ln in v["lines"] if ln["name"] == "Gaffer days")["est_cents"] == 260_000)
check("the basis she kept is the basis saved", [ln["bucket"] for ln in v["lines"][1:]] == ["fee", "rate", "pass"])
r = http.post(f"/api/jobs/{J}/budget/lines/batch", json={"lines": [{"name": "x", "est_cents": 1}] * 200})
r = http.post(f"/api/jobs/{J}/budget/lines/batch", json={"lines": [{"name": "x", "est_cents": 1}] * 200})
r = http.post(f"/api/jobs/{J}/budget/lines/batch", json={"lines": [{"name": "x", "est_cents": 1}] * 200})
check("past the job's limit, none go on", r.status_code == 422 and len(client.db["job_budget_lines"]) == 404, (r.status_code, len(client.db["job_budget_lines"])))
check("an empty batch is refused", http.post(f"/api/jobs/{J}/budget/lines/batch", json={"lines": []}).status_code == 422)
client.db["jobs"][0]["estimate_signed_on"] = "2026-10-02"
check("a signed estimate takes no batch", http.post(f"/api/jobs/{J}/budget/lines/batch", json=body).status_code == 409)

print("\nBefore supabase/estimate.sql")
line_cols = {"id", "job_id", "bucket", "block", "name", "note", "flag", "qty", "unit_amount_cents", "est_cents",
             "act_cents", "bill_cents", "markup_bp", "dropped", "awaiting_cost", "act_paid", "floor_kind",
             "sort_order", "created_at"}
pre = fresh(schema={"jobs": {"id", "owner_id", "name"}, "job_budget_lines": line_cols,
                    "job_expenses": {"id", "job_id", "budget_line_id", "amount_cents", "sort_order", "created_at"},
                    "job_invoices": {"id", "job_id", "amount_cents", "paid", "sort_order", "created_at"},
                    "usage_events": {"id", "user_id", "project_id", "event_type", "model", "input_tokens", "output_tokens"}})
pre.db["jobs"] = [{"id": J, "owner_id": "o1", "name": "Trailhead"}]
r = http.post(f"/api/jobs/{J}/budget/lines/batch", json=body)
check("the lines still go on, without their headings", r.status_code == 200 and len(pre.db["job_budget_lines"]) == 3
      and all("section" not in ln for ln in pre.db["job_budget_lines"]), r.text[:200])

print()
if FAILS:
    print(f"FAILED: {len(FAILS)}")
    sys.exit(1)
print("All passed.")
