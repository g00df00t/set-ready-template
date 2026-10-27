"""The client Production Reconciliation statement (services/reconciliation_
statement.py, its template, and the two routes in routers/budget.py).
docs/estimate-reconcile-plan.md, PR 4.

    cd backend && venv/bin/python tests/test_reconciliation_statement.py

Checked against the real reference job (tests/fixtures/reference_job_v7.json):
the statement Patrick sent that client is the v7 job without its $750 retouching
line, and its figures were original 66,370.00, reduction -20,548.58, revised
45,821.42, final invoice 12,636.42 after the 33,185.00 deposit.
"""

import json
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import HTTPException  # noqa: E402

from services import budget, reconciliation_statement as st  # noqa: E402
from tests.fake_supabase import FakeClient  # noqa: E402
from routers import budget as budget_router, jobs as jobs_router  # noqa: E402
from models.budget import StatementSettings  # noqa: E402

FAILS = []
FIXTURE = json.loads((Path(__file__).resolve().parent / "fixtures" / "reference_job_v7.json").read_text())


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else '  -- ' + str(detail)}")
    if not ok:
        FAILS.append(name)


print("\nThe real job's statement")
lines = [{**ln, "id": f"l{i}"} for i, ln in enumerate(FIXTURE["lines"]) if not ln["name"].startswith("Photo retouching")]
s = st.build({"name": "Reference job", "client_name": "Example Group"}, lines, FIXTURE["invoices"],
             {"name": "Producer Example", "email": "producer@example.com"}, "Jul 28 - Aug 14, 2026", "2026-08-16")
check("original estimate 66,370.00", s["original"] == 6_637_000, s["original"])
check("reduction -20,548.58", s["change"] == -2_054_858, s["change"])
check("revised project total 45,821.42", s["revised"] == 4_582_142, s["revised"])
check("after the 33,185.00 deposit, 12,636.42 to invoice", s["balance"] == 1_263_642, s["balance"])
check("sections add up to the revised total", sum(x["project"] for x in s["sections"]) == s["revised"])
html = st.to_html(s)
text = re.sub(r"<style>.*?</style>", "", html, flags=re.S)       # the words a reader sees, not the CSS
check("it says it isn't an invoice", "This statement is not an invoice." in html)
check("and asks the client to confirm", "Please confirm this reconciliation" in html)
yak = [x for x in s["sections"] if any("Yakima" in r["name"] or r["block"] == "Yakima" for r in x["rows"])]
check("sections follow the estimate's headings (none here: one section)", len(s["sections"]) == 1)
by_market = [{**ln, "section": f"{ln['block'] or 'Project'} production"} for ln in lines]
m = st.build({"name": "Reference job"}, by_market, [], {}, "", "2026-08-16")
yak = next(x for x in m["sections"] if x["name"] == "Yakima production")
check("a market where nothing was shot collapses to one line, at its estimate",
      len(yak["rows"]) == 1 and yak["rows"][0]["note"] == "Not shot" and yak["rows"][0]["est"] == 877_500
      and yak["rows"][0]["project"] == 0, yak["rows"])
det = next(x for x in m["sections"] if x["name"] == "Detroit production")
check("a line under its market's heading doesn't repeat the market", all(r["block"] == "" for r in det["rows"]))
check("figures print as on the sent statement", "45,821.42" in html and "-20,548.58" in html and "12,636.42" in html)

print("\nNothing about cost or profit")
priv = []
for ln in lines:
    c = budget.calc(ln)
    if ln["bucket"] == "rate" and ln.get("act_cents") is not None and c["billed_cents"] != ln["act_cents"]:
        priv.append(st.amount(ln["act_cents"]))
check("a Fixed line's actual cost never appears", priv and not any(p in html for p in priv), [p for p in priv if p in html])
check("nor any of these words", not any(w in text.lower() for w in ("profit", "margin", "retained", "cost ")),
      [w for w in ("profit", "margin", "retained", "cost ") if w in text.lower()])

print("\nWhat's on it, and what isn't")
small = [
    {"id": "a", "bucket": "fee", "section": "Fees", "name": "Director fee", "est_cents": 500_000, "act_cents": None},
    {"id": "b", "bucket": "rate", "section": "Crew", "name": "Gaffer", "est_cents": 260_000, "bill_cents": 130_000,
     "act_cents": 117_500, "note": "1 day worked of the 2 estimated"},
    {"id": "c", "bucket": "rate", "section": "Crew", "name": "Swing", "est_cents": 120_000, "dropped": True},
    {"id": "d", "bucket": "pass", "section": "Travel", "name": "Flights", "est_cents": 180_000, "act_cents": 150_050,
     "block": "Detroit"},
    {"id": "e", "bucket": "pass", "section": "Travel", "name": "Lodging", "est_cents": 135_000, "act_cents": None},
    {"id": "f", "bucket": "rate", "section": "Crew", "name": "Fuel (absorbed)", "est_cents": None, "act_cents": 5_492},
    {"id": "g", "bucket": "fee", "section": "Admin", "name": "Insurance", "est_cents": 0, "floor_kind": "insurance"},
    {"id": "h", "bucket": "pass", "section": "Travel", "name": "Inflight wifi", "est_cents": None, "act_cents": 2_000},
]
s = st.build({"name": "Example Spot", "client_name": "Example Co", "producer_phone": "555-0100",
              "statement": {"client_contact": "Pat Example\nExample Agency", "estimate_ref": "EX-1007",
                            "intro": "Two of three days were shot."}},
             small, [{"label": "Deposit", "amount_cents": 1_000_000, "issued_on": "2026-10-01", "paid": True}],
             {"name": "Producer Example", "email": "p@example.com"}, "Oct 13 - 16, 2026", "2026-10-20")
