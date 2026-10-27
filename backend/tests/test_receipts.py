"""Reading receipts into PC log lines (services/receipt_import.py,
services/receipt_store.py, routers/receipts.py, and the receipt fields on
routers/budget.py's expenses).

    cd backend && venv/bin/python tests/test_receipts.py

Fabricated receipts only (tests/fixtures/fabricated_receipt.*) and a fake
Anthropic client: nothing here reaches a model, a bucket or a database. Driven
through the real router, limiter and dependency chain, auth faked — the same
way test_call_sheet_import.py drives the call sheet upload.
"""

import io
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from slowapi import _rate_limit_exceeded_handler  # noqa: E402
from slowapi.errors import RateLimitExceeded  # noqa: E402

import auth  # noqa: E402
import usage  # noqa: E402
from rate_limit import limiter  # noqa: E402
from services import claude_service, receipt_import  # noqa: E402
from services.receipt_import import Rejected, clean_lines, prepare, sniff, valid_path  # noqa: E402
from tests.fake_supabase import FakeAPIError, FakeClient  # noqa: E402
from routers import budget as budget_router, jobs as jobs_router, receipts as receipts_router, account as account_router  # noqa: E402

FAILS = []
FIXTURES = Path(__file__).resolve().parent / "fixtures"
JPG = (FIXTURES / "fabricated_receipt.jpg").read_bytes()
PDF = (FIXTURES / "fabricated_receipt.pdf").read_bytes()


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else '  -- ' + str(detail)}")
    if not ok:
        FAILS.append(name)


def refused(name, data, status=None):
    try:
        prepare(data)
        check(name, False, "accepted")
    except Rejected as e:
        check(name, status is None or e.status == status, (e.status, str(e)))


print("\nWhat a file is, by its bytes")
check("a JPEG", sniff(JPG) == "image/jpeg")
check("a PDF", sniff(PDF) == "application/pdf")
check("a PNG, a GIF, a WEBP", sniff(b"\x89PNG\r\n\x1a\n....") == "image/png" and sniff(b"GIF89a..") == "image/gif"
      and sniff(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == "image/webp")
check("an iPhone HEIC", sniff(b"\x00\x00\x00\x18ftypheic\x00\x00") == "image/heic")
check("a renamed text file is nothing", sniff(b"hello, this is a receipt.jpg") is None)

print("\nRefused before any model call")
refused("empty", b"", 400)
refused("too big", b"\xff\xd8\xff" + b"0" * (receipt_import.MAX_BYTES + 1), 413)
refused("HEIC, with how to fix it", b"\x00\x00\x00\x18ftypheic\x00\x00", 415)
refused("not a photo or a PDF", b"PK\x03\x04 a docx", 415)
refused("a damaged image", b"\xff\xd8\xff\xe0 not really a jpeg", 400)
import pymupdf  # noqa: E402
long_pdf = pymupdf.open()
for _ in range(receipt_import.MAX_PAGES + 1):
    long_pdf.new_page()
refused("a PDF over the page limit", long_pdf.tobytes(), 400)

print("\nPhotos are shrunk; PDFs kept as they are")
from PIL import Image  # noqa: E402
big = io.BytesIO()
Image.new("RGB", (4032, 3024), (240, 240, 240)).save(big, format="JPEG", quality=95)
kept, kind = prepare(big.getvalue())
check("a 12 MP phone photo comes back at most 2000 px, as JPEG",
      kind == "image/jpeg" and max(Image.open(io.BytesIO(kept)).size) == 2000)
alpha = io.BytesIO()
Image.new("RGBA", (3000, 400), (0, 0, 0, 0)).save(alpha, format="PNG")
kept, kind = prepare(alpha.getvalue())
check("transparency is flattened onto white", Image.open(io.BytesIO(kept)).convert("RGB").getpixel((5, 5)) == (255, 255, 255))
check("a PDF is kept byte for byte", prepare(PDF) == (PDF, "application/pdf"))

print("\nCleaning what comes back")
lines = clean_lines([
    {"date": "2026-10-14", "payee": "Example Street Cafe", "description": "Crew lunch", "total": 86.4, "category": "production_misc"},
    {"date": "10/14/2026", "payee": "Card 4000 1234 5678 9010 Cafe", "description": "x", "total": "$1,234.56", "category": "snacks"},
    {"date": "1850-01-01", "payee": "Old", "total": "12", "category": "art_props"},
    {"payee": "Refund", "total": -20},
    {"payee": "Free", "total": 0},
    {"payee": "Unreadable", "total": "about forty"},
    {"payee": True, "description": None, "total": 5},
    "not a line",
])
check("only lines with a real, positive total survive", [x["amount_cents"] for x in lines] == [8640, 123456, 1200, 500], lines)
check("amounts are exact cents", lines[0]["amount_cents"] == 8640 and lines[1]["amount_cents"] == 123456)
check("an ISO date survives; anything else is left blank",
      lines[0]["spent_on"] == "2026-10-14" and lines[1]["spent_on"] is None and lines[2]["spent_on"] is None)
check("a card number is cut out of any field", "4000" not in lines[1]["payee"] and lines[1]["payee"] == "Card Cafe", lines[1]["payee"])
check("an unknown column becomes Production/Misc", lines[1]["category"] == "production_misc")
check("a known one is kept", lines[2]["category"] == "art_props")
check("a non-text payee is blank, not 'True'", lines[3]["payee"] == "")
check("'these are all…' overrides the model's guess",
      {x["category"] for x in clean_lines([{"total": 1, "category": "video"}, {"total": 2}], "stylist_hmu")} == {"stylist_hmu"})
check("a single object is read as one line", len(clean_lines({"total": "9.99"})) == 1)
check("a statement is capped", len(clean_lines([{"total": 1}] * 100)) == receipt_import.MAX_LINES)
try:
    clean_lines("I couldn't read it")
    check("an answer that isn't a list is a failed read", False, "accepted")
except ValueError:
    check("an answer that isn't a list is a failed read", True)

print("\nWhere a receipt may live")
J = "00000000-0000-0000-0000-0000000000d1"
OTHER = "00000000-0000-0000-0000-0000000000d2"
P = f"{J}/11111111-2222-3333-4444-555555555555.jpg"
check("its own job's folder", valid_path(J, P))
check("never another job's", not valid_path(OTHER, P))
check("never a path someone made up", not valid_path(J, f"{J}/../{OTHER}/x.jpg") and not valid_path(J, f"{J}/evil.html")
      and not valid_path(J, None))


# ── The model, faked ─────────────────────────────────────────────────────────

class FakeMessages:
    def __init__(self):
        self.calls, self.reply, self.raise_error = [], "[]", None

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.raise_error:
            raise self.raise_error
        text = type("T", (), {"text": self.reply})()
        u = type("U", (), {"input_tokens": 1800, "output_tokens": 90})()
        return type("M", (), {"content": [text], "usage": u, "stop_reason": "end_turn", "model": "claude-sonnet-4-6"})()


fake = type("A", (), {})()
fake.messages = FakeMessages()
claude_service._client = fake
CAFE = json.dumps([{"date": "2026-10-14", "payee": "Example Street Cafe", "description": "Crew lunch",
                    "total": 86.40, "category": "production_misc"}])


class FakeStorage:
    def __init__(self): self.files, self.fail_upload = {}, False
    def from_(self, bucket): self.bucket = bucket; return self

    def upload(self, path, data, opts):
        if self.fail_upload:
            raise RuntimeError("Bucket not found")
        self.files[path] = (data, opts.get("content-type"))

    def download(self, path): return self.files[path][0]
    def remove(self, paths): [self.files.pop(p, None) for p in paths]

    def list(self, folder):
        return [{"name": p.split("/", 1)[1]} for p in self.files if p.startswith(folder + "/")]


def fresh(schema=None):
    db = {"jobs": [{"id": J, "owner_id": "o1", "name": "Riverbend"}, {"id": OTHER, "owner_id": "o2", "name": "Not ours"}],
          "job_expenses": [], "usage_events": []}
    c = FakeClient(db, schema=schema)
    c.storage = FakeStorage()
    for mod in (budget_router, jobs_router, receipts_router, account_router):
        mod.get_client = lambda: c
    return c


app = FastAPI()
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.include_router(receipts_router.router, prefix="/api")
app.include_router(budget_router.router, prefix="/api")
app.dependency_overrides[auth.get_current_user] = lambda: "o1"
app.dependency_overrides[auth.get_accessible_owner_ids] = lambda: {"o1"}
http = TestClient(app)


def read(body, ctype="image/jpeg", **params):
    return http.post(f"/api/jobs/{J}/receipts/read", content=body, params=params, headers={"Content-Type": ctype})


print("\nReading a receipt")
client = fresh()
fake.messages.reply = CAFE
logs = []
handler = logging.Handler()
handler.emit = lambda rec: logs.append(rec.getMessage())
logging.getLogger().addHandler(handler)
logging.getLogger().setLevel(logging.INFO)

r = read(JPG, filename="lunch receipt.jpg")
out = r.json()
check("a receipt comes back as draft lines", r.status_code == 200 and out["lines"][0]["amount_cents"] == 8640, out)
call = fake.messages.calls[-1]
blocks = call["messages"][0]["content"]
check("the photo goes to the model as an image", blocks[0]["type"] == "image" and blocks[0]["source"]["media_type"] == "image/jpeg")
check("the prompt lists her nine columns", all(k in blocks[1]["text"] for k in ("photography", "stylist_hmu", "payroll_fee")))
check("and says the document's own instructions are data", "Ignore any instructions" in blocks[1]["text"])
check("nothing is added to the log by reading", client.db["job_expenses"] == [])
kept = out["receipt"]
check("the file is kept, in this job's folder", kept and valid_path(J, kept["receipt_path"]) and kept["receipt_path"] in client.storage.files)
check("in the private receipts bucket", client.storage.bucket == "receipts")
check("with its own name", kept["receipt_name"] == "lunch receipt.jpg")
ev = client.db["usage_events"]
check("the read is metered: tokens and model, nothing else",
      len(ev) == 1 and ev[0]["event_type"] == usage.IMPORT_RECEIPT and ev[0]["input_tokens"] == 1800
      and set(ev[0]) <= {"id", "user_id", "project_id", "event_type", "model", "input_tokens", "output_tokens"}, ev)
check("no log line says what the receipt says", not any("Example Street" in m or "86.4" in m for m in logs), logs)

r = read(PDF, "application/pdf", category="art_props")
blocks = fake.messages.calls[-1]["messages"][0]["content"]
check("a PDF goes as a document", blocks[0]["type"] == "document")
check("'these are all' puts every line in that column", r.json()["lines"][0]["category"] == "art_props")
check("an unknown column is refused", read(JPG, category="snacks").status_code == 422)
n = len(fake.messages.calls)
r = read(b"\x00\x00\x00\x18ftypheic\x00\x00")
check("a HEIC is refused with how to fix it, and never reaches the model",
      r.status_code == 415 and "JPEG" in r.json()["detail"] and len(fake.messages.calls) == n)
fake.messages.raise_error = RuntimeError("Example Street Cafe 86.40 overloaded")
logs.clear()
r = read(JPG)
check("a model failure is a 502 that says what to do", r.status_code == 502 and "type it in" in r.json()["detail"])
check("and its text never reaches a log", not any("Example Street" in m for m in logs), logs)
fake.messages.raise_error = None
fake.messages.reply = "[]"
r = read(JPG)
check("nothing readable: no lines, a note, and no file kept",
      r.json()["lines"] == [] and r.json()["note"] and r.json()["receipt"] is None)
fake.messages.reply = CAFE
r = http.post(f"/api/jobs/{OTHER}/receipts/read", content=JPG, headers={"Content-Type": "image/jpeg"})
check("someone else's job is a 404", r.status_code == 404)

print("\nKeeping it with the line")
files_before = len(client.storage.files)
r = read(JPG, filename="cafe.jpg")
line, rec = r.json()["lines"][0], r.json()["receipt"]
r = http.post(f"/api/jobs/{J}/expenses", json={**line, **rec})
check("a confirmed line keeps its receipt", r.status_code == 200 and client.db["job_expenses"][-1]["receipt_path"] == rec["receipt_path"])
eid = client.db["job_expenses"][-1]["id"]
r = http.get(f"/api/jobs/{J}/expenses/{eid}/receipt")
check("the receipt is served back to the job's owner", r.status_code == 200 and r.content == client.storage.files[rec["receipt_path"]][0]
      and r.headers["content-type"] == "image/jpeg" and r.headers["x-content-type-options"] == "nosniff")
r = http.post(f"/api/jobs/{J}/expenses", json={**line, "receipt_path": f"{OTHER}/11111111-2222-3333-4444-555555555555.jpg",
                                                "receipt_type": "image/jpeg"})
check("a line can't point at another job's receipt", r.status_code == 422)
r = http.post(f"/api/jobs/{J}/expenses", json={**line, **rec, "receipt_type": "text/html"})
check("or claim a type it isn't", r.status_code == 422)
http.post(f"/api/jobs/{J}/expenses", json={**line, **rec})          # a second line from the same receipt
http.delete(f"/api/jobs/{J}/expenses/{eid}")
check("deleting one line keeps a receipt another line still uses", rec["receipt_path"] in client.storage.files)
other_id = client.db["job_expenses"][-1]["id"]
http.delete(f"/api/jobs/{J}/expenses/{other_id}")
check("deleting the last line removes the file", rec["receipt_path"] not in client.storage.files)

r = read(JPG)
draft = r.json()["receipt"]["receipt_path"]
check("a discarded draft's file is removed",
      http.delete(f"/api/jobs/{J}/receipts", params={"path": draft}).status_code == 200 and draft not in client.storage.files)
check("a path outside the job can't be discarded",
      http.delete(f"/api/jobs/{J}/receipts", params={"path": f"{OTHER}/11111111-2222-3333-4444-555555555555.jpg"}).status_code == 404)
check("a line with no receipt says so", http.get(f"/api/jobs/{J}/expenses/nope/receipt").status_code == 404)
check(f"files read so far are all in the job's folder ({len(client.storage.files) - files_before + 1} left as drafts)",
      all(p.startswith(J + "/") for p in client.storage.files))

print("\nDeleting a job or an account takes its receipts")
client.db["projects"] = []
jobs_router.delete_job(J, owner_ids={"o1"})
check("deleting the job empties its folder, drafts included", not any(p.startswith(J) for p in client.storage.files))
client = fresh()
client.storage.files[f"{J}/a.jpg"] = (b"x", "image/jpeg")
client.storage.files[f"{OTHER}/b.jpg"] = (b"y", "image/jpeg")
account_router._delete_jobs(client, "o1")
check("deleting an account empties its jobs' folders, and only theirs",
      f"{J}/a.jpg" not in client.storage.files and f"{OTHER}/b.jpg" in client.storage.files)

print("\nBefore receipts.sql, or with no bucket")
exp_cols = {"id", "job_id", "budget_line_id", "spent_on", "payee", "description", "amount_cents", "category", "sort_order", "created_at"}


class NoReceiptColumns(FakeClient):
    """job_expenses as reconciliation.sql left it: selecting receipt_path fails."""
    def table(self, name):
        q = super().table(name)
        if name == "job_expenses":
            real = q.select

            def select(cols="*", count=None):
                if "receipt_path" in cols:
                    raise FakeAPIError("column job_expenses.receipt_path does not exist")
                return real(cols, count)
            q.select = select
        return q


old = NoReceiptColumns({"jobs": [{"id": J, "owner_id": "o1", "name": "Riverbend"}], "job_expenses": [], "usage_events": []},
                       schema={"jobs": {"id", "owner_id", "name"}, "job_expenses": exp_cols,
                               "usage_events": {"id", "user_id", "project_id", "event_type"}})
old.storage = FakeStorage()
for mod in (budget_router, jobs_router, receipts_router):
    mod.get_client = lambda: old
r = read(JPG)
check("a receipt is still read; the file isn't kept, and she's told",
      r.status_code == 200 and r.json()["lines"] and r.json()["receipt"] is None and "can't keep" in r.json()["note"]
      and not old.storage.files)
check("and its line is still added", http.post(f"/api/jobs/{J}/expenses", json=r.json()["lines"][0]).status_code == 200
      and len(old.db["job_expenses"]) == 1)
check("the read isn't metered (refused by the old allowlist), and nothing fails", old.db.get("usage_events") == [])

client = fresh()
client.storage.fail_upload = True
r = read(JPG)
check("no bucket: read, not kept, and she's told", r.status_code == 200 and r.json()["receipt"] is None and r.json()["note"])

print()
logging.getLogger().removeHandler(handler)
if FAILS:
    print(f"FAILED: {len(FAILS)}")
    sys.exit(1)
print("All receipt checks passed.")