rows = {r["name"]: r for sec in s["sections"] for r in sec["rows"]}
check("an absorbed cost nobody quoted is left off", "Fuel (absorbed)" not in rows)
check("a floor line zeroed on purpose is left off", "Insurance" not in rows)
check("an unquoted cost that bills is on, with no estimate", rows["Inflight wifi"]["est"] is None and rows["Inflight wifi"]["project"] == 2_000)
check("a line not shot shows 0.00, noted", rows["Swing"]["project"] == 0 and rows["Swing"]["note"] == "Not shot")
check("a Fixed line bills its revised amount, never its cost", rows["Gaffer"]["project"] == 130_000)
check("her own note is kept", rows["Gaffer"]["note"] == "1 day worked of the 2 estimated")
check("an At cost line trued up says so", rows["Flights"]["note"] == "Trued up to actual" and rows["Flights"]["project"] == 150_050)
check("one still open stays at estimate, and says that", rows["Lodging"]["project"] == 135_000
      and "estimate" in rows["Lodging"]["note"])
check("headings in estimate order", [x["name"] for x in s["sections"]] == ["Fees", "Crew", "Travel"])
check("a deposit beyond the revised total reads as a credit", s["balance"] == 500_000 + 130_000 + 150_050 + 135_000 + 2_000 - 1_000_000)
html = st.to_html(s)
check("the page's own marks are ASCII only", html.isascii(), [ch for ch in html if not ch.isascii()][:5])
check("the contact block, estimate number and opening paragraph print",
      "Pat Example" in html and "Estimate EX-1007" in html and "Two of three days were shot." in html)
check("The producer's phone and email head it", "555-0100" in html and "p@example.com" in html)
check("the market prints beside the line", "Flights - Detroit" in html)
check("the Fixed line's cost (1,175.00) isn't on it", "1,175.00" not in html)
check("a long date", "October 20, 2026" in html)

print("\nRoutes")
J = "00000000-0000-0000-0000-0000000000b1"
OWN = {"o1"}
JOB = {"id": J, "owner_id": "o1", "name": "Example Spot", "client_name": "Example Co", "crew_dates": {},
       "estimate_signed_on": "2026-10-02", "statement": {}}
client = FakeClient({"jobs": [dict(JOB)], "projects": [{"id": "d1", "job_id": J, "shoot_date": "2026-10-13"}],
                     "job_budget_lines": [], "job_expenses": [], "job_invoices": []})
for mod in (budget_router, jobs_router):
    mod.get_client = lambda: client
budget_router.get_user_identity = lambda uid: {"name": "Producer Example", "email": "p@example.com"}
budget_router.render_call_sheet_pdf = lambda html: html.encode()
try:
    budget_router.statement_pdf(J, owner_ids=OWN)
    check("no estimate yet: a 422", False, "rendered")
except HTTPException as e:
    check("no estimate yet: a 422", e.status_code == 422)
client.db["job_budget_lines"] = [{**ln, "job_id": J, "sort_order": i} for i, ln in enumerate(small)]
v = budget_router.save_statement(J, StatementSettings(client_contact="  Pat   Example \n\n Example Agency ", estimate_ref="EX-1"),
                                 owner_ids=OWN)
check("the statement's details are saved, line breaks kept", client.db["jobs"][0]["statement"]["client_contact"]
      == "Pat Example\nExample Agency" and v["statement"]["estimate_ref"] == "EX-1" and v["statement"]["ready"], v["statement"])
r = budget_router.statement_pdf(J, statement_on=date(2026, 10, 20), owner_ids=OWN)
body = r.body.decode()
check("the PDF downloads, named for the job", r.media_type == "application/pdf"
      and "Production%20Reconciliation%20-%20Example%20Spot.pdf" in r.headers["content-disposition"])
check("with the saved details and the job's dates", "Estimate EX-1" in body and "Oct 13" in body and "October 20, 2026" in body)

pre = FakeClient({"jobs": [{k: v for k, v in JOB.items() if k != "statement"}], "projects": [],
                  "job_budget_lines": client.db["job_budget_lines"], "job_expenses": [], "job_invoices": []})
for mod in (budget_router, jobs_router):
    mod.get_client = lambda: pre
check("before statement.sql the budget says so", budget_router.get_budget(J, owner_ids=OWN)["statement"]["ready"] is False)
check("the PDF still downloads", budget_router.statement_pdf(J, owner_ids=OWN).media_type == "application/pdf")
try:
    budget_router.save_statement(J, StatementSettings(intro="x"), owner_ids=OWN)
    check("saving its details is a 503 naming the file", False, "saved")
except HTTPException as e:
    check("saving its details is a 503 naming the file", e.status_code == 503 and "statement.sql" in e.detail)

print()
if FAILS:
    print(f"FAILED: {len(FAILS)}")
    sys.exit(1)
print("All passed.")
